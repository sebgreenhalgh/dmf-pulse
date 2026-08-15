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
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view


def _hash_without(value: Any, field: str) -> str:
    payload = value.model_dump(mode="json")
    payload[field] = None
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
    plan_sha256: str | None = None,
    result_sha256: str | None = None,
) -> OptimisationLineage:
    request_hash = _hash_without(request, "request_sha256")
    input_hash = semantic_sha256(
        {
            "request_sha256": request_hash,
            "candidate_snapshot_sha256": snapshot_hash(request.candidate_pool),
            "gameweek_result_sha256": projection.result_sha256,
            "ruleset_hash": rules.ruleset_hash,
            "capability_hash": capability.capability_hash if capability else None,
        }
    )
    return OptimisationLineage(
        request_sha256=request_hash,
        candidate_snapshot_sha256=snapshot_hash(request.candidate_pool),
        gameweek_artifact_sha256=projection.result_sha256 or semantic_sha256(projection),
        ruleset_hash=rules.ruleset_hash,
        capability_hash=capability.capability_hash if capability else None,
        input_sha256=input_hash,
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
) -> OneGameweekOptimisationResult:
    lineage = _lineage(request, projection, rules, capability)
    result = OneGameweekOptimisationResult(
        status=status,
        search_scope=request.search_scope,
        optimality_guarantee=OptimalityGuarantee.NONE,
        solver_status=solver_status or SolverStatus(),
        lineage=lineage,
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
        request_hash = _hash_without(request, "request_sha256")
        if request.request_sha256 is not None and request.request_sha256 != request_hash:
            raise OptimisationError("OPTIMISATION_INPUT_INVALID", "request semantic hash mismatch")
        actual_snapshot = snapshot_hash(request.candidate_pool)
        if (
            request.candidate_pool.candidate_snapshot_sha256 is not None
            and request.candidate_pool.candidate_snapshot_sha256 != actual_snapshot
        ):
            raise OptimisationError(
                "OPTIMISATION_INPUT_INVALID", "candidate snapshot hash mismatch"
            )
        if request.gameweek_id != projection.scenario_set.gameweek_id:
            raise OptimisationError(
                "STAGE9_CONTRACT_MISMATCH", "request and Stage-9 Gameweek IDs differ"
            )
        if projection.scenario_set.ruleset_hash != rules.ruleset_hash:
            raise OptimisationError(
                "RULESET_IDENTITY_MISMATCH", "Stage-9 and compiled ruleset hashes differ"
            )
        if projection.monte_carlo.stopping_result == "CONTINUE":
            return _blocked(
                request,
                projection,
                rules,
                capability,
                "UPSTREAM_MONTE_CARLO_CONTINUE",
                "Stage-9 Monte Carlo stopping status is CONTINUE",
            )
        if projection.monte_carlo.stopping_result == "BLOCKED":
            return _blocked(
                request,
                projection,
                rules,
                capability,
                "UPSTREAM_MONTE_CARLO_BLOCKED",
                "Stage-9 Monte Carlo stopping status is BLOCKED",
            )
        if (
            request.projection_mode is ProjectionMode.PRODUCTION
            and request.information_cutoff_utc is None
        ):
            # Capability is checked first so the current target returns the frozen capability error.
            build_one_gameweek_rules_view(
                rules, projection_mode=request.projection_mode, capability=capability
            )
            return _blocked(
                request,
                projection,
                rules,
                capability,
                "STAGE9_CUTOFF_LINEAGE_UNAVAILABLE",
                "production Stage-9 cutoff lineage is unavailable",
            )
        view = build_one_gameweek_rules_view(
            rules, projection_mode=request.projection_mode, capability=capability
        )
        output = solve(request, projection.scenario_set.scenarios, view, policy)
        if not output.plans:
            raise InfeasibleError("solver returned no plan")
        for plan in output.plans:
            if not plan.legality_report.legal:
                return _blocked(
                    request,
                    projection,
                    rules,
                    capability,
                    "OPTIMISER_EMITTED_ILLEGAL_PLAN",
                    "independent legality validation rejected the emitted plan",
                    solver_status=output.status,
                )
        plans = []
        for plan in output.plans:
            plan_hash = _hash_without(plan, "plan_sha256")
            plans.append(plan.model_copy(update={"plan_sha256": plan_hash}))
        recommended = plans[0]
        lineage = _lineage(
            request, projection, rules, capability, plan_sha256=recommended.plan_sha256
        )
        result = OneGameweekOptimisationResult(
            status=OptimisationStatus.SUCCESS,
            search_scope=request.search_scope,
            optimality_guarantee=_guarantee(request.search_scope),
            recommended_plan=recommended,
            tied_plans=tuple(plans),
            solver_status=output.status,
            lineage=lineage,
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
        )
    except RulesValidationError as exc:
        return _blocked(request, projection, rules, capability, exc.code, str(exc))
    except OptimisationError as exc:
        return _blocked(request, projection, rules, capability, exc.code, exc.message)
