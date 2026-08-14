"""Offline CLI for Stage-9 fixture player-points distributions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from dmf_pulse.fpl_points.artifacts import load_verified_model, persist_model_artifact
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import FixtureProjectionResult
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter
from dmf_pulse.fpl_points.service import FplPointsService, load_fixture_request, load_mc_policy

fpl_points_app = typer.Typer(help="Generate raw player FPL-points scenario distributions.")


def _emit(payload: dict[str, Any]) -> None:
    typer.echo(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _validate_output(output: str) -> None:
    if output != "json":
        raise FplPointsError("USAGE_INVALID", "--output must be json")


@fpl_points_app.command("simulate-fixture")
def simulate_fixture_command(
    request_path: Annotated[
        Path,
        typer.Option(
            "--request",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Path to an fpl-points-fixture-request-v1 JSON file.",
        ),
    ],
    ruleset_path: Annotated[
        Path,
        typer.Option(
            "--ruleset",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Canonical compiled DMFP-02 ruleset JSON.",
        ),
    ],
    mc_policy_path: Annotated[
        Path,
        typer.Option(
            "--mc-policy",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    artifact_root: Annotated[
        Path,
        typer.Option("--artifact-root", file_okay=False, dir_okay=True),
    ],
    approval_path: Annotated[
        Path | None,
        typer.Option(
            "--approval",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Required matching human approval record for PRODUCTION mode.",
        ),
    ] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Run the deterministic Stage-7 + Stage-8 -> Stage-9 fixture slice."""

    try:
        _validate_output(output)
        request = load_fixture_request(request_path)
        engine = AcceptedRulesAdapter.from_paths(ruleset_path, approval_path)
        policy = load_mc_policy(mc_policy_path)
        result = FplPointsService(engine, policy).project(request)
        path = persist_model_artifact(
            result,
            artifact_root=artifact_root,
            category="fixture",
            identity_parts=(result.gameweek_id, result.fixture_id),
        )
        _emit(
            {
                "artifact_path": str(path),
                "result": result.model_dump(mode="json"),
                "schema_version": "fpl-points-simulate-command-v1",
            }
        )
    except FplPointsError as exc:
        _emit(exc.as_error_object())
        raise typer.Exit(2) from None
    except (ValidationError, ValueError, ArithmeticError) as exc:
        _emit({"error": {"code": "FPL_POINTS_INVALID", "message": str(exc)}})
        raise typer.Exit(2) from None
    if result.status.value == "BLOCKED":
        raise typer.Exit(4)


@fpl_points_app.command("validate")
def validate_command(
    artifact: Annotated[
        Path,
        typer.Option(
            "--artifact",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Verify detached hash, canonical JSON, and all strict model invariants."""

    try:
        _validate_output(output)
        result = load_verified_model(artifact, FixtureProjectionResult)
        _emit(
            {
                "fixture_id": result.fixture_id,
                "gameweek_id": result.gameweek_id,
                "result_sha256": result.result_sha256,
                "schema_version": "fpl-points-validation-v1",
                "status": "VALID",
            }
        )
    except FplPointsError as exc:
        _emit(exc.as_error_object())
        raise typer.Exit(2) from None


@fpl_points_app.command("mc-diagnostics")
def diagnostics_command(
    artifact: Annotated[
        Path,
        typer.Option(
            "--artifact",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Read the explicit numerical-error diagnostics from an immutable artifact."""

    try:
        _validate_output(output)
        result = load_verified_model(artifact, FixtureProjectionResult)
        if result.monte_carlo is None:
            raise FplPointsError("MC_DIAGNOSTICS_MISSING", "artifact has no diagnostics")
        _emit(
            {
                "fixture_id": result.fixture_id,
                "monte_carlo": result.monte_carlo.model_dump(mode="json"),
                "schema_version": "fpl-points-mc-diagnostics-v1",
            }
        )
    except FplPointsError as exc:
        _emit(exc.as_error_object())
        raise typer.Exit(2) from None


__all__ = ["fpl_points_app"]
