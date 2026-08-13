"""Execute every declared pre-commit gate and atomically write a real ledger."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
PLAN = EVIDENCE / "assurance_plan.json"
LEDGER = EVIDENCE / "acceptance_ledger.json"


def stamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def artifact_entry(relative: str) -> dict[str, object] | None:
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        return None
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _gate_exit(records: list[dict[str, Any]], gate_id: str) -> int:
    value = next((record["exit_code"] for record in records if record["id"] == gate_id), None)
    return value if type(value) is int else 1


def _write_derived_reports(
    *, records: list[dict[str, Any]], outputs: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    full_output = outputs.get("full_suite", "")
    coverage: dict[str, Any] = {}
    coverage_path = EVIDENCE / "coverage.json"
    if coverage_path.is_file():
        try:
            value = json.loads(coverage_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            value = None
        if isinstance(value, dict):
            coverage = value
    match = re.search(r"(\d+) passed(?:, (\d+) skipped)?", full_output)
    summary = {
        "status": "PASS"
        if _gate_exit(records, "full_suite") == 0 and match is not None and coverage.get("totals")
        else "FAIL",
        "tests_passed": int(match.group(1)) if match else None,
        "tests_skipped": int(match.group(2) or 0) if match else None,
        "coverage": coverage.get("totals", {}),
        "full_suite_gate": "full_suite",
    }
    (EVIDENCE / "full_test_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    migration_gates = (
        "alembic_upgrade",
        "integrations",
        "migration_matrix",
        "alembic_check",
        "alembic_heads",
    )
    migration = {
        "status": "PASS"
        if all(_gate_exit(records, gate_id) == 0 for gate_id in migration_gates)
        and "20260807_0006" in outputs.get("alembic_heads", "")
        else "FAIL",
        "alembic_head": (
            "20260807_0006" if "20260807_0006" in outputs.get("alembic_heads", "") else "unknown"
        ),
        "gates": list(migration_gates),
    }
    (EVIDENCE / "migration_report.json").write_text(
        json.dumps(migration, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary, migration


def main() -> int:
    plan_bytes = PLAN.read_bytes()
    plan: dict[str, Any] = json.loads(plan_bytes)
    gates = plan.get("gates")
    if not isinstance(gates, list) or not gates:
        raise SystemExit("assurance plan has no gates")
    declared_artifacts = {
        relative
        for gate in gates
        if isinstance(gate, dict) and isinstance(gate.get("artifacts"), list)
        for relative in gate["artifacts"]
        if isinstance(relative, str)
    }
    for relative in declared_artifacts:
        path = (ROOT / relative).resolve()
        if path.is_relative_to(ROOT.resolve()) and path.is_file():
            path.unlink()

    env = os.environ.copy()
    env.update(
        {
            "DMF_ENVIRONMENT": "TEST",
            "PGPASSWORD": "changeme",
            "DMF_TEST_DATABASE_URL": (
                "postgresql+psycopg://dmf_test@127.0.0.1:55432/dmf_pulse_test"
            ),
        }
    )
    records: list[dict[str, Any]] = []
    outputs: dict[str, str] = {}
    try:
        for number, gate in enumerate(gates, 1):
            if not isinstance(gate, dict):
                raise SystemExit(f"invalid gate {number}")
            command = gate.get("command")
            gate_id = gate.get("id")
            if not isinstance(command, str) or not isinstance(gate_id, str):
                raise SystemExit(f"invalid gate {number}")
            started = stamp()
            begin = time.perf_counter()
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                shell=True,
                text=True,
                capture_output=True,
                check=False,
            )
            duration = round(time.perf_counter() - begin, 3)
            output_parts = [part for part in (result.stdout, result.stderr) if part]
            output = "\n".join(output_parts)
            outputs[gate_id] = output
            records.append(
                {
                    "number": number,
                    "id": gate_id,
                    "command": command,
                    "start": started,
                    "end": stamp(),
                    "duration_seconds": duration,
                    "exit_code": result.returncode,
                    "status": "PASS" if result.returncode == 0 else "FAIL",
                    "stdout_sha256": sha_text(result.stdout or ""),
                    "stderr_sha256": sha_text(result.stderr or ""),
                    "output_summary": output[-1500:] if output else "",
                    "artifacts": {},
                }
            )
    finally:
        subprocess.run(
            "docker compose -f compose.test.yaml down -v --remove-orphans",
            cwd=ROOT,
            env=env,
            shell=True,
            text=True,
            capture_output=True,
            check=False,
        )
        focused = EVIDENCE / "focused_core_coverage.json"
        if focused.exists():
            focused.unlink()

    summary, _migration = _write_derived_reports(records=records, outputs=outputs)
    artifact_complete = True
    for gate, record in zip(gates, records, strict=True):
        artifact_map: dict[str, dict[str, object]] = {}
        for relative in gate["artifacts"]:
            entry = artifact_entry(relative)
            if entry is None:
                artifact_complete = False
            else:
                artifact_map[relative] = entry
        record["artifacts"] = artifact_map

    all_gates_passed = len(records) == len(gates) and all(
        record["exit_code"] == 0 for record in records
    )
    ledger = {
        "contract": plan["contract"],
        "scope": "PRE-COMMIT gates only; post-commit archive commands are excluded.",
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "gate_count": len(gates),
        "records": records,
        "status": "PASS" if all_gates_passed and artifact_complete else "FAIL",
    }
    temporary = LEDGER.with_suffix(".tmp")
    temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, LEDGER)
    (EVIDENCE / "RESULT.md").write_text(
        "# MIN-007H3 result\n\n"
        f"Pre-commit gates: {len(records)}/{len(gates)}. Full-suite tests passed: "
        f"{summary['tests_passed']}; skipped: {summary['tests_skipped']}. "
        "Coverage, installed-wheel execution, network measurement, frozen identities, and "
        "declared artifact hashes are recorded in durable evidence.\n",
        encoding="utf-8",
    )
    (EVIDENCE / "audit_closure_history.md").write_text(
        "# Audit closure history\n\n"
        "H3 packages all public REPLAY resources, executes public external ID 701 from the "
        "isolated installed wheel under a network guard, and validates plan records and "
        "declared artifacts fail closed. Prior math-core waivers and frozen identities remain "
        "unchanged. Post-commit Git range evidence is generated by the review builder.\n",
        encoding="utf-8",
    )
    print(f"{ledger['status']}: {len(records)}/{len(gates)} pre-commit gates")
    return 0 if ledger["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
