"""Two real canonical prior worlds; no provider or optimiser mocks."""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from decimal import Decimal

import pytest

from dmf_pulse.ingestion.openfootball.team_strength_data import authenticate, seal
from dmf_pulse.private_v1 import automatic_inputs
from dmf_pulse.private_v1.rolling import PrivateV1RollingRecommendationService
from dmf_pulse.private_v1.rolling_models import seal_rolling_decision
from dmf_pulse.private_v1.team_strength_comparison import (
    TeamStrengthComparisonRun,
    _compare_runs,
    _fixture_comparisons,
    _movements,
    run_team_strength_shadow_comparison,
    safe_team_strength_summary,
)
from dmf_pulse.private_v1.team_strength_shadow_inputs import (
    TeamStrengthShadowPreparation,
    prepare_team_strength_shadow,
)
from tests.unit.private_v1.team_strength_shadow_support import (
    synthetic_model_prepared,
    synthetic_prepared,
    synthetic_strength,
)
from tests.unit.private_v1.test_team_strength_shadow_inputs import reseal


@pytest.fixture(scope="module")
def comparison_inputs(repository_root, tmp_path_factory):
    counts = {"fit": 0, "predict": 0}
    fit = automatic_inputs.fit_projection_artifact
    predict = automatic_inputs.predict_minutes_baseline

    def counted_fit(*args, **kwargs):
        counts["fit"] += 1
        return fit(*args, **kwargs)

    def counted_predict(*args, **kwargs):
        counts["predict"] += 1
        return predict(*args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(automatic_inputs, "fit_projection_artifact", counted_fit)
        patch.setattr(automatic_inputs, "predict_minutes_baseline", counted_predict)
        prepared = synthetic_model_prepared(
            repository_root, tmp_path_factory.mktemp("001p-compare")
        )
    assert counts == {"fit": 1, "predict": 18}
    dataset, artifact = synthetic_strength()
    preparation = prepare_team_strength_shadow(
        prepared.rolling_execution,
        artifact=artifact,
        expected_artifact_sha256=artifact.semantic_sha256,
        fixture_registry=dataset.fixture_registry,
    )
    return prepared, preparation


@pytest.fixture(scope="module")
def real_comparison(comparison_inputs):
    from dmf_pulse.football_events.service import ScoreDistributionService
    from dmf_pulse.fpl_points import allocation
    from dmf_pulse.private_v1 import service as private_service

    original_run = PrivateV1RollingRecommendationService.run
    original_project = ScoreDistributionService.project
    original_rng = allocation.rng_for
    runs, requests, draws = [], [[], []], [[], []]
    active = 0

    def forbidden(*args, **kwargs):
        raise AssertionError("comparison must not acquire providers or recompute Stage 7")

    def observed_run(self, execution, **kwargs):
        nonlocal active
        active = len(runs)
        result = original_run(self, execution, **kwargs)
        runs.append(result)
        return result

    def observed_project(self, request, **kwargs):
        requests[active].append(request)
        return original_project(self, request, **kwargs)

    def observed_rng(seed, *namespace):
        if namespace[0] == "scoreline":
            draws[active].append(
                (seed, namespace, original_rng(seed, *namespace).randbelow(10**12))
            )
        return original_rng(seed, *namespace)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket, "getaddrinfo", forbidden)
        patch.setattr(socket.socket, "connect", forbidden)
        patch.setattr(automatic_inputs, "fit_projection_artifact", forbidden)
        patch.setattr(automatic_inputs, "predict_minutes_baseline", forbidden)
        patch.setattr(private_service, "build_manual_minutes_override", forbidden)
        patch.setattr(PrivateV1RollingRecommendationService, "run", observed_run)
        patch.setattr(ScoreDistributionService, "project", observed_project)
        patch.setattr(allocation, "rng_for", observed_rng)
        result = run_team_strength_shadow_comparison(*comparison_inputs)
    assert draws[0] == draws[1] and len(draws[0]) == 9
    for baseline, shadow in zip(*requests, strict=True):
        assert baseline.model_dump(exclude={"prior"}) == shadow.model_dump(exclude={"prior"})
        assert baseline.prior != shadow.prior
    return result, tuple(runs)


def test_two_real_worlds_keep_controls_and_publish_safe_summary(real_comparison):
    real_comparison, _runs = real_comparison
    assert isinstance(real_comparison, TeamStrengthComparisonRun)
    comparison = real_comparison.comparison
    assert authenticate(comparison) == comparison
    left, right = comparison.worlds
    assert left.controls == right.controls
    assert left.canonical_legal_actions > 0 and right.canonical_legal_actions > 0
    assert left.stage8_sha256s != right.stage8_sha256s
    assert len(comparison.fixtures) == 9
    assert len(comparison.player_movements) == comparison.movement.player_gameweek_count
    summary = safe_team_strength_summary(real_comparison)
    text = json.dumps(summary)
    assert "player_movements" not in text
    assert "entry_id" not in text and "live_by_gameweek" not in text
    assert summary["status"] == "SHADOW_NOT_MODEL_INPUT"
    assert summary["production_activation"] is False
    assert summary["provider_requests_during_solves"] == 0
    assert real_comparison.timings.baseline_solve_ms > 0


def test_unavailable_world_never_runs_solver(comparison_inputs, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unavailable comparison cannot solve")

    monkeypatch.setattr(PrivateV1RollingRecommendationService, "run", forbidden)
    prepared, _preparation = comparison_inputs
    blocked = seal(
        TeamStrengthShadowPreparation,
        status="TEAM_STRENGTH_WORLD_UNAVAILABLE",
        reason="CURRENT_ARTIFACT_UNAVAILABLE",
    )
    assert run_team_strength_shadow_comparison(prepared, blocked) == blocked


@pytest.mark.parametrize(
    "updates",
    [
        {"_world_order": ("LEAGUE_BASELINE", "LEAGUE_BASELINE")},
        {"preparation_ms": Decimal(-1)},
        {"preparation_ms": Decimal("NaN")},
    ],
)
def test_invalid_execution_options_fail_before_solve(comparison_inputs, updates):
    with pytest.raises(ValueError):
        run_team_strength_shadow_comparison(*comparison_inputs, **updates)


def test_frozen_prepared_context_mismatch_blocks(comparison_inputs):
    from datetime import timedelta

    prepared, preparation = comparison_inputs
    with pytest.raises(ValueError, match="prepared context"):
        run_team_strength_shadow_comparison(
            replace(
                prepared, information_cutoff=prepared.information_cutoff + timedelta(seconds=1)
            ),
            preparation,
        )


@pytest.mark.parametrize(
    "field", ["stage7_context_sha256_by_gameweek", "player_prior_binding_sha256_by_gameweek"]
)
def test_actual_run_control_divergence_fails_closed(comparison_inputs, real_comparison, field):
    _comparison, (baseline, shadow) = real_comparison
    lineage = shadow.decision.lineage
    values = {gw: dict(rows) for gw, rows in getattr(lineage, field).items()}
    gw = min(values)
    values[gw][min(values[gw])] = "f" * 64
    altered_lineage = lineage.model_copy(update={field: values})
    altered = seal_rolling_decision(
        type(shadow.decision).model_construct(
            **(dict(shadow.decision) | {"lineage": altered_lineage})
        )
    )
    prepared, preparation = comparison_inputs
    with pytest.raises(ValueError, match="hard controls"):
        _compare_runs(
            prepared, preparation.shadow_input, baseline, replace(shadow, decision=altered)
        )


def test_prior_world_swap_and_nested_comparison_tamper_fail(comparison_inputs, real_comparison):
    comparison, (baseline, shadow) = real_comparison
    prepared, preparation = comparison_inputs
    with pytest.raises(ValueError, match="exact prior worlds"):
        _compare_runs(prepared, preparation.shadow_input, shadow, baseline)
    value = type(comparison.comparison).model_validate_json(comparison.comparison.model_dump_json())
    object.__setattr__(value.player_movements[0], "shadow_xp", Decimal(123))
    with pytest.raises(ValueError):
        safe_team_strength_summary(replace(comparison, comparison=value))


@pytest.mark.parametrize(
    "change",
    [
        "worlds",
        "controls",
        "control_inventory",
        "execution",
        "fixtures",
        "stage8",
        "players",
        "aggregate",
        "coverage",
        "signature",
    ],
)
def test_resealed_comparison_cannot_lie_about_nested_evidence(real_comparison, change):
    run, _results = real_comparison
    value = run.comparison
    with pytest.raises(ValueError):
        if change == "worlds":
            reseal(value, worlds=tuple(reversed(value.worlds)))
        elif change == "controls":
            controls = value.worlds[1].controls
            world = reseal(value.worlds[1], controls=((controls[0][0], "f" * 64), *controls[1:]))
            reseal(value, worlds=(value.worlds[0], world))
        elif change == "control_inventory":
            reseal(value.worlds[1], controls=value.worlds[1].controls[:-1])
        elif change == "execution":
            reseal(value, baseline_execution_sha256="f" * 64)
        elif change == "fixtures":
            reseal(value, fixtures=tuple(reversed(value.fixtures)))
        elif change == "stage8":
            row = value.fixtures[0].model_copy(update={"shadow_stage8_sha256": "f" * 64})
            reseal(value, fixtures=(row, *value.fixtures[1:]))
        elif change == "players":
            reseal(value, player_movements=tuple(reversed(value.player_movements)))
        elif change == "aggregate":
            summary = value.movement.model_copy(
                update={"player_count": value.movement.player_count + 1}
            )
            reseal(value, movement=summary)
        elif change == "coverage":
            reseal(value, market_coverage=value.market_coverage[:-1])
        else:
            signature = value.worlds[0].signature
            reseal(signature, action_sha256s=("f" * 64, *signature.action_sha256s[1:]))


def test_unprepared_manual_stage7_is_not_recomputed(repository_root, tmp_path):
    prepared = synthetic_prepared(repository_root, tmp_path)
    dataset, artifact = synthetic_strength()
    preparation = prepare_team_strength_shadow(
        prepared.rolling_execution,
        artifact=artifact,
        expected_artifact_sha256=artifact.semantic_sha256,
        fixture_registry=dataset.fixture_registry,
    )
    with pytest.raises(ValueError, match="already prepared"):
        run_team_strength_shadow_comparison(prepared, preparation)


def test_projection_and_stage8_coverage_divergence_fail(comparison_inputs, real_comparison):
    run, (baseline, shadow) = real_comparison
    prepared, preparation = comparison_inputs
    projection = shadow.gameweek_projections[0]
    missing = type(projection).model_construct(**(dict(projection) | {"player_summaries": {}}))
    with pytest.raises(ValueError, match="player projection coverage"):
        _movements(
            prepared.rolling_execution,
            baseline,
            replace(shadow, gameweek_projections=(missing, *shadow.gameweek_projections[1:])),
        )
    world = reseal(
        run.comparison.worlds[1], stage8_sha256s=run.comparison.worlds[1].stage8_sha256s[:-1]
    )
    with pytest.raises(ValueError, match="exact horizon"):
        _fixture_comparisons(
            prepared.rolling_execution, preparation.shadow_input, (run.comparison.worlds[0], world)
        )


def test_partial_market_classification(comparison_inputs, real_comparison, monkeypatch):
    from dmf_pulse.football_events.market_constraints import MarketFamily
    from dmf_pulse.private_v1 import team_strength_comparison as module
    from dmf_pulse.private_v1.team_strength_shadow_inputs import horizon_fixtures

    run, _results = real_comparison
    prepared, preparation = comparison_inputs
    rows = horizon_fixtures(prepared.rolling_execution)
    row = replace(
        rows[0],
        constraints=tuple(
            item for item in rows[0].constraints if item.family == MarketFamily.ONE_X_TWO
        ),
    )
    monkeypatch.setattr(module, "horizon_fixtures", lambda execution: (row, *rows[1:]))
    fixtures = _fixture_comparisons(
        prepared.rolling_execution, preparation.shadow_input, run.comparison.worlds
    )
    assert fixtures[0].market_coverage == "PARTIAL_MARKET"


def test_frozen_input_mutation_during_solve_fails(comparison_inputs, real_comparison, monkeypatch):
    _run, (baseline, _shadow) = real_comparison
    prepared, preparation = comparison_inputs

    def corrupt(self, execution, **kwargs):
        object.__setattr__(execution.current_execution, "root_seed", 999)
        return baseline

    monkeypatch.setattr(PrivateV1RollingRecommendationService, "run", corrupt)
    with pytest.raises(ValueError, match="changed during"):
        run_team_strength_shadow_comparison(prepared, preparation)
