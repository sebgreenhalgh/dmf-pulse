from __future__ import annotations

import pytest

from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.rank_utility import evaluate_rank_strategy
from dmf_pulse.rank_strategy.utility_models import (
    RankActivationStatus,
    RankObjectiveMode,
    RankTargetDefinition,
)
from tests.support.rank_utility_fixtures import candidate, context, policy

pytestmark = pytest.mark.unit


def _two_plans(*, rank_confidence: str = "A"):
    return (
        candidate("points", 60.0, {1: 0.2, 3: 0.8}, confidence=rank_confidence),
        candidate("target", 59.2, {1: 0.8, 3: 0.2}, confidence=rank_confidence),
    )


def test_undefined_target_fails_closed_to_pure_points() -> None:
    result = evaluate_rank_strategy(
        request_id="undefined",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=_two_plans(),
        context=context(explicit=False),
        policy=policy(material_threshold=1.0),
    )
    assert result.selected_plan_id == "points"
    assert result.effective_objective is RankObjectiveMode.PURE_POINTS
    assert result.activation_status is RankActivationStatus.FALLBACK_PURE_POINTS
    assert "TARGET_RANK_UNDEFINED" in result.fallback_reasons


@pytest.mark.parametrize(
    ("gate", "reason"),
    [
        ("target_rules_active", "TARGET_RULES_INACTIVE"),
        ("rules_verified", "RANK_RULES_UNVERIFIED"),
        ("rights_valid", "RANK_SAMPLE_RIGHTS_INVALID"),
        ("cohort_valid", "RANK_COHORT_INVALID"),
        ("opponent_data_valid", "RANK_OPPONENT_DATA_INVALID"),
    ],
)
def test_invalid_activation_gate_fails_closed(gate: str, reason: str) -> None:
    result = evaluate_rank_strategy(
        request_id=f"gate-{gate}",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=_two_plans(),
        context=context(explicit=False, **{gate: False}),
        policy=policy(material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.selected_plan_id == "points"
    assert reason in result.fallback_reasons


def test_low_confidence_explicit_target_is_evaluated_but_cannot_override_points() -> None:
    result = evaluate_rank_strategy(
        request_id="low-confidence",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=_two_plans(rank_confidence="D"),
        context=context(confidence="D", explicit=True),
        policy=policy(material_threshold=0.5, minimum_confidence="C"),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.rank_optimal_plan_id == "target"
    assert result.selected_plan_id == "points"
    assert result.activation_status is RankActivationStatus.DIAGNOSTIC_ONLY
    assert "RANK_CONFIDENCE_TOO_LOW" in result.fallback_reasons
    assert result.human_review_required is True


def test_rank_mode_requires_explicit_user_selected_target() -> None:
    result = evaluate_rank_strategy(
        request_id="implicit-target",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=_two_plans(),
        context=context(explicit=False),
        policy=policy(material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.rank_optimal_plan_id == "target"
    assert result.selected_plan_id == "points"
    assert result.activation_status is RankActivationStatus.FALLBACK_PURE_POINTS
    assert "RANK_TARGET_NOT_USER_SELECTED" in result.fallback_reasons


def test_candidate_level_rank_confidence_cannot_be_hidden_by_context() -> None:
    candidates = (
        candidate("points", 60.0, {1: 0.2, 3: 0.8}, confidence="A"),
        candidate("target", 59.2, {1: 0.8, 3: 0.2}, confidence="D"),
    )
    result = evaluate_rank_strategy(
        request_id="candidate-confidence",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=candidates,
        context=context(confidence="A", explicit=True),
        policy=policy(material_threshold=1.0, minimum_confidence="C"),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.rank_optimal_plan_id == "target"
    assert result.selected_plan_id == "points"
    assert "RANK_PLAN_CONFIDENCE_TOO_LOW" in result.fallback_reasons


def test_early_season_material_sacrifice_is_diagnostic_only_even_for_explicit_target() -> None:
    result = evaluate_rank_strategy(
        request_id="early",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=_two_plans(),
        context=context(gameweek=3, explicit=True),
        policy=policy(material_threshold=0.5, early_through=8),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.rank_optimal_plan_id == "target"
    assert result.selected_plan_id == "points"
    assert "EARLY_SEASON_MATERIAL_POINTS_GATE" in result.fallback_reasons
    assert "HUMAN_REVIEW_UNAVAILABLE" in result.fallback_reasons


def test_early_season_nonmaterial_sacrifice_can_activate_when_all_gates_pass() -> None:
    candidates = (
        candidate("points", 60.0, {1: 0.2, 3: 0.8}),
        candidate("target", 59.8, {1: 0.8, 3: 0.2}),
    )
    result = evaluate_rank_strategy(
        request_id="early-small",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=candidates,
        context=context(gameweek=3, explicit=True),
        policy=policy(material_threshold=0.5, early_through=8),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.selected_plan_id == "target"
    assert result.activation_status is RankActivationStatus.ACTIVE


def test_human_review_availability_does_not_bypass_low_confidence_fail_closed_gate() -> None:
    result = evaluate_rank_strategy(
        request_id="review",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=_two_plans(rank_confidence="D"),
        context=context(confidence="D", explicit=True, human_review=True),
        policy=policy(material_threshold=0.5, minimum_confidence="C"),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.selected_plan_id == "points"
    assert "HUMAN_REVIEW_UNAVAILABLE" not in result.fallback_reasons
    assert "RANK_CONFIDENCE_TOO_LOW" in result.fallback_reasons


def test_minimum_target_gain_gate_blocks_cosmetic_rank_override() -> None:
    candidates = (
        candidate("points", 60.0, {1: 0.50, 3: 0.50}),
        candidate("target", 59.9, {1: 0.51, 3: 0.49}),
    )
    result = evaluate_rank_strategy(
        request_id="gain",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=candidates,
        context=context(),
        policy=policy(minimum_gain=0.05, material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.rank_optimal_plan_id == "target"
    assert result.selected_plan_id == "points"
    assert "TARGET_GAIN_BELOW_MINIMUM" in result.fallback_reasons


def test_missing_rank_distribution_cannot_activate_rank_mode() -> None:
    candidates = (
        candidate("points", 60.0, {1: 0.2, 2: 0.8}),
        candidate("missing", 59.9, None),
    )
    result = evaluate_rank_strategy(
        request_id="missing-distribution",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=candidates,
        context=context(),
        policy=policy(),
        target=RankTargetDefinition(target_rank=1),
    )
    missing = next(item for item in result.evaluations if item.plan_id == "missing")
    assert missing.eligible_for_counterfactual_rank_selection is False
    assert set(missing.exclusion_reasons) == {
        "RANK_DISTRIBUTION_MISSING",
        "TARGET_PROBABILITY_UNAVAILABLE",
    }


def test_raw_projection_and_scenario_set_mismatches_are_p0_failures() -> None:
    base = candidate("base", 60.0, {1: 0.5, 2: 0.5})
    cases = (
        (
            candidate("other", 59.0, {1: 0.6, 2: 0.4}, raw_hash="c" * 64),
            "RANK_PROJECTION_INVARIANCE_VIOLATION",
        ),
        (
            candidate("other", 59.0, {1: 0.6, 2: 0.4}, scenario_hash="d" * 64),
            "RANK_SCENARIO_SET_INVARIANCE_VIOLATION",
        ),
    )
    for invalid, expected_code in cases:
        with pytest.raises(RankStrategyError) as exc_info:
            evaluate_rank_strategy(
                request_id="p0",
                objective=RankObjectiveMode.PURE_POINTS,
                candidates=(base, invalid),
                context=context(),
                policy=policy(),
            )
        assert exc_info.value.code == expected_code


def test_post_validation_scenario_mutation_is_detected_from_semantic_content() -> None:
    plan = candidate("mutated", 60.0, {1: 0.5, 2: 0.5})
    plan.scenario_points["s1|d1"] = 999.0
    with pytest.raises(RankStrategyError) as exc_info:
        evaluate_rank_strategy(
            request_id="mutated-scores",
            objective=RankObjectiveMode.PURE_POINTS,
            candidates=(plan,),
            context=context(),
            policy=policy(),
        )
    assert exc_info.value.code == "RANK_SCENARIO_SCORE_HASH_INVALID"


def test_empty_and_duplicate_candidate_sets_fail_closed() -> None:
    with pytest.raises(RankStrategyError) as exc_info:
        evaluate_rank_strategy(
            request_id="empty",
            objective=RankObjectiveMode.PURE_POINTS,
            candidates=(),
            context=context(),
            policy=policy(),
        )
    assert exc_info.value.code == "RANK_PLAN_CANDIDATES_EMPTY"

    item = candidate("same", 60.0, {1: 1.0})
    with pytest.raises(RankStrategyError) as exc_info:
        evaluate_rank_strategy(
            request_id="duplicate",
            objective=RankObjectiveMode.PURE_POINTS,
            candidates=(item, item),
            context=context(),
            policy=policy(),
        )
    assert exc_info.value.code == "RANK_PLAN_CANDIDATE_DUPLICATE"
