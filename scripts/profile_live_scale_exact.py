"""Frozen synthetic R7 physical-work profiles; never reads private provider input."""

from __future__ import annotations

import argparse
import cProfile
import importlib.util
import io
import json
import pstats
import random
import sys
from dataclasses import asdict
from itertools import combinations, product
from pathlib import Path
from time import perf_counter, process_time

from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Baseline timing must also use the immutable canonical evaluator, not only the
# old kernel class with current shared helpers. Select its source before imports.
if "--baseline-root" in sys.argv:
    baseline_root = Path(sys.argv[sys.argv.index("--baseline-root") + 1]).resolve()
    sys.path[:0] = [str(baseline_root / "src"), str(baseline_root)]

from dmf_pulse.assurance.canonical import canonical_sha256  # noqa: E402
from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode  # noqa: E402
from dmf_pulse.optimisation.models import CandidatePlayer, CandidateSquad  # noqa: E402
from dmf_pulse.optimisation.multi_gameweek_models import (  # noqa: E402
    PlayerCatalogEntry,
    PlayerPriceState,
    seal_request,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_solver import (  # noqa: E402
    Stage11SearchProfile,
    enumerate_legal_actions,
    solve_frontier,
)
from dmf_pulse.optimisation.tactics import ExactTacticalNodeKernel  # noqa: E402
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view  # noqa: E402
from tests.support.optimisation_factories import players, synthetic_ruleset  # noqa: E402
from tests.unit.optimisation.test_stage10_batch import _policy, _scenarios  # noqa: E402
from tests.unit.private_v1.horizon_oracle_support import (  # noqa: E402
    HorizonPointsEvaluator,
    oracle_fixture,
    with_candidates,
)


def overlapping_fixture(*, extra_per_position: int = 3):
    original = tuple(players())
    additions = tuple(
        CandidatePlayer(
            player_id=f"extra-{position.value}-{i}",
            club_id=f"extra-{position.value}-{i}",
            position=position,
        )
        for position in PlayerPosition
        for i in range(extra_per_position)
    )
    catalog = {p.player_id: p for p in (*original, *additions)}
    base = {p.player_id for p in original}
    squads = {tuple(sorted(base))}
    for count in (1, 2):
        for outgoing, incoming in product(
            combinations(original, count), combinations(additions, count)
        ):
            if sorted(p.position.value for p in outgoing) != sorted(
                p.position.value for p in incoming
            ):
                continue
            squads.add(
                tuple(
                    sorted(
                        (base - {p.player_id for p in outgoing}) | {p.player_id for p in incoming}
                    )
                )
            )
    return catalog, tuple(CandidateSquad(player_ids=ids) for ids in sorted(squads))


def _plan_decision_summary(plan):
    if plan is None:
        return None
    decisions = (plan.current_action, *plan.future_policy)
    return {
        "plan_kind": plan.plan_kind.value,
        "selection_score": str(plan.selection_score),
        "decisions": [
            {
                "node_id": decision.node_id,
                "gameweek": decision.gameweek,
                "action_signature": decision.action.signature,
                "expected_points": str(decision.tactical_evaluation.expected_points),
            }
            for decision in decisions
        ],
        "utility": plan.utility.model_dump(mode="json"),
        "leaf_utilities": [item.model_dump(mode="json") for item in plan.leaf_utilities],
    }


def _decision_semantics(result):
    frontier = result.transfer_count_frontier
    value = {
        "recommended": _plan_decision_summary(result.recommended_plan),
        "no_transfer_baseline": _plan_decision_summary(result.no_transfer_baseline),
        "root_counterfactual": _plan_decision_summary(result.root_action_counterfactual_plan),
        "transfer_count_frontier": (
            None
            if frontier is None
            else [
                {
                    "transfer_count": point.transfer_count,
                    "immediate_expected_points_before_hit": str(
                        point.immediate_expected_points_before_hit
                    ),
                    "transfer_hit_points": point.transfer_hit_points,
                    "current_gameweek_objective": str(point.current_gameweek_objective),
                    "expected_horizon_utility": str(point.expected_horizon_utility),
                    "plan": _plan_decision_summary(point.plan),
                }
                for point in frontier.points
            ]
        ),
    }
    return {"semantic_sha256": canonical_sha256(value), "value": value}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=32)
    parser.add_argument("--scenarios", type=int, default=8)
    parser.add_argument("--mode", choices=("kernel", "search"), default="kernel")
    parser.add_argument("--public-search", action="store_true")
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument("--extra-per-position", type=int, default=3)
    parser.add_argument("--cumulative-legal-action-limit", type=int)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--no-profile", action="store_true")
    parser.add_argument("--warmup", action="store_true")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("limit must be positive")
    if args.extra_per_position < 1:
        parser.error("extra-per-position must be positive")
    catalog, family = overlapping_fixture(extra_per_position=args.extra_per_position)
    if args.mode == "search":
        base, _, _, _ = oracle_fixture()
        for player in base.candidate_pool:
            if player.player_id in base.initial_state.squad_ids:
                catalog[player.player_id] = CandidatePlayer(
                    player_id=player.player_id, club_id=player.club_id, position=player.position
                )
        incoming = tuple(sorted(p for p in catalog if p not in base.initial_state.squad_ids))
        prices = {p: PlayerPriceState(current_price_tenths=50) for p in catalog}
        request = with_candidates(
            seal_request(
                base.model_copy(
                    update={
                        "candidate_pool": tuple(
                            PlayerCatalogEntry(
                                player_id=p.player_id, club_id=p.club_id, position=p.position
                            )
                            for p in sorted(catalog.values(), key=lambda p: p.player_id)
                        ),
                        "search_policy": seal_search_policy(
                            base.search_policy.model_copy(
                                update={
                                    "max_actions_per_state": 17000,
                                    "max_cumulative_legal_actions": (
                                        args.cumulative_legal_action_limit
                                        if args.cumulative_legal_action_limit is not None
                                        else base.search_policy.max_cumulative_legal_actions
                                    ),
                                }
                            )
                        ),
                    }
                )
            ),
            incoming,
            prices=prices,
        )
        points = {gw: {p: (sum(p.encode()) * (gw + 3)) % 17 for p in catalog} for gw in (1, 2, 3)}
        evaluator = HorizonPointsEvaluator(points)
        profile = Stage11SearchProfile(progress=lambda message: print(message, flush=True))
        wall, cpu = perf_counter(), process_time()
        result = None
        if not args.public_only:
            result = solve_frontier(
                request, evaluator, profile=profile, prefer_deterministic_linear=True
            )
        payload = {
            "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
            "mode": "SEARCH_SHAPE_WITH_SURROGATE_NOT_TACTICAL_TIMING",
            "wall_seconds": perf_counter() - wall,
            "cpu_seconds": process_time() - cpu,
            "complete": None if result is None else result.complete,
            "profile": profile.as_dict(),
            "tactical_batch_calls": evaluator.batch_calls,
            "unique_tactical_squads": len(evaluator.cache),
            "extra_per_position": args.extra_per_position,
            "candidate_pool_size": len(request.candidate_pool),
            "retained_incoming_count": len(incoming),
            "peak_memory_bytes": None,
            "memory_measurement": "UNAVAILABLE_WITHOUT_NEW_RUNTIME_DEPENDENCY",
            "configured_cumulative_legal_action_limit": (
                request.search_policy.cumulative_legal_action_limit
            ),
        }
        if not args.summary_only:
            payload["request"] = request.model_dump(mode="json")
            payload["candidates"] = (
                []
                if result is None
                else [TypeAdapter(type(c)).dump_python(c, mode="json") for c in result.candidates]
            )
            payload["squads_by_node"] = {
                node.node_id: sorted(
                    squad for node_id, squad in evaluator.cache if node_id == node.node_id
                )
                for node in request.scenario_tree.nodes
            }
        if args.public_search:
            from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek

            public_profile = Stage11SearchProfile(
                progress=lambda message: print(message, flush=True)
            )
            public_wall, public_cpu = perf_counter(), process_time()
            root = request.scenario_tree.root
            no_transfer = next(
                action
                for action in enumerate_legal_actions(
                    request.initial_state,
                    node=root,
                    candidate_pool=request.candidate_pool,
                    rules=request.rules,
                    policy=request.search_policy,
                )
                if action.transfer_count == 0
            )
            public_result = optimise_multi_gameweek(
                request,
                evaluator=evaluator,
                prefer_deterministic_linear=True,
                profile=public_profile,
                root_action_counterfactual=no_transfer,
            )
            payload["whole_public_solve"] = {
                "profile": public_profile.as_dict(),
                "wall_seconds": perf_counter() - public_wall,
                "cpu_seconds": process_time() - public_cpu,
                "status": public_result.status.value,
                "diagnostics": public_result.solver_status.model_dump(mode="json"),
                "decision_semantics": _decision_semantics(public_result),
                "result": (None if args.summary_only else public_result.model_dump(mode="json")),
            }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        print(
            json.dumps(
                {
                    k: v
                    for k, v in payload.items()
                    if k not in {"request", "candidates", "squads_by_node", "whole_public_solve"}
                }
            )
        )
        if args.public_search:
            print(
                json.dumps(
                    {
                        "whole_public_solve": {
                            key: value
                            for key, value in payload["whole_public_solve"]["profile"].items()
                            if key.startswith("cumulative_") or key == "exact_accelerator"
                        }
                    }
                )
            )
        return
    # Evenly spaced deterministic sample includes heterogeneous positional replacements.
    selected = tuple(
        family[i * len(family) // min(args.limit, len(family))]
        for i in range(min(args.limit, len(family)))
    )
    scenarios = _scenarios(tuple(sorted(catalog)))
    if args.scenarios != 8:
        if args.scenarios < 1:
            parser.error("scenarios must be positive")
        rng = random.Random(7001)
        expanded = []
        for i in range(args.scenarios):
            template = scenarios[i % len(scenarios)]
            appeared = {p: rng.random() < 0.85 for p in sorted(catalog)}
            points = {p: rng.randrange(-3, 19) if appeared[p] else 0 for p in sorted(catalog)}
            expanded.append(
                template.model_copy(
                    update={
                        "scenario_id": f"r7-{i}",
                        "outcome_draw_id": f"r7-{i}",
                        "weight": 1 / args.scenarios,
                        "player_points": points,
                        "player_appeared": appeared,
                        "player_minutes": {p: 90 if appeared[p] else 0 for p in sorted(catalog)},
                        "player_components": {
                            p: {
                                component: points[p] if component == "appearance" else 0
                                for component in template.player_components[p]
                            }
                            for p in sorted(catalog)
                        },
                    }
                )
            )
        scenarios = tuple(expanded)
    rules = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    kernel_type = ExactTacticalNodeKernel
    if args.baseline_root is not None:
        spec = importlib.util.spec_from_file_location(
            "r7_frozen_r6_tactics", args.baseline_root / "src/dmf_pulse/optimisation/tactics.py"
        )
        if spec is None or spec.loader is None:
            raise ValueError("baseline kernel module unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        kernel_type = module.ExactTacticalNodeKernel
    if args.warmup:
        warm_kernel = kernel_type(scenarios=scenarios, players=catalog, rules=rules)
        for squad in selected[:8]:
            warm_kernel.optimise(squad, _policy())
        del warm_kernel
    kernel = kernel_type(scenarios=scenarios, players=catalog, rules=rules)
    profiler = cProfile.Profile()
    wall, cpu = perf_counter(), process_time()
    if not args.no_profile:
        profiler.enable()
    results = [kernel.optimise(squad, _policy()) for squad in selected]
    if not args.no_profile:
        profiler.disable()
    elapsed_wall, elapsed_cpu = perf_counter() - wall, process_time() - cpu
    output = io.StringIO()
    if not args.no_profile:
        pstats.Stats(profiler, stream=output).strip_dirs().sort_stats("cumulative").print_stats(35)
    payload = {
        "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "mode": "UNINSTRUMENTED_DIRECT_EXACT_KERNEL"
        if args.no_profile
        else "CPROFILE_INSTRUMENTED_DIRECT_EXACT_KERNEL",
        "family_size": len(family),
        "squads": len(selected),
        "scenario_count": len(scenarios),
        "wall_seconds": elapsed_wall,
        "cpu_seconds": elapsed_cpu,
        "squads_per_wall_second": len(selected) / elapsed_wall,
        "work": asdict(kernel.work_snapshot()),
        "semantic_results": [
            {
                "squad": s.player_ids,
                "plan": r[0].model_dump(mode="json"),
                "objective": str(r[1]),
                "tactics": r[2],
                "ties": r[3],
            }
            for s, r in zip(selected, results, strict=True)
        ],
        "profile": output.getvalue(),
    }
    payload["semantic_sha256"] = canonical_sha256(payload["semantic_results"])
    if args.reference is not None:
        reference = json.loads(args.reference.read_text(encoding="utf-8"))
        assert reference["semantic_results"] == json.loads(json.dumps(payload["semantic_results"]))
        payload["all_reference_results_equal"] = True
        payload["wall_speedup"] = reference["wall_seconds"] / elapsed_wall
        payload["cpu_speedup"] = reference["cpu_seconds"] / elapsed_cpu
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps({k: v for k, v in payload.items() if k not in {"semantic_results", "profile"}})
    )
    print(output.getvalue())


if __name__ == "__main__":
    main()
