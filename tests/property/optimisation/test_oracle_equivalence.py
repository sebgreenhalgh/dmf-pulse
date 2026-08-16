"""Independent-oracle equivalence tests for the frozen OPT-010 semantics."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.optimisation.autosub_evaluator import evaluate_scenario as production_score
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidateSquad,
    OneGameweekOptimiserPolicy,
    OneGameweekRulesView,
)
from dmf_pulse.optimisation.tactics import (
    enumerate_tactical_configurations,
    evaluate_tactical_configuration,
)
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import players, request, scenario_set, synthetic_ruleset
from tests.support.optimisation_oracle import OracleTactic, evaluate_scenario, exhaustive_optimum


def _policy() -> OneGameweekOptimiserPolicy:
    return OneGameweekOptimiserPolicy(
        max_squad_candidates=12,
        max_tactical_configurations=5_000_000,
        max_scenario_score_operations=20_000_000,
        max_returned_ties=16,
    )


@settings(max_examples=100, deadline=None, derandomize=True)
@given(
    values=st.lists(st.integers(min_value=-5, max_value=20), min_size=15, max_size=15),
    appearances=st.lists(st.booleans(), min_size=15, max_size=15),
)
def test_independent_oracle_matches_every_scenario_score(
    values: list[int], appearances: list[bool]
) -> None:
    rules = synthetic_ruleset()
    view = build_one_gameweek_rules_view(rules, projection_mode=request().projection_mode)
    squad_ids = tuple(player.player_id for player in players())
    player_map = {player.player_id: player for player in players()}
    production_tactic = next(
        enumerate_tactical_configurations(
            CandidateSquad(player_ids=squad_ids), player_map, view, _policy()
        )[0]
    )
    scenario = scenario_set(
        rules.ruleset_hash,
        values=(dict(zip(squad_ids, values, strict=True)),),
        appeared_values=(dict(zip(squad_ids, appearances, strict=True)),),
    ).scenarios[0]
    oracle = evaluate_scenario(
        scenario,
        OracleTactic(
            starting_xi=production_tactic.starting_xi,
            bench_goalkeeper=production_tactic.bench_goalkeeper,
            outfield_bench_order=production_tactic.outfield_bench_order,
            captain=production_tactic.captain,
            vice_captain=production_tactic.vice_captain,
        ),
        {player_id: player.position for player_id, player in player_map.items()},
        view,
    )
    production, weighted = production_score(scenario, production_tactic, player_map, view)
    assert weighted == oracle.weighted
    assert production.manager_points == oracle.manager_points
    assert production.player_points == oracle.player_points
    assert production.captain_resolution.multiplier_player == oracle.multiplier_player
    assert production.captain_resolution.multiplier == oracle.multiplier
    assert tuple(
        (event.player_out, event.player_in, event.slot, event.position)
        for event in production.autosub_events
    ) == tuple(
        (event.player_out, event.player_in, event.slot, event.position) for event in oracle.autosubs
    )


def _toy_rules_view() -> OneGameweekRulesView:
    return OneGameweekRulesView(
        ruleset_id="oracle-toy",
        ruleset_version="1.0.0",
        ruleset_hash="0" * 64,
        projection_mode=ProjectionMode.TEST,
        squad_size=7,
        position_squad_quota={
            PlayerPosition.GK: 2,
            PlayerPosition.DEF: 2,
            PlayerPosition.MID: 2,
            PlayerPosition.FWD: 1,
        },
        starting_size=5,
        bench_size=2,
        lineup_min={
            PlayerPosition.GK: 1,
            PlayerPosition.DEF: 1,
            PlayerPosition.MID: 1,
            PlayerPosition.FWD: 1,
        },
        lineup_max={
            PlayerPosition.GK: 1,
            PlayerPosition.DEF: 2,
            PlayerPosition.MID: 2,
            PlayerPosition.FWD: 1,
        },
        initial_budget_tenths=None,
        max_players_per_club=None,
        captain_multiplier=2,
        vice_captain_fallback=True,
        auto_substitution_timing="AFTER_ALL_GAMEWEEK_FIXTURES",
        auto_substitution_zero_appearance_minutes=0,
        designated_bench_goalkeeper_if_appeared=True,
        manager_bench_order=True,
        maintain_legal_formation=True,
        capability="REFERENCE_ONLY",
    )


def test_independent_exhaustive_oracle_matches_exact_global_optimum() -> None:
    rules = synthetic_ruleset()
    squad_ids = ("p00", "p01", "p02", "p03", "p07", "p08", "p12")
    positions = {
        "p00": PlayerPosition.GK,
        "p01": PlayerPosition.GK,
        "p02": PlayerPosition.DEF,
        "p03": PlayerPosition.DEF,
        "p07": PlayerPosition.MID,
        "p08": PlayerPosition.MID,
        "p12": PlayerPosition.FWD,
    }
    player_map = {
        player_id: CandidatePlayer(
            player_id=player_id, position=position, club_id=f"club-{player_id}"
        )
        for player_id, position in positions.items()
    }
    all_ids = tuple(player.player_id for player in players())
    values = (
        {player_id: index for index, player_id in enumerate(all_ids)},
        {player_id: 30 - index for index, player_id in enumerate(all_ids)},
    )
    appeared = (
        {player_id: player_id not in {"p04", "p11", "p14"} for player_id in all_ids},
        {player_id: player_id not in {"p03", "p08", "p13"} for player_id in all_ids},
    )
    scenarios = scenario_set(
        rules.ruleset_hash,
        values=values,
        appeared_values=appeared,
        weights=(0.5, 0.5),
    ).scenarios
    view = _toy_rules_view()
    objective, signatures, scenario_scores = exhaustive_optimum(
        squad_ids, scenarios, positions, view
    )
    production: dict[str, tuple[object, tuple[int, ...]]] = {}
    squad = CandidateSquad(player_ids=squad_ids)
    for tactic in enumerate_tactical_configurations(squad, player_map, view, _policy())[0]:
        plan, candidate_objective = evaluate_tactical_configuration(
            squad, tactic, scenarios, player_map, view
        )
        production[plan.signature] = (
            candidate_objective,
            tuple(score.manager_points for score in plan.scenario_scores),
        )
    production_objective = max(value[0] for value in production.values())
    production_signatures = tuple(
        sorted(
            signature for signature, value in production.items() if value[0] == production_objective
        )
    )
    assert production_objective == objective
    assert production_signatures == signatures
    for signature in production_signatures:
        assert production[signature][1] == tuple(
            score.manager_points for score in scenario_scores[signature]
        )
