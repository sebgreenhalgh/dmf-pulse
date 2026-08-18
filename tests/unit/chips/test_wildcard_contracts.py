"""Fail-closed contracts for the Stage-14 Wildcard evaluator."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.compiler import compile_synthetic_bundle
from dmf_pulse.chips.definitions import (
    ActivationRoute,
    ChipDefinition,
    ChipEffect,
    InventoryGrant,
)
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.free_hit import make_policy_candidate
from dmf_pulse.chips.inventory import build_chip_inventory
from dmf_pulse.chips.wildcard import apply_wildcard_reset, evaluate_wildcard
from dmf_pulse.optimisation.multi_gameweek_models import FreeTransferEventRule
from tests.support.chip_wildcard_factories import (
    base_wildcard_routes,
    evaluate_wildcard_routes,
    future_outcome,
    wildcard_bundle,
    wildcard_definition,
    wildcard_policy,
    wildcard_request,
    wildcard_route,
    wildcard_rules,
)
from tests.support.multi_gameweek_factories import (
    NodeSpec,
    base_squad,
    build_request,
    constrain_mid_transfer_prices,
)
from tests.support.multi_gameweek_factories import replace as swap

pytestmark = pytest.mark.unit


def _valid_result():
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


@pytest.mark.parametrize(
    ("desired", "message"),
    [
        (base_squad()[:-1], "complete unique"),
        (tuple(sorted((*base_squad()[:-1], "unknown"))), "unknown player"),
        (swap(base_squad(), "p07", "p16"), "position quotas"),
    ],
)
def test_wildcard_reset_rejects_illegal_desired_squads(
    desired: tuple[str, ...], message: str
) -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    with pytest.raises(ChipError, match=message):
        apply_wildcard_reset(
            request.initial_state,
            desired_squad_ids=desired,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
        )


def test_wildcard_reset_rejects_club_limit_violation() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request).model_copy(update={"max_players_per_club": 1})
    candidate_pool = tuple(
        item.model_copy(update={"club_id": "club-p00"}) if item.player_id == "p15" else item
        for item in request.candidate_pool
    )
    with pytest.raises(ChipError, match="club limits"):
        apply_wildcard_reset(
            request.initial_state,
            desired_squad_ids=swap(base_squad(), "p07", "p15"),
            node=request.scenario_tree.root,
            candidate_pool=candidate_pool,
            transfer_rules=rules,
        )


def test_wildcard_reset_wraps_unaffordable_transition() -> None:
    prices = constrain_mid_transfer_prices(target_price=50)
    prices["p15"] = 100
    squad = base_squad()
    target = swap(squad, "p07", "p15")
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=2,
                points={"p07": 1, "p15": 10},
                allowed_transfer_in_ids=("p15",),
                squads=(squad, target),
            ),
        ),
        free_transfers=1,
        root_prices=prices,
        max_transfers_per_node=1,
    )
    rules = wildcard_rules(request)
    with pytest.raises(ChipError) as exc_info:
        apply_wildcard_reset(
            request.initial_state,
            desired_squad_ids=target,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
        )
    assert exc_info.value.code == "CHIP_WC_TRANSITION_INVALID"


def test_wildcard_reset_rejects_non_unlimited_event() -> None:
    request = wildcard_request(free_transfers=1)
    rules = wildcard_rules(request)
    events = dict(rules.event_rules)
    events["WILDCARD"] = FreeTransferEventRule(
        unlimited_transfers_without_hits=False,
        earn_for_next_deadline=0,
        carry_unused=True,
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
    assert exc_info.value.code == "CHIP_WC_TRANSFER_EVENT_INVALID"


def test_wildcard_reset_rejects_invalid_state_and_node() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    bad_state = request.initial_state.model_copy(update={"state_sha256": "f" * 64})
    with pytest.raises(ChipError) as exc_info:
        apply_wildcard_reset(
            bad_state,
            desired_squad_ids=swap(base_squad(), "p07", "p15"),
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
        )
    assert exc_info.value.code == "CHIP_WC_MANAGER_STATE_INVALID"

    bad_node = request.scenario_tree.root.model_copy(update={"node_id": "other"})
    with pytest.raises(ChipError) as exc_info:
        apply_wildcard_reset(
            request.initial_state,
            desired_squad_ids=swap(base_squad(), "p07", "p15"),
            node=bad_node,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
        )
    assert exc_info.value.code == "CHIP_WC_NODE_MISMATCH"


def _other_definition() -> ChipDefinition:
    return ChipDefinition(
        chip_key="OTHER",
        definition_version="SYNTHETIC:OTHER:V1",
        grants=(
            InventoryGrant(
                grant_id="window-1",
                copies=1,
                acquired_gameweek=2,
                activation_start_gameweek=2,
                activation_end_gameweek=19,
                expires_after_gameweek=19,
            ),
        ),
        duration_gameweeks=1,
        concurrency_group="SQUAD_CHIP",
        activation_route=ActivationRoute.PICK_TEAM_SAVE,
        cancellable_before_lock=True,
        effects=(ChipEffect(surface="SCORING", operation="ADD_POINTS", parameters={"points": 1}),),
    )


def test_wildcard_definition_missing_and_blocked_fail_closed() -> None:
    request, rules, immediate, hold, _ = _valid_result()
    missing_bundle = compile_synthetic_bundle(
        ruleset_id=rules.ruleset_id,
        ruleset_version=rules.ruleset_version,
        ruleset_hash=rules.ruleset_hash,
        concurrency_limit=1,
        definitions=(_other_definition(),),
    )
    missing_inventory = build_chip_inventory(missing_bundle, current_gameweek=2)
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard(
            routes=(immediate, hold),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=missing_bundle,
            inventory=missing_inventory,
            token_id=missing_inventory.tokens[0].token_id,
        )
    assert exc_info.value.code == "CHIP_WC_DEFINITION_MISSING"

    blocked = wildcard_definition(
        effects=(
            ChipEffect(surface="UNKNOWN", operation="UNKNOWN", parameters={}),
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
        )
    )
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, rules, (immediate, hold), definition=blocked)
    assert exc_info.value.code == "CHIP_EFFECT_BLOCKED"


def test_route_set_requires_immediate_hold_unique_and_common_lineage() -> None:
    request, rules, immediate, hold, _ = _valid_result()
    for routes, code in (
        ((), "CHIP_WC_ROUTES_EMPTY"),
        ((hold,), "CHIP_WC_IMMEDIATE_MISSING"),
        ((immediate,), "CHIP_WC_HOLD_MISSING"),
        ((immediate, hold, hold), "CHIP_WC_ROUTES_DUPLICATE"),
    ):
        with pytest.raises(ChipError) as exc_info:
            evaluate_wildcard_routes(request, rules, routes)
        assert exc_info.value.code == code

    wrong_policy = make_policy_candidate(
        policy_id="wrong-lineage",
        policy_role="HOLD",
        state_before_sha256="f" * 64,
        state_after_sha256=hold.permanent_state_after_current_action.state_sha256,
        transition_event="NORMAL",
        squad_ids=hold.current_policy.squad_ids,
        bank_tenths=hold.current_policy.bank_tenths,
        active_purchase_spell_ids=hold.current_policy.active_purchase_spell_ids,
        free_transfers_after=hold.current_policy.free_transfers_after,
        transfer_count=hold.current_policy.transfer_count,
        transfer_hit_points=hold.current_policy.transfer_hit_points,
        tactical_plan_sha256="c" * 64,
        scenario_scores=hold.current_policy.scenario_scores,
    )
    wrong = wildcard_route(
        route_id="wrong-lineage",
        policy=wrong_policy,
        state=hold.permanent_state_after_current_action,
        outcomes=hold.information_outcomes,
    )
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, rules, (immediate, wrong))
    assert exc_info.value.code == "CHIP_WC_STATE_LINEAGE"


def test_route_validation_rejects_invalid_state_event_and_activation_time() -> None:
    request, rules, immediate, hold, _ = _valid_result()
    invalid_state = hold.permanent_state_after_current_action.model_copy(
        update={"state_sha256": "f" * 64}
    )
    invalid_route = hold.model_copy(update={"permanent_state_after_current_action": invalid_state})
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, rules, (immediate, invalid_route))
    assert exc_info.value.code == "CHIP_WC_RESULTING_STATE_INVALID"

    missing_event_rules = rules.model_copy(
        update={"event_rules": {"WILDCARD": rules.event_rules["WILDCARD"]}}
    )
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, missing_event_rules, (immediate, hold))
    assert exc_info.value.code == "CHIP_WC_TRANSFER_EVENT_MISSING"

    delayed_policy, delayed_state = wildcard_policy(
        request,
        rules,
        policy_id="past-delay",
        role="WILDCARD_DELAYED",
        event="NORMAL",
        squad=base_squad(),
        points=(20.0,),
    )
    for gameweek in (1, 2):
        route = wildcard_route(
            route_id=f"delay-{gameweek}",
            policy=delayed_policy,
            state=delayed_state,
            outcomes=(future_outcome(),),
            activation_gameweek=gameweek,
            information_event_id="INFO",
        )
        with pytest.raises(ChipError) as exc_info:
            evaluate_wildcard_routes(request, rules, (immediate, route))
        assert exc_info.value.code == "CHIP_WC_ACTIVATION_TIME"


def test_route_event_roles_are_enforced() -> None:
    request, rules, immediate, hold, _ = _valid_result()
    immediate_bad = immediate.model_copy(
        update={
            "current_policy": immediate.current_policy.model_copy(
                update={"transition_event": "NORMAL"}
            )
        }
    )
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, rules, (immediate_bad, hold))
    assert exc_info.value.code in {
        "CHIP_WC_TRANSFER_TRANSITION_MISMATCH",
        "CHIP_WC_ROUTE_EVENT",
    }

    delayed_policy, delayed_state = wildcard_policy(
        request,
        rules,
        policy_id="delay-wrong-event",
        role="WILDCARD_DELAYED",
        event="FREE_HIT",
        squad=base_squad(),
        points=(20.0,),
    )
    delayed = wildcard_route(
        route_id="delay-wrong-event",
        policy=delayed_policy,
        state=delayed_state,
        outcomes=(future_outcome(),),
        activation_gameweek=3,
        information_event_id="INFO",
    )
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, rules, (immediate, delayed))
    assert exc_info.value.code == "CHIP_WC_ROUTE_EVENT"

    bridge_policy, bridge_state = wildcard_policy(
        request,
        rules,
        policy_id="bridge-wrong-event",
        role="FREE_HIT_BRIDGE",
        event="NORMAL",
        squad=base_squad(),
        points=(20.0,),
    )
    bridge = wildcard_route(
        route_id="bridge-wrong-event",
        policy=bridge_policy,
        state=bridge_state,
        outcomes=(future_outcome(),),
        activation_gameweek=3,
        information_event_id="INFO",
    )
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, rules, (immediate, bridge))
    assert exc_info.value.code == "CHIP_WC_ROUTE_EVENT"


def test_evaluator_rejects_lineage_token_status_and_inventory_time() -> None:
    request, rules, immediate, hold, _ = _valid_result()
    bundle = wildcard_bundle(request)
    inventory = build_chip_inventory(bundle, current_gameweek=2)

    wrong_bundle = bundle.model_copy(update={"ruleset_hash": "f" * 64})
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard(
            routes=(immediate, hold),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=wrong_bundle,
            inventory=inventory,
            token_id=inventory.tokens[0].token_id,
        )
    assert exc_info.value.code == "CHIP_RULESET_LINEAGE_MISMATCH"

    bad_inventory = inventory.model_copy(update={"bundle_hash": "f" * 64})
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard(
            routes=(immediate, hold),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=bundle,
            inventory=bad_inventory,
            token_id=inventory.tokens[0].token_id,
        )
    assert exc_info.value.code == "CHIP_INVENTORY_LINEAGE_MISMATCH"

    wrong_time = inventory.model_copy(update={"current_gameweek": 3})
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard(
            routes=(immediate, hold),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=bundle,
            inventory=wrong_time,
            token_id=inventory.tokens[0].token_id,
        )
    assert exc_info.value.code == "CHIP_WC_INVENTORY_TIME_MISMATCH"

    combined = compile_synthetic_bundle(
        ruleset_id=rules.ruleset_id,
        ruleset_version=rules.ruleset_version,
        ruleset_hash=rules.ruleset_hash,
        concurrency_limit=1,
        definitions=(wildcard_definition(), _other_definition()),
    )
    combined_inventory = build_chip_inventory(combined, current_gameweek=2)
    other_token = next(token for token in combined_inventory.tokens if token.chip_key == "OTHER")
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard(
            routes=(immediate, hold),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=combined,
            inventory=combined_inventory,
            token_id=other_token.token_id,
        )
    assert exc_info.value.code == "CHIP_WC_TOKEN_MISMATCH"


def _mutated_payload(model: Any, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    payload = model.model_dump(mode="python")
    mutate(payload)
    return payload


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload.update(route_role="HOLD"), "role must match"),
        (lambda payload: payload.update(information_outcomes=()), "non-empty"),
        (
            lambda payload: payload.update(
                information_outcomes=(
                    future_outcome("z", probability=0.5).model_dump(mode="python"),
                    future_outcome("a", probability=0.5).model_dump(mode="python"),
                )
            ),
            "sorted",
        ),
        (
            lambda payload: payload.update(
                information_outcomes=(
                    future_outcome("x", probability=0.5).model_dump(mode="python"),
                    future_outcome("x", probability=0.5).model_dump(mode="python"),
                )
            ),
            "unique",
        ),
        (
            lambda payload: payload["information_outcomes"][0].update(probability=0.5),
            "sum to one",
        ),
        (lambda payload: payload.update(activation_gameweek=None), "consume the token"),
        (lambda payload: payload.update(information_event_id="INFO"), "cannot be delayed"),
        (lambda payload: payload.update(expires_without_use=True), "cannot expire unused"),
        (lambda payload: payload.update(current_net_value=999.0), "current net value"),
        (lambda payload: payload.update(expected_future_value=999.0), "expected future value"),
        (lambda payload: payload.update(route_value=999.0), "route value"),
        (lambda payload: payload.update(route_hash="f" * 64), "route hash"),
    ],
)
def test_wildcard_route_contract_rejects_tampering(
    mutator: Callable[[dict[str, Any]], None], message: str
) -> None:
    _, _, immediate, _, _ = _valid_result()
    payload = _mutated_payload(immediate, mutator)
    with pytest.raises(ValidationError, match=message):
        type(immediate).model_validate(payload)


def test_delayed_and_hold_route_contracts_reject_invalid_state_flags() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    _, delayed = base_wildcard_routes(
        request,
        rules,
        hold_role="WILDCARD_DELAYED",
        hold_activation=3,
        hold_information_event="INFO",
    )
    for update, message in (
        ({"token_consumed_now": True}, "retains the token"),
        ({"expires_without_use": True}, "cannot expire unused"),
        ({"activation_gameweek": None}, "explicit information event"),
    ):
        payload = delayed.model_dump(mode="python")
        payload.update(update)
        with pytest.raises(ValidationError, match=message):
            type(delayed).model_validate(payload)

    _, hold = base_wildcard_routes(request, rules)
    for update, message in (
        ({"activation_gameweek": 3}, "hold route cannot declare"),
        ({"information_event_id": "INFO"}, "hold route cannot declare"),
        ({"token_consumed_now": True}, "hold route cannot consume"),
    ):
        payload = hold.model_dump(mode="python")
        payload.update(update)
        with pytest.raises(ValidationError, match=message):
            type(hold).model_validate(payload)


def test_wildcard_scenario_contract_rejects_arithmetic_tampering() -> None:
    _, _, _, _, result = _valid_result()
    payload = result.scenario_values[0].model_dump(mode="python")
    payload["gross_current_increment"] += 1.0
    with pytest.raises(ValidationError, match="scenario increment"):
        type(result.scenario_values[0]).model_validate(payload)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload.update(routes=()), "non-empty and sorted"),
        (lambda payload: payload.update(routes=tuple(reversed(payload["routes"]))), "sorted"),
        (
            lambda payload: payload.update(best_immediate_route=payload["best_hold_route"]),
            "wrong role",
        ),
        (
            lambda payload: payload.update(best_hold_route=payload["best_immediate_route"]),
            "retain the token",
        ),
        (
            lambda payload: payload.update(
                immediate_wildcard_state=payload["best_hold_route"][
                    "permanent_state_after_current_action"
                ]
            ),
            "immediate state",
        ),
        (
            lambda payload: payload["scenario_values"][0].update(scenario_id="other"),
            "common scenario set",
        ),
        (lambda payload: payload.update(gross_current_gain=999.0), "gross current gain"),
        (lambda payload: payload.update(net_policy_value=999.0), "decomposition"),
        (lambda payload: payload.update(exercise_advantage=999.0), "exercise advantage"),
        (lambda payload: payload.update(use_now=False), "use-now"),
        (
            lambda payload: payload.update(selected_route=payload["best_hold_route"]),
            "selected route",
        ),
        (
            lambda payload: payload.update(
                inventory_after_activation_hash=payload["inventory_before_hash"]
            ),
            "change projected inventory",
        ),
        (
            lambda payload: payload.update(
                incoming_purchase_spell_ids=(
                    payload["incoming_purchase_spell_ids"][0],
                    payload["incoming_purchase_spell_ids"][0],
                )
            ),
            "unique",
        ),
        (lambda payload: payload.update(evaluation_hash="f" * 64), "evaluation hash"),
    ],
)
def test_wildcard_evaluation_contract_rejects_tampering(
    mutator: Callable[[dict[str, Any]], None], message: str
) -> None:
    _, _, _, _, result = _valid_result()
    payload = _mutated_payload(result, mutator)
    with pytest.raises(ValidationError, match=message):
        type(result).model_validate(payload)


def test_evaluator_rejects_post_state_time_and_immediate_activation_mismatch() -> None:
    request, rules, immediate, hold, _ = _valid_result()
    from dmf_pulse.optimisation.manager_state import seal_manager_state

    wrong_time_state = seal_manager_state(
        hold.permanent_state_after_current_action.model_copy(update={"current_gameweek": 4})
    )
    wrong_time_route = hold.model_copy(
        update={"permanent_state_after_current_action": wrong_time_state}
    )
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, rules, (immediate, wrong_time_route))
    assert exc_info.value.code == "CHIP_WC_RESULTING_STATE_INVALID"

    wrong_activation = immediate.model_copy(update={"activation_gameweek": 3})
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, rules, (wrong_activation, hold))
    assert exc_info.value.code == "CHIP_WC_ACTIVATION_TIME"


def test_evaluator_rejects_invalid_manager_node_and_unavailable_token() -> None:
    request, rules, immediate, hold, _ = _valid_result()
    bundle = wildcard_bundle(request)
    inventory = build_chip_inventory(bundle, current_gameweek=2)

    bad_state = request.initial_state.model_copy(update={"state_sha256": "f" * 64})
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard(
            routes=(immediate, hold),
            permanent_state=bad_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=bundle,
            inventory=inventory,
            token_id=inventory.tokens[0].token_id,
        )
    assert exc_info.value.code == "CHIP_WC_MANAGER_STATE_INVALID"

    from dmf_pulse.optimisation.manager_state import seal_manager_state

    other_node_state = seal_manager_state(
        request.initial_state.model_copy(update={"observed_node_id": "other"})
    )
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard(
            routes=(immediate, hold),
            permanent_state=other_node_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=bundle,
            inventory=inventory,
            token_id=inventory.tokens[0].token_id,
        )
    assert exc_info.value.code == "CHIP_WC_NODE_MISMATCH"

    from dmf_pulse.chips.inventory import TokenStatus

    used = inventory.tokens[0].model_copy(update={"status": TokenStatus.USED})
    unavailable_inventory = inventory.model_copy(update={"tokens": (used,)})
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard(
            routes=(immediate, hold),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=bundle,
            inventory=unavailable_inventory,
            token_id=used.token_id,
        )
    assert exc_info.value.code == "CHIP_WC_TOKEN_UNAVAILABLE"


def test_evaluator_rejects_nonfinite_and_unreconciled_policy_value() -> None:
    request, rules, immediate, hold, _ = _valid_result()
    nonfinite = immediate.model_copy(update={"route_value": float("inf")})
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, rules, (nonfinite, hold))
    assert exc_info.value.code == "CHIP_WC_VALUE_INVALID"

    unreconciled = immediate.model_copy(update={"route_value": immediate.route_value + 1.0})
    with pytest.raises(ChipError) as exc_info:
        evaluate_wildcard_routes(request, rules, (unreconciled, hold))
    assert exc_info.value.code == "CHIP_WC_VALUE_MISMATCH"


def test_wildcard_route_rejects_non_wildcard_policy_role() -> None:
    request = wildcard_request()
    rules = wildcard_rules(request)
    policy, state = wildcard_policy(
        request,
        rules,
        policy_id="normal-policy",
        role="NORMAL_TRANSFER",
        event="NORMAL",
        squad=base_squad(),
        points=(20.0,),
    )
    with pytest.raises(ChipError) as exc_info:
        wildcard_route(
            route_id="invalid-normal-route",
            policy=policy,
            state=state,
            outcomes=(future_outcome(),),
        )
    assert exc_info.value.code == "CHIP_WC_ROUTE_ROLE_INVALID"
