"""Review-pack cap, diff, detached manifest, and tamper tests."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from dmf_pulse.assurance import review_pack as review_pack_module
from dmf_pulse.assurance.manifests import build_repository_manifest
from dmf_pulse.assurance.review_pack import (
    DAT_MANDATORY_ACCEPTANCE_COMMANDS,
    DAT_PREFERRED_NAMES,
    DAT_REQUIRED_BASELINE,
    DAT_REVIEW_WRITE_AHEAD_RESULT,
    DAT_REVIEW_ZIP_NAME,
    DAT_TEARDOWN_WRITE_AHEAD_RESULT,
    REVIEW_ZIP_NAME,
    RUL_MANDATORY_ACCEPTANCE_COMMANDS,
    RUL_PREFERRED_NAMES,
    RUL_REQUIRED_BASELINE,
    RUL_REVIEW_FINAL_RESULT,
    RUL_REVIEW_ZIP_NAME,
    ReviewEntry,
    ReviewPackError,
    build_empty_baseline_diff,
    build_review_pack,
    calculate_review_payload_digest,
    enforce_review_limit,
    validate_review_zip,
)
from dmf_pulse.system.process import ProcessResult, SubprocessProcessRunner


class GitRunner:
    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        assert timeout_seconds == 5
        if "rev-parse" in command:
            if "--abbrev-ref" in command:
                return ProcessResult(return_code=0, stdout="stage/A2/RUL-002-rules-foundation\n")
            return ProcessResult(return_code=0, stdout="a" * 40 + "\n")
        if "--porcelain=v1" in command or "--merges" in command:
            return ProcessResult(return_code=0, stdout="")
        return ProcessResult(return_code=0, stdout="## test/FND-001\n")


class OneResultRunner:
    def __init__(self, result: ProcessResult) -> None:
        self.result = result

    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        assert "-C" in command
        assert timeout_seconds == 5
        return self.result


class RulGitRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        assert timeout_seconds in {5, 30}
        self.commands.append(tuple(command))
        if "rev-parse" in command:
            if "--abbrev-ref" in command:
                return ProcessResult(return_code=0, stdout="stage/A2/RUL-002-rules-foundation\n")
            return ProcessResult(return_code=0, stdout="a" * 40 + "\n")
        if "--porcelain=v1" in command or "--merges" in command:
            return ProcessResult(return_code=0, stdout="")
        if "--stat" in command:
            return ProcessResult(return_code=0, stdout="2 files changed, 4 insertions(+)\n")
        if "diff" in command:
            return ProcessResult(
                return_code=0,
                stdout=(
                    "diff --git a/fixtures/rules/RUL-002/reference_2025_26/scoring.yaml "
                    "b/fixtures/rules/RUL-002/reference_2025_26/scoring.yaml\n"
                ),
            )
        return ProcessResult(return_code=0, stdout="## stage/A2/RUL-002-rules-foundation\n")


class DatGitRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        assert timeout_seconds in {5, 30}
        self.commands.append(tuple(command))
        if "rev-parse" in command:
            if "--abbrev-ref" in command:
                return ProcessResult(
                    return_code=0, stdout="stage/A3/DAT-003-canonical-foundation\n"
                )
            return ProcessResult(return_code=0, stdout="a" * 40 + "\n")
        if "--porcelain=v1" in command or "--merges" in command or "merge-base" in command:
            return ProcessResult(return_code=0, stdout="")
        if "--stat" in command:
            return ProcessResult(return_code=0, stdout="3 files changed, 12 insertions(+)\n")
        if "diff" in command:
            return ProcessResult(
                return_code=0,
                stdout="diff --git a/src/dmf_pulse/data_model/models.py b/src/dmf_pulse/data_model/models.py\n",
            )
        return ProcessResult(return_code=0, stdout="## stage/A3/DAT-003-canonical-foundation\n")


class DatStateRunner:
    def __init__(
        self,
        *,
        branch: str = "stage/A3/DAT-003-canonical-foundation",
        head: str = "a" * 40,
        merges: str = "",
        dirty: str = "",
    ) -> None:
        self.branch = branch
        self.head = head
        self.merges = merges
        self.dirty = dirty

    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        assert timeout_seconds == 30
        if "--abbrev-ref" in command:
            return ProcessResult(return_code=0, stdout=self.branch + "\n")
        if "rev-parse" in command:
            return ProcessResult(return_code=0, stdout=self.head + "\n")
        if "--merges" in command:
            return ProcessResult(return_code=0, stdout=self.merges)
        if "--porcelain=v1" in command:
            return ProcessResult(return_code=0, stdout=self.dirty)
        return ProcessResult(return_code=0, stdout="")


def _codex_result(*, status: str = "FAILED") -> dict[str, object]:
    return {
        "ticket_id": "FND-001",
        "status": status,
        "summary": "Fixture foundation complete.",
        "files_changed": [{"path": "src/example.py", "change": "created"}],
        "public_interfaces": ["dmf --version"],
        "commands": [{"command": "pytest", "exit_code": 0}],
        "tests": [{"name": "fixture", "status": "PASS"}],
        "acceptance": [{"name": "fixture", "status": "PASS"}],
        "dependency_impact": "approved only",
        "migration_impact": "none",
        "assumptions": [],
        "exclusions_verified": ["domain logic"],
        "risks": [],
        "review_pack": {
            "path": "review_pack/FND-001/" + REVIEW_ZIP_NAME,
            "file_count": 20,
            "sha256": "0" * 64,
        },
    }


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _fixture_repository(root: Path) -> None:
    _write(
        root / "evidence/tickets/FND-001/baseline_manifest.json",
        json.dumps({"repository_empty": True}),
    )
    _write(root / "evidence/tickets/FND-001/codex_result.json", json.dumps(_codex_result()))
    for name, text in {
        "commands.log": "pytest | exit=0\n",
        "TEST_RESULTS.md": "# Tests\n\nPass.\n",
        "ACCEPTANCE.md": "# Acceptance\n\nComplete.\n",
        "DEPENDENCY_REPORT.md": "# Dependencies\n\nApproved.\n",
        "SECURITY_REVIEW.md": "# Security\n\nNo findings.\n",
        "PACKAGE_REVIEW.md": "# Package\n\nClean wheel.\n",
        "KNOWN_LIMITATIONS.md": "None.\n",
    }.items():
        _write(root / "evidence/tickets/FND-001" / name, text)
    _write(root / "docs/adr/ADR-FND-001-TOOLCHAIN.md", "# Toolchain\n\nPython 3.13.\n")
    _write(root / "AGENTS.md", "# Agents\n\nStay in scope.\n")
    _write(root / "pyproject.toml", '[project]\nname = "fixture"\n')
    _write(root / "Makefile", "test:\n\tuv run pytest\n")
    _write(root / ".github/workflows/ci.yml", "name: ci\n")
    _write(root / "src/example.py", "VALUE = 1\n")
    _write(root / "uv.lock", "generated lock noise\n")
    _write(root / ".secret-scan-allowlist.json", '{"entries": [], "version": "1.0"}\n')


def _rul_fixture_repository(root: Path) -> None:
    commands = []
    for index, command in enumerate(RUL_MANDATORY_ACCEPTANCE_COMMANDS, start=1):
        result_text = "PASS: fixture acceptance"
        if index == 14:
            result_text = "PASS: expected blocking exit 4; RULESET_ACTIVATION_BLOCKED"
        elif index == 19:
            result_text = RUL_REVIEW_FINAL_RESULT
        commands.append(
            {
                "command": command,
                "duration_seconds": 0.1,
                "exit_code": 4 if index == 14 else 0,
                "result": result_text,
            }
        )
    acceptance = [
        {
            "command": record["command"],
            "duration_seconds": record["duration_seconds"],
            "exit_code": record["exit_code"],
            "expected_exit_code": 4 if index == 14 else 0,
            "status": "PASS",
        }
        for index, record in enumerate(commands, start=1)
    ]
    tests = {
        "branch_coverage_percent": 91.0,
        "branches_covered": 91,
        "branches_total": 100,
        "collected": 10,
        "failed": 0,
        "passed": 10,
        "rules_branch_coverage_percent": 96.0,
        "rules_branches_covered": 96,
        "rules_branches_total": 100,
        "skipped": 0,
        "status": "PASS",
    }
    result = _codex_result()
    result.update(
        {
            "acceptance": acceptance,
            "ticket_id": "RUL-002",
            "code_commit": "a" * 40,
            "commands": commands,
            "review_pack": {
                "path": "review_pack/RUL-002/" + RUL_REVIEW_ZIP_NAME,
                "file_count": 20,
                "payload_sha256": "0" * 64,
            },
            "repository": {
                "baseline": RUL_REQUIRED_BASELINE,
                "branch": "stage/A2/RUL-002-rules-foundation",
                "clean": True,
                "head": "a" * 40,
                "merged": False,
                "pushed": False,
            },
            "tests": [tests],
        }
    )
    _write(root / "evidence/tickets/RUL-002/codex_result.json", json.dumps(result))
    _write(
        root / "evidence/tickets/RUL-002/commands.log",
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in commands),
    )
    _write(root / "evidence/tickets/RUL-002/tests.json", json.dumps(tests))
    _write(
        root / "evidence/tickets/RUL-002/acceptance_matrix.json",
        json.dumps(
            {
                "commands": acceptance,
                "failed": 0,
                "passed": 19,
                "status": "COMPLETE",
                "ticket_id": "RUL-002",
            }
        ),
    )
    for name in (
        "TEST_RESULTS.md",
        "ACCEPTANCE.md",
        "AUTHORITY_REMEDIATION.md",
        "RULES_COMPILER_REPORT.md",
        "GOLDEN_SCORING_REPORT.md",
        "DEPENDENCY_PACKAGE_REPORT.md",
        "SECURITY_SOURCE_RIGHTS.md",
        "KNOWN_LIMITATIONS.md",
    ):
        _write(root / "evidence/tickets/RUL-002" / name, f"# {name}\n\nPASS\n")
    for relative in (
        "src/dmf_pulse/rules/__init__.py",
        "src/dmf_pulse/rules/models.py",
        "src/dmf_pulse/rules/errors.py",
        "src/dmf_pulse/rules/yaml_loader.py",
        "src/dmf_pulse/rules/compiler.py",
        "src/dmf_pulse/rules/lifecycle.py",
        "src/dmf_pulse/rules/scoring.py",
        "src/dmf_pulse/rules/bps.py",
        "src/dmf_pulse/rules/bonus.py",
        "src/dmf_pulse/rules/aggregation.py",
        "src/dmf_pulse/cli/rules_cmd.py",
        "pyproject.toml",
        ".github/workflows/ci.yml",
        "fixtures/rules/RUL-002/reference_2025_26/scoring.yaml",
    ):
        _write(root / relative, f"# {relative}\n")
    _write(root / ".secret-scan-allowlist.json", '{"entries": [], "version": "1.0"}\n')
    for name in ("coverage.json", "dependency_report.json", "package_report.json"):
        _write(root / "evidence/tickets/RUL-002" / name, "{}\n")
    _write(
        root / "evidence/tickets/RUL-002/repository_validation_report.json",
        json.dumps({"error_count": 0, "errors": [], "status": "PASS"}),
    )
    current = build_repository_manifest(root, ticket_id="RUL-002")
    _write(
        root / "evidence/tickets/RUL-002/current_manifest.json",
        json.dumps(current.model_dump(mode="json")),
    )
    _refresh_rul_evidence_manifest(root)


def _refresh_rul_evidence_manifest(root: Path) -> None:
    evidence_root = root / "evidence/tickets/RUL-002"
    result = json.loads((evidence_root / "codex_result.json").read_text(encoding="utf-8"))
    artifacts = []
    for path in sorted(evidence_root.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.name != "evidence_manifest.json":
            payload = path.read_bytes()
            artifacts.append(
                {
                    "bytes": len(payload),
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    _write(
        evidence_root / "evidence_manifest.json",
        json.dumps(
            {
                "artifacts": artifacts,
                "code_commit": "a" * 40,
                "commands": result["commands"],
                "context_hash": "0" * 64,
                "created_at": "2026-07-22T00:00:00Z",
                "known_limitations": [],
                "status": "COMPLETE",
                "ticket_id": "RUL-002",
            }
        ),
    )


def _refresh_dat_evidence_manifest(root: Path) -> None:
    evidence_root = root / "evidence/tickets/DAT-003"
    result = json.loads((evidence_root / "codex_result.json").read_text(encoding="utf-8"))
    artifacts = []
    for path in sorted(evidence_root.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.name != "evidence_manifest.json":
            payload = path.read_bytes()
            artifacts.append(
                {
                    "bytes": len(payload),
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    _write(
        evidence_root / "evidence_manifest.json",
        json.dumps(
            {
                "artifacts": artifacts,
                "code_commit": "a" * 40,
                "commands": result["commands"],
                "context_hash": "0" * 64,
                "created_at": "2026-07-23T00:00:00Z",
                "known_limitations": [],
                "status": "COMPLETE",
                "ticket_id": "DAT-003",
            }
        ),
    )


def _dat_fixture_repository(root: Path) -> None:
    evidence_root = root / "evidence/tickets/DAT-003"
    commands = []
    for index, command in enumerate(DAT_MANDATORY_ACCEPTANCE_COMMANDS, start=1):
        result = "PASS: fixture acceptance"
        duration: float | None = 0.1
        if index == 12:
            result = "PASS: offline SQL captured by safe Windows equivalence"
        elif index == 22:
            result = DAT_REVIEW_WRITE_AHEAD_RESULT
            duration = None
        elif index == 23:
            result = DAT_TEARDOWN_WRITE_AHEAD_RESULT
            duration = None
        commands.append(
            {
                "command": command,
                "duration_seconds": duration,
                "exit_code": 0,
                "result": result,
            }
        )
    acceptance = [
        {
            "command": record["command"],
            "duration_seconds": record["duration_seconds"],
            "exit_code": 0,
            "expected_exit_code": 0,
            "status": "PASS",
        }
        for record in commands
    ]
    tests = {
        "branch_coverage_percent": 91.0,
        "branches_covered": 91,
        "branches_total": 100,
        "collected": 12,
        "critical_oracles": [f"oracle-{index}" for index in range(7)],
        "data_database_branch_coverage_percent": 93.0,
        "data_database_branches_covered": 93,
        "data_database_branches_total": 100,
        "failed": 0,
        "passed": 12,
        "rules_branch_coverage_percent": 99.0,
        "rules_branches_covered": 99,
        "rules_branches_total": 100,
        "skipped": 0,
        "status": "PASS",
    }
    result = {
        "ticket_id": "DAT-003",
        "status": "COMPLETE",
        "code_commit": "a" * 40,
        "summary": "Fixture DAT foundation complete.",
        "files_changed": [{"path": "src/example.py", "change": "created"}],
        "public_interfaces": ["dmf data-model doctor --json"],
        "commands": commands,
        "tests": [tests],
        "acceptance": acceptance,
        "dependency_impact": "approved only",
        "migration_impact": "reversible",
        "assumptions": [],
        "exclusions_verified": ["no SQLite"],
        "risks": [],
        "repository": {
            "baseline": DAT_REQUIRED_BASELINE,
            "branch": "stage/A3/DAT-003-canonical-foundation",
            "clean": True,
            "head": "a" * 40,
            "merged": False,
            "pushed": False,
        },
        "review_pack": {
            "path": "review_pack/DAT-003/DMF_PULSE_DAT-003_REVIEW.zip",
            "file_count": 20,
            "payload_sha256": "0" * 64,
        },
    }
    _write(evidence_root / "codex_result.json", json.dumps(result))
    _write(
        evidence_root / "commands.log",
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in commands),
    )
    _write(evidence_root / "tests.json", json.dumps(tests))
    _write(
        evidence_root / "acceptance_matrix.json",
        json.dumps(
            {
                "commands": acceptance,
                "failed": 0,
                "passed": 23,
                "status": "COMPLETE",
                "ticket_id": "DAT-003",
            }
        ),
    )
    for name in (
        "TEST_RESULTS.md",
        "ACCEPTANCE.md",
        "RUL002_REMEDIATION_MATRIX.md",
        "SCHEMA_MIGRATION.md",
        "TEMPORAL_IDENTITY_ASOF_CONCURRENCY.md",
        "PROVENANCE_IMMUTABILITY_RULES_REGISTRY.md",
        "DEPENDENCY_DOCKER_CI_SECURITY.md",
        "KNOWN_LIMITATIONS.md",
    ):
        _write(evidence_root / name, f"# {name}\n\nPASS\n")
    schema_hash = "1" * 64
    _write(
        evidence_root / "database_doctor.json",
        json.dumps(
            {
                "status": "HEALTHY",
                "postgres": {"major": 18, "supported": True, "version": "18.4"},
                "schema_sha256": schema_hash,
            }
        ),
    )
    _write(
        evidence_root / "schema_manifest.json",
        json.dumps({"alembic_revision": "20260723_0001", "schema_sha256": schema_hash}),
    )
    _write(evidence_root / "package_report.json", json.dumps({"status": "PASS"}))
    _write(evidence_root / "migration_report.json", json.dumps({"status": "PASS"}))
    _write(
        evidence_root / "repository_validation_report.json",
        json.dumps({"error_count": 0, "errors": [], "status": "PASS"}),
    )
    _write(evidence_root / "demo_result.json", '{"fixture_id":"demo"}\n')
    _write(evidence_root / "offline_upgrade.sql", "CREATE TABLE safe_fixture(id integer);\n" * 40)
    for relative in (
        "src/dmf_pulse/data_model/__init__.py",
        "src/dmf_pulse/data_model/models.py",
        "src/dmf_pulse/data_model/tables.py",
        "src/dmf_pulse/data_model/repositories.py",
        "src/dmf_pulse/data_model/services.py",
        "src/dmf_pulse/database/models.py",
        "src/dmf_pulse/database/errors.py",
        "src/dmf_pulse/database/schema.py",
        "src/dmf_pulse/database/engine.py",
        "src/dmf_pulse/database/migrations/versions/20260723_0001_dat003_foundation.py",
        "src/dmf_pulse/cli/data_model_cmd.py",
        "fixtures/data_model/DAT-003/demo.json",
        "fixtures/data_model/DAT-003/expected_schema.json",
        "alembic.ini",
        "compose.test.yaml",
        "pyproject.toml",
        ".github/workflows/ci.yml",
    ):
        _write(root / relative, f"# {relative}\n")
    _write(root / ".secret-scan-allowlist.json", '{"entries": [], "version": "1.0"}\n')
    current = build_repository_manifest(root, ticket_id="DAT-003")
    _write(
        evidence_root / "current_manifest.json",
        json.dumps(current.model_dump(mode="json")),
    )
    _refresh_dat_evidence_manifest(root)


@pytest.mark.unit
def test_review_pack_refuses_twenty_one_files() -> None:
    entries = [
        ReviewEntry(name=f"{index:02d}.txt", data=b"x", purpose="test") for index in range(21)
    ]
    with pytest.raises(ReviewPackError) as caught:
        enforce_review_limit(entries)
    assert caught.value.code == "REVIEW_PACK_FILE_LIMIT"


@pytest.mark.unit
def test_review_entries_reject_duplicate_and_nested_names() -> None:
    duplicate = [
        ReviewEntry(name="same.txt", data=b"one", purpose="one"),
        ReviewEntry(name="same.txt", data=b"two", purpose="two"),
    ]
    with pytest.raises(ReviewPackError) as duplicate_error:
        enforce_review_limit(duplicate)
    assert duplicate_error.value.code == "REVIEW_PACK_DUPLICATE_NAME"
    with pytest.raises(ReviewPackError) as nested_error:
        enforce_review_limit([ReviewEntry(name="nested/file.txt", data=b"x", purpose="x")])
    assert nested_error.value.code == "REVIEW_PACK_NESTED_PATH"


@pytest.mark.unit
def test_empty_baseline_diff_includes_authored_file_and_omits_lock(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    (tmp_path / ".coverage").write_bytes(b"sqlite\x00generated")
    (tmp_path / "coverage.xml").write_text("<generated/>\n", encoding="utf-8")
    diff, stat = build_empty_baseline_diff(tmp_path)
    assert "+++ b/src/example.py" in diff
    assert "+VALUE = 1" in diff
    assert "uv.lock" not in diff
    assert ".coverage" not in diff
    assert "coverage.xml" not in diff
    assert "uv.lock" in stat


@pytest.mark.unit
def test_diff_rejects_missing_nonempty_and_binary_baselines(tmp_path: Path) -> None:
    with pytest.raises(ReviewPackError) as missing:
        build_empty_baseline_diff(tmp_path)
    assert missing.value.code == "BASELINE_INVALID"

    _write(
        tmp_path / "evidence/tickets/FND-001/baseline_manifest.json",
        json.dumps({"repository_empty": False}),
    )
    with pytest.raises(ReviewPackError) as nonempty:
        build_empty_baseline_diff(tmp_path)
    assert nonempty.value.code == "BASELINE_DIFF_UNSUPPORTED"

    _write(
        tmp_path / "evidence/tickets/FND-001/baseline_manifest.json",
        json.dumps({"repository_empty": True}),
    )
    binary = tmp_path / "src/binary.py"
    binary.parent.mkdir()
    binary.write_bytes(b"text\x00binary")
    with pytest.raises(ReviewPackError) as prohibited:
        build_empty_baseline_diff(tmp_path)
    assert prohibited.value.code == "BINARY_DIFF_PROHIBITED"


@pytest.mark.unit
def test_full_review_pack_build_validates_and_detects_tamper(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture_repository(root)
    digest = calculate_review_payload_digest(
        root, generated_at="2026-07-22T00:00:00Z", process_runner=GitRunner()
    )
    result_path = root / "evidence/tickets/FND-001/codex_result.json"
    result = _codex_result(status="COMPLETE")
    review_reference = result["review_pack"]
    assert isinstance(review_reference, dict)
    review_reference["sha256"] = digest
    result_path.write_text(json.dumps(result), encoding="utf-8")
    output = tmp_path / "output"
    summary = build_review_pack(
        root,
        ticket="FND-001",
        output=output,
        generated_at="2026-07-22T00:00:00Z",
        process_runner=GitRunner(),
    )
    assert summary.file_count == 20
    assert summary.payload_sha256 == digest
    assert summary.path.name == REVIEW_ZIP_NAME
    assert validate_review_zip(summary.path).sha256 == summary.sha256
    with zipfile.ZipFile(summary.path) as archive:
        assert len(archive.namelist()) == 20
        assert all("/" not in name for name in archive.namelist())

    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(summary.path) as source, zipfile.ZipFile(tampered, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            target.writestr(name, data + b"tamper" if name == "16_AGENTS.md" else data)
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(tampered)
    assert caught.value.code in {"REVIEW_MANIFEST_HASH", "REVIEW_CHECKSUM_HASH"}


@pytest.mark.unit
def test_rul_review_pack_has_exact_layout_and_keeps_authored_fixtures_in_patch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _rul_fixture_repository(root)
    runner = RulGitRunner()
    baseline = RUL_REQUIRED_BASELINE
    generated_at = "2026-07-22T00:00:00Z"
    digest = calculate_review_payload_digest(
        root,
        ticket="RUL-002",
        baseline=baseline,
        generated_at=generated_at,
        process_runner=runner,
    )
    result_path = root / "evidence/tickets/RUL-002/codex_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["status"] = "COMPLETE"
    result["review_pack"]["payload_sha256"] = digest
    result_path.write_text(json.dumps(result), encoding="utf-8")
    _refresh_rul_evidence_manifest(root)

    summary = build_review_pack(
        root,
        ticket="RUL-002",
        baseline=baseline,
        output=tmp_path / "output",
        generated_at=generated_at,
        process_runner=runner,
    )

    assert summary.file_count == 20
    assert summary.path.name == RUL_REVIEW_ZIP_NAME
    assert validate_review_zip(summary.path).payload_sha256 == digest
    with zipfile.ZipFile(summary.path) as archive:
        assert tuple(archive.namelist()) == RUL_PREFERRED_NAMES
        assert "reference_2025_26/scoring.yaml" in archive.read("04_FULL_DIFF.patch").decode()
    diff_commands = [command for command in runner.commands if "diff" in command]
    assert diff_commands
    assert all(":(exclude)fixtures/rules/RUL-002/**" not in command for command in diff_commands)


@pytest.mark.unit
def test_dat_review_pack_has_exact_layout_and_complete_evidence(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _dat_fixture_repository(root)
    runner = DatGitRunner()
    generated_at = "2026-07-23T00:00:00Z"
    digest = calculate_review_payload_digest(
        root,
        ticket="DAT-003",
        baseline=DAT_REQUIRED_BASELINE,
        generated_at=generated_at,
        process_runner=runner,
    )
    result_path = root / "evidence/tickets/DAT-003/codex_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["review_pack"]["payload_sha256"] = digest
    result_path.write_text(json.dumps(result), encoding="utf-8")
    _refresh_dat_evidence_manifest(root)

    summary = build_review_pack(
        root,
        ticket="DAT-003",
        baseline=DAT_REQUIRED_BASELINE,
        output=tmp_path / "output",
        generated_at=generated_at,
        process_runner=runner,
    )

    assert summary.file_count == 20
    assert summary.path.name == DAT_REVIEW_ZIP_NAME
    assert validate_review_zip(summary.path).payload_sha256 == digest
    with zipfile.ZipFile(summary.path) as archive:
        assert tuple(archive.namelist()) == DAT_PREFERRED_NAMES
        contracts = archive.read("17_DATA_MODEL_PUBLIC_CONTRACTS_MODELS.txt").decode()
        assert "fixtures/data_model/DAT-003/demo.json" in contracts
        migration = archive.read("18_INITIAL_MIGRATION_CRITICAL_SQL.txt").decode()
        assert "20260723_0001_dat003_foundation.py" in migration
    diff_commands = [command for command in runner.commands if "diff" in command]
    assert diff_commands
    assert all(":(exclude)src/dmf_pulse/data_model/**" not in command for command in diff_commands)


@pytest.mark.unit
def test_dat_review_rejects_baseline_and_git_state_false_successes(tmp_path: Path) -> None:
    with pytest.raises(ReviewPackError) as baseline:
        review_pack_module._dat_baseline_diff(tmp_path, "0" * 40, DatGitRunner())
    assert baseline.value.code == "BASELINE_INVALID"

    cases = (
        (DatStateRunner(branch="wrong"), "REVIEW_BRANCH_INVALID"),
        (DatStateRunner(head="not-a-commit"), "REVIEW_HEAD_INVALID"),
        (DatStateRunner(merges="a" * 40), "REVIEW_HISTORY_INVALID"),
        (DatStateRunner(dirty=" M source.py"), "REVIEW_TREE_DIRTY"),
    )
    for runner, code in cases:
        with pytest.raises(ReviewPackError) as caught:
            review_pack_module._required_dat_git_state(tmp_path, DAT_REQUIRED_BASELINE, runner)
        assert caught.value.code == code


@pytest.mark.unit
def test_dat_review_rejects_malformed_machine_evidence_and_command_set(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(ReviewPackError) as malformed_error:
        review_pack_module._dat_json_object(malformed)
    assert malformed_error.value.code == "REVIEW_EVIDENCE_INVALID"

    malformed.write_text("[]", encoding="utf-8")
    with pytest.raises(ReviewPackError) as scalar_error:
        review_pack_module._dat_json_object(malformed)
    assert scalar_error.value.code == "REVIEW_EVIDENCE_INVALID"

    root = tmp_path / "repository"
    root.mkdir()
    _dat_fixture_repository(root)
    result_value = json.loads(
        (root / "evidence/tickets/DAT-003/codex_result.json").read_text(encoding="utf-8")
    )
    result_value["commands"] = result_value["commands"][:1]
    result = review_pack_module.CodexResult.model_validate(result_value)
    with pytest.raises(ReviewPackError) as command_error:
        review_pack_module._validate_dat_complete_evidence(root, result, "a" * 40)
    assert command_error.value.code == "REVIEW_ACCEPTANCE_INVALID"


@pytest.mark.unit
def test_complete_rul_review_rejects_incomplete_command_evidence(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _rul_fixture_repository(root)
    result_path = root / "evidence/tickets/RUL-002/codex_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["status"] = "COMPLETE"
    result["commands"] = result["commands"][:1]
    result_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="RUL-002",
            baseline=RUL_REQUIRED_BASELINE,
            output=tmp_path / "output",
            generated_at="2026-07-22T00:00:00Z",
            process_runner=RulGitRunner(),
        )
    assert caught.value.code == "REVIEW_ACCEPTANCE_INVALID"


@pytest.mark.unit
def test_complete_rul_review_rejects_traversal_evidence_artifact(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _rul_fixture_repository(root)
    result_path = root / "evidence/tickets/RUL-002/codex_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["status"] = "COMPLETE"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    _refresh_rul_evidence_manifest(root)
    manifest_path = root / "evidence/tickets/RUL-002/evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].append(
        {
            "bytes": 0,
            "path": "evidence/tickets/RUL-002/../../outside.txt",
            "sha256": "0" * 64,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="RUL-002",
            baseline=RUL_REQUIRED_BASELINE,
            output=tmp_path / "output",
            generated_at="2026-07-22T00:00:00Z",
            process_runner=RulGitRunner(),
        )
    assert caught.value.code == "REVIEW_EVIDENCE_INVALID"


@pytest.mark.unit
def test_builder_rejects_ticket_and_repository_secret(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture_repository(root)
    with pytest.raises(ReviewPackError) as ticket_error:
        build_review_pack(
            root,
            ticket="OTHER",
            output=tmp_path / "out",
            generated_at="2026-07-22T00:00:00Z",
            process_runner=GitRunner(),
        )
    assert ticket_error.value.code == "REVIEW_TICKET_UNSUPPORTED"

    _write(root / "leak.txt", "token=" + "ghp_" + "FakeCredentialValue987654321")
    with pytest.raises(ReviewPackError) as secret_error:
        build_review_pack(
            root,
            ticket="FND-001",
            output=tmp_path / "out",
            generated_at="2026-07-22T00:00:00Z",
            process_runner=GitRunner(),
        )
    assert secret_error.value.code == "REPOSITORY_SECRET"


@pytest.mark.unit
def test_complete_pack_rejects_wrong_primary_payload_digest(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture_repository(root)
    result_path = root / "evidence/tickets/FND-001/codex_result.json"
    result_path.write_text(json.dumps(_codex_result(status="COMPLETE")), encoding="utf-8")
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="FND-001",
            output=tmp_path / "out",
            generated_at="2026-07-22T00:00:00Z",
            process_runner=GitRunner(),
        )
    assert caught.value.code == "REVIEW_PAYLOAD_DIGEST"


@pytest.mark.unit
def test_bad_zip_checksum_parser_and_error_object(tmp_path: Path) -> None:
    with pytest.raises(ReviewPackError) as invalid_zip:
        validate_review_zip(tmp_path / "missing.zip")
    assert invalid_zip.value.code == "REVIEW_ZIP_INVALID"
    assert invalid_zip.value.as_error_object()["ok"] is False

    with pytest.raises(ReviewPackError) as malformed:
        review_pack_module._parse_checksums("bad-line")
    assert malformed.value.code == "REVIEW_CHECKSUM_FORMAT"
    digest = "0" * 64
    with pytest.raises(ReviewPackError) as duplicate:
        review_pack_module._parse_checksums(f"{digest}  same.txt\n{digest}  same.txt\n")
    assert duplicate.value.code == "REVIEW_CHECKSUM_DUPLICATE"


@pytest.mark.unit
def test_zip_over_limit_and_layout_fail_before_metadata(tmp_path: Path) -> None:
    over = tmp_path / "over.zip"
    with zipfile.ZipFile(over, "w") as archive:
        for index in range(21):
            archive.writestr(f"{index}.txt", "x")
    with pytest.raises(ReviewPackError) as over_error:
        validate_review_zip(over)
    assert over_error.value.code == "REVIEW_PACK_FILE_LIMIT"

    layout = tmp_path / "layout.zip"
    with zipfile.ZipFile(layout, "w") as archive:
        archive.writestr("wrong.txt", "x")
    with pytest.raises(ReviewPackError) as layout_error:
        validate_review_zip(layout)
    assert layout_error.value.code == "REVIEW_PACK_LAYOUT"


@pytest.mark.unit
def test_git_and_small_review_helper_failure_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_pack_module.shutil, "which", lambda _name: None)
    assert review_pack_module._run_git(tmp_path, ["status"], GitRunner()) == "git unavailable\n"

    monkeypatch.setattr(review_pack_module.shutil, "which", lambda _name: "git")
    timed_out = OneResultRunner(ProcessResult(return_code=None, timed_out=True))
    assert "timed out" in review_pack_module._run_git(tmp_path, ["status"], timed_out)
    failed = OneResultRunner(ProcessResult(return_code=1))
    assert "failed" in review_pack_module._run_git(tmp_path, ["status"], failed)
    invalid_head = OneResultRunner(ProcessResult(return_code=0, stdout="not-a-head\n"))
    assert review_pack_module._repository_head(tmp_path, invalid_head) == "UNAVAILABLE"

    with pytest.raises(ReviewPackError) as missing:
        review_pack_module._required_text(tmp_path, "missing.txt")
    assert missing.value.code == "REVIEW_SOURCE_MISSING"
    assert review_pack_module._entry("x", "no-newline", "test").data.endswith(b"\n")
    with pytest.raises(ReviewPackError) as incomplete:
        review_pack_module._primary_payload_digest({})
    assert incomplete.value.code == "REVIEW_PRIMARY_PAYLOAD"


@pytest.mark.unit
def test_required_git_capture_does_not_use_diagnostic_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"x" * 8192

    def fake_run(command, *, stdout, stderr, check, shell, timeout):
        del command, stderr
        assert check is False and shell is False and timeout == 30.0
        stdout.write(payload)
        return review_pack_module.subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(review_pack_module.shutil, "which", lambda _name: "git")
    monkeypatch.setattr(review_pack_module.subprocess, "run", fake_run)
    value = review_pack_module._required_git(
        tmp_path,
        ["diff"],
        SubprocessProcessRunner(),
        code="TEST_GIT",
    )
    assert value == payload.decode("utf-8")
