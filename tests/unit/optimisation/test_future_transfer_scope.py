"""R4 root restrictions must not leak into saved-FT continuation states."""

from decimal import Decimal

import pytest

from dmf_pulse.optimisation.multi_gameweek_models import (
    ObjectiveMode,
    TransferActionScope,
    seal_request,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.optimisation.multi_gameweek_solver import (
    Stage11SearchProfile,
    apply_transfer_action,
    enumerate_legal_actions,
    observe_node,
    select_candidate,
    solve_frontier,
)
from tests.support.multi_gameweek_factories import NodeSpec, build_request
from tests.unit.optimisation.test_stage11_exact_acceleration import _ExactSurrogate

LINEAR_ASSUMPTIONS = tuple(
    sorted(
        (
            "DETERMINISTIC_NO_NEW_INFORMATION_REVELATION_V1",
            "EXPECTED_THREE_GAMEWEEK_POINTS_WITH_LEGAL_RECOURSE",
            "FUTURE_PRICE_CHANGES_NOT_MODELLED_IN_PRIVATE_3GW_V1",
            "NO_CHIP_EXPLICIT",
            "HORIZON_TRANSFER_COUNT_FRONTIER_V1",
            "THREE_GAMEWEEK_ZERO_TERMINAL_VALUE_AFTER_HORIZON",
        )
    )
)


def scoped_request(ft=1):
    request = build_request(
        (NodeSpec("root", 1), NodeSpec("next", 2, "root"), NodeSpec("last", 3, "next")),
        free_transfers=ft,
        include_second_mid=True,
    )
    search = seal_search_policy(
        request.search_policy.model_copy(
            update={
                "transfer_action_scope": TransferActionScope(
                    root_maximum_transfers=min(ft, 2), continuation_mode="FREE_TRANSFERS_ONLY"
                ),
            }
        )
    )
    return seal_request(
        request.model_copy(update={"search_policy": search, "assumptions": LINEAR_ASSUMPTIONS})
    )


def actions(request, state, node):
    return enumerate_legal_actions(
        state,
        node=node,
        candidate_pool=request.candidate_pool,
        rules=request.rules,
        policy=request.search_policy,
    )


@pytest.mark.parametrize("ft", [0, 1, 2, 5])
def test_root_and_continuation_scope_follow_ft_inventory(ft):
    request = scoped_request(ft)
    root, future, _ = request.scenario_tree.nodes
    roots = actions(request, request.initial_state, root)
    assert {a.transfer_count for a in roots} == set(range(min(ft, 2) + 1))
    for count in range(min(ft, 2) + 1):
        action = next(a for a in roots if a.transfer_count == count)
        transition = apply_transfer_action(
            request.initial_state,
            action,
            node=root,
            candidate_pool=request.candidate_pool,
            rules=request.rules,
        )
        state = observe_node(transition.state, node=future)
        assert state.free_transfers == min(ft - count + 1, request.rules.maximum_free_transfers)
        assert {a.transfer_count for a in actions(request, state, future)} == set(
            range(min(state.free_transfers, 2) + 1)
        )


def test_r2_acceleration_equals_generic_for_state_dependent_scope():
    request = scoped_request()
    generic = solve_frontier(request, _ExactSurrogate())
    profile = Stage11SearchProfile()
    accelerated = solve_frontier(
        request, _ExactSurrogate(), prefer_deterministic_linear=True, profile=profile
    )
    assert profile.fast_path_used
    assert generic.complete and accelerated.complete
    assert generic.candidates == accelerated.candidates


def test_absent_scope_keeps_legacy_policy_serialization():
    request = build_request((NodeSpec("root", 1),))
    assert "transfer_action_scope" not in request.search_policy.model_dump(mode="json")


class _PairEvaluator(_ExactSurrogate):
    @staticmethod
    def _value(node, squad_ids):
        points = (
            (5 if "p16" in squad_ids else 0)
            if node.parent_id is None
            else (20 if {"p15", "p19"} <= set(squad_ids) else 0)
        )
        return _ExactSurrogate._value(node, squad_ids).model_copy(
            update={
                "expected_points": Decimal(points),
                "p10_points": Decimal(points),
                "p90_points": Decimal(points),
            }
        )


def test_saved_ft_can_enable_two_move_optimum_and_change_root_choice():
    incoming = ("p15", "p16", "p19")
    request = build_request(
        (
            NodeSpec(
                "root",
                1,
                allowed_transfer_in_ids=incoming,
                purchasable={"p15": False, "p19": False},
            ),
            NodeSpec("next", 2, "root", allowed_transfer_in_ids=incoming),
            NodeSpec("last", 3, "next", allowed_transfer_in_ids=incoming),
        ),
        include_second_mid=True,
    )
    search = seal_search_policy(
        request.search_policy.model_copy(
            update={
                "transfer_action_scope": TransferActionScope(
                    root_maximum_transfers=1, continuation_mode="FREE_TRANSFERS_ONLY"
                )
            }
        )
    )
    request = seal_request(request.model_copy(update={"search_policy": search}))
    new = solve_frontier(request, _PairEvaluator(), prefer_deterministic_linear=True)
    oracle = solve_frontier(request, _PairEvaluator())
    assert new.complete and oracle.complete and new.candidates == oracle.candidates
    winner = select_candidate(new.candidates, mode=ObjectiveMode.EXPECTED)
    assert winner.root_action.transfer_count == 0
    assert winner.decisions[1].action.transfer_count == 2
    old_policy = seal_search_policy(search.model_copy(update={"max_transfers_per_node": 1}))
    old = solve_frontier(
        seal_request(request.model_copy(update={"search_policy": old_policy})),
        _PairEvaluator(),
        prefer_deterministic_linear=True,
    )
    assert (
        select_candidate(old.candidates, mode=ObjectiveMode.EXPECTED).root_action.transfer_count
        == 1
    )
    from dmf_pulse.private_v1.rolling import _one_gameweek_comparison

    immediate = select_candidate(old.candidates, mode=ObjectiveMode.EXPECTED).root_action
    result = optimise_multi_gameweek(
        request, evaluator=_PairEvaluator(), root_action_counterfactual=immediate
    )
    counter = result.root_action_counterfactual_plan
    chosen = result.recommended_plan
    assert counter is not None and chosen is not None
    comparison = _one_gameweek_comparison(
        counter,
        chosen,
        counter,
        request=request,
        element_by_player={p.player_id: i + 1 for i, p in enumerate(request.candidate_pool)},
    )
    assert comparison.actions_differ
    assert comparison.current_gameweek_points_difference == -5
    assert comparison.free_transfers_entering_next_difference == 1
    assert comparison.total_horizon_utility_difference > 0


class _ActionEvaluator(_ExactSurrogate):
    @staticmethod
    def _value(node, squad_ids):
        points = (
            (4 * ("p15" in squad_ids) + 3 * ("p19" in squad_ids))
            if node.parent_id is None
            else (10 * ("p19" in squad_ids))
        )
        return _ExactSurrogate._value(node, squad_ids).model_copy(
            update={
                "expected_points": Decimal(points),
                "p10_points": Decimal(points),
                "p90_points": Decimal(points),
            }
        )


def test_actual_action_counterfactual_is_not_same_count_winner():
    from dmf_pulse.private_v1.rolling import _one_gameweek_comparison

    specs = (
        NodeSpec("root", 1, allowed_transfer_in_ids=("p15", "p19")),
        NodeSpec(
            "next", 2, "root", allowed_transfer_in_ids=("p15", "p19"), purchasable={"p19": False}
        ),
        NodeSpec(
            "last", 3, "next", allowed_transfer_in_ids=("p15", "p19"), purchasable={"p19": False}
        ),
    )
    one_request = build_request(specs[:1], include_second_mid=True, max_transfers_per_node=1)
    request = build_request(specs, include_second_mid=True, max_transfers_per_node=1)
    one = optimise_multi_gameweek(one_request, evaluator=_ActionEvaluator()).recommended_plan
    assert one is not None
    result = optimise_multi_gameweek(
        request,
        evaluator=_ActionEvaluator(),
        prefer_deterministic_linear=True,
        root_action_counterfactual=one.current_action.action,
    )
    counter = result.root_action_counterfactual_plan
    winner = result.recommended_plan
    assert counter is not None and winner is not None
    assert (
        winner.current_action.action.transfer_count == one.current_action.action.transfer_count == 1
    )
    assert (
        counter.current_action.action == one.current_action.action != winner.current_action.action
    )
    comparison = _one_gameweek_comparison(
        one,
        winner,
        counter,
        request=request,
        element_by_player={p.player_id: i + 1 for i, p in enumerate(request.candidate_pool)},
    )
    assert comparison.actions_differ
    assert comparison.current_gameweek_points_difference == -1
    assert comparison.future_gameweek_points_difference == 20
    assert comparison.total_horizon_utility_difference == 19
    assert comparison.counterfactual_horizon_utility == 4
    same = _one_gameweek_comparison(
        one,
        counter,
        counter,
        request=request,
        element_by_player={p.player_id: i + 1 for i, p in enumerate(request.candidate_pool)},
    )
    assert not same.actions_differ and same.total_horizon_utility_difference == 0
    assert same.current_gameweek_points_difference == same.future_gameweek_points_difference == 0
    from dmf_pulse.private_v1.errors import PrivateV1Error

    with pytest.raises(PrivateV1Error, match="counterfactual root action differs"):
        _one_gameweek_comparison(one, winner, winner, request=request, element_by_player={})
    payload = comparison.model_dump(mode="python")
    payload["counterfactual_action_matches_one_gameweek_action"] = False
    with pytest.raises(ValueError, match="actual one-GW root action"):
        type(comparison).model_validate(payload)


def test_explicit_rules_bounded_continuation_preserves_paid_transfers():
    request = scoped_request()
    scope = request.search_policy.transfer_action_scope.model_copy(
        update={"continuation_mode": "RULES_BOUNDED"}
    )
    policy = seal_search_policy(
        request.search_policy.model_copy(update={"transfer_action_scope": scope})
    )
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    root, future, _ = request.scenario_tree.nodes
    root_action = next(
        a for a in actions(request, request.initial_state, root) if a.transfer_count == 1
    )
    first = apply_transfer_action(
        request.initial_state,
        root_action,
        node=root,
        candidate_pool=request.candidate_pool,
        rules=request.rules,
    )
    state = observe_node(first.state, node=future)
    assert state.free_transfers == 1
    second = next(a for a in actions(request, state, future) if a.transfer_count == 2)
    transition = apply_transfer_action(
        state, second, node=future, candidate_pool=request.candidate_pool, rules=request.rules
    )
    assert transition.free_transfer_arc.paid_transfers == 1
    assert transition.free_transfer_arc.hit_points == request.rules.hit_cost_per_paid_transfer


@pytest.mark.parametrize("bank", [0, 5, 10])
def test_future_affordability_and_cohort_prices_use_the_same_exact_transition(bank):
    from dmf_pulse.optimisation.manager_state import seal_manager_state

    request = scoped_request()
    root, future, _ = request.scenario_tree.nodes
    hold = next(a for a in actions(request, request.initial_state, root) if a.transfer_count == 0)
    moved = apply_transfer_action(
        request.initial_state,
        hold,
        node=root,
        candidate_pool=request.candidate_pool,
        rules=request.rules,
    )
    state = observe_node(moved.state, node=future)
    state = seal_manager_state(state.model_copy(update={"bank_tenths": bank}))
    ordinary = actions(request, state, future)
    checked = enumerate_legal_actions(
        state,
        node=future,
        candidate_pool=request.candidate_pool,
        rules=request.rules,
        policy=request.search_policy,
        precheck_economics=True,
    )
    assert ordinary == checked
    for action in checked:
        transition = apply_transfer_action(
            state, action, node=future, candidate_pool=request.candidate_pool, rules=request.rules
        )
        assert transition.free_transfer_arc.hit_points == 0
        assert transition.state.bank_tenths >= 0


@pytest.mark.parametrize("incomplete", [False, True])
def test_counterfactual_fails_closed_for_absent_action_or_incomplete_family(
    monkeypatch, incomplete
):
    from dataclasses import replace

    import dmf_pulse.optimisation.multi_gameweek_service as service

    request = build_request((NodeSpec("root", 1),))
    frontier = solve_frontier(request, _ExactSurrogate())
    action = next(c.root_action for c in frontier.candidates if c.root_action.transfer_count == 1)
    if incomplete:
        frontier = replace(frontier, complete=False)
    else:
        frontier = replace(
            frontier, candidates=tuple(c for c in frontier.candidates if c.root_action != action)
        )
    monkeypatch.setattr(service, "solve_frontier", lambda *args, **kwargs: frontier)
    result = service.optimise_multi_gameweek(
        request, evaluator=_ExactSurrogate(), root_action_counterfactual=action
    )
    assert result.status.value != "SUCCESS"
    assert result.root_action_counterfactual_plan is None
    assert result.recommended_plan is None


class _TieEvaluator(_ExactSurrogate):
    @staticmethod
    def _value(node, squad_ids):
        return _ExactSurrogate._value(node, squad_ids).model_copy(
            update={
                "expected_points": Decimal(0),
                "p10_points": Decimal(0),
                "p90_points": Decimal(0),
            }
        )


def test_replay_rejects_a_plan_outside_the_root_scope():
    from dmf_pulse.optimisation.multi_gameweek_solver import validate_plan

    request = build_request((NodeSpec("root", 1),))
    action = next(
        a
        for a in actions(request, request.initial_state, request.scenario_tree.root)
        if a.transfer_count == 1
    )
    plan = optimise_multi_gameweek(
        request, evaluator=_ExactSurrogate(), root_action_counterfactual=action
    ).root_action_counterfactual_plan
    assert plan is not None
    policy = seal_search_policy(
        request.search_policy.model_copy(
            update={
                "transfer_action_scope": TransferActionScope(
                    root_maximum_transfers=0, continuation_mode="FREE_TRANSFERS_ONLY"
                )
            }
        )
    )
    restricted = seal_request(request.model_copy(update={"search_policy": policy}))
    with pytest.raises(ValueError, match="declared root or continuation action scope"):
        validate_plan(restricted, plan, evaluator=_ExactSurrogate())


def test_scope_respects_existing_unlimited_and_reset_event_rules():
    from dmf_pulse.optimisation.multi_gameweek_solver import maximum_transfer_count

    request = scoped_request()
    future = request.scenario_tree.nodes[1]
    for event_name, rule in request.rules.event_rules.items():
        node = future.model_copy(update={"transition_event": event_name})
        maximum = min(
            request.search_policy.max_transfers_per_node, request.rules.max_transfers_per_deadline
        )
        expected = (
            maximum
            if rule.unlimited_transfers_without_hits
            else min(
                maximum,
                rule.reset_before
                if rule.reset_before is not None
                else request.initial_state.free_transfers,
            )
        )
        assert (
            maximum_transfer_count(
                request.initial_state, node=node, rules=request.rules, policy=request.search_policy
            )
            == expected
        )


def test_ties_are_deterministic_and_two_available_transfers_are_not_forced():
    request = scoped_request()
    generic = solve_frontier(request, _TieEvaluator())
    fast = solve_frontier(request, _TieEvaluator(), prefer_deterministic_linear=True)
    left = select_candidate(generic.candidates, mode=ObjectiveMode.EXPECTED)
    right = select_candidate(fast.candidates, mode=ObjectiveMode.EXPECTED)
    assert left == right
    assert all(decision.action.transfer_count == 0 for decision in left.decisions)


def test_saved_ft_pair_releases_club_slot_and_uses_cohort_sale_prices():
    from dmf_pulse.optimisation.manager_state import seal_manager_state

    request = build_request(
        (NodeSpec("root", 1), NodeSpec("next", 2, "root")),
        root_prices={"p07": 55, "p15": 51, "p16": 51},
        purchase_prices={"p07": 50},
    )
    catalog = tuple(
        item.model_copy(update={"club_id": "full-club"})
        if item.player_id in {"p00", "p02", "p07", "p16"}
        else item
        for item in request.candidate_pool
    )
    clubs = {item.player_id: item.club_id for item in catalog}
    initial = seal_manager_state(
        request.initial_state.model_copy(
            update={
                "ownership_spells": tuple(
                    spell.model_copy(update={"club_id": clubs[spell.player_id]})
                    for spell in request.initial_state.ownership_spells
                )
            }
        )
    )
    search = seal_search_policy(
        request.search_policy.model_copy(
            update={
                "transfer_action_scope": TransferActionScope(
                    root_maximum_transfers=1, continuation_mode="FREE_TRANSFERS_ONLY"
                )
            }
        )
    )
    request = seal_request(
        request.model_copy(
            update={"initial_state": initial, "candidate_pool": catalog, "search_policy": search}
        )
    )
    root, future = request.scenario_tree.nodes
    hold = next(a for a in actions(request, initial, root) if a.transfer_count == 0)
    state = observe_node(
        apply_transfer_action(
            initial, hold, node=root, candidate_pool=catalog, rules=request.rules
        ).state,
        node=future,
    )
    legal = actions(request, state, future)
    pair = next(
        a for a in legal if a.transfers_out == ("p07", "p12") and a.transfers_in == ("p15", "p16")
    )
    assert not any(a.transfers_out == ("p12",) and a.transfers_in == ("p16",) for a in legal)
    result = apply_transfer_action(
        state, pair, node=future, candidate_pool=catalog, rules=request.rules
    )
    assert {p.player_id: p.price_tenths for p in result.selling_prices} == {"p07": 52, "p12": 50}
    assert result.state.bank_tenths == 0
    assert result.free_transfer_arc.hit_points == 0
    assert (
        next(s for s in result.state.active_spells if s.player_id == "p15").purchase_price_tenths
        == 51
    )
