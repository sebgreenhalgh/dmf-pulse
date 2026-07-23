"""PostgreSQL 18, migration, capability, and schema diagnostics."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from dmf_pulse.database.engine import database_location
from dmf_pulse.database.errors import DatabaseError
from dmf_pulse.database.migrate import head_revision
from dmf_pulse.database.models import DatabaseDoctorResult, PostgresStatus, SchemaManifest
from dmf_pulse.database.schema import current_alembic_revision, inspect_schema

TEMPORAL_TABLES = {
    "core": {"entity_alias", "external_identifier"},
    "football": {
        "fixture_gameweek_assignment",
        "fixture_revision",
        "player_team_membership",
    },
}
TEMPORAL_TRIGGERS = {
    "trg_entity_alias_temporal": ("core", "entity_alias"),
    "trg_external_identifier_temporal": ("core", "external_identifier"),
    "trg_fixture_gameweek_assignment_temporal": (
        "football",
        "fixture_gameweek_assignment",
    ),
    "trg_fixture_revision_temporal": ("football", "fixture_revision"),
    "trg_player_team_membership_temporal": ("football", "player_team_membership"),
}
IMMUTABLE_TRIGGERS = {
    "trg_raw_blob_deletion_immutable": ("provenance", "raw_blob_deletion"),
    "trg_raw_blob_immutable": ("provenance", "raw_blob"),
    "trg_ruleset_activation_immutable": ("provenance", "ruleset_activation"),
    "trg_ruleset_artifact_immutable": ("provenance", "ruleset_artifact"),
    "trg_source_snapshot_immutable": ("provenance", "source_snapshot"),
}


def _capabilities(manifest: SchemaManifest, *, uuidv7: bool) -> dict[str, bool]:
    function_names = {
        f"{schema}.{function['name']}"
        for schema, value in manifest.schemas.items()
        for function in value["functions"]
    }
    enabled_triggers = {
        trigger["name"]: (schema, trigger["table"], str(trigger["definition"]))
        for schema, value in manifest.schemas.items()
        for trigger in value["triggers"]
        if trigger.get("enabled") in {"O", "A"}
    }

    def expected_triggers(expected: dict[str, tuple[str, str]], function_name: str) -> bool:
        return all(
            name in enabled_triggers
            and enabled_triggers[name][:2] == location
            and function_name in enabled_triggers[name][2]
            for name, location in expected.items()
        )

    temporal_columns_valid = True
    exclusions = 0
    for schema, tables in TEMPORAL_TABLES.items():
        for table_name in tables:
            table = manifest.schemas.get(schema, {}).get("tables", {}).get(table_name)
            if not isinstance(table, dict):
                temporal_columns_valid = False
                continue
            columns = {column["name"]: column for column in table["columns"]}
            temporal_columns_valid = temporal_columns_valid and all(
                columns.get(name, {}).get("udt") == "pg_catalog.tstzrange"
                for name in ("valid_during", "system_during")
            )
            exclusions += sum(
                constraint["kind"] == "EXCLUSION" and constraint["deferrable"] is True
                for constraint in table["constraints"]
            )
    return {
        "controlled_supersession": (
            "core.guard_temporal_version" in function_names
            and expected_triggers(TEMPORAL_TRIGGERS, "guard_temporal_version")
        ),
        "gist_exclusion": "btree_gist" in manifest.extensions and exclusions == 5,
        "immutable_point_observations": (
            "provenance.reject_immutable_change" in function_names
            and expected_triggers(IMMUTABLE_TRIGGERS, "reject_immutable_change")
        ),
        "tstzrange": temporal_columns_valid,
        "uuidv7": uuidv7,
    }


def build_database_doctor(engine: Engine, database_url: str) -> DatabaseDoctorResult:
    location = database_location(database_url)
    try:
        with engine.connect() as connection:
            version = str(connection.execute(text("SHOW server_version")).scalar_one())
            version_number = int(connection.execute(text("SHOW server_version_num")).scalar_one())
            major = version_number // 10000
            if major != 18:
                raise DatabaseError(
                    "DATABASE_VERSION_UNSUPPORTED", "PostgreSQL major 18 is required"
                )
            head = head_revision()
            current = current_alembic_revision(connection)
            if current != head:
                raise DatabaseError("DATABASE_SCHEMA_BEHIND", "database migration is not at head")
            manifest = inspect_schema(connection)
            generated = UUID(str(connection.execute(text("SELECT uuidv7()")).scalar_one()))
            capabilities = _capabilities(manifest, uuidv7=generated.version == 7)
            status: Literal["HEALTHY", "DEGRADED"] = (
                "HEALTHY" if all(capabilities.values()) else "DEGRADED"
            )
            return DatabaseDoctorResult(
                status=status,
                database=location,
                postgres=PostgresStatus(version=version, major=18, supported=True),
                migration={"current": current, "head": head, "at_head": current == head},
                capabilities=capabilities,
                schema_sha256=manifest.schema_sha256,
            )
    except DatabaseError:
        raise
    except (SQLAlchemyError, OSError, ValueError, TypeError) as exc:
        raise DatabaseError("DATABASE_UNAVAILABLE", "database diagnostic failed") from exc
