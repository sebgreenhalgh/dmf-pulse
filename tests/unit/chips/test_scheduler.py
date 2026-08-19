from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.compiler import compile_synthetic_bundle
from dmf_pulse.chips.definitions import (
    ActivationRoute,
    ChipDefinition,
    ChipEffect,
    InventoryGrant,
    semantic_sha256,
)
from dmf_pulse.chips.inventory import ChipInventory, TokenStatus, build_chip_inventory
from dmf_pulse.chips.schedule_models import (
    ChipScheduleCandidate,
    ChipScheduleOpportunity,
    ChipSchedulePolicy,
    ChipScheduleRequest,
    OpportunityLineage,
    OpportunitySourceKind,
    PerfectInformationUpperBound,
    RootScheduleAction,
    ScheduleObjectiveConfig,
    ScheduleObjectiveMode,
    ScheduleScenarioIdentity,
    ScheduleScenarioOutcome,
    ScheduleScenarioValue,
    ScheduleSearchMethod,
    TerminalTokenValue,
    scenario_set_hash,
    seal_opportunity,
    seal_schedule_request,
)
from dmf_pulse.chips.scheduler import (
    estimate_state_space,
    exact_small_schedule_oracle,
    optimise_chip_schedule,
)

NOW = datetime(2026, 8, 18, 18, tzinfo=UTC)
RULESET_HASH = "1" * 64
SOURCE_HASH = "2" * 64
CONFIG_HASH = "3" * 64


def _definition(
    key: str,
    *,
    start: int = 1,
    end: int = 6,
    copies: int = 1,
    duration: int = 1,
    group: str = "CHIP",
    minimum_gap: int = 0,
    acquired: int | None = None,
    excluded: tuple[int, ...] = (),
) -> ChipDefinition:
    return ChipDefinition(
        chip_key=key,
        definition_version=f"SYNTHETIC:{key}:V1",
        grants=(
            InventoryGrant(
                grant_id="window",
                copies=copies,
                acquired_gameweek=acquired if acquired is not None else start,
                activation_start_gameweek=start,
                activation_end_gameweek=end,
                expires_after_gameweek=end,
            ),
        ),
        duration_gameweeks=duration,
        concurrency_group=group,
        activation_route=ActivationRoute.PICK_TEAM_SAVE,
        cancellable_before_lock=True,
        excluded_gameweeks=excluded,
        minimum_gap_gameweeks=minimum_gap,
        effects=(
            ChipEffect(
                surface="SCORING",
                operation="ADD_POINTS",
                parameters={"points": 1},
            ),
        ),
    )


def _inventory(
    *definitions: ChipDefinition,
    current_gameweek: int = 1,
    concurrency_limit: int = 1,
) -> ChipInventory:
    bundle = compile_synthetic_bundle(
        ruleset_id="SYNTHETIC-CHIPS",
        ruleset_version="1.0",
        ruleset_hash=RULESET_HASH,
        concurrency_limit=concurrency_limit,
        definitions=definitions,
    )
    return build_chip_inventory(bundle, current_gameweek=current_gameweek)


def _scenarios() -> tuple[ScheduleScenarioIdentity, ...]:
    return (
        ScheduleScenarioIdentity(scenario_id="S1", outcome_draw_id="D1", weight=0.5),
        ScheduleScenarioIdentity(scenario_id="S2", outcome_draw_id="D2", weight=0.5),
    )


def _opportunity(
    inventory: ChipInventory,
    *,
    token_id: str,
    gameweek: int,
    values: tuple[float, float],
    opportunity_id: str | None = None,
    continuation: tuple[float, float] = (0.0, 0.0),
    costs: tuple[float, float] = (0.0, 0.0),
    cash: tuple[float, float] = (0.0, 0.0),
    terminal: tuple[float, float] = (0.0, 0.0),
    robust_penalty: float = 0.0,
    optimistic_upper_bound: float | None = None,
    requires: tuple[str, ...] = (),
    forbids: tuple[str, ...] = (),
    source_kind: OpportunitySourceKind = OpportunitySourceKind.FORECAST,
    usable_at: datetime = NOW,
    information_cutoff: datetime = NOW,
    forecast_origin: datetime = NOW,
    scenario_ids: tuple[tuple[str, str, float], ...] | None = None,
) -> ChipScheduleOpportunity:
    token = inventory.token(token_id)
    identity_values = scenario_ids or (("S1", "D1", 0.5), ("S2", "D2", 0.5))
    scenario_values = tuple(
        ScheduleScenarioValue(
            scenario_id=identity[0],
            outcome_draw_id=identity[1],
            weight=identity[2],
            gross_current_gain=values[index],
            continuation_value=continuation[index],
            policy_cost=costs[index],
            net_policy_value=values[index] + continuation[index] - costs[index],
            cash_like_value=cash[index],
            terminal_state_value=terminal[index],
        )
        for index, identity in enumerate(identity_values)
    )
    expected_gross = sum(item.weight * item.gross_current_gain for item in scenario_values)
    expected_continuation = sum(item.weight * item.continuation_value for item in scenario_values)
    expected_cost = sum(item.weight * item.policy_cost for item in scenario_values)
    expected_net = sum(item.weight * item.net_policy_value for item in scenario_values)
    expected_cash = sum(item.weight * item.cash_like_value for item in scenario_values)
    expected_terminal = sum(item.weight * item.terminal_state_value for item in scenario_values)
    scenario_hash = scenario_set_hash(
        tuple(
            ScheduleScenarioIdentity(
                scenario_id=item.scenario_id,
                outcome_draw_id=item.outcome_draw_id,
                weight=item.weight,
            )
            for item in scenario_values
        )
    )
    identifier = opportunity_id or f"{token.chip_key.lower()}-{gameweek}-{token.copy_index}"
    value = ChipScheduleOpportunity(
        opportunity_id=identifier,
        candidate_history_key=f"history:{identifier}",
        token_id=token_id,
        chip_key=token.chip_key,
        activation_gameweek=gameweek,
        duration_gameweeks=token.duration_gameweeks,
        requires_prior_opportunity_ids=tuple(sorted(requires)),
        forbids_prior_opportunity_ids=tuple(sorted(forbids)),
        scenario_values=scenario_values,
        expected_gross_current_gain=expected_gross,
        expected_continuation_value=expected_continuation,
        expected_policy_cost=expected_cost,
        expected_net_policy_value=expected_net,
        expected_cash_like_value=expected_cash,
        expected_terminal_state_value=expected_terminal,
        robust_penalty=robust_penalty,
        optimistic_upper_bound=(
            optimistic_upper_bound
            if optimistic_upper_bound is not None
            else max(
                item.net_policy_value + item.cash_like_value + item.terminal_state_value
                for item in scenario_values
            )
        ),
        lineage=OpportunityLineage(
            forecast_origin=forecast_origin,
            information_cutoff=information_cutoff,
            usable_at=usable_at,
            decision_cutoff=NOW + timedelta(days=max(0, gameweek - 1) * 7),
            source_kind=source_kind,
            source_artifact_hash=SOURCE_HASH,
            scenario_set_hash=scenario_hash,
            model_version="SYNTHETIC-V1",
            configuration_hash=CONFIG_HASH,
            code_commit="abcdef0",
        ),
        opportunity_hash="0" * 64,
    )
    return seal_opportunity(value)


def _request(
    inventory: ChipInventory,
    *opportunities: ChipScheduleOpportunity,
    horizon_end: int = 6,
    terminal_values: tuple[TerminalTokenValue, ...] = (),
    objective: ScheduleObjectiveConfig | None = None,
    information_cutoff: datetime = NOW,
) -> ChipScheduleRequest:
    scenarios = _scenarios()
    value = ChipScheduleRequest(
        request_id="SCHEDULE-REQUEST",
        inventory=inventory,
        horizon_start_gameweek=inventory.current_gameweek,
        horizon_end_gameweek=horizon_end,
        information_cutoff=information_cutoff,
        scenario_universe=scenarios,
        scenario_set_hash=scenario_set_hash(scenarios),
        opportunities=tuple(
            sorted(
                opportunities,
                key=lambda item: (
                    item.activation_gameweek,
                    item.chip_key,
                    item.token_id,
                    item.opportunity_id,
                ),
            )
        ),
        terminal_token_values=tuple(sorted(terminal_values, key=lambda item: item.token_id)),
        objective=objective or ScheduleObjectiveConfig(config_version="TEST-V1"),
        request_hash="0" * 64,
    )
    return seal_schedule_request(value)


def test_exact_small_schedule_matches_forced_oracle() -> None:
    inventory = _inventory(_definition("TC"), _definition("BB"))
    tc, bb = inventory.tokens
    request = _request(
        inventory,
        _opportunity(inventory, token_id=tc.token_id, gameweek=1, values=(4.0, 2.0)),
        _opportunity(inventory, token_id=tc.token_id, gameweek=3, values=(5.0, 5.0)),
        _opportunity(inventory, token_id=bb.token_id, gameweek=2, values=(3.0, 3.0)),
    )

    policy = optimise_chip_schedule(request)
    oracle = exact_small_schedule_oracle(request)

    assert policy.diagnostics.method is ScheduleSearchMethod.EXACT_DYNAMIC_PROGRAMMING
    assert policy.diagnostics.exact_optimality is True
    assert policy.selected_schedule.schedule_hash == oracle.selected_schedule.schedule_hash
    assert tuple(item.activation_gameweek for item in policy.selected_schedule.activations) == (
        2,
        3,
    )


def test_finite_token_is_never_reused() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(inventory, token_id=token.token_id, gameweek=1, values=(4.0, 4.0)),
        _opportunity(inventory, token_id=token.token_id, gameweek=2, values=(5.0, 5.0)),
    )

    policy = optimise_chip_schedule(request)

    assert len(policy.selected_schedule.activations) == 1
    assert policy.selected_schedule.activations[0].activation_gameweek == 2


def test_multiple_copies_are_jointly_scheduled() -> None:
    inventory = _inventory(_definition("TC", copies=2, minimum_gap=0))
    first, second = inventory.tokens
    request = _request(
        inventory,
        _opportunity(inventory, token_id=first.token_id, gameweek=1, values=(3.0, 3.0)),
        _opportunity(inventory, token_id=second.token_id, gameweek=2, values=(4.0, 4.0)),
    )

    policy = optimise_chip_schedule(request)

    assert {item.token_id for item in policy.selected_schedule.activations} == {
        first.token_id,
        second.token_id,
    }


def test_minimum_gap_uses_completed_interval() -> None:
    inventory = _inventory(_definition("BOOST", copies=2, minimum_gap=1))
    first, second = inventory.tokens
    blocked = _request(
        inventory,
        _opportunity(inventory, token_id=first.token_id, gameweek=1, values=(5.0, 5.0)),
        _opportunity(inventory, token_id=second.token_id, gameweek=2, values=(5.0, 5.0)),
    )
    legal = _request(
        inventory,
        _opportunity(inventory, token_id=first.token_id, gameweek=1, values=(5.0, 5.0)),
        _opportunity(inventory, token_id=second.token_id, gameweek=3, values=(5.0, 5.0)),
    )

    assert len(optimise_chip_schedule(blocked).selected_schedule.activations) == 1
    assert len(optimise_chip_schedule(legal).selected_schedule.activations) == 2


def test_multiweek_duration_blocks_conflicting_future_chip() -> None:
    inventory = _inventory(
        _definition("MULTI", duration=2, group="SQUAD"),
        _definition("FH", group="SQUAD"),
    )
    token_by_key = {item.chip_key: item for item in inventory.tokens}
    multi = token_by_key["MULTI"]
    free_hit = token_by_key["FH"]
    request = _request(
        inventory,
        _opportunity(inventory, token_id=multi.token_id, gameweek=1, values=(8.0, 8.0)),
        _opportunity(inventory, token_id=free_hit.token_id, gameweek=2, values=(7.0, 7.0)),
    )

    policy = optimise_chip_schedule(request)

    assert len(policy.selected_schedule.activations) == 1
    assert policy.selected_schedule.activations[0].chip_key == "MULTI"


def test_concurrency_limit_allows_distinct_groups_when_configured() -> None:
    inventory = _inventory(
        _definition("A", group="A"),
        _definition("B", group="B"),
        concurrency_limit=2,
    )
    first, second = inventory.tokens
    request = _request(
        inventory,
        _opportunity(inventory, token_id=first.token_id, gameweek=1, values=(3.0, 3.0)),
        _opportunity(inventory, token_id=second.token_id, gameweek=1, values=(4.0, 4.0)),
    )

    policy = optimise_chip_schedule(request)

    assert len(policy.selected_schedule.current_opportunity_ids) == 2


def test_same_concurrency_group_conflicts_even_with_global_capacity() -> None:
    inventory = _inventory(
        _definition("A", group="SAME"),
        _definition("B", group="SAME"),
        concurrency_limit=2,
    )
    first, second = inventory.tokens
    request = _request(
        inventory,
        _opportunity(inventory, token_id=first.token_id, gameweek=1, values=(3.0, 3.0)),
        _opportunity(inventory, token_id=second.token_id, gameweek=1, values=(4.0, 4.0)),
    )

    assert len(optimise_chip_schedule(request).selected_schedule.activations) == 1


def test_hold_is_legal_and_wins_a_zero_tie() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(inventory, token_id=token.token_id, gameweek=1, values=(0.0, 0.0)),
    )

    policy = optimise_chip_schedule(request)

    assert policy.recommended_action is RootScheduleAction.HOLD
    assert policy.selected_schedule.activations == ()


def test_expire_unused_is_explicit() -> None:
    inventory = _inventory(_definition("TC", end=1))
    request = _request(inventory, horizon_end=1)

    policy = optimise_chip_schedule(request)

    assert policy.recommended_action is RootScheduleAction.EXPIRE_UNUSED
    assert policy.best_never_use_schedule.token_dispositions[0].disposition.value == "EXPIRE_UNUSED"


def test_terminal_inventory_value_can_make_hold_optimal() -> None:
    inventory = _inventory(_definition("TC", end=10))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(inventory, token_id=token.token_id, gameweek=1, values=(3.0, 3.0)),
        horizon_end=3,
        terminal_values=(TerminalTokenValue(token_id=token.token_id, expected_terminal_value=5.0),),
    )

    policy = optimise_chip_schedule(request)

    assert policy.recommended_action is RootScheduleAction.HOLD
    assert policy.best_never_use_schedule.expected_terminal_state_value == 5.0


def test_robust_objective_uses_declared_penalty_not_outcome_variance() -> None:
    inventory = _inventory(_definition("A"), _definition("B"))
    first, second = inventory.tokens
    objective = ScheduleObjectiveConfig(
        objective_mode=ScheduleObjectiveMode.ROBUST,
        robust_penalty_weight=1.0,
        config_version="ROBUST-V1",
    )
    request = _request(
        inventory,
        _opportunity(
            inventory,
            token_id=first.token_id,
            gameweek=1,
            values=(8.0, 8.0),
            robust_penalty=5.0,
        ),
        _opportunity(
            inventory,
            token_id=second.token_id,
            gameweek=1,
            values=(5.0, 5.0),
            robust_penalty=0.0,
        ),
        objective=objective,
    )

    policy = optimise_chip_schedule(request)

    assert policy.selected_chip_keys == ("B",)
    assert policy.selected_schedule.risk_adjusted_objective == 5.0


def test_cash_terminal_objective_is_configured_explicitly() -> None:
    inventory = _inventory(_definition("A"), _definition("B"))
    first, second = inventory.tokens
    objective = ScheduleObjectiveConfig(
        objective_mode=ScheduleObjectiveMode.CASH_TERMINAL,
        cash_like_weight=1.0,
        terminal_state_weight=1.0,
        config_version="CASH-V1",
    )
    request = _request(
        inventory,
        _opportunity(
            inventory,
            token_id=first.token_id,
            gameweek=1,
            values=(5.0, 5.0),
        ),
        _opportunity(
            inventory,
            token_id=second.token_id,
            gameweek=1,
            values=(3.0, 3.0),
            cash=(4.0, 4.0),
        ),
        objective=objective,
    )

    assert optimise_chip_schedule(request).selected_chip_keys == ("B",)


def test_use_now_delay_and_never_use_are_kept_separate() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(inventory, token_id=token.token_id, gameweek=1, values=(4.0, 4.0)),
        _opportunity(inventory, token_id=token.token_id, gameweek=3, values=(6.0, 6.0)),
    )

    policy = optimise_chip_schedule(request)

    assert policy.best_use_now_schedule is not None
    assert policy.best_delay_schedule is not None
    assert policy.best_delay_schedule.activations[0].activation_gameweek == 3
    assert policy.best_never_use_schedule.activations == ()
    assert policy.exercise_advantage == -2.0
    assert policy.recommended_action is RootScheduleAction.HOLD


def test_probability_now_optimal_has_explicit_common_scenario_definition() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(inventory, token_id=token.token_id, gameweek=1, values=(10.0, -1.0)),
        _opportunity(inventory, token_id=token.token_id, gameweek=2, values=(0.0, 5.0)),
    )

    diagnostic = optimise_chip_schedule(request).probability_now_optimal

    assert diagnostic.probability_now_optimal == 0.5
    assert diagnostic.denominator_weight == 1.0
    assert diagnostic.diagnostic_only is True
    assert diagnostic.scenario_set_hash == request.scenario_set_hash


def test_perfect_information_bound_is_diagnostic_and_does_not_select_schedule() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(inventory, token_id=token.token_id, gameweek=1, values=(10.0, -1.0)),
        _opportunity(inventory, token_id=token.token_id, gameweek=2, values=(0.0, 5.0)),
    )

    policy = optimise_chip_schedule(request)

    assert policy.selected_schedule.activations[0].activation_gameweek == 1
    assert policy.perfect_information_upper_bound.expected_upper_bound == 7.5
    assert policy.perfect_information_upper_bound.diagnostic_only is True
    assert policy.perfect_information_upper_bound.bound_method == "EXACT_SCENARIO_ORACLE"


def test_post_cutoff_forecast_is_rejected_as_future_artifact_leakage() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    opportunity = _opportunity(
        inventory,
        token_id=token.token_id,
        gameweek=2,
        values=(5.0, 5.0),
        usable_at=NOW + timedelta(minutes=1),
        forecast_origin=NOW + timedelta(minutes=1),
        information_cutoff=NOW + timedelta(minutes=1),
    )

    with pytest.raises(ValidationError, match="future-artifact leakage"):
        _request(inventory, opportunity)


@pytest.mark.parametrize(
    "source_kind",
    [
        OpportunitySourceKind.REALISED_OUTCOME,
        OpportunitySourceKind.PERFECT_INFORMATION_DIAGNOSTIC,
    ],
)
def test_nonforecast_truth_paths_are_rejected(source_kind: OpportunitySourceKind) -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    opportunity = _opportunity(
        inventory,
        token_id=token.token_id,
        gameweek=1,
        values=(5.0, 5.0),
        source_kind=source_kind,
    )

    with pytest.raises(ValidationError, match="forecast opportunities only"):
        _request(inventory, opportunity)


def test_common_scenario_alignment_is_mandatory() -> None:
    inventory = _inventory(_definition("A"), _definition("B"))
    first, second = inventory.tokens
    aligned = _opportunity(
        inventory,
        token_id=first.token_id,
        gameweek=1,
        values=(1.0, 1.0),
    )
    misaligned = _opportunity(
        inventory,
        token_id=second.token_id,
        gameweek=2,
        values=(1.0, 1.0),
        scenario_ids=(("S1", "D1", 0.4), ("S2", "D2", 0.6)),
    )

    with pytest.raises(ValidationError, match="scenario hash differs"):
        _request(inventory, aligned, misaligned)


def test_prefix_sensitive_history_does_not_alias_same_token_routes() -> None:
    inventory = _inventory(_definition("WC"), _definition("BB"))
    bb_token, wc_token = sorted(inventory.tokens, key=lambda item: item.chip_key)
    wc_plain = _opportunity(
        inventory,
        token_id=wc_token.token_id,
        gameweek=1,
        values=(6.0, 6.0),
        opportunity_id="wc-plain",
    )
    wc_prepare = _opportunity(
        inventory,
        token_id=wc_token.token_id,
        gameweek=1,
        values=(4.0, 4.0),
        opportunity_id="wc-prepare-bb",
    )
    prepared_bb = _opportunity(
        inventory,
        token_id=bb_token.token_id,
        gameweek=2,
        values=(8.0, 8.0),
        opportunity_id="bb-after-wc",
        requires=("wc-prepare-bb",),
    )
    request = _request(inventory, wc_plain, wc_prepare, prepared_bb)

    policy = optimise_chip_schedule(request)

    assert tuple(item.opportunity_id for item in policy.selected_schedule.activations) == (
        "wc-prepare-bb",
        "bb-after-wc",
    )
    assert policy.diagnostics.prefix_sensitive_memoisation is True


def test_forbidden_prefix_prevents_incompatible_route() -> None:
    inventory = _inventory(_definition("WC"), _definition("FH"))
    fh_token, wc_token = sorted(inventory.tokens, key=lambda item: item.chip_key)
    wildcard = _opportunity(
        inventory,
        token_id=wc_token.token_id,
        gameweek=1,
        values=(5.0, 5.0),
        opportunity_id="wc",
    )
    free_hit = _opportunity(
        inventory,
        token_id=fh_token.token_id,
        gameweek=2,
        values=(8.0, 8.0),
        opportunity_id="fh",
        forbids=("wc",),
    )

    policy = optimise_chip_schedule(_request(inventory, wildcard, free_hit))

    assert tuple(item.opportunity_id for item in policy.selected_schedule.activations) == ("fh",)


def test_beam_search_is_bounded_deterministic_and_reports_relaxed_upper_bound() -> None:
    inventory = _inventory(
        _definition("A"),
        _definition("B"),
        _definition("C"),
        _definition("D"),
    )
    opportunities = tuple(
        _opportunity(
            inventory,
            token_id=token.token_id,
            gameweek=gameweek,
            values=(float(gameweek + token.copy_index),) * 2,
            opportunity_id=f"{token.chip_key}-{gameweek}",
            optimistic_upper_bound=float(gameweek + 10),
        )
        for token in inventory.tokens
        for gameweek in (1, 2, 3)
    )
    objective = ScheduleObjectiveConfig(
        exact_state_threshold=2,
        beam_width=3,
        beam_branch_limit=4,
        config_version="BEAM-V1",
    )
    request = _request(inventory, *opportunities, objective=objective)

    first = optimise_chip_schedule(request)
    second = optimise_chip_schedule(request)

    assert first.diagnostics.method is ScheduleSearchMethod.BOUNDED_BEAM
    assert first.diagnostics.exact_optimality is False
    assert first.diagnostics.explored_states <= 3 * (3 + 3)
    assert first.perfect_information_upper_bound.bound_method == "RELAXED_FINITE_STATE_BOUND"
    assert first.selected_schedule.schedule_hash == second.selected_schedule.schedule_hash
    assert first.policy_hash == second.policy_hash


def test_beam_retains_use_now_delay_and_never_use_comparators() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(inventory, token_id=token.token_id, gameweek=1, values=(8.0, 8.0)),
        _opportunity(inventory, token_id=token.token_id, gameweek=3, values=(9.0, 9.0)),
        objective=ScheduleObjectiveConfig(
            exact_state_threshold=1,
            beam_width=1,
            beam_branch_limit=2,
            config_version="BEAM-COMPARATORS-V1",
        ),
    )

    policy = optimise_chip_schedule(request)

    assert policy.diagnostics.method is ScheduleSearchMethod.BOUNDED_BEAM
    assert policy.best_use_now_schedule is not None
    assert policy.best_delay_schedule is not None
    assert policy.best_never_use_schedule.activations == ()
    assert policy.best_delay_schedule.activations[0].activation_gameweek == 3


def test_estimated_state_space_switches_at_configured_threshold() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    opportunities = tuple(
        _opportunity(
            inventory,
            token_id=token.token_id,
            gameweek=gameweek,
            values=(float(gameweek),) * 2,
        )
        for gameweek in (1, 2, 3)
    )
    exact_request = _request(inventory, *opportunities)
    beam_request = _request(
        inventory,
        *opportunities,
        objective=ScheduleObjectiveConfig(
            exact_state_threshold=1,
            beam_width=2,
            config_version="SMALL-THRESHOLD",
        ),
    )

    assert estimate_state_space(exact_request) == 8
    assert estimate_state_space(beam_request) == 2
    assert (
        optimise_chip_schedule(beam_request).diagnostics.method is ScheduleSearchMethod.BOUNDED_BEAM
    )


def test_duplicate_inventory_token_is_rejected_at_scheduler_boundary() -> None:
    inventory = _inventory(_definition("TC"))
    duplicate = ChipInventory.model_construct(
        **{
            **inventory.model_dump(mode="python"),
            "tokens": (inventory.tokens[0], inventory.tokens[0]),
        }
    )
    scenarios = _scenarios()

    with pytest.raises(
        ValidationError, match=r"token IDs must be unique|duplicate inventory token"
    ):
        ChipScheduleRequest(
            request_id="DUPLICATE",
            inventory=duplicate,
            horizon_start_gameweek=1,
            horizon_end_gameweek=2,
            information_cutoff=NOW,
            scenario_universe=scenarios,
            scenario_set_hash=scenario_set_hash(scenarios),
            opportunities=(),
            objective=ScheduleObjectiveConfig(config_version="TEST-V1"),
            request_hash="0" * 64,
        )


def test_unknown_token_opportunity_is_rejected() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    opportunity = _opportunity(
        inventory,
        token_id=token.token_id,
        gameweek=1,
        values=(1.0, 1.0),
    ).model_copy(update={"token_id": "UNKNOWN", "opportunity_hash": "0" * 64})
    opportunity = seal_opportunity(opportunity)

    with pytest.raises(ValidationError, match="unknown inventory token"):
        _request(inventory, opportunity)


def test_activation_window_and_excluded_gameweeks_are_enforced() -> None:
    inventory = _inventory(
        _definition("TC", start=2, acquired=1, excluded=(3,)), current_gameweek=1
    )
    token = inventory.tokens[0]

    with pytest.raises(ValidationError, match="precedes token activation start"):
        _request(
            inventory,
            _opportunity(inventory, token_id=token.token_id, gameweek=1, values=(1.0, 1.0)),
        )
    with pytest.raises(ValidationError, match="excluded Gameweek"):
        _request(
            inventory,
            _opportunity(inventory, token_id=token.token_id, gameweek=3, values=(1.0, 1.0)),
        )


def test_tampered_request_hash_fails_closed() -> None:
    inventory = _inventory(_definition("TC"))
    request = _request(inventory)
    tampered = request.model_copy(update={"horizon_end_gameweek": 5})

    with pytest.raises(ValueError, match="request semantic hash mismatch"):
        optimise_chip_schedule(tampered)


def test_tampered_opportunity_hash_fails_closed() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    opportunity = _opportunity(
        inventory,
        token_id=token.token_id,
        gameweek=1,
        values=(2.0, 2.0),
    )
    request = _request(inventory, opportunity)
    tampered_opportunity = opportunity.model_copy(update={"expected_net_policy_value": 99.0})
    tampered_request = request.model_copy(
        update={"opportunities": (tampered_opportunity,), "request_hash": "0" * 64}
    )
    from dmf_pulse.chips.definitions import semantic_sha256

    payload = tampered_request.model_dump(mode="json", exclude={"request_hash"})
    tampered_request = tampered_request.model_copy(
        update={"request_hash": semantic_sha256(payload)}
    )

    with pytest.raises(ValueError, match="opportunity semantic hash mismatch"):
        optimise_chip_schedule(tampered_request)


def test_tampered_inventory_hash_fails_closed() -> None:
    inventory = _inventory(_definition("TC"))
    request = _request(inventory)
    tampered_inventory = inventory.model_copy(update={"bundle_hash": "9" * 64})
    tampered_request = request.model_copy(update={"inventory": tampered_inventory})
    payload = tampered_request.model_dump(mode="json", exclude={"request_hash"})
    from dmf_pulse.chips.definitions import semantic_sha256

    tampered_request = tampered_request.model_copy(
        update={"request_hash": semantic_sha256(payload)}
    )

    with pytest.raises(ValueError, match="inventory semantic hash mismatch"):
        optimise_chip_schedule(tampered_request)


def test_value_decomposition_remains_distinct_in_public_policy() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(
            inventory,
            token_id=token.token_id,
            gameweek=1,
            values=(10.0, 10.0),
            continuation=(3.0, 3.0),
            costs=(2.0, 2.0),
        ),
    )

    policy = optimise_chip_schedule(request)

    assert policy.gross_current_gain == 10.0
    assert policy.selected_schedule.expected_continuation_value == 3.0
    assert policy.selected_schedule.expected_policy_cost == 2.0
    assert policy.selected_schedule.expected_net_policy_value == 11.0
    assert policy.net_policy_value == 11.0
    assert policy.opportunity_cost == 0.0


def test_active_inventory_interval_blocks_overlapping_schedule() -> None:
    inventory = _inventory(
        _definition("MULTI", duration=2),
        _definition("TC"),
        concurrency_limit=1,
    )
    active, candidate = inventory.tokens
    active = active.model_copy(
        update={
            "status": TokenStatus.ACTIVE,
            "active_from_gameweek": 1,
            "active_until_gameweek": 2,
            "selected_at_gameweek": 1,
        }
    )
    inventory = inventory.model_copy(update={"tokens": (active, candidate)})
    # Re-seal the intentionally constructed current inventory state.
    from dmf_pulse.chips.definitions import semantic_sha256

    inventory = inventory.model_copy(
        update={
            "inventory_hash": semantic_sha256(
                inventory.model_dump(mode="json", exclude={"inventory_hash"})
            )
        }
    )
    request = _request(
        inventory,
        _opportunity(
            inventory,
            token_id=candidate.token_id,
            gameweek=2,
            values=(9.0, 9.0),
        ),
    )

    assert optimise_chip_schedule(request).selected_schedule.activations == ()


def test_schedule_result_is_semantically_stable() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(inventory, token_id=token.token_id, gameweek=2, values=(4.0, 4.0)),
    )

    first = optimise_chip_schedule(request)
    second = optimise_chip_schedule(request)

    assert first == second
    assert first.policy_hash == second.policy_hash


def test_invalid_prefix_reference_is_rejected() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    opportunity = _opportunity(
        inventory,
        token_id=token.token_id,
        gameweek=2,
        values=(1.0, 1.0),
        requires=("missing",),
    )

    with pytest.raises(ValidationError, match="required prior opportunity does not exist"):
        _request(inventory, opportunity)


def test_opportunity_optimistic_bound_cannot_understate_declared_value() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]

    with pytest.raises(ValidationError, match="optimistic upper bound"):
        _opportunity(
            inventory,
            token_id=token.token_id,
            gameweek=1,
            values=(5.0, 5.0),
            optimistic_upper_bound=4.0,
        )


def test_no_opportunity_request_still_returns_legal_finite_inventory_policy() -> None:
    inventory = _inventory(_definition("TC", end=10))
    request = _request(inventory, horizon_end=3)

    policy = optimise_chip_schedule(request)

    assert policy.selected_schedule.activations == ()
    assert policy.best_never_use_schedule == policy.selected_schedule
    assert policy.diagnostics.feasible_schedules == 1


def test_policy_model_rejects_inconsistent_selected_root_identity() -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    policy = optimise_chip_schedule(
        _request(
            inventory,
            _opportunity(
                inventory,
                token_id=token.token_id,
                gameweek=1,
                values=(5.0, 5.0),
            ),
        )
    )
    payload: dict[str, Any] = policy.model_dump(mode="python")
    payload["selected_token_ids"] = ("WRONG",)

    with pytest.raises(ValidationError, match="identities do not reconcile"):
        type(policy).model_validate(payload)


def _policy_fixture() -> tuple[ChipScheduleRequest, ChipSchedulePolicy]:
    inventory = _inventory(_definition("A", end=10), _definition("B", end=10))
    first, second = inventory.tokens
    request = _request(
        inventory,
        _opportunity(
            inventory,
            token_id=first.token_id,
            gameweek=1,
            values=(5.0, 3.0),
            continuation=(1.0, 1.0),
        ),
        _opportunity(
            inventory,
            token_id=second.token_id,
            gameweek=2,
            values=(4.0, 4.0),
        ),
        horizon_end=3,
    )
    return request, optimise_chip_schedule(request)


@pytest.mark.parametrize(
    ("value", "match"),
    [
        (datetime(2026, 8, 18, 18), "timezone-aware UTC"),
        (datetime(2026, 8, 18, 18, tzinfo=timezone(timedelta(hours=1))), "must use UTC"),
    ],
)
def test_utc_contract_rejects_ambiguous_timestamps(value: datetime, match: str) -> None:
    from dmf_pulse.chips.schedule_models import require_utc

    with pytest.raises(ValueError, match=match):
        require_utc(value, field_name="cutoff")


def test_scenario_value_decomposition_fails_closed() -> None:
    with pytest.raises(ValidationError, match="net policy value"):
        ScheduleScenarioValue(
            scenario_id="S1",
            outcome_draw_id="D1",
            weight=1.0,
            gross_current_gain=1.0,
            continuation_value=2.0,
            policy_cost=0.0,
            net_policy_value=99.0,
        )


@pytest.mark.parametrize(
    ("updates", "match"),
    [
        ({"information_cutoff": NOW + timedelta(seconds=1)}, "information cutoff"),
        ({"usable_at": NOW + timedelta(seconds=1)}, "usable after"),
        ({"decision_cutoff": NOW - timedelta(seconds=1)}, "decision cutoff"),
    ],
)
def test_opportunity_lineage_rejects_impossible_time_order(
    updates: dict[str, datetime], match: str
) -> None:
    payload: dict[str, Any] = {
        "forecast_origin": NOW,
        "information_cutoff": NOW,
        "usable_at": NOW,
        "decision_cutoff": NOW,
        "source_kind": OpportunitySourceKind.FORECAST,
        "source_artifact_hash": SOURCE_HASH,
        "scenario_set_hash": "4" * 64,
        "model_version": "TEST",
        "configuration_hash": CONFIG_HASH,
        "code_commit": "abcdef0",
    }
    payload.update(updates)
    with pytest.raises(ValidationError, match=match):
        OpportunityLineage.model_validate(payload)


def _opportunity_payload() -> dict[str, Any]:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    return _opportunity(
        inventory,
        token_id=token.token_id,
        gameweek=1,
        values=(2.0, 2.0),
    ).model_dump(mode="python")


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"scenario_values": ()}, "non-empty and sorted"),
        ({"requires_prior_opportunity_ids": ("z", "a")}, "required prior.*sorted"),
        ({"forbids_prior_opportunity_ids": ("z", "a")}, "forbidden prior.*sorted"),
        ({"requires_prior_opportunity_ids": ("a", "a")}, "prefix constraints.*unique"),
        (
            {
                "requires_prior_opportunity_ids": ("a",),
                "forbids_prior_opportunity_ids": ("a",),
            },
            "both require and forbid",
        ),
        ({"requires_prior_opportunity_ids": ("tc-1-1",)}, "depend on itself"),
        ({"expected_gross_current_gain": 99.0}, "expected gross current gain"),
        ({"opportunity_hash": "9" * 64}, "opportunity hash mismatch"),
    ],
)
def test_opportunity_contract_rejects_incoherent_payloads(
    mutation: dict[str, Any], match: str
) -> None:
    payload = _opportunity_payload()
    payload.update(mutation)
    if "opportunity_hash" not in mutation:
        payload["opportunity_hash"] = "0" * 64
    with pytest.raises(ValidationError, match=match):
        ChipScheduleOpportunity.model_validate(payload)


def test_opportunity_contract_rejects_duplicate_and_misaligned_scenarios() -> None:
    payload = _opportunity_payload()
    first, second = payload["scenario_values"]
    duplicate = dict(first)
    duplicate["weight"] = 0.5
    payload["scenario_values"] = (duplicate, duplicate)
    payload["opportunity_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="identities must be unique"):
        ChipScheduleOpportunity.model_validate(payload)

    payload = _opportunity_payload()
    first, second = payload["scenario_values"]
    payload["scenario_values"] = (second, first)
    payload["opportunity_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="non-empty and sorted"):
        ChipScheduleOpportunity.model_validate(payload)

    payload = _opportunity_payload()
    payload["scenario_values"] = tuple(
        {**item, "weight": 0.4} for item in payload["scenario_values"]
    )
    payload["opportunity_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="weights must sum to one"):
        ChipScheduleOpportunity.model_validate(payload)


def _request_payload() -> tuple[ChipScheduleRequest, dict[str, Any]]:
    inventory = _inventory(_definition("TC", end=10))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(inventory, token_id=token.token_id, gameweek=1, values=(2.0, 2.0)),
        _opportunity(inventory, token_id=token.token_id, gameweek=2, values=(3.0, 3.0)),
        horizon_end=3,
    )
    payload = request.model_dump(mode="python")
    payload["request_hash"] = "0" * 64
    return request, payload


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"horizon_start_gameweek": 2}, "horizon must begin"),
        ({"horizon_end_gameweek": 0}, "greater than 0|horizon is inverted"),
        ({"scenario_universe": ()}, "non-empty and sorted"),
        ({"scenario_set_hash": "9" * 64}, "scenario-set hash mismatch"),
    ],
)
def test_request_contract_rejects_invalid_top_level_state(
    mutation: dict[str, Any], match: str
) -> None:
    _, payload = _request_payload()
    payload.update(mutation)
    with pytest.raises(ValidationError, match=match):
        ChipScheduleRequest.model_validate(payload)


def test_request_contract_rejects_scenario_and_opportunity_ordering_defects() -> None:
    _, payload = _request_payload()
    payload["scenario_universe"] = tuple(reversed(payload["scenario_universe"]))
    payload["scenario_set_hash"] = scenario_set_hash(
        tuple(
            ScheduleScenarioIdentity.model_validate(item) for item in payload["scenario_universe"]
        )
    )
    with pytest.raises(ValidationError, match="non-empty and sorted"):
        ChipScheduleRequest.model_validate(payload)

    _, payload = _request_payload()
    first, _ = payload["scenario_universe"]
    payload["scenario_universe"] = (first, first)
    payload["scenario_set_hash"] = scenario_set_hash(
        tuple(
            ScheduleScenarioIdentity.model_validate(item) for item in payload["scenario_universe"]
        )
    )
    with pytest.raises(ValidationError, match="universe must be unique"):
        ChipScheduleRequest.model_validate(payload)

    _, payload = _request_payload()
    payload["opportunities"] = tuple(reversed(payload["opportunities"]))
    with pytest.raises(ValidationError, match="opportunities must be sorted"):
        ChipScheduleRequest.model_validate(payload)

    _, payload = _request_payload()
    first = payload["opportunities"][0]
    payload["opportunities"] = (first, first)
    with pytest.raises(ValidationError, match="opportunity IDs must be unique"):
        ChipScheduleRequest.model_validate(payload)


def _reseal_inventory(inventory: ChipInventory, tokens: tuple[Any, ...]) -> ChipInventory:
    value = inventory.model_copy(update={"tokens": tokens})
    return value.model_copy(
        update={
            "inventory_hash": semantic_sha256(
                value.model_dump(mode="json", exclude={"inventory_hash"})
            )
        }
    )


def test_request_contract_rejects_token_and_horizon_mismatches() -> None:
    request, payload = _request_payload()
    opportunity = request.opportunities[0]

    changed = seal_opportunity(
        opportunity.model_copy(update={"chip_key": "WRONG", "opportunity_hash": "0" * 64})
    )
    payload["opportunities"] = (changed, request.opportunities[1])
    with pytest.raises(ValidationError, match="chip key differs"):
        ChipScheduleRequest.model_validate(payload)

    request, payload = _request_payload()
    changed = seal_opportunity(
        request.opportunities[0].model_copy(
            update={"duration_gameweeks": 2, "opportunity_hash": "0" * 64}
        )
    )
    payload["opportunities"] = (changed, request.opportunities[1])
    with pytest.raises(ValidationError, match="duration differs"):
        ChipScheduleRequest.model_validate(payload)

    request, payload = _request_payload()
    payload["horizon_end_gameweek"] = 1
    with pytest.raises(ValidationError, match="outside the request horizon"):
        ChipScheduleRequest.model_validate(payload)

    request, payload = _request_payload()
    token = request.inventory.tokens[0].model_copy(
        update={"status": TokenStatus.USED, "used_at_gameweek": 1}
    )
    payload["inventory"] = _reseal_inventory(request.inventory, (token,))
    with pytest.raises(ValidationError, match="consumed or already-active"):
        ChipScheduleRequest.model_validate(payload)


def test_request_contract_rejects_future_origin_and_scenario_misalignment() -> None:
    request, payload = _request_payload()
    opportunity = request.opportunities[0]
    lineage = opportunity.lineage.model_copy(
        update={
            "forecast_origin": NOW + timedelta(seconds=1),
            "decision_cutoff": NOW + timedelta(seconds=1),
        }
    )
    changed = seal_opportunity(
        opportunity.model_copy(update={"lineage": lineage, "opportunity_hash": "0" * 64})
    )
    payload["opportunities"] = (changed, request.opportunities[1])
    with pytest.raises(ValidationError, match="forecast is post-cutoff"):
        ChipScheduleRequest.model_validate(payload)

    request, payload = _request_payload()
    opportunity = request.opportunities[0]
    values = tuple(
        item.model_copy(update={"weight": weight})
        for item, weight in zip(opportunity.scenario_values, (0.4, 0.6), strict=True)
    )
    changed_payload = opportunity.model_dump(mode="python")
    changed_payload.update(
        {
            "scenario_values": values,
            "expected_gross_current_gain": sum(i.weight * i.gross_current_gain for i in values),
            "expected_continuation_value": sum(i.weight * i.continuation_value for i in values),
            "expected_policy_cost": sum(i.weight * i.policy_cost for i in values),
            "expected_net_policy_value": sum(i.weight * i.net_policy_value for i in values),
            "expected_cash_like_value": sum(i.weight * i.cash_like_value for i in values),
            "expected_terminal_state_value": sum(i.weight * i.terminal_state_value for i in values),
            "opportunity_hash": "0" * 64,
        }
    )
    changed = seal_opportunity(ChipScheduleOpportunity.model_validate(changed_payload))
    payload["opportunities"] = (changed, request.opportunities[1])
    with pytest.raises(ValidationError, match="not aligned on common scenarios"):
        ChipScheduleRequest.model_validate(payload)


def test_request_contract_rejects_prefix_and_terminal_value_defects() -> None:
    inventory = _inventory(_definition("A"), _definition("B"), current_gameweek=1)
    a, b = inventory.tokens
    first = _opportunity(
        inventory, token_id=a.token_id, gameweek=1, values=(1.0, 1.0), opportunity_id="first"
    )
    same_time_required = _opportunity(
        inventory,
        token_id=b.token_id,
        gameweek=1,
        values=(2.0, 2.0),
        opportunity_id="second",
        requires=("first",),
    )
    with pytest.raises(ValidationError, match="must occur in an earlier Gameweek"):
        _request(inventory, first, same_time_required)

    request = _request(inventory, first, horizon_end=3)
    payload = request.model_dump(mode="python")
    payload.update(
        {
            "terminal_token_values": (
                TerminalTokenValue(token_id=b.token_id),
                TerminalTokenValue(token_id=a.token_id),
            ),
            "request_hash": "0" * 64,
        }
    )
    with pytest.raises(ValidationError, match="sorted by token ID"):
        ChipScheduleRequest.model_validate(payload)

    payload["terminal_token_values"] = (
        TerminalTokenValue(token_id=a.token_id),
        TerminalTokenValue(token_id=a.token_id),
    )
    with pytest.raises(ValidationError, match="unique by token ID"):
        ChipScheduleRequest.model_validate(payload)

    payload["terminal_token_values"] = (TerminalTokenValue(token_id="UNKNOWN"),)
    with pytest.raises(ValidationError, match="unknown inventory token"):
        ChipScheduleRequest.model_validate(payload)


def test_scenario_outcome_and_perfect_information_contracts_fail_closed() -> None:
    outcome = ScheduleScenarioOutcome(
        scenario_id="S1",
        outcome_draw_id="D1",
        weight=1.0,
        gross_current_gain=2.0,
        continuation_value=1.0,
        policy_cost=1.0,
        net_policy_value=2.0,
        cash_like_value=0.0,
        terminal_state_value=3.0,
        expected_mode_value=5.0,
    )
    payload = outcome.model_dump(mode="python")
    payload["net_policy_value"] = 99.0
    with pytest.raises(ValidationError, match="decomposition"):
        ScheduleScenarioOutcome.model_validate(payload)
    payload = outcome.model_dump(mode="python")
    payload["expected_mode_value"] = 99.0
    with pytest.raises(ValidationError, match="expected-mode"):
        ScheduleScenarioOutcome.model_validate(payload)

    with pytest.raises(ValidationError, match="upper-bound gap"):
        PerfectInformationUpperBound(
            expected_upper_bound=5.0,
            executable_expected_objective=2.0,
            upper_bound_gap=1.0,
            scenario_best_schedule_ids=("schedule",),
            bound_method="EXACT_SCENARIO_ORACLE",
            exact_search=True,
        )


def test_schedule_candidate_contract_rejects_tampered_public_state() -> None:
    _, policy = _policy_fixture()
    candidate = policy.selected_schedule

    def reject(update: dict[str, Any], match: str) -> None:
        payload = candidate.model_dump(mode="python")
        payload.update(update)
        payload["schedule_hash"] = "0" * 64
        with pytest.raises(ValidationError, match=match):
            ChipScheduleCandidate.model_validate(payload)

    reject({"activations": tuple(reversed(candidate.activations))}, "activations must be sorted")
    if candidate.activations:
        reject(
            {"activations": (candidate.activations[0], candidate.activations[0])},
            "cannot be scheduled more than once",
        )
    reject({"scenario_outcomes": ()}, "non-empty and sorted")
    reject({"expected_net_policy_value": 99.0}, "expected net policy value")
    reject({"current_opportunity_ids": ("z", "a")}, "current opportunity IDs must be sorted")
    reject(
        {"current_action": RootScheduleAction.ACTIVATE, "current_opportunity_ids": ()},
        "ACTIVATE requires",
    )
    reject(
        {"current_action": RootScheduleAction.HOLD, "current_opportunity_ids": ("x",)},
        "non-activation root action",
    )
    reject({"selected_objective": 99.0}, "selected objective differs")

    payload = candidate.model_dump(mode="python")
    payload["schedule_hash"] = "9" * 64
    with pytest.raises(ValidationError, match="schedule hash mismatch"):
        ChipScheduleCandidate.model_validate(payload)


def test_policy_contract_rejects_tampered_comparators_and_lineage() -> None:
    _, policy = _policy_fixture()

    def reject(update: dict[str, Any], match: str) -> None:
        payload = policy.model_dump(mode="python")
        payload.update(update)
        payload["policy_hash"] = "0" * 64
        with pytest.raises(ValidationError, match=match):
            ChipSchedulePolicy.model_validate(payload)

    reject({"alternatives": ()}, "alternatives must be non-empty")
    reject(
        {"alternatives": (policy.best_never_use_schedule,)}, "selected schedule must be retained"
    )
    reject({"recommended_action": RootScheduleAction.EXPIRE_UNUSED}, "root action differs")
    reject({"selected_chip_keys": ("Z", "A")}, "chip keys must be sorted")
    reject({"selected_token_ids": ("Z", "A")}, "token IDs must be sorted")
    reject({"net_policy_value": 99.0}, "relative to the never-use baseline")
    reject({"exercise_advantage": 99.0}, "exercise advantage")

    payload = policy.model_dump(mode="python")
    payload["policy_hash"] = "9" * 64
    with pytest.raises(ValidationError, match="policy hash mismatch"):
        ChipSchedulePolicy.model_validate(payload)


def _with_inventory_tokens(
    inventory: ChipInventory,
    tokens: tuple[Any, ...],
) -> ChipInventory:
    value = ChipInventory.model_construct(
        ruleset_id=inventory.ruleset_id,
        ruleset_version=inventory.ruleset_version,
        ruleset_hash=inventory.ruleset_hash,
        bundle_hash=inventory.bundle_hash,
        current_gameweek=inventory.current_gameweek,
        concurrency_limit=inventory.concurrency_limit,
        tokens=tokens,
        inventory_hash="0" * 64,
    )
    return value.model_copy(
        update={
            "inventory_hash": semantic_sha256(
                value.model_dump(mode="json", exclude={"inventory_hash"})
            )
        }
    )


def _with_request_inventory(
    request: ChipScheduleRequest,
    inventory: ChipInventory,
) -> ChipScheduleRequest:
    value = request.model_copy(update={"inventory": inventory, "request_hash": "0" * 64})
    return value.model_copy(
        update={
            "request_hash": semantic_sha256(value.model_dump(mode="json", exclude={"request_hash"}))
        }
    )


def test_scheduler_fails_closed_on_malformed_active_interval() -> None:
    inventory = _inventory(_definition("MULTI", duration=2))
    token = inventory.tokens[0]
    malformed = token.model_copy(
        update={
            "status": TokenStatus.ACTIVE,
            "active_from_gameweek": None,
            "active_until_gameweek": None,
        }
    )
    malformed_inventory = _with_inventory_tokens(inventory, (malformed,))
    request = _with_request_inventory(_request(inventory), malformed_inventory)

    with pytest.raises(ValueError, match="lacks an occupied interval"):
        optimise_chip_schedule(request)


def test_used_copy_minimum_gap_blocks_a_new_copy() -> None:
    inventory = _inventory(
        _definition("BOOST", copies=2, minimum_gap=1),
        current_gameweek=2,
    )
    first, second = inventory.tokens
    used = first.model_copy(update={"status": TokenStatus.USED, "used_at_gameweek": 1})
    inventory = _with_inventory_tokens(inventory, (used, second))
    request = _request(
        inventory,
        _opportunity(
            inventory,
            token_id=second.token_id,
            gameweek=2,
            values=(8.0, 8.0),
        ),
    )

    assert optimise_chip_schedule(request).selected_schedule.activations == ()


def test_concurrency_is_checked_per_gameweek_not_by_interval_union() -> None:
    inventory = _inventory(
        _definition("A", duration=1, group="A"),
        _definition("B", duration=1, group="B"),
        _definition("C", duration=3, group="C"),
        concurrency_limit=2,
    )
    by_chip = {token.chip_key: token for token in inventory.tokens}
    request = _request(
        inventory,
        _opportunity(
            inventory,
            token_id=by_chip["A"].token_id,
            gameweek=1,
            values=(3.0, 3.0),
        ),
        _opportunity(
            inventory,
            token_id=by_chip["B"].token_id,
            gameweek=3,
            values=(3.0, 3.0),
        ),
        _opportunity(
            inventory,
            token_id=by_chip["C"].token_id,
            gameweek=1,
            values=(4.0, 4.0),
        ),
        horizon_end=3,
    )

    policy = optimise_chip_schedule(request)

    assert {item.chip_key for item in policy.selected_schedule.activations} == {"A", "B", "C"}


def test_concurrency_rejects_a_third_overlapping_group() -> None:
    inventory = _inventory(
        _definition("A", duration=2, group="A"),
        _definition("B", duration=2, group="B"),
        _definition("C", duration=1, group="C"),
        concurrency_limit=2,
    )
    by_chip = {token.chip_key: token for token in inventory.tokens}
    request = _request(
        inventory,
        _opportunity(
            inventory,
            token_id=by_chip["A"].token_id,
            gameweek=1,
            values=(5.0, 5.0),
        ),
        _opportunity(
            inventory,
            token_id=by_chip["B"].token_id,
            gameweek=1,
            values=(5.0, 5.0),
        ),
        _opportunity(
            inventory,
            token_id=by_chip["C"].token_id,
            gameweek=2,
            values=(4.0, 4.0),
        ),
    )

    assert len(optimise_chip_schedule(request).selected_schedule.activations) == 2


@pytest.mark.parametrize(
    "objective_mode",
    [ScheduleObjectiveMode.ROBUST, ScheduleObjectiveMode.CASH_TERMINAL],
)
def test_beam_exercises_each_nondefault_objective_mode(
    objective_mode: ScheduleObjectiveMode,
) -> None:
    inventory = _inventory(_definition("TC", end=10))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(
            inventory,
            token_id=token.token_id,
            gameweek=1,
            values=(3.0, 3.0),
            cash=(2.0, 2.0),
            robust_penalty=1.0,
        ),
        horizon_end=3,
        terminal_values=(
            TerminalTokenValue(
                token_id=token.token_id,
                expected_terminal_value=1.0,
                cash_like_value=1.0,
            ),
        ),
        objective=ScheduleObjectiveConfig(
            objective_mode=objective_mode,
            exact_state_threshold=1,
            beam_width=2,
            max_returned_alternatives=1,
            config_version=f"BEAM-{objective_mode.value}",
        ),
    )

    policy = optimise_chip_schedule(request)

    assert policy.diagnostics.method is ScheduleSearchMethod.BOUNDED_BEAM
    assert policy.selected_schedule.objective_mode is objective_mode
    assert policy.best_never_use_schedule in policy.alternatives


def test_beam_reports_used_and_expired_inventory_dispositions() -> None:
    inventory = _inventory(
        _definition("A"),
        _definition("B"),
        _definition("C", end=10),
    )
    first, second, third = inventory.tokens
    used = first.model_copy(update={"status": TokenStatus.USED, "used_at_gameweek": 1})
    expired = second.model_copy(update={"status": TokenStatus.EXPIRED})
    inventory = _with_inventory_tokens(inventory, (used, expired, third))
    request = _request(
        inventory,
        _opportunity(
            inventory,
            token_id=third.token_id,
            gameweek=1,
            values=(2.0, 2.0),
        ),
        objective=ScheduleObjectiveConfig(
            exact_state_threshold=1,
            beam_width=2,
            config_version="BEAM-DISPOSITIONS",
        ),
    )

    dispositions = optimise_chip_schedule(request).selected_schedule.token_dispositions

    assert {item.disposition.value for item in dispositions} >= {
        "ALREADY_USED",
        "ALREADY_EXPIRED",
    }


def test_exact_oracle_enforces_its_independent_safety_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = _inventory(_definition("TC"))
    request = _request(inventory)
    monkeypatch.setattr(
        "dmf_pulse.chips.scheduler.estimate_state_space",
        lambda _request: 2_000_001,
    )

    with pytest.raises(ValueError, match="safety ceiling"):
        exact_small_schedule_oracle(request)


def test_exact_oracle_does_not_call_production_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    request = _request(
        inventory,
        _opportunity(
            inventory,
            token_id=token.token_id,
            gameweek=1,
            values=(5.0, 4.0),
        ),
    )
    monkeypatch.setattr(
        "dmf_pulse.chips.scheduler._exact_search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("production exact search must not be called")
        ),
    )

    policy = exact_small_schedule_oracle(request)

    assert policy.selected_schedule.activations[0].token_id == token.token_id
