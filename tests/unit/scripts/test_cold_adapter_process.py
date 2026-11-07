"""A zero exit, skip or incomplete proof cannot pass the isolated benchmark."""

import json
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from tests.support import cold_adapter_process as runner


def report(*, names=None, properties=None, skipped=False, classname=None):
    document = ET.Element("testsuites")
    suite = ET.SubElement(document, "testsuite", tests="1", failures="0", errors="0", skipped="0")
    entries = ET.SubElement(suite, "properties")
    values = [*runner.PROOF.items(), ("cold_adapter_elapsed_seconds", "0.025")]
    for name, value in values if properties is None else properties:
        ET.SubElement(entries, "property", name=name, value=value)
    for name in [runner.CASE] if names is None else names:
        case = ET.SubElement(
            suite,
            "testcase",
            name=name,
            classname=classname or "tests.unit.football_events.test_team_strength_adapter",
        )
        if skipped:
            ET.SubElement(case, "skipped")
    return ET.tostring(document)


def fake_child(monkeypatch, *, body=None, code=0, stdout=b"native child\n"):
    def run(command, **options):
        assert command[:3] == [sys.executable, "-m", "pytest"]
        assert command[-1] == runner.NODE
        assert options["cwd"] == runner.ROOT
        assert options["env"][runner.CHILD_FLAG] == "1"
        assert options["timeout"] == 90 and options["capture_output"] is True
        assert "shell" not in options
        path = next(x.removeprefix("--junitxml=") for x in command if x.startswith("--junitxml="))
        if body is not None:
            runner.Path(path).write_bytes(body)
        return subprocess.CompletedProcess(command, code, stdout=stdout, stderr=b"")

    monkeypatch.setattr(runner.subprocess, "run", run)


def test_verified_case_preserves_native_evidence(tmp_path, monkeypatch):
    fake_child(monkeypatch, body=report())
    folder = tmp_path / "child with spaces"
    result = runner.run_cold_adapter_child(folder)
    assert result["status"] == "PASS"
    assert result["proof"]["cold_adapter_cache_misses"] == "1"
    assert result["proof"]["cold_adapter_cache_hits"] == "29"
    assert result["stdout_text"] == "native child\n"
    assert (folder / "stdout.log").read_bytes() == b"native child\n"
    assert (folder / "junit.xml").read_bytes() == report()
    assert json.loads((folder / "receipt.json").read_text())["status"] == "PASS"


@pytest.mark.parametrize(
    "body",
    [
        None,
        b"broken XML",
        b"x" * 65537,
        report(names=[]),
        report(names=[runner.CASE, runner.CASE]),
        report(names=["different_case"]),
        report(classname="different.module"),
        report(skipped=True),
        report(properties=[]),
    ],
    ids=[
        "missing",
        "malformed",
        "oversized",
        "zero",
        "multiple",
        "wrong-case",
        "wrong-module",
        "skipped",
        "no-proof",
    ],
)
def test_zero_exit_does_not_replace_required_work(tmp_path, monkeypatch, body):
    fake_child(monkeypatch, body=body)
    folder = tmp_path / "child"
    with pytest.raises(AssertionError):
        runner.run_cold_adapter_child(folder)
    assert json.loads((folder / "receipt.json").read_text())["status"] == "FAIL"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("cold_adapter_calls", "29"),
        ("cold_adapter_unique_outputs", "29"),
        ("cold_adapter_initial_cache_entries", "1"),
        ("cold_adapter_cache_misses", "0"),
        ("cold_adapter_cache_hits", "28"),
        ("cold_adapter_elapsed_seconds", "0.1"),
        ("cold_adapter_elapsed_seconds", "NaN"),
        ("cold_adapter_elapsed_seconds", "Infinity"),
        ("cold_adapter_elapsed_seconds", "-0.01"),
        ("cold_adapter_elapsed_seconds", "invalid"),
    ],
)
def test_wrong_cold_work_or_wall_time_cannot_pass(tmp_path, monkeypatch, key, value):
    values = {**runner.PROOF, "cold_adapter_elapsed_seconds": "0.025", key: value}
    fake_child(monkeypatch, body=report(properties=list(values.items())))
    with pytest.raises(AssertionError):
        runner.run_cold_adapter_child(tmp_path / "child")


def test_duplicate_proof_cannot_hide_wrong_value(tmp_path, monkeypatch):
    values = [*runner.PROOF.items(), ("cold_adapter_elapsed_seconds", "0.025")]
    fake_child(monkeypatch, body=report(properties=[("cold_adapter_cache_hits", "0"), *values]))
    with pytest.raises(AssertionError, match="inventory"):
        runner.run_cold_adapter_child(tmp_path / "child")


@pytest.mark.parametrize("kind", ["root-failure", "suite-count", "doctype", "nested-suite"])
def test_report_envelope_cannot_claim_a_false_pass(tmp_path, monkeypatch, kind):
    document = ET.fromstring(report())
    if kind == "root-failure":
        document.tag = "failure"
    elif kind == "suite-count":
        document[0].set("tests", "0")
        document[0].set("failures", "1")
    elif kind == "nested-suite":
        ET.SubElement(document[0], "testsuite")
    body = ET.tostring(document)
    if kind == "doctype":
        body = b'<!DOCTYPE testsuites [<!ENTITY owned "0.025">]>' + body
    fake_child(monkeypatch, body=body)
    with pytest.raises(AssertionError):
        runner.run_cold_adapter_child(tmp_path / "child")


def test_non_utf8_streams_are_retained_but_cannot_claim_lossless_pass(tmp_path, monkeypatch):
    fake_child(monkeypatch, body=report(), stdout=b"\xff")
    folder = tmp_path / "child"
    with pytest.raises(AssertionError):
        runner.run_cold_adapter_child(folder)
    assert (folder / "stdout.log").read_bytes() == b"\xff"
    assert json.loads((folder / "receipt.json").read_text())["status"] == "FAIL"


def test_nonzero_child_fails_even_with_valid_junit(tmp_path, monkeypatch):
    fake_child(monkeypatch, body=report(), code=1)
    with pytest.raises(AssertionError, match="failed"):
        runner.run_cold_adapter_child(tmp_path / "child")


@pytest.mark.parametrize("kind", ["timeout", "startup"])
def test_startup_and_timeout_leave_failed_evidence(tmp_path, monkeypatch, kind):
    def fail(command, **options):
        if kind == "timeout":
            raise subprocess.TimeoutExpired(command, options["timeout"], output=b"partial")
        raise OSError("owned startup failure")

    monkeypatch.setattr(runner.subprocess, "run", fail)
    folder = tmp_path / "child"
    with pytest.raises(AssertionError, match="failed"):
        runner.run_cold_adapter_child(folder)
    receipt = json.loads((folder / "receipt.json").read_text())
    assert receipt["status"] == "FAIL"
    assert receipt["exit_code"] == (124 if kind == "timeout" else 127)
    if kind == "timeout":
        assert (folder / "stdout.log").read_bytes() == b"partial"
