"""Focused tests for strict NRM-006 evidence generation."""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _namespace() -> dict[str, Any]:
    return runpy.run_path("scripts/generate_nrm006_evidence.py")


def _records(namespace: dict[str, Any]) -> list[dict[str, Any]]:
    commands = namespace["NRM_MANDATORY_ACCEPTANCE_COMMANDS"]
    records = [
        {
            "command": command,
            "duration_seconds": float(index),
            "exit_code": 0,
            "result": "PASS: command completed",
        }
        for index, command in enumerate(commands, start=1)
    ]
    records[26]["result"] = "PASS: 321 tests; 0 skipped; 95.25% combined coverage"
    records[30]["result"] = namespace["NRM_REVIEW_FINAL_RESULT"]
    records[31]["result"] = namespace["NRM_TEARDOWN_FINAL_RESULT"]
    return records


def _critical(namespace: dict[str, Any]) -> dict[str, Any]:
    categories = namespace["CRITICAL_CATEGORIES"]
    report: dict[str, Any] = {
        "critical_oracles": {
            category: [f"src/example.py:{category} - oracle {index}"]
            for index, category in enumerate(categories, start=1)
        },
        "errors": [],
        "mathematical_core_branch_coverage_percent": 100.0,
        "ok": True,
        "overall_branch_coverage_percent": 92.5,
        "overall_branches_covered": 185,
        "overall_branches_total": 200,
        "repository_combined_coverage_percent": 94.0,
        "repository_combined_units_covered": 940,
        "repository_combined_units_total": 1000,
        "status": "PASS",
    }
    for index, category in enumerate(categories):
        report[f"{category}_branch_coverage_percent"] = 95.0 + index / 10
        report[f"{category}_branches_covered"] = 19
        report[f"{category}_branches_total"] = 20
    report["critical_oracles"][categories[0]].append(
        "src/example.py:second_temporal_oracle - independent oracle"
    )
    return report


def test_acceptance_requires_exact_final_records() -> None:
    namespace = _namespace()
    records = _records(namespace)

    rows = namespace["_acceptance"](records)

    assert len(rows) == 32
    assert all(row["status"] == "PASS" for row in rows)
    assert set(rows[0]) == {
        "command",
        "duration_seconds",
        "exit_code",
        "expected_exit_code",
        "status",
    }
    records[30]["result"] = namespace["NRM_REVIEW_WRITE_AHEAD_RESULT"]
    records[30]["duration_seconds"] = None
    assert namespace["_acceptance"](records)[30]["status"] == "NOT_PASSED"


def test_acceptance_rejects_schema_and_order_drift() -> None:
    namespace = _namespace()
    records = _records(namespace)
    records[0]["unexpected"] = True
    with pytest.raises(ValueError, match="four exact fields"):
        namespace["_acceptance"](records)

    records = _records(namespace)
    records[0], records[1] = records[1], records[0]
    with pytest.raises(ValueError, match="exactly 32 ordered"):
        namespace["_acceptance"](records)


def test_tests_report_uses_minimum_critical_gate_and_exact_full_suite() -> None:
    namespace = _namespace()
    report = namespace["_tests"](_records(namespace), _critical(namespace))

    assert report["status"] == "PASS"
    assert report["passed"] == 321
    assert report["skipped"] == 0
    assert report["critical_branch_coverage_percent"] == 95.0
    assert report["math_branch_coverage_percent"] == 100.0
    assert len(report["critical_oracles"]) == len(namespace["CRITICAL_CATEGORIES"]) + 1

    below_gate = _critical(namespace)
    below_gate["usable_at_branch_coverage_percent"] = 94.999
    assert namespace["_tests"](_records(namespace), below_gate)["status"] == "FAIL"


def test_manifest_hashes_every_immediate_evidence_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _namespace()
    repository_root = tmp_path / "repository"
    evidence_root = repository_root / "evidence/tickets/NRM-006"
    evidence_root.mkdir(parents=True)
    (evidence_root / ".gitignore").write_text("*\n", encoding="utf-8")
    (evidence_root / "tests.json").write_text("{}\n", encoding="utf-8")
    nested = evidence_root / "prior_blockers"
    nested.mkdir()
    (nested / "ignored.md").write_text("ignored\n", encoding="utf-8")
    monkeypatch.setitem(namespace["_manifest"].__globals__, "REPOSITORY_ROOT", repository_root)
    monkeypatch.setitem(namespace["_manifest"].__globals__, "EVIDENCE_ROOT", evidence_root)

    namespace["_manifest"]("COMPLETE", [], "a" * 40)

    manifest = json.loads((evidence_root / "evidence_manifest.json").read_text(encoding="utf-8"))
    assert manifest["context_hash"] == namespace["PACK_MANIFEST_SHA256"]
    assert manifest["known_limitations"] == []
    assert [item["path"] for item in manifest["artifacts"]] == [
        "evidence/tickets/NRM-006/.gitignore",
        "evidence/tickets/NRM-006/tests.json",
    ]
