from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.manager_multipliers import calculate_manager_multipliers
from dmf_pulse.rank_strategy.models import (
    CohortMember,
    CohortSample,
    EffectiveOwnershipReport,
    ManagerChip,
    ManagerMultiplierSet,
    ManagerTeamPlan,
    PlayerOwnership,
    SampleRightsStatus,
    ScenarioManagerMultiplier,
)
from tests.support.rank_strategy_fixtures import (
    cohort,
    manager_plan,
    multiplier_policy,
    rank_players,
    rank_rules,
    scenario_set,
    tactic,
)

pytestmark = pytest.mark.unit


def test_rank_error_exposes_stable_machine_contract() -> None:
    error = RankStrategyError("RANK_TEST", "broken", value=3)
    assert error.as_error_object() == {
        "error": {"code": "RANK_TEST", "message": "broken", "details": {"value": 3}}
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(permanent_squad=tuple(reversed(payload["permanent_squad"]))),
        lambda payload: payload.update(active_chip="FREE_HIT", temporary_free_hit_squad=None),
        lambda payload: payload.update(temporary_free_hit_squad=payload["permanent_squad"]),
        lambda payload: payload.update(
            tactical_configuration=tactic().model_copy(
                update={"bench_order": ("p05", "p10", "p06")}
            )
        ),
    ],
)
def test_manager_team_contract_rejects_noncanonical_or_cross_surface_state(mutation) -> None:
    payload = manager_plan("m1").model_dump(mode="python")
    mutation(payload)
    with pytest.raises(ValidationError):
        ManagerTeamPlan.model_validate(payload)


def _sample_payload() -> dict[str, object]:
    return cohort(manager_plan("m1")).model_dump(mode="python")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(observed_at=datetime(2026, 8, 20, 10)),
        lambda payload: payload.update(
            observed_at=datetime(2026, 8, 20, 13, tzinfo=UTC),
            information_cutoff=datetime(2026, 8, 20, 12, tzinfo=UTC),
        ),
        lambda payload: payload.update(members=(payload["members"][0], payload["members"][0])),
        lambda payload: payload.update(
            members=(
                payload["members"][0],
                CohortMember(
                    sample_unit_id="different-unit",
                    manager_plan=manager_plan("m1"),
                    weight=1.0,
                ),
            )
        ),
        lambda payload: payload.update(rights_status="REPOSITORY_APPROVED"),
        lambda payload: payload.update(
            kind="NAMED_MINI_LEAGUE", rights_status="SYNTHETIC_APPROVED"
        ),
    ],
)
def test_cohort_contract_rejects_temporal_duplicate_and_rights_errors(mutation) -> None:
    payload = _sample_payload()
    mutation(payload)
    with pytest.raises(ValidationError):
        CohortSample.model_validate(payload)


def _multiplier() -> ScenarioManagerMultiplier:
    return calculate_manager_multipliers(
        manager_plan("m1"),
        scenario_set(),
        rank_players(),
        rank_rules(),
        multiplier_policy(),
    ).scenarios[0]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(
            player_multipliers=dict(reversed(payload["player_multipliers"].items()))
        ),
        lambda payload: payload.update(counted_player_ids=()),
        lambda payload: payload.update(net_points=payload["net_points"] + 1),
    ],
)
def test_multiplier_contract_rejects_noncanonical_and_unreconciled_state(mutation) -> None:
    payload = _multiplier().model_dump(mode="python")
    mutation(payload)
    with pytest.raises(ValidationError):
        ScenarioManagerMultiplier.model_validate(payload)


def test_multiplier_set_rejects_duplicate_identity_and_invalid_total_weight() -> None:
    result = calculate_manager_multipliers(
        manager_plan("m1"),
        scenario_set(
            {f"p{index:02d}": 1 for index in range(15)},
            {f"p{index:02d}": 2 for index in range(15)},
        ),
        rank_players(),
        rank_rules(),
        multiplier_policy(),
    )
    duplicate = result.model_dump(mode="python")
    duplicate["scenarios"] = (duplicate["scenarios"][0], duplicate["scenarios"][0])
    with pytest.raises(ValidationError):
        ManagerMultiplierSet.model_validate(duplicate)

    invalid_weight = result.model_dump(mode="python")
    invalid_weight["scenarios"] = tuple(
        {**item, "weight": 0.4} for item in invalid_weight["scenarios"]
    )
    with pytest.raises(ValidationError):
        ManagerMultiplierSet.model_validate(invalid_weight)


def _ownership() -> PlayerOwnership:
    return PlayerOwnership(
        player_id="p1",
        raw_ownership=10.0,
        starting_ownership=10.0,
        normal_captain_ownership=0.0,
        triple_captain_ownership=0.0,
        vice_ownership=0.0,
        bench_boost_counted_ownership=0.0,
        saved_effective_ownership=10.0,
        expected_scenario_effective_ownership=20.0,
        scenario_effective_ownership={"s|d": 20.0},
        eo_p10=10.0,
        eo_p90=30.0,
        sebastian_expected_multiplier=1.0,
        expected_leverage=0.8,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(raw_ownership=101.0),
        lambda payload: payload.update(scenario_effective_ownership={"z": 1.0, "a": 2.0}),
        lambda payload: payload.update(eo_p10=40.0, eo_p90=30.0),
        lambda payload: payload.update(expected_leverage=None),
        lambda payload: payload.update(expected_leverage=0.7),
    ],
)
def test_player_ownership_contract_rejects_misleading_diagnostics(mutation) -> None:
    payload = _ownership().model_dump(mode="python")
    mutation(payload)
    with pytest.raises(ValidationError):
        PlayerOwnership.model_validate(payload)


def test_effective_ownership_report_requires_sorted_unique_players() -> None:
    entry = _ownership()
    with pytest.raises(ValidationError):
        EffectiveOwnershipReport(
            sample_id="sample",
            rights_status=SampleRightsStatus.SYNTHETIC_APPROVED,
            scenario_set_hash="0" * 64,
            raw_projection_hash="1" * 64,
            entries=(entry, entry),
            confidence="A",
            report_hash="2" * 64,
        )


@pytest.mark.parametrize(
    ("players_mutation", "scenario_mutation", "rules_mutation", "expected_code"),
    [
        (lambda players: players.pop("p14"), None, None, "RANK_PLAYER_UNIVERSE_INVALID"),
        (
            None,
            lambda _scenarios: scenario_set(),
            None,
            "RANK_SCENARIO_UNIVERSE_INVALID",
        ),
        (
            None,
            None,
            lambda rules: rules.model_copy(update={"ruleset_hash": "9" * 64}),
            "RANK_RULESET_MISMATCH",
        ),
        (
            None,
            None,
            lambda rules: rules.model_copy(update={"squad_size": 14}),
            "RANK_SQUAD_SIZE_INVALID",
        ),
    ],
)
def test_manager_multiplier_input_boundary_fails_closed(
    players_mutation,
    scenario_mutation,
    rules_mutation,
    expected_code: str,
) -> None:
    plan = (
        manager_plan("m1", chip=ManagerChip.FREE_HIT, free_hit=True)
        if expected_code == "RANK_SCENARIO_UNIVERSE_INVALID"
        else manager_plan("m1")
    )
    players = rank_players(include_extra=plan.active_chip is ManagerChip.FREE_HIT)
    scenarios = scenario_set(include_extra=plan.active_chip is ManagerChip.FREE_HIT)
    rules = rank_rules()
    if players_mutation is not None:
        players_mutation(players)
    if scenario_mutation is not None:
        scenarios = scenario_mutation(scenarios)
    if rules_mutation is not None:
        rules = rules_mutation(rules)

    with pytest.raises(RankStrategyError) as exc_info:
        calculate_manager_multipliers(plan, scenarios, players, rules, multiplier_policy())
    assert exc_info.value.code == expected_code


def test_cohort_timezone_must_be_utc_not_merely_timezone_aware() -> None:
    payload = _sample_payload()
    payload["information_cutoff"] = datetime(2026, 8, 20, 14, tzinfo=timezone(timedelta(hours=2)))
    with pytest.raises(ValidationError):
        CohortSample.model_validate(payload)
