"""Explicit local dashboard startup; no server side effects during command import."""

from __future__ import annotations

from datetime import datetime, timedelta
from secrets import token_urlsafe
from time import monotonic
from typing import Annotated

import typer


def dashboard_command(
    port: Annotated[int, typer.Option(min=1024, max=65535)] = 8765,
    demo: Annotated[
        bool, typer.Option(help="Run actual models with packaged synthetic sources only.")
    ] = False,
) -> None:
    """Open Seb's Desk on http://127.0.0.1:8765 (private, memory-only)."""
    import uvicorn

    from dmf_pulse.dashboard.app import create_app
    from dmf_pulse.dashboard.runtime import DeskRuntime
    from dmf_pulse.dashboard.synthetic import DEMO_TIME

    started = monotonic()

    def clock() -> datetime:
        return DEMO_TIME + timedelta(seconds=monotonic() - started)

    runtime = DeskRuntime(demo=True, clock=clock) if demo else DeskRuntime()
    code = token_urlsafe(24)
    application = create_app(runtime=runtime, pairing_code=code, port=port)
    typer.echo(f"Seb's Desk: http://127.0.0.1:{port}")
    typer.echo(f"Enter this one-time pairing code in the local page: {code}")
    typer.echo(
        "Synthetic model demonstration."
        if demo
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
