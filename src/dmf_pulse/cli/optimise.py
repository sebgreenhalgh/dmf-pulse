"""CLI for the explicit-path OPT-010 commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from dmf_pulse.fpl_points.artifacts import load_verified_model
from dmf_pulse.fpl_points.models import GameweekProjectionResult
from dmf_pulse.optimisation.artifacts import load_canonical_json, persist_result
from dmf_pulse.optimisation.errors import OptimisationError
from dmf_pulse.optimisation.models import (
    OneGameweekOptimisationRequest,
    OneGameweekOptimisationResult,
    OptimisationStatus,
)
from dmf_pulse.optimisation.service import optimise_one_gameweek
from dmf_pulse.optimisation.validation import validate_plan_against_request
from dmf_pulse.rules.capabilities import load_capability_artifact
from dmf_pulse.rules.compiler import load_compiled_ruleset
from dmf_pulse.rules.models import CapabilityArtifact

optimise_app = typer.Typer(add_completion=False, no_args_is_help=True)


def _emit(value: BaseModel) -> None:
    typer.echo(
        json.dumps(value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2)
    )


def _exit_for(status: OptimisationStatus) -> None:
    raise typer.Exit(
        {
            OptimisationStatus.SUCCESS: 0,
            OptimisationStatus.BLOCKED: 3,
            OptimisationStatus.INFEASIBLE: 4,
            OptimisationStatus.RESOURCE_LIMIT: 5,
        }[status]
    )


@optimise_app.command("one-gameweek")
def one_gameweek(
    request: Annotated[Path, typer.Option("--request")],
    gameweek_artifact: Annotated[Path, typer.Option("--gameweek-artifact")],
    ruleset: Annotated[Path, typer.Option("--ruleset")],
    artifact_root: Annotated[Path, typer.Option("--artifact-root")],
    capability: Annotated[Path | None, typer.Option("--capability")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    if output != "json":
        raise typer.BadParameter("--output must be json")
    try:
        req = load_canonical_json(request, OneGameweekOptimisationRequest)
        projection = load_verified_model(gameweek_artifact, GameweekProjectionResult)
        compiled = load_compiled_ruleset(ruleset)
        cap: CapabilityArtifact | None = (
            load_capability_artifact(capability) if capability else None
        )
        result = optimise_one_gameweek(req, projection, compiled, capability=cap)
        persist_result(result, artifact_root=artifact_root, gameweek_id=req.gameweek_id)
    except OptimisationError as exc:
        typer.echo(
            json.dumps(
                {"status": "BLOCKED", "error_code": exc.code, "error_message": exc.message},
                sort_keys=True,
            )
        )
        raise typer.Exit(2) from None
    _emit(result)
    _exit_for(result.status)


@optimise_app.command("validate-plan")
def validate_plan(
    request: Annotated[Path, typer.Option("--request")],
    gameweek_artifact: Annotated[Path, typer.Option("--gameweek-artifact")],
    ruleset: Annotated[Path, typer.Option("--ruleset")],
    artifact: Annotated[Path, typer.Option("--artifact")],
    capability: Annotated[Path | None, typer.Option("--capability")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    if output != "json":
        raise typer.BadParameter("--output must be json")
    try:
        req = load_canonical_json(request, OneGameweekOptimisationRequest)
        projection = load_verified_model(gameweek_artifact, GameweekProjectionResult)
        compiled = load_compiled_ruleset(ruleset)
        cap: CapabilityArtifact | None = (
            load_capability_artifact(capability) if capability else None
        )
        result = load_canonical_json(artifact, OneGameweekOptimisationResult)
        if result.recommended_plan is None:
            raise OptimisationError(
                "OPTIMISATION_ARTIFACT_INVALID", "artifact has no recommended plan"
            )
        report = validate_plan_against_request(
            req, projection, compiled, result.recommended_plan, capability=cap
        )
        _emit(report)
        raise typer.Exit(0 if report.legal else 2)
    except OptimisationError as exc:
        typer.echo(
            json.dumps(
                {"legal": False, "error_code": exc.code, "error_message": exc.message},
                sort_keys=True,
            )
        )
        raise typer.Exit(2) from None
