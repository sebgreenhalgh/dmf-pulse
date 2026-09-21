"""Verify CURRENT-TEAM-STRENGTH-001A-P0 from an offline installed wheel."""

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
    raise VerificationError("installed P0 smoke emitted no JSON result")


_INSTALLED_SMOKE = r"""
import json
import socket
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

attempts = []
def blocked(*args, **kwargs):
    attempts.append((args, kwargs))
    raise AssertionError("installed P0 smoke attempted network access")

socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.socket.sendto = blocked

import dmf_pulse
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability
from dmf_pulse.ingestion.openfootball.config import (
    APPROVED_PROFILE_ID,
    TEAM_STRENGTH_APPROVED_PROFILE_ID,
    load_rights_profiles,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    SourceFreshnessState,
    classify_source_freshness,
    eligibility_not_before,
    load_current_team_strength_governance,
    load_historical_team_identity,
    resolve_openfootball_team,
)

profiles = load_rights_profiles()
assert set(profiles) == {APPROVED_PROFILE_ID, TEAM_STRENGTH_APPROVED_PROFILE_ID}
profile = profiles[TEAM_STRENGTH_APPROVED_PROFILE_ID]
assert profile.capabilities[RightsCapability.MODEL_TRAINING] is CapabilityValue.ALLOW
assert profile.capabilities[RightsCapability.PUBLIC_DISPLAY] is CapabilityValue.DENY
assert profile.capabilities[RightsCapability.REDISTRIBUTION] is CapabilityValue.DENY

identity = load_historical_team_identity()
policy = load_current_team_strength_governance()
assert identity.canonical_club_count == 42
assert identity.alias_count == 56
assert identity.additional_alias_count == 14
assert identity.record_count == 56
assert len(identity.seasons_covered) == 17
assert identity.unresolved_club_count == 0
assert identity.ambiguous_mapping_count == 0
assert policy.materiality_policy.calibration_relative_harm_limit == Decimal("0.01")
assert policy.materiality_policy.player_xp_materiality_per_gw == Decimal("0.15")
assert policy.materiality_policy.transfer_horizon_materiality_points == Decimal("0.50")
assert policy.materiality_policy.prospective_min_gameweeks == 10
assert policy.materiality_policy.prospective_min_labelled_fixtures == 100
assert policy.model_implementation_present is False
assert policy.production_active is False

old_id = resolve_openfootball_team(
    identity, season_code="2019/20", source_team_name="Manchester City"
)
new_id = resolve_openfootball_team(
    identity, season_code="2020/21", source_team_name="Manchester City FC"
)
assert old_id == new_id
try:
    resolve_openfootball_team(
        identity, season_code="2020/21", source_team_name="manchester city fc"
    )
except IngestionError as error:
    assert error.code == "MAPPING_FAILED"
else:
    raise AssertionError("installed artifact performed fuzzy/casefold matching")

assert eligibility_not_before(date(2026, 9, 19)) == datetime(2026, 9, 21, tzinfo=UTC)
cutoff = datetime(2026, 9, 21, 12, tzinfo=UTC)
common = {
    "cutoff": cutoff,
    "missing_due": 0,
    "canonical_mapping_valid": True,
    "status_unambiguous": True,
    "schema_valid": True,
    "source_lineage_valid": True,
}
assert classify_source_freshness(
    latest_successful_usable_retrieval=cutoff - timedelta(hours=24), **common
) is SourceFreshnessState.FRESH
assert classify_source_freshness(
    latest_successful_usable_retrieval=cutoff - timedelta(hours=72), **common
) is SourceFreshnessState.DEGRADED
assert classify_source_freshness(
    latest_successful_usable_retrieval=cutoff - timedelta(hours=73), **common
) is SourceFreshnessState.STALE_BLOCKED

assert not attempts
print(json.dumps({
    "alias_count": identity.alias_count,
    "canonical_club_count": identity.canonical_club_count,
    "clean_import_network_requests": len(attempts),
    "identity_semantic_sha256": identity.root_semantic_sha256,
    "module_path": dmf_pulse.__file__,
    "policy_semantic_sha256": policy.semantic_sha256,
    "rights_profiles_packaged": True,
    "status": "PASS",
}, sort_keys=True))
"""


def verify() -> dict[str, Any]:
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv is unavailable")
    wheel = _wheel()
    with tempfile.TemporaryDirectory(prefix="dmf-team-strength-p0-wheel-") as temporary:
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
            step="installed P0 smoke",
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
