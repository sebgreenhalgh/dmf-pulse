#!/usr/bin/env python3
"""Validate Stage-9 coverage counts and percentages without trusting prose evidence."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

REQUIRED_MODULES = (
    "src/dmf_pulse/fpl_points/allocation.py",
    "src/dmf_pulse/fpl_points/artifacts.py",
    "src/dmf_pulse/fpl_points/evaluation.py",
    "src/dmf_pulse/fpl_points/gameweek.py",
    "src/dmf_pulse/fpl_points/gameweek_summaries.py",
    "src/dmf_pulse/fpl_points/models.py",
    "src/dmf_pulse/fpl_points/monte_carlo.py",
    "src/dmf_pulse/fpl_points/rules_adapter.py",
    "src/dmf_pulse/fpl_points/seed.py",
    "src/dmf_pulse/fpl_points/service.py",
    "src/dmf_pulse/fpl_points/summaries.py",
    "src/dmf_pulse/fpl_points/upstream.py",
)
BRANCH_REQUIRED = {
    "src/dmf_pulse/fpl_points/allocation.py",
    "src/dmf_pulse/fpl_points/gameweek.py",
    "src/dmf_pulse/fpl_points/models.py",
    "src/dmf_pulse/fpl_points/rules_adapter.py",
    "src/dmf_pulse/fpl_points/seed.py",
    "src/dmf_pulse/fpl_points/service.py",
    "src/dmf_pulse/fpl_points/summaries.py",
    "src/dmf_pulse/fpl_points/upstream.py",
}


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _percent(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and 0.0 <= result <= 100.0 else None


def _validate_summary(
    summary: dict[str, Any], *, label: str, branch_required: bool
) -> tuple[list[str], float | None, float | None]:
    errors: list[str] = []
    statements = _integer(summary.get("num_statements"))
    covered_lines = _integer(summary.get("covered_lines"))
    missing_lines = _integer(summary.get("missing_lines"))
    reported_line = _percent(summary.get("percent_statements_covered"))
    if statements is None or statements <= 0:
        errors.append(f"COVERAGE_ZERO_STATEMENTS:{label}")
        line_percent = None
    elif covered_lines is None or missing_lines is None:
        errors.append(f"COVERAGE_LINE_COUNTS_MALFORMED:{label}")
        line_percent = None
    else:
        if covered_lines + missing_lines != statements:
            errors.append(f"COVERAGE_LINE_COUNTS_INCONSISTENT:{label}")
        line_percent = 100.0 * covered_lines / statements
        if reported_line is None:
            errors.append(f"COVERAGE_LINE_PERCENT_MALFORMED:{label}")
        elif not math.isclose(reported_line, line_percent, rel_tol=0.0, abs_tol=1e-9):
            errors.append(f"COVERAGE_LINE_PERCENT_INCONSISTENT:{label}")

    branches = _integer(summary.get("num_branches"))
    covered_branches = _integer(summary.get("covered_branches"))
    missing_branches = _integer(summary.get("missing_branches"))
    reported_branch = _percent(summary.get("percent_branches_covered"))
    branch_percent: float | None = None
    if branches is None or covered_branches is None or missing_branches is None:
        if branch_required:
            errors.append(f"COVERAGE_BRANCH_DATA_MISSING:{label}")
    elif branches == 0:
        if branch_required:
            errors.append(f"COVERAGE_BRANCHES_ZERO:{label}")
    else:
        if covered_branches + missing_branches != branches:
            errors.append(f"COVERAGE_BRANCH_COUNTS_INCONSISTENT:{label}")
        branch_percent = 100.0 * covered_branches / branches
        if reported_branch is None:
            errors.append(f"COVERAGE_BRANCH_PERCENT_MALFORMED:{label}")
        elif not math.isclose(reported_branch, branch_percent, rel_tol=0.0, abs_tol=1e-9):
            errors.append(f"COVERAGE_BRANCH_PERCENT_INCONSISTENT:{label}")

    combined = _percent(summary.get("percent_covered"))
    if (
        statements is not None
        and statements > 0
        and covered_lines is not None
        and branches is not None
        and covered_branches is not None
    ):
        denominator = statements + branches
        expected_combined = 100.0 * (covered_lines + covered_branches) / denominator
        if combined is None:
            errors.append(f"COVERAGE_COMBINED_PERCENT_MALFORMED:{label}")
        elif not math.isclose(combined, expected_combined, rel_tol=0.0, abs_tol=1e-9):
            errors.append(f"COVERAGE_COMBINED_PERCENT_INCONSISTENT:{label}")
    return errors, line_percent, branch_percent


def validate_coverage(
    payload: dict[str, Any], *, minimum_line_percent: float, minimum_branch_percent: float
) -> list[str]:
    files = payload.get("files")
    totals = payload.get("totals")
    if not isinstance(files, dict) or not isinstance(totals, dict):
        return ["COVERAGE_JSON_MALFORMED"]
    normalized_files = {str(key).replace("\\", "/"): value for key, value in files.items()}
    errors, _, _ = _validate_summary(totals, label="TOTALS", branch_required=True)
    for module in REQUIRED_MODULES:
        record = normalized_files.get(module)
        if not isinstance(record, dict):
            errors.append(f"COVERAGE_MODULE_MISSING:{module}")
            continue
        summary = record.get("summary")
        if not isinstance(summary, dict):
            errors.append(f"COVERAGE_SUMMARY_MALFORMED:{module}")
            continue
        summary_errors, line_percent, branch_percent = _validate_summary(
            summary,
            label=module,
            branch_required=module in BRANCH_REQUIRED,
        )
        errors.extend(summary_errors)
        if line_percent is not None and line_percent < minimum_line_percent:
            errors.append(f"COVERAGE_LINE_BELOW_GATE:{module}:{line_percent:.2f}")
        if (
            module in BRANCH_REQUIRED
            and branch_percent is not None
            and branch_percent < minimum_branch_percent
        ):
            errors.append(f"COVERAGE_BRANCH_BELOW_GATE:{module}:{branch_percent:.2f}")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--minimum-line-percent", type=float, default=85.0)
    parser.add_argument("--minimum-branch-percent", type=float, default=70.0)
    args = parser.parse_args()
    try:
        payload = json.loads(args.coverage_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = {}
    errors = validate_coverage(
        payload,
        minimum_line_percent=args.minimum_line_percent,
        minimum_branch_percent=args.minimum_branch_percent,
    )
    print(
        json.dumps(
            {
                "schema_version": "pts-009-coverage-assurance-v1",
                "status": "PASS" if not errors else "FAIL",
                "errors": errors,
            },
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
