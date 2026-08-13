"""Mutation proofs for the MIN-007H3 final assurance validators."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
RESOURCE_NAMES = (
    "MIN-007/canonical_history.json",
    "MIN-007/external_mapping_plan.json",
    "MIN-007/training_dataset.json",
    "MIN-007G/evaluation_dataset.json",
    "MIN-007G/minutes_baseline_policy.json",
    "MIN-007G/contexts/goalkeeper.json",
    "MIN-007G/contexts/hard_ineligible.json",
    "MIN-007G/contexts/high_rotation.json",
    "MIN-007G/contexts/insufficient_eligible_squad.json",
    "MIN-007G/contexts/new_manager.json",
    "MIN-007G/contexts/new_signing.json",
    "MIN-007G/contexts/promoted_team.json",
    "MIN-007G/contexts/rare_bench_60_plus.json",
    "MIN-007G/contexts/stable_xi.json",
)
IDENTITY_NAMES = (
    "B_dataset",
    "C_role",
    "D_minutes",
    "E_stable_scenario",
    "F_dataset_registry",
    "F_model_registry",
    "F_prediction_signature",
    "G_evaluation",
    "G_model_artifact",
    "G_prediction_registry",
    "current_probability_schema",
    "historical_nrm_probability_schema",
    "mapping_plan",
)
WAIVERS = {
    "src/dmf_pulse/availability/decimal_integrity.py": ([16], [[15, 16]]),
    "src/dmf_pulse/availability/role_model.py": (
        [335, 336, 351, 354, 409, 558, 559],
        [[350, 351], [353, 354], [408, 409]],
    ),
    "src/dmf_pulse/availability/minutes.py": (
        [591, 594, 595, 596, 597, 670, 683, 684, 685, 686],
        [[590, 591], [595, 596], [595, 597], [669, 670], [684, 685], [684, 686]],
    ),
    "src/dmf_pulse/availability/lineup.py": (
        [221, 223, 225, 344, 348, 350, 453, 719, 720, 721, 722],
        [
            [220, 221],
            [222, 223],
            [224, 225],
            [343, 344],
            [347, 348],
            [349, 350],
            [447, 453],
            [720, 721],
            [720, 722],
        ],
    ),
    "src/dmf_pulse/availability/projection.py": ([], []),
    "src/dmf_pulse/availability/pipeline.py": ([105], [[104, 105]]),
}
PUBLIC_COMMAND = (
    "dmf availability predict --fixture-external-provider synthetic_availability "
    "--fixture-external-id 701 --season-code 2026/27 --team-side HOME --as-of "
    "2026-08-14T17:30:00Z --model-key min007-baseline-v1 --seed MIN-007-COHERENCE-V1 "
    "--output json"
)
NETWORK_CLAIM = (
    "the isolated installed-wheel public REPLAY external-ID-701 CLI produced zero measured "
    "non-loopback network attempts under this guard"
)
NETWORK_HOOKS = [
    "socket.socket.connect",
    "socket.socket.connect_ex",
    "socket.create_connection",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.gethostbyname_ex",
    "socket.getnameinfo",
]


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_valid_evidence(repository_root: Path, temporary_root: Path) -> tuple[Path, Path]:
    artifact_root = temporary_root / "artifact-root"
    evidence = artifact_root / "evidence/tickets/MIN-007H"
    evidence.mkdir(parents=True)
    source = repository_root / "evidence/tickets/MIN-007H"
    shutil.copyfile(source / "assurance_plan.json", evidence / "assurance_plan.json")
    for name in ("PLAN.md", "RESULT.md", "audit_closure_history.md"):
        (evidence / name).write_text(f"# {name}\n", encoding="utf-8")

    totals = {
        "covered_branches": 95,
        "covered_lines": 95,
        "excluded_lines": 0,
        "missing_branches": 5,
        "missing_lines": 5,
        "num_branches": 100,
        "num_partial_branches": 0,
        "num_statements": 100,
        "percent_branches_covered": 95.0,
        "percent_branches_covered_display": "95",
        "percent_covered": 95.0,
        "percent_covered_display": "95",
        "percent_statements_covered": 95.0,
        "percent_statements_covered_display": "95",
    }
    coverage_files = {
        source_path: {
            "excluded_lines": [],
            "missing_branches": branches,
            "missing_lines": lines,
        }
        for source_path, (lines, branches) in WAIVERS.items()
    }
    _write(evidence / "coverage.json", {"files": coverage_files, "totals": totals})
    modules = {
        source_path: {
            "excluded_lines": [],
            "raw_missing_branches": branches,
            "raw_missing_lines": lines,
            "reachable": {
                "covered_branches": 1,
                "covered_lines": 1,
                "num_branches": 1,
                "num_statements": 1,
            },
        }
        for source_path, (lines, branches) in WAIVERS.items()
    }
    reachable = {
        "covered_branches": len(modules),
        "covered_lines": len(modules),
        "num_branches": len(modules),
        "num_statements": len(modules),
    }
    _write(
        evidence / "math_core_manifest.json",
        {"modules": modules, "overall_reachable": reachable, "status": "PASS"},
    )
    _write(
        evidence / "coverage_summary.json",
        {
            "math_core": modules,
            "overall_reachable": reachable,
            "status": "PASS",
            "totals": totals,
        },
    )
    _write(
        evidence / "frozen_identity_report.json",
        {
            "identities": {
                name: {
                    "derived": True,
                    "expected": hashlib.sha256(name.encode()).hexdigest(),
                    "observed": hashlib.sha256(name.encode()).hexdigest(),
                    "status": "PASS",
                }
                for name in IDENTITY_NAMES
            },
            "status": "PASS",
        },
    )
    _write(
        evidence / "full_test_summary.json",
        {
            "coverage": totals,
            "full_suite_gate": "full_suite",
            "status": "PASS",
            "tests_passed": 1,
            "tests_skipped": 0,
        },
    )
    _write(
        evidence / "migration_report.json",
        {
            "alembic_head": "20260807_0006",
            "gates": [
                "alembic_upgrade",
                "integrations",
                "migration_matrix",
                "alembic_check",
                "alembic_heads",
            ],
            "status": "PASS",
        },
    )
    wheel = artifact_root / "dist/dmf_pulse-0.2.0-py3-none-any.whl"
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"synthetic exact-wheel artifact for validator mutation tests")
    runtime = (temporary_root / "cleaned-isolated-runtime").resolve()
    entry_point = runtime / "Scripts/dmf.exe"
    interpreter = runtime / "Scripts/python.exe"
    import_path = runtime / "Lib/site-packages/dmf_pulse/__init__.py"
    fixture_sha = hashlib.sha256(b"fixture").hexdigest()
    result_sha = hashlib.sha256(b"result").hexdigest()
    stdout_sha = hashlib.sha256(b"stdout").hexdigest()
    resources = {
        name: {"sha256": hashlib.sha256(name.encode()).hexdigest(), "size": 1}
        for name in RESOURCE_NAMES
    }
    _write(
        evidence / "installed_wheel_report.json",
        {
            "additional_contexts": {
                "702": {"exit_code": 0, "status": "PROJECTED"},
                "709": {
                    "error_code": "INSUFFICIENT_ELIGIBLE_SQUAD",
                    "exit_code": 42,
                    "status": "BLOCKED",
                },
            },
            "isolated_runtime": {
                "cleaned_up": True,
                "current_working_directory": str(runtime),
                "entry_point": str(entry_point),
                "import_path": str(import_path),
                "interpreter": str(interpreter),
                "repository_source_on_sys_path": False,
                "resource_count": len(RESOURCE_NAMES),
            },
            "network_guard": None,
            "public_701": {
                "as_of": "2026-08-14T17:30:00Z",
                "command": PUBLIC_COMMAND,
                "entry_point": str(entry_point),
                "exit_code": 0,
                "fixture_external_id": 701,
                "fixture_id": "943094f5-1d10-5d96-b88b-d271464f3e48",
                "mapping_provider": "synthetic_availability",
                "mapping_resolution_success": True,
                "projection_present": True,
                "result_sha256": result_sha,
                "status": "PROJECTED",
                "stdout_sha256": stdout_sha,
                "team_id": "cc1083fa-0c4a-59ab-b6c5-60c04f760782",
            },
            "python": "3.13.9",
            "sha256": _sha(wheel),
            "size": wheel.stat().st_size,
            "status": "PASS",
            "wheel": "dist/dmf_pulse-0.2.0-py3-none-any.whl",
            "wheel_integrity": {
                "metadata_name": "dmf-pulse",
                "metadata_version": "0.2.0",
                "record": {
                    "entry_count": len(RESOURCE_NAMES) + 1,
                    "record_path": "dmf_pulse-0.2.0.dist-info/RECORD",
                    "status": "PASS",
                },
                "resource_count": len(RESOURCE_NAMES),
                "resources": resources,
                "status": "PASS",
            },
        },
    )
    _write(
        evidence / "security_report.json",
        {
            "network": {
                "attempted_endpoints": [],
                "claim": NETWORK_CLAIM,
                "command": PUBLIC_COMMAND,
                "entry_point": str(entry_point),
                "exit_code": 0,
                "fixture_external_id": 701,
                "fixture_id": "943094f5-1d10-5d96-b88b-d271464f3e48",
                "guard_active": True,
                "guard_hooks": NETWORK_HOOKS,
                "installed_interpreter": str(interpreter),
                "mapping_provider": "synthetic_availability",
                "mapping_resolution_success": True,
                "non_loopback_attempts": [],
                "non_loopback_count": 0,
                "result_sha256": result_sha,
                "status": "PROJECTED",
                "stdout_sha256": stdout_sha,
                "team_id": "cc1083fa-0c4a-59ab-b6c5-60c04f760782",
            },
            "portable_source_scan": {"files_scanned": 1, "violations": {}},
            "scope": NETWORK_CLAIM,
            "secret_scan": {
                "exit_code": 0,
                "finding_count": 0,
                "status": "PASS",
                "stdout_sha256": fixture_sha,
            },
            "status": "PASS",
        },
    )

    plan_path = evidence / "assurance_plan.json"
    plan = _json(plan_path)
    records = []
    for number, gate in enumerate(plan["gates"], 1):
        artifacts = {}
        for relative in gate["artifacts"]:
            path = artifact_root / relative
            artifacts[relative] = {"sha256": _sha(path), "size": path.stat().st_size}
        records.append(
            {
                "artifacts": artifacts,
                "command": gate["command"],
                "duration_seconds": 0.001,
                "end": "2026-08-13T12:00:00.001000Z",
                "exit_code": 0,
                "id": gate["id"],
                "number": number,
                "output_summary": "",
                "start": "2026-08-13T12:00:00Z",
                "status": "PASS",
                "stderr_sha256": EMPTY_SHA256,
                "stdout_sha256": EMPTY_SHA256,
            }
        )
    _write(
        evidence / "acceptance_ledger.json",
        {
            "contract": plan["contract"],
            "gate_count": len(plan["gates"]),
            "plan_sha256": _sha(plan_path),
            "records": records,
            "scope": "PRE-COMMIT gates only; post-commit archive commands are excluded.",
            "status": "PASS",
        },
    )
    return artifact_root, evidence


def _run_ledger(
    repository_root: Path, artifact_root: Path, evidence: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(repository_root / "evidence/tickets/MIN-007H/validate_acceptance_ledger.py"),
            "--ledger",
            str(evidence / "acceptance_ledger.json"),
            "--plan",
            str(evidence / "assurance_plan.json"),
            "--artifact-root",
            str(artifact_root),
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_final(
    repository_root: Path, artifact_root: Path, evidence: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(repository_root / "evidence/tickets/MIN-007H/validate_final_evidence.py"),
            "--evidence",
            str(evidence),
            "--artifact-root",
            str(artifact_root),
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _refresh_artifact(evidence: Path, artifact_root: Path, relative: str) -> None:
    ledger_path = evidence / "acceptance_ledger.json"
    ledger = _json(ledger_path)
    matches = [record for record in ledger["records"] if relative in record["artifacts"]]
    assert len(matches) == 1
    path = artifact_root / relative
    matches[0]["artifacts"][relative] = {"sha256": _sha(path), "size": path.stat().st_size}
    _write(ledger_path, ledger)


def test_hardened_validators_accept_a_complete_mechanical_fixture(
    repository_root: Path, tmp_path: Path
) -> None:
    artifact_root, evidence = _build_valid_evidence(repository_root, tmp_path)
    assert _run_ledger(repository_root, artifact_root, evidence).returncode == 0
    result = _run_final(repository_root, artifact_root, evidence)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize(
    "mutation", ["non_hex_sha", "missing_summary", "missing_artifacts", "artifact_mismatch"]
)
def test_ledger_validator_rejects_structural_and_artifact_mutations(
    repository_root: Path, tmp_path: Path, mutation: str
) -> None:
    artifact_root, evidence = _build_valid_evidence(repository_root, tmp_path)
    ledger_path = evidence / "acceptance_ledger.json"
    ledger = _json(ledger_path)
    if mutation == "non_hex_sha":
        ledger["records"][0]["stdout_sha256"] = "z" * 64
    elif mutation == "missing_summary":
        ledger["records"][0].pop("output_summary")
    elif mutation == "missing_artifacts":
        full = next(record for record in ledger["records"] if record["id"] == "full_suite")
        full["artifacts"] = {}
    else:
        full = next(record for record in ledger["records"] if record["id"] == "full_suite")
        entry = full["artifacts"]["evidence/tickets/MIN-007H/coverage.json"]
        entry["sha256"] = "0" * 64
        entry["size"] += 1
    _write(ledger_path, ledger)
    assert _run_ledger(repository_root, artifact_root, evidence).returncode != 0


@pytest.mark.parametrize(
    "mutation",
    [
        "full_test_fail",
        "migration_fail",
        "installed_fail",
        "installed_public_missing",
        "identities_empty",
        "secret_missing",
        "portability_missing",
        "network_missing",
        "non_loopback_attempt",
    ],
)
def test_final_validator_rejects_critical_evidence_mutations_even_with_fresh_artifact_hash(
    repository_root: Path, tmp_path: Path, mutation: str
) -> None:
    artifact_root, evidence = _build_valid_evidence(repository_root, tmp_path)
    paths = {
        "full_test_fail": "full_test_summary.json",
        "migration_fail": "migration_report.json",
        "installed_fail": "installed_wheel_report.json",
        "installed_public_missing": "installed_wheel_report.json",
        "identities_empty": "frozen_identity_report.json",
        "secret_missing": "security_report.json",
        "portability_missing": "security_report.json",
        "network_missing": "security_report.json",
        "non_loopback_attempt": "security_report.json",
    }
    name = paths[mutation]
    path = evidence / name
    value = _json(path)
    if mutation in {"full_test_fail", "migration_fail", "installed_fail"}:
        value["status"] = "FAIL"
    elif mutation == "installed_public_missing":
        value.pop("public_701")
    elif mutation == "identities_empty":
        value["identities"] = {}
    elif mutation == "secret_missing":
        value.pop("secret_scan")
    elif mutation == "portability_missing":
        value.pop("portable_source_scan")
    elif mutation == "network_missing":
        value.pop("network")
    else:
        value["network"]["non_loopback_count"] = 1
        value["network"]["non_loopback_attempts"] = [
            {"host": "203.0.113.1", "kind": "socket.socket.connect", "port": 443}
        ]
    _write(path, value)
    relative = f"evidence/tickets/MIN-007H/{name}"
    _refresh_artifact(evidence, artifact_root, relative)
    assert _run_ledger(repository_root, artifact_root, evidence).returncode == 0
    assert _run_final(repository_root, artifact_root, evidence).returncode != 0
