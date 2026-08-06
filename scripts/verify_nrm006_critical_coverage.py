"""Materialize and enforce NRM-006's frozen critical coverage gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

from coverage import Coverage
from coverage.exceptions import CoverageException, NoDataError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / ".coverage"
DEFAULT_COVERAGE = ROOT / "evidence" / "tickets" / "NRM-006" / "coverage.json"
DEFAULT_REPORT = ROOT / "evidence" / "tickets" / "NRM-006" / "critical_coverage.json"

FunctionLocator = tuple[str, str, str]

# Function-scoped gates avoid diluting ticket-critical branches with unrelated module
# setup while remaining stable across harmless line movement. A missing/renamed
# function fails closed and therefore requires an explicit assurance review.
CRITICAL_FUNCTIONS: Final[dict[str, tuple[FunctionLocator, ...]]] = {
    "temporal_mapping": (
        (
            "src/dmf_pulse/ingestion/odds/mapping.py",
            "OddsMappingPlan.validate_unique_explicit_mappings",
            "mapping-plan evidence and interval invariants",
        ),
        (
            "src/dmf_pulse/ingestion/odds/mapping.py",
            "OddsMappingPlan.fixture",
            "explicit fixture mapping resolution",
        ),
        (
            "src/dmf_pulse/ingestion/odds/mapping.py",
            "OddsMappingPlan.operator",
            "explicit operator mapping resolution",
        ),
        (
            "src/dmf_pulse/ingestion/odds/persistence.py",
            "_current_mapping",
            "valid-time and system-time mapping selection",
        ),
        (
            "src/dmf_pulse/ingestion/odds/persistence.py",
            "_ensure_external_mapping",
            "immutable external mapping publication",
        ),
        (
            "src/dmf_pulse/ingestion/odds/persistence.py",
            "OddsPersistence.resolve_fixture",
            "strict fixture and schedule mapping cutoff",
        ),
        (
            "src/dmf_pulse/ingestion/odds/persistence.py",
            "OddsPersistence._validate_team_mapping",
            "strict team alias mapping cutoff",
        ),
        (
            "src/dmf_pulse/ingestion/odds/persistence.py",
            "OddsPersistence.resolve_operator",
            "canonical operator mapping and provenance",
        ),
        (
            "src/dmf_pulse/markets/repository.py",
            "MarketObservationRepository.resolve_fixture",
            "historical public fixture resolution",
        ),
    ),
    "usable_at": (
        (
            "src/dmf_pulse/ingestion/odds/persistence.py",
            "create_publication_batch",
            "atomic activation batch publication",
        ),
        (
            "src/dmf_pulse/ingestion/odds/persistence.py",
            "attest_publication_batch",
            "separate immutable post-commit attestation",
        ),
        (
            "src/dmf_pulse/ingestion/odds/service.py",
            "OddsIngestionService._promote",
            "prepare, activate, sample, and attest lifecycle",
        ),
        (
            "src/dmf_pulse/ingestion/odds/service.py",
            "OddsIngestionService.repair_publication_attestation",
            "conservative later attestation repair",
        ),
        (
            "src/dmf_pulse/markets/repository.py",
            "MarketObservationRepository.observations",
            "strict attested as-of observation query",
        ),
    ),
    "retry_429": (
        (
            "src/dmf_pulse/ingestion/odds/client.py",
            "parse_quota_headers",
            "all-or-nothing inherited quota evidence",
        ),
        (
            "src/dmf_pulse/ingestion/odds/client.py",
            "_response_quota",
            "case-insensitive quota response classification",
        ),
        (
            "src/dmf_pulse/ingestion/odds/client.py",
            "_response_failure",
            "typed 429 and quota failure policy",
        ),
        (
            "src/dmf_pulse/ingestion/odds/client.py",
            "_retry_delay",
            "bounded Retry-After/default delay",
        ),
        (
            "src/dmf_pulse/ingestion/odds/client.py",
            "OddsClient.fetch",
            "bounded retry, sleeper, deadline, and attempt evidence",
        ),
    ),
    "completeness": (
        (
            "src/dmf_pulse/markets/normalisation.py",
            "_ordered_quotes",
            "exact HOME/DRAW/AWAY compatible book",
        ),
        (
            "src/dmf_pulse/markets/consensus.py",
            "_group_observations",
            "immutable selected-book grouping",
        ),
        (
            "src/dmf_pulse/markets/consensus.py",
            "evaluate_market_consensus",
            "complete, fresh, latest canonical-operator selection",
        ),
    ),
    "proportional": (
        (
            "src/dmf_pulse/markets/normalisation.py",
            "raw_implied_probability",
            "exact Decimal raw implied probability",
        ),
        (
            "src/dmf_pulse/markets/normalisation.py",
            "_compute_market",
            "proportional baseline and primary mode",
        ),
        (
            "src/dmf_pulse/markets/normalisation.py",
            "_public_vector",
            "HALF_EVEN vector residual policy",
        ),
    ),
    "power": (
        (
            "src/dmf_pulse/markets/normalisation.py",
            "_power_vector",
            "frozen bracket and 256-iteration solver",
        ),
        (
            "src/dmf_pulse/markets/normalisation.py",
            "_compute_market",
            "typed power fallback boundary",
        ),
        (
            "src/dmf_pulse/markets/normalisation.py",
            "_public_vector",
            "public power-vector residual policy",
        ),
    ),
    "consensus": (
        (
            "src/dmf_pulse/markets/consensus.py",
            "_tv",
            "Decimal total-variation disagreement",
        ),
        (
            "src/dmf_pulse/markets/consensus.py",
            "_confidence_grade",
            "frozen A/B/C/D thresholds",
        ),
        (
            "src/dmf_pulse/markets/consensus.py",
            "evaluate_market_consensus",
            "equal-operator consensus, bounds, and warnings",
        ),
        (
            "src/dmf_pulse/markets/consensus.py",
            "build_market_consensus",
            "typed no-eligible consensus boundary",
        ),
    ),
    "persistence": (
        (
            "src/dmf_pulse/markets/repository.py",
            "MarketObservationRepository.persist_normalisation",
            "immutable exact-signature persistence and reuse",
        ),
    ),
    "cli": (
        (
            "src/dmf_pulse/cli/market_cmd.py",
            "_exit_code",
            "typed public CLI exit mapping",
        ),
        (
            "src/dmf_pulse/cli/market_cmd.py",
            "normalise_command",
            "public normalisation command boundary",
        ),
        (
            "src/dmf_pulse/markets/service.py",
            "MarketService.normalise",
            "shared application service and status mapping",
        ),
    ),
}

# Every measured branch in each numerical-kernel function must be observed.
# Statement coverage remains reported, while the repository-wide 90% gate owns it.
MATHEMATICAL_CORE: Final[tuple[FunctionLocator, ...]] = (
    (
        "src/dmf_pulse/markets/normalisation.py",
        "_q12",
        "public 12-place HALF_EVEN quantisation",
    ),
    (
        "src/dmf_pulse/markets/normalisation.py",
        "_overround12",
        "public overround quantisation",
    ),
    (
        "src/dmf_pulse/markets/normalisation.py",
        "_public_vector",
        "deterministic public vector residual",
    ),
    (
        "src/dmf_pulse/markets/normalisation.py",
        "raw_implied_probability",
        "exact raw implied probability",
    ),
    (
        "src/dmf_pulse/markets/normalisation.py",
        "_power_vector",
        "frozen Decimal power solver",
    ),
    (
        "src/dmf_pulse/markets/normalisation.py",
        "_compute_market",
        "proportional, power, and typed fallback",
    ),
    (
        "src/dmf_pulse/markets/normalisation.py",
        "_ordered_quotes",
        "exclusive complete-book boundary",
    ),
    (
        "src/dmf_pulse/markets/consensus.py",
        "_tv",
        "total-variation metric",
    ),
    (
        "src/dmf_pulse/markets/consensus.py",
        "_confidence_grade",
        "frozen confidence classifier",
    ),
)


def _integer(value: dict[str, Any], key: str, label: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"{label} lacks a valid {key}")
    return item


def _percentage(covered: int, total: int, *, empty: float = 100.0) -> float:
    return 100.0 * covered / total if total else empty


def _normalized_files(raw_files: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for raw_path, record in raw_files.items():
        path = str(raw_path).replace("\\", "/")
        if path in files or not isinstance(record, dict):
            raise ValueError("coverage JSON contains duplicate or malformed file records")
        files[path] = record
    return files


def _function_counts(
    files: dict[str, dict[str, Any]], locator: FunctionLocator, *, label: str
) -> dict[str, int]:
    path, function_name, _description = locator
    record = files.get(path)
    functions = record.get("functions") if isinstance(record, dict) else None
    function = functions.get(function_name) if isinstance(functions, dict) else None
    summary = function.get("summary") if isinstance(function, dict) else None
    if not isinstance(summary, dict):
        raise ValueError(f"{label} coverage is missing {path}:{function_name}")
    counts = {
        key: _integer(summary, key, label)
        for key in ("covered_lines", "covered_branches", "num_statements", "num_branches")
    }
    if (
        counts["covered_lines"] > counts["num_statements"]
        or counts["covered_branches"] > counts["num_branches"]
    ):
        raise ValueError(f"{label} coverage counts are impossible: {path}:{function_name}")
    return counts


def _scope_counts(
    files: dict[str, dict[str, Any]], locators: tuple[FunctionLocator, ...], *, label: str
) -> tuple[dict[str, int], list[str]]:
    counts = {
        "covered_lines": 0,
        "covered_branches": 0,
        "num_statements": 0,
        "num_branches": 0,
    }
    oracles: list[str] = []
    seen: set[tuple[str, str]] = set()
    for locator in locators:
        path, function_name, description = locator
        identity = path, function_name
        if identity in seen:
            raise ValueError(f"{label} contains a duplicate function locator")
        seen.add(identity)
        function_counts = _function_counts(files, locator, label=label)
        for key in counts:
            counts[key] += function_counts[key]
        oracles.append(f"{path}:{function_name} - {description}")
    if counts["num_statements"] <= 0 or counts["num_branches"] <= 0:
        raise ValueError(f"{label} coverage denominator is unavailable")
    return counts, oracles


def _validate_totals(totals: dict[str, Any]) -> dict[str, int]:
    counts = {
        key: _integer(totals, key, "repository coverage")
        for key in ("covered_lines", "covered_branches", "num_statements", "num_branches")
    }
    if (
        counts["num_statements"] <= 0
        or counts["num_branches"] <= 0
        or counts["covered_lines"] > counts["num_statements"]
        or counts["covered_branches"] > counts["num_branches"]
    ):
        raise ValueError("repository coverage totals are impossible")
    combined = _percentage(
        counts["covered_lines"] + counts["covered_branches"],
        counts["num_statements"] + counts["num_branches"],
    )
    branch = _percentage(counts["covered_branches"], counts["num_branches"])
    reported_combined = totals.get("percent_covered")
    reported_branch = totals.get("percent_branches_covered")
    for reported, calculated, label in (
        (reported_combined, combined, "combined"),
        (reported_branch, branch, "branch"),
    ):
        if (
            not isinstance(reported, (int, float))
            or isinstance(reported, bool)
            or not math.isfinite(float(reported))
            or not math.isclose(float(reported), calculated, rel_tol=0.0, abs_tol=1e-6)
        ):
            raise ValueError(f"repository {label} coverage percentage conflicts with its counts")
    return counts


def check_coverage(path: Path) -> dict[str, Any]:
    """Validate coverage JSON and return the exact NRM-006 metric contract."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("coverage JSON is unavailable or malformed") from exc
    totals = value.get("totals") if isinstance(value, dict) else None
    raw_files = value.get("files") if isinstance(value, dict) else None
    if not isinstance(totals, dict) or not isinstance(raw_files, dict):
        raise ValueError("coverage JSON lacks totals or files")
    files = _normalized_files(raw_files)
    repository = _validate_totals(totals)
    combined_covered = repository["covered_lines"] + repository["covered_branches"]
    combined_total = repository["num_statements"] + repository["num_branches"]
    combined_percent = _percentage(combined_covered, combined_total)
    branch_percent = _percentage(repository["covered_branches"], repository["num_branches"])
    errors: list[str] = []
    if combined_percent < 90.0:
        errors.append("repository combined statement/branch coverage is below 90 percent")
    if branch_percent < 90.0:
        errors.append("overall branch coverage is below 90 percent")

    report: dict[str, Any] = {
        "repository_combined_coverage_percent": round(combined_percent, 6),
        "repository_combined_units_covered": combined_covered,
        "repository_combined_units_total": combined_total,
        "overall_branch_coverage_percent": round(branch_percent, 6),
        "overall_branches_covered": repository["covered_branches"],
        "overall_branches_total": repository["num_branches"],
    }
    critical_oracles: dict[str, list[str]] = {}
    for category, locators in CRITICAL_FUNCTIONS.items():
        counts, oracles = _scope_counts(files, locators, label=category.replace("_", " "))
        percent = _percentage(counts["covered_branches"], counts["num_branches"])
        report[f"{category}_branch_coverage_percent"] = round(percent, 6)
        report[f"{category}_branches_covered"] = counts["covered_branches"]
        report[f"{category}_branches_total"] = counts["num_branches"]
        critical_oracles[category] = oracles
        if percent < 95.0:
            errors.append(f"{category.replace('_', ' ')} branch coverage is below 95 percent")

    core_rows: list[dict[str, Any]] = []
    core_covered_lines = 0
    core_statements = 0
    core_covered_branches = 0
    core_branches = 0
    for locator in MATHEMATICAL_CORE:
        path_name, function_name, description = locator
        counts = _function_counts(files, locator, label="mathematical core")
        line_percent = _percentage(counts["covered_lines"], counts["num_statements"])
        function_branch_percent = _percentage(counts["covered_branches"], counts["num_branches"])
        core_covered_lines += counts["covered_lines"]
        core_statements += counts["num_statements"]
        core_covered_branches += counts["covered_branches"]
        core_branches += counts["num_branches"]
        core_rows.append(
            {
                "branch_coverage_percent": round(function_branch_percent, 6),
                "branches_covered": counts["covered_branches"],
                "branches_total": counts["num_branches"],
                "description": description,
                "function": function_name,
                "line_coverage_percent": round(line_percent, 6),
                "lines_covered": counts["covered_lines"],
                "path": path_name,
                "statements_total": counts["num_statements"],
            }
        )
        if function_branch_percent < 100.0:
            errors.append(
                f"mathematical core branch is not fully covered: {path_name}:{function_name}"
            )
    if core_statements <= 0 or core_branches <= 0:
        raise ValueError("mathematical core coverage denominator is unavailable")
    report.update(
        critical_oracles=critical_oracles,
        mathematical_core_branch_coverage_percent=round(
            _percentage(core_covered_branches, core_branches), 6
        ),
        mathematical_core_branches_covered=core_covered_branches,
        mathematical_core_branches_total=core_branches,
        mathematical_core_function_coverage=core_rows,
        mathematical_core_line_coverage_percent=round(
            _percentage(core_covered_lines, core_statements), 6
        ),
        mathematical_core_lines_covered=core_covered_lines,
        mathematical_core_statements_total=core_statements,
        errors=errors,
        ok=not errors,
    )
    return report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _materialize_coverage(data_path: Path, json_path: Path) -> None:
    try:
        coverage = Coverage(data_file=str(data_path), config_file=str(ROOT / "pyproject.toml"))
        coverage.load()
        with tempfile.TemporaryDirectory(prefix="dmf-nrm006-coverage-") as temporary:
            raw_path = Path(temporary) / "coverage.json"
            coverage.json_report(outfile=str(raw_path), pretty_print=False, show_contexts=False)
            value = json.loads(raw_path.read_text(encoding="utf-8"))
    except (CoverageException, NoDataError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("coverage data could not be materialized") from exc
    if not isinstance(value, dict):
        raise ValueError("materialized coverage root is malformed")
    meta = value.get("meta")
    if isinstance(meta, dict):
        meta.pop("timestamp", None)
    _write_json(json_path, value)


def verify_critical_coverage(
    *,
    data_path: Path = DEFAULT_DATA,
    coverage_path: Path = DEFAULT_COVERAGE,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    """Materialize deterministic evidence, enforce the gates, and save the report."""

    _materialize_coverage(data_path, coverage_path)
    report = check_coverage(coverage_path)
    report["coverage_json_sha256"] = _sha256(coverage_path)
    report["coverage_path"] = coverage_path.relative_to(ROOT).as_posix()
    report["status"] = "PASS" if report["ok"] else "FAIL"
    _write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage-data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--coverage-json", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    arguments = parser.parse_args()
    try:
        report = verify_critical_coverage(
            data_path=arguments.coverage_data,
            coverage_path=arguments.coverage_json,
            report_path=arguments.report,
        )
    except ValueError as exc:
        report = {"errors": [str(exc)], "ok": False, "status": "FAIL"}
    except Exception as exc:
        report = {
            "errors": [f"critical coverage verification failed ({type(exc).__name__})"],
            "ok": False,
            "status": "FAIL",
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
