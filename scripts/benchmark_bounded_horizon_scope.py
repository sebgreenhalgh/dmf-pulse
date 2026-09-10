"""R6 synthetic capacity/search profiles, including node-specific FT2 exact recourse."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dmf_pulse.assurance.canonical import canonical_sha256, sha256_file  # noqa: E402
from dmf_pulse.optimisation.multi_gameweek_errors import ResourceLimitReached  # noqa: E402
from dmf_pulse.optimisation.multi_gameweek_models import (  # noqa: E402
    PlayerPriceState,
    seal_request,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_solver import (  # noqa: E402
    Stage11SearchProfile,
    solve_frontier,
)
from dmf_pulse.private_v1.horizon_candidates import bounded_horizon_screen  # noqa: E402
from scripts.profile_horizon_candidate_pressure import pressure_fixture, v2_pressure  # noqa: E402
from tests.unit.private_v1.horizon_oracle_support import (  # noqa: E402
    HorizonPointsEvaluator,
    oracle_fixture,
    with_candidates,
)
from tests.unit.private_v1.test_bounded_horizon_oracle import with_node_candidates  # noqa: E402


def near_limit_fixture():
    ids, catalog, prices, projections = pressure_fixture("low_overlap")
    # Six distinct economic/football bucket leaders per position; two protected extras.
    for i, p in enumerate(ids):
        rank = i // 4
        prices[p] = PlayerPriceState(current_price_tenths={3: 10, 4: 1}.get(rank, 50))
        for gw, projection in enumerate(projections):
            mean = {0: 20, 1: 19, 2: 30 if gw == 0 else 0, 3: 10, 4: 0, 5: -1}.get(rank, -rank)
            projection.player_summaries[p].expected_points = mean
            projection.player_summaries[p].points_standard_deviation = 100 if rank == 5 else 0
            projection.scenario_set.scenarios[0].player_points[p] = mean
    for gw, projection in enumerate(projections):
        projection.result_sha256 = canonical_sha256(
            {"gw": gw, "points": projection.scenario_set.scenarios[0].player_points}
        )
    return ids, catalog, prices, projections


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--collect-from", type=Path)
    mode.add_argument(
        "--shape",
        choices=("large_tie", "low_overlap", "high_overlap", "near_limit", "oracle"),
    )
    args = parser.parse_args()
    if args.collect_from is not None:
        shapes = ("large_tie", "low_overlap", "high_overlap", "oracle", "near_limit")
        final = {
            shape: json.loads(
                (args.collect_from / f"final-{shape}.json").read_text(encoding="utf-8")
            )
            for shape in shapes
        }
        assert all(data["V3_screen"]["maximum_retained"] == 18 for data in final.values())
        source_paths = (
            "src/dmf_pulse/private_v1/horizon_candidates.py",
            "src/dmf_pulse/private_v1/service.py",
            "src/dmf_pulse/private_v1/rolling.py",
            "src/dmf_pulse/private_v1/rolling_models.py",
            "src/dmf_pulse/private_v1/one_command.py",
            "src/dmf_pulse/optimisation/multi_gameweek_solver.py",
        )
        payload = {
            "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
            "runtime_claim": "SYNTHETIC_TACTICAL_EVALUATOR_NOT_LIVE_STAGE10_TIMING",
            "production_source_sha256": {p: sha256_file(ROOT / p) for p in source_paths},
            "V2_pressure": json.loads(
                (args.collect_from / "v2-pressure.json").read_text(encoding="utf-8")
            ),
            "final_V3": final,
            "rejected_six_bucket_prototype": {
                shape: json.loads((args.collect_from / f"{shape}.json").read_text(encoding="utf-8"))
                for shape in ("low_overlap", "near_limit")
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "sha256": sha256_file(args.output),
                    "shapes": list(final),
                }
            )
        )
        return
    if args.shape == "oracle":
        request, ids, projections, points = oracle_fixture("root")
        catalog = {p.player_id: p for p in request.candidate_pool}
        prices = request.scenario_tree.root.prices
        protected = ("p15",)
        pressure = None
    else:
        fixture = (
            near_limit_fixture() if args.shape == "near_limit" else pressure_fixture(args.shape)
        )
        ids, catalog, prices, projections = fixture
        pressure = v2_pressure(fixture)
        protected = ids[28:30] if args.shape == "near_limit" else ()
        base, _, _, _ = oracle_fixture()
        owned = tuple(p for p in base.candidate_pool if p.player_id in base.initial_state.squad_ids)
        all_catalog = tuple(sorted((*owned, *catalog.values()), key=lambda p: p.player_id))
        all_prices = {
            **{p.player_id: base.scenario_tree.root.prices[p.player_id] for p in owned},
            **prices,
        }
        request = with_candidates(
            seal_request(base.model_copy(update={"candidate_pool": all_catalog})),
            ids,
            prices=all_prices,
        )
        points = {
            gw: {p: g.player_summaries[p].expected_points for p in ids}
            for gw, g in enumerate(projections, start=1)
        }
    started = perf_counter()
    screen = bounded_horizon_screen(
        ids, catalog=catalog, prices=prices, gameweeks=projections, protected_incoming_ids=protected
    )
    screening_seconds = perf_counter() - started
    request = with_node_candidates(request, tuple(n.retained_incoming_ids for n in screen.nodes))
    policy = seal_search_policy(
        request.search_policy.model_copy(
            update={"max_actions_per_state": screen.maximum_action_combinations}
        )
    )
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    measurements = {}
    candidates = []
    for fast in (True, False) if args.shape == "oracle" else (True,):
        profile = Stage11SearchProfile()
        evaluator = HorizonPointsEvaluator(points)
        started = perf_counter()
        try:
            result = solve_frontier(
                request, evaluator, prefer_deterministic_linear=fast, profile=profile
            )
        except ResourceLimitReached as exc:
            measurements["fast" if fast else "generic"] = {
                "status": "RESOURCE_LIMIT_NOT_OPTIMAL",
                "reason": exc.message,
                "seconds": perf_counter() - started,
                "unique_tactical_node_squads": len(evaluator.cache),
                "profile": profile.as_dict(),
            }
            break
        elapsed = perf_counter() - started
        assert result.complete and profile.fast_path_used == fast
        candidates.append(result.candidates)
        measurements["fast" if fast else "generic"] = {
            "status": "COMPLETE_EXACT_WITHIN_DECLARED_SCOPE",
            "seconds": elapsed,
            "unique_tactical_node_squads": len(evaluator.cache),
            "root_actions": len({p.root_action.signature for p in result.candidates}),
            "profile": profile.as_dict(),
        }
    assert len(candidates) < 2 or candidates[0] == candidates[1]
    payload = {
        "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "shape": args.shape,
        "runtime_claim": "SYNTHETIC_TACTICAL_EVALUATOR_NOT_LIVE_STAGE10_TIMING",
        "screening_seconds": screening_seconds,
        "V2_pressure": pressure,
        "V3_screen": asdict(screen),
        "measurements": measurements,
        "fast_generic_equality": True if len(candidates) == 2 else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                "shape": args.shape,
                "full": len(ids),
                "V2_union": None if pressure is None else pressure["v2_union"],
                "V3_nodes": [len(n.retained_incoming_ids) for n in screen.nodes],
                "screen_seconds": screening_seconds,
                "measurements": {
                    k: {key: val for key, val in v.items() if key != "profile"}
                    for k, v in measurements.items()
                },
            }
        )
    )


if __name__ == "__main__":
    main()
