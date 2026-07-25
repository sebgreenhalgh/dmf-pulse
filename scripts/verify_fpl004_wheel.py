"""Verify FPL-004 from a clean, offline wheel installation outside the repository."""

from __future__ import annotations

import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPOSITORY_ROOT / "evidence/tickets/FPL-004/package_report.json"
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures/fpl/FPL-004"


class VerificationError(Exception):
    """A secret-safe installed-wheel verification failure."""


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
    return (
        environment_root / "Scripts/python.exe"
        if os.name == "nt"
        else environment_root / "bin/python"
    )


def _environment_dmf(environment_root: Path) -> Path:
    return environment_root / "Scripts/dmf.exe" if os.name == "nt" else environment_root / "bin/dmf"


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
    tool = pyproject.get("tool")
    hatch = tool.get("hatch") if isinstance(tool, dict) else None
    version_config = hatch.get("version") if isinstance(hatch, dict) else None
    version_path = version_config.get("path") if isinstance(version_config, dict) else None
    if not isinstance(version_path, str):
        raise VerificationError("canonical package version path is unavailable")
    version_source = (REPOSITORY_ROOT / version_path).read_text(encoding="utf-8")
    matches = re.findall(r'^__version__\s*=\s*"([^"]+)"', version_source, re.MULTILINE)
    if len(matches) != 1:
        raise VerificationError("canonical package version is ambiguous")
    return project["name"], matches[0]


def _inherited_verification() -> dict[str, Any]:
    namespace = runpy.run_path(str(REPOSITORY_ROOT / "scripts/verify_wheel.py"))
    verify = namespace.get("verify_wheel")
    if not callable(verify):
        raise VerificationError("inherited wheel verifier is unavailable")
    try:
        result = verify(report_path=REPORT_PATH)
    except Exception as exc:
        raise VerificationError("inherited wheel verification failed") from exc
    if not isinstance(result, dict) or result.get("status") != "PASS":
        raise VerificationError("inherited wheel verification did not pass")
    return result


def _json_object(output: str, step: str) -> dict[str, Any]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"{step} did not emit one JSON object") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{step} JSON result is not an object")
    return value


def _assert_validation(value: dict[str, Any]) -> None:
    if value.get("schema_version") != "1.0.0" or value.get("resource") != "bootstrap":
        raise VerificationError("installed FPL validation result identity is invalid")
    if value.get("status") not in {"VALID", "VALID_WITH_WARNINGS", "USABLE_WITH_WARNINGS"}:
        raise VerificationError("installed FPL validation did not accept the happy fixture")
    drift = value.get("drift")
    if not isinstance(drift, dict) or drift.get("classification") not in {
        "NO_DRIFT",
        "MISSING_OPTIONAL",
    }:
        raise VerificationError("installed FPL validation drift classification is invalid")
    quality = value.get("quality")
    if not isinstance(quality, dict) or quality.get("blocker_count") != 0:
        raise VerificationError("installed FPL validation reported a blocker")


def _assert_replay(value: dict[str, Any]) -> None:
    if value.get("schema_version") != "1.0.0" or value.get("status") != "USABLE":
        raise VerificationError("installed FPL replay did not produce a usable result")
    resources = value.get("resources")
    if not isinstance(resources, list) or [item.get("resource") for item in resources] != [
        "bootstrap",
        "fixtures",
    ]:
        raise VerificationError("installed FPL replay resource order is invalid")
    if any(item.get("lifecycle_state") != "USABLE" for item in resources):
        raise VerificationError("installed FPL replay lifecycle is not usable")
    quality = value.get("quality")
    if not isinstance(quality, dict) or quality.get("blocker_count") != 0:
        raise VerificationError("installed FPL replay quality is blocked")
    bundle = value.get("source_bundle")
    if not isinstance(bundle, dict):
        raise VerificationError("installed FPL replay did not create a source bundle")
    members = bundle.get("members")
    if not isinstance(members, list) or [member.get("role") for member in members] != [
        "BOOTSTRAP",
        "FIXTURES",
    ]:
        raise VerificationError("installed FPL replay bundle membership is invalid")
    semantic_sha256 = bundle.get("semantic_sha256")
    if not isinstance(semantic_sha256, str) or len(semantic_sha256) != 64:
        raise VerificationError("installed FPL replay bundle hash is invalid")
    effects = value.get("canonical_effects")
    if not isinstance(effects, dict) or not isinstance(effects.get("created"), dict):
        raise VerificationError("installed FPL replay canonical effect summary is invalid")


def _write_report(value: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT_PATH.with_name(f".{REPORT_PATH.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, REPORT_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def verify_fpl004_wheel() -> dict[str, Any]:
    """Run inherited package gates plus an installed synthetic FPL replay."""

    database_url = os.environ.get("DMF_TEST_DATABASE_URL")
    if not database_url:
        raise VerificationError("DMF_TEST_DATABASE_URL is required for FPL wheel verification")
    base_report = _inherited_verification()
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv is unavailable")
    project_name, project_version = _project_identity()
    normalized_distribution = project_name.replace("-", "_")
    clean_environment = _sanitized_environment()
    clean_environment["DMF_ENVIRONMENT"] = "TEST"
    clean_environment["DMF_TEST_DATABASE_URL"] = database_url

    temporary_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="dmf-fpl004-wheel-") as temporary:
        temporary_path = Path(temporary).resolve()
        try:
            temporary_path.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise VerificationError("FPL wheel verification directory is inside the repository")

        distributions = temporary_path / "distributions"
        distributions.mkdir()
        _run(
            [uv, "build", "--wheel", "--out-dir", str(distributions)],
            cwd=REPOSITORY_ROOT,
            step="FPL wheel build",
            environment=clean_environment,
        )
        wheels = sorted(distributions.glob(f"{normalized_distribution}-{project_version}-*.whl"))
        if len(wheels) != 1:
            raise VerificationError("FPL wheel build did not produce exactly one wheel")
        wheel = wheels[0]
        try:
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile as exc:
            raise VerificationError("FPL wheel is malformed") from exc
        required_resources = {
            "dmf_pulse/ingestion/resources/fpl.json",
            "dmf_pulse/ingestion/resources/fpl_profiles.json",
            "dmf_pulse/py.typed",
        }
        if not required_resources <= names:
            raise VerificationError("FPL wheel omits a required configuration or typing resource")

        environment_root = temporary_path / "clean-environment"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(environment_root)],
            cwd=temporary_path,
            step="FPL clean environment creation",
            environment=clean_environment,
        )
        environment_python = _environment_python(environment_root)
        environment_dmf = _environment_dmf(environment_root)
        dependency_environment = dict(clean_environment)
        dependency_environment["VIRTUAL_ENV"] = str(environment_root)
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
            step="FPL locked runtime dependency installation",
            environment=dependency_environment,
        )
        _run(
            [
                uv,
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--python",
                str(environment_python),
                str(wheel),
            ],
            cwd=temporary_path,
            step="FPL clean wheel installation",
            environment=clean_environment,
        )

        module = _run(
            [str(environment_python), "-c", "import dmf_pulse; print(dmf_pulse.__file__)"],
            cwd=temporary_path,
            step="FPL installed module location",
            environment=clean_environment,
        )
        installed_module = Path(module.stdout.strip()).resolve()
        try:
            installed_module.relative_to(environment_root.resolve())
        except ValueError as exc:
            raise VerificationError("FPL command imported outside its clean environment") from exc
        try:
            installed_module.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise VerificationError("FPL command imported from the repository source tree")

        validation_process = _run(
            [
                str(environment_dmf),
                "ingest",
                "fpl",
                "validate",
                "--resource",
                "bootstrap",
                "--input",
                str(FIXTURE_ROOT / "happy_path/bootstrap.json"),
                "--contract-version",
                "fpl-reference-v1",
                "--output",
                "json",
            ],
            cwd=temporary_path,
            step="installed FPL validation",
            environment=clean_environment,
        )
        validation = _json_object(validation_process.stdout, "installed FPL validation")
        _assert_validation(validation)

        replay_process = _run(
            [
                str(environment_dmf),
                "ingest",
                "fpl",
                "replay",
                "--fixture-set",
                str(FIXTURE_ROOT),
                "--scenario",
                "happy_path",
                "--information-cutoff",
                "2026-08-21T17:30:00Z",
                "--rights-profile",
                "synthetic_test_v1",
                "--output",
                "json",
            ],
            cwd=temporary_path,
            step="installed FPL synthetic replay",
            timeout_seconds=300.0,
            environment=clean_environment,
        )
        replay = _json_object(replay_process.stdout, "installed FPL synthetic replay")
        _assert_replay(replay)
        bundle = replay["source_bundle"]

        fpl_report: dict[str, Any] = {
            "fixture_source": "manifest-approved synthetic fixtures",
            "installed_module_path": "<temporary-environment>/site-packages/dmf_pulse/__init__.py",
            "network_requests": 0,
            "replay": {
                "bundle_member_count": len(bundle["members"]),
                "bundle_semantic_sha256": bundle["semantic_sha256"],
                "status": replay["status"],
            },
            "validation": {
                "drift": validation["drift"]["classification"],
                "status": validation["status"],
            },
            "wheel": {
                "bytes": wheel.stat().st_size,
                "contains_fpl_resources": True,
                "name": wheel.name,
                "sha256": _sha256(wheel),
            },
        }

    if temporary_path is None or temporary_path.exists():
        raise VerificationError("FPL wheel verification directory was not cleaned up")
    inherited_wheel = base_report.get("wheel")
    if (
        not isinstance(inherited_wheel, dict)
        or inherited_wheel.get("sha256") != fpl_report["wheel"]["sha256"]
    ):
        raise VerificationError("successive offline FPL wheel builds were not reproducible")
    base_report["fpl004"] = fpl_report
    base_report["status"] = "PASS"
    _write_report(base_report)
    return base_report


def main() -> int:
    try:
        report = verify_fpl004_wheel()
    except VerificationError as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, indent=2, sort_keys=True))
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": f"FPL wheel verification failed ({type(exc).__name__})",
                    "status": "FAIL",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
