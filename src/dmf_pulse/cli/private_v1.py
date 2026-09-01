"""Offline commands for the private current recommendation vertical slice."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from dmf_pulse.private_v1.artifacts import (
    load_execution_input,
    write_synthetic_replay_bundle,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.service import PrivateV1RecommendationService

private_v1_app = typer.Typer(help="Run or replay the private current recommendation path.")


def _emit_error(error: PrivateV1Error) -> None:
    typer.echo(
        json.dumps(
            {"error": {"code": error.code, "message": error.message}},
            allow_nan=False,
            sort_keys=True,
        )
    )


@private_v1_app.command("run")
def run_command(
    input_path: Annotated[
        Path,
        typer.Option(
            "--input",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Strict private-v1-execution-input-v1 JSON.",
        ),
    ],
    freeze_dir: Annotated[
        Path | None,
        typer.Option(
            "--freeze-dir",
            file_okay=False,
            help="New directory for a retention-authorised synthetic replay bundle.",
        ),
    ] = None,
) -> None:
    """Execute the in-memory path; optionally freeze a synthetic-only replay bundle."""

    try:
        execution = load_execution_input(input_path)
        result = PrivateV1RecommendationService().run(execution)
        typer.echo(result.report, nl=False)
        if freeze_dir is not None:
            manifest = write_synthetic_replay_bundle(
                execution,
                result.decision,
                result.report,
                freeze_dir,
            )
            typer.echo(f"Replay manifest: {manifest.manifest_sha256}")
            typer.echo(f"Replay: dmf private-v1 replay --bundle {freeze_dir}")
    except PrivateV1Error as exc:
        _emit_error(exc)
        raise typer.Exit(2) from None
    except (ValidationError, ValueError, ArithmeticError):
        _emit_error(PrivateV1Error("PRIVATE_V1_FAILED", "private recommendation execution failed"))
        raise typer.Exit(2) from None


@private_v1_app.command("replay")
def replay_command(
    bundle: Annotated[
        Path,
        typer.Option(
            "--bundle",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="Frozen synthetic replay bundle directory.",
        ),
    ],
) -> None:
    """Verify and recompute a synthetic replay bundle entirely offline."""

    try:
        replay = PrivateV1RecommendationService().replay(bundle)
        typer.echo(replay.run.report, nl=False)
        typer.echo(f"Replay verified: {replay.manifest_sha256}")
    except PrivateV1Error as exc:
        _emit_error(exc)
        raise typer.Exit(2) from None
    except (ValidationError, ValueError, ArithmeticError):
        _emit_error(PrivateV1Error("REPLAY_FAILED", "private replay execution failed"))
        raise typer.Exit(2) from None


__all__ = ["private_v1_app"]
