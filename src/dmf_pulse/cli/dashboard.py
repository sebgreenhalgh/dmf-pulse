"""Explicit local dashboard startup; no server side effects during command import."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from secrets import token_urlsafe
from tempfile import mkdtemp
from time import monotonic
from typing import Annotated

import typer


def dashboard_command(
    port: Annotated[int, typer.Option(min=1024, max=65535)] = 8765,
    demo: Annotated[
        bool, typer.Option(help="Run actual models with packaged synthetic sources only.")
    ] = False,
    current_demo: Annotated[
        bool,
        typer.Option(help="Exercise the current-mode worker with owned injected sources only."),
    ] = False,
    entry_id: Annotated[int | None, typer.Option(min=1)] = None,
    refresh_approval: Annotated[
        str | None, typer.Option(help="Separately enrolled approval identifier.")
    ] = None,
    control_dir: Annotated[
        Path | None, typer.Option(help="Owned synthetic control-metadata directory only.")
    ] = None,
    deadline_at: Annotated[
        str | None, typer.Option(help="Qualified pilot deadline with UTC offset.")
    ] = None,
) -> None:
    """Open Seb's Desk on http://127.0.0.1:8765 (private, memory-only)."""
    import uvicorn

    from dmf_pulse.dashboard.app import create_app
    from dmf_pulse.dashboard.authorization import AuthorizationError
    from dmf_pulse.dashboard.current import CurrentRefreshSession
    from dmf_pulse.dashboard.runtime import DeskRuntime
    from dmf_pulse.dashboard.synthetic import DEMO_TIME

    started = monotonic()

    def clock() -> datetime:
        return DEMO_TIME + timedelta(seconds=monotonic() - started)

    if (demo and current_demo) or ((demo or current_demo) and refresh_approval is not None):
        raise typer.BadParameter("Select one execution/source context.")
    if control_dir is not None and not current_demo:
        raise typer.BadParameter(
            "--control-dir is restricted to --current-demo; production control uses PostgreSQL."
        )
    if (entry_id is not None or deadline_at is not None) and refresh_approval is None:
        raise typer.BadParameter("Entry and deadline options require an enrolled refresh approval.")
    try:
        if demo:
            runtime = DeskRuntime(demo=True, clock=clock)
        elif current_demo:
            base = (
                Path(mkdtemp(prefix="dmf-owned-current-")) if control_dir is None else control_dir
            )
            current = CurrentRefreshSession.owned(base / "usage")
            runtime = DeskRuntime(current_session=current, clock=clock)
        elif refresh_approval is not None:
            if entry_id is None or deadline_at is None:
                raise typer.BadParameter(
                    "The enrolled current scope requires an entry and qualified deadline."
                )
            try:
                deadline = datetime.fromisoformat(deadline_at)
            except ValueError:
                raise typer.BadParameter(
                    "The deadline must be an ISO datetime with UTC offset."
                ) from None
            if deadline.tzinfo is None or deadline.utcoffset() is None:
                raise typer.BadParameter("The deadline must have a UTC offset.")
            runtime = DeskRuntime(
                current_session=CurrentRefreshSession.enrolled(
                    authorization_id=refresh_approval,
                    entry_id=entry_id,
                    deadline_at=deadline,
                )
            )
        else:
            runtime = DeskRuntime()
    except AuthorizationError as error:
        typer.echo(error.code, err=True)
        raise typer.Exit(2) from None
    code = token_urlsafe(24)
    application = create_app(runtime=runtime, pairing_code=code, port=port)
    typer.echo(f"Seb's Desk: http://127.0.0.1:{port}")
    typer.echo(f"Enter this one-time pairing code in the local page: {code}")
    typer.echo(
        "Synthetic model demonstration."
        if demo
        else "Synthetic current-mode architecture; all source transports are owned and injected."
        if current_demo
        else "Private current mode; exact enrolled rights and quota are checked before every Refresh."
        if refresh_approval is not None
        else "Live refresh is rights-blocked until an eligible market approval exists."
    )
    typer.echo(
        "Presentation expires after 15 minutes or the official deadline. Ctrl+C clears the session."
    )
    try:
        uvicorn.run(
            application,
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_config=None,
            log_level="critical",
            proxy_headers=False,
            server_header=False,
            limit_concurrency=8,
            timeout_keep_alive=5,
            timeout_graceful_shutdown=10,
        )
    finally:
        runtime.close()
