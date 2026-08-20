from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.rank_strategy.opponent_actions import model_opponent_actions
from tests.support.opponent_action_fixtures import (
    behaviour_profile,
    candidate,
    observed_state,
)

pytestmark = pytest.mark.property


@given(
    first=st.floats(min_value=-50.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    second=st.floats(min_value=-50.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    shift=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_softmax_distribution_is_invariant_to_common_expected_points_shift(
    first: float,
    second: float,
    shift: float,
) -> None:
    candidates = (
        candidate("no-transfer", expected_points=first),
        candidate("transfer", expected_points=second, transfer_count=1),
    )
    shifted = (
        candidate("no-transfer", expected_points=first + shift),
        candidate("transfer", expected_points=second + shift, transfer_count=1),
    )
    baseline = model_opponent_actions(observed_state(), candidates, behaviour_profile())
    shifted_result = model_opponent_actions(observed_state(), shifted, behaviour_profile())
    assert [item.probability for item in shifted_result.actions] == pytest.approx(
        [item.probability for item in baseline.actions]
    )


@given(
    scores=st.lists(
        st.floats(min_value=-50.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=8,
    )
)
def test_probability_vector_is_always_positive_and_normalised(scores: list[float]) -> None:
    candidates = tuple(
        candidate(
            f"action-{index}",
            expected_points=score,
            transfer_count=0 if index == 0 else 1,
            captain="p12" if index % 2 == 0 else "p13",
            vice="p13" if index % 2 == 0 else "p12",
        )
        for index, score in enumerate(scores)
    )
    # Make semantically distinct transfer plans for all transfer branches by varying hits.
    unique: list = [candidates[0]]
    for index, item in enumerate(candidates[1:], start=1):
        unique.append(
            item.model_copy(
                update={
                    "manager_plan": item.manager_plan.model_copy(
                        update={
                            "plan_id": f"plan-rival-action-{index}",
                            "transfer_hit_points": 4 * index,
                        }
                    )
                }
            )
        )
    result = model_opponent_actions(observed_state(), tuple(unique), behaviour_profile())
    probabilities = [item.probability for item in result.actions]
    assert sum(probabilities) == pytest.approx(1.0)
    assert min(probabilities) >= behaviour_profile().probability_floor
    assert max(probabilities) < 1.0


@given(
    base=st.floats(min_value=-20.0, max_value=80.0, allow_nan=False, allow_infinity=False),
    improvement=st.floats(min_value=0.001, max_value=30.0, allow_nan=False, allow_infinity=False),
)
def test_increasing_only_one_action_points_increases_its_probability(
    base: float,
    improvement: float,
) -> None:
    baseline_candidates = (
        candidate("no-transfer", expected_points=base),
        candidate("transfer", expected_points=base, transfer_count=1),
    )
    improved_candidates = (
        candidate("no-transfer", expected_points=base),
        candidate("transfer", expected_points=base + improvement, transfer_count=1),
    )
    baseline = model_opponent_actions(
        observed_state(), baseline_candidates, behaviour_profile()
    )
    improved = model_opponent_actions(
        observed_state(), improved_candidates, behaviour_profile()
    )
    base_probability = next(
        item.probability for item in baseline.actions if item.action_id == "transfer"
    )
    improved_probability = next(
        item.probability for item in improved.actions if item.action_id == "transfer"
    )
    assert improved_probability > base_probability
