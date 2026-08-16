"""Independent plan validation entry point."""

from __future__ import annotations

from typing import Any

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import GameweekProjectionResult
from dmf_pulse.optimisation.candidate_pool import snapshot_hash
from dmf_pulse.optimisation.errors import OptimisationError
from dmf_pulse.optimisation.legality import validate_squad_legality, validate_tactical_configuration
from dmf_pulse.optimisation.models import (
    LegalityIssue,
    LegalityReport,
    OneGameweekOptimisationRequest,
    OneGameweekOptimisationResult,
    OneGameweekPlan,
    OptimisationStatus,
)
from dmf_pulse.optimisation.policy import load_policy
from dmf_pulse.optimisation.tactics import evaluate_tactical_configuration
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view


def _hash_without(value: Any, field: str) -> str:
    payload = value.model_dump(mode="json")
    payload[field] = None
    if field == "result_sha256" and isinstance(payload.get("lineage"), dict):
        payload["lineage"]["result_sha256"] = None
    return semantic_sha256(payload)


def validate_stage9_boundary(
    request: OneGameweekOptimisationRequest,
    projection: GameweekProjectionResult,
    *,
    ruleset_hash: str,
) -> None:
    """Fail closed unless Stage-9's scenario and matrix identities agree exactly.

    Stage 10 consumes the accepted Gameweek projection as one coherent object.  This check is
    intentionally performed before candidate generation so no search can proceed from a
    reordered, weakened, or separately reconstructed scenario representation.
    """

    if projection.result_sha256 != _hash_without(projection, "result_sha256"):
        raise OptimisationError(
            "STAGE9_CONTRACT_MISMATCH", "Stage-9 projection semantic hash mismatch"
        )
    scenarios = projection.scenario_set.scenarios
    matrix = projection.joint_matrix
    player_ids = projection.scenario_set.player_ids
    if request.gameweek_id != projection.scenario_set.gameweek_id:
        raise OptimisationError(
            "STAGE9_CONTRACT_MISMATCH", "request and Stage-9 Gameweek IDs differ"
        )
    if projection.scenario_set.ruleset_hash != ruleset_hash or matrix.ruleset_hash != ruleset_hash:
        raise OptimisationError(
            "RULESET_IDENTITY_MISMATCH", "Stage-9 and compiled ruleset hashes differ"
        )
    if matrix.player_ids != player_ids:
        raise OptimisationError(
            "STAGE9_CONTRACT_MISMATCH", "Stage-9 player ordering differs from the joint matrix"
        )
    expected_ids = tuple(scenario.scenario_id for scenario in scenarios)
    expected_draws = tuple(scenario.outcome_draw_id for scenario in scenarios)
    expected_weights = tuple(scenario.weight for scenario in scenarios)
    expected_points = tuple(
        tuple(scenario.player_points[player_id] for player_id in player_ids)
        for scenario in scenarios
    )
    if (
        matrix.scenario_ids != expected_ids
        or matrix.outcome_draw_ids != expected_draws
        or matrix.weights != expected_weights
        or matrix.points != expected_points
    ):
        raise OptimisationError(
            "STAGE9_CONTRACT_MISMATCH",
            "Stage-9 scenario set and joint matrix are not exactly aligned",
        )


def validate_request_boundary(request: OneGameweekOptimisationRequest) -> None:
    """Validate caller-provided semantic identities before any Stage-10 computation."""

    request_hash = _hash_without(request, "request_sha256")
    if request.request_sha256 is not None and request.request_sha256 != request_hash:
        raise OptimisationError("OPTIMISATION_INPUT_INVALID", "request semantic hash mismatch")
    actual_snapshot = snapshot_hash(request.candidate_pool)
    if (
        request.candidate_pool.candidate_snapshot_sha256 is not None
        and request.candidate_pool.candidate_snapshot_sha256 != actual_snapshot
    ):
        raise OptimisationError("OPTIMISATION_INPUT_INVALID", "candidate snapshot hash mismatch")


def validate_plan_against_request(
    request: OneGameweekOptimisationRequest,
    projection: GameweekProjectionResult,
    rules: CompiledRuleset,
    plan: OneGameweekPlan,
    *,
    capability: CapabilityArtifact | None = None,
) -> LegalityReport:
    validate_request_boundary(request)
    validate_stage9_boundary(request, projection, ruleset_hash=rules.ruleset_hash)
    if plan.plan_sha256 is not None and plan.plan_sha256 != _hash_without(plan, "plan_sha256"):
        raise OptimisationError("OPTIMISATION_ARTIFACT_INVALID", "plan semantic hash mismatch")
    view = build_one_gameweek_rules_view(
        rules, projection_mode=request.projection_mode, capability=capability
    )
    players = {item.player_id: item for item in request.candidate_pool.candidates}
    squad_report = validate_squad_legality(
        plan.candidate_squad,
        players,
        view,
        required_player_ids=request.required_player_ids,
        excluded_player_ids=request.excluded_player_ids,
        stage9_player_ids=projection.scenario_set.player_ids,
        enforce_budget=request.search_scope.value == "BOUNDED_PLAYER_POOL",
    )
    tactic_report = validate_tactical_configuration(
        plan.candidate_squad, plan.tactical_configuration, players, view
    )
    issues = squad_report.issues + tactic_report.issues
    recomputed = LegalityReport(legal=not issues, issues=issues)
    if plan.legality_report != recomputed:
        issues += (
            LegalityIssue(
                code="PLAN_LEGALITY_REPORT_MISMATCH",
                message="plan carries a stale or tampered legality report",
            ),
        )
    if not issues:
        expected_plan, _ = evaluate_tactical_configuration(
            plan.candidate_squad,
            plan.tactical_configuration,
            projection.scenario_set.scenarios,
            players,
            view,
        )
        actual_payload = plan.model_dump(mode="json")
        actual_payload["plan_sha256"] = None
        expected_payload = expected_plan.model_dump(mode="json")
        expected_payload["plan_sha256"] = None
        if actual_payload != expected_payload:
            issues += (
                LegalityIssue(
                    code="PLAN_EVALUATION_MISMATCH",
                    message="plan score or distribution does not match its declared inputs",
                ),
            )
    return LegalityReport(legal=not issues, issues=issues)


def validate_result_against_request(
    request: OneGameweekOptimisationRequest,
    projection: GameweekProjectionResult,
    rules: CompiledRuleset,
    result: OneGameweekOptimisationResult,
    *,
    capability: CapabilityArtifact | None = None,
) -> LegalityReport:
    """Substantively revalidate an immutable success result for ``validate-plan``."""

    validate_request_boundary(request)
    validate_stage9_boundary(request, projection, ruleset_hash=rules.ruleset_hash)
    if result.status is not OptimisationStatus.SUCCESS or result.recommended_plan is None:
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", "validate-plan accepts only successful exact results"
        )
    if result.result_sha256 is None or result.result_sha256 != _hash_without(
        result, "result_sha256"
    ):
        raise OptimisationError("OPTIMISATION_ARTIFACT_INVALID", "result semantic hash mismatch")
    policy = load_policy()
    request_hash = _hash_without(request, "request_sha256")
    snapshot = snapshot_hash(request.candidate_pool)
    policy_hash = semantic_sha256(policy)
    expected_input_hash = semantic_sha256(
        {
            "request_sha256": request_hash,
            "candidate_snapshot_sha256": snapshot,
            "gameweek_result_sha256": projection.result_sha256,
            "ruleset_hash": rules.ruleset_hash,
            "capability_hash": capability.capability_hash if capability else None,
            "policy_sha256": policy_hash,
        }
    )
    lineage = result.lineage
    if (
        result.request_id != request.request_id
        or result.gameweek_id != request.gameweek_id
        or lineage.request_sha256 != request_hash
        or lineage.candidate_snapshot_sha256 != snapshot
        or lineage.gameweek_artifact_sha256 != projection.result_sha256
        or lineage.stage9_scenario_set_sha256 != semantic_sha256(projection.scenario_set)
        or lineage.stage9_joint_matrix_sha256 != semantic_sha256(projection.joint_matrix)
        or lineage.ruleset_hash != rules.ruleset_hash
        or lineage.capability_hash != (capability.capability_hash if capability else None)
        or lineage.policy_sha256 != policy_hash
        or lineage.input_sha256 != expected_input_hash
        or lineage.plan_sha256 != result.recommended_plan.plan_sha256
        or lineage.result_sha256 != result.result_sha256
    ):
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", "result lineage does not bind inputs"
        )
    plans = result.tied_plans
    if not plans or result.recommended_plan.signature != min(plan.signature for plan in plans):
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", "result recommendation is not canonical among ties"
        )
    issues: tuple[LegalityIssue, ...] = ()
    for plan in plans:
        report = validate_plan_against_request(
            request, projection, rules, plan, capability=capability
        )
        issues += report.issues
    return LegalityReport(legal=not issues, issues=issues)
