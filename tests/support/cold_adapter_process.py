"""Supervise the exact cold-adapter pytest case in a fresh, bounded process."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path

CHILD_FLAG = "DMF_PULSE_COLD_ADAPTER_BENCHMARK_CHILD"
CASE = "test_thirty_fixture_inferences_under_100ms"
NODE = f"tests/unit/football_events/test_team_strength_adapter.py::{CASE}"
ROOT = Path(__file__).resolve().parents[2]
PROOF = {
    "cold_adapter_calls": "30",
    "cold_adapter_unique_outputs": "30",
    "cold_adapter_initial_cache_entries": "0",
    "cold_adapter_cache_misses": "1",
    "cold_adapter_cache_hits": "29",
}


def run_cold_adapter_child(folder: Path) -> dict[str, object]:
    """Accept only an actual passing cold benchmark, never a bare child exit."""
    folder.mkdir(exist_ok=False)
    junit = folder / "junit.xml"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-m",
        "performance",
        "-p",
        "no:cacheprovider",
        f"--basetemp={folder / 'temp'}",
        f"--junitxml={junit}",
        NODE,
    ]
    environment = os.environ.copy()
    environment[CHILD_FLAG] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    receipt: dict[str, object] = {"command": command, "status": "RUNNING"}

    def persist() -> None:
        (folder / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    persist()
    try:
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, timeout=90)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        code, stdout, stderr = 124, error.stdout or b"", error.stderr or b""
    except OSError as error:
        code, stdout, stderr = 127, b"", type(error).__name__.encode()
    (folder / "stdout.log").write_bytes(stdout)
    (folder / "stderr.log").write_bytes(stderr)
    receipt.update(
        status="FAIL",
        exit_code=code,
        stdout_sha256=hashlib.sha256(stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr).hexdigest(),
    )
    persist()
    assert code == 0, f"Cold adapter child failed ({code}): {stdout[-8192:]!r} {stderr[-8192:]!r}"
    assert junit.is_file() and junit.stat().st_size <= 65536, "Cold adapter JUnit absent/oversized"
    body = junit.read_bytes()
    receipt["junit_sha256"] = hashlib.sha256(body).hexdigest()
    persist()
    try:
        junit_text = body.decode("utf-8")
        stdout_text = stdout.decode("utf-8")
        stderr_text = stderr.decode("utf-8")
        assert b"<!doctype" not in body.lower() and b"<!entity" not in body.lower(), (
            "Cold adapter JUnit declarations forbidden"
        )
        report = ET.fromstring(body)
    except (ET.ParseError, UnicodeError) as error:
        raise AssertionError("Cold adapter JUnit malformed") from error
    assert report.tag == "testsuites" and len(report) == 1 and report[0].tag == "testsuite", (
        "Cold adapter report shape differs"
    )
    suite = report[0]
    assert all(
        suite.get(key) == value
        for key, value in {"tests": "1", "failures": "0", "errors": "0", "skipped": "0"}.items()
    ), "Cold adapter suite counts differ"
    assert all(
        node.tag in {"properties", "testcase", "system-out", "system-err"} for node in suite
    ), "Cold adapter suite shape differs"
    cases = suite.findall("testcase")
    assert (
        len(cases) == 1
        and cases[0].get("name") == CASE
        and cases[0].get("classname") == "tests.unit.football_events.test_team_strength_adapter"
    ), "Cold adapter case inventory differs"
    assert not any(report.findall(f".//{tag}") for tag in ("failure", "error", "skipped")), (
        "Cold adapter child did not pass the required case"
    )
    groups = suite.findall("properties")
    assert len(groups) == 1 and all(
        node.tag == "property" and not list(node) for node in groups[0]
    ), "Cold adapter proof shape differs"
    properties = groups[0].findall("property")
    values = {p.get("name"): p.get("value") for p in properties}
    assert len(properties) == len(values) == len(PROOF) + 1, "Cold adapter proof inventory differs"
    assert all(values.get(key) == value for key, value in PROOF.items()), (
        "Cold adapter proof differs"
    )
    try:
        elapsed = Decimal(str(values.get("cold_adapter_elapsed_seconds")))
    except InvalidOperation as error:
        raise AssertionError("Cold adapter elapsed proof invalid") from error
    assert elapsed.is_finite() and 0 <= elapsed < Decimal("0.1"), "Cold adapter exceeded 100ms"
    assert len(stdout) <= 65536 and len(stderr) <= 65536, "Cold adapter child streams oversized"
    receipt.update(status="PASS", proof=values)
    persist()
    return {
        **receipt,
        "stdout_text": stdout_text,
        "stderr_text": stderr_text,
        "junit_text": junit_text,
    }
