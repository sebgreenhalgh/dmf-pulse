"""Offline CLI for Stage-8 team score and clean-sheet distributions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from dmf_pulse.football_events.coherence import assert_score_coherence
from dmf_pulse.football_events.evaluation import evaluate_realized_score
from dmf_pulse.football_events.service import (
    ScoreDistributionError,
    ScoreDistributionService,
    explain_market_fit,
    load_joint_score_distribution,
    load_score_distribution_request,
    persist_joint_score_distribution,
)

events_app = typer.Typer(help="Build coherent team score and clean-sheet distributions.")


def _emit(payload: dict[str, Any]) -> None:
    typer.echo(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _validate_output(output: str) -> None:
    if output != "json":
        raise ScoreDistributionError("USAGE_INVALID", "--output must be json")


@events_app.command("score-distribution")
def score_distribution_command(
    fixture: Annotated[
        Path,
        typer.Option(
            "--fixture",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Path to a score-distribution-request-v1 JSON fixture.",
        ),
    ],
    artifact_root: Annotated[
        Path | None,
        typer.Option(
            "--artifact-root",
            file_okay=False,
            dir_okay=True,
            help="Optional immutable artifact root.",
        ),
    ] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Build one deterministic market-constrained score distribution."""

    try:
        _validate_output(output)
        request = load_score_distribution_request(fixture)
        result = ScoreDistributionService().project(request)
        artifact_path: str | None = None
        if result.distribution is not None and artifact_root is not None:
            artifact_path = str(
                persist_joint_score_distribution(
                    result.distribution,
                    artifact_root=artifact_root,
                )
            )
    except ScoreDistributionError as exc:
        _emit(exc.as_error_object())
        raise typer.Exit(2) from None
    except (ValidationError, ValueError, ArithmeticError) as exc:
        _emit(_error("SCORE_DISTRIBUTION_INVALID", str(exc)))
        raise typer.Exit(2) from None
    payload = {
        "artifact_path": artifact_path,
        "result": result.model_dump(mode="json"),
        "schema_version": "score-distribution-command-v1",
    }
    _emit(payload)
    if result.status == "BLOCKED":
        raise typer.Exit(4)


@events_app.command("explain-market-fit")
def explain_market_fit_command(
    fixture: Annotated[
        Path,
        typer.Option(
            "--fixture",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Explain target-versus-projected market residuals for one fixture."""

    try:
        _validate_output(output)
        request = load_score_distribution_request(fixture)
        result = ScoreDistributionService().project(request)
        if result.distribution is None:
            _emit(
                {
                    "error": {
                        "code": result.error_code,
                        "message": result.error_message,
                    }
                }
            )
            raise typer.Exit(4)
        _emit(explain_market_fit(result.distribution))
    except ScoreDistributionError as exc:
        _emit(exc.as_error_object())
        raise typer.Exit(2) from None
    except (ValidationError, ValueError, ArithmeticError) as exc:
        _emit(_error("SCORE_DISTRIBUTION_INVALID", str(exc)))
        raise typer.Exit(2) from None


@events_app.command("evaluate")
def evaluate_command(
    distribution: Annotated[
        Path,
        typer.Option(
            "--distribution",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    home_goals: Annotated[int, typer.Option("--home-goals", min=0)],
    away_goals: Annotated[int, typer.Option("--away-goals", min=0)],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Score one finalized result against an immutable Stage-8 forecast."""

    try:
        _validate_output(output)
        forecast = load_joint_score_distribution(distribution)
        _emit(
            evaluate_realized_score(
                forecast,
                home_goals=home_goals,
                away_goals=away_goals,
            )
        )
    except ScoreDistributionError as exc:
        _emit(exc.as_error_object())
        raise typer.Exit(2) from None
    except (ValidationError, ValueError, ArithmeticError) as exc:
        _emit(_error("EVALUATION_INVALID", str(exc)))
        raise typer.Exit(2) from None


@events_app.command("validate")
def validate_command(
    distribution: Annotated[
        Path,
        typer.Option(
            "--distribution",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Fail closed unless a public score artifact and all identities validate."""

    try:
        _validate_output(output)
        forecast = load_joint_score_distribution(distribution)
        assert_score_coherence(forecast)
    except ScoreDistributionError as exc:
        _emit(exc.as_error_object())
        raise typer.Exit(2) from None
    except (ValidationError, ValueError, ArithmeticError) as exc:
        _emit(_error("ARTIFACT_INVALID", str(exc)))
        raise typer.Exit(2) from None
    _emit(
        {
            "fixture_id": forecast.fixture_id,
            "result_sha256": forecast.result_sha256,
            "schema_version": "score-distribution-validation-v1",
            "status": "VALID",
        }
    )


__all__ = ["events_app"]
