"""NRM-006 coverage-gate false-success and threshold tests."""

from __future__ import annotations

import json
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

pytestmark = pytest.mark.unit


def _namespace(repository_root: Path) -> dict[str, Any]:
    return runpy.run_path(str(repository_root / "scripts" / "verify_nrm006_critical_coverage.py"))


def _summary(*, covered_branches: int = 10, num_branches: int = 10) -> dict[str, Any]:
    return {
        "covered_branches": covered_branches,
        "covered_lines": 20,
        "num_branches": num_branches,
        "num_statements": 20,
    }


def _coverage(namespace: dict[str, Any]) -> dict[str, Any]:
    critical = cast(dict[str, tuple[tuple[str, str, str], ...]], namespace["CRITICAL_FUNCTIONS"])
    core = cast(tuple[tuple[str, str, str], ...], namespace["MATHEMATICAL_CORE"])
    files: dict[str, dict[str, Any]] = {}
    for locator in (*core, *(item for scope in critical.values() for item in scope)):
        path, function_name, _description = locator
        record = files.setdefault(path, {"functions": {}})
        functions = cast(dict[str, Any], record["functions"])
        functions.setdefault(function_name, {"summary": _summary()})
    return {
        "files": files,
        "totals": {
            "covered_branches": 90,
            "covered_lines": 90,
            "num_branches": 100,
            "num_statements": 100,
            "percent_branches_covered": 90.0,
            "percent_covered": 90.0,
        },
    }


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _checker(namespace: dict[str, Any]) -> Callable[[Path], dict[str, Any]]:
    return cast(Callable[[Path], dict[str, Any]], namespace["check_coverage"])


def _function_summary(value: dict[str, Any], path: str, function_name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        cast(dict[str, Any], cast(dict[str, Any], value["files"])[path])["functions"][
            function_name
        ]["summary"],
    )


def test_nrm006_gate_accepts_exact_global_thresholds_and_complete_critical_scopes(
    repository_root: Path, tmp_path: Path
) -> None:
    namespace = _namespace(repository_root)
    value = _coverage(namespace)
    path = tmp_path / "coverage.json"
    _write(path, value)
    report = _checker(namespace)(path)
    assert report["ok"] is True
    assert report["repository_combined_coverage_percent"] == 90.0
    assert report["overall_branch_coverage_percent"] == 90.0
    assert report["mathematical_core_branch_coverage_percent"] == 100.0
    assert report["mathematical_core_line_coverage_percent"] == 100.0
    for category in namespace["CRITICAL_FUNCTIONS"]:
        assert report[f"{category}_branch_coverage_percent"] == 100.0


def test_nrm006_gate_accepts_critical_scope_at_exactly_95_percent(
    repository_root: Path, tmp_path: Path
) -> None:
    namespace = _namespace(repository_root)
    value = _coverage(namespace)
    cli = namespace["CRITICAL_FUNCTIONS"]["cli"]
    first_path, first_name, _description = cli[0]
    summary = _function_summary(value, first_path, first_name)
    summary["covered_branches"] = 18
    summary["num_branches"] = 20
    path = tmp_path / "coverage.json"
    _write(path, value)
    report = _checker(namespace)(path)
    assert report["ok"] is True
    assert report["cli_branch_coverage_percent"] == 95.0


def test_nrm006_gate_rejects_each_global_coverage_shortfall(
    repository_root: Path, tmp_path: Path
) -> None:
    namespace = _namespace(repository_root)
    value = _coverage(namespace)
    totals = cast(dict[str, Any], value["totals"])
    totals.update(
        covered_branches=89,
        covered_lines=100,
        percent_branches_covered=89.0,
        percent_covered=94.5,
    )
    path = tmp_path / "coverage.json"
    _write(path, value)
    report = _checker(namespace)(path)
    assert report["ok"] is False
    assert "overall branch coverage is below 90 percent" in report["errors"]


def test_nrm006_gate_rejects_critical_scope_below_95_percent(
    repository_root: Path, tmp_path: Path
) -> None:
    namespace = _namespace(repository_root)
    value = _coverage(namespace)
    persistence = namespace["CRITICAL_FUNCTIONS"]["persistence"]
    function_path, function_name, _description = persistence[0]
    summary = _function_summary(value, function_path, function_name)
    summary["covered_branches"] = 9
    path = tmp_path / "coverage.json"
    _write(path, value)
    report = _checker(namespace)(path)
    assert report["ok"] is False
    assert report["persistence_branch_coverage_percent"] == 90.0
    assert "persistence branch coverage is below 95 percent" in report["errors"]


def test_nrm006_gate_rejects_one_uncovered_mathematical_core_branch(
    repository_root: Path, tmp_path: Path
) -> None:
    namespace = _namespace(repository_root)
    value = _coverage(namespace)
    core = namespace["MATHEMATICAL_CORE"]
    function_path, function_name, _description = core[4]
    summary = _function_summary(value, function_path, function_name)
    summary["covered_branches"] = 9
    path = tmp_path / "coverage.json"
    _write(path, value)
    report = _checker(namespace)(path)
    assert report["ok"] is False
    assert report["mathematical_core_branch_coverage_percent"] < 100.0
    assert any(
        "mathematical core branch is not fully covered" in error for error in report["errors"]
    )


def test_nrm006_gate_rejects_missing_function_evidence(
    repository_root: Path, tmp_path: Path
) -> None:
    namespace = _namespace(repository_root)
    value = _coverage(namespace)
    function_path, function_name, _description = namespace["MATHEMATICAL_CORE"][0]
    functions = cast(
        dict[str, Any], cast(dict[str, Any], value["files"])[function_path]["functions"]
    )
    del functions[function_name]
    path = tmp_path / "coverage.json"
    _write(path, value)
    with pytest.raises(ValueError, match="coverage is missing"):
        _checker(namespace)(path)
