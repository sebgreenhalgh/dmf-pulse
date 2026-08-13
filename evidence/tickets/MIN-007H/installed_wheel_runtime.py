"""Isolated installed-wheel runtime used by final Stage-7 assurance."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parents[3]
WHEEL_NAME: Final = "dmf_pulse-0.2.0-py3-none-any.whl"
EXPECTED_FIXTURE_ID: Final = "943094f5-1d10-5d96-b88b-d271464f3e48"
EXPECTED_TEAM_ID: Final = "cc1083fa-0c4a-59ab-b6c5-60c04f760782"
EXPECTED_AS_OF: Final = "2026-08-14T17:30:00Z"
RESOURCE_NAMES: Final[tuple[str, ...]] = (
    "MIN-007/canonical_history.json",
    "MIN-007/external_mapping_plan.json",
    "MIN-007/training_dataset.json",
    "MIN-007G/evaluation_dataset.json",
    "MIN-007G/minutes_baseline_policy.json",
    "MIN-007G/contexts/goalkeeper.json",
    "MIN-007G/contexts/hard_ineligible.json",
    "MIN-007G/contexts/high_rotation.json",
    "MIN-007G/contexts/insufficient_eligible_squad.json",
    "MIN-007G/contexts/new_manager.json",
    "MIN-007G/contexts/new_signing.json",
    "MIN-007G/contexts/promoted_team.json",
    "MIN-007G/contexts/rare_bench_60_plus.json",
    "MIN-007G/contexts/stable_xi.json",
)
NETWORK_HOOKS: Final[tuple[str, ...]] = (
    "socket.socket.connect",
    "socket.socket.connect_ex",
    "socket.create_connection",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.gethostbyname_ex",
    "socket.getnameinfo",
)

IMPORT_PROBE = """
import hashlib
import importlib.metadata
import json
import pathlib
import sys
import dmf_pulse
from dmf_pulse.availability.resources import (
    AVAILABILITY_RESOURCE_NAMES,
    availability_resource_bytes,
)
entries = [
    entry for entry in importlib.metadata.distribution("dmf-pulse").entry_points
    if entry.group == "console_scripts" and entry.name == "dmf"
]
print(json.dumps({
    "distribution_version": importlib.metadata.version("dmf-pulse"),
    "entry_points": [entry.value for entry in entries],
    "module_path": str(pathlib.Path(dmf_pulse.__file__).resolve()),
    "resource_names": list(AVAILABILITY_RESOURCE_NAMES),
    "resource_sha256": {
        name: hashlib.sha256(availability_resource_bytes(name)).hexdigest()
        for name in AVAILABILITY_RESOURCE_NAMES
    },
    "python_version": sys.version.split()[0],
    "sys_path": sys.path,
}, sort_keys=True))
"""

NETWORK_GUARD = r"""
from __future__ import annotations
import errno
import ipaddress
import json
import os
import socket
from pathlib import Path

_trace = Path(os.environ["DMF_NETWORK_TRACE_PATH"])
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_create_connection = socket.create_connection
_original_getaddrinfo = socket.getaddrinfo
_original_gethostbyname = socket.gethostbyname
_original_gethostbyname_ex = socket.gethostbyname_ex
_original_getnameinfo = socket.getnameinfo

def _write(kind, host="", port=None):
    with _trace.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": kind, "host": str(host), "port": port}, sort_keys=True) + "\n")

def _loopback(host):
    text = str(host).strip().lower()
    if text in {"", "localhost"}:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False

def _parts(address):
    if isinstance(address, tuple) and address:
        return address[0], address[1] if len(address) > 1 else None
    return address, None

def _connect(sock, address):
    host, port = _parts(address)
    _write("socket.socket.connect", host, port)
    if not _loopback(host):
        raise OSError(errno.EPERM, "non-loopback network blocked")
    return _original_connect(sock, address)

def _connect_ex(sock, address):
    host, port = _parts(address)
    _write("socket.socket.connect_ex", host, port)
    if not _loopback(host):
        return errno.EPERM
    return _original_connect_ex(sock, address)

def _create_connection(address, *args, **kwargs):
    host, port = _parts(address)
    _write("socket.create_connection", host, port)
    if not _loopback(host):
        raise OSError(errno.EPERM, "non-loopback network blocked")
    return _original_create_connection(address, *args, **kwargs)

def _getaddrinfo(host, port, *args, **kwargs):
    _write("socket.getaddrinfo", host, port)
    if not _loopback(host):
        raise OSError(errno.EPERM, "non-loopback hostname resolution blocked")
    return _original_getaddrinfo(host, port, *args, **kwargs)

def _gethostbyname(host):
    _write("socket.gethostbyname", host, None)
    if not _loopback(host):
        raise OSError(errno.EPERM, "non-loopback hostname resolution blocked")
    return _original_gethostbyname(host)

def _gethostbyname_ex(host):
    _write("socket.gethostbyname_ex", host, None)
    if not _loopback(host):
        raise OSError(errno.EPERM, "non-loopback hostname resolution blocked")
    return _original_gethostbyname_ex(host)

def _getnameinfo(sockaddr, flags):
    host, port = _parts(sockaddr)
    _write("socket.getnameinfo", host, port)
    if not _loopback(host):
        raise OSError(errno.EPERM, "non-loopback reverse resolution blocked")
    return _original_getnameinfo(sockaddr, flags)

socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.create_connection = _create_connection
socket.getaddrinfo = _getaddrinfo
socket.gethostbyname = _gethostbyname
socket.gethostbyname_ex = _gethostbyname_ex
socket.getnameinfo = _getnameinfo
_write("guard_startup", "", None)
"""


class WheelRuntimeError(RuntimeError):
    """A bounded installed-wheel verification failure."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def public_command(external_id: int = 701) -> tuple[str, ...]:
    return (
        "dmf",
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
        EXPECTED_AS_OF,
        "--model-key",
        "min007-baseline-v1",
        "--seed",
        "MIN-007-COHERENCE-V1",
        "--output",
        "json",
    )


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    step: str,
    expected: frozenset[int] = frozenset({0}),
) -> subprocess.CompletedProcess[str]:
    try:
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
            timeout=240,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WheelRuntimeError(f"{step} could not complete") from exc
    if result.returncode not in expected:
        raise WheelRuntimeError(f"{step} failed with exit code {result.returncode}")
    return result


def _runtime_python(environment_root: Path) -> Path:
    return (
        environment_root / "Scripts" / "python.exe"
        if os.name == "nt"
        else environment_root / "bin" / "python"
    )


def _runtime_entry_point(environment_root: Path) -> Path:
    return (
        environment_root / "Scripts" / "dmf.exe"
        if os.name == "nt"
        else environment_root / "bin" / "dmf"
    )


def _site_packages(
    environment_root: Path, environment_python: Path, environment: dict[str, str]
) -> Path:
    result = _run(
        (
            str(environment_python),
            "-I",
            "-c",
            "import json,site;print(json.dumps(site.getsitepackages()))",
        ),
        cwd=environment_root,
        environment=environment,
        step="isolated site-packages discovery",
    )
    values = json.loads(result.stdout)
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise WheelRuntimeError("isolated site-packages discovery was ambiguous")
    candidates = {
        Path(value).resolve()
        for value in values
        if Path(value).resolve().is_relative_to(environment_root.resolve())
        and Path(value).name.lower() == "site-packages"
    }
    if len(candidates) != 1:
        raise WheelRuntimeError("isolated site-packages escaped or was ambiguous")
    return candidates.pop()


def _verify_record(archive: zipfile.ZipFile, names: tuple[str, ...]) -> dict[str, object]:
    record_names = [name for name in names if name.endswith(".dist-info/RECORD")]
    if len(record_names) != 1:
        raise WheelRuntimeError("wheel RECORD is missing or ambiguous")
    record_name = record_names[0]
    rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
    entries = {row[0]: row[1:] for row in rows if len(row) == 3}
    if len(rows) != len(entries) or set(entries) != set(names):
        raise WheelRuntimeError("wheel RECORD inventory differs from archive inventory")
    for name in names:
        digest, size = entries[name]
        if name == record_name:
            if digest or size:
                raise WheelRuntimeError("wheel RECORD self-entry must omit hash and size")
            continue
        data = archive.read(name)
        expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        if digest != f"sha256={expected}" or size != str(len(data)):
            raise WheelRuntimeError(f"wheel RECORD mismatch: {name}")
    return {"entry_count": len(entries), "record_path": record_name, "status": "PASS"}


def inspect_wheel(wheel: Path) -> dict[str, object]:
    if not wheel.is_file() or wheel.name != WHEEL_NAME:
        raise WheelRuntimeError("exact newly built Stage-7 wheel is unavailable")
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = tuple(archive.namelist())
            if len(names) != len(set(names)):
                raise WheelRuntimeError("wheel contains duplicate members")
            record = _verify_record(archive, names)
            resources: dict[str, dict[str, object]] = {}
            for relative in RESOURCE_NAMES:
                member = f"dmf_pulse/availability/resources/{relative}"
                data = archive.read(member)
                authority = ROOT / "fixtures" / "availability" / relative
                if data != authority.read_bytes():
                    raise WheelRuntimeError(f"packaged availability resource drift: {relative}")
                resources[relative] = {"sha256": sha256_bytes(data), "size": len(data)}
            metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise WheelRuntimeError("wheel metadata is missing or ambiguous")
            metadata = archive.read(metadata_names[0]).decode("utf-8")
            if "Name: dmf-pulse\n" not in metadata or "Version: 0.2.0\n" not in metadata:
                raise WheelRuntimeError("wheel metadata identity is incorrect")
    except (KeyError, OSError, UnicodeError, zipfile.BadZipFile) as exc:
        raise WheelRuntimeError("wheel archive is invalid") from exc
    return {
        "metadata_name": "dmf-pulse",
        "metadata_version": "0.2.0",
        "record": record,
        "resource_count": len(resources),
        "resources": resources,
        "status": "PASS",
    }


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "DMF_TEST_DATABASE_URL",
        "PGPASSWORD",
        "DMF_NETWORK_TRACE_PATH",
    ):
        environment.pop(name, None)
    environment["DMF_ENVIRONMENT"] = "REPLAY"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["UV_OFFLINE"] = "1"
    return environment


def _parse_result(result: subprocess.CompletedProcess[str], external_id: int) -> dict[str, Any]:
    try:
        value: Any = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise WheelRuntimeError(f"public {external_id} output is not JSON") from exc
    if not isinstance(value, dict):
        raise WheelRuntimeError(f"public {external_id} output is not an object")
    return value


def run_installed_wheel(
    *,
    network_guard: bool,
    additional_contexts: bool,
) -> dict[str, object]:
    """Install the exact wheel and exercise its public availability CLI outside the repository."""

    wheel = ROOT / "dist" / WHEEL_NAME
    wheel_inspection = inspect_wheel(wheel)
    uv = shutil.which("uv")
    if uv is None:
        raise WheelRuntimeError("uv is unavailable")
    environment = _environment()
    temporary_path: Path | None = None
    report: dict[str, object]
    with tempfile.TemporaryDirectory(prefix="dmf-min007-installed-") as temporary:
        temporary_path = Path(temporary).resolve()
        if temporary_path.is_relative_to(ROOT.resolve()):
            raise WheelRuntimeError("isolated runtime is inside the repository")
        environment_root = temporary_path / "runtime"
        _run(
            (uv, "venv", "--python", "3.13", "--no-project", str(environment_root)),
            cwd=temporary_path,
            environment=environment,
            step="isolated runtime creation",
        )
        environment_python = _runtime_python(environment_root)
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
            cwd=ROOT,
            environment=dependency_environment,
            step="isolated locked dependency installation",
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
                str(wheel),
            ),
            cwd=temporary_path,
            environment=environment,
            step="isolated wheel installation",
        )
        entry_point = _runtime_entry_point(environment_root).resolve()
        if not entry_point.is_file() or not entry_point.is_relative_to(environment_root.resolve()):
            raise WheelRuntimeError("installed dmf entry point is unavailable")
        probe_result = _run(
            (str(environment_python), "-I", "-c", IMPORT_PROBE),
            cwd=temporary_path,
            environment=environment,
            step="isolated import/resource probe",
        )
        probe: Any = json.loads(probe_result.stdout)
        if not isinstance(probe, dict):
            raise WheelRuntimeError("isolated import probe was invalid")
        module_path = Path(str(probe.get("module_path"))).resolve()
        raw_sys_path = probe.get("sys_path")
        if (
            not module_path.is_relative_to(environment_root.resolve())
            or module_path.is_relative_to(ROOT.resolve())
            or not isinstance(raw_sys_path, list)
            or any(str(ROOT.resolve()) in str(item) for item in raw_sys_path)
            or probe.get("distribution_version") != "0.2.0"
            or probe.get("entry_points") != ["dmf_pulse.cli.app:main"]
            or tuple(probe.get("resource_names", ())) != RESOURCE_NAMES
        ):
            raise WheelRuntimeError("isolated import/resource provenance failed")
        inspected_resources = wheel_inspection.get("resources")
        if not isinstance(inspected_resources, dict):
            raise WheelRuntimeError("inspected wheel resource inventory is invalid")
        expected_resource_hashes = {}
        for name, item in inspected_resources.items():
            if not isinstance(name, str) or not isinstance(item, dict):
                raise WheelRuntimeError("inspected wheel resource entry is invalid")
            digest = item.get("sha256")
            if not isinstance(digest, str):
                raise WheelRuntimeError("inspected wheel resource hash is invalid")
            expected_resource_hashes[name] = digest
        if probe.get("resource_sha256") != expected_resource_hashes:
            raise WheelRuntimeError("installed resources differ from inspected wheel")

        trace_path = temporary_path / "network_trace.jsonl"
        if network_guard:
            site_packages = _site_packages(environment_root, environment_python, environment)
            (site_packages / "sitecustomize.py").write_text(NETWORK_GUARD, encoding="utf-8")
            environment["DMF_NETWORK_TRACE_PATH"] = str(trace_path)

        actual_command = (str(entry_point), *public_command(701)[1:])
        result_701 = _run(
            actual_command,
            cwd=temporary_path,
            environment=environment,
            step="installed public external-ID-701 command",
        )
        value_701 = _parse_result(result_701, 701)
        projection = value_701.get("projection")
        if (
            value_701.get("status") != "PROJECTED"
            or value_701.get("fixture_id") != EXPECTED_FIXTURE_ID
            or value_701.get("team_id") != EXPECTED_TEAM_ID
            or value_701.get("as_of") != EXPECTED_AS_OF
            or not isinstance(projection, dict)
            or not isinstance(projection.get("result_sha256"), str)
        ):
            raise WheelRuntimeError("installed public external-ID-701 result is incorrect")
        public_701 = {
            "as_of": value_701["as_of"],
            "command": " ".join(public_command(701)),
            "entry_point": str(entry_point),
            "exit_code": result_701.returncode,
            "fixture_external_id": 701,
            "fixture_id": value_701["fixture_id"],
            "mapping_provider": "synthetic_availability",
            "mapping_resolution_success": True,
            "projection_present": True,
            "result_sha256": projection["result_sha256"],
            "status": value_701["status"],
            "stdout_sha256": sha256_bytes(result_701.stdout.encode("utf-8")),
            "team_id": value_701["team_id"],
        }

        additional: dict[str, object] = {}
        if additional_contexts:
            result_702 = _run(
                (str(entry_point), *public_command(702)[1:]),
                cwd=temporary_path,
                environment=environment,
                step="installed alternate context 702",
            )
            value_702 = _parse_result(result_702, 702)
            if value_702.get("status") != "PROJECTED":
                raise WheelRuntimeError("installed alternate context 702 did not project")
            result_709 = _run(
                (str(entry_point), *public_command(709)[1:]),
                cwd=temporary_path,
                environment=environment,
                step="installed blocked context 709",
                expected=frozenset({42}),
            )
            value_709 = _parse_result(result_709, 709)
            if (
                value_709.get("status") != "BLOCKED"
                or value_709.get("error_code") != "INSUFFICIENT_ELIGIBLE_SQUAD"
            ):
                raise WheelRuntimeError("installed blocked context 709 is incorrect")
            additional = {
                "702": {"exit_code": 0, "status": "PROJECTED"},
                "709": {
                    "error_code": "INSUFFICIENT_ELIGIBLE_SQUAD",
                    "exit_code": 42,
                    "status": "BLOCKED",
                },
            }

        network: dict[str, object] | None = None
        if network_guard:
            try:
                events: Any = [
                    json.loads(line)
                    for line in trace_path.read_text(encoding="utf-8").splitlines()
                    if line
                ]
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise WheelRuntimeError("network guard trace is unavailable") from exc
            if not isinstance(events, list) or not any(
                isinstance(event, dict) and event.get("kind") == "guard_startup" for event in events
            ):
                raise WheelRuntimeError("network guard did not start at the installed CLI boundary")
            attempts = [
                event
                for event in events
                if isinstance(event, dict) and event.get("kind") != "guard_startup"
            ]
            non_loopback = [
                event
                for event in attempts
                if str(event.get("host", "")).lower() not in {"", "localhost", "127.0.0.1", "::1"}
            ]
            if non_loopback:
                raise WheelRuntimeError(
                    "installed public 701 attempted non-loopback network access"
                )
            network = {
                "attempted_endpoints": attempts,
                "guard_active": True,
                "guard_hooks": list(NETWORK_HOOKS),
                "non_loopback_attempts": non_loopback,
                "non_loopback_count": len(non_loopback),
            }

        report = {
            "additional_contexts": additional,
            "isolated_runtime": {
                "cleaned_up": False,
                "current_working_directory": str(temporary_path),
                "entry_point": str(entry_point),
                "import_path": str(module_path),
                "interpreter": str(environment_python.resolve()),
                "repository_source_on_sys_path": False,
                "resource_count": len(RESOURCE_NAMES),
            },
            "network_guard": network,
            "public_701": public_701,
            "python": probe.get("python_version"),
            "sha256": sha256_file(wheel),
            "size": wheel.stat().st_size,
            "status": "PASS",
            "wheel": str(wheel.relative_to(ROOT)).replace("\\", "/"),
            "wheel_integrity": wheel_inspection,
        }
    if temporary_path is None or temporary_path.exists():
        raise WheelRuntimeError("isolated runtime cleanup failed")
    isolated = report["isolated_runtime"]
    if not isinstance(isolated, dict):
        raise WheelRuntimeError("isolated runtime report is invalid")
    isolated["cleaned_up"] = True
    return report


__all__ = [
    "EXPECTED_AS_OF",
    "EXPECTED_FIXTURE_ID",
    "EXPECTED_TEAM_ID",
    "NETWORK_HOOKS",
    "RESOURCE_NAMES",
    "ROOT",
    "WHEEL_NAME",
    "WheelRuntimeError",
    "public_command",
    "run_installed_wheel",
    "sha256_bytes",
]
