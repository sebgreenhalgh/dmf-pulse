"""Lossless generated-report transport; branch proof and scanner limits stay intact."""

from __future__ import annotations

import argparse
import copy
import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.scripts.test_ci_coverage_shards import _module

pytestmark = pytest.mark.unit


def _report() -> dict:
    return {
        "meta": {"branch_coverage": True, "version": "owned-test"},
        "totals": {
            "covered_lines": 4,
            "num_statements": 5,
            "covered_branches": 2,
            "num_branches": 3,
        },
        "files": {
            "owned.py": {
                "executed_lines": [1, 2, 4, 5],
                "missing_lines": [3],
                "executed_branches": [[1, 2], [1, 4]],
                "missing_branches": [[2, 3]],
                "functions": {"example": {"contexts": ["é", 'quote"', "\\", "\n"]}},
                "classes": {"Example": {"arbitrary": [None, True, 1, 1.0, -0.0]}},
            }
        },
        "unknown_future_field": {"preserve": [1, {"nested": "unchanged"}]},
    }


def _write(tmp_path: Path, report: dict | None = None) -> tuple[Path, bytes]:
    path = tmp_path / "coverage.json"
    body = json.dumps(_report() if report is None else report, indent=2).encode()
    path.write_bytes(body)
    return path, body


def test_pure_validator_stays_read_only_and_cli_preserves_every_field(tmp_path, capsys):
    module = _module()
    path, before = _write(tmp_path)
    expected = module.verify_branch_report(path)
    assert path.read_bytes() == before
    result = module._command_verify_branch_report(argparse.Namespace(coverage_json=path))
    after = path.read_bytes()
    assert result == expected
    assert (
        after == (json.dumps(_report(), ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    )
    assert json.loads(after) == json.loads(before)
    assert len(after) < len(before)
    captured = capsys.readouterr()
    assert captured.out == ""
    receipt = json.loads(captured.err)
    assert receipt["semantic_payload_preserved"] and receipt["rewritten"]
    assert receipt["input_bytes"] == len(before) and receipt["output_bytes"] == len(after)
    assert not list(tmp_path.glob(".coverage-transport-*"))


def test_canonical_cli_is_idempotent_without_staging_or_replacement(tmp_path, monkeypatch, capsys):
    module = _module()
    path = tmp_path / "coverage.json"
    body = (json.dumps(_report(), ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    path.write_bytes(body)

    def denied(*_args, **_kwargs):
        raise AssertionError("idempotent transport must not stage or replace")

    monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", denied)
    monkeypatch.setattr(module.os, "replace", denied)
    module._command_verify_branch_report(argparse.Namespace(coverage_json=path))
    assert path.read_bytes() == body
    assert json.loads(capsys.readouterr().err)["rewritten"] is False


@pytest.mark.parametrize(
    "change", ("line-only", "zero-branches", "impossible-count", "empty-files")
)
def test_original_branch_failures_leave_report_bytes_unchanged(tmp_path, capsys, change):
    module = _module()
    value = _report()
    if change == "line-only":
        value["meta"]["branch_coverage"] = False
    elif change == "zero-branches":
        value["totals"]["num_branches"] = 0
    elif change == "impossible-count":
        value["totals"]["covered_branches"] = 4
    else:
        value["files"] = {}
    path, before = _write(tmp_path, value)
    with pytest.raises(module.ShardPlannerError):
        module._command_verify_branch_report(argparse.Namespace(coverage_json=path))
    assert path.read_bytes() == before
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert not list(tmp_path.glob(".coverage-transport-*"))


@pytest.mark.parametrize("extra", ('{"duplicate":1,"duplicate":2}', "NaN", "Infinity", "-Infinity"))
def test_ambiguous_or_nonfinite_nested_transport_is_not_rewritten(tmp_path, capsys, extra):
    module = _module()
    value = copy.deepcopy(_report())
    value["unknown_future_field"] = "REPLACE_OWNED"
    before = json.dumps(value).replace('"REPLACE_OWNED"', extra).encode()
    path = tmp_path / "coverage.json"
    path.write_bytes(before)
    with pytest.raises(module.ShardPlannerError):
        module._command_verify_branch_report(argparse.Namespace(coverage_json=path))
    assert path.read_bytes() == before
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert not list(tmp_path.glob(".coverage-transport-*"))


def test_replace_failure_preserves_original_and_removes_staged_file(tmp_path, monkeypatch, capsys):
    module = _module()
    path, before = _write(tmp_path)

    def failure(*_args):
        raise OSError("owned replacement failure")

    monkeypatch.setattr(module.os, "replace", failure)
    with pytest.raises(module.ShardPlannerError):
        module._command_verify_branch_report(argparse.Namespace(coverage_json=path))
    assert path.read_bytes() == before
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert not list(tmp_path.glob(".coverage-transport-*"))


def test_staged_corruption_never_replaces_the_report(tmp_path, monkeypatch, capsys):
    module = _module()
    path, before = _write(tmp_path)
    original_read = Path.read_bytes

    def corrupt(target):
        return (
            b"corrupt staged bytes"
            if target.name.startswith(".coverage-transport-")
            else original_read(target)
        )

    monkeypatch.setattr(Path, "read_bytes", corrupt)
    with pytest.raises(module.ShardPlannerError, match="staged"):
        module._command_verify_branch_report(argparse.Namespace(coverage_json=path))
    assert path.read_bytes() == before
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert not list(tmp_path.glob(".coverage-transport-*"))


def test_concurrent_report_drift_is_not_overwritten(tmp_path, monkeypatch, capsys):
    module = _module()
    path, _before = _write(tmp_path)
    changed = b'{"owned_external_change":true}'
    original_verify = module.verify_branch_report

    def drift(target):
        result = original_verify(target)
        target.write_bytes(changed)
        return result

    monkeypatch.setattr(module, "verify_branch_report", drift)
    with pytest.raises(module.ShardPlannerError, match="changed"):
        module._command_verify_branch_report(argparse.Namespace(coverage_json=path))
    assert path.read_bytes() == changed
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert not list(tmp_path.glob(".coverage-transport-*"))


def test_report_identity_drift_is_not_replaced(tmp_path, monkeypatch, capsys):
    module = _module()
    path, before = _write(tmp_path)
    original_stat = Path.lstat
    calls = 0

    def drift(target):
        nonlocal calls
        result = original_stat(target)
        if target == path:
            calls += 1
            if calls > 1:
                return SimpleNamespace(
                    st_mode=stat.S_IFREG, st_dev=result.st_dev, st_ino=result.st_ino + 1
                )
        return result

    monkeypatch.setattr(Path, "lstat", drift)
    with pytest.raises(module.ShardPlannerError, match="changed"):
        module._command_verify_branch_report(argparse.Namespace(coverage_json=path))
    assert path.read_bytes() == before
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert not list(tmp_path.glob(".coverage-transport-*"))


def test_cli_stdout_keeps_exact_branch_proof_schema(tmp_path, capsys):
    module = _module()
    path, _before = _write(tmp_path)
    assert module.main(["verify-branch-report", str(path)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "covered_branches": 2,
        "num_branches": 3,
        "schema_version": module.BRANCH_REPORT_SCHEMA_VERSION,
        "status": "PASS",
    }
    assert json.loads(captured.err)["semantic_payload_preserved"]
