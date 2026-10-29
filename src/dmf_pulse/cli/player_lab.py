"""Offline owned-cohort commands; external assertions cannot confer custody."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_lab.cohort import FinalCohort, ForecastCohort
from dmf_pulse.player_lab.compatibility import future_cohort_proposal
from dmf_pulse.player_lab.contracts import Sealed
from dmf_pulse.player_lab.runner import (
    OwnedForecastPhase,
    PlayerEvaluationService,
    finalize_owned_cohort,
    freeze_owned_cohort,
    operational_synthetic_evaluation,
)

player_lab_app = typer.Typer(add_completion=False, no_args_is_help=True)
_MAX_INPUT_BYTES = 4_000_000


def _emit(value: Sealed, output: Path | None) -> None:
    body = (value.model_dump_json(indent=2) + "\n").encode("utf-8")
    if output is None:
        typer.echo(body.decode("utf-8"), nl=False)
    else:
        # Explicitly requested exports are owned synthetic only, never overwrite.
        with output.open("xb") as handle:
            handle.write(body)
        typer.echo(json.dumps({"semantic_sha256": value.semantic_sha256, "status": "WRITTEN"}))


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON keys")
        value[key] = item
    return value


def _load(path: Path) -> bytes:
    with path.open("rb") as handle:
        body = handle.read(_MAX_INPUT_BYTES + 1)
    if len(body) > _MAX_INPUT_BYTES:
        raise ValueError("cohort input exceeds resource limit")
    json.loads(body, object_pairs_hook=_object)
    return body


def _owned_phase(path: Path) -> OwnedForecastPhase:
    supplied = ForecastCohort.model_validate_json(_load(path))
    phase = freeze_owned_cohort()
    if supplied != phase.cohort:
        raise ValueError("input lacks original qualified owned custody")
    return phase


def _fail() -> None:
    typer.echo(
        json.dumps(
            {"error": {"code": "PLAYER_COHORT_INVALID_OR_UNQUALIFIED", "blocking": True}},
            sort_keys=True,
        )
    )
    raise typer.Exit(2)


@player_lab_app.command("freeze-owned")
def freeze_owned(
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Export all owned forecasts before any final-outcome body is read."""
    try:
        _emit(freeze_owned_cohort().cohort, output)
    except (ValueError, TypeError, OSError, RecursionError, IngestionError):
        _fail()


@player_lab_app.command("labels-owned")
def labels_owned(
    cohort: Annotated[Path, typer.Option("--cohort")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Authenticate the owned freeze, then export its later complete final labels."""
    try:
        _emit(finalize_owned_cohort(_owned_phase(cohort)), output)
    except (ValueError, TypeError, OSError, RecursionError, IngestionError):
        _fail()


@player_lab_app.command("score")
def score(
    cohort: Annotated[Path, typer.Option("--cohort")],
    labels: Annotated[Path, typer.Option("--labels")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Score exact owned original custody; no generic real import is authorized."""
    try:
        phase = _owned_phase(cohort)
        supplied = FinalCohort.model_validate_json(_load(labels))
        expected = finalize_owned_cohort(phase)
        if supplied != expected:
            raise ValueError("input differs from complete original owned final labels")
        report = PlayerEvaluationService().run(
            phase.cohort, supplied, custody=phase.custody, evaluated_at=phase.clock[0]
        )
        _emit(report, output)
    except (ValueError, TypeError, OSError, RecursionError, IngestionError):
        _fail()


@player_lab_app.command("demo")
def demo(output: Annotated[Path | None, typer.Option("--output")] = None) -> None:
    """Run the same complete two-phase service used by Model Performance."""
    try:
        _emit(operational_synthetic_evaluation(), output)
    except (ValueError, TypeError, OSError, RecursionError, IngestionError):
        _fail()


@player_lab_app.command("proposal")
def proposal() -> None:
    """Show a time-expiring public-text candidate; never issue a real forecast."""
    _emit(future_cohort_proposal(assessed_at=datetime.now(UTC)), None)
