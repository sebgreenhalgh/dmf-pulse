"""CLI for strict machine evidence validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from dmf_pulse.assurance.evidence import EvidenceValidationError, validate_evidence_file

EVIDENCE_INVALID_EXIT = 20

evidence_app = typer.Typer(help="Validate strict DMF Pulse evidence contracts.")


@evidence_app.command("validate")
def validate_command(
    path: Annotated[Path, typer.Argument(help="UTF-8 JSON evidence path.")],
) -> None:
    """Detect and validate a result, ticket manifest, or review manifest."""

    try:
        validated = validate_evidence_file(path)
    except EvidenceValidationError as exc:
        typer.echo(json.dumps(exc.as_error_object(), sort_keys=True), err=True)
        raise typer.Exit(EVIDENCE_INVALID_EXIT) from exc
    typer.echo(json.dumps({"kind": validated.kind.value, "ok": True}, sort_keys=True))
