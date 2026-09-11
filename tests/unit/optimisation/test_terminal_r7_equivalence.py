"""Terminal-only economic equivalence must not weaken complete-history replay."""

from decimal import Decimal

import pytest

from dmf_pulse.optimisation.manager_state import seal_manager_state
from dmf_pulse.optimisation.multi_gameweek_models import seal_request, seal_search_policy
from dmf_pulse.optimisation.multi_gameweek_solver import (
    DeterministicLinearExactEnumerator,
    apply_transfer_action,
    make_transfer_action,
    observe_node,
    solve_frontier,
    terminal_coalescing_eligible,
    terminal_decision_fingerprint,
)
from tests.unit.private_v1.horizon_oracle_support import HorizonPointsEvaluator, oracle_fixture


def setup_terminal():
    request, _, _, points = oracle_fixture()
    node = request.scenario_tree.nodes[-1]
    state = request.initial_state
    for predecessor in request.scenario_tree.nodes[:-1]:
        state = observe_node(state, node=predecessor)
        state = apply_transfer_action(
            state,
            make_transfer_action(transfers_out=(), transfers_in=(), event="NORMAL"),
            node=predecessor,
            candidate_pool=request.candidate_pool,
            rules=request.rules,
        ).state
    state = observe_node(state, node=node)
    return request, node, state, points


def with_purchase(state, purchase):
    return seal_manager_state(
        state.model_copy(
            update={
                "ownership_spells": tuple(
                    s.model_copy(update={"purchase_price_tenths": purchase})
                    if s.player_id == "p07"
                    else s
                    for s in state.ownership_spells
                )
            }
        )
    )


def test_same_sale_different_purchase_coalesces_and_replays_real_history():
    request, node, state, points = setup_terminal()
    other = with_purchase(state, 51)
    assert state.state_sha256 != other.state_sha256
    assert terminal_coalescing_eligible(request, node)
    assert terminal_decision_fingerprint(
        state, node, request.rules
    ) == terminal_decision_fingerprint(other, node, request.rules)
    solver = DeterministicLinearExactEnumerator(request, HorizonPointsEvaluator(points))
    first = solver._enumerate_node(node.node_id, state)
    before = solver.counters.state_expansions
    second = solver._enumerate_node(node.node_id, other)
    assert solver.counters.state_expansions == before
    assert [(p.tie_key, p.expected_score, p.conservative_score, p.upside_score) for p in first] == [
        (p.tie_key, p.expected_score, p.conservative_score, p.upside_score) for p in second
    ]
    for candidate in second:
        decision = candidate.decisions[0]
        assert decision.state_before_sha256 == other.state_sha256
        # The caller's ownership history, not the cached history, is retained/closed.
        assert (
            next(
                s
                for s in decision.state_after.ownership_spells
                if s.spell_id == other.active_by_player["p07"].spell_id
            ).purchase_price_tenths
            == 51
        )


@pytest.mark.parametrize("change", ["sale", "bank", "ft", "squad", "scope"])
def test_terminal_fingerprint_separates_decision_semantics(change):
    request, node, state, _ = setup_terminal()
    other, other_node = state, node
    if change == "sale":
        other = with_purchase(state, 48)
    elif change == "bank":
        other = seal_manager_state(state.model_copy(update={"bank_tenths": state.bank_tenths + 1}))
    elif change == "ft":
        other = seal_manager_state(
            state.model_copy(update={"free_transfers": state.free_transfers + 1})
        )
    elif change == "squad":
        other = seal_manager_state(
            state.model_copy(
                update={
                    "ownership_spells": tuple(
                        s.model_copy(update={"player_id": "p15"}) if s.player_id == "p14" else s
                        for s in state.ownership_spells
                    )
                }
            )
        )
    else:
        other_node = node.model_copy(
            update={"allowed_transfer_in_ids": node.allowed_transfer_in_ids[:-1]}
        )
    assert terminal_decision_fingerprint(
        state, node, request.rules
    ) != terminal_decision_fingerprint(other, other_node, request.rules)


def test_terminal_specialisation_falls_back_outside_proof():
    request, node, _, _ = setup_terminal()
    assert not terminal_coalescing_eligible(request, request.scenario_tree.root)
    terminal = request.terminal_policy.model_copy(
        update={"enabled": True, "bank_points_per_tenth": Decimal(1)}
    )
    assert not terminal_coalescing_eligible(
        request.model_copy(update={"terminal_policy": terminal}), node
    )
    policy = seal_search_policy(
        request.search_policy.model_copy(update={"transfer_action_scope": None})
    )
    assert not terminal_coalescing_eligible(
        seal_request(request.model_copy(update={"search_policy": policy})), node
    )


def test_closed_history_coalesces_but_replay_preserves_closed_spell():
    request, node, state, points = setup_terminal()
    catalog_entry = next(p for p in request.candidate_pool if p.player_id == "p15")
    closed = state.active_spells[0].model_copy(
        update={
            "player_id": "p15",
            "club_id": catalog_entry.club_id,
            "position": catalog_entry.position,
            "spell_id": "closed-only",
            "ended_gameweek": 1,
            "ended_at_node_id": "historical",
            "realised_selling_price_tenths": 50,
        }
    )
    other = seal_manager_state(
        state.model_copy(
            update={
                "ownership_spells": tuple(
                    sorted(
                        (*state.ownership_spells, closed),
                        key=lambda s: (s.player_id, s.started_gameweek, s.spell_id),
                    )
                )
            }
        )
    )
    solver = DeterministicLinearExactEnumerator(request, HorizonPointsEvaluator(points))
    solver._enumerate_node(node.node_id, state)
    before = solver.counters.state_expansions
    replay = solver._enumerate_node(node.node_id, other)
    assert solver.counters.state_expansions == before
    assert all(closed in p.decisions[0].state_after.ownership_spells for p in replay)


@pytest.mark.parametrize("case", ["root", "future", "budget", "club"])
@pytest.mark.parametrize("purchase", [50, 51])
def test_terminal_acceleration_complete_candidates_equal_generic(case, purchase):
    request, _, _, points = oracle_fixture(case)
    request = seal_request(
        request.model_copy(update={"initial_state": with_purchase(request.initial_state, purchase)})
    )
    generic = solve_frontier(request, HorizonPointsEvaluator(points))
    accelerated = solve_frontier(
        request, HorizonPointsEvaluator(points), prefer_deterministic_linear=True
    )
    assert generic.complete and accelerated.complete
    assert accelerated.candidates == generic.candidates
