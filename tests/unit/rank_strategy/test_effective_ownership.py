from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dmf_pulse.rank_strategy.effective_ownership import calculate_effective_ownership
from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.models import (
    CohortKind,
    CohortMember,
    CohortSample,
    ManagerChip,
    SampleRightsStatus,
)
from tests.support.rank_strategy_fixtures import (
    cohort,
    manager_plan,
    multiplier_policy,
    rank_players,
    rank_rules,
    scenario_set,
)

pytestmark = pytest.mark.unit


def _entry(report, player_id: str):
    return next(item for item in report.entries if item.player_id == player_id)


def test_effective_ownership_is_mean_multiplier_and_can_exceed_100() -> None:
    sample = cohort(
        manager_plan("captain"),
        manager_plan("triple", chip=ManagerChip.TRIPLE_CAPTAIN),
        weights=(0.5, 0.5),
    )
    report = calculate_effective_ownership(
        sample,
        scenario_set(),
        rank_players(),
        rank_rules(),
        multiplier_policy(),
    )

    captain = _entry(report, "p12")
    assert captain.raw_ownership == 100.0
    assert captain.normal_captain_ownership == 50.0
    assert captain.triple_captain_ownership == 50.0
    assert captain.expected_scenario_effective_ownership == 250.0


def test_raw_ownership_is_not_substituted_for_effective_ownership() -> None:
    report = calculate_effective_ownership(
        cohort(manager_plan("captain")),
        scenario_set(),
        rank_players(),
        rank_rules(),
        multiplier_policy(),
    )
    captain = _entry(report, "p12")
    bench = _entry(report, "p05")

    assert captain.raw_ownership == bench.raw_ownership == 100.0
    assert captain.expected_scenario_effective_ownership == 200.0
    assert bench.expected_scenario_effective_ownership == 0.0


def test_expected_leverage_reconciles_to_sebastian_multiplier_minus_eo() -> None:
    sample = cohort(manager_plan("rival", captain="p13", vice="p12"))
    report = calculate_effective_ownership(
        sample,
        scenario_set(),
        rank_players(),
        rank_rules(),
        multiplier_policy(),
        sebastian_plan=manager_plan("sebastian"),
    )
    player = _entry(report, "p12")

    assert player.sebastian_expected_multiplier == 2.0
    assert player.expected_scenario_effective_ownership == 100.0
    assert player.expected_leverage == 1.0


def test_vice_fallback_and_bench_boost_change_scenario_eo_not_raw_ownership() -> None:
    appearances = ({"p12": False, "p13": True, "p04": False, "p05": True},)
    sample = cohort(
        manager_plan("ordinary"),
        manager_plan("bench", chip=ManagerChip.BENCH_BOOST),
    )
    report = calculate_effective_ownership(
        sample,
        scenario_set(appearances=appearances),
        rank_players(),
        rank_rules(),
        multiplier_policy(),
    )

    vice = _entry(report, "p13")
    bench = _entry(report, "p05")
    assert vice.expected_scenario_effective_ownership == 200.0
    assert bench.raw_ownership == 100.0
    assert bench.expected_scenario_effective_ownership == 100.0
    assert bench.bench_boost_counted_ownership == 50.0


def test_invalid_rights_fail_closed_before_numerical_use() -> None:
    plan = manager_plan("unknown")
    sample = CohortSample(
        sample_id="invalid",
        kind=CohortKind.REPOSITORY_SAMPLE,
        rights_status=SampleRightsStatus.UNKNOWN,
        observed_at=datetime(2026, 8, 20, 10, tzinfo=UTC),
        information_cutoff=datetime(2026, 8, 20, 12, tzinfo=UTC),
        members=(CohortMember(sample_unit_id="u1", manager_plan=plan, weight=1.0),),
        confidence="E",
    )

    with pytest.raises(RankStrategyError) as exc_info:
        calculate_effective_ownership(
            sample,
            scenario_set(),
            rank_players(),
            rank_rules(),
            multiplier_policy(),
        )

    assert exc_info.value.code == "RANK_SAMPLE_RIGHTS_INVALID"
