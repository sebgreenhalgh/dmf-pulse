"""Lexicographic Stage-15 rank utility with fail-closed activation gates."""

from __future__ import annotations

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.prices.models import ConfidenceGrade
from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.synthetic_models import SyntheticOverallDistribution
from dmf_pulse.rank_strategy.utility_models import (
    ProjectionInvarianceEvidence,
    RankActivationContext,
    RankActivationStatus,
    RankDistributionScope,
    RankObjectiveMode,
    RankPlanCandidate,
    RankPlanEvaluation,
    RankPlanMetrics,
    RankStrategyDecision,
    RankTargetDefinition,
    RankUtilityPolicy,
)

_CONFIDENCE_ORDER = {
    ConfidenceGrade.A: 0,
    ConfidenceGrade.B: 1,
    ConfidenceGrade.C: 2,
    ConfidenceGrade.D: 3,
    ConfidenceGrade.E: 4,
}


def _confidence_sufficient(actual: ConfidenceGrade, minimum: ConfidenceGrade) -> bool:
    return _CONFIDENCE_ORDER[actual] <= _CONFIDENCE_ORDER[minimum]


def _scenario_score_hash(candidate: RankPlanCandidate) -> str:
    return semantic_sha256(
        {
            "scenario_set_hash": candidate.scenario_set_hash,
            "scenario_points": candidate.scenario_points,
            "scenario_weights": candidate.scenario_weights,
        }
    )


def _validate_rank_distribution_surface(candidate: RankPlanCandidate) -> None:
    distribution = candidate.rank_distribution
    if distribution is None:
        return
    ranks = tuple(item.rank for item in distribution.rank_pmf)
    if ranks != tuple(sorted(ranks)) or len(ranks) != len(set(ranks)):
        raise RankStrategyError(
            "RANK_PMF_NONCANONICAL",
            "rank PMF must be sorted by unique rank",
            plan_id=candidate.plan_id,
        )
    if abs(sum(item.probability for item in distribution.rank_pmf) - 1.0) > 1e-10:
        raise RankStrategyError(
            "RANK_PMF_PROBABILITY_INVALID",
            "rank PMF probabilities must sum to one",
            plan_id=candidate.plan_id,
        )
    if any(item.rank > distribution.population_size for item in distribution.rank_pmf):
        raise RankStrategyError(
            "RANK_PMF_OUTSIDE_POPULATION",
            "rank PMF contains a rank outside the represented population",
            plan_id=candidate.plan_id,
        )


def _require_common_projection_surface(
    candidates: tuple[RankPlanCandidate, ...],
) -> tuple[str, str, dict[str, str]]:
    if not candidates:
        raise RankStrategyError(
            "RANK_PLAN_CANDIDATES_EMPTY",
            "rank utility requires at least one accepted candidate plan",
        )
    ids = tuple(item.plan_id for item in candidates)
    if len(ids) != len(set(ids)):
        raise RankStrategyError(
            "RANK_PLAN_CANDIDATE_DUPLICATE",
            "rank utility candidate plan IDs must be unique",
        )
    baseline = candidates[0]
    baseline_keys = tuple(baseline.scenario_points)
    baseline_weights = baseline.scenario_weights
    before_hashes: dict[str, str] = {}
    for candidate in candidates:
        actual_score_hash = _scenario_score_hash(candidate)
        if actual_score_hash != candidate.scenario_score_hash:
            raise RankStrategyError(
                "RANK_SCENARIO_SCORE_HASH_INVALID",
                "accepted candidate scenario scores no longer reconcile with their sealed hash",
                plan_id=candidate.plan_id,
            )
        _validate_rank_distribution_surface(candidate)
        before_hashes[candidate.plan_id] = actual_score_hash
    for candidate in candidates[1:]:
        if candidate.raw_projection_hash != baseline.raw_projection_hash:
            raise RankStrategyError(
                "RANK_PROJECTION_INVARIANCE_VIOLATION",
                "raw football/FPL projections differ across utility candidates",
                plan_id=candidate.plan_id,
            )
        if candidate.scenario_set_hash != baseline.scenario_set_hash:
            raise RankStrategyError(
                "RANK_SCENARIO_SET_INVARIANCE_VIOLATION",
                "accepted utility candidates use different scenario sets",
                plan_id=candidate.plan_id,
            )
        if tuple(candidate.scenario_points) != baseline_keys:
            raise RankStrategyError(
                "RANK_SCENARIO_IDENTITY_INVARIANCE_VIOLATION",
                "accepted utility candidates use different scenario identities",
                plan_id=candidate.plan_id,
            )
        if candidate.scenario_weights != baseline_weights:
            raise RankStrategyError(
                "RANK_SCENARIO_WEIGHT_INVARIANCE_VIOLATION",
                "accepted utility candidates use different scenario weights",
                plan_id=candidate.plan_id,
            )
    return (
        baseline.raw_projection_hash,
        baseline.scenario_set_hash,
        dict(sorted(before_hashes.items())),
    )


def _target_probability(
    candidate: RankPlanCandidate,
    objective: RankObjectiveMode,
    target: RankTargetDefinition | None,
) -> float | None:
    distribution = candidate.rank_distribution
    if objective in {RankObjectiveMode.PURE_POINTS, RankObjectiveMode.MEASURED_LEVERAGE}:
        return None
    if distribution is None:
        return None
    if objective in {RankObjectiveMode.TARGET_RANK, RankObjectiveMode.RANK_PROTECTION}:
        if target is None or target.target_rank is None:
            return None
        return sum(
            (item.probability for item in distribution.rank_pmf if item.rank <= target.target_rank),
            0.0,
        )
    if objective is RankObjectiveMode.MINI_LEAGUE_WIN:
        if isinstance(distribution, SyntheticOverallDistribution):
            return None
        return sum(
            (item.probability for item in distribution.rank_pmf if item.rank == 1),
            0.0,
        )
    if objective in {RankObjectiveMode.RANK_BAND, RankObjectiveMode.PRIZE_BAND}:
        if target is None or target.band_best_rank is None or target.band_worst_rank is None:
            return None
        return sum(
            (
                item.probability
                for item in distribution.rank_pmf
                if target.band_best_rank <= item.rank <= target.band_worst_rank
            ),
            0.0,
        )
    raise AssertionError(f"unhandled objective {objective}")


def _target_definition_reasons(
    objective: RankObjectiveMode,
    target: RankTargetDefinition | None,
) -> tuple[str, ...]:
    if objective in {RankObjectiveMode.PURE_POINTS, RankObjectiveMode.MEASURED_LEVERAGE}:
        return ()
    if objective in {RankObjectiveMode.TARGET_RANK, RankObjectiveMode.RANK_PROTECTION}:
        if target is None or target.target_rank is None:
            return ("TARGET_RANK_UNDEFINED",)
        if target.band_best_rank is not None or target.prize_band_id is not None:
            return ("TARGET_DEFINITION_INVALID",)
        return ()
    if objective in {RankObjectiveMode.RANK_BAND, RankObjectiveMode.PRIZE_BAND}:
        if target is None or target.band_best_rank is None or target.band_worst_rank is None:
            return ("RANK_BAND_UNDEFINED",)
        if target.target_rank is not None:
            return ("TARGET_DEFINITION_INVALID",)
        if objective is RankObjectiveMode.PRIZE_BAND and target.prize_band_id is None:
            return ("PRIZE_BAND_UNDEFINED",)
        if objective is RankObjectiveMode.RANK_BAND and target.prize_band_id is not None:
            return ("TARGET_DEFINITION_INVALID",)
        return ()
    if objective is RankObjectiveMode.MINI_LEAGUE_WIN:
        if target is not None and (
            target.band_best_rank is not None
            or target.prize_band_id is not None
            or target.target_rank not in {None, 1}
        ):
            return ("TARGET_DEFINITION_INVALID",)
        return ()
    raise AssertionError(f"unhandled objective {objective}")


def _activation_reasons(
    objective: RankObjectiveMode,
    context: RankActivationContext,
    target: RankTargetDefinition | None,
    policy: RankUtilityPolicy,
) -> tuple[str, ...]:
    if objective is RankObjectiveMode.PURE_POINTS:
        return ()
    reasons = list(_target_definition_reasons(objective, target))
    if not context.user_selected_explicit_target:
        reasons.append("RANK_TARGET_NOT_USER_SELECTED")
    if not context.target_rules_active:
        reasons.append("TARGET_RULES_INACTIVE")
    if not context.rules_verified:
        reasons.append("RANK_RULES_UNVERIFIED")
    if not context.rights_valid:
        reasons.append("RANK_SAMPLE_RIGHTS_INVALID")
    if not context.cohort_valid:
        reasons.append("RANK_COHORT_INVALID")
    if not context.opponent_data_valid:
        reasons.append("RANK_OPPONENT_DATA_INVALID")
    if not _confidence_sufficient(
        context.rank_model_confidence,
        policy.minimum_rank_confidence,
    ):
        reasons.append("RANK_CONFIDENCE_TOO_LOW")
    return tuple(sorted(set(reasons)))


def _objective_sort_key(
    objective: RankObjectiveMode,
    evaluation: RankPlanEvaluation,
) -> tuple[float | str, ...]:
    metrics = evaluation.metrics
    if objective is RankObjectiveMode.PURE_POINTS:
        return (-metrics.expected_points, metrics.plan_id)
    if objective is RankObjectiveMode.MEASURED_LEVERAGE:
        return (
            -metrics.measured_leverage_score,
            metrics.tracking_error,
            -metrics.expected_points,
            metrics.plan_id,
        )
    probability = metrics.probability_target
    if probability is None:
        return (float("inf"), float("inf"), float("inf"), metrics.plan_id)
    expected_rank = metrics.expected_rank if metrics.expected_rank is not None else float("inf")
    return (
        -probability,
        expected_rank,
        metrics.tracking_error,
        -metrics.expected_points,
        metrics.plan_id,
    )


def evaluate_rank_strategy(
    *,
    request_id: str,
    objective: RankObjectiveMode,
    candidates: tuple[RankPlanCandidate, ...],
    context: RankActivationContext,
    policy: RankUtilityPolicy,
    target: RankTargetDefinition | None = None,
) -> RankStrategyDecision:
    """Evaluate accepted plans without mutating projections or scenario scores.

    Selection is lexicographic: first enforce the expected-points floor, then
    maximise the requested target metric, then use expected rank, tracking error,
    expected points and plan ID as deterministic tie-breaks. No hidden weighted
    sum is used.
    """

    raw_hash, scenario_hash, before_hashes = _require_common_projection_surface(candidates)
    ordered_candidates = tuple(sorted(candidates, key=lambda item: item.plan_id))
    points_optimal = min(
        ordered_candidates,
        key=lambda item: (-item.expected_points, item.plan_id),
    )
    points_floor = points_optimal.expected_points - policy.points_epsilon
    points_target_probability = _target_probability(points_optimal, objective, target)

    evaluations: list[RankPlanEvaluation] = []
    for candidate in ordered_candidates:
        probability = _target_probability(candidate, objective, target)
        distribution = candidate.rank_distribution
        synthetic_overall = isinstance(distribution, SyntheticOverallDistribution)
        rank_one_probability = (
            None
            if distribution is None
            else sum(
                (item.probability for item in distribution.rank_pmf if item.rank == 1),
                0.0,
            )
        )
        sacrifice = max(0.0, points_optimal.expected_points - candidate.expected_points)
        points_floor_satisfied = candidate.expected_points + 1e-12 >= points_floor
        reasons: list[str] = []
        if not points_floor_satisfied:
            reasons.append("POINTS_FLOOR_VIOLATION")
        if objective not in {RankObjectiveMode.PURE_POINTS, RankObjectiveMode.MEASURED_LEVERAGE}:
            if distribution is None:
                reasons.append("RANK_DISTRIBUTION_MISSING")
            if objective is RankObjectiveMode.MINI_LEAGUE_WIN and synthetic_overall:
                reasons.append("EXACT_MINI_LEAGUE_DISTRIBUTION_REQUIRED")
            if probability is None:
                reasons.append("TARGET_PROBABILITY_UNAVAILABLE")
        metrics = RankPlanMetrics(
            plan_id=candidate.plan_id,
            expected_points=candidate.expected_points,
            expected_rank=(
                None
                if distribution is None
                else sum(item.rank * item.probability for item in distribution.rank_pmf)
            ),
            rank_pmf=() if distribution is None else distribution.rank_pmf,
            distribution_scope=(
                None
                if distribution is None
                else (
                    RankDistributionScope.SYNTHETIC_OVERALL_APPROXIMATION
                    if synthetic_overall
                    else RankDistributionScope.EXACT_MINI_LEAGUE
                )
            ),
            probability_target=probability,
            rank_one_probability=rank_one_probability,
            mini_league_win_probability=(
                None if distribution is None or synthetic_overall else rank_one_probability
            ),
            overall_rank_one_probability=(rank_one_probability if synthetic_overall else None),
            approximation_only=synthetic_overall,
            expected_points_sacrifice=sacrifice,
            target_probability_gain=(
                None
                if probability is None or points_target_probability is None
                else probability - points_target_probability
            ),
            measured_leverage_score=candidate.measured_leverage_score,
            template_beta=candidate.template_beta,
            tracking_error=candidate.tracking_error,
            mean_raw_ownership=candidate.mean_raw_ownership,
            mean_effective_ownership=candidate.mean_effective_ownership,
            confidence=None if distribution is None else distribution.confidence,
            points_floor_satisfied=points_floor_satisfied,
        )
        evaluations.append(
            RankPlanEvaluation(
                plan_id=candidate.plan_id,
                metrics=metrics,
                eligible_for_counterfactual_rank_selection=not reasons,
                exclusion_reasons=tuple(sorted(reasons)),
            )
        )

    eligible = [item for item in evaluations if item.eligible_for_counterfactual_rank_selection]
    if objective is RankObjectiveMode.PURE_POINTS:
        rank_optimal_evaluation = next(
            item for item in evaluations if item.plan_id == points_optimal.plan_id
        )
    elif eligible:
        rank_optimal_evaluation = min(
            eligible,
            key=lambda item: _objective_sort_key(objective, item),
        )
    else:
        rank_optimal_evaluation = next(
            item for item in evaluations if item.plan_id == points_optimal.plan_id
        )

    points_evaluation = next(item for item in evaluations if item.plan_id == points_optimal.plan_id)
    activation_reasons = list(_activation_reasons(objective, context, target, policy))
    if not eligible and objective is not RankObjectiveMode.PURE_POINTS:
        activation_reasons.append("NO_ELIGIBLE_RANK_PLAN")
        activation_reasons.extend(
            reason for evaluation in evaluations for reason in evaluation.exclusion_reasons
        )

    rank_metrics = rank_optimal_evaluation.metrics
    if (
        objective not in {RankObjectiveMode.PURE_POINTS, RankObjectiveMode.MEASURED_LEVERAGE}
        and rank_metrics.confidence is not None
        and not _confidence_sufficient(rank_metrics.confidence, policy.minimum_rank_confidence)
    ):
        activation_reasons.append("RANK_PLAN_CONFIDENCE_TOO_LOW")
    material_sacrifice = (
        rank_metrics.expected_points_sacrifice + 1e-12 >= policy.material_points_threshold
        and rank_metrics.expected_points_sacrifice > 0.0
    )
    early_season = context.gameweek <= policy.early_season_through_gameweek
    if objective is not RankObjectiveMode.PURE_POINTS and early_season and material_sacrifice:
        activation_reasons.append("EARLY_SEASON_MATERIAL_POINTS_GATE")
    if (
        objective is not RankObjectiveMode.PURE_POINTS
        and rank_metrics.target_probability_gain is not None
        and rank_metrics.target_probability_gain + 1e-12 < policy.minimum_target_probability_gain
    ):
        activation_reasons.append("TARGET_GAIN_BELOW_MINIMUM")

    low_confidence = "RANK_CONFIDENCE_TOO_LOW" in activation_reasons
    human_review_required = bool(
        context.user_selected_explicit_target
        and material_sacrifice
        and (early_season or low_confidence)
    )
    if human_review_required and not context.human_review_available:
        activation_reasons.append("HUMAN_REVIEW_UNAVAILABLE")

    activation_reasons = sorted(set(activation_reasons))
    if objective is RankObjectiveMode.PURE_POINTS:
        status = RankActivationStatus.ACTIVE
        effective_objective = RankObjectiveMode.PURE_POINTS
        selected_plan_id = points_optimal.plan_id
    elif activation_reasons:
        status = (
            RankActivationStatus.DIAGNOSTIC_ONLY
            if context.user_selected_explicit_target
            else RankActivationStatus.FALLBACK_PURE_POINTS
        )
        effective_objective = RankObjectiveMode.PURE_POINTS
        selected_plan_id = points_optimal.plan_id
    else:
        status = RankActivationStatus.ACTIVE
        effective_objective = objective
        selected_plan_id = rank_optimal_evaluation.plan_id

    after_hashes = {
        item.plan_id: _scenario_score_hash(item)
        for item in sorted(candidates, key=lambda value: value.plan_id)
    }
    if before_hashes != after_hashes:
        raise RankStrategyError(
            "RANK_SCENARIO_SCORE_MUTATION",
            "rank utility mutated accepted scenario scores",
        )
    invariance = ProjectionInvarianceEvidence(
        identical=True,
        raw_projection_hash=raw_hash,
        scenario_set_hash=scenario_hash,
        before_score_hashes=before_hashes,
        after_score_hashes=after_hashes,
        code="RAW_PROJECTIONS_AND_SCENARIO_SCORES_IDENTICAL",
    )
    target_difference = (
        None
        if rank_metrics.probability_target is None
        or points_evaluation.metrics.probability_target is None
        else rank_metrics.probability_target - points_evaluation.metrics.probability_target
    )
    evaluation_tuple = tuple(evaluations)
    fallback_reasons = tuple(activation_reasons)
    expected_points_difference = (
        rank_metrics.expected_points - points_evaluation.metrics.expected_points
    )
    unsealed = RankStrategyDecision.model_construct(
        request_id=request_id,
        requested_objective=objective,
        effective_objective=effective_objective,
        activation_status=status,
        points_optimal_plan_id=points_optimal.plan_id,
        rank_optimal_plan_id=rank_optimal_evaluation.plan_id,
        selected_plan_id=selected_plan_id,
        points_optimal_metrics=points_evaluation.metrics,
        rank_optimal_metrics=rank_metrics,
        expected_points_difference=expected_points_difference,
        target_probability_difference=target_difference,
        evaluations=evaluation_tuple,
        fallback_reasons=fallback_reasons,
        human_review_required=human_review_required,
        projection_invariance=invariance,
        decision_hash="0" * 64,
    )
    semantic_payload = unsealed.model_dump(mode="json", exclude={"decision_hash"})
    return RankStrategyDecision(
        request_id=request_id,
        requested_objective=objective,
        effective_objective=effective_objective,
        activation_status=status,
        points_optimal_plan_id=points_optimal.plan_id,
        rank_optimal_plan_id=rank_optimal_evaluation.plan_id,
        selected_plan_id=selected_plan_id,
        points_optimal_metrics=points_evaluation.metrics,
        rank_optimal_metrics=rank_metrics,
        expected_points_difference=expected_points_difference,
        target_probability_difference=target_difference,
        evaluations=evaluation_tuple,
        fallback_reasons=fallback_reasons,
        human_review_required=human_review_required,
        projection_invariance=invariance,
        decision_hash=semantic_sha256(semantic_payload),
    )
