from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path("scripts/validate_gcs008_scope.py")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gcs008_scope", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scope_accepts_stage_paths_and_sorts() -> None:
    module = _module()
    assert module.validate_changed_paths(
        [
            "src/dmf_pulse/football_events/poisson.py",
            "IMPLEMENTATION_PLAN.md",
            "PLANS.md",
            "src/dmf_pulse/cli/app.py",
        ]
    ) == (
        "IMPLEMENTATION_PLAN.md",
        "PLANS.md",
        "src/dmf_pulse/cli/app.py",
        "src/dmf_pulse/football_events/poisson.py",
    )


def test_scope_rejects_stage7_change() -> None:
    module = _module()
    with pytest.raises(module.ScopeError, match="frozen dependency"):
        module.validate_changed_paths(["src/dmf_pulse/availability/service.py"])


def test_scope_rejects_migration_and_lock_changes() -> None:
    module = _module()
    with pytest.raises(module.ScopeError, match="frozen dependency"):
        module.validate_changed_paths(["src/dmf_pulse/database/migrations/new.py"])
    with pytest.raises(module.ScopeError, match="frozen dependency"):
        module.validate_changed_paths(["uv.lock"])


def test_scope_rejects_unrelated_path_and_empty_diff() -> None:
    module = _module()
    with pytest.raises(module.ScopeError, match="outside GCS-008"):
        module.validate_changed_paths(["src/dmf_pulse/prices/model.py"])
    with pytest.raises(module.ScopeError, match="diff is empty"):
        module.validate_changed_paths([])


def test_scope_rejects_unsafe_path() -> None:
    module = _module()
    with pytest.raises(module.ScopeError, match="unsafe"):
        module.validate_changed_paths(["../AGENTS.md"])


def test_scope_rejects_delivery_helper_patch() -> None:
    module = _module()
    with pytest.raises(module.ScopeError, match="outside GCS-008"):
        module.validate_changed_paths(["PLANS_GCS008_APPEND.patch"])


def test_scope_rejects_prefix_lookalike_paths() -> None:
    module = _module()
    with pytest.raises(module.ScopeError, match="outside GCS-008"):
        module.validate_changed_paths(["public_contracts/joint_score_distribution.schema.json.bak"])
    with pytest.raises(module.ScopeError, match="outside GCS-008"):
        module.validate_changed_paths(["docs/stages/GCS-008.md.backup"])


@pytest.mark.parametrize(
    "path",
    [
        "src/dmf_pulse/football_events/player_scorer.py",
        "src/dmf_pulse/football_events/player_assists.py",
        "src/dmf_pulse/football_events/card_model.py",
        "src/dmf_pulse/football_events/goalkeeper_saves.py",
        "src/dmf_pulse/football_events/penalty_events.py",
        "src/dmf_pulse/football_events/event_timing.py",
        "src/dmf_pulse/football_events/full_event_simulation.py",
        "src/dmf_pulse/football_events/fpl_points.py",
        "src/dmf_pulse/football_events/fpl_points_optimizer.py",
        "src/dmf_pulse/football_events/fpl_points_optimisation.py",
    ],
)
def test_scope_rejects_later_stage_event_modules(path: str) -> None:
    module = _module()
    with pytest.raises(module.ScopeError, match="outside GCS-008"):
        module.validate_changed_paths([path])


def test_git_changed_paths_includes_uncommitted_and_untracked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def fake_run_git(arguments: list[str], *, allow_failure: bool = False) -> str:
        del allow_failure
        if arguments[:2] == ["cat-file", "-e"]:
            return ""
        if arguments == ["branch", "--show-current"]:
            return module.EXPECTED_BRANCH + "\n"
        if arguments == ["diff", "--name-only", module.REQUIRED_PARENT, "--"]:
            return "src/dmf_pulse/cli/app.py\n"
        if arguments == ["ls-files", "--others", "--exclude-standard"]:
            return "src/dmf_pulse/football_events/poisson.py\n"
        raise AssertionError(arguments)

    monkeypatch.setattr(module, "_run_git", fake_run_git)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: module.subprocess.CompletedProcess(args[0], 0, "", ""),
    )
    assert module._git_changed_paths() == (
        "src/dmf_pulse/cli/app.py",
        "src/dmf_pulse/football_events/poisson.py",
    )


def test_git_changed_paths_accepts_pull_request_head_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def fake_run_git(arguments: list[str], *, allow_failure: bool = False) -> str:
        del allow_failure
        if arguments[:2] == ["cat-file", "-e"]:
            return ""
        if arguments == ["branch", "--show-current"]:
            return ""
        if arguments == ["diff", "--name-only", module.REQUIRED_PARENT, "--"]:
            return "IMPLEMENTATION_PLAN.md\n"
        if arguments == ["ls-files", "--others", "--exclude-standard"]:
            return ""
        raise AssertionError(arguments)

    monkeypatch.setattr(module, "_run_git", fake_run_git)
    monkeypatch.setenv("GITHUB_HEAD_REF", module.EXPECTED_BRANCH)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: module.subprocess.CompletedProcess(args[0], 0, "", ""),
    )
    assert module._git_changed_paths() == ("IMPLEMENTATION_PLAN.md",)
