"""Verify PTS-009 from an offline clean wheel installation outside the checkout."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures/points/PTS-009"
REQUIRED_WHEEL_MEMBERS = {
    "dmf_pulse/fpl_points/__init__.py",
    "dmf_pulse/fpl_points/allocation.py",
    "dmf_pulse/fpl_points/models.py",
    "dmf_pulse/fpl_points/resources/event_allocation_baseline.yaml",
    "dmf_pulse/fpl_points/resources/fpl_points_simulation.yaml",
    "dmf_pulse/fpl_points/rules_adapter.py",
    "dmf_pulse/fpl_points/service.py",
    "dmf_pulse/fpl_points/upstream.py",
}


class VerificationError(RuntimeError):
    """The isolated wheel or installed Stage-9 vertical is invalid."""


def _environment(environment_root: Path | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "DATABASE_URL",
        "DMF_DATABASE_URL",
        "THE_ODDS_API_KEY",
    ):
        environment.pop(name, None)
    environment.update(
        PYTHONNOUSERSITE="1",
        UV_OFFLINE="1",
        HTTP_PROXY="http://127.0.0.1:9",
        HTTPS_PROXY="http://127.0.0.1:9",
        NO_PROXY="",
    )
    if environment_root is not None:
        environment["VIRTUAL_ENV"] = str(environment_root)
    return environment


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    step: str,
    expected_codes: tuple[int, ...] = (0,),
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
    if result.returncode not in expected_codes:
        raise VerificationError(
            f"{step} failed with exit {result.returncode}: "
            f"{result.stdout[-500:]} {result.stderr[-500:]}"
        )
    return result


def _json_object(text: str) -> dict[str, Any]:
    for line in reversed([item for item in text.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise VerificationError("installed CLI did not emit one JSON object")


def _validate_record(archive: zipfile.ZipFile) -> int:
    members = archive.namelist()
    if len(members) != len(set(members)):
        raise VerificationError("wheel contains duplicate members")
    if any(
        PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in members
    ):
        raise VerificationError("wheel contains an unsafe member path")
    records = [name for name in members if name.endswith(".dist-info/RECORD")]
    if len(records) != 1:
        raise VerificationError("wheel must contain exactly one RECORD")
    record_name = records[0]
    try:
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
    except (KeyError, UnicodeError, csv.Error) as exc:
        raise VerificationError("wheel RECORD is unreadable") from exc
    by_path: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3 or not row[0] or row[0] in by_path:
            raise VerificationError("wheel RECORD has a malformed or duplicate row")
        by_path[row[0]] = (row[1], row[2])
    if set(by_path) != set(members):
        raise VerificationError("wheel RECORD membership differs from archive")
    for name in members:
        digest, size = by_path[name]
        data = archive.read(name)
        if name == record_name:
            if digest or size:
                raise VerificationError("wheel RECORD self-row must omit hash and size")
            continue
        expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(
            b"="
        ).decode("ascii")
        if digest != expected or size != str(len(data)):
            raise VerificationError(f"wheel RECORD integrity mismatch: {name}")
    return len(members)


def _python(environment_root: Path) -> Path:
    return (
        environment_root / "Scripts/python.exe"
        if os.name == "nt"
        else environment_root / "bin/python"
    )


def _dmf(environment_root: Path) -> Path:
    return environment_root / "Scripts/dmf.exe" if os.name == "nt" else environment_root / "bin/dmf"


def verify(wheel: Path) -> dict[str, Any]:
    wheel = wheel.resolve()
    if not wheel.is_file():
        raise VerificationError("wheel path does not exist")
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            bad_member = archive.testzip()
            record_count = _validate_record(archive)
            for name in ("event_allocation_baseline.yaml", "fpl_points_simulation.yaml"):
                member = f"dmf_pulse/fpl_points/resources/{name}"
                if archive.read(member) != (REPOSITORY_ROOT / "config/models" / name).read_bytes():
                    raise VerificationError(
                        f"packaged resource differs from tracked config: {name}"
                    )
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise VerificationError("wheel archive is unavailable or invalid") from exc
    if bad_member is not None:
        raise VerificationError(f"wheel CRC failed for {bad_member}")
    missing = sorted(REQUIRED_WHEEL_MEMBERS - names)
    if missing:
        raise VerificationError(f"wheel omits Stage-9 modules/resources: {missing}")
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv is unavailable")
    with tempfile.TemporaryDirectory(prefix="dmf-pts009-wheel-") as temporary:
        root = Path(temporary).resolve()
        checkout = REPOSITORY_ROOT.resolve()
        if root == checkout or checkout in root.parents:
            raise VerificationError("isolated environment is inside the checkout")
        environment_root = root / "venv"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(environment_root)],
            cwd=root,
            environment=_environment(),
            step="isolated virtual environment creation",
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
            cwd=checkout,
            environment=environment,
            step="locked runtime dependency installation",
        )
        python = _python(environment_root)
        dmf = _dmf(environment_root)
        _run(
            [uv, "pip", "install", "--offline", "--no-deps", "--python", str(python), str(wheel)],
            cwd=root,
            environment=environment,
            step="wheel installation",
        )
        module = _run(
            [str(python), "-c", "import dmf_pulse; print(dmf_pulse.__file__)"],
            cwd=root,
            environment=environment,
            step="installed module location",
        )
        module_path = Path(module.stdout.strip()).resolve()
        if module_path == checkout or checkout in module_path.parents:
            raise VerificationError("installed command imported the checkout")
        request = root / "request.json"
        rules = root / "reference_rules.json"
        policy = root / "policy.yaml"
        request.write_bytes((FIXTURE_ROOT / "fixture_request_example.json").read_bytes())
        rules.write_bytes((FIXTURE_ROOT / "reference_ruleset_test_only.json").read_bytes())
        policy.write_bytes(
            (REPOSITORY_ROOT / "config/models/fpl_points_simulation.yaml").read_bytes()
        )
        artifact_root = root / "artifacts"
        command = [
            str(dmf),
            "fpl-points",
            "simulate-fixture",
            "--request",
            str(request),
            "--ruleset",
            str(rules),
            "--mc-policy",
            str(policy),
            "--artifact-root",
            str(artifact_root),
            "--output",
            "json",
        ]
        replay = _json_object(
            _run(command, cwd=root, environment=environment, step="installed TEST CLI").stdout
        )
        result = replay.get("result")
        if not isinstance(result, dict) or result.get("status") != "SUCCESS":
            raise VerificationError("installed TEST CLI did not produce a successful result")
        artifact_path = replay.get("artifact_path")
        if not isinstance(artifact_path, str) or not Path(artifact_path).is_file():
            raise VerificationError("installed TEST CLI did not persist its artifact")
        _run(
            [str(dmf), "fpl-points", "validate", "--artifact", artifact_path, "--output", "json"],
            cwd=root,
            environment=environment,
            step="installed artifact validation",
        )
        diagnostics = _json_object(
            _run(
                [
                    str(dmf),
                    "fpl-points",
                    "mc-diagnostics",
                    "--artifact",
                    artifact_path,
                    "--output",
                    "json",
                ],
                cwd=root,
                environment=environment,
                step="installed MC diagnostics",
            ).stdout
        )
        production_payload = json.loads(request.read_text(encoding="utf-8"))
        production_payload["projection_mode"] = "PRODUCTION"
        production_request = root / "production_request.json"
        production_request.write_text(json.dumps(production_payload), encoding="utf-8")
        production_command = list(command)
        production_command[production_command.index(str(request))] = str(production_request)
        production = _json_object(
            _run(
                production_command,
                cwd=root,
                environment=environment,
                step="installed PRODUCTION fail-closed CLI",
                expected_codes=(4,),
            ).stdout
        )
        production_result = production.get("result")
        if not isinstance(production_result, dict) or (
            production_result.get("status"),
            production_result.get("error_code"),
        ) != ("BLOCKED", "RULESET_NOT_ACTIVE"):
            raise VerificationError("installed PRODUCTION command did not fail closed")
        return {
            "module_path": str(module_path),
            "production_error_code": production_result["error_code"],
            "record_members_verified": record_count,
            "replay_result_sha256": result.get("result_sha256"),
            "scenario_count": diagnostics["monte_carlo"]["scenario_count"],
            "schema_version": "pts-009-wheel-verification-v1",
            "status": "PASS",
            "wheel": wheel.name,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        }


def _wheel_argument() -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path)
    argument = parser.parse_args()
    if argument.wheel is not None:
        return argument.wheel
    wheels = sorted((REPOSITORY_ROOT / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise VerificationError("--wheel is required unless dist contains exactly one wheel")
    return wheels[0]


def main() -> int:
    try:
        report = verify(_wheel_argument())
    except VerificationError as exc:
        print(
            json.dumps(
                {
                    "error": {"code": "PTS009_WHEEL_VERIFICATION_FAILED", "message": str(exc)},
                    "schema_version": "pts-009-wheel-verification-v1",
                    "status": "FAIL",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
