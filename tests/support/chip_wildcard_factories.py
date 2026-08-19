"""Deterministic Wildcard policy fixtures shared by Stage-14 tests."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from dmf_pulse.chips.compiler import compile_synthetic_bundle
from dmf_pulse.chips.definitions import (
    ActivationRoute,
    ChipDefinition,
    ChipEffect,
    InventoryGrant,
)
from dmf_pulse.chips.free_hit import make_policy_candidate
from dmf_pulse.chips.inventory import build_chip_inventory
from dmf_pulse.chips.policy_models import (
    PolicyCostProfile,
    PolicyScenarioScore,
    WildcardFutureOutcome,
    WildcardRouteCandidate,
    WildcardRouteCostProfile,
)
from dmf_pulse.chips.wildcard import (
    apply_wildcard_reset,
    evaluate_wildcard,
    make_wildcard_route_candidate,
)
from dmf_pulse.optimisation.multi_gameweek_models import FreeTransferEventRule
from dmf_pulse.optimisation.multi_gameweek_solver import (
    apply_transfer_action,
    make_transfer_action,
)
from tests.support.multi_gameweek_factories import (
    NodeSpec,
    base_squad,
    build_request,
    constrain_mid_transfer_prices,
    replace,
)

swap = replace


def wildcard_request(*, gameweek: int = 2, free_transfers: int = 1, target_price: int = 50):
    squad = base_squad()
    wildcard_squad = swap(squad, "p07", "p15")
    return build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=gameweek,
                points={"p07": 1, "p15": 10},
                allowed_transfer_in_ids=("p15",),
                squads=(squad, wildcard_squad),
            ),
        ),
        free_transfers=free_transfers,
        root_prices=constrain_mid_transfer_prices(target_price=target_price),
        max_transfers_per_node=1,
    )


def wildcard_rules(request):
    events = dict(request.rules.event_rules)
    events["WILDCARD"] = FreeTransferEventRule(
        unlimited_transfers_without_hits=True,
        earn_for_next_deadline=0,
        carry_unused=True,
    )
    events["FREE_HIT"] = FreeTransferEventRule(
        unlimited_transfers_without_hits=True,
        earn_for_next_deadline=0,
        carry_unused=True,
    )
    return request.rules.model_copy(
        update={"event_rules": events, "max_transfers_per_deadline": 20}
    )


def wildcard_definition(
    *,
    end: int = 19,
    effects: tuple[ChipEffect, ...] | None = None,
) -> ChipDefinition:
    return ChipDefinition(
        chip_key="WILDCARD",
        definition_version="SYNTHETIC:WILDCARD:V1",
        grants=(
            InventoryGrant(
                grant_id="window-1",
                copies=1,
                acquired_gameweek=2,
                activation_start_gameweek=2,
                activation_end_gameweek=end,
                expires_after_gameweek=end,
            ),
        ),
        duration_gameweeks=1,
        concurrency_group="SQUAD_CHIP",
        activation_route=ActivationRoute.CONFIRMED_TRANSFERS,
        cancellable_before_lock=True,
        lock_after_confirmed_transfer_count=2,
        effects=effects
        or (
            ChipEffect(surface="TRANSFERS", operation="UNLIMITED_FREE", parameters={}),
            ChipEffect(
                surface="TRANSFERS",
                operation="REMOVE_CURRENT_GAMEWEEK_HITS",
                parameters={},
            ),
            ChipEffect(
                surface="TRANSFERS",
                operation="PRESERVE_SAVED_FREE_TRANSFERS",
                parameters={},
            ),
            ChipEffect(surface="SQUAD", operation="PERMANENT", parameters={}),
        ),
    )


def wildcard_bundle(request, *, definition: ChipDefinition | None = None):
    return compile_synthetic_bundle(
        ruleset_id=request.rules.ruleset_id,
        ruleset_version=request.rules.ruleset_version,
        ruleset_hash=request.rules.ruleset_hash,
        concurrency_limit=1,
        definitions=(definition or wildcard_definition(),),
    )


def policy_scores(
    points: Sequence[float], weights: Sequence[float] | None = None
) -> tuple[PolicyScenarioScore, ...]:
    resolved_weights = tuple(weights) if weights else tuple(1.0 / len(points) for _ in points)
    return tuple(
        PolicyScenarioScore(
            scenario_id=f"s{index}",
            outcome_draw_id=f"d{index}",
            weight=weight,
            manager_points=point,
        )
        for index, (point, weight) in enumerate(zip(points, resolved_weights, strict=True))
    )


def future_outcome(
    outcome_id: str = "base",
    *,
    probability: float = 1.0,
    future_squad_points: float = 0.0,
    transfer_hits_saved: float = 0.0,
    price_route_value: float = 0.0,
    flexibility_value: float = 0.0,
    forced_transfer_value: float = 0.0,
    bench_boost_synergy: float = 0.0,
    free_hit_synergy: float = 0.0,
    triple_captain_synergy: float = 0.0,
    terminal_value: float = 0.0,
) -> WildcardFutureOutcome:
    return WildcardFutureOutcome(
        outcome_id=outcome_id,
        probability=probability,
        future_squad_points=future_squad_points,
        transfer_hits_saved=transfer_hits_saved,
        price_route_value=price_route_value,
        flexibility_value=flexibility_value,
        forced_transfer_value=forced_transfer_value,
        bench_boost_synergy=bench_boost_synergy,
        free_hit_synergy=free_hit_synergy,
        triple_captain_synergy=triple_captain_synergy,
        terminal_value=terminal_value,
    )


def state_for(request, rules, *, event: str, squad: tuple[str, ...]):
    if event == "WILDCARD":
        state = apply_wildcard_reset(
            request.initial_state,
            desired_squad_ids=squad,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
        )
        count = len(set(squad) - set(request.initial_state.squad_ids))
        return state, count, 0.0

    outs = tuple(sorted(set(request.initial_state.squad_ids) - set(squad)))
    ins = tuple(sorted(set(squad) - set(request.initial_state.squad_ids)))
    node = request.scenario_tree.root.model_copy(update={"transition_event": event})
    action = make_transfer_action(transfers_out=outs, transfers_in=ins, event=event)
    applied = apply_transfer_action(
        request.initial_state,
        action,
        node=node,
        candidate_pool=request.candidate_pool,
        rules=rules,
    )
    return applied.state, action.transfer_count, float(applied.free_transfer_arc.hit_points)


def wildcard_policy(
    request,
    rules,
    *,
    policy_id: str,
    role: str,
    event: str,
    squad: tuple[str, ...],
    points: Sequence[float],
    costs: PolicyCostProfile | None = None,
):
    state, count, hit = state_for(request, rules, event=event, squad=squad)
    return (
        make_policy_candidate(
            policy_id=policy_id,
            policy_role=role,
            state_before_sha256=request.initial_state.state_sha256,
            state_after_sha256=state.state_sha256,
            transition_event=event,
            squad_ids=state.squad_ids,
            bank_tenths=state.bank_tenths,
            active_purchase_spell_ids=(item.spell_id for item in state.active_spells),
            free_transfers_after=state.free_transfers,
            transfer_count=count,
            transfer_hit_points=hit,
            tactical_plan_sha256="c" * 64,
            scenario_scores=policy_scores(points),
            costs=costs,
        ),
        state,
    )


def wildcard_route(
    *,
    route_id: str,
    policy,
    state,
    outcomes: Iterable[WildcardFutureOutcome],
    activation_gameweek: int | None = None,
    information_event_id: str | None = None,
    token_consumed_now: bool = False,
    expires_without_use: bool = False,
    information_value: float = 0.0,
    route_costs: WildcardRouteCostProfile | None = None,
) -> WildcardRouteCandidate:
    return make_wildcard_route_candidate(
        route_id=route_id,
        current_policy=policy,
        permanent_state_after_current_action=state,
        information_outcomes=outcomes,
        activation_gameweek=activation_gameweek,
        information_event_id=information_event_id,
        token_consumed_now=token_consumed_now,
        expires_without_use=expires_without_use,
        information_value=information_value,
        route_costs=route_costs,
    )


def base_wildcard_routes(
    request,
    rules,
    *,
    immediate_points: Sequence[float] = (30.0,),
    hold_points: Sequence[float] = (20.0,),
    immediate_outcomes: tuple[WildcardFutureOutcome, ...] | None = None,
    hold_outcomes: tuple[WildcardFutureOutcome, ...] | None = None,
    hold_squad: tuple[str, ...] | None = None,
    hold_event: str = "NORMAL",
    hold_role: str = "HOLD",
    hold_activation: int | None = None,
    hold_information_event: str | None = None,
    hold_information_value: float = 0.0,
    hold_costs: WildcardRouteCostProfile | None = None,
    expires_without_use: bool = False,
):
    squad = base_squad()
    wildcard_squad = swap(squad, "p07", "p15")
    immediate_policy, immediate_state = wildcard_policy(
        request,
        rules,
        policy_id="wildcard-now",
        role="WILDCARD_IMMEDIATE",
        event="WILDCARD",
        squad=wildcard_squad,
        points=immediate_points,
    )
    hold_policy, hold_state = wildcard_policy(
        request,
        rules,
        policy_id="retain-wildcard",
        role=hold_role,
        event=hold_event,
        squad=hold_squad or squad,
        points=hold_points,
    )
    immediate = wildcard_route(
        route_id="route-wildcard-now",
        policy=immediate_policy,
        state=immediate_state,
        outcomes=immediate_outcomes or (future_outcome(future_squad_points=20.0),),
        activation_gameweek=request.scenario_tree.root.gameweek,
        token_consumed_now=True,
    )
    hold = wildcard_route(
        route_id="route-retain-wildcard",
        policy=hold_policy,
        state=hold_state,
        outcomes=hold_outcomes or (future_outcome(future_squad_points=20.0),),
        activation_gameweek=hold_activation,
        information_event_id=hold_information_event,
        information_value=hold_information_value,
        route_costs=hold_costs,
        expires_without_use=expires_without_use,
    )
    return immediate, hold


def evaluate_wildcard_routes(
    request,
    rules,
    routes: Sequence[WildcardRouteCandidate],
    *,
    definition: ChipDefinition | None = None,
):
    bundle = wildcard_bundle(request, definition=definition)
    inventory = build_chip_inventory(bundle, current_gameweek=request.scenario_tree.root.gameweek)
    return evaluate_wildcard(
        routes=routes,
        permanent_state=request.initial_state,
        node=request.scenario_tree.root,
        candidate_pool=request.candidate_pool,
        transfer_rules=rules,
        chip_bundle=bundle,
        inventory=inventory,
        token_id=inventory.tokens[0].token_id,
    )


def valid_wildcard_result():
    request = wildcard_request()
    rules = wildcard_rules(request)
    immediate, hold = base_wildcard_routes(
        request,
        rules,
        immediate_points=(35.0,),
        hold_points=(20.0,),
        immediate_outcomes=(future_outcome(future_squad_points=40.0),),
        hold_outcomes=(future_outcome(future_squad_points=20.0),),
    )
    return (
        request,
        rules,
        immediate,
        hold,
        evaluate_wildcard_routes(request, rules, (immediate, hold)),
    )
