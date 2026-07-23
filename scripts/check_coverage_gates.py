"""Enforce DAT-003's independent production-package branch coverage gates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COVERAGE = ROOT / "evidence/tickets/DAT-003/coverage.json"
CRITICAL_ORACLES = (
    "schema catalog SHA-256 oracle",
    "temporal boundary and double-supersession oracles",
    "independent-connection overlap race oracles",
    "immutable point-observation mutation oracles",
    "rules activation and registry hash-mutation oracles",
)


def _percentage(covered: int, total: int) -> float:
    return 100.0 * covered / total if total else 0.0


def _scope_branches(files: dict[str, Any], scopes: tuple[str, ...], label: str) -> tuple[int, int]:
    covered_total = 0
    branch_total = 0
    for filename, record in files.items():
        normalized = str(filename).replace("\\", "/")
        if not any(f"/dmf_pulse/{scope}/" in f"/{normalized}" for scope in scopes):
            continue
        summary = record.get("summary") if isinstance(record, dict) else None
        if not isinstance(summary, dict):
            raise ValueError(f"{label} coverage record lacks a summary")
        covered = summary.get("covered_branches")
        total = summary.get("num_branches")
        if (
            not isinstance(covered, int)
            or isinstance(covered, bool)
            or not isinstance(total, int)
            or isinstance(total, bool)
            or covered < 0
            or total < 0
            or covered > total
        ):
            raise ValueError(f"{label} coverage record lacks integer branch counts")
        covered_total += covered
        branch_total += total
    return covered_total, branch_total


def check_coverage(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("coverage JSON is unavailable or malformed") from exc
    totals = value.get("totals") if isinstance(value, dict) else None
    files = value.get("files") if isinstance(value, dict) else None
    if not isinstance(totals, dict) or not isinstance(files, dict):
        raise ValueError("coverage JSON lacks totals or files")
    overall = totals.get("percent_branches_covered")
    if (
        not isinstance(overall, (int, float))
        or isinstance(overall, bool)
        or not math.isfinite(float(overall))
    ):
        raise ValueError("coverage JSON lacks overall branch coverage")
    rules_covered, rules_total = _scope_branches(files, ("rules",), "rules")
    database_covered, database_total = _scope_branches(
        files, ("data_model", "database"), "data-model/database"
    )
    rules_percent = _percentage(rules_covered, rules_total)
    database_percent = _percentage(database_covered, database_total)
    errors = []
    if float(overall) < 90.0:
        errors.append("overall production-package branch coverage is below 90 percent")
    if rules_total == 0 or rules_percent < 98.0:
        errors.append("dmf_pulse.rules branch coverage is below 98 percent")
    if database_total == 0 or database_percent < 92.0:
        errors.append("dmf_pulse.data_model/database branch coverage is below 92 percent")
    return {
        "critical_gate": "EXPLICIT_MUTATION_ORACLE_EVIDENCE",
        "critical_oracles": list(CRITICAL_ORACLES),
        "data_model_database_branch_coverage_percent": round(database_percent, 2),
        "data_model_database_branches_covered": database_covered,
        "data_model_database_branches_total": database_total,
        "errors": errors,
        "ok": not errors,
        "overall_branch_coverage_percent": round(float(overall), 2),
        "rules_branch_coverage_percent": round(rules_percent, 2),
        "rules_branches_covered": rules_covered,
        "rules_branches_total": rules_total,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_COVERAGE)
    arguments = parser.parse_args()
    try:
        report = check_coverage(arguments.path)
    except ValueError as exc:
        report = {"errors": [str(exc)], "ok": False}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
