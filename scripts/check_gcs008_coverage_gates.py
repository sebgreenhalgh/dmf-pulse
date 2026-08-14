"""Fail closed unless measured GCS-008 coverage clears the stage gates."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

SOURCE_PREFIX = "src/dmf_pulse/football_events/"
CLI_PATH = "src/dmf_pulse/cli/events.py"
CRITICAL_FILES = {
    "src/dmf_pulse/football_events/_decimal.py",
    "src/dmf_pulse/football_events/coherence.py",
    "src/dmf_pulse/football_events/market_constraints.py",
    "src/dmf_pulse/football_events/poisson.py",
    "src/dmf_pulse/football_events/score_distribution.py",
    "src/dmf_pulse/football_events/score_projection.py",
}
AGGREGATE_STATEMENT_MINIMUM = 90.0
AGGREGATE_BRANCH_MINIMUM = 80.0
CRITICAL_STATEMENT_MINIMUM = 90.0
CRITICAL_BRANCH_MINIMUM = 80.0


class CoverageGateError(ValueError):
    """Coverage input is absent, malformed, or below a mandatory threshold."""


def _percentage(covered: int, total: int) -> float:
    if total <= 0:
        raise CoverageGateError("coverage denominator must be positive")
    return 100.0 * covered / total


def _validate_reported_percentage(
    value: dict[str, object],
    *,
    key: str,
    expected: float,
    label: str,
) -> None:
    if key not in value:
        return
    reported = value[key]
    if (
        isinstance(reported, bool)
        or not isinstance(reported, (int, float))
        or not math.isfinite(float(reported))
        or abs(float(reported) - expected) > 0.000001
    ):
        raise CoverageGateError(f"{label} {key} conflicts with coverage counts")


def _summary(value: object, *, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise CoverageGateError(f"{label} summary is missing")
    required = ("covered_lines", "num_statements", "covered_branches", "num_branches")
    parsed: dict[str, int] = {}
    for key in required:
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise CoverageGateError(f"{label} {key} is invalid")
        parsed[key] = item
    if parsed["covered_lines"] > parsed["num_statements"]:
        raise CoverageGateError(f"{label} line coverage is impossible")
    if parsed["covered_branches"] > parsed["num_branches"]:
        raise CoverageGateError(f"{label} branch coverage is impossible")
    statement_percent = (
        100.0
        if parsed["num_statements"] == 0
        else 100.0 * parsed["covered_lines"] / parsed["num_statements"]
    )
    branch_percent = (
        100.0
        if parsed["num_branches"] == 0
        else 100.0 * parsed["covered_branches"] / parsed["num_branches"]
    )
    combined_total = parsed["num_statements"] + parsed["num_branches"]
    combined_percent = (
        100.0
        if combined_total == 0
        else 100.0 * (parsed["covered_lines"] + parsed["covered_branches"]) / combined_total
    )
    _validate_reported_percentage(
        value,
        key="percent_statements_covered",
        expected=statement_percent,
        label=label,
    )
    _validate_reported_percentage(
        value,
        key="percent_branches_covered",
        expected=branch_percent,
        label=label,
    )
    _validate_reported_percentage(
        value,
        key="percent_covered",
        expected=combined_percent,
        label=label,
    )
    return parsed


def evaluate(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageGateError("coverage JSON is unreadable") from exc
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, dict):
        raise CoverageGateError("coverage JSON has no files object")
    selected: dict[str, dict[str, int]] = {}
    for name, value in files.items():
        if not isinstance(name, str):
            raise CoverageGateError("coverage file name is invalid")
        normalized_name = name.replace("\\", "/")
        if normalized_name.startswith(SOURCE_PREFIX) or normalized_name == CLI_PATH:
            if not isinstance(value, dict):
                raise CoverageGateError(f"coverage entry for {name} is invalid")
            if normalized_name in selected:
                raise CoverageGateError(
                    f"coverage contains duplicate normalized path: {normalized_name}"
                )
            selected[normalized_name] = _summary(value.get("summary"), label=normalized_name)
    missing = sorted(CRITICAL_FILES - selected.keys())
    if CLI_PATH not in selected:
        missing.append(CLI_PATH)
    if missing:
        raise CoverageGateError(f"mandatory GCS-008 files are absent: {missing}")
    required_files = CRITICAL_FILES | {CLI_PATH}
    empty_statements = sorted(
        name for name in required_files if selected[name]["num_statements"] == 0
    )
    if empty_statements:
        raise CoverageGateError(f"mandatory GCS-008 files have zero statements: {empty_statements}")
    empty_branches = sorted(name for name in CRITICAL_FILES if selected[name]["num_branches"] == 0)
    if empty_branches:
        raise CoverageGateError(f"critical GCS-008 files have zero branches: {empty_branches}")
    totals = {
        key: sum(summary[key] for summary in selected.values())
        for key in ("covered_lines", "num_statements", "covered_branches", "num_branches")
    }
    statement_percent = _percentage(totals["covered_lines"], totals["num_statements"])
    branch_percent = _percentage(totals["covered_branches"], totals["num_branches"])
    failures: list[str] = []
    if statement_percent < AGGREGATE_STATEMENT_MINIMUM:
        failures.append(
            f"aggregate statement coverage {statement_percent:.2f}% < "
            f"{AGGREGATE_STATEMENT_MINIMUM:.2f}%"
        )
    if branch_percent < AGGREGATE_BRANCH_MINIMUM:
        failures.append(
            f"aggregate branch coverage {branch_percent:.2f}% < {AGGREGATE_BRANCH_MINIMUM:.2f}%"
        )
    critical: dict[str, dict[str, float]] = {}
    for name in sorted(CRITICAL_FILES):
        summary = selected[name]
        file_statement = _percentage(summary["covered_lines"], summary["num_statements"])
        file_branch = _percentage(summary["covered_branches"], summary["num_branches"])
        critical[name] = {
            "branch_percent": round(file_branch, 6),
            "statement_percent": round(file_statement, 6),
        }
        if file_statement < CRITICAL_STATEMENT_MINIMUM:
            failures.append(
                f"{name} statement coverage {file_statement:.2f}% < "
                f"{CRITICAL_STATEMENT_MINIMUM:.2f}%"
            )
        if file_branch < CRITICAL_BRANCH_MINIMUM:
            failures.append(
                f"{name} branch coverage {file_branch:.2f}% < {CRITICAL_BRANCH_MINIMUM:.2f}%"
            )
    if failures:
        raise CoverageGateError("; ".join(failures))
    return {
        "aggregate": {
            "branch_percent": round(branch_percent, 6),
            "statement_percent": round(statement_percent, 6),
        },
        "critical_files": critical,
        "file_count": len(selected),
        "schema_version": "gcs008-coverage-gate-v1",
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coverage_json", type=Path)
    arguments = parser.parse_args()
    try:
        report = evaluate(arguments.coverage_json)
    except CoverageGateError as exc:
        print(
            json.dumps(
                {
                    "error": {"code": "GCS008_COVERAGE_GATE_FAILED", "message": str(exc)},
                    "schema_version": "gcs008-coverage-gate-v1",
                    "status": "FAIL",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
