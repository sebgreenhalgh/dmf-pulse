from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.manager_multipliers import calculate_manager_multipliers
from dmf_pulse.rank_strategy.mini_league import simulate_mini_league_rank
from dmf_pulse.rank_strategy.models import (
    CohortKind,
    RankDistribution,
    RankMass,
    SampleRightsStatus,
)
from tests.support.rank_strategy_fixtures import (
    cohort,
    exact_named_league,
    manager_plan,
    multiplier_policy,
    rank_players,
    rank_rules,
    rank_tie_policy,
    scenario_set,
)

pytestmark = pytest.mark.unit


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


def _simulate(plans, *, target="sebastian", target_rank=1, scenarios=None):
    scenarios = scenarios or scenario_set()
    return simulate_mini_league_rank(
        exact_named_league(*plans),
        _sets(plans, scenarios),
        rank_tie_policy(),
        target_manager_id=target,
        target_rank=target_rank,
    )


def test_points_tie_is_broken_by_fewer_counted_transfers() -> None:
    plans = (
        manager_plan("sebastian", cumulative_points=100, counted_transfers=7),
        manager_plan("rival", cumulative_points=100, counted_transfers=5),
    )
    result = _simulate(plans)
    standings = {item.manager_id: item for item in result.outcomes[0].standings}
    assert standings["rival"].rank == 1
    assert standings["sebastian"].rank == 2
    assert result.mini_league_win_probability == 0.0


def test_equal_points_and_counted_transfers_share_exact_rank() -> None:
    plans = (
        manager_plan("sebastian", cumulative_points=100, counted_transfers=5),
        manager_plan("rival", cumulative_points=100, counted_transfers=5),
        manager_plan("third", cumulative_points=90, counted_transfers=1),
    )
    result = _simulate(plans)
    standings = {item.manager_id: item for item in result.outcomes[0].standings}
    assert standings["sebastian"].rank == standings["rival"].rank == 1
    assert standings["third"].rank == 3
    assert standings["sebastian"].shared_rank is True
    assert result.outcomes[0].winner_manager_ids == ("rival", "sebastian")


def test_identical_teams_have_zero_relative_football_variance_except_hits() -> None:
    plans = (
        manager_plan("sebastian", cumulative_points=100, hit_points=0),
        manager_plan("rival", cumulative_points=100, hit_points=4),
    )
    scenarios = scenario_set(
        {f"p{index:02d}": index for index in range(15)},
        {f"p{index:02d}": 20 - index for index in range(15)},
        weights=(0.25, 0.75),
    )
    result = _simulate(plans, scenarios=scenarios)
    differences = []
    for outcome in result.outcomes:
        values = {item.manager_id: item.final_points for item in outcome.standings}
        differences.append(values["sebastian"] - values["rival"])
    assert differences == [4, 4]
    assert result.rank_pmf == (RankMass(rank=1, probability=1.0),)


def test_target_probability_is_derived_from_rank_pmf() -> None:
    plans = (
        manager_plan("sebastian", captain="p12"),
        manager_plan("rival", captain="p13"),
    )
    scenarios = scenario_set(
        {**{f"p{index:02d}": 2 for index in range(15)}, "p12": 8, "p13": 1},
        {**{f"p{index:02d}": 2 for index in range(15)}, "p12": 1, "p13": 8},
        weights=(0.3, 0.7),
    )
    result = _simulate(plans, target_rank=1, scenarios=scenarios)
    assert result.rank_pmf == (
        RankMass(rank=1, probability=0.3),
        RankMass(rank=2, probability=0.7),
    )
    assert result.probability_target_rank == 0.3
    assert result.expected_rank == 1.7


def test_unverified_tie_policy_fails_closed() -> None:
    plans = (manager_plan("sebastian"), manager_plan("rival"))
    scenarios = scenario_set()
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_mini_league_rank(
            exact_named_league(*plans),
            _sets(plans, scenarios),
            rank_tie_policy(verified=False),
            target_manager_id="sebastian",
        )
    assert exc_info.value.code == "RANK_TIE_RULES_INACTIVE"


def test_non_exact_cohort_kind_fails_closed() -> None:
    plans = (manager_plan("sebastian"), manager_plan("rival"))
    scenarios = scenario_set()
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_mini_league_rank(
            cohort(
                *plans,
                rights=SampleRightsStatus.REPOSITORY_APPROVED,
                kind=CohortKind.REPOSITORY_SAMPLE,
            ),
            _sets(plans, scenarios),
            rank_tie_policy(),
            target_manager_id="sebastian",
        )
    assert exc_info.value.code == "RANK_EXACT_LEAGUE_KIND_INVALID"


def test_manager_membership_plan_and_target_mismatches_fail_closed() -> None:
    plans = (manager_plan("sebastian"), manager_plan("rival"))
    scenarios = scenario_set()
    multiplier_sets = _sets(plans, scenarios)
    sample = exact_named_league(*plans)
    with pytest.raises(RankStrategyError, match="target manager"):
        simulate_mini_league_rank(
            sample,
            multiplier_sets,
            rank_tie_policy(),
            target_manager_id="missing",
        )
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_mini_league_rank(
            sample,
            multiplier_sets[:1],
            rank_tie_policy(),
            target_manager_id="sebastian",
        )
    assert exc_info.value.code == "RANK_MANAGER_SET_MISMATCH"
    tampered = multiplier_sets[1].model_copy(update={"plan_id": "wrong"})
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_mini_league_rank(
            sample,
            (multiplier_sets[0], tampered),
            rank_tie_policy(),
            target_manager_id="sebastian",
        )
    assert exc_info.value.code == "RANK_MANAGER_PLAN_MISMATCH"


def test_projection_and_shared_scenario_tampering_fail_closed() -> None:
    plans = (manager_plan("sebastian"), manager_plan("rival"))
    scenarios = scenario_set()
    multiplier_sets = _sets(plans, scenarios)
    sample = exact_named_league(*plans)
    raw_tampered = multiplier_sets[1].model_copy(update={"raw_projection_hash": "9" * 64})
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_mini_league_rank(
            sample,
            (multiplier_sets[0], raw_tampered),
            rank_tie_policy(),
            target_manager_id="sebastian",
        )
    assert exc_info.value.code == "RANK_RAW_PROJECTION_MISMATCH"

    hash_tampered = multiplier_sets[1].model_copy(update={"scenario_set_hash": "8" * 64})
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_mini_league_rank(
            sample,
            (multiplier_sets[0], hash_tampered),
            rank_tie_policy(),
            target_manager_id="sebastian",
        )
    assert exc_info.value.code == "RANK_SHARED_SCENARIO_HASH_MISMATCH"

    first = multiplier_sets[1].scenarios[0]
    identity_tampered = multiplier_sets[1].model_copy(
        update={"scenarios": (first.model_copy(update={"scenario_id": "different"}),)}
    )
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_mini_league_rank(
            sample,
            (multiplier_sets[0], identity_tampered),
            rank_tie_policy(),
            target_manager_id="sebastian",
        )
    assert exc_info.value.code == "RANK_SHARED_SCENARIO_IDENTITY_MISMATCH"


def test_rank_distribution_contract_rejects_invalid_probability_and_target_derivation() -> None:
    result = _simulate((manager_plan("sebastian"), manager_plan("rival")))
    payload = result.model_dump(mode="python")
    payload["rank_pmf"] = (
        {"rank": 1, "probability": 0.6},
        {"rank": 2, "probability": 0.6},
    )
    with pytest.raises(ValidationError):
        RankDistribution.model_validate(payload)

    payload = result.model_dump(mode="python")
    payload["probability_target_rank"] = 0.0
    with pytest.raises(ValidationError):
        RankDistribution.model_validate(payload)


def test_invalid_target_rank_fails_with_stable_error() -> None:
    plans = (manager_plan("sebastian"), manager_plan("rival"))
    scenarios = scenario_set()
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_mini_league_rank(
            exact_named_league(*plans),
            _sets(plans, scenarios),
            rank_tie_policy(),
            target_manager_id="sebastian",
            target_rank=0,
        )
    assert exc_info.value.code == "RANK_TARGET_INVALID"
