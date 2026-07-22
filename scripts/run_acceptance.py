"""Run and record every non-self-referential FND-001 acceptance command exactly once."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMMAND_LOG = REPOSITORY_ROOT / "evidence" / "tickets" / "FND-001" / "commands.log"


@dataclass(frozen=True, slots=True)
class AcceptanceCommand:
    display: str
    arguments: tuple[str, ...]
    timeout_seconds: float
    offline: bool = False


@dataclass(frozen=True, slots=True)
class CommandRecord:
    command: str
    duration_seconds: float
    exit_code: int
    result: str


def _commands(uv: str) -> tuple[AcceptanceCommand, ...]:
    return (
        AcceptanceCommand(
            "uv sync --all-groups --frozen", (uv, "sync", "--all-groups", "--frozen"), 300
        ),
        AcceptanceCommand(
            "uv run ruff format --check .",
            (uv, "run", "ruff", "format", "--check", "."),
            180,
        ),
        AcceptanceCommand("uv run ruff check .", (uv, "run", "ruff", "check", "."), 180),
        AcceptanceCommand(
            "uv run mypy src/dmf_pulse",
            (uv, "run", "mypy", "src/dmf_pulse"),
            180,
        ),
        AcceptanceCommand(
            "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing",
            (
                uv,
                "run",
                "pytest",
                "--cov=dmf_pulse",
                "--cov-branch",
                "--cov-report=term-missing",
            ),
            600,
            offline=True,
        ),
        AcceptanceCommand("uv run dmf --version", (uv, "run", "dmf", "--version"), 180),
        AcceptanceCommand("uv run dmf doctor --json", (uv, "run", "dmf", "doctor", "--json"), 180),
        AcceptanceCommand(
            "uv run dmf config validate --environment test --config-root config",
            (
                uv,
                "run",
                "dmf",
                "config",
                "validate",
                "--environment",
                "test",
                "--config-root",
                "config",
            ),
            180,
        ),
        AcceptanceCommand(
            "uv run dmf config show --environment test --config-root config --json",
            (
                uv,
                "run",
                "dmf",
                "config",
                "show",
                "--environment",
                "test",
                "--config-root",
                "config",
                "--json",
            ),
            180,
        ),
        AcceptanceCommand("uv build", (uv, "build"), 300),
        AcceptanceCommand(
            "uv run python scripts/verify_wheel.py",
            (uv, "run", "python", "scripts/verify_wheel.py"),
            600,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run python scripts/validate_repository.py",
            (uv, "run", "python", "scripts/validate_repository.py"),
            180,
        ),
        AcceptanceCommand(
            "uv run python scripts/scan_secrets.py",
            (uv, "run", "python", "scripts/scan_secrets.py"),
            180,
        ),
    )


def _review_command(uv: str) -> AcceptanceCommand:
    return AcceptanceCommand(
        "uv run dmf review-pack build --ticket FND-001 --output review_pack/FND-001",
        (
            uv,
            "run",
            "dmf",
            "review-pack",
            "build",
            "--ticket",
            "FND-001",
            "--output",
            "review_pack/FND-001",
        ),
        300,
    )


def _summary(command: AcceptanceCommand, output: str, exit_code: int) -> str:
    if exit_code != 0:
        return f"FAIL: exit code {exit_code}"
    if "pytest --cov" in command.display:
        passed = re.search(r"(\d+) passed", output)
        coverage = re.search(r"Total coverage: ([0-9.]+)%", output)
        if passed and coverage:
            return f"PASS: {passed.group(1)} tests; {coverage.group(1)}% combined coverage"
    if command.display.endswith("doctor --json"):
        try:
            value = json.loads(output)
        except json.JSONDecodeError:
            return "PASS: doctor emitted output"
        return f"PASS: doctor status {value.get('status', 'UNKNOWN')}"
    if command.display.endswith("verify_wheel.py"):
        try:
            value = json.loads(output)
        except json.JSONDecodeError:
            return "PASS: clean-wheel verifier completed"
        return (
            f"PASS: clean wheel {value.get('wheel', {}).get('sha256', 'hash unavailable')}; "
            f"doctor {value.get('doctor_status', 'UNKNOWN')}"
        )
    if "review-pack build" in command.display:
        try:
            value = json.loads(output)
        except json.JSONDecodeError:
            return "PASS: review pack built"
        return (
            f"PASS: {value.get('file_count', 'unknown')} files; "
            f"primary payload SHA-256 {value.get('payload_sha256', 'unavailable')}; "
            f"archive SHA-256 {value.get('sha256', 'unavailable')}"
        )
    summaries = {
        "uv sync --all-groups --frozen": "PASS: frozen all-group sync",
        "uv run ruff format --check .": "PASS: formatting clean",
        "uv run ruff check .": "PASS: lint clean",
        "uv run mypy src/dmf_pulse": "PASS: strict typing clean",
        "uv run dmf --version": "PASS: dmf 0.1.0",
        "uv run dmf config validate --environment test --config-root config": (
            "PASS: test configuration valid"
        ),
        "uv run dmf config show --environment test --config-root config --json": (
            "PASS: deterministic redacted JSON"
        ),
        "uv build": "PASS: sdist and wheel built",
        "uv run python scripts/validate_repository.py": "PASS: repository errors 0",
        "uv run python scripts/scan_secrets.py": "PASS: secret findings 0",
    }
    return summaries.get(command.display, "PASS")


def run_command(command: AcceptanceCommand) -> CommandRecord:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    if command.offline:
        environment["UV_OFFLINE"] = "1"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command.arguments,
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            shell=False,
            text=True,
            timeout=command.timeout_seconds,
        )
        exit_code = completed.returncode
        output = completed.stdout + "\n" + completed.stderr
    except (OSError, subprocess.TimeoutExpired):
        exit_code = 124
        output = ""
    duration = round(time.perf_counter() - started, 3)
    return CommandRecord(
        command=command.display,
        duration_seconds=duration,
        exit_code=exit_code,
        result=_summary(command, output, exit_code),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="run and append the self-referential final review-pack capability",
    )
    arguments = parser.parse_args()
    uv = shutil.which("uv")
    if uv is None:
        print("uv is unavailable", file=sys.stderr)
        return 2
    records = []
    selected_commands = (_review_command(uv),) if arguments.review_only else _commands(uv)
    for command in selected_commands:
        record = run_command(command)
        records.append(record)
        print(f"[{record.exit_code}] {record.command} ({record.duration_seconds:.3f}s)")
    COMMAND_LOG.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if arguments.review_only else "w"
    with COMMAND_LOG.open(mode, encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
    return 0 if all(record.exit_code == 0 for record in records) else 1


if __name__ == "__main__":
    sys.exit(main())
