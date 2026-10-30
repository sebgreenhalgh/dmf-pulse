"""Offline recovered-forecast metadata and explicit local byte authentication."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from dmf_pulse.player_lab.recovery import (
    RecoveryError,
    recovery_catalogue,
    verify_recovered_artifact,
)

recovery_app = typer.Typer(add_completion=False, no_args_is_help=True)


def _fail(error: RecoveryError) -> None:
    typer.echo(json.dumps({"error": {"code": error.code, "blocking": True}}, sort_keys=True))
    raise typer.Exit(2)


@recovery_app.command("inventory")
def inventory() -> None:
    """Show reviewed metadata, coverage gaps and original P01 label status offline."""
    try:
        typer.echo(recovery_catalogue().model_dump_json(indent=2))
    except RecoveryError as error:
        _fail(error)


@recovery_app.command("verify")
def verify(artifact: Annotated[Path, typer.Option("--artifact")]) -> None:
    """Hash one local artifact; an unknown payload never creates custody or rights."""
    try:
        typer.echo(verify_recovered_artifact(artifact).model_dump_json(indent=2))
    except RecoveryError as error:
        _fail(error)


@recovery_app.command("p01-canonical-proposal")
def p01_canonical_proposal(
    output: Annotated[
        Path, typer.Option(help="New immutable PROPOSED_UNACCEPTED code-binding artifact.")
    ],
) -> None:
    from dmf_pulse.evaluation.p01_canonical import (
        propose_canonical_binding,
        write_canonical_artifact,
    )
    from dmf_pulse.ingestion.openfootball.team_strength_data import StrengthEvidenceError

    try:
        proposal = propose_canonical_binding()
        digest = write_canonical_artifact(output, proposal)
    except (StrengthEvidenceError, ValueError, OSError):
        typer.echo("P01_CANONICAL_PROPOSAL_FAILED", err=True)
        raise typer.Exit(2) from None
    typer.echo(
        json.dumps(
            {
                "state": proposal.state,
                "artifact_sha256": digest,
                "semantic_sha256": proposal.semantic_sha256,
                "scoring_authorized": False,
            },
            sort_keys=True,
        )
    )


@recovery_app.command("p01-canonical-score")
def p01_canonical_score(
    forecast: Annotated[Path, typer.Option(help="Exact original P01 forecast artifact.")],
    outcomes: Annotated[
        Path, typer.Option(help="Already-qualified local canonical outcome bytes; no acquisition.")
    ],
    output: Annotated[
        Path,
        typer.Option(
            help="New immutable descriptive score; only accepted installed authority can score."
        ),
    ],
) -> None:
    from dmf_pulse.evaluation.p01_canonical import score_original_p01, write_canonical_artifact
    from dmf_pulse.ingestion.openfootball.team_strength_data import StrengthEvidenceError

    try:
        score = score_original_p01(forecast, outcomes, as_of=datetime.now(UTC))
        digest = write_canonical_artifact(output, score)
    except StrengthEvidenceError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None
    typer.echo(
        json.dumps(
            {
                "artifact_sha256": digest,
                "semantic_sha256": score.semantic_sha256,
                "fixture_outcomes": score.fixture_outcome_count,
                "product_rows": len(score.score.scores),
                "promotion": "FORBIDDEN",
            },
            sort_keys=True,
        )
    )
