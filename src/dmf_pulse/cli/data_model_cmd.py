"""Typer commands for the explicit DAT-003 PostgreSQL boundary."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from dmf_pulse.data_model.models import AsOfResult, DemoResult
from dmf_pulse.data_model.services import run_as_of, run_demo
from dmf_pulse.database.doctor import build_database_doctor
from dmf_pulse.database.engine import (
    create_database_engine,
    resolve_test_database_url,
    session_factory,
)
from dmf_pulse.database.errors import DatabaseError
from dmf_pulse.database.models import DatabaseDoctorResult, DatabaseSettings, SchemaManifest
from dmf_pulse.database.schema import inspect_schema

data_model_app = typer.Typer(
    help="Inspect and exercise the canonical temporal PostgreSQL foundation."
)


def _runtime() -> tuple[Engine, str]:
    environment = os.environ.get("DMF_ENVIRONMENT", "")
    url = resolve_test_database_url(environment=environment)
    settings = DatabaseSettings(
        url_secret_ref="env:DMF_TEST_DATABASE_URL",
        connect_timeout_seconds=5,
        application_name="dmf-pulse-dat003",
    )
    return create_database_engine(url, settings), url


def _run[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except DatabaseError as exc:
        typer.echo(json.dumps(exc.as_error_object(), sort_keys=True), err=True)
        raise typer.Exit(exc.exit_code) from exc
    except SQLAlchemyError as exc:
        error = DatabaseError("DATABASE_UNAVAILABLE", "database operation failed")
        typer.echo(json.dumps(error.as_error_object(), sort_keys=True), err=True)
        raise typer.Exit(error.exit_code) from exc
    except Exception as exc:  # pragma: no cover - final secret-safe CLI boundary
        error = DatabaseError("DATABASE_INTERNAL_ERROR", "data-model command failed safely")
        typer.echo(json.dumps(error.as_error_object(), sort_keys=True), err=True)
        raise typer.Exit(1) from exc


def _emit(value: BaseModel | Mapping[str, object], *, as_json: bool, human: str) -> None:
    if as_json:
        data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        typer.echo(json.dumps(data, allow_nan=False, ensure_ascii=False, sort_keys=True))
    else:
        typer.echo(human)


@data_model_app.command("doctor")
def doctor_command(
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    """Check PostgreSQL version, migration, capabilities, and schema."""

    def operation() -> DatabaseDoctorResult:
        engine, url = _runtime()
        try:
            return build_database_doctor(engine, url)
        finally:
            engine.dispose()

    result = _run(operation)
    _emit(result, as_json=as_json, human=f"Database: {result.status}")


@data_model_app.command("schema-manifest")
def schema_manifest_command(
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    """Emit the canonical nonvolatile PostgreSQL schema manifest."""

    def operation() -> SchemaManifest:
        engine, _ = _runtime()
        try:
            with engine.connect() as connection:
                return inspect_schema(connection)
        finally:
            engine.dispose()

    result = _run(operation)
    _emit(
        result,
        as_json=as_json,
        human=f"Schema {result.alembic_revision}: {result.schema_sha256}",
    )


@data_model_app.command("demo")
def demo_command(
    fixture: Annotated[Path, typer.Option("--fixture", help="Synthetic demo fixture JSON.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    """Execute the synthetic persistence demonstration in rollback mode."""

    def operation() -> DemoResult:
        engine, _ = _runtime()
        try:
            return run_demo(session_factory(engine), fixture)
        finally:
            engine.dispose()

    result = _run(operation)
    _emit(result, as_json=as_json, human=f"Fixture {result.fixture_id}: all assertions passed")


@data_model_app.command("as-of")
def as_of_command(
    fixture: Annotated[Path, typer.Option("--fixture", help="As-of query fixture JSON.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    """Run declared valid-time/system-known-time fixture queries in rollback mode."""

    def operation() -> AsOfResult:
        engine, _ = _runtime()
        try:
            return run_as_of(session_factory(engine), fixture)
        finally:
            engine.dispose()

    result = _run(operation)
    _emit(result, as_json=as_json, human=f"Fixture {result.fixture_id}: all queries passed")
