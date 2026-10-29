"""Explicit owned-synthetic player-evidence demonstration, with no real-data route."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import typer

from dmf_pulse.player_evidence.contracts import EvidenceError

player_evidence_app = typer.Typer(help="Describe authenticated owned starts/minutes evidence.")


@player_evidence_app.command("demo")
def demo_command(
    revised: Annotated[
        bool, typer.Option(help="Use the later synthetic cutoff after the owned correction.")
    ] = False,
) -> None:
    """Run source qualification -> temporal joins -> descriptive features, without transport."""
    from dmf_pulse.player_evidence.demo import owned_demo

    cutoff = datetime(2026, 10, 12, 12, tzinfo=UTC) if revised else None
    try:
        result = owned_demo(cutoff)
    except EvidenceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    payload = result.model_dump(mode="json")
    payload["semantic_sha256"] = result.semantic_sha256
    import json

    typer.echo(json.dumps(payload, sort_keys=True, indent=2))
