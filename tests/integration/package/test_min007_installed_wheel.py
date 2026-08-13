"""Isolated installed-wheel proof for the public MIN-007 REPLAY command."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ENTRY_POINT_RUNNER = (
    "import importlib.metadata as m,sys;"
    "e=[e for e in m.distribution('dmf-pulse').entry_points "
    "if e.group=='console_scripts' and e.name=='dmf'];"
    "ep=e[0] if len(e)==1 else sys.exit(125);"
    "sys.exit(ep.load()()) "
    "if ep.value=='dmf_pulse.cli.app:main' else sys.exit(125)"
)
IMPORT_PROBE = """
import json
import pathlib
import sys
import dmf_pulse
from dmf_pulse.availability.resources import (
    AVAILABILITY_RESOURCE_NAMES,
    availability_resource_bytes,
)
module_path = pathlib.Path(dmf_pulse.__file__).resolve()
print(json.dumps({
    "module_path": str(module_path),
    "resource_count": len(AVAILABILITY_RESOURCE_NAMES),
    "resource_sizes": {
        name: len(availability_resource_bytes(name))
        for name in AVAILABILITY_RESOURCE_NAMES
    },
    "sys_path": sys.path,
}, sort_keys=True))
"""


def _python(environment_root: Path) -> Path:
    return (
        environment_root / "Scripts" / "python.exe"
        if os.name == "nt"
        else environment_root / "bin" / "python"
    )


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    expected: int = 0,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        text=True,
        timeout=180,
    )
    assert result.returncode == expected, (result.stdout, result.stderr)
    return result


def _availability_args(external_id: int) -> tuple[str, ...]:
    return (
        "availability",
        "predict",
        "--fixture-external-provider",
        "synthetic_availability",
        "--fixture-external-id",
        str(external_id),
        "--season-code",
        "2026/27",
        "--team-side",
        "HOME",
        "--as-of",
        "2026-08-14T17:30:00Z",
        "--model-key",
        "min007-baseline-v1",
        "--seed",
        "MIN-007-COHERENCE-V1",
        "--output",
        "json",
    )


def test_public_availability_command_runs_from_isolated_installed_wheel(
    repository_root: Path, tmp_path: Path
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    outside = tmp_path / "installed-wheel-proof"
    outside.mkdir()
    distributions = outside / "distributions"
    environment_root = outside / "runtime"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("VIRTUAL_ENV", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["UV_OFFLINE"] = "1"

    _run(
        (uv, "build", "--wheel", "--out-dir", str(distributions)),
        cwd=repository_root,
        environment=environment,
    )
    wheels = list(distributions.glob("dmf_pulse-0.2.0-py3-none-any.whl"))
    assert len(wheels) == 1
    _run(
        (uv, "venv", "--python", "3.13", "--no-project", str(environment_root)),
        cwd=outside,
        environment=environment,
    )
    environment_python = _python(environment_root)
    dependency_environment = dict(environment)
    dependency_environment["VIRTUAL_ENV"] = str(environment_root)
    _run(
        (
            uv,
            "sync",
            "--frozen",
            "--offline",
            "--no-dev",
            "--no-install-project",
            "--active",
        ),
        cwd=repository_root,
        environment=dependency_environment,
    )
    _run(
        (
            uv,
            "pip",
            "install",
            "--offline",
            "--no-deps",
            "--python",
            str(environment_python),
            str(wheels[0]),
        ),
        cwd=outside,
        environment=environment,
    )

    probe = json.loads(
        _run(
            (str(environment_python), "-I", "-c", IMPORT_PROBE),
            cwd=outside,
            environment=environment,
        ).stdout
    )
    installed_module = Path(probe["module_path"]).resolve()
    assert installed_module.is_relative_to(environment_root.resolve())
    assert not installed_module.is_relative_to(repository_root.resolve())
    assert all(str(repository_root.resolve()) not in entry for entry in probe["sys_path"])
    assert probe["resource_count"] == 14
    assert all(size > 0 for size in probe["resource_sizes"].values())

    replay_environment = dict(environment)
    replay_environment["DMF_ENVIRONMENT"] = "REPLAY"
    entry_point = (str(environment_python), "-I", "-c", ENTRY_POINT_RUNNER)
    projected = json.loads(
        _run(
            (*entry_point, *_availability_args(701)),
            cwd=outside,
            environment=replay_environment,
        ).stdout
    )
    assert projected["status"] == "PROJECTED"
    assert projected["fixture_id"] == "943094f5-1d10-5d96-b88b-d271464f3e48"
    assert projected["team_id"] == "cc1083fa-0c4a-59ab-b6c5-60c04f760782"
    assert projected["as_of"] == "2026-08-14T17:30:00Z"
    assert projected["projection"] is not None

    alternate = json.loads(
        _run(
            (*entry_point, *_availability_args(702)),
            cwd=outside,
            environment=replay_environment,
        ).stdout
    )
    assert alternate["status"] == "PROJECTED"
    blocked = json.loads(
        _run(
            (*entry_point, *_availability_args(709)),
            cwd=outside,
            environment=replay_environment,
            expected=42,
        ).stdout
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["error_code"] == "INSUFFICIENT_ELIGIBLE_SQUAD"
