"""Shared Stage-15 application service for rank-aware plan re-evaluation.

The service consumes only accepted upstream plans and sealed diagnostics. It does
not call, replace, or mutate the Stage-9 to Stage-14 projection and optimisation
engines. Rank affects plan utility only.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import ValidationError

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import GameweekScenarioSet
from dmf_pulse.optimisation.models import CandidatePlayer, OneGameweekRulesView
from dmf_pulse.prices.models import ActivationStatus as PriceActivationStatus
from dmf_pulse.prices.models import ConfidenceGrade
from dmf_pulse.rank_strategy.effective_ownership import calculate_effective_ownership
from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.mini_league import simulate_mini_league_rank
from dmf_pulse.rank_strategy.models import (
    CohortSample,
    EffectiveOwnershipReport,
    ManagerMultiplierPolicy,
    ManagerMultiplierSet,
    ManagerTeamPlan,
    RankDistribution,
    RankTiePolicy,
)
from dmf_pulse.rank_strategy.opponent_actions import (
    combine_opponent_action_distributions,
    model_opponent_actions,
)
from dmf_pulse.rank_strategy.opponent_models import (
    JointOpponentActionDistribution,
    OpponentActionCandidate,
    OpponentActionDistribution,
    OpponentBehaviourProfile,
    OpponentObservedState,
)
from dmf_pulse.rank_strategy.rank_utility import evaluate_rank_strategy
from dmf_pulse.rank_strategy.service_models import (
    AcceptedRankPlan,
    RankCapabilityValidation,
    RankGateCheck,
    RankGateName,
    RankGateReport,
    RankServiceLineage,
    RankServiceProjectionEvidence,
    RankServiceRequest,
    RankServiceResult,
)
from dmf_pulse.rank_strategy.synthetic_field import simulate_synthetic_overall_rank
from dmf_pulse.rank_strategy.synthetic_models import (
    SyntheticOverallPopulation,
    SyntheticOverallRankResult,
)
from dmf_pulse.rank_strategy.utility_models import (
    RankActivationStatus,
    RankObjectiveMode,
    RankPlanCandidate,
    RankStrategyDecision,
)

_ZERO_HASH = "0" * 64
_CONFIDENCE_ORDER = {
    ConfidenceGrade.A: 0,
    ConfidenceGrade.B: 1,
    ConfidenceGrade.C: 2,
    ConfidenceGrade.D: 3,
    ConfidenceGrade.E: 4,
}
_LIMITED_PRICE_STATUSES = {
    PriceActivationStatus.SHADOW_ONLY,
    PriceActivationStatus.TARGET_SEASON_UNCALIBRATED,
    PriceActivationStatus.RIGHTS_BLOCKED,
    PriceActivationStatus.INSUFFICIENT_EVENTS,
    PriceActivationStatus.CALIBRATION_BLOCKED,
}


def _seal_lineage(value: RankServiceLineage) -> RankServiceLineage:
    payload = value.model_dump(mode="json", exclude={"lineage_hash"})
    return RankServiceLineage.model_validate(
        value.model_copy(update={"lineage_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def _seal_plan(value: AcceptedRankPlan) -> AcceptedRankPlan:
    payload = value.model_dump(mode="json", exclude={"binding_hash"})
    return AcceptedRankPlan.model_validate(
        value.model_copy(update={"binding_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def bind_accepted_plan(
    candidate: RankPlanCandidate,
    *,
    source_plan_hash: str,
    source_result_hash: str,
) -> AcceptedRankPlan:
    """Bind a Stage-15 candidate to immutable accepted upstream plan identities."""

    value = AcceptedRankPlan(
        plan_id=candidate.plan_id,
        source_stage=candidate.source_stage,
        source_plan_hash=source_plan_hash,
        source_result_hash=source_result_hash,
        candidate=candidate,
        binding_hash=_ZERO_HASH,
    )
    return _seal_plan(value)


def seal_rank_service_request(value: RankServiceRequest) -> RankServiceRequest:
    """Return a request with every nested semantic binding sealed deterministically."""

    policy_hash = semantic_sha256(value.policy.model_dump(mode="json"))
    lineage_unsealed = value.lineage.model_copy(
        update={"points_floor_hash": policy_hash, "lineage_hash": _ZERO_HASH}
    )
    lineage = _seal_lineage(RankServiceLineage.model_validate(lineage_unsealed.model_dump()))
    plans = tuple(
        _seal_plan(item.model_copy(update={"binding_hash": _ZERO_HASH})) for item in value.plans
    )
    unsealed = RankServiceRequest.model_validate(
        value.model_copy(
            update={
                "lineage": lineage,
                "plans": plans,
                "service_request_hash": _ZERO_HASH,
            }
        ).model_dump(mode="python")
    )
    payload = unsealed.model_dump(mode="json", exclude={"service_request_hash"})
    return RankServiceRequest.model_validate(
        unsealed.model_copy(update={"service_request_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def _verified_request(value: RankServiceRequest) -> RankServiceRequest:
    try:
        checked = RankServiceRequest.model_validate(value.model_dump(mode="python"))
    except ValidationError as exc:
        raise RankStrategyError(
            "RANK_SERVICE_REQUEST_INVALID",
            "rank service request violates the sealed application contract",
        ) from exc
    if checked.service_request_hash == _ZERO_HASH:
        raise RankStrategyError(
            "RANK_SERVICE_REQUEST_UNSEALED",
            "rank service requires a sealed request",
        )
    if checked.lineage.lineage_hash == _ZERO_HASH:
        raise RankStrategyError(
            "RANK_SERVICE_LINEAGE_UNSEALED",
            "rank service requires sealed upstream lineage",
        )
    if any(item.binding_hash == _ZERO_HASH for item in checked.plans):
        raise RankStrategyError(
            "RANK_SERVICE_PLAN_UNSEALED",
            "rank service requires sealed accepted plan bindings",
        )
    expected = semantic_sha256(checked.model_dump(mode="json", exclude={"service_request_hash"}))
    if checked.service_request_hash != expected:
        raise RankStrategyError(
            "RANK_SERVICE_REQUEST_HASH_MISMATCH",
            "rank service request hash does not match its semantic payload",
        )
    return checked


def _same_scenario_surface(plans: tuple[AcceptedRankPlan, ...], expected_hash: str) -> bool:
    baseline = plans[0].candidate
    baseline_ids = tuple(baseline.scenario_points)
    baseline_weights = baseline.scenario_weights
    return all(
        item.candidate.scenario_set_hash == expected_hash
        and tuple(item.candidate.scenario_points) == baseline_ids
        and item.candidate.scenario_weights == baseline_weights
        for item in plans
    )


def _target_gate_passes(request: RankServiceRequest) -> tuple[bool, str | None]:
    if request.objective is RankObjectiveMode.PURE_POINTS:
        return True, None
    if not request.context.user_selected_explicit_target:
        return False, "RANK_TARGET_NOT_USER_SELECTED"
    if not request.context.target_rules_active:
        return False, "TARGET_RULES_INACTIVE"
    target = request.target
    if request.objective in {
        RankObjectiveMode.MEASURED_LEVERAGE,
        RankObjectiveMode.MINI_LEAGUE_WIN,
    }:
        if (
            request.objective is RankObjectiveMode.MINI_LEAGUE_WIN
            and target is not None
            and (target.target_rank not in {None, 1} or target.band_best_rank is not None)
        ):
            return False, "TARGET_DEFINITION_INVALID"
        return True, None
    if request.objective in {RankObjectiveMode.TARGET_RANK, RankObjectiveMode.RANK_PROTECTION}:
        if target is None or target.target_rank is None:
            return False, "TARGET_RANK_UNDEFINED"
        return True, None
    if target is None or target.band_best_rank is None or target.band_worst_rank is None:
        return False, "RANK_BAND_UNDEFINED"
    if request.objective is RankObjectiveMode.PRIZE_BAND and target.prize_band_id is None:
        return False, "PRIZE_BAND_UNDEFINED"
    if request.objective is RankObjectiveMode.RANK_BAND and target.prize_band_id is not None:
        return False, "TARGET_DEFINITION_INVALID"
    return True, None


def _gate(
    name: RankGateName,
    *,
    required: bool,
    passed: bool,
    reason: str,
) -> RankGateCheck:
    return RankGateCheck(
        name=name,
        required=required,
        passed=passed or not required,
        reason_code=None if passed or not required else reason,
    )


def _seal_gate_report(checks: Iterable[RankGateCheck]) -> RankGateReport:
    ordered = tuple(sorted(checks, key=lambda item: item.name.value))
    executable = all(item.passed for item in ordered if item.required)
    unsealed = RankGateReport.model_construct(
        checks=ordered,
        executable_rank_utility=executable,
        report_hash=_ZERO_HASH,
    )
    payload = unsealed.model_dump(mode="json", exclude={"report_hash"})
    return RankGateReport(
        checks=ordered,
        executable_rank_utility=executable,
        report_hash=semantic_sha256(payload),
    )


def _projection_evidence(
    request: RankServiceRequest,
    *,
    before: dict[str, str],
    after: dict[str, str],
    common_raw: bool,
    common_scenarios: bool,
) -> RankServiceProjectionEvidence:
    unsealed = RankServiceProjectionEvidence.model_construct(
        unchanged=True,
        expected_raw_projection_hash=request.lineage.raw_projection_hash,
        expected_scenario_set_hash=request.lineage.scenario_set_hash,
        common_raw_projection_lineage=common_raw,
        common_scenario_lineage=common_scenarios,
        before_score_hashes=dict(sorted(before.items())),
        after_score_hashes=dict(sorted(after.items())),
        evidence_hash=_ZERO_HASH,
    )
    payload = unsealed.model_dump(mode="json", exclude={"evidence_hash"})
    return RankServiceProjectionEvidence(
        unchanged=True,
        expected_raw_projection_hash=request.lineage.raw_projection_hash,
        expected_scenario_set_hash=request.lineage.scenario_set_hash,
        common_raw_projection_lineage=common_raw,
        common_scenario_lineage=common_scenarios,
        before_score_hashes=dict(sorted(before.items())),
        after_score_hashes=dict(sorted(after.items())),
        evidence_hash=semantic_sha256(payload),
    )


def _worst_confidence(
    request: RankServiceRequest, decision: RankStrategyDecision | None
) -> ConfidenceGrade:
    values = [request.context.rank_model_confidence]
    if decision is not None and decision.rank_optimal_metrics.confidence is not None:
        values.append(decision.rank_optimal_metrics.confidence)
    if _LIMITED_PRICE_STATUSES.intersection(request.lineage.stage13_activation_statuses):
        values.append(ConfidenceGrade.D)
    return max(values, key=_CONFIDENCE_ORDER.__getitem__)


def _confidence_sufficient(actual: ConfidenceGrade, minimum: ConfidenceGrade) -> bool:
    return _CONFIDENCE_ORDER[actual] <= _CONFIDENCE_ORDER[minimum]


def _build_gate_report(
    request: RankServiceRequest,
    *,
    decision: RankStrategyDecision | None,
    common_raw: bool,
    common_scenarios: bool,
) -> RankGateReport:
    rank_required = request.objective is not RankObjectiveMode.PURE_POINTS
    target_passed, target_reason = _target_gate_passes(request)
    confidence = _worst_confidence(request, decision)
    fallback = set(() if decision is None else decision.fallback_reasons)
    price_rights_valid = (
        PriceActivationStatus.RIGHTS_BLOCKED not in request.lineage.stage13_activation_statuses
    )
    checks = (
        _gate(
            RankGateName.RULES,
            required=rank_required,
            passed=request.context.rules_verified,
            reason="RANK_RULES_UNVERIFIED",
        ),
        _gate(
            RankGateName.TARGET,
            required=rank_required,
            passed=target_passed,
            reason=target_reason or "RANK_TARGET_INVALID",
        ),
        _gate(
            RankGateName.RIGHTS,
            required=rank_required,
            passed=(
                request.context.rights_valid
                and request.lineage.rights_status.permitted
                and price_rights_valid
            ),
            reason=(
                "RANK_SAMPLE_RIGHTS_INVALID"
                if price_rights_valid
                else "STAGE13_RIGHTS_BLOCKED_PROPAGATED"
            ),
        ),
        _gate(
            RankGateName.COHORT,
            required=rank_required,
            passed=request.context.cohort_valid and request.lineage.cohort_model is not None,
            reason="RANK_COHORT_INVALID",
        ),
        _gate(
            RankGateName.OPPONENT_MODEL,
            required=rank_required,
            passed=(
                request.context.opponent_data_valid and request.lineage.opponent_model is not None
            ),
            reason="RANK_OPPONENT_DATA_INVALID",
        ),
        _gate(
            RankGateName.CONFIDENCE,
            required=rank_required,
            passed=_confidence_sufficient(confidence, request.policy.minimum_rank_confidence),
            reason="RANK_CONFIDENCE_TOO_LOW",
        ),
        _gate(
            RankGateName.PROJECTION_LINEAGE,
            required=True,
            passed=common_raw,
            reason="RANK_RAW_PROJECTION_LINEAGE_MISMATCH",
        ),
        _gate(
            RankGateName.SCENARIO_LINEAGE,
            required=True,
            passed=common_scenarios,
            reason="RANK_SCENARIO_LINEAGE_MISMATCH",
        ),
        _gate(
            RankGateName.POINTS_FLOOR,
            required=rank_required,
            passed=(
                decision is not None
                and decision.rank_optimal_metrics.points_floor_satisfied
                and "NO_ELIGIBLE_RANK_PLAN" not in fallback
            ),
            reason="RANK_POINTS_FLOOR_UNSATISFIED",
        ),
        _gate(
            RankGateName.EARLY_SEASON_POLICY,
            required=rank_required,
            passed="EARLY_SEASON_MATERIAL_POINTS_GATE" not in fallback,
            reason="EARLY_SEASON_MATERIAL_POINTS_GATE",
        ),
    )
    return _seal_gate_report(checks)


def _seal_result(value: RankServiceResult) -> RankServiceResult:
    payload = value.model_dump(mode="json", exclude={"result_hash"})
    return RankServiceResult.model_validate(
        value.model_copy(update={"result_hash": semantic_sha256(payload)}).model_dump(mode="python")
    )


def evaluate_rank_plans(request: RankServiceRequest) -> RankServiceResult:
    """Re-evaluate accepted Stage-12 to Stage-14 plans under Stage-15 utility.

    The accepted scenario points and raw projection identities are snapshotted
    before and after evaluation. Any activation or lineage failure selects the
    pure-points plan while retaining safe diagnostic output when available.
    """

    checked = _verified_request(request)
    plans = checked.plans
    candidates = tuple(item.candidate for item in plans)
    plan_by_id = {item.plan_id: item for item in plans}
    points_optimal = min(plans, key=lambda item: (-item.candidate.expected_points, item.plan_id))
    before = {item.plan_id: item.candidate.scenario_score_hash for item in plans}
    common_raw = all(
        item.candidate.raw_projection_hash == checked.lineage.raw_projection_hash for item in plans
    )
    common_scenarios = _same_scenario_surface(plans, checked.lineage.scenario_set_hash)

    decision: RankStrategyDecision | None = None
    evaluator_failure: str | None = None
    if common_raw and common_scenarios:
        try:
            decision = evaluate_rank_strategy(
                request_id=checked.request_id,
                objective=checked.objective,
                candidates=candidates,
                context=checked.context,
                policy=checked.policy,
                target=checked.target,
            )
        except RankStrategyError as exc:
            evaluator_failure = exc.code

    after = {item.plan_id: item.candidate.scenario_score_hash for item in plans}
    if before != after:
        raise RankStrategyError(
            "RANK_SERVICE_PROJECTION_MUTATION",
            "rank service mutated accepted scenario-score identities",
        )
    projection = _projection_evidence(
        checked,
        before=before,
        after=after,
        common_raw=common_raw,
        common_scenarios=common_scenarios,
    )
    gate_report = _build_gate_report(
        checked,
        decision=decision,
        common_raw=common_raw,
        common_scenarios=common_scenarios,
    )

    if decision is None:
        rank_optimal = points_optimal
        diagnostic_available = False
        reasons = {
            item.reason_code
            for item in gate_report.checks
            if item.required and not item.passed and item.reason_code is not None
        }
        if evaluator_failure is not None:
            reasons.add(evaluator_failure)
        status = (
            RankActivationStatus.DIAGNOSTIC_ONLY
            if checked.context.user_selected_explicit_target
            else RankActivationStatus.FALLBACK_PURE_POINTS
        )
        effective_objective = RankObjectiveMode.PURE_POINTS
        selected = points_optimal
        target_difference = None
    else:
        rank_optimal = plan_by_id[decision.rank_optimal_plan_id]
        diagnostic_available = True
        reasons = set(decision.fallback_reasons)
        reasons.update(
            item.reason_code
            for item in gate_report.checks
            if item.required and not item.passed and item.reason_code is not None
        )
        if (
            gate_report.executable_rank_utility
            and decision.activation_status is RankActivationStatus.ACTIVE
        ):
            status = RankActivationStatus.ACTIVE
            effective_objective = decision.effective_objective
            selected = plan_by_id[decision.selected_plan_id]
            reasons.clear()
        else:
            status = (
                RankActivationStatus.DIAGNOSTIC_ONLY
                if checked.context.user_selected_explicit_target
                else RankActivationStatus.FALLBACK_PURE_POINTS
            )
            effective_objective = RankObjectiveMode.PURE_POINTS
            selected = points_optimal
        target_difference = decision.target_probability_difference

    unsealed = RankServiceResult(
        request_id=checked.request_id,
        request_hash=checked.service_request_hash,
        requested_objective=checked.objective,
        effective_objective=effective_objective,
        activation_status=status,
        points_optimal_plan=points_optimal,
        rank_optimal_plan=rank_optimal,
        selected_plan=selected,
        expected_points_difference=(
            rank_optimal.candidate.expected_points - points_optimal.candidate.expected_points
        ),
        target_probability_difference=target_difference,
        rank_decision=decision,
        gate_report=gate_report,
        confidence=_worst_confidence(checked, decision),
        stage13_activation_statuses=checked.lineage.stage13_activation_statuses,
        diagnostic_output_available=diagnostic_available,
        fail_closed_reasons=tuple(sorted(reasons)),
        raw_projection_hash=checked.lineage.raw_projection_hash,
        scenario_set_hash=checked.lineage.scenario_set_hash,
        projection_invariance=projection,
        result_hash=_ZERO_HASH,
    )
    return _seal_result(unsealed)


def evaluate_effective_ownership(
    sample: CohortSample,
    scenario_set: GameweekScenarioSet,
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
    policy: ManagerMultiplierPolicy,
    *,
    sebastian_plan: ManagerTeamPlan | None = None,
) -> EffectiveOwnershipReport:
    """Expose the accepted EO engine through the shared Stage-15 service."""

    return calculate_effective_ownership(
        sample,
        scenario_set,
        players,
        rules,
        policy,
        sebastian_plan=sebastian_plan,
    )


def evaluate_exact_mini_league(
    sample: CohortSample,
    multiplier_sets: tuple[ManagerMultiplierSet, ...],
    tie_policy: RankTiePolicy,
    *,
    target_manager_id: str,
    target_rank: int | None = None,
) -> RankDistribution:
    """Expose exact shared-scenario mini-league simulation through the service."""

    return simulate_mini_league_rank(
        sample,
        multiplier_sets,
        tie_policy,
        target_manager_id=target_manager_id,
        target_rank=target_rank,
    )


def evaluate_opponent_actions(
    state: OpponentObservedState,
    candidates: tuple[OpponentActionCandidate, ...],
    profile: OpponentBehaviourProfile,
    *,
    additional_distributions: tuple[OpponentActionDistribution, ...] = (),
    max_joint_scenarios: int = 10_000,
) -> OpponentActionDistribution | JointOpponentActionDistribution:
    """Model one opponent and optionally form the exact joint marginal product."""

    current = model_opponent_actions(state, candidates, profile)
    if not additional_distributions:
        return current
    return combine_opponent_action_distributions(
        (current, *additional_distributions),
        max_joint_scenarios=max_joint_scenarios,
    )


def evaluate_synthetic_cohort(
    population: SyntheticOverallPopulation,
    multiplier_sets: tuple[ManagerMultiplierSet, ...],
    tie_policy: RankTiePolicy,
    *,
    target_rank: int | None = None,
) -> SyntheticOverallRankResult:
    """Expose the rights-gated synthetic overall simulator through the service."""

    return simulate_synthetic_overall_rank(
        population,
        multiplier_sets,
        tie_policy,
        target_rank=target_rank,
    )


def validate_rank_service_request(request: RankServiceRequest) -> RankServiceResult:
    """Validate a sealed request by executing the canonical application service."""

    return evaluate_rank_plans(request)


def validate_rank_service_requests(
    requests: Iterable[RankServiceRequest],
) -> tuple[str, ...]:
    """Validate multiple sealed requests and return deterministic result identities."""

    return tuple(evaluate_rank_plans(item).result_hash for item in requests)


def validate_installed_rank_capability() -> RankCapabilityValidation:
    """Return the installed Stage-15 public-capability contract."""

    commands = tuple(
        sorted(("cohort", "compare", "eo", "evaluate", "mini-league", "opponents", "validate"))
    )
    unsealed = RankCapabilityValidation.model_construct(
        status="REVIEW_READY_PENDING_HUMAN_ACCEPTANCE",
        shared_service_available=True,
        cli_commands=commands,
        fail_closed_to_pure_points=True,
        raw_projection_mutation_permitted=False,
        mass_manager_scraping_permitted=False,
        definitive_overall_win_claim_permitted=False,
        validation_hash=_ZERO_HASH,
    )
    payload = unsealed.model_dump(mode="json", exclude={"validation_hash"})
    return RankCapabilityValidation(
        cli_commands=commands,
        validation_hash=semantic_sha256(payload),
    )


__all__ = [
    "bind_accepted_plan",
    "evaluate_effective_ownership",
    "evaluate_exact_mini_league",
    "evaluate_opponent_actions",
    "evaluate_rank_plans",
    "evaluate_synthetic_cohort",
    "seal_rank_service_request",
    "validate_installed_rank_capability",
    "validate_rank_service_request",
    "validate_rank_service_requests",
]
