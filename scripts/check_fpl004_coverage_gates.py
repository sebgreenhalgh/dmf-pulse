"""Enforce FPL-004's ticket-specific, authority-tiered coverage gates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COVERAGE = ROOT / "evidence/tickets/FPL-004/coverage.json"

CRITICAL_DETERMINISTIC_FILES = (
    "src/dmf_pulse/ingestion/fpl/parser.py",
    "src/dmf_pulse/ingestion/models.py",
)
RIGHTS_FILES = ("src/dmf_pulse/ingestion/rights.py",)
PROVIDER_ADAPTER_FILES = (
    "src/dmf_pulse/ingestion/fpl/adapter.py",
    "src/dmf_pulse/ingestion/fpl/client.py",
    "src/dmf_pulse/ingestion/fpl/config.py",
    "src/dmf_pulse/ingestion/provider.py",
)
INGESTION_PREFIX = "src/dmf_pulse/ingestion/"

# These are the ticket's cutoff-critical control-flow decisions. Locating the exact
# predicate text keeps the gate stable across harmless line movement while failing
# closed if the policy implementation changes without an assurance update.
CUTOFF_PREDICATES = (
    (
        "src/dmf_pulse/ingestion/fpl/persistence.py",
        "if usable > cutoff:",
        "post-cutoff bundle member is rejected",
    ),
    (
        "src/dmf_pulse/ingestion/fpl/service.py",
        'if exc.code != "POST_CUTOFF":',
        "only POST_CUTOFF is converted to an observed non-bundle outcome",
    ),
    (
        "src/dmf_pulse/ingestion/fpl/service.py",
        "if len(blockers) != 1:",
        "post-cutoff evidence requires exactly one blocker",
    ),
    (
        "src/dmf_pulse/ingestion/fpl/service.py",
        "if exists:",
        "post-cutoff issue publication is idempotent",
    ),
)


def _percentage(covered: int, total: int) -> float:
    return 100.0 * covered / total if total else 0.0


def _integer(summary: dict[str, Any], key: str, *, label: str) -> int:
    value = summary.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} coverage lacks a valid {key}")
    return value


def _normalized_files(files: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw_path, raw_record in files.items():
        path = str(raw_path).replace("\\", "/")
        if path in result or not isinstance(raw_record, dict):
            raise ValueError("coverage JSON contains a duplicate or malformed file record")
        result[path] = raw_record
    return result


def _scope_counts(
    files: dict[str, dict[str, Any]], paths: tuple[str, ...], *, label: str
) -> dict[str, int]:
    counts = {
        "covered_lines": 0,
        "covered_branches": 0,
        "num_statements": 0,
        "num_branches": 0,
    }
    for path in paths:
        record = files.get(path)
        summary = record.get("summary") if isinstance(record, dict) else None
        if not isinstance(summary, dict):
            raise ValueError(f"{label} coverage is missing {path}")
        for key in counts:
            counts[key] += _integer(summary, key, label=label)
        if counts["covered_lines"] > counts["num_statements"]:
            raise ValueError(f"{label} covered lines exceed statements")
        if counts["covered_branches"] > counts["num_branches"]:
            raise ValueError(f"{label} covered branches exceed branches")
    if counts["num_statements"] <= 0 or counts["num_branches"] <= 0:
        raise ValueError(f"{label} coverage denominator is unavailable")
    return counts


def _prefix_counts(files: dict[str, dict[str, Any]], prefix: str, *, label: str) -> dict[str, int]:
    paths = tuple(sorted(path for path in files if path.startswith(prefix)))
    if not paths:
        raise ValueError(f"{label} coverage has no matching files")
    return _scope_counts(files, paths, label=label)


def _branch_arcs(record: dict[str, Any], key: str, *, label: str) -> set[tuple[int, int]]:
    raw_arcs = record.get(key)
    if not isinstance(raw_arcs, list):
        raise ValueError(f"{label} coverage lacks {key}")
    arcs: set[tuple[int, int]] = set()
    for raw_arc in raw_arcs:
        if (
            not isinstance(raw_arc, list)
            or len(raw_arc) != 2
            or any(not isinstance(value, int) or isinstance(value, bool) for value in raw_arc)
        ):
            raise ValueError(f"{label} coverage contains a malformed branch arc")
        arc = (raw_arc[0], raw_arc[1])
        if arc in arcs:
            raise ValueError(f"{label} coverage contains a duplicate branch arc")
        arcs.add(arc)
    return arcs


def _cutoff_counts(
    files: dict[str, dict[str, Any]], repository_root: Path
) -> tuple[int, int, list[str]]:
    covered_total = 0
    branch_total = 0
    oracles: list[str] = []
    for relative, predicate, description in CUTOFF_PREDICATES:
        try:
            lines = (repository_root / relative).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"cutoff source is unavailable: {relative}") from exc
        matches = [index for index, line in enumerate(lines, start=1) if line.strip() == predicate]
        if len(matches) != 1:
            raise ValueError(f"cutoff predicate must occur exactly once: {relative}: {predicate}")
        record = files.get(relative)
        if record is None:
            raise ValueError(f"cutoff coverage is missing {relative}")
        executed = _branch_arcs(record, "executed_branches", label="cutoff")
        missing = _branch_arcs(record, "missing_branches", label="cutoff")
        if executed & missing:
            raise ValueError("cutoff branch is simultaneously executed and missing")
        line_number = matches[0]
        predicate_executed = {arc for arc in executed if arc[0] == line_number}
        predicate_missing = {arc for arc in missing if arc[0] == line_number}
        predicate_total = predicate_executed | predicate_missing
        if len(predicate_total) != 2:
            raise ValueError(f"cutoff predicate lacks exactly two measured branches: {relative}")
        covered_total += len(predicate_executed)
        branch_total += len(predicate_total)
        oracles.append(f"{relative}:{line_number} - {description}")
    return covered_total, branch_total, oracles


def _finite_percentage(totals: dict[str, Any], key: str) -> float:
    value = totals.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 100.0
    ):
        raise ValueError(f"coverage JSON lacks a valid {key}")
    return float(value)


def check_coverage(path: Path, *, repository_root: Path = ROOT) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("coverage JSON is unavailable or malformed") from exc
    totals = value.get("totals") if isinstance(value, dict) else None
    raw_files = value.get("files") if isinstance(value, dict) else None
    if not isinstance(totals, dict) or not isinstance(raw_files, dict):
        raise ValueError("coverage JSON lacks totals or files")
    files = _normalized_files(raw_files)

    combined = _finite_percentage(totals, "percent_covered")
    overall_branch = _finite_percentage(totals, "percent_branches_covered")
    overall_counts = {
        key: _integer(totals, key, label="repository")
        for key in ("covered_lines", "covered_branches", "num_statements", "num_branches")
    }
    if (
        overall_counts["covered_lines"] > overall_counts["num_statements"]
        or overall_counts["covered_branches"] > overall_counts["num_branches"]
        or overall_counts["num_statements"] <= 0
        or overall_counts["num_branches"] <= 0
    ):
        raise ValueError("repository coverage totals are impossible")
    combined_covered = overall_counts["covered_lines"] + overall_counts["covered_branches"]
    combined_total = overall_counts["num_statements"] + overall_counts["num_branches"]
    calculated_combined = _percentage(combined_covered, combined_total)
    calculated_branch = _percentage(
        overall_counts["covered_branches"], overall_counts["num_branches"]
    )
    if not math.isclose(combined, calculated_combined, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError("repository combined coverage percentage conflicts with its counts")
    if not math.isclose(overall_branch, calculated_branch, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError("repository branch coverage percentage conflicts with its counts")
    critical = _scope_counts(files, CRITICAL_DETERMINISTIC_FILES, label="critical deterministic")
    rights = _scope_counts(files, RIGHTS_FILES, label="rights")
    provider = _scope_counts(files, PROVIDER_ADAPTER_FILES, label="provider adapter")
    ingestion = _prefix_counts(files, INGESTION_PREFIX, label="ingestion package")
    cutoff_covered, cutoff_total, cutoff_oracles = _cutoff_counts(files, repository_root)

    critical_percent = _percentage(critical["covered_branches"], critical["num_branches"])
    rights_percent = _percentage(rights["covered_branches"], rights["num_branches"])
    provider_percent = _percentage(provider["covered_branches"], provider["num_branches"])
    ingestion_percent = _percentage(ingestion["covered_branches"], ingestion["num_branches"])
    cutoff_percent = _percentage(cutoff_covered, cutoff_total)
    errors: list[str] = []
    if combined < 90.0:
        errors.append("repository combined statement/branch coverage is below 90 percent")
    if critical_percent < 95.0:
        errors.append("critical deterministic branch coverage is below 95 percent")
    if rights_percent < 90.0:
        errors.append("rights branch coverage is below 90 percent")
    if provider_percent < 75.0:
        errors.append("provider adapter branch coverage is below 75 percent")
    if cutoff_percent < 95.0:
        errors.append("cutoff-critical branch coverage is below 95 percent")

    return {
        "critical_deterministic_branch_coverage_percent": round(critical_percent, 6),
        "critical_deterministic_branches_covered": critical["covered_branches"],
        "critical_deterministic_branches_total": critical["num_branches"],
        "cutoff_branch_coverage_percent": round(cutoff_percent, 6),
        "cutoff_branches_covered": cutoff_covered,
        "cutoff_branches_total": cutoff_total,
        "cutoff_oracles": cutoff_oracles,
        "errors": errors,
        "ingestion_package_branch_coverage_percent": round(ingestion_percent, 6),
        "ingestion_package_branches_covered": ingestion["covered_branches"],
        "ingestion_package_branches_total": ingestion["num_branches"],
        "ok": not errors,
        "overall_branch_coverage_percent": round(overall_branch, 6),
        "overall_branches_covered": overall_counts["covered_branches"],
        "overall_branches_total": overall_counts["num_branches"],
        "provider_adapter_branch_coverage_percent": round(provider_percent, 6),
        "provider_adapter_branches_covered": provider["covered_branches"],
        "provider_adapter_branches_total": provider["num_branches"],
        "repository_combined_coverage_percent": round(combined, 6),
        "repository_combined_units_covered": combined_covered,
        "repository_combined_units_total": combined_total,
        "rights_branch_coverage_percent": round(rights_percent, 6),
        "rights_branches_covered": rights["covered_branches"],
        "rights_branches_total": rights["num_branches"],
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
