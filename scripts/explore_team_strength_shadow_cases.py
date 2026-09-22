"""Offline synthetic acceptance-case construction, never historical model selection.

Runs the unchanged accepted models and canonical optimiser. Only generated source
histories and shared experiment seeds vary, identically across the two worlds.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dmf_pulse.private_v1.models import (  # noqa: E402
    seal_candidate_action_policy,
    seal_execution_input,
)
from dmf_pulse.private_v1.rolling_models import seal_rolling_execution_input  # noqa: E402
from dmf_pulse.private_v1.team_strength_comparison import (  # noqa: E402
    run_team_strength_shadow_comparison,
    safe_team_strength_summary,
)
from dmf_pulse.private_v1.team_strength_shadow_inputs import (  # noqa: E402
    prepare_team_strength_shadow,
)
from tests.unit.private_v1.team_strength_shadow_support import (  # noqa: E402
    synthetic_model_prepared,
    synthetic_strength,
)


def blocked(*args, **kwargs):
    raise AssertionError("synthetic case exploration must remain offline")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--variant", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--screen", action="store_true")
    args = parser.parse_args()
    socket.getaddrinfo = blocked
    socket.create_connection = blocked
    socket.socket.connect = blocked
    started = perf_counter()
    prepared = synthetic_model_prepared(ROOT, ROOT / "review_pack" / (args.output.stem + "-input"))
    dataset, artifact = synthetic_strength(args.variant)
    preparation_ms = Decimal(str((perf_counter() - started) * 1000))
    print(json.dumps({"preparation_ms": str(preparation_ms), "variant": args.variant}), flush=True)
    reports = []
    for seed in args.seeds:
        execution = prepared.rolling_execution
        current = execution.current_execution
        updates = {"root_seed": seed}
        if args.screen:
            owned = {row.official_fpl_element_id for row in current.ownership.members}
            incoming = tuple(
                sorted(
                    row.provider_element_id
                    for row in current.current_state.fpl_input.players
                    if row.position.value == "GK" and row.provider_element_id not in owned
                )
            )
            policy = current.candidate_action_policy
            updates["candidate_action_policy"] = seal_candidate_action_policy(
                type(policy).model_construct(
                    **(
                        dict(policy)
                        | {
                            "allowed_transfer_in_element_ids": incoming,
                            "rationale": "PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1: synthetic complete goalkeeper candidate universe",
                        }
                    )
                )
            )
        current = seal_execution_input(type(current).model_construct(**(dict(current) | updates)))
        execution = seal_rolling_execution_input(
            type(execution).model_construct(**(dict(execution) | {"current_execution": current}))
        )
        case = replace(prepared, rolling_execution=execution)
        preparation = prepare_team_strength_shadow(
            execution,
            artifact=artifact,
            expected_artifact_sha256=artifact.semantic_sha256,
            fixture_registry=dataset.fixture_registry,
        )
        run = run_team_strength_shadow_comparison(case, preparation, preparation_ms=preparation_ms)
        summary = safe_team_strength_summary(run)
        by_gw = [
            [
                {
                    "gw": row.gameweek,
                    "transfers": [
                        (move.player_out_id, move.player_in_id) for move in row.transfers
                    ],
                    "xi": row.tactics.starting_xi,
                    "captain": row.tactics.captain,
                    "vice": row.tactics.vice_captain,
                }
                for row in world.signature.by_gameweek
            ]
            for world in run.comparison.worlds
        ]
        reports.append(
            {
                "seed": seed,
                "variant": args.variant,
                "screen": args.screen,
                "summary": summary,
                "synthetic_by_gameweek": by_gw,
            }
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(reports, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "seed": seed,
                    "classification": run.comparison.comparison.classification,
                    "delta": str(run.comparison.comparison.utility_delta),
                    "root": [world[0]["transfers"] for world in by_gw],
                    "root_captain": [world[0]["captain"] for world in by_gw],
                    "root_xi_equal": by_gw[0][0]["xi"] == by_gw[1][0]["xi"],
                    "screen_equal": run.comparison.comparison.candidate_screen_equal,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
