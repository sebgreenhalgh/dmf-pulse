"""Fail-closed unit proofs for the NRM-006 independent acceptance verifier."""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _namespace(repository_root: Path) -> dict[str, Any]:
    return runpy.run_path(str(repository_root / "scripts/verify_nrm006_acceptance.py"))


def _package() -> dict[str, Any]:
    return {
        "cleaned_up": True,
        "database_cleaned_up": True,
        "database_isolated": True,
        "fpl_status": "USABLE",
        "network_requests": 0,
        "normalisation_status": "NORMALISED",
        "observation_count": 6,
        "odds_status": "COMPLETE",
        "semantic_result_sha256": (
            "bd8840cceed27199e3b10945ef54529a517df68b522a82ab0c935c460116a499"
        ),
        "status": "PASS",
        "wheel": {
            "contains_confidence_gate_policy": True,
            "contains_normalisation_policy": True,
            "distribution": "dmf-pulse==0.2.0",
            "sha256": "a" * 64,
        },
    }


def test_nrm006_acceptance_composes_exact_review_pack_shape_and_writes_atomically(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _namespace(repository_root)
    sections: dict[str, dict[str, Any]] = {
        "_verify_git": {
            "baseline": namespace["REQUIRED_BASELINE"],
            "branch": namespace["REQUIRED_BRANCH"],
            "clean": True,
            "head": "a" * 40,
        },
        "_verify_frozen_inputs": {"policy_sha256": namespace["POLICY_SHA256"]},
        "_verify_migration_and_database": {
            "postgres_version": "18.4",
            "target_revision": namespace["TARGET_REVISION"],
        },
        "_verify_package": {"network_requests": 0, "cleaned_up": True},
        "_verify_coverage": {
            "overall_branch_coverage_percent": 90.0,
            "critical_branch_coverage_percent": 95.0,
            "math_branch_coverage_percent": 100.0,
        },
        "_verify_goldens": {"status": "PASS"},
        "_verify_temporal_canaries": {"status": "PASS"},
        "_verify_captured_outputs": {"capture_count": 0},
        "_verify_security": {"finding_count": 0, "status": "PASS"},
    }
    function_globals = namespace["verify"].__globals__
    for name, value in sections.items():
        monkeypatch.setitem(function_globals, name, lambda value=value: value)
    report_path = tmp_path / "acceptance_verification.json"
    security_path = tmp_path / "security_scan.json"
    report = namespace["verify"](
        report_path=report_path,
        security_report_path=security_path,
    )
    assert report["status"] == "PASS"
    assert report["ticket_id"] == "NRM-006"
    assert report["git"]["baseline"] == namespace["REQUIRED_BASELINE"]
    assert report["package"] == {"network_requests": 0, "cleaned_up": True}
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    assert json.loads(security_path.read_text(encoding="utf-8")) == sections["_verify_security"]
    assert not (tmp_path / ".acceptance_verification.json.tmp").exists()


def test_nrm006_package_report_requires_zero_network_cleanup_and_exact_golden(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _namespace(repository_root)
    path = tmp_path / "package_report.json"
    path.write_text(json.dumps(_package()), encoding="utf-8")
    function_globals = namespace["_verify_package"].__globals__
    monkeypatch.setitem(function_globals, "PACKAGE_REPORT_PATH", path)
    report = namespace["_verify_package"]()
    assert report["network_requests"] == 0
    assert report["cleaned_up"] is True
    assert report["semantic_result_sha256"] == namespace["HAPPY_SEMANTIC_SHA256"]

    unsafe = _package()
    unsafe["network_requests"] = 1
    path.write_text(json.dumps(unsafe), encoding="utf-8")
    with pytest.raises(namespace["AcceptanceError"], match="installed-wheel"):
        namespace["_verify_package"]()

    missing_gate_policy = _package()
    del missing_gate_policy["wheel"]["contains_confidence_gate_policy"]
    path.write_text(json.dumps(missing_gate_policy), encoding="utf-8")
    with pytest.raises(namespace["AcceptanceError"], match="installed-wheel"):
        namespace["_verify_package"]()


def test_nrm006_migration_report_requires_exact_0004_to_0005_matrix_and_hashes(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _namespace(repository_root)
    evidence = tmp_path / "evidence" / "tickets" / "NRM-006"
    evidence.mkdir(parents=True)
    offline = evidence / "offline_upgrade.sql"
    schema_manifest = evidence / "schema_manifest.json"
    offline.write_text("-- deterministic SQL\n", encoding="utf-8")
    schema_manifest.write_text("{}\n", encoding="utf-8")
    sha256 = namespace["_sha256"]
    report = {
        "baseline_revision": namespace["BASELINE_REVISION"],
        "data_preservation": {"status": "PASS"},
        "database": {"postgres_version": "18.4"},
        "matrix": namespace["EXPECTED_MATRIX"],
        "metadata_drift_check": "PASS",
        "offline_sql": {
            "path": "evidence/tickets/NRM-006/offline_upgrade.sql",
            "secret_free": True,
            "sha256": sha256(offline),
        },
        "revision_count": 1,
        "revisions": [namespace["TARGET_REVISION"]],
        "schema": {
            "alembic_revision": namespace["TARGET_REVISION"],
            "schema_sha256": "b" * 64,
        },
        "schema_manifest": {
            "path": "evidence/tickets/NRM-006/schema_manifest.json",
            "sha256": sha256(schema_manifest),
        },
        "status": "PASS",
        "target_revision": namespace["TARGET_REVISION"],
        "ticket_id": "NRM-006",
    }
    report_path = evidence / "migration_matrix.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    function_globals = namespace["_verify_migration_report"].__globals__
    monkeypatch.setitem(function_globals, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setitem(function_globals, "MIGRATION_REPORT_PATH", report_path)
    observed, schema = namespace["_verify_migration_report"]()
    assert observed["matrix"] == namespace["EXPECTED_MATRIX"]
    assert schema["alembic_revision"] == namespace["TARGET_REVISION"]

    report["ticket_id"] = "FPL-004"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(namespace["AcceptanceError"], match="exact NRM-006 path"):
        namespace["_verify_migration_report"]()


def test_nrm006_real_frozen_inputs_and_goldens_are_self_consistent(
    repository_root: Path,
) -> None:
    namespace = _namespace(repository_root)
    frozen = namespace["_verify_frozen_inputs"]()
    goldens = namespace["_verify_goldens"]()
    assert frozen["fixture_entry_count"] == 12
    assert frozen["oracle_count"] == 11
    assert frozen["confidence_gate_policy_sha256"] == namespace["CONFIDENCE_GATE_POLICY_SHA256"]
    assert frozen["policy_sha256"] == namespace["POLICY_SHA256"]
    assert goldens["case_count"] == 6
    assert (
        goldens["semantic_result_sha256"]["happy_path_consensus.json"]
        == namespace["HAPPY_SEMANTIC_SHA256"]
    )


def test_nrm006_optional_observation_capture_preserves_lexical_odds(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _namespace(repository_root)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    source = repository_root / "fixtures/odds/NRM-006/happy_path_market_query.json"
    (evidence / "market_observations.json").write_bytes(source.read_bytes())
    monkeypatch.setitem(
        namespace["_verify_captured_outputs"].__globals__, "EVIDENCE_ROOT", evidence
    )
    report = namespace["_verify_captured_outputs"]()
    assert report == {
        "capture_count": 1,
        "observations": {
            "observation_count": 6,
            "operator_count": 2,
            "source_scale_preserved": True,
        },
    }


def test_nrm006_main_overwrites_stale_pass_report_with_safe_failure(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _namespace(repository_root)
    report_path = tmp_path / "acceptance_verification.json"
    report_path.write_text('{"status":"PASS"}\n', encoding="utf-8")
    function_globals = namespace["main"].__globals__

    def fail() -> None:
        raise namespace["AcceptanceError"]("bounded synthetic failure")

    monkeypatch.setitem(function_globals, "verify", fail)
    monkeypatch.setitem(function_globals, "REPORT_PATH", report_path)
    assert namespace["main"]() == 1
    assert json.loads(report_path.read_text(encoding="utf-8")) == {
        "error": "bounded synthetic failure",
        "status": "FAIL",
        "ticket_id": "NRM-006",
    }
