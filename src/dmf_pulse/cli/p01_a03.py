"""Explicit guarded A03 command; failures disclose only closed diagnostics."""

from pathlib import Path
from typing import Annotated

import typer

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.ingestion.p01_a03_execution import execute_a03
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    DiagnosticProgress,
    FailureReason,
    P01FallbackExecutionFailure,
    ReasonFailure,
)


def execute_a03_command(
    forecast: Annotated[Path, typer.Option()],
    review: Annotated[Path, typer.Option()],
    review_binding: Annotated[Path, typer.Option()],
    review_binding_sha256: Annotated[str, typer.Option()],
    implementation_root: Annotated[Path, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()],
) -> None:
    """Execute the single separately reviewed and CI-sealed A03 authority."""
    progress = DiagnosticProgress()
    try:
        result = execute_a03(
            forecast_path=forecast,
            review_path=review,
            binding_path=review_binding,
            expected_binding_sha256=review_binding_sha256,
            implementation_root=implementation_root,
            artifact_root=artifact_root,
            progress=progress,
        )
    except P01FallbackExecutionFailure as failure:
        typer.echo(
            pretty_json(
                {
                    "status": "P01_A03_PRECHECK_STOPPED",
                    "stage": failure.stage.value,
                    "reason": failure.reason.value,
                    "diagnostics": failure.diagnostics.model_dump(mode="json"),
                    "production_active": False,
                }
            ),
            nl=False,
        )
        raise typer.Exit(2) from None
    except Exception as failure:
        reason = (
            failure.reason
            if isinstance(failure, ReasonFailure)
            else FailureReason.UNKNOWN_P01_OUTCOME_FAILURE
        )
        typer.echo(
            pretty_json(
                {
                    "status": "P01_A03_STOPPED_UNSEALED_HANDOFF",
                    "stage": progress.stage.value,
                    "reason": reason.value,
                    "diagnostics": progress.safe.model_dump(mode="json"),
                    "production_active": False,
                }
            ),
            nl=False,
        )
        raise typer.Exit(2) from None
    typer.echo(pretty_json(result), nl=False)
    if result.status != "P01_A03_COMPLETE":
        raise typer.Exit(2)
