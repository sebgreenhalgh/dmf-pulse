from __future__ import annotations

import pytest

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
from tests.support.rank_strategy_oracle import exhaustive_mini_league_oracle

pytestmark = pytest.mark.integration


def _sets(plans, scenarios):
    return tuple(
        calculate_manager_multipliers(
            plan,
            scenarios,
            rank_players(),
            rank_rules(),
            multiplier_policy(),
        )
        for plan in plans
    )


def _point_map(**updates: int) -> dict[str, int]:
    values = {f"p{index:02d}": 2 for index in range(15)}
    values.update(updates)
    return values


def _assert_matches_oracle(plans, scenarios, target_manager_id: str, target_rank: int) -> None:
    sample = exact_named_league(*plans)
    multiplier_sets = _sets(plans, scenarios)
    actual = simulate_mini_league_rank(
        sample,
        multiplier_sets,
        rank_tie_policy(),
        target_manager_id=target_manager_id,
        target_rank=target_rank,
    )
    oracle = exhaustive_mini_league_oracle(
        sample,
        multiplier_sets,
        target_manager_id=target_manager_id,
        target_rank=target_rank,
    )
    assert tuple((item.rank, item.probability) for item in actual.rank_pmf) == oracle["rank_pmf"]
    assert actual.expected_rank == oracle["expected_rank"]
    assert actual.probability_target_rank == oracle["probability_target_rank"]
    assert actual.mini_league_win_probability == oracle["win_probability"]
    for actual_outcome, oracle_outcome in zip(actual.outcomes, oracle["outcomes"], strict=True):
        assert {item.manager_id: item.rank for item in actual_outcome.standings} == oracle_outcome[
            "ranks"
        ]
        assert {
            item.manager_id: item.final_points for item in actual_outcome.standings
        } == oracle_outcome["final_points"]


def test_exact_two_manager_league_matches_independent_exhaustive_oracle() -> None:
    plans = (
        manager_plan("sebastian", captain="p12", vice="p13", cumulative_points=100),
        manager_plan("rival", captain="p13", vice="p12", cumulative_points=100),
    )
    scenarios = scenario_set(
        _point_map(p12=10, p13=1),
        _point_map(p12=1, p13=10),
        weights=(0.4, 0.6),
    )
    _assert_matches_oracle(plans, scenarios, "sebastian", 1)


def test_exact_three_manager_league_matches_independent_exhaustive_oracle() -> None:
    plans = (
        manager_plan("sebastian", captain="p12", cumulative_points=100),
        manager_plan("rival-a", captain="p13", cumulative_points=101),
        manager_plan("rival-b", captain="p14", cumulative_points=99),
    )
    scenarios = scenario_set(
        _point_map(p12=12, p13=2, p14=4),
        _point_map(p12=2, p13=12, p14=4),
        _point_map(p12=2, p13=4, p14=12),
        weights=(0.2, 0.3, 0.5),
    )
    _assert_matches_oracle(plans, scenarios, "sebastian", 2)


def test_exact_multi_manager_league_matches_oracle() -> None:
    plans = (
        manager_plan("sebastian", captain="p12", cumulative_points=98),
        manager_plan("rival-a", captain="p13", cumulative_points=100),
        manager_plan("rival-b", captain="p14", cumulative_points=97),
        manager_plan("rival-c", captain="p12", cumulative_points=96, hit_points=4),
    )
    scenarios = scenario_set(
        _point_map(p12=8, p13=3, p14=5),
        _point_map(p12=2, p13=9, p14=4),
        weights=(0.45, 0.55),
    )
    _assert_matches_oracle(plans, scenarios, "sebastian", 2)
