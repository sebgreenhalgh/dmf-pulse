"""Verify ODD-005 from a clean offline wheel installation outside the repository."""

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
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence/tickets/ODD-005"
REPORT_PATH = EVIDENCE_ROOT / "package_report.json"
FOUNDATION_REPORT = EVIDENCE_ROOT / "foundation_package_report.json"
FPL_FIXTURES = REPOSITORY_ROOT / "fixtures/fpl/FPL-004"
ODD_FIXTURES = REPOSITORY_ROOT / "fixtures/odds/ODD-005"


class VerificationError(Exception):
    """A bounded, secret-safe installed-wheel failure."""


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
    environment: dict[str, str],
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
        error_code = "UNKNOWN"
        for line in reversed([item for item in result.stdout.splitlines() if item.strip()]):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                error = value.get("error")
                if isinstance(error, dict) and isinstance(error.get("code"), str):
                    error_code = error["code"]
                elif isinstance(value.get("status"), str):
                    error_code = value["status"]
                break
        raise VerificationError(f"{step} returned an unexpected exit code ({error_code})")
    return result


def _json_object(output: str, step: str) -> dict[str, Any]:
    lines = [line for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise VerificationError(f"{step} did not emit one JSON object")


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


def _python(environment_root: Path) -> Path:
    return (
        environment_root / "Scripts/python.exe"
        if os.name == "nt"
        else environment_root / "bin/python"
    )


def _dmf(environment_root: Path) -> Path:
    return environment_root / "Scripts/dmf.exe" if os.name == "nt" else environment_root / "bin/dmf"


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


@contextmanager
def _isolated_database(source_url: str) -> Iterator[str]:
    """Create and always remove one uniquely named database on the approved local service."""

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
    database_name = f"dmf_pulse_wheel_{uuid4().hex[:12]}"
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
        migration_environment = _environment(isolated_url)
        _run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPOSITORY_ROOT,
            step="isolated database migration",
            environment=migration_environment,
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


def _assert_fpl(value: dict[str, Any]) -> dict[str, Any]:
    bundle = value.get("source_bundle")
    if (
        value.get("status") != "USABLE"
        or not isinstance(bundle, dict)
        or not isinstance(bundle.get("members"), list)
        or len(bundle["members"]) != 2
    ):
        raise VerificationError("installed FPL replay did not remain usable")
    return {
        "bundle_member_count": len(bundle["members"]),
        "semantic_sha256": bundle.get("semantic_sha256"),
        "status": value.get("status"),
    }


def _assert_odds_replay(value: dict[str, Any]) -> dict[str, Any]:
    if (
        value.get("status") != "COMPLETE"
        or value.get("events_seen") != 1
        or value.get("operator_books_seen") != 2
        or value.get("complete_books_created") != 2
        or value.get("observations_created") != 6
        or value.get("quarantined") != 0
    ):
        observed = {
            "complete_books_created": value.get("complete_books_created"),
            "events_seen": value.get("events_seen"),
            "observations_created": value.get("observations_created"),
            "operator_books_seen": value.get("operator_books_seen"),
            "quarantined": value.get("quarantined"),
            "status": value.get("status"),
        }
        raise VerificationError(
            "installed ODD replay differs from the frozen happy oracle "
            + json.dumps(observed, sort_keys=True)
        )
    return {
        "complete_books_created": value["complete_books_created"],
        "observations_created": value["observations_created"],
        "status": value["status"],
    }


def _assert_market(value: dict[str, Any]) -> dict[str, Any]:
    books = value.get("books")
    if value.get("observation_count") != 6 or not isinstance(books, list) or len(books) != 2:
        raise VerificationError("installed as-of query differs from its frozen count oracle")
    prices: dict[str, dict[str, str]] = {}
    for book in books:
        if not isinstance(book, dict) or not isinstance(book.get("observations"), list):
            raise VerificationError("installed market book is malformed")
        operator = book.get("operator_key")
        if not isinstance(operator, str):
            raise VerificationError("installed market operator identity is malformed")
        prices[operator] = {
            str(quote.get("outcome")): str(quote.get("decimal_odds"))
            for quote in book["observations"]
            if isinstance(quote, dict)
        }
    expected = {
        "book_alpha": {"AWAY": "4.20", "DRAW": "3.60", "HOME": "1.80"},
        "book_beta": {"AWAY": "4.10", "DRAW": "3.50", "HOME": "1.85"},
    }
    if prices != expected:
        raise VerificationError("installed as-of prices do not preserve source lexical scale")
    serialized = json.dumps(value, sort_keys=True).casefold()
    if "probability" in serialized or "consensus" in serialized or "de-vig" in serialized:
        raise VerificationError("installed market output contains an excluded derived product")
    return {"observation_count": 6, "operator_books": 2, "prices": prices}


def _assert_refusal(value: dict[str, Any]) -> dict[str, Any]:
    error = value.get("error")
    if (
        value.get("status") != "BLOCKED"
        or not isinstance(error, dict)
        or error.get("code") != "CREDENTIAL_UNAVAILABLE"
        or error.get("transport_called") is not False
    ):
        raise VerificationError("installed controlled snapshot did not refuse before transport")
    return {"code": "CREDENTIAL_UNAVAILABLE", "transport_called": False}


def _verify_in_database(database_url: str, inherited: Callable[..., object]) -> dict[str, Any]:
    """Run every installed-wheel proof against one already migrated isolated database."""

    try:
        foundation = inherited(report_path=FOUNDATION_REPORT)
    except Exception as exc:
        raise VerificationError("inherited wheel verifier failed") from exc
    if not isinstance(foundation, dict) or foundation.get("status") != "PASS":
        raise VerificationError("inherited wheel verifier did not pass")

    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv is unavailable")
    project_name, project_version = _project_identity()
    environment = _environment(database_url)
    report: dict[str, Any]
    temporary_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="dmf-odd005-wheel-") as temporary:
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
            step="wheel build",
            environment=environment,
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
        required_resources = {
            "dmf_pulse/ingestion/resources/fpl.json",
            "dmf_pulse/ingestion/resources/fpl_profiles.json",
            "dmf_pulse/ingestion/resources/odds_profiles.json",
            "dmf_pulse/ingestion/resources/the_odds_api.json",
            "dmf_pulse/py.typed",
        }
        if not required_resources <= names:
            raise VerificationError("wheel omits a required configuration or typing resource")

        environment_root = temporary_path / "clean-environment"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(environment_root)],
            cwd=temporary_path,
            step="clean environment creation",
            environment=environment,
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
            step="locked runtime dependency installation",
            environment=dependency_environment,
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
            cwd=temporary_path,
            step="clean wheel installation",
            environment=environment,
        )
        module = _run(
            [str(python), "-c", "import dmf_pulse; print(dmf_pulse.__file__)"],
            cwd=temporary_path,
            step="installed module location",
            environment=environment,
        )
        module_path = Path(module.stdout.strip()).resolve()
        try:
            module_path.relative_to(environment_root)
        except ValueError as exc:
            raise VerificationError("module was not imported from the clean environment") from exc
        try:
            module_path.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise VerificationError("module was imported from the repository source tree")

        fpl = _json_object(
            _run(
                [
                    str(dmf),
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
                step="installed FPL replay",
                environment=environment,
            ).stdout,
            "installed FPL replay",
        )
        validation = _json_object(
            _run(
                [
                    str(dmf),
                    "ingest",
                    "odds",
                    "validate",
                    "--provider",
                    "the_odds_api",
                    "--input",
                    str(ODD_FIXTURES / "happy_path.json"),
                    "--contract-version",
                    "the-odds-api-v4-reference-v1",
                    "--output",
                    "json",
                ],
                cwd=temporary_path,
                step="installed ODD validation",
                environment=environment,
            ).stdout,
            "installed ODD validation",
        )
        if validation.get("status") not in {"VALID", "VALID_WITH_WARNINGS"}:
            raise VerificationError("installed ODD validation did not accept the happy fixture")
        replay = _json_object(
            _run(
                [
                    str(dmf),
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
                step="installed ODD replay",
                environment=environment,
            ).stdout,
            "installed ODD replay",
        )
        market = _json_object(
            _run(
                [
                    str(dmf),
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
                step="installed market query",
                environment=environment,
            ).stdout,
            "installed market query",
        )
        refusal = _json_object(
            _run(
                [
                    str(dmf),
                    "ingest",
                    "odds",
                    "snapshot",
                    "--provider",
                    "the_odds_api",
                    "--competition-key",
                    "PL",
                    "--sport-key",
                    "soccer_epl",
                    "--region",
                    "uk",
                    "--market",
                    "h2h",
                    "--as-of",
                    "2026-08-20T12:05:00Z",
                    "--output",
                    "json",
                ],
                cwd=temporary_path,
                step="installed controlled refusal",
                environment=environment,
                expected_exit=4,
            ).stdout,
            "installed controlled refusal",
        )
        report = {
            "cleaned_up": True,
            "foundation": foundation,
            "fpl004": _assert_fpl(fpl),
            "network_requests": 0,
            "odd005": {
                "market": _assert_market(market),
                "refusal": _assert_refusal(refusal),
                "replay": _assert_odds_replay(replay),
                "validation_status": validation.get("status"),
            },
            "status": "PASS",
            "wheel": {
                "contains_odds_resources": True,
                "contains_py_typed": "dmf_pulse/py.typed" in names,
                "distribution": f"{project_name}=={project_version}",
                "sha256": _sha256(wheel),
            },
        }
    if temporary_path is None or temporary_path.exists():
        raise VerificationError("temporary wheel directory was not removed")
    return report


def verify_odd005_wheel() -> dict[str, Any]:
    """Build, install, and execute the inherited and ODD vertical slices offline."""

    source_url = os.environ.get("DMF_TEST_DATABASE_URL")
    if not source_url:
        raise VerificationError("DMF_TEST_DATABASE_URL is required")
    namespace = runpy.run_path(str(REPOSITORY_ROOT / "scripts/verify_wheel.py"))
    inherited = namespace.get("verify_wheel")
    if not callable(inherited):
        raise VerificationError("inherited wheel verifier is unavailable")
    previous_url = os.environ.get("DMF_TEST_DATABASE_URL")
    with _isolated_database(source_url) as database_url:
        os.environ["DMF_TEST_DATABASE_URL"] = database_url
        try:
            report = _verify_in_database(database_url, inherited)
        finally:
            if previous_url is None:
                os.environ.pop("DMF_TEST_DATABASE_URL", None)
            else:
                os.environ["DMF_TEST_DATABASE_URL"] = previous_url
    report["database_cleaned_up"] = True
    report["database_isolated"] = True
    _write_report(report)
    return report


def main() -> int:
    try:
        report = verify_odd005_wheel()
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
