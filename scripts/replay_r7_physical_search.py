"""Real Stage-10/11 frozen layered-search differential, without upstream surrogates."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from time import perf_counter, process_time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--request-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.code_root.resolve()
    sys.path[:0] = [str(root / "src"), str(root)]

    from pydantic import TypeAdapter

    from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
    from dmf_pulse.optimisation.multi_gameweek_models import MultiGameweekOptimisationRequest
    from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
    from dmf_pulse.optimisation.multi_gameweek_solver import Stage11SearchProfile, solve_frontier
    from dmf_pulse.optimisation.stage10_adapter import Stage10TacticalAdapter
    from dmf_pulse.private_v1.service import _MemoizedStage10Evaluator
    from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
    from tests.support.optimisation_factories import synthetic_ruleset
    from tests.unit.optimisation.test_stage10_batch import _policy, _scenarios
    from tests.unit.private_v1.horizon_oracle_support import with_candidates

    source = json.loads(args.request_source.read_text(encoding="utf-8"))
    request = MultiGameweekOptimisationRequest.model_validate(source["request"])
    # A distinct frozen tractable fixture, not pruning either algorithm's scope:
    # one incoming per position, identical sealed request for R6 and R7.
    incoming = tuple(
        min(
            p.player_id
            for p in request.candidate_pool
            if p.position is position and p.player_id not in request.initial_state.squad_ids
        )
        for position in PlayerPosition
    )
    request = with_candidates(request, incoming)
    ids = tuple(p.player_id for p in request.candidate_pool)
    templates = _scenarios(ids)
    rng = random.Random(7001)
    scenarios = []
    for i in range(256):
        template = templates[i % len(templates)]
        appeared = {p: rng.random() < 0.85 for p in ids}
        points = {p: rng.randrange(-3, 19) if appeared[p] else 0 for p in ids}
        scenarios.append(
            template.model_copy(
                update={
                    "scenario_id": f"r7-{i}",
                    "outcome_draw_id": f"r7-{i}",
                    "weight": 1 / 256,
                    "player_points": points,
                    "player_appeared": appeared,
                    "player_minutes": {p: 90 if appeared[p] else 0 for p in ids},
                    "player_components": {
                        p: {
                            c: points[p] if c == "appearance" else 0
                            for c in template.player_components[p]
                        }
                        for p in ids
                    },
                }
            )
        )
    adapter = Stage10TacticalAdapter(
        candidate_pool=request.candidate_pool,
        rules=build_one_gameweek_rules_view(
            synthetic_ruleset(), projection_mode=ProjectionMode.TEST
        ),
        policy=_policy(),
        scenarios_by_node={node.node_id: tuple(scenarios) for node in request.scenario_tree.nodes},
    )
    evaluator = _MemoizedStage10Evaluator(adapter)
    profile = Stage11SearchProfile(progress=lambda text: print(text, flush=True))
    wall, cpu = perf_counter(), process_time()
    frontier = solve_frontier(request, evaluator, prefer_deterministic_linear=True, profile=profile)
    assert frontier.complete
    # Cached physical tactics make this second pass inexpensive; it exercises
    # full plan/frontier/alternative/move-attribution assembly on the same inputs.
    public_profile = Stage11SearchProfile()
    result = optimise_multi_gameweek(
        request, evaluator=evaluator, prefer_deterministic_linear=True, profile=public_profile
    )
    payload = {
        "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "mode": "REAL_STAGE10_STAGE11_FROZEN_DIFFERENTIAL",
        "wall_seconds": perf_counter() - wall,
        "cpu_seconds": process_time() - cpu,
        "request": request.model_dump(mode="json"),
        "candidates": [
            TypeAdapter(type(c)).dump_python(c, mode="json") for c in frontier.candidates
        ],
        "result": result.model_dump(mode="json"),
        "profile": profile.as_dict(),
        "whole_public_solve_profile": public_profile.as_dict(),
        "unique_tactical_squads": len(evaluator._cache),
        "batch_calls": evaluator.batch_calls,
        "scenario_count": 256,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {k: v for k, v in payload.items() if k not in {"request", "result", "candidates"}}
        )
    )


if __name__ == "__main__":
    main()
