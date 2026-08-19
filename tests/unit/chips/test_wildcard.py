"""Adversarial acceptance tests for the Stage-14 Wildcard comparator."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.definitions import ChipEffect
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.policy_models import WildcardRouteCostProfile
from dmf_pulse.chips.wildcard import apply_wildcard_reset
from dmf_pulse.optimisation.multi_gameweek_models import FreeTransferEventRule
from tests.support.chip_wildcard_factories import (
    base_wildcard_routes,
    evaluate_wildcard_routes,
    future_outcome,
    wildcard_definition,
    wildcard_policy,
    wildcard_request,
    wildcard_route,
    wildcard_rules,
)
from tests.support.multi_gameweek_factories import base_squad
from tests.support.multi_gameweek_factories import replace as swap

pytestmark = pytest.mark.unit


def test_immediate_wildcard_is_clear_optimum() -> None:
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
    result = evaluate_wildcard_routes(request, rules, (immediate, hold))

    assert result.use_now is True
    assert result.selected_route.route_role == "WILDCARD_IMMEDIATE"
    assert result.exercise_advantage == 35.0
    assert result.net_policy_value == result.exercise_advantage


def test_one_free_transfer_repair_prefers_hold() -> None:
    request = wildcard_request(free_transfers=1)
    rules = wildcard_rules(request)
    repaired = swap(base_squad(), "p07", "p15")
    immediate, hold = base_wildcard_routes(
        request,
        rules,
        immediate_points=(31.0,),
        hold_points=(33.0,),
        immediate_outcomes=(future_outcome(future_squad_points=25.0),),
        hold_outcomes=(future_outcome(future_squad_points=30.0),),
        hold_squad=repaired,
    )
    result = evaluate_wildcard_routes(request, rules, (immediate, hold))

    assert hold.current_policy.transfer_count == 1
    assert hold.current_policy.transfer_hit_points == 0.0
    assert result.use_now is False
    assert result.selected_route.route_role == "HOLD"


def test_future_information_makes_delayed_wildcard_best() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    immediate, delayed = base_wildcard_routes(
        request,
        rules,
        immediate_points=(30.0,),
        hold_points=(29.0,),
        immediate_outcomes=(future_outcome(future_squad_points=35.0),),
        hold_outcomes=(
            future_outcome("lineup-a", probability=0.5, future_squad_points=42.0),
            future_outcome("lineup-b", probability=0.5, future_squad_points=42.0),
        ),
        hold_role="WILDCARD_DELAYED",
        hold_activation=3,
        hold_information_event="FUTURE_LINEUP_AND_FIXTURE_INFORMATION",
        hold_information_value=3.0,
    )
    result = evaluate_wildcard_routes(request, rules, (immediate, delayed))

    assert result.use_now is False
    assert result.selected_route.route_role == "WILDCARD_DELAYED"
    assert result.information_value_difference == -3.0


def test_waiting_loses_affordability_and_immediate_wildcard_wins() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    immediate, delayed = base_wildcard_routes(
        request,
        rules,
        immediate_points=(31.0,),
        hold_points=(29.0,),
        immediate_outcomes=(future_outcome(future_squad_points=50.0, price_route_value=4.0),),
        hold_outcomes=(
            future_outcome("price-rise", probability=0.5, future_squad_points=53.0),
            future_outcome("price-flat", probability=0.5, future_squad_points=51.0),
        ),
        hold_role="WILDCARD_DELAYED",
        hold_activation=3,
        hold_information_event="NEXT_PRICE_AND_AVAILABILITY_SNAPSHOT",
        hold_information_value=2.0,
        hold_costs=WildcardRouteCostProfile(affordability_loss=12.0),
    )
    result = evaluate_wildcard_routes(request, rules, (immediate, delayed))

    assert result.use_now is True
    assert result.route_costs_avoided == 12.0
    assert result.selected_route.route_role == "WILDCARD_IMMEDIATE"


def test_wildcard_is_an_exact_permanent_state_reset() -> None:
    request = wildcard_request(free_transfers=2)
    rules = wildcard_rules(request)
    desired = swap(base_squad(), "p07", "p15")
    reset = apply_wildcard_reset(
        request.initial_state,
        desired_squad_ids=desired,
        node=request.scenario_tree.root,
        candidate_pool=request.candidate_pool,
        transfer_rules=rules,
    )
    immediate, hold = base_wildcard_routes(request, rules)
    result = evaluate_wildcard_routes(request, rules, (immediate, hold))

    assert result.immediate_wildcard_state == reset
    assert reset.squad_ids == desired
    assert reset.free_transfers == request.initial_state.free_transfers
    assert reset.current_gameweek == request.scenario_tree.root.gameweek + 1


def test_wildcard_replaces_incoming_purchase_price_cohort() -> None:
    request = wildcard_request(target_price=57)
    rules = wildcard_rules(request)
    immediate, hold = base_wildcard_routes(request, rules)
    result = evaluate_wildcard_routes(request, rules, (immediate, hold))

    incoming = tuple(
        item for item in result.immediate_wildcard_state.active_spells if item.player_id == "p15"
    )
    assert len(incoming) == 1
    assert incoming[0].spell_id in result.incoming_purchase_spell_ids
    assert incoming[0].purchase_price_tenths == 57
    assert incoming[0].started_gameweek == request.scenario_tree.root.gameweek
    assert incoming[0].started_at_node_id == request.scenario_tree.root.node_id


def test_expiry_pressure_can_make_current_wildcard_optimal() -> None:
    request = wildcard_request(gameweek=19)
    rules = wildcard_rules(request)
    immediate, expire = base_wildcard_routes(
        request,
        rules,
        immediate_points=(28.0,),
        hold_points=(29.0,),
        immediate_outcomes=(future_outcome(future_squad_points=20.0),),
        hold_outcomes=(future_outcome(future_squad_points=22.0),),
        hold_costs=WildcardRouteCostProfile(expiry_loss=10.0),
        expires_without_use=True,
    )
    result = evaluate_wildcard_routes(
        request,
        rules,
        (immediate, expire),
        definition=wildcard_definition(end=19),
    )

    assert result.use_now is True
    assert result.best_hold_route.expires_without_use is True
    assert result.route_costs_avoided == 10.0


def test_positive_and_negative_wildcard_bench_boost_synergy_are_measured() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    positive_now, neutral_hold = base_wildcard_routes(
        request,
        rules,
        immediate_outcomes=(future_outcome(bench_boost_synergy=8.0),),
        hold_outcomes=(future_outcome(bench_boost_synergy=1.0),),
    )
    positive = evaluate_wildcard_routes(request, rules, (positive_now, neutral_hold))
    assert positive.bench_boost_synergy_difference == 7.0

    negative_now, better_hold = base_wildcard_routes(
        request,
        rules,
        immediate_outcomes=(future_outcome(bench_boost_synergy=-5.0),),
        hold_outcomes=(future_outcome(bench_boost_synergy=2.0),),
    )
    negative = evaluate_wildcard_routes(request, rules, (negative_now, better_hold))
    assert negative.bench_boost_synergy_difference == -7.0


def test_free_hit_bridge_then_wildcard_can_be_best_hold_policy() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    immediate, bridge = base_wildcard_routes(
        request,
        rules,
        immediate_points=(32.0,),
        hold_points=(45.0,),
        immediate_outcomes=(future_outcome(future_squad_points=30.0),),
        hold_outcomes=(future_outcome(future_squad_points=45.0, free_hit_synergy=6.0),),
        hold_event="FREE_HIT",
        hold_role="FREE_HIT_BRIDGE",
        hold_activation=3,
        hold_information_event="POST_FREE_HIT_INFORMATION",
    )
    result = evaluate_wildcard_routes(request, rules, (immediate, bridge))

    assert result.use_now is False
    assert result.best_hold_route.route_role == "FREE_HIT_BRIDGE"
    assert result.selected_route.route_role == "FREE_HIT_BRIDGE"


def test_delayed_route_without_explicit_information_is_rejected() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    policy, state = wildcard_policy(
        request,
        rules,
        policy_id="invalid-delay",
        role="WILDCARD_DELAYED",
        event="NORMAL",
        squad=base_squad(),
        points=(20.0,),
    )
    with pytest.raises(ValidationError, match="explicit information event"):
        wildcard_route(
            route_id="invalid-delay",
            policy=policy,
            state=state,
            outcomes=(future_outcome(),),
            activation_gameweek=3,
        )


def test_delayed_activation_after_expiry_is_rejected() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    immediate, delayed = base_wildcard_routes(
        request,
        rules,
        hold_role="WILDCARD_DELAYED",
        hold_activation=20,
        hold_information_event="INFO",
    )
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(
            request,
            rules,
            (immediate, delayed),
            definition=wildcard_definition(end=19),
        )
    assert exc_info.value.code == "CHIP_WC_ACTIVATION_AFTER_EXPIRY"


def test_missing_permanent_effect_fails_closed() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    immediate, hold = base_wildcard_routes(request, rules)
    definition = wildcard_definition(
        effects=(
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
        )
    )
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(
            request,
            rules,
            (immediate, hold),
            definition=definition,
        )
    assert exc_info.value.code == "CHIP_WC_EFFECT_MISSING"


def test_wildcard_transfer_event_must_preserve_saved_free_transfers() -> None:
    request = wildcard_request(free_transfers=2)
    rules = wildcard_rules(request)
    events = dict(rules.event_rules)
    events["WILDCARD"] = FreeTransferEventRule(
        unlimited_transfers_without_hits=True,
        earn_for_next_deadline=0,
        carry_unused=False,
        reset_after=1,
    )
    broken = rules.model_copy(update={"event_rules": events})
    with pytest.raises(ChipError) as exc_info:
        apply_wildcard_reset(
            request.initial_state,
            desired_squad_ids=swap(base_squad(), "p07", "p15"),
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=broken,
        )
    assert exc_info.value.code == "CHIP_WC_FT_NOT_PRESERVED"


def test_common_current_scenario_set_is_required() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    immediate, hold = base_wildcard_routes(request, rules)
    altered_score = hold.current_policy.scenario_scores[0].model_copy(
        update={"scenario_id": "different"}
    )
    altered_policy = hold.current_policy.model_copy(update={"scenario_scores": (altered_score,)})
    altered_hold = hold.model_copy(update={"current_policy": altered_policy})

    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, rules, (immediate, altered_hold))
    assert exc_info.value.code == "CHIP_WC_SCENARIO_MISMATCH"
