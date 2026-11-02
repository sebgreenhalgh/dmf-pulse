"""Permanent private one-command operation; imports perform no setup or I/O."""

from __future__ import annotations

import typer


def start_command() -> None:
    """Check the accepted standing policy and open Seb's Desk with one acquisition."""
    from dmf_pulse.credentials.service import CredentialError
    from dmf_pulse.dashboard.authorization import AuthorizationError
    from dmf_pulse.operation.diagnostics import safe_failure
    from dmf_pulse.operation.models import OperationError
    from dmf_pulse.operation.start import run_start

    try:
        run_start(progress=typer.echo)
    except CredentialError as error:
        failure = safe_failure(error, "WORKER_START")
        typer.echo(f"{failure.code}: {failure.stage} ({failure.category})", err=True)
        raise typer.Exit(2) from None
    except (OperationError, AuthorizationError) as error:
        failure = safe_failure(error, "WORKER_START")
        reason = f" [{failure.integrity_reason}]" if failure.integrity_reason else ""
        typer.echo(f"{failure.code}: {failure.stage} ({failure.category}){reason}", err=True)
        raise typer.Exit(2) from None
    except KeyboardInterrupt:
        typer.echo("Seb's Desk closed; durable acquisition markers retained.")
