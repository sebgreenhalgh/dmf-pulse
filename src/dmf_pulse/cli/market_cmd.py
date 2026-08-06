"""CLI for exact as-of market observation retrieval."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.parser import parse_rfc3339_timestamp
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.markets.models import NormalisationStatus
from dmf_pulse.markets.service import MarketService

market_app = typer.Typer(help="Query canonical raw market observations.")


def _exit_code(error: IngestionError) -> int:
    if error.code in {"USAGE_INVALID", "MAPPING_CONFLICT", "DATABASE_REFERENCE_INVALID"}:
        return 3
    if error.code in {"NO_USABLE_BUNDLE", "POST_CUTOFF", "QUALITY_BLOCKED"}:
        return 2
    return 6


@market_app.command("observations")
def observations_command(
    fixture_external_provider: Annotated[str, typer.Option("--fixture-external-provider")],
    fixture_external_id: Annotated[str, typer.Option("--fixture-external-id")],
    season_code: Annotated[str, typer.Option("--season-code")],
    as_of: Annotated[str, typer.Option("--as-of")],
    database_url_ref: Annotated[str, typer.Option("--database-url-ref")] = DATABASE_REF,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    exit_code: int | None
    try:
        if output != "json":
            raise IngestionError("USAGE_INVALID", "--output must be json")
        cutoff = parse_rfc3339_timestamp(as_of)
    except (IngestionError, ValueError) as exc:
        error = (
            exc
            if isinstance(exc, IngestionError)
            else IngestionError("USAGE_INVALID", "--as-of must be an RFC3339 timestamp")
        )
        typer.echo(json.dumps(error.as_error_object(), sort_keys=True))
        exit_code = _exit_code(error)
    else:
        exit_code = None
    if exit_code is not None:
        raise typer.Exit(exit_code)
    try:
        result = MarketService().observations(
            fixture_external_provider=fixture_external_provider,
            fixture_external_id=fixture_external_id,
            season_code=season_code,
            as_of=cutoff,
            database_url_ref=database_url_ref,
        )
    except IngestionError as exc:
        typer.echo(json.dumps(exc.as_error_object(), sort_keys=True))
        exit_code = _exit_code(exc)
    except Exception:  # pragma: no cover - final secret-safe CLI boundary
        error = IngestionError("INTERNAL_INVARIANT", "market query failed safely")
        typer.echo(json.dumps(error.as_error_object(), sort_keys=True))
        exit_code = 6
    else:
        typer.echo(
            json.dumps(
                result.model_dump(mode="json"),
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return
    raise typer.Exit(exit_code)


@market_app.command("normalise")
def normalise_command(
    fixture_external_provider: Annotated[str, typer.Option("--fixture-external-provider")],
    fixture_external_id: Annotated[str, typer.Option("--fixture-external-id")],
    season_code: Annotated[str, typer.Option("--season-code")],
    as_of: Annotated[str, typer.Option("--as-of")],
    database_url_ref: Annotated[str, typer.Option("--database-url-ref")] = DATABASE_REF,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Normalise canonical stored 1X2 books and persist the exact consensus."""

    try:
        if output != "json":
            raise IngestionError("USAGE_INVALID", "--output must be json")
        cutoff = parse_rfc3339_timestamp(as_of)
    except (IngestionError, ValueError) as exc:
        error = (
            exc
            if isinstance(exc, IngestionError)
            else IngestionError("USAGE_INVALID", "--as-of must be an RFC3339 timestamp")
        )
        typer.echo(json.dumps(error.as_error_object(), sort_keys=True))
        raise typer.Exit(1) from None
    try:
        result = MarketService().normalise(
            fixture_external_provider=fixture_external_provider,
            fixture_external_id=fixture_external_id,
            season_code=season_code,
            as_of=cutoff,
            database_url_ref=database_url_ref,
        )
    except IngestionError as exc:
        typer.echo(json.dumps(exc.as_error_object(), sort_keys=True))
        raise typer.Exit(4 if exc.code in {"MAPPING_CONFLICT", "QUALITY_BLOCKED"} else 1) from None
    except Exception:  # pragma: no cover - final secret-safe CLI boundary
        error = IngestionError("INTERNAL_INVARIANT", "market normalisation failed safely")
        typer.echo(json.dumps(error.as_error_object(), sort_keys=True))
        raise typer.Exit(1) from None
    typer.echo(
        json.dumps(
            result.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result.status is NormalisationStatus.INSUFFICIENT:
        raise typer.Exit(2)
    if result.status is NormalisationStatus.BLOCKED:
        raise typer.Exit(4)
