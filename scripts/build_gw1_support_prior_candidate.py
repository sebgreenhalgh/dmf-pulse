"""Build the unaccepted GW1 support-prior candidate from a local pinned clone.

Network retrieval is intentionally outside this script.  It accepts only an
already checked-out OpenFootball source tree and refuses any commit other than
the governed pin, so CI and deterministic tests never need GitHub access.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dmf_pulse.football_events.service import load_score_baseline_policy
from dmf_pulse.football_events.support_prior import (
    SOURCE_COMMIT,
    build_candidate_artifact,
    calibrate_openfootball_support_prior,
    canonical_candidate_json,
)


def _pinned_source_commit(source_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError("source_root must be a local Git checkout at the governed source pin")
    commit = completed.stdout.strip()
    if commit != SOURCE_COMMIT:
        raise ValueError(f"source_root commit drift: expected {SOURCE_COMMIT}, got {commit}")
    dirty = subprocess.run(
        ["git", "-C", str(source_root), "status", "--porcelain"],
        check=False,
        capture_output=True,
        text=True,
    )
    if dirty.returncode != 0 or dirty.stdout:
        raise ValueError("source_root must be clean before candidate calibration")
    return commit


def _write_content_addressed(path: Path, content: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == content:
            return
        raise FileExistsError(f"refusing to overwrite different candidate artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-retrieved-at", required=True)
    parser.add_argument("--produced-at", required=True)
    parser.add_argument("--information-cutoff", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _pinned_source_commit(args.source_root)
        calibration = calibrate_openfootball_support_prior(args.source_root)
        artifact = build_candidate_artifact(
            calibration,
            policy=load_score_baseline_policy(),
            source_retrieved_at=args.source_retrieved_at,
            produced_at=args.produced_at,
            information_cutoff=args.information_cutoff,
            code_commit=args.code_commit,
        )
        _write_content_addressed(args.output, canonical_candidate_json(artifact))
    except (OSError, ValueError) as exc:
        print(f"GW1 support-prior candidate blocked: {exc}", file=sys.stderr)
        return 2
    print(artifact["artifact_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
