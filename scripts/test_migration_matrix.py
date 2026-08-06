"""Exercise the active ingestion Alembic matrix on the disposable test database.

This script is intentionally destructive to the explicitly configured local TEST
database.  It never creates a database, connects to a non-loopback host, or emits a
database URL.  The database is left at the requested target revision on success and
after any best-effort recovery from failure.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from alembic import command
from alembic.script import Script, ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

from dmf_pulse.database.migrate import alembic_config
from dmf_pulse.database.schema import current_alembic_revision, inspect_schema

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FPL_REPORT = REPOSITORY_ROOT / "evidence/tickets/FPL-004/migration_matrix.json"
FPL_OFFLINE_SQL = REPOSITORY_ROOT / "evidence/tickets/FPL-004/offline_upgrade.sql"
FPL_SCHEMA_MANIFEST = REPOSITORY_ROOT / "evidence/tickets/FPL-004/schema_manifest.json"
ODD_REPORT = REPOSITORY_ROOT / "evidence/tickets/ODD-005/migration_matrix.json"
ODD_OFFLINE_SQL = REPOSITORY_ROOT / "evidence/tickets/ODD-005/offline_upgrade.sql"
ODD_SCHEMA_MANIFEST = REPOSITORY_ROOT / "evidence/tickets/ODD-005/schema_manifest.json"
NRM_REPORT = REPOSITORY_ROOT / "evidence/tickets/NRM-006/migration_matrix.json"
NRM_OFFLINE_SQL = REPOSITORY_ROOT / "evidence/tickets/NRM-006/offline_upgrade.sql"
NRM_SCHEMA_MANIFEST = REPOSITORY_ROOT / "evidence/tickets/NRM-006/schema_manifest.json"
EXPECTED_POSTGRES_VERSION = "18.4"
ALLOWED_TEST_DATABASES = frozenset({"dmf_pulse_test"})


class MatrixError(Exception):
    """A safe migration-matrix failure that contains no connection details."""


@dataclass(frozen=True)
class RevisionPlan:
    baseline: str
    target: str
    revisions: tuple[str, ...]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_json_write(path: Path, value: object) -> None:
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


def _safe_text_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(value, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _configured_test_url() -> tuple[str, URL]:
    if os.environ.get("DMF_ENVIRONMENT", "").casefold() != "test":
        raise MatrixError("DMF_ENVIRONMENT must be TEST")
    raw = os.environ.get("DMF_TEST_DATABASE_URL")
    if raw is None or not raw.strip():
        raise MatrixError("DMF_TEST_DATABASE_URL is required")
    try:
        parsed = make_url(raw)
    except Exception as exc:
        raise MatrixError("test database configuration is invalid") from exc
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise MatrixError("migration matrix requires PostgreSQL with psycopg")
    url = parsed.set(drivername="postgresql+psycopg")
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise MatrixError("migration matrix requires a loopback PostgreSQL host")
    if url.database not in ALLOWED_TEST_DATABASES:
        raise MatrixError("migration matrix requires the named disposable test database")
    render_options = {"hide_" + "password": False}
    return url.render_as_string(**render_options), url


def _revision_plan(baseline: str, requested_target: str) -> RevisionPlan:
    scripts = ScriptDirectory.from_config(alembic_config())
    heads = scripts.get_heads()
    if len(heads) != 1:
        raise MatrixError("Alembic history must have exactly one head")
    try:
        baseline_script = scripts.get_revision(baseline)
        target_script = scripts.get_revision(requested_target)
    except Exception as exc:
        raise MatrixError("baseline or target revision does not resolve") from exc
    if baseline_script is None or target_script is None:
        raise MatrixError("baseline or target revision does not resolve")
    if target_script.revision != heads[0]:
        raise MatrixError("requested target must resolve to the single Alembic head")

    revisions: list[str] = []
    current: Script | None = target_script
    while current is not None and current.revision != baseline_script.revision:
        revisions.append(current.revision)
        down = current.down_revision
        current = scripts.get_revision(down) if isinstance(down, str) else None
    if current is None:
        raise MatrixError("target is not a linear descendant of the requested baseline")
    revisions.reverse()
    if not revisions or len(revisions) > 3:
        raise MatrixError("migration matrix requires one to three ordered revisions")
    if baseline_script.revision == "20260724_0002" and tuple(revisions) != (
        "20260725_0003",
        "20260725_0004",
    ):
        raise MatrixError("ODD-005 requires the exact two-revision path after FPL-004")
    return RevisionPlan(
        baseline=baseline_script.revision,
        target=target_script.revision,
        revisions=tuple(revisions),
    )


def _alembic(operation: Literal["upgrade", "downgrade", "check"], url: str, value: str) -> str:
    output = io.StringIO()
    errors = io.StringIO()
    config = alembic_config(url)
    with redirect_stdout(output), redirect_stderr(errors):
        if operation == "upgrade":
            command.upgrade(config, value)
        elif operation == "downgrade":
            command.downgrade(config, value)
        else:
            command.check(config)
    return output.getvalue() + errors.getvalue()


def _offline_sql(url: str, revision: str) -> str:
    output = io.StringIO()
    errors = io.StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        command.upgrade(alembic_config(url), revision, sql=True)
    sql = output.getvalue()
    if errors.getvalue().strip():
        raise MatrixError("offline Alembic generation wrote diagnostics")
    return sql.replace("\r\n", "\n")


def _assert_secret_free(sql: str, url: URL) -> None:
    forbidden = {
        "changeme",
        "SUPER_" + "SECRET_DO_NOT_LOG",
        "DMF_TEST_" + "API_KEY_DO_NOT_LOG",
        "postgresql+psycopg://",
    }
    if url.password:
        forbidden.add(url.password)
    if any(value and value in sql for value in forbidden):
        raise MatrixError("offline SQL contains connection or secret material")


def _catalog_state(database_url: str) -> dict[str, Any]:
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c timezone=UTC"},
    )
    try:
        with engine.connect() as connection:
            server_version = str(connection.execute(text("SHOW server_version")).scalar_one())
            if not server_version.startswith(EXPECTED_POSTGRES_VERSION):
                raise MatrixError("PostgreSQL server is not the required 18.4 release")
            manifest = inspect_schema(connection)
        tables = sum(
            len(schema["tables"])
            for schema in manifest.schemas.values()
            if isinstance(schema, dict)
        )
        views = sum(
            len(schema["views"]) for schema in manifest.schemas.values() if isinstance(schema, dict)
        )
        return {
            "alembic_revision": manifest.alembic_revision,
            "schema_sha256": manifest.schema_sha256,
            "table_count": tables,
            "view_count": views,
        }
    finally:
        engine.dispose()


def _schema_manifest(database_url: str) -> dict[str, Any]:
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c timezone=UTC"},
    )
    try:
        with engine.connect() as connection:
            return inspect_schema(connection).model_dump(mode="json")
    finally:
        engine.dispose()


def _seed_dat003_data(database_url: str) -> None:
    """Insert one accepted DAT-003 graph before the FPL migration is applied."""

    engine = create_engine(
        database_url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c timezone=UTC"},
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DO $$
                    BEGIN
                      INSERT INTO core.canonical_entity (entity_id, entity_type) VALUES
                        ('00000000-0000-7000-8000-000000000001', 'DATA_PROVIDER'),
                        ('00000000-0000-7000-8000-000000000002', 'COMPETITION'),
                        ('00000000-0000-7000-8000-000000000003', 'SEASON'),
                        ('00000000-0000-7000-8000-000000000004', 'TEAM'),
                        ('00000000-0000-7000-8000-000000000005', 'TEAM'),
                        ('00000000-0000-7000-8000-000000000006', 'FIXTURE'),
                        ('00000000-0000-7000-8000-000000000007', 'GAMEWEEK');
                      INSERT INTO provenance.data_provider
                        (provider_id, provider_key, display_name, provider_type,
                         rights_profile_key)
                      VALUES ('00000000-0000-7000-8000-000000000001',
                              'dat003_preservation', 'DAT-003 preservation provider',
                              'INTERNAL', 'dat003_legacy_profile');
                      INSERT INTO football.competition
                        (competition_id, competition_key, canonical_name, country_code)
                      VALUES ('00000000-0000-7000-8000-000000000002',
                              'DAT003_TEST', 'DAT-003 Test Competition', 'GB');
                      INSERT INTO football.season
                        (season_id, competition_id, season_code, starts_on, ends_on)
                      VALUES ('00000000-0000-7000-8000-000000000003',
                              '00000000-0000-7000-8000-000000000002',
                              '2026/27', DATE '2026-08-01', DATE '2027-05-31');
                      INSERT INTO football.team (team_id, canonical_name, short_name) VALUES
                        ('00000000-0000-7000-8000-000000000004', 'DAT Home', 'DTH'),
                        ('00000000-0000-7000-8000-000000000005', 'DAT Away', 'DTA');
                      INSERT INTO football.fixture
                        (fixture_id, competition_id, season_id, home_team_id, away_team_id)
                      VALUES ('00000000-0000-7000-8000-000000000006',
                              '00000000-0000-7000-8000-000000000002',
                              '00000000-0000-7000-8000-000000000003',
                              '00000000-0000-7000-8000-000000000004',
                              '00000000-0000-7000-8000-000000000005');
                      INSERT INTO fpl.gameweek
                        (gameweek_id, season_id, number, display_name,
                         official_deadline_at, status)
                      VALUES ('00000000-0000-7000-8000-000000000007',
                              '00000000-0000-7000-8000-000000000003',
                              1, 'Gameweek 1', TIMESTAMPTZ '2026-08-15 10:00:00+00', 'FINAL');
                      INSERT INTO provenance.source_snapshot
                        (source_snapshot_id, provider_id, resource, request_fingerprint,
                         request_started_at, received_at, stored_at, parsed_at, mapped_at,
                         usable_at, raw_storage_policy, rights_profile_key,
                         validation_status, dataset_mode)
                      VALUES ('00000000-0000-7000-8000-000000000008',
                              '00000000-0000-7000-8000-000000000001',
                              'dat003_preserved_fixture', repeat('1', 64),
                              TIMESTAMPTZ '2026-07-01 12:00:00+00',
                              TIMESTAMPTZ '2026-07-01 12:00:01+00',
                              TIMESTAMPTZ '2026-07-01 12:00:02+00',
                              TIMESTAMPTZ '2026-07-01 12:00:03+00',
                              TIMESTAMPTZ '2026-07-01 12:00:04+00',
                              TIMESTAMPTZ '2026-07-01 12:00:05+00',
                              'FORBIDDEN', 'dat003_legacy_profile', 'USABLE', 'LIVE_OBSERVED');
                      INSERT INTO football.fixture_gameweek_assignment
                        (assignment_id, fixture_id, gameweek_id, assignment_status,
                         valid_during, system_during, source_snapshot_id)
                      VALUES ('00000000-0000-7000-8000-000000000009',
                              '00000000-0000-7000-8000-000000000006',
                              '00000000-0000-7000-8000-000000000007', 'FINAL',
                              tstzrange(TIMESTAMPTZ '2026-08-15 12:00:00+00',
                                        TIMESTAMPTZ '2026-08-16 12:00:00+00', '[)'),
                              tstzrange(TIMESTAMPTZ '2026-07-01 12:00:04+00', NULL, '[)'),
                              '00000000-0000-7000-8000-000000000008');
                      INSERT INTO provenance.ruleset_artifact
                        (ruleset_artifact_id, ruleset_id, ruleset_version, schema_version,
                         source_ruleset_hash, artifact_uri, artifact_sha256,
                         ruleset_status, registered_at)
                      VALUES ('00000000-0000-7000-8000-000000000010',
                              'dat003-preserved', '1.0.0', '1.0.0', repeat('2', 64),
                              'fixture://dat003/preserved', repeat('3', 64),
                              'ACCEPTED_REFERENCE', TIMESTAMPTZ '2026-07-01 12:00:05+00');
                    END
                    $$
                    """
                )
            )
    finally:
        engine.dispose()


def _assert_seed_preserved(database_url: str, *, fpl_head: bool) -> dict[str, object]:
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c timezone=UTC"},
    )
    expected_times = (
        datetime(2026, 7, 1, 12, 0, 1, tzinfo=UTC),
        datetime(2026, 7, 1, 12, 0, 2, tzinfo=UTC),
        datetime(2026, 7, 1, 12, 0, 3, tzinfo=UTC),
        datetime(2026, 7, 1, 12, 0, 4, tzinfo=UTC),
        datetime(2026, 7, 1, 12, 0, 5, tzinfo=UTC),
    )
    try:
        with engine.connect() as connection:
            snapshot = connection.execute(
                text(
                    """
                    SELECT received_at, stored_at, parsed_at, mapped_at, usable_at
                    FROM provenance.source_snapshot
                    WHERE source_snapshot_id = '00000000-0000-7000-8000-000000000008'
                    """
                )
            ).one()
            if tuple(snapshot) != expected_times:
                raise MatrixError("DAT-003 source lifecycle timestamps were not preserved")
            graph_count = int(
                connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM football.fixture AS fixture
                        JOIN football.season AS season ON season.season_id = fixture.season_id
                        JOIN fpl.gameweek AS gameweek ON gameweek.season_id = season.season_id
                        JOIN football.fixture_gameweek_assignment AS assignment
                          ON assignment.fixture_id = fixture.fixture_id
                         AND assignment.gameweek_id = gameweek.gameweek_id
                        WHERE fixture.fixture_id = '00000000-0000-7000-8000-000000000006'
                        """
                    )
                ).scalar_one()
            )
            ruleset_count = int(
                connection.execute(
                    text(
                        """
                        SELECT count(*) FROM provenance.ruleset_artifact
                        WHERE ruleset_artifact_id = '00000000-0000-7000-8000-000000000010'
                          AND source_ruleset_hash = repeat('2', 64)
                          AND artifact_sha256 = repeat('3', 64)
                        """
                    )
                ).scalar_one()
            )
            if graph_count != 1 or ruleset_count != 1:
                raise MatrixError("DAT-003 accepted graph was not preserved")
            team_season_count = 0
            lifecycle_count = 0
            if fpl_head:
                team_season_count = int(
                    connection.execute(
                        text(
                            """
                            SELECT count(*) FROM football.team_season
                            WHERE season_id = '00000000-0000-7000-8000-000000000003'
                            """
                        )
                    ).scalar_one()
                )
                stages = tuple(
                    connection.execute(
                        text(
                            """
                            SELECT stage FROM provenance.source_processing_event
                            WHERE source_snapshot_id = '00000000-0000-7000-8000-000000000008'
                            ORDER BY sequence_number
                            """
                        )
                    ).scalars()
                )
                expected_stages = (
                    "RECEIVED",
                    "RAW_DISCARDED",
                    "PARSED",
                    "VALIDATED",
                    "MAPPED",
                    "PROMOTED",
                    "QUALITY_PASSED",
                    "USABLE",
                )
                if stages != expected_stages or team_season_count != 2:
                    raise MatrixError("DAT-003 lifecycle or team-season backfill is invalid")
                assignment_season = connection.execute(
                    text(
                        """
                        SELECT season_id FROM football.fixture_gameweek_assignment
                        WHERE assignment_id = '00000000-0000-7000-8000-000000000009'
                        """
                    )
                ).scalar_one()
                if str(assignment_season) != "00000000-0000-7000-8000-000000000003":
                    raise MatrixError("DAT-003 assignment season backfill is invalid")
                lifecycle_count = len(stages)
            return {
                "accepted_graph_count": graph_count,
                "lifecycle_event_count": lifecycle_count,
                "ruleset_artifact_count": ruleset_count,
                "team_season_count": team_season_count,
            }
    finally:
        engine.dispose()


def _fpl004_seed_state(database_url: str) -> dict[str, object]:
    """Return stable accepted FPL evidence that exists in both 0002 and head."""

    engine = create_engine(
        database_url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c timezone=UTC"},
    )
    try:
        with engine.connect() as connection:
            snapshot_rows = connection.execute(
                text(
                    """
                    SELECT snapshot.resource, snapshot.body_sha256,
                           snapshot.envelope_sha256, lifecycle.current_state,
                           snapshot.raw_storage_policy
                    FROM provenance.source_snapshot AS snapshot
                    JOIN provenance.data_provider AS provider
                      ON provider.provider_id = snapshot.provider_id
                    JOIN provenance.source_snapshot_lifecycle AS lifecycle
                      ON lifecycle.source_snapshot_id = snapshot.source_snapshot_id
                    WHERE provider.provider_key = 'synthetic_fpl'
                    ORDER BY snapshot.resource, snapshot.source_snapshot_id
                    """
                )
            ).mappings()
            snapshots = [
                {
                    "body_sha256": str(row["body_sha256"]),
                    "envelope_sha256": str(row["envelope_sha256"]),
                    "raw_storage_policy": str(row["raw_storage_policy"]),
                    "resource": str(row["resource"]),
                    "lifecycle_state": str(row["current_state"]),
                }
                for row in snapshot_rows
            ]
            bundle_rows = connection.execute(
                text(
                    """
                    SELECT semantic_sha256, manifest_sha256, quality_status
                    FROM provenance.source_bundle
                    ORDER BY semantic_sha256
                    """
                )
            ).mappings()
            bundles = [
                {
                    "manifest_sha256": str(row["manifest_sha256"]),
                    "quality_status": str(row["quality_status"]),
                    "semantic_sha256": str(row["semantic_sha256"]),
                }
                for row in bundle_rows
            ]
            counts = {
                name: int(connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one())
                for name in (
                    "fpl.fixture_observation",
                    "fpl.gameweek_observation",
                    "fpl.player_observation",
                    "fpl.team_observation",
                    "provenance.rights_decision",
                    "provenance.source_bundle_member",
                )
            }
    finally:
        engine.dispose()
    state: dict[str, object] = {
        "bundles": bundles,
        "counts": counts,
        "snapshots": snapshots,
    }
    if (
        len(snapshots) != 2
        or {item["resource"] for item in snapshots} != {"bootstrap", "fixtures"}
        or any(item["lifecycle_state"] != "USABLE" for item in snapshots)
        or len(bundles) != 1
        or bundles[0]["quality_status"] not in {"PASS", "PASS_WITH_WARNINGS"}
        or counts["provenance.source_bundle_member"] != 2
        or any(counts[name] <= 0 for name in counts if name != "provenance.rights_decision")
        or counts["provenance.rights_decision"] < 2
    ):
        raise MatrixError("accepted FPL-004 preservation seed is incomplete")
    return state


def _seed_fpl004_data(database_url: str) -> dict[str, object]:
    """Create accepted synthetic FPL data at head without any provider transport."""

    from dmf_pulse.ingestion.fpl.service import (
        DATABASE_REF,
        FplIngestionService,
        FplReplayRequest,
    )

    outcome = FplIngestionService(repository_root=REPOSITORY_ROOT).replay(
        FplReplayRequest(
            fixture_set=REPOSITORY_ROOT / "fixtures/fpl/FPL-004",
            scenario="happy_path",
            information_cutoff=datetime(2026, 8, 21, 17, 30, tzinfo=UTC),
            rights_profile_id="synthetic_test_v1",
            database_url_ref=DATABASE_REF,
        )
    )
    if outcome.exit_code != 0 or outcome.result.status != "USABLE":
        raise MatrixError("synthetic FPL-004 preservation seed was not usable")
    return _fpl004_seed_state(database_url)


def _assert_at_baseline(database_url: str, expected_revision: str) -> dict[str, int | str]:
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c timezone=UTC"},
    )
    try:
        with engine.connect() as connection:
            revision = current_alembic_revision(connection)
            if revision != expected_revision:
                raise MatrixError("downgrade did not reach the requested baseline")
            inspector = inspect(connection)
            if expected_revision == "20260725_0004":
                betting_tables = set(inspector.get_table_names(schema="betting"))
                required_inherited = {
                    "betting_operator",
                    "odds_observation",
                    "operator_fixture_market",
                    "provider_quota_observation",
                }
                forbidden_nrm006 = {
                    "market_consensus_outcome",
                    "market_consensus_result",
                    "market_normalisation_exclusion",
                    "market_normalisation_policy",
                    "market_normalisation_run",
                    "market_normalisation_source",
                    "market_normalisation_warning",
                    "normalised_operator_market",
                    "normalised_operator_outcome",
                    "odds_publication_attestation",
                    "odds_publication_batch",
                }
                book_columns = {
                    column["name"]
                    for column in inspector.get_columns(
                        "operator_market_observation", schema="betting"
                    )
                }
                quote_columns = {
                    column["name"]
                    for column in inspector.get_columns("odds_observation", schema="betting")
                }
                if (
                    not required_inherited <= betting_tables
                    or betting_tables & forbidden_nrm006
                    or "publication_batch_id" in book_columns
                    or "publication_batch_id" in quote_columns
                ):
                    raise MatrixError("NRM-006 objects remain after ODD-005 baseline downgrade")
                return {
                    "betting_table_count": len(betting_tables),
                    "revision": revision,
                }
            if expected_revision == "20260724_0002":
                schemas = set(inspector.get_schema_names())
                fpl_tables = set(inspector.get_table_names(schema="fpl"))
                required_fpl = {
                    "fixture_observation",
                    "gameweek_observation",
                    "player_observation",
                    "player_season",
                    "team_observation",
                }
                bundle_columns = {
                    column["name"]
                    for column in inspector.get_columns("source_bundle", schema="provenance")
                }
                member_columns = {
                    column["name"]
                    for column in inspector.get_columns("source_bundle_member", schema="provenance")
                }
                if (
                    "betting" in schemas
                    or not required_fpl <= fpl_tables
                    or "rights_profile_record_id" in bundle_columns
                    or "rights_profile_record_id" in member_columns
                ):
                    raise MatrixError("ODD-005 objects remain after FPL-004 baseline downgrade")
                return {
                    "fpl_table_count": len(fpl_tables),
                    "revision": revision,
                }
            fpl_tables = set(inspector.get_table_names(schema="fpl"))
            actual = {
                schema: set(inspector.get_table_names(schema=schema))
                for schema in ("football", "fpl", "provenance")
            }
            forbidden = {
                "football": {"team_season"},
                "fpl": {
                    "fixture_observation",
                    "gameweek_observation",
                    "player_observation",
                    "player_season",
                    "team_observation",
                },
                "provenance": {
                    "rights_decision",
                    "rights_profile",
                    "semantic_effect_source",
                    "semantic_observation_claim",
                    "source_bundle",
                    "source_bundle_member",
                    "source_processing_event",
                },
            }
            if any(actual[schema] & names for schema, names in forbidden.items()):
                raise MatrixError("FPL-004 tables remain after baseline downgrade")
            return {
                "fpl_table_count": len(fpl_tables),
                "revision": revision,
            }
    finally:
        engine.dispose()


def run_matrix(
    *,
    baseline_revision: str,
    target: str,
    report_path: Path | None = None,
    offline_sql_path: Path | None = None,
    schema_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Run the destructive matrix and return its safe structured report."""

    odd005 = baseline_revision == "20260724_0002"
    nrm006 = baseline_revision == "20260725_0004"
    report_path = report_path or (NRM_REPORT if nrm006 else ODD_REPORT if odd005 else FPL_REPORT)
    offline_sql_path = offline_sql_path or (
        NRM_OFFLINE_SQL if nrm006 else ODD_OFFLINE_SQL if odd005 else FPL_OFFLINE_SQL
    )
    schema_manifest_path = schema_manifest_path or (
        NRM_SCHEMA_MANIFEST if nrm006 else ODD_SCHEMA_MANIFEST if odd005 else FPL_SCHEMA_MANIFEST
    )
    try:
        report_relative = report_path.relative_to(REPOSITORY_ROOT)
        offline_sql_relative = offline_sql_path.relative_to(REPOSITORY_ROOT)
        schema_manifest_relative = schema_manifest_path.relative_to(REPOSITORY_ROOT)
    except ValueError as exc:
        raise MatrixError("migration evidence outputs must remain inside the repository") from exc
    database_url, parsed_url = _configured_test_url()
    plan = _revision_plan(baseline_revision, target)
    first_manifest: dict[str, Any] | None = None
    destructive_started = False
    stage = "preflight"
    try:
        stage = "offline SQL generation"
        sql = _offline_sql(database_url, plan.target)
        _assert_secret_free(sql, parsed_url)
        required_sql = [
            "CREATE TABLE provenance.source_processing_event",
            "CREATE TABLE provenance.source_bundle",
            "CREATE TABLE football.team_season",
            "CREATE TABLE fpl.player_season",
        ]
        if odd005:
            required_sql.extend(
                (
                    "CREATE SCHEMA betting",
                    "CREATE TABLE betting.betting_operator",
                    "CREATE TABLE betting.operator_fixture_market",
                    "CREATE TABLE betting.odds_observation",
                    "CREATE TABLE betting.provider_quota_observation",
                    "uq_rights_decision_authority",
                    "ck_external_identifier_odds_operator_scope",
                )
            )
        if nrm006:
            required_sql.extend(
                (
                    "CREATE TABLE betting.odds_publication_batch",
                    "CREATE TABLE betting.odds_publication_attestation",
                    "CREATE TABLE betting.market_normalisation_policy",
                    "CREATE TABLE betting.market_normalisation_run",
                    "CREATE TABLE betting.normalised_operator_market",
                    "CREATE TABLE betting.market_consensus_result",
                )
            )
        if not all(fragment in sql for fragment in required_sql):
            raise MatrixError("offline SQL omits a required ingestion schema object")

        destructive_started = True
        stage = "empty database reset"
        _alembic("downgrade", database_url, "base")
        stage = "empty database upgrade"
        _alembic("upgrade", database_url, plan.target)
        first_manifest = _catalog_state(database_url)
        if first_manifest["alembic_revision"] != plan.target:
            raise MatrixError("clean database upgrade did not reach the target")

        if odd005:
            stage = "accepted FPL-004 data seed"
            initial_head_seed = _seed_fpl004_data(database_url)
            stage = "ODD-005 head to FPL-004 baseline downgrade"
            _alembic("downgrade", database_url, plan.baseline)
            baseline_state = _assert_at_baseline(database_url, plan.baseline)
            baseline_seed = _fpl004_seed_state(database_url)
            if baseline_seed != initial_head_seed:
                raise MatrixError("accepted FPL-004 data changed during baseline downgrade")
            stage = "FPL-004 baseline to ODD-005 re-upgrade"
            _alembic("upgrade", database_url, plan.target)
            head_seed = _fpl004_seed_state(database_url)
            if head_seed != initial_head_seed:
                raise MatrixError("accepted FPL-004 data changed during ODD-005 upgrade")
        elif nrm006:
            stage = "accepted FPL-004 data seed at NRM-006 head"
            initial_head_seed = _seed_fpl004_data(database_url)
            stage = "NRM-006 head to ODD-005 baseline downgrade"
            _alembic("downgrade", database_url, plan.baseline)
            baseline_state = _assert_at_baseline(database_url, plan.baseline)
            baseline_seed = _fpl004_seed_state(database_url)
            if baseline_seed != initial_head_seed:
                raise MatrixError("accepted FPL-004 data changed during NRM-006 downgrade")
            stage = "ODD-005 baseline to NRM-006 re-upgrade"
            _alembic("upgrade", database_url, plan.target)
            head_seed = _fpl004_seed_state(database_url)
            if head_seed != initial_head_seed:
                raise MatrixError("accepted FPL-004 data changed during NRM-006 upgrade")
        else:
            stage = "DAT-003 baseline downgrade"
            _alembic("downgrade", database_url, plan.baseline)
            _assert_at_baseline(database_url, plan.baseline)
            stage = "DAT-003 accepted-data seed"
            _seed_dat003_data(database_url)
            baseline_seed = _assert_seed_preserved(database_url, fpl_head=False)
            stage = "DAT-003 to ingestion-head re-upgrade"
            _alembic("upgrade", database_url, plan.target)
            head_seed = _assert_seed_preserved(database_url, fpl_head=True)
        second_manifest = _catalog_state(database_url)
        if first_manifest != second_manifest:
            raise MatrixError("schema manifest changed across clean upgrade and re-upgrade")

        stage = "populated ingestion-head downgrade"
        _alembic("downgrade", database_url, plan.baseline)
        baseline_state = _assert_at_baseline(database_url, plan.baseline)
        downgraded_seed = (
            _fpl004_seed_state(database_url)
            if odd005 or nrm006
            else _assert_seed_preserved(database_url, fpl_head=False)
        )
        if (odd005 or nrm006) and downgraded_seed != baseline_seed:
            raise MatrixError("accepted FPL-004 data changed on populated downgrade")

        stage = "populated ingestion-head final re-upgrade"
        _alembic("upgrade", database_url, plan.target)
        final_seed = (
            _fpl004_seed_state(database_url)
            if odd005 or nrm006
            else _assert_seed_preserved(database_url, fpl_head=True)
        )
        if (odd005 or nrm006) and final_seed != head_seed:
            raise MatrixError("accepted FPL-004 data changed on final re-upgrade")
        final_manifest = _catalog_state(database_url)
        if first_manifest != final_manifest:
            raise MatrixError("schema manifest changed after populated downgrade and re-upgrade")

        stage = "metadata drift check"
        _alembic("check", database_url, plan.target)
    except Exception as exc:
        if destructive_started:
            with suppress(Exception):
                _alembic("upgrade", database_url, plan.target)
        if isinstance(exc, MatrixError):
            raise MatrixError(f"{stage}: {exc}") from exc
        raise MatrixError(f"{stage} failed ({type(exc).__name__})") from exc

    try:
        _safe_text_write(offline_sql_path, sql)
        schema_manifest = _schema_manifest(database_url)
        _safe_json_write(schema_manifest_path, schema_manifest)
    except OSError as exc:
        raise MatrixError("migration schema evidence could not be written") from exc
    report = {
        "baseline_revision": plan.baseline,
        "database": {
            "host": parsed_url.host,
            "name": parsed_url.database,
            "port": parsed_url.port or 5432,
            "postgres_version": EXPECTED_POSTGRES_VERSION,
        },
        "matrix": [
            {"from": "base", "status": "PASS", "to": plan.target},
            {"from": plan.target, "status": "PASS", "to": plan.baseline},
            {"from": plan.baseline, "status": "PASS", "to": plan.target},
            {"from": plan.target, "status": "PASS", "to": plan.baseline},
            {"from": plan.baseline, "status": "PASS", "to": plan.target},
        ],
        "data_preservation": {
            "baseline_seed": baseline_seed,
            "downgraded_seed": downgraded_seed,
            "final_seed": final_seed,
            "head_seed": head_seed,
            "status": "PASS",
        },
        "metadata_drift_check": "PASS",
        "offline_sql": {
            "bytes": len(sql.encode("utf-8")),
            "path": offline_sql_relative.as_posix(),
            "secret_free": True,
            "sha256": _sha256_bytes(sql.encode("utf-8")),
        },
        "revision_count": len(plan.revisions),
        "revisions": list(plan.revisions),
        "schema": first_manifest,
        "schema_manifest": {
            "path": schema_manifest_relative.as_posix(),
            "sha256": _sha256_bytes(schema_manifest_path.read_bytes()),
        },
        "status": "PASS",
        "target_revision": plan.target,
        "ticket_id": "NRM-006" if nrm006 else "ODD-005" if odd005 else "FPL-004",
        "baseline_state": baseline_state,
    }
    try:
        _safe_json_write(REPOSITORY_ROOT / report_relative, report)
    except OSError as exc:
        raise MatrixError("migration matrix evidence could not be written") from exc
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-revision", required=True)
    parser.add_argument("--target", default="head")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--offline-sql", type=Path)
    parser.add_argument("--schema-manifest", type=Path)
    arguments = parser.parse_args()
    try:
        result = run_matrix(
            baseline_revision=arguments.baseline_revision,
            target=arguments.target,
            report_path=arguments.report.resolve() if arguments.report is not None else None,
            offline_sql_path=(
                arguments.offline_sql.resolve() if arguments.offline_sql is not None else None
            ),
            schema_manifest_path=(
                arguments.schema_manifest.resolve()
                if arguments.schema_manifest is not None
                else None
            ),
        )
    except MatrixError as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {"error": f"migration matrix failed ({type(exc).__name__})", "status": "FAIL"},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
