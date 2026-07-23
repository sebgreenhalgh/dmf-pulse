"""Independent coverage-gate false-success tests."""

from __future__ import annotations

import json
import math
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest


def _checker(repository_root: Path) -> Callable[[Path], dict[str, Any]]:
    namespace = runpy.run_path(str(repository_root / "scripts" / "check_coverage_gates.py"))
    return cast(Callable[[Path], dict[str, Any]], namespace["check_coverage"])


def _coverage(overall: float, covered: int = 98, total: int = 100) -> dict[str, object]:
    return {
        "totals": {"percent_branches_covered": overall},
        "files": {
            "src/dmf_pulse/rules/compiler.py": {
                "summary": {"covered_branches": covered, "num_branches": total}
            },
            "src/dmf_pulse/data_model/repositories.py": {
                "summary": {"covered_branches": 92, "num_branches": 100}
            },
        },
    }


@pytest.mark.unit
def test_coverage_gate_accepts_both_independent_thresholds(
    repository_root: Path, tmp_path: Path
) -> None:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(_coverage(90.0)), encoding="utf-8")
    report = _checker(repository_root)(path)
    assert report["ok"] is True
    assert report["rules_branch_coverage_percent"] == 98.0
    assert report["data_model_database_branch_coverage_percent"] == 92.0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("overall", "covered", "total"),
    [
        (math.nan, 98, 100),
        (math.inf, 98, 100),
        (90.0, 101, 100),
        (90.0, -1, 100),
    ],
)
def test_coverage_gate_rejects_nonfinite_or_impossible_metrics(
    repository_root: Path,
    tmp_path: Path,
    overall: float,
    covered: int,
    total: int,
) -> None:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(_coverage(overall, covered, total)), encoding="utf-8")
    with pytest.raises(ValueError):
        _checker(repository_root)(path)
