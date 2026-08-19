from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.rank_strategy.effective_ownership import calculate_effective_ownership
from dmf_pulse.rank_strategy.manager_multipliers import (
    calculate_manager_multipliers,
    raw_projection_hash,
)
from tests.support.rank_strategy_fixtures import (
    cohort,
    manager_plan,
    multiplier_policy,
    rank_players,
    rank_rules,
    scenario_set,
)

pytestmark = pytest.mark.property


@given(
    captain_points=st.integers(min_value=-3, max_value=30), hit_points=st.sampled_from([0, 4, 8])
)
def test_manager_score_is_always_dot_product_minus_hits(
    captain_points: int,
    hit_points: int,
) -> None:
    points = {f"p{index:02d}": index % 7 for index in range(15)}
    points["p12"] = captain_points
    scenarios = scenario_set(points)
    result = calculate_manager_multipliers(
        manager_plan("sebastian", hit_points=hit_points),
        scenarios,
        rank_players(),
        rank_rules(),
        multiplier_policy(),
    )
    value = result.scenarios[0]
    expected = sum(
        scenarios.scenarios[0].player_points[player_id] * multiplier
        for player_id, multiplier in value.player_multipliers.items()
    )
    assert value.gross_points == expected
    assert value.net_points == expected - hit_points


def test_projection_hash_is_identical_before_and_after_eo_evaluation() -> None:
    scenarios = scenario_set(
        {f"p{index:02d}": index for index in range(15)},
        {f"p{index:02d}": 15 - index for index in range(15)},
        weights=(0.3, 0.7),
    )
    before = raw_projection_hash(scenarios)
    report = calculate_effective_ownership(
        cohort(manager_plan("rival")),
        scenarios,
        rank_players(),
        rank_rules(),
        multiplier_policy(),
        sebastian_plan=manager_plan("sebastian"),
    )
    after = raw_projection_hash(scenarios)

    assert before == after == report.raw_projection_hash
    assert scenarios.scenarios[0].player_points["p14"] == 14
