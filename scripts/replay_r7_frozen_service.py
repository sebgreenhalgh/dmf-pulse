"""Offline full private-stack frozen R6/R7 differential artifact (synthetic only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter, process_time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.code_root.resolve()
    sys.path[:0] = [str(root / "src"), str(root)]

    from dmf_pulse.private_v1.models import seal_candidate_action_policy, seal_execution_input
    from dmf_pulse.private_v1.rolling import PrivateV1RollingRecommendationService
    from dmf_pulse.private_v1.rolling_models import seal_rolling_execution_input
    from tests.unit.private_v1.e2e_test_support import build_rolling_execution_input

    execution = build_rolling_execution_input(root, args.fixture_dir.resolve())
    current = execution.current_execution
    # Preserve the synthetic factory's frozen projection/scenario input. The real
    # automatic V3 assembly is selected by its existing contract marker.
    policy = seal_candidate_action_policy(
        current.candidate_action_policy.model_copy(
            update={"rationale": "PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1"}
        )
    )
    current = seal_execution_input(current.model_copy(update={"candidate_action_policy": policy}))
    execution = seal_rolling_execution_input(
        execution.model_copy(
            update={
                "current_execution": current,
                "search_scope_mode": "PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V3",
            }
        )
    )
    wall, cpu = perf_counter(), process_time()
    result = PrivateV1RollingRecommendationService().run(execution)
    payload = {
        "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "wall_seconds": perf_counter() - wall,
        "cpu_seconds": process_time() - cpu,
        "execution_sha256": execution.semantic_sha256,
        "request": result.optimiser_request.model_dump(mode="json"),
        "decision": result.decision.model_dump(mode="json"),
        "optimiser_result": result.optimiser_result.model_dump(mode="json"),
        "one_gameweek_result": result.one_gameweek_optimiser_result.model_dump(mode="json"),
        "projection_hashes": [p.result_sha256 for p in result.gameweek_projections],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in payload.items()
                if k not in {"request", "decision", "optimiser_result", "one_gameweek_result"}
            }
        )
    )


if __name__ == "__main__":
    main()
