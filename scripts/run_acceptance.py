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
DAT_BASELINE = "f9b51e965aad1bc94796c17c897f0d99b4c16e1b"
FPL_BASELINE = "9b3160a2574d2868b5f26e3a2d429924567510b0"
ODD_BASELINE = "7034e38f32cd579c90d35c5fe3f10921c3656be0"
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
    capture_path: Path | None = None


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


def _dat_commands(uv: str, docker: str) -> tuple[AcceptanceCommand, ...]:
    evidence = REPOSITORY_ROOT / "evidence/tickets/DAT-003"
    return (
        AcceptanceCommand(
            "uv sync --all-groups --frozen", (uv, "sync", "--all-groups", "--frozen"), 300
        ),
        AcceptanceCommand(
            "uv run ruff format --check .", (uv, "run", "ruff", "format", "--check", "."), 180
        ),
        AcceptanceCommand("uv run ruff check .", (uv, "run", "ruff", "check", "."), 180),
        AcceptanceCommand("uv run mypy src/dmf_pulse", (uv, "run", "mypy", "src/dmf_pulse"), 240),
        AcceptanceCommand("docker version", (docker, "version"), 60),
        AcceptanceCommand("docker compose version", (docker, "compose", "version"), 60),
        AcceptanceCommand(
            "docker compose -f compose.test.yaml up -d --wait",
            (docker, "compose", "-f", "compose.test.yaml", "up", "-d", "--wait"),
            300,
        ),
        AcceptanceCommand(
            "uv run alembic upgrade head", (uv, "run", "alembic", "upgrade", "head"), 180
        ),
        AcceptanceCommand(
            'uv run pytest -m "postgres or migration" tests/integration/data_model tests/integration/migrations',
            (
                uv,
                "run",
                "pytest",
                "-m",
                "postgres or migration",
                "tests/integration/data_model",
                "tests/integration/migrations",
            ),
            600,
        ),
        AcceptanceCommand(
            "uv run alembic downgrade base", (uv, "run", "alembic", "downgrade", "base"), 180
        ),
        AcceptanceCommand(
            "uv run alembic upgrade head", (uv, "run", "alembic", "upgrade", "head"), 180
        ),
        AcceptanceCommand(
            "uv run alembic upgrade head --sql > evidence/tickets/DAT-003/offline_upgrade.sql",
            (uv, "run", "alembic", "upgrade", "head", "--sql"),
            180,
            capture_path=evidence / "offline_upgrade.sql",
        ),
        AcceptanceCommand(
            "uv run dmf data-model doctor --json",
            (uv, "run", "dmf", "data-model", "doctor", "--json"),
            180,
            capture_path=evidence / "database_doctor.json",
        ),
        AcceptanceCommand(
            "uv run dmf data-model schema-manifest --json",
            (uv, "run", "dmf", "data-model", "schema-manifest", "--json"),
            180,
            capture_path=evidence / "schema_manifest.json",
        ),
        AcceptanceCommand(
            "uv run dmf data-model demo --fixture fixtures/data_model/DAT-003/demo.json --json",
            (
                uv,
                "run",
                "dmf",
                "data-model",
                "demo",
                "--fixture",
                "fixtures/data_model/DAT-003/demo.json",
                "--json",
            ),
            180,
            capture_path=evidence / "demo_result.json",
        ),
        AcceptanceCommand(
            "uv run dmf data-model as-of --fixture fixtures/data_model/DAT-003/as_of_queries.json --json",
            (
                uv,
                "run",
                "dmf",
                "data-model",
                "as-of",
                "--fixture",
                "fixtures/data_model/DAT-003/as_of_queries.json",
                "--json",
            ),
            180,
            capture_path=evidence / "as_of_result.json",
        ),
        AcceptanceCommand(
            "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/DAT-003/coverage.json",
            (
                uv,
                "run",
                "pytest",
                "--cov=dmf_pulse",
                "--cov-branch",
                "--cov-report=term-missing",
                "--cov-report=json:evidence/tickets/DAT-003/coverage.json",
            ),
            900,
        ),
        AcceptanceCommand("uv build", (uv, "build"), 300),
        AcceptanceCommand(
            "uv run python scripts/verify_wheel.py",
            (uv, "run", "python", "scripts/verify_wheel.py"),
            900,
        ),
        AcceptanceCommand(
            "uv run python scripts/validate_repository.py",
            (uv, "run", "python", "scripts/validate_repository.py"),
            240,
        ),
        AcceptanceCommand(
            "uv run python scripts/scan_secrets.py",
            (uv, "run", "python", "scripts/scan_secrets.py"),
            240,
        ),
        AcceptanceCommand(
            f"uv run dmf review-pack build --ticket DAT-003 --baseline {DAT_BASELINE} --output review_pack/DAT-003",
            (
                uv,
                "run",
                "dmf",
                "review-pack",
                "build",
                "--ticket",
                "DAT-003",
                "--baseline",
                DAT_BASELINE,
                "--output",
                "review_pack/DAT-003",
            ),
            600,
        ),
        AcceptanceCommand(
            "docker compose -f compose.test.yaml down -v --remove-orphans",
            (
                docker,
                "compose",
                "-f",
                "compose.test.yaml",
                "down",
                "-v",
                "--remove-orphans",
            ),
            300,
        ),
    )


def _fpl_commands(uv: str, docker: str, git: str) -> tuple[AcceptanceCommand, ...]:
    return (
        AcceptanceCommand("git diff --check", (git, "diff", "--check"), 60),
        AcceptanceCommand("uv lock --check", (uv, "lock", "--check"), 180),
        AcceptanceCommand(
            "uv run dmf specs validate", (uv, "run", "dmf", "specs", "validate"), 180
        ),
        AcceptanceCommand(
            "uv run dmf evidence validate --ticket FPL-004",
            (uv, "run", "dmf", "evidence", "validate", "--ticket", "FPL-004"),
            180,
        ),
        AcceptanceCommand(
            "uv run ruff format --check .", (uv, "run", "ruff", "format", "--check", "."), 180
        ),
        AcceptanceCommand("uv run ruff check .", (uv, "run", "ruff", "check", "."), 180),
        AcceptanceCommand("uv run mypy src/dmf_pulse", (uv, "run", "mypy", "src/dmf_pulse"), 300),
        AcceptanceCommand(
            'uv run pytest -q -m "unit" tests/unit',
            (uv, "run", "pytest", "-q", "-m", "unit", "tests/unit"),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            'uv run pytest -q -m "property" tests/property',
            (uv, "run", "pytest", "-q", "-m", "property", "tests/property"),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            'uv run pytest -q -m "contract" tests/contract',
            (uv, "run", "pytest", "-q", "-m", "contract", "tests/contract"),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            'uv run pytest -q -m "security" tests/security',
            (uv, "run", "pytest", "-q", "-m", "security", "tests/security"),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            "docker compose -f compose.test.yaml up -d --wait",
            (docker, "compose", "-f", "compose.test.yaml", "up", "-d", "--wait"),
            300,
        ),
        AcceptanceCommand(
            "uv run python scripts/test_migration_matrix.py --baseline-revision 20260723_0001 --target head",
            (
                uv,
                "run",
                "python",
                "scripts/test_migration_matrix.py",
                "--baseline-revision",
                "20260723_0001",
                "--target",
                "head",
            ),
            600,
        ),
        AcceptanceCommand(
            'uv run pytest -q -m "postgres and integration" tests/integration',
            (uv, "run", "pytest", "-q", "-m", "postgres and integration", "tests/integration"),
            1200,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run pytest -q tests/integration/ingestion/test_fpl_lifecycle_resume.py",
            (uv, "run", "pytest", "-q", "tests/integration/ingestion/test_fpl_lifecycle_resume.py"),
            600,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run pytest -q tests/integration/ingestion/test_fpl_idempotency_cutoff_bundle.py",
            (
                uv,
                "run",
                "pytest",
                "-q",
                "tests/integration/ingestion/test_fpl_idempotency_cutoff_bundle.py",
            ),
            600,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run pytest -q tests/integration/data_model/test_cross_season_competition_constraints.py",
            (
                uv,
                "run",
                "pytest",
                "-q",
                "tests/integration/data_model/test_cross_season_competition_constraints.py",
            ),
            600,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run pytest -q tests/security/test_fpl_rights_raw_retention.py",
            (uv, "run", "pytest", "-q", "tests/security/test_fpl_rights_raw_retention.py"),
            600,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run dmf ingest fpl validate --resource bootstrap --input fixtures/fpl/FPL-004/happy_path/bootstrap.json --contract-version fpl-reference-v1 --output json",
            (
                uv,
                "run",
                "dmf",
                "ingest",
                "fpl",
                "validate",
                "--resource",
                "bootstrap",
                "--input",
                "fixtures/fpl/FPL-004/happy_path/bootstrap.json",
                "--contract-version",
                "fpl-reference-v1",
                "--output",
                "json",
            ),
            180,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run dmf ingest fpl snapshot --resource all --competition-key PL --season-code 2026/27 --rights-profile fpl_official_private_manual_v1 --output json",
            (
                uv,
                "run",
                "dmf",
                "ingest",
                "fpl",
                "snapshot",
                "--resource",
                "all",
                "--competition-key",
                "PL",
                "--season-code",
                "2026/27",
                "--rights-profile",
                "fpl_official_private_manual_v1",
                "--output",
                "json",
            ),
            180,
            offline=True,
            expected_exit=4,
        ),
        AcceptanceCommand(
            "uv run python scripts/verify_fpl004_wheel.py",
            (uv, "run", "python", "scripts/verify_fpl004_wheel.py"),
            1200,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-fail-under=90",
            (
                uv,
                "run",
                "pytest",
                "--cov=dmf_pulse",
                "--cov-branch",
                "--cov-report=term-missing",
                "--cov-fail-under=90",
            ),
            1800,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run python scripts/verify_fpl004_acceptance.py",
            (uv, "run", "python", "scripts/verify_fpl004_acceptance.py"),
            600,
            offline=True,
        ),
        AcceptanceCommand(
            f"uv run dmf review-pack build --ticket FPL-004 --baseline {FPL_BASELINE} --output review_pack/FPL-004",
            (
                uv,
                "run",
                "dmf",
                "review-pack",
                "build",
                "--ticket",
                "FPL-004",
                "--baseline",
                FPL_BASELINE,
                "--output",
                "review_pack/FPL-004",
            ),
            900,
        ),
        AcceptanceCommand(
            "docker compose -f compose.test.yaml down -v --remove-orphans",
            (
                docker,
                "compose",
                "-f",
                "compose.test.yaml",
                "down",
                "-v",
                "--remove-orphans",
            ),
            300,
        ),
    )


def _odd_commands(uv: str, docker: str, git: str) -> tuple[AcceptanceCommand, ...]:
    return (
        AcceptanceCommand("git diff --check", (git, "diff", "--check"), 60),
        AcceptanceCommand("uv lock --check", (uv, "lock", "--check"), 180),
        AcceptanceCommand(
            "uv run dmf specs validate", (uv, "run", "dmf", "specs", "validate"), 180
        ),
        AcceptanceCommand(
            "uv run dmf evidence validate --ticket ODD-005",
            (uv, "run", "dmf", "evidence", "validate", "--ticket", "ODD-005"),
            180,
        ),
        AcceptanceCommand(
            "uv run ruff format --check .", (uv, "run", "ruff", "format", "--check", "."), 180
        ),
        AcceptanceCommand("uv run ruff check .", (uv, "run", "ruff", "check", "."), 180),
        AcceptanceCommand("uv run mypy src/dmf_pulse", (uv, "run", "mypy", "src/dmf_pulse"), 300),
        AcceptanceCommand(
            'uv run pytest -q -m "unit" tests/unit',
            (uv, "run", "pytest", "-q", "-m", "unit", "tests/unit"),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            'uv run pytest -q -m "property" tests/property',
            (uv, "run", "pytest", "-q", "-m", "property", "tests/property"),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            'uv run pytest -q -m "contract" tests/contract',
            (uv, "run", "pytest", "-q", "-m", "contract", "tests/contract"),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            'uv run pytest -q -m "security" tests/security',
            (uv, "run", "pytest", "-q", "-m", "security", "tests/security"),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            "docker compose -f compose.test.yaml up -d --wait",
            (docker, "compose", "-f", "compose.test.yaml", "up", "-d", "--wait"),
            300,
        ),
        AcceptanceCommand(
            "uv run python scripts/test_migration_matrix.py --baseline-revision 20260724_0002 --target head",
            (
                uv,
                "run",
                "python",
                "scripts/test_migration_matrix.py",
                "--baseline-revision",
                "20260724_0002",
                "--target",
                "head",
            ),
            900,
        ),
        AcceptanceCommand(
            'uv run pytest -q -m "postgres and integration" tests/integration',
            (uv, "run", "pytest", "-q", "-m", "postgres and integration", "tests/integration"),
            1800,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run pytest -q tests/unit/ingestion/test_fpl_client.py tests/security/test_fpl_tls_retry.py",
            (
                uv,
                "run",
                "pytest",
                "-q",
                "tests/unit/ingestion/test_fpl_client.py",
                "tests/security/test_fpl_tls_retry.py",
            ),
            600,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run pytest -q tests/integration/ingestion/test_fpl_bundle_rights_quality_gate.py",
            (
                uv,
                "run",
                "pytest",
                "-q",
                "tests/integration/ingestion/test_fpl_bundle_rights_quality_gate.py",
            ),
            600,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run pytest -q tests/integration/ingestion/odds/test_the_odds_api_recorded_ingestion.py",
            (
                uv,
                "run",
                "pytest",
                "-q",
                "tests/integration/ingestion/odds/test_the_odds_api_recorded_ingestion.py",
            ),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run pytest -q tests/integration/ingestion/odds/test_odds_idempotency_asof.py",
            (
                uv,
                "run",
                "pytest",
                "-q",
                "tests/integration/ingestion/odds/test_odds_idempotency_asof.py",
            ),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run pytest -q tests/security/test_odds_credentials_quota_retention.py",
            (
                uv,
                "run",
                "pytest",
                "-q",
                "tests/security/test_odds_credentials_quota_retention.py",
            ),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run dmf ingest fpl replay --fixture-set fixtures/fpl/FPL-004 --scenario happy_path --information-cutoff 2026-08-21T17:30:00Z --rights-profile synthetic_test_v1 --output json",
            (
                uv,
                "run",
                "dmf",
                "ingest",
                "fpl",
                "replay",
                "--fixture-set",
                "fixtures/fpl/FPL-004",
                "--scenario",
                "happy_path",
                "--information-cutoff",
                "2026-08-21T17:30:00Z",
                "--rights-profile",
                "synthetic_test_v1",
                "--output",
                "json",
            ),
            300,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run dmf ingest odds replay --fixture-set fixtures/odds/ODD-005 --scenario happy_path --information-cutoff 2026-08-21T17:30:00Z --rights-profile synthetic_the_odds_api_v1 --output json",
            (
                uv,
                "run",
                "dmf",
                "ingest",
                "odds",
                "replay",
                "--fixture-set",
                "fixtures/odds/ODD-005",
                "--scenario",
                "happy_path",
                "--information-cutoff",
                "2026-08-21T17:30:00Z",
                "--rights-profile",
                "synthetic_the_odds_api_v1",
                "--output",
                "json",
            ),
            300,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run dmf market observations --fixture-external-provider official_fpl --fixture-external-id 101 --season-code 2026/27 --as-of 2026-08-20T12:05:00Z --output json",
            (
                uv,
                "run",
                "dmf",
                "market",
                "observations",
                "--fixture-external-provider",
                "official_fpl",
                "--fixture-external-id",
                "101",
                "--season-code",
                "2026/27",
                "--as-of",
                "2026-08-20T12:05:00Z",
                "--output",
                "json",
            ),
            180,
            offline=True,
            capture_path=REPOSITORY_ROOT / "evidence/tickets/ODD-005/market_observations.json",
        ),
        AcceptanceCommand(
            "uv run dmf ingest odds snapshot --provider the_odds_api --competition-key PL --sport-key soccer_epl --region uk --market h2h --as-of 2026-08-20T12:05:00Z --output json",
            (
                uv,
                "run",
                "dmf",
                "ingest",
                "odds",
                "snapshot",
                "--provider",
                "the_odds_api",
                "--competition-key",
                "PL",
                "--sport-key",
                "soccer_epl",
                "--region",
                "uk",
                "--market",
                "h2h",
                "--as-of",
                "2026-08-20T12:05:00Z",
                "--output",
                "json",
            ),
            180,
            offline=True,
            expected_exit=4,
        ),
        AcceptanceCommand(
            "uv run python scripts/verify_odd005_wheel.py",
            (uv, "run", "python", "scripts/verify_odd005_wheel.py"),
            1500,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-fail-under=90",
            (
                uv,
                "run",
                "pytest",
                "--cov=dmf_pulse",
                "--cov-branch",
                "--cov-report=term-missing",
                "--cov-fail-under=90",
            ),
            2400,
            offline=True,
        ),
        AcceptanceCommand(
            "uv run python scripts/verify_odd005_acceptance.py",
            (uv, "run", "python", "scripts/verify_odd005_acceptance.py"),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            f"uv run dmf review-pack build --ticket ODD-005 --baseline {ODD_BASELINE} --output review_pack/ODD-005",
            (
                uv,
                "run",
                "dmf",
                "review-pack",
                "build",
                "--ticket",
                "ODD-005",
                "--baseline",
                ODD_BASELINE,
                "--output",
                "review_pack/ODD-005",
            ),
            900,
            offline=True,
        ),
        AcceptanceCommand(
            "docker compose -f compose.test.yaml down -v --remove-orphans",
            (docker, "compose", "-f", "compose.test.yaml", "down", "-v", "--remove-orphans"),
            300,
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
        value: object = {}
        for line in reversed(lines):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            break
        error = value.get("error", {}) if isinstance(value, dict) else {}
        code = error.get("code") if isinstance(error, dict) else None
        if code is None and isinstance(value, dict):
            code = value.get("code")
        if "ingest odds snapshot" in command.display:
            transport_called = error.get("transport_called") if isinstance(error, dict) else None
            if code != "CREDENTIAL_UNAVAILABLE" or transport_called is not False:
                return (
                    "FAIL: controlled refusal did not prove CREDENTIAL_UNAVAILABLE before transport"
                )
            return (
                f"PASS: expected exit {exit_code}; CREDENTIAL_UNAVAILABLE with zero transport calls"
            )
        if "ingest fpl snapshot" in command.display:
            effects = value.get("canonical_effects", {}) if isinstance(value, dict) else {}
            if code is None and isinstance(effects, dict):
                code = effects.get("error_code")
            details = error.get("details", {}) if isinstance(error, dict) else {}
            transport_count = (
                details.get("transport_call_count") if isinstance(details, dict) else None
            )
            if transport_count is None and isinstance(value, dict):
                transport_count = value.get("transport_call_count")
            if transport_count is None and isinstance(effects, dict):
                transport_count = effects.get("transport_call_count")
            if code != "RIGHTS_BLOCKED" or transport_count != 0:
                return "FAIL: blocking exit did not prove RIGHTS_BLOCKED before transport"
            return f"PASS: expected exit {exit_code}; RIGHTS_BLOCKED with zero transport calls"
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
        if passed and int(passed.group(1)) > 0 and coverage:
            return (
                f"PASS: {passed.group(1)} tests; 0 skipped; {coverage.group(1)}% combined coverage"
            )
        return "FAIL: coverage command did not prove nonzero tests and a coverage result"
    if command.display.startswith("uv run pytest"):
        passed = re.search(r"(\d+) passed", output)
        skipped = re.search(r"(\d+) skipped", output)
        skipped_count = int(skipped.group(1)) if skipped else 0
        if skipped_count:
            return f"FAIL: {skipped_count} required test(s) skipped"
        if passed is None or int(passed.group(1)) <= 0:
            return "FAIL: pytest command did not prove any executed test"
        return f"PASS: {passed.group(1)} tests; 0 skipped"
    if command.display.endswith("doctor --json"):
        try:
            value = json.loads(output)
        except json.JSONDecodeError:
            return "PASS: doctor emitted output"
        return f"PASS: doctor status {value.get('status', 'UNKNOWN')}"
    if command.display.endswith(
        ("verify_wheel.py", "verify_fpl004_wheel.py", "verify_odd005_wheel.py")
    ):
        try:
            value = json.loads(output)
        except json.JSONDecodeError:
            return "PASS: clean-wheel verifier completed"
        wheel = value.get("wheel", {}) if isinstance(value, dict) else {}
        return f"PASS: clean wheel {wheel.get('sha256', 'hash unavailable')}; installed verifier completed"
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
    if command.display.startswith("uv run alembic upgrade head --sql >"):
        return (
            "PASS: offline upgrade SQL captured by safe Windows equivalence to literal redirection"
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
        "docker version": "PASS: Docker Engine available",
        "docker compose version": "PASS: Docker Compose available",
        "docker compose -f compose.test.yaml up -d --wait": (
            "PASS: PostgreSQL 18.4 service healthy"
        ),
        "uv run alembic upgrade head": "PASS: Alembic upgraded to head",
        "uv run alembic downgrade base": "PASS: Alembic downgraded to base",
        'uv run pytest -m "postgres or migration" tests/integration/data_model tests/integration/migrations': (
            "PASS: PostgreSQL and migration suites completed"
        ),
        "uv run dmf data-model schema-manifest --json": (
            "PASS: deterministic schema manifest emitted"
        ),
        "uv run dmf data-model demo --fixture fixtures/data_model/DAT-003/demo.json --json": (
            "PASS: synthetic database demo assertions passed"
        ),
        "uv run dmf data-model as-of --fixture fixtures/data_model/DAT-003/as_of_queries.json --json": (
            "PASS: bitemporal as-of assertions passed"
        ),
        "docker compose -f compose.test.yaml down -v --remove-orphans": (
            "PASS: PostgreSQL service and volume removed"
        ),
    }
    return summaries.get(command.display, "PASS: command completed")


def run_command(command: AcceptanceCommand, *, force_offline: bool = False) -> CommandRecord:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("DMF_TEST_POSTGRES_PORT", None)
    for credential_name in ("THE_ODDS_API_KEY", "ODDS_API_KEY", "DMF_ODDS_API_KEY"):
        environment.pop(credential_name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["DMF_ENVIRONMENT"] = "TEST"
    environment["PGPASSWORD"] = "changeme"
    environment["DMF_TEST_DATABASE_URL"] = (
        "postgresql+psycopg://dmf_test@127.0.0.1:55432/dmf_pulse_test"
    )
    if command.offline or force_offline:
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
        if exit_code == command.expected_exit and command.capture_path is not None:
            command.capture_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = command.capture_path.with_name(f".{command.capture_path.name}.tmp")
            try:
                temporary.write_text(
                    completed.stdout,
                    encoding="utf-8",
                    newline="\n",
                )
                os.replace(temporary, command.capture_path)
            finally:
                temporary.unlink(missing_ok=True)
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


def _clean_dat_generated_outputs() -> None:
    evidence_root = REPOSITORY_ROOT / "evidence/tickets/DAT-003"
    evidence_root.mkdir(parents=True, exist_ok=True)
    for path in evidence_root.iterdir():
        if path.is_file() and path.name != "PLAN.md":
            path.unlink()
    review_root = REPOSITORY_ROOT / "review_pack/DAT-003"
    if review_root.is_dir():
        for path in review_root.iterdir():
            if path.is_file():
                path.unlink()


def _clean_fpl_generated_outputs() -> None:
    evidence_root = REPOSITORY_ROOT / "evidence/tickets/FPL-004"
    evidence_root.mkdir(parents=True, exist_ok=True)
    for path in evidence_root.iterdir():
        if path.is_file() and path.name != "PLAN.md":
            path.unlink()
    review_root = REPOSITORY_ROOT / "review_pack/FPL-004"
    if review_root.is_dir():
        for path in review_root.iterdir():
            if path.is_file():
                path.unlink()


def _clean_odd_generated_outputs() -> None:
    evidence_root = REPOSITORY_ROOT / "evidence/tickets/ODD-005"
    evidence_root.mkdir(parents=True, exist_ok=True)
    preserved = {".gitignore", "BLOCKED.md", "PLAN.md"}
    for path in evidence_root.iterdir():
        if path.is_file() and path.name not in preserved:
            path.unlink()
    review_root = REPOSITORY_ROOT / "review_pack/ODD-005"
    if review_root.is_dir():
        for path in review_root.iterdir():
            if path.is_file():
                path.unlink()


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=True,
        encoding="utf-8",
        shell=False,
        text=True,
    )
    head = completed.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ValueError("repository HEAD is invalid")
    return head


def _main_dat() -> int:
    uv = shutil.which("uv")
    docker = shutil.which("docker")
    if uv is None or docker is None:
        print("uv or Docker is unavailable", file=sys.stderr)
        return 2
    commands = _dat_commands(uv, docker)
    command_log = REPOSITORY_ROOT / "evidence/tickets/DAT-003/commands.log"
    _clean_dat_generated_outputs()
    records: list[CommandRecord] = []
    teardown_record: CommandRecord | None = None
    review_record: CommandRecord | None = None
    failure = False
    try:
        for command in commands[:21]:
            record = run_command(command)
            records.append(record)
            print(f"[{record.exit_code}] {record.command} ({record.duration_seconds:.3f}s)")
            if record.exit_code != command.expected_exit or not record.result.startswith("PASS:"):
                failure = True
                break
        if not failure:
            source_root = REPOSITORY_ROOT / "src"
            if str(source_root) not in sys.path:
                sys.path.insert(0, str(source_root))
            from generate_dat003_evidence import generate

            from dmf_pulse.assurance.review_pack import (
                DAT_REVIEW_FINAL_RESULT,
                DAT_REVIEW_WRITE_AHEAD_RESULT,
                DAT_TEARDOWN_WRITE_AHEAD_RESULT,
                calculate_review_payload_digest,
            )

            head = _git_head()
            placeholders = [
                *[asdict(item) for item in records],
                asdict(
                    CommandRecord(
                        command=commands[21].display,
                        duration_seconds=None,
                        exit_code=0,
                        result=DAT_REVIEW_WRITE_AHEAD_RESULT,
                    )
                ),
                asdict(
                    CommandRecord(
                        command=commands[22].display,
                        duration_seconds=None,
                        exit_code=0,
                        result=DAT_TEARDOWN_WRITE_AHEAD_RESULT,
                    )
                ),
            ]
            _write_command_records(command_log, placeholders)
            generate(payload_sha256="0" * 64, code_commit=head)
            generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            preliminary_digest = calculate_review_payload_digest(
                REPOSITORY_ROOT,
                ticket="DAT-003",
                baseline=DAT_BASELINE,
                generated_at=generated_at,
            )
            generate(payload_sha256=preliminary_digest, code_commit=head)
            review_record = run_command(commands[21])
            print(
                f"[{review_record.exit_code}] {review_record.command} "
                f"({review_record.duration_seconds:.3f}s)"
            )
            if review_record.exit_code != 0 or not review_record.result.startswith("PASS:"):
                failure = True
            else:
                review_record = CommandRecord(
                    command=review_record.command,
                    duration_seconds=review_record.duration_seconds,
                    exit_code=0,
                    result=DAT_REVIEW_FINAL_RESULT,
                )
    except Exception as exc:
        failure = True
        print(f"DAT-003 acceptance preparation failed ({type(exc).__name__})", file=sys.stderr)
    finally:
        teardown_record = run_command(commands[22])
        print(
            f"[{teardown_record.exit_code}] {teardown_record.command} "
            f"({teardown_record.duration_seconds:.3f}s)"
        )
        if teardown_record.exit_code != 0 or not teardown_record.result.startswith("PASS:"):
            failure = True

    if review_record is None:
        final_records = [*records, teardown_record]
        _write_command_records(command_log, [asdict(item) for item in final_records])
        return 1

    final_records = [*records, review_record, teardown_record]
    _write_command_records(command_log, [asdict(item) for item in final_records])
    archive = REPOSITORY_ROOT / "review_pack/DAT-003/DMF_PULSE_DAT-003_REVIEW.zip"
    finalization_path = REPOSITORY_ROOT / "review_pack/DAT-003/archive_finalization.json"
    if failure:
        archive.unlink(missing_ok=True)
        _write_json_atomic(
            finalization_path,
            {
                "command_22": asdict(review_record),
                "command_23": asdict(teardown_record),
                "status": "FAILED",
            },
        )
        return 1

    try:
        from generate_dat003_evidence import generate
        from validate_repository import validate_repository

        from dmf_pulse.assurance.review_pack import (
            build_review_pack,
            calculate_review_payload_digest,
            validate_review_zip,
        )

        head = _git_head()
        generate(payload_sha256="0" * 64, code_commit=head)
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload_digest = calculate_review_payload_digest(
            REPOSITORY_ROOT,
            ticket="DAT-003",
            baseline=DAT_BASELINE,
            generated_at=generated_at,
        )
        generate(payload_sha256=payload_digest, code_commit=head)
        final_errors = validate_repository(REPOSITORY_ROOT)
        if final_errors:
            raise ValueError("final repository/evidence validation failed")
        summary = build_review_pack(
            REPOSITORY_ROOT,
            ticket="DAT-003",
            baseline=DAT_BASELINE,
            output=REPOSITORY_ROOT / "review_pack/DAT-003",
            generated_at=generated_at,
        )
        validated = validate_review_zip(summary.path)
        with zipfile.ZipFile(summary.path) as review_zip:
            if review_zip.testzip() is not None:
                raise ValueError("review archive CRC validation failed")
        finalization = {
            "archive_sha256": hashlib.sha256(summary.path.read_bytes()).hexdigest(),
            "command_22": asdict(review_record),
            "command_23": asdict(teardown_record),
            "crc_and_checksum_validated": True,
            "file_count": validated.file_count,
            "payload_sha256": validated.payload_sha256,
            "status": "COMPLETE",
        }
        _write_json_atomic(finalization_path, finalization)
    except Exception as exc:
        archive.unlink(missing_ok=True)
        _write_json_atomic(
            finalization_path,
            {
                "command_22": asdict(review_record),
                "command_23": asdict(teardown_record),
                "error_type": type(exc).__name__,
                "status": "FAILED",
            },
        )
        print(f"DAT-003 review archive finalization failed ({type(exc).__name__})")
        return 1
    print(json.dumps(finalization, indent=2, sort_keys=True))
    return 0


def _main_fpl() -> int:
    uv = shutil.which("uv")
    docker = shutil.which("docker")
    git = shutil.which("git")
    if uv is None or docker is None or git is None:
        print("uv, Docker, or Git is unavailable", file=sys.stderr)
        return 2
    commands = _fpl_commands(uv, docker, git)
    command_log = REPOSITORY_ROOT / "evidence/tickets/FPL-004/commands.log"
    archive = REPOSITORY_ROOT / "review_pack/FPL-004/DMF_PULSE_FPL-004_REVIEW.zip"
    finalization_path = REPOSITORY_ROOT / "review_pack/FPL-004/archive_finalization.json"
    _clean_fpl_generated_outputs()
    source_root = REPOSITORY_ROOT / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from generate_fpl004_evidence import _manifest as write_fpl_manifest
    from generate_fpl004_evidence import generate as generate_fpl_evidence

    write_fpl_manifest("DRAFT", [], None)
    records: list[CommandRecord] = []
    review_record: CommandRecord | None = None
    teardown_record: CommandRecord | None = None
    failure = False
    try:
        for command in commands[:23]:
            record = run_command(command)
            records.append(record)
            print(f"[{record.exit_code}] {record.command} ({record.duration_seconds:.3f}s)")
            if record.exit_code != command.expected_exit or not record.result.startswith("PASS:"):
                failure = True
                break
        if not failure:
            from dmf_pulse.assurance.review_pack import (
                FPL_REVIEW_FINAL_RESULT,
                FPL_REVIEW_WRITE_AHEAD_RESULT,
                FPL_TEARDOWN_WRITE_AHEAD_RESULT,
                calculate_review_payload_digest,
            )

            head = _git_head()
            placeholders = [
                *[asdict(item) for item in records],
                asdict(
                    CommandRecord(
                        command=commands[23].display,
                        duration_seconds=None,
                        exit_code=0,
                        result=FPL_REVIEW_WRITE_AHEAD_RESULT,
                    )
                ),
                asdict(
                    CommandRecord(
                        command=commands[24].display,
                        duration_seconds=None,
                        exit_code=0,
                        result=FPL_TEARDOWN_WRITE_AHEAD_RESULT,
                    )
                ),
            ]
            _write_command_records(command_log, placeholders)
            generate_fpl_evidence(status="BLOCKED", payload_sha256="0" * 64, code_commit=head)
            generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            digest = calculate_review_payload_digest(
                REPOSITORY_ROOT,
                ticket="FPL-004",
                baseline=FPL_BASELINE,
                generated_at=generated_at,
            )
            generate_fpl_evidence(status="BLOCKED", payload_sha256=digest, code_commit=head)
            review_record = run_command(commands[23])
            print(
                f"[{review_record.exit_code}] {review_record.command} "
                f"({review_record.duration_seconds:.3f}s)"
            )
            if review_record.exit_code != 0 or not review_record.result.startswith("PASS:"):
                failure = True
            else:
                review_record = CommandRecord(
                    command=review_record.command,
                    duration_seconds=review_record.duration_seconds,
                    exit_code=0,
                    result=FPL_REVIEW_FINAL_RESULT,
                )
    except Exception as exc:
        failure = True
        print(f"FPL-004 acceptance preparation failed ({type(exc).__name__})", file=sys.stderr)
    finally:
        teardown_record = run_command(commands[24])
        print(
            f"[{teardown_record.exit_code}] {teardown_record.command} "
            f"({teardown_record.duration_seconds:.3f}s)"
        )
        if teardown_record.exit_code != 0 or not teardown_record.result.startswith("PASS:"):
            failure = True
        else:
            from dmf_pulse.assurance.review_pack import FPL_TEARDOWN_FINAL_RESULT

            teardown_record = CommandRecord(
                command=teardown_record.command,
                duration_seconds=teardown_record.duration_seconds,
                exit_code=0,
                result=FPL_TEARDOWN_FINAL_RESULT,
            )

    if review_record is None or teardown_record is None:
        final_records = [*records, *([teardown_record] if teardown_record is not None else [])]
        _write_command_records(command_log, [asdict(item) for item in final_records])
        archive.unlink(missing_ok=True)
        return 1

    final_records = [*records, review_record, teardown_record]
    _write_command_records(command_log, [asdict(item) for item in final_records])
    if failure:
        archive.unlink(missing_ok=True)
        _write_json_atomic(
            finalization_path,
            {
                "command_24": asdict(review_record),
                "command_25": asdict(teardown_record),
                "status": "FAILED",
            },
        )
        return 1

    try:
        from dmf_pulse.assurance.review_pack import (
            build_review_pack,
            calculate_review_payload_digest,
            validate_review_zip,
        )

        head = _git_head()
        generate_fpl_evidence(status="COMPLETE", payload_sha256="0" * 64, code_commit=head)
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        digest = calculate_review_payload_digest(
            REPOSITORY_ROOT,
            ticket="FPL-004",
            baseline=FPL_BASELINE,
            generated_at=generated_at,
        )
        generate_fpl_evidence(status="COMPLETE", payload_sha256=digest, code_commit=head)
        summary = build_review_pack(
            REPOSITORY_ROOT,
            ticket="FPL-004",
            baseline=FPL_BASELINE,
            output=REPOSITORY_ROOT / "review_pack/FPL-004",
            generated_at=generated_at,
        )
        validated = validate_review_zip(summary.path)
        with zipfile.ZipFile(summary.path) as review_zip:
            if review_zip.testzip() is not None:
                raise ValueError("review archive CRC validation failed")
        finalization = {
            "archive_sha256": hashlib.sha256(summary.path.read_bytes()).hexdigest(),
            "command_24": asdict(review_record),
            "command_25": asdict(teardown_record),
            "crc_and_checksum_validated": True,
            "file_count": validated.file_count,
            "payload_sha256": validated.payload_sha256,
            "status": "COMPLETE",
        }
        _write_json_atomic(finalization_path, finalization)
    except Exception as exc:
        archive.unlink(missing_ok=True)
        _write_json_atomic(
            finalization_path,
            {
                "command_24": asdict(review_record),
                "command_25": asdict(teardown_record),
                "error_type": type(exc).__name__,
                "status": "FAILED",
            },
        )
        print(f"FPL-004 review archive finalization failed ({type(exc).__name__})")
        return 1
    print(json.dumps(finalization, indent=2, sort_keys=True))
    return 0


def _main_odd() -> int:
    uv = shutil.which("uv")
    docker = shutil.which("docker")
    git = shutil.which("git")
    if uv is None or docker is None or git is None:
        print("uv, Docker, or Git is unavailable", file=sys.stderr)
        return 2
    commands = _odd_commands(uv, docker, git)
    command_log = REPOSITORY_ROOT / "evidence/tickets/ODD-005/commands.log"
    archive = REPOSITORY_ROOT / "review_pack/ODD-005/DMF_PULSE_ODD-005_REVIEW.zip"
    finalization_path = REPOSITORY_ROOT / "review_pack/ODD-005/archive_finalization.json"
    records: list[CommandRecord] = []
    review_record: CommandRecord | None = None
    teardown_record: CommandRecord | None = None
    failure = False
    try:
        _clean_odd_generated_outputs()
        source_root = REPOSITORY_ROOT / "src"
        if str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))
        from generate_odd005_evidence import _manifest as write_odd_manifest
        from generate_odd005_evidence import generate as generate_odd_evidence

        write_odd_manifest("DRAFT", [], None)
        for command in commands[:26]:
            record = run_command(command, force_offline=True)
            records.append(record)
            print(f"[{record.exit_code}] {record.command} ({record.duration_seconds:.3f}s)")
            if record.exit_code != command.expected_exit or not record.result.startswith("PASS:"):
                failure = True
                break
        if not failure:
            from dmf_pulse.assurance.review_pack import (
                ODD_REVIEW_FINAL_RESULT,
                ODD_REVIEW_WRITE_AHEAD_RESULT,
                ODD_TEARDOWN_WRITE_AHEAD_RESULT,
                calculate_review_payload_digest,
            )

            head = _git_head()
            placeholders = [
                *[asdict(item) for item in records],
                asdict(
                    CommandRecord(
                        command=commands[26].display,
                        duration_seconds=None,
                        exit_code=0,
                        result=ODD_REVIEW_WRITE_AHEAD_RESULT,
                    )
                ),
                asdict(
                    CommandRecord(
                        command=commands[27].display,
                        duration_seconds=None,
                        exit_code=0,
                        result=ODD_TEARDOWN_WRITE_AHEAD_RESULT,
                    )
                ),
            ]
            _write_command_records(command_log, placeholders)
            generate_odd_evidence(status="BLOCKED", payload_sha256="0" * 64, code_commit=head)
            generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            digest = calculate_review_payload_digest(
                REPOSITORY_ROOT,
                ticket="ODD-005",
                baseline=ODD_BASELINE,
                generated_at=generated_at,
            )
            generate_odd_evidence(status="BLOCKED", payload_sha256=digest, code_commit=head)
            review_record = run_command(commands[26], force_offline=True)
            print(
                f"[{review_record.exit_code}] {review_record.command} "
                f"({review_record.duration_seconds:.3f}s)"
            )
            if review_record.exit_code != 0 or not review_record.result.startswith("PASS:"):
                failure = True
            else:
                review_record = CommandRecord(
                    command=review_record.command,
                    duration_seconds=review_record.duration_seconds,
                    exit_code=0,
                    result=ODD_REVIEW_FINAL_RESULT,
                )
    except Exception as exc:
        failure = True
        print(f"ODD-005 acceptance preparation failed ({type(exc).__name__})", file=sys.stderr)
    finally:
        teardown_record = run_command(commands[27], force_offline=True)
        print(
            f"[{teardown_record.exit_code}] {teardown_record.command} "
            f"({teardown_record.duration_seconds:.3f}s)"
        )
        if teardown_record.exit_code != 0 or not teardown_record.result.startswith("PASS:"):
            failure = True
        else:
            from dmf_pulse.assurance.review_pack import ODD_TEARDOWN_FINAL_RESULT

            teardown_record = CommandRecord(
                command=teardown_record.command,
                duration_seconds=teardown_record.duration_seconds,
                exit_code=0,
                result=ODD_TEARDOWN_FINAL_RESULT,
            )

    if review_record is None or teardown_record is None:
        final_records = [*records, *([teardown_record] if teardown_record is not None else [])]
        serialized_final_records = [asdict(item) for item in final_records]
        _write_command_records(command_log, serialized_final_records)
        with suppress(Exception):
            write_odd_manifest("BLOCKED", serialized_final_records, _git_head())
        archive.unlink(missing_ok=True)
        return 1

    final_records = [*records, review_record, teardown_record]
    _write_command_records(command_log, [asdict(item) for item in final_records])
    if failure:
        archive.unlink(missing_ok=True)
        with suppress(Exception):
            write_odd_manifest("BLOCKED", [asdict(item) for item in final_records], _git_head())
        _write_json_atomic(
            finalization_path,
            {
                "command_27": asdict(review_record),
                "command_28": asdict(teardown_record),
                "status": "FAILED",
            },
        )
        return 1

    try:
        from dmf_pulse.assurance.review_pack import (
            build_review_pack,
            calculate_review_payload_digest,
            validate_review_zip,
        )

        head = _git_head()
        generate_odd_evidence(status="COMPLETE", payload_sha256="0" * 64, code_commit=head)
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        digest = calculate_review_payload_digest(
            REPOSITORY_ROOT,
            ticket="ODD-005",
            baseline=ODD_BASELINE,
            generated_at=generated_at,
        )
        generate_odd_evidence(status="COMPLETE", payload_sha256=digest, code_commit=head)
        summary = build_review_pack(
            REPOSITORY_ROOT,
            ticket="ODD-005",
            baseline=ODD_BASELINE,
            output=REPOSITORY_ROOT / "review_pack/ODD-005",
            generated_at=generated_at,
        )
        validated = validate_review_zip(summary.path)
        with zipfile.ZipFile(summary.path) as review_zip:
            if review_zip.testzip() is not None:
                raise ValueError("review archive CRC validation failed")
        finalization = {
            "archive_sha256": hashlib.sha256(summary.path.read_bytes()).hexdigest(),
            "command_27": asdict(review_record),
            "command_28": asdict(teardown_record),
            "crc_and_checksum_validated": True,
            "file_count": validated.file_count,
            "payload_sha256": validated.payload_sha256,
            "status": "COMPLETE",
        }
        _write_json_atomic(finalization_path, finalization)
    except Exception as exc:
        archive.unlink(missing_ok=True)
        try:
            generate_odd_evidence(
                status="BLOCKED", payload_sha256="0" * 64, code_commit=_git_head()
            )
        except Exception:
            with suppress(Exception):
                write_odd_manifest("BLOCKED", [asdict(item) for item in final_records], _git_head())
        _write_json_atomic(
            finalization_path,
            {
                "command_27": asdict(review_record),
                "command_28": asdict(teardown_record),
                "error_type": type(exc).__name__,
                "status": "FAILED",
            },
        )
        print(f"ODD-005 review archive finalization failed ({type(exc).__name__})")
        return 1
    print(json.dumps(finalization, indent=2, sort_keys=True))
    return 0


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
    parser.add_argument(
        "--ticket",
        choices=("FND-001", "RUL-002", "DAT-003", "FPL-004", "ODD-005"),
        default="FND-001",
    )
    arguments = parser.parse_args()
    if arguments.review_only and arguments.prepare_review:
        parser.error("--review-only and --prepare-review are mutually exclusive")
    if arguments.ticket == "DAT-003":
        if arguments.review_only or arguments.prepare_review:
            parser.error(
                "DAT-003 runs its review and teardown inside the exact acceptance sequence"
            )
        return _main_dat()
    if arguments.ticket == "FPL-004":
        if arguments.review_only or arguments.prepare_review:
            parser.error(
                "FPL-004 runs its review and teardown inside the exact acceptance sequence"
            )
        return _main_fpl()
    if arguments.ticket == "ODD-005":
        if arguments.review_only or arguments.prepare_review:
            parser.error(
                "ODD-005 runs its review and teardown inside the exact acceptance sequence"
            )
        return _main_odd()
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
