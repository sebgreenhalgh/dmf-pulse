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
import hashlib
import json
import socket
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError

class BlockMarkets:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "dmf_pulse.markets" or fullname.startswith("dmf_pulse.markets."):
            raise ModuleNotFoundError("market import blocked")
        return None

sys.meta_path.insert(0, BlockMarkets())

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
from dmf_pulse.football_events.score_prior_request import ScorePriorRequest
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.client import OpenFootballHttpResponse
from dmf_pulse.ingestion.openfootball.config import (
    APPROVED_PROFILE_ID,
    OpenFootballProviderConfig,
    load_provider_config,
    load_rights_profiles,
)
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorBundle,
    CurrentScorePriorResult,
    CurrentScorePriorService,
    build_current_score_prior_bundle,
    score_prior_request_from_bundle,
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
assert "dmf_pulse.markets" not in sys.modules
assert ScorePriorRequest(
    home_goal_rate=Decimal("1.613158"),
    away_goal_rate=Decimal("1.374561"),
).public_dict()["home_goal_rate"] == "1.613158"

class NeverTransport:
    transport_id = "never"
    calls = 0
    def send(self, request):
        self.calls += 1
        raise AssertionError("rights refusal crossed the transport boundary")

never_transport = NeverTransport()
service = CurrentScorePriorService(transport=never_transport)
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
assert never_transport.calls == 0

def fixtures():
    teams = [f"Team {index:02d}" for index in range(1, 21)]
    rotation = list(teams)
    result = []
    for leg in range(2):
        for round_index in range(19):
            for index in range(10):
                left = rotation[index]
                right = rotation[-index - 1]
                home, away = (left, right) if leg == 0 else (right, left)
                result.append((home, away, leg * 19 + round_index + 1))
            rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    return result

def season_body(season):
    matches = []
    for index, (home_team, away_team, round_number) in enumerate(fixtures()):
        home_score = 2 if index < season.home_goals - season.expected_matches else 1
        away_score = 2 if index < season.away_goals - season.expected_matches else 1
        full_time = [home_score, away_score]
        if index < season.object_ht_ft_count:
            score = {"ft": full_time, "ht": [0, 0]}
        elif index < season.object_ht_ft_count + season.object_ft_count:
            score = {"ft": full_time}
        else:
            score = full_time
        matches.append({
            "date": (datetime(2023, 7, 1, tzinfo=UTC) + timedelta(days=round_number))
                .date().isoformat(),
            "round": f"Round {round_number}",
            "score": score,
            "team1": home_team,
            "team2": away_team,
            "time": "15:00",
        })
    return json.dumps(
        {"matches": matches, "name": season.expected_name},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

def identity(body):
    header = f"blob {len(body)}\0".encode("ascii")
    return {
        "blob_sha1": hashlib.sha1(header + body, usedforsecurity=False).hexdigest(),
        "byte_size": len(body),
        "content_sha256": hashlib.sha256(body).hexdigest(),
    }

licence_body = b"Creative Commons CC0 1.0 Universal\n"
bodies = {season.path: season_body(season) for season in config.seasons}
bodies[config.licence.path] = licence_body
raw_config = config.model_dump()
raw_config["licence"] = {**raw_config["licence"], **identity(licence_body)}
raw_config["seasons"] = tuple(
    {**season, **identity(bodies[str(season["path"])])}
    for season in raw_config["seasons"]
)
synthetic_config = OpenFootballProviderConfig.model_validate(raw_config)

class FakeTransport:
    transport_id = "installed_fake_transport"
    def __init__(self):
        self.calls = 0
    def send(self, request):
        self.calls += 1
        resource_path = "/".join(request.path.lstrip("/").split("/")[3:])
        body = bodies[resource_path]
        content_type = "text/plain" if resource_path == "LICENSE.md" else "application/json"
        return OpenFootballHttpResponse(
            status_code=200,
            content_type=content_type,
            headers={"content-type": content_type},
            body=body,
        )

clock_values = iter(
    datetime(2026, 8, 30, 9, 0, tzinfo=UTC) + timedelta(seconds=index)
    for index in range(100)
)
transport = FakeTransport()
source_result = CurrentScorePriorService(
    provider_config=synthetic_config,
    rights_profiles=profiles,
    transport=transport,
    clock=lambda: next(clock_values),
    provider_config_identity="a" * 64,
    rights_config_identity="b" * 64,
).build(CurrentScorePriorBuildRequest(
    information_cutoff=datetime(2026, 8, 30, 10, 0, tzinfo=UTC),
    rights_profile_id=APPROVED_PROFILE_ID,
))
assert source_result.sample_size == 1140
assert source_result.home_goal_total == 1839
assert source_result.away_goal_total == 1567
assert source_result.score_prior_request.home_goal_rate == Decimal("1.613158")
assert source_result.score_prior_request.away_goal_rate == Decimal("1.374561")
assert transport.calls == 4

fixture_id = UUID("10000000-0000-7000-8000-000000000801")
competition_id = UUID("30000000-0000-7000-8000-000000000001")
home_team_id = UUID("20000000-0000-7000-8000-000000000001")
away_team_id = UUID("20000000-0000-7000-8000-000000000002")
as_of = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
bundle = build_current_score_prior_bundle(
    source_result,
    fixture_id=fixture_id,
    competition_id=competition_id,
    home_team_id=home_team_id,
    away_team_id=away_team_id,
    as_of=as_of,
)
calls_before_conversion = transport.calls
converted = score_prior_request_from_bundle(
    bundle,
    fixture_id=fixture_id,
    competition_id=competition_id,
    home_team_id=home_team_id,
    away_team_id=away_team_id,
    as_of=as_of,
)
assert converted is bundle.score_prior_request
assert converted.home_goal_rate == Decimal("1.613158")
assert transport.calls == calls_before_conversion

try:
    build_current_score_prior_bundle(
        source_result,
        fixture_id=fixture_id,
        competition_id=competition_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        as_of=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
    )
except IngestionError as error:
    assert error.code == "POST_CUTOFF"
else:
    raise AssertionError("installed wheel accepted a backdated bundle")

result_tamper = source_result.model_dump(mode="json")
result_tamper["score_prior_request"]["home_goal_rate"] = "1.700000"
try:
    CurrentScorePriorResult.model_validate_json(json.dumps(result_tamper))
except ValidationError:
    pass
else:
    raise AssertionError("installed wheel accepted result semantic tampering")

bundle_tamper = bundle.model_dump(mode="json")
bundle_tamper["fixture_id"] = "10000000-0000-7000-8000-000000000899"
try:
    CurrentScorePriorBundle.model_validate_json(json.dumps(bundle_tamper))
except ValidationError:
    pass
else:
    raise AssertionError("installed wheel accepted bundle semantic tampering")

assert not attempts
print(json.dumps({
    "approved_profile_packaged": True,
    "bundle_hash_tamper_blocked": True,
    "commit_pinned": True,
    "conversion_network_requests": transport.calls - calls_before_conversion,
    "exact_conversion": True,
    "fixture_bound_bundle": True,
    "market_free_fresh_import": True,
    "module_path": dmf_pulse.__file__,
    "network_requests": len(attempts),
    "past_as_of_blocked": True,
    "reference_rates_unchanged": True,
    "result_hash_tamper_blocked": True,
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
