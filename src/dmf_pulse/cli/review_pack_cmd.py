"""CLI for deterministic ticket review-pack assembly."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from dmf_pulse.assurance.review_pack import ReviewPackError, build_review_pack

REVIEW_PACK_INVALID_EXIT = 30

review_pack_app = typer.Typer(help="Build and validate capped ticket review packs.")


@review_pack_app.command("build")
def build_command(
    ticket: Annotated[str, typer.Option("--ticket", help="Exact ticket ID.")],
    output: Annotated[Path, typer.Option("--output", help="ZIP path or output directory.")],
    baseline: Annotated[
        str | None,
        typer.Option("--baseline", help="Exact baseline Git commit for non-bootstrap tickets."),
    ] = None,
) -> None:
    """Build the root-only, maximum-20-file FND-001 review ZIP."""

    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        summary = build_review_pack(
            Path.cwd(),
            ticket=ticket,
            output=output,
            generated_at=generated_at,
            baseline=baseline,
        )
    except ReviewPackError as exc:
        typer.echo(json.dumps(exc.as_error_object(), sort_keys=True), err=True)
        raise typer.Exit(REVIEW_PACK_INVALID_EXIT) from exc
    typer.echo(
        json.dumps(
            {
                "file_count": summary.file_count,
                "ok": True,
                "path": summary.path.as_posix(),
                "payload_sha256": summary.payload_sha256,
                "archive_sha256": summary.sha256,
            },
            sort_keys=True,
        )
    )
