"""Strict actuals, immutable custody, leakage, scoring and retention acceptance."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from importlib.resources import files
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsCapability
from dmf_pulse.ingestion.rights import load_rights_profiles
from dmf_pulse.player_lab.actuals import ActualsError, FinalityContext, parse_actuals
from dmf_pulse.player_lab.contracts import (
    FrozenForecast,
    PlayerForecast,
    seal,
)
from dmf_pulse.player_lab.demo import synthetic_evaluation
from dmf_pulse.player_lab.evaluation import MemoryLedger, compare_holdout, evaluate_players
from dmf_pulse.player_lab.rights import (
    acquire_actuals,
    ingest_offline_actuals,
    profile_identity,
    require_qualified_outcome,
    require_sources,
)
from dmf_pulse.player_lab.snapshots import decimal_pmf

pytestmark = pytest.mark.unit


def test_registered_source_hashes_actual_resource_bytes(tmp_path, monkeypatch):
    from dmf_pulse.ingestion.models import RightsCapability
    from dmf_pulse.player_lab import rights
    from dmf_pulse.player_lab.demo import synthetic_forecasts

    _, forecasts, _ = synthetic_forecasts()
    source = forecasts[0].sources[0]
    resource_root = files("dmf_pulse.player_lab.resources")
    registry = json.loads(resource_root.joinpath("source-registry.json").read_bytes())
    (tmp_path / "source-registry.json").write_bytes(
        resource_root.joinpath("source-registry.json").read_bytes()
    )
    resource = registry["sources"][source.source_id]["resource"]
    (tmp_path / resource).write_bytes(b'{"unused_owned_synthetic_marker":true}')
    monkeypatch.setattr(rights, "files", lambda _: tmp_path)
    with pytest.raises(ValueError, match="SOURCE_RESOURCE_IDENTITY_MISMATCH"):
        rights.require_sources((source,), RightsCapability.DERIVED_STORAGE)


def fixture():
    root = files("dmf_pulse.player_lab.resources")
    body = root.joinpath("actuals-gw2.json").read_bytes()
    context = FinalityContext.model_validate_json(root.joinpath("context-gw2.json").read_bytes())
    return body, context


@pytest.fixture(scope="module")
def evaluation():
    return synthetic_evaluation()


def test_complete_adapter_to_frozen_scoring_and_holdout(evaluation):
    body, context = fixture()
    result = ingest_offline_actuals(body, context)
    assert result.expected_players == result.observed_players == result.matched_players == 4
    assert all(
        len(item.components) == 13 and sum(item.components.values()) == item.total_points
        for item in result.labels
    )
    score = evaluation.scorecard
    assert score.count == 8 and score.missing_count == 0
    assert score.point_metrics.mae == score.point_metrics.rmse == Decimal(2)
    assert score.point_metrics.signed_bias == 0
    assert score.zero_baseline.mae == 4
    assert score.probability_5plus.brier_score == Decimal("0.25")
    assert score.mean_ranked_probability_score == Decimal("0.25")
    assert score.central_80_coverage == 1
    assert set(score.by_position) == {"GK", "DEF", "MID", "FWD"}
    assert set(score.by_gameweek) == {"2", "3"}
    assert set(score.by_minutes_band) == {"UNDER_60", "60_PLUS"}
    assert evaluation.holdout.development_count == evaluation.holdout.holdout_count == 4
    assert evaluation.holdout.promotion == "FORBIDDEN"
    assert score.real_cohort_status == "NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT"
    assert all(item.recorded_at < item.forecast.deadline_at for item in evaluation.forecasts)


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing", "ACTUALS_COHORT_MISMATCH"),
        ("duplicate", "ACTUALS_DUPLICATE_PLAYER"),
        ("wrong_player", "ACTUALS_COHORT_MISMATCH"),
        ("wrong_fixture", "ACTUALS_FIXTURE_MISMATCH"),
        ("component", "ACTUALS_COMPONENT_SCHEMA_DRIFT"),
        ("total", "ACTUALS_TOTAL_RECONCILIATION_FAILED"),
        ("count", "ACTUALS_COUNT_RECONCILIATION_FAILED"),
        ("boolean", "ACTUALS_SCHEMA_OR_FINALITY_INVALID"),
        ("float", "ACTUALS_SCHEMA_OR_FINALITY_INVALID"),
        ("string", "ACTUALS_SCHEMA_OR_FINALITY_INVALID"),
        ("new_stat", "ACTUALS_SCHEMA_OR_FINALITY_INVALID"),
        ("sparse", "ACTUALS_SCHEMA_OR_FINALITY_INVALID"),
        ("new_top_level", "ACTUALS_SCHEMA_OR_FINALITY_INVALID"),
    ],
)
def test_adapter_adversarial_rows(mutation, code):
    body, context = fixture()
    payload = json.loads(body)
    row = payload["elements"][0]
    if mutation == "missing":
        payload["elements"].pop()
    elif mutation == "duplicate":
        payload["elements"].append(row)
    elif mutation == "wrong_player":
        row["id"] = 999999
    elif mutation == "wrong_fixture":
        row["explain"][0]["fixture"] += 1
    elif mutation == "component":
        row["explain"][0]["stats"][0]["identifier"] = "new_scored_field"
    elif mutation == "total":
        row["stats"]["total_points"] += 1
    elif mutation == "count":
        row["stats"]["minutes"] += 1
    elif mutation == "boolean":
        row["stats"]["total_points"] = True
    elif mutation == "float":
        row["explain"][0]["stats"][0]["points"] = 2.5
    elif mutation == "string":
        row["explain"][0]["stats"][0]["points"] = "2"
    elif mutation == "new_stat":
        row["stats"]["new_scored_stat"] = 0
    elif mutation == "sparse":
        row["explain"][0]["stats"].pop()
    else:
        payload["season"] = "unexpected-schema"
    with pytest.raises(ActualsError) as error:
        parse_actuals(json.dumps(payload).encode(), context)
    assert error.value.code == code


@pytest.mark.parametrize(
    "mutation",
    [
        "season",
        "gameweek",
        "route",
        "interim",
        "unchecked",
        "pre_lock",
        "wrong_lock",
        "naive",
        "duplicate_identity",
        "fixture_map",
        "revision",
    ],
)
def test_context_wrong_season_gw_finality_mapping_and_vintage(mutation):
    body, context = fixture()
    raw = context.model_dump(mode="python")
    if mutation == "season":
        raw["season"] = "2025/26"
    elif mutation == "gameweek":
        raw["gameweek"] = 3
    elif mutation == "route":
        raw["request_path"] = "/api/event/3/live/"
    elif mutation == "interim":
        raw["all_fixtures_finished"] = False
    elif mutation == "unchecked":
        raw["event_data_checked"] = False
    elif mutation == "pre_lock":
        raw["retrieved_at"] = context.points_lock_at - timedelta(seconds=1)
    elif mutation == "wrong_lock":
        raw["points_lock_at"] = context.points_lock_at - timedelta(hours=1)
    elif mutation == "naive":
        raw["usable_at"] = context.usable_at.replace(tzinfo=None)
    elif mutation == "duplicate_identity":
        raw["players"] = (*context.players, context.players[0])
    elif mutation == "fixture_map":
        raw["fixture_mapping"] = {200: uuid4()}
    else:
        raw["revision"] = 1
    with pytest.raises(ValueError):
        changed = FinalityContext.model_validate(raw)
        ingest_offline_actuals(body, changed)


@pytest.mark.parametrize(
    "body",
    [
        b'{"elements":[],"elements":[]}',
        b'{"elements":NaN}',
        b"not json",
        b"[" * 1100 + b"]" * 1100,
        b"x" * 4_000_001,
    ],
    ids=["duplicate-key", "nonfinite", "malformed", "deep", "oversize"],
)
def test_duplicate_nonfinite_malformed_deep_and_oversize_payloads(body):
    _, context = fixture()
    with pytest.raises(ActualsError):
        parse_actuals(body, context)


def test_qualification_no_fake_source_values_or_live_route(evaluation):
    body, context = fixture()
    called = []
    with pytest.raises(IngestionError):
        acquire_actuals(context.source, lambda: (called.append(True), body)[1])
    assert called == []
    for source in (
        context.source.model_copy(update={"source_id": "invented-source"}),
        context.source.model_copy(update={"profile_sha256": "0" * 64}),
        context.source.model_copy(update={"profile_id": "unknown-profile"}),
        context.source.model_copy(update={"payload_sha256": "0" * 64}),
        context.source.model_copy(
            update={"observed_at": context.source.observed_at - timedelta(minutes=1)}
        ),
    ):
        with pytest.raises(ValueError):
            require_sources((source,), RightsCapability.DERIVED_STORAGE)
    with pytest.raises(ValueError):
        require_sources((), RightsCapability.DERIVED_STORAGE)
    with pytest.raises(ValueError):
        ingest_offline_actuals(body + b" ", context)
    label = evaluation.labels[0]
    components = {**label.components, "appearance": label.components["appearance"] + 1}
    invented = seal(
        label.model_copy(update={"total_points": label.total_points + 1, "components": components})
    )
    with pytest.raises(ActualsError, match="LABEL_VALUES"):
        require_qualified_outcome(invented)
    with pytest.raises(ValueError):
        require_qualified_outcome(
            seal(label.model_copy(update={"source": evaluation.forecasts[0].forecast.sources[0]}))
        )


def test_private_fpl_derived_storage_denied_before_ledger_write(evaluation):
    private = load_rights_profiles()["fpl_official_private_operator_initiated_read_v1"]
    source = (
        evaluation.forecasts[0]
        .forecast.sources[0]
        .model_copy(
            update={
                "profile_id": private.rights_profile_id,
                "profile_sha256": profile_identity(private),
            }
        )
    )
    original = evaluation.forecasts[0].forecast
    contaminated = seal(original.model_copy(update={"sources": (*original.sources, source)}))
    ledger = MemoryLedger(clock=lambda: original.generated_at)
    with pytest.raises(IngestionError, match="operation is not permitted"):
        ledger.freeze(contaminated)
    assert ledger._forecasts == {}


def test_no_posthoc_freeze_substitution_outcome_leak_or_inexact_join(evaluation):
    frozen = evaluation.forecasts[0]
    forecast = frozen.forecast
    ledger = MemoryLedger(clock=lambda: forecast.generated_at)
    first = ledger.freeze(forecast)
    assert ledger.freeze(forecast) is first
    changed = seal(forecast.model_copy(update={"input_sha256": "1" * 64}))
    with pytest.raises(ValueError):
        ledger.freeze(changed)
    with pytest.raises(ValueError, match="prospectively"):
        MemoryLedger(clock=lambda: forecast.deadline_at).freeze(forecast)
    for update in (
        {"generated_at": forecast.deadline_at},
        {"information_cutoff": forecast.generated_at + timedelta(seconds=1)},
        {"pmf": {2: Decimal("0.9")}},
        {"mean": Decimal("NaN")},
        {"components": {"appearance": Decimal(4)}},
    ):
        with pytest.raises(ValueError):
            seal(forecast.model_copy(update=update))
    with pytest.raises(ValueError):
        PlayerForecast.model_validate_json(
            forecast.model_copy(update={"mean": Decimal(9)}).model_dump_json()
        )
    champion = tuple(
        item
        for item in evaluation.forecasts
        if item.forecast.model_id == evaluation.experiment.champion_id
    )
    for labels in (evaluation.labels[:-1], (*evaluation.labels[:-1], evaluation.labels[0])):
        with pytest.raises(ValueError):
            evaluate_players(champion, labels, custody=evaluation.custody)
    wrong = seal(
        evaluation.labels[0].model_copy(
            update={"key": evaluation.labels[0].key.model_copy(update={"season": "2025/26"})}
        )
    )
    with pytest.raises(ValueError):
        evaluate_players(champion, (wrong, *evaluation.labels[1:]), custody=evaluation.custody)
    with pytest.raises(ValueError):
        FrozenForecast.model_validate_json(
            first.model_copy(
                update={"recorded_at": forecast.generated_at - timedelta(seconds=1)}
            ).model_dump_json()
        )


def test_holdout_cannot_change_models_cohort_information_or_registration(evaluation):
    experiment = evaluation.experiment
    champion = tuple(
        item for item in evaluation.forecasts if item.forecast.model_id == experiment.champion_id
    )
    challenger = tuple(
        item for item in evaluation.forecasts if item.forecast.model_id == experiment.challenger_id
    )
    for changed in (
        seal(experiment.model_copy(update={"registered_at": champion[-1].recorded_at})),
        seal(experiment.model_copy(update={"target_ids": experiment.target_ids[:-1]})),
        seal(experiment.model_copy(update={"holdout_start_gameweek": 2})),
        seal(experiment.model_copy(update={"champion_id": "wrong-model"})),
    ):
        with pytest.raises(ValueError):
            compare_holdout(
                changed, champion, challenger, evaluation.labels, custody=evaluation.custody
            )
    changed_forecast = seal(
        challenger[0].forecast.model_copy(
            update={
                "information_cutoff": challenger[0].forecast.information_cutoff
                - timedelta(seconds=1)
            }
        )
    )
    changed_frozen = seal(challenger[0].model_copy(update={"forecast": changed_forecast}))
    with pytest.raises(ValueError):
        compare_holdout(
            experiment,
            champion,
            (changed_frozen, *challenger[1:]),
            evaluation.labels,
            custody=evaluation.custody,
        )
    with pytest.raises(ValueError):
        seal(experiment.model_copy(update={"target_ids": ()}))
    with pytest.raises(ValueError):
        seal(experiment.model_copy(update={"champion_id": experiment.challenger_id}))


@given(st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=20))
def test_stage9_decimal_mass_normalization_is_exact(values):
    total = sum(values)
    pmf = {index: value / total for index, value in enumerate(values)}
    normalized = decimal_pmf(pmf)
    assert sum(normalized.values(), Decimal(0)) == 1
    assert sum(reversed(tuple(normalized.values())), Decimal(0)) == 1
    assert sum((normalized[key] for key in sorted(normalized, key=str)), Decimal(0)) == 1
    assert all(value >= 0 for value in normalized.values())


@pytest.mark.parametrize(
    "values", [{}, {0: 0.2}, {0: -1.0, 1: 2.0}, {0: float("nan")}, {0: 1e-20, 1: 1.0}]
)
def test_decimal_conversion_rejects_invalid_mass(values):
    with pytest.raises(ValueError):
        decimal_pmf(values)


def test_successful_append_only_corrections_keep_original_score(evaluation):
    root = files("dmf_pulse.player_lab.resources")
    context = FinalityContext.model_validate_json(
        root.joinpath("context-gw2-revision1.json").read_bytes()
    )
    corrected = ingest_offline_actuals(
        root.joinpath("actuals-gw2-revision1.json").read_bytes(), context
    ).labels
    clock = [context.usable_at]
    ledger = MemoryLedger(clock=lambda: clock[0])
    for label in evaluation.labels:
        if label.key.gameweek == 2:
            ledger.record_outcome(label)
    for label in corrected:
        ledger.record_outcome(label)
    assert len(ledger._outcomes) == 8
    with pytest.raises(ValueError):
        ledger.record_outcome(corrected[0])
    assert corrected[0].finalized_at > corrected[0].original_points_lock_at
    assert corrected[0].finality_evidence_sha256 and corrected[0].supersedes_sha256
    champion = tuple(
        item
        for item in evaluation.forecasts
        if item.forecast.model_id == evaluation.experiment.champion_id
    )
    new_labels = (*corrected, *(item for item in evaluation.labels if item.key.gameweek == 3))
    new_score = evaluate_players(champion, new_labels, custody=evaluation.custody)
    assert new_score.semantic_sha256 != evaluation.scorecard.semantic_sha256
    assert evaluation.scorecard.point_metrics.mae == 2
    assert new_score.point_metrics.mae == Decimal("1.875")
    with pytest.raises(ValueError):
        MemoryLedger(clock=lambda: context.usable_at).record_outcome(corrected[0])
    with pytest.raises(ValueError):
        MemoryLedger(clock=lambda: context.usable_at - timedelta(days=1)).record_outcome(
            corrected[0]
        )


@pytest.mark.parametrize("field", ["all_fixtures_finished", "event_data_checked"])
@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_finality_flags_reject_numeric_or_string_boolean(field, value):
    _, context = fixture()
    raw = context.model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValueError):
        FinalityContext.model_validate_json(json.dumps(raw))


def test_candidate_blank_and_double_fixture_reconciliation_is_explicit():
    body, context = fixture()
    payload = json.loads(body)
    for row in payload["elements"]:
        row["stats"] = {key: 0 for key in row["stats"]}
        row["explain"] = []
    players = tuple(
        player.model_copy(
            update={
                "key": player.key.model_copy(update={"fixture_ids": ()}),
                "official_fixture_ids": (),
            }
        )
        for player in context.players
    )
    blank = context.model_copy(update={"players": players})
    result = parse_actuals(json.dumps(payload).encode(), blank)
    assert all(label.total_points == 0 and not label.key.fixture_ids for label in result.labels)
    with pytest.raises(ActualsError):
        require_qualified_outcome(result.labels[0])
    payload = json.loads(body)
    second_id = uuid4()
    for row in payload["elements"]:
        second = deepcopy(row["explain"][0])
        second["fixture"] = 201
        row["explain"].append(second)
        row["stats"] = {key: value * 2 for key, value in row["stats"].items()}
    players = tuple(
        player.model_copy(
            update={
                "key": player.key.model_copy(
                    update={
                        "fixture_ids": tuple(sorted((*player.key.fixture_ids, second_id), key=str))
                    }
                ),
                "official_fixture_ids": (200, 201),
            }
        )
        for player in context.players
    )
    doubled = context.model_copy(
        update={"players": players, "fixture_mapping": {**context.fixture_mapping, 201: second_id}}
    )
    result = parse_actuals(json.dumps(payload).encode(), doubled)
    assert all(
        len(label.key.fixture_ids) == 2 and sum(label.components.values()) == label.total_points
        for label in result.labels
    )


def test_outcome_informed_reseal_and_borrowed_source_cannot_enter_custody(evaluation):
    original = evaluation.forecasts[0]
    components = {name: Decimal(0) for name in original.forecast.components}
    components["appearance"] = Decimal(20)
    invented = seal(
        original.forecast.model_copy(
            update={"mean": Decimal(20), "pmf": {20: Decimal(1)}, "components": components}
        )
    )
    with pytest.raises(ActualsError, match="FORECAST_VALUES_NOT_QUALIFIED"):
        MemoryLedger(clock=lambda: original.recorded_at).freeze(invented)
    forged = seal(original.model_copy(update={"forecast": invented}))
    champion = tuple(
        item
        for item in evaluation.forecasts
        if item.forecast.model_id == evaluation.experiment.champion_id
    )
    replacements = tuple(forged if item == original else item for item in champion)
    with pytest.raises(ValueError, match="custody"):
        evaluate_players(replacements, evaluation.labels, custody=evaluation.custody)
