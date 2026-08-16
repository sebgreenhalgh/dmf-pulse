"""Independent exhaustive OPT-010 oracle used only by assurance tests.

This module intentionally contains its own tactic enumeration, autosubstitution, formation
validation, score calculation, and exact-weight arithmetic.  It must not import production
optimiser search, tactic, autosubstitution, or legality helpers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from itertools import combinations, permutations, product
from typing import TYPE_CHECKING

from dmf_pulse.fpl_points.models import GameweekPointScenario, PlayerPosition

if TYPE_CHECKING:
    from dmf_pulse.optimisation.models import OneGameweekRulesView


@dataclass(frozen=True)
class OracleTactic:
    starting_xi: tuple[str, ...]
    bench_goalkeeper: str
    outfield_bench_order: tuple[str, ...]
    captain: str
    vice_captain: str


@dataclass(frozen=True)
class OracleAutosub:
    player_out: str
    player_in: str
    slot: int
    position: PlayerPosition


@dataclass(frozen=True)
class OracleScenarioScore:
    manager_points: int
    player_points: dict[str, int]
    autosubs: tuple[OracleAutosub, ...]
    multiplier_player: str | None
    multiplier: int
    weighted: Fraction


def _weight(weight: float) -> Fraction:
    return Fraction(Decimal(json.dumps(weight, allow_nan=False, separators=(",", ":"))))


def _outfield_legal(
    player_ids: tuple[str, ...],
    positions: dict[str, PlayerPosition],
    rules: OneGameweekRulesView,
) -> bool:
    counts = {position: 0 for position in PlayerPosition}
    for player_id in player_ids:
        counts[positions[player_id]] += 1
    return all(
        rules.lineup_min[position] <= counts[position] <= rules.lineup_max[position]
        for position in (PlayerPosition.DEF, PlayerPosition.MID, PlayerPosition.FWD)
    )


def resolve_autosubs(
    *,
    starting_outfield: tuple[str, ...],
    bench_outfield: tuple[str, ...],
    positions: dict[str, PlayerPosition],
    appeared: set[str],
    rules: OneGameweekRulesView,
) -> tuple[OracleAutosub, ...]:
    """Resolve all legal pairings independently, including the frozen multi-absence rule."""

    absent = tuple(player_id for player_id in starting_outfield if player_id not in appeared)
    eligible = tuple(player_id for player_id in bench_outfield if player_id in appeared)
    selected: tuple[str, ...] | None = None
    for count in range(min(len(absent), len(eligible)), -1, -1):
        for candidate in combinations(eligible, count):
            retained = tuple(
                player_id for player_id in starting_outfield if player_id not in absent
            )
            if _outfield_legal((*retained, *candidate), positions, rules):
                selected = candidate
                break
        if selected is not None:
            break
    if selected is None:
        return ()
    legal: list[tuple[tuple[str, ...], tuple[OracleAutosub, ...]]] = []
    for outgoing in permutations(absent, len(selected)):
        current = list(starting_outfield)
        events: list[OracleAutosub] = []
        for incoming, player_out in zip(selected, outgoing, strict=True):
            current[current.index(player_out)] = incoming
            if not _outfield_legal(tuple(current), positions, rules):
                break
            events.append(
                OracleAutosub(
                    player_out=player_out,
                    player_in=incoming,
                    slot=bench_outfield.index(incoming) + 1,
                    position=positions[incoming],
                )
            )
        else:
            legal.append((outgoing, tuple(events)))
    return min(legal, key=lambda item: item[0])[1] if legal else ()


def evaluate_scenario(
    scenario: GameweekPointScenario,
    tactic: OracleTactic,
    positions: dict[str, PlayerPosition],
    rules: OneGameweekRulesView,
) -> OracleScenarioScore:
    """Score one scenario from first principles using only the frozen rules view."""

    appeared = {player_id for player_id, value in scenario.player_appeared.items() if value}
    active = list(tactic.starting_xi)
    events: list[OracleAutosub] = []
    starting_goalkeeper = next(
        player_id for player_id in tactic.starting_xi if positions[player_id] is PlayerPosition.GK
    )
    if starting_goalkeeper not in appeared and tactic.bench_goalkeeper in appeared:
        active[active.index(starting_goalkeeper)] = tactic.bench_goalkeeper
        events.append(
            OracleAutosub(
                player_out=starting_goalkeeper,
                player_in=tactic.bench_goalkeeper,
                slot=1,
                position=PlayerPosition.GK,
            )
        )
    outfield_events = resolve_autosubs(
        starting_outfield=tuple(
            player_id
            for player_id in tactic.starting_xi
            if positions[player_id] is not PlayerPosition.GK
        ),
        bench_outfield=tactic.outfield_bench_order,
        positions=positions,
        appeared=appeared,
        rules=rules,
    )
    for event in outfield_events:
        active[active.index(event.player_out)] = event.player_in
    events.extend(outfield_events)
    multiplier_player = (
        tactic.captain
        if tactic.captain in appeared
        else (
            tactic.vice_captain
            if rules.vice_captain_fallback and tactic.vice_captain in appeared
            else None
        )
    )
    multiplier = rules.captain_multiplier if multiplier_player is not None else 1
    counted = tuple(player_id for player_id in active if player_id in appeared)
    manager_points = sum(scenario.player_points[player_id] for player_id in counted)
    if multiplier_player is not None:
        manager_points += (multiplier - 1) * scenario.player_points[multiplier_player]
    return OracleScenarioScore(
        manager_points=manager_points,
        player_points={
            player_id: scenario.player_points[player_id] for player_id in sorted(counted)
        },
        autosubs=tuple(events),
        multiplier_player=multiplier_player,
        multiplier=multiplier,
        weighted=_weight(scenario.weight) * manager_points,
    )


def enumerate_tactics(
    squad_ids: tuple[str, ...],
    positions: dict[str, PlayerPosition],
    rules: OneGameweekRulesView,
) -> tuple[OracleTactic, ...]:
    """Enumerate every legal tactic without invoking production candidate or tactic code."""

    grouped = {
        position: tuple(
            sorted(player_id for player_id in squad_ids if positions[player_id] is position)
        )
        for position in PlayerPosition
    }
    tactics: list[OracleTactic] = []
    for bench_goalkeeper in grouped[PlayerPosition.GK]:
        starting_goalkeeper = next(
            player_id for player_id in grouped[PlayerPosition.GK] if player_id != bench_goalkeeper
        )
        for defenders in range(
            rules.lineup_min[PlayerPosition.DEF], rules.lineup_max[PlayerPosition.DEF] + 1
        ):
            for midfielders in range(
                rules.lineup_min[PlayerPosition.MID], rules.lineup_max[PlayerPosition.MID] + 1
            ):
                forwards = rules.starting_size - 1 - defenders - midfielders
                if (
                    not rules.lineup_min[PlayerPosition.FWD]
                    <= forwards
                    <= rules.lineup_max[PlayerPosition.FWD]
                ):
                    continue
                for defence, midfield, forward in product(
                    combinations(grouped[PlayerPosition.DEF], defenders),
                    combinations(grouped[PlayerPosition.MID], midfielders),
                    combinations(grouped[PlayerPosition.FWD], forwards),
                ):
                    starting = (starting_goalkeeper, *defence, *midfield, *forward)
                    bench_outfield = tuple(
                        sorted(set(squad_ids) - set(starting) - {bench_goalkeeper})
                    )
                    for bench_order in permutations(bench_outfield):
                        for captain, vice_captain in permutations(starting, 2):
                            tactics.append(
                                OracleTactic(
                                    starting_xi=starting,
                                    bench_goalkeeper=bench_goalkeeper,
                                    outfield_bench_order=bench_order,
                                    captain=captain,
                                    vice_captain=vice_captain,
                                )
                            )
    return tuple(tactics)


def tactic_signature(squad_ids: tuple[str, ...], tactic: OracleTactic) -> str:
    return "|".join(
        (
            ",".join(sorted(squad_ids)),
            ",".join(sorted(tactic.starting_xi)),
            tactic.bench_goalkeeper,
            ",".join(tactic.outfield_bench_order),
            tactic.captain,
            tactic.vice_captain,
        )
    )


def exhaustive_optimum(
    squad_ids: tuple[str, ...],
    scenarios: tuple[GameweekPointScenario, ...],
    positions: dict[str, PlayerPosition],
    rules: OneGameweekRulesView,
) -> tuple[Fraction, tuple[str, ...], dict[str, tuple[OracleScenarioScore, ...]]]:
    """Return the exact objective, complete tie set, and scenario scores for each optimum."""

    best: Fraction | None = None
    optimal: dict[str, tuple[OracleScenarioScore, ...]] = {}
    for tactic in enumerate_tactics(squad_ids, positions, rules):
        scores = tuple(
            evaluate_scenario(scenario, tactic, positions, rules) for scenario in scenarios
        )
        objective = sum((score.weighted for score in scores), Fraction(0))
        signature = tactic_signature(squad_ids, tactic)
        if best is None or objective > best:
            best = objective
            optimal = {signature: scores}
        elif objective == best:
            optimal[signature] = scores
    if best is None:
        raise AssertionError("oracle was given no legal tactical configuration")
    return best, tuple(sorted(optimal)), optimal
