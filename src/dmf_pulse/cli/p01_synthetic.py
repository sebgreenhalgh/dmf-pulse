"""Offline byte-injected synthetic readiness command; no transport or authority."""

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from dmf_pulse.evaluation.p01_fallback_context import (
    FORECAST_SHA,
    P01FallbackContext,
    strict_json,
)
from dmf_pulse.evaluation.p01_frozen_view import _read_pinned_representation
from dmf_pulse.evaluation.p01_synthetic_readiness import exercise_synthetic_pipeline
from dmf_pulse.ingestion.openfootball.team_strength_data import StrengthEvidenceError
from dmf_pulse.ingestion.p01_metadata_candidate import require_synthetic_context


def synthetic_readiness_command(
    forecast: Annotated[Path, typer.Option()],
    context: Annotated[Path, typer.Option()],
    global_types: Annotated[Path, typer.Option()],
    league_types: Annotated[Path, typer.Option()],
    matchday: Annotated[Path, typer.Option()],
    as_of: Annotated[str, typer.Option(help="Synthetic UTC exercise time, ISO8601.")],
    candidate: Annotated[
        bool, typer.Option(help="Exercise inactive descriptive candidate.")
    ] = False,
) -> None:
    """Print a SYNTHETIC_ONLY receipt, never outcome labels or a real P01 score."""

    def read(path: Path, limit: int) -> bytes:
        if path.is_symlink():
            raise StrengthEvidenceError("synthetic input symlink refused")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise StrengthEvidenceError("synthetic input exceeds size bound")
        strict_json(data)
        return data

    try:
        frozen_context = P01FallbackContext.model_validate_json(read(context, 131072))
        require_synthetic_context(frozen_context)
        raw = read(forecast, 64 * 1024 * 1024)
        value = strict_json(raw)
        if not isinstance(value, dict) or value.get("semantic_sha256") == FORECAST_SHA:
            raise StrengthEvidenceError("actual P01 is not a synthetic forecast")
        if value.get("dataset_mode") != "RECONSTRUCTED":
            raise StrengthEvidenceError("synthetic reconstructed forecast required")
        view = _read_pinned_representation(
            raw,
            expected_byte_sha256=frozen_context.forecast_byte_sha256,
            expected_semantic_sha256=frozen_context.forecast_sha256,
        )
        receipt = exercise_synthetic_pipeline(
            view,
            context=frozen_context,
            global_types=read(global_types, 524288),
            league_types=read(league_types, 524288),
            matchday=read(matchday, 524288),
            as_of=datetime.fromisoformat(as_of),
            candidate=candidate,
        )
    except (ValueError, OSError):
        typer.echo("SYNTHETIC_READINESS_REFUSED", err=True)
        raise typer.Exit(2) from None
    typer.echo(receipt.model_dump_json())
