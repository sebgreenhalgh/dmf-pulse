"""Enforce ODD-005's frozen critical-branch coverage gates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COVERAGE = ROOT / "evidence/tickets/ODD-005/coverage.json"

# Each locator identifies a policy decision rather than an arbitrary whole module.
# This keeps the 95% gates tied to the ticket's safety-critical branches while the
# literal pytest-cov command independently enforces 90% across the entire package.
Predicate = tuple[str, str, str]
PREDICATES: Final[dict[str, tuple[Predicate, ...]]] = {
    "critical_odds_ingestion": (
        (
            "src/dmf_pulse/ingestion/odds/parser.py",
            "if key in result:",
            "duplicate provider JSON keys fail closed",
        ),
        (
            "src/dmf_pulse/ingestion/odds/parser.py",
            'if value != "soccer_epl":',
            "only the frozen EPL sport key is accepted",
        ),
        (
            "src/dmf_pulse/ingestion/odds/parser.py",
            "if previous is not None and previous != candidate:",
            "contradictory same-book price or line outcomes are blocked",
        ),
        (
            "src/dmf_pulse/ingestion/odds/persistence.py",
            'if provider_market.key != "h2h":',
            "unsupported markets are blocked from canonical publication",
        ),
        (
            "src/dmf_pulse/ingestion/odds/service.py",
            "if post_cutoff:",
            "post-cutoff observations remain ineligible",
        ),
    ),
    "rights": (
        (
            "src/dmf_pulse/ingestion/rights.py",
            'if decision.decision != "ALLOW":',
            "unknown or denied capability blocks the operation",
        ),
        (
            "src/dmf_pulse/ingestion/odds/service.py",
            "if profile is None:",
            "unknown odds rights profile fails closed",
        ),
        (
            "src/dmf_pulse/ingestion/odds/client.py",
            "if credential_failed or not isinstance(credential, str) or not credential:",
            "credential failure stops before transport",
        ),
    ),
    "quota": (
        (
            "src/dmf_pulse/ingestion/odds/client.py",
            "if quota is not None and quota.remaining < config.request_cost:",
            "known exhausted quota blocks before transport",
        ),
        (
            "src/dmf_pulse/ingestion/odds/client.py",
            "if not present:",
            "absent quota headers are distinguished",
        ),
        (
            "src/dmf_pulse/ingestion/odds/client.py",
            "if present != required:",
            "partial quota headers are invalid",
        ),
        (
            "src/dmf_pulse/ingestion/odds/client.py",
            "if quota_blocks_retry and response_error.retryable:",
            "quota depletion cancels a transient retry",
        ),
    ),
    "cutoff": (
        (
            "src/dmf_pulse/ingestion/odds/service.py",
            "if post_cutoff:",
            "usable time is compared to the requested information cutoff",
        ),
    ),
    "tls": (
        (
            "src/dmf_pulse/ingestion/odds/client.py",
            "if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):",
            "wrapped odds TLS failures are typed and non-retryable",
        ),
        (
            "src/dmf_pulse/ingestion/fpl/client.py",
            "if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):",
            "wrapped inherited FPL TLS failures are typed and non-retryable",
        ),
    ),
    "fpl_remediation": (
        (
            "src/dmf_pulse/ingestion/fpl/parser.py",
            "elif isinstance(item, list):",
            "heterogeneous array members retain every observed type",
        ),
        (
            "src/dmf_pulse/ingestion/fpl/persistence.py",
            'if decisions != {"ALLOW"}:',
            "bundle publication uses persisted authoritative rights decisions",
        ),
        (
            "src/dmf_pulse/ingestion/fpl/persistence.py",
            'if any(severity in {"P0", "P1"} for severity in open_issues):',
            "persisted P0/P1 quality issues block bundle publication",
        ),
        (
            "src/dmf_pulse/ingestion/fpl/client.py",
            "if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):",
            "FPL certificate failures are independently exercised",
        ),
    ),
}


def _integer(value: dict[str, Any], key: str, label: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"{label} lacks a valid {key}")
    return item


def _percentage(covered: int, total: int) -> float:
    return 100.0 * covered / total if total else 0.0


def _arcs(record: dict[str, Any], key: str, label: str) -> set[tuple[int, int]]:
    raw = record.get(key)
    if not isinstance(raw, list):
        raise ValueError(f"{label} coverage lacks {key}")
    result: set[tuple[int, int]] = set()
    for item in raw:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or any(not isinstance(part, int) or isinstance(part, bool) for part in item)
        ):
            raise ValueError(f"{label} coverage contains a malformed branch arc")
        result.add((item[0], item[1]))
    if len(result) != len(raw):
        raise ValueError(f"{label} coverage contains duplicate branch arcs")
    return result


def _predicate_counts(
    files: dict[str, dict[str, Any]],
    predicates: tuple[Predicate, ...],
    repository_root: Path,
    label: str,
) -> tuple[int, int, list[str]]:
    covered = 0
    total = 0
    oracles: list[str] = []
    for relative, predicate, description in predicates:
        try:
            source = (repository_root / relative).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"{label} source is unavailable: {relative}") from exc
        matches = [
            number for number, line in enumerate(source, start=1) if line.strip() == predicate
        ]
        if len(matches) != 1:
            raise ValueError(f"{label} predicate must occur exactly once: {relative}: {predicate}")
        record = files.get(relative)
        if record is None:
            raise ValueError(f"{label} coverage is missing {relative}")
        executed = _arcs(record, "executed_branches", label)
        missing = _arcs(record, "missing_branches", label)
        if executed & missing:
            raise ValueError(f"{label} branch is simultaneously executed and missing")
        line_number = matches[0]
        measured = {arc for arc in executed | missing if arc[0] == line_number}
        exercised = {arc for arc in executed if arc[0] == line_number}
        if len(measured) < 2:
            raise ValueError(f"{label} predicate lacks measured true/false branches: {relative}")
        covered += len(exercised)
        total += len(measured)
        oracles.append(f"{relative}:{line_number} - {description}")
    return covered, total, oracles


def check_coverage(path: Path, *, repository_root: Path = ROOT) -> dict[str, Any]:
    """Validate coverage JSON and return the exact ODD-005 metric contract."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("coverage JSON is unavailable or malformed") from exc
    totals = value.get("totals") if isinstance(value, dict) else None
    raw_files = value.get("files") if isinstance(value, dict) else None
    if not isinstance(totals, dict) or not isinstance(raw_files, dict):
        raise ValueError("coverage JSON lacks totals or files")
    files: dict[str, dict[str, Any]] = {}
    for raw_path, record in raw_files.items():
        normalized = str(raw_path).replace("\\", "/")
        if normalized in files or not isinstance(record, dict):
            raise ValueError("coverage JSON contains duplicate or malformed file records")
        files[normalized] = record

    repository_counts = {
        key: _integer(totals, key, "repository coverage")
        for key in ("covered_lines", "covered_branches", "num_statements", "num_branches")
    }
    if (
        repository_counts["num_statements"] <= 0
        or repository_counts["num_branches"] <= 0
        or repository_counts["covered_lines"] > repository_counts["num_statements"]
        or repository_counts["covered_branches"] > repository_counts["num_branches"]
    ):
        raise ValueError("repository coverage totals are impossible")
    combined_covered = repository_counts["covered_lines"] + repository_counts["covered_branches"]
    combined_total = repository_counts["num_statements"] + repository_counts["num_branches"]
    combined_percent = _percentage(combined_covered, combined_total)
    branch_percent = _percentage(
        repository_counts["covered_branches"], repository_counts["num_branches"]
    )
    reported_combined = totals.get("percent_covered")
    reported_branch = totals.get("percent_branches_covered")
    if (
        not isinstance(reported_combined, (int, float))
        or isinstance(reported_combined, bool)
        or not math.isfinite(float(reported_combined))
        or not math.isclose(float(reported_combined), combined_percent, abs_tol=1e-6)
        or not isinstance(reported_branch, (int, float))
        or isinstance(reported_branch, bool)
        or not math.isfinite(float(reported_branch))
        or not math.isclose(float(reported_branch), branch_percent, abs_tol=1e-6)
    ):
        raise ValueError("repository coverage percentages conflict with their counts")

    result: dict[str, Any] = {
        "repository_combined_coverage_percent": round(combined_percent, 6),
        "repository_combined_units_covered": combined_covered,
        "repository_combined_units_total": combined_total,
        "overall_branch_coverage_percent": round(branch_percent, 6),
        "overall_branches_covered": repository_counts["covered_branches"],
        "overall_branches_total": repository_counts["num_branches"],
    }
    errors: list[str] = []
    if combined_percent < 90.0:
        errors.append("repository combined statement/branch coverage is below 90 percent")
    if branch_percent < 90.0:
        errors.append("overall branch coverage is below 90 percent")
    all_oracles: list[str] = []
    for category, predicates in PREDICATES.items():
        covered, total, oracles = _predicate_counts(
            files, predicates, repository_root, category.replace("_", " ")
        )
        percent = _percentage(covered, total)
        result[f"{category}_branch_coverage_percent"] = round(percent, 6)
        result[f"{category}_branches_covered"] = covered
        result[f"{category}_branches_total"] = total
        all_oracles.extend(oracles)
        if percent < 95.0:
            errors.append(f"{category.replace('_', ' ')} branch coverage is below 95 percent")
    result["critical_oracles"] = all_oracles
    result["errors"] = errors
    result["ok"] = not errors
    return result


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
