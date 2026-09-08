"""Synthetic R4 incremental action-space benchmark; no provider access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dmf_pulse.optimisation.multi_gameweek_models import (  # noqa: E402
    TransferActionScope,
    seal_request,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_solver import (  # noqa: E402
    Stage11SearchProfile,
    solve_frontier,
)
from dmf_pulse.private_v1.service import _MemoizedStage10Evaluator  # noqa: E402
from scripts.benchmark_stage11_policy import ExactSurrogate  # noqa: E402
from tests.support.multi_gameweek_factories import NodeSpec, build_request  # noqa: E402
from tests.unit.optimisation.test_future_transfer_scope import LINEAR_ASSUMPTIONS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    incoming = ("p15", "p16", "p17")
    request = build_request(
        (
            NodeSpec("root", 1, allowed_transfer_in_ids=incoming),
            NodeSpec("next", 2, "root", allowed_transfer_in_ids=incoming),
            NodeSpec("last", 3, "next", allowed_transfer_in_ids=incoming),
        ),
        free_transfers=1,
    )
    candidates = {}
    measurements = {}
    for name, maximum, fast in (
        ("old_root_cap", 1, True),
        ("r4_fast", 2, True),
        ("r4_generic", 2, False),
    ):
        policy = seal_search_policy(
            request.search_policy.model_copy(
                update={
                    "max_transfers_per_node": maximum,
                    "transfer_action_scope": TransferActionScope(
                        root_maximum_transfers=1, continuation_mode="FREE_TRANSFERS_ONLY"
                    ),
                }
            )
        )
        scoped = seal_request(
            request.model_copy(update={"search_policy": policy, "assumptions": LINEAR_ASSUMPTIONS})
        )
        evaluator = _MemoizedStage10Evaluator(ExactSurrogate())
        profile = Stage11SearchProfile()
        started = perf_counter()
        result = solve_frontier(
            scoped, evaluator, prefer_deterministic_linear=fast, profile=profile
        )
        elapsed = perf_counter() - started
        if not result.complete:
            raise AssertionError("benchmark did not complete exact enumeration")
        if profile.fast_path_used != fast:
            raise AssertionError("benchmark did not exercise the requested backend")
        candidates[name] = result.candidates
        measurements[name] = {
            "elapsed_seconds": elapsed,
            "profile": profile.as_dict(),
            "tactical_unique_squads": evaluator.cache_misses,
            "tactical_cache_hits": evaluator.cache_hits,
            "root_actions": len({item.root_action.signature for item in result.candidates}),
        }
    if candidates["r4_fast"] != candidates["r4_generic"]:
        raise AssertionError("fast/generic complete policy candidates differ")
    payload = {
        "fixture": "SYNTHETIC_15_PLAYER_3_INCOMING_3_GW_ROOT_FT1",
        "tactical_mode": "EXACT_SYNTHETIC_SURROGATE_NOT_FOOTBALL_MODEL_TIMING",
        "fast_generic_exact_equality": True,
        "measurements": measurements,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                "exact_equality": True,
                "measurements": {
                    key: {
                        "seconds": value["elapsed_seconds"],
                        "root_actions": value["root_actions"],
                    }
                    for key, value in measurements.items()
                },
            }
        )
    )


if __name__ == "__main__":
    main()
