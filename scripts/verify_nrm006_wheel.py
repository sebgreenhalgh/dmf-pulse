"""Verify NRM-006 from a clean offline wheel outside the repository."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPOSITORY_ROOT / "evidence/tickets/NRM-006/package_report.json"
FPL_FIXTURES = REPOSITORY_ROOT / "fixtures/fpl/FPL-004"
ODD_FIXTURES = REPOSITORY_ROOT / "fixtures/odds/ODD-005"
HAPPY_GOLDEN = REPOSITORY_ROOT / "fixtures/odds/NRM-006/expected_outputs/happy_path_consensus.json"


class VerificationError(Exception):
    """Bounded installed-wheel verification failure."""


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
    environment: dict[str, str],
    step: str,
    expected_exit: int = 0,
    timeout_seconds: float = 300,
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
    if result.returncode != expected_exit:
        raise VerificationError(f"{step} returned exit {result.returncode}")
    return result


def _json_object(output: str, step: str) -> dict[str, Any]:
    for line in reversed([item for item in output.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise VerificationError(f"{step} did not emit a JSON object")


def _project_identity() -> tuple[str, str]:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project")
    tool = pyproject.get("tool")
    hatch = tool.get("hatch") if isinstance(tool, dict) else None
    version_config = hatch.get("version") if isinstance(hatch, dict) else None
    version_path = version_config.get("path") if isinstance(version_config, dict) else None
    if (
        not isinstance(project, dict)
        or not isinstance(project.get("name"), str)
        or not isinstance(version_path, str)
    ):
        raise VerificationError("project identity is unavailable")
    source = (REPOSITORY_ROOT / version_path).read_text(encoding="utf-8")
    versions = re.findall(r'^__version__\s*=\s*"([^"]+)"', source, re.MULTILINE)
    if len(versions) != 1:
        raise VerificationError("canonical package version is ambiguous")
    return project["name"], versions[0]


def _environment(database_url: str) -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "THE_ODDS_API_KEY",
        "ODDS_API_KEY",
        "DMF_ODDS_API_KEY",
    ):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["UV_OFFLINE"] = "1"
    environment["DMF_ENVIRONMENT"] = "TEST"
    environment["DMF_TEST_DATABASE_URL"] = database_url
    return environment


def _python(environment_root: Path) -> Path:
    return (
        environment_root / "Scripts/python.exe"
        if os.name == "nt"
        else environment_root / "bin/python"
    )


def _dmf(python: Path) -> tuple[str, ...]:
    """Load the clean wheel's console entry point through its trusted Python."""

    runner = (
        "import importlib.metadata as m,sys;"
        "e=[e for e in m.distribution('dmf-pulse').entry_points "
        "if e.group=='console_scripts' and e.name=='dmf'];"
        "ep=e[0] if len(e)==1 else sys.exit(125);"
        "sys.exit(ep.load()()) "
        "if ep.value=='dmf_pulse.cli.app:main' else sys.exit(125)"
    )
    return (str(python), "-I", "-c", runner)


@contextmanager
def _isolated_database(source_url: str) -> Iterator[str]:
    try:
        parsed = make_url(source_url)
    except Exception as exc:
        raise VerificationError("test database configuration is invalid") from exc
    if (
        parsed.drivername not in {"postgresql", "postgresql+psycopg"}
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
        or parsed.database != "dmf_pulse_test"
    ):
        raise VerificationError("wheel verification requires the disposable local database")
    database_name = f"dmf_pulse_nrm006_{uuid4().hex[:12]}"
    admin_url = parsed.set(drivername="postgresql+psycopg", database="postgres")
    isolated_url = parsed.set(
        drivername="postgresql+psycopg", database=database_name
    ).render_as_string(hide_password=False)
    engine = create_engine(
        admin_url,
        poolclass=NullPool,
        hide_parameters=True,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5, "options": "-c timezone=UTC"},
    )
    created = False
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}" TEMPLATE template0'))
        created = True
        _run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPOSITORY_ROOT,
            environment=_environment(isolated_url),
            step="isolated database migration",
        )
        yield isolated_url
    finally:
        try:
            if created:
                with engine.connect() as connection:
                    connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        except Exception as exc:
            raise VerificationError("isolated database cleanup failed") from exc
        finally:
            engine.dispose()


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


def _verify(database_url: str) -> dict[str, Any]:
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv is unavailable")
    project_name, project_version = _project_identity()
    environment = _environment(database_url)
    temporary_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="dmf-nrm006-wheel-") as temporary:
        temporary_path = Path(temporary).resolve()
        try:
            temporary_path.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise VerificationError("wheel verification directory is inside the repository")
        distributions = temporary_path / "distributions"
        distributions.mkdir()
        _run(
            [uv, "build", "--wheel", "--out-dir", str(distributions)],
            cwd=REPOSITORY_ROOT,
            environment=environment,
            step="wheel build",
        )
        normalized = project_name.replace("-", "_")
        wheels = sorted(distributions.glob(f"{normalized}-{project_version}-*.whl"))
        if len(wheels) != 1:
            raise VerificationError("wheel build did not produce exactly one distribution")
        wheel = wheels[0]
        try:
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
                if archive.testzip() is not None:
                    raise VerificationError("wheel CRC validation failed")
        except zipfile.BadZipFile as exc:
            raise VerificationError("wheel is malformed") from exc
        required = {
            "dmf_pulse/ingestion/resources/fpl.json",
            "dmf_pulse/ingestion/resources/odds_profiles.json",
            "dmf_pulse/ingestion/resources/the_odds_api.json",
            "dmf_pulse/markets/resources/confidence_gate_policy.json",
            "dmf_pulse/markets/resources/normalisation_policy.json",
            "dmf_pulse/py.typed",
        }
        if not required <= names:
            raise VerificationError("wheel omits a required configuration or policy resource")

        environment_root = temporary_path / "clean-environment"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(environment_root)],
            cwd=temporary_path,
            environment=environment,
            step="clean environment creation",
        )
        dependency_environment = dict(environment)
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
            environment=dependency_environment,
            step="locked runtime dependency installation",
        )
        python = _python(environment_root)
        dmf = _dmf(python)
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
            cwd=temporary_path,
            environment=environment,
            step="clean wheel installation",
        )
        module = _run(
            [str(python), "-c", "import dmf_pulse; print(dmf_pulse.__file__)"],
            cwd=temporary_path,
            environment=environment,
            step="installed module location",
        )
        module_path = Path(module.stdout.strip()).resolve()
        try:
            module_path.relative_to(environment_root)
        except ValueError as exc:
            raise VerificationError("module was not imported from the clean environment") from exc

        fpl = _json_object(
            _run(
                [
                    *dmf,
                    "ingest",
                    "fpl",
                    "replay",
                    "--fixture-set",
                    str(FPL_FIXTURES),
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
                environment=environment,
                step="installed FPL replay",
            ).stdout,
            "installed FPL replay",
        )
        odds = _json_object(
            _run(
                [
                    *dmf,
                    "ingest",
                    "odds",
                    "replay",
                    "--fixture-set",
                    str(ODD_FIXTURES),
                    "--scenario",
                    "happy_path",
                    "--information-cutoff",
                    "2026-08-21T17:30:00Z",
                    "--rights-profile",
                    "synthetic_the_odds_api_v1",
                    "--output",
                    "json",
                ],
                cwd=temporary_path,
                environment=environment,
                step="installed odds replay",
            ).stdout,
            "installed odds replay",
        )
        observations = _json_object(
            _run(
                [
                    *dmf,
                    "market",
                    "observations",
                    "--fixture-external-provider",
                    "synthetic_fpl",
                    "--fixture-external-id",
                    "101",
                    "--season-code",
                    "2026/27",
                    "--as-of",
                    "2026-08-20T12:05:00Z",
                    "--output",
                    "json",
                ],
                cwd=temporary_path,
                environment=environment,
                step="installed observation query",
            ).stdout,
            "installed observation query",
        )
        cli_result = _json_object(
            _run(
                [
                    *dmf,
                    "market",
                    "normalise",
                    "--fixture-external-provider",
                    "synthetic_fpl",
                    "--fixture-external-id",
                    "101",
                    "--season-code",
                    "2026/27",
                    "--as-of",
                    "2026-08-20T12:05:00Z",
                    "--output",
                    "json",
                ],
                cwd=temporary_path,
                environment=environment,
                step="installed normalisation CLI",
            ).stdout,
            "installed normalisation CLI",
        )
        projection_code = (
            "import json; from datetime import datetime; "
            "from dmf_pulse.markets.policy import load_market_normalisation_policy; "
            "from dmf_pulse.markets.projection import market_normalisation_semantic_projection; "
            "from dmf_pulse.markets.service import MarketService; "
            "r=MarketService().normalise(fixture_external_provider='synthetic_fpl',"
            "fixture_external_id='101',season_code='2026/27',"
            "as_of=datetime.fromisoformat('2026-08-20T12:05:00+00:00')); "
            "print(json.dumps({'projection':market_normalisation_semantic_projection("
            "r,policy=load_market_normalisation_policy()),'result':r.model_dump(mode='json')},"
            "sort_keys=True))"
        )
        library = _json_object(
            _run(
                [str(python), "-c", projection_code],
                cwd=temporary_path,
                environment=environment,
                step="installed normalisation library",
            ).stdout,
            "installed normalisation library",
        )
        expected = json.loads(HAPPY_GOLDEN.read_text(encoding="utf-8"))
        if fpl.get("status") != "USABLE":
            raise VerificationError("installed FPL replay was not usable")
        if odds.get("status") != "COMPLETE" or odds.get("observations_created") != 6:
            raise VerificationError("installed odds replay differed from its frozen oracle")
        if observations.get("observation_count") != 6:
            raise VerificationError("installed observation query differed from its frozen oracle")
        if cli_result != library.get("result"):
            raise VerificationError("installed CLI and library results differ")
        if library.get("projection") != expected:
            raise VerificationError("installed normalisation differs from the frozen golden")
        report = {
            "cleaned_up": True,
            "database_isolated": True,
            "fpl_status": "USABLE",
            "network_requests": 0,
            "normalisation_status": cli_result.get("status"),
            "observation_count": 6,
            "odds_status": "COMPLETE",
            "semantic_result_sha256": expected["semantic_result_sha256"],
            "status": "PASS",
            "wheel": {
                "contains_confidence_gate_policy": True,
                "contains_normalisation_policy": True,
                "distribution": f"{project_name}=={project_version}",
                "sha256": _sha256(wheel),
            },
        }
    if temporary_path is None or temporary_path.exists():
        raise VerificationError("temporary wheel directory was not removed")
    return report


def verify_nrm006_wheel() -> dict[str, Any]:
    source_url = os.environ.get("DMF_TEST_DATABASE_URL")
    if not source_url:
        raise VerificationError("DMF_TEST_DATABASE_URL is required")
    with _isolated_database(source_url) as database_url:
        report = _verify(database_url)
    report["database_cleaned_up"] = True
    _write_report(report)
    return report


def main() -> int:
    try:
        report = verify_nrm006_wheel()
    except VerificationError as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {"error": f"wheel verification failed ({type(exc).__name__})", "status": "FAIL"},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
