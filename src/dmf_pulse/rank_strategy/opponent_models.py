"""Strict cutoff-safe contracts for the Stage-15 opponent action model."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from math import log
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictStr, model_validator

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.prices.models import ConfidenceGrade
from dmf_pulse.rank_strategy.models import (
    FiniteFloat,
    ManagerChip,
    ManagerTeamPlan,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    Probability,
    RankModel,
    SampleRightsStatus,
    Sha256,
)

_ZERO_HASH = "0" * 64


class OpponentChipAction(StrEnum):
    """Opponent chip descriptor, including non-scoring Wildcard state."""

    NONE = "NONE"
    TRIPLE_CAPTAIN = "TRIPLE_CAPTAIN"
    BENCH_BOOST = "BENCH_BOOST"
    FREE_HIT = "FREE_HIT"
    WILDCARD = "WILDCARD"


class OpponentObservedState(RankModel):
    """Last legally available rival state at a predeadline cutoff."""

    schema_version: Literal["rank-opponent-observed-state-v1"] = "rank-opponent-observed-state-v1"
    state_id: StrictStr = Field(min_length=1, max_length=200)
    manager_id: StrictStr = Field(min_length=1, max_length=200)
    observed_plan: ManagerTeamPlan
    rights_status: SampleRightsStatus
    observed_at: datetime
    information_cutoff: datetime
    deadline: datetime

    @model_validator(mode="after")
    def state_is_predeadline_and_canonical(self) -> OpponentObservedState:
        for label, value in (
            ("observed_at", self.observed_at),
            ("information_cutoff", self.information_cutoff),
            ("deadline", self.deadline),
        ):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{label} must be timezone-aware UTC")
        if self.observed_at > self.information_cutoff:
            raise ValueError("opponent state cannot be observed after the information cutoff")
        if self.information_cutoff > self.deadline:
            raise ValueError("opponent information cutoff cannot follow the deadline")
        if self.observed_plan.manager_id != self.manager_id:
            raise ValueError("observed opponent plan manager ID does not match state manager")
        return self


class OpponentActionFeatures(RankModel):
    """Transparent cutoff-safe features for one plausible rival action."""

    schema_version: Literal["rank-opponent-action-features-v1"] = "rank-opponent-action-features-v1"
    observed_at: datetime
    contains_postdeadline_action_label: StrictBool = False
    perceived_expected_points: FiniteFloat
    popularity_signal: Annotated[StrictFloat, Field(ge=-10.0, le=10.0, allow_inf_nan=False)]
    recent_form_signal: Annotated[StrictFloat, Field(ge=-10.0, le=10.0, allow_inf_nan=False)]
    price_pressure_signal: Annotated[StrictFloat, Field(ge=-10.0, le=10.0, allow_inf_nan=False)]
    relative_risk_signal: Annotated[StrictFloat, Field(ge=-10.0, le=10.0, allow_inf_nan=False)]
    confidence: ConfidenceGrade

    @model_validator(mode="after")
    def feature_time_is_utc(self) -> OpponentActionFeatures:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() != timedelta(0):
            raise ValueError("opponent action feature timestamp must be timezone-aware UTC")
        return self


class OpponentBehaviourProfile(RankModel):
    """Explicit baseline random-utility coefficients for one rival."""

    schema_version: Literal["rank-opponent-behaviour-profile-v1"] = (
        "rank-opponent-behaviour-profile-v1"
    )
    profile_id: StrictStr = Field(min_length=1, max_length=200)
    manager_id: StrictStr = Field(min_length=1, max_length=200)
    estimated_at: datetime
    information_cutoff: datetime
    points_coefficient: FiniteFloat
    popularity_coefficient: FiniteFloat
    recent_form_coefficient: FiniteFloat
    price_pressure_coefficient: FiniteFloat
    relative_risk_coefficient: FiniteFloat
    no_transfer_bias: FiniteFloat
    hit_point_penalty: NonNegativeFloat
    chip_biases: dict[OpponentChipAction, FiniteFloat]
    random_utility_temperature: PositiveFloat
    probability_floor: Annotated[StrictFloat, Field(gt=0.0, lt=0.5, allow_inf_nan=False)]
    confidence: ConfidenceGrade
    assumes_perfect_rationality: Literal[False] = False

    @model_validator(mode="after")
    def profile_is_cutoff_safe(self) -> OpponentBehaviourProfile:
        for label, value in (
            ("estimated_at", self.estimated_at),
            ("information_cutoff", self.information_cutoff),
        ):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{label} must be timezone-aware UTC")
        if self.estimated_at > self.information_cutoff:
            raise ValueError("opponent profile cannot be estimated after its information cutoff")
        return self


class OpponentActionCandidate(RankModel):
    """One exact future rival plan with explicit action descriptors."""

    schema_version: Literal["rank-opponent-action-candidate-v1"] = (
        "rank-opponent-action-candidate-v1"
    )
    action_id: StrictStr = Field(min_length=1, max_length=200)
    manager_plan: ManagerTeamPlan
    transfer_count: NonNegativeInt
    counted_transfer_delta: NonNegativeInt
    chip_action: OpponentChipAction
    generated_at: datetime
    features: OpponentActionFeatures

    @model_validator(mode="after")
    def action_is_canonical(self) -> OpponentActionCandidate:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() != timedelta(0):
            raise ValueError("opponent action generation timestamp must be timezone-aware UTC")
        expected_active_chip = {
            OpponentChipAction.NONE: ManagerChip.NONE,
            OpponentChipAction.TRIPLE_CAPTAIN: ManagerChip.TRIPLE_CAPTAIN,
            OpponentChipAction.BENCH_BOOST: ManagerChip.BENCH_BOOST,
            OpponentChipAction.FREE_HIT: ManagerChip.FREE_HIT,
            OpponentChipAction.WILDCARD: ManagerChip.NONE,
        }[self.chip_action]
        if self.manager_plan.active_chip is not expected_active_chip:
            raise ValueError("opponent chip descriptor does not match the exact manager plan")
        if self.features.observed_at > self.generated_at:
            raise ValueError("opponent action features cannot postdate candidate generation")
        if self.chip_action in {OpponentChipAction.FREE_HIT, OpponentChipAction.WILDCARD}:
            if self.counted_transfer_delta != 0:
                raise ValueError("Free Hit and Wildcard transfers cannot enter counted tie state")
        elif self.counted_transfer_delta != self.transfer_count:
            raise ValueError("ordinary transfers must enter counted tie state exactly")
        if self.transfer_count == 0 and self.manager_plan.transfer_hit_points != 0:
            raise ValueError("a no-transfer action cannot carry a transfer hit")
        if self.chip_action is OpponentChipAction.WILDCARD and self.transfer_count == 0:
            raise ValueError("Wildcard candidate must describe at least one transfer")
        if (
            self.chip_action is OpponentChipAction.WILDCARD
            and self.manager_plan.transfer_hit_points != 0
        ):
            raise ValueError("Wildcard action cannot carry ordinary transfer-hit deductions")
        return self


class OpponentActionProbability(RankModel):
    action_id: StrictStr = Field(min_length=1, max_length=200)
    manager_plan: ManagerTeamPlan
    transfer_count: NonNegativeInt
    counted_transfer_delta: NonNegativeInt
    chip_action: OpponentChipAction
    deterministic_utility: FiniteFloat
    probability: Annotated[StrictFloat, Field(gt=0.0, le=1.0, allow_inf_nan=False)]
    feature_confidence: ConfidenceGrade


class OpponentActionDistribution(RankModel):
    """A non-degenerate predeadline probability vector over exact rival plans."""

    schema_version: Literal["rank-opponent-action-distribution-v1"] = (
        "rank-opponent-action-distribution-v1"
    )
    manager_id: StrictStr = Field(min_length=1, max_length=200)
    state_id: StrictStr = Field(min_length=1, max_length=200)
    profile_id: StrictStr = Field(min_length=1, max_length=200)
    information_cutoff: datetime
    deadline: datetime
    actions: tuple[OpponentActionProbability, ...] = Field(min_length=2)
    no_transfer_probability: Probability
    expected_transfer_count: NonNegativeFloat
    expected_hit_points: NonNegativeFloat
    entropy: NonNegativeFloat
    normalised_entropy: Probability
    confidence: ConfidenceGrade
    assumes_perfect_rationality: Literal[False] = False
    distribution_hash: Sha256

    @model_validator(mode="after")
    def distribution_is_valid(self) -> OpponentActionDistribution:
        for label, value in (
            ("information_cutoff", self.information_cutoff),
            ("deadline", self.deadline),
        ):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{label} must be timezone-aware UTC")
        if self.information_cutoff > self.deadline:
            raise ValueError("opponent distribution cutoff cannot follow the deadline")
        action_ids = tuple(item.action_id for item in self.actions)
        if action_ids != tuple(sorted(action_ids)) or len(action_ids) != len(set(action_ids)):
            raise ValueError("opponent action probabilities must be sorted and unique")
        if any(item.manager_plan.manager_id != self.manager_id for item in self.actions):
            raise ValueError("opponent action plan manager IDs must match distribution manager")
        total = sum(item.probability for item in self.actions)
        if abs(total - 1.0) > 1e-10:
            raise ValueError("opponent action probabilities must sum to one")
        no_transfer = sum(item.probability for item in self.actions if item.transfer_count == 0)
        if abs(self.no_transfer_probability - no_transfer) > 1e-10:
            raise ValueError("no-transfer probability must reconcile with action vector")
        expected_transfers = sum(item.probability * item.transfer_count for item in self.actions)
        if abs(self.expected_transfer_count - expected_transfers) > 1e-10:
            raise ValueError("expected transfer count must reconcile with action vector")
        expected_hits = sum(
            item.probability * item.manager_plan.transfer_hit_points for item in self.actions
        )
        if abs(self.expected_hit_points - expected_hits) > 1e-10:
            raise ValueError("expected hit points must reconcile with action vector")
        expected_entropy = -sum(item.probability * log(item.probability) for item in self.actions)
        if abs(self.entropy - expected_entropy) > 1e-10:
            raise ValueError("entropy must reconcile with the action probability vector")
        expected_normalised_entropy = expected_entropy / log(len(self.actions))
        if abs(self.normalised_entropy - expected_normalised_entropy) > 1e-10:
            raise ValueError("normalised entropy must reconcile with the action probability vector")
        payload = self.model_dump(mode="json", exclude={"distribution_hash"})
        if self.distribution_hash != _ZERO_HASH and self.distribution_hash != semantic_sha256(
            payload
        ):
            raise ValueError("opponent action distribution hash does not reconcile")
        return self


class JointOpponentActionScenario(RankModel):
    scenario_id: StrictStr = Field(min_length=1, max_length=200)
    probability: Annotated[StrictFloat, Field(gt=0.0, le=1.0, allow_inf_nan=False)]
    action_ids: dict[StrictStr, StrictStr]
    manager_plans: dict[StrictStr, ManagerTeamPlan]

    @model_validator(mode="after")
    def joint_scenario_is_canonical(self) -> JointOpponentActionScenario:
        action_managers = tuple(self.action_ids)
        plan_managers = tuple(self.manager_plans)
        if action_managers != tuple(sorted(action_managers)):
            raise ValueError("joint action IDs must be sorted by manager ID")
        if plan_managers != tuple(sorted(plan_managers)):
            raise ValueError("joint manager plans must be sorted by manager ID")
        if action_managers != plan_managers:
            raise ValueError("joint action and plan manager sets must match")
        if any(
            self.manager_plans[manager_id].manager_id != manager_id for manager_id in plan_managers
        ):
            raise ValueError("joint plan manager IDs must match mapping keys")
        return self


class JointOpponentActionDistribution(RankModel):
    schema_version: Literal["rank-joint-opponent-action-distribution-v1"] = (
        "rank-joint-opponent-action-distribution-v1"
    )
    manager_ids: tuple[StrictStr, ...] = Field(min_length=1)
    information_cutoff: datetime
    deadline: datetime
    source_distribution_hashes: dict[StrictStr, Sha256]
    scenarios: tuple[JointOpponentActionScenario, ...] = Field(min_length=1)
    joint_hash: Sha256

    @model_validator(mode="after")
    def joint_distribution_is_valid(self) -> JointOpponentActionDistribution:
        for label, value in (
            ("information_cutoff", self.information_cutoff),
            ("deadline", self.deadline),
        ):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{label} must be timezone-aware UTC")
        if self.information_cutoff > self.deadline:
            raise ValueError("joint opponent cutoff cannot follow the deadline")
        if self.manager_ids != tuple(sorted(self.manager_ids)) or len(self.manager_ids) != len(
            set(self.manager_ids)
        ):
            raise ValueError("joint opponent manager IDs must be sorted and unique")
        if tuple(self.source_distribution_hashes) != self.manager_ids:
            raise ValueError("source distribution hashes must match manager IDs")
        identities = tuple(item.scenario_id for item in self.scenarios)
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("joint opponent scenarios must be sorted and unique")
        if abs(sum(item.probability for item in self.scenarios) - 1.0) > 1e-10:
            raise ValueError("joint opponent scenario probabilities must sum to one")
        if any(tuple(item.action_ids) != self.manager_ids for item in self.scenarios):
            raise ValueError("every joint scenario must contain every represented manager")
        if any(value == _ZERO_HASH for value in self.source_distribution_hashes.values()):
            raise ValueError("joint opponent sources cannot use unsealed hash sentinels")
        payload = self.model_dump(mode="json", exclude={"joint_hash"})
        if self.joint_hash != _ZERO_HASH and self.joint_hash != semantic_sha256(payload):
            raise ValueError("joint opponent distribution hash does not reconcile")
        return self
