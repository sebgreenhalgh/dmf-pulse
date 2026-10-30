"""One current recommendation through the enrolled dashboard worker and ledger."""

from __future__ import annotations

from typing import Annotated, Literal, cast

import typer

from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.current_failures import CURRENT_FAILURE_ACTIONS
from dmf_pulse.operation.console import run_enrolled_current


def pulse_command(
    entry_id: Annotated[int, typer.Option("--entry-id", min=1, help="Private FPL entry ID.")],
    horizon_gameweeks: Annotated[
        int,
        typer.Option(
            "--horizon-gameweeks",
            help="Optimisation horizon: 1 (default) or explicit rolling 3-GW mode.",
        ),
    ] = 1,
    no_progress: Annotated[
        bool,
        typer.Option("--no-progress", help="Suppress human progress output on STDERR."),
    ] = False,
    refresh_approval: Annotated[
        str | None,
        typer.Option("--refresh-approval", help="Reviewed approval ID in the installed registry."),
    ] = None,
) -> None:
    """Publish one read-only current recommendation under an installed approval."""
    if horizon_gameweeks not in {1, 3}:
        typer.echo("--horizon-gameweeks must be exactly 1 or 3.", err=True)
        raise typer.Exit(2)
    if not refresh_approval:
        typer.echo("A reviewed refresh approval is required. Run dmf operation status.", err=True)
        raise typer.Exit(2)
    try:
        run_enrolled_current(
            authorization_id=refresh_approval,
            entry_id=entry_id,
            horizon=cast(Literal[1, 3], horizon_gameweeks),
            publish=lambda view: typer.echo(view.team.report),
            progress=None if no_progress else lambda value: typer.echo(value, err=True),
        )
    except AuthorizationError as error:
        # Fixed known diagnostics preserve the required operator action without
        # copying arbitrary worker/transport text into the console.
        code = error.code
        if type(code) is str and code in CURRENT_FAILURE_ACTIONS:
            message = f"{code}: {CURRENT_FAILURE_ACTIONS[code]}"
        else:
            message = (
                "Current refresh was blocked or expired. Run dmf operation status for readiness."
            )
        typer.echo(message, err=True)
        raise typer.Exit(2) from None


__all__ = ["pulse_command"]
