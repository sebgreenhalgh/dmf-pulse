from __future__ import annotations

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
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.free_hit import (
    evaluate_free_hit,
    make_policy_candidate,
    policy_candidate_from_stage11,
)
from dmf_pulse.chips.inventory import build_chip_inventory
from dmf_pulse.chips.policy_models import PolicyCostProfile, PolicyScenarioScore
from dmf_pulse.optimisation.multi_gameweek_models import FreeTransferEventRule
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from tests.support.multi_gameweek_factories import (
    NodeSpec,
    base_squad,
    build_request,
    constrain_mid_transfer_prices,
)
from tests.support.multi_gameweek_factories import (
    replace as swap,
)

pytestmark = pytest.mark.unit


def _request():
    squad = base_squad()
    temporary = swap(squad, "p07", "p15")
    return build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=2,
                points={"p07": 1, "p15": 10},
                allowed_transfer_in_ids=("p15",),
                squads=(squad, temporary),
            ),
        ),
        free_transfers=3,
        root_prices=constrain_mid_transfer_prices(target_price=50),
        max_transfers_per_node=1,
    )


def _rules(request):
    events = dict(request.rules.event_rules)
    events["FREE_HIT"] = FreeTransferEventRule(
        unlimited_transfers_without_hits=True,
        earn_for_next_deadline=0,
        carry_unused=True,
    )
    return request.rules.model_copy(
        update={"event_rules": events, "max_transfers_per_deadline": 20}
    )


def _definition(*, effects: tuple[ChipEffect, ...] | None = None) -> ChipDefinition:
    return ChipDefinition(
        chip_key="FREE_HIT",
        definition_version="SYNTHETIC:FREE_HIT:V1",
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
        activation_route=ActivationRoute.CONFIRMED_TRANSFERS,
        cancellable_before_lock=True,
        lock_after_confirmed_transfer_count=1,
        minimum_gap_gameweeks=1,
        effects=effects
        or (
            ChipEffect(surface="TRANSFERS", operation="UNLIMITED_FREE", parameters={}),
            ChipEffect(
                surface="TRANSFERS",
                operation="PRESERVE_SAVED_FREE_TRANSFERS",
                parameters={},
            ),
            ChipEffect(surface="SQUAD", operation="RESTORE_NEXT_DEADLINE", parameters={}),
            ChipEffect(surface="BANK", operation="RESTORE_NEXT_DEADLINE", parameters={}),
            ChipEffect(
                surface="PURCHASE_PRICES",
                operation="RESTORE_NEXT_DEADLINE",
                parameters={},
            ),
        ),
    )


def _bundle(request, *, definition: ChipDefinition | None = None):
    return compile_synthetic_bundle(
        ruleset_id=request.rules.ruleset_id,
        ruleset_version=request.rules.ruleset_version,
        ruleset_hash=request.rules.ruleset_hash,
        concurrency_limit=1,
        definitions=(definition or _definition(),),
    )


def _scores(points: tuple[float, ...], weights: tuple[float, ...] | None = None):
    weights = weights or tuple(1.0 / len(points) for _ in points)
    return tuple(
        PolicyScenarioScore(
            scenario_id=f"s{index}",
            outcome_draw_id=f"d{index}",
            weight=weight,
            manager_points=point,
        )
        for index, (point, weight) in enumerate(zip(points, weights, strict=True))
    )


def _candidate(
    request,
    *,
    policy_id: str,
    role: str,
    points: tuple[float, ...],
    hit: float = 0.0,
    costs: PolicyCostProfile | None = None,
    continuation: float = 0.0,
    transfer_count: int = 0,
    squad: tuple[str, ...] | None = None,
    spells: tuple[str, ...] | None = None,
):
    squad = tuple(sorted(squad or request.initial_state.squad_ids))
    default_spells = tuple(sorted(item.spell_id for item in request.initial_state.active_spells))
    return make_policy_candidate(
        policy_id=policy_id,
        policy_role=role,  # type: ignore[arg-type]
        state_before_sha256=request.initial_state.state_sha256,
        state_after_sha256=("a" if role == "NORMAL_TRANSFER" else "b") * 64,
        transition_event="NORMAL" if role == "NORMAL_TRANSFER" else "FREE_HIT",
        squad_ids=squad,
        bank_tenths=request.initial_state.bank_tenths if role == "NORMAL_TRANSFER" else 1,
        active_purchase_spell_ids=spells or default_spells,
        free_transfers_after=(
            max(1, request.initial_state.free_transfers - transfer_count + 1)
            if role == "NORMAL_TRANSFER"
            else request.initial_state.free_transfers
        ),
        transfer_count=transfer_count,
        transfer_hit_points=hit,
        tactical_plan_sha256="c" * 64,
        scenario_scores=_scores(points),
        costs=costs,
        continuation_value=continuation,
    )


def _evaluate(
    *,
    normal_points: tuple[float, ...] = (20.0,),
    free_hit_points: tuple[float, ...] = (30.0,),
    normal_hit: float = 0.0,
    normal_costs: PolicyCostProfile | None = None,
    free_hit_costs: PolicyCostProfile | None = None,
    normal_continuation: float = 0.0,
    free_hit_continuation: float = 0.0,
    normal_candidates=None,
    free_hit_candidates=None,
    definition: ChipDefinition | None = None,
):
    request = _request()
    rules = _rules(request)
    bundle = _bundle(request, definition=definition)
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    token = inventory.tokens[0]
    temporary_squad = swap(base_squad(), "p07", "p15")
    normal = normal_candidates or (
        _candidate(
            request,
            policy_id="normal",
            role="NORMAL_TRANSFER",
            points=normal_points,
            hit=normal_hit,
            costs=normal_costs,
            continuation=normal_continuation,
        ),
    )
    temporary_spells = tuple(
        sorted(
            (
                *(
                    item.spell_id
                    for item in request.initial_state.active_spells
                    if item.player_id != "p07"
                ),
                "temporary-p15-cohort",
            )
        )
    )
    free_hit = free_hit_candidates or (
        _candidate(
            request,
            policy_id="free-hit",
            role="FREE_HIT_TEMPORARY",
            points=free_hit_points,
            costs=free_hit_costs,
            continuation=free_hit_continuation,
            transfer_count=1,
            squad=temporary_squad,
            spells=temporary_spells,
        ),
    )
    result = evaluate_free_hit(
        normal_candidates=normal,
        free_hit_candidates=free_hit,
        permanent_state=request.initial_state,
        node=request.scenario_tree.root,
        candidate_pool=request.candidate_pool,
        transfer_rules=rules,
        chip_bundle=bundle,
        inventory=inventory,
        token_id=token.token_id,
    )
    return request, result


def test_blank_gameweek_free_hit_is_clear_optimum() -> None:
    _, result = _evaluate(normal_points=(8.0, 12.0), free_hit_points=(42.0, 38.0))
    assert result.gross_current_gain == 30.0
    assert result.use_now is True


def test_offensive_double_gameweek_free_hit_is_selected() -> None:
    _, result = _evaluate(normal_points=(34.0,), free_hit_points=(61.0,))
    assert result.exercise_advantage == 27.0
    assert result.free_hit_policy.policy_id == "free-hit"


def test_defensive_free_hit_can_win_despite_negative_current_uplift() -> None:
    costs = PolicyCostProfile(
        permanent_squad_damage_points=4.0,
        route_flexibility_cost_points=3.0,
        purchase_price_spell_damage_points=2.0,
    )
    _, result = _evaluate(
        normal_points=(31.0,),
        free_hit_points=(29.0,),
        normal_costs=costs,
        free_hit_continuation=1.0,
    )
    assert result.gross_current_gain == -2.0
    assert result.net_policy_value == 8.0
    assert result.use_now is True


def test_best_ordinary_transfer_policy_can_beat_free_hit() -> None:
    _, result = _evaluate(normal_points=(40.0,), free_hit_points=(36.0,))
    assert result.net_policy_value == -4.0
    assert result.use_now is False


def test_free_hit_counts_transfer_hits_avoided() -> None:
    _, result = _evaluate(normal_points=(30.0,), free_hit_points=(30.0,), normal_hit=8.0)
    assert result.transfer_hits_avoided == 8.0
    assert result.net_pre_continuation_value == 8.0


def test_free_hit_preserves_valuable_purchase_price_spell() -> None:
    costs = PolicyCostProfile(purchase_price_spell_damage_points=7.5)
    _, result = _evaluate(normal_points=(30.0,), free_hit_points=(30.0,), normal_costs=costs)
    assert result.purchase_price_spell_value_preserved == 7.5
    assert result.use_now is True


def test_permanent_squad_bank_and_purchase_prices_restore_exactly() -> None:
    request, result = _evaluate()
    restored = result.restored_state
    assert restored.squad_ids == request.initial_state.squad_ids
    assert restored.bank_tenths == request.initial_state.bank_tenths
    assert {item.spell_id: item.purchase_price_tenths for item in restored.ownership_spells} == {
        item.spell_id: item.purchase_price_tenths for item in request.initial_state.ownership_spells
    }
    assert result.permanent_squad_restored is True
    assert result.permanent_bank_restored is True
    assert result.purchase_prices_restored is True


def test_free_transfer_transition_is_rules_driven_and_preserved() -> None:
    request, result = _evaluate()
    assert request.initial_state.free_transfers == 3
    assert result.restored_state.free_transfers == 3
    assert result.free_hit_policy.free_transfers_after == 3


def test_temporary_purchases_do_not_contaminate_permanent_cohorts() -> None:
    request, result = _evaluate()
    restored_ids = {item.spell_id for item in result.restored_state.ownership_spells}
    assert "temporary-p15-cohort" not in restored_ids
    assert restored_ids == {item.spell_id for item in request.initial_state.ownership_spells}
    assert result.temporary_purchases_excluded_from_permanent_cohorts is True


def test_best_normal_and_best_free_hit_routes_are_optimised_independently() -> None:
    request = _request()
    normal = (
        _candidate(request, policy_id="normal-low", role="NORMAL_TRANSFER", points=(20.0,)),
        _candidate(request, policy_id="normal-best", role="NORMAL_TRANSFER", points=(28.0,)),
    )
    temporary = swap(base_squad(), "p07", "p15")
    temporary_spells = tuple(f"temp-{index}" for index in range(15))
    free_hit = (
        _candidate(
            request,
            policy_id="fh-current-high",
            role="FREE_HIT_TEMPORARY",
            points=(35.0,),
            continuation=-10.0,
            transfer_count=1,
            squad=temporary,
            spells=temporary_spells,
        ),
        _candidate(
            request,
            policy_id="fh-policy-best",
            role="FREE_HIT_TEMPORARY",
            points=(32.0,),
            continuation=1.0,
            transfer_count=1,
            squad=temporary,
            spells=tuple(f"tmp-{index}" for index in range(15)),
        ),
    )
    _, result = _evaluate(normal_candidates=normal, free_hit_candidates=free_hit)
    assert result.normal_policy.policy_id == "normal-best"
    assert result.free_hit_policy.policy_id == "fh-policy-best"


def test_stage11_adapter_preserves_root_decision_contract() -> None:
    request = _request()
    result = optimise_multi_gameweek(request)
    assert result.recommended_plan is not None
    decision = result.recommended_plan.current_action
    score = PolicyScenarioScore(
        scenario_id="root-scenario",
        outcome_draw_id="root-draw",
        weight=1.0,
        manager_points=float(decision.tactical_evaluation.expected_points),
    )
    candidate = policy_candidate_from_stage11(
        decision,
        policy_id="accepted-stage11-root",
        policy_role="NORMAL_TRANSFER",
        scenario_scores=(score,),
    )
    assert candidate.state_after_sha256 == decision.state_after.state_sha256
    assert candidate.tactical_plan_sha256 == decision.tactical_evaluation.tactical_plan_sha256


def test_stage11_adapter_rejects_scenario_mean_mismatch() -> None:
    request = _request()
    result = optimise_multi_gameweek(request)
    assert result.recommended_plan is not None
    with pytest.raises(ChipError, match="common-scenario"):
        policy_candidate_from_stage11(
            result.recommended_plan.current_action,
            policy_id="bad",
            policy_role="NORMAL_TRANSFER",
            scenario_scores=_scores((999.0,)),
        )


def test_missing_effect_wrong_token_and_invalid_transfer_event_fail_closed() -> None:
    missing = _definition(
        effects=(ChipEffect(surface="TRANSFERS", operation="UNLIMITED_FREE", parameters={}),)
    )
    with pytest.raises(ChipError) as exc:
        _evaluate(definition=missing)
    assert exc.value.code == "CHIP_FH_EFFECT_MISSING"

    request = _request()
    bad = _candidate(
        request,
        policy_id="bad-event",
        role="FREE_HIT_TEMPORARY",
        points=(30.0,),
        transfer_count=1,
    ).model_copy(update={"transition_event": "UNKNOWN", "candidate_hash": "0" * 64})
    payload = bad.model_dump(mode="json")
    payload["candidate_hash"] = None
    bad = bad.model_copy(update={"candidate_hash": semantic_sha256(payload)})
    with pytest.raises(ChipError) as exc:
        _evaluate(free_hit_candidates=(bad,))
    assert exc.value.code == "CHIP_FH_TRANSFER_EVENT_MISSING"


def test_common_scenario_mismatch_and_duplicate_candidates_fail_closed() -> None:
    request = _request()
    normal = _candidate(request, policy_id="normal", role="NORMAL_TRANSFER", points=(20.0,))
    duplicate = (normal, normal)
    with pytest.raises(ChipError) as exc:
        _evaluate(normal_candidates=duplicate)
    assert exc.value.code == "CHIP_FH_CANDIDATES_DUPLICATE"

    different = make_policy_candidate(
        policy_id="fh-different",
        policy_role="FREE_HIT_TEMPORARY",
        state_before_sha256=request.initial_state.state_sha256,
        state_after_sha256="d" * 64,
        transition_event="FREE_HIT",
        squad_ids=swap(base_squad(), "p07", "p15"),
        bank_tenths=0,
        active_purchase_spell_ids=tuple(f"x-{index}" for index in range(15)),
        free_transfers_after=3,
        transfer_count=1,
        transfer_hit_points=0.0,
        tactical_plan_sha256="e" * 64,
        scenario_scores=(
            PolicyScenarioScore(
                scenario_id="other", outcome_draw_id="other", weight=1.0, manager_points=30.0
            ),
        ),
    )
    with pytest.raises(ChipError) as exc:
        _evaluate(free_hit_candidates=(different,))
    assert exc.value.code == "CHIP_FH_SCENARIO_MISMATCH"


def test_hashes_are_deterministic_and_tamper_evident() -> None:
    _, first = _evaluate()
    _, second = _evaluate()
    assert first == second
    assert (
        semantic_sha256(first.model_dump(mode="json", exclude={"evaluation_hash"}))
        == first.evaluation_hash
    )

    payload = first.model_dump(mode="python")
    payload["net_policy_value"] += 1.0
    with pytest.raises(ValidationError, match="net policy value"):
        type(first).model_validate(payload)

    candidate_payload = first.normal_policy.model_dump(mode="python")
    candidate_payload["candidate_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="candidate hash"):
        type(first.normal_policy).model_validate(candidate_payload)


def _direct_inputs():
    request = _request()
    rules = _rules(request)
    bundle = _bundle(request)
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    normal = _candidate(request, policy_id="normal-direct", role="NORMAL_TRANSFER", points=(20.0,))
    free_hit = _candidate(
        request,
        policy_id="fh-direct",
        role="FREE_HIT_TEMPORARY",
        points=(30.0,),
        transfer_count=1,
        squad=swap(base_squad(), "p07", "p15"),
        spells=tuple(f"temporary-{index}" for index in range(15)),
    )
    return request, rules, bundle, inventory, normal, free_hit


def test_missing_or_blocked_definition_fails_closed() -> None:
    request, rules, _, _, normal, free_hit = _direct_inputs()
    other = ChipDefinition(
        chip_key="OTHER",
        definition_version="OTHER:V1",
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
    missing_bundle = compile_synthetic_bundle(
        ruleset_id=request.rules.ruleset_id,
        ruleset_version=request.rules.ruleset_version,
        ruleset_hash=request.rules.ruleset_hash,
        concurrency_limit=1,
        definitions=(other,),
    )
    missing_inventory = build_chip_inventory(missing_bundle, current_gameweek=2)
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(
            normal_candidates=(normal,),
            free_hit_candidates=(free_hit,),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=missing_bundle,
            inventory=missing_inventory,
            token_id=missing_inventory.tokens[0].token_id,
        )
    assert exc.value.code == "CHIP_FH_DEFINITION_MISSING"

    blocked_bundle = _bundle(
        request,
        definition=_definition(
            effects=(ChipEffect(surface="UNKNOWN", operation="UNKNOWN", parameters={}),)
        ),
    )
    blocked_inventory = build_chip_inventory(blocked_bundle, current_gameweek=2)
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(
            normal_candidates=(normal,),
            free_hit_candidates=(free_hit,),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=blocked_bundle,
            inventory=blocked_inventory,
            token_id=blocked_inventory.tokens[0].token_id,
        )
    assert exc.value.code == "CHIP_EFFECT_BLOCKED"


def test_empty_wrong_role_and_state_lineage_candidates_fail_closed() -> None:
    request, rules, bundle, inventory, normal, free_hit = _direct_inputs()
    kwargs = dict(
        permanent_state=request.initial_state,
        node=request.scenario_tree.root,
        candidate_pool=request.candidate_pool,
        transfer_rules=rules,
        chip_bundle=bundle,
        inventory=inventory,
        token_id=inventory.tokens[0].token_id,
    )
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(normal_candidates=(), free_hit_candidates=(free_hit,), **kwargs)
    assert exc.value.code == "CHIP_FH_CANDIDATES_EMPTY"

    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(normal_candidates=(free_hit,), free_hit_candidates=(free_hit,), **kwargs)
    assert exc.value.code == "CHIP_FH_CANDIDATE_ROLE"

    payload = normal.model_dump(mode="python")
    payload["state_before_sha256"] = "f" * 64
    payload["candidate_hash"] = "0" * 64
    raw = payload.copy()
    raw.pop("candidate_hash")
    payload["candidate_hash"] = semantic_sha256(raw)
    wrong_state = type(normal).model_validate(payload)
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(
            normal_candidates=(wrong_state,), free_hit_candidates=(free_hit,), **kwargs
        )
    assert exc.value.code == "CHIP_FH_STATE_LINEAGE"


def test_candidate_internal_scenario_disagreement_fails_closed() -> None:
    request, rules, bundle, inventory, normal, free_hit = _direct_inputs()
    second = make_policy_candidate(
        policy_id="normal-other-scenario",
        policy_role="NORMAL_TRANSFER",
        state_before_sha256=request.initial_state.state_sha256,
        state_after_sha256="9" * 64,
        transition_event="NORMAL",
        squad_ids=request.initial_state.squad_ids,
        bank_tenths=request.initial_state.bank_tenths,
        active_purchase_spell_ids=tuple(
            item.spell_id for item in request.initial_state.active_spells
        ),
        free_transfers_after=3,
        transfer_count=0,
        transfer_hit_points=0.0,
        tactical_plan_sha256="8" * 64,
        scenario_scores=(
            PolicyScenarioScore(
                scenario_id="different",
                outcome_draw_id="different",
                weight=1.0,
                manager_points=21.0,
            ),
        ),
    )
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(
            normal_candidates=(normal, second),
            free_hit_candidates=(free_hit,),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=bundle,
            inventory=inventory,
            token_id=inventory.tokens[0].token_id,
        )
    assert exc.value.code == "CHIP_FH_SCENARIO_MISMATCH"


def test_manager_node_and_rules_lineage_fail_closed() -> None:
    request, rules, bundle, inventory, normal, free_hit = _direct_inputs()
    base = dict(
        normal_candidates=(normal,),
        free_hit_candidates=(free_hit,),
        candidate_pool=request.candidate_pool,
        transfer_rules=rules,
        chip_bundle=bundle,
        inventory=inventory,
        token_id=inventory.tokens[0].token_id,
    )
    bad_state = request.initial_state.model_copy(update={"state_sha256": "f" * 64})
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(permanent_state=bad_state, node=request.scenario_tree.root, **base)
    assert exc.value.code == "CHIP_FH_MANAGER_STATE_INVALID"

    wrong_id = request.scenario_tree.root.model_copy(update={"node_id": "other"})
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(permanent_state=request.initial_state, node=wrong_id, **base)
    assert exc.value.code == "CHIP_FH_NODE_MISMATCH"

    wrong_gw = request.scenario_tree.root.model_copy(update={"gameweek": 3})
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(permanent_state=request.initial_state, node=wrong_gw, **base)
    assert exc.value.code == "CHIP_FH_NODE_MISMATCH"

    wrong_bundle = compile_synthetic_bundle(
        ruleset_id="OTHER",
        ruleset_version=bundle.ruleset_version,
        ruleset_hash=bundle.ruleset_hash,
        concurrency_limit=1,
        definitions=(_definition(),),
    )
    wrong_inventory = build_chip_inventory(wrong_bundle, current_gameweek=2)
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(
            normal_candidates=(normal,),
            free_hit_candidates=(free_hit,),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=wrong_bundle,
            inventory=wrong_inventory,
            token_id=wrong_inventory.tokens[0].token_id,
        )
    assert exc.value.code == "CHIP_RULESET_LINEAGE_MISMATCH"

    wrong_rules = rules.model_copy(update={"ruleset_version": "different"})
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(
            normal_candidates=(normal,),
            free_hit_candidates=(free_hit,),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=wrong_rules,
            chip_bundle=bundle,
            inventory=inventory,
            token_id=inventory.tokens[0].token_id,
        )
    assert exc.value.code == "CHIP_FH_MANAGER_STATE_INVALID"


def test_wrong_or_unavailable_token_fails_closed() -> None:
    request, rules, _, _, normal, free_hit = _direct_inputs()
    other = ChipDefinition(
        chip_key="OTHER",
        definition_version="OTHER:V1",
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
        concurrency_group="OTHER_GROUP",
        activation_route=ActivationRoute.PICK_TEAM_SAVE,
        cancellable_before_lock=True,
        effects=(ChipEffect(surface="SCORING", operation="ADD_POINTS", parameters={"points": 1}),),
    )
    bundle = compile_synthetic_bundle(
        ruleset_id=request.rules.ruleset_id,
        ruleset_version=request.rules.ruleset_version,
        ruleset_hash=request.rules.ruleset_hash,
        concurrency_limit=1,
        definitions=(_definition(), other),
    )
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    other_token = next(item for item in inventory.tokens if item.chip_key == "OTHER")
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(
            normal_candidates=(normal,),
            free_hit_candidates=(free_hit,),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=bundle,
            inventory=inventory,
            token_id=other_token.token_id,
        )
    assert exc.value.code == "CHIP_FH_TOKEN_MISMATCH"

    expired = build_chip_inventory(_bundle(request), current_gameweek=20)
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(
            normal_candidates=(normal,),
            free_hit_candidates=(free_hit,),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=_bundle(request),
            inventory=expired,
            token_id=expired.tokens[0].token_id,
        )
    assert exc.value.code == "CHIP_FH_TOKEN_UNAVAILABLE"


def test_invalid_free_hit_transition_and_candidate_hit_fail_closed() -> None:
    request, rules, bundle, inventory, normal, free_hit = _direct_inputs()
    invalid_events = dict(rules.event_rules)
    invalid_events["FREE_HIT"] = FreeTransferEventRule(
        unlimited_transfers_without_hits=False,
        earn_for_next_deadline=1,
        carry_unused=True,
    )
    invalid_rules = rules.model_copy(update={"event_rules": invalid_events})
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(
            normal_candidates=(normal,),
            free_hit_candidates=(free_hit,),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=invalid_rules,
            chip_bundle=bundle,
            inventory=inventory,
            token_id=inventory.tokens[0].token_id,
        )
    assert exc.value.code == "CHIP_FH_TRANSFER_EVENT_INVALID"

    hit_candidate = _candidate(
        request,
        policy_id="fh-hit",
        role="FREE_HIT_TEMPORARY",
        points=(30.0,),
        hit=4.0,
        transfer_count=1,
        squad=swap(base_squad(), "p07", "p15"),
        spells=tuple(f"hit-{index}" for index in range(15)),
    )
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(
            normal_candidates=(normal,),
            free_hit_candidates=(hit_candidate,),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=bundle,
            inventory=inventory,
            token_id=inventory.tokens[0].token_id,
        )
    assert exc.value.code == "CHIP_FH_TEMPORARY_HIT"


def test_free_transfer_after_mismatch_is_detected() -> None:
    request, rules, bundle, inventory, normal, free_hit = _direct_inputs()
    payload = free_hit.model_dump(mode="python")
    payload["free_transfers_after"] = 2
    payload["candidate_hash"] = "0" * 64
    raw = payload.copy()
    raw.pop("candidate_hash")
    payload["candidate_hash"] = semantic_sha256(raw)
    mismatched = type(free_hit).model_validate(payload)
    with pytest.raises(ChipError) as exc:
        evaluate_free_hit(
            normal_candidates=(normal,),
            free_hit_candidates=(mismatched,),
            permanent_state=request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            transfer_rules=rules,
            chip_bundle=bundle,
            inventory=inventory,
            token_id=inventory.tokens[0].token_id,
        )
    assert exc.value.code == "CHIP_FH_TRANSFER_TRANSITION_MISMATCH"
