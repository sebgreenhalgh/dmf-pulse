"""FPL-004 evidence, exact review layout, privacy, and manifest false-success tests."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from dmf_pulse.assurance.evidence import (
    FPL_DETACHED_REVIEW_NAMES,
    FPL_REQUIRED_BASELINE,
    FPL_REQUIRED_BRANCH,
    CodexResult,
    EvidenceValidationError,
    validate_ticket_evidence,
)
from dmf_pulse.assurance.review_pack import (
    FPL_MANDATORY_ACCEPTANCE_COMMANDS,
    FPL_PREFERRED_NAMES,
    FPL_REVIEW_FINAL_RESULT,
    FPL_REVIEW_ZIP_NAME,
    FPL_TEARDOWN_FINAL_RESULT,
    ReviewPackError,
    _parse_fpl_command_log,
    _validate_fpl_complete_evidence,
    build_review_pack,
    validate_review_zip,
)
from dmf_pulse.system.process import ProcessResult


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_rehashed_fpl_zip(payload: dict[str, bytes], target_path: Path) -> None:
    manifest = json.loads(payload["19_ARCHIVE_MANIFEST.json"])
    result = json.loads(payload["18_CODEX_RESULT.json"])
    manifest["acceptance_status"] = result["status"]
    for entry in manifest["files"]:
        name = entry["name"]
        entry["bytes"] = len(payload[name])
        entry["sha256"] = hashlib.sha256(payload[name]).hexdigest()
    payload["19_ARCHIVE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
    payload["20_SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(payload[name]).hexdigest()}  {name}\n"
        for name in sorted(payload)
        if name != "20_SHA256SUMS.txt"
    ).encode()
    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name in FPL_PREFERRED_NAMES:
            target.writestr(name, payload[name])


class FplGitRunner:
    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        assert timeout_seconds in {5, 30}
        assert ":(exclude)evidence/tickets/FPL-004/**" not in command
        if "--abbrev-ref" in command:
            return ProcessResult(return_code=0, stdout=FPL_REQUIRED_BRANCH + "\n")
        if "rev-parse" in command:
            return ProcessResult(return_code=0, stdout="a" * 40 + "\n")
        if "--merges" in command or "--porcelain=v1" in command or "merge-base" in command:
            return ProcessResult(return_code=0, stdout="")
        if "--stat" in command:
            return ProcessResult(return_code=0, stdout="2 files changed, 4 insertions(+)\n")
        if "--name-status" in command:
            return ProcessResult(return_code=0, stdout="A\tconfig/rights/fpl_profiles.json\n")
        if "diff" in command:
            return ProcessResult(
                return_code=0,
                stdout=(
                    "diff --git a/config/rights/fpl_profiles.json b/config/rights/fpl_profiles.json\n"
                    "+account_scope: Sebastian approved private context only\n"
                    "diff --git a/evidence/tickets/FPL-004/PLAN.md "
                    "b/evidence/tickets/FPL-004/PLAN.md\n"
                    "+Final acceptance remains pending.\n"
                ),
            )
        return ProcessResult(return_code=0, stdout="")


class FplRawMarkerRunner(FplGitRunner):
    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        if "diff" in command and "--stat" not in command and "--name-status" not in command:
            marker = "RAW_BODY_" + "MUST_NOT_SURVIVE_FPL004"
            return ProcessResult(return_code=0, stdout=f"diff --git a/x b/x\n+{marker}\n")
        return super().run(command, timeout_seconds=timeout_seconds)


def _review_result(
    *, status: str = "FAILED", commands: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "ticket_id": "FPL-004",
        "status": status,
        "code_commit": "a" * 40,
        "summary": "FPL fixture result.",
        "files_changed": [{"path": "src/example.py", "change": "A"}],
        "public_interfaces": ["dmf ingest fpl validate"],
        "commands": commands or [],
        "tests": [],
        "acceptance": [],
        "dependency_impact": "none",
        "migration_impact": "one revision",
        "assumptions": [],
        "exclusions_verified": ["no live request"],
        "risks": ["fixture"],
        "repository": {
            "baseline": FPL_REQUIRED_BASELINE,
            "branch": FPL_REQUIRED_BRANCH,
            "clean": True,
            "head": "a" * 40,
            "merged": False,
            "pushed": False,
        },
        "review_pack": {
            "path": "review_pack/FPL-004/DMF_PULSE_FPL-004_REVIEW.zip",
            "file_count": 20,
            "payload_sha256": "0" * 64,
        },
    }


def _review_fixture(root: Path) -> None:
    evidence = root / "evidence/tickets/FPL-004"
    _write(evidence / "codex_result.json", json.dumps(_review_result()))
    _write(evidence / "commands.log", "")
    for name in (
        "PUBLIC_CONTRACTS.md",
        "MIGRATION_SCHEMA_REVIEW.md",
        "SOURCE_LIFECYCLE_RESUME.md",
        "RIGHTS_RETENTION_REVIEW.md",
        "TEST_COVERAGE_MUTATION.md",
        "ACCEPTANCE.md",
        "DAT003_REMEDIATION.md",
        "FPL_SCHEMA_MAPPING_IDEMPOTENCY.md",
        "SOURCE_BUNDLE_CUTOFF_QUALITY.md",
        "DEPENDENCY_LOCK_PACKAGE.md",
        "SECURITY_AND_SECRET_REVIEW.md",
        "KNOWN_LIMITATIONS.md",
    ):
        _write(evidence / name, f"# {name}\n\nFixture.\n")
    _write(root / "uv.lock", "version = 1\n")
    _write(root / "fixtures/manifest.json", "{}\n")
    _write(
        root / "src/dmf_pulse/database/migrations/versions/20260724_0002_fpl004_ingestion.py",
        "revision = 'fixture'\n",
    )
    _write(root / ".secret-scan-allowlist.json", '{"entries": [], "version": "1.0"}\n')


@pytest.mark.unit
def test_fpl_review_pack_exact_layout_redacts_personal_owner_and_validates(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _review_fixture(root)
    summary = build_review_pack(
        root,
        ticket="FPL-004",
        baseline=FPL_REQUIRED_BASELINE,
        output=tmp_path / "out",
        generated_at="2026-07-24T00:00:00Z",
        process_runner=FplGitRunner(),
    )
    assert summary.file_count == 20
    assert summary.path.name == FPL_REVIEW_ZIP_NAME
    assert validate_review_zip(summary.path).payload_sha256 == summary.payload_sha256
    with zipfile.ZipFile(summary.path) as archive:
        assert tuple(archive.namelist()) == FPL_PREFERRED_NAMES
        patch = archive.read("03_COMPLETE_HUMAN_PATCH.diff").decode()
        assert "<REDACTED_OWNER>" in patch
        assert "Sebastian" not in patch
        assert "evidence/tickets/FPL-004/PLAN.md" in patch
        manifest = json.loads(archive.read("19_ARCHIVE_MANIFEST.json"))
        assert {item["name"] for item in manifest["files"]} == FPL_DETACHED_REVIEW_NAMES


@pytest.mark.unit
def test_detached_validator_rejects_rehashed_false_complete_write_ahead_zip(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _review_fixture(root)
    summary = build_review_pack(
        root,
        ticket="FPL-004",
        baseline=FPL_REQUIRED_BASELINE,
        output=tmp_path / "out",
        generated_at="2026-07-24T00:00:00Z",
        process_runner=FplGitRunner(),
    )
    with zipfile.ZipFile(summary.path) as source:
        payload = {name: source.read(name) for name in source.namelist()}

    records = _complete_records()
    records[23]["duration_seconds"] = None
    records[23]["result"] = (
        "PASS: write-ahead record committed only by successful external archive "
        "finalization; exact duration and digests are in archive_finalization.json"
    )
    records[24]["duration_seconds"] = None
    records[24]["result"] = (
        "PASS: finally-guaranteed PostgreSQL teardown pending; exact duration and result "
        "are in archive_finalization.json"
    )
    acceptance = [
        {
            "command": record["command"],
            "duration_seconds": record["duration_seconds"],
            "exit_code": record["exit_code"],
            "expected_exit_code": 4 if index == 20 else 0,
            "status": "PASS",
        }
        for index, record in enumerate(records, start=1)
    ]
    result = json.loads(payload["18_CODEX_RESULT.json"])
    result["status"] = "COMPLETE"
    result["commands"] = records
    result["acceptance"] = acceptance
    result["review_pack"]["payload_sha256"] = summary.payload_sha256
    payload["18_CODEX_RESULT.json"] = json.dumps(result, indent=2).encode()

    false_complete = tmp_path / "false-complete.zip"
    _write_rehashed_fpl_zip(payload, false_complete)

    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(false_complete)
    assert caught.value.code == "REVIEW_ACCEPTANCE_INVALID"


@pytest.mark.unit
def test_detached_validator_rejects_valid_complete_result_with_empty_command_log(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _review_fixture(root)
    summary = build_review_pack(
        root,
        ticket="FPL-004",
        baseline=FPL_REQUIRED_BASELINE,
        output=tmp_path / "out",
        generated_at="2026-07-24T00:00:00Z",
        process_runner=FplGitRunner(),
    )
    with zipfile.ZipFile(summary.path) as source:
        payload = {name: source.read(name) for name in source.namelist()}

    records = _complete_records()
    acceptance = [
        {
            "command": record["command"],
            "duration_seconds": record["duration_seconds"],
            "exit_code": record["exit_code"],
            "expected_exit_code": 4 if index == 20 else 0,
            "status": "PASS",
        }
        for index, record in enumerate(records, start=1)
    ]
    result = json.loads(payload["18_CODEX_RESULT.json"])
    result["status"] = "COMPLETE"
    result["commands"] = records
    result["acceptance"] = acceptance
    result["review_pack"]["payload_sha256"] = summary.payload_sha256
    payload["18_CODEX_RESULT.json"] = json.dumps(result, indent=2).encode()
    assert payload["17_COMMANDS_AND_RESULTS.log"].strip() == b""

    false_complete = tmp_path / "false-complete-empty-log.zip"
    _write_rehashed_fpl_zip(payload, false_complete)

    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(false_complete)
    assert caught.value.code == "REVIEW_ACCEPTANCE_INVALID"


@pytest.mark.unit
@pytest.mark.parametrize(
    "command_log",
    [
        (
            b'{"command":"first","command":"second","duration_seconds":0.1,'
            b'"exit_code":0,"result":"PASS: fixture"}\n'
        ),
        (b'{"command":"fixture","duration_seconds":true,"exit_code":0,"result":"PASS: fixture"}\n'),
    ],
)
def test_detached_command_log_rejects_ambiguous_or_nonstrict_json(
    command_log: bytes,
) -> None:
    with pytest.raises(ReviewPackError) as caught:
        _parse_fpl_command_log(command_log)
    assert caught.value.code == "REVIEW_ACCEPTANCE_INVALID"


@pytest.mark.unit
def test_fpl_review_validator_rejects_personal_data_even_with_valid_zip_shape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _review_fixture(root)
    summary = build_review_pack(
        root,
        ticket="FPL-004",
        baseline=FPL_REQUIRED_BASELINE,
        output=tmp_path / "out",
        generated_at="2026-07-24T00:00:00Z",
        process_runner=FplGitRunner(),
    )
    tampered = tmp_path / "personal.zip"
    with zipfile.ZipFile(summary.path) as source, zipfile.ZipFile(tampered, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "01_REVIEW_INDEX.md":
                data += b"Sebastian\n"
            target.writestr(name, data)
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(tampered)
    assert caught.value.code == "REVIEW_PACK_PERSONAL_DATA"


@pytest.mark.unit
def test_fpl_review_assembly_rejects_raw_body_canary_in_complete_patch(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _review_fixture(root)

    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="FPL-004",
            baseline=FPL_REQUIRED_BASELINE,
            output=tmp_path / "out",
            generated_at="2026-07-24T00:00:00Z",
            process_runner=FplRawMarkerRunner(),
        )

    assert caught.value.code == "REVIEW_PACK_RAW_PAYLOAD"


def _complete_records() -> list[dict[str, object]]:
    records = []
    for index, command in enumerate(FPL_MANDATORY_ACCEPTANCE_COMMANDS, start=1):
        result = "PASS: fixture"
        exit_code = 0
        if index == 20:
            exit_code = 4
            result = "PASS: RIGHTS_BLOCKED with zero transport calls"
        elif index == 24:
            result = FPL_REVIEW_FINAL_RESULT
        elif index == 25:
            result = FPL_TEARDOWN_FINAL_RESULT
        records.append(
            {
                "command": command,
                "duration_seconds": 0.1,
                "exit_code": exit_code,
                "result": result,
            }
        )
    return records


def _complete_evidence(root: Path) -> CodexResult:
    evidence = root / "evidence/tickets/FPL-004"
    records = _complete_records()
    acceptance = [
        {
            "command": record["command"],
            "duration_seconds": record["duration_seconds"],
            "exit_code": record["exit_code"],
            "expected_exit_code": 4 if index == 20 else 0,
            "status": "PASS",
        }
        for index, record in enumerate(records, start=1)
    ]
    tests = {
        "critical_deterministic_branch_coverage_percent": 96.0,
        "critical_deterministic_branches_covered": 96,
        "critical_deterministic_branches_total": 100,
        "critical_oracles": [f"oracle-{index}" for index in range(8)],
        "cutoff_branch_coverage_percent": 100.0,
        "cutoff_branches_covered": 8,
        "cutoff_branches_total": 8,
        "cutoff_oracles": [
            "persistence.py:1 - post-cutoff bundle member is rejected",
            "service.py:2 - only POST_CUTOFF is converted to an observed non-bundle outcome",
            "service.py:3 - post-cutoff evidence requires exactly one blocker",
            "service.py:4 - post-cutoff issue publication is idempotent",
        ],
        "failed": 0,
        "ingestion_package_branch_coverage_percent": 85.0,
        "ingestion_package_branches_covered": 85,
        "ingestion_package_branches_total": 100,
        "mutation_method": "boundary negative controls",
        "overall_branch_coverage_percent": 86.0,
        "overall_branches_covered": 86,
        "overall_branches_total": 100,
        "passed": 100,
        "provider_adapter_branch_coverage_percent": 85.0,
        "provider_adapter_branches_covered": 85,
        "provider_adapter_branches_total": 100,
        "repository_combined_coverage_percent": 91.0,
        "repository_combined_units_covered": 91,
        "repository_combined_units_total": 100,
        "rights_branch_coverage_percent": 94.0,
        "rights_branches_covered": 94,
        "rights_branches_total": 100,
        "skipped": 0,
        "status": "PASS",
    }
    value = _review_result(status="COMPLETE", commands=records)
    value["tests"] = [tests]
    value["acceptance"] = acceptance
    result = CodexResult.model_validate(value)
    _write(evidence / "commands.log", "".join(json.dumps(item) + "\n" for item in records))
    _write(evidence / "tests.json", json.dumps(tests))
    _write(
        evidence / "acceptance_matrix.json",
        json.dumps(
            {
                "ticket_id": "FPL-004",
                "status": "COMPLETE",
                "passed": 25,
                "failed": 0,
                "commands": acceptance,
            }
        ),
    )
    for name in ("migration_matrix.json", "package_report.json", "acceptance_verification.json"):
        _write(evidence / name, '{"status":"PASS"}\n')
    _write(evidence / "codex_result.json", result.model_dump_json())
    artifacts = []
    for path in sorted(evidence.iterdir(), key=lambda item: item.name):
        if path.name == "evidence_manifest.json":
            continue
        artifacts.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha(path),
            }
        )
    _write(
        evidence / "evidence_manifest.json",
        json.dumps(
            {
                "ticket_id": "FPL-004",
                "status": "COMPLETE",
                "created_at": "2026-07-24T00:00:00Z",
                "code_commit": "a" * 40,
                "commands": records,
                "artifacts": artifacts,
            }
        ),
    )
    return result


@pytest.mark.unit
def test_complete_fpl_evidence_validates_exact_commands_coverage_and_hashes(tmp_path: Path) -> None:
    result = _complete_evidence(tmp_path)
    manifest = validate_ticket_evidence(tmp_path, "FPL-004")
    assert manifest.status == "COMPLETE"
    _validate_fpl_complete_evidence(tmp_path, result, "a" * 40)


@pytest.mark.unit
def test_ticket_evidence_rejects_hash_coverage_and_path_false_successes(tmp_path: Path) -> None:
    _complete_evidence(tmp_path)
    manifest_path = tmp_path / "evidence/tickets/FPL-004/evidence_manifest.json"
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    value["artifacts"][0]["sha256"] = "0" * 64
    _write(manifest_path, json.dumps(value))
    with pytest.raises(EvidenceValidationError) as mismatch:
        validate_ticket_evidence(tmp_path, "FPL-004")
    assert mismatch.value.code == "EVIDENCE_ARTIFACT_MISMATCH"

    _complete_evidence(tmp_path)
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    value["artifacts"].pop()
    _write(manifest_path, json.dumps(value))
    with pytest.raises(EvidenceValidationError) as coverage:
        validate_ticket_evidence(tmp_path, "FPL-004")
    assert coverage.value.code == "EVIDENCE_ARTIFACT_COVERAGE"

    _complete_evidence(tmp_path)
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    value["artifacts"][0]["path"] = "evidence/tickets/FPL-004/../escape.json"
    _write(manifest_path, json.dumps(value))
    with pytest.raises(EvidenceValidationError) as path_error:
        validate_ticket_evidence(tmp_path, "FPL-004")
    assert path_error.value.code in {"EVIDENCE_ARTIFACT_COVERAGE", "EVIDENCE_ARTIFACT_PATH"}


@pytest.mark.unit
def test_complete_fpl_evidence_rejects_command_false_success(tmp_path: Path) -> None:
    result = _complete_evidence(tmp_path)
    bad_value = result.model_dump(mode="json")
    bad_value["commands"] = bad_value["commands"][:-1]
    with pytest.raises(ReviewPackError) as commands:
        _validate_fpl_complete_evidence(tmp_path, CodexResult.model_validate(bad_value), "a" * 40)
    assert commands.value.code == "REVIEW_ACCEPTANCE_INVALID"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("percent_key", "covered_key", "bad_percent", "bad_covered"),
    [
        ("repository_combined_coverage_percent", "repository_combined_units_covered", 89.0, 89),
        (
            "critical_deterministic_branch_coverage_percent",
            "critical_deterministic_branches_covered",
            94.0,
            94,
        ),
        ("rights_branch_coverage_percent", "rights_branches_covered", 89.0, 89),
        (
            "provider_adapter_branch_coverage_percent",
            "provider_adapter_branches_covered",
            74.0,
            74,
        ),
        ("cutoff_branch_coverage_percent", "cutoff_branches_covered", 87.5, 7),
    ],
)
def test_complete_fpl_evidence_rejects_each_tiered_coverage_false_success(
    tmp_path: Path,
    percent_key: str,
    covered_key: str,
    bad_percent: float,
    bad_covered: int,
) -> None:
    result = _complete_evidence(tmp_path)
    tests_path = tmp_path / "evidence/tickets/FPL-004/tests.json"
    tests = json.loads(tests_path.read_text(encoding="utf-8"))
    tests[percent_key] = bad_percent
    tests[covered_key] = bad_covered
    _write(tests_path, json.dumps(tests))
    value = result.model_dump(mode="json")
    value["tests"] = [tests]
    with pytest.raises(ReviewPackError) as coverage:
        _validate_fpl_complete_evidence(
            tmp_path,
            CodexResult.model_validate(value),
            "a" * 40,
        )
    assert coverage.value.code == "REVIEW_EVIDENCE_INVALID"


@pytest.mark.unit
def test_complete_fpl_evidence_rejects_coverage_count_mismatch(tmp_path: Path) -> None:
    result = _complete_evidence(tmp_path)
    tests_path = tmp_path / "evidence/tickets/FPL-004/tests.json"
    tests = json.loads(tests_path.read_text(encoding="utf-8"))
    tests["rights_branches_covered"] = 93
    _write(tests_path, json.dumps(tests))
    value = result.model_dump(mode="json")
    value["tests"] = [tests]
    with pytest.raises(ReviewPackError) as coverage:
        _validate_fpl_complete_evidence(
            tmp_path,
            CodexResult.model_validate(value),
            "a" * 40,
        )
    assert coverage.value.code == "REVIEW_EVIDENCE_INVALID"


@pytest.mark.unit
def test_complete_fpl_result_rejects_legacy_pass_prefixed_pending_teardown(
    tmp_path: Path,
) -> None:
    result = _complete_evidence(tmp_path)
    value = result.model_dump(mode="json")
    value["commands"][24]["result"] = (
        "PASS: finally-guaranteed PostgreSQL teardown pending; exact duration and result "
        "are in archive_finalization.json"
    )
    with pytest.raises(ReviewPackError) as caught:
        _validate_fpl_complete_evidence(
            tmp_path,
            CodexResult.model_validate(value),
            "a" * 40,
        )
    assert caught.value.code == "REVIEW_ACCEPTANCE_INVALID"
