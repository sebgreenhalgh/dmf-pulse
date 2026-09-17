"""Run the single authorized transient R9C-A2 observation.

This repository-only operator script has no output-file option, no world selector
and no retry loop.  It prints one safe JSON summary to the invoking terminal.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from typing import Never

from dmf_pulse.private_v1.live_shadow_observation import (
    A2OperatorRequest,
    LiveA2BlockedResult,
    R9CA2LiveShadowObservationService,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.exit(2, "Invalid A2 operator arguments; use --help.\n")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description="One-shot private transient R9C-A2 observation")
    parser.add_argument("--entry-id", type=int, required=True, help=argparse.SUPPRESS)
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--execution-attestation", required=True)
    parser.add_argument("--confirm-one-shot", action="store_true", required=True)
    parser.add_argument("--scenario-count", type=int, default=256)
    parser.add_argument("--root-seed", type=int, default=20260901)
    return parser


def main() -> int:
    args = _parser().parse_args()
    approved_at = datetime.now(UTC)
    service = R9CA2LiveShadowObservationService()
    result = service.run(
        A2OperatorRequest(
            entry_id=args.entry_id,
            code_sha=args.code_sha,
            operator_approved_at=approved_at,
            acquisition_cutoff=approved_at + timedelta(minutes=5),
            provider_approval_reference=args.approval_reference,
            execution_attestation=args.execution_attestation,
            scenario_count=args.scenario_count,
            root_seed=args.root_seed,
        )
    )
    if isinstance(result, LiveA2BlockedResult):
        print(json.dumps(result.public_dict(), sort_keys=True, separators=(",", ":")))
        return 2
    summary = service.take_safe_summary(result)
    if isinstance(summary, LiveA2BlockedResult):
        print(json.dumps(summary.public_dict(), sort_keys=True, separators=(",", ":")))
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
