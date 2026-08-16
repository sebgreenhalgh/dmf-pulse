"""Exact per-scenario autosubstitution and captain evaluation."""

from __future__ import annotations

import json
from decimal import Decimal
from fractions import Fraction

from dmf_pulse.fpl_points.models import GameweekPointScenario, PlayerPosition
from dmf_pulse.optimisation.models import (
    AutosubEvent,
    CandidatePlayer,
    CaptainResolution,
    OneGameweekRulesView,
    ScenarioManagerScore,
    TacticalConfiguration,
)
from dmf_pulse.rules.one_gameweek import resolve_outfield_substitutions


def canonical_weight_token(weight: float) -> str:
    return json.dumps(weight, allow_nan=False, ensure_ascii=False, separators=(",", ":"))


def weight_fraction(weight: float) -> Fraction:
    return Fraction(Decimal(canonical_weight_token(weight)))


def evaluate_scenario(
    scenario: GameweekPointScenario,
    tactic: TacticalConfiguration,
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
) -> tuple[ScenarioManagerScore, Fraction]:
    appeared = {player for player, value in scenario.player_appeared.items() if value}
    active = list(tactic.starting_xi)
    events: list[AutosubEvent] = []
    starting_gk_index = next(
        (
            index
            for index, player in enumerate(active)
            if players[player].position is PlayerPosition.GK
        ),
        None,
    )
    if (
        starting_gk_index is not None
        and active[starting_gk_index] not in appeared
        and tactic.bench_goalkeeper in appeared
    ):
        player_out = active[starting_gk_index]
        active[starting_gk_index] = tactic.bench_goalkeeper
        events.append(
            AutosubEvent(
                scenario_id=scenario.scenario_id,
                player_out=player_out,
                player_in=tactic.bench_goalkeeper,
                slot=1,
                position=PlayerPosition.GK,
            )
        )
    starting_outfield = tuple(
        player for player in tactic.starting_xi if players[player].position is not PlayerPosition.GK
    )
    resolution = resolve_outfield_substitutions(
        starting_outfield=starting_outfield,
        bench_outfield=tactic.outfield_bench_order,
        positions={player: players[player].position for player in players},
        appeared=appeared,
        lineup_min=rules.lineup_min,
        lineup_max=rules.lineup_max,
    )
    for item in resolution:
        if item.player_out in active:  # pragma: no branch - resolver emits only starter absences
            active[active.index(item.player_out)] = item.player_in
            events.append(
                AutosubEvent(
                    scenario_id=scenario.scenario_id,
                    player_out=item.player_out,
                    player_in=item.player_in,
                    slot=item.slot,
                    position=item.position,
                )
            )
    captain_appeared = tactic.captain in appeared
    vice_appeared = tactic.vice_captain in appeared
    multiplier_player = (
        tactic.captain
        if captain_appeared
        else (tactic.vice_captain if rules.vice_captain_fallback and vice_appeared else None)
    )
    captain_resolution = CaptainResolution(
        captain=tactic.captain,
        vice_captain=tactic.vice_captain,
        multiplier_player=multiplier_player,
        multiplier=rules.captain_multiplier if multiplier_player else 1,
    )
    counted = tuple(player for player in active if player in appeared)
    score = sum(scenario.player_points[player] for player in counted)
    if multiplier_player is not None:
        score += (rules.captain_multiplier - 1) * scenario.player_points[multiplier_player]
    token = canonical_weight_token(scenario.weight)
    fraction = weight_fraction(scenario.weight)
    weighted = fraction * score
    return (
        ScenarioManagerScore(
            scenario_id=scenario.scenario_id,
            weighted_numerator=weighted.numerator,
            weight_token=token,
            manager_points=score,
            player_points={player: scenario.player_points[player] for player in sorted(counted)},
            autosub_events=tuple(events),
            captain_resolution=captain_resolution,
        ),
        weighted,
    )
