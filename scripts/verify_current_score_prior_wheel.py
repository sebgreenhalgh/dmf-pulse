"""Verify CURRENT-SCORE-PRIOR-001A from an offline wheel outside the repository."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class VerificationError(RuntimeError):
    """A bounded installed-wheel verification failure."""


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    step: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError(f"{step} could not complete") from exc
    if result.returncode != 0:
        raise VerificationError(
            f"{step} failed with exit {result.returncode}: "
            f"{result.stdout[-500:]} {result.stderr[-500:]}"
        )
    return result


def _python(environment_root: Path) -> Path:
    return (
        environment_root / "Scripts/python.exe"
        if os.name == "nt"
        else environment_root / "bin/python"
    )


def _environment(environment_root: Path | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "DATABASE_URL",
        "DMF_DATABASE_URL",
        "DMF_TEST_DATABASE_URL",
    ):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["UV_OFFLINE"] = "1"
    environment["HTTP_PROXY"] = "http://127.0.0.1:9"
    environment["HTTPS_PROXY"] = "http://127.0.0.1:9"
    environment["NO_PROXY"] = ""
    if environment_root is not None:
        environment["VIRTUAL_ENV"] = str(environment_root)
    return environment


def _wheel() -> Path:
    matches = sorted((REPOSITORY_ROOT / "dist").glob("dmf_pulse-0.2.0-py3-none-any.whl"))
    if len(matches) != 1:
        raise VerificationError("exactly one current dmf-pulse wheel is required")
    return matches[0].resolve()


def _json_object(output: str) -> dict[str, Any]:
    for line in reversed([item for item in output.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise VerificationError("installed score-prior smoke emitted no JSON result")


_INSTALLED_SMOKE = r"""
import json
import socket
from datetime import UTC, datetime
from decimal import Decimal

attempts = []
def blocked(*args, **kwargs):
    attempts.append((args, kwargs))
    raise AssertionError("installed score-prior smoke attempted network access")

socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.socket.sendto = blocked

import dmf_pulse
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.config import (
    APPROVED_PROFILE_ID,
    load_provider_config,
    load_rights_profiles,
)
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorService,
)

config = load_provider_config()
profiles = load_rights_profiles()
assert config.commit_sha == "f27dcbef681db2c3195f9def62316ce497278781"
assert config.expected_home_goal_rate == Decimal("1.613158")
assert config.expected_away_goal_rate == Decimal("1.374561")
assert tuple(item.season_code for item in config.seasons) == (
    "2023/24", "2024/25", "2025/26"
)
assert APPROVED_PROFILE_ID in profiles

class NeverTransport:
    transport_id = "never"
    def send(self, request):
        raise AssertionError("rights refusal crossed the transport boundary")

service = CurrentScorePriorService(transport=NeverTransport())
try:
    service.build(CurrentScorePriorBuildRequest(
        information_cutoff=datetime(2026, 8, 30, 10, 0, tzinfo=UTC),
        rights_profile_id="unapproved_profile",
    ))
except IngestionError as error:
    assert error.code == "RIGHTS_BLOCKED"
    assert error.details["transport_call_count"] == 0
else:
    raise AssertionError("installed wheel accepted an unavailable rights profile")

assert not attempts
print(json.dumps({
    "approved_profile_packaged": True,
    "commit_pinned": True,
    "module_path": dmf_pulse.__file__,
    "network_requests": len(attempts),
    "rights_zero_call": True,
    "status": "PASS",
}, sort_keys=True))
"""


def verify() -> dict[str, Any]:
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv is unavailable")
    wheel = _wheel()
    with tempfile.TemporaryDirectory(prefix="dmf-score-prior-wheel-") as temporary:
        temporary_root = Path(temporary).resolve()
        repository_root = REPOSITORY_ROOT.resolve()
        if temporary_root == repository_root or repository_root in temporary_root.parents:
            raise VerificationError("clean environment is inside the repository")
        environment_root = temporary_root / "venv"
        base_environment = _environment()
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(environment_root)],
            cwd=temporary_root,
            environment=base_environment,
            step="clean virtual environment creation",
        )
        environment = _environment(environment_root)
        _run(
            [
                uv,
                "sync",
                "--frozen",
                "--offline",
                "--no-dev",
                "--no-install-project",
                "--active",
            ],
            cwd=repository_root,
            environment=environment,
            step="locked runtime dependency installation",
        )
        python = _python(environment_root)
        _run(
            [
                uv,
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--python",
                str(python),
                str(wheel),
            ],
            cwd=temporary_root,
            environment=environment,
            step="wheel installation",
        )
        smoke = _run(
            [str(python), "-c", _INSTALLED_SMOKE],
            cwd=temporary_root,
            environment=environment,
            step="installed score-prior smoke",
        )
        report = _json_object(smoke.stdout)
        module_path = Path(str(report["module_path"])).resolve()
        if module_path == repository_root or repository_root in module_path.parents:
            raise VerificationError("installed smoke imported repository source")
        report["clean_environment_outside_repository"] = True
        report["wheel"] = wheel.name
        return report


def main() -> int:
    try:
        report = verify()
    except VerificationError as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
