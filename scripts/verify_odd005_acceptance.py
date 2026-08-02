"""Independently verify ODD-005 artifacts and fail-closed invariants."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import runpy
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from coverage import Coverage
from coverage.exceptions import CoverageException, NoDataError
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from dmf_pulse.assurance.secret_scan import scan_repository
from dmf_pulse.assurance.specs import validate_odd005_frozen_inputs
from dmf_pulse.database.migrate import head_revision
from dmf_pulse.database.schema import inspect_schema
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.client import (
    OddsClient,
    StaticCredentialProvider,
    UnavailableCredentialProvider,
)
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.markets.models import MarketOutcome, MarketQueryResult

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence/tickets/ODD-005"
REPORT_PATH = EVIDENCE_ROOT / "acceptance_verification.json"
MIGRATION_REPORT = EVIDENCE_ROOT / "migration_matrix.json"
PACKAGE_REPORT = EVIDENCE_ROOT / "package_report.json"
MARKET_REPORT = EVIDENCE_ROOT / "market_observations.json"
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures/odds/ODD-005"
REQUIRED_BRANCH = "stage/A5/ODD-005-odds-provider-foundation"
REQUIRED_BASELINE = "7034e38f32cd579c90d35c5fe3f10921c3656be0"
EXPECTED_BASELINE_REVISION = "20260724_0002"


class AcceptanceError(Exception):
    """A safe verifier failure that never contains a body, credential, or URL."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise AcceptanceError(f"required report is unavailable: {path.name}") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"required report is malformed: {path.name}")
    return value


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


def _git(*arguments: str) -> str:
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
    if completed.returncode != 0:
        raise AcceptanceError("Git provenance command failed")
    return completed.stdout.strip()


def _verify_git() -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "--verify", "HEAD")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", REQUIRED_BASELINE, head],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        shell=False,
        timeout=30,
    )
    merges = _git("rev-list", "--merges", f"{REQUIRED_BASELINE}..{head}")
    dirty = _git("status", "--porcelain=v1", "--untracked-files=all")
    if branch != REQUIRED_BRANCH or len(head) != 40 or ancestor.returncode != 0 or merges or dirty:
        raise AcceptanceError("repository provenance is not the exact clean ODD-005 state")
    return {"baseline": REQUIRED_BASELINE, "branch": branch, "clean": True, "head": head}


def _verify_migration_and_database() -> dict[str, Any]:
    report = _read_json(MIGRATION_REPORT)
    matrix = report.get("matrix")
    preservation = report.get("data_preservation")
    offline = report.get("offline_sql")
    target = head_revision()
    expected_matrix = [
        {"from": "base", "status": "PASS", "to": "20260725_0004"},
        {"from": "20260725_0004", "status": "PASS", "to": "20260724_0002"},
        {"from": "20260724_0002", "status": "PASS", "to": "20260725_0004"},
        {"from": "20260725_0004", "status": "PASS", "to": "20260724_0002"},
        {"from": "20260724_0002", "status": "PASS", "to": "20260725_0004"},
    ]
    if (
        report.get("status") != "PASS"
        or report.get("ticket_id") != "ODD-005"
        or report.get("baseline_revision") != EXPECTED_BASELINE_REVISION
        or report.get("target_revision") != target
        or report.get("revisions") != ["20260725_0003", "20260725_0004"]
        or report.get("metadata_drift_check") != "PASS"
        or matrix != expected_matrix
        or not isinstance(preservation, dict)
        or preservation.get("status") != "PASS"
        or not isinstance(offline, dict)
        or offline.get("secret_free") is not True
    ):
        raise AcceptanceError("migration matrix does not prove the exact ODD-005 path")
    if offline.get("path") != "evidence/tickets/ODD-005/offline_upgrade.sql":
        raise AcceptanceError("offline SQL path is not the exact bounded evidence path")
    offline_path = (REPOSITORY_ROOT / str(offline["path"])).resolve()
    try:
        offline_path.relative_to(EVIDENCE_ROOT.resolve())
    except ValueError as exc:
        raise AcceptanceError("offline SQL path escapes ODD-005 evidence") from exc
    if not offline_path.is_file() or _sha256(offline_path) != offline.get("sha256"):
        raise AcceptanceError("offline SQL does not match the migration report")

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
        raise AcceptanceError("verifier requires the disposable local PostgreSQL database")
    engine = create_engine(
        parsed.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c timezone=UTC"},
    )
    try:
        with engine.connect() as connection:
            first = inspect_schema(connection)
            second = inspect_schema(connection)
    except Exception as exc:
        raise AcceptanceError("current PostgreSQL schema could not be inspected") from exc
    finally:
        engine.dispose()
    expected_schema = report.get("schema")
    if (
        not isinstance(expected_schema, dict)
        or first.alembic_revision != target
        or first.schema_sha256 != second.schema_sha256
        or first.schema_sha256 != expected_schema.get("schema_sha256")
        or not first.postgres_version.startswith("18.4")
    ):
        raise AcceptanceError("current schema differs from deterministic migration evidence")
    return {
        "baseline_revision": EXPECTED_BASELINE_REVISION,
        "postgres_version": "18.4",
        "schema_sha256": first.schema_sha256,
        "target_revision": target,
    }


def _verify_frozen_inputs_and_decimal() -> dict[str, Any]:
    frozen = validate_odd005_frozen_inputs(REPOSITORY_ROOT)
    source = (FIXTURE_ROOT / "happy_path.json").read_bytes()
    lexical_variant = source.replace(b'"price": 1.80', b'"price": 1.8', 1)
    first = parse_odds_payload(source)
    second = parse_odds_payload(lexical_variant)
    if (
        first.body_sha256 == second.body_sha256
        or first.semantic_sha256 != second.semantic_sha256
        or format(first.events[0].bookmakers[0].markets[0].outcomes[0].price, "f") != "1.80"
    ):
        raise AcceptanceError("Decimal lexical and semantic hash policies conflict")
    return {
        "fixture_entry_count": frozen["fixture_entry_count"],
        "frozen_input_count": frozen["file_count"],
        "lexical_price": "1.80",
        "semantic_equivalence": True,
    }


def _verify_zero_transport() -> dict[str, Any]:
    profiles = load_rights_profiles()
    profile = profiles["the_odds_api_private_analytics_v1"]
    constructed = 0
    sent = 0

    class CountingTransport:
        def send(self, request: object) -> object:
            nonlocal sent
            sent += 1
            raise AssertionError("transport must not be invoked")

    def factory() -> CountingTransport:
        nonlocal constructed
        constructed += 1
        return CountingTransport()

    missing_client = OddsClient(
        profile,
        credential_provider=UnavailableCredentialProvider(),
        transport_factory=factory,
        clock=lambda: datetime(2026, 8, 20, 12, tzinfo=UTC),
    )
    try:
        missing_client.fetch()
    except IngestionError as exc:
        if exc.code != "CREDENTIAL_UNAVAILABLE":
            raise AcceptanceError("missing credential emitted the wrong failure") from None
    else:
        raise AcceptanceError("missing credential did not block")
    if constructed != 0 or sent != 0 or missing_client.transport_call_count != 0:
        raise AcceptanceError("credential refusal crossed the transport boundary")

    fake_credential = (
        (FIXTURE_ROOT / "security_fake_credential.txt").read_text(encoding="utf-8").strip()
    )
    quota_client = OddsClient(
        profile,
        credential_provider=StaticCredentialProvider(fake_credential),
        transport_factory=factory,
        clock=lambda: datetime(2026, 8, 20, 12, tzinfo=UTC),
    )
    quota = QuotaState(
        remaining=0,
        used=500,
        last_cost=1,
        observed_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        source=QuotaSource.SYNTHETIC_FIXTURE,
    )
    try:
        quota_client.fetch(quota=quota)
    except IngestionError as exc:
        if exc.code != "QUOTA_EXHAUSTED":
            raise AcceptanceError("quota preflight emitted the wrong failure") from None
    else:
        raise AcceptanceError("quota preflight did not block")
    if constructed != 0 or sent != 0 or quota_client.transport_call_count != 0:
        raise AcceptanceError("quota refusal crossed the transport boundary")
    return {
        "credential_failure": "CREDENTIAL_UNAVAILABLE",
        "quota_failure": "QUOTA_EXHAUSTED",
        "transport_call_count": 0,
        "transport_construct_count": 0,
    }


def _verify_market() -> dict[str, Any]:
    try:
        if MARKET_REPORT.stat().st_size > 1024 * 1024:
            raise ValueError("captured result exceeds its bound")
        result = MarketQueryResult.model_validate_json(MARKET_REPORT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise AcceptanceError("captured literal market query is invalid") from exc
    prices = {
        book.operator_key: {
            quote.outcome.value: format(quote.decimal_odds, "f") for quote in book.observations
        }
        for book in result.books
    }
    expected = {
        "SYNTHETIC_BOOK_ALPHA": {
            "HOME": "1.80",
            "DRAW": "3.60",
            "AWAY": "4.20",
        },
        "SYNTHETIC_BOOK_BETA": {
            "HOME": "1.85",
            "DRAW": "3.50",
            "AWAY": "4.10",
        },
    }
    if (
        result.as_of != datetime(2026, 8, 20, 12, 5, tzinfo=UTC)
        or result.observation_count != 6
        or prices != expected
    ):
        raise AcceptanceError("current as-of market state differs from the golden oracle")
    if any(
        quote.outcome not in {MarketOutcome.HOME, MarketOutcome.DRAW, MarketOutcome.AWAY}
        for book in result.books
        for quote in book.observations
    ):
        raise AcceptanceError("market output contains an unsupported selection")
    return {
        "observation_count": 6,
        "operator_books": 2,
        "source_scale_preserved": True,
        "literal_command_output_validated": True,
    }


def _verify_package() -> dict[str, Any]:
    report = _read_json(PACKAGE_REPORT)
    foundation = report.get("foundation")
    fpl = report.get("fpl004")
    odd = report.get("odd005")
    wheel = report.get("wheel")
    expected_prices = {
        "SYNTHETIC_BOOK_ALPHA": {"AWAY": "4.20", "DRAW": "3.60", "HOME": "1.80"},
        "SYNTHETIC_BOOK_BETA": {"AWAY": "4.10", "DRAW": "3.50", "HOME": "1.85"},
    }
    if (
        report.get("status") != "PASS"
        or report.get("network_requests") != 0
        or report.get("cleaned_up") is not True
        or report.get("database_isolated") is not True
        or report.get("database_cleaned_up") is not True
        or not isinstance(foundation, dict)
        or foundation.get("status") != "PASS"
        or foundation.get("cleaned_up") is not True
        or foundation.get("network_fetch_disabled") is not True
        or foundation.get("clean_environment_outside_repository") is not True
        or not isinstance(fpl, dict)
        or fpl.get("status") != "USABLE"
        or fpl.get("bundle_member_count") != 2
        or re.fullmatch(r"[0-9a-f]{64}", str(fpl.get("semantic_sha256"))) is None
        or not isinstance(odd, dict)
        or not isinstance(wheel, dict)
        or wheel.get("contains_odds_resources") is not True
        or wheel.get("contains_py_typed") is not True
        or wheel.get("distribution") != "dmf-pulse==0.2.0"
        or re.fullmatch(r"[0-9a-f]{64}", str(wheel.get("sha256"))) is None
    ):
        raise AcceptanceError("installed-wheel report did not prove the ODD-005 contract")
    refusal = odd.get("refusal")
    replay = odd.get("replay")
    market = odd.get("market")
    if (
        odd.get("validation_status") not in {"VALID", "VALID_WITH_WARNINGS"}
        or replay
        != {
            "complete_books_created": 2,
            "observations_created": 6,
            "status": "COMPLETE",
        }
        or market
        != {
            "observation_count": 6,
            "operator_books": 2,
            "prices": expected_prices,
        }
        or refusal != {"code": "CREDENTIAL_UNAVAILABLE", "transport_called": False}
    ):
        raise AcceptanceError("installed-wheel ODD-005 proof differs from the frozen oracles")
    return {"cleaned_up": True, "network_requests": 0, "wheel_sha256": wheel["sha256"]}


def _verify_coverage() -> dict[str, Any]:
    data_file = REPOSITORY_ROOT / ".coverage"
    coverage_path = EVIDENCE_ROOT / "coverage.json"
    if not data_file.is_file():
        raise AcceptanceError("coverage data from command 25 is missing")
    coverage = Coverage(
        data_file=str(data_file), config_file=str(REPOSITORY_ROOT / "pyproject.toml")
    )
    try:
        coverage.load()
        output = io.StringIO()
        observed = float(coverage.report(file=output, show_missing=False))
        coverage.json_report(outfile=str(coverage_path), pretty_print=False, show_contexts=False)
    except (CoverageException, NoDataError, OSError, ValueError) as exc:
        raise AcceptanceError("coverage data could not be independently reported") from exc
    namespace = runpy.run_path(str(REPOSITORY_ROOT / "scripts/check_odd005_coverage_gates.py"))
    checker = namespace.get("check_coverage")
    if not callable(checker):
        raise AcceptanceError("ODD-005 coverage checker is unavailable")
    try:
        report = checker(coverage_path, repository_root=REPOSITORY_ROOT)
    except ValueError as exc:
        raise AcceptanceError("ODD-005 coverage gates could not be evaluated") from exc
    if (
        not isinstance(report, dict)
        or report.get("ok") is not True
        or observed < 90.0
        or float(report.get("overall_branch_coverage_percent", 0.0)) < 90.0
    ):
        raise AcceptanceError("ODD-005 coverage gates did not pass")
    return {
        "critical_odds_ingestion_percent": report[
            "critical_odds_ingestion_branch_coverage_percent"
        ],
        "minimum_percent": 90.0,
        "observed_percent": round(observed, 6),
    }


def verify() -> dict[str, Any]:
    findings = scan_repository(REPOSITORY_ROOT)
    if findings:
        raise AcceptanceError("repository secret/canary scan has unapproved findings")
    report = {
        "coverage": _verify_coverage(),
        "database": _verify_migration_and_database(),
        "frozen_inputs": _verify_frozen_inputs_and_decimal(),
        "git": _verify_git(),
        "market": _verify_market(),
        "package": _verify_package(),
        "security": {"finding_count": 0, "status": "PASS"},
        "status": "PASS",
        "transport_preflight": _verify_zero_transport(),
    }
    _write_report(report)
    return report


def main() -> int:
    try:
        report = verify()
    except AcceptanceError as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": f"ODD-005 acceptance verification failed ({type(exc).__name__})",
                    "status": "FAIL",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
