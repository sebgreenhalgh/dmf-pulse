"""Explicit offline P01 fallback commands; acquisition requires reviewed runner."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from dmf_pulse.cli.p01_a03 import execute_a03_command
from dmf_pulse.evaluation.p01_fallback import (
    P01FallbackScoreV1,
    fallback_scorecard,
    reconcile_openfootball,
    score_p01_fallback,
)
from dmf_pulse.evaluation.p01_fallback_context import authenticate_p01, load_context
from dmf_pulse.evaluation.p01_fallback_store import load_fallback, persist_fallback
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    ParsedSnapshot,
    StrengthEvidenceError,
)
from dmf_pulse.ingestion.p01_fallback import PublicP01FallbackOutcomesV1

fallback_app = typer.Typer(help="P01 descriptive fallback evidence; shadow only, no activation.")
fallback_app.command("execute-a03")(execute_a03_command)


@fallback_app.command("context")
def context_command() -> None:
    typer.echo(load_context().model_dump_json())


@fallback_app.command("score")
def score_command(
    forecast: Annotated[Path, typer.Option()],
    outcomes: Annotated[Path, typer.Option()],
    outcomes_sha256: Annotated[str, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()],
) -> None:
    value = authenticate_p01(forecast)
    labels = load_fallback(outcomes, expected_sha256=outcomes_sha256)
    if not isinstance(labels, PublicP01FallbackOutcomesV1):
        raise StrengthEvidenceError("not a P01 fallback outcome artifact")
    result = score_p01_fallback(value, outcomes=labels, as_of=datetime.now(UTC))
    path = persist_fallback(result, artifact_root=artifact_root)
    authenticate_p01(forecast)
    typer.echo(result.model_dump_json())
    typer.echo(str(path), err=True)


@fallback_app.command("report")
def report_command(
    score: Annotated[Path, typer.Option()],
    score_sha256: Annotated[str, typer.Option()],
    outcomes: Annotated[Path, typer.Option()],
    outcomes_sha256: Annotated[str, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()],
) -> None:
    result = load_fallback(score, expected_sha256=score_sha256)
    labels = load_fallback(outcomes, expected_sha256=outcomes_sha256)
    if not isinstance(result, P01FallbackScoreV1) or not isinstance(
        labels, PublicP01FallbackOutcomesV1
    ):
        raise StrengthEvidenceError("fallback report requires explicit typed evidence")
    if result.context != load_context():
        raise StrengthEvidenceError("fallback report authority differs")
    report = fallback_scorecard(result, outcomes=labels)
    persist_fallback(report, artifact_root=artifact_root)
    typer.echo(report.model_dump_json())


@fallback_app.command("reconcile")
def reconcile_command(
    outcomes: Annotated[Path, typer.Option()],
    outcomes_sha256: Annotated[str, typer.Option()],
    openfootball: Annotated[Path, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()],
) -> None:
    labels = load_fallback(outcomes, expected_sha256=outcomes_sha256)
    if not isinstance(labels, PublicP01FallbackOutcomesV1) or labels.context != load_context():
        raise StrengthEvidenceError("fallback reconciliation authority differs")
    snapshot = ParsedSnapshot.model_validate_json(openfootball.read_bytes())
    result = reconcile_openfootball(labels, snapshot=snapshot, audited_at=datetime.now(UTC))
    persist_fallback(result, artifact_root=artifact_root)
    typer.echo(result.model_dump_json())
