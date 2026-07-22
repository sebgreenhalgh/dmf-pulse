"""Build and verify the DMF Pulse wheel from a clean environment outside the repository."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Sequence
from pathlib import Path

from packaging.markers import Marker

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPOSITORY_ROOT / "evidence" / "tickets" / "RUL-002" / "package_report.json"
RUNTIME_MANIFEST = REPOSITORY_ROOT / "specs" / "manifests" / "runtime_lock_manifest.json"
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
    environment["UV_OFFLINE"] = "1"
    return environment


def _project_identity() -> tuple[str, str]:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("name"), str):
        raise VerificationError("pyproject project identity is invalid")
    name = project["name"]
    tool = pyproject.get("tool")
    hatch = tool.get("hatch") if isinstance(tool, dict) else None
    version_config = hatch.get("version") if isinstance(hatch, dict) else None
    version_path = version_config.get("path") if isinstance(version_config, dict) else None
    if not isinstance(version_path, str):
        raise VerificationError("canonical dynamic version path is unavailable")
    try:
        version_source = (REPOSITORY_ROOT / version_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise VerificationError("canonical version source is unavailable") from exc
    matches = re.findall(r'^__version__\s*=\s*"([^"]+)"', version_source, re.MULTILINE)
    if len(matches) != 1:
        raise VerificationError("canonical version source is ambiguous")
    version = matches[0]
    return name, version


def _runtime_manifest_from_lock() -> dict[str, object]:
    lock = tomllib.loads((REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8"))
    raw_packages = lock.get("package")
    if not isinstance(raw_packages, list):
        raise VerificationError("uv.lock package table is missing")
    packages = {
        item["name"]: item
        for item in raw_packages
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    project = packages.get("dmf-pulse")
    if not isinstance(project, dict) or not isinstance(project.get("dependencies"), list):
        raise VerificationError("uv.lock project runtime dependencies are missing")
    roots = project["dependencies"]
    selected: set[str] = set()
    pending = [item.get("name") for item in roots if isinstance(item, dict)]
    while pending:
        name = pending.pop()
        if not isinstance(name, str) or name in selected:
            continue
        package = packages.get(name)
        if not isinstance(package, dict):
            raise VerificationError("uv.lock runtime graph is incomplete")
        dependencies = package.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise VerificationError("uv.lock runtime dependency graph is malformed")
        selected.add(name)
        pending.extend(item.get("name") for item in dependencies if isinstance(item, dict))
    records = []
    for name in sorted(selected):
        package = packages[name]
        version = package.get("version")
        dependencies = package.get("dependencies", [])
        if not isinstance(version, str) or not isinstance(dependencies, list):
            raise VerificationError("uv.lock runtime package metadata is malformed")
        records.append(
            {
                "dependencies": sorted(
                    [
                        {"marker": item.get("marker"), "name": item["name"]}
                        for item in dependencies
                        if isinstance(item, dict)
                        and isinstance(item.get("name"), str)
                        and item["name"] in selected
                    ],
                    key=lambda item: (item["name"], str(item["marker"])),
                ),
                "name": name,
                "version": version,
            }
        )
    return {
        "lock_sha256": _sha256(REPOSITORY_ROOT / "uv.lock"),
        "manifest_version": "1.0",
        "packages": records,
        "project": "dmf-pulse",
        "roots": sorted(item["name"] for item in roots if isinstance(item, dict)),
    }


def _expected_runtime_distributions() -> dict[str, str]:
    try:
        manifest = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError("locked runtime manifest is unavailable or invalid") from exc
    if manifest != _runtime_manifest_from_lock():
        raise VerificationError("locked runtime manifest does not exactly match uv.lock")
    raw_packages = manifest.get("packages")
    roots = manifest.get("roots")
    if not isinstance(raw_packages, list) or not isinstance(roots, list):
        raise VerificationError("locked runtime manifest shape is invalid")
    packages = {
        item.get("name"): item
        for item in raw_packages
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    selected: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if not isinstance(name, str) or name in selected:
            continue
        package = packages.get(name)
        if not isinstance(package, dict) or not isinstance(package.get("version"), str):
            raise VerificationError("locked runtime package graph is incomplete")
        selected.add(name)
        dependencies = package.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise VerificationError("locked runtime dependency graph is malformed")
        for dependency in dependencies:
            if not isinstance(dependency, dict) or not isinstance(dependency.get("name"), str):
                raise VerificationError("locked runtime dependency is malformed")
            marker = dependency.get("marker")
            if marker is None or (isinstance(marker, str) and Marker(marker).evaluate()):
                pending.append(dependency["name"])
    return {name: str(packages[name]["version"]) for name in sorted(selected)}


def verify_wheel(*, report_path: Path = DEFAULT_REPORT) -> dict[str, object]:
    """Perform the complete build/content/clean-install/CLI verification."""

    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv is unavailable")
    uv_version = _run([uv, "--version"], cwd=REPOSITORY_ROOT, step="uv version").stdout.strip()
    project_name, project_version = _project_identity()
    normalized_distribution = project_name.replace("-", "_")
    expected_runtime = _expected_runtime_distributions()
    offline_environment = _sanitized_environment()
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
            environment=offline_environment,
        )
        distributions = sorted(
            distribution_directory.glob(f"{normalized_distribution}-{project_version}*")
        )
        if [path.name for path in distributions] != [
            f"{normalized_distribution}-{project_version}-py3-none-any.whl",
            f"{normalized_distribution}-{project_version}.tar.gz",
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
            environment=offline_environment,
        )
        environment_python = _environment_python(environment_root)
        environment_dmf = _environment_dmf(environment_root)
        _run(
            [uv, "pip", "install", "--offline", "--python", str(environment_python), str(wheel)],
            cwd=temporary_path,
            step="clean wheel installation",
            environment=offline_environment,
        )
        clean_environment = offline_environment
        version_result = _run(
            [str(environment_dmf), "--version"],
            cwd=temporary_path,
            step="installed dmf version",
            environment=clean_environment,
        )
        if version_result.stdout.strip() != f"dmf {project_version}":
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

        rules_result = _run(
            [
                str(environment_dmf),
                "rules",
                "validate",
                str(REPOSITORY_ROOT / "fixtures/rules/RUL-002/synthetic_complete"),
                "--json",
            ],
            cwd=temporary_path,
            step="installed rules validation",
            environment=clean_environment,
        )
        try:
            rules_report = json.loads(rules_result.stdout)
        except json.JSONDecodeError as exc:
            raise VerificationError("installed rules command did not emit JSON") from exc
        if rules_report.get("ruleset_id") != "fpl-synthetic-2099-2100":
            raise VerificationError("installed rules command did not validate the fixture")

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

        distributions_result = _run(
            [
                str(environment_python),
                "-c",
                (
                    "import importlib.metadata,json;"
                    "print(json.dumps(sorted((d.metadata['Name'].lower().replace('_','-'),d.version) "
                    "for d in importlib.metadata.distributions())))"
                ),
            ],
            cwd=temporary_path,
            step="installed runtime distribution inventory",
            environment=clean_environment,
        )
        try:
            installed_runtime = dict(json.loads(distributions_result.stdout))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise VerificationError("installed runtime distribution inventory is invalid") from exc
        expected_installed = {project_name: project_version, **expected_runtime}
        if installed_runtime != expected_installed:
            raise VerificationError(
                "installed runtime distributions do not match the frozen lock graph"
            )

        report = {
            "clean_environment_outside_repository": True,
            "cleaned_up": False,
            "network_fetch_disabled": True,
            "doctor_nvidia_status": doctor.get("nvidia", {}).get("status")
            if isinstance(doctor.get("nvidia"), dict)
            else None,
            "doctor_status": doctor.get("status"),
            "installed_module_path": "<temporary-environment>/site-packages/dmf_pulse/__init__.py",
            "installed_version_output": version_result.stdout.strip(),
            "installed_runtime_distributions": [
                {"name": name, "version": version}
                for name, version in sorted(installed_runtime.items())
            ],
            "locked_runtime_manifest_sha256": _sha256(RUNTIME_MANIFEST),
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
