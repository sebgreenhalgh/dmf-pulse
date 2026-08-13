"""Recompute critical durable evidence facts and reject omissions or status-only claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXCLUSION = re.compile(
    r"pragma\s*:\s*no\s*(?:cover|branch)|coverage\s*:\s*(?:ignore|exclude)|no[-_ ]cover", re.I
)
ALEMBIC_HEAD = "20260807_0006"
FIXTURE_ID = "943094f5-1d10-5d96-b88b-d271464f3e48"
TEAM_ID = "cc1083fa-0c4a-59ab-b6c5-60c04f760782"
AS_OF = "2026-08-14T17:30:00Z"
NETWORK_CLAIM = (
    "the isolated installed-wheel public REPLAY external-ID-701 CLI produced zero measured "
    "non-loopback network attempts under this guard"
)
PUBLIC_COMMAND = (
    "dmf availability predict --fixture-external-provider synthetic_availability "
    "--fixture-external-id 701 --season-code 2026/27 --team-side HOME --as-of "
    "2026-08-14T17:30:00Z --model-key min007-baseline-v1 --seed MIN-007-COHERENCE-V1 "
    "--output json"
)
NETWORK_HOOKS = {
    "socket.socket.connect",
    "socket.socket.connect_ex",
    "socket.create_connection",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.gethostbyname_ex",
    "socket.getnameinfo",
}
RESOURCE_NAMES = {
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
}
IDENTITY_NAMES = {
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
}
WAIVERS: dict[str, tuple[list[int], list[list[int]]]] = {
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
REQUIRED = (
    "PLAN.md",
    "assurance_plan.json",
    "acceptance_ledger.json",
    "RESULT.md",
    "full_test_summary.json",
    "coverage.json",
    "coverage_summary.json",
    "math_core_manifest.json",
    "migration_report.json",
    "installed_wheel_report.json",
    "frozen_identity_report.json",
    "security_report.json",
    "audit_closure_history.md",
)
TRANSIENT = {
    "focused_core_coverage.json",
    "full_test_output.txt",
    "full_test_error.txt",
    "full_test_exit.txt",
    "full_test_launcher_pid.txt",
    "stage7_changed_files.txt",
    "stage7_diffstat.txt",
    "raw_stdout.txt",
    "raw_stderr.txt",
}
CRITICAL_ARTIFACTS = {
    "core_inventory": {
        "evidence/tickets/MIN-007H/math_core_manifest.json",
        "evidence/tickets/MIN-007H/coverage_summary.json",
    },
    "full_suite": {
        "evidence/tickets/MIN-007H/coverage.json",
        "evidence/tickets/MIN-007H/full_test_summary.json",
    },
    "migration_matrix": {"evidence/tickets/MIN-007H/migration_report.json"},
    "wheel_build": {"dist/dmf_pulse-0.2.0-py3-none-any.whl"},
    "installed_wheel": {"evidence/tickets/MIN-007H/installed_wheel_report.json"},
    "frozen_identities": {"evidence/tickets/MIN-007H/frozen_identity_report.json"},
    "security_portability": {"evidence/tickets/MIN-007H/security_report.json"},
}


class EvidenceError(ValueError):
    """A fail-closed final evidence validation error."""


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} is not an object")
    return value


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _record(ledger: dict[str, Any], gate_id: str) -> dict[str, Any]:
    records = ledger.get("records")
    if not isinstance(records, list):
        raise EvidenceError("ledger records are missing")
    matches = [item for item in records if isinstance(item, dict) and item.get("id") == gate_id]
    if len(matches) != 1:
        raise EvidenceError(f"ledger gate is missing or duplicated: {gate_id}")
    return matches[0]


def _validate_full_suite(evidence: Path) -> None:
    summary = _load(evidence / "full_test_summary.json", "full-test summary")
    coverage = _load(evidence / "coverage.json", "coverage")
    totals = coverage.get("totals")
    if not isinstance(totals, dict):
        raise EvidenceError("coverage totals are missing")
    tests_passed = summary.get("tests_passed")
    tests_skipped = summary.get("tests_skipped")
    percent = totals.get("percent_covered")
    if (
        summary.get("status") != "PASS"
        or summary.get("full_suite_gate") != "full_suite"
        or type(tests_passed) is not int
        or tests_passed <= 0
        or type(tests_skipped) is not int
        or tests_skipped != 0
        or isinstance(percent, bool)
        or not isinstance(percent, (int, float))
        or percent < 90.0
        or summary.get("coverage") != totals
    ):
        raise EvidenceError("full-suite result/coverage is not accepted")


def _validate_migration(evidence: Path) -> None:
    migration = _load(evidence / "migration_report.json", "migration report")
    required_gates = {
        "alembic_upgrade",
        "integrations",
        "migration_matrix",
        "alembic_check",
        "alembic_heads",
    }
    gates = migration.get("gates")
    if (
        migration.get("status") != "PASS"
        or migration.get("alembic_head") != ALEMBIC_HEAD
        or not isinstance(gates, list)
        or set(gates) != required_gates
        or len(gates) != len(required_gates)
    ):
        raise EvidenceError("migration evidence is not accepted")


def _absolute_isolated_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return path.is_absolute() and not path.resolve().is_relative_to(ROOT.resolve())


def _validate_installed_wheel(evidence: Path, artifact_root: Path) -> None:
    report = _load(evidence / "installed_wheel_report.json", "installed-wheel report")
    wheel = artifact_root / "dist/dmf_pulse-0.2.0-py3-none-any.whl"
    runtime = report.get("isolated_runtime")
    public = report.get("public_701")
    integrity = report.get("wheel_integrity")
    additional = report.get("additional_contexts")
    if (
        report.get("status") != "PASS"
        or report.get("wheel") != "dist/dmf_pulse-0.2.0-py3-none-any.whl"
        or not wheel.is_file()
        or not _is_sha(report.get("sha256"))
        or report.get("sha256") != hashlib.sha256(wheel.read_bytes()).hexdigest()
        or type(report.get("size")) is not int
        or report.get("size") != wheel.stat().st_size
        or not isinstance(report.get("python"), str)
        or not report["python"].startswith("3.13.")
        or not isinstance(runtime, dict)
        or not isinstance(public, dict)
        or not isinstance(integrity, dict)
        or not isinstance(additional, dict)
    ):
        raise EvidenceError("installed-wheel report is incomplete or inconsistent")
    if (
        runtime.get("cleaned_up") is not True
        or runtime.get("repository_source_on_sys_path") is not False
        or runtime.get("resource_count") != len(RESOURCE_NAMES)
        or not _absolute_isolated_path(runtime.get("current_working_directory"))
        or not _absolute_isolated_path(runtime.get("entry_point"))
        or not _absolute_isolated_path(runtime.get("import_path"))
        or not _absolute_isolated_path(runtime.get("interpreter"))
        or public.get("entry_point") != runtime.get("entry_point")
    ):
        raise EvidenceError("installed-wheel runtime was not isolated")
    if (
        public.get("command") != PUBLIC_COMMAND
        or public.get("exit_code") != 0
        or public.get("status") != "PROJECTED"
        or public.get("fixture_external_id") != 701
        or public.get("mapping_provider") != "synthetic_availability"
        or public.get("mapping_resolution_success") is not True
        or public.get("fixture_id") != FIXTURE_ID
        or public.get("team_id") != TEAM_ID
        or public.get("as_of") != AS_OF
        or public.get("projection_present") is not True
        or not _is_sha(public.get("result_sha256"))
        or not _is_sha(public.get("stdout_sha256"))
    ):
        raise EvidenceError("installed public 701 result is not accepted")
    resources = integrity.get("resources")
    record = integrity.get("record")
    if (
        integrity.get("status") != "PASS"
        or integrity.get("metadata_name") != "dmf-pulse"
        or integrity.get("metadata_version") != "0.2.0"
        or integrity.get("resource_count") != len(RESOURCE_NAMES)
        or not isinstance(resources, dict)
        or set(resources) != RESOURCE_NAMES
        or not all(
            isinstance(item, dict)
            and _is_sha(item.get("sha256"))
            and type(item.get("size")) is int
            and item["size"] > 0
            for item in resources.values()
        )
        or not isinstance(record, dict)
        or record.get("status") != "PASS"
        or type(record.get("entry_count")) is not int
        or record["entry_count"] <= len(RESOURCE_NAMES)
    ):
        raise EvidenceError("wheel resource/RECORD integrity evidence is not accepted")
    if additional.get("702") != {"exit_code": 0, "status": "PROJECTED"} or additional.get(
        "709"
    ) != {
        "error_code": "INSUFFICIENT_ELIGIBLE_SQUAD",
        "exit_code": 42,
        "status": "BLOCKED",
    }:
        raise EvidenceError("installed alternate/blocked context evidence is not accepted")


def _validate_identities(evidence: Path) -> None:
    report = _load(evidence / "frozen_identity_report.json", "frozen identities")
    identities = report.get("identities")
    if (
        report.get("status") != "PASS"
        or not isinstance(identities, dict)
        or set(identities) != IDENTITY_NAMES
    ):
        raise EvidenceError("frozen identity collection is missing or incomplete")
    for name, item in identities.items():
        if (
            not isinstance(item, dict)
            or item.get("status") != "PASS"
            or item.get("derived") is not True
            or not _is_sha(item.get("expected"))
            or item.get("observed") != item.get("expected")
        ):
            raise EvidenceError(f"frozen identity mismatch: {name}")


def _validate_security(evidence: Path) -> None:
    report = _load(evidence / "security_report.json", "security report")
    secret = report.get("secret_scan")
    portability = report.get("portable_source_scan")
    network = report.get("network")
    if report.get("status") != "PASS" or report.get("scope") != NETWORK_CLAIM:
        raise EvidenceError("security report status/scope is not accepted")
    if (
        not isinstance(secret, dict)
        or secret.get("status") != "PASS"
        or secret.get("exit_code") != 0
        or secret.get("finding_count") != 0
        or not _is_sha(secret.get("stdout_sha256"))
    ):
        raise EvidenceError("secret scan evidence is missing or failed")
    if (
        not isinstance(portability, dict)
        or type(portability.get("files_scanned")) is not int
        or portability["files_scanned"] <= 0
        or portability.get("violations") != {}
    ):
        raise EvidenceError("portability measurement is missing or failed")
    if (
        not isinstance(network, dict)
        or network.get("claim") != NETWORK_CLAIM
        or network.get("guard_active") is not True
        or not isinstance(network.get("guard_hooks"), list)
        or set(network["guard_hooks"]) != NETWORK_HOOKS
        or network.get("attempted_endpoints") != []
        or network.get("non_loopback_attempts") != []
        or network.get("non_loopback_count") != 0
        or network.get("command") != PUBLIC_COMMAND
        or network.get("exit_code") != 0
        or network.get("status") != "PROJECTED"
        or network.get("fixture_external_id") != 701
        or network.get("mapping_provider") != "synthetic_availability"
        or network.get("mapping_resolution_success") is not True
        or network.get("fixture_id") != FIXTURE_ID
        or network.get("team_id") != TEAM_ID
        or not _is_sha(network.get("result_sha256"))
        or not _is_sha(network.get("stdout_sha256"))
        or not _absolute_isolated_path(network.get("installed_interpreter"))
        or not _absolute_isolated_path(network.get("entry_point"))
    ):
        raise EvidenceError("installed public 701 network measurement is missing or failed")


def _validate_math_core(evidence: Path) -> None:
    manifest = _load(evidence / "math_core_manifest.json", "math-core manifest")
    coverage = _load(evidence / "coverage.json", "coverage")
    coverage_summary = _load(evidence / "coverage_summary.json", "coverage summary")
    modules = manifest.get("modules")
    files = coverage.get("files")
    if (
        manifest.get("status") != "PASS"
        or not isinstance(modules, dict)
        or set(modules) != set(WAIVERS)
        or not isinstance(files, dict)
    ):
        raise EvidenceError("math-core manifest is incomplete")
    for source_path, (lines, branches) in WAIVERS.items():
        item = modules[source_path]
        if not isinstance(item, dict) or EXCLUSION.search(
            (ROOT / source_path).read_text(encoding="utf-8")
        ):
            raise EvidenceError(f"math-core source/entry invalid: {source_path}")
        found = [
            value
            for key, value in files.items()
            if isinstance(key, str) and key.replace("\\", "/").endswith(source_path)
        ]
        reachable = item.get("reachable")
        if (
            len(found) != 1
            or not isinstance(found[0], dict)
            or found[0].get("excluded_lines") != []
            or found[0].get("missing_lines") != lines
            or found[0].get("missing_branches") != branches
            or item.get("excluded_lines") != []
            or item.get("raw_missing_lines") != lines
            or item.get("raw_missing_branches") != branches
            or not isinstance(reachable, dict)
            or reachable.get("covered_lines") != reachable.get("num_statements")
            or reachable.get("covered_branches") != reachable.get("num_branches")
        ):
            raise EvidenceError(f"math-core coverage/waiver mismatch: {source_path}")
    if (
        coverage_summary.get("status") != "PASS"
        or not isinstance(coverage_summary.get("totals"), dict)
        or coverage_summary.get("math_core") != modules
        or coverage_summary.get("overall_reachable") != manifest.get("overall_reachable")
    ):
        raise EvidenceError("coverage summary does not derive from durable raw coverage")


def validate(*, evidence: Path, artifact_root: Path) -> None:
    missing = [name for name in REQUIRED if not (evidence / name).is_file()]
    stale = [name for name in TRANSIENT if (evidence / name).exists()]
    if missing or stale:
        raise EvidenceError(f"missing={missing} stale={stale}")
    ledger_command = [
        sys.executable,
        str(ROOT / "evidence/tickets/MIN-007H/validate_acceptance_ledger.py"),
        "--ledger",
        str(evidence / "acceptance_ledger.json"),
        "--plan",
        str(evidence / "assurance_plan.json"),
        "--artifact-root",
        str(artifact_root),
    ]
    result = subprocess.run(ledger_command, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise EvidenceError(f"acceptance ledger validation failed: {detail}")
    ledger = _load(evidence / "acceptance_ledger.json", "acceptance ledger")
    plan = _load(evidence / "assurance_plan.json", "assurance plan")
    gates = plan.get("gates")
    if not isinstance(gates, list):
        raise EvidenceError("assurance plan gates are missing")
    declared = {
        gate.get("id"): set(gate.get("artifacts", []))
        for gate in gates
        if isinstance(gate, dict)
        and isinstance(gate.get("id"), str)
        and isinstance(gate.get("artifacts"), list)
    }
    if any(declared.get(gate_id) != artifacts for gate_id, artifacts in CRITICAL_ARTIFACTS.items()):
        raise EvidenceError("critical assurance artifact declarations are missing or changed")
    if _record(ledger, "full_suite").get("exit_code") != 0:
        raise EvidenceError("full-suite ledger gate failed")
    _validate_full_suite(evidence)
    _validate_migration(evidence)
    _validate_installed_wheel(evidence, artifact_root)
    _validate_identities(evidence)
    _validate_security(evidence)
    _validate_math_core(evidence)
    banned = ("C:" + "\\Users\\", "dmf-" + "pulse-context", "Codex" + "Packs")
    for path in evidence.glob("*.py"):
        if any(token in path.read_text(encoding="utf-8") for token in banned):
            raise EvidenceError(f"nonportable helper: {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--artifact-root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        validate(evidence=args.evidence, artifact_root=args.artifact_root)
    except (EvidenceError, OSError, UnicodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print("PASS: critical final evidence and declared artifacts recomputed fail closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
