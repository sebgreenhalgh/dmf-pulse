"""CLI for installed specification authority validation."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from dmf_pulse.assurance.specs import (
    FrozenInputValidationError,
    OddFrozenInputValidationError,
    SpecValidationError,
    validate_fpl004_frozen_inputs,
    validate_odd005_frozen_inputs,
    validate_specifications,
)

specs_app = typer.Typer(help="Validate installed specification authority.")


@specs_app.command("validate")
def validate_command() -> None:
    """Validate installed source bytes and all manifest references."""

    try:
        report = validate_specifications(Path.cwd())
        validate_fpl004_frozen_inputs(Path.cwd())
        if (Path.cwd() / "tickets/ODD-005/ticket.yaml").is_file():
            validate_odd005_frozen_inputs(Path.cwd())
    except SpecValidationError as exc:
        typer.echo(json.dumps(exc.as_error_object(), sort_keys=True))
        raise typer.Exit(21) from exc
    except FrozenInputValidationError as exc:
        error = SpecValidationError(list(exc.errors))
        typer.echo(json.dumps(error.as_error_object(), sort_keys=True))
        raise typer.Exit(21) from exc
    except OddFrozenInputValidationError as exc:
        error = SpecValidationError(list(exc.errors))
        typer.echo(json.dumps(error.as_error_object(), sort_keys=True))
        raise typer.Exit(21) from exc
    typer.echo(json.dumps(report, sort_keys=True))
