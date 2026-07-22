"""Build and verify the DMF Pulse wheel from a clean environment outside the repository."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPOSITORY_ROOT / "evidence" / "tickets" / "FND-001" / "package_report.json"
BUNDLED_ZONEINFO = "dmf_pulse/_data/zoneinfo/Europe/London"
BUNDLED_ZONEINFO_SHA256 = "676541f0b8ad457c744c093f807589adcad909e3fd03f901787d08786eedbd33"


class VerificationError(Exception):
    """A safe package verification failure."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    step: str,
    timeout_seconds: float = 180.0,
    environment: dict[str, str] | None = None,
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
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise VerificationError(f"{step} timed out") from exc
    except OSError as exc:
        raise VerificationError(f"{step} could not start") from exc
    if result.returncode != 0:
        raise VerificationError(f"{step} failed with exit code {result.returncode}")
    return result


def _environment_python(environment_root: Path) -> Path:
    if os.name == "nt":
        return environment_root / "Scripts" / "python.exe"
    return environment_root / "bin" / "python"


def _environment_dmf(environment_root: Path) -> Path:
    if os.name == "nt":
        return environment_root / "Scripts" / "dmf.exe"
    return environment_root / "bin" / "dmf"


def _sanitized_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("VIRTUAL_ENV", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def verify_wheel(*, report_path: Path = DEFAULT_REPORT) -> dict[str, object]:
    """Perform the complete build/content/clean-install/CLI verification."""

    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv is unavailable")
    uv_version = _run([uv, "--version"], cwd=REPOSITORY_ROOT, step="uv version").stdout.strip()
    temporary_path: Path | None = None
    report: dict[str, object]
    with tempfile.TemporaryDirectory(prefix="dmf-wheel-") as temporary:
        temporary_path = Path(temporary).resolve()
        try:
            temporary_path.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise VerificationError("temporary verification directory is inside the repository")

        distribution_directory = temporary_path / "distributions"
        distribution_directory.mkdir()
        _run(
            [uv, "build", "--out-dir", str(distribution_directory)],
            cwd=REPOSITORY_ROOT,
            step="distribution build",
        )
        distributions = sorted(distribution_directory.glob("dmf_pulse-0.1.0*"))
        if [path.name for path in distributions] != [
            "dmf_pulse-0.1.0-py3-none-any.whl",
            "dmf_pulse-0.1.0.tar.gz",
        ]:
            raise VerificationError("uv build did not produce the exact sdist and wheel pair")
        wheel = distributions[0]
        try:
            with zipfile.ZipFile(wheel) as archive:
                wheel_names = archive.namelist()
                bundled_zoneinfo_sha256 = hashlib.sha256(archive.read(BUNDLED_ZONEINFO)).hexdigest()
        except zipfile.BadZipFile as exc:
            raise VerificationError("built wheel is malformed") from exc
        except KeyError as exc:
            raise VerificationError(
                "built wheel does not contain the Windows zoneinfo fallback"
            ) from exc
        if "dmf_pulse/py.typed" not in wheel_names:
            raise VerificationError("built wheel does not contain dmf_pulse/py.typed")
        if bundled_zoneinfo_sha256 != BUNDLED_ZONEINFO_SHA256:
            raise VerificationError("built wheel zoneinfo fallback hash is invalid")

        environment_root = temporary_path / "clean-environment"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(environment_root)],
            cwd=temporary_path,
            step="clean environment creation",
        )
        environment_python = _environment_python(environment_root)
        environment_dmf = _environment_dmf(environment_root)
        _run(
            [uv, "pip", "install", "--python", str(environment_python), str(wheel)],
            cwd=temporary_path,
            step="clean wheel installation",
        )
        clean_environment = _sanitized_environment()
        version_result = _run(
            [str(environment_dmf), "--version"],
            cwd=temporary_path,
            step="installed dmf version",
            environment=clean_environment,
        )
        if version_result.stdout.strip() != "dmf 0.1.0":
            raise VerificationError("installed dmf version output is not exact")
        doctor_result = _run(
            [str(environment_dmf), "doctor", "--json"],
            cwd=temporary_path,
            step="installed dmf doctor",
            environment=clean_environment,
        )
        try:
            doctor = json.loads(doctor_result.stdout)
        except json.JSONDecodeError as exc:
            raise VerificationError("installed dmf doctor did not emit JSON") from exc
        if not isinstance(doctor, dict) or doctor.get("status") != "HEALTHY":
            raise VerificationError("installed dmf doctor was not healthy")

        zoneinfo_result = _run(
            [
                str(environment_python),
                "-c",
                (
                    "import pathlib,sys,zoneinfo;"
                    "zoneinfo.reset_tzpath(());zoneinfo.ZoneInfo.clear_cache();"
                    "import dmf_pulse.config.models as m;"
                    "m.TZPATH=();sys.base_prefix=str(pathlib.Path.cwd()/'no-system-zoneinfo');"
                    "c=m.AppConfig(environment=m.EnvironmentName.TEST,artifact_root=pathlib.Path('artifacts'));"
                    "assert c.display_timezone=='Europe/London';print('ZONEINFO_OK')"
                ),
            ],
            cwd=temporary_path,
            step="installed bundled zoneinfo fallback",
            environment=clean_environment,
        )
        if zoneinfo_result.stdout.strip() != "ZONEINFO_OK":
            raise VerificationError("installed bundled zoneinfo fallback did not validate")

        module_result = _run(
            [
                str(environment_python),
                "-c",
                "import dmf_pulse; print(dmf_pulse.__file__)",
            ],
            cwd=temporary_path,
            step="installed module location",
            environment=clean_environment,
        )
        installed_module = Path(module_result.stdout.strip()).resolve()
        try:
            installed_module.relative_to(environment_root.resolve())
        except ValueError as exc:
            raise VerificationError(
                "dmf_pulse was not imported from the clean environment"
            ) from exc
        try:
            installed_module.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise VerificationError("dmf_pulse was imported from the repository source tree")

        report = {
            "clean_environment_outside_repository": True,
            "cleaned_up": False,
            "doctor_nvidia_status": doctor.get("nvidia", {}).get("status")
            if isinstance(doctor.get("nvidia"), dict)
            else None,
            "doctor_status": doctor.get("status"),
            "installed_module_path": "<temporary-environment>/site-packages/dmf_pulse/__init__.py",
            "installed_version_output": version_result.stdout.strip(),
            "installed_zoneinfo_fallback": True,
            "platform": {
                "architecture": platform.machine(),
                "operating_system": platform.system(),
                "python": platform.python_version(),
            },
            "status": "PASS",
            "toolchain": {
                "build": importlib.metadata.version("build"),
                "build_backend": "hatchling",
                "hatchling": importlib.metadata.version("hatchling"),
            },
            "uv_version": uv_version,
            "uv_build_distributions": [
                {"bytes": path.stat().st_size, "name": path.name, "sha256": _sha256(path)}
                for path in distributions
            ],
            "wheel": {
                "bytes": wheel.stat().st_size,
                "contains_py_typed": True,
                "file_count": len(wheel_names),
                "name": wheel.name,
                "sha256": _sha256(wheel),
                "zoneinfo_fallback_sha256": bundled_zoneinfo_sha256,
            },
        }
    if temporary_path is None or temporary_path.exists():
        raise VerificationError("temporary verification directory was not cleaned up")
    report["cleaned_up"] = True
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return report


def main() -> int:
    try:
        report = verify_wheel()
    except VerificationError as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
