"""Feedback selection cannot masquerade as complete exact-commit acceptance."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from tests.unit.scripts.script_support import load_script

checks = load_script("dev_checks")
FULL_JOBS, ROOT, SMOKES = checks.FULL_JOBS, checks.ROOT, checks.SMOKES
partial_commands, require_full_run = checks.partial_commands, checks.require_full_run


def full_payload():
    return {
        "headSha": "a" * 40,
        "workflowName": "dmf-pulse-ci",
        "workflowDatabaseId": 37,
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "jobs": [
            {"name": name, "status": "completed", "conclusion": "success"} for name in FULL_JOBS
        ],
    }


@pytest.mark.parametrize(
    "change", ["head", "pending", "failed", "missing", "duplicate", "skipped", "other_workflow"]
)
def test_full_refuses_partial_stale_or_incomplete_ci(change):
    payload = full_payload()
    if change == "head":
        payload["headSha"] = "b" * 40
    elif change == "pending":
        payload["status"] = "in_progress"
    elif change == "failed":
        payload["conclusion"] = "failure"
    elif change == "missing":
        payload["jobs"].pop()
    elif change == "duplicate":
        payload["jobs"][-1] = payload["jobs"][0]
    elif change == "skipped":
        payload["jobs"][0]["conclusion"] = "skipped"
    else:
        payload["workflowName"] = "unrelated-green-workflow"
    with pytest.raises(ValueError, match="FULL"):
        require_full_run(payload, "a" * 40, workflow_id=37)


def test_full_requires_all_twenty_jobs_at_exact_head():
    require_full_run(full_payload(), "a" * 40, workflow_id=37)
    assert len(FULL_JOBS) == 20


@pytest.mark.parametrize(
    "target",
    [
        "../tests",
        "C:/tests/a.py",
        "tests/../src",
        "tests/missing.py",
        "tests/unit/a.py::test_one",
        "--ignore=tests",
    ],
)
def test_partial_selection_rejects_escaping_unknown_and_node_only_targets(target):
    with pytest.raises(ValueError):
        partial_commands("focused", [target], [], [], ROOT / "review_pack/owned-plan")


def test_partial_feedback_includes_all_requested_modules_and_essential_smokes():
    target = "tests/unit/scripts/test_dev_checks.py"
    commands = partial_commands("fast", [target], [], [], ROOT / "review_pack/owned-plan")
    assert target in commands[-1]
    assert set(SMOKES).issubset(commands[-1])
    assert not any(arg.startswith("--cov") for arg in commands[-1])
    assert commands[0][-3:] == ["format", "--check", "."]


def test_integration_requires_cross_boundary_target_and_coverage_stays_explicit():
    with pytest.raises(ValueError, match="integration target"):
        partial_commands(
            "integration", ["tests/unit/scripts"], [], [], ROOT / "review_pack/owned-plan"
        )
    commands = partial_commands(
        "focused",
        ["tests/unit/operation/test_analysis_quality.py"],
        [],
        ["dmf_pulse.operation.analysis_quality"],
        ROOT / "review_pack/owned-plan",
    )
    assert "--cov-branch" in commands[-1]
    assert "--cov-fail-under=0" in commands[-1]
    with pytest.raises(ValueError, match="inside ignored"):
        partial_commands("fast", ["tests/unit/scripts"], [], [], ROOT / "evidence/outside")


def prepare_main(tmp_path, monkeypatch):
    target = tmp_path / "tests/unit/owned.py"
    target.parent.mkdir(parents=True)
    target.write_text("# owned\n", encoding="utf-8")
    monkeypatch.setattr(checks, "ROOT", tmp_path)
    monkeypatch.setattr(
        checks, "_git", lambda *args: "a" * 40 if args == ("rev-parse", "HEAD") else ""
    )


def test_interrupted_tier_never_leaves_a_pass_receipt(tmp_path, monkeypatch):
    prepare_main(tmp_path, monkeypatch)
    count = 0

    def run(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise KeyboardInterrupt
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(checks.subprocess, "run", run)
    with pytest.raises(KeyboardInterrupt):
        checks.main(["fast", "--target", "tests/unit/owned.py"])
    (receipt,) = (tmp_path / "review_pack/dev-checks").glob("*/receipt.json")
    value = json.loads(receipt.read_text())
    assert value["status"] == "INTERRUPTED"
    assert value["completed_steps"] == 1 and value["planned_steps"] == 3
    assert value["full_release_acceptance"] is False


@pytest.mark.parametrize("failure", ["startup", "timeout"])
def test_child_start_or_timeout_failure_is_retained(tmp_path, monkeypatch, failure):
    prepare_main(tmp_path, monkeypatch)

    def run(*args, **kwargs):
        if failure == "startup":
            raise OSError("owned exception details must not become receipt data")
        raise subprocess.TimeoutExpired(args[0], 180)

    monkeypatch.setattr(checks.subprocess, "run", run)
    expected = 127 if failure == "startup" else 124
    assert checks.main(["fast", "--target", "tests/unit/owned.py"]) == expected
    (receipt,) = (tmp_path / "review_pack/dev-checks").glob("*/receipt.json")
    value = json.loads(receipt.read_text())
    assert value["status"] == "FAIL" and value["steps"][0]["exit_code"] == expected
    assert "owned exception details" not in receipt.read_text()


def test_full_rechecks_source_after_workflow_queries(tmp_path, monkeypatch):
    prepare_main(tmp_path, monkeypatch)
    heads = iter(("a" * 40, "b" * 40))
    monkeypatch.setattr(
        checks, "_git", lambda *args: next(heads) if args == ("rev-parse", "HEAD") else ""
    )

    def run(command, **kwargs):
        payload = (
            full_payload()
            if command[1] == "run"
            else {"id": 37, "path": ".github/workflows/ci.yml"}
        )
        return SimpleNamespace(stdout=json.dumps(payload).encode())

    monkeypatch.setattr(checks.subprocess, "run", run)
    with pytest.raises(ValueError, match="source changed"):
        checks.main(["full", "--ci-run", "123"])
    (receipt,) = (tmp_path / "review_pack/dev-checks").glob("*/receipt.json")
    assert json.loads(receipt.read_text())["status"] == "INCOMPLETE_OR_FAILED"


def test_matching_display_name_cannot_substitute_another_workflow_id():
    payload = full_payload()
    payload["workflowDatabaseId"] = 99
    with pytest.raises(ValueError, match="authoritative workflow"):
        require_full_run(payload, "a" * 40, workflow_id=37)


def test_pr_merge_checkout_is_not_exact_head_full_acceptance():
    payload = full_payload()
    payload["event"] = "pull_request"
    with pytest.raises(ValueError, match="authoritative workflow"):
        require_full_run(payload, "a" * 40, workflow_id=37)
