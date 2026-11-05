"""Execute the shipped JS session lifecycle offline; no browser/provider inputs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "scenario",
    (
        "background_open",
        "hidden_response",
        "show_before_abort_settles",
        "duplicate_events",
        "unauthorized",
        "logout",
        "logout_during_pending",
    ),
)
def test_actual_controller_authenticated_resume_without_acquisition(scenario: str) -> None:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("Hosted CI must supply its existing Node QA runtime")
        pytest.skip("Optional existing Node QA runtime is unavailable; no package dependency")
    root = Path(__file__).resolve().parents[3]
    controller = root / "src/dmf_pulse/dashboard/resources/desk.js"
    harness = root / "tests/fixtures/dashboard_session_bootstrap.cjs"
    environment = {
        name: os.environ[name]
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if name in os.environ
    }
    environment["PATH"] = str(Path(node).parent)
    result = subprocess.run(
        [node, str(harness), str(controller), scenario],
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    receipt = json.loads(result.stdout)
    assert receipt["state"] == "PASS"
    assert receipt["scenario"] == scenario
    assert receipt["source_sha256"] == hashlib.sha256(controller.read_bytes()).hexdigest()
    assert receipt["maximum_polling_intervals"] <= 1
    assert receipt["provider_requests"] == 0
