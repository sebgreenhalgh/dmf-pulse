"""Stage-15 rank CLI backed by the shared application service."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel, Field, StrictInt, StrictStr, ValidationError

from dmf_pulse.evaluation.artifacts import canonical_json_bytes
from dmf_pulse.evaluation.errors import EvaluationError
from dmf_pulse.evaluation.service import load_json
from dmf_pulse.fpl_points.models import GameweekScenarioSet
from dmf_pulse.optimisation.models import CandidatePlayer, OneGameweekRulesView
from dmf_pulse.rank_strategy.artifacts import (
    Stage15DecisionArtifact,
    load_decision_artifact,
    persist_decision_artifact,
    seal_decision_artifact,
    verify_decision_artifact,
)
from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.models import (
    CohortSample,
    ManagerMultiplierPolicy,
    ManagerMultiplierSet,
    ManagerTeamPlan,
    PositiveInt,
    RankModel,
    RankTiePolicy,
)
from dmf_pulse.rank_strategy.opponent_models import (
    OpponentActionCandidate,
    OpponentActionDistribution,
    OpponentBehaviourProfile,
    OpponentObservedState,
)
from dmf_pulse.rank_strategy.service import (
    evaluate_effective_ownership,
    evaluate_exact_mini_league,
    evaluate_opponent_actions,
    evaluate_rank_plans,
    evaluate_synthetic_cohort,
    seal_rank_service_request,
    validate_installed_rank_capability,
)
from dmf_pulse.rank_strategy.service_models import RankServiceRequest, RankServiceResult
from dmf_pulse.rank_strategy.synthetic_models import SyntheticOverallPopulation

_ZERO_HASH = "0" * 64

rank_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Validate rank inputs and evaluate EO, opponents, cohorts, and accepted plans.",
)


class _EffectiveOwnershipInput(RankModel):
    sample: CohortSample
    scenario_set: GameweekScenarioSet
    players: dict[StrictStr, CandidatePlayer]
    rules: OneGameweekRulesView
    policy: ManagerMultiplierPolicy
    sebastian_plan: ManagerTeamPlan | None = None


class _MiniLeagueInput(RankModel):
    sample: CohortSample
    multiplier_sets: tuple[ManagerMultiplierSet, ...]
    tie_policy: RankTiePolicy
    target_manager_id: StrictStr = Field(min_length=1, max_length=200)
    target_rank: PositiveInt | None = None


class _OpponentInput(RankModel):
    observed_state: OpponentObservedState
    candidates: tuple[OpponentActionCandidate, ...] = Field(min_length=2)
    profile: OpponentBehaviourProfile
    additional_distributions: tuple[OpponentActionDistribution, ...] = ()
    max_joint_scenarios: StrictInt = Field(default=10_000, gt=0)


class _SyntheticCohortInput(RankModel):
    population: SyntheticOverallPopulation
    multiplier_sets: tuple[ManagerMultiplierSet, ...]
    tie_policy: RankTiePolicy
    target_rank: PositiveInt | None = None


def _load(path: Path) -> dict[str, Any]:
    try:
        return load_json(path)
    except (OSError, ValueError) as exc:
        raise RankStrategyError(
            "RANK_INPUT_INVALID",
            "rank input JSON is unavailable or malformed",
        ) from exc


def _emit(value: BaseModel | tuple[Any, ...] | dict[str, Any] | list[Any]) -> None:
    payload: BaseModel | dict[str, Any] | list[Any]
    if isinstance(value, BaseModel):
        payload = value
    elif isinstance(value, tuple):
        payload = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value
        ]
    else:
        payload = value
    typer.echo(canonical_json_bytes(payload).decode("utf-8"), nl=False)


def _fail(exc: Exception) -> None:
    if isinstance(exc, RankStrategyError):
        payload = exc.as_error_object()
    elif isinstance(exc, EvaluationError):
        payload = {
            "error": {
                "code": f"RANK_{exc.code}",
                "message": exc.message,
                "details": {},
            }
        }
    elif isinstance(exc, ValidationError):
        payload = {
            "error": {
                "code": "RANK_INPUT_INVALID",
                "message": "rank input violates the Stage-15 contract",
                "details": {},
            }
        }
    else:
        payload = {
            "error": {
                "code": "RANK_EXECUTION_INVALID",
                "message": str(exc),
                "details": {},
            }
        }
    typer.echo(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    raise typer.Exit(2)


def _execute(operation: Callable[[], BaseModel | tuple[Any, ...] | dict[str, Any]]) -> None:
    try:
        _emit(operation())
    except (
        RankStrategyError,
        EvaluationError,
        ValidationError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OSError,
    ) as exc:
        _fail(exc)


def _request(path: Path) -> RankServiceRequest:
    value = RankServiceRequest.model_validate(_load(path))
    if value.service_request_hash == _ZERO_HASH:
        return seal_rank_service_request(value)
    return value


def _evaluate(path: Path) -> RankServiceResult:
    return evaluate_rank_plans(_request(path))


@rank_app.command("eo")
def effective_ownership(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Calculate multiplier-aware effective ownership on shared scenarios."""

    if output != "json":
        raise typer.BadParameter("--output must be json")

    def operation() -> BaseModel:
        value = _EffectiveOwnershipInput.model_validate(_load(input_path))
        return evaluate_effective_ownership(
            value.sample,
            value.scenario_set,
            value.players,
            value.rules,
            value.policy,
            sebastian_plan=value.sebastian_plan,
        )

    _execute(operation)


@rank_app.command("mini-league")
def mini_league(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Run exact named/synthetic mini-league rank enumeration."""

    if output != "json":
        raise typer.BadParameter("--output must be json")

    def operation() -> BaseModel:
        value = _MiniLeagueInput.model_validate(_load(input_path))
        return evaluate_exact_mini_league(
            value.sample,
            value.multiplier_sets,
            value.tie_policy,
            target_manager_id=value.target_manager_id,
            target_rank=value.target_rank,
        )

    _execute(operation)


@rank_app.command("opponents")
def opponents(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Model cutoff-safe opponent actions and optional exact joint marginals."""

    if output != "json":
        raise typer.BadParameter("--output must be json")

    def operation() -> BaseModel:
        value = _OpponentInput.model_validate(_load(input_path))
        return evaluate_opponent_actions(
            value.observed_state,
            value.candidates,
            value.profile,
            additional_distributions=value.additional_distributions,
            max_joint_scenarios=value.max_joint_scenarios,
        )

    _execute(operation)


@rank_app.command("cohort")
def cohort(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Run the rights-gated weighted synthetic overall-field simulator."""

    if output != "json":
        raise typer.BadParameter("--output must be json")

    def operation() -> BaseModel:
        value = _SyntheticCohortInput.model_validate(_load(input_path))
        return evaluate_synthetic_cohort(
            value.population,
            value.multiplier_sets,
            value.tie_policy,
            target_rank=value.target_rank,
        )

    _execute(operation)


@rank_app.command("evaluate")
def evaluate(
    input_path: Annotated[Path, typer.Option("--input")],
    artifact_root: Annotated[Path | None, typer.Option("--artifact-root")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Re-evaluate accepted Stage-12 to Stage-14 plans under rank utility."""

    if output != "json":
        raise typer.BadParameter("--output must be json")

    def operation() -> BaseModel:
        request = _request(input_path)
        result = evaluate_rank_plans(request)
        if artifact_root is None:
            return result
        artifact = seal_decision_artifact(request, result)
        persist_decision_artifact(artifact, artifact_root=artifact_root)
        return artifact

    _execute(operation)


@rank_app.command("compare")
def compare(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Compare points-optimal, rank-optimal, and executable selected plans."""

    if output != "json":
        raise typer.BadParameter("--output must be json")

    def operation() -> dict[str, Any]:
        value = _evaluate(input_path)
        return {
            "activation_status": value.activation_status.value,
            "requested_objective": value.requested_objective.value,
            "effective_objective": value.effective_objective.value,
            "points_optimal_plan_id": value.points_optimal_plan.plan_id,
            "rank_optimal_plan_id": value.rank_optimal_plan.plan_id,
            "selected_plan_id": value.selected_plan.plan_id,
            "expected_points_difference": value.expected_points_difference,
            "target_probability_difference": value.target_probability_difference,
            "confidence": value.confidence.value,
            "fail_closed_reasons": list(value.fail_closed_reasons),
            "gate_report": value.gate_report.model_dump(mode="json"),
            "raw_projection_hash": value.raw_projection_hash,
            "scenario_set_hash": value.scenario_set_hash,
            "result_hash": value.result_hash,
        }

    _execute(operation)


@rank_app.command("validate")
def validate(
    input_path: Annotated[Path | None, typer.Option("--input")] = None,
    artifact: Annotated[Path | None, typer.Option("--artifact")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Validate installed capability, a service request, or a sealed artifact."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    if input_path is not None and artifact is not None:
        raise typer.BadParameter("use only one of --input or --artifact")

    def operation() -> BaseModel | dict[str, Any]:
        if artifact is not None:
            return load_decision_artifact(artifact)
        if input_path is None:
            return validate_installed_rank_capability()
        payload = _load(input_path)
        if payload.get("schema_version") == "stage15-rank-decision-v1":
            value = Stage15DecisionArtifact.model_validate(payload)
            verify_decision_artifact(value)
            return value
        request = RankServiceRequest.model_validate(payload)
        if request.service_request_hash == _ZERO_HASH:
            request = seal_rank_service_request(request)
        result = evaluate_rank_plans(request)
        decision_artifact = seal_decision_artifact(request, result)
        return {
            "status": "VALID",
            "service_request_hash": request.service_request_hash,
            "result_hash": result.result_hash,
            "artifact_hash": decision_artifact.artifact_hash,
            "activation_status": result.activation_status.value,
        }

    _execute(operation)


__all__ = ["rank_app"]
