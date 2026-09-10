"""R5 reproducible synthetic candidate-scope and exact-search profiles; no network."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dmf_pulse.fpl_points.models import PlayerPosition  # noqa: E402
from dmf_pulse.optimisation.multi_gameweek_models import seal_request  # noqa: E402
from dmf_pulse.optimisation.multi_gameweek_solver import (  # noqa: E402
    Stage11SearchProfile,
    solve_frontier,
)
from dmf_pulse.private_v1.service import (  # noqa: E402
    _bounded_private_incoming_ids,
    _horizon_private_incoming_ids,
)
from tests.unit.private_v1.horizon_oracle_support import (  # noqa: E402
    HorizonPointsEvaluator,
    oracle_fixture,
    with_candidates,
)
from tests.unit.private_v1.test_horizon_candidate_screen import screen_fixture  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ids, catalog, prices, projections = screen_fixture(count=600)
    positions = tuple(PlayerPosition)
    catalog = {
        p: entry.model_copy(update={"position": positions[i % 4]})
        for i, (p, entry) in enumerate(catalog.items())
    }
    old, removed = _bounded_private_incoming_ids(
        ids, catalog=catalog, prices=prices, gameweek=projections[0], maximum_transfers=1
    )
    started = perf_counter()
    screen = _horizon_private_incoming_ids(
        ids, catalog=catalog, prices=prices, gameweeks=projections, maximum_transfers=1
    )
    screen_seconds = perf_counter() - started
    large_points = {
        gw: {p: g.player_summaries[p].expected_points for p in ids}
        for gw, g in enumerate(projections, start=1)
    }
    full, incoming, projections, points = oracle_fixture("root")
    small_catalog = {p.player_id: p for p in full.candidate_pool}
    small_prices = full.scenario_tree.root.prices
    old_small, _ = _bounded_private_incoming_ids(
        incoming,
        catalog=small_catalog,
        prices=small_prices,
        gameweek=projections[0],
        maximum_transfers=1,
    )
    new_small = _horizon_private_incoming_ids(
        incoming,
        catalog=small_catalog,
        prices=small_prices,
        gameweeks=projections,
        maximum_transfers=1,
    )
    measurements = {}
    policies = {}
    for name, retained, fast in (
        ("R4", old_small, True),
        ("R5", new_small.retained_incoming_ids, True),
        ("R5_GENERIC", new_small.retained_incoming_ids, False),
    ):
        request = with_candidates(full, retained)
        evaluator = HorizonPointsEvaluator(points)
        profile = Stage11SearchProfile()
        started = perf_counter()
        result = solve_frontier(
            request, evaluator, prefer_deterministic_linear=fast, profile=profile
        )
        elapsed = perf_counter() - started
        assert result.complete and profile.fast_path_used == fast
        policies[name] = result.candidates
        measurements[name] = {
            "full_incoming": len(incoming),
            "post_dominance": len(incoming),
            "retained": len(retained),
            "seconds": elapsed,
            "root_actions": len({p.root_action.signature for p in result.candidates}),
            "tactical_unique_node_squads": len(evaluator.cache),
            "profile": profile.as_dict(),
        }
    assert policies["R5"] == policies["R5_GENERIC"]
    base_catalog = tuple(
        p for p in full.candidate_pool if p.player_id in full.initial_state.squad_ids
    )
    large_catalog = tuple(sorted((*base_catalog, *catalog.values()), key=lambda p: p.player_id))
    large_prices = {**{p.player_id: small_prices[p.player_id] for p in base_catalog}, **prices}
    large_request = seal_request(full.model_copy(update={"candidate_pool": large_catalog}))
    large_measurements = {}
    for name, retained in (("R4", old), ("R5", screen.retained_incoming_ids)):
        request = with_candidates(large_request, retained, prices=large_prices)
        evaluator = HorizonPointsEvaluator(large_points)
        profile = Stage11SearchProfile()
        started = perf_counter()
        result = solve_frontier(
            request, evaluator, prefer_deterministic_linear=True, profile=profile
        )
        elapsed = perf_counter() - started
        assert result.complete and profile.fast_path_used
        large_measurements[name] = {
            "full_incoming": len(ids),
            "post_dominance": len(ids),
            "retained": len(retained),
            "seconds": elapsed,
            "root_actions": len({p.root_action.signature for p in result.candidates}),
            "tactical_unique_node_squads": len(evaluator.cache),
            "profile": profile.as_dict(),
        }
    payload = {
        "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "runtime_claim": "SYNTHETIC_TACTICAL_EVALUATOR_NOT_LIVE_STAGE10_TIMING",
        "large_screen": {
            "full_incoming": len(ids),
            "R4_post_dominance": len(ids) - removed,
            "R4_retained": len(old),
            "R5_post_dominance": len(ids),
            "R5_retained": len(screen.retained_incoming_ids),
            "screen_seconds": screen_seconds,
            "audit": asdict(screen),
        },
        "exact_fast_generic_equality": True,
        "measurements": measurements,
        "large_search_measurements": large_measurements,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                "large_screen_counts": [len(ids), len(old), len(screen.retained_incoming_ids)],
                "measurements": {
                    name: {k: v for k, v in values.items() if k != "profile"}
                    for name, values in measurements.items()
                },
                "exact_equality": True,
                "large_search": {
                    name: {k: v for k, v in values.items() if k != "profile"}
                    for name, values in large_measurements.items()
                },
            }
        )
    )


if __name__ == "__main__":
    main()
