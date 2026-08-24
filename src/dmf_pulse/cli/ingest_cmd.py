"""Typer surface for the rights-gated FPL-004 ingestion vertical slice."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, NoReturn
from uuid import UUID

import typer
from pydantic import BaseModel, ValidationError

from dmf_pulse.cli.odds_cmd import odds_app
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplInputRequest,
    CurrentFplInputService,
    CurrentFplInputSummary,
)
from dmf_pulse.ingestion.fpl.parser import (
    CONTRACT_VERSION,
    FplResource,
    parse_rfc3339_timestamp,
)
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    DEFAULT_INFORMATION_CUTOFF,
    FplImportRequest,
    FplIngestionService,
    FplOperationOutcome,
    FplReplayRequest,
)

ingest_app = typer.Typer(help="Run explicitly rights-gated ingestion operations.")
fpl_app = typer.Typer(help="Validate and ingest frozen FPL reference payloads.")
bundle_app = typer.Typer(help="Inspect immutable FPL source bundles.")
current_app = typer.Typer(help="Compile manual current FPL files without network or storage.")
ingest_app.add_typer(fpl_app, name="fpl")
ingest_app.add_typer(odds_app, name="odds")
fpl_app.add_typer(bundle_app, name="bundle")
fpl_app.add_typer(current_app, name="current")


def _json(value: BaseModel | dict[str, object]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(payload, allow_nan=False, ensure_ascii=False, sort_keys=True)


def _require_json(output: str) -> None:
    if output != "json":
        raise IngestionError("USAGE_INVALID", "--output must be json")


def _timestamp(value: str, *, option: str) -> datetime:
    try:
        parsed = parse_rfc3339_timestamp(value)
    except ValueError as exc:
        raise IngestionError("USAGE_INVALID", f"{option} must be an RFC3339 timestamp") from exc
    return parsed.astimezone(UTC)


def _failure(error: IngestionError) -> NoReturn:
    typer.echo(_json(error.as_error_object()))
    raise typer.Exit(error.exit_code)


def _emit_outcome(outcome: FplOperationOutcome) -> None:
    typer.echo(_json(outcome.result))
    if outcome.exit_code:
        raise typer.Exit(outcome.exit_code)


def _safe(operation: Callable[[], object]) -> object:
    try:
        return operation()
    except IngestionError as exc:
        _failure(exc)
    except Exception as exc:  # pragma: no cover - final secret-safe boundary
        error = IngestionError("INTERNAL_INVARIANT", "ingestion command failed safely")
        typer.echo(_json(error.as_error_object()))
        raise typer.Exit(error.exit_code) from exc


@current_app.command("validate")
def current_validate_command(
    bootstrap: Annotated[Path, typer.Option("--bootstrap")],
    fixtures: Annotated[Path, typer.Option("--fixtures")],
    competition_key: Annotated[str, typer.Option("--competition-key")],
    season_code: Annotated[str, typer.Option("--season-code")],
    captured_at: Annotated[str, typer.Option("--captured-at")],
    information_cutoff: Annotated[str, typer.Option("--information-cutoff")],
    rights_profile: Annotated[str, typer.Option("--rights-profile")],
    gameweek: Annotated[int, typer.Option("--gameweek")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Compile a private manual bootstrap/fixtures pair and emit only its safe summary."""

    def operation() -> CurrentFplInputSummary:
        _require_json(output)
        try:
            request = CurrentFplInputRequest(
                bootstrap_path=bootstrap,
                fixtures_path=fixtures,
                competition_key=competition_key,
                season_code=season_code,
                target_gameweek=gameweek,
                captured_at=_timestamp(captured_at, option="--captured-at"),
                information_cutoff=_timestamp(information_cutoff, option="--information-cutoff"),
                rights_profile_id=rights_profile,
            )
        except ValidationError as exc:
            raise IngestionError("USAGE_INVALID", "current FPL arguments are invalid") from exc
        return CurrentFplInputService().compile(request).safe_summary()

    result = _safe(operation)
    if not isinstance(result, CurrentFplInputSummary):
        _failure(IngestionError("INTERNAL_INVARIANT", "current FPL summary is invalid"))
    typer.echo(_json(result))


@fpl_app.command("validate")
def validate_command(
    resource: Annotated[FplResource, typer.Option("--resource")],
    input_path: Annotated[Path, typer.Option("--input")],
    contract_version: Annotated[str, typer.Option("--contract-version")] = CONTRACT_VERSION,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Parse one payload without a database or network boundary."""

    def operation() -> BaseModel:
        _require_json(output)
        return FplIngestionService().validate(
            resource, input_path, contract_version=contract_version
        )

    result = _safe(operation)
    if not isinstance(result, BaseModel):
        _failure(IngestionError("INTERNAL_INVARIANT", "validation result is invalid"))
    typer.echo(_json(result))


@fpl_app.command("import")
def import_command(
    bootstrap: Annotated[Path, typer.Option("--bootstrap")],
    fixtures: Annotated[Path, typer.Option("--fixtures")],
    competition_key: Annotated[str, typer.Option("--competition-key")],
    season_code: Annotated[str, typer.Option("--season-code")],
    captured_at: Annotated[str, typer.Option("--captured-at")],
    information_cutoff: Annotated[str, typer.Option("--information-cutoff")],
    rights_profile: Annotated[str, typer.Option("--rights-profile")],
    database_url_ref: Annotated[str, typer.Option("--database-url-ref")] = DATABASE_REF,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Import a governed bootstrap/fixtures pair."""

    def operation() -> FplOperationOutcome:
        _require_json(output)
        return FplIngestionService().import_pair(
            FplImportRequest(
                bootstrap_path=bootstrap,
                fixtures_path=fixtures,
                competition_key=competition_key,
                season_code=season_code,
                captured_at=_timestamp(captured_at, option="--captured-at"),
                information_cutoff=_timestamp(information_cutoff, option="--information-cutoff"),
                rights_profile_id=rights_profile,
                database_url_ref=database_url_ref,
            )
        )

    result = _safe(operation)
    if not isinstance(result, FplOperationOutcome):
        _failure(IngestionError("INTERNAL_INVARIANT", "import result is invalid"))
    _emit_outcome(result)


@fpl_app.command("replay")
def replay_command(
    fixture_set: Annotated[Path, typer.Option("--fixture-set")],
    scenario: Annotated[str, typer.Option("--scenario")],
    information_cutoff: Annotated[str, typer.Option("--information-cutoff")] = (
        DEFAULT_INFORMATION_CUTOFF.isoformat().replace("+00:00", "Z")
    ),
    rights_profile: Annotated[str, typer.Option("--rights-profile")] = "synthetic_test_v1",
    database_url_ref: Annotated[str, typer.Option("--database-url-ref")] = DATABASE_REF,
    competition_key: Annotated[str, typer.Option("--competition-key")] = "SYNTHETIC_PL",
    season_code: Annotated[str, typer.Option("--season-code")] = "2026/27",
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Replay a manifest-approved deterministic synthetic scenario."""

    def operation() -> FplOperationOutcome:
        _require_json(output)
        return FplIngestionService().replay(
            FplReplayRequest(
                fixture_set=fixture_set,
                scenario=scenario,
                information_cutoff=_timestamp(information_cutoff, option="--information-cutoff"),
                rights_profile_id=rights_profile,
                database_url_ref=database_url_ref,
                competition_key=competition_key,
                season_code=season_code,
            )
        )

    result = _safe(operation)
    if not isinstance(result, FplOperationOutcome):
        _failure(IngestionError("INTERNAL_INVARIANT", "replay result is invalid"))
    _emit_outcome(result)


@fpl_app.command("resume")
def resume_command(
    snapshot_id: Annotated[UUID, typer.Option("--snapshot-id")],
    database_url_ref: Annotated[str, typer.Option("--database-url-ref")] = DATABASE_REF,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Resume the first incomplete stage of a synthetic source pair."""

    def operation() -> FplOperationOutcome:
        _require_json(output)
        return FplIngestionService().resume(snapshot_id, database_url_ref=database_url_ref)

    result = _safe(operation)
    if not isinstance(result, FplOperationOutcome):
        _failure(IngestionError("INTERNAL_INVARIANT", "resume result is invalid"))
    _emit_outcome(result)


@bundle_app.command("show")
def bundle_show_command(
    bundle_id: Annotated[UUID, typer.Option("--bundle-id")],
    database_url_ref: Annotated[str, typer.Option("--database-url-ref")] = DATABASE_REF,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Show an immutable bundle using its exact public schema."""

    def operation() -> BaseModel:
        _require_json(output)
        return FplIngestionService().show_bundle(bundle_id, database_url_ref=database_url_ref)

    result = _safe(operation)
    if not isinstance(result, BaseModel):
        _failure(IngestionError("INTERNAL_INVARIANT", "bundle result is invalid"))
    typer.echo(_json(result))


@fpl_app.command("snapshot")
def snapshot_command(
    resource: Annotated[str, typer.Option("--resource")],
    competition_key: Annotated[str, typer.Option("--competition-key")],
    season_code: Annotated[str, typer.Option("--season-code")],
    rights_profile: Annotated[str, typer.Option("--rights-profile")],
    database_url_ref: Annotated[str | None, typer.Option("--database-url-ref")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Attempt a live snapshot only after the automated-access rights gate."""

    def operation() -> FplOperationOutcome:
        _require_json(output)
        if resource not in {"bootstrap", "fixtures", "all"}:
            raise IngestionError("USAGE_INVALID", "--resource is invalid")
        return FplIngestionService().snapshot(
            resource=resource,
            competition_key=competition_key,
            season_code=season_code,
            rights_profile_id=rights_profile,
            database_url_ref=database_url_ref,
        )

    result = _safe(operation)
    if not isinstance(result, FplOperationOutcome):
        _failure(IngestionError("INTERNAL_INVARIANT", "snapshot result is invalid"))
    _emit_outcome(result)
