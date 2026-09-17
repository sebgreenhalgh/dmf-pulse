"""R9C-A1.03: real canonical four-world rolling acceptance cases."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from dmf_pulse.private_v1.shadow_comparison import (
    FourWorldShadowComparison,
    build_shadow_comparison_artifact,
    run_four_world_shadow_comparison,
)
from tests.unit.private_v1.a1_03_support import build_a1_03_inputs


@pytest.fixture(scope="module")
def root_case(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[FourWorldShadowComparison, Any, Any]:
    execution, shadow = build_a1_03_inputs(
        Path.cwd(),
        tmp_path_factory.mktemp("a1-03-root"),
        candidate_saves_per_gameweek=1000,
    )
    return run_four_world_shadow_comparison(execution, shadow), execution, shadow


@pytest.fixture(scope="module")
def continuation_case(
    tmp_path_factory: pytest.TempPathFactory,
) -> FourWorldShadowComparison:
    execution, shadow = build_a1_03_inputs(
        Path.cwd(),
        tmp_path_factory.mktemp("a1-03-continuation"),
        candidate_saves_per_gameweek=40,
        force_candidate_low_current_minutes=True,
    )
    return run_four_world_shadow_comparison(execution, shadow)


def _assert_controls(comparison: FourWorldShadowComparison) -> None:
    assert comparison.stage7_identical_across_worlds is True
    assert comparison.stage8_identical_across_worlds is True
    assert comparison.root_randomness_aligned is True
    assert comparison.scenario_identity_aligned is True
    assert comparison.candidate_universe_same_across_worlds is True
    assert comparison.prices_identical_across_worlds is True
    assert comparison.manager_state_identical_across_worlds is True
    assert comparison.rules_identical_across_worlds is True
    assert comparison.work_budget_semantics_identical_across_worlds is True


def test_root_sensitive_case_comes_from_complete_real_canonical_solves(
    root_case: tuple[FourWorldShadowComparison, Any, Any],
) -> None:
    comparison, _execution, shadow = root_case
    _assert_controls(comparison)
    assert comparison.history_gameweeks == (1, 2, 3, 4)
    assert comparison.horizon_gameweeks == (5, 6, 7)
    assert len({item.decision_signature.root_action_signature for item in comparison.results}) > 1
    assert any(pair.classification == "WORLD_SENSITIVE_ROOT_ACTION" for pair in comparison.pairs)
    assert all(item.solver_status == "OPTIMAL" for item in comparison.results)
    assert all(item.recommended_plan_present for item in comparison.results)
    assert all(item.no_transfer_baseline_present for item in comparison.results)
    assert all(item.horizon_frontier_present for item in comparison.results)
    assert all(item.stage11_work.cumulative_state_expansions > 0 for item in comparison.results)
    assert all(item.stage11_work.cumulative_legal_actions > 0 for item in comparison.results)
    assert all(item.candidate_screen_node_count == 3 for item in comparison.results)
    for world in shadow.worlds:
        for stale, profile in zip(world.stale_profiles, world.profiles, strict=True):
            assert profile.goal_share == stale.goal_share
            assert profile.penalty_taker_share == stale.penalty_taker_share
            assert profile.own_goal_share == stale.own_goal_share


def test_continuation_sensitive_case_keeps_root_and_changes_real_future_action(
    continuation_case: FourWorldShadowComparison,
) -> None:
    comparison = continuation_case
    _assert_controls(comparison)
    assert len({item.decision_signature.root_action_signature for item in comparison.results}) == 1
    assert (
        len(
            {
                item.decision_signature.by_gameweek_action_signatures[1:]
                for item in comparison.results
            }
        )
        > 1
    )
    assert any(
        pair.classification == "ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE"
        for pair in comparison.pairs
    )
    assert any(pair.continuation_changed for pair in comparison.pairs)


def test_contract_rejects_unsealed_tampering_and_false_control(
    root_case: tuple[FourWorldShadowComparison, Any, Any],
) -> None:
    comparison, _execution, _shadow = root_case
    with pytest.raises(ValueError, match="semantic hash"):
        replace(comparison.results[0], prices_sha256="f" * 64)
    with pytest.raises(ValueError, match="controls"):
        replace(
            comparison,
            stage7_identical_across_worlds=False,
            semantic_sha256=comparison.semantic_sha256,
        )


def test_world_execution_order_cannot_contaminate_results(
    root_case: tuple[FourWorldShadowComparison, Any, Any],
) -> None:
    forward, execution, shadow = root_case
    reverse = run_four_world_shadow_comparison(
        execution,
        shadow,
        _world_order=("HIGH_SHRINKAGE", "LOW_SHRINKAGE", "CENTRAL_TEMPORARY", "STALE"),
    )
    assert reverse.semantic_sha256 == forward.semantic_sha256
    assert tuple(item.semantic_sha256 for item in reverse.results) == tuple(
        item.semantic_sha256 for item in forward.results
    )


def test_comparison_is_synthetic_inert_complete_and_sealed(
    root_case: tuple[FourWorldShadowComparison, Any, Any],
) -> None:
    comparison, _execution, _shadow = root_case
    assert comparison.experiment_mode == "SYNTHETIC_OFFLINE_NOT_ACTIVE"
    assert comparison.model_input_status == "SHADOW_NOT_MODEL_INPUT"
    assert comparison.production_activation is False
    assert comparison.new_network_requests == 0
    assert comparison.persistence_performed is False
    assert tuple(item.world for item in comparison.results) == comparison.world_set
    assert len(comparison.pairs) == 6
    assert comparison.semantic_sha256


def test_artifact_envelope_is_deterministic_and_truthfully_bound(
    root_case: tuple[FourWorldShadowComparison, Any, Any],
) -> None:
    comparison, _execution, _shadow = root_case
    first = build_shadow_comparison_artifact(
        comparison,
        generating_implementation_sha="a" * 40,
        case="ROOT_SENSITIVE",
    )
    second = build_shadow_comparison_artifact(
        comparison,
        generating_implementation_sha="a" * 40,
        case="ROOT_SENSITIVE",
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["comparison_semantic_sha256"] == comparison.semantic_sha256
    assert first["evidence_class"] == "SYNTHETIC"
    assert first["execution_mode"] == "OFFLINE"
    assert first["activation_status"] == "NOT_PRODUCTION_ACTIVE"
    assert first["timing_status"] == "NON_SEMANTIC_DIAGNOSTIC_MEASUREMENTS"
