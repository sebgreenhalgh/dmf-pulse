"""Deterministic capped review-pack construction and detached-manifest validation."""

from __future__ import annotations

import difflib
import json
import math
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dmf_pulse.assurance.canonical import pretty_json, sha256_file
from dmf_pulse.assurance.evidence import (
    DAT_DETACHED_REVIEW_NAMES,
    DAT_REQUIRED_BASELINE,
    DAT_REQUIRED_BRANCH,
    CodexResult,
    ReviewFile,
    ReviewManifest,
    TicketEvidenceManifest,
    validate_evidence_file,
)
from dmf_pulse.assurance.manifests import RepositoryManifest, validate_repository_manifest
from dmf_pulse.assurance.secret_scan import scan_repository, scan_text
from dmf_pulse.assurance.tickets import TicketIdError, ticket_paths, validate_ticket_id
from dmf_pulse.system import ProcessRunner, SubprocessProcessRunner

MAX_REVIEW_FILES: Final = 20
MAX_GIT_CAPTURE_BYTES: Final = 32 * 1024 * 1024
RUL_REQUIRED_BASELINE: Final = "12049a7de23a4a8fcca3d219dbcab1bf5e1027ea"
RUL_REQUIRED_BRANCH: Final = "stage/A2/RUL-002-rules-foundation"
REVIEW_ZIP_NAME: Final = "DMF_PULSE_FND-001_REVIEW.zip"
RUL_REVIEW_ZIP_NAME: Final = "DMF_PULSE_RUL-002_REVIEW.zip"
DAT_REVIEW_ZIP_NAME: Final = "DMF_PULSE_DAT-003_REVIEW.zip"
MANIFEST_NAME: Final = "03_REVIEW_MANIFEST.json"
CHECKSUM_NAME: Final = "20_SHA256SUMS.txt"
PREFERRED_NAMES: Final = (
    "01_REVIEW_INDEX.md",
    "02_CODEX_RESULT.json",
    MANIFEST_NAME,
    "04_FULL_DIFF.patch",
    "05_DIFF_STAT.txt",
    "06_GIT_STATUS.txt",
    "07_FILE_TREE.txt",
    "08_COMMANDS_LOG.txt",
    "09_TEST_RESULTS.md",
    "10_ACCEPTANCE_MATRIX.md",
    "11_TOOLCHAIN_DECISIONS.md",
    "12_DEPENDENCY_REPORT.md",
    "13_SECURITY_AND_SECRET_REVIEW.md",
    "14_CI_AND_PACKAGE_REVIEW.md",
    "15_KNOWN_LIMITATIONS_AND_OPEN_QUESTIONS.md",
    "16_AGENTS.md",
    "17_PYPROJECT.toml",
    "18_MAKEFILE.txt",
    "19_CI_YML.txt",
    CHECKSUM_NAME,
)
RUL_PREFERRED_NAMES: Final = (
    "01_REVIEW_INDEX.md",
    "02_CODEX_RESULT.json",
    MANIFEST_NAME,
    "04_FULL_DIFF.patch",
    "05_DIFF_STAT.txt",
    "06_GIT_STATUS.txt",
    "07_FILE_TREE.txt",
    "08_COMMANDS_LOG.txt",
    "09_TEST_COVERAGE_MUTATION.md",
    "10_ACCEPTANCE_MATRIX.md",
    "11_AUTHORITY_DECISION_REMEDIATION.md",
    "12_RULES_COMPILER_LIFECYCLE.md",
    "13_GOLDEN_SCORING_BPS_BONUS.md",
    "14_DEPENDENCY_LOCK_PACKAGE.md",
    "15_SECURITY_SOURCE_RIGHTS.md",
    "16_KNOWN_LIMITATIONS.md",
    "17_RULES_PUBLIC_CONTRACTS.txt",
    "18_RULES_IMPLEMENTATION.txt",
    "19_CLI_CONFIG_CI.txt",
    CHECKSUM_NAME,
)
DAT_PREFERRED_NAMES: Final = (
    "01_REVIEW_INDEX.md",
    "02_CODEX_RESULT.json",
    MANIFEST_NAME,
    "04_FULL_DIFF.patch",
    "05_DIFF_STAT.txt",
    "06_GIT_STATUS.txt",
    "07_FILE_TREE.txt",
    "08_COMMANDS_LOG.txt",
    "09_TEST_COVERAGE_MUTATION_ORACLES.md",
    "10_ACCEPTANCE_MATRIX.md",
    "11_RUL002_REMEDIATION_MATRIX.md",
    "12_SCHEMA_MIGRATION.md",
    "13_TEMPORAL_IDENTITY_ASOF_CONCURRENCY.md",
    "14_PROVENANCE_IMMUTABILITY_RULES_REGISTRY.md",
    "15_DEPENDENCY_DOCKER_CI_SECURITY.md",
    "16_KNOWN_LIMITATIONS.md",
    "17_DATA_MODEL_PUBLIC_CONTRACTS_MODELS.txt",
    "18_INITIAL_MIGRATION_CRITICAL_SQL.txt",
    "19_REPOSITORY_CLI_CONFIG_COMPOSE_CI.txt",
    CHECKSUM_NAME,
)
OPERATIONAL_EXCLUDED_PARTS: Final = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".coverage",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
    "htmlcov",
    "coverage.xml",
    "review_pack",
}
VERBATIM_OR_GENERATED_DIFF_EXCLUSIONS: Final = {
    ".github/CODEOWNERS",
    ".codex/schemas/codex_result.schema.json",
    ".codex/schemas/evidence_manifest.schema.json",
    ".codex/schemas/review_manifest.schema.json",
    "docs/implementation/DMF_PULSE_CODEX_IMPLEMENTATION_PLAYBOOK_v1.txt",
    "specs/manifests/document_manifest.json",
    "tickets/FND-001/ACCEPTANCE.md",
    "tickets/FND-001/ticket.yaml",
    "uv.lock",
    "src/dmf_pulse/_data/zoneinfo/Europe/London",
}


class ReviewPackError(Exception):
    """An actionable review-pack contract failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_error_object(self) -> dict[str, object]:
        return {"error": {"code": self.code, "message": self.message}, "ok": False}


@dataclass(frozen=True, slots=True)
class ReviewEntry:
    """One root-level review file before ZIP assembly."""

    name: str
    data: bytes
    purpose: str


@dataclass(frozen=True, slots=True)
class ReviewPackSummary:
    path: Path
    file_count: int
    sha256: str
    payload_sha256: str


def enforce_review_limit(entries: list[ReviewEntry]) -> None:
    """Reject duplicate, nested, or over-cap entry sets before writing anything."""

    if len(entries) > MAX_REVIEW_FILES:
        raise ReviewPackError(
            "REVIEW_PACK_FILE_LIMIT",
            f"review pack has {len(entries)} files; maximum is {MAX_REVIEW_FILES}",
        )
    names = [entry.name for entry in entries]
    if len(names) != len(set(names)):
        raise ReviewPackError("REVIEW_PACK_DUPLICATE_NAME", "review pack has duplicate names")
    if any(Path(name).name != name or "/" in name or "\\" in name for name in names):
        raise ReviewPackError("REVIEW_PACK_NESTED_PATH", "all review files must be at ZIP root")


def _is_operationally_excluded(path: Path) -> bool:
    return any(part in OPERATIONAL_EXCLUDED_PARTS for part in path.parts)


def _is_human_authored(relative: str) -> bool:
    if relative in VERBATIM_OR_GENERATED_DIFF_EXCLUSIONS:
        return False
    return not (
        relative.startswith("evidence/")
        or relative.startswith("specs/approved/")
        or relative.startswith("review_pack/")
    )


def _repository_files(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and not _is_operationally_excluded(path.relative_to(root))
    ]


def build_empty_baseline_diff(root: Path) -> tuple[str, str]:
    """Build one deterministic new-file unified diff from the captured empty baseline."""

    baseline_path = root / "evidence" / "tickets" / "FND-001" / "baseline_manifest.json"
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewPackError(
            "BASELINE_INVALID", "baseline manifest is unavailable or invalid"
        ) from exc
    if not isinstance(baseline, dict) or baseline.get("repository_empty") is not True:
        raise ReviewPackError(
            "BASELINE_DIFF_UNSUPPORTED",
            "FND-001 deterministic diff requires its captured empty baseline",
        )

    chunks: list[str] = []
    changed_files = 0
    insertions = 0
    for path in _repository_files(root):
        relative = path.relative_to(root).as_posix()
        if not _is_human_authored(relative):
            continue
        try:
            data = path.read_bytes()
            if b"\x00" in data:
                raise UnicodeError
            text = data.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise ReviewPackError(
                "BINARY_DIFF_PROHIBITED",
                f"human-authored diff input is not UTF-8 text: {relative}",
            ) from exc
        lines = text.splitlines(keepends=True)
        diff_lines = difflib.unified_diff(
            [],
            lines,
            fromfile="/dev/null",
            tofile=f"b/{relative}",
            lineterm="\n",
        )
        for line in diff_lines:
            chunks.append(line if line.endswith("\n") else f"{line}\n")
        changed_files += 1
        insertions += len(lines)
    omissions = [
        "uv.lock (generated exact lock; hash/dependency summary in file 12)",
        "approved DMFP corpus and implementation playbook (verbatim governed inputs)",
        "bundled Europe/London TZif fallback (reviewed binary; hash in file 14)",
        "remote-derived CODEOWNERS metadata (installed in repository, omitted for pack privacy)",
        "document manifest and supplied schemas/ticket contracts (verbatim pack inputs)",
        "generated evidence, build outputs, caches, and review output",
    ]
    stat = (
        f"{changed_files} human-authored files changed, {insertions} insertions(+), 0 deletions(-)\n"
        "Omitted from patch:\n" + "".join(f"- {item}\n" for item in omissions)
    )
    return "".join(chunks), stat


def _run_git(root: Path, arguments: list[str], runner: ProcessRunner) -> str:
    executable = shutil.which("git")
    if executable is None:
        return "git unavailable\n"
    result = runner.run([executable, "-C", str(root), *arguments], timeout_seconds=5.0)
    if result.timed_out:
        return "git command timed out\n"
    if result.return_code != 0:
        return "git command failed\n"
    return result.stdout.replace("\r\n", "\n").rstrip() + "\n"


def _repository_head(root: Path, runner: ProcessRunner) -> str:
    value = _run_git(root, ["rev-parse", "--verify", "HEAD"], runner).strip()
    if len(value) == 40 and all(character in "0123456789abcdef" for character in value):
        return value
    return "UNAVAILABLE"


def _file_tree(root: Path) -> str:
    paths = [path.relative_to(root).as_posix() for path in _repository_files(root)]
    return "".join(f"{path}\n" for path in paths)


def _required_text(root: Path, relative: str) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError) as exc:
        raise ReviewPackError(
            "REVIEW_SOURCE_MISSING", f"required review source missing: {relative}"
        ) from exc


def _review_index(status: str, head: str, limitations: str) -> str:
    return f"""# FND-001 review index

DMF Pulse FND-001 built the governed Python 3.13 package, strict configuration/CLI/doctor, first-party assurance, offline tests, exact uv lock, and CI foundation. Acceptance status: **{status}**.

Repository HEAD at review build: `{head}`. The implementation baseline is the captured empty tree at `evidence/tickets/FND-001/baseline_manifest.json`; the existing empty initial commit was not manufactured or rewritten.

Read `02_CODEX_RESULT.json`, `10_ACCEPTANCE_MATRIX.md`, `04_FULL_DIFF.patch`, then the security/package reports. Reproduce with `uv sync --all-groups --frozen` followed by the literal commands in `tickets/FND-001/ACCEPTANCE.md`.

    The detached convention breaks the checksum circularity: `03_REVIEW_MANIFEST.json` hashes files 01-02 and 04-19; `20_SHA256SUMS.txt` hashes files 01-19, including the manifest, and excludes itself. The validator enforces both sets. `02_CODEX_RESULT.json` records a stable digest over primary implementation files 04-05 and 07-19; the actual archive hash is emitted externally because a ZIP cannot contain its own hash.

## Exact unresolved issues

{limitations.rstrip() or "None."}

Command execution and any failure are recorded individually in files 08 and 10. Human acceptance, merge, and tagging remain outside Codex completion.
"""


def _entry(name: str, text: str, purpose: str) -> ReviewEntry:
    normalized = text.replace("\r\n", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    return ReviewEntry(name=name, data=normalized.encode("utf-8"), purpose=purpose)


def _sha256_bytes(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


PRIMARY_PAYLOAD_NAMES: Final = {
    "04_FULL_DIFF.patch",
    "05_DIFF_STAT.txt",
    "07_FILE_TREE.txt",
    "08_COMMANDS_LOG.txt",
    "09_TEST_RESULTS.md",
    "10_ACCEPTANCE_MATRIX.md",
    "11_TOOLCHAIN_DECISIONS.md",
    "12_DEPENDENCY_REPORT.md",
    "13_SECURITY_AND_SECRET_REVIEW.md",
    "14_CI_AND_PACKAGE_REVIEW.md",
    "15_KNOWN_LIMITATIONS_AND_OPEN_QUESTIONS.md",
    "16_AGENTS.md",
    "17_PYPROJECT.toml",
    "18_MAKEFILE.txt",
    "19_CI_YML.txt",
}
RUL_PRIMARY_PAYLOAD_NAMES: Final = set(RUL_PREFERRED_NAMES[3:19])
DAT_PRIMARY_PAYLOAD_NAMES: Final = set(DAT_PREFERRED_NAMES[3:19])
RUL_MANDATORY_ACCEPTANCE_COMMANDS: Final = (
    "uv sync --all-groups --frozen",
    "uv run ruff format --check .",
    "uv run ruff check .",
    "uv run mypy src/dmf_pulse",
    "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/RUL-002/coverage.json",
    "uv run dmf --version",
    "uv run dmf doctor --json",
    "uv run dmf rules validate fixtures/rules/RUL-002/synthetic_complete --json",
    "uv run dmf rules compile fixtures/rules/RUL-002/synthetic_complete --output artifacts/rules/rul-002-synthetic.json --json",
    "uv run dmf rules hash artifacts/rules/rul-002-synthetic.json --json",
    "uv run dmf rules score-fixture artifacts/rules/rul-002-synthetic.json fixtures/rules/RUL-002/golden_fixture_001.json --json",
    "uv run dmf rules score-gameweek artifacts/rules/rul-002-synthetic.json fixtures/rules/RUL-002/golden_gameweek_001.json --json",
    "uv run dmf rules diff fixtures/rules/RUL-002/reference_2025_26 fixtures/rules/RUL-002/target_2026_27_partial --json",
    "uv run dmf rules activate fixtures/rules/RUL-002/target_2026_27_partial --approval fixtures/rules/RUL-002/invalid_target_approval.json --json",
    "uv build",
    "uv run python scripts/verify_wheel.py",
    "uv run python scripts/validate_repository.py",
    "uv run python scripts/scan_secrets.py",
    f"uv run dmf review-pack build --ticket RUL-002 --baseline {RUL_REQUIRED_BASELINE} --output review_pack/RUL-002",
)
RUL_REVIEW_WRITE_AHEAD_RESULT: Final = (
    "PASS: write-ahead record committed only by successful external archive finalization; "
    "exact duration and digests are in archive_finalization.json"
)
RUL_REVIEW_FINAL_RESULT: Final = (
    "PASS: exact 20-file review build completed; final detached digests are in "
    "archive_finalization.json"
)
DAT_MANDATORY_ACCEPTANCE_COMMANDS: Final = (
    "uv sync --all-groups --frozen",
    "uv run ruff format --check .",
    "uv run ruff check .",
    "uv run mypy src/dmf_pulse",
    "docker version",
    "docker compose version",
    "docker compose -f compose.test.yaml up -d --wait",
    "uv run alembic upgrade head",
    'uv run pytest -m "postgres or migration" tests/integration/data_model tests/integration/migrations',
    "uv run alembic downgrade base",
    "uv run alembic upgrade head",
    "uv run alembic upgrade head --sql > evidence/tickets/DAT-003/offline_upgrade.sql",
    "uv run dmf data-model doctor --json",
    "uv run dmf data-model schema-manifest --json",
    "uv run dmf data-model demo --fixture fixtures/data_model/DAT-003/demo.json --json",
    "uv run dmf data-model as-of --fixture fixtures/data_model/DAT-003/as_of_queries.json --json",
    "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/DAT-003/coverage.json",
    "uv build",
    "uv run python scripts/verify_wheel.py",
    "uv run python scripts/validate_repository.py",
    "uv run python scripts/scan_secrets.py",
    f"uv run dmf review-pack build --ticket DAT-003 --baseline {DAT_REQUIRED_BASELINE} --output review_pack/DAT-003",
    "docker compose -f compose.test.yaml down -v --remove-orphans",
)
DAT_REVIEW_WRITE_AHEAD_RESULT: Final = (
    "PASS: write-ahead record committed only by successful external archive finalization; "
    "exact duration and digests are in archive_finalization.json"
)
DAT_REVIEW_FINAL_RESULT: Final = (
    "PASS: exact 20-file review build completed; final detached digests are in "
    "archive_finalization.json"
)
DAT_TEARDOWN_WRITE_AHEAD_RESULT: Final = (
    "PASS: finally-guaranteed PostgreSQL teardown pending; exact duration and result are in "
    "archive_finalization.json"
)


def _primary_payload_digest(
    payload: dict[str, bytes], primary_names: set[str] | frozenset[str] = PRIMARY_PAYLOAD_NAMES
) -> str:
    if set(payload) & primary_names != primary_names:
        raise ReviewPackError(
            "REVIEW_PRIMARY_PAYLOAD", "review primary payload coverage is incomplete"
        )
    ledger = "".join(f"{_sha256_bytes(payload[name])}  {name}\n" for name in sorted(primary_names))
    return _sha256_bytes(ledger.encode("utf-8"))


def calculate_review_payload_digest(
    root: Path,
    *,
    generated_at: str,
    ticket: str = "FND-001",
    baseline: str | None = None,
    process_runner: ProcessRunner | None = None,
) -> str:
    """Calculate the stable non-self-referential implementation-payload digest."""

    selected_runner = process_runner or SubprocessProcessRunner()
    entries = _assemble_for_ticket(
        root,
        ticket=ticket,
        baseline=baseline,
        generated_at=generated_at,
        process_runner=selected_runner,
    )
    names = (
        DAT_PRIMARY_PAYLOAD_NAMES
        if ticket == "DAT-003"
        else RUL_PRIMARY_PAYLOAD_NAMES
        if ticket == "RUL-002"
        else PRIMARY_PAYLOAD_NAMES
    )
    return _primary_payload_digest({entry.name: entry.data for entry in entries}, names)


def _assemble_fnd_entries(
    root: Path,
    *,
    generated_at: str,
    process_runner: ProcessRunner,
) -> list[ReviewEntry]:
    validated = validate_evidence_file(
        root / "evidence" / "tickets" / "FND-001" / "codex_result.json"
    )
    if not isinstance(validated.model, CodexResult):
        raise ReviewPackError(
            "CODEX_RESULT_INVALID", "codex_result.json has the wrong evidence kind"
        )
    result = validated.model
    diff, diff_stat = build_empty_baseline_diff(root)
    head = _repository_head(root, process_runner)
    limitations = _required_text(root, "evidence/tickets/FND-001/KNOWN_LIMITATIONS.md")

    entries = [
        _entry(
            "01_REVIEW_INDEX.md",
            _review_index(result.status.value, head, limitations),
            "review navigation",
        ),
        _entry("02_CODEX_RESULT.json", pretty_json(result), "structured implementation result"),
        _entry("04_FULL_DIFF.patch", diff, "all human-authored implementation changes"),
        _entry("05_DIFF_STAT.txt", diff_stat, "concise diff scope and generated omissions"),
        _entry(
            "06_GIT_STATUS.txt",
            _run_git(root, ["status", "--short", "--branch"], process_runner),
            "Git state",
        ),
        _entry("07_FILE_TREE.txt", _file_tree(root), "current non-operational repository tree"),
        _entry(
            "08_COMMANDS_LOG.txt",
            _required_text(root, "evidence/tickets/FND-001/commands.log"),
            "literal command evidence",
        ),
        _entry(
            "09_TEST_RESULTS.md",
            _required_text(root, "evidence/tickets/FND-001/TEST_RESULTS.md"),
            "test and coverage summary",
        ),
        _entry(
            "10_ACCEPTANCE_MATRIX.md",
            _required_text(root, "evidence/tickets/FND-001/ACCEPTANCE.md"),
            "mandatory acceptance matrix",
        ),
        _entry(
            "11_TOOLCHAIN_DECISIONS.md",
            _required_text(root, "docs/adr/ADR-FND-001-TOOLCHAIN.md"),
            "sanctioned toolchain realization",
        ),
        _entry(
            "12_DEPENDENCY_REPORT.md",
            _required_text(root, "evidence/tickets/FND-001/DEPENDENCY_REPORT.md"),
            "direct/transitive dependency report",
        ),
        _entry(
            "13_SECURITY_AND_SECRET_REVIEW.md",
            _required_text(root, "evidence/tickets/FND-001/SECURITY_REVIEW.md"),
            "security and secret review",
        ),
        _entry(
            "14_CI_AND_PACKAGE_REVIEW.md",
            _required_text(root, "evidence/tickets/FND-001/PACKAGE_REVIEW.md"),
            "CI, build, and clean-wheel review",
        ),
        _entry("15_KNOWN_LIMITATIONS_AND_OPEN_QUESTIONS.md", limitations, "unresolved issues"),
        _entry(
            "16_AGENTS.md",
            _required_text(root, "AGENTS.md"),
            "repository implementation constraints",
        ),
        _entry(
            "17_PYPROJECT.toml",
            _required_text(root, "pyproject.toml"),
            "package and quality configuration",
        ),
        _entry("18_MAKEFILE.txt", _required_text(root, "Makefile"), "optional command aliases"),
        _entry(
            "19_CI_YML.txt", _required_text(root, ".github/workflows/ci.yml"), "required Ubuntu CI"
        ),
    ]
    enforce_review_limit(entries)

    manifest_files = [
        ReviewFile(
            name=item.name,
            sha256=_sha256_bytes(item.data),
            bytes=len(item.data),
            purpose=item.purpose,
        )
        for item in entries
    ]
    manifest = ReviewManifest(
        ticket_id="FND-001",
        generated_at=generated_at,
        repository_head=head,
        baseline="evidence/tickets/FND-001/baseline_manifest.json",
        file_count=MAX_REVIEW_FILES,
        files=manifest_files,
        acceptance_status=result.status,
    )
    manifest_entry = _entry(MANIFEST_NAME, pretty_json(manifest), "detached payload manifest")
    entries.append(manifest_entry)
    entries.sort(key=lambda item: item.name)
    checksum_text = "".join(f"{_sha256_bytes(item.data)}  {item.name}\n" for item in entries)
    entries.append(_entry(CHECKSUM_NAME, checksum_text, "detached checksum ledger"))
    entries.sort(key=lambda item: item.name)
    enforce_review_limit(entries)
    if tuple(item.name for item in entries) != PREFERRED_NAMES:
        raise ReviewPackError(
            "REVIEW_PACK_LAYOUT", "review pack does not match the 20-file contract"
        )
    for item in entries:
        if scan_text(item.data.decode("utf-8"), path=item.name):
            raise ReviewPackError(
                "REVIEW_PACK_SECRET", f"secret-like content detected in {item.name}"
            )
    return entries


def _required_git(root: Path, arguments: list[str], runner: ProcessRunner, *, code: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise ReviewPackError(code, "Git is required for the RUL-002 baseline patch")
    command = [executable, "-C", str(root), *arguments]
    if isinstance(runner, SubprocessProcessRunner):
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                completed = subprocess.run(
                    command,
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                    shell=False,
                    timeout=30.0,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ReviewPackError(code, "Git could not produce the RUL-002 evidence") from exc
            size = stdout.tell()
            if size > MAX_GIT_CAPTURE_BYTES:
                raise ReviewPackError(code, "Git evidence exceeds the 32 MiB review limit")
            if completed.returncode != 0:
                raise ReviewPackError(code, "Git could not produce the RUL-002 evidence")
            stdout.seek(0)
            try:
                return stdout.read().decode("utf-8").replace("\r\n", "\n")
            except UnicodeDecodeError as exc:
                raise ReviewPackError(code, "Git evidence is not UTF-8 text") from exc
    result = runner.run(command, timeout_seconds=30.0)
    if result.timed_out or result.return_code != 0:
        raise ReviewPackError(code, "Git could not produce the RUL-002 baseline patch")
    return result.stdout.replace("\r\n", "\n")


def _rul_baseline_diff(root: Path, baseline: str | None, runner: ProcessRunner) -> tuple[str, str]:
    if baseline != RUL_REQUIRED_BASELINE:
        raise ReviewPackError(
            "BASELINE_INVALID", "RUL-002 requires the ticket's exact baseline commit"
        )
    exclusions = [
        ":(exclude)uv.lock",
        ":(exclude)fixtures/rules/RUL-002/manifest.json",
        ":(exclude)fixtures/rules/RUL-002/bonus_tie_cases.json",
        ":(exclude)fixtures/rules/RUL-002/golden_fixture_001*.json",
        ":(exclude)fixtures/rules/RUL-002/golden_gameweek_001*.json",
        ":(exclude)fixtures/rules/RUL-002/invalid_alias.yaml",
        ":(exclude)fixtures/rules/RUL-002/invalid_custom_tag.yaml",
        ":(exclude)fixtures/rules/RUL-002/invalid_duplicate_key.yaml",
        ":(exclude)fixtures/rules/RUL-002/invalid_target_approval.json",
        ":(exclude)fixtures/rules/RUL-002/target_2026_27_claims.yaml",
        ":(exclude)fixtures/rules/RUL-002/synthetic_complete/**",
        ":(exclude)tickets/RUL-002/ticket.yaml",
        ":(exclude)tickets/RUL-002/ACCEPTANCE.md",
        ":(exclude)docs/rules/07_RULES_MODULE_PUBLIC_CONTRACT.md",
        ":(exclude)docs/rules/08_RULESET_SCHEMA_CONTRACT.md",
        ":(exclude)docs/rules/09_SCORING_CONTRACT.md",
        ":(exclude)docs/rules/10_BPS_AND_BONUS_CONTRACT.md",
        ":(exclude)docs/rules/11_CLI_CONTRACT.md",
        ":(exclude)specs/manifests/decision_manifest.json",
        ":(exclude)specs/manifests/authority_manifest.json",
        ":(exclude)specs/manifests/stage_authority_requirements.json",
        ":(exclude)specs/manifests/runtime_lock_manifest.json",
        ":(exclude).codex/schemas/*.json",
        ":(exclude)evidence/tickets/RUL-002/**",
    ]
    arguments = ["diff", "--no-ext-diff", "--binary", f"{baseline}..HEAD", "--", ".", *exclusions]
    patch = _required_git(root, arguments, runner, code="BASELINE_DIFF_FAILED")
    stat = _required_git(
        root,
        ["diff", "--stat", f"{baseline}..HEAD", "--", ".", *exclusions],
        runner,
        code="BASELINE_DIFF_FAILED",
    )
    omissions = (
        "uv.lock (generated; exact hash and runtime graph are reported in file 14)\n"
        "v1.1 supplied fixtures/contracts and generated authority/schema manifests "
        "(hash-validated governed inputs); authored reference/target fixtures remain in the patch\n"
        "generated ticket evidence and review output\n"
    )
    return patch, stat + "\nOmitted from the human-authored patch:\n" + omissions


def _required_rul_git_state(root: Path, baseline: str, runner: ProcessRunner) -> tuple[str, str]:
    branch = _required_git(
        root, ["rev-parse", "--abbrev-ref", "HEAD"], runner, code="REVIEW_BRANCH_INVALID"
    ).strip()
    if branch != RUL_REQUIRED_BRANCH:
        raise ReviewPackError(
            "REVIEW_BRANCH_INVALID", "RUL-002 review must use the required branch"
        )
    head = _required_git(
        root, ["rev-parse", "--verify", "HEAD"], runner, code="REVIEW_HEAD_INVALID"
    ).strip()
    if len(head) != 40 or any(character not in "0123456789abcdef" for character in head):
        raise ReviewPackError("REVIEW_HEAD_INVALID", "RUL-002 repository HEAD is invalid")
    _required_git(
        root,
        ["merge-base", "--is-ancestor", baseline, head],
        runner,
        code="REVIEW_BASELINE_ANCESTRY",
    )
    merges = _required_git(
        root,
        ["rev-list", "--merges", f"{baseline}..{head}"],
        runner,
        code="REVIEW_HISTORY_INVALID",
    )
    if merges.strip():
        raise ReviewPackError("REVIEW_HISTORY_INVALID", "RUL-002 history contains a merge commit")
    dirty = _required_git(
        root,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        runner,
        code="REVIEW_GIT_STATUS",
    )
    if dirty.strip():
        raise ReviewPackError("REVIEW_TREE_DIRTY", "RUL-002 review requires a clean working tree")
    state = (
        f"branch: {branch}\n"
        f"head: {head}\n"
        f"baseline: {baseline}\n"
        "baseline_is_ancestor: true\n"
        "clean: true\n"
        "merge_commits_since_baseline: 0\n"
        "pushed_by_codex: false\n"
        "merged_by_codex: false\n"
    )
    return head, state


def _concat_sources(root: Path, paths: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for relative in paths:
        chunks.append(f"===== {relative} =====\n")
        chunks.append(_required_text(root, relative))
        if not chunks[-1].endswith("\n"):
            chunks.append("\n")
    return "".join(chunks)


def _rul_review_index(status: str, head: str, baseline: str, limitations: str) -> str:
    return f"""# RUL-002 review index

DMF Pulse RUL-002 remediates foundation authority/evidence provenance and implements the strict rules compiler, immutable lifecycle, configured BPS/bonus, pure fixture/Gameweek scorer, installed CLI, and offline assurance vertical slice. Acceptance status: **{status}**.

Baseline: `{baseline}`. Final repository HEAD: `{head}`. Read files 02, 10, 04, 11-15, then the compact public-contract/implementation extracts in 17-19.

`payload_sha256` is the stable digest ledger for files 04-19. The archive SHA-256 is emitted only after ZIP construction because a ZIP cannot embed its own digest. File 03 hashes files 01-02 and 04-19; file 20 hashes files 01-19. Both ledgers are independently validated.

Command 19 is executed exactly once against a write-ahead ledger. After it succeeds, its measured duration replaces that provisional record and the same first-party assembler transactionally refreshes the final archive without a second CLI invocation. The external `archive_finalization.json` records the final archive digest and successful CRC/checksum validation.

## Exact unresolved issues

{limitations.rstrip() or "None."}

No push, merge, rebase, reset, amend, tag, or repository-visibility change is part of this milestone. Human acceptance remains external.
"""


def _rul_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 machine evidence is unavailable or malformed"
        ) from exc
    if not isinstance(value, dict):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 machine evidence must be a JSON object"
        )
    return value


def _validate_rul_complete_evidence(root: Path, result: CodexResult, head: str) -> None:
    if result.status.value != "COMPLETE":
        return
    expected_commands = list(RUL_MANDATORY_ACCEPTANCE_COMMANDS)
    records = [item.model_dump(mode="json") for item in result.commands]
    if [item.get("command") for item in records] != expected_commands:
        raise ReviewPackError(
            "REVIEW_ACCEPTANCE_INVALID",
            "COMPLETE RUL-002 review requires the exact ordered 19-command result",
        )
    for index, record in enumerate(records, start=1):
        expected_exit = 4 if index == 14 else 0
        duration = record.get("duration_seconds")
        result_text = record.get("result")
        write_ahead = (
            index == 19 and duration is None and result_text == RUL_REVIEW_WRITE_AHEAD_RESULT
        )
        exact_final = index == 19 and result_text == RUL_REVIEW_FINAL_RESULT
        if (
            record.get("exit_code") != expected_exit
            or not isinstance(result_text, str)
            or not result_text.startswith("PASS:")
            or (
                not write_ahead
                and (
                    not isinstance(duration, (int, float))
                    or isinstance(duration, bool)
                    or not math.isfinite(float(duration))
                    or duration < 0
                )
            )
            or (index == 14 and "RULESET_ACTIVATION_BLOCKED" not in result_text)
            or (index == 19 and not (write_ahead or exact_final))
        ):
            raise ReviewPackError(
                "REVIEW_ACCEPTANCE_INVALID",
                f"COMPLETE RUL-002 command {index} evidence is invalid",
            )

    evidence_root = root / "evidence/tickets/RUL-002"
    try:
        command_values = [
            json.loads(
                line,
                parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
            )
            for line in (evidence_root / "commands.log").read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 command log is malformed"
        ) from exc
    if command_values != records:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 command log and result do not match exactly"
        )

    tests = _rul_json_object(evidence_root / "tests.json")
    required_test_fields = {
        "branch_coverage_percent",
        "branches_covered",
        "branches_total",
        "collected",
        "failed",
        "passed",
        "rules_branch_coverage_percent",
        "rules_branches_covered",
        "rules_branches_total",
        "skipped",
        "status",
    }
    overall = tests.get("branch_coverage_percent")
    rules = tests.get("rules_branch_coverage_percent")
    passed = tests.get("passed")
    if (
        set(tests) != required_test_fields
        or tests.get("status") != "PASS"
        or tests.get("failed") != 0
        or tests.get("skipped") != 0
        or not isinstance(passed, int)
        or isinstance(passed, bool)
        or passed <= 0
        or not isinstance(overall, (int, float))
        or isinstance(overall, bool)
        or not math.isfinite(float(overall))
        or float(overall) < 90
        or not isinstance(rules, (int, float))
        or isinstance(rules, bool)
        or not math.isfinite(float(rules))
        or float(rules) < 95
        or result.tests != [tests]
    ):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 test and coverage evidence is incomplete"
        )

    acceptance = _rul_json_object(evidence_root / "acceptance_matrix.json")
    expected_rows = [
        {
            "command": record["command"],
            "duration_seconds": record["duration_seconds"],
            "exit_code": record["exit_code"],
            "expected_exit_code": 4 if index == 14 else 0,
            "status": "PASS",
        }
        for index, record in enumerate(records, start=1)
    ]
    if (
        set(acceptance) != {"commands", "failed", "passed", "status", "ticket_id"}
        or acceptance.get("ticket_id") != "RUL-002"
        or acceptance.get("status") != "COMPLETE"
        or acceptance.get("passed") != 19
        or acceptance.get("failed") != 0
        or acceptance.get("commands") != expected_rows
        or result.acceptance != expected_rows
    ):
        raise ReviewPackError(
            "REVIEW_ACCEPTANCE_INVALID", "RUL-002 acceptance matrix is incomplete"
        )

    validated_manifest = validate_evidence_file(evidence_root / "evidence_manifest.json")
    if not isinstance(validated_manifest.model, TicketEvidenceManifest):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 evidence manifest has the wrong contract kind"
        )
    manifest = validated_manifest.model
    if (
        manifest.ticket_id != "RUL-002"
        or manifest.status != "COMPLETE"
        or manifest.code_commit != head
        or manifest.commands != records
    ):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 evidence manifest provenance is incomplete"
        )
    artifact_paths = [item.path for item in manifest.artifacts]
    required_artifacts = {
        "evidence/tickets/RUL-002/ACCEPTANCE.md",
        "evidence/tickets/RUL-002/AUTHORITY_REMEDIATION.md",
        "evidence/tickets/RUL-002/DEPENDENCY_PACKAGE_REPORT.md",
        "evidence/tickets/RUL-002/GOLDEN_SCORING_REPORT.md",
        "evidence/tickets/RUL-002/KNOWN_LIMITATIONS.md",
        "evidence/tickets/RUL-002/RULES_COMPILER_REPORT.md",
        "evidence/tickets/RUL-002/SECURITY_SOURCE_RIGHTS.md",
        "evidence/tickets/RUL-002/TEST_RESULTS.md",
        "evidence/tickets/RUL-002/acceptance_matrix.json",
        "evidence/tickets/RUL-002/codex_result.json",
        "evidence/tickets/RUL-002/commands.log",
        "evidence/tickets/RUL-002/coverage.json",
        "evidence/tickets/RUL-002/current_manifest.json",
        "evidence/tickets/RUL-002/dependency_report.json",
        "evidence/tickets/RUL-002/package_report.json",
        "evidence/tickets/RUL-002/repository_validation_report.json",
        "evidence/tickets/RUL-002/tests.json",
    }
    if len(artifact_paths) != len(set(artifact_paths)) or not required_artifacts.issubset(
        artifact_paths
    ):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 evidence manifest artifact coverage is incomplete"
        )
    evidence_relative = Path("evidence/tickets/RUL-002")
    try:
        actual_artifacts = {
            path.relative_to(root).as_posix()
            for path in evidence_root.iterdir()
            if path.is_file() and path.name != "evidence_manifest.json"
        }
    except OSError as exc:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 evidence directory cannot be inspected"
        ) from exc
    if set(artifact_paths) != actual_artifacts:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 evidence manifest does not cover exact files"
        )
    for artifact in manifest.artifacts:
        relative = Path(artifact.path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.parent != evidence_relative
            or relative.as_posix() != artifact.path
            or relative.name == "evidence_manifest.json"
        ):
            raise ReviewPackError(
                "REVIEW_EVIDENCE_INVALID", "RUL-002 evidence artifact path is outside its ticket"
            )
        path = root / relative
        try:
            invalid = (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != artifact.bytes
                or sha256_file(path) != artifact.sha256
            )
        except OSError:
            invalid = True
        if invalid:
            raise ReviewPackError(
                "REVIEW_EVIDENCE_INVALID", "RUL-002 evidence artifact hash is invalid"
            )

    try:
        current_manifest = RepositoryManifest.model_validate(
            _rul_json_object(evidence_root / "current_manifest.json")
        )
    except ValueError as exc:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 current repository manifest is malformed"
        ) from exc
    if current_manifest.ticket_id != "RUL-002" or validate_repository_manifest(
        root, current_manifest
    ):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 current repository manifest has drift"
        )
    repository_report = _rul_json_object(evidence_root / "repository_validation_report.json")
    if repository_report != {"error_count": 0, "errors": [], "status": "PASS"}:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "RUL-002 repository validation report is not PASS"
        )


def _assemble_rul_entries(
    root: Path,
    *,
    baseline: str | None,
    generated_at: str,
    process_runner: ProcessRunner,
) -> list[ReviewEntry]:
    paths = ticket_paths(root, "RUL-002")
    validated = validate_evidence_file(paths.evidence / "codex_result.json")
    if not isinstance(validated.model, CodexResult) or validated.model.ticket_id != "RUL-002":
        raise ReviewPackError(
            "CODEX_RESULT_INVALID", "RUL-002 codex_result has the wrong evidence kind"
        )
    result = validated.model
    if baseline is None:
        raise ReviewPackError("BASELINE_INVALID", "RUL-002 baseline is required")
    head, git_state = _required_rul_git_state(root, baseline, process_runner)
    diff, diff_stat = _rul_baseline_diff(root, baseline, process_runner)
    if result.status.value == "COMPLETE" and result.code_commit != head:
        raise ReviewPackError(
            "REVIEW_COMMIT_MISMATCH", "COMPLETE result does not identify final HEAD"
        )
    _validate_rul_complete_evidence(root, result, head)
    limitations = _required_text(root, "evidence/tickets/RUL-002/KNOWN_LIMITATIONS.md")
    entries = [
        _entry(
            "01_REVIEW_INDEX.md",
            _rul_review_index(result.status.value, head, baseline, limitations),
            "review navigation",
        ),
        _entry("02_CODEX_RESULT.json", pretty_json(result), "structured implementation result"),
        _entry("04_FULL_DIFF.patch", diff, "full human-authored patch from required baseline"),
        _entry("05_DIFF_STAT.txt", diff_stat, "human-authored diff stat and exact omissions"),
        _entry(
            "06_GIT_STATUS.txt",
            git_state,
            "branch, HEAD, and clean-tree state",
        ),
        _entry("07_FILE_TREE.txt", _file_tree(root), "final non-operational repository tree"),
        _entry(
            "08_COMMANDS_LOG.txt",
            _required_text(root, "evidence/tickets/RUL-002/commands.log"),
            "exact command, exit, duration, and result records",
        ),
        _entry(
            "09_TEST_COVERAGE_MUTATION.md",
            _required_text(root, "evidence/tickets/RUL-002/TEST_RESULTS.md"),
            "tests, coverage, and mutation probes",
        ),
        _entry(
            "10_ACCEPTANCE_MATRIX.md",
            _required_text(root, "evidence/tickets/RUL-002/ACCEPTANCE.md"),
            "19-command acceptance matrix",
        ),
        _entry(
            "11_AUTHORITY_DECISION_REMEDIATION.md",
            _required_text(root, "evidence/tickets/RUL-002/AUTHORITY_REMEDIATION.md"),
            "authority precedence, full decision index, and stage map",
        ),
        _entry(
            "12_RULES_COMPILER_LIFECYCLE.md",
            _required_text(root, "evidence/tickets/RUL-002/RULES_COMPILER_REPORT.md"),
            "compiler, hash, and lifecycle review",
        ),
        _entry(
            "13_GOLDEN_SCORING_BPS_BONUS.md",
            _required_text(root, "evidence/tickets/RUL-002/GOLDEN_SCORING_REPORT.md"),
            "corrected v1.1 scoring oracle review",
        ),
        _entry(
            "14_DEPENDENCY_LOCK_PACKAGE.md",
            _required_text(root, "evidence/tickets/RUL-002/DEPENDENCY_PACKAGE_REPORT.md"),
            "lock, runtime graph, build, and clean-wheel provenance",
        ),
        _entry(
            "15_SECURITY_SOURCE_RIGHTS.md",
            _required_text(root, "evidence/tickets/RUL-002/SECURITY_SOURCE_RIGHTS.md"),
            "security, path, source-rights, and exclusion review",
        ),
        _entry(
            "16_KNOWN_LIMITATIONS.md",
            limitations,
            "exact unresolved limitations and open questions",
        ),
        _entry(
            "17_RULES_PUBLIC_CONTRACTS.txt",
            _concat_sources(
                root,
                (
                    "src/dmf_pulse/rules/__init__.py",
                    "src/dmf_pulse/rules/models.py",
                    "src/dmf_pulse/rules/errors.py",
                ),
            ),
            "public types, services, models, and errors",
        ),
        _entry(
            "18_RULES_IMPLEMENTATION.txt",
            _concat_sources(
                root,
                (
                    "src/dmf_pulse/rules/yaml_loader.py",
                    "src/dmf_pulse/rules/compiler.py",
                    "src/dmf_pulse/rules/lifecycle.py",
                    "src/dmf_pulse/rules/scoring.py",
                    "src/dmf_pulse/rules/bps.py",
                    "src/dmf_pulse/rules/bonus.py",
                    "src/dmf_pulse/rules/aggregation.py",
                ),
            ),
            "compiler, lifecycle, and scoring implementation",
        ),
        _entry(
            "19_CLI_CONFIG_CI.txt",
            _concat_sources(
                root,
                ("src/dmf_pulse/cli/rules_cmd.py", "pyproject.toml", ".github/workflows/ci.yml"),
            ),
            "CLI, package, and CI contracts",
        ),
    ]
    payload = {entry.name: entry.data for entry in entries}
    payload_sha256 = _primary_payload_digest(payload, RUL_PRIMARY_PAYLOAD_NAMES)
    manifest = ReviewManifest(
        ticket_id="RUL-002",
        generated_at=generated_at,
        repository_head=head,
        baseline=baseline,
        file_count=MAX_REVIEW_FILES,
        files=[
            ReviewFile(
                name=item.name,
                sha256=_sha256_bytes(item.data),
                bytes=len(item.data),
                purpose=item.purpose,
            )
            for item in entries
        ],
        acceptance_status=result.status,
        payload_sha256=payload_sha256,
        archive_sha256=None,
    )
    entries.append(_entry(MANIFEST_NAME, pretty_json(manifest), "detached payload manifest"))
    entries.sort(key=lambda item: item.name)
    entries.append(
        _entry(
            CHECKSUM_NAME,
            "".join(f"{_sha256_bytes(item.data)}  {item.name}\n" for item in entries),
            "detached checksum ledger",
        )
    )
    entries.sort(key=lambda item: item.name)
    enforce_review_limit(entries)
    if tuple(item.name for item in entries) != RUL_PREFERRED_NAMES:
        raise ReviewPackError(
            "REVIEW_PACK_LAYOUT", "RUL-002 review pack does not match its 20-file contract"
        )
    for item in entries:
        if scan_text(item.data.decode("utf-8"), path=item.name):
            raise ReviewPackError(
                "REVIEW_PACK_SECRET", f"secret-like content detected in {item.name}"
            )
    return entries


def _dat_baseline_diff(root: Path, baseline: str | None, runner: ProcessRunner) -> tuple[str, str]:
    if baseline != DAT_REQUIRED_BASELINE:
        raise ReviewPackError(
            "BASELINE_INVALID", "DAT-003 requires the ticket's exact baseline commit"
        )
    exclusions = [
        ":(exclude)uv.lock",
        ":(exclude)fixtures/data_model/DAT-003/**",
        ":(exclude)tickets/DAT-003/ticket.yaml",
        ":(exclude)tickets/DAT-003/ACCEPTANCE.md",
        ":(exclude).codex/schemas/*.json",
        ":(exclude)specs/manifests/runtime_lock_manifest.json",
        ":(exclude)evidence/tickets/DAT-003/**",
    ]
    patch = _required_git(
        root,
        ["diff", "--no-ext-diff", "--binary", f"{baseline}..HEAD", "--", ".", *exclusions],
        runner,
        code="BASELINE_DIFF_FAILED",
    )
    stat = _required_git(
        root,
        ["diff", "--stat", f"{baseline}..HEAD", "--", ".", *exclusions],
        runner,
        code="BASELINE_DIFF_FAILED",
    )
    omissions = (
        "uv.lock (generated; exact hash/runtime graph are reported in file 15)\n"
        "Pack 003 supplied fixtures and ticket contracts (hash-validated governed inputs; "
        "representative final fixture/output are included in file 17)\n"
        "generated JSON schemas, runtime-lock manifest, ticket evidence, and review output\n"
    )
    return patch, stat + "\nOmitted from the human-authored patch:\n" + omissions


def _required_dat_git_state(root: Path, baseline: str, runner: ProcessRunner) -> tuple[str, str]:
    branch = _required_git(
        root, ["rev-parse", "--abbrev-ref", "HEAD"], runner, code="REVIEW_BRANCH_INVALID"
    ).strip()
    if branch != DAT_REQUIRED_BRANCH:
        raise ReviewPackError(
            "REVIEW_BRANCH_INVALID", "DAT-003 review must use the required branch"
        )
    head = _required_git(
        root, ["rev-parse", "--verify", "HEAD"], runner, code="REVIEW_HEAD_INVALID"
    ).strip()
    if len(head) != 40 or any(character not in "0123456789abcdef" for character in head):
        raise ReviewPackError("REVIEW_HEAD_INVALID", "DAT-003 repository HEAD is invalid")
    _required_git(
        root,
        ["merge-base", "--is-ancestor", baseline, head],
        runner,
        code="REVIEW_BASELINE_ANCESTRY",
    )
    merges = _required_git(
        root,
        ["rev-list", "--merges", f"{baseline}..{head}"],
        runner,
        code="REVIEW_HISTORY_INVALID",
    )
    if merges.strip():
        raise ReviewPackError("REVIEW_HISTORY_INVALID", "DAT-003 history contains a merge commit")
    dirty = _required_git(
        root,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        runner,
        code="REVIEW_GIT_STATUS",
    )
    if dirty.strip():
        raise ReviewPackError("REVIEW_TREE_DIRTY", "DAT-003 review requires a clean working tree")
    return head, (
        f"branch: {branch}\n"
        f"head: {head}\n"
        f"baseline: {baseline}\n"
        "baseline_is_ancestor: true\n"
        "clean: true\n"
        "merge_commits_since_baseline: 0\n"
        "pushed_by_codex: false\n"
        "merged_by_codex: false\n"
    )


def _dat_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 machine evidence is unavailable or malformed"
        ) from exc
    if not isinstance(value, dict):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 machine evidence must be a JSON object"
        )
    return value


def _valid_duration(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and value >= 0
    )


def _number_at_least(value: object, minimum: float) -> bool:
    return _valid_duration(value) and isinstance(value, (int, float)) and float(value) >= minimum


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_dat_complete_evidence(root: Path, result: CodexResult, head: str) -> None:
    if result.status.value != "COMPLETE":
        return
    records = [item.model_dump(mode="json") for item in result.commands]
    if [item.get("command") for item in records] != list(DAT_MANDATORY_ACCEPTANCE_COMMANDS):
        raise ReviewPackError(
            "REVIEW_ACCEPTANCE_INVALID",
            "COMPLETE DAT-003 review requires the exact ordered 23-command result",
        )
    for index, record in enumerate(records, start=1):
        result_text = record.get("result")
        duration = record.get("duration_seconds")
        write_ahead = (
            (index == 22 and result_text == DAT_REVIEW_WRITE_AHEAD_RESULT)
            or (index == 23 and result_text == DAT_TEARDOWN_WRITE_AHEAD_RESULT)
        ) and duration is None
        if (
            record.get("exit_code") != 0
            or not isinstance(result_text, str)
            or not result_text.startswith("PASS:")
            or (not write_ahead and not _valid_duration(duration))
            or (index == 12 and "safe Windows equivalence" not in result_text)
            or (
                index == 22
                and result_text not in {DAT_REVIEW_WRITE_AHEAD_RESULT, DAT_REVIEW_FINAL_RESULT}
            )
        ):
            raise ReviewPackError(
                "REVIEW_ACCEPTANCE_INVALID",
                f"COMPLETE DAT-003 command {index} evidence is invalid",
            )

    evidence_root = root / "evidence/tickets/DAT-003"
    try:
        command_values = [
            json.loads(
                line,
                parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
            )
            for line in (evidence_root / "commands.log").read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 command log is malformed"
        ) from exc
    if command_values != records:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 command log and result do not match exactly"
        )

    tests = _dat_json_object(evidence_root / "tests.json")
    required_test_fields = {
        "branch_coverage_percent",
        "branches_covered",
        "branches_total",
        "collected",
        "critical_oracles",
        "data_database_branch_coverage_percent",
        "data_database_branches_covered",
        "data_database_branches_total",
        "failed",
        "passed",
        "rules_branch_coverage_percent",
        "rules_branches_covered",
        "rules_branches_total",
        "skipped",
        "status",
    }
    critical_oracles = tests.get("critical_oracles")
    if (
        set(tests) != required_test_fields
        or tests.get("status") != "PASS"
        or tests.get("failed") != 0
        or tests.get("skipped") != 0
        or not _positive_int(tests.get("passed"))
        or not _number_at_least(tests.get("branch_coverage_percent"), 90)
        or not _number_at_least(tests.get("rules_branch_coverage_percent"), 98)
        or not _number_at_least(tests.get("data_database_branch_coverage_percent"), 92)
        or not isinstance(critical_oracles, list)
        or len(critical_oracles) < 7
        or not all(isinstance(item, str) and item for item in critical_oracles)
        or result.tests != [tests]
    ):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 test and coverage evidence is incomplete"
        )

    acceptance = _dat_json_object(evidence_root / "acceptance_matrix.json")
    expected_rows = [
        {
            "command": record["command"],
            "duration_seconds": record["duration_seconds"],
            "exit_code": record["exit_code"],
            "expected_exit_code": 0,
            "status": "PASS",
        }
        for record in records
    ]
    if (
        set(acceptance) != {"commands", "failed", "passed", "status", "ticket_id"}
        or acceptance.get("ticket_id") != "DAT-003"
        or acceptance.get("status") != "COMPLETE"
        or acceptance.get("passed") != 23
        or acceptance.get("failed") != 0
        or acceptance.get("commands") != expected_rows
        or result.acceptance != expected_rows
    ):
        raise ReviewPackError(
            "REVIEW_ACCEPTANCE_INVALID", "DAT-003 acceptance matrix is incomplete"
        )

    validated_manifest = validate_evidence_file(evidence_root / "evidence_manifest.json")
    if not isinstance(validated_manifest.model, TicketEvidenceManifest):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 evidence manifest has the wrong contract kind"
        )
    manifest = validated_manifest.model
    if (
        manifest.ticket_id != "DAT-003"
        or manifest.status != "COMPLETE"
        or manifest.code_commit != head
        or manifest.commands != records
    ):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 evidence manifest provenance is incomplete"
        )
    artifact_paths = [item.path for item in manifest.artifacts]
    try:
        actual_artifacts = {
            path.relative_to(root).as_posix()
            for path in evidence_root.iterdir()
            if path.is_file() and path.name != "evidence_manifest.json"
        }
    except OSError as exc:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 evidence directory cannot be inspected"
        ) from exc
    if (
        artifact_paths != sorted(artifact_paths)
        or len(artifact_paths) != len(set(artifact_paths))
        or set(artifact_paths) != actual_artifacts
    ):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 evidence manifest does not cover exact files"
        )
    evidence_relative = Path("evidence/tickets/DAT-003")
    for artifact in manifest.artifacts:
        relative = Path(artifact.path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.parent != evidence_relative
            or relative.as_posix() != artifact.path
            or relative.name == "evidence_manifest.json"
        ):
            raise ReviewPackError(
                "REVIEW_EVIDENCE_INVALID", "DAT-003 evidence artifact path is outside its ticket"
            )
        path = root / relative
        try:
            invalid = (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != artifact.bytes
                or sha256_file(path) != artifact.sha256
            )
        except OSError:
            invalid = True
        if invalid:
            raise ReviewPackError(
                "REVIEW_EVIDENCE_INVALID", "DAT-003 evidence artifact hash is invalid"
            )

    try:
        current_manifest = RepositoryManifest.model_validate(
            _dat_json_object(evidence_root / "current_manifest.json")
        )
    except ValueError as exc:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 current repository manifest is malformed"
        ) from exc
    if current_manifest.ticket_id != "DAT-003" or validate_repository_manifest(
        root, current_manifest
    ):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 current repository manifest has drift"
        )
    repository_report = _dat_json_object(evidence_root / "repository_validation_report.json")
    if repository_report != {"error_count": 0, "errors": [], "status": "PASS"}:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 repository validation report is not PASS"
        )
    doctor = _dat_json_object(evidence_root / "database_doctor.json")
    schema = _dat_json_object(evidence_root / "schema_manifest.json")
    package = _dat_json_object(evidence_root / "package_report.json")
    migration = _dat_json_object(evidence_root / "migration_report.json")
    postgres = doctor.get("postgres")
    if (
        doctor.get("status") != "HEALTHY"
        or not isinstance(postgres, dict)
        or postgres.get("major") != 18
        or postgres.get("supported") is not True
        or schema.get("alembic_revision") != "20260723_0001"
        or schema.get("schema_sha256") != doctor.get("schema_sha256")
        or package.get("status") != "PASS"
        or migration.get("status") != "PASS"
    ):
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 database/package evidence is incomplete"
        )
    try:
        offline_sql = (evidence_root / "offline_upgrade.sql").read_bytes()
    except OSError as exc:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 offline migration SQL is unavailable"
        ) from exc
    if len(offline_sql) < 1024:
        raise ReviewPackError(
            "REVIEW_EVIDENCE_INVALID", "DAT-003 offline migration SQL is incomplete"
        )


def _dat_review_index(status: str, head: str, baseline: str, limitations: str) -> str:
    return f"""# DAT-003 review index

DMF Pulse DAT-003 closes the blocking RUL-002 findings and implements the PostgreSQL 18.4 canonical UUIDv7, bitemporal, immutable-provenance, rules-registry, migration, repository, installed-CLI, and assurance vertical slice. Acceptance status: **{status}**.

Baseline: `{baseline}`. Final repository HEAD: `{head}`. Read files 02, 10, 04, 11-16, then the compact contracts/implementation extracts in 17-19.

`payload_sha256` is the stable digest ledger for files 04-19. File 03 hashes files 01-02 and 04-19; file 20 hashes files 01-19. The actual archive SHA-256 and successful CRC/checksum result are external in `archive_finalization.json`, because the archive cannot embed its own hash.

Commands 22-23 use explicit write-ahead records so the review command runs once and PostgreSQL teardown remains finally-guaranteed. After teardown, the same deterministic assembler refreshes the archive without a second CLI invocation.

## Exact unresolved issues

{limitations.rstrip() or "None."}

No push, merge, rebase, reset, tag, amend, or repository-visibility change is part of this milestone. Human acceptance remains external.
"""


def _assemble_dat_entries(
    root: Path,
    *,
    baseline: str | None,
    generated_at: str,
    process_runner: ProcessRunner,
) -> list[ReviewEntry]:
    paths = ticket_paths(root, "DAT-003")
    validated = validate_evidence_file(paths.evidence / "codex_result.json")
    if not isinstance(validated.model, CodexResult) or validated.model.ticket_id != "DAT-003":
        raise ReviewPackError(
            "CODEX_RESULT_INVALID", "DAT-003 codex_result has the wrong evidence kind"
        )
    result = validated.model
    if baseline is None:
        raise ReviewPackError("BASELINE_INVALID", "DAT-003 baseline is required")
    head, git_state = _required_dat_git_state(root, baseline, process_runner)
    diff, diff_stat = _dat_baseline_diff(root, baseline, process_runner)
    if result.status.value == "COMPLETE" and result.code_commit != head:
        raise ReviewPackError(
            "REVIEW_COMMIT_MISMATCH", "COMPLETE result does not identify final HEAD"
        )
    _validate_dat_complete_evidence(root, result, head)
    limitations = _required_text(root, "evidence/tickets/DAT-003/KNOWN_LIMITATIONS.md")
    entries = [
        _entry(
            "01_REVIEW_INDEX.md",
            _dat_review_index(result.status.value, head, baseline, limitations),
            "review navigation and detached-hash semantics",
        ),
        _entry("02_CODEX_RESULT.json", pretty_json(result), "structured implementation result"),
        _entry("04_FULL_DIFF.patch", diff, "complete human-authored patch from required baseline"),
        _entry("05_DIFF_STAT.txt", diff_stat, "human-authored diff stat and exact omissions"),
        _entry("06_GIT_STATUS.txt", git_state, "branch, HEAD, baseline, and clean-tree state"),
        _entry("07_FILE_TREE.txt", _file_tree(root), "final non-operational repository tree"),
        _entry(
            "08_COMMANDS_LOG.txt",
            _required_text(root, "evidence/tickets/DAT-003/commands.log"),
            "exact 23-command ledger",
        ),
        _entry(
            "09_TEST_COVERAGE_MUTATION_ORACLES.md",
            _required_text(root, "evidence/tickets/DAT-003/TEST_RESULTS.md"),
            "tests, branch gates, and independent mutation oracles",
        ),
        _entry(
            "10_ACCEPTANCE_MATRIX.md",
            _required_text(root, "evidence/tickets/DAT-003/ACCEPTANCE.md"),
            "literal 23-command acceptance matrix",
        ),
        _entry(
            "11_RUL002_REMEDIATION_MATRIX.md",
            _required_text(root, "evidence/tickets/DAT-003/RUL002_REMEDIATION_MATRIX.md"),
            "blocking RUL-002 finding-to-code/test closure",
        ),
        _entry(
            "12_SCHEMA_MIGRATION.md",
            _required_text(root, "evidence/tickets/DAT-003/SCHEMA_MIGRATION.md"),
            "schema fingerprint and reversible migration evidence",
        ),
        _entry(
            "13_TEMPORAL_IDENTITY_ASOF_CONCURRENCY.md",
            _required_text(root, "evidence/tickets/DAT-003/TEMPORAL_IDENTITY_ASOF_CONCURRENCY.md"),
            "UUIDv7, bitemporal, boundary, and concurrent-writer review",
        ),
        _entry(
            "14_PROVENANCE_IMMUTABILITY_RULES_REGISTRY.md",
            _required_text(
                root, "evidence/tickets/DAT-003/PROVENANCE_IMMUTABILITY_RULES_REGISTRY.md"
            ),
            "source, immutability, correction, and rules-registry review",
        ),
        _entry(
            "15_DEPENDENCY_DOCKER_CI_SECURITY.md",
            _required_text(root, "evidence/tickets/DAT-003/DEPENDENCY_DOCKER_CI_SECURITY.md"),
            "lock, wheel, Docker, CI, security, and secret review",
        ),
        _entry("16_KNOWN_LIMITATIONS.md", limitations, "exact limitations and open questions"),
        _entry(
            "17_DATA_MODEL_PUBLIC_CONTRACTS_MODELS.txt",
            _concat_sources(
                root,
                (
                    "src/dmf_pulse/data_model/__init__.py",
                    "src/dmf_pulse/data_model/models.py",
                    "src/dmf_pulse/data_model/tables.py",
                    "src/dmf_pulse/database/models.py",
                    "src/dmf_pulse/database/errors.py",
                    "fixtures/data_model/DAT-003/demo.json",
                    "evidence/tickets/DAT-003/demo_result.json",
                    "evidence/tickets/DAT-003/schema_manifest.json",
                ),
            ),
            "public contracts/models plus representative fixture, result, and schema manifest",
        ),
        _entry(
            "18_INITIAL_MIGRATION_CRITICAL_SQL.txt",
            _concat_sources(
                root,
                (
                    "src/dmf_pulse/database/migrations/versions/20260723_0001_dat003_foundation.py",
                    "src/dmf_pulse/database/schema.py",
                ),
            ),
            "complete initial migration and schema inspection contract",
        ),
        _entry(
            "19_REPOSITORY_CLI_CONFIG_COMPOSE_CI.txt",
            _concat_sources(
                root,
                (
                    "src/dmf_pulse/data_model/repositories.py",
                    "src/dmf_pulse/data_model/services.py",
                    "src/dmf_pulse/cli/data_model_cmd.py",
                    "src/dmf_pulse/database/engine.py",
                    "alembic.ini",
                    "compose.test.yaml",
                    "pyproject.toml",
                    ".github/workflows/ci.yml",
                    "fixtures/data_model/DAT-003/expected_schema.json",
                ),
            ),
            "repositories, CLI, config, Compose, CI, and expected schema",
        ),
    ]
    payload = {entry.name: entry.data for entry in entries}
    payload_sha256 = _primary_payload_digest(payload, DAT_PRIMARY_PAYLOAD_NAMES)
    manifest = ReviewManifest(
        ticket_id="DAT-003",
        generated_at=generated_at,
        repository_head=head,
        baseline=baseline,
        file_count=MAX_REVIEW_FILES,
        files=[
            ReviewFile(
                name=item.name,
                sha256=_sha256_bytes(item.data),
                bytes=len(item.data),
                purpose=item.purpose,
            )
            for item in entries
        ],
        acceptance_status=result.status,
        payload_sha256=payload_sha256,
        archive_sha256=None,
    )
    entries.append(_entry(MANIFEST_NAME, pretty_json(manifest), "detached payload manifest"))
    entries.sort(key=lambda item: item.name)
    entries.append(
        _entry(
            CHECKSUM_NAME,
            "".join(f"{_sha256_bytes(item.data)}  {item.name}\n" for item in entries),
            "detached checksum ledger",
        )
    )
    entries.sort(key=lambda item: item.name)
    enforce_review_limit(entries)
    if tuple(item.name for item in entries) != DAT_PREFERRED_NAMES:
        raise ReviewPackError(
            "REVIEW_PACK_LAYOUT", "DAT-003 review pack does not match its 20-file contract"
        )
    if set(item.name for item in entries if item.name not in {MANIFEST_NAME, CHECKSUM_NAME}) != (
        DAT_DETACHED_REVIEW_NAMES
    ):
        raise ReviewPackError("REVIEW_PACK_LAYOUT", "DAT-003 detached manifest layout drifted")
    for item in entries:
        if scan_text(item.data.decode("utf-8"), path=item.name):
            raise ReviewPackError(
                "REVIEW_PACK_SECRET", f"secret-like content detected in {item.name}"
            )
    return entries


def _assemble_for_ticket(
    root: Path,
    *,
    ticket: str,
    baseline: str | None,
    generated_at: str,
    process_runner: ProcessRunner,
) -> list[ReviewEntry]:
    try:
        validated_ticket = validate_ticket_id(ticket)
    except TicketIdError as exc:
        raise ReviewPackError("REVIEW_TICKET_INVALID", str(exc)) from exc
    if validated_ticket == "FND-001":
        return _assemble_fnd_entries(root, generated_at=generated_at, process_runner=process_runner)
    if validated_ticket == "RUL-002":
        return _assemble_rul_entries(
            root,
            baseline=baseline,
            generated_at=generated_at,
            process_runner=process_runner,
        )
    if validated_ticket == "DAT-003":
        return _assemble_dat_entries(
            root,
            baseline=baseline,
            generated_at=generated_at,
            process_runner=process_runner,
        )
    raise ReviewPackError("REVIEW_TICKET_UNSUPPORTED", "ticket review contract is not installed")


def _write_deterministic_zip(path: Path, entries: list[ReviewEntry]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for entry in entries:
            info = zipfile.ZipInfo(entry.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entry.data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_review_pack(
    root: Path,
    *,
    ticket: str,
    output: Path,
    generated_at: str,
    baseline: str | None = None,
    process_runner: ProcessRunner | None = None,
) -> ReviewPackSummary:
    """Build, atomically place, and revalidate an installed ticket review contract."""

    try:
        validated_ticket = validate_ticket_id(ticket)
    except TicketIdError as exc:
        raise ReviewPackError("REVIEW_TICKET_INVALID", str(exc)) from exc
    repository_findings = scan_repository(root)
    if repository_findings:
        raise ReviewPackError(
            "REPOSITORY_SECRET",
            f"repository secret scan has {len(repository_findings)} finding(s)",
        )
    selected_runner = process_runner or SubprocessProcessRunner()
    entries = _assemble_for_ticket(
        root,
        ticket=validated_ticket,
        baseline=baseline,
        generated_at=generated_at,
        process_runner=selected_runner,
    )
    primary_names = (
        DAT_PRIMARY_PAYLOAD_NAMES
        if validated_ticket == "DAT-003"
        else RUL_PRIMARY_PAYLOAD_NAMES
        if validated_ticket == "RUL-002"
        else PRIMARY_PAYLOAD_NAMES
    )
    payload_sha256 = _primary_payload_digest(
        {entry.name: entry.data for entry in entries}, primary_names
    )
    result_entry = next(item for item in entries if item.name == "02_CODEX_RESULT.json")
    result = CodexResult.model_validate_json(result_entry.data)
    if (
        result.status.value == "COMPLETE"
        and result.review_pack.effective_payload_sha256 != payload_sha256
    ):
        raise ReviewPackError(
            "REVIEW_PAYLOAD_DIGEST",
            "codex_result review-pack digest does not match the detached primary payload",
        )
    zip_name = (
        DAT_REVIEW_ZIP_NAME
        if validated_ticket == "DAT-003"
        else RUL_REVIEW_ZIP_NAME
        if validated_ticket == "RUL-002"
        else REVIEW_ZIP_NAME
    )
    output_path = output if output.suffix.casefold() == ".zip" else output / zip_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_zip: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".dmf-review-", suffix=".tmp", dir=output_path.parent, delete=False
        ) as handle:
            temporary_zip = Path(handle.name)
        _write_deterministic_zip(temporary_zip, entries)
        validate_review_zip(temporary_zip)
        os.replace(temporary_zip, output_path)
        temporary_zip = None
    finally:
        if temporary_zip is not None:
            temporary_zip.unlink(missing_ok=True)
    validate_review_zip(output_path)
    return ReviewPackSummary(
        path=output_path,
        file_count=len(entries),
        sha256=sha256_file(output_path),
        payload_sha256=payload_sha256,
    )


def _parse_checksums(value: str) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in value.splitlines():
        parts = line.split("  ", maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ReviewPackError("REVIEW_CHECKSUM_FORMAT", "checksum ledger is malformed")
        digest, name = parts
        if name in checksums:
            raise ReviewPackError("REVIEW_CHECKSUM_DUPLICATE", "checksum ledger has duplicates")
        checksums[name] = digest
    return checksums


def validate_review_zip(path: Path) -> ReviewPackSummary:
    """Validate root layout, cap, detached manifest, checksums, hashes, and archive policy."""

    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) > MAX_REVIEW_FILES:
                raise ReviewPackError(
                    "REVIEW_PACK_FILE_LIMIT",
                    f"review pack has {len(names)} files; maximum is {MAX_REVIEW_FILES}",
                )
            if len(names) != len(set(names)):
                raise ReviewPackError("REVIEW_PACK_LAYOUT", "review ZIP contains duplicate entries")
            if any(Path(name).name != name or "/" in name or "\\" in name for name in names):
                raise ReviewPackError("REVIEW_PACK_NESTED_PATH", "review ZIP contains nested paths")
            if any(name.casefold().endswith((".zip", ".tar", ".gz", ".7z")) for name in names):
                raise ReviewPackError(
                    "REVIEW_PACK_NESTED_ARCHIVE", "nested archives are prohibited"
                )
            payload = {name: archive.read(name) for name in names}
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReviewPackError(
            "REVIEW_ZIP_INVALID", "review ZIP is unavailable or malformed"
        ) from exc

    if {"02_CODEX_RESULT.json", MANIFEST_NAME, CHECKSUM_NAME} - set(payload):
        raise ReviewPackError("REVIEW_PACK_LAYOUT", "review ZIP root layout is invalid")

    try:
        result = CodexResult.model_validate_json(payload["02_CODEX_RESULT.json"])
        if result.ticket_id not in {"FND-001", "RUL-002", "DAT-003"}:
            raise ReviewPackError("REVIEW_TICKET_UNSUPPORTED", "review ZIP ticket is unsupported")
        preferred = (
            DAT_PREFERRED_NAMES
            if result.ticket_id == "DAT-003"
            else RUL_PREFERRED_NAMES
            if result.ticket_id == "RUL-002"
            else PREFERRED_NAMES
        )
        if tuple(sorted(payload)) != preferred:
            raise ReviewPackError("REVIEW_PACK_LAYOUT", "review ZIP root layout is invalid")
        manifest_value = json.loads(payload[MANIFEST_NAME].decode("utf-8"))
        manifest = ReviewManifest.model_validate(manifest_value)
        checksums = _parse_checksums(payload[CHECKSUM_NAME].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReviewPackError("REVIEW_METADATA_INVALID", "review metadata is malformed") from exc
    if manifest.file_count != len(payload):
        raise ReviewPackError("REVIEW_FILE_COUNT_MISMATCH", "manifest file_count is not ZIP count")
    if result.review_pack.file_count != len(payload):
        raise ReviewPackError("REVIEW_FILE_COUNT_MISMATCH", "result file_count is not ZIP count")
    expected_manifest_names = set(payload) - {MANIFEST_NAME, CHECKSUM_NAME}
    if {item.name for item in manifest.files} != expected_manifest_names:
        raise ReviewPackError(
            "REVIEW_MANIFEST_COVERAGE", "detached manifest coverage is incomplete"
        )
    for item in manifest.files:
        if item.bytes != len(payload[item.name]) or item.sha256 != _sha256_bytes(
            payload[item.name]
        ):
            raise ReviewPackError("REVIEW_MANIFEST_HASH", f"manifest mismatch for {item.name}")
    expected_checksum_names = set(payload) - {CHECKSUM_NAME}
    if set(checksums) != expected_checksum_names:
        raise ReviewPackError("REVIEW_CHECKSUM_COVERAGE", "checksum ledger coverage is incomplete")
    for name, digest in checksums.items():
        if digest != _sha256_bytes(payload[name]):
            raise ReviewPackError("REVIEW_CHECKSUM_HASH", f"checksum mismatch for {name}")
    primary_names = (
        DAT_PRIMARY_PAYLOAD_NAMES
        if result.ticket_id == "DAT-003"
        else RUL_PRIMARY_PAYLOAD_NAMES
        if result.ticket_id == "RUL-002"
        else PRIMARY_PAYLOAD_NAMES
    )
    payload_sha256 = _primary_payload_digest(payload, primary_names)
    if manifest.ticket_id != result.ticket_id:
        raise ReviewPackError(
            "REVIEW_TICKET_MISMATCH", "review result and manifest ticket IDs differ"
        )
    if manifest.acceptance_status is not result.status:
        raise ReviewPackError(
            "REVIEW_STATUS_MISMATCH", "review result and manifest statuses differ"
        )
    if result.ticket_id == "RUL-002" and (
        result.code_commit is None
        or manifest.repository_head != result.code_commit
        or manifest.baseline != RUL_REQUIRED_BASELINE
        or result.repository is None
        or result.repository.head != manifest.repository_head
    ):
        raise ReviewPackError(
            "REVIEW_PROVENANCE_MISMATCH", "RUL-002 review provenance is contradictory"
        )
    if result.ticket_id == "RUL-002" and manifest.payload_sha256 != payload_sha256:
        raise ReviewPackError(
            "REVIEW_PAYLOAD_DIGEST", "review manifest payload digest does not match"
        )
    if result.ticket_id == "DAT-003" and (
        result.code_commit is None
        or manifest.repository_head != result.code_commit
        or manifest.baseline != DAT_REQUIRED_BASELINE
        or result.repository is None
        or result.repository.head != manifest.repository_head
    ):
        raise ReviewPackError(
            "REVIEW_PROVENANCE_MISMATCH", "DAT-003 review provenance is contradictory"
        )
    if result.ticket_id == "DAT-003" and manifest.payload_sha256 != payload_sha256:
        raise ReviewPackError(
            "REVIEW_PAYLOAD_DIGEST", "DAT-003 review manifest payload digest does not match"
        )
    if (
        result.status.value == "COMPLETE"
        and result.review_pack.effective_payload_sha256 != payload_sha256
    ):
        raise ReviewPackError(
            "REVIEW_PAYLOAD_DIGEST", "embedded result digest does not match primary payload"
        )
    return ReviewPackSummary(
        path=path,
        file_count=len(payload),
        sha256=sha256_file(path),
        payload_sha256=payload_sha256,
    )
