"""Shared application contracts for Stage-15 rank-aware plan re-evaluation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, StrictBool, StrictStr, model_validator

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.prices.models import ActivationStatus as PriceActivationStatus
from dmf_pulse.prices.models import ConfidenceGrade, require_utc
from dmf_pulse.rank_strategy.models import FiniteFloat, RankModel, SampleRightsStatus, Sha256
from dmf_pulse.rank_strategy.utility_models import (
    RankActivationContext,
    RankActivationStatus,
    RankObjectiveMode,
    RankPlanCandidate,
    RankPlanSource,
    RankStrategyDecision,
    RankTargetDefinition,
    RankUtilityPolicy,
)

_ZERO_HASH = "0" * 64


class RankComponentKind(StrEnum):
    STAGE_9_SCENARIOS = "STAGE_9_SCENARIOS"
    STAGE_10_TACTICS = "STAGE_10_TACTICS"
    STAGE_11_MANAGER_STATE = "STAGE_11_MANAGER_STATE"
    STAGE_12_PLANS = "STAGE_12_PLANS"
    STAGE_13_PRICES = "STAGE_13_PRICES"
    STAGE_14_CHIPS = "STAGE_14_CHIPS"
    STAGE_15_EFFECTIVE_OWNERSHIP = "STAGE_15_EFFECTIVE_OWNERSHIP"
    STAGE_15_COHORT = "STAGE_15_COHORT"
    STAGE_15_OPPONENT_MODEL = "STAGE_15_OPPONENT_MODEL"


class RankGateName(StrEnum):
    RULES = "RULES"
    TARGET = "TARGET"
    RIGHTS = "RIGHTS"
    COHORT = "COHORT"
    OPPONENT_MODEL = "OPPONENT_MODEL"
    CONFIDENCE = "CONFIDENCE"
    PROJECTION_LINEAGE = "PROJECTION_LINEAGE"
    SCENARIO_LINEAGE = "SCENARIO_LINEAGE"
    POINTS_FLOOR = "POINTS_FLOOR"
    EARLY_SEASON_POLICY = "EARLY_SEASON_POLICY"


class RankComponentIdentity(RankModel):
    """Immutable identity of an accepted upstream component or artifact."""

    component: RankComponentKind
    identity: StrictStr = Field(min_length=1, max_length=240)
    semantic_hash: Sha256

    @model_validator(mode="after")
    def identity_is_sealed(self) -> RankComponentIdentity:
        if self.semantic_hash == _ZERO_HASH:
            raise ValueError("rank component identity cannot use the unsealed hash sentinel")
        return self


class RankServiceLineage(RankModel):
    """Complete Stage-9-through-15 lineage bound into one service request."""

    schema_version: Literal["rank-service-lineage-v1"] = "rank-service-lineage-v1"
    information_cutoff: datetime
    raw_projection_hash: Sha256
    scenario_set_hash: Sha256
    stage9_scenarios: RankComponentIdentity
    stage10_tactics: RankComponentIdentity
    stage11_manager_state: RankComponentIdentity
    stage12_plans: RankComponentIdentity
    stage13_prices: RankComponentIdentity | None = None
    stage13_activation_statuses: tuple[PriceActivationStatus, ...] = ()
    stage14_chips: RankComponentIdentity | None = None
    effective_ownership_model: RankComponentIdentity
    cohort_model: RankComponentIdentity | None = None
    opponent_model: RankComponentIdentity | None = None
    rights_profile_id: StrictStr = Field(min_length=1, max_length=240)
    rights_profile_hash: Sha256
    rights_status: SampleRightsStatus
    ruleset_id: StrictStr = Field(min_length=1, max_length=240)
    ruleset_hash: Sha256
    points_floor_hash: Sha256
    code_version: StrictStr = Field(min_length=1, max_length=240)
    config_version: StrictStr = Field(min_length=1, max_length=240)
    lineage_hash: Sha256

    @model_validator(mode="after")
    def lineage_is_coherent(self) -> RankServiceLineage:
        require_utc(self.information_cutoff, field_name="information_cutoff")
        expected_components = {
            RankComponentKind.STAGE_9_SCENARIOS: self.stage9_scenarios,
            RankComponentKind.STAGE_10_TACTICS: self.stage10_tactics,
            RankComponentKind.STAGE_11_MANAGER_STATE: self.stage11_manager_state,
            RankComponentKind.STAGE_12_PLANS: self.stage12_plans,
            RankComponentKind.STAGE_13_PRICES: self.stage13_prices,
            RankComponentKind.STAGE_14_CHIPS: self.stage14_chips,
            RankComponentKind.STAGE_15_EFFECTIVE_OWNERSHIP: self.effective_ownership_model,
            RankComponentKind.STAGE_15_COHORT: self.cohort_model,
            RankComponentKind.STAGE_15_OPPONENT_MODEL: self.opponent_model,
        }
        for component, value in expected_components.items():
            if value is not None and value.component is not component:
                raise ValueError(f"rank lineage component identity mismatch: {component.value}")
        expected_statuses = tuple(
            sorted(set(self.stage13_activation_statuses), key=lambda item: item.value)
        )
        if self.stage13_activation_statuses != expected_statuses:
            raise ValueError("Stage-13 activation statuses must be sorted and unique")
        if self.stage13_prices is None and self.stage13_activation_statuses:
            raise ValueError("Stage-13 statuses require a Stage-13 price component")
        if self.stage13_prices is not None and not self.stage13_activation_statuses:
            raise ValueError("Stage-13 price lineage requires its activation-status inventory")
        protected_hashes = {
            "raw_projection_hash": self.raw_projection_hash,
            "scenario_set_hash": self.scenario_set_hash,
            "rights_profile_hash": self.rights_profile_hash,
            "ruleset_hash": self.ruleset_hash,
            "points_floor_hash": self.points_floor_hash,
        }
        zero_fields = tuple(
            sorted(name for name, value in protected_hashes.items() if value == _ZERO_HASH)
        )
        if zero_fields:
            raise ValueError(
                "rank service lineage contains unsealed protected hashes: " + ", ".join(zero_fields)
            )
        payload = self.model_dump(mode="json", exclude={"lineage_hash"})
        if self.lineage_hash != _ZERO_HASH and semantic_sha256(payload) != self.lineage_hash:
            raise ValueError("rank service lineage hash mismatch")
        return self


class AcceptedRankPlan(RankModel):
    """One immutable upstream plan and its Stage-15 diagnostic candidate."""

    schema_version: Literal["accepted-rank-plan-v1"] = "accepted-rank-plan-v1"
    plan_id: StrictStr = Field(min_length=1, max_length=200)
    source_stage: RankPlanSource
    source_status: Literal["ACCEPTED"] = "ACCEPTED"
    source_plan_hash: Sha256
    source_result_hash: Sha256
    candidate: RankPlanCandidate
    binding_hash: Sha256

    @model_validator(mode="after")
    def plan_binding_is_coherent(self) -> AcceptedRankPlan:
        if self.source_plan_hash == _ZERO_HASH or self.source_result_hash == _ZERO_HASH:
            raise ValueError("accepted plan source identities cannot use unsealed hashes")
        if self.plan_id != self.candidate.plan_id:
            raise ValueError("accepted plan ID differs from rank candidate")
        if self.source_stage is not self.candidate.source_stage:
            raise ValueError("accepted plan source stage differs from rank candidate")
        payload = self.model_dump(mode="json", exclude={"binding_hash"})
        if self.binding_hash != _ZERO_HASH and semantic_sha256(payload) != self.binding_hash:
            raise ValueError("accepted rank plan binding hash mismatch")
        return self


class RankServiceRequest(RankModel):
    """Sealed application request for re-evaluating accepted plans."""

    schema_version: Literal["rank-service-request-v1"] = "rank-service-request-v1"
    request_id: StrictStr = Field(min_length=1, max_length=200)
    forecast_origin: datetime
    information_cutoff: datetime
    objective: RankObjectiveMode
    target: RankTargetDefinition | None = None
    context: RankActivationContext
    policy: RankUtilityPolicy
    lineage: RankServiceLineage
    plans: tuple[AcceptedRankPlan, ...] = Field(min_length=1)
    service_request_hash: Sha256

    @model_validator(mode="after")
    def request_is_canonical(self) -> RankServiceRequest:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        if cutoff > origin:
            raise ValueError("rank information cutoff cannot follow forecast origin")
        if self.lineage.information_cutoff != cutoff:
            raise ValueError("rank request and lineage information cutoffs differ")
        ids = tuple(item.plan_id for item in self.plans)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("accepted rank plans must be sorted and unique")
        source_plan_ids = tuple(
            (item.source_stage.value, item.source_plan_hash) for item in self.plans
        )
        if len(source_plan_ids) != len(set(source_plan_ids)):
            raise ValueError("accepted rank plans must bind unique upstream plan identities")
        source_stages = {item.source_stage for item in self.plans}
        if RankPlanSource.STAGE_13 in source_stages and self.lineage.stage13_prices is None:
            raise ValueError("accepted Stage-13 plan requires Stage-13 price lineage")
        if RankPlanSource.STAGE_14 in source_stages and self.lineage.stage14_chips is None:
            raise ValueError("accepted Stage-14 plan requires Stage-14 chip lineage")
        expected_floor_hash = semantic_sha256(self.policy.model_dump(mode="json"))
        if self.lineage.points_floor_hash != expected_floor_hash:
            raise ValueError("rank points-floor configuration hash mismatch")
        payload = self.model_dump(mode="json", exclude={"service_request_hash"})
        if (
            self.service_request_hash != _ZERO_HASH
            and semantic_sha256(payload) != self.service_request_hash
        ):
            raise ValueError("rank service request hash mismatch")
        return self


class RankGateCheck(RankModel):
    name: RankGateName
    required: StrictBool
    passed: StrictBool
    reason_code: StrictStr | None = Field(default=None, min_length=1, max_length=240)

    @model_validator(mode="after")
    def gate_reconciles(self) -> RankGateCheck:
        if self.passed == (self.reason_code is not None):
            raise ValueError("rank gate pass state must reconcile with its reason")
        return self


class RankGateReport(RankModel):
    checks: tuple[RankGateCheck, ...]
    executable_rank_utility: StrictBool
    report_hash: Sha256

    @model_validator(mode="after")
    def report_reconciles(self) -> RankGateReport:
        names = tuple(item.name.value for item in self.checks)
        expected_names = tuple(sorted(item.value for item in RankGateName))
        if names != expected_names:
            raise ValueError("rank gate report must contain the complete sorted gate inventory")
        executable = all(item.passed for item in self.checks if item.required)
        if executable != self.executable_rank_utility:
            raise ValueError("rank gate report executable status does not reconcile")
        payload = self.model_dump(mode="json", exclude={"report_hash"})
        if self.report_hash != semantic_sha256(payload):
            raise ValueError("rank gate report hash mismatch")
        return self


class RankServiceProjectionEvidence(RankModel):
    unchanged: Literal[True]
    expected_raw_projection_hash: Sha256
    expected_scenario_set_hash: Sha256
    common_raw_projection_lineage: StrictBool
    common_scenario_lineage: StrictBool
    before_score_hashes: dict[StrictStr, Sha256]
    after_score_hashes: dict[StrictStr, Sha256]
    evidence_hash: Sha256

    @model_validator(mode="after")
    def evidence_reconciles(self) -> RankServiceProjectionEvidence:
        if tuple(self.before_score_hashes) != tuple(sorted(self.before_score_hashes)):
            raise ValueError("rank service before-score hashes must be sorted")
        if tuple(self.after_score_hashes) != tuple(sorted(self.after_score_hashes)):
            raise ValueError("rank service after-score hashes must be sorted")
        if self.before_score_hashes != self.after_score_hashes:
            raise ValueError("rank service cannot mutate accepted scenario scores")
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if self.evidence_hash != semantic_sha256(payload):
            raise ValueError("rank service projection evidence hash mismatch")
        return self


class RankServiceResult(RankModel):
    """Complete Stage-15 response retaining both points and rank plans."""

    schema_version: Literal["rank-service-result-v1"] = "rank-service-result-v1"
    request_id: StrictStr = Field(min_length=1, max_length=200)
    request_hash: Sha256
    requested_objective: RankObjectiveMode
    effective_objective: RankObjectiveMode
    activation_status: RankActivationStatus
    points_optimal_plan: AcceptedRankPlan
    rank_optimal_plan: AcceptedRankPlan
    selected_plan: AcceptedRankPlan
    expected_points_difference: FiniteFloat
    target_probability_difference: FiniteFloat | None
    rank_decision: RankStrategyDecision | None
    gate_report: RankGateReport
    confidence: ConfidenceGrade
    stage13_activation_statuses: tuple[PriceActivationStatus, ...]
    diagnostic_output_available: StrictBool
    fail_closed_reasons: tuple[StrictStr, ...]
    raw_projection_hash: Sha256
    scenario_set_hash: Sha256
    projection_invariance: RankServiceProjectionEvidence
    result_hash: Sha256

    @model_validator(mode="after")
    def result_reconciles(self) -> RankServiceResult:
        if self.fail_closed_reasons != tuple(sorted(set(self.fail_closed_reasons))):
            raise ValueError("rank service fail-closed reasons must be sorted and unique")
        expected_statuses = tuple(
            sorted(set(self.stage13_activation_statuses), key=lambda item: item.value)
        )
        if self.stage13_activation_statuses != expected_statuses:
            raise ValueError("rank result Stage-13 statuses must be sorted and unique")
        expected_difference = (
            self.rank_optimal_plan.candidate.expected_points
            - self.points_optimal_plan.candidate.expected_points
        )
        if abs(self.expected_points_difference - expected_difference) > 1e-10:
            raise ValueError("rank service expected-points difference does not reconcile")
        if self.rank_decision is None:
            if self.diagnostic_output_available:
                raise ValueError("rank diagnostics cannot be available without a decision")
            if self.activation_status is RankActivationStatus.ACTIVE and (
                self.requested_objective is not RankObjectiveMode.PURE_POINTS
            ):
                raise ValueError("active non-points result requires rank diagnostics")
            if self.rank_optimal_plan.plan_id != self.points_optimal_plan.plan_id:
                raise ValueError("unavailable rank diagnostics must retain the points plan")
            if self.target_probability_difference is not None:
                raise ValueError("unavailable rank diagnostics cannot claim target gain")
        else:
            if not self.diagnostic_output_available:
                raise ValueError("rank decision must be exposed as diagnostic output")
            if self.rank_decision.request_id != self.request_id:
                raise ValueError("rank service and rank decision request IDs differ")
            if self.rank_decision.points_optimal_plan_id != self.points_optimal_plan.plan_id:
                raise ValueError("rank service points-optimal plan differs from decision")
            if self.rank_decision.rank_optimal_plan_id != self.rank_optimal_plan.plan_id:
                raise ValueError("rank service rank-optimal plan differs from decision")
            if (
                self.target_probability_difference
                != self.rank_decision.target_probability_difference
            ):
                raise ValueError("rank service target-probability difference differs from decision")
        evidence_plan_ids = tuple(self.projection_invariance.before_score_hashes)
        if self.rank_decision is None:
            required_plan_ids = {
                self.points_optimal_plan.plan_id,
                self.rank_optimal_plan.plan_id,
            }
            if not required_plan_ids.issubset(evidence_plan_ids):
                raise ValueError("rank service projection evidence omits retained plans")
        else:
            evaluation_plan_ids = tuple(
                sorted(item.plan_id for item in self.rank_decision.evaluations)
            )
            if evidence_plan_ids != evaluation_plan_ids:
                raise ValueError(
                    "rank service projection evidence differs from decision candidates"
                )
        if self.activation_status is RankActivationStatus.ACTIVE:
            if self.fail_closed_reasons:
                raise ValueError("active rank service result cannot contain fallback reasons")
            if not self.gate_report.executable_rank_utility:
                raise ValueError("active rank service result requires every executable gate")
            expected_objective = (
                RankObjectiveMode.PURE_POINTS
                if self.requested_objective is RankObjectiveMode.PURE_POINTS
                else self.requested_objective
            )
            if self.effective_objective is not expected_objective:
                raise ValueError("active rank service effective objective is inconsistent")
            if (
                self.rank_decision is not None
                and self.rank_decision.activation_status is not RankActivationStatus.ACTIVE
            ):
                raise ValueError("active rank service result requires an active rank decision")
            expected_selected = (
                self.points_optimal_plan
                if self.requested_objective is RankObjectiveMode.PURE_POINTS
                else self.rank_optimal_plan
            )
            if self.selected_plan.plan_id != expected_selected.plan_id:
                raise ValueError("active rank service selected plan is inconsistent")
        else:
            if not self.fail_closed_reasons:
                raise ValueError("inactive rank service result requires fail-closed reasons")
            if self.effective_objective is not RankObjectiveMode.PURE_POINTS:
                raise ValueError("inactive rank service result must use pure points")
            if self.selected_plan.plan_id != self.points_optimal_plan.plan_id:
                raise ValueError("inactive rank service result must select points optimum")
        if self.raw_projection_hash != self.projection_invariance.expected_raw_projection_hash:
            raise ValueError("rank service raw projection lineage differs from evidence")
        if self.scenario_set_hash != self.projection_invariance.expected_scenario_set_hash:
            raise ValueError("rank service scenario lineage differs from evidence")
        payload = self.model_dump(mode="json", exclude={"result_hash"})
        if self.result_hash != _ZERO_HASH and self.result_hash != semantic_sha256(payload):
            raise ValueError("rank service result hash mismatch")
        return self


class RankCapabilityValidation(RankModel):
    schema_version: Literal["rank-capability-validation-v1"] = "rank-capability-validation-v1"
    status: Literal["IMPLEMENTED_PENDING_INDEPENDENT_REVIEW"] = (
        "IMPLEMENTED_PENDING_INDEPENDENT_REVIEW"
    )
    shared_service_available: Literal[True] = True
    cli_commands: tuple[StrictStr, ...]
    fail_closed_to_pure_points: Literal[True] = True
    raw_projection_mutation_permitted: Literal[False] = False
    mass_manager_scraping_permitted: Literal[False] = False
    definitive_overall_win_claim_permitted: Literal[False] = False
    validation_hash: Sha256

    @model_validator(mode="after")
    def validation_is_canonical(self) -> RankCapabilityValidation:
        if self.cli_commands != tuple(sorted(set(self.cli_commands))):
            raise ValueError("rank capability CLI commands must be sorted and unique")
        payload = self.model_dump(mode="json", exclude={"validation_hash"})
        if self.validation_hash != semantic_sha256(payload):
            raise ValueError("rank capability validation hash mismatch")
        return self


__all__ = [
    "AcceptedRankPlan",
    "RankCapabilityValidation",
    "RankComponentIdentity",
    "RankComponentKind",
    "RankGateCheck",
    "RankGateName",
    "RankGateReport",
    "RankServiceLineage",
    "RankServiceProjectionEvidence",
    "RankServiceRequest",
    "RankServiceResult",
]
