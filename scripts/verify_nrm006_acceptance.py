"""Independently verify the complete NRM-006 milestone and its evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import runpy
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from dmf_pulse.assurance.secret_scan import scan_repository
from dmf_pulse.database.migrate import head_revision
from dmf_pulse.database.schema import inspect_schema
from dmf_pulse.markets.models import MarketNormalisationResult, MarketQueryResult
from dmf_pulse.markets.policy import (
    CONFIDENCE_GATE_POLICY_SHA256,
    POLICY_SHA256,
    canonical_json_sha256,
    load_confidence_gate_policy,
    load_market_normalisation_policy,
)
from dmf_pulse.markets.projection import market_normalisation_semantic_projection

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence" / "tickets" / "NRM-006"
REPORT_PATH = EVIDENCE_ROOT / "acceptance_verification.json"
SECURITY_REPORT_PATH = EVIDENCE_ROOT / "security_scan.json"
MIGRATION_REPORT_PATH = EVIDENCE_ROOT / "migration_matrix.json"
PACKAGE_REPORT_PATH = EVIDENCE_ROOT / "package_report.json"
COVERAGE_PATH = EVIDENCE_ROOT / "coverage.json"
CRITICAL_COVERAGE_PATH = EVIDENCE_ROOT / "critical_coverage.json"
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures" / "odds" / "NRM-006"

REQUIRED_BRANCH = "stage/A6/NRM-006-odds-normalisation"
REQUIRED_BASELINE = "e36ea84cda9e80191a9160d037f8e7035477b9b1"
BASELINE_REVISION = "20260725_0004"
TARGET_REVISION = "20260803_0005"
FIXTURE_MANIFEST_SHA256 = "a63bd28ef7fcea90c56697ee0e77dc28ec10f63b53bdd794d21aa84815d85d23"
HAPPY_SEMANTIC_SHA256 = "bd8840cceed27199e3b10945ef54529a517df68b522a82ab0c935c460116a499"
SCHEMA_HASHES: dict[str, str] = {
    "probability.schema.json": "b2900cdbdb3c6d5dd4300eaa14508c8eb09852dc917d7fa95b5df15cfcba63df",
    "normalised_operator_market.schema.json": (
        "c2851ca0c051c61aaa404fb290f6974640b2b1453f8c5a43e8d89502d0ee21fb"
    ),
    "market_consensus.schema.json": (
        "60e59a14cb5c3a9abdbac5c7b4c929c9a38993a07a0b71cdc80704517fc56ad4"
    ),
    "market_normalisation_result.schema.json": (
        "b9a39f8f2a612645ddde141f8e9c8df340d65d1b1a8a4e01b42bb2f64a1eb789"
    ),
}
EXPECTED_MATRIX = [
    {"from": "base", "status": "PASS", "to": TARGET_REVISION},
    {"from": TARGET_REVISION, "status": "PASS", "to": BASELINE_REVISION},
    {"from": BASELINE_REVISION, "status": "PASS", "to": TARGET_REVISION},
    {"from": TARGET_REVISION, "status": "PASS", "to": BASELINE_REVISION},
    {"from": BASELINE_REVISION, "status": "PASS", "to": TARGET_REVISION},
]
EXPECTED_PRICES = {
    "book_alpha": {"AWAY": "4.20", "DRAW": "3.60", "HOME": "1.80"},
    "book_beta": {"AWAY": "4.10", "DRAW": "3.50", "HOME": "1.85"},
}


class AcceptanceError(Exception):
    """A bounded verifier failure that never contains provider data or credentials."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise AcceptanceError(f"required evidence is unavailable: {path.name}") from exc
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("report exceeds its bound")
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise AcceptanceError(f"required report is unavailable or invalid: {path.name}") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"required report root is invalid: {path.name}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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
        raise AcceptanceError("Git provenance command failed safely") from exc
    if completed.returncode != 0:
        raise AcceptanceError("Git provenance command failed safely")
    return completed.stdout.strip()


def _verify_git() -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "--verify", "HEAD")
    merge_base = _git("merge-base", REQUIRED_BASELINE, head)
    merges = _git("rev-list", "--merges", f"{REQUIRED_BASELINE}..{head}")
    dirty = _git("status", "--porcelain=v1", "--untracked-files=all")
    if (
        branch != REQUIRED_BRANCH
        or re.fullmatch(r"[0-9a-f]{40}", head) is None
        or merge_base != REQUIRED_BASELINE
        or merges
        or dirty
    ):
        raise AcceptanceError("repository provenance is not the exact clean NRM-006 state")
    return {
        "baseline": REQUIRED_BASELINE,
        "baseline_is_ancestor": True,
        "branch": branch,
        "clean": True,
        "head": head,
        "merge_commits_since_baseline": 0,
    }


def _verify_frozen_inputs() -> dict[str, Any]:
    manifest_path = FIXTURE_ROOT / "manifest.json"
    if _sha256(manifest_path) != FIXTURE_MANIFEST_SHA256:
        raise AcceptanceError("NRM-006 frozen fixture manifest hash differs")
    manifest = _read_json(manifest_path)
    entries = manifest.get("entries")
    oracles = manifest.get("oracles")
    if (
        manifest.get("fixture_manifest_version") != "nrm-006-fixtures-v1.1"
        or manifest.get("ticket") != "NRM-006"
        or not isinstance(entries, list)
        or len(entries) != 12
        or not isinstance(oracles, list)
        or len(oracles) != 11
        or len(set(oracles)) != 11
        or not all(isinstance(item, str) and item for item in oracles)
    ):
        raise AcceptanceError("NRM-006 frozen fixture manifest is malformed")
    seen: set[str] = set()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "rights_classification", "sha256", "synthetic"}
            or not isinstance(entry.get("path"), str)
            or re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))) is None
            or entry.get("synthetic") is not True
            or entry.get("rights_classification") != "SYNTHETIC_TEST"
        ):
            raise AcceptanceError("NRM-006 frozen fixture manifest entry is malformed")
        relative = str(entry["path"])
        if relative in seen or not relative.startswith("fixtures/odds/NRM-006/"):
            raise AcceptanceError("NRM-006 frozen fixture manifest path is invalid")
        seen.add(relative)
        candidate = (REPOSITORY_ROOT / relative).resolve()
        try:
            candidate.relative_to(FIXTURE_ROOT.resolve())
        except ValueError as exc:
            raise AcceptanceError("NRM-006 frozen fixture path escapes its root") from exc
        if _sha256(candidate) != entry["sha256"]:
            raise AcceptanceError("NRM-006 frozen fixture hash differs")
    for oracle in oracles:
        if not (FIXTURE_ROOT / str(oracle)).is_file():
            raise AcceptanceError("NRM-006 frozen oracle is unavailable")

    fixture_policy = _read_json(FIXTURE_ROOT / "normalisation_policy.json")
    config_policy = _read_json(REPOSITORY_ROOT / "config/markets/normalisation_policy.json")
    resource_policy = _read_json(
        REPOSITORY_ROOT / "src/dmf_pulse/markets/resources/normalisation_policy.json"
    )
    loaded = load_market_normalisation_policy()
    gate_config = _read_json(REPOSITORY_ROOT / "config/markets/confidence_gate_policy.json")
    gate_resource = _read_json(
        REPOSITORY_ROOT / "src/dmf_pulse/markets/resources/confidence_gate_policy.json"
    )
    gate_policy = load_confidence_gate_policy()
    if (
        fixture_policy != config_policy
        or fixture_policy != resource_policy
        or canonical_json_sha256(fixture_policy) != POLICY_SHA256
        or loaded.sha256 != POLICY_SHA256
        or loaded.policy_id != "market-normalisation-v1"
        or gate_config != gate_resource
        or canonical_json_sha256(gate_config) != CONFIDENCE_GATE_POLICY_SHA256
        or gate_policy.sha256 != CONFIDENCE_GATE_POLICY_SHA256
        or gate_policy.normalisation_policy_sha256 != POLICY_SHA256
    ):
        raise AcceptanceError("frozen normalisation policy identity differs")
    for name, expected_hash in SCHEMA_HASHES.items():
        if _sha256(REPOSITORY_ROOT / "public_contracts" / name) != expected_hash:
            raise AcceptanceError("a frozen NRM-006 public schema hash differs")
    return {
        "fixture_entry_count": len(entries),
        "fixture_manifest_sha256": FIXTURE_MANIFEST_SHA256,
        "confidence_gate_policy_sha256": gate_policy.sha256,
        "oracle_count": len(oracles),
        "policy_id": loaded.policy_id,
        "policy_sha256": loaded.sha256,
        "public_schema_count": len(SCHEMA_HASHES),
        "rights_classification": "SYNTHETIC_TEST",
    }


def _verify_migration_report() -> tuple[dict[str, Any], dict[str, Any]]:
    report = _read_json(MIGRATION_REPORT_PATH)
    database = report.get("database")
    offline = report.get("offline_sql")
    schema = report.get("schema")
    preservation = report.get("data_preservation")
    schema_manifest = report.get("schema_manifest")
    if (
        report.get("status") != "PASS"
        or report.get("ticket_id") != "NRM-006"
        or report.get("baseline_revision") != BASELINE_REVISION
        or report.get("target_revision") != TARGET_REVISION
        or report.get("revisions") != [TARGET_REVISION]
        or report.get("revision_count") != 1
        or report.get("metadata_drift_check") != "PASS"
        or report.get("matrix") != EXPECTED_MATRIX
        or not isinstance(database, dict)
        or database.get("postgres_version") != "18.4"
        or not isinstance(preservation, dict)
        or preservation.get("status") != "PASS"
        or not isinstance(offline, dict)
        or offline.get("secret_free") is not True
        or offline.get("path") != "evidence/tickets/NRM-006/offline_upgrade.sql"
        or re.fullmatch(r"[0-9a-f]{64}", str(offline.get("sha256"))) is None
        or not isinstance(schema, dict)
        or schema.get("alembic_revision") != TARGET_REVISION
        or re.fullmatch(r"[0-9a-f]{64}", str(schema.get("schema_sha256"))) is None
        or not isinstance(schema_manifest, dict)
        or schema_manifest.get("path") != "evidence/tickets/NRM-006/schema_manifest.json"
        or re.fullmatch(r"[0-9a-f]{64}", str(schema_manifest.get("sha256"))) is None
    ):
        raise AcceptanceError("migration matrix does not prove the exact NRM-006 path")
    offline_path = REPOSITORY_ROOT / str(offline["path"])
    schema_path = REPOSITORY_ROOT / str(schema_manifest["path"])
    if (
        _sha256(offline_path) != offline["sha256"]
        or _sha256(schema_path) != schema_manifest["sha256"]
    ):
        raise AcceptanceError("migration evidence hashes differ from their files")
    return report, schema


def _verify_database(expected_schema: dict[str, Any]) -> dict[str, Any]:
    if os.environ.get("DMF_ENVIRONMENT", "").casefold() != "test":
        raise AcceptanceError("DMF_ENVIRONMENT must select TEST")
    raw_url = os.environ.get("DMF_TEST_DATABASE_URL")
    if not raw_url:
        raise AcceptanceError("DMF_TEST_DATABASE_URL is required")
    try:
        parsed = make_url(raw_url)
    except Exception as exc:
        raise AcceptanceError("disposable database configuration is invalid") from exc
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
    if (
        head_revision() != TARGET_REVISION
        or first.alembic_revision != TARGET_REVISION
        or first.schema_sha256 != second.schema_sha256
        or first.schema_sha256 != expected_schema.get("schema_sha256")
        or not first.postgres_version.startswith("18.4")
    ):
        raise AcceptanceError("current PostgreSQL 18.4 schema differs from migration evidence")
    return {
        "alembic_revision": first.alembic_revision,
        "postgres_version": "18.4",
        "schema_sha256": first.schema_sha256,
    }


def _verify_migration_and_database() -> dict[str, Any]:
    report, expected_schema = _verify_migration_report()
    database = _verify_database(expected_schema)
    return {
        **database,
        "baseline_revision": BASELINE_REVISION,
        "matrix_step_count": len(cast(list[object], report["matrix"])),
        "target_revision": TARGET_REVISION,
    }


def _verify_package() -> dict[str, Any]:
    report = _read_json(PACKAGE_REPORT_PATH)
    wheel = report.get("wheel")
    if (
        report.get("status") != "PASS"
        or report.get("network_requests") != 0
        or report.get("cleaned_up") is not True
        or report.get("database_isolated") is not True
        or report.get("database_cleaned_up") is not True
        or report.get("fpl_status") != "USABLE"
        or report.get("odds_status") != "COMPLETE"
        or report.get("normalisation_status") != "NORMALISED"
        or report.get("observation_count") != 6
        or report.get("semantic_result_sha256") != HAPPY_SEMANTIC_SHA256
        or not isinstance(wheel, dict)
        or wheel.get("contains_confidence_gate_policy") is not True
        or wheel.get("contains_normalisation_policy") is not True
        or wheel.get("distribution") != "dmf-pulse==0.2.0"
        or re.fullmatch(r"[0-9a-f]{64}", str(wheel.get("sha256"))) is None
    ):
        raise AcceptanceError("installed-wheel report does not prove NRM-006 offline behavior")
    return {
        "cleaned_up": True,
        "database_cleaned_up": True,
        "database_isolated": True,
        "network_requests": 0,
        "semantic_result_sha256": HAPPY_SEMANTIC_SHA256,
        "wheel_sha256": wheel["sha256"],
    }


def _percentage(value: object, minimum: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and minimum <= float(value) <= 100.0
    )


def _verify_coverage() -> dict[str, Any]:
    critical = _read_json(CRITICAL_COVERAGE_PATH)
    if critical.get("coverage_json_sha256") != _sha256(COVERAGE_PATH):
        raise AcceptanceError("critical coverage report does not bind the coverage JSON")
    namespace = runpy.run_path(
        str(REPOSITORY_ROOT / "scripts" / "verify_nrm006_critical_coverage.py")
    )
    checker = cast(Callable[[Path], dict[str, Any]], namespace["check_coverage"])
    try:
        independent = checker(COVERAGE_PATH)
    except ValueError as exc:
        raise AcceptanceError(
            "NRM-006 critical coverage could not be independently checked"
        ) from exc
    if any(critical.get(key) != value for key, value in independent.items()):
        raise AcceptanceError("critical coverage report differs from independent calculation")
    categories = tuple(cast(dict[str, object], namespace["CRITICAL_FUNCTIONS"]))
    category_values = [
        critical.get(f"{category}_branch_coverage_percent") for category in categories
    ]
    if (
        critical.get("status") != "PASS"
        or critical.get("ok") is not True
        or critical.get("errors") != []
        or not _percentage(critical.get("repository_combined_coverage_percent"), 90.0)
        or not _percentage(critical.get("overall_branch_coverage_percent"), 90.0)
        or not all(_percentage(value, 95.0) for value in category_values)
        or not _percentage(critical.get("mathematical_core_branch_coverage_percent"), 100.0)
    ):
        raise AcceptanceError("NRM-006 overall or critical coverage gates did not pass")
    numeric_category_values = cast(list[int | float], category_values)
    return {
        "coverage_json_sha256": critical["coverage_json_sha256"],
        "critical_branch_coverage_percent": min(float(value) for value in numeric_category_values),
        "critical_scope_count": len(categories),
        "math_branch_coverage_percent": float(
            critical["mathematical_core_branch_coverage_percent"]
        ),
        "overall_branch_coverage_percent": float(critical["overall_branch_coverage_percent"]),
        "repository_combined_coverage_percent": float(
            critical["repository_combined_coverage_percent"]
        ),
    }


def _verify_goldens() -> dict[str, Any]:
    namespace = runpy.run_path(str(REPOSITORY_ROOT / "scripts" / "verify_nrm006_goldens.py"))
    verifier = cast(Callable[[Path], dict[str, Any]], namespace["verify_goldens"])
    try:
        report = verifier(REPOSITORY_ROOT)
    except Exception as exc:
        raise AcceptanceError("NRM-006 frozen goldens did not verify") from exc
    hashes = report.get("semantic_result_sha256")
    if (
        report.get("status") != "PASS"
        or report.get("case_count") != 6
        or report.get("network_requests") != 0
        or not isinstance(hashes, dict)
        or hashes.get("happy_path_consensus.json") != HAPPY_SEMANTIC_SHA256
    ):
        raise AcceptanceError("NRM-006 frozen golden report is incomplete")
    return report


def _verify_temporal_canaries() -> dict[str, Any]:
    namespace = runpy.run_path(
        str(REPOSITORY_ROOT / "scripts" / "verify_nrm006_temporal_canaries.py")
    )
    frozen_verifier = cast(Callable[[], dict[str, object]], namespace["_verify_frozen_canaries"])
    environment_builder = cast(Callable[[], dict[str, str]], namespace["_test_environment"])
    runner = cast(Callable[[dict[str, str]], None], namespace["_run_canaries"])
    try:
        frozen = frozen_verifier()
        runner(environment_builder())
    except Exception as exc:
        raise AcceptanceError("NRM-006 temporal and retry canaries did not verify") from exc
    modules = namespace.get("TEST_MODULES")
    if frozen.get("verified_file_count") != 6 or not isinstance(modules, tuple):
        raise AcceptanceError("NRM-006 temporal canary evidence is incomplete")
    return {
        "database_scope": "DISPOSABLE_LOCAL_POSTGRESQL",
        "external_network_calls": 0,
        "frozen_canaries": frozen,
        "real_sleep_calls": 0,
        "status": "PASS",
        "test_modules": list(modules),
    }


def _verify_captured_outputs() -> dict[str, Any]:
    captured: dict[str, Any] = {}
    observations_path = EVIDENCE_ROOT / "market_observations.json"
    if observations_path.is_file():
        try:
            observations = MarketQueryResult.model_validate_json(
                observations_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise AcceptanceError("captured market observation output is invalid") from exc
        prices = {
            book.operator_key: {
                observation.outcome.value: format(observation.decimal_odds, "f")
                for observation in book.observations
            }
            for book in observations.books
        }
        if (
            observations.as_of != datetime(2026, 8, 20, 12, 5, tzinfo=UTC)
            or observations.observation_count != 6
            or prices != EXPECTED_PRICES
        ):
            raise AcceptanceError("captured market observation output differs from its oracle")
        captured["observations"] = {
            "observation_count": 6,
            "operator_count": 2,
            "source_scale_preserved": True,
        }
    normalisation_candidates = tuple(
        path
        for path in (
            EVIDENCE_ROOT / "market_normalisation.json",
            EVIDENCE_ROOT / "market_normalisation_result.json",
            EVIDENCE_ROOT / "normalisation_result.json",
        )
        if path.is_file()
    )
    projections: list[dict[str, Any]] = []
    policy = load_market_normalisation_policy()
    for path in normalisation_candidates:
        try:
            result = MarketNormalisationResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise AcceptanceError("captured normalisation output is invalid") from exc
        projections.append(market_normalisation_semantic_projection(result, policy=policy))
    if projections:
        expected = _read_json(FIXTURE_ROOT / "expected_outputs/happy_path_consensus.json")
        if any(projection != expected for projection in projections):
            raise AcceptanceError("captured normalisation output differs from its golden")
        captured["normalisation"] = {
            "capture_count": len(projections),
            "semantic_result_sha256": HAPPY_SEMANTIC_SHA256,
        }
    return {"capture_count": len(captured), **captured}


def _verify_security() -> dict[str, Any]:
    try:
        findings = scan_repository(REPOSITORY_ROOT)
    except Exception as exc:
        raise AcceptanceError("repository security scan could not complete") from exc
    if findings:
        raise AcceptanceError("repository security scan has unapproved findings")
    return {"finding_count": 0, "status": "PASS"}


def verify(
    *,
    report_path: Path = REPORT_PATH,
    security_report_path: Path = SECURITY_REPORT_PATH,
) -> dict[str, Any]:
    """Verify every independently reproducible NRM-006 completion invariant."""

    git = _verify_git()
    frozen = _verify_frozen_inputs()
    migration = _verify_migration_and_database()
    package = _verify_package()
    coverage = _verify_coverage()
    goldens = _verify_goldens()
    temporal = _verify_temporal_canaries()
    captures = _verify_captured_outputs()
    security = _verify_security()
    report = {
        "captures": captures,
        "coverage": coverage,
        "database": migration,
        "frozen_inputs": frozen,
        "git": git,
        "goldens": goldens,
        "package": package,
        "security": security,
        "status": "PASS",
        "temporal_canaries": temporal,
        "ticket_id": "NRM-006",
    }
    _write_json(security_report_path, security)
    _write_json(report_path, report)
    return report


def main() -> int:
    try:
        report = verify()
    except AcceptanceError as exc:
        report = {"error": str(exc), "status": "FAIL", "ticket_id": "NRM-006"}
        _write_json(REPORT_PATH, report)
        print(json.dumps(report, sort_keys=True))
        return 1
    except Exception as exc:
        report = {
            "error": f"NRM-006 acceptance verification failed ({type(exc).__name__})",
            "status": "FAIL",
            "ticket_id": "NRM-006",
        }
        _write_json(REPORT_PATH, report)
        print(json.dumps(report, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
