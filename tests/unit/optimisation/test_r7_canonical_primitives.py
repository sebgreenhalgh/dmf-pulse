"""Canonical verification remains exact when immutable interpretation is reused."""

from dataclasses import replace
from itertools import permutations

import pytest

from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.optimisation.autosub_evaluator import CanonicalScenarioPrimitives
from dmf_pulse.optimisation.tactics import ExactTacticalNodeKernel, evaluate_tactical_configuration
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import synthetic_ruleset
from tests.unit.optimisation.test_stage10_batch import _players, _policy, _scenarios, _squads


def test_canonical_reused_primitives_preserve_all_scores_events_hashes_and_reject_wrong_context():
    players = {p.player_id: p for p in _players()}
    scenarios = _scenarios(tuple(players))
    rules = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    kernel = ExactTacticalNodeKernel(scenarios=scenarios, players=players, rules=rules)
    context = CanonicalScenarioPrimitives(scenarios, players, rules)
    # Fill unrelated entries to force physical LRU eviction, never a skipped solve.
    for i in range(4096):
        context.resolutions[((f"unused-{i}",), (), frozenset())] = ()
    for squad in _squads():
        plan, _, _, _ = kernel.optimise(squad, _policy())
        tactic = plan.tactical_configuration
        original = evaluate_tactical_configuration(squad, tactic, scenarios, players, rules)
        assert (
            evaluate_tactical_configuration(
                squad, tactic, scenarios, players, rules, primitives=context
            )
            == original
        )
        assert (
            evaluate_tactical_configuration(
                squad, tactic, scenarios, players, rules, primitives=context
            )
            == original
        )
        with pytest.raises(ValueError, match="different sealed node"):
            evaluate_tactical_configuration(
                squad, tactic, scenarios, dict(players), rules, primitives=context
            )
    assert len(context.resolutions) == 4096
    assert (("unused-0",), (), frozenset()) not in context.resolutions


def test_packed_bench_lanes_do_not_overflow_or_borrow_for_large_signed_numerators():
    players = {p.player_id: p for p in _players()}
    rules = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    kernel = ExactTacticalNodeKernel(
        scenarios=_scenarios(tuple(players)), players=players, rules=rules
    )
    squad = _squads()[0]
    states, indexes = kernel._squad_appearance_states(squad)
    states = tuple(
        replace(
            s,
            weighted_player_point_numerators=tuple(
                ((-1) ** (i + j)) * ((1 << 512) + v)
                for j, v in enumerate(s.weighted_player_point_numerators)
            ),
        )
        for i, s in enumerate(states)
    )
    bench = ("p06", "p11", "p14")
    starting = tuple(
        p
        for p in squad.player_ids
        if p not in bench and players[p].position is not PlayerPosition.GK
    )
    kwargs = {
        "starting_outfield": starting,
        "bench_orders": tuple(permutations(bench)),
        "appearance_states": states,
        "local_player_index": indexes,
    }
    for i in range(4096):
        kernel._bench_values_cache[((f"unused-{i}",), kwargs["bench_orders"])] = (0,) * 6
    assert kernel._bench_order_objective_numerators(
        **kwargs
    ) == kernel._reference_bench_order_objective_numerators(**kwargs)
    assert len(kernel._bench_values_cache) == 4096
    assert (("unused-0",), kwargs["bench_orders"]) not in kernel._bench_values_cache


def test_direct_captain_pair_initialisation_is_exact_and_empty_xi_fails_closed():
    players = {p.player_id: p for p in _players()}
    rules = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    kernel = ExactTacticalNodeKernel(
        scenarios=_scenarios(tuple(players)), players=players, rules=rules
    )
    xi = _squads()[0].player_ids[:11]
    values = {
        (captain, vice): kernel._captain_bonus_numerator(captain, vice)
        for captain, vice in permutations(xi, 2)
    }
    best = max(values.values())
    assert kernel._best_captains(xi) == (
        best,
        tuple(sorted(pair for pair, value in values.items() if value == best)),
    )
    with pytest.raises(ValueError, match="no captain pair"):
        kernel._best_captains(())
