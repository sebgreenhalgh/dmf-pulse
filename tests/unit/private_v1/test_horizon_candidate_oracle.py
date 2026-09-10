"""Targeted full-universe oracle evidence is not a global optimality claim."""

import pytest

from dmf_pulse.optimisation.multi_gameweek_models import ObjectiveMode
from dmf_pulse.optimisation.multi_gameweek_solver import (
    Stage11SearchProfile,
    select_candidate,
    solve_frontier,
)
from dmf_pulse.private_v1.service import (
    _bounded_private_incoming_ids,
    _horizon_private_incoming_ids,
)
from tests.unit.private_v1.horizon_oracle_support import (
    HorizonPointsEvaluator,
    oracle_fixture,
    with_candidates,
)


@pytest.mark.parametrize("case", ["root", "future", "budget", "club"])
def test_horizon_screen_matches_complete_universe_oracle_and_preserves_fast_path(case):
    full, incoming, projections, points = oracle_fixture(case)
    catalog = {p.player_id: p for p in full.candidate_pool}
    prices = full.scenario_tree.root.prices
    screen = _horizon_private_incoming_ids(
        incoming, catalog=catalog, prices=prices, gameweeks=projections, maximum_transfers=1
    )
    bounded = with_candidates(full, screen.retained_incoming_ids)
    profile = Stage11SearchProfile()
    fast = solve_frontier(
        bounded, HorizonPointsEvaluator(points), prefer_deterministic_linear=True, profile=profile
    )
    generic = solve_frontier(bounded, HorizonPointsEvaluator(points))
    complete = solve_frontier(full, HorizonPointsEvaluator(points))
    assert profile.fast_path_used
    assert fast.complete and generic.complete and complete.complete
    assert fast.candidates == generic.candidates
    winner = select_candidate(fast.candidates, mode=ObjectiveMode.EXPECTED)
    oracle = select_candidate(complete.candidates, mode=ObjectiveMode.EXPECTED)
    assert winner.root_action == oracle.root_action
    assert (winner.expected_score, winner.conservative_score, winner.upside_score) == (
        oracle.expected_score,
        oracle.conservative_score,
        oracle.upside_score,
    )
    # Observed scope binds information, state and derived spell identities. Compare every
    # non-identity field, including complete ownership-cohort economics and tactical values.
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
    assert tuple(d.model_dump(exclude=excluded) for d in winner.decisions) == tuple(
        d.model_dump(exclude=excluded) for d in oracle.decisions
    )
    assert "p22" in screen.retained_incoming_ids
    if case == "root":
        assert "p22" in winner.root_action.transfers_in
        old, _ = _bounded_private_incoming_ids(
            incoming, catalog=catalog, prices=prices, gameweek=projections[0], maximum_transfers=1
        )
        previous = solve_frontier(
            with_candidates(full, old),
            HorizonPointsEvaluator(points),
            prefer_deterministic_linear=True,
        )
        old_winner = select_candidate(previous.candidates, mode=ObjectiveMode.EXPECTED)
        assert old_winner.root_action != winner.root_action
        assert old_winner.expected_score < winner.expected_score
    if case == "future":
        assert winner.root_action.transfer_count == 0
        assert winner.decisions[1].action.transfer_count == 2
        assert "p22" in winner.decisions[1].action.transfers_in
    if case in {"budget", "club"}:
        assert any("p21" in d.action.transfers_in for d in winner.decisions)
        assert any("p22" in d.action.transfers_in for d in winner.decisions)
