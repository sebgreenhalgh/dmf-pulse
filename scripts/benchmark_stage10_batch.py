"""Deterministic 001L old/new exact Stage-10 batch benchmark."""

from __future__ import annotations

import argparse
import json
from itertools import combinations, islice, product
from pathlib import Path
from time import perf_counter

from dmf_pulse.fpl_points.models import (
    GameweekAssemblyMode,
    GameweekPointScenario,
    PlayerPosition,
    ProjectionMode,
)
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidateSquad,
    OneGameweekOptimiserPolicy,
)
from dmf_pulse.optimisation.tactics import (
    ExactTacticalNodeKernel,
    optimise_fixed_squad_tactics_exact,
)
from dmf_pulse.rules.compiler import load_compiled_ruleset
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view

POINT_COMPONENTS = (
    "appearance",
    "goals",
    "assists",
    "clean_sheet",
    "saves",
    "penalty_saves",
    "defensive_contributions",
    "goals_conceded",
    "penalty_misses",
    "yellow_cards",
    "red_cards",
    "own_goals",
    "bonus",
)


def _players(*, include_signal_players: bool = False) -> tuple[CandidatePlayer, ...]:
    quotas = (
        ("g", 4, PlayerPosition.GK),
        ("d", 8, PlayerPosition.DEF),
        ("m", 8, PlayerPosition.MID),
        ("f", 5, PlayerPosition.FWD),
    )
    players = tuple(
        sorted(
            (
                CandidatePlayer(
                    player_id=f"{prefix}{index:02d}",
                    club_id=f"club-{prefix}{index:02d}",
                    position=position,
                )
                for prefix, count, position in quotas
                for index in range(count)
            ),
            key=lambda item: item.player_id,
        )
    )
    if not include_signal_players:
        return players
    return tuple(
        sorted(
            (
                *players,
                *(
                    CandidatePlayer(
                        player_id=f"x{index:02d}",
                        club_id=f"club-x{index:02d}",
                        position=PlayerPosition.MID,
                    )
                    for index in range(8)
                ),
            ),
            key=lambda item: item.player_id,
        )
    )


def _squads(count: int) -> tuple[CandidateSquad, ...]:
    choices = product(
        combinations(tuple(f"g{index:02d}" for index in range(4)), 2),
        combinations(tuple(f"d{index:02d}" for index in range(8)), 5),
        combinations(tuple(f"m{index:02d}" for index in range(8)), 5),
        combinations(tuple(f"f{index:02d}" for index in range(5)), 3),
    )
    squads = tuple(
        CandidateSquad(player_ids=tuple(sorted((*goalkeepers, *defenders, *mids, *forwards))))
        for goalkeepers, defenders, mids, forwards in islice(choices, count)
    )
    if len(squads) != count:
        raise ValueError("requested benchmark squad count exceeds deterministic universe")
    return squads


def _scenarios(
    candidate_ids: tuple[str, ...], count: int, *, unique_global_appearances: bool
) -> tuple[GameweekPointScenario, ...]:
    weight = 1.0 / count
    scenarios: list[GameweekPointScenario] = []
    for scenario_index in range(count):
        appeared = {
            player_id: ((scenario_index * 17 + player_index * 19 + player_index**2) % 101) > 0
            for player_index, player_id in enumerate(candidate_ids)
        }
        if unique_global_appearances:
            for signal_index in range(8):
                appeared[f"x{signal_index:02d}"] = bool(scenario_index & (1 << signal_index))
        selectable_ids = tuple(
            player_id for player_id in candidate_ids if not player_id.startswith("x")
        )
        appeared[selectable_ids[scenario_index % len(selectable_ids)]] = True
        points = {
            player_id: (
                ((scenario_index * 11 + player_index * 7 + player_index**2) % 20) - 3
                if appeared[player_id]
                else 0
            )
            for player_index, player_id in enumerate(candidate_ids)
        }
        scenarios.append(
            GameweekPointScenario(
                scenario_id=f"live-shaped-{scenario_index:03d}",
                outcome_draw_id=f"draw-{scenario_index:03d}",
                weight=weight,
                gameweek_id="GW3",
                fixture_ids=("live-shaped",),
                player_points=points,
                player_components={
                    player_id: {
                        component: (points[player_id] if component == "appearance" else 0)
                        for component in POINT_COMPONENTS
                    }
                    for player_id in candidate_ids
                },
                player_bps={player_id: 0 for player_id in candidate_ids},
                player_bonus={player_id: 0 for player_id in candidate_ids},
                player_minutes={
                    player_id: 90 if appeared[player_id] else 0 for player_id in candidate_ids
                },
                player_appeared=appeared,
                assembly_mode=GameweekAssemblyMode.SINGLE_FIXTURE,
                approximation_labels=(),
            )
        )
    return tuple(scenarios)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--squads", type=int, default=263)
    parser.add_argument("--scenarios", type=int, default=256)
    parser.add_argument("--reference-squads", type=int)
    parser.add_argument("--unique-global-appearances", action="store_true")
    args = parser.parse_args()
    if args.squads <= 0 or args.scenarios <= 0:
        parser.error("benchmark dimensions must be positive")

    reference_squad_count = args.reference_squads or args.squads
    if reference_squad_count <= 0 or reference_squad_count > args.squads:
        parser.error("reference squad count must be within the benchmark squad count")
    candidate_players = _players(include_signal_players=args.unique_global_appearances)
    player_map = {item.player_id: item for item in candidate_players}
    candidate_ids = tuple(player_map)
    squads = _squads(args.squads)
    scenarios = _scenarios(
        candidate_ids,
        args.scenarios,
        unique_global_appearances=args.unique_global_appearances,
    )
    rules = build_one_gameweek_rules_view(
        load_compiled_ruleset(
            Path("fixtures/optimisation/one_gameweek/reference_ruleset_test_only.json")
        ),
        projection_mode=ProjectionMode.TEST,
    )
    policy = OneGameweekOptimiserPolicy(
        max_squad_candidates=max(300, args.squads),
        max_tactical_configurations=5_000_000,
        max_scenario_score_operations=100_000_000_000,
        max_returned_ties=16,
    )

    reference_started = perf_counter()
    reference = tuple(
        optimise_fixed_squad_tactics_exact(squad, scenarios, player_map, rules, policy)
        for squad in squads[:reference_squad_count]
    )
    reference_seconds = perf_counter() - reference_started

    kernel = ExactTacticalNodeKernel(scenarios=scenarios, players=player_map, rules=rules)
    accelerated_started = perf_counter()
    accelerated = tuple(kernel.optimise(squad, policy) for squad in squads)
    accelerated_seconds = perf_counter() - accelerated_started
    exact = accelerated[:reference_squad_count] == reference
    work = kernel.work_snapshot()
    output = {
        "accelerated_seconds": accelerated_seconds,
        "canonical_scenario_operations": work.canonical_scenario_operations,
        "exact": exact,
        "factored_scenario_operations": work.factored_scenario_operations,
        "logical_scenario_operations": work.logical_scenario_operations,
        "reference_seconds": reference_seconds,
        "reference_squads": reference_squad_count,
        "scenarios": len(scenarios),
        "projected_speedup_from_reference_subset": (
            reference_seconds / reference_squad_count * len(squads) / accelerated_seconds
            if reference_squad_count < len(squads)
            else None
        ),
        "squads": len(squads),
        "speedup": (
            reference_seconds / accelerated_seconds
            if reference_squad_count == len(squads)
            else None
        ),
        "unique_appearance_states": len(
            {tuple(scenario.player_appeared.items()) for scenario in scenarios}
        ),
    }
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if exact else 1


if __name__ == "__main__":
    raise SystemExit(main())
