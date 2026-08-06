"""NRM-006 evidence provenance and capped review-pack contract tests."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from dmf_pulse.assurance.evidence import (
    NRM_REQUIRED_BASELINE,
    NRM_REQUIRED_BRANCH,
    CodexResult,
)
from dmf_pulse.assurance.review_pack import (
    NRM_MANDATORY_ACCEPTANCE_COMMANDS,
    NRM_PACK_MANIFEST_SHA256,
    NRM_PREFERRED_NAMES,
    NRM_REVIEW_FINAL_RESULT,
    NRM_REVIEW_ZIP_NAME,
    NRM_TEARDOWN_FINAL_RESULT,
    ReviewPackError,
    ReviewPackSummary,
    _validate_nrm_complete_evidence,
    _validate_nrm_complete_result,
    build_review_pack,
    calculate_review_payload_digest,
    validate_review_zip,
)
from dmf_pulse.cli.app import app
from dmf_pulse.system.process import ProcessResult

HEAD = "a" * 40


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NrmGitRunner:
    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        assert timeout_seconds in {5, 30}
        if "--abbrev-ref" in command:
            return ProcessResult(return_code=0, stdout=NRM_REQUIRED_BRANCH + "\n")
        if "rev-parse" in command:
            return ProcessResult(return_code=0, stdout=HEAD + "\n")
        if "--merges" in command or "--porcelain=v1" in command or "merge-base" in command:
            return ProcessResult(return_code=0, stdout="")
        if "--stat" in command:
            return ProcessResult(return_code=0, stdout="2 files changed, 4 insertions(+)\n")
        if "--name-status" in command:
            return ProcessResult(
                return_code=0, stdout="A\tsrc/dmf_pulse/markets/normalisation.py\n"
            )
        if "diff" in command:
            return ProcessResult(
                return_code=0,
                stdout=(
                    "diff --git a/src/dmf_pulse/markets/normalisation.py "
                    "b/src/dmf_pulse/markets/normalisation.py\n"
                    "+decimal_context_precision = 60\n"
                ),
            )
        return ProcessResult(return_code=0, stdout="")


class NrmBranchRunner(NrmGitRunner):
    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        if "--abbrev-ref" in command:
            return ProcessResult(return_code=0, stdout="wrong-branch\n")
        return super().run(command, timeout_seconds=timeout_seconds)


class NrmStateRunner(NrmGitRunner):
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        if self.mode == "head" and "rev-parse" in command and "--abbrev-ref" not in command:
            return ProcessResult(return_code=0, stdout="not-a-commit\n")
        if (
            self.mode == "different_head"
            and "rev-parse" in command
            and "--abbrev-ref" not in command
        ):
            return ProcessResult(return_code=0, stdout="b" * 40 + "\n")
        if self.mode == "ancestry" and "merge-base" in command:
            return ProcessResult(return_code=1, stdout="")
        if self.mode == "merge" and "--merges" in command:
            return ProcessResult(return_code=0, stdout="b" * 40 + "\n")
        if self.mode == "dirty" and "--porcelain=v1" in command:
            return ProcessResult(return_code=0, stdout=" M src/example.py\n")
        if self.mode == "diff" and "diff" in command:
            return ProcessResult(return_code=1, stdout="")
        return super().run(command, timeout_seconds=timeout_seconds)


class NrmUnsafeDiffRunner(NrmGitRunner):
    def __init__(self, value: str) -> None:
        self.value = value

    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        if "diff" in command and "--stat" not in command and "--name-status" not in command:
            return ProcessResult(return_code=0, stdout=f"diff --git a/x b/x\n+{self.value}\n")
        return super().run(command, timeout_seconds=timeout_seconds)


def _result() -> dict[str, object]:
    return {
        "acceptance": [],
        "assumptions": [],
        "code_commit": HEAD,
        "commands": [],
        "dependency_impact": "no dependency expansion",
        "exclusions_verified": ["no live provider request"],
        "files_changed": [{"change": "A", "path": "src/example.py"}],
        "migration_impact": "one ordered PostgreSQL revision",
        "public_interfaces": ["dmf market normalise"],
        "repository": {
            "baseline": NRM_REQUIRED_BASELINE,
            "branch": NRM_REQUIRED_BRANCH,
            "clean": True,
            "head": HEAD,
            "merged": False,
            "pushed": False,
        },
        "review_pack": {
            "file_count": 20,
            "path": "review_pack/NRM-006/DMF_PULSE_NRM-006_REVIEW.zip",
            "payload_sha256": "0" * 64,
        },
        "risks": ["synthetic incomplete evidence"],
        "status": "FAILED",
        "summary": "Synthetic NRM review fixture.",
        "tests": [],
        "ticket_id": "NRM-006",
    }


def _complete_result(tests: dict[str, object] | None = None) -> dict[str, object]:
    value = _result()
    records = [
        {
            "command": command,
            "duration_seconds": 0.1,
            "exit_code": 0,
            "result": (
                NRM_REVIEW_FINAL_RESULT
                if index == 31
                else NRM_TEARDOWN_FINAL_RESULT
                if index == 32
                else "PASS: synthetic acceptance proof"
            ),
        }
        for index, command in enumerate(NRM_MANDATORY_ACCEPTANCE_COMMANDS, start=1)
    ]
    value.update(
        {
            "acceptance": [
                {
                    "command": record["command"],
                    "duration_seconds": record["duration_seconds"],
                    "exit_code": 0,
                    "expected_exit_code": 0,
                    "status": "PASS",
                }
                for record in records
            ],
            "commands": records,
            "risks": [],
            "status": "COMPLETE",
            "tests": [tests] if tests is not None else [],
        }
    )
    return value


def _complete_tests() -> dict[str, object]:
    return {
        "critical_branch_coverage_percent": 95.0,
        "critical_oracles": [f"nrm-oracle-{index:02d}" for index in range(1, 11)],
        "failed": 0,
        "math_branch_coverage_percent": 100.0,
        "overall_branch_coverage_percent": 90.0,
        "passed": 100,
        "skipped": 0,
        "status": "PASS",
    }


def _refresh_evidence_manifest(
    root: Path,
    records: list[dict[str, object]],
    *,
    context_hash: str = NRM_PACK_MANIFEST_SHA256,
    known_limitations: list[str] | None = None,
) -> None:
    evidence = root / "evidence/tickets/NRM-006"
    artifacts = [
        {
            "bytes": path.stat().st_size,
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path),
        }
        for path in sorted(evidence.iterdir(), key=lambda item: item.name)
        if path.is_file() and path.name != "evidence_manifest.json"
    ]
    _write(
        evidence / "evidence_manifest.json",
        json.dumps(
            {
                "artifacts": artifacts,
                "code_commit": HEAD,
                "commands": records,
                "context_hash": context_hash,
                "created_at": "2026-08-06T00:00:00Z",
                "known_limitations": known_limitations or [],
                "status": "COMPLETE",
                "ticket_id": "NRM-006",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _complete_evidence(root: Path) -> tuple[CodexResult, list[dict[str, object]]]:
    _fixture(root)
    evidence = root / "evidence/tickets/NRM-006"
    tests = _complete_tests()
    result_value = _complete_result(tests)
    raw_records = result_value["commands"]
    raw_acceptance = result_value["acceptance"]
    assert isinstance(raw_records, list)
    assert isinstance(raw_acceptance, list)
    records = [dict(item) for item in raw_records]
    _write(evidence / "commands.log", "".join(json.dumps(item) + "\n" for item in records))
    _write(evidence / "tests.json", json.dumps(tests, indent=2, sort_keys=True) + "\n")
    _write(
        evidence / "acceptance_matrix.json",
        json.dumps(
            {
                "commands": raw_acceptance,
                "failed": 0,
                "passed": 32,
                "status": "COMPLETE",
                "ticket_id": "NRM-006",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _write(
        evidence / "migration_matrix.json",
        json.dumps(
            {
                "baseline_revision": "20260725_0004",
                "database": {"postgres_version": "18.4"},
                "matrix": [
                    {"from": "base", "status": "PASS", "to": "20260803_0005"},
                    {"from": "20260803_0005", "status": "PASS", "to": "20260725_0004"},
                    {"from": "20260725_0004", "status": "PASS", "to": "20260803_0005"},
                ],
                "metadata_drift_check": "PASS",
                "offline_sql": {
                    "path": "evidence/tickets/NRM-006/offline_upgrade.sql",
                    "secret_free": True,
                },
                "revision_count": 1,
                "revisions": ["20260803_0005"],
                "schema": {"alembic_revision": "20260803_0005", "schema_sha256": "b" * 64},
                "status": "PASS",
                "target_revision": "20260803_0005",
                "ticket_id": "NRM-006",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _write(evidence / "offline_upgrade.sql", "-- synthetic secret-free SQL\n")
    _write(evidence / "schema_manifest.json", '{"alembic_revision":"20260803_0005"}\n')
    _write(
        evidence / "acceptance_verification.json",
        json.dumps(
            {
                "git": {
                    "baseline": NRM_REQUIRED_BASELINE,
                    "branch": NRM_REQUIRED_BRANCH,
                    "clean": True,
                    "head": HEAD,
                },
                "package": {"cleaned_up": True, "network_requests": 0},
                "status": "PASS",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _write(evidence / "security_scan.json", '{"finding_count":0,"status":"PASS"}\n')
    _write(evidence / "KNOWN_LIMITATIONS.md", "# Known limitations\n\nNone.\n")
    _write(
        evidence / "codex_result.json", json.dumps(result_value, indent=2, sort_keys=True) + "\n"
    )
    _refresh_evidence_manifest(root, records)

    payload_sha256 = calculate_review_payload_digest(
        root,
        generated_at="2026-08-06T00:00:00Z",
        ticket="NRM-006",
        baseline=NRM_REQUIRED_BASELINE,
        process_runner=NrmGitRunner(),
    )
    review_reference = result_value["review_pack"]
    assert isinstance(review_reference, dict)
    review_reference["payload_sha256"] = payload_sha256
    _write(
        evidence / "codex_result.json", json.dumps(result_value, indent=2, sort_keys=True) + "\n"
    )
    _refresh_evidence_manifest(root, records)
    return CodexResult.model_validate(result_value), records


def _fixture(root: Path) -> None:
    evidence = root / "evidence/tickets/NRM-006"
    _write(evidence / "codex_result.json", json.dumps(_result()))
    _write(evidence / "commands.log", "")
    _write(evidence / "acceptance_matrix.json", "{}\n")
    for name in (
        "PUBLIC_CONTRACTS.md",
        "MIGRATION_SCHEMA_REVIEW.md",
        "ODD005_REMEDIATION.md",
        "TEMPORAL_MAPPING_USABLE_AT.md",
        "RETRY_DUPLICATE_PROVENANCE.md",
        "NORMALISATION_NUMERICS.md",
        "CONSENSUS_CONFIDENCE.md",
        "ASOF_CACHE_CONCURRENCY.md",
        "TESTS_AND_COVERAGE.md",
        "SECURITY_RIGHTS_WHEEL.md",
        "KNOWN_LIMITATIONS.md",
    ):
        _write(evidence / name, f"# {name}\n\nSynthetic review fixture.\n")
    _write(root / ".secret-scan-allowlist.json", '{"entries": [], "version": "1.0"}\n')


def _built_payload(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    summary = build_review_pack(
        root,
        ticket="NRM-006",
        baseline=NRM_REQUIRED_BASELINE,
        output=tmp_path / "out",
        generated_at="2026-08-06T00:00:00Z",
        process_runner=NrmGitRunner(),
    )
    with zipfile.ZipFile(summary.path) as archive:
        return summary.path, {name: archive.read(name) for name in archive.namelist()}


def _built_complete_payload(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    root = tmp_path / "complete-repository"
    root.mkdir()
    _complete_evidence(root)
    summary = build_review_pack(
        root,
        ticket="NRM-006",
        baseline=NRM_REQUIRED_BASELINE,
        output=tmp_path / "complete-out",
        generated_at="2026-08-06T00:00:00Z",
        process_runner=NrmGitRunner(),
    )
    with zipfile.ZipFile(summary.path) as archive:
        return summary.path, {name: archive.read(name) for name in archive.namelist()}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _refresh_archive_ledgers(payload: dict[str, bytes]) -> None:
    manifest = json.loads(payload["19_ARCHIVE_MANIFEST.json"])
    for item in manifest["files"]:
        name = item["name"]
        item["bytes"] = len(payload[name])
        item["sha256"] = hashlib.sha256(payload[name]).hexdigest()
    payload["19_ARCHIVE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
    payload["20_SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(payload[name]).hexdigest()}  {name}\n"
        for name in NRM_PREFERRED_NAMES
        if name != "20_SHA256SUMS.txt"
    ).encode()


def _refresh_checksum_only(payload: dict[str, bytes]) -> None:
    payload["20_SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(payload[name]).hexdigest()}  {name}\n"
        for name in NRM_PREFERRED_NAMES
        if name != "20_SHA256SUMS.txt"
    ).encode()


def _write_zip(path: Path, payload: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in NRM_PREFERRED_NAMES:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload[name])


@pytest.mark.unit
def test_nrm006_result_contract_requires_exact_repository_and_review_provenance() -> None:
    assert CodexResult.model_validate(_result()).ticket_id == "NRM-006"
    for path, value in (
        (("repository", "baseline"), "0" * 40),
        (("repository", "branch"), "wrong-branch"),
        (("review_pack", "path"), "review_pack/wrong.zip"),
        (("review_pack", "file_count"), 19),
    ):
        mutated = deepcopy(_result())
        container = mutated[path[0]]
        assert isinstance(container, dict)
        container[path[1]] = value
        with pytest.raises(ValidationError):
            CodexResult.model_validate(mutated)


@pytest.mark.unit
def test_nrm006_complete_result_requires_all_literal_commands_and_final_records() -> None:
    result = CodexResult.model_validate(_complete_result())
    records, acceptance = _validate_nrm_complete_result(result)
    assert len(records) == len(acceptance) == 32
    assert [item["command"] for item in records] == list(NRM_MANDATORY_ACCEPTANCE_COMMANDS)

    wrong_command = _complete_result()
    commands = wrong_command["commands"]
    assert isinstance(commands, list)
    commands[0]["command"] = "git status --short"
    with pytest.raises(ReviewPackError, match="exact ordered 32-command"):
        _validate_nrm_complete_result(CodexResult.model_validate(wrong_command))

    provisional_review = _complete_result()
    provisional_commands = provisional_review["commands"]
    assert isinstance(provisional_commands, list)
    provisional_commands[30]["result"] = "PASS: archive pending"
    with pytest.raises(ReviewPackError, match="command 31"):
        _validate_nrm_complete_result(CodexResult.model_validate(provisional_review))


@pytest.mark.unit
def test_nrm006_complete_evidence_builds_and_validates_full_archive(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    result, _records = _complete_evidence(root)
    _validate_nrm_complete_evidence(root, result, HEAD)
    summary = build_review_pack(
        root,
        ticket="NRM-006",
        baseline=NRM_REQUIRED_BASELINE,
        output=tmp_path / "out",
        generated_at="2026-08-06T00:00:00Z",
        process_runner=NrmGitRunner(),
    )
    validated = validate_review_zip(summary.path)
    assert validated.payload_sha256 == result.review_pack.payload_sha256
    with zipfile.ZipFile(summary.path) as archive:
        manifest = json.loads(archive.read("19_ARCHIVE_MANIFEST.json"))
        assert manifest["acceptance_status"] == "COMPLETE"
        assert manifest["repository_head"] == HEAD
        assert len(manifest["files"]) == 18


@pytest.mark.unit
def test_nrm006_review_pack_is_flat_capped_crc_and_detached_hash_valid(tmp_path: Path) -> None:
    path, payload = _built_payload(tmp_path)
    summary = validate_review_zip(path)
    assert summary.file_count == 20 <= 20
    assert path.name == NRM_REVIEW_ZIP_NAME
    assert tuple(payload) == NRM_PREFERRED_NAMES
    assert NRM_PACK_MANIFEST_SHA256.encode() in payload["04_FILE_CHANGE_MAP.md"]
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert all("/" not in name and "\\" not in name for name in archive.namelist())


@pytest.mark.unit
def test_nrm006_review_pack_cli_forwards_exact_ticket_baseline_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "NRM"
    expected_path = output / NRM_REVIEW_ZIP_NAME
    captured: dict[str, object] = {}

    def fake_build(root: Path, **kwargs: object) -> ReviewPackSummary:
        captured.update(kwargs)
        assert root == Path.cwd()
        return ReviewPackSummary(
            path=expected_path,
            file_count=20,
            sha256="a" * 64,
            payload_sha256="b" * 64,
        )

    monkeypatch.setattr("dmf_pulse.cli.review_pack_cmd.build_review_pack", fake_build)
    result = CliRunner().invoke(
        app,
        [
            "review-pack",
            "build",
            "--ticket",
            "NRM-006",
            "--baseline",
            NRM_REQUIRED_BASELINE,
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    assert captured["ticket"] == "NRM-006"
    assert captured["baseline"] == NRM_REQUIRED_BASELINE
    assert captured["output"] == output
    assert json.loads(result.stdout) == {
        "archive_sha256": "a" * 64,
        "file_count": 20,
        "ok": True,
        "path": expected_path.as_posix(),
        "payload_sha256": "b" * 64,
    }


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ("baseline", "branch"))
def test_nrm006_review_pack_rejects_wrong_git_provenance(tmp_path: Path, mutation: str) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="NRM-006",
            baseline="0" * 40 if mutation == "baseline" else NRM_REQUIRED_BASELINE,
            output=tmp_path / "out",
            generated_at="2026-08-06T00:00:00Z",
            process_runner=NrmBranchRunner() if mutation == "branch" else NrmGitRunner(),
        )
    assert caught.value.code == (
        "BASELINE_INVALID" if mutation == "baseline" else "REVIEW_BRANCH_INVALID"
    )


@pytest.mark.unit
def test_nrm006_review_validator_rejects_detached_checksum_drift(tmp_path: Path) -> None:
    _source, payload = _built_payload(tmp_path)
    target_name = "10_NORMALISATION_NUMERICS.md"
    payload[target_name] += b"tampered\n"
    manifest = json.loads(payload["19_ARCHIVE_MANIFEST.json"])
    for item in manifest["files"]:
        if item["name"] == target_name:
            item["bytes"] = len(payload[target_name])
            item["sha256"] = hashlib.sha256(payload[target_name]).hexdigest()
    payload["19_ARCHIVE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
    target = tmp_path / "checksum-drift.zip"
    _write_zip(target, payload)
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(target)
    assert caught.value.code == "REVIEW_CHECKSUM_HASH"


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    (
        "risk",
        "missing_command",
        "wrong_exit",
        "missing_result",
        "negative_duration",
        "wrong_teardown",
        "acceptance_mismatch",
    ),
)
def test_nrm006_complete_result_rejects_every_false_success(mutation: str) -> None:
    value = _complete_result()
    commands = value["commands"]
    acceptance = value["acceptance"]
    assert isinstance(commands, list)
    assert isinstance(acceptance, list)
    if mutation == "risk":
        value["risks"] = ["unresolved P1"]
        expected = "REVIEW_EVIDENCE_INVALID"
    elif mutation == "missing_command":
        commands.pop()
        expected = "REVIEW_ACCEPTANCE_INVALID"
    elif mutation == "wrong_exit":
        commands[0]["exit_code"] = 1
        expected = "REVIEW_ACCEPTANCE_INVALID"
    elif mutation == "missing_result":
        commands[0]["result"] = None
        expected = "REVIEW_ACCEPTANCE_INVALID"
    elif mutation == "negative_duration":
        commands[0]["duration_seconds"] = -1
        expected = "REVIEW_ACCEPTANCE_INVALID"
    elif mutation == "wrong_teardown":
        commands[31]["result"] = "PASS: teardown pending"
        expected = "REVIEW_ACCEPTANCE_INVALID"
    else:
        acceptance[0]["status"] = "FAIL"
        expected = "REVIEW_ACCEPTANCE_INVALID"
    with pytest.raises(ReviewPackError) as caught:
        _validate_nrm_complete_result(CodexResult.model_validate(value))
    assert caught.value.code == expected


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ("missing", "mismatch"))
def test_nrm006_complete_evidence_rejects_command_log_drift(tmp_path: Path, mutation: str) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    result, records = _complete_evidence(root)
    command_path = root / "evidence/tickets/NRM-006/commands.log"
    if mutation == "missing":
        command_path.unlink()
        expected = "REVIEW_ACCEPTANCE_INVALID"
    else:
        _write(command_path, "".join(json.dumps(item) + "\n" for item in records[1:]))
        expected = "REVIEW_EVIDENCE_INVALID"
    with pytest.raises(ReviewPackError) as caught:
        _validate_nrm_complete_evidence(root, result, HEAD)
    assert caught.value.code == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "bad_value", "sync_result"),
    (
        ("status", "FAIL", True),
        ("failed", 1, True),
        ("skipped", 1, True),
        ("passed", 0, True),
        ("overall_branch_coverage_percent", 89.99, True),
        ("critical_branch_coverage_percent", 94.99, True),
        ("math_branch_coverage_percent", 99.99, True),
        ("math_branch_coverage_percent", 101.0, True),
        ("critical_oracles", [], True),
        ("critical_oracles", [1] * 10, True),
        ("overall_branch_coverage_percent", 91.0, False),
    ),
)
def test_nrm006_complete_evidence_rejects_test_and_coverage_false_success(
    tmp_path: Path,
    field: str,
    bad_value: object,
    sync_result: bool,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    result, records = _complete_evidence(root)
    tests_path = root / "evidence/tickets/NRM-006/tests.json"
    tests = _json(tests_path)
    tests[field] = bad_value
    _write_json(tests_path, tests)
    _refresh_evidence_manifest(root, records)
    checked_result = result
    if sync_result:
        value = result.model_dump(mode="json")
        value["tests"] = [tests]
        checked_result = CodexResult.model_validate(value)
    with pytest.raises(ReviewPackError) as caught:
        _validate_nrm_complete_evidence(root, checked_result, HEAD)
    assert caught.value.code == "REVIEW_EVIDENCE_INVALID"


@pytest.mark.unit
def test_nrm006_complete_evidence_rejects_acceptance_matrix_drift(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    result, records = _complete_evidence(root)
    path = root / "evidence/tickets/NRM-006/acceptance_matrix.json"
    acceptance = _json(path)
    rows = acceptance["commands"]
    assert isinstance(rows, list)
    rows[0]["status"] = "FAIL"
    _write_json(path, acceptance)
    _refresh_evidence_manifest(root, records)
    with pytest.raises(ReviewPackError) as caught:
        _validate_nrm_complete_evidence(root, result, HEAD)
    assert caught.value.code == "REVIEW_ACCEPTANCE_INVALID"


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    ("context", "commit", "commands", "limitations", "artifacts"),
)
def test_nrm006_complete_evidence_rejects_manifest_provenance_drift(
    tmp_path: Path, mutation: str
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    result, _records = _complete_evidence(root)
    path = root / "evidence/tickets/NRM-006/evidence_manifest.json"
    manifest = _json(path)
    if mutation == "context":
        manifest["context_hash"] = "legacy-pack"
    elif mutation == "commit":
        manifest["code_commit"] = "b" * 40
    elif mutation == "commands":
        commands = manifest["commands"]
        assert isinstance(commands, list)
        commands[0]["exit_code"] = 1
    elif mutation == "limitations":
        manifest["known_limitations"] = ["unresolved P1"]
    else:
        artifacts = manifest["artifacts"]
        assert isinstance(artifacts, list)
        artifacts.pop()
    _write_json(path, manifest)
    with pytest.raises(ReviewPackError) as caught:
        _validate_nrm_complete_evidence(root, result, HEAD)
    assert caught.value.code == "REVIEW_EVIDENCE_INVALID"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("report", "path_parts", "bad_value"),
    (
        ("migration_matrix.json", ("status",), "FAIL"),
        ("migration_matrix.json", ("database", "postgres_version"), "17.6"),
        ("migration_matrix.json", ("offline_sql", "secret_free"), False),
        ("migration_matrix.json", ("schema", "schema_sha256"), "bad"),
        ("migration_matrix.json", ("matrix",), []),
        ("acceptance_verification.json", ("git", "clean"), False),
        ("acceptance_verification.json", ("package", "network_requests"), 1),
        ("security_scan.json", ("finding_count",), 1),
    ),
)
def test_nrm006_complete_evidence_rejects_tampered_proof_reports(
    tmp_path: Path,
    report: str,
    path_parts: tuple[str, ...],
    bad_value: object,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    result, records = _complete_evidence(root)
    path = root / "evidence/tickets/NRM-006" / report
    value = _json(path)
    target: dict[str, Any] = value
    for part in path_parts[:-1]:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    target[path_parts[-1]] = bad_value
    _write_json(path, value)
    _refresh_evidence_manifest(root, records)
    with pytest.raises(ReviewPackError) as caught:
        _validate_nrm_complete_evidence(root, result, HEAD)
    assert caught.value.code == "REVIEW_EVIDENCE_INVALID"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        ("head", "REVIEW_HEAD_INVALID"),
        ("ancestry", "REVIEW_BASELINE_ANCESTRY"),
        ("merge", "REVIEW_HISTORY_INVALID"),
        ("dirty", "REVIEW_TREE_DIRTY"),
        ("diff", "BASELINE_DIFF_FAILED"),
    ),
)
def test_nrm006_review_pack_rejects_all_git_state_failures(
    tmp_path: Path, mode: str, expected: str
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="NRM-006",
            baseline=NRM_REQUIRED_BASELINE,
            output=tmp_path / "out",
            generated_at="2026-08-06T00:00:00Z",
            process_runner=NrmStateRunner(mode),
        )
    assert caught.value.code == expected


@pytest.mark.unit
def test_nrm006_review_pack_requires_baseline(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="NRM-006",
            baseline=None,
            output=tmp_path / "out",
            generated_at="2026-08-06T00:00:00Z",
            process_runner=NrmGitRunner(),
        )
    assert caught.value.code == "BASELINE_INVALID"


@pytest.mark.unit
def test_nrm006_review_pack_rejects_wrong_codex_result_kind(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    _write_json(
        root / "evidence/tickets/NRM-006/codex_result.json",
        {
            "artifacts": [],
            "commands": [],
            "created_at": "2026-08-06T00:00:00Z",
            "status": "DRAFT",
            "ticket_id": "NRM-006",
        },
    )
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="NRM-006",
            baseline=NRM_REQUIRED_BASELINE,
            output=tmp_path / "out",
            generated_at="2026-08-06T00:00:00Z",
            process_runner=NrmGitRunner(),
        )
    assert caught.value.code == "CODEX_RESULT_INVALID"


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ("preferred_order", "detached_set"))
def test_nrm006_assembly_enforces_both_exact_layout_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    if mutation == "preferred_order":
        changed_order = (
            NRM_PREFERRED_NAMES[1],
            NRM_PREFERRED_NAMES[0],
            *NRM_PREFERRED_NAMES[2:],
        )
        monkeypatch.setattr("dmf_pulse.assurance.review_pack.NRM_PREFERRED_NAMES", changed_order)
    else:
        monkeypatch.setattr(
            "dmf_pulse.assurance.review_pack.NRM_DETACHED_REVIEW_NAMES", frozenset()
        )
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="NRM-006",
            baseline=NRM_REQUIRED_BASELINE,
            output=tmp_path / "out",
            generated_at="2026-08-06T00:00:00Z",
            process_runner=NrmGitRunner(),
        )
    assert caught.value.code == "REVIEW_PACK_LAYOUT"


@pytest.mark.unit
def test_nrm006_assembly_rechecks_personal_data_after_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    _write(
        root / "evidence/tickets/NRM-006/PUBLIC_CONTRACTS.md",
        "# Synthetic fixture\n\nC:\\Users\\fixture-user\\workspace\n",
    )
    monkeypatch.setattr(
        "dmf_pulse.assurance.review_pack._redact_fpl_personal_text", lambda value: value
    )
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="NRM-006",
            baseline=NRM_REQUIRED_BASELINE,
            output=tmp_path / "out",
            generated_at="2026-08-06T00:00:00Z",
            process_runner=NrmGitRunner(),
        )
    assert caught.value.code == "REVIEW_PACK_PERSONAL_DATA"


@pytest.mark.unit
def test_nrm006_build_removes_temporary_zip_after_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    output = tmp_path / "out"

    def fail_validation(_path: Path) -> ReviewPackSummary:
        raise ReviewPackError("REVIEW_METADATA_INVALID", "synthetic validator failure")

    monkeypatch.setattr("dmf_pulse.assurance.review_pack.validate_review_zip", fail_validation)
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="NRM-006",
            baseline=NRM_REQUIRED_BASELINE,
            output=output,
            generated_at="2026-08-06T00:00:00Z",
            process_runner=NrmGitRunner(),
        )
    assert caught.value.code == "REVIEW_METADATA_INVALID"
    assert not tuple(output.glob(".dmf-review-*.tmp"))


@pytest.mark.unit
def test_nrm006_complete_review_pack_rejects_commit_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _complete_evidence(root)
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="NRM-006",
            baseline=NRM_REQUIRED_BASELINE,
            output=tmp_path / "out",
            generated_at="2026-08-06T00:00:00Z",
            process_runner=NrmStateRunner("different_head"),
        )
    assert caught.value.code == "REVIEW_COMMIT_MISMATCH"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("ODD005_RAW_BODY_" + "CANARY_7c4f91", "REVIEW_PACK_RAW_PAYLOAD"),
        ("ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890", "REVIEW_PACK_SECRET"),
    ),
)
def test_nrm006_assembly_rejects_unsafe_diff_payload(
    tmp_path: Path, value: str, expected: str
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="NRM-006",
            baseline=NRM_REQUIRED_BASELINE,
            output=tmp_path / "out",
            generated_at="2026-08-06T00:00:00Z",
            process_runner=NrmUnsafeDiffRunner(value),
        )
    assert caught.value.code == expected


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ("manifest_hash", "manifest_payload", "provenance", "result"))
def test_nrm006_review_zip_rejects_manifest_payload_and_provenance_drift(
    tmp_path: Path, mutation: str
) -> None:
    _source, payload = _built_complete_payload(tmp_path)
    if mutation == "manifest_hash":
        payload["10_NORMALISATION_NUMERICS.md"] += b"tampered\n"
    elif mutation == "result":
        result = json.loads(payload["18_CODEX_RESULT.json"])
        result["review_pack"]["payload_sha256"] = "f" * 64
        payload["18_CODEX_RESULT.json"] = json.dumps(result, indent=2).encode()
        _refresh_archive_ledgers(payload)
    else:
        manifest = json.loads(payload["19_ARCHIVE_MANIFEST.json"])
        if mutation == "manifest_payload":
            manifest["payload_sha256"] = "f" * 64
        else:
            manifest["repository_head"] = "c" * 40
        payload["19_ARCHIVE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
        _refresh_checksum_only(payload)
    target = tmp_path / f"{mutation}.zip"
    _write_zip(target, payload)
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(target)
    assert caught.value.code == (
        "REVIEW_MANIFEST_HASH"
        if mutation == "manifest_hash"
        else "REVIEW_PROVENANCE_MISMATCH"
        if mutation == "provenance"
        else "REVIEW_PAYLOAD_DIGEST"
    )


@pytest.mark.unit
def test_nrm006_review_zip_rejects_detached_command_log_mismatch(tmp_path: Path) -> None:
    _source, payload = _built_complete_payload(tmp_path)
    records = [json.loads(line) for line in payload["15_COMMANDS_AND_RESULTS.log"].splitlines()]
    records[0]["result"] = "PASS: detached record drift"
    payload["15_COMMANDS_AND_RESULTS.log"] = b"".join(
        json.dumps(record).encode() + b"\n" for record in records
    )
    _refresh_archive_ledgers(payload)
    target = tmp_path / "command-log-drift.zip"
    _write_zip(target, payload)
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(target)
    assert caught.value.code == "REVIEW_ACCEPTANCE_INVALID"


@pytest.mark.unit
def test_nrm006_review_zip_rejects_result_manifest_status_mismatch(tmp_path: Path) -> None:
    _source, payload = _built_complete_payload(tmp_path)
    manifest = json.loads(payload["19_ARCHIVE_MANIFEST.json"])
    manifest["acceptance_status"] = "BLOCKED"
    payload["19_ARCHIVE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
    _refresh_checksum_only(payload)
    target = tmp_path / "status-drift.zip"
    _write_zip(target, payload)
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(target)
    assert caught.value.code == "REVIEW_STATUS_MISMATCH"


@pytest.mark.unit
def test_nrm006_review_zip_rejects_wrong_physical_order(tmp_path: Path) -> None:
    _source, payload = _built_complete_payload(tmp_path)
    path = tmp_path / "reverse.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in reversed(NRM_PREFERRED_NAMES):
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload[name])
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(path)
    assert caught.value.code == "REVIEW_PACK_LAYOUT"
