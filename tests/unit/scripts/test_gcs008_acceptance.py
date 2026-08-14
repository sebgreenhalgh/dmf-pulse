from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path("scripts/validate_gcs008_acceptance.py")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gcs008_acceptance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_measured_state_binds_coverage_and_real_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    coverage = {
        "aggregate": {"branch_percent": 90.0, "statement_percent": 95.0},
        "status": "PASS",
    }
    monkeypatch.setattr(module, "evaluate_coverage", lambda path: coverage)
    monkeypatch.setattr(module, "_git_changed_paths", lambda: ("IMPLEMENTATION_PLAN.md",))
    assert module._validate_measured_state() == (coverage, 1)


def test_measured_state_fails_closed_without_coverage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "COVERAGE_PATH", tmp_path / "missing.json")
    with pytest.raises(ValueError, match="unreadable"):
        module._validate_measured_state()


def test_measured_state_fails_closed_for_out_of_scope_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "evaluate_coverage",
        lambda path: {"aggregate": {}, "status": "PASS"},
    )
    monkeypatch.setattr(module, "_git_changed_paths", lambda: ("uv.lock",))
    with pytest.raises(ValueError, match="frozen dependency"):
        module._validate_measured_state()


def test_clean_checkout_acceptance_inputs_are_all_tracked() -> None:
    module = _module()
    assert module._tracked_repository_paths() >= module.REQUIRED_TRACKED_ACCEPTANCE_INPUTS
    assert module._validate_tracked_acceptance_inputs() == len(
        module.REQUIRED_TRACKED_ACCEPTANCE_INPUTS
    )


def test_tracked_input_inventory_fails_closed_on_missing_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_tracked_repository_paths",
        lambda: module.REQUIRED_TRACKED_ACCEPTANCE_INPUTS - {"config/models/score_baseline.yaml"},
    )
    with pytest.raises(module.AcceptanceError, match=r"score_baseline\.yaml"):
        module._validate_tracked_acceptance_inputs()


def test_literal_ledger_uses_accepted_stage7_matrix_and_guaranteed_teardown() -> None:
    ledger = Path("ACCEPTANCE_COMMANDS.ps1").read_text(encoding="utf-8")
    assert "--baseline-revision 20260803_0005 --target head" in ledger
    assert "--baseline-revision 20260724_0002" not in ledger
    assert "docker compose -f compose.test.yaml up -d --wait" in ledger
    assert "finally {" in ledger
    assert "docker compose -f compose.test.yaml down -v --remove-orphans" in ledger


def test_ci_uses_the_accepted_stage7_matrix_and_measured_acceptance_boundary() -> None:
    linux = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    windows = Path(".github/workflows/windows-smoke.yml").read_text(encoding="utf-8")
    assert "--baseline-revision 20260803_0005 --target head" in linux
    assert "--baseline-revision 20260724_0002" not in linux
    assert "scripts/validate_gcs008_acceptance.py" in linux
    assert "scripts/validate_gcs008_acceptance.py" not in windows
    assert "scripts/verify_gcs008_wheel.py" in windows


def test_repository_validator_enforces_the_current_gcs008_ci_contract() -> None:
    script = Path("scripts/validate_repository.py")
    spec = importlib.util.spec_from_file_location("gcs008_repository_validator", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    errors: list[str] = []
    module._validate_ci_contract(Path.cwd(), errors)
    assert errors == []
    assert module._active_ticket(Path.cwd()) == "GCS-008"
