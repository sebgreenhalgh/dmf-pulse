"""Hostile exact sufficient-state factoring and captain-pair reuse checks."""

from itertools import permutations

import pytest

from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.optimisation.tactics import (
    ExactTacticalNodeKernel,
    optimise_fixed_squad_tactics_exact,
)
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import synthetic_ruleset
from tests.unit.optimisation.test_stage10_batch import _players, _policy, _scenarios, _squads


@pytest.mark.parametrize("all_zero", [False, True])
def test_r7_preserves_whole_plan_distribution_hash_and_all_ties(all_zero):
    players = {p.player_id: p for p in _players()}
    scenarios = _scenarios(tuple(players))
    if all_zero:
        scenarios = tuple(
            s.model_copy(update={"player_points": {p: 0 for p in players}}) for s in scenarios
        )
    rules = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    kernel = ExactTacticalNodeKernel(scenarios=scenarios, players=players, rules=rules)
    for squad in reversed(_squads()):
        reference = optimise_fixed_squad_tactics_exact(squad, scenarios, players, rules, _policy())
        assert kernel.optimise(squad, _policy()) == reference
        assert kernel.optimise(squad, _policy()) == reference


def test_bench_sufficient_state_matches_original_for_each_order_and_goalkeeper_projection():
    players = {p.player_id: p for p in _players()}
    rules = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    kernel = ExactTacticalNodeKernel(
        scenarios=_scenarios(tuple(players)), players=players, rules=rules
    )
    squad = _squads()[0]
    states, indexes = kernel._squad_appearance_states(squad)
    bench = ("p06", "p11", "p14")
    starting = tuple(
        p
        for p in squad.player_ids
        if p not in bench and players[p].position is not PlayerPosition.GK
    )
    for orders in (tuple(permutations(bench)), tuple(reversed(tuple(permutations(bench))))):
        kwargs = {
            "starting_outfield": starting,
            "bench_orders": orders,
            "appearance_states": states,
            "local_player_index": indexes,
        }
        reference = kernel._reference_bench_order_objective_numerators(**kwargs)
        assert kernel._bench_order_objective_numerators(**kwargs) == reference
        # Same exact outfield function is reused on a cache hit, without state visits.
        before = kernel.work_snapshot()
        assert kernel._bench_order_objective_numerators(**kwargs) == reference
        assert kernel.work_snapshot() == before
