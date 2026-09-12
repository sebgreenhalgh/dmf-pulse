"""Offline R8B-R1 installed-wheel authority verification; not a live command."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_APPROVAL = "DMF-R8B-PRIVATE-RIGHTS-2026-09-12"

_SMOKE = r"""
import hashlib, json, os, socket, sys
from datetime import UTC, datetime
from importlib import resources

attempts = []
def forbidden(*args, **kwargs):
    attempts.append("forbidden access")
    raise AssertionError("network or environment inspection forbidden")
socket.create_connection = socket.getaddrinfo = forbidden
socket.socket.connect = socket.socket.connect_ex = forbidden
import dmf_pulse.ingestion.odds.config as config
class NoEnvironment(dict):
    __getitem__ = get = __contains__ = forbidden
os.environ = NoEnvironment()
os.getenv = forbidden
profile = config.load_rights_profiles()["the_odds_api_private_analytics_v1"]
raw = resources.files("dmf_pulse").joinpath(config.RIGHTS_RESOURCE).read_bytes()
assert hashlib.sha256(raw).hexdigest() == sys.argv[1]
assert profile.human_approval_id == "DMF-R8B-PRIVATE-RIGHTS-2026-09-12"
assert profile.approved_at == datetime(2026, 9, 12, 12, 29, 46, tzinfo=UTC)
assert profile.checked_at == datetime(2026, 9, 11, 21, 21, 31, tzinfo=UTC)
assert profile.terms_version == "checked-2026-08-31"
assert attempts == []
print(json.dumps({"status": "PASS", "approval_id": profile.human_approval_id,
    "provider_requests": 0, "credential_inspections": 0,
    "canonical_resource_byte_identical": True}))
"""


def _run(command: list[str], cwd: Path, *, text: str | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"offline wheel verification failed: exit {result.returncode}")
    return result.stdout


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required")
    wheel = ROOT / "dist/dmf_pulse-0.2.0-py3-none-any.whl"
    if not wheel.is_file():
        raise RuntimeError("build the current wheel first")
    requirements = _run(
        [uv, "export", "--frozen", "--offline", "--no-dev", "--no-emit-project"], ROOT
    )
    digest = hashlib.sha256((ROOT / "config/rights/odds_profiles.json").read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="dmf-r8b-r1-authority-") as temporary:
        target = Path(temporary).resolve()
        environment = target / "venv"
        _run(
            [uv, "venv", "--offline", "--python", "3.13", "--no-project", str(environment)], target
        )
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        _run(
            [uv, "pip", "sync", "--offline", "--require-hashes", "--python", str(python), "-"],
            target,
            text=requirements,
        )
        _run(
            [uv, "pip", "install", "--offline", "--no-deps", "--python", str(python), str(wheel)],
            target,
        )
        print(_run([str(python), "-I", "-c", _SMOKE, digest], target).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
