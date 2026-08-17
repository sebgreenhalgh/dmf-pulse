"""CLI for the explicit-path Stage-10 and Stage-11 optimisation commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from dmf_pulse.fpl_points.artifacts import load_verified_model
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import GameweekProjectionResult
from dmf_pulse.optimisation.artifacts import (
    load_canonical_json,
    load_verified_artifact,
    persist_result,
)
from dmf_pulse.optimisation.errors import OptimisationError
from dmf_pulse.optimisation.models import (
    OneGameweekOptimisationRequest,
    OneGameweekOptimisationResult,
    OptimisationStatus,
)
from dmf_pulse.optimisation.multi_gameweek_artifacts import (
    load_canonical_json as load_multi_gameweek_json,
)
from dmf_pulse.optimisation.multi_gameweek_artifacts import (
    load_verified_artifact as load_verified_multi_gameweek_artifact,
)
from dmf_pulse.optimisation.multi_gameweek_artifacts import (
    persist_advance as persist_multi_gameweek_advance,
)
from dmf_pulse.optimisation.multi_gameweek_artifacts import (
    persist_result as persist_multi_gameweek_result,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekOptimisationRequest,
    MultiGameweekOptimisationResult,
    MultiGameweekResultStatus,
)
from dmf_pulse.optimisation.multi_gameweek_service import (
    advance_current_action,
    optimise_multi_gameweek,
)
from dmf_pulse.optimisation.service import optimise_one_gameweek
from dmf_pulse.optimisation.validation import validate_result_against_request
from dmf_pulse.rules.capabilities import load_capability_artifact
from dmf_pulse.rules.compiler import load_compiled_ruleset
from dmf_pulse.rules.errors import RulesError
from dmf_pulse.rules.models import CapabilityArtifact
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules

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


def _integrity_failure(
    exc: OptimisationError | FplPointsError | RulesError, *, validate: bool = False
) -> None:
    payload: dict[str, object] = {
        "error_code": exc.code,
        "error_message": exc.message,
    }
    if validate:
        payload["legal"] = False
    else:
        payload["status"] = "BLOCKED"
    typer.echo(json.dumps(payload, sort_keys=True))
    raise typer.Exit(2)


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
        persist_result(
            result,
            artifact_root=artifact_root,
            gameweek_id=req.gameweek_id,
            request_id=req.request_id,
        )
    except (OptimisationError, FplPointsError, RulesError) as exc:
        _integrity_failure(exc)
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
        result = load_verified_artifact(artifact, OneGameweekOptimisationResult)
        report = validate_result_against_request(req, projection, compiled, result, capability=cap)
        _emit(report)
        raise typer.Exit(0 if report.legal else 2)
    except (OptimisationError, FplPointsError, RulesError) as exc:
        _integrity_failure(exc, validate=True)


def _exit_for_multi_gameweek(status: MultiGameweekResultStatus) -> None:
    raise typer.Exit(
        {
            MultiGameweekResultStatus.SUCCESS: 0,
            MultiGameweekResultStatus.RESOURCE_LIMIT: 5,
            MultiGameweekResultStatus.INFEASIBLE: 4,
            MultiGameweekResultStatus.BLOCKED: 3,
            MultiGameweekResultStatus.ERROR: 6,
        }[status]
    )


@optimise_app.command("multi-gameweek")
def multi_gameweek(
    request: Annotated[Path, typer.Option("--request")],
    ruleset: Annotated[Path, typer.Option("--ruleset")],
    artifact_root: Annotated[Path, typer.Option("--artifact-root")],
    capability: Annotated[Path | None, typer.Option("--capability")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Optimise one nonanticipative multi-Gameweek policy from a canonical request."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    try:
        req = load_multi_gameweek_json(request, MultiGameweekOptimisationRequest)
        compiled = load_compiled_ruleset(ruleset)
        cap: CapabilityArtifact | None = (
            load_capability_artifact(capability) if capability else None
        )
        resolved_rules = build_multi_gameweek_transfer_rules(
            compiled,
            projection_mode=req.projection_mode,
            capability=cap,
        )
        if resolved_rules != req.rules:
            raise OptimisationError(
                "MULTI_GAMEWEEK_RULES_LINEAGE_MISMATCH",
                "request transfer rules differ from the supplied compiled ruleset",
            )
        result = optimise_multi_gameweek(req)
        persist_multi_gameweek_result(result, artifact_root=artifact_root)
    except (OptimisationError, FplPointsError, RulesError) as exc:
        _integrity_failure(exc)
    _emit(result)
    _exit_for_multi_gameweek(result.status)


@optimise_app.command("advance-multi-gameweek")
def advance_multi_gameweek(
    request: Annotated[Path, typer.Option("--request")],
    result: Annotated[Path, typer.Option("--result")],
    artifact_root: Annotated[Path, typer.Option("--artifact-root")],
    observed_node: Annotated[str | None, typer.Option("--observed-node")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Execute only a verified result's current action and optionally observe one child node."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    try:
        req = load_multi_gameweek_json(request, MultiGameweekOptimisationRequest)
        value = load_verified_multi_gameweek_artifact(result, MultiGameweekOptimisationResult)
        advanced = advance_current_action(
            req,
            value,
            observed_node_id=observed_node,
        )
        persist_multi_gameweek_advance(advanced, artifact_root=artifact_root)
    except (OptimisationError, FplPointsError, RulesError, ValueError) as exc:
        if isinstance(exc, (OptimisationError, FplPointsError, RulesError)):
            _integrity_failure(exc)
        wrapped = OptimisationError("MULTI_GAMEWEEK_ADVANCE_INVALID", str(exc))
        _integrity_failure(wrapped)
    _emit(advanced)


def main() -> None:
    """Run the optimisation command group directly for offline verification."""

    optimise_app(prog_name="dmf optimise")


if __name__ == "__main__":  # pragma: no cover - installed entry point owns dispatch
    main()
