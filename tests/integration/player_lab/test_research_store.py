"""PostgreSQL write denial, custody, corrections and direct-SQL adversarial checks."""

from __future__ import annotations

import json
from importlib.resources import files

import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.tables import (
    player_research_artifact,
    player_research_pair,
    player_research_source,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.rights import load_rights_profiles
from dmf_pulse.player_lab.actuals import FinalityContext
from dmf_pulse.player_lab.contracts import seal
from dmf_pulse.player_lab.demo import synthetic_evaluation
from dmf_pulse.player_lab.rights import ingest_offline_actuals, profile_identity
from dmf_pulse.player_lab.store import PostgresResearchLedger

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.parametrize(
    "kind,field,operation",
    [
        ("FORECAST", "recorded_at", "remove"),
        ("FORECAST", "recorded_at", "null"),
        ("FORECAST", "recorded_at", "naive"),
        ("FORECAST", "restricted_marker", "extra"),
        ("EXPERIMENT", "registered_at", "remove"),
        ("EXPERIMENT", "registered_at", "null"),
        ("EXPERIMENT", "promotion", "remove"),
        ("EXPERIMENT", "dataset_mode", "null"),
        ("EXPERIMENT", "restricted_marker", "extra"),
        ("SCORECARD", "count", "remove"),
        ("SCORECARD", "forecast_hashes", "remove"),
        ("SCORECARD", "label_hashes", "null"),
        ("SCORECARD", "promotion", "remove"),
        ("SCORECARD", "restricted_marker", "extra"),
        ("SCORECARD", "mean_ranked_probability_score", "null"),
    ],
)
def test_direct_sql_missing_null_extra_fields_fail_closed(postgres_engine, kind, field, operation):
    evaluation = synthetic_evaluation()
    PostgresResearchLedger(lambda: postgres_engine).persist(evaluation)
    with postgres_engine.connect() as connection:
        row = (
            connection.execute(
                select(player_research_artifact).where(player_research_artifact.c.kind == kind)
            )
            .mappings()
            .first()
        )
        values = {key: value for key, value in row.items() if key != "stored_at"}
    payload = dict(values["payload"])
    if operation == "remove":
        payload.pop(field)
    elif operation == "naive":
        payload[field] = "2026-09-01T12:01:00"
    else:
        payload[field] = "OWNED_SYNTHETIC_RESTRICTED_MARKER" if operation == "extra" else None
    payload["semantic_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "semantic_sha256"}
    )
    values.update(payload=payload, artifact_sha256=payload["semantic_sha256"])
    with pytest.raises(DBAPIError), postgres_engine.begin() as connection:
        connection.execute(insert(player_research_artifact).values(**values))
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_persist_reproduce_idempotent_and_append_corrections(postgres_engine):
    evaluation = synthetic_evaluation()
    ledger = PostgresResearchLedger(lambda: postgres_engine)
    sha = ledger.persist(evaluation)
    assert ledger.evaluate_stored(sha).semantic_sha256 == evaluation.scorecard.semantic_sha256
    assert ledger.persist(evaluation) == sha
    with postgres_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(player_research_artifact)) == 26
        assert connection.scalar(select(func.count()).select_from(player_research_pair)) == 8
    root = files("dmf_pulse.player_lab.resources")
    context = FinalityContext.model_validate_json(
        root.joinpath("context-gw2-revision1.json").read_bytes()
    )
    labels = ingest_offline_actuals(
        root.joinpath("actuals-gw2-revision1.json").read_bytes(), context
    ).labels
    for label in labels:
        ledger.append_correction(label)
    # An old report stays bound to its original label vintage.
    assert ledger.evaluate_stored(sha).semantic_sha256 == sha
    with pytest.raises(ValueError):
        ledger.append_correction(evaluation.labels[0])
    with pytest.raises(ValueError):
        ledger.evaluate_stored("invalid")


def test_private_derived_data_denied_before_connection_factory():
    evaluation = synthetic_evaluation()
    private = load_rights_profiles()["fpl_official_private_operator_initiated_read_v1"]
    original = evaluation.forecasts[0]
    source = original.forecast.sources[0].model_copy(
        update={
            "profile_id": private.rights_profile_id,
            "profile_sha256": profile_identity(private),
        }
    )
    forecast = seal(
        original.forecast.model_copy(update={"sources": (*original.forecast.sources, source)})
    )
    frozen = seal(original.model_copy(update={"forecast": forecast}))
    altered = evaluation._replace(forecasts=(frozen, *evaluation.forecasts[1:]))
    # Custody rejects first; standalone qualification also proves the rights denial.
    calls = []
    ledger = PostgresResearchLedger(lambda: calls.append(True))
    with pytest.raises(ValueError, match="custody"):
        ledger.persist(altered)
    assert calls == []
    from dmf_pulse.player_lab.evaluation import MemoryLedger

    with pytest.raises(IngestionError):
        MemoryLedger(clock=lambda: forecast.generated_at).freeze(forecast)
    assert calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        "private_source",
        "new_source",
        "nonfinal",
        "forecast_substitution",
        "incomplete_pairs",
        "mismatched_target",
        "immutability",
        "pair_parent",
    ],
)
def test_direct_sql_cannot_bypass_research_boundary(postgres_engine, mutation):
    evaluation = synthetic_evaluation()
    ledger = PostgresResearchLedger(lambda: postgres_engine)
    score_sha = ledger.persist(evaluation)
    pattern = {
        "private_source": "PLAYER_SOURCE_RIGHTS_BLOCKED",
        "new_source": "PLAYER_SOURCE_QUALIFICATION_REQUIRED",
    }.get(mutation)
    with pytest.raises(DBAPIError, match=pattern), postgres_engine.begin() as connection:
        if mutation == "private_source":
            row = (
                connection.execute(
                    select(player_research_artifact).where(
                        player_research_artifact.c.kind == "FORECAST"
                    )
                )
                .mappings()
                .first()
            )
            values = {key: value for key, value in row.items() if key != "stored_at"}
            values["source_refs"] = [
                {
                    **values["source_refs"][0],
                    "profile_id": "fpl_official_private_operator_initiated_read_v1",
                }
            ]
            connection.execute(insert(player_research_artifact).values(**values))
        elif mutation == "new_source":
            connection.execute(
                insert(player_research_source).values(
                    source_id="CALLER_ALLOW",
                    source_ref={},
                    qualification={},
                    dataset_mode="SYNTHETIC",
                )
            )
        elif mutation == "immutability":
            connection.execute(
                update(player_research_artifact)
                .values(model_id="changed")
                .where(player_research_artifact.c.artifact_sha256 == score_sha)
            )
        elif mutation == "pair_parent":
            connection.execute(
                insert(player_research_pair).values(
                    score_sha256=evaluation.experiment.semantic_sha256,
                    target_id=evaluation.labels[0].key.target_id(),
                    forecast_sha256=evaluation.forecasts[0].semantic_sha256,
                    label_sha256=evaluation.labels[0].semantic_sha256,
                )
            )
        elif mutation == "incomplete_pairs":
            score = seal(evaluation.scorecard.model_copy(update={"model_id": "changed"}))
            connection.execute(
                insert(player_research_artifact).values(
                    artifact_sha256=score.semantic_sha256,
                    kind="SCORECARD",
                    dataset_mode="SYNTHETIC",
                    model_id=score.model_id,
                    source_refs=[
                        evaluation.forecasts[0].forecast.sources[0].model_dump(mode="json")
                    ],
                    payload=score.model_dump(mode="json"),
                    experiment_sha256=evaluation.experiment.semantic_sha256,
                )
            )
        else:
            kind = "LABEL" if mutation == "nonfinal" else "FORECAST"
            row = (
                connection.execute(
                    select(player_research_artifact).where(player_research_artifact.c.kind == kind)
                )
                .mappings()
                .first()
            )
            values = {key: value for key, value in row.items() if key != "stored_at"}
            payload = json.loads(json.dumps(values["payload"]))
            if mutation == "nonfinal":
                payload["finalization_status"] = "INTERIM"
            elif mutation == "forecast_substitution":
                payload["forecast"]["mean"] = "999"
            else:
                values["target_id"] = "2" * 64
            if mutation == "forecast_substitution":
                payload["forecast"]["semantic_sha256"] = canonical_sha256(
                    {
                        key: value
                        for key, value in payload["forecast"].items()
                        if key != "semantic_sha256"
                    }
                )
            if mutation in {"nonfinal", "forecast_substitution"}:
                payload["semantic_sha256"] = canonical_sha256(
                    {key: value for key, value in payload.items() if key != "semantic_sha256"}
                )
                values["artifact_sha256"] = payload["semantic_sha256"]
            values["payload"] = payload
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            connection.execute(insert(player_research_artifact).values(**values))
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
