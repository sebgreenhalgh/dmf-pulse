"""FPL-004 tiered coverage-gate false-success tests."""

from __future__ import annotations

import json
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest


def _checker(repository_root: Path) -> Callable[..., dict[str, Any]]:
    namespace = runpy.run_path(str(repository_root / "scripts" / "check_fpl004_coverage_gates.py"))
    return cast(Callable[..., dict[str, Any]], namespace["check_coverage"])


def _summary(covered: int, total: int) -> dict[str, int]:
    return {
        "covered_branches": covered,
        "covered_lines": 10,
        "num_branches": total,
        "num_statements": 10,
    }


def _coverage(repository_root: Path) -> dict[str, object]:
    files: dict[str, dict[str, object]] = {
        "src/dmf_pulse/ingestion/fpl/parser.py": {"summary": _summary(48, 50)},
        "src/dmf_pulse/ingestion/models.py": {"summary": _summary(48, 50)},
        "src/dmf_pulse/ingestion/rights.py": {"summary": _summary(94, 100)},
        "src/dmf_pulse/ingestion/fpl/adapter.py": {"summary": _summary(20, 25)},
        "src/dmf_pulse/ingestion/fpl/client.py": {"summary": _summary(20, 25)},
        "src/dmf_pulse/ingestion/fpl/config.py": {"summary": _summary(20, 25)},
        "src/dmf_pulse/ingestion/provider.py": {"summary": _summary(20, 25)},
        "src/dmf_pulse/ingestion/fpl/persistence.py": {"summary": _summary(10, 10)},
        "src/dmf_pulse/ingestion/fpl/service.py": {"summary": _summary(10, 10)},
    }
    predicates = (
        ("src/dmf_pulse/ingestion/fpl/persistence.py", "if usable > cutoff:"),
        (
            "src/dmf_pulse/ingestion/fpl/service.py",
            'if exc.code != "POST_CUTOFF":',
        ),
        ("src/dmf_pulse/ingestion/fpl/service.py", "if len(blockers) != 1:"),
        ("src/dmf_pulse/ingestion/fpl/service.py", "if exists:"),
    )
    for relative, predicate in predicates:
        lines = (repository_root / relative).read_text(encoding="utf-8").splitlines()
        line_number = next(
            index for index, line in enumerate(lines, start=1) if line.strip() == predicate
        )
        record = files[relative]
        record.setdefault("executed_branches", []).extend(  # type: ignore[union-attr]
            ([line_number, line_number + 1], [line_number, line_number + 2])
        )
    for record in files.values():
        record.setdefault("executed_branches", [])
        record["missing_branches"] = []
    return {
        "totals": {
            "covered_branches": 86,
            "covered_lines": 96,
            "num_branches": 100,
            "num_statements": 100,
            "percent_branches_covered": 86.0,
            "percent_covered": 91.0,
        },
        "files": files,
    }


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, allow_nan=True), encoding="utf-8")


@pytest.mark.unit
def test_fpl_coverage_gate_accepts_literal_and_tiered_thresholds(
    repository_root: Path, tmp_path: Path
) -> None:
    path = tmp_path / "coverage.json"
    _write(path, _coverage(repository_root))
    report = _checker(repository_root)(path, repository_root=repository_root)
    assert report["ok"] is True
    assert report["repository_combined_coverage_percent"] == 91.0
    assert report["overall_branch_coverage_percent"] == 86.0
    assert report["critical_deterministic_branch_coverage_percent"] == 96.0
    assert report["rights_branch_coverage_percent"] == 94.0
    assert report["provider_adapter_branch_coverage_percent"] == 80.0
    assert report["cutoff_branch_coverage_percent"] == 100.0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("scope", "covered", "total", "expected_error"),
    [
        ("combined", 89, 100, "combined statement/branch"),
        ("critical", 94, 100, "critical deterministic"),
        ("rights", 89, 100, "rights branch"),
        ("provider", 74, 100, "provider adapter"),
    ],
)
def test_fpl_coverage_gate_rejects_each_independent_threshold(
    repository_root: Path,
    tmp_path: Path,
    scope: str,
    covered: int,
    total: int,
    expected_error: str,
) -> None:
    value = _coverage(repository_root)
    totals = value["totals"]
    files = value["files"]
    assert isinstance(totals, dict) and isinstance(files, dict)
    if scope == "combined":
        totals["covered_lines"] = covered
        totals["covered_branches"] = covered
        totals["num_statements"] = total
        totals["num_branches"] = total
        totals["percent_covered"] = float(covered)
        totals["percent_branches_covered"] = float(covered)
    else:
        targets = {
            "critical": (
                "src/dmf_pulse/ingestion/fpl/parser.py",
                "src/dmf_pulse/ingestion/models.py",
            ),
            "rights": ("src/dmf_pulse/ingestion/rights.py",),
            "provider": (
                "src/dmf_pulse/ingestion/fpl/adapter.py",
                "src/dmf_pulse/ingestion/fpl/client.py",
                "src/dmf_pulse/ingestion/fpl/config.py",
                "src/dmf_pulse/ingestion/provider.py",
            ),
        }[scope]
        per_file_total = total // len(targets)
        per_file_covered = covered // len(targets)
        for target in targets:
            record = files[target]
            assert isinstance(record, dict)
            record["summary"] = _summary(per_file_covered, per_file_total)
    path = tmp_path / "coverage.json"
    _write(path, value)
    report = _checker(repository_root)(path, repository_root=repository_root)
    assert report["ok"] is False
    assert any(expected_error in error for error in report["errors"])


@pytest.mark.unit
def test_fpl_coverage_gate_rejects_missing_cutoff_arc(
    repository_root: Path, tmp_path: Path
) -> None:
    value = _coverage(repository_root)
    files = value["files"]
    assert isinstance(files, dict)
    record = files["src/dmf_pulse/ingestion/fpl/service.py"]
    assert isinstance(record, dict)
    executed = record["executed_branches"]
    assert isinstance(executed, list)
    missing = executed.pop()
    record["missing_branches"] = [missing]
    path = tmp_path / "coverage.json"
    _write(path, value)
    report = _checker(repository_root)(path, repository_root=repository_root)
    assert report["ok"] is False
    assert report["cutoff_branch_coverage_percent"] == 87.5


@pytest.mark.unit
@pytest.mark.parametrize("bad_value", [True, float("nan"), float("inf")])
def test_fpl_coverage_gate_rejects_nonfinite_boolean_or_inconsistent_totals(
    repository_root: Path, tmp_path: Path, bad_value: object
) -> None:
    value = _coverage(repository_root)
    totals = value["totals"]
    assert isinstance(totals, dict)
    totals["percent_covered"] = bad_value
    path = tmp_path / "coverage.json"
    _write(path, value)
    with pytest.raises(ValueError):
        _checker(repository_root)(path, repository_root=repository_root)
