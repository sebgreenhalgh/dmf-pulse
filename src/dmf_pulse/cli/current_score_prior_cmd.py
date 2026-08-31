"""Private CLI for the approved commit-pinned OpenFootball score prior."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from dmf_pulse.football_events._decimal import parse_utc
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.config import APPROVED_PROFILE_ID
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorService,
    CurrentScorePriorSummary,
)

openfootball_app = typer.Typer(
    help="Build the private commit-pinned OpenFootball historical score prior."
)


def _timestamp(value: str) -> datetime:
    try:
        return parse_utc(value, field_name="information_cutoff")
    except ValueError as exc:
        raise IngestionError(
            "USAGE_INVALID", "--information-cutoff must be an RFC3339 UTC timestamp"
        ) from exc


def _json(value: object) -> str:
    return json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True)


def _failure(error: IngestionError) -> NoReturn:
    typer.echo(_json(error.as_error_object()))
    raise typer.Exit(error.exit_code)


def _safe(operation: Callable[[], CurrentScorePriorSummary]) -> CurrentScorePriorSummary:
    try:
        return operation()
    except IngestionError as exc:
        _failure(exc)
    except (ValidationError, ValueError) as exc:
        error = IngestionError("USAGE_INVALID", "score-prior request is invalid")
        typer.echo(_json(error.as_error_object()))
        raise typer.Exit(error.exit_code) from exc
    except Exception as exc:  # pragma: no cover - final secret-safe boundary
        error = IngestionError("INTERNAL_INVARIANT", "score-prior command failed safely")
        typer.echo(_json(error.as_error_object()))
        raise typer.Exit(error.exit_code) from exc


@openfootball_app.command("score-prior")
def score_prior_command(
    information_cutoff: Annotated[str, typer.Option("--information-cutoff")],
    rights_profile: Annotated[str, typer.Option("--rights-profile")] = APPROVED_PROFILE_ID,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Acquire, validate and emit only a private safe score-prior summary."""

    def operation() -> CurrentScorePriorSummary:
        if output != "json":
            raise IngestionError("USAGE_INVALID", "--output must be json")
        request = CurrentScorePriorBuildRequest(
            information_cutoff=_timestamp(information_cutoff),
            rights_profile_id=rights_profile,
        )
        return CurrentScorePriorService().build(request).safe_summary()

    result = _safe(operation)
    # The command intentionally emits neither raw source content nor provider headers.
    typer.echo(_json(canonical_summary_json_from_summary(result)))


def canonical_summary_json_from_summary(summary: CurrentScorePriorSummary) -> dict[str, object]:
    """Render canonical public timestamps without widening the disclosure surface."""

    value = summary.model_dump(mode="json")
    value["information_cutoff"] = summary.information_cutoff.isoformat().replace("+00:00", "Z")
    value["usable_at"] = summary.usable_at.isoformat().replace("+00:00", "Z")
    return value


__all__ = ["openfootball_app", "score_prior_command"]
