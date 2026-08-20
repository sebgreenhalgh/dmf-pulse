"""Strict contracts for lexicographic Stage-15 decision utility."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.prices.models import ConfidenceGrade
from dmf_pulse.rank_strategy.models import (
    FiniteFloat,
    NonNegativeFloat,
    PositiveInt,
    Probability,
    RankDistribution,
    RankMass,
    RankModel,
    Sha256,
)
from dmf_pulse.rank_strategy.synthetic_models import SyntheticOverallDistribution


class RankObjectiveMode(StrEnum):
    PURE_POINTS = "PURE_POINTS"
    MEASURED_LEVERAGE = "MEASURED_LEVERAGE"
    TARGET_RANK = "TARGET_RANK"
    RANK_PROTECTION = "RANK_PROTECTION"
    MINI_LEAGUE_WIN = "MINI_LEAGUE_WIN"
    RANK_BAND = "RANK_BAND"
    PRIZE_BAND = "PRIZE_BAND"


class RankActivationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    FALLBACK_PURE_POINTS = "FALLBACK_PURE_POINTS"


class RankPlanSource(StrEnum):
    STAGE_12 = "STAGE_12"
    STAGE_13 = "STAGE_13"
    STAGE_14 = "STAGE_14"
    SYNTHETIC_TEST = "SYNTHETIC_TEST"


class RankDistributionScope(StrEnum):
    EXACT_MINI_LEAGUE = "EXACT_MINI_LEAGUE"
    SYNTHETIC_OVERALL_APPROXIMATION = "SYNTHETIC_OVERALL_APPROXIMATION"


class RankTargetDefinition(RankModel):
    schema_version: Literal["rank-target-definition-v1"] = "rank-target-definition-v1"
    target_rank: PositiveInt | None = None
    band_best_rank: PositiveInt | None = None
    band_worst_rank: PositiveInt | None = None
    prize_band_id: StrictStr | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def band_is_ordered(self) -> RankTargetDefinition:
        supplied = (self.band_best_rank is not None, self.band_worst_rank is not None)
        if supplied[0] != supplied[1]:
            raise ValueError("rank band requires both best and worst rank")
        if (
            self.band_best_rank is not None
            and self.band_worst_rank is not None
            and self.band_best_rank > self.band_worst_rank
        ):
            raise ValueError("rank band best rank cannot exceed worst rank")
        if self.target_rank is not None and self.band_best_rank is not None:
            raise ValueError("rank target cannot mix a single target rank with a rank band")
        if self.prize_band_id is not None and self.band_best_rank is None:
            raise ValueError("prize band ID requires a complete rank band")
        return self


class RankActivationContext(RankModel):
    schema_version: Literal["rank-activation-context-v1"] = "rank-activation-context-v1"
    gameweek: PositiveInt
    season_gameweeks: PositiveInt
    current_rank: PositiveInt | None = None
    user_selected_explicit_target: StrictBool = False
    target_rules_active: StrictBool
    rules_verified: StrictBool
    rights_valid: StrictBool
    cohort_valid: StrictBool
    opponent_data_valid: StrictBool
    rank_model_confidence: ConfidenceGrade
    human_review_available: StrictBool = False

    @model_validator(mode="after")
    def gameweek_is_in_season(self) -> RankActivationContext:
        if self.gameweek > self.season_gameweeks:
            raise ValueError("gameweek cannot exceed configured season length")
        return self


class RankUtilityPolicy(RankModel):
    schema_version: Literal["rank-utility-policy-v1"] = "rank-utility-policy-v1"
    points_epsilon: NonNegativeFloat
    material_points_threshold: NonNegativeFloat
    early_season_through_gameweek: Annotated[StrictInt, Field(ge=0)]
    minimum_rank_confidence: ConfidenceGrade
    minimum_target_probability_gain: NonNegativeFloat = 0.0
    early_season_default_mode: Literal[RankObjectiveMode.PURE_POINTS] = (
        RankObjectiveMode.PURE_POINTS
    )
    fail_closed: Literal[True] = True


class RankPlanCandidate(RankModel):
    """One accepted points plan plus immutable rank diagnostics.

    Scenario points are the accepted Stage-9/12/13/14 plan scores. Rank utility may
    inspect them but cannot alter them.
    """

    schema_version: Literal["rank-plan-candidate-v1"] = "rank-plan-candidate-v1"
    plan_id: StrictStr = Field(min_length=1, max_length=200)
    source_stage: RankPlanSource
    raw_projection_hash: Sha256
    scenario_set_hash: Sha256
    scenario_points: dict[StrictStr, FiniteFloat]
    scenario_weights: dict[StrictStr, Probability]
    expected_points: FiniteFloat
    rank_distribution: RankDistribution | SyntheticOverallDistribution | None = None
    measured_leverage_score: FiniteFloat = 0.0
    template_beta: FiniteFloat = 0.0
    tracking_error: NonNegativeFloat = 0.0
    mean_raw_ownership: NonNegativeFloat | None = None
    mean_effective_ownership: NonNegativeFloat | None = None
    scenario_score_hash: Sha256

    @model_validator(mode="after")
    def candidate_is_reconciled_and_canonical(self) -> RankPlanCandidate:
        point_ids = tuple(self.scenario_points)
        weight_ids = tuple(self.scenario_weights)
        if point_ids != tuple(sorted(point_ids)) or weight_ids != tuple(sorted(weight_ids)):
            raise ValueError("candidate scenario maps must be sorted")
        if not point_ids or point_ids != weight_ids:
            raise ValueError("candidate scenario points and weights must share non-empty keys")
        if abs(sum(self.scenario_weights.values()) - 1.0) > 1e-10:
            raise ValueError("candidate scenario weights must sum to one")
        expected = sum(
            self.scenario_points[scenario_id] * self.scenario_weights[scenario_id]
            for scenario_id in point_ids
        )
        if abs(self.expected_points - expected) > 1e-10:
            raise ValueError("candidate expected points must reconcile with scenario scores")
        semantic_score_hash = semantic_sha256(
            {
                "scenario_set_hash": self.scenario_set_hash,
                "scenario_points": self.scenario_points,
                "scenario_weights": self.scenario_weights,
            }
        )
        if self.scenario_score_hash != semantic_score_hash:
            raise ValueError("candidate scenario score hash does not reconcile")
        if self.rank_distribution is not None:
            if self.rank_distribution.raw_projection_hash != self.raw_projection_hash:
                raise ValueError("candidate rank distribution raw projection hash differs")
            if self.rank_distribution.scenario_set_hash != self.scenario_set_hash:
                raise ValueError("candidate rank distribution scenario set hash differs")
        return self


class RankPlanMetrics(RankModel):
    plan_id: StrictStr = Field(min_length=1, max_length=200)
    expected_points: FiniteFloat
    expected_rank: FiniteFloat | None
    rank_pmf: tuple[RankMass, ...]
    distribution_scope: RankDistributionScope | None
    probability_target: Probability | None
    rank_one_probability: Probability | None
    mini_league_win_probability: Probability | None
    overall_rank_one_probability: Probability | None
    approximation_only: StrictBool
    expected_points_sacrifice: NonNegativeFloat
    target_probability_gain: FiniteFloat | None
    measured_leverage_score: FiniteFloat
    template_beta: FiniteFloat
    tracking_error: NonNegativeFloat
    mean_raw_ownership: NonNegativeFloat | None
    mean_effective_ownership: NonNegativeFloat | None
    confidence: ConfidenceGrade | None
    points_floor_satisfied: StrictBool

    @model_validator(mode="after")
    def distribution_diagnostics_reconcile(self) -> RankPlanMetrics:
        ranks = tuple(item.rank for item in self.rank_pmf)
        if ranks != tuple(sorted(ranks)) or len(ranks) != len(set(ranks)):
            raise ValueError("rank metrics PMF must be sorted by unique rank")
        if not self.rank_pmf:
            if any(
                value is not None
                for value in (
                    self.expected_rank,
                    self.probability_target,
                    self.rank_one_probability,
                    self.mini_league_win_probability,
                    self.overall_rank_one_probability,
                    self.confidence,
                    self.distribution_scope,
                )
            ):
                raise ValueError("rank metrics without a PMF cannot contain rank diagnostics")
            if self.approximation_only:
                raise ValueError("rank metrics without a PMF cannot be approximation-labelled")
            return self
        if abs(sum(item.probability for item in self.rank_pmf) - 1.0) > 1e-10:
            raise ValueError("rank metrics probabilities must sum to one")
        expected_rank = sum(item.rank * item.probability for item in self.rank_pmf)
        if self.expected_rank is None or abs(self.expected_rank - expected_rank) > 1e-10:
            raise ValueError("rank metrics expected rank must be derived from the PMF")
        win_probability = sum(item.probability for item in self.rank_pmf if item.rank == 1)
        if (
            self.rank_one_probability is None
            or abs(self.rank_one_probability - win_probability) > 1e-10
        ):
            raise ValueError("rank metrics rank-one probability must equal PMF mass")
        if self.distribution_scope is RankDistributionScope.EXACT_MINI_LEAGUE:
            if (
                self.mini_league_win_probability is None
                or abs(self.mini_league_win_probability - win_probability) > 1e-10
                or self.overall_rank_one_probability is not None
                or self.approximation_only
            ):
                raise ValueError("exact mini-league rank-one diagnostics do not reconcile")
        elif self.distribution_scope is RankDistributionScope.SYNTHETIC_OVERALL_APPROXIMATION:
            if (
                self.overall_rank_one_probability is None
                or abs(self.overall_rank_one_probability - win_probability) > 1e-10
                or self.mini_league_win_probability is not None
                or not self.approximation_only
            ):
                raise ValueError("synthetic overall rank-one diagnostics do not reconcile")
        else:
            raise ValueError("rank metrics with a PMF require a distribution scope")
        if self.confidence is None:
            raise ValueError("rank metrics with a PMF require confidence")
        return self


class RankPlanEvaluation(RankModel):
    plan_id: StrictStr = Field(min_length=1, max_length=200)
    metrics: RankPlanMetrics
    eligible_for_counterfactual_rank_selection: StrictBool
    exclusion_reasons: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def evaluation_is_canonical(self) -> RankPlanEvaluation:
        if self.metrics.plan_id != self.plan_id:
            raise ValueError("rank evaluation metrics plan mismatch")
        if self.exclusion_reasons != tuple(sorted(set(self.exclusion_reasons))):
            raise ValueError("rank evaluation exclusion reasons must be sorted and unique")
        if self.eligible_for_counterfactual_rank_selection == bool(self.exclusion_reasons):
            raise ValueError("rank evaluation eligibility must reconcile with exclusion reasons")
        return self


class ProjectionInvarianceEvidence(RankModel):
    identical: Literal[True]
    raw_projection_hash: Sha256
    scenario_set_hash: Sha256
    before_score_hashes: dict[StrictStr, Sha256]
    after_score_hashes: dict[StrictStr, Sha256]
    code: Literal["RAW_PROJECTIONS_AND_SCENARIO_SCORES_IDENTICAL"]

    @model_validator(mode="after")
    def evidence_is_canonical(self) -> ProjectionInvarianceEvidence:
        if tuple(self.before_score_hashes) != tuple(sorted(self.before_score_hashes)):
            raise ValueError("before score hashes must be sorted")
        if tuple(self.after_score_hashes) != tuple(sorted(self.after_score_hashes)):
            raise ValueError("after score hashes must be sorted")
        if self.before_score_hashes != self.after_score_hashes:
            raise ValueError("projection invariance evidence must contain identical score hashes")
        return self


class RankStrategyDecision(RankModel):
    schema_version: Literal["rank-strategy-decision-v1"] = "rank-strategy-decision-v1"
    request_id: StrictStr = Field(min_length=1, max_length=200)
    requested_objective: RankObjectiveMode
    effective_objective: RankObjectiveMode
    activation_status: RankActivationStatus
    points_optimal_plan_id: StrictStr = Field(min_length=1, max_length=200)
    rank_optimal_plan_id: StrictStr = Field(min_length=1, max_length=200)
    selected_plan_id: StrictStr = Field(min_length=1, max_length=200)
    points_optimal_metrics: RankPlanMetrics
    rank_optimal_metrics: RankPlanMetrics
    expected_points_difference: FiniteFloat
    target_probability_difference: FiniteFloat | None
    evaluations: tuple[RankPlanEvaluation, ...] = Field(min_length=1)
    fallback_reasons: tuple[StrictStr, ...]
    human_review_required: StrictBool
    projection_invariance: ProjectionInvarianceEvidence
    decision_hash: Sha256

    @model_validator(mode="after")
    def decision_reconciles(self) -> RankStrategyDecision:
        ids = tuple(item.plan_id for item in self.evaluations)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("rank plan evaluations must be sorted and unique")
        if self.points_optimal_metrics.plan_id != self.points_optimal_plan_id:
            raise ValueError("points-optimal metrics plan mismatch")
        if self.rank_optimal_metrics.plan_id != self.rank_optimal_plan_id:
            raise ValueError("rank-optimal metrics plan mismatch")
        if self.selected_plan_id not in ids:
            raise ValueError("selected rank plan must exist in evaluations")
        evaluation_by_id = {item.plan_id: item for item in self.evaluations}
        if evaluation_by_id[self.points_optimal_plan_id].metrics != self.points_optimal_metrics:
            raise ValueError("points-optimal metrics must match the retained evaluation")
        if evaluation_by_id[self.rank_optimal_plan_id].metrics != self.rank_optimal_metrics:
            raise ValueError("rank-optimal metrics must match the retained evaluation")
        if not self.rank_optimal_metrics.points_floor_satisfied:
            raise ValueError("rank-optimal plan must satisfy the expected-points floor")
        expected_difference = (
            self.rank_optimal_metrics.expected_points - self.points_optimal_metrics.expected_points
        )
        if abs(self.expected_points_difference - expected_difference) > 1e-10:
            raise ValueError("expected-points difference does not reconcile")
        probabilities_available = (
            self.rank_optimal_metrics.probability_target is not None
            and self.points_optimal_metrics.probability_target is not None
        )
        if probabilities_available != (self.target_probability_difference is not None):
            raise ValueError("target-probability difference availability does not reconcile")
        if self.target_probability_difference is not None:
            rank_probability = self.rank_optimal_metrics.probability_target
            points_probability = self.points_optimal_metrics.probability_target
            if rank_probability is None or points_probability is None:
                raise ValueError("target-probability difference requires both plan probabilities")
            expected_target_difference = rank_probability - points_probability
            if abs(self.target_probability_difference - expected_target_difference) > 1e-10:
                raise ValueError("target-probability difference does not reconcile")
        if self.fallback_reasons != tuple(sorted(set(self.fallback_reasons))):
            raise ValueError("rank fallback reasons must be sorted and unique")
        if self.activation_status is RankActivationStatus.ACTIVE:
            if self.fallback_reasons:
                raise ValueError("active rank decision cannot contain fallback reasons")
            if self.effective_objective is not self.requested_objective:
                raise ValueError("active rank decision must retain the requested objective")
            expected_selected = (
                self.points_optimal_plan_id
                if self.requested_objective is RankObjectiveMode.PURE_POINTS
                else self.rank_optimal_plan_id
            )
            if self.selected_plan_id != expected_selected:
                raise ValueError("active rank decision selected plan is inconsistent")
        else:
            if not self.fallback_reasons:
                raise ValueError("inactive rank decision requires a fallback reason")
            if self.effective_objective is not RankObjectiveMode.PURE_POINTS:
                raise ValueError("inactive rank decision must fail closed to pure points")
            if self.selected_plan_id != self.points_optimal_plan_id:
                raise ValueError("inactive rank decision must select the points-optimal plan")
        payload = self.model_dump(mode="json", exclude={"decision_hash"})
        if self.decision_hash != semantic_sha256(payload):
            raise ValueError("rank decision hash does not reconcile")
        return self
