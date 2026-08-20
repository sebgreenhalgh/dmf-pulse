from __future__ import annotations

import pytest

from dmf_pulse.rank_strategy.manager_multipliers import (
    calculate_manager_multipliers,
    raw_projection_hash,
    shared_scenario_set_hash,
)
from dmf_pulse.rank_strategy.models import ManagerChip
from tests.support.rank_strategy_fixtures import (
    manager_plan,
    multiplier_policy,
    rank_players,
    rank_rules,
    scenario_set,
)

pytestmark = pytest.mark.unit


def _points(**updates: int) -> dict[str, int]:
    values = {f"p{index:02d}": 2 for index in range(16)}
    values.update(updates)
    return values


def test_raw_projection_hash_binds_stage9_and_upstream_event_lineage() -> None:
    scenarios = scenario_set()
    changed_model = scenarios.model_copy(update={"model_version_ids": ("different-model",)})
    changed_stage8 = scenarios.model_copy(update={"upstream_stage8_sha256s": ("9" * 64,)})

    assert raw_projection_hash(changed_model) != raw_projection_hash(scenarios)
    assert raw_projection_hash(changed_stage8) != raw_projection_hash(scenarios)
    assert shared_scenario_set_hash(changed_model) == shared_scenario_set_hash(scenarios)
    assert shared_scenario_set_hash(changed_stage8) == shared_scenario_set_hash(scenarios)


def test_normal_captain_and_player_multipliers_reconcile_exactly() -> None:
    scenarios = scenario_set(_points(p12=6))
    result = calculate_manager_multipliers(
        manager_plan("sebastian"), scenarios, rank_players(), rank_rules(), multiplier_policy()
    )

    multiplier = result.scenarios[0]
    assert multiplier.player_multipliers["p12"] == 2
    assert multiplier.player_multipliers["p05"] == 0
    assert multiplier.gross_points == sum(
        scenarios.scenarios[0].player_points[player_id] * value
        for player_id, value in multiplier.player_multipliers.items()
    )
    assert result.expected_gross_points == float(multiplier.gross_points)


def test_vice_inherits_multiplier_only_when_captain_does_not_appear() -> None:
    appearances = ({"p12": False, "p13": True},)
    scenarios = scenario_set(_points(p12=10, p13=7), appearances=appearances)
    result = calculate_manager_multipliers(
        manager_plan("sebastian"), scenarios, rank_players(), rank_rules(), multiplier_policy()
    )

    multiplier = result.scenarios[0]
    assert multiplier.player_multipliers["p12"] == 0
    assert multiplier.player_multipliers["p13"] == 2
    assert multiplier.effective_captain_id == "p13"
    assert multiplier.captain_resolution.value == "VICE_CAPTAIN"


def test_triple_captain_uses_three_not_raw_captain_ownership() -> None:
    scenarios = scenario_set(_points(p12=8))
    result = calculate_manager_multipliers(
        manager_plan("sebastian", chip=ManagerChip.TRIPLE_CAPTAIN),
        scenarios,
        rank_players(),
        rank_rules(),
        multiplier_policy(),
    )

    assert result.scenarios[0].player_multipliers["p12"] == 3


def test_bench_boost_counts_appearing_bench_once_without_recording_autosubs() -> None:
    appearances = ({"p04": False, "p05": True, "p11": True, "p06": True, "p01": True},)
    scenarios = scenario_set(_points(p05=9, p11=7, p06=5, p01=6), appearances=appearances)
    result = calculate_manager_multipliers(
        manager_plan("sebastian", chip=ManagerChip.BENCH_BOOST),
        scenarios,
        rank_players(),
        rank_rules(),
        multiplier_policy(),
    )

    multiplier = result.scenarios[0]
    assert multiplier.player_multipliers["p01"] == 1
    assert multiplier.player_multipliers["p05"] == 1
    assert multiplier.player_multipliers["p11"] == 1
    assert multiplier.player_multipliers["p06"] == 1
    assert multiplier.player_multipliers["p04"] == 0
    assert multiplier.autosubs == ()


def test_free_hit_scores_temporary_squad_without_mutating_permanent_squad() -> None:
    scenarios = scenario_set(_points(p11=1, p15=12), include_extra=True)
    plan = manager_plan("sebastian", chip=ManagerChip.FREE_HIT, free_hit=True)
    result = calculate_manager_multipliers(
        plan,
        scenarios,
        rank_players(include_extra=True),
        rank_rules(),
        multiplier_policy(),
    )

    multiplier = result.scenarios[0]
    assert "p11" in plan.permanent_squad
    assert "p11" not in plan.active_squad
    assert multiplier.player_multipliers["p11"] == 0
    assert multiplier.player_multipliers["p15"] == 1


def test_transfer_hit_is_deducted_once_from_net_score() -> None:
    scenarios = scenario_set(_points())
    result = calculate_manager_multipliers(
        manager_plan("sebastian", hit_points=4),
        scenarios,
        rank_players(),
        rank_rules(),
        multiplier_policy(),
    )
    assert result.scenarios[0].net_points == result.scenarios[0].gross_points - 4
    assert result.expected_net_points == result.expected_gross_points - 4.0
