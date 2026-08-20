from __future__ import annotations

import pytest

from dmf_pulse.rank_strategy.rank_utility import evaluate_rank_strategy
from dmf_pulse.rank_strategy.utility_models import (
    RankActivationStatus,
    RankObjectiveMode,
    RankTargetDefinition,
)
from tests.support.rank_utility_fixtures import candidate, context, policy

pytestmark = pytest.mark.unit


def test_pure_points_retains_and_selects_exact_points_optimum() -> None:
    candidates = (
        candidate("points", 60.0, {1: 0.2, 2: 0.8}),
        candidate("rank", 59.5, {1: 0.9, 2: 0.1}),
    )
    result = evaluate_rank_strategy(
        request_id="pure",
        objective=RankObjectiveMode.PURE_POINTS,
        candidates=candidates,
        context=context(explicit=False),
        policy=policy(),
    )
    assert result.points_optimal_plan_id == "points"
    assert result.rank_optimal_plan_id == "points"
    assert result.selected_plan_id == "points"
    assert result.effective_objective is RankObjectiveMode.PURE_POINTS
    assert result.activation_status is RankActivationStatus.ACTIVE
    assert result.expected_points_difference == 0.0


def test_target_rank_uses_points_floor_then_target_probability_lexicographically() -> None:
    candidates = (
        candidate("points", 60.0, {1: 0.1, 3: 0.9}, tracking_error=0.1),
        candidate("target", 59.2, {1: 0.7, 3: 0.3}, tracking_error=0.3),
        candidate("too-expensive", 58.8, {1: 0.99, 3: 0.01}),
    )
    result = evaluate_rank_strategy(
        request_id="target",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=candidates,
        context=context(),
        policy=policy(points_epsilon=1.0, material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.points_optimal_plan_id == "points"
    assert result.rank_optimal_plan_id == "target"
    assert result.selected_plan_id == "target"
    assert result.rank_optimal_metrics.probability_target == pytest.approx(0.7)
    assert result.points_optimal_metrics.probability_target == pytest.approx(0.1)
    assert result.expected_points_difference == pytest.approx(-0.8)
    assert result.target_probability_difference == pytest.approx(0.6)
    excluded = next(item for item in result.evaluations if item.plan_id == "too-expensive")
    assert excluded.eligible_for_counterfactual_rank_selection is False
    assert excluded.exclusion_reasons == ("POINTS_FLOOR_VIOLATION",)


def test_target_probability_is_rederived_from_rank_pmf_not_cached_distribution_field() -> None:
    plan = candidate("target", 60.0, {1: 0.25, 2: 0.25, 5: 0.5})
    assert plan.rank_distribution is not None
    altered = plan.model_copy(
        update={
            "rank_distribution": plan.rank_distribution.model_copy(
                update={"probability_target_rank": 0.99}
            )
        }
    )
    result = evaluate_rank_strategy(
        request_id="pmf",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=(altered,),
        context=context(),
        policy=policy(),
        target=RankTargetDefinition(target_rank=2),
    )
    assert result.rank_optimal_metrics.probability_target == pytest.approx(0.5)


def test_impossible_and_secure_targets_produce_zero_and_one_from_pmf() -> None:
    plan = candidate("one", 60.0, {3: 0.4, 5: 0.6})
    impossible = evaluate_rank_strategy(
        request_id="impossible",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=(plan,),
        context=context(),
        policy=policy(),
        target=RankTargetDefinition(target_rank=1),
    )
    secure = evaluate_rank_strategy(
        request_id="secure",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=(plan,),
        context=context(),
        policy=policy(),
        target=RankTargetDefinition(target_rank=5),
    )
    assert impossible.rank_optimal_metrics.probability_target == 0.0
    assert secure.rank_optimal_metrics.probability_target == 1.0


def test_rank_protection_does_not_automatically_template_match_when_ahead() -> None:
    candidates = (
        candidate(
            "template",
            60.0,
            {1: 0.3, 10: 0.7},
            template_beta=1.0,
            tracking_error=0.05,
        ),
        candidate(
            "non-template",
            59.8,
            {1: 0.8, 10: 0.2},
            template_beta=0.1,
            tracking_error=0.8,
        ),
    )
    result = evaluate_rank_strategy(
        request_id="protection",
        objective=RankObjectiveMode.RANK_PROTECTION,
        candidates=candidates,
        context=context(current_rank=1),
        policy=policy(points_epsilon=1.0, material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.rank_optimal_plan_id == "non-template"
    assert result.rank_optimal_metrics.template_beta == pytest.approx(0.1)


def test_being_behind_does_not_automatically_increase_variance() -> None:
    candidates = (
        candidate("stable", 60.0, {1: 0.6, 3: 0.4}, tracking_error=0.1),
        candidate("volatile", 60.0, {1: 0.6, 3: 0.4}, tracking_error=2.0),
    )
    ahead = evaluate_rank_strategy(
        request_id="ahead",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=candidates,
        context=context(current_rank=1),
        policy=policy(),
        target=RankTargetDefinition(target_rank=1),
    )
    behind = evaluate_rank_strategy(
        request_id="behind",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=candidates,
        context=context(current_rank=5_000_000),
        policy=policy(),
        target=RankTargetDefinition(target_rank=1),
    )
    assert ahead.rank_optimal_plan_id == behind.rank_optimal_plan_id == "stable"


def test_measured_leverage_uses_explicit_outcome_score_not_raw_or_effective_ownership() -> None:
    candidates = (
        candidate(
            "popular-value",
            60.0,
            leverage=2.0,
            raw_ownership=90.0,
            effective_ownership=180.0,
        ),
        candidate(
            "low-owned-low-value",
            60.0,
            leverage=0.1,
            raw_ownership=1.0,
            effective_ownership=1.0,
        ),
    )
    result = evaluate_rank_strategy(
        request_id="leverage",
        objective=RankObjectiveMode.MEASURED_LEVERAGE,
        candidates=candidates,
        context=context(),
        policy=policy(),
    )
    assert result.rank_optimal_plan_id == "popular-value"
    assert result.rank_optimal_metrics.mean_effective_ownership == pytest.approx(180.0)


def test_mini_league_win_and_rank_band_modes_use_exact_pmf_events() -> None:
    candidates = (
        candidate("a", 60.0, {1: 0.2, 2: 0.6, 4: 0.2}),
        candidate("b", 59.8, {1: 0.5, 2: 0.1, 4: 0.4}),
    )
    win = evaluate_rank_strategy(
        request_id="win",
        objective=RankObjectiveMode.MINI_LEAGUE_WIN,
        candidates=candidates,
        context=context(),
        policy=policy(material_threshold=1.0),
    )
    band = evaluate_rank_strategy(
        request_id="band",
        objective=RankObjectiveMode.RANK_BAND,
        candidates=candidates,
        context=context(),
        policy=policy(material_threshold=1.0),
        target=RankTargetDefinition(band_best_rank=2, band_worst_rank=4),
    )
    assert win.rank_optimal_plan_id == "b"
    assert win.rank_optimal_metrics.probability_target == pytest.approx(0.5)
    assert band.rank_optimal_plan_id == "a"
    assert band.rank_optimal_metrics.probability_target == pytest.approx(0.8)


def test_prize_band_requires_named_band_and_uses_same_rank_event() -> None:
    candidates = (
        candidate("a", 60.0, {1: 0.4, 5: 0.6}),
        candidate("b", 59.9, {1: 0.7, 5: 0.3}),
    )
    missing = evaluate_rank_strategy(
        request_id="missing-prize",
        objective=RankObjectiveMode.PRIZE_BAND,
        candidates=candidates,
        context=context(),
        policy=policy(),
        target=RankTargetDefinition(band_best_rank=1, band_worst_rank=1),
    )
    active = evaluate_rank_strategy(
        request_id="prize",
        objective=RankObjectiveMode.PRIZE_BAND,
        candidates=candidates,
        context=context(),
        policy=policy(material_threshold=1.0),
        target=RankTargetDefinition(
            band_best_rank=1,
            band_worst_rank=1,
            prize_band_id="winner",
        ),
    )
    assert missing.effective_objective is RankObjectiveMode.PURE_POINTS
    assert "PRIZE_BAND_UNDEFINED" in missing.fallback_reasons
    assert active.rank_optimal_plan_id == "b"


def test_deterministic_ties_use_expected_rank_tracking_error_points_then_id() -> None:
    candidates = (
        candidate("z", 60.0, {1: 0.5, 3: 0.5}, tracking_error=0.3),
        candidate("b", 60.0, {1: 0.5, 2: 0.5}, tracking_error=0.3),
        candidate("a", 60.0, {1: 0.5, 2: 0.5}, tracking_error=0.2),
    )
    result = evaluate_rank_strategy(
        request_id="ties",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=candidates,
        context=context(),
        policy=policy(),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.rank_optimal_plan_id == "a"
