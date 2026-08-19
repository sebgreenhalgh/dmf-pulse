from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.chips.compiler import compile_synthetic_bundle
from dmf_pulse.chips.definitions import ActivationRoute, ChipDefinition, ChipEffect, InventoryGrant
from dmf_pulse.chips.inventory import ChipInventory, build_chip_inventory
from dmf_pulse.chips.schedule_models import (
    ChipScheduleOpportunity,
    ChipScheduleRequest,
    OpportunityLineage,
    OpportunitySourceKind,
    ScheduleObjectiveConfig,
    ScheduleScenarioIdentity,
    ScheduleScenarioValue,
    scenario_set_hash,
    seal_opportunity,
    seal_schedule_request,
)
from dmf_pulse.chips.scheduler import exact_small_schedule_oracle, optimise_chip_schedule

NOW = datetime(2026, 8, 18, 18, tzinfo=UTC)
RULESET_HASH = "1" * 64
SOURCE_HASH = "2" * 64
CONFIG_HASH = "3" * 64
SCENARIOS = (
    ScheduleScenarioIdentity(scenario_id="S1", outcome_draw_id="D1", weight=0.5),
    ScheduleScenarioIdentity(scenario_id="S2", outcome_draw_id="D2", weight=0.5),
)


def _definition(key: str, *, duration: int = 1, group: str = "CHIP") -> ChipDefinition:
    return ChipDefinition(
        chip_key=key,
        definition_version=f"SYNTHETIC:{key}:V1",
        grants=(
            InventoryGrant(
                grant_id="window",
                copies=1,
                acquired_gameweek=1,
                activation_start_gameweek=1,
                activation_end_gameweek=4,
                expires_after_gameweek=4,
            ),
        ),
        duration_gameweeks=duration,
        concurrency_group=group,
        activation_route=ActivationRoute.PICK_TEAM_SAVE,
        cancellable_before_lock=True,
        effects=(ChipEffect(surface="SCORING", operation="ADD_POINTS", parameters={"points": 1}),),
    )


def _inventory(*definitions: ChipDefinition, concurrency_limit: int = 1) -> ChipInventory:
    bundle = compile_synthetic_bundle(
        ruleset_id="SYNTHETIC-SCHEDULE-PROPERTIES",
        ruleset_version="1.0",
        ruleset_hash=RULESET_HASH,
        concurrency_limit=concurrency_limit,
        definitions=definitions,
    )
    return build_chip_inventory(bundle, current_gameweek=1)


def _opportunity(
    inventory: ChipInventory,
    *,
    token_id: str,
    gameweek: int,
    values: tuple[float, float],
) -> ChipScheduleOpportunity:
    token = inventory.token(token_id)
    scenario_values = tuple(
        ScheduleScenarioValue(
            scenario_id=scenario.scenario_id,
            outcome_draw_id=scenario.outcome_draw_id,
            weight=scenario.weight,
            gross_current_gain=value,
            continuation_value=0.0,
            policy_cost=0.0,
            net_policy_value=value,
            cash_like_value=0.0,
            terminal_state_value=0.0,
        )
        for scenario, value in zip(SCENARIOS, values, strict=True)
    )
    identifier = f"{token.chip_key.lower()}-{gameweek}"
    expected = sum(item.weight * item.net_policy_value for item in scenario_values)
    value = ChipScheduleOpportunity(
        opportunity_id=identifier,
        candidate_history_key=f"history:{identifier}",
        token_id=token_id,
        chip_key=token.chip_key,
        activation_gameweek=gameweek,
        duration_gameweeks=token.duration_gameweeks,
        scenario_values=scenario_values,
        expected_gross_current_gain=expected,
        expected_continuation_value=0.0,
        expected_policy_cost=0.0,
        expected_net_policy_value=expected,
        expected_cash_like_value=0.0,
        expected_terminal_state_value=0.0,
        optimistic_upper_bound=max(values),
        lineage=OpportunityLineage(
            forecast_origin=NOW,
            information_cutoff=NOW,
            usable_at=NOW,
            decision_cutoff=NOW + timedelta(days=(gameweek - 1) * 7),
            source_kind=OpportunitySourceKind.FORECAST,
            source_artifact_hash=SOURCE_HASH,
            scenario_set_hash=scenario_set_hash(SCENARIOS),
            model_version="PROPERTY-V1",
            configuration_hash=CONFIG_HASH,
            code_commit="abcdef0",
        ),
        opportunity_hash="0" * 64,
    )
    return seal_opportunity(value)


def _request(
    inventory: ChipInventory,
    opportunities: tuple[ChipScheduleOpportunity, ...],
    *,
    exact_threshold: int = 100_000,
    beam_width: int = 8,
) -> ChipScheduleRequest:
    ordered = tuple(
        sorted(
            opportunities,
            key=lambda item: (
                item.activation_gameweek,
                item.chip_key,
                item.token_id,
                item.opportunity_id,
            ),
        )
    )
    value = ChipScheduleRequest(
        request_id="PROPERTY-REQUEST",
        inventory=inventory,
        horizon_start_gameweek=1,
        horizon_end_gameweek=4,
        information_cutoff=NOW,
        scenario_universe=SCENARIOS,
        scenario_set_hash=scenario_set_hash(SCENARIOS),
        opportunities=ordered,
        objective=ScheduleObjectiveConfig(
            exact_state_threshold=exact_threshold,
            beam_width=beam_width,
            beam_branch_limit=8,
            config_version="PROPERTY-V1",
        ),
        request_hash="0" * 64,
    )
    return seal_schedule_request(value)


@settings(max_examples=60, deadline=None)
@given(
    first=st.lists(st.integers(min_value=-5, max_value=15), min_size=1, max_size=4),
    second=st.lists(st.integers(min_value=-5, max_value=15), min_size=1, max_size=4),
)
def test_one_finite_token_matches_closed_form_best_single_use(
    first: list[int], second: list[int]
) -> None:
    count = min(len(first), len(second))
    inventory = _inventory(_definition("TC"))
    token = inventory.tokens[0]
    opportunities = tuple(
        _opportunity(
            inventory,
            token_id=token.token_id,
            gameweek=index + 1,
            values=(float(first[index]), float(second[index])),
        )
        for index in range(count)
    )

    policy = optimise_chip_schedule(_request(inventory, opportunities))

    expected_values = [0.0, *((first[index] + second[index]) / 2 for index in range(count))]
    assert policy.selected_schedule.selected_objective == max(expected_values)
    assert len(policy.selected_schedule.activations) <= 1


@settings(max_examples=50, deadline=None)
@given(
    values=st.lists(
        st.tuples(
            st.integers(min_value=-3, max_value=12),
            st.integers(min_value=-3, max_value=12),
        ),
        min_size=6,
        max_size=6,
    )
)
def test_exact_scheduler_matches_forced_exhaustive_oracle(
    values: list[tuple[int, int]],
) -> None:
    inventory = _inventory(_definition("A"), _definition("B"))
    opportunities: list[ChipScheduleOpportunity] = []
    for token_index, token in enumerate(inventory.tokens):
        for gameweek in range(1, 4):
            left, right = values[token_index * 3 + gameweek - 1]
            opportunities.append(
                _opportunity(
                    inventory,
                    token_id=token.token_id,
                    gameweek=gameweek,
                    values=(float(left), float(right)),
                )
            )
    request = _request(inventory, tuple(opportunities))

    policy = optimise_chip_schedule(request)
    oracle = exact_small_schedule_oracle(request)

    assert policy.selected_schedule.schedule_hash == oracle.selected_schedule.schedule_hash
    assert (
        policy.selected_schedule.selected_objective == oracle.selected_schedule.selected_objective
    )


@settings(max_examples=40, deadline=None)
@given(
    values=st.lists(
        st.tuples(
            st.integers(min_value=-2, max_value=20),
            st.integers(min_value=-2, max_value=20),
        ),
        min_size=8,
        max_size=8,
    )
)
def test_beam_search_is_reproducible_and_preserves_never_use_baseline(
    values: list[tuple[int, int]],
) -> None:
    inventory = _inventory(
        _definition("A"),
        _definition("B"),
        _definition("C"),
        _definition("D"),
    )
    opportunities: list[ChipScheduleOpportunity] = []
    for token_index, token in enumerate(inventory.tokens):
        for gameweek in (1, 2):
            left, right = values[token_index * 2 + gameweek - 1]
            opportunities.append(
                _opportunity(
                    inventory,
                    token_id=token.token_id,
                    gameweek=gameweek,
                    values=(float(left), float(right)),
                )
            )
    request = _request(
        inventory,
        tuple(opportunities),
        exact_threshold=1,
        beam_width=3,
    )

    first = optimise_chip_schedule(request)
    second = optimise_chip_schedule(request)

    assert first.policy_hash == second.policy_hash
    assert not first.best_never_use_schedule.activations
    assert first.perfect_information_upper_bound.expected_upper_bound >= (
        first.selected_schedule.selected_objective
    )


@settings(max_examples=40, deadline=None)
@given(
    duration_a=st.integers(min_value=1, max_value=3),
    duration_b=st.integers(min_value=1, max_value=3),
    gameweek_a=st.integers(min_value=1, max_value=4),
    gameweek_b=st.integers(min_value=1, max_value=4),
)
def test_selected_occupancies_never_overlap_with_single_concurrency_group(
    duration_a: int,
    duration_b: int,
    gameweek_a: int,
    gameweek_b: int,
) -> None:
    inventory = _inventory(
        _definition("A", duration=duration_a, group="SQUAD"),
        _definition("B", duration=duration_b, group="SQUAD"),
    )
    first, second = inventory.tokens
    request = _request(
        inventory,
        (
            _opportunity(
                inventory,
                token_id=first.token_id,
                gameweek=gameweek_a,
                values=(8.0, 8.0),
            ),
            _opportunity(
                inventory,
                token_id=second.token_id,
                gameweek=gameweek_b,
                values=(7.0, 7.0),
            ),
        ),
    )

    policy = optimise_chip_schedule(request)
    activations = policy.selected_schedule.activations

    for left_index, left in enumerate(activations):
        for right in activations[left_index + 1 :]:
            assert left.active_until_gameweek < right.activation_gameweek or (
                right.active_until_gameweek < left.activation_gameweek
            )
