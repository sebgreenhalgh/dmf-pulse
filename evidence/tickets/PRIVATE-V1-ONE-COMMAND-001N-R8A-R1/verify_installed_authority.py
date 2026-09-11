"""Offline R8A-R1 acceptance harness, not a product command or live probe."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

SMOKE = r"""
import hashlib
import json
import os
import runpy
import socket
import sys
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

attempts = []
def forbidden(*args, **kwargs):
    attempts.append("forbidden access")
    raise AssertionError("network or environment inspection forbidden")

socket.create_connection = socket.getaddrinfo = forbidden
socket.socket.connect = socket.socket.connect_ex = forbidden
import dmf_pulse.ingestion.odds.config as config
script = runpy.run_path(sys.argv[1], run_name="offline_authority_check")
script["EnvironmentOddsCredentialProvider"]._configured = forbidden
script["EnvironmentOddsCredentialProvider"].get_credential = forbidden
class NoEnvironment(dict):
    __getitem__ = get = __contains__ = forbidden
os.environ = NoEnvironment()
os.getenv = forbidden

profile = config.load_rights_profiles()["the_odds_api_private_analytics_v1"]
raw = resources.files("dmf_pulse").joinpath(config.RIGHTS_RESOURCE).read_bytes()
assert hashlib.sha256(raw).hexdigest() == sys.argv[2]
assert profile.human_approval_id == "DMF-R8A-PRIVATE-RIGHTS-2026-09-11"
assert profile.approved_by == "Sebastian"
assert profile.account_scope == "Sebastian-owned and authorized private The Odds API account"
assert profile.geography_scope == "United Kingdom private use"
assert profile.approved_purpose == (
    "Private, operator-initiated observation of current EPL H2H/totals market coverage "
    "across the officially assigned three-Gameweek horizon for DMF Pulse R8A."
)
assert profile.terms_version == "checked-2026-08-31"
assert profile.checked_at == datetime(2026, 9, 11, 21, 21, 31, tzinfo=UTC)
assert profile.approved_at == datetime(2026, 9, 11, 21, 22, 20, tzinfo=UTC)
assert script["live_rights_blocker"](
    profile, profile.human_approval_id, True, datetime(2026, 9, 11, 21, 23, tzinfo=UTC)
) is None
module = Path(config.__file__).resolve()
assert Path(sys.argv[3]).resolve() in module.parents
assert Path(sys.argv[4]).resolve() not in module.parents
assert attempts == []
print(json.dumps({
    "status": "PASS", "installed_external_authority": True,
    "canonical_resource_byte_identical": True,
    "approval_id": profile.human_approval_id,
    "rights_config_sha256": config.rights_config_sha256(),
    "provider_requests": 0, "credential_inspections": 0,
}))
"""


def run(command: list[str], cwd: Path, *, text: str | None = None) -> str:
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
        # Never echo inherited environment or arbitrary subprocess diagnostics.
        raise RuntimeError(f"offline wheel verification step failed: exit {result.returncode}")
    return result.stdout


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required")
    wheel = ROOT / "dist/dmf_pulse-0.2.0-py3-none-any.whl"
    if not wheel.is_file():
        raise RuntimeError("build the current wheel first")
    requirements = run(
        [uv, "export", "--frozen", "--offline", "--no-dev", "--no-emit-project"], ROOT
    )
    digest = hashlib.sha256((ROOT / "config/rights/odds_profiles.json").read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="dmf-r8a-r1-authority-") as temporary:
        target = Path(temporary).resolve()
        if target == ROOT or ROOT in target.parents:
            raise RuntimeError("wheel environment must be outside the repository")
        environment = target / "venv"
        run([uv, "venv", "--offline", "--python", "3.13", "--no-project", str(environment)], target)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(
            [uv, "pip", "sync", "--offline", "--require-hashes", "--python", str(python), "-"],
            target,
            text=requirements,
        )
        run(
            [uv, "pip", "install", "--offline", "--no-deps", "--python", str(python), str(wheel)],
            target,
        )
        output = run(
            [
                str(python),
                "-I",
                "-c",
                SMOKE,
                str(ROOT / "scripts/probe_horizon_market_coverage.py"),
                digest,
                str(environment),
                str(ROOT),
            ],
            target,
        )
        report = json.loads(output)
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
