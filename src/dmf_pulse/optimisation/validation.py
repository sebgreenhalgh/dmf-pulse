"""Independent plan validation entry point."""

from __future__ import annotations

from typing import Any

from dmf_pulse.fpl_points.artifacts import canonical_json_bytes, semantic_sha256, sha256_bytes
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
    stage9_players = set(player_ids)
    if request.search_scope.value == "FIXED_SQUAD":
        selected_players = set(request.fixed_squad_ids or ())
    elif request.search_scope.value == "PROVIDED_SQUADS":
        selected_players = {
            player_id
            for squad in request.provided_candidate_squads
            for player_id in squad.player_ids
        }
    else:
        selected_players = {player.player_id for player in request.candidate_pool.players}
    if not selected_players <= stage9_players:
        raise OptimisationError(
            "STAGE9_CONTRACT_MISMATCH",
            "declared search scope contains a player outside the Stage-9 universe",
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
    if request.request_sha256 != request_hash:
        raise OptimisationError("OPTIMISATION_INPUT_INVALID", "request semantic hash mismatch")
    actual_snapshot = snapshot_hash(request.candidate_pool)
    if request.candidate_pool.snapshot_sha256 != actual_snapshot:
        raise OptimisationError("OPTIMISATION_INPUT_INVALID", "candidate snapshot hash mismatch")
    if request.information_cutoff_utc != request.candidate_pool.information_cutoff_utc:
        raise OptimisationError(
            "OPTIMISATION_INPUT_INVALID",
            "request and candidate snapshot information cutoffs differ",
        )


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
    if plan.plan_sha256 != _hash_without(plan, "plan_sha256"):
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
            search_scope=request.search_scope,
            report_budget=request.search_scope.value == "BOUNDED_PLAYER_POOL",
        )
        actual_payload = plan.model_dump(mode="json")
        expected_payload = expected_plan.model_dump(mode="json")
        for field in ("plan_sha256", "solver_status", "explanations"):
            actual_payload.pop(field)
            expected_payload.pop(field)
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
    stage9_artifact_hash = sha256_bytes(canonical_json_bytes(projection))
    manager_capability = capability.capability.value if capability is not None else None
    manager_capability_hash = capability.capability_hash if capability is not None else None
    expected_input_hash = semantic_sha256(
        {
            "request_sha256": request_hash,
            "candidate_pool_sha256": snapshot,
            "stage9_result_sha256": projection.result_sha256,
            "stage9_artifact_sha256": stage9_artifact_hash,
            "stage9_scenario_set_sha256": semantic_sha256(projection.scenario_set),
            "stage9_joint_matrix_sha256": semantic_sha256(projection.joint_matrix),
            "ruleset_hash": rules.ruleset_hash,
            "manager_capability": manager_capability,
            "manager_capability_hash": manager_capability_hash,
            "policy_sha256": policy_hash,
        }
    )
    lineage = result.lineage
    if (
        result.request_id != request.request_id
        or result.gameweek_id != request.gameweek_id
        or result.search_scope is not request.search_scope
        or result.optimality_guarantee.value
        != {
            "FIXED_SQUAD": "EXACT_FIXED_SQUAD",
            "PROVIDED_SQUADS": "EXACT_PROVIDED_SET",
            "BOUNDED_PLAYER_POOL": "EXACT_DECLARED_PLAYER_POOL",
        }[request.search_scope.value]
        or result.upstream_mc_status != projection.monte_carlo.stopping_result
        or result.upstream_warnings != projection.scenario_set.warnings
        or lineage.request_sha256 != request_hash
        or lineage.candidate_pool_sha256 != snapshot
        or lineage.stage9_result_sha256 != projection.result_sha256
        or lineage.stage9_artifact_sha256 != stage9_artifact_hash
        or lineage.stage9_scenario_set_sha256 != semantic_sha256(projection.scenario_set)
        or lineage.stage9_joint_matrix_sha256 != semantic_sha256(projection.joint_matrix)
        or lineage.ruleset_hash != rules.ruleset_hash
        or lineage.manager_capability != manager_capability
        or lineage.manager_capability_hash != manager_capability_hash
        or lineage.policy_sha256 != policy_hash
        or lineage.input_sha256 != expected_input_hash
    ):
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", "result lineage does not bind inputs"
        )
    plans = result.tied_optimal_plans
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
    if len({plan.signature for plan in plans}) != len(plans):
        issues += (
            LegalityIssue(
                code="RESULT_DUPLICATE_TIE",
                message="result contains duplicate tied plans",
            ),
        )
    if any(plan.expected_manager_points != plans[0].expected_manager_points for plan in plans):
        issues += (
            LegalityIssue(
                code="RESULT_NON_TIED_PLAN",
                message="returned plans do not have exactly equal objectives",
            ),
        )
    from dmf_pulse.optimisation.service import optimise_one_gameweek

    recomputed = optimise_one_gameweek(
        request,
        projection,
        rules,
        capability=capability,
        policy=policy,
    )
    if recomputed != result:
        issues += (
            LegalityIssue(
                code="RESULT_RECOMPUTATION_MISMATCH",
                message="result does not match a fresh exact deterministic optimisation",
            ),
        )
    return LegalityReport(legal=not issues, issues=issues)
