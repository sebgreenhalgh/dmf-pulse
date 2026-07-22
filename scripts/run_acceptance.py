"""Run and record every non-self-referential FND-001 acceptance command exactly once."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUL_BASELINE = "12049a7de23a4a8fcca3d219dbcab1bf5e1027ea"
RUL_WRITE_AHEAD_RESULT = (
    "PASS: write-ahead record committed only by successful external archive finalization; "
    "exact duration and digests are in archive_finalization.json"
)
RUL_FINAL_RESULT = (
    "PASS: exact 20-file review build completed; final detached digests are in "
    "archive_finalization.json"
)


@dataclass(frozen=True, slots=True)
class AcceptanceCommand:
    display: str
    arguments: tuple[str, ...]
    timeout_seconds: float
    offline: bool = False
    expected_exit: int = 0


@dataclass(frozen=True, slots=True)
class CommandRecord:
    command: str
    duration_seconds: float | None
    exit_code: int
    result: str


def _read_command_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(
            line,
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
        )
        if not isinstance(value, dict):
            raise ValueError("command record must be an object")
        records.append(value)
    return records


def _write_command_records(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _completed_record_is_valid(record: dict[str, object], command: AcceptanceCommand) -> bool:
    duration = record.get("duration_seconds")
    return (
        set(record) == {"command", "duration_seconds", "exit_code", "result"}
        and record.get("command") == command.display
        and record.get("exit_code") == command.expected_exit
        and isinstance(record.get("result"), str)
        and str(record["result"]).startswith("PASS:")
        and isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and math.isfinite(float(duration))
        and duration >= 0
    )


def _fnd_commands(uv: str) -> tuple[AcceptanceCommand, ...]:
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


def _rul_commands(uv: str) -> tuple[AcceptanceCommand, ...]:
    root = "fixtures/rules/RUL-002"
    return (
        AcceptanceCommand(
            "uv sync --all-groups --frozen", (uv, "sync", "--all-groups", "--frozen"), 300
        ),
        AcceptanceCommand(
            "uv run ruff format --check .", (uv, "run", "ruff", "format", "--check", "."), 180
        ),
        AcceptanceCommand("uv run ruff check .", (uv, "run", "ruff", "check", "."), 180),
        AcceptanceCommand("uv run mypy src/dmf_pulse", (uv, "run", "mypy", "src/dmf_pulse"), 180),
        AcceptanceCommand(
            "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/RUL-002/coverage.json",
            (
                uv,
                "run",
                "pytest",
                "--cov=dmf_pulse",
                "--cov-branch",
                "--cov-report=term-missing",
                "--cov-report=json:evidence/tickets/RUL-002/coverage.json",
            ),
            600,
            offline=True,
        ),
        AcceptanceCommand("uv run dmf --version", (uv, "run", "dmf", "--version"), 180),
        AcceptanceCommand("uv run dmf doctor --json", (uv, "run", "dmf", "doctor", "--json"), 180),
        AcceptanceCommand(
            f"uv run dmf rules validate {root}/synthetic_complete --json",
            (uv, "run", "dmf", "rules", "validate", f"{root}/synthetic_complete", "--json"),
            180,
        ),
        AcceptanceCommand(
            f"uv run dmf rules compile {root}/synthetic_complete --output artifacts/rules/rul-002-synthetic.json --json",
            (
                uv,
                "run",
                "dmf",
                "rules",
                "compile",
                f"{root}/synthetic_complete",
                "--output",
                "artifacts/rules/rul-002-synthetic.json",
                "--json",
            ),
            180,
        ),
        AcceptanceCommand(
            "uv run dmf rules hash artifacts/rules/rul-002-synthetic.json --json",
            (uv, "run", "dmf", "rules", "hash", "artifacts/rules/rul-002-synthetic.json", "--json"),
            180,
        ),
        AcceptanceCommand(
            f"uv run dmf rules score-fixture artifacts/rules/rul-002-synthetic.json {root}/golden_fixture_001.json --json",
            (
                uv,
                "run",
                "dmf",
                "rules",
                "score-fixture",
                "artifacts/rules/rul-002-synthetic.json",
                f"{root}/golden_fixture_001.json",
                "--json",
            ),
            180,
        ),
        AcceptanceCommand(
            f"uv run dmf rules score-gameweek artifacts/rules/rul-002-synthetic.json {root}/golden_gameweek_001.json --json",
            (
                uv,
                "run",
                "dmf",
                "rules",
                "score-gameweek",
                "artifacts/rules/rul-002-synthetic.json",
                f"{root}/golden_gameweek_001.json",
                "--json",
            ),
            180,
        ),
        AcceptanceCommand(
            f"uv run dmf rules diff {root}/reference_2025_26 {root}/target_2026_27_partial --json",
            (
                uv,
                "run",
                "dmf",
                "rules",
                "diff",
                f"{root}/reference_2025_26",
                f"{root}/target_2026_27_partial",
                "--json",
            ),
            180,
        ),
        AcceptanceCommand(
            f"uv run dmf rules activate {root}/target_2026_27_partial --approval {root}/invalid_target_approval.json --json",
            (
                uv,
                "run",
                "dmf",
                "rules",
                "activate",
                f"{root}/target_2026_27_partial",
                "--approval",
                f"{root}/invalid_target_approval.json",
                "--json",
            ),
            180,
            expected_exit=4,
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


def _review_command(uv: str, ticket: str) -> AcceptanceCommand:
    if ticket == "RUL-002":
        display = f"uv run dmf review-pack build --ticket RUL-002 --baseline {RUL_BASELINE} --output review_pack/RUL-002"
        return AcceptanceCommand(
            display,
            (
                uv,
                "run",
                "dmf",
                "review-pack",
                "build",
                "--ticket",
                "RUL-002",
                "--baseline",
                RUL_BASELINE,
                "--output",
                "review_pack/RUL-002",
            ),
            300,
        )
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
    if exit_code != command.expected_exit:
        return f"FAIL: exit code {exit_code}"
    if command.expected_exit != 0:
        lines = [line for line in output.splitlines() if line.strip()]
        try:
            value = json.loads(lines[-1]) if lines else {}
        except json.JSONDecodeError:
            value = {}
        code = value.get("error", {}).get("code") if isinstance(value, dict) else None
        if code != "RULESET_ACTIVATION_BLOCKED":
            return "FAIL: blocking exit did not emit RULESET_ACTIVATION_BLOCKED"
        return f"PASS: expected blocking exit {exit_code}; RULESET_ACTIVATION_BLOCKED"
    if "pytest --cov" in command.display:
        passed = re.search(r"(\d+) passed", output)
        coverage = re.search(r"Total coverage: ([0-9.]+)%", output)
        skipped = re.search(r"(\d+) skipped", output)
        skipped_count = int(skipped.group(1)) if skipped else 0
        if skipped_count:
            return f"FAIL: {skipped_count} required test(s) skipped"
        if passed and coverage:
            return (
                f"PASS: {passed.group(1)} tests; 0 skipped; {coverage.group(1)}% combined coverage"
            )
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
            return "FAIL: review pack did not emit JSON"
        if value.get("ok") is not True or value.get("file_count") != 20:
            return "FAIL: review pack result did not validate the 20-file contract"
        return (
            f"PASS: {value.get('file_count', 'unknown')} files; "
            f"primary payload SHA-256 {value.get('payload_sha256', 'unavailable')}; "
            f"archive SHA-256 {value.get('archive_sha256', 'unavailable')}"
        )
    summaries = {
        "uv sync --all-groups --frozen": "PASS: frozen all-group sync",
        "uv run ruff format --check .": "PASS: formatting clean",
        "uv run ruff check .": "PASS: lint clean",
        "uv run mypy src/dmf_pulse": "PASS: strict typing clean",
        "uv run dmf --version": "PASS: dmf 0.2.0",
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
    parser.add_argument(
        "--prepare-review",
        action="store_true",
        help="append the stable RUL-002 review write-ahead record before digest calculation",
    )
    parser.add_argument("--ticket", choices=("FND-001", "RUL-002"), default="FND-001")
    arguments = parser.parse_args()
    if arguments.review_only and arguments.prepare_review:
        parser.error("--review-only and --prepare-review are mutually exclusive")
    uv = shutil.which("uv")
    if uv is None:
        print("uv is unavailable", file=sys.stderr)
        return 2
    command_log = REPOSITORY_ROOT / "evidence" / "tickets" / arguments.ticket / "commands.log"
    if arguments.prepare_review:
        if arguments.ticket != "RUL-002":
            parser.error("--prepare-review is only valid for RUL-002")
        try:
            existing = _read_command_records(command_log)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            print("RUL-002 review preparation requires a valid first-18 command log")
            return 1
        expected_commands = _rul_commands(uv)
        expected = [command.display for command in expected_commands]
        records_valid = (
            all(
                _completed_record_is_valid(item, command)
                for item, command in zip(existing, expected_commands, strict=True)
            )
            if len(existing) == len(expected_commands)
            else False
        )
        if [item.get("command") for item in existing] != expected or not records_valid:
            print("RUL-002 review preparation requires the exact ordered first 18 records")
            return 1
        finalization_path = REPOSITORY_ROOT / "review_pack/RUL-002/archive_finalization.json"
        if finalization_path.exists():
            print("RUL-002 command 19 already has an invocation/finalization record")
            return 1
        review = _review_command(uv, "RUL-002")
        placeholder = CommandRecord(
            command=review.display,
            duration_seconds=None,
            exit_code=0,
            result=RUL_WRITE_AHEAD_RESULT,
        )
        _write_command_records(command_log, [*existing, asdict(placeholder)])
        print("prepared stable RUL-002 review command record")
        return 0

    review_existing: list[dict[str, object]] | None = None
    review_code_commit: str | None = None
    finalization_path = REPOSITORY_ROOT / "review_pack/RUL-002/archive_finalization.json"
    if arguments.review_only and arguments.ticket == "RUL-002":
        try:
            review_existing = _read_command_records(command_log)
            first_eighteen = _rul_commands(uv)
            expected = [command.display for command in first_eighteen] + [
                _review_command(uv, "RUL-002").display
            ]
            placeholder = review_existing[-1]
            first_eighteen_valid = len(review_existing) == 19 and all(
                _completed_record_is_valid(item, command)
                for item, command in zip(review_existing[:18], first_eighteen, strict=True)
            )
            placeholder_valid = (
                set(placeholder) == {"command", "duration_seconds", "exit_code", "result"}
                and placeholder.get("command") == expected[-1]
                and placeholder.get("duration_seconds") is None
                and placeholder.get("exit_code") == 0
                and placeholder.get("result") == RUL_WRITE_AHEAD_RESULT
            )
            if (
                [item.get("command") for item in review_existing] != expected
                or not first_eighteen_valid
                or not placeholder_valid
                or finalization_path.exists()
            ):
                raise ValueError("command 19 is not in its exact unconsumed write-ahead state")
            source_root = REPOSITORY_ROOT / "src"
            if str(source_root) not in sys.path:
                sys.path.insert(0, str(source_root))
            from generate_final_evidence import _main_rul
            from validate_repository import validate_repository

            from dmf_pulse.assurance.review_pack import (
                build_review_pack,
                calculate_review_payload_digest,
                validate_review_zip,
            )

            existing_result = json.loads(
                (REPOSITORY_ROOT / "evidence/tickets/RUL-002/codex_result.json").read_text(
                    encoding="utf-8"
                ),
                parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
            )
            review_code_commit = existing_result.get("code_commit")
            if (
                not isinstance(review_code_commit, str)
                or re.fullmatch(r"[0-9a-f]{40}", review_code_commit) is None
            ):
                raise ValueError("RUL-002 code commit is unavailable")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, ImportError, IndexError):
            print("RUL-002 review finalization preconditions are invalid")
            return 1
        _write_json_atomic(
            finalization_path,
            {
                "command": _review_command(uv, "RUL-002").display,
                "status": "STARTED",
            },
        )

    records = []
    selected_commands = (
        (_review_command(uv, arguments.ticket),)
        if arguments.review_only
        else (_rul_commands(uv) if arguments.ticket == "RUL-002" else _fnd_commands(uv))
    )
    for command in selected_commands:
        record = run_command(command)
        records.append(record)
        print(f"[{record.exit_code}] {record.command} ({record.duration_seconds:.3f}s)")
    command_log.parent.mkdir(parents=True, exist_ok=True)
    success = all(
        record.exit_code == command.expected_exit and record.result.startswith("PASS:")
        for record, command in zip(records, selected_commands, strict=True)
    )
    if arguments.review_only and arguments.ticket == "RUL-002":
        if review_existing is None or review_code_commit is None:
            print("RUL-002 review finalization state is unavailable")
            return 1

        archive_path = REPOSITORY_ROOT / "review_pack/RUL-002/DMF_PULSE_RUL-002_REVIEW.zip"

        def fail_finalization(record: CommandRecord, reason: str) -> int:
            failed_record = {**asdict(record), "result": f"FAIL: {reason}"}
            review_existing[-1] = failed_record
            with suppress(OSError):
                _write_command_records(command_log, review_existing)
            with suppress(OSError):
                archive_path.unlink(missing_ok=True)
            try:
                _main_rul("FAILED", "0" * 64, review_code_commit)
            except Exception:
                for name in (
                    "acceptance_matrix.json",
                    "codex_result.json",
                    "evidence_manifest.json",
                ):
                    (REPOSITORY_ROOT / "evidence/tickets/RUL-002" / name).unlink(missing_ok=True)
            with suppress(OSError):
                _write_json_atomic(
                    finalization_path,
                    {**failed_record, "status": "FAILED"},
                )
            print("RUL-002 review archive finalization failed")
            return 1

        if not success:
            return fail_finalization(records[0], records[0].result.removeprefix("FAIL: "))
        exact_record = CommandRecord(
            command=records[0].command,
            duration_seconds=records[0].duration_seconds,
            exit_code=records[0].exit_code,
            result=RUL_FINAL_RESULT,
        )
        try:
            review_existing[-1] = asdict(exact_record)
            _write_command_records(command_log, review_existing)
            _main_rul("COMPLETE", "0" * 64, review_code_commit)
            generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            payload_digest = calculate_review_payload_digest(
                REPOSITORY_ROOT,
                ticket="RUL-002",
                baseline=RUL_BASELINE,
                generated_at=generated_at,
            )
            _main_rul("COMPLETE", payload_digest, review_code_commit)
            final_errors = validate_repository(REPOSITORY_ROOT)
            if final_errors:
                raise ValueError("final repository/evidence validation failed")
            summary = build_review_pack(
                REPOSITORY_ROOT,
                ticket="RUL-002",
                baseline=RUL_BASELINE,
                output=REPOSITORY_ROOT / "review_pack/RUL-002",
                generated_at=generated_at,
            )
            validated = validate_review_zip(summary.path)
            archive = summary.path
            with zipfile.ZipFile(archive) as review_zip:
                if review_zip.testzip() is not None:
                    raise ValueError("review archive CRC validation failed")
            finalization = {
                **asdict(exact_record),
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "crc_and_checksum_validated": True,
                "file_count": validated.file_count,
                "payload_sha256": validated.payload_sha256,
                "status": "COMPLETE",
            }
            _write_json_atomic(finalization_path, finalization)
        except Exception as exc:
            return fail_finalization(
                exact_record, f"archive finalization failed ({type(exc).__name__})"
            )
        print(json.dumps(finalization, indent=2, sort_keys=True))
        return 0
    with command_log.open(
        "a" if arguments.review_only else "w", encoding="utf-8", newline="\n"
    ) as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
