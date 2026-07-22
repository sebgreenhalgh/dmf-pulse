"""Clean installed-wheel integration proof using the portable verifier."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest


@pytest.mark.integration
def test_wheel_installs_and_runs_outside_source_tree(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UV_OFFLINE", "1")
    namespace = runpy.run_path(str(repository_root / "scripts" / "verify_wheel.py"))
    verify = namespace["verify_wheel"]
    assert callable(verify)
    report = verify(report_path=tmp_path / "package_report.json")
    assert report["status"] == "PASS"
    assert report["clean_environment_outside_repository"] is True
    assert report["cleaned_up"] is True
    assert report["installed_version_output"] == "dmf 0.2.0"
    assert report["installed_runtime_distributions"]
    assert report["locked_runtime_manifest_sha256"]
    assert report["doctor_status"] == "HEALTHY"
    wheel = report["wheel"]
    assert isinstance(wheel, dict)
    assert wheel["contains_py_typed"] is True
