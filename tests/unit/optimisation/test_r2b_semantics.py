"""R2B regressions for exact tactical semantics and deterministic preflight."""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_UP, localcontext

import pytest

from dmf_pulse.fpl_points.artifacts import canonical_json_bytes, semantic_sha256
from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.optimisation.autosub_evaluator import evaluate_scenario
from dmf_pulse.optimisation.candidate_pool import enumerate_squads
from dmf_pulse.optimisation.errors import ResourceLimitError
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidatePoolSnapshot,
    CandidateSquad,
    OneGameweekOptimisationRequest,
    OneGameweekOptimiserPolicy,
    SearchScope,
    TacticalConfiguration,
)
from dmf_pulse.optimisation.service import optimise_one_gameweek
from dmf_pulse.optimisation.solver import solve
from dmf_pulse.optimisation.tactics import evaluate_tactical_configuration
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import (
    players,
    projection,
    request,
    scenario_set,
    synthetic_ruleset,
)


def _policy(**updates: int) -> OneGameweekOptimiserPolicy:
    values = {
        "max_squad_candidates": 12,
        "max_tactical_configurations": 5_000_000,
        "max_scenario_score_operations": 20_000_000,
        "max_returned_ties": 16,
    }
    values.update(updates)
    return OneGameweekOptimiserPolicy(**values)


def _seal_pool(candidates: tuple[CandidatePlayer, ...]) -> CandidatePoolSnapshot:
    pool = CandidatePoolSnapshot(
        information_cutoff_utc="2026-08-16T00:00:00Z",
        players=candidates,
        snapshot_sha256="0" * 64,
    )
    payload = pool.model_dump(mode="json")
    payload["snapshot_sha256"] = None
    return pool.model_copy(update={"snapshot_sha256": semantic_sha256(payload)})


def _seal_request(req: OneGameweekOptimisationRequest) -> OneGameweekOptimisationRequest:
    payload = req.model_dump(mode="json")
    payload["request_sha256"] = None
    return req.model_copy(update={"request_sha256": semantic_sha256(payload)})


def test_multiple_absence_audit_pairs_follow_formation_feasible_bench_order() -> None:
    rules = synthetic_ruleset()
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    player_map = {player.player_id: player for player in players()}
    tactic = TacticalConfiguration(
        starting_xi=("p00", "p02", "p03", "p04", "p07", "p08", "p09", "p10", "p11", "p12", "p13"),
        bench_goalkeeper="p01",
        bench_order=("p14", "p05", "p06"),
        captain="p07",
        vice_captain="p08",
    )
    values = {player_id: 1 for player_id in player_map}
    values.update({"p02": 0, "p07": 0, "p14": 2, "p05": 2})
    appeared = {player_id: True for player_id in player_map}
    appeared.update({"p02": False, "p07": False})
    scenario = scenario_set(
        rules.ruleset_hash, values=(values,), appeared_values=(appeared,)
    ).scenarios[0]
    score, _ = evaluate_scenario(scenario, tactic, player_map, view)
    assert tuple(
        (event.player_out, event.player_in, event.slot) for event in score.autosub_events
    ) == (
        ("p07", "p14", 1),
        ("p02", "p05", 2),
    )


def test_global_exact_tie_recommendation_is_not_limited_to_first_enumerated_prefix() -> None:
    rules = synthetic_ruleset()
    result = optimise_one_gameweek(request(), projection(rules.ruleset_hash), rules)
    assert result.recommended_plan is not None
    assert result.solver_status.total_optimal_ties > 16
    assert result.recommended_plan.signature == (
        "p00,p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14|"
        "p00,p02,p03,p04,p05,p06,p07,p08,p09,p10,p12|p01|p11,p13,p14|p00|p02"
    )
    assert tuple(plan.signature for plan in result.tied_plans) == tuple(
        sorted(plan.signature for plan in result.tied_plans)
    )


def test_aggregate_tactical_cap_blocks_multiple_provided_squads_before_enumeration() -> None:
    rules = synthetic_ruleset()
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    candidates: list[CandidatePlayer] = []
    squads: list[CandidateSquad] = []
    for squad_index in range(2):
        ids: list[str] = []
        for position, count in (
            (PlayerPosition.GK, 2),
            (PlayerPosition.DEF, 5),
            (PlayerPosition.MID, 5),
            (PlayerPosition.FWD, 3),
        ):
            for number in range(count):
                player_id = f"{squad_index}-{position.value}-{number}"
                ids.append(player_id)
                candidates.append(
                    CandidatePlayer(
                        player_id=player_id,
                        position=position,
                        club_id=f"club-{squad_index}-{position.value}-{number}",
                    )
                )
        squads.append(CandidateSquad(player_ids=tuple(sorted(ids))))
    req = _seal_request(
        OneGameweekOptimisationRequest(
            request_id="provided-cap-request",
            projection_mode=ProjectionMode.TEST,
            gameweek_id="GW1",
            information_cutoff_utc="2026-08-16T00:00:00Z",
            search_scope=SearchScope.PROVIDED_SQUADS,
            candidate_pool=_seal_pool(tuple(sorted(candidates, key=lambda item: item.player_id))),
            provided_candidate_squads=tuple(squads),
            request_sha256="0" * 64,
        )
    )
    with pytest.raises(ResourceLimitError) as raised:
        solve(
            req,
            scenario_set(rules.ruleset_hash).scenarios,
            view,
            _policy(max_tactical_configurations=500_000),
        )
    assert raised.value.solver_status is not None
    assert raised.value.solver_status.conservative_tactical_upper_bound == 726_000


def test_decimal_context_cannot_change_semantic_tactical_output() -> None:
    rules = synthetic_ruleset()
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    player_map = {player.player_id: player for player in players()}
    req = request()
    assert req.fixed_squad is not None
    tactic = TacticalConfiguration(
        starting_xi=("p00", "p02", "p03", "p04", "p07", "p08", "p09", "p10", "p12", "p13", "p14"),
        bench_goalkeeper="p01",
        bench_order=("p05", "p06", "p11"),
        captain="p07",
        vice_captain="p08",
    )
    scenarios = scenario_set(
        rules.ruleset_hash,
        values=({"p07": 2}, {"p08": 5}),
        appeared_values=({"p07": True}, {"p08": True}),
        weights=(0.3333333333333333, 0.6666666666666667),
    ).scenarios
    with localcontext() as context:
        context.prec = 8
        context.rounding = ROUND_DOWN
        left, _ = evaluate_tactical_configuration(
            req.fixed_squad, tactic, scenarios, player_map, view
        )
    with localcontext() as context:
        context.prec = 70
        context.rounding = ROUND_UP
        right, _ = evaluate_tactical_configuration(
            req.fixed_squad, tactic, scenarios, player_map, view
        )
    assert canonical_json_bytes(left) == canonical_json_bytes(right)


def test_duplicate_provided_squads_are_rejected_before_caps_or_ties() -> None:
    base = request(scope=SearchScope.PROVIDED_SQUADS)
    assert base.provided_squads
    with pytest.raises(ValueError, match="provided squads must be unique"):
        OneGameweekOptimisationRequest(
            request_id=base.request_id,
            gameweek_id=base.gameweek_id,
            projection_mode=base.projection_mode,
            information_cutoff_utc=base.information_cutoff_utc,
            search_scope=SearchScope.PROVIDED_SQUADS,
            candidate_pool=base.candidate_pool,
            provided_candidate_squads=(base.provided_squads[0], base.provided_squads[0]),
            request_sha256="0" * 64,
        )
    rules = synthetic_ruleset()
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    duplicated = base.model_construct(
        **{
            **base.model_dump(),
            "provided_candidate_squads": (base.provided_squads[0], base.provided_squads[0]),
        }
    )
    with pytest.raises(Exception):
        enumerate_squads(duplicated, view, _policy())
