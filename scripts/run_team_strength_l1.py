"""Separate public preflight and terminal-only private L1 observation.

Publication/review/exact-SHA CI are operator gates documented in the L1 ticket.
This script has no retry loop, output-file option, normal CLI registration, model
selector, scenario-count override or player-allocation override.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Never

from dmf_pulse.ingestion.openfootball.team_strength_corpus import load_reconstructed_corpus
from dmf_pulse.ingestion.openfootball.team_strength_current import (
    CurrentTeamStrengthReadiness,
    acquire_current_public,
    public_preflight_summary,
    retain_public_readiness,
    retain_public_source,
)
from dmf_pulse.private_v1.team_strength_live import (
    L1OperatorRequest,
    TeamStrengthL1ObservationService,
    json_safe,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.exit(2, "Invalid L1 operator arguments; use --help.\n")


def parser() -> argparse.ArgumentParser:
    result = _Parser(
        description="Separate public readiness and one-shot private CTS L1 observation"
    )
    commands = result.add_subparsers(dest="command", required=True, parser_class=_Parser)
    public = commands.add_parser("public-preflight")
    public.add_argument("--commit", required=True)
    public.add_argument("--historical-corpus", type=Path, required=True)
    public.add_argument("--public-artifact-root", type=Path, required=True)
    private = commands.add_parser("observe")
    private.add_argument("--public-readiness", type=Path, required=True)
    private.add_argument("--readiness-sha256", required=True)
    private.add_argument("--entry-id", type=int, required=True, help=argparse.SUPPRESS)
    private.add_argument("--code-sha", required=True)
    private.add_argument("--approval-reference", required=True)
    private.add_argument("--execution-attestation", required=True)
    private.add_argument("--confirm-one-shot", action="store_true", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    # This is an operator terminal surface, not a file/export interface. Public
    # OpenFootball persistence below is explicitly separated from private data.
    if args.command == "observe" and not sys.stdout.isatty():
        print('{"status":"BLOCKED","reason":"TERMINAL_REQUIRED","private_attempt_consumed":false}')
        return 2
    try:
        if args.command == "public-preflight":
            registry, sources = load_reconstructed_corpus(args.historical_corpus)
            result, acquired = acquire_current_public(
                commit=args.commit, historical_sources=sources, fixtures=registry
            )
            summary = public_preflight_summary(result)
            if result.readiness is not None:
                retain_public_source(acquired, artifact_root=args.public_artifact_root)
                retain_public_readiness(result.readiness, artifact_root=args.public_artifact_root)
            print(json.dumps(json_safe(summary), sort_keys=True))
            return 0 if result.readiness is not None else 2
        ready = CurrentTeamStrengthReadiness.model_validate_json(args.public_readiness.read_bytes())
    except (Exception, KeyboardInterrupt):
        print(
            '{"status":"TEAM_STRENGTH_PUBLIC_PREFLIGHT_BLOCKED","reason":"PUBLIC_EVIDENCE_INVALID_OR_UNAVAILABLE","private_attempt_consumed":false,"fpl_requests":0,"odds_requests":0}'
        )
        return 2
    service = TeamStrengthL1ObservationService()

    def network_audit(event: str, values: tuple[object, ...]) -> None:
        # One-way process-local backstop for an unexpected additional service,
        # including one that does not use any of the three instrumented clients.
        del values
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"}:
            service.guard_network_event()

    sys.addaudithook(network_audit)
    summary = service.run(
        L1OperatorRequest(
            entry_id=args.entry_id,
            code_sha=args.code_sha,
            approval=args.approval_reference,
            attestation=args.execution_attestation,
            readiness_sha256=args.readiness_sha256,
        ),
        ready,
    )
    print(json.dumps(json_safe(summary), sort_keys=True))
    return (
        0 if summary["status"] == "CURRENT_TEAM_STRENGTH_001P_L1_LIVE_OBSERVATION_COMPLETE" else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
