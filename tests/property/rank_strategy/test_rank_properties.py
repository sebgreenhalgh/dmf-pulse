from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.rank_strategy.manager_multipliers import calculate_manager_multipliers
from dmf_pulse.rank_strategy.mini_league import simulate_mini_league_rank
from tests.support.rank_strategy_fixtures import (
    exact_named_league,
    manager_plan,
    multiplier_policy,
    rank_players,
    rank_rules,
    rank_tie_policy,
    scenario_set,
)

pytestmark = pytest.mark.property


@given(
    sebastian_points=st.integers(min_value=0, max_value=5000),
    rival_points=st.integers(min_value=0, max_value=5000),
    sebastian_transfers=st.integers(min_value=0, max_value=100),
    rival_transfers=st.integers(min_value=0, max_value=100),
)
def test_two_manager_rank_is_exact_under_points_and_transfer_ties(
    sebastian_points: int,
    rival_points: int,
    sebastian_transfers: int,
    rival_transfers: int,
) -> None:
    plans = (
        manager_plan(
            "sebastian",
            cumulative_points=sebastian_points,
            counted_transfers=sebastian_transfers,
        ),
        manager_plan(
            "rival",
            cumulative_points=rival_points,
            counted_transfers=rival_transfers,
        ),
    )
    scenarios = scenario_set()
    multiplier_sets = tuple(
        calculate_manager_multipliers(
            plan,
            scenarios,
            rank_players(),
            rank_rules(),
            multiplier_policy(),
        )
        for plan in plans
    )
    result = simulate_mini_league_rank(
        exact_named_league(*plans),
        multiplier_sets,
        rank_tie_policy(),
        target_manager_id="sebastian",
    )
    expected_rank = 1 + int(
        rival_points > sebastian_points
        or (rival_points == sebastian_points and rival_transfers < sebastian_transfers)
    )
    assert result.rank_pmf[0].rank == expected_rank
    assert sum(item.probability for item in result.rank_pmf) == pytest.approx(1.0)
