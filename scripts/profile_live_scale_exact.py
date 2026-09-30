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
    SearchPolicy,
    TransferActionScope,
    seal_request,
    seal_scenario_tree,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_solver import (  # noqa: E402
    Stage11SearchProfile,
    enumerate_legal_actions,
    information_set_key,
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


class _StatelessHorizonPointsEvaluator(HorizonPointsEvaluator):
    """Exact synthetic evaluator without an unbounded profiling-only cache."""

    def evaluate(self, *, node, state):
        self.calls += 1
        return self._value(node, state.squad_ids)

    def precompute_node(self, *, node, squads):
        if squads:
            self.batch_calls[node.node_id] = self.batch_calls.get(node.node_id, 0) + 1


def _profile_squads(profile: Stage11SearchProfile) -> dict[str, list[tuple[str, ...]]]:
    return {
        node_id: sorted(node.unique_resulting_squads)
        for node_id, node in sorted(profile.nodes.items())
    }


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
    value = plan.model_dump(mode="json")
    # These bind the configured resource policy rather than the selected
    # football decision. Every action, state, economic, tactical, uncertainty,
    # utility, path and leaf field remains in the authenticated projection.
    value.pop("solver_status")
    value.pop("plan_sha256")
    return value


def _decision_semantics(result):
    frontier = result.transfer_count_frontier
    value = {
        "recommended": _plan_decision_summary(result.recommended_plan),
        "no_transfer_baseline": _plan_decision_summary(result.no_transfer_baseline),
        "root_counterfactual": _plan_decision_summary(result.root_action_counterfactual_plan),
        "conservative_alternative": {
            "availability": result.conservative_plan.availability.value,
            "reason": result.conservative_plan.reason,
            "plan": _plan_decision_summary(result.conservative_plan.plan),
        },
        "high_upside_alternative": {
            "availability": result.high_upside_plan.availability.value,
            "reason": result.high_upside_plan.reason,
            "plan": _plan_decision_summary(result.high_upside_plan.plan),
        },
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


def _resolve_policy_candidate_limits(
    *,
    legacy: int | None,
    generated: int | None,
    retained: int | None,
    default_generated: int,
    default_retained: int,
) -> tuple[int, int]:
    """Preserve the legacy flag's two-unit meaning without an ambiguous mix."""

    if legacy is not None and (generated is not None or retained is not None):
        raise ValueError(
            "--max-policy-candidates cannot be combined with either split policy limit"
        )
    if legacy is not None:
        if legacy <= 0:
            raise ValueError("--max-policy-candidates must be positive")
        return legacy, legacy
    if generated is not None and generated <= 0:
        raise ValueError("--max-generated-policy-candidates must be positive")
    if retained is not None and retained <= 0:
        raise ValueError("--max-retained-pareto-candidates must be positive")
    return (
        generated if generated is not None else default_generated,
        retained if retained is not None else default_retained,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=32)
    parser.add_argument("--scenarios", type=int, default=8)
    parser.add_argument("--mode", choices=("kernel", "search"), default="kernel")
    parser.add_argument("--public-search", action="store_true")
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument("--extra-per-position", type=int, default=3)
    parser.add_argument("--l6-shape", action="store_true")
    parser.add_argument("--terminal-incoming-count", type=int, default=6)
    parser.add_argument("--cumulative-legal-action-limit", type=int)
    parser.add_argument("--max-policy-candidates", type=int)
    parser.add_argument("--max-generated-policy-candidates", type=int)
    parser.add_argument("--max-retained-pareto-candidates", type=int)
    parser.add_argument(
        "--projection-ordering", choices=("baseline", "shifted-shadow"), default="baseline"
    )
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
    if not 1 <= args.terminal_incoming_count <= 13:
        parser.error("terminal-incoming-count must be between 1 and 13")
    # Keep each governed node at the locked 13-player incoming screen while
    # allowing the later information set to carry a materially different
    # screen. Five synthetic players per position produce seven replacements
    # (six overlaps) without inflating the horizon union to an artificial pair
    # of disjoint screens.
    fixture_extras = 5 if args.l6_shape else args.extra_per_position
    catalog, family = overlapping_fixture(extra_per_position=fixture_extras)
    if args.mode == "search":
        base, _, _, _ = oracle_fixture()
        try:
            generated_policy_limit, retained_pareto_limit = _resolve_policy_candidate_limits(
                legacy=args.max_policy_candidates,
                generated=args.max_generated_policy_candidates,
                retained=args.max_retained_pareto_candidates,
                default_generated=base.search_policy.generated_policy_limit,
                default_retained=base.search_policy.retained_pareto_limit,
            )
        except ValueError as exc:
            parser.error(str(exc))
        for player in base.candidate_pool:
            if player.player_id in base.initial_state.squad_ids:
                catalog[player.player_id] = CandidatePlayer(
                    player_id=player.player_id, club_id=player.club_id, position=player.position
                )
        incoming = tuple(sorted(p for p in catalog if p not in base.initial_state.squad_ids))
        if args.l6_shape:
            per_position = {
                PlayerPosition.GK: 3,
                PlayerPosition.DEF: 4,
                PlayerPosition.MID: 3,
                PlayerPosition.FWD: 3,
            }
            incoming = tuple(
                sorted(
                    player_id
                    for position, count in per_position.items()
                    for player_id in tuple(
                        sorted(
                            item.player_id
                            for item in catalog.values()
                            if item.position is position
                            and item.player_id not in base.initial_state.squad_ids
                        )
                    )[:count]
                )
            )
        prices = {p: PlayerPriceState(current_price_tenths=50) for p in catalog}
        root_maximum_transfers = 2 if args.l6_shape else 1
        root_action_upper = sum(
            len(tuple(combinations(base.initial_state.squad_ids, count)))
            * len(tuple(combinations(incoming, count)))
            for count in range(root_maximum_transfers + 1)
        )
        policy_payload = base.search_policy.model_dump(mode="python")
        policy_payload.update(
            {
                "schema_version": "multi-gameweek-search-policy-v2",
                "max_actions_per_state": 17000,
                "max_returned_root_candidates": (
                    8386 if args.l6_shape else base.search_policy.max_returned_root_candidates
                ),
                "max_generated_policy_candidates": generated_policy_limit,
                "max_retained_pareto_candidates": retained_pareto_limit,
                "transfer_action_scope": TransferActionScope(
                    root_maximum_transfers=root_maximum_transfers,
                    continuation_mode="FREE_TRANSFERS_ONLY",
                ),
                "max_cumulative_legal_actions": (
                    args.cumulative_legal_action_limit
                    if args.cumulative_legal_action_limit is not None
                    else base.search_policy.max_cumulative_legal_actions
                ),
                "policy_sha256": "0" * 64,
            }
        )
        policy_payload.pop("max_policy_candidates")
        probe_policy = seal_search_policy(SearchPolicy.model_validate(policy_payload))
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
                        "search_policy": probe_policy,
                    }
                )
            ),
            incoming,
            prices=prices,
        )
        terminal_incoming = incoming
        if args.l6_shape:
            position_order = (
                PlayerPosition.GK,
                PlayerPosition.DEF,
                PlayerPosition.MID,
                PlayerPosition.FWD,
                PlayerPosition.DEF,
                PlayerPosition.MID,
                PlayerPosition.FWD,
                PlayerPosition.GK,
                PlayerPosition.DEF,
                PlayerPosition.MID,
                PlayerPosition.FWD,
                PlayerPosition.DEF,
                PlayerPosition.GK,
            )
            terminal_counts = {
                PlayerPosition.GK: 3,
                PlayerPosition.DEF: 4,
                PlayerPosition.MID: 3,
                PlayerPosition.FWD: 3,
            }
            terminal_pool = {
                player_id
                for position, count in terminal_counts.items()
                for player_id in tuple(
                    sorted(
                        item.player_id
                        for item in catalog.values()
                        if item.position is position
                        and item.player_id not in base.initial_state.squad_ids
                    )
                )[-count:]
            }
            by_position = {
                position: iter(
                    sorted(
                        item.player_id
                        for item in catalog.values()
                        if item.position is position and item.player_id in terminal_pool
                    )
                )
                for position in PlayerPosition
            }
            terminal_incoming = tuple(
                sorted(
                    next(by_position[position])
                    for position in position_order[: args.terminal_incoming_count]
                )
            )
            nodes = list(request.scenario_tree.nodes)
            terminal = nodes[-1].model_copy(update={"allowed_transfer_in_ids": terminal_incoming})
            terminal = terminal.model_copy(
                update={
                    "information_set_key": information_set_key(
                        terminal,
                        parent_key=nodes[-2].information_set_key,
                    )
                }
            )
            nodes[-1] = terminal
            request = seal_request(
                request.model_copy(
                    update={
                        "scenario_tree": seal_scenario_tree(
                            request.scenario_tree.model_copy(update={"nodes": tuple(nodes)})
                        ),
                        "assumptions": tuple(
                            sorted(
                                {
                                    *request.assumptions,
                                    "SEALED_NODE_SPECIFIC_CANDIDATE_SCOPE_V1",
                                }
                            )
                        ),
                    }
                )
            )
        points = {
            gw: {
                p: (
                    (sum(p.encode()) * (gw + 3)) % 17
                    if args.projection_ordering == "baseline"
                    else ((997 - sum(p.encode())) * (gw + 5)) % 19
                )
                for p in catalog
            }
            for gw in (1, 2, 3)
        }

        class _ShiftedShadowEvaluator(HorizonPointsEvaluator):
            def _value(self, node, squad_ids):
                value = super()._value(node, squad_ids)
                risk = sum(
                    ((sum(player_id.encode()) * (node.gameweek + 7)) % 5) for player_id in squad_ids
                )
                return value.model_copy(
                    update={
                        "p10_points": value.expected_points - risk,
                        "p90_points": value.expected_points + risk,
                    }
                )

        class _StatelessShiftedShadowEvaluator(_StatelessHorizonPointsEvaluator):
            def _value(self, node, squad_ids):
                value = super()._value(node, squad_ids)
                risk = sum(
                    ((sum(player_id.encode()) * (node.gameweek + 7)) % 5) for player_id in squad_ids
                )
                return value.model_copy(
                    update={
                        "p10_points": value.expected_points - risk,
                        "p90_points": value.expected_points + risk,
                    }
                )

        if args.l6_shape:
            evaluator = (
                _StatelessHorizonPointsEvaluator(points)
                if args.projection_ordering == "baseline"
                else _StatelessShiftedShadowEvaluator(points)
            )
        else:
            evaluator = (
                HorizonPointsEvaluator(points)
                if args.projection_ordering == "baseline"
                else _ShiftedShadowEvaluator(points)
            )
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
            "unique_tactical_squads": sum(
                len(node.unique_resulting_squads) for node in profile.nodes.values()
            ),
            "extra_per_position": fixture_extras,
            "candidate_pool_size": len(request.candidate_pool),
            "fixture_extra_players_per_position": fixture_extras,
            "retained_incoming_count": len(incoming),
            "terminal_retained_incoming_count": len(terminal_incoming),
            "root_terminal_incoming_overlap": len(set(incoming) & set(terminal_incoming)),
            "root_incoming_by_position": {
                position.value: sum(
                    catalog[player_id].position is position for player_id in incoming
                )
                for position in PlayerPosition
            },
            "terminal_incoming_by_position": {
                position.value: sum(
                    catalog[player_id].position is position for player_id in terminal_incoming
                )
                for position in PlayerPosition
            },
            "root_action_upper": root_action_upper,
            "effective_max_actions_per_state": request.search_policy.max_actions_per_state,
            "effective_max_returned_root_candidates": (
                request.search_policy.max_returned_root_candidates
            ),
            "configured_max_policy_candidates": request.search_policy.max_policy_candidates,
            "configured_max_generated_policy_candidates": (
                request.search_policy.generated_policy_limit
            ),
            "configured_max_retained_pareto_candidates": (
                request.search_policy.retained_pareto_limit
            ),
            "projection_ordering": args.projection_ordering,
            "stress_case": "L6_SHAPE_13_INCOMING" if args.l6_shape else "GENERAL",
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
            payload["squads_by_node"] = _profile_squads(profile)
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
            payload["unique_tactical_squads"] = sum(
                len(node.unique_resulting_squads) for node in public_profile.nodes.values()
            )
            if not args.summary_only:
                payload["squads_by_node"] = _profile_squads(public_profile)
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
