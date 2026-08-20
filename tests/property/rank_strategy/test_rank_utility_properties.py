from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.rank_strategy.rank_utility import evaluate_rank_strategy
from dmf_pulse.rank_strategy.utility_models import RankObjectiveMode, RankTargetDefinition
from tests.support.rank_utility_fixtures import candidate, context, policy

pytestmark = pytest.mark.property


@given(
    probability=st.floats(
        min_value=0.0,
        max_value=1.0,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_target_probability_is_exact_rank_pmf_event(probability: float) -> None:
    plan = candidate("plan", 60.0, {1: probability, 2: 1.0 - probability})
    result = evaluate_rank_strategy(
        request_id="pmf-property",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=(plan,),
        context=context(),
        policy=policy(),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.rank_optimal_metrics.probability_target == pytest.approx(probability)


@given(
    epsilon=st.floats(
        min_value=0.0,
        max_value=5.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    sacrifice=st.floats(
        min_value=0.0,
        max_value=8.0,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_points_floor_eligibility_is_exact_epsilon_constraint(
    epsilon: float,
    sacrifice: float,
) -> None:
    candidates = (
        candidate("points", 60.0, {1: 0.1, 2: 0.9}),
        candidate("target", 60.0 - sacrifice, {1: 0.9, 2: 0.1}),
    )
    result = evaluate_rank_strategy(
        request_id="floor-property",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=candidates,
        context=context(),
        policy=policy(points_epsilon=epsilon, material_threshold=100.0),
        target=RankTargetDefinition(target_rank=1),
    )
    target = next(item for item in result.evaluations if item.plan_id == "target")
    assert target.metrics.points_floor_satisfied is (sacrifice <= epsilon + 1e-12)


@given(current_rank=st.integers(min_value=1, max_value=10_000_000))
def test_current_rank_position_cannot_change_identical_utility_surface(
    current_rank: int,
) -> None:
    candidates = (
        candidate("stable", 60.0, {1: 0.5, 2: 0.5}, tracking_error=0.1),
        candidate("volatile", 60.0, {1: 0.5, 2: 0.5}, tracking_error=2.0),
    )
    result = evaluate_rank_strategy(
        request_id="position-property",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=candidates,
        context=context(current_rank=current_rank),
        policy=policy(),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.rank_optimal_plan_id == "stable"
