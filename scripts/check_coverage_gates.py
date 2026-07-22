"""Enforce the independent overall and rules-package branch coverage gates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COVERAGE = ROOT / "evidence/tickets/RUL-002/coverage.json"


def _percentage(covered: int, total: int) -> float:
    return 100.0 * covered / total if total else 0.0


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
    rules_covered = 0
    rules_total = 0
    for filename, record in files.items():
        normalized = str(filename).replace("\\", "/")
        summary = record.get("summary") if isinstance(record, dict) else None
        if "/dmf_pulse/rules/" not in f"/{normalized}" or not isinstance(summary, dict):
            continue
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
            raise ValueError("rules coverage record lacks integer branch counts")
        rules_covered += covered
        rules_total += total
    rules_percent = _percentage(rules_covered, rules_total)
    errors = []
    if float(overall) < 90.0:
        errors.append("overall production-package branch coverage is below 90 percent")
    if rules_total == 0 or rules_percent < 95.0:
        errors.append("dmf_pulse.rules branch coverage is below 95 percent")
    return {
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
