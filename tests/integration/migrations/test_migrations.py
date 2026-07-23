"""Alembic reversibility and exact PostgreSQL catalog acceptance."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from dmf_pulse.data_model.tables import metadata
from dmf_pulse.database.doctor import build_database_doctor
from dmf_pulse.database.errors import DatabaseError
from dmf_pulse.database.migrate import (
    alembic_config,
    downgrade_database,
    head_revision,
    upgrade_database,
)
from dmf_pulse.database.schema import inspect_schema

pytestmark = pytest.mark.migration
EXPECTED_SCHEMA_SHA256 = "b85e36bbc457054125df884b0ed107591a93182f20e6308fe1b9cb3d7a9bf7ea"


def _catalog_names(manifest: object) -> tuple[set[str], set[str]]:
    schemas = manifest.schemas  # type: ignore[attr-defined]
    tables = {f"{schema}.{table}" for schema, value in schemas.items() for table in value["tables"]}
    views = {f"{schema}.{view}" for schema, value in schemas.items() for view in value["views"]}
    return tables, views


def test_catalog_matches_expected_schema_and_is_deterministic(
    postgres_engine: Engine, repository_root: Path, postgres_url: str
) -> None:
    expected = json.loads(
        (repository_root / "fixtures/data_model/DAT-003/expected_schema.json").read_text(
            encoding="utf-8"
        )
    )
    with postgres_engine.connect() as connection:
        first = inspect_schema(connection)
        second = inspect_schema(connection)
    tables, views = _catalog_names(first)
    assert tables == set(expected["tables"])
    assert views == set(expected["views"])
    assert set(first.extensions) == set(expected["extensions"])
    assert first.schema_sha256 == second.schema_sha256
    assert first.schema_sha256 == EXPECTED_SCHEMA_SHA256
    assert first.alembic_revision == head_revision() == "20260723_0001"

    function_names = {
        f"{schema}.{function['name']}"
        for schema, value in first.schemas.items()
        for function in value["functions"]
    }
    assert function_names == {
        "core.guard_canonical_successor",
        "core.guard_temporal_version",
        "core.is_canonical_tstzrange",
        "provenance.reject_immutable_change",
    }
    trigger_names = {
        trigger["name"] for value in first.schemas.values() for trigger in value["triggers"]
    }
    assert trigger_names == {
        "trg_canonical_entity_successor",
        "trg_entity_alias_temporal",
        "trg_external_identifier_temporal",
        "trg_fixture_gameweek_assignment_temporal",
        "trg_fixture_revision_temporal",
        "trg_player_team_membership_temporal",
        "trg_raw_blob_deletion_immutable",
        "trg_raw_blob_immutable",
        "trg_ruleset_activation_immutable",
        "trg_ruleset_artifact_immutable",
        "trg_source_snapshot_immutable",
    }
    exclusions = [
        constraint
        for value in first.schemas.values()
        for table in value["tables"].values()
        for constraint in table["constraints"]
        if constraint["kind"] == "EXCLUSION"
    ]
    assert len(exclusions) == 5
    assert all(item["deferrable"] is True for item in exclusions)
    assert all(item["initially_deferred"] is False for item in exclusions)

    for table in metadata.sorted_tables:
        schema_name = table.schema or "public"
        declared = first.schemas[schema_name]["tables"][table.name]
        assert [column["name"] for column in declared["columns"]] == [
            column.name for column in table.columns
        ]
        assert {
            constraint["name"]
            for constraint in declared["constraints"]
            if constraint["kind"] != "n"
        } == {constraint.name for constraint in table.constraints}
        assert {index.name for index in table.indexes} <= {
            index["name"] for index in declared["indexes"]
        }

    doctor = build_database_doctor(postgres_engine, postgres_url)
    assert doctor.status == "HEALTHY"
    assert doctor.postgres.major == 18
    assert set(doctor.capabilities) == set(expected["required_capabilities"])
    assert all(doctor.capabilities.values())


def test_single_linear_revision_and_secret_free_offline_sql(postgres_url: str) -> None:
    revisions = list(ScriptDirectory.from_config(alembic_config()).walk_revisions())
    assert [(revision.revision, revision.down_revision) for revision in revisions] == [
        ("20260723_0001", None)
    ]
    output = io.StringIO()
    with redirect_stdout(output):
        command.upgrade(alembic_config(postgres_url), "head", sql=True)
    sql = output.getvalue()
    assert "CREATE SCHEMA core" in sql
    assert "CREATE TABLE football.player_team_membership" in sql
    assert all(value not in sql for value in ("changeme", "dmf_test_password"))
    assert "postgresql+psycopg" not in sql


def test_alembic_metadata_drift_check_is_clean(postgres_url: str) -> None:
    command.check(alembic_config(postgres_url))


def test_doctor_detects_a_disabled_critical_trigger(
    postgres_engine: Engine, postgres_url: str
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE provenance.raw_blob DISABLE TRIGGER trg_raw_blob_immutable")
        )
    try:
        doctor = build_database_doctor(postgres_engine, postgres_url)
        assert doctor.status == "DEGRADED"
        assert doctor.capabilities["immutable_point_observations"] is False
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE provenance.raw_blob ENABLE TRIGGER trg_raw_blob_immutable")
            )


def test_clean_downgrade_and_reupgrade(postgres_engine: Engine, postgres_url: str) -> None:
    postgres_engine.dispose()
    downgrade_database(postgres_url)
    with postgres_engine.connect() as connection:
        remaining = connection.execute(
            text(
                "SELECT count(*) FROM information_schema.schemata "
                "WHERE schema_name IN ('core','football','fpl','provenance')"
            )
        ).scalar_one()
    assert remaining == 0
    with pytest.raises(DatabaseError) as behind:
        build_database_doctor(postgres_engine, postgres_url)
    assert behind.value.code == "DATABASE_SCHEMA_BEHIND"
    postgres_engine.dispose()
    upgrade_database(postgres_url)
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT uuidv7() IS NOT NULL")).scalar_one() is True
        assert inspect_schema(connection).alembic_revision == "20260723_0001"
