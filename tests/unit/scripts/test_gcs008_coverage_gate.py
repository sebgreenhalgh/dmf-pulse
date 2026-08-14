from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path("scripts/check_gcs008_coverage_gates.py")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gcs008_coverage_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _summary(
    *,
    statements: int = 10,
    covered: int = 10,
    branches: int = 10,
    branch_covered: int = 10,
) -> dict[str, int]:
    return {
        "covered_branches": branch_covered,
        "covered_lines": covered,
        "num_branches": branches,
        "num_statements": statements,
    }


def _payload(module: ModuleType, summary: dict[str, int] | None = None) -> dict[str, object]:
    chosen = summary or _summary()
    names = set(module.CRITICAL_FILES) | {module.CLI_PATH}
    names.add("src/dmf_pulse/football_events/service.py")
    return {"files": {name: {"summary": chosen} for name in names}}


def test_coverage_gate_passes_measured_complete_input(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(_payload(module)), encoding="utf-8")
    report = module.evaluate(path)
    assert report["status"] == "PASS"
    assert report["aggregate"] == {
        "branch_percent": 100.0,
        "statement_percent": 100.0,
    }


def test_coverage_gate_accepts_windows_coverage_paths(tmp_path: Path) -> None:
    module = _module()
    payload = _payload(module)
    files = payload["files"]
    assert isinstance(files, dict)
    payload["files"] = {name.replace("/", "\\"): value for name, value in files.items()}
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert module.evaluate(path)["status"] == "PASS"


def test_coverage_gate_rejects_duplicate_normalized_paths(tmp_path: Path) -> None:
    module = _module()
    payload = _payload(module)
    files = payload["files"]
    assert isinstance(files, dict)
    name = sorted(module.CRITICAL_FILES)[0]
    files[name.replace("/", "\\")] = files[name]
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(module.CoverageGateError, match="duplicate normalized path"):
        module.evaluate(path)


def test_coverage_gate_fails_when_critical_file_is_absent(tmp_path: Path) -> None:
    module = _module()
    payload = _payload(module)
    files = payload["files"]
    assert isinstance(files, dict)
    files.pop(sorted(module.CRITICAL_FILES)[0])
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(module.CoverageGateError, match="mandatory GCS-008 files"):
        module.evaluate(path)


def test_coverage_gate_fails_below_threshold(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "coverage.json"
    path.write_text(
        json.dumps(
            _payload(
                module,
                _summary(statements=10, covered=8, branches=10, branch_covered=7),
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(module.CoverageGateError, match="aggregate statement coverage"):
        module.evaluate(path)


def test_coverage_gate_rejects_impossible_counts(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "coverage.json"
    path.write_text(
        json.dumps(_payload(module, _summary(statements=1, covered=2))),
        encoding="utf-8",
    )
    with pytest.raises(module.CoverageGateError, match="line coverage is impossible"):
        module.evaluate(path)


def test_coverage_gate_rejects_unreadable_json(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "coverage.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(module.CoverageGateError, match="unreadable"):
        module.evaluate(path)
