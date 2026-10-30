"""Offline recovered-forecast metadata and explicit local byte authentication."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from dmf_pulse.player_lab.recovery import (
    RecoveryError,
    recovery_catalogue,
    verify_recovered_artifact,
)

recovery_app = typer.Typer(add_completion=False, no_args_is_help=True)


def _fail(error: RecoveryError) -> None:
    typer.echo(json.dumps({"error": {"code": error.code, "blocking": True}}, sort_keys=True))
    raise typer.Exit(2)


@recovery_app.command("inventory")
def inventory() -> None:
    """Show reviewed metadata, coverage gaps and original P01 label status offline."""
    try:
        typer.echo(recovery_catalogue().model_dump_json(indent=2))
    except RecoveryError as error:
        _fail(error)


@recovery_app.command("verify")
def verify(artifact: Annotated[Path, typer.Option("--artifact")]) -> None:
    """Hash one local artifact; an unknown payload never creates custody or rights."""
    try:
        typer.echo(verify_recovered_artifact(artifact).model_dump_json(indent=2))
    except RecoveryError as error:
        _fail(error)
