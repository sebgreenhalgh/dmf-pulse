"""ODD-005 overall and safety-critical branch-gate false-success tests."""

from __future__ import annotations

import json
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest


def _namespace(repository_root: Path) -> dict[str, Any]:
    return runpy.run_path(str(repository_root / "scripts" / "check_odd005_coverage_gates.py"))


def _coverage(repository_root: Path, namespace: dict[str, Any]) -> dict[str, object]:
    files: dict[str, dict[str, object]] = {}
    predicates = cast(dict[str, tuple[tuple[str, str, str], ...]], namespace["PREDICATES"])
    for category in predicates.values():
        for relative, predicate, _description in category:
            lines = (repository_root / relative).read_text(encoding="utf-8").splitlines()
            matches = [
                number for number, line in enumerate(lines, start=1) if line.strip() == predicate
            ]
            assert len(matches) == 1
            line_number = matches[0]
            record = files.setdefault(
                relative,
                {"executed_branches": [], "missing_branches": []},
            )
            executed = cast(list[list[int]], record["executed_branches"])
            for arc in ([line_number, line_number + 1], [line_number, line_number + 2]):
                if arc not in executed:
                    executed.append(arc)
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


def _checker(namespace: dict[str, Any]) -> Callable[..., dict[str, Any]]:
    return cast(Callable[..., dict[str, Any]], namespace["check_coverage"])


@pytest.mark.unit
def test_odd005_coverage_gate_accepts_exact_thresholds_and_all_critical_arcs(
    repository_root: Path, tmp_path: Path
) -> None:
    namespace = _namespace(repository_root)
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(_coverage(repository_root, namespace)), encoding="utf-8")
    report = _checker(namespace)(path, repository_root=repository_root)
    assert report["ok"] is True
    assert report["repository_combined_coverage_percent"] == 90.0
    assert report["overall_branch_coverage_percent"] == 90.0
    for category in namespace["PREDICATES"]:
        assert report[f"{category}_branch_coverage_percent"] == 100.0


@pytest.mark.unit
def test_odd005_coverage_gate_rejects_branch_below_90_when_combined_passes(
    repository_root: Path, tmp_path: Path
) -> None:
    namespace = _namespace(repository_root)
    value = _coverage(repository_root, namespace)
    totals = cast(dict[str, object], value["totals"])
    totals.update(
        covered_branches=89,
        covered_lines=100,
        percent_branches_covered=89.0,
        percent_covered=94.5,
    )
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    report = _checker(namespace)(path, repository_root=repository_root)
    assert report["ok"] is False
    assert "overall branch coverage is below 90 percent" in report["errors"]


@pytest.mark.unit
def test_odd005_coverage_gate_rejects_missing_canonical_publication_arc(
    repository_root: Path, tmp_path: Path
) -> None:
    namespace = _namespace(repository_root)
    value = _coverage(repository_root, namespace)
    predicates = cast(dict[str, tuple[tuple[str, str, str], ...]], namespace["PREDICATES"])
    relative, predicate, _description = predicates["critical_odds_ingestion"][3]
    lines = (repository_root / relative).read_text(encoding="utf-8").splitlines()
    line_number = next(
        number for number, line in enumerate(lines, start=1) if line.strip() == predicate
    )
    record = cast(dict[str, object], cast(dict[str, object], value["files"])[relative])
    executed = cast(list[list[int]], record["executed_branches"])
    missing = next(item for item in executed if item[0] == line_number)
    executed.remove(missing)
    cast(list[list[int]], record["missing_branches"]).append(missing)
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    report = _checker(namespace)(path, repository_root=repository_root)
    assert report["ok"] is False
    assert report["critical_odds_ingestion_branch_coverage_percent"] < 95.0
