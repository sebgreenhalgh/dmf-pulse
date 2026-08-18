"""Typer surface for ODD-005 validation, replay, import, and refusal."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import BaseModel

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.parser import parse_rfc3339_timestamp
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.ingestion.odds.credentials import (
    RuntimeOddsCredentialProvider,
    credential_is_configured,
)
from dmf_pulse.ingestion.odds.parser import CONTRACT_VERSION
from dmf_pulse.ingestion.odds.service import (
    OddsImportRequest,
    OddsIngestionService,
    OddsOperationOutcome,
    OddsReplayRequest,
)

odds_app = typer.Typer(help="Validate and ingest governed The Odds API-shaped observations.")

_INVALID_CODES = {
    "VALIDATION_FAILED",
    "MALFORMED_JSON",
    "PAYLOAD_TOO_LARGE",
    "PAYLOAD_TOO_DEEP",
    "DUPLICATE_JSON_KEY",
    "MAPPING_CONFLICT",
    "USAGE_INVALID",
    "CONFIGURATION_INVALID",
    "FIXTURE_NOT_APPROVED",
    "DATABASE_REFERENCE_INVALID",
}
_CONTROLLED_CODES = {"RIGHTS_BLOCKED", "CREDENTIAL_UNAVAILABLE", "QUOTA_EXHAUSTED"}
_PROVIDER_CODES = {
    "CONNECT_TIMEOUT",
    "READ_TIMEOUT",
    "TOTAL_TIMEOUT",
    "HTTP_429",
    "HTTP_4XX",
    "HTTP_5XX",
    "CONTENT_TYPE_INVALID",
    "REDIRECT_BLOCKED",
    "TLS_ERROR",
    "SOURCE_UNAVAILABLE",
    "CANCELLED",
}


def _odd_exit_code(code: str) -> int:
    if code in _INVALID_CODES:
        return 3
    if code in _CONTROLLED_CODES:
        return 4
    if code in _PROVIDER_CODES:
        return 5
    if code in {"NO_USABLE_BUNDLE", "POST_CUTOFF", "QUALITY_BLOCKED"}:
        return 2
    return 6


def _json(value: BaseModel | dict[str, object]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(payload, allow_nan=False, ensure_ascii=False, sort_keys=True)


def _failure(error: IngestionError) -> NoReturn:
    typer.echo(_json(error.as_error_object()))
    raise typer.Exit(_odd_exit_code(error.code))


def _safe(operation: Callable[[], object]) -> object:
    try:
        return operation()
    except IngestionError as exc:
        typer.echo(_json(exc.as_error_object()))
        exit_code = _odd_exit_code(exc.code)
    except Exception:  # pragma: no cover - final secret-safe boundary
        error = IngestionError("INTERNAL_INVARIANT", "odds command failed safely")
        typer.echo(_json(error.as_error_object()))
        exit_code = 6
    raise typer.Exit(exit_code)


def _timestamp(value: str, option: str) -> datetime:
    try:
        return parse_rfc3339_timestamp(value)
    except ValueError as exc:
        raise IngestionError("USAGE_INVALID", f"{option} must be an RFC3339 timestamp") from exc


def _require_json(output: str) -> None:
    if output != "json":
        raise IngestionError("USAGE_INVALID", "--output must be json")


def _emit(outcome: OddsOperationOutcome) -> None:
    typer.echo(_json(outcome.result))
    if outcome.exit_code:
        raise typer.Exit(outcome.exit_code)


@odds_app.command("credential-status")
def credential_status_command(
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Report only whether a valid runtime credential is configured."""

    def operation() -> dict[str, object]:
        _require_json(output)
        return {
            "configured": credential_is_configured(RuntimeOddsCredentialProvider()),
        }

    result = _safe(operation)
    if not isinstance(result, dict) or set(result) != {"configured"}:
        _failure(IngestionError("INTERNAL_INVARIANT", "credential diagnostic is invalid"))
    typer.echo(_json(result))


@odds_app.command("validate")
def validate_command(
    provider: Annotated[str, typer.Option("--provider")],
    input_path: Annotated[Path, typer.Option("--input")],
    contract_version: Annotated[str, typer.Option("--contract-version")] = CONTRACT_VERSION,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    def operation() -> BaseModel:
        _require_json(output)
        return OddsIngestionService().validate(
            input_path, provider=provider, contract_version=contract_version
        )

    result = _safe(operation)
    if not isinstance(result, BaseModel):
        _failure(IngestionError("INTERNAL_INVARIANT", "odds validation result is invalid"))
    typer.echo(_json(result))


@odds_app.command("import")
def import_command(
    provider: Annotated[str, typer.Option("--provider")],
    input_path: Annotated[Path, typer.Option("--input")],
    mapping_plan: Annotated[Path, typer.Option("--mapping-plan")],
    captured_at: Annotated[str, typer.Option("--captured-at")],
    information_cutoff: Annotated[str, typer.Option("--information-cutoff")],
    rights_profile: Annotated[str, typer.Option("--rights-profile")],
    database_url_ref: Annotated[str, typer.Option("--database-url-ref")] = DATABASE_REF,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    def operation() -> OddsOperationOutcome:
        _require_json(output)
        if provider != "the_odds_api":
            raise IngestionError("USAGE_INVALID", "--provider is unsupported")
        return OddsIngestionService().import_payload(
            OddsImportRequest(
                input_path=input_path,
                mapping_plan_path=mapping_plan,
                captured_at=_timestamp(captured_at, "--captured-at"),
                information_cutoff=_timestamp(information_cutoff, "--information-cutoff"),
                rights_profile_id=rights_profile,
                database_url_ref=database_url_ref,
            )
        )

    result = _safe(operation)
    if not isinstance(result, OddsOperationOutcome):
        _failure(IngestionError("INTERNAL_INVARIANT", "odds import result is invalid"))
    _emit(result)


@odds_app.command("replay")
def replay_command(
    fixture_set: Annotated[Path, typer.Option("--fixture-set")],
    scenario: Annotated[str, typer.Option("--scenario")],
    information_cutoff: Annotated[str, typer.Option("--information-cutoff")],
    rights_profile: Annotated[str, typer.Option("--rights-profile")],
    database_url_ref: Annotated[str, typer.Option("--database-url-ref")] = DATABASE_REF,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    def operation() -> OddsOperationOutcome:
        _require_json(output)
        return OddsIngestionService().replay(
            OddsReplayRequest(
                fixture_set=fixture_set,
                scenario=scenario,
                information_cutoff=_timestamp(information_cutoff, "--information-cutoff"),
                rights_profile_id=rights_profile,
                database_url_ref=database_url_ref,
            )
        )

    result = _safe(operation)
    if not isinstance(result, OddsOperationOutcome):
        _failure(IngestionError("INTERNAL_INVARIANT", "odds replay result is invalid"))
    _emit(result)


@odds_app.command("snapshot")
def snapshot_command(
    provider: Annotated[str, typer.Option("--provider")],
    competition_key: Annotated[str, typer.Option("--competition-key")],
    sport_key: Annotated[str, typer.Option("--sport-key")],
    region: Annotated[str, typer.Option("--region")],
    market: Annotated[str, typer.Option("--market")],
    as_of: Annotated[str, typer.Option("--as-of")],
    database_url_ref: Annotated[str, typer.Option("--database-url-ref")] = DATABASE_REF,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    def operation() -> OddsOperationOutcome:
        _require_json(output)
        return OddsIngestionService().snapshot(
            provider=provider,
            competition_key=competition_key,
            sport_key=sport_key,
            region=region,
            market=market,
            as_of=_timestamp(as_of, "--as-of"),
            database_url_ref=database_url_ref,
        )

    result = _safe(operation)
    if not isinstance(result, OddsOperationOutcome):
        _failure(IngestionError("INTERNAL_INVARIANT", "odds snapshot result is invalid"))
    _emit(result)
