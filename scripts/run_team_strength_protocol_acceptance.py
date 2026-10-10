"""Bounded portable offline protocol acceptance with exact command evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICKET = "CURRENT-TEAM-STRENGTH-001V-PROTOCOL"
EVIDENCE = ROOT / "evidence" / "tickets" / TICKET


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("quality", "package", "repository"))
    phase = parser.parse_args().phase
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("locked uv frontend unavailable")
    commands = {
        "quality": [
            [uv, "sync", "--all-groups", "--frozen"],
            [uv, "run", "python", "-m", "ruff", "format", "--check", "."],
            [uv, "run", "python", "-m", "ruff", "check", "."],
            [uv, "run", "python", "-m", "mypy", "src/dmf_pulse"],
            [
                uv,
                "run",
                "python",
                "-m",
                "pytest",
                "tests/unit/evaluation",
                "tests/unit/football_events",
                "tests/unit/ingestion/openfootball",
                "tests/unit/private_v1/test_team_strength_u_closure.py",
                "tests/unit/cli/test_team_strength_cli.py",
                "--ignore=tests/unit/evaluation/test_team_strength_campaign_end_to_end.py",
                "--basetemp=review_pack/pytest-regressions",
                "-q",
                "--tb=short",
            ],
        ],
        "package": [
            [uv, "build"],
            [uv, "run", "python", "scripts/verify_team_strength_protocol_wheel.py"],
            [uv, "run", "python", "scripts/verify_team_strength_u_wheel.py"],
        ],
        "repository": [
            [uv, "run", "python", "scripts/generate_repository_manifest.py", "--ticket", "PRC-013"],
            [uv, "run", "python", "scripts/generate_repository_manifest.py", "--ticket", TICKET],
            [uv, "run", "python", "scripts/validate_repository.py", "--ticket", TICKET],
            [uv, "run", "python", "scripts/scan_secrets.py"],
            ["git", "diff", "--check"],
        ],
    }[phase]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (ROOT / "review_pack").mkdir(exist_ok=True)
    records = []
    for index, command in enumerate(commands, 1):
        started = datetime.now(UTC)
        print(f"Starting {phase} acceptance step {index}/{len(commands)}", flush=True)
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2400,
            check=False,
        )
        body = result.stdout + result.stderr
        log = EVIDENCE / f"{phase}-{index:02d}.log"
        log.write_text(body, encoding="utf-8", newline="\n")
        records.append(
            {
                "argv": command,
                "cwd": str(ROOT),
                "started_at": started.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "timeout_seconds": 2400,
                "exit_code": result.returncode,
                "log": log.name,
                "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            }
        )
        (EVIDENCE / f"COMMANDS-{phase.upper()}.json").write_text(
            json.dumps(
                {
                    "commands": records,
                    "status": ("PASS" if index == len(commands) else "RUNNING")
                    if result.returncode == 0
                    else "FAIL",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"Completed {phase} step {index}: exit {result.returncode}", flush=True)
        if result.returncode:
            print(body[-3000:], flush=True)
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
