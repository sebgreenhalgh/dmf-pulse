"""Public Stage-14 application contracts for chip decisions.

The service models deliberately retain the decomposition required by DMFP-13:
current gain, continuation value, opportunity cost, exercise advantage and the
fully explained probability diagnostic are never collapsed into one opaque
score.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from dmf_pulse.chips.definitions import (
    CompiledChipBundle,
    FrozenModel,
    Sha256,
    semantic_sha256,
)
from dmf_pulse.chips.inventory import ChipInventory
from dmf_pulse.chips.policy_models import (
    BenchBoostEvaluation,
    CaptainViceDecision,
    FreeHitEvaluation,
    TripleCaptainEvaluation,
    WildcardEvaluation,
)
from dmf_pulse.chips.schedule_models import (
    ChipSchedulePolicy,
    ChipScheduleRequest,
    require_utc,
)
from dmf_pulse.evaluation.leakage import scan_for_leakage
from dmf_pulse.evaluation.models import DatasetMode, FeatureRecord, LeakageReport
from dmf_pulse.prices.models import ActivationStatus as PriceActivationStatus
from dmf_pulse.prices.models import ConfidenceGrade

FiniteFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0.0, allow_inf_nan=False)]
Probability = Annotated[StrictFloat, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class ChipDecisionAction(StrEnum):
    """Executable current/root recommendation emitted by the shared service."""

    USE = "USE"
    HOLD = "HOLD"
    WAIT = "WAIT"
    EXPIRE_UNUSED = "EXPIRE_UNUSED"
    BLOCKED = "BLOCKED"


class ScenarioWeight(FrozenModel):
    """Explicit retained denominator member for an auditable decision."""

    scenario_id: StrictStr = Field(min_length=1)
    outcome_draw_id: StrictStr = Field(min_length=1)
    weight: Probability


ProbabilityComparisonRule = Literal[
    "PER_SCENARIO_BEST_LEGAL_SCHEDULE_ACTIVATES_AT_ROOT",
    "PER_SCENARIO_CURRENT_OPPORTUNITY_GTE_BEST_SAME_TOKEN_DELAY_OR_TERMINAL",
]


class ChipProbabilityDiagnostic(FrozenModel):
    """Auditable probability retaining its universe, denominator and method."""

    probability_now_optimal: Probability
    numerator_weight: Probability
    denominator_weight: Probability
    scenario_set_hash: Sha256
    scenario_weights: tuple[ScenarioWeight, ...]
    comparison_rule: ProbabilityComparisonRule
    model_version: StrictStr = Field(min_length=1)
    configuration_hash: Sha256
    exact_search: StrictBool
    diagnostic_only: Literal[True] = True
    diagnostic_hash: Sha256

    @model_validator(mode="after")
    def probability_is_explained(self) -> ChipProbabilityDiagnostic:
        identities = tuple(
            (item.scenario_id, item.outcome_draw_id, item.weight) for item in self.scenario_weights
        )
        if not identities or identities != tuple(sorted(identities)):
            raise ValueError("chip probability scenario weights must be non-empty and sorted")
        if len(identities) != len(set(identities)):
            raise ValueError("chip probability scenario identities must be unique")
        weight_sum = sum(item.weight for item in self.scenario_weights)
        if abs(weight_sum - 1.0) > 1e-9:
            raise ValueError("chip probability scenario weights must sum to one")
        if abs(self.denominator_weight - weight_sum) > 1e-9:
            raise ValueError("chip probability denominator differs from scenario weights")
        if self.numerator_weight > self.denominator_weight + 1e-12:
            raise ValueError("chip probability numerator exceeds denominator")
        expected_probability = self.numerator_weight / self.denominator_weight
        if abs(self.probability_now_optimal - expected_probability) > 1e-12:
            raise ValueError("chip probability does not reconcile with its denominator")
        expected_scenario_hash = semantic_sha256(
            {
                "scenarios": [
                    {
                        "scenario_id": item.scenario_id,
                        "outcome_draw_id": item.outcome_draw_id,
                        "weight": item.weight,
                    }
                    for item in self.scenario_weights
                ]
            }
        )
        if self.scenario_set_hash != expected_scenario_hash:
            raise ValueError("chip probability scenario-set hash differs from retained weights")
        payload = self.model_dump(mode="json", exclude={"diagnostic_hash"})
        if self.diagnostic_hash != "0" * 64 and semantic_sha256(payload) != self.diagnostic_hash:
            raise ValueError("chip probability diagnostic hash mismatch")
        return self


class ChipDecisionLineage(FrozenModel):
    """Complete semantic lineage for one Stage-14 decision."""

    manager_state_id: StrictStr = Field(min_length=1)
    manager_state_hash: Sha256
    ruleset_id: StrictStr = Field(min_length=1)
    ruleset_version: StrictStr = Field(min_length=1)
    ruleset_hash: Sha256
    chip_bundle_hash: Sha256
    chip_definition_hashes: tuple[Sha256, ...]
    inventory_hash: Sha256
    service_request_hash: Sha256
    schedule_request_hash: Sha256
    scenario_set_hash: Sha256
    scenario_weights: tuple[ScenarioWeight, ...]
    dataset_mode: DatasetMode
    feature_record_hashes: tuple[Sha256, ...]
    leakage_report_hash: Sha256
    price_input_hash: Sha256 | None = None
    price_activation_statuses: tuple[PriceActivationStatus, ...] = ()
    continuation_model_version: StrictStr = Field(min_length=1)
    continuation_configuration_hash: Sha256
    forecast_origin: datetime
    information_cutoff: datetime
    code_commit: StrictStr = Field(min_length=7)
    random_seed: NonNegativeInt | None = None
    lineage_hash: Sha256

    @model_validator(mode="after")
    def lineage_is_coherent(self) -> ChipDecisionLineage:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        if cutoff > origin:
            raise ValueError("chip decision information cutoff cannot follow forecast origin")
        if not self.chip_definition_hashes:
            raise ValueError("chip decision lineage requires chip definitions")
        if self.chip_definition_hashes != tuple(sorted(set(self.chip_definition_hashes))):
            raise ValueError("chip definition hashes must be sorted and unique")
        weights = tuple(
            (item.scenario_id, item.outcome_draw_id, item.weight) for item in self.scenario_weights
        )
        if not weights or weights != tuple(sorted(weights)):
            raise ValueError("chip scenario weights must be non-empty and sorted")
        if len(weights) != len(set(weights)):
            raise ValueError("chip scenario weights must have unique identities")
        if abs(sum(item.weight for item in self.scenario_weights) - 1.0) > 1e-9:
            raise ValueError("chip scenario weights must sum to one")
        if not self.feature_record_hashes:
            raise ValueError("chip decision lineage requires Stage-12 feature records")
        if self.feature_record_hashes != tuple(sorted(set(self.feature_record_hashes))):
            raise ValueError("Stage-12 feature record hashes must be sorted and unique")
        statuses = tuple(item.value for item in self.price_activation_statuses)
        if statuses != tuple(sorted(set(statuses))):
            raise ValueError("Stage-13 activation statuses must be sorted and unique")
        if self.price_activation_statuses and self.price_input_hash is None:
            raise ValueError("Stage-13 statuses require a price input hash")
        payload = self.model_dump(mode="json", exclude={"lineage_hash"})
        if self.lineage_hash != "0" * 64 and semantic_sha256(payload) != self.lineage_hash:
            raise ValueError("chip decision lineage hash mismatch")
        return self


class ChipOpportunityEvaluation(FrozenModel):
    """Public, comparable policy value for one current chip opportunity."""

    opportunity_id: StrictStr = Field(min_length=1)
    chip_key: StrictStr = Field(min_length=1)
    token_id: StrictStr = Field(min_length=1)
    activation_gameweek: StrictInt = Field(gt=0)
    gross_current_gain: FiniteFloat
    continuation_value: FiniteFloat
    policy_cost: NonNegativeFloat
    net_policy_value: FiniteFloat
    opportunity_cost: NonNegativeFloat
    exercise_advantage: FiniteFloat
    probability_now_optimal: Probability
    probability_diagnostic: ChipProbabilityDiagnostic
    robust_penalty: NonNegativeFloat
    domain_evaluation_hash: Sha256 | None = None
    opportunity_hash: Sha256
    summary_hash: Sha256

    @model_validator(mode="after")
    def opportunity_reconciles(self) -> ChipOpportunityEvaluation:
        expected = self.gross_current_gain + self.continuation_value - self.policy_cost
        if abs(self.net_policy_value - expected) > 1e-9:
            raise ValueError("chip opportunity net policy value does not reconcile")
        if (
            abs(self.probability_now_optimal - self.probability_diagnostic.probability_now_optimal)
            > 1e-12
        ):
            raise ValueError("chip opportunity probability differs from its diagnostic")
        payload = self.model_dump(mode="json", exclude={"summary_hash"})
        if self.summary_hash != "0" * 64 and semantic_sha256(payload) != self.summary_hash:
            raise ValueError("chip opportunity summary hash mismatch")
        return self


class ChipDecision(FrozenModel):
    """Executable root decision with separately reported policy components."""

    decision_id: StrictStr = Field(min_length=1)
    recommended_action: ChipDecisionAction
    selected_chip: StrictStr | None = None
    selected_token_id: StrictStr | None = None
    gross_current_gain: FiniteFloat
    net_policy_value: FiniteFloat
    continuation_value: FiniteFloat
    opportunity_cost: NonNegativeFloat
    exercise_advantage: FiniteFloat
    robust_regret: NonNegativeFloat
    probability_now_optimal: Probability
    probability_diagnostic: ChipProbabilityDiagnostic
    confidence: ConfidenceGrade
    expiry_pressure: StrictBool
    reasons: tuple[StrictStr, ...]
    price_activation_statuses: tuple[PriceActivationStatus, ...] = ()
    executable_root_only: Literal[True] = True
    future_schedule_advisory_only: Literal[True] = True
    schedule_policy_hash: Sha256
    decision_hash: Sha256

    @model_validator(mode="after")
    def decision_is_coherent(self) -> ChipDecision:
        uses_chip = self.recommended_action is ChipDecisionAction.USE
        if uses_chip != (self.selected_chip is not None):
            raise ValueError("USE must identify exactly one selected chip")
        if uses_chip != (self.selected_token_id is not None):
            raise ValueError("USE must identify exactly one selected token")
        if not self.reasons or self.reasons != tuple(sorted(set(self.reasons))):
            raise ValueError("chip decision reasons must be non-empty, sorted and unique")
        if (
            abs(self.probability_now_optimal - self.probability_diagnostic.probability_now_optimal)
            > 1e-12
        ):
            raise ValueError("chip probability differs from its retained diagnostic")
        statuses = tuple(item.value for item in self.price_activation_statuses)
        if statuses != tuple(sorted(set(statuses))):
            raise ValueError("decision Stage-13 statuses must be sorted and unique")
        payload = self.model_dump(mode="json", exclude={"decision_hash"})
        if self.decision_hash != "0" * 64 and semantic_sha256(payload) != self.decision_hash:
            raise ValueError("chip decision hash mismatch")
        return self


class ChipServiceRequest(FrozenModel):
    """Sealed shared-service request composing existing Stage-14 capabilities."""

    request_id: StrictStr = Field(min_length=1)
    decision_id: StrictStr = Field(min_length=1)
    manager_state_id: StrictStr = Field(min_length=1)
    manager_state_hash: Sha256
    forecast_origin: datetime
    information_cutoff: datetime
    dataset_mode: DatasetMode
    feature_records: tuple[FeatureRecord, ...]
    leakage_report: LeakageReport
    chip_bundle: CompiledChipBundle
    inventory: ChipInventory
    schedule_request: ChipScheduleRequest
    captain_vice: CaptainViceDecision | None = None
    triple_captain: TripleCaptainEvaluation | None = None
    bench_boost: BenchBoostEvaluation | None = None
    free_hit: FreeHitEvaluation | None = None
    wildcard: WildcardEvaluation | None = None
    confidence: ConfidenceGrade = ConfidenceGrade.E
    price_input_hash: Sha256 | None = None
    price_activation_statuses: tuple[PriceActivationStatus, ...] = ()
    continuation_model_version: StrictStr = Field(min_length=1)
    continuation_configuration_hash: Sha256
    code_commit: StrictStr = Field(min_length=7)
    random_seed: NonNegativeInt | None = None
    service_request_hash: Sha256

    @model_validator(mode="after")
    def request_is_coherent(self) -> ChipServiceRequest:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        if cutoff > origin:
            raise ValueError("chip service information cutoff cannot follow forecast origin")
        record_ids = tuple(item.record_id for item in self.feature_records)
        if not record_ids or record_ids != tuple(sorted(record_ids)):
            raise ValueError("Stage-12 feature records must be non-empty and sorted")
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("Stage-12 feature record IDs must be unique")
        expected_leakage = scan_for_leakage(
            self.feature_records,
            forecast_origin=cutoff,
            dataset_mode=self.dataset_mode,
        )
        if self.leakage_report != expected_leakage:
            raise ValueError("Stage-12 leakage report differs from the retained feature set")
        if self.leakage_report.status != "PASS":
            raise ValueError("future-information leakage blocks executable chip decisions")
        if cutoff != self.schedule_request.information_cutoff:
            raise ValueError("chip service and scheduler information cutoffs differ")
        bundle_lineage = (
            self.chip_bundle.ruleset_id,
            self.chip_bundle.ruleset_version,
            self.chip_bundle.ruleset_hash,
            self.chip_bundle.bundle_hash,
        )
        inventory_lineage = (
            self.inventory.ruleset_id,
            self.inventory.ruleset_version,
            self.inventory.ruleset_hash,
            self.inventory.bundle_hash,
        )
        schedule_inventory_lineage = (
            self.schedule_request.inventory.ruleset_id,
            self.schedule_request.inventory.ruleset_version,
            self.schedule_request.inventory.ruleset_hash,
            self.schedule_request.inventory.bundle_hash,
        )
        if bundle_lineage != inventory_lineage or bundle_lineage != schedule_inventory_lineage:
            raise ValueError("chip service rules, bundle and inventory lineage differ")
        if self.inventory.inventory_hash != self.schedule_request.inventory.inventory_hash:
            raise ValueError("chip service scheduler inventory differs from current inventory")
        expected_config_hash = semantic_sha256(self.schedule_request.objective)
        if self.continuation_configuration_hash != expected_config_hash:
            raise ValueError("continuation configuration hash differs from scheduler objective")
        statuses = tuple(item.value for item in self.price_activation_statuses)
        if statuses != tuple(sorted(set(statuses))):
            raise ValueError("Stage-13 activation statuses must be sorted and unique")
        if self.price_activation_statuses and self.price_input_hash is None:
            raise ValueError("Stage-13 statuses require a price input hash")

        scenario_signature = tuple(
            (item.scenario_id, item.outcome_draw_id, item.weight)
            for item in self.schedule_request.scenario_universe
        )
        if self.captain_vice is not None:
            captain_signature = tuple(
                (item.scenario_id, item.outcome_draw_id, item.weight)
                for item in self.captain_vice.scenario_scores
            )
            if captain_signature != scenario_signature:
                raise ValueError("captain/vice decision differs from scheduler scenario universe")

        evaluations = tuple(
            item
            for item in (
                self.triple_captain,
                self.bench_boost,
                self.free_hit,
                self.wildcard,
            )
            if item is not None
        )
        keys = tuple(item.chip_key for item in evaluations)
        if len(keys) != len(set(keys)):
            raise ValueError("chip service evaluations must be unique by chip key")
        definition_map = {
            item.chip_key: item.definition_hash for item in self.chip_bundle.definitions
        }
        token_map = {item.token_id: item for item in self.inventory.tokens}
        for evaluation in evaluations:
            lineage = (
                evaluation.ruleset_id,
                evaluation.ruleset_version,
                evaluation.ruleset_hash,
            )
            if lineage != bundle_lineage[:3]:
                raise ValueError("chip-specific evaluation has different rules lineage")
            if evaluation.inventory_before_hash != self.inventory.inventory_hash:
                raise ValueError("chip-specific evaluation has different inventory lineage")
            if evaluation.scenario_set_hash != self.schedule_request.scenario_set_hash:
                raise ValueError("chip-specific evaluation has different scenario lineage")
            token = token_map.get(evaluation.token_id)
            if token is None or token.chip_key != evaluation.chip_key:
                raise ValueError("chip-specific evaluation token is absent or mismatched")
            if definition_map.get(evaluation.chip_key) != evaluation.chip_definition_hash:
                raise ValueError("chip-specific evaluation definition hash differs")

        payload = self.model_dump(mode="json", exclude={"service_request_hash"})
        if (
            self.service_request_hash != "0" * 64
            and semantic_sha256(payload) != self.service_request_hash
        ):
            raise ValueError("chip service request hash mismatch")
        return self


class ChipDecisionSet(FrozenModel):
    """Complete shared Stage-14 application response."""

    request_hash: Sha256
    lineage: ChipDecisionLineage
    decision: ChipDecision
    opportunities: tuple[ChipOpportunityEvaluation, ...]
    captain_vice: CaptainViceDecision | None = None
    triple_captain: TripleCaptainEvaluation | None = None
    bench_boost: BenchBoostEvaluation | None = None
    free_hit: FreeHitEvaluation | None = None
    wildcard: WildcardEvaluation | None = None
    schedule_policy: ChipSchedulePolicy
    decision_set_hash: Sha256

    @model_validator(mode="after")
    def decision_set_is_coherent(self) -> ChipDecisionSet:
        if self.request_hash != self.lineage.service_request_hash:
            raise ValueError("decision-set request and service lineage hashes differ")
        if self.schedule_policy.request_hash != self.lineage.schedule_request_hash:
            raise ValueError("decision-set schedule policy has a different scheduler request hash")
        if self.decision.schedule_policy_hash != self.schedule_policy.policy_hash:
            raise ValueError("decision is not bound to its schedule policy")
        checks = (
            (self.decision.gross_current_gain, self.schedule_policy.gross_current_gain),
            (self.decision.net_policy_value, self.schedule_policy.net_policy_value),
            (self.decision.continuation_value, self.schedule_policy.continuation_value),
            (self.decision.opportunity_cost, self.schedule_policy.opportunity_cost),
            (self.decision.exercise_advantage, self.schedule_policy.exercise_advantage),
        )
        if any(abs(observed - expected) > 1e-9 for observed, expected in checks):
            raise ValueError("decision value decomposition differs from schedule policy")
        opportunities = tuple(
            sorted(
                self.opportunities,
                key=lambda item: (item.chip_key, item.token_id, item.opportunity_id),
            )
        )
        if self.opportunities != opportunities:
            raise ValueError("current chip opportunities must be sorted")
        ids = tuple(item.opportunity_id for item in self.opportunities)
        if len(ids) != len(set(ids)):
            raise ValueError("current chip opportunity IDs must be unique")
        if self.decision.selected_chip is not None:
            selected = tuple(
                item
                for item in self.opportunities
                if item.chip_key == self.decision.selected_chip
                and item.token_id == self.decision.selected_token_id
            )
            if not selected:
                raise ValueError("selected chip decision lacks a current opportunity")
        payload = self.model_dump(mode="json", exclude={"decision_set_hash"})
        if (
            self.decision_set_hash != "0" * 64
            and semantic_sha256(payload) != self.decision_set_hash
        ):
            raise ValueError("chip decision-set hash mismatch")
        return self


class ChipRulesValidation(FrozenModel):
    """Deterministic validation result for one compiled chip bundle."""

    status: Literal["READY"] = "READY"
    ruleset_id: StrictStr = Field(min_length=1)
    ruleset_version: StrictStr = Field(min_length=1)
    ruleset_hash: Sha256
    bundle_hash: Sha256
    definition_count: StrictInt = Field(gt=0)
    chip_keys: tuple[StrictStr, ...]
    compiler_version: StrictStr = Field(min_length=1)
    validation_hash: Sha256

    @model_validator(mode="after")
    def validation_is_coherent(self) -> ChipRulesValidation:
        if self.chip_keys != tuple(sorted(set(self.chip_keys))):
            raise ValueError("validated chip keys must be sorted and unique")
        if self.definition_count != len(self.chip_keys):
            raise ValueError("validated chip definition count differs from chip keys")
        payload = self.model_dump(mode="json", exclude={"validation_hash"})
        if self.validation_hash != "0" * 64 and semantic_sha256(payload) != self.validation_hash:
            raise ValueError("chip rules validation hash mismatch")
        return self


class ChipCapabilityValidation(FrozenModel):
    """Installed Stage-14 engineering capability report."""

    status: Literal["ENGINEERING_READY_PENDING_TARGET_RULES"] = (
        "ENGINEERING_READY_PENDING_TARGET_RULES"
    )
    service_version: Literal["stage14-service-v1"] = "stage14-service-v1"
    capabilities: tuple[StrictStr, ...]
    production_eligible: Literal[False] = False
    target_rules_required: Literal[True] = True
    validation_hash: Sha256

    @model_validator(mode="after")
    def capability_is_coherent(self) -> ChipCapabilityValidation:
        if not self.capabilities or self.capabilities != tuple(sorted(set(self.capabilities))):
            raise ValueError("Stage-14 capabilities must be non-empty, sorted and unique")
        payload = self.model_dump(mode="json", exclude={"validation_hash"})
        if self.validation_hash != "0" * 64 and semantic_sha256(payload) != self.validation_hash:
            raise ValueError("Stage-14 capability validation hash mismatch")
        return self


# Public names intentionally alias the accepted chip-domain models instead of
# cloning them in the application layer.
__all__ = [
    "BenchBoostEvaluation",
    "CaptainViceDecision",
    "ChipCapabilityValidation",
    "ChipDecision",
    "ChipDecisionAction",
    "ChipDecisionLineage",
    "ChipDecisionSet",
    "ChipOpportunityEvaluation",
    "ChipProbabilityDiagnostic",
    "ChipRulesValidation",
    "ChipSchedulePolicy",
    "ChipServiceRequest",
    "ConfidenceGrade",
    "FreeHitEvaluation",
    "PriceActivationStatus",
    "ScenarioWeight",
    "TripleCaptainEvaluation",
    "WildcardEvaluation",
]
