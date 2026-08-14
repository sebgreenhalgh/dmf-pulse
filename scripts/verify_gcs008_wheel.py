"""Verify GCS-008 from an offline clean wheel installation outside the repository."""

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
FIXTURE = REPOSITORY_ROOT / "fixtures/events/score/GCS-008/balanced_fixture.json"
EXPECTED_RESULT_SHA256 = "6537d930643e91629ee793d15aa6f4f86930a36640862aa99b13a201d62b94ea"
REQUIRED_WHEEL_MEMBERS = {
    "dmf_pulse/football_events/resources/score_baseline.yaml",
    "dmf_pulse/football_events/resources/score_distribution_request.schema.json",
    "dmf_pulse/football_events/resources/joint_score_distribution.schema.json",
    "dmf_pulse/football_events/resources/score_distribution_result.schema.json",
}


class VerificationError(RuntimeError):
    """An installed-wheel acceptance failure."""


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


def _dmf(environment_root: Path) -> Path:
    return environment_root / "Scripts/dmf.exe" if os.name == "nt" else environment_root / "bin/dmf"


def _environment(environment_root: Path | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "THE_ODDS_API_KEY",
        "ODDS_API_KEY",
        "DMF_ODDS_API_KEY",
        "DATABASE_URL",
        "DMF_DATABASE_URL",
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


def _json_object(text: str) -> dict[str, Any]:
    for line in reversed([item for item in text.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise VerificationError("installed CLI did not emit one JSON object")


def _validate_wheel_record(archive: zipfile.ZipFile) -> int:
    """Verify exact wheel membership, SHA-256 digests and byte sizes from RECORD."""

    members = archive.namelist()
    if len(members) != len(set(members)):
        raise VerificationError("wheel contains duplicate archive members")
    for name in members:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise VerificationError(f"wheel contains an unsafe member path: {name}")
    records = [name for name in members if name.endswith(".dist-info/RECORD")]
    if len(records) != 1:
        raise VerificationError("wheel must contain exactly one dist-info RECORD")
    record_name = records[0]
    try:
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
    except (KeyError, UnicodeError, csv.Error) as exc:
        raise VerificationError("wheel RECORD is unreadable") from exc
    by_path: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3 or not row[0] or row[0] in by_path:
            raise VerificationError("wheel RECORD contains a malformed or duplicate row")
        by_path[row[0]] = (row[1], row[2])
    if set(by_path) != set(members):
        raise VerificationError("wheel RECORD membership differs from the archive")
    for name in members:
        digest, size = by_path[name]
        data = archive.read(name)
        if name == record_name:
            if digest or size:
                raise VerificationError("wheel RECORD self-row must omit hash and size")
            continue
        expected_digest = "sha256=" + base64.urlsafe_b64encode(
            hashlib.sha256(data).digest()
        ).rstrip(b"=").decode("ascii")
        if digest != expected_digest or size != str(len(data)):
            raise VerificationError(f"wheel RECORD integrity mismatch: {name}")
    return len(members)


def verify(wheel: Path) -> dict[str, Any]:
    wheel = wheel.resolve()
    if not wheel.is_file():
        raise VerificationError("wheel path does not exist")
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            bad_member = archive.testzip()
            record_members_verified = _validate_wheel_record(archive)
    except zipfile.BadZipFile as exc:
        raise VerificationError("wheel is not a valid ZIP archive") from exc
    if bad_member is not None:
        raise VerificationError(f"wheel CRC failed for {bad_member}")
    missing = sorted(REQUIRED_WHEEL_MEMBERS - names)
    if missing:
        raise VerificationError(f"wheel omits packaged GCS-008 resources: {missing}")
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv is unavailable")
    with tempfile.TemporaryDirectory(prefix="dmf-gcs008-wheel-") as temporary:
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
            cwd=REPOSITORY_ROOT,
            environment=environment,
            step="locked runtime dependency installation",
        )
        python = _python(environment_root)
        dmf = _dmf(environment_root)
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
        module = _run(
            [str(python), "-c", "import dmf_pulse; print(dmf_pulse.__file__)"],
            cwd=temporary_root,
            environment=environment,
            step="installed module location",
        )
        module_path = Path(module.stdout.strip()).resolve()
        if module_path == repository_root or repository_root in module_path.parents:
            raise VerificationError("installed command imported the repository source tree")
        fixture = temporary_root / "balanced_fixture.json"
        fixture.write_bytes(FIXTURE.read_bytes())
        artifact_root = temporary_root / "artifacts"
        command = _run(
            [
                str(dmf),
                "events",
                "score-distribution",
                "--fixture",
                str(fixture),
                "--artifact-root",
                str(artifact_root),
                "--output",
                "json",
            ],
            cwd=temporary_root,
            environment=environment,
            step="installed Stage-8 CLI",
        )
        payload = _json_object(command.stdout)
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("status") != "PROJECTED":
            raise VerificationError("installed Stage-8 CLI did not project the fixture")
        distribution = result.get("distribution")
        if not isinstance(distribution, dict):
            raise VerificationError("installed Stage-8 CLI omitted its distribution")
        if distribution.get("result_sha256") != EXPECTED_RESULT_SHA256:
            raise VerificationError("installed Stage-8 semantic identity differs from golden")
        artifact_path = payload.get("artifact_path")
        if not isinstance(artifact_path, str) or not Path(artifact_path).is_file():
            raise VerificationError("installed Stage-8 CLI did not persist its artifact")
        validation = _run(
            [
                str(dmf),
                "events",
                "validate",
                "--distribution",
                artifact_path,
                "--output",
                "json",
            ],
            cwd=temporary_root,
            environment=environment,
            step="installed Stage-8 artifact validation",
        )
        validation_payload = _json_object(validation.stdout)
        if validation_payload.get("status") != "VALID":
            raise VerificationError("installed artifact validator did not pass")
        return {
            "artifact_result_sha256": distribution["result_sha256"],
            "module_path": str(module_path),
            "record_members_verified": record_members_verified,
            "required_resources": sorted(REQUIRED_WHEEL_MEMBERS),
            "schema_version": "gcs008-wheel-verification-v1",
            "status": "PASS",
            "wheel": wheel.name,
        }


def _wheel_argument() -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path)
    arguments = parser.parse_args()
    if arguments.wheel is not None:
        return arguments.wheel
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
                    "error": {"code": "GCS008_WHEEL_VERIFICATION_FAILED", "message": str(exc)},
                    "schema_version": "gcs008-wheel-verification-v1",
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
