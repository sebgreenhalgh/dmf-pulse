"""R6 node-scoped fast/generic and complete-universe economic differentials."""

import pytest

from dmf_pulse.optimisation.multi_gameweek_models import (
    ObjectiveMode,
    seal_request,
    seal_scenario_tree,
)
from dmf_pulse.optimisation.multi_gameweek_solver import (
    Stage11SearchProfile,
    information_set_key,
    select_candidate,
    solve_frontier,
)
from dmf_pulse.private_v1.horizon_candidates import bounded_horizon_screen
from dmf_pulse.private_v1.service import _bounded_private_incoming_ids
from tests.unit.private_v1.horizon_oracle_support import (
    HorizonPointsEvaluator,
    oracle_fixture,
    with_candidates,
)


def with_node_candidates(request, incoming_by_node):
    nodes = []
    for original, incoming in zip(request.scenario_tree.nodes, incoming_by_node, strict=True):
        node = original.model_copy(update={"allowed_transfer_in_ids": tuple(sorted(incoming))})
        node = node.model_copy(
            update={
                "information_set_key": information_set_key(
                    node,
                    parent_key=nodes[-1].information_set_key if nodes else None,
                )
            }
        )
        nodes.append(node)
    tree = seal_scenario_tree(request.scenario_tree.model_copy(update={"nodes": tuple(nodes)}))
    return seal_request(
        request.model_copy(
            update={
                "scenario_tree": tree,
                "assumptions": tuple(
                    sorted(set(request.assumptions) | {"SEALED_NODE_SPECIFIC_CANDIDATE_SCOPE_V1"})
                ),
            }
        )
    )


@pytest.mark.parametrize("case", ["root", "future", "budget", "club", "positional"])
def test_v3_matches_generic_full_universe_with_exact_node_specific_fast_path(case):
    full, incoming, projections, points = oracle_fixture("budget" if case == "positional" else case)
    if case == "positional":
        from dmf_pulse.fpl_points.models import PlayerPosition

        full = seal_request(
            full.model_copy(
                update={
                    "candidate_pool": tuple(
                        p.model_copy(update={"position": PlayerPosition.DEF})
                        if p.player_id == "p21"
                        else p
                        for p in full.candidate_pool
                    )
                }
            )
        )
    legacy, _ = _bounded_private_incoming_ids(
        incoming,
        catalog={p.player_id: p for p in full.candidate_pool},
        prices=full.scenario_tree.root.prices,
        gameweek=projections[0],
        maximum_transfers=1,
    )
    one = with_candidates(full, legacy)
    one = seal_request(
        one.model_copy(
            update={
                "scenario_tree": seal_scenario_tree(
                    one.scenario_tree.model_copy(update={"nodes": (one.scenario_tree.root,)})
                )
            }
        )
    )
    actual_one_gw = select_candidate(
        solve_frontier(one, HorizonPointsEvaluator(points)).candidates,
        mode=ObjectiveMode.EXPECTED,
    ).root_action
    screen = bounded_horizon_screen(
        incoming,
        catalog={p.player_id: p for p in full.candidate_pool},
        prices=full.scenario_tree.root.prices,
        gameweeks=projections,
        protected_incoming_ids=actual_one_gw.transfers_in,
    )
    request = with_node_candidates(full, tuple(n.retained_incoming_ids for n in screen.nodes))
    profile = Stage11SearchProfile()
    fast = solve_frontier(
        request, HorizonPointsEvaluator(points), prefer_deterministic_linear=True, profile=profile
    )
    generic = solve_frontier(request, HorizonPointsEvaluator(points))
    complete = solve_frontier(full, HorizonPointsEvaluator(points))
    assert profile.fast_path_used
    assert fast.complete and generic.complete and complete.complete
    assert fast.candidates == generic.candidates
    winner = select_candidate(fast.candidates, mode=ObjectiveMode.EXPECTED)
    oracle = select_candidate(complete.candidates, mode=ObjectiveMode.EXPECTED)
    assert winner.root_action == oracle.root_action
    excluded = {
        "information_set_key": True,
        "state_before_sha256": True,
        "state_after": {
            "state_id": True,
            "parent_state_id": True,
            "state_sha256": True,
            "ownership_spells": {"__all__": {"spell_id"}},
        },
    }
    assert winner.expected_score == oracle.expected_score
    assert tuple(d.model_dump(exclude=excluded) for d in winner.decisions) == tuple(
        d.model_dump(exclude=excluded) for d in oracle.decisions
    )
    assert any("p22" in d.action.transfers_in for d in winner.decisions)
    if case == "root":
        assert "p22" in winner.root_action.transfers_in
    if case == "future":
        assert winner.root_action.transfer_count == 0
        assert winner.decisions[1].action.transfer_count == 2
    if case in {"budget", "club", "positional"}:
        assert any("p21" in d.action.transfers_in for d in winner.decisions)
    # The exact pinned one-GW action remains a root action, not a representative at its count.
    left = select_candidate(
        tuple(p for p in fast.candidates if p.root_action == actual_one_gw),
        mode=ObjectiveMode.EXPECTED,
    )
    right = select_candidate(
        tuple(p for p in complete.candidates if p.root_action == actual_one_gw),
        mode=ObjectiveMode.EXPECTED,
    )
    assert left.expected_score == right.expected_score


def test_node_candidate_membership_binds_information_and_request_hashes():
    request, incoming, _, _ = oracle_fixture()
    changed = with_node_candidates(request, (incoming, incoming[:-1], incoming))
    assert changed.request_sha256 != request.request_sha256
    assert (
        changed.scenario_tree.nodes[0].information_set_key
        == request.scenario_tree.nodes[0].information_set_key
    )
    assert all(
        a.information_set_key != b.information_set_key
        for a, b in zip(
            changed.scenario_tree.nodes[1:], request.scenario_tree.nodes[1:], strict=True
        )
    )


def test_inherited_action_guard_fails_before_expensive_tactical_batch():
    from dmf_pulse.optimisation.multi_gameweek_errors import ResourceLimitReached
    from dmf_pulse.optimisation.multi_gameweek_models import seal_search_policy

    request, incoming, _, points = oracle_fixture()
    request = with_node_candidates(request, (incoming, incoming[:-1], incoming))
    policy = seal_search_policy(
        request.search_policy.model_copy(update={"max_actions_per_state": 1})
    )
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    evaluator = HorizonPointsEvaluator(points)
    with pytest.raises(ResourceLimitReached, match="max_actions_per_state"):
        solve_frontier(request, evaluator, prefer_deterministic_linear=True)
    assert not evaluator.cache
