from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.rank_strategy.synthetic_field import simulate_synthetic_overall_rank
from tests.support.rank_strategy_fixtures import manager_plan, rank_tie_policy, scenario_set
from tests.support.synthetic_field_fixtures import (
    multiplier_sets_for_population,
    rank_band,
    representative,
    tiny_known_truth_population,
)

pytestmark = pytest.mark.property


@given(
    population_count=st.integers(min_value=1, max_value=50),
    target_points=st.integers(min_value=0, max_value=5000),
    rival_points=st.integers(min_value=0, max_value=5000),
    target_transfers=st.integers(min_value=0, max_value=100),
    rival_transfers=st.integers(min_value=0, max_value=100),
)
def test_weighted_representative_rank_is_exact_under_points_and_transfer_ties(
    population_count: int,
    target_points: int,
    rival_points: int,
    target_transfers: int,
    rival_transfers: int,
) -> None:
    target = manager_plan(
        "sebastian",
        captain="p12",
        cumulative_points=target_points,
        counted_transfers=target_transfers,
    )
    rival = manager_plan(
        "rival",
        captain="p12",
        cumulative_points=rival_points,
        counted_transfers=rival_transfers,
    )
    population = tiny_known_truth_population(
        target_plan=target,
        bands=(
            rank_band(
                "band-a",
                1,
                population_count + 1,
                representative("rep-rival", rival, population_count),
            ),
        ),
    )
    scenarios = scenario_set()
    result = simulate_synthetic_overall_rank(
        population,
        multiplier_sets_for_population(population, scenarios),
        rank_tie_policy(),
        target_rank=1,
    )
    rival_ahead = rival_points > target_points or (
        rival_points == target_points and rival_transfers < target_transfers
    )
    expected_rank = 1 + (population_count if rival_ahead else 0)
    assert result.distribution.rank_pmf[0].rank == expected_rank
    assert result.distribution.rank_pmf[0].probability == 1.0
    assert result.distribution.probability_target_rank == (0.0 if rival_ahead else 1.0)
    assert result.distribution.expected_rank == expected_rank
    assert expected_rank <= result.distribution.population_size
