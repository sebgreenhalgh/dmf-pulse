"""Independently verify FPL-004 acceptance artifacts and fail-closed invariants."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from coverage import Coverage
from coverage.exceptions import CoverageException, NoDataError
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from dmf_pulse.database.migrate import head_revision
from dmf_pulse.database.schema import inspect_schema
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.client import FplClient, Transport
from dmf_pulse.ingestion.fpl.parser import FplResource, parse_fpl_payload
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability
from dmf_pulse.ingestion.rights import load_rights_profiles

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence/tickets/FPL-004"
REPORT_PATH = EVIDENCE_ROOT / "acceptance_verification.json"
MIGRATION_REPORT = EVIDENCE_ROOT / "migration_matrix.json"
PACKAGE_REPORT = EVIDENCE_ROOT / "package_report.json"
FIXTURE_MANIFEST = REPOSITORY_ROOT / "fixtures/manifest.json"
REQUIRED_BRANCH = "stage/A4/FPL-004-official-ingestion"
REQUIRED_BASELINE = "9b3160a2574d2868b5f26e3a2d429924567510b0"
EXPECTED_FIXTURE_COUNT = 18
EXPECTED_BASELINE_REVISION = "20260723_0001"


class AcceptanceError(Exception):
    """A safe verifier failure that never includes a source body or secret."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise AcceptanceError(f"{path.name} is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"{path.name} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise AcceptanceError("fixture file is unavailable") from exc
    return digest.hexdigest()


def _git(*arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            shell=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AcceptanceError("Git repository state is unavailable") from exc
    if completed.returncode != 0:
        raise AcceptanceError("Git repository state check failed")
    return completed.stdout.strip()


def _verify_git() -> dict[str, str]:
    branch = _git("branch", "--show-current")
    ci_ref_allowed = (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("DMF_ACCEPTANCE_CI_REF") == "1"
    )
    if not ci_ref_allowed and branch != REQUIRED_BRANCH:
        raise AcceptanceError("repository is not on the required FPL-004 branch")
    head = _git("rev-parse", "--verify", "HEAD")
    if len(head) != 40:
        raise AcceptanceError("repository HEAD is invalid")
    try:
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", REQUIRED_BASELINE, "HEAD"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            shell=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AcceptanceError("baseline ancestry check could not run") from exc
    if completed.returncode != 0:
        raise AcceptanceError("required DAT-003 baseline is not an ancestor of HEAD")
    return {
        "baseline": REQUIRED_BASELINE,
        "branch": (
            f"CI:{os.environ.get('GITHUB_HEAD_REF') or os.environ.get('GITHUB_REF_NAME') or 'detached'}"
            if ci_ref_allowed
            else branch
        ),
        "head": head,
    }


def _verify_fixtures() -> dict[str, Any]:
    manifest = _read_json(FIXTURE_MANIFEST)
    entries = manifest.get("entries")
    if (
        manifest.get("pack_id") != "FPL-004"
        or manifest.get("fixture_count") != EXPECTED_FIXTURE_COUNT
        or not isinstance(entries, list)
        or len(entries) != EXPECTED_FIXTURE_COUNT
    ):
        raise AcceptanceError("FPL-004 fixture manifest identity or count is invalid")
    seen: set[str] = set()
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            raise AcceptanceError("fixture manifest entry is invalid")
        raw_path = raw_entry.get("path")
        if not isinstance(raw_path, str) or raw_path in seen:
            raise AcceptanceError("fixture manifest path is invalid or duplicated")
        seen.add(raw_path)
        pure = PurePosixPath(raw_path)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or pure.parts[:3]
            != (
                "fixtures",
                "fpl",
                "FPL-004",
            )
        ):
            raise AcceptanceError("fixture manifest path escapes the approved fixture root")
        path = REPOSITORY_ROOT.joinpath(*pure.parts)
        if path.is_symlink() or not path.is_file():
            raise AcceptanceError("fixture manifest points to a non-regular file")
        if (
            raw_entry.get("synthetic") is not True
            or raw_entry.get("rights_profile") != "synthetic_test_v1"
            or raw_entry.get("bytes") != path.stat().st_size
            or raw_entry.get("sha256") != _sha256(path)
        ):
            raise AcceptanceError("fixture bytes or synthetic rights metadata do not match")

    happy = REPOSITORY_ROOT / "fixtures/fpl/FPL-004/happy_path"
    bootstrap = parse_fpl_payload(FplResource.BOOTSTRAP, (happy / "bootstrap.json").read_bytes())
    fixtures = parse_fpl_payload(FplResource.FIXTURES, (happy / "fixtures.json").read_bytes())
    if bootstrap.drift.classification.value not in {"NO_DRIFT", "MISSING_OPTIONAL"}:
        raise AcceptanceError("happy bootstrap parser oracle failed")
    if fixtures.drift.classification.value != "NO_DRIFT":
        raise AcceptanceError("happy fixtures parser oracle failed")
    return {
        "bootstrap_semantic_sha256": bootstrap.semantic_sha256,
        "fixture_count": len(entries),
        "fixtures_semantic_sha256": fixtures.semantic_sha256,
        "status": "PASS",
    }


def _verify_rights_gate() -> dict[str, Any]:
    profiles = load_rights_profiles()
    try:
        official = profiles["fpl_official_private_manual_v1"]
        synthetic = profiles["synthetic_test_v1"]
    except KeyError as exc:
        raise AcceptanceError("required FPL rights profile is missing") from exc
    required_denials = {
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.BACKUP,
        RightsCapability.CACHE,
        RightsCapability.MODEL_TRAINING,
        RightsCapability.PUBLIC_DISPLAY,
        RightsCapability.RAW_STORAGE,
        RightsCapability.REDISTRIBUTION,
    }
    if any(official.capabilities[item] is not CapabilityValue.DENY for item in required_denials):
        raise AcceptanceError("official FPL profile permits a contractually forbidden capability")
    if official.capabilities[RightsCapability.DERIVED_STORAGE] is not CapabilityValue.UNKNOWN:
        raise AcceptanceError("official FPL derived-storage ambiguity was not preserved")
    if official.capabilities[RightsCapability.MANUAL_IMPORT] is not CapabilityValue.ALLOW:
        raise AcceptanceError("official FPL profile does not allow bounded manual import")
    if synthetic.capabilities[RightsCapability.RAW_STORAGE] is not CapabilityValue.ALLOW:
        raise AcceptanceError("synthetic FPL fixture profile cannot retain approved raw fixtures")

    calls = 0

    def forbidden_transport() -> Transport:
        nonlocal calls
        calls += 1
        raise AssertionError("transport factory must not be called")

    client = FplClient(official, transport_factory=forbidden_transport)
    try:
        client.fetch(FplResource.BOOTSTRAP)
    except IngestionError as exc:
        if exc.code != "RIGHTS_BLOCKED" or exc.exit_code != 4:
            raise AcceptanceError("official FPL request did not fail with RIGHTS_BLOCKED") from exc
        transport_count = exc.details.get("transport_call_count")
        if transport_count != 0:
            raise AcceptanceError("rights rejection did not report zero transport calls") from exc
    else:
        raise AcceptanceError("official FPL automated access did not fail closed")
    if calls != 0:
        raise AcceptanceError("official FPL rights gate called the transport factory")
    return {
        "official_automated_access": "DENY",
        "official_derived_storage": "UNKNOWN_DENIED",
        "synthetic_raw_storage": "ALLOW",
        "transport_call_count": calls,
    }


def _verify_migration_and_database() -> dict[str, Any]:
    report = _read_json(MIGRATION_REPORT)
    target = head_revision()
    if (
        report.get("status") != "PASS"
        or report.get("baseline_revision") != EXPECTED_BASELINE_REVISION
        or report.get("target_revision") != target
        or report.get("metadata_drift_check") != "PASS"
    ):
        raise AcceptanceError("migration matrix report does not prove the required revision path")
    matrix = report.get("matrix")
    if (
        not isinstance(matrix, list)
        or len(matrix) != 5
        or any(not isinstance(item, dict) or item.get("status") != "PASS" for item in matrix)
    ):
        raise AcceptanceError("migration matrix path records are incomplete")
    preservation = report.get("data_preservation")
    if not isinstance(preservation, dict) or preservation.get("status") != "PASS":
        raise AcceptanceError("migration report lacks DAT-003 data-preservation evidence")
    offline = report.get("offline_sql")
    if not isinstance(offline, dict) or offline.get("secret_free") is not True:
        raise AcceptanceError("migration report lacks secret-free offline SQL evidence")
    offline_path = REPOSITORY_ROOT / str(offline.get("path", ""))
    if not offline_path.is_file() or _sha256(offline_path) != offline.get("sha256"):
        raise AcceptanceError("offline migration SQL hash does not match its report")

    if os.environ.get("DMF_ENVIRONMENT", "").casefold() != "test":
        raise AcceptanceError("DMF_ENVIRONMENT must be TEST")
    raw_url = os.environ.get("DMF_TEST_DATABASE_URL")
    if not raw_url:
        raise AcceptanceError("DMF_TEST_DATABASE_URL is required")
    try:
        parsed = make_url(raw_url)
    except Exception as exc:
        raise AcceptanceError("test database configuration is invalid") from exc
    if (
        parsed.drivername not in {"postgresql", "postgresql+psycopg"}
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
        or parsed.database != "dmf_pulse_test"
    ):
        raise AcceptanceError("acceptance verifier requires the disposable local test database")
    normalized_url = parsed.set(drivername="postgresql+psycopg").render_as_string(
        hide_password=False
    )
    engine = create_engine(
        normalized_url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c timezone=UTC"},
    )
    try:
        with engine.connect() as connection:
            first = inspect_schema(connection)
            second = inspect_schema(connection)
    except Exception as exc:
        raise AcceptanceError("current PostgreSQL schema could not be verified") from exc
    finally:
        engine.dispose()
    expected_schema = report.get("schema")
    if not isinstance(expected_schema, dict):
        raise AcceptanceError("migration report schema evidence is missing")
    if (
        first.alembic_revision != target
        or first.schema_sha256 != second.schema_sha256
        or first.schema_sha256 != expected_schema.get("schema_sha256")
        or not first.postgres_version.startswith("18.4")
    ):
        raise AcceptanceError("current PostgreSQL schema differs from the migration evidence")
    return {
        "baseline_revision": EXPECTED_BASELINE_REVISION,
        "postgres_version": "18.4",
        "schema_sha256": first.schema_sha256,
        "target_revision": target,
    }


def _verify_package() -> dict[str, Any]:
    report = _read_json(PACKAGE_REPORT)
    fpl = report.get("fpl004")
    wheel = report.get("wheel")
    if report.get("status") != "PASS" or not isinstance(fpl, dict) or not isinstance(wheel, dict):
        raise AcceptanceError("installed-wheel report did not pass")
    replay = fpl.get("replay")
    validation = fpl.get("validation")
    if (
        fpl.get("network_requests") != 0
        or not isinstance(replay, dict)
        or replay.get("status") != "USABLE"
        or replay.get("bundle_member_count") != 2
        or not isinstance(validation, dict)
        or validation.get("status")
        not in {
            "VALID",
            "VALID_WITH_WARNINGS",
            "USABLE_WITH_WARNINGS",
        }
        or wheel.get("contains_py_typed") is not True
        or report.get("cleaned_up") is not True
    ):
        raise AcceptanceError("installed-wheel FPL replay or cleanup evidence is invalid")
    return {
        "bundle_semantic_sha256": replay.get("bundle_semantic_sha256"),
        "cleaned_up": True,
        "network_requests": 0,
        "wheel_sha256": wheel.get("sha256"),
    }


def _verify_coverage() -> dict[str, Any]:
    data_file = REPOSITORY_ROOT / ".coverage"
    if not data_file.is_file():
        raise AcceptanceError("coverage data from acceptance command 22 is missing")
    coverage = Coverage(
        data_file=str(data_file), config_file=str(REPOSITORY_ROOT / "pyproject.toml")
    )
    try:
        coverage.load()
        output = io.StringIO()
        percent = float(coverage.report(file=output, show_missing=False))
    except (CoverageException, NoDataError, OSError, ValueError) as exc:
        raise AcceptanceError("coverage data could not be independently reported") from exc
    if percent < 90.0:
        raise AcceptanceError("foundation package coverage is below 90 percent")
    return {"minimum_percent": 90.0, "observed_percent": round(percent, 6)}


def _verify_public_schemas() -> dict[str, Any]:
    required = (
        "provider_snapshot_result.schema.json",
        "quality_report.schema.json",
        "rights_decision.schema.json",
        "source_bundle_summary.schema.json",
    )
    hashes: dict[str, str] = {}
    for name in required:
        path = REPOSITORY_ROOT / "public_contracts" / name
        value = _read_json(path)
        if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise AcceptanceError("public FPL JSON Schema dialect is invalid")
        hashes[name] = _sha256(path)
    return hashes


def _verify_evidence_has_no_sensitive_marker() -> None:
    forbidden = (
        "RAW_BODY_" + "MUST_NOT_SURVIVE_FPL004",
        "SUPER_" + "SECRET_DO_NOT_LOG",
        "DMF_TEST_" + "API_KEY_DO_NOT_LOG",
        "postgresql://dmf_test:",
        "postgresql+psycopg://dmf_test:",
    )
    if not EVIDENCE_ROOT.is_dir():
        raise AcceptanceError("FPL-004 evidence directory is missing")
    for path in EVIDENCE_ROOT.rglob("*"):
        if not path.is_file() or path == REPORT_PATH or path.stat().st_size > 10 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if any(marker in text for marker in forbidden):
            raise AcceptanceError("FPL-004 evidence contains a forbidden sensitive marker")


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


def verify_acceptance() -> dict[str, Any]:
    """Verify independently observable artifacts produced by commands 1 through 22."""

    checks = {
        "coverage": _verify_coverage(),
        "fixtures": _verify_fixtures(),
        "git": _verify_git(),
        "migration": _verify_migration_and_database(),
        "package": _verify_package(),
        "public_schemas": _verify_public_schemas(),
        "rights": _verify_rights_gate(),
    }
    _verify_evidence_has_no_sensitive_marker()
    result = {
        "checks": checks,
        "checked_acceptance_commands": [13, 19, 20, 21, 22],
        "network_requests": 0,
        "status": "PASS",
        "ticket_id": "FPL-004",
    }
    _write_report(result)
    return result


def main() -> int:
    try:
        result = verify_acceptance()
    except AcceptanceError as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, indent=2, sort_keys=True))
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": f"acceptance verification failed ({type(exc).__name__})",
                    "status": "FAIL",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
