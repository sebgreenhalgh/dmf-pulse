"""Retired A02 execution gate with safe diagnostics; D1 grants no live authority."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.evaluation.p01_fallback_context import CONTEXT_SHA
from dmf_pulse.ingestion.p01_fallback_acquisition import acquire_p01_once
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    DiagnosticProgress,
    ExecutionStage,
    FailureReason,
    P01FallbackExecutionFailure,
    persist_stopped,
    stopped_record,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--review-sha256", required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    started = datetime.now(UTC)
    progress = DiagnosticProgress()
    try:
        acquire_p01_once(
            forecast_path=args.forecast,
            review_path=args.review,
            expected_review_sha256=args.review_sha256,
            implementation_root=Path(__file__).resolve().parents[1],
            artifact_root=args.artifact_root,
            progress=progress,
        )
    except P01FallbackExecutionFailure as failure:
        record = stopped_record(
            failure,
            started_at=started,
            stopped_at=datetime.now(UTC),
            context_sha256=None if failure.stage == ExecutionStage.LOAD_CONTEXT else CONTEXT_SHA,
            one_attempt_consumed=True,
        )
        persisted = False
        persistence_reason: str | None = None
        # No provider receipts exist before rights authentication; do not write
        # internal provider evidence when that prerequisite has failed.
        if failure.stage not in {ExecutionStage.LOAD_CONTEXT, ExecutionStage.AUTHENTICATE_RIGHTS}:
            try:
                persist_stopped(record, root=args.artifact_root)
                persisted = True
            except Exception:
                persistence_reason = FailureReason.PERSISTENCE_FAILED.value
        print(
            pretty_json(
                {
                    "stopped_diagnostic": record.model_dump(mode="json"),
                    "diagnostic_persisted": persisted,
                    "diagnostic_persistence_reason": persistence_reason,
                }
            ),
            end="",
        )
        return 2
    # No scoring import or scoring operation exists in this retired entrypoint.
    print(
        pretty_json(
            {
                "stage": ExecutionStage.COMPLETE.value,
                "scoring_performed": False,
                "production_active": False,
            }
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
