from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from dmf_pulse.availability.persistence import register_prediction_bundle
from dmf_pulse.availability.pipeline import fit_projection_artifact, predict_minutes_baseline
from dmf_pulse.availability.registry import (
    dataset_version_semantic_sha256,
    model_version_semantic_sha256,
    prediction_input_signature_sha256,
)
from dmf_pulse.cli.app import app
from dmf_pulse.cli.availability_cmd import _dataset_payload
from dmf_pulse.data_model.errors import DataModelError
from dmf_pulse.data_model.tables import (
    conditional_minute_pmf,
    lineup_scenario,
    player_minutes_projection,
    prediction_run,
    role_marginal,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SEED = "MIN-007-COHERENCE-V1"


def _args(external_id: int, *, as_of: str = "2026-08-14T17:30:00Z") -> list[str]:
    return [
        "availability",
        "predict",
        "--fixture-external-provider",
        "synthetic_availability",
        "--fixture-external-id",
        str(external_id),
        "--season-code",
        "2026/27",
        "--team-side",
        "HOME",
        "--as-of",
        as_of,
        "--model-key",
        "min007-baseline-v1",
        "--seed",
        SEED,
        "--output",
        "json",
    ]


def _graph(repository_root: Path) -> tuple[dict[str, object], object]:
    history = json.loads(
        (repository_root / "fixtures/availability/MIN-007/canonical_history.json").read_text()
    )
    training = json.loads(
        (repository_root / "fixtures/availability/MIN-007/training_dataset.json").read_text()
    )
    policy = json.loads(
        (
            repository_root / "fixtures/availability/MIN-007G/minutes_baseline_policy.json"
        ).read_text()
    )
    context = json.loads(
        (repository_root / "fixtures/availability/MIN-007G/contexts/stable_xi.json").read_text()
    )
    artifact = fit_projection_artifact(training, policy=policy)
    result = predict_minutes_baseline(history, artifact, context=context, policy=policy)
    dataset = _dataset_payload(
        "min007-synthetic-train-v1",
        "SYNTH_EPL",
        "2026/27",
        str(training["training_cutoff"]),
        training,
        policy,
    )
    model = {
        "schema_version": "minutes-model-version-v1",
        "model_key": "min007-baseline-v1",
        "dataset_version_sha256": dataset_version_semantic_sha256(dataset),
        "role_artifact_sha256": "baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96",
        "minute_artifact_sha256": "8e0b410e37d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422",
        "policy_sha256": dataset["policy_sha256"],
        "model_family": artifact.model_family,
        "code_identity": "MIN-007G",
    }
    prediction = {
        "schema_version": "minutes-prediction-signature-v1",
        "fixture_id": result.fixture_id,
        "team_id": result.team_id,
        "as_of": result.as_of,
        "model_version_sha256": model_version_semantic_sha256(model),
        "dataset_version_sha256": dataset_version_semantic_sha256(dataset),
        "policy_sha256": dataset["policy_sha256"],
        "manager_context": {"manager_regime_id": context["manager_regime_id"]},
        "manager_regime_id": context["manager_regime_id"],
        "seed": SEED,
        "sample_count": result.projection.sample_count if result.projection else 0,
        "bench_size": result.projection.bench_size if result.projection else 0,
        "bench_goalkeeper_slots": result.projection.bench_goalkeeper_slots
        if result.projection
        else 0,
        "code_identity": "MIN-007G",
        "hard_eligibility": list(result.core_hard_eligibility),
    }
    return prediction, result


def test_frozen_701_complete_graph_reload_idempotency_and_blocked_709(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DMF_ENVIRONMENT", "TEST")
    runner = CliRunner()
    first = runner.invoke(app, _args(701))
    assert first.exit_code == 0, first.stderr
    value = json.loads(first.stdout)
    assert value["status"] == "PROJECTED"
    assert value["as_of"] == "2026-08-14T17:30:00Z"
    expected = json.loads(
        (repository_root / "fixtures/availability/MIN-007G/prediction_registry.json").read_text()
    )["stable_xi"]
    assert value["projection"]["result_sha256"] == expected["team_result_sha256"]

    prediction, result = _graph(repository_root)
    signature = prediction_input_signature_sha256(prediction)
    with postgres_session_factory.begin() as session:
        run = (
            session.execute(
                select(prediction_run).where(
                    prediction_run.c.prediction_input_signature_sha256 == signature
                )
            )
            .mappings()
            .one()
        )
        assert run["as_of"].isoformat().replace("+00:00", "Z") == "2026-08-14T17:30:00Z"
        counts = {
            "role": session.scalar(
                select(func.count())
                .select_from(role_marginal)
                .where(role_marginal.c.prediction_run_id == run["prediction_run_id"])
            ),
            "pmf": session.scalar(
                select(func.count())
                .select_from(conditional_minute_pmf)
                .where(conditional_minute_pmf.c.prediction_run_id == run["prediction_run_id"])
            ),
            "scenario": session.scalar(
                select(func.count())
                .select_from(lineup_scenario)
                .where(lineup_scenario.c.prediction_run_id == run["prediction_run_id"])
            ),
            "final": session.scalar(
                select(func.count())
                .select_from(player_minutes_projection)
                .where(player_minutes_projection.c.prediction_run_id == run["prediction_run_id"])
            ),
        }
        assert counts == {"role": 23, "pmf": 46, "scenario": 256, "final": 23}
        assert result.projection is not None
        assert result.projection.result_sha256 == expected["team_result_sha256"]
        assert sorted(item.player_id for item in result.projection.players) == sorted(
            row[0]
            for row in session.execute(
                select(player_minutes_projection.c.player_id).where(
                    player_minutes_projection.c.prediction_run_id == run["prediction_run_id"]
                )
            )
        )

        altered = deepcopy(list(result.core_scenarios))
        altered[0]["scenario_sha256"] = "0" * 64
        with pytest.raises(DataModelError) as collision:
            register_prediction_bundle(
                session,
                prediction,
                role_marginals=result.core_role_marginals,
                minute_pmfs=result.core_minute_pmfs,
                scenarios=altered,
                hard_eligibility=result.core_hard_eligibility,
                final_projection=result.projection,
            )
        assert collision.value.code == "PREDICTION_SIGNATURE_COLLISION"

    repeat = runner.invoke(app, _args(701))
    assert repeat.exit_code == 0
    with postgres_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(prediction_run)) == 1
        assert session.scalar(select(func.count()).select_from(player_minutes_projection)) == 23

    blocked = runner.invoke(app, _args(709))
    assert blocked.exit_code == 42
    blocked_value = json.loads(blocked.stdout)
    assert blocked_value["status"] == "BLOCKED"
    assert blocked_value["error_code"] == "INSUFFICIENT_ELIGIBLE_SQUAD"
    with postgres_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(player_minutes_projection)) == 23
        assert (
            session.scalar(
                select(func.count())
                .select_from(prediction_run)
                .where(prediction_run.c.fixture_id == blocked_value["fixture_id"])
            )
            == 0
        )
