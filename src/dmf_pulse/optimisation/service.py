"""Orchestration and fail-closed gates around the pure exhaustive solver."""

from __future__ import annotations

from typing import Any

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import GameweekProjectionResult, ProjectionMode
from dmf_pulse.optimisation.candidate_pool import snapshot_hash
from dmf_pulse.optimisation.errors import InfeasibleError, OptimisationError, ResourceLimitError
from dmf_pulse.optimisation.models import (
    ExplanationItem,
    OneGameweekOptimisationRequest,
    OneGameweekOptimisationResult,
    OneGameweekOptimiserPolicy,
    OptimalityGuarantee,
    OptimisationLineage,
    OptimisationStatus,
    SearchScope,
    SolverStatus,
)
from dmf_pulse.optimisation.policy import load_policy
from dmf_pulse.optimisation.solver import solve
from dmf_pulse.optimisation.validation import (
    validate_plan_against_request,
    validate_request_boundary,
    validate_stage9_boundary,
)
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view


def _hash_without(value: Any, field: str) -> str:
    payload = value.model_dump(mode="json")
    payload[field] = None
    if field == "result_sha256" and isinstance(payload.get("lineage"), dict):
        payload["lineage"]["result_sha256"] = None
    return semantic_sha256(payload)


def _guarantee(scope: SearchScope) -> OptimalityGuarantee:
    return {
        SearchScope.FIXED_SQUAD: OptimalityGuarantee.EXACT_FIXED_SQUAD,
        SearchScope.PROVIDED_SQUADS: OptimalityGuarantee.EXACT_PROVIDED_SET,
        SearchScope.BOUNDED_PLAYER_POOL: OptimalityGuarantee.EXACT_DECLARED_PLAYER_POOL,
    }[scope]


def _lineage(
    request: OneGameweekOptimisationRequest,
    projection: GameweekProjectionResult,
    rules: CompiledRuleset,
    capability: CapabilityArtifact | None,
    *,
    policy: OneGameweekOptimiserPolicy | None = None,
    plan_sha256: str | None = None,
    result_sha256: str | None = None,
) -> OptimisationLineage:
    request_hash = _hash_without(request, "request_sha256")
    policy_hash = semantic_sha256(policy) if policy is not None else None
    input_hash = semantic_sha256(
        {
            "request_sha256": request_hash,
            "candidate_snapshot_sha256": snapshot_hash(request.candidate_pool),
            "gameweek_result_sha256": projection.result_sha256,
            "ruleset_hash": rules.ruleset_hash,
            "capability_hash": capability.capability_hash if capability else None,
            "policy_sha256": policy_hash,
        }
    )
    return OptimisationLineage(
        request_sha256=request_hash,
        candidate_snapshot_sha256=snapshot_hash(request.candidate_pool),
        gameweek_artifact_sha256=projection.result_sha256 or semantic_sha256(projection),
        stage9_scenario_set_sha256=semantic_sha256(projection.scenario_set),
        stage9_joint_matrix_sha256=semantic_sha256(projection.joint_matrix),
        ruleset_hash=rules.ruleset_hash,
        capability_hash=capability.capability_hash if capability else None,
        input_sha256=input_hash,
        policy_sha256=policy_hash,
        plan_sha256=plan_sha256,
        result_sha256=result_sha256,
    )


def _blocked(
    request: OneGameweekOptimisationRequest,
    projection: GameweekProjectionResult,
    rules: CompiledRuleset,
    capability: CapabilityArtifact | None,
    code: str,
    message: str,
    *,
    status: OptimisationStatus = OptimisationStatus.BLOCKED,
    solver_status: SolverStatus | None = None,
    policy: OneGameweekOptimiserPolicy | None = None,
) -> OneGameweekOptimisationResult:
    lineage = _lineage(request, projection, rules, capability, policy=policy)
    if solver_status is None:
        if status is OptimisationStatus.INFEASIBLE:
            solver_status = SolverStatus(termination="INFEASIBLE")
        elif status is OptimisationStatus.RESOURCE_LIMIT:
            solver_status = SolverStatus(termination="RESOURCE_LIMIT")
        else:
            solver_status = SolverStatus(termination="BLOCKED")
    result = OneGameweekOptimisationResult(
        status=status,
        request_id=request.request_id,
        gameweek_id=request.gameweek_id,
        search_scope=request.search_scope,
        optimality_guarantee=OptimalityGuarantee.NONE,
        solver_status=solver_status,
        lineage=lineage,
        upstream_mc_status=projection.monte_carlo.stopping_result,
        upstream_warnings=projection.scenario_set.warnings,
        explanations=(ExplanationItem(code=code, message=message),),
        error_code=code,
        error_message=message,
    )
    digest = _hash_without(result, "result_sha256")
    return result.model_copy(
        update={
            "result_sha256": digest,
            "lineage": lineage.model_copy(update={"result_sha256": digest}),
        }
    )


def optimise_one_gameweek(
    request: OneGameweekOptimisationRequest,
    projection: GameweekProjectionResult,
    rules: CompiledRuleset,
    *,
    capability: CapabilityArtifact | None = None,
    policy: OneGameweekOptimiserPolicy | None = None,
) -> OneGameweekOptimisationResult:
    """Execute the frozen gate sequence and exact search."""

    policy = policy or load_policy()
    try:
        validate_request_boundary(request)
        validate_stage9_boundary(request, projection, ruleset_hash=rules.ruleset_hash)
        view = build_one_gameweek_rules_view(
            rules, projection_mode=request.projection_mode, capability=capability
        )
        if request.projection_mode is ProjectionMode.PRODUCTION:
            # The frozen Stage-9 public object does not carry independently provable cutoff
            # lineage.  Request fields cannot supply that authority, and this check is reached
            # only after the derived FULL_SEASON capability gate above has passed.
            return _blocked(
                request,
                projection,
                rules,
                capability,
                "STAGE9_CUTOFF_LINEAGE_UNAVAILABLE",
                "production Stage-9 cutoff lineage is unavailable",
                policy=policy,
            )
        if projection.monte_carlo.stopping_result == "CONTINUE":
            return _blocked(
                request,
                projection,
                rules,
                capability,
                "UPSTREAM_MONTE_CARLO_CONTINUE",
                "Stage-9 Monte Carlo stopping status is CONTINUE",
                policy=policy,
            )
        if projection.monte_carlo.stopping_result == "BLOCKED":
            return _blocked(
                request,
                projection,
                rules,
                capability,
                "UPSTREAM_MONTE_CARLO_BLOCKED",
                "Stage-9 Monte Carlo stopping status is BLOCKED",
                policy=policy,
            )
        output = solve(request, projection.scenario_set.scenarios, view, policy)
        if not output.plans:
            raise InfeasibleError("solver returned no plan")
        for plan in output.plans:
            report = validate_plan_against_request(
                request, projection, rules, plan, capability=capability
            )
            if not report.legal:
                return _blocked(
                    request,
                    projection,
                    rules,
                    capability,
                    "OPTIMISER_EMITTED_ILLEGAL_PLAN",
                    "independent legality validation rejected the emitted plan",
                    solver_status=output.status,
                    policy=policy,
                )
        plans = []
        for plan in output.plans:
            plan_hash = _hash_without(plan, "plan_sha256")
            plans.append(plan.model_copy(update={"plan_sha256": plan_hash}))
        recommended = plans[0]
        lineage = _lineage(
            request,
            projection,
            rules,
            capability,
            policy=policy,
            plan_sha256=recommended.plan_sha256,
        )
        result = OneGameweekOptimisationResult(
            status=OptimisationStatus.SUCCESS,
            request_id=request.request_id,
            gameweek_id=request.gameweek_id,
            search_scope=request.search_scope,
            optimality_guarantee=_guarantee(request.search_scope),
            recommended_plan=recommended,
            tied_plans=tuple(plans),
            solver_status=output.status,
            lineage=lineage,
            upstream_mc_status=projection.monte_carlo.stopping_result,
            upstream_warnings=projection.scenario_set.warnings,
            explanations=(
                ExplanationItem(
                    code="EXACT_EXHAUSTIVE_SEARCH",
                    message="all plans in the declared scope were enumerated",
                ),
            ),
        )
        digest = _hash_without(result, "result_sha256")
        return result.model_copy(
            update={
                "result_sha256": digest,
                "lineage": lineage.model_copy(update={"result_sha256": digest}),
            }
        )
    except ResourceLimitError as exc:
        return _blocked(
            request,
            projection,
            rules,
            capability,
            exc.code,
            exc.message,
            status=OptimisationStatus.RESOURCE_LIMIT,
            solver_status=exc.solver_status
            if isinstance(exc.solver_status, SolverStatus)
            else None,
            policy=policy,
        )
    except InfeasibleError as exc:
        return _blocked(
            request,
            projection,
            rules,
            capability,
            exc.code,
            exc.message,
            status=OptimisationStatus.INFEASIBLE,
            policy=policy,
        )
    except RulesValidationError as exc:
        return _blocked(request, projection, rules, capability, exc.code, str(exc), policy=policy)
    except OptimisationError as exc:
        return _blocked(
            request, projection, rules, capability, exc.code, exc.message, policy=policy
        )
