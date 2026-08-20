from __future__ import annotations

import pytest

from dmf_pulse.rank_strategy.models import RankMass
from dmf_pulse.rank_strategy.rank_utility import evaluate_rank_strategy
from dmf_pulse.rank_strategy.utility_models import (
    RankActivationStatus,
    RankDistributionScope,
    RankObjectiveMode,
    RankPlanEvaluation,
    RankPlanMetrics,
    RankStrategyDecision,
    RankTargetDefinition,
)
from tests.support.rank_utility_fixtures import candidate, context, policy

pytestmark = pytest.mark.unit


def _active_decision() -> RankStrategyDecision:
    return evaluate_rank_strategy(
        request_id="utility-guard-active",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=(
            candidate("points", 60.0, {1: 0.2, 2: 0.8}),
            candidate("target", 59.5, {1: 0.8, 2: 0.2}),
        ),
        context=context(),
        policy=policy(material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )


def _inactive_decision() -> RankStrategyDecision:
    return evaluate_rank_strategy(
        request_id="utility-guard-inactive",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=(
            candidate("points", 60.0, {1: 0.2, 2: 0.8}),
            candidate("target", 59.5, {1: 0.8, 2: 0.2}),
        ),
        context=context(rights_valid=False),
        policy=policy(material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )


def _replace_evaluation_metrics(
    decision: RankStrategyDecision,
    plan_id: str,
    metrics: RankPlanMetrics,
) -> tuple[RankPlanEvaluation, ...]:
    return tuple(
        item.model_copy(update={"metrics": metrics}) if item.plan_id == plan_id else item
        for item in decision.evaluations
    )


def test_candidate_rejects_empty_or_mismatched_scenario_inventory() -> None:
    value = candidate("candidate", 60.0)

    empty = value.model_copy(update={"scenario_points": {}, "scenario_weights": {}})
    with pytest.raises(ValueError, match="share non-empty keys"):
        empty.candidate_is_reconciled_and_canonical()

    mismatched = value.model_copy(update={"scenario_weights": {"different": 1.0}})
    with pytest.raises(ValueError, match="share non-empty keys"):
        mismatched.candidate_is_reconciled_and_canonical()


def test_rank_metrics_without_pmf_reject_rank_diagnostics_and_approximation() -> None:
    exact = _active_decision().points_optimal_metrics
    empty = exact.model_copy(
        update={
            "expected_rank": None,
            "rank_pmf": (),
            "distribution_scope": None,
            "probability_target": None,
            "rank_one_probability": None,
            "mini_league_win_probability": None,
            "overall_rank_one_probability": None,
            "approximation_only": False,
            "confidence": None,
        }
    )
    assert empty.distribution_diagnostics_reconcile() is empty

    with_diagnostic = empty.model_copy(update={"expected_rank": 1.0})
    with pytest.raises(ValueError, match="cannot contain rank diagnostics"):
        with_diagnostic.distribution_diagnostics_reconcile()

    approximation = empty.model_copy(update={"approximation_only": True})
    with pytest.raises(ValueError, match="cannot be approximation-labelled"):
        approximation.distribution_diagnostics_reconcile()


def test_rank_metrics_reject_noncanonical_pmf_summaries() -> None:
    metrics = _active_decision().points_optimal_metrics

    duplicate = metrics.model_copy(update={"rank_pmf": (metrics.rank_pmf[0],) * 2})
    with pytest.raises(ValueError, match="sorted by unique rank"):
        duplicate.distribution_diagnostics_reconcile()

    bad_mass = metrics.model_copy(update={"rank_pmf": (RankMass(rank=1, probability=0.2),)})
    with pytest.raises(ValueError, match="probabilities must sum to one"):
        bad_mass.distribution_diagnostics_reconcile()

    bad_expected = metrics.model_copy(update={"expected_rank": 99.0})
    with pytest.raises(ValueError, match="expected rank must be derived"):
        bad_expected.distribution_diagnostics_reconcile()

    bad_rank_one = metrics.model_copy(update={"rank_one_probability": 0.0})
    with pytest.raises(ValueError, match="rank-one probability must equal PMF mass"):
        bad_rank_one.distribution_diagnostics_reconcile()


def test_rank_metrics_reject_scope_specific_rank_one_mismatches() -> None:
    exact = _active_decision().points_optimal_metrics

    bad_exact = exact.model_copy(update={"mini_league_win_probability": None})
    with pytest.raises(ValueError, match="exact mini-league rank-one diagnostics"):
        bad_exact.distribution_diagnostics_reconcile()

    synthetic = exact.model_copy(
        update={
            "distribution_scope": RankDistributionScope.SYNTHETIC_OVERALL_APPROXIMATION,
            "mini_league_win_probability": None,
            "overall_rank_one_probability": exact.rank_one_probability,
            "approximation_only": True,
        }
    )
    assert synthetic.distribution_diagnostics_reconcile() is synthetic

    bad_synthetic = synthetic.model_copy(update={"overall_rank_one_probability": None})
    with pytest.raises(ValueError, match="synthetic overall rank-one diagnostics"):
        bad_synthetic.distribution_diagnostics_reconcile()

    missing_scope = exact.model_copy(
        update={"distribution_scope": None, "mini_league_win_probability": None}
    )
    with pytest.raises(ValueError, match="require a distribution scope"):
        missing_scope.distribution_diagnostics_reconcile()

    missing_confidence = exact.model_copy(update={"confidence": None})
    with pytest.raises(ValueError, match="require confidence"):
        missing_confidence.distribution_diagnostics_reconcile()


def test_plan_evaluation_rejects_identity_reason_and_eligibility_mismatch() -> None:
    evaluation = _active_decision().evaluations[0]

    wrong_identity = evaluation.model_copy(update={"plan_id": "different"})
    with pytest.raises(ValueError, match="metrics plan mismatch"):
        wrong_identity.evaluation_is_canonical()

    unsorted_reasons = evaluation.model_copy(
        update={
            "eligible_for_counterfactual_rank_selection": False,
            "exclusion_reasons": ("z", "a"),
        }
    )
    with pytest.raises(ValueError, match="reasons must be sorted and unique"):
        unsorted_reasons.evaluation_is_canonical()

    mismatched_eligibility = evaluation.model_copy(
        update={"eligible_for_counterfactual_rank_selection": False, "exclusion_reasons": ()}
    )
    with pytest.raises(ValueError, match="eligibility must reconcile"):
        mismatched_eligibility.evaluation_is_canonical()


def test_projection_evidence_rejects_order_and_cross_mode_differences() -> None:
    evidence = _active_decision().projection_invariance
    reversed_before = dict(reversed(tuple(evidence.before_score_hashes.items())))
    reversed_after = dict(reversed(tuple(evidence.after_score_hashes.items())))

    bad_before = evidence.model_copy(update={"before_score_hashes": reversed_before})
    with pytest.raises(ValueError, match="before score hashes must be sorted"):
        bad_before.evidence_is_canonical()

    bad_after = evidence.model_copy(update={"after_score_hashes": reversed_after})
    with pytest.raises(ValueError, match="after score hashes must be sorted"):
        bad_after.evidence_is_canonical()

    changed_after = dict(evidence.after_score_hashes)
    changed_after[next(iter(changed_after))] = "f" * 64
    unequal = evidence.model_copy(update={"after_score_hashes": changed_after})
    with pytest.raises(ValueError, match="identical score hashes"):
        unequal.evidence_is_canonical()


def test_decision_rejects_retained_metric_and_floor_mismatch() -> None:
    decision = _active_decision()

    changed_points = decision.points_optimal_metrics.model_copy(update={"tracking_error": 1.0})
    points_mismatch = decision.model_copy(update={"points_optimal_metrics": changed_points})
    with pytest.raises(ValueError, match="points-optimal metrics must match"):
        points_mismatch.decision_reconciles()

    changed_rank = decision.rank_optimal_metrics.model_copy(update={"tracking_error": 1.0})
    rank_mismatch = decision.model_copy(update={"rank_optimal_metrics": changed_rank})
    with pytest.raises(ValueError, match="rank-optimal metrics must match"):
        rank_mismatch.decision_reconciles()

    floor_failed = decision.rank_optimal_metrics.model_copy(
        update={"points_floor_satisfied": False}
    )
    invalid_floor = decision.model_copy(
        update={
            "rank_optimal_metrics": floor_failed,
            "evaluations": _replace_evaluation_metrics(
                decision,
                decision.rank_optimal_plan_id,
                floor_failed,
            ),
        }
    )
    with pytest.raises(ValueError, match="rank-optimal plan must satisfy"):
        invalid_floor.decision_reconciles()


def test_decision_rejects_probability_and_fallback_state_mismatch() -> None:
    active = _active_decision()

    unavailable_delta = active.model_copy(update={"target_probability_difference": None})
    with pytest.raises(ValueError, match="availability does not reconcile"):
        unavailable_delta.decision_reconciles()

    unsorted_reasons = active.model_copy(update={"fallback_reasons": ("z", "a")})
    with pytest.raises(ValueError, match="fallback reasons must be sorted and unique"):
        unsorted_reasons.decision_reconciles()

    active_with_reason = active.model_copy(update={"fallback_reasons": ("UNEXPECTED",)})
    with pytest.raises(ValueError, match="active rank decision cannot contain"):
        active_with_reason.decision_reconciles()

    active_wrong_selection = active.model_copy(
        update={"selected_plan_id": active.points_optimal_plan_id}
    )
    with pytest.raises(ValueError, match="selected plan is inconsistent"):
        active_wrong_selection.decision_reconciles()

    inactive = _inactive_decision()
    assert inactive.activation_status is not RankActivationStatus.ACTIVE

    inactive_without_reason = inactive.model_copy(update={"fallback_reasons": ()})
    with pytest.raises(ValueError, match="requires a fallback reason"):
        inactive_without_reason.decision_reconciles()

    inactive_rank_objective = inactive.model_copy(
        update={"effective_objective": RankObjectiveMode.TARGET_RANK}
    )
    with pytest.raises(ValueError, match="fail closed to pure points"):
        inactive_rank_objective.decision_reconciles()

    inactive_rank_selection = inactive.model_copy(
        update={"selected_plan_id": inactive.rank_optimal_plan_id}
    )
    with pytest.raises(ValueError, match="select the points-optimal"):
        inactive_rank_selection.decision_reconciles()
