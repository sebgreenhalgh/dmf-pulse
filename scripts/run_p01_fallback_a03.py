"""Execute the independently reviewed, CI-sealed, single A03 authorization."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.ingestion.p01_a03_execution import execute_a03
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    DiagnosticProgress,
    FailureReason,
    P01FallbackExecutionFailure,
    ReasonFailure,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--review-binding", type=Path, required=True)
    parser.add_argument("--review-binding-sha256", required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    progress = DiagnosticProgress()
    try:
        result = execute_a03(
            forecast_path=args.forecast,
            review_path=args.review,
            binding_path=args.review_binding,
            expected_binding_sha256=args.review_binding_sha256,
            implementation_root=Path(__file__).resolve().parents[1],
            artifact_root=args.artifact_root,
            progress=progress,
        )
    except P01FallbackExecutionFailure as failure:
        print(
            pretty_json(
                {
                    "status": "P01_A03_PRECHECK_STOPPED",
                    "stage": failure.stage.value,
                    "reason": failure.reason.value,
                    "diagnostics": failure.diagnostics.model_dump(mode="json"),
                    "scoring_performed": False,
                    "production_active": False,
                }
            ),
            end="",
        )
        return 2
    except Exception as failure:
        # Last-resort storage/runtime failure: disclose only a closed reason and
        # safe progress. Never emit arbitrary exceptions or claim a sealed result.
        reason = (
            failure.reason
            if isinstance(failure, ReasonFailure)
            else FailureReason.UNKNOWN_P01_OUTCOME_FAILURE
        )
        print(
            pretty_json(
                {
                    "status": "P01_A03_STOPPED_UNSEALED_HANDOFF",
                    "stage": progress.stage.value,
                    "reason": reason.value,
                    "diagnostics": progress.safe.model_dump(mode="json"),
                    "production_active": False,
                }
            ),
            end="",
        )
        return 2
    print(pretty_json(result), end="")
    return 0 if result.status == "P01_A03_COMPLETE" else 2


if __name__ == "__main__":
    sys.exit(main())
