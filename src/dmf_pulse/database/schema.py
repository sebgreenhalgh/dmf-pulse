"""Deterministic PostgreSQL catalog inspection and canonical schema hashing."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Connection, text

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.database.errors import DatabaseError
from dmf_pulse.database.models import SchemaManifest

REQUIRED_SCHEMAS = ("core", "football", "fpl", "provenance")
SPACE = re.compile(r"\s+")


def _normalized(value: object) -> str | None:
    if value is None:
        return None
    return SPACE.sub(" ", str(value)).strip()


def _rows(connection: Connection, query: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(text(query)).mappings()]


def current_alembic_revision(connection: Connection) -> str | None:
    exists = bool(
        connection.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar_one()
    )
    if not exists:
        return None
    value = connection.execute(
        text("SELECT version_num FROM public.alembic_version")
    ).scalar_one_or_none()
    return str(value) if value is not None else None


def inspect_schema(connection: Connection) -> SchemaManifest:
    version = str(connection.execute(text("SHOW server_version")).scalar_one())
    revision = current_alembic_revision(connection)
    if revision is None:
        raise DatabaseError("DATABASE_SCHEMA_BEHIND", "database migration is not at head")
    extensions = tuple(
        row["extname"]
        for row in _rows(
            connection,
            "SELECT extname FROM pg_extension WHERE extname = 'btree_gist' ORDER BY extname",
        )
    )
    schemas: dict[str, dict[str, Any]] = {
        name: {"functions": [], "tables": {}, "triggers": [], "views": {}}
        for name in REQUIRED_SCHEMAS
    }
    schema_filter = "'core','football','fpl','provenance'"
    columns = _rows(
        connection,
        f"""
        SELECT columns_record.table_schema, columns_record.table_name,
               columns_record.ordinal_position, columns_record.column_name,
               columns_record.data_type, columns_record.udt_schema, columns_record.udt_name,
               columns_record.is_nullable, columns_record.column_default
        FROM information_schema.columns AS columns_record
        JOIN information_schema.tables AS tables_record
          ON tables_record.table_schema = columns_record.table_schema
         AND tables_record.table_name = columns_record.table_name
         AND tables_record.table_type = 'BASE TABLE'
        WHERE columns_record.table_schema IN ({schema_filter})
        ORDER BY columns_record.table_schema, columns_record.table_name,
                 columns_record.ordinal_position
        """,
    )
    for row in columns:
        schema = schemas[str(row["table_schema"])]
        table_name = str(row["table_name"])
        table = schema["tables"].setdefault(
            table_name, {"columns": [], "constraints": [], "indexes": []}
        )
        table["columns"].append(
            {
                "default": _normalized(row["column_default"]),
                "name": row["column_name"],
                "nullable": row["is_nullable"] == "YES",
                "ordinal": row["ordinal_position"],
                "type": row["data_type"],
                "udt": f"{row['udt_schema']}.{row['udt_name']}",
            }
        )
    constraints = _rows(
        connection,
        f"""
        SELECT namespace.nspname AS table_schema, relation.relname AS table_name,
               constraint_record.conname AS name,
               CASE constraint_record.contype
                 WHEN 'p' THEN 'PRIMARY_KEY' WHEN 'f' THEN 'FOREIGN_KEY'
                 WHEN 'u' THEN 'UNIQUE' WHEN 'c' THEN 'CHECK'
                 WHEN 'x' THEN 'EXCLUSION' ELSE constraint_record.contype::text
               END AS kind,
               pg_get_constraintdef(constraint_record.oid, true) AS definition,
               constraint_record.condeferrable AS deferrable,
               constraint_record.condeferred AS initially_deferred
        FROM pg_constraint AS constraint_record
        JOIN pg_class AS relation ON relation.oid = constraint_record.conrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname IN ({schema_filter})
        ORDER BY namespace.nspname, relation.relname, constraint_record.conname
        """,
    )
    for row in constraints:
        table = schemas[str(row["table_schema"])]["tables"][str(row["table_name"])]
        table["constraints"].append(
            {
                "deferrable": row["deferrable"],
                "definition": _normalized(row["definition"]),
                "initially_deferred": row["initially_deferred"],
                "kind": row["kind"],
                "name": row["name"],
            }
        )
    indexes = _rows(
        connection,
        f"""
        SELECT schemaname AS table_schema, tablename AS table_name,
               indexname AS name, indexdef AS definition
        FROM pg_indexes
        WHERE schemaname IN ({schema_filter})
        ORDER BY schemaname, tablename, indexname
        """,
    )
    for row in indexes:
        table = schemas[str(row["table_schema"])]["tables"][str(row["table_name"])]
        table["indexes"].append({"definition": _normalized(row["definition"]), "name": row["name"]})
    views = _rows(
        connection,
        f"""
        SELECT schemaname AS table_schema, viewname AS name,
               pg_get_viewdef(format('%I.%I', schemaname, viewname)::regclass, true) AS definition
        FROM pg_views
        WHERE schemaname IN ({schema_filter})
        ORDER BY schemaname, viewname
        """,
    )
    for row in views:
        schemas[str(row["table_schema"])]["views"][str(row["name"])] = _normalized(
            row["definition"]
        )
    functions = _rows(
        connection,
        f"""
        SELECT namespace.nspname AS table_schema, procedure.proname AS name,
               pg_get_function_identity_arguments(procedure.oid) AS arguments,
               pg_get_functiondef(procedure.oid) AS definition
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname IN ({schema_filter})
          AND NOT EXISTS (
            SELECT 1 FROM pg_depend AS dependency
            JOIN pg_extension AS extension ON extension.oid = dependency.refobjid
            WHERE dependency.classid = 'pg_proc'::regclass
              AND dependency.objid = procedure.oid
              AND dependency.deptype = 'e'
          )
        ORDER BY namespace.nspname, procedure.proname,
                 pg_get_function_identity_arguments(procedure.oid)
        """,
    )
    for row in functions:
        schemas[str(row["table_schema"])]["functions"].append(
            {
                "arguments": _normalized(row["arguments"]),
                "definition": _normalized(row["definition"]),
                "name": row["name"],
            }
        )
    triggers = _rows(
        connection,
        f"""
        SELECT namespace.nspname AS table_schema, relation.relname AS table_name,
               trigger_record.tgname AS name,
               trigger_record.tgenabled AS enabled,
               pg_get_triggerdef(trigger_record.oid, true) AS definition
        FROM pg_trigger AS trigger_record
        JOIN pg_class AS relation ON relation.oid = trigger_record.tgrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname IN ({schema_filter}) AND NOT trigger_record.tgisinternal
        ORDER BY namespace.nspname, relation.relname, trigger_record.tgname
        """,
    )
    for row in triggers:
        schemas[str(row["table_schema"])]["triggers"].append(
            {
                "definition": _normalized(row["definition"]),
                "enabled": row["enabled"],
                "name": row["name"],
                "table": row["table_name"],
            }
        )
    body: dict[str, Any] = {
        "alembic_revision": revision,
        "extensions": extensions,
        "postgres_version": version,
        "schemas": schemas,
    }
    # Runtime and deployment metadata remain useful evidence, but they are not part of
    # the semantic database contract.  A PostgreSQL patch upgrade or a migration-label
    # change must not alter the schema fingerprint when the inspected objects are
    # otherwise identical.
    semantic_schemas: dict[str, dict[str, Any]] = {}
    for schema_name, schema in schemas.items():
        semantic_tables: dict[str, dict[str, Any]] = {}
        for table_name, table in schema["tables"].items():
            semantic_tables[table_name] = {
                **table,
                "columns": sorted(
                    (
                        {key: value for key, value in column.items() if key != "ordinal"}
                        for column in table["columns"]
                    ),
                    key=lambda column: str(column["name"]),
                ),
            }
        semantic_schemas[schema_name] = {**schema, "tables": semantic_tables}
    semantic_body = {"extensions": extensions, "schemas": semantic_schemas}
    return SchemaManifest.model_validate({**body, "schema_sha256": canonical_sha256(semantic_body)})
