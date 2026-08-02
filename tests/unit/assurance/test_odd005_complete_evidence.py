"""ODD-005 COMPLETE evidence provenance and false-success oracles."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from dmf_pulse.assurance.evidence import (
    ODD_REQUIRED_BASELINE,
    ODD_REQUIRED_BRANCH,
    CodexResult,
)
from dmf_pulse.assurance.review_pack import (
    ODD_MANDATORY_ACCEPTANCE_COMMANDS,
    ODD_PACK_MANIFEST_SHA256,
    ODD_REVIEW_FINAL_RESULT,
    ODD_TEARDOWN_FINAL_RESULT,
    ReviewPackError,
    _validate_odd_complete_evidence,
)

HEAD = "a" * 40
EVIDENCE_RELATIVE = Path("evidence/tickets/ODD-005")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True)
    path.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8", newline="\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index, command in enumerate(ODD_MANDATORY_ACCEPTANCE_COMMANDS, start=1):
        exit_code = 4 if index == 23 else 0
        result = "PASS: synthetic acceptance proof"
        if index == 23:
            result = "PASS: CREDENTIAL_UNAVAILABLE with zero transport calls"
        elif index == 27:
            result = ODD_REVIEW_FINAL_RESULT
        elif index == 28:
            result = ODD_TEARDOWN_FINAL_RESULT
        records.append(
            {
                "command": command,
                "duration_seconds": 0.1,
                "exit_code": exit_code,
                "result": result,
            }
        )
    return records


def _acceptance(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "command": record["command"],
            "duration_seconds": record["duration_seconds"],
            "exit_code": record["exit_code"],
            "expected_exit_code": 4 if index == 23 else 0,
            "status": "PASS",
        }
        for index, record in enumerate(records, start=1)
    ]


def _tests() -> dict[str, object]:
    value: dict[str, object] = {
        "critical_oracles": [f"odd-oracle-{index}" for index in range(10)],
        "failed": 0,
        "mutation_method": "boundary mutation and deterministic negative controls",
        "passed": 700,
        "skipped": 0,
        "status": "PASS",
    }
    for prefix in (
        "critical_odds_ingestion",
        "cutoff",
        "fpl_remediation",
        "overall",
        "quota",
        "rights",
        "tls",
    ):
        value[f"{prefix}_branch_coverage_percent"] = 96.0
        value[f"{prefix}_branches_covered"] = 96
        value[f"{prefix}_branches_total"] = 100
    value["repository_combined_coverage_percent"] = 96.0
    value["repository_combined_units_covered"] = 96
    value["repository_combined_units_total"] = 100
    return value


def _reports() -> dict[str, dict[str, object]]:
    schema_hash = "b" * 64
    return {
        "migration_matrix.json": {
            "baseline_revision": "20260724_0002",
            "database": {"postgres_version": "18.4"},
            "matrix": [
                {"from": "base", "status": "PASS", "to": "20260725_0004"},
                {"from": "20260725_0004", "status": "PASS", "to": "20260724_0002"},
                {"from": "20260724_0002", "status": "PASS", "to": "20260725_0004"},
                {"from": "20260725_0004", "status": "PASS", "to": "20260724_0002"},
                {"from": "20260724_0002", "status": "PASS", "to": "20260725_0004"},
            ],
            "metadata_drift_check": "PASS",
            "offline_sql": {
                "path": "evidence/tickets/ODD-005/offline_upgrade.sql",
                "secret_free": True,
            },
            "revision_count": 2,
            "revisions": ["20260725_0003", "20260725_0004"],
            "schema": {
                "alembic_revision": "20260725_0004",
                "schema_sha256": schema_hash,
            },
            "status": "PASS",
            "target_revision": "20260725_0004",
            "ticket_id": "ODD-005",
        },
        "package_report.json": {
            "cleaned_up": True,
            "database_cleaned_up": True,
            "database_isolated": True,
            "foundation": {
                "clean_environment_outside_repository": True,
                "cleaned_up": True,
                "network_fetch_disabled": True,
                "status": "PASS",
            },
            "fpl004": {
                "bundle_member_count": 2,
                "semantic_sha256": "e" * 64,
                "status": "USABLE",
            },
            "network_requests": 0,
            "odd005": {
                "market": {
                    "observation_count": 6,
                    "operator_books": 2,
                    "prices": {
                        "SYNTHETIC_BOOK_ALPHA": {
                            "AWAY": "4.20",
                            "DRAW": "3.60",
                            "HOME": "1.80",
                        },
                        "SYNTHETIC_BOOK_BETA": {
                            "AWAY": "4.10",
                            "DRAW": "3.50",
                            "HOME": "1.85",
                        },
                    },
                },
                "refusal": {
                    "code": "CREDENTIAL_UNAVAILABLE",
                    "transport_called": False,
                },
                "replay": {
                    "complete_books_created": 2,
                    "observations_created": 6,
                    "status": "COMPLETE",
                },
                "validation_status": "VALID",
            },
            "status": "PASS",
            "wheel": {
                "contains_odds_resources": True,
                "contains_py_typed": True,
                "distribution": "dmf-pulse==0.2.0",
                "sha256": "c" * 64,
            },
        },
        "acceptance_verification.json": {
            "database": {
                "baseline_revision": "20260724_0002",
                "postgres_version": "18.4",
                "schema_sha256": schema_hash,
            },
            "git": {
                "baseline": ODD_REQUIRED_BASELINE,
                "branch": ODD_REQUIRED_BRANCH,
                "clean": True,
                "head": HEAD,
            },
            "market": {
                "literal_command_output_validated": True,
                "observation_count": 6,
                "operator_books": 2,
                "source_scale_preserved": True,
            },
            "package": {"cleaned_up": True, "network_requests": 0},
            "status": "PASS",
            "transport_preflight": {
                "credential_failure": "CREDENTIAL_UNAVAILABLE",
                "quota_failure": "QUOTA_EXHAUSTED",
                "transport_call_count": 0,
            },
        },
        "security_scan.json": {"finding_count": 0, "status": "PASS"},
    }


def _result(records: list[dict[str, object]], tests: dict[str, object]) -> CodexResult:
    return CodexResult.model_validate(
        {
            "acceptance": _acceptance(records),
            "assumptions": [],
            "code_commit": HEAD,
            "commands": records,
            "dependency_impact": "no dependency expansion",
            "exclusions_verified": ["no live provider request"],
            "files_changed": [{"change": "A", "path": "src/example.py"}],
            "migration_impact": "two ordered PostgreSQL revisions",
            "public_interfaces": ["dmf ingest odds replay"],
            "repository": {
                "baseline": ODD_REQUIRED_BASELINE,
                "branch": ODD_REQUIRED_BRANCH,
                "clean": True,
                "head": HEAD,
                "merged": False,
                "pushed": False,
            },
            "review_pack": {
                "file_count": 20,
                "path": "review_pack/ODD-005/DMF_PULSE_ODD-005_REVIEW.zip",
                "payload_sha256": "d" * 64,
            },
            "risks": [],
            "status": "COMPLETE",
            "summary": "Synthetic complete ODD-005 evidence.",
            "tests": [tests],
            "ticket_id": "ODD-005",
        }
    )


def _refresh_manifest(root: Path, records: list[dict[str, object]], *, context_hash: str) -> None:
    evidence = root / EVIDENCE_RELATIVE
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
        {
            "artifacts": artifacts,
            "code_commit": HEAD,
            "commands": records,
            "context_hash": context_hash,
            "created_at": "2026-08-02T00:00:00Z",
            "known_limitations": [],
            "status": "COMPLETE",
            "ticket_id": "ODD-005",
        },
    )


def _complete_evidence(root: Path) -> tuple[CodexResult, list[dict[str, object]]]:
    evidence = root / EVIDENCE_RELATIVE
    records = _records()
    tests = _tests()
    result = _result(records, tests)
    _write(evidence / "commands.log", "".join(json.dumps(item) + "\n" for item in records))
    _write(evidence / "tests.json", tests)
    _write(
        evidence / "acceptance_matrix.json",
        {
            "commands": _acceptance(records),
            "failed": 0,
            "passed": 28,
            "status": "COMPLETE",
            "ticket_id": "ODD-005",
        },
    )
    for name, value in _reports().items():
        _write(evidence / name, value)
    _write(evidence / "codex_result.json", result.model_dump(mode="json"))
    _refresh_manifest(root, records, context_hash=ODD_PACK_MANIFEST_SHA256)
    return result, records


@pytest.mark.unit
def test_complete_odd_evidence_validates_all_provenance_and_proof_reports(
    tmp_path: Path,
) -> None:
    result, _records_value = _complete_evidence(tmp_path)
    _validate_odd_complete_evidence(tmp_path, result, HEAD)


@pytest.mark.unit
def test_complete_odd_evidence_rejects_wrong_pack_context_hash(tmp_path: Path) -> None:
    result, records = _complete_evidence(tmp_path)
    _refresh_manifest(tmp_path, records, context_hash="legacy-pack-1.0")
    with pytest.raises(ReviewPackError) as caught:
        _validate_odd_complete_evidence(tmp_path, result, HEAD)
    assert caught.value.code == "REVIEW_EVIDENCE_INVALID"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("metric", "covered"),
    (
        ("repository_combined", "repository_combined_units_covered"),
        ("overall", "overall_branches_covered"),
        ("critical_odds_ingestion", "critical_odds_ingestion_branches_covered"),
        ("rights", "rights_branches_covered"),
        ("quota", "quota_branches_covered"),
        ("cutoff", "cutoff_branches_covered"),
        ("tls", "tls_branches_covered"),
        ("fpl_remediation", "fpl_remediation_branches_covered"),
    ),
)
def test_complete_odd_evidence_rejects_every_coverage_tier(
    tmp_path: Path,
    metric: str,
    covered: str,
) -> None:
    result, records = _complete_evidence(tmp_path)
    tests_path = tmp_path / EVIDENCE_RELATIVE / "tests.json"
    tests = json.loads(tests_path.read_text(encoding="utf-8"))
    tests[f"{metric}_coverage_percent"] = (
        89.0 if metric in {"repository_combined", "overall"} else 94.0
    )
    tests[covered] = 89 if metric in {"repository_combined", "overall"} else 94
    _write(tests_path, tests)
    _refresh_manifest(tmp_path, records, context_hash=ODD_PACK_MANIFEST_SHA256)
    value = result.model_dump(mode="json")
    value["tests"] = [tests]
    with pytest.raises(ReviewPackError) as caught:
        _validate_odd_complete_evidence(tmp_path, CodexResult.model_validate(value), HEAD)
    assert caught.value.code == "REVIEW_EVIDENCE_INVALID"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("report_name", "path", "bad_value"),
    (
        ("migration_matrix.json", ("matrix",), []),
        ("migration_matrix.json", ("database", "postgres_version"), "17.6"),
        ("migration_matrix.json", ("offline_sql", "secret_free"), False),
        ("package_report.json", ("database_cleaned_up",), False),
        ("package_report.json", ("foundation", "network_fetch_disabled"), False),
        ("package_report.json", ("fpl004", "status"), "INVALID"),
        ("package_report.json", ("wheel", "contains_odds_resources"), False),
        ("package_report.json", ("odd005", "validation_status"), "INVALID"),
        ("package_report.json", ("odd005", "replay", "observations_created"), 5),
        (
            "package_report.json",
            ("odd005", "market", "prices", "SYNTHETIC_BOOK_ALPHA", "HOME"),
            "1.8",
        ),
        ("package_report.json", ("odd005", "refusal", "transport_called"), True),
        ("acceptance_verification.json", ("git", "clean"), False),
        ("acceptance_verification.json", ("transport_preflight", "transport_call_count"), 1),
        ("acceptance_verification.json", ("market", "source_scale_preserved"), False),
        ("security_scan.json", ("finding_count",), 1),
    ),
)
def test_complete_odd_evidence_rejects_tampered_proof_reports(
    tmp_path: Path,
    report_name: str,
    path: tuple[str, ...],
    bad_value: object,
) -> None:
    result, records = _complete_evidence(tmp_path)
    report_path = tmp_path / EVIDENCE_RELATIVE / report_name
    report = json.loads(report_path.read_text(encoding="utf-8"))
    target: dict[str, Any] = report
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = bad_value
    _write(report_path, report)
    _refresh_manifest(tmp_path, records, context_hash=ODD_PACK_MANIFEST_SHA256)
    with pytest.raises(ReviewPackError) as caught:
        _validate_odd_complete_evidence(tmp_path, result, HEAD)
    assert caught.value.code == "REVIEW_EVIDENCE_INVALID"


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation", ("missing", "wrong_exit", "pending_review", "pending_teardown")
)
def test_complete_odd_result_rejects_command_false_success(
    tmp_path: Path,
    mutation: str,
) -> None:
    result, _records_value = _complete_evidence(tmp_path)
    value = deepcopy(result.model_dump(mode="json"))
    if mutation == "missing":
        value["commands"].pop()
    elif mutation == "wrong_exit":
        value["commands"][22]["exit_code"] = 0
    elif mutation == "pending_review":
        value["commands"][26]["result"] = "PENDING: review command has not run"
    else:
        value["commands"][27]["result"] = "PENDING: teardown has not run"
    with pytest.raises(ReviewPackError) as caught:
        _validate_odd_complete_evidence(tmp_path, CodexResult.model_validate(value), HEAD)
    assert caught.value.code == "REVIEW_ACCEPTANCE_INVALID"


@pytest.mark.unit
def test_complete_odd_evidence_rejects_acceptance_and_manifest_false_successes(
    tmp_path: Path,
) -> None:
    result, records = _complete_evidence(tmp_path)
    acceptance_path = tmp_path / EVIDENCE_RELATIVE / "acceptance_matrix.json"
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    acceptance["commands"][0]["status"] = "FAIL"
    _write(acceptance_path, acceptance)
    _refresh_manifest(tmp_path, records, context_hash=ODD_PACK_MANIFEST_SHA256)
    with pytest.raises(ReviewPackError) as matrix_error:
        _validate_odd_complete_evidence(tmp_path, result, HEAD)
    assert matrix_error.value.code == "REVIEW_ACCEPTANCE_INVALID"

    result, records = _complete_evidence(tmp_path)
    manifest_path = tmp_path / EVIDENCE_RELATIVE / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].pop()
    _write(manifest_path, manifest)
    with pytest.raises(ReviewPackError) as manifest_error:
        _validate_odd_complete_evidence(tmp_path, result, HEAD)
    assert manifest_error.value.code == "REVIEW_EVIDENCE_INVALID"


@pytest.mark.unit
def test_complete_odd_evidence_requires_zero_unresolved_risks_and_limitations(
    tmp_path: Path,
) -> None:
    result, _records_value = _complete_evidence(tmp_path)
    value = result.model_dump(mode="json")
    value["risks"] = ["unresolved P0 synthetic finding"]
    with pytest.raises(ReviewPackError) as risk_error:
        _validate_odd_complete_evidence(tmp_path, CodexResult.model_validate(value), HEAD)
    assert risk_error.value.code == "REVIEW_EVIDENCE_INVALID"

    result, _records_value = _complete_evidence(tmp_path)
    manifest_path = tmp_path / EVIDENCE_RELATIVE / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["known_limitations"] = ["unresolved P1 synthetic finding"]
    _write(manifest_path, manifest)
    with pytest.raises(ReviewPackError) as limitation_error:
        _validate_odd_complete_evidence(tmp_path, result, HEAD)
    assert limitation_error.value.code == "REVIEW_EVIDENCE_INVALID"
