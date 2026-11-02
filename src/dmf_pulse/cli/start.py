"""Permanent private one-command operation; imports perform no setup or I/O."""

from __future__ import annotations

import typer


def start_command() -> None:
    """Check the accepted standing policy and open Seb's Desk with one acquisition."""
    from dmf_pulse.credentials.service import CredentialError
    from dmf_pulse.dashboard.authorization import AuthorizationError
    from dmf_pulse.operation.models import OperationError
    from dmf_pulse.operation.start import run_start

    try:
        run_start(progress=typer.echo)
    except CredentialError as error:
        typer.echo(f"{error.code}: {error.message}", err=True)
        raise typer.Exit(2) from None
    except (OperationError, AuthorizationError) as error:
        typer.echo(error.code, err=True)
        raise typer.Exit(2) from None
    except KeyboardInterrupt:
        typer.echo("Seb's Desk closed; durable acquisition markers retained.")
