"""CLI for strict machine evidence validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from dmf_pulse.assurance.evidence import (
    EvidenceValidationError,
    validate_evidence_file,
    validate_ticket_evidence,
)

EVIDENCE_INVALID_EXIT = 20

evidence_app = typer.Typer(help="Validate strict DMF Pulse evidence contracts.")


@evidence_app.command("validate")
def validate_command(
    path: Annotated[Path | None, typer.Argument(help="UTF-8 JSON evidence path.")] = None,
    ticket: Annotated[
        str | None,
        typer.Option("--ticket", help="Validate the exact evidence directory for this ticket."),
    ] = None,
) -> None:
    """Validate one JSON contract or a ticket's exact manifested evidence directory."""

    try:
        if (path is None) == (ticket is None):
            raise EvidenceValidationError(
                "EVIDENCE_INPUT_REQUIRED", "provide exactly one evidence path or --ticket"
            )
        if ticket is not None:
            manifest = validate_ticket_evidence(Path.cwd(), ticket)
            result = {
                "artifact_count": len(manifest.artifacts),
                "kind": "ticket_evidence_directory",
                "ok": True,
                "status": manifest.status,
                "ticket_id": manifest.ticket_id,
            }
        else:
            if path is None:  # pragma: no cover - guarded above
                raise EvidenceValidationError(
                    "EVIDENCE_INPUT_REQUIRED", "provide exactly one evidence path or --ticket"
                )
            validated = validate_evidence_file(path)
            result = {"kind": validated.kind.value, "ok": True}
    except EvidenceValidationError as exc:
        typer.echo(json.dumps(exc.as_error_object(), sort_keys=True), err=True)
        raise typer.Exit(EVIDENCE_INVALID_EXIT) from exc
    typer.echo(json.dumps(result, sort_keys=True))
