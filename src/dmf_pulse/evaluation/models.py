"""Strict public contracts for the Stage-12 evaluation framework."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
Probability = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]


def require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    normalized = value.astimezone(UTC)
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must be expressed in UTC")
    return normalized


def require_canonical_payload(value: object, *, field_name: str) -> None:
    """Reject opaque values whose JSON identity is lossy or non-deterministic."""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{field_name} decimals must be finite")
        return
    if isinstance(value, float):
        raise ValueError(f"{field_name} binary floats are prohibited; use Decimal or a string")
    if isinstance(value, (list, tuple)):
        for item in value:
            require_canonical_payload(item, field_name=field_name)
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{field_name} mapping keys must be strings")
        for item in value.values():
            require_canonical_payload(item, field_name=field_name)
        return
    raise ValueError(f"{field_name} contains a non-canonical value")


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class DatasetMode(StrEnum):
    LIVE_OBSERVED = "LIVE_OBSERVED"
    RAW_OBSERVED = "RAW_OBSERVED"
    RECONSTRUCTED = "RECONSTRUCTED"
    FINAL_OUTCOME = "FINAL_OUTCOME"
    COUNTERFACTUAL = "COUNTERFACTUAL"


class OperationalUsability(StrEnum):
    LIVE_OPERATIONAL = "LIVE_OPERATIONAL"
    RECEIVED_NOT_OPERATIONAL = "RECEIVED_NOT_OPERATIONAL"
    RECONSTRUCTED_ONLY = "RECONSTRUCTED_ONLY"
    LABEL_ONLY = "LABEL_ONLY"
    COUNTERFACTUAL_ONLY = "COUNTERFACTUAL_ONLY"


class ObservationRole(StrEnum):
    FEATURE = "FEATURE"
    LABEL = "LABEL"
    MANAGER_STATE = "MANAGER_STATE"
    METADATA = "METADATA"


class ObservationKind(StrEnum):
    RECENT_POINTS = "RECENT_POINTS"
    OFFICIAL_FPL_FORM = "OFFICIAL_FPL_FORM"
    MARKET = "MARKET"
    MINUTES_DISTRIBUTION = "MINUTES_DISTRIBUTION"
    PULSE_PROJECTION = "PULSE_PROJECTION"
    FIXTURE_ASSIGNMENT = "FIXTURE_ASSIGNMENT"
    PRICE = "PRICE"
    LINEUP = "LINEUP"
    ENTITY_MAPPING = "ENTITY_MAPPING"
    PROVIDER_CORRECTION = "PROVIDER_CORRECTION"
    OUTCOME = "OUTCOME"
    MANAGER_STATE = "MANAGER_STATE"
    MODEL_SELECTION = "MODEL_SELECTION"
    OTHER = "OTHER"


class FeatureRecord(EvaluationModel):
    record_id: StrictStr = Field(min_length=1, max_length=200)
    entity_id: StrictStr = Field(min_length=1, max_length=200)
    target_id: StrictStr = Field(min_length=1, max_length=200)
    gameweek: PositiveInt
    dataset_mode: DatasetMode
    operational_usability: OperationalUsability
    role: ObservationRole
    kind: ObservationKind
    source_timestamp: datetime
    received_at: datetime
    mapped_at: datetime | None = None
    usable_at: datetime | None = None
    valid_from: datetime | None = None
    corrected_at: datetime | None = None
    target_outcome_at: datetime | None = None
    current_vintage: StrictBool = False
    feature_intended: StrictBool = True
    values: dict[StrictStr, object] = Field(default_factory=dict)
    source_snapshot_id: StrictStr | None = None
    mapping_version_id: StrictStr | None = None

    @model_validator(mode="after")
    def temporal_fields_are_utc(self) -> FeatureRecord:
        require_utc(self.source_timestamp, field_name="source_timestamp")
        require_utc(self.received_at, field_name="received_at")
        for name in ("mapped_at", "usable_at", "valid_from", "corrected_at", "target_outcome_at"):
            value = getattr(self, name)
            if value is not None:
                require_utc(value, field_name=name)
        if self.role is ObservationRole.LABEL and self.feature_intended:
            raise ValueError("label records cannot be marked as intended features")
        if self.role is ObservationRole.FEATURE and not self.feature_intended:
            raise ValueError("feature records must be marked as intended features")
        if (
            self.dataset_mode is DatasetMode.FINAL_OUTCOME
            and self.role is not ObservationRole.LABEL
        ):
            raise ValueError("FINAL_OUTCOME records are labels only")
        require_canonical_payload(self.values, field_name="feature values")
        return self


class EvaluationLineage(EvaluationModel):
    forecast_origin: datetime
    information_cutoff: datetime
    usable_at_cutoff: datetime
    training_cutoff: datetime | None = None
    label_finality_cutoff: datetime | None = None
    model_version_ids: tuple[StrictStr, ...]
    ruleset_id: StrictStr
    ruleset_hash: Sha256
    code_commit: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")
    dataset_manifest_sha256: Sha256
    input_manifest_sha256: Sha256
    fold_sha256: Sha256 | None = None
    benchmark_config_sha256: Sha256 | None = None
    metric_config_sha256: Sha256 | None = None
    random_seed: NonNegativeInt | None = None

    @model_validator(mode="after")
    def cutoffs_are_valid(self) -> EvaluationLineage:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        information = require_utc(self.information_cutoff, field_name="information_cutoff")
        usable = require_utc(self.usable_at_cutoff, field_name="usable_at_cutoff")
        if information > origin or usable > origin:
            raise ValueError("information and usable-at cutoffs cannot be after forecast origin")
        if information != usable:
            raise ValueError("Stage-12 strict information and usable-at cutoffs must be identical")
        if self.training_cutoff is not None:
            training = require_utc(self.training_cutoff, field_name="training_cutoff")
            if training > origin:
                raise ValueError("training cutoff cannot be after forecast origin")
            if training > information:
                raise ValueError("training cutoff cannot be after information cutoff")
        if self.label_finality_cutoff is not None:
            finality = require_utc(
                self.label_finality_cutoff,
                field_name="label_finality_cutoff",
            )
            if finality <= origin:
                raise ValueError("label finality cutoff must be after forecast origin")
        if self.model_version_ids != tuple(sorted(self.model_version_ids)):
            raise ValueError("model version IDs must be sorted")
        if len(self.model_version_ids) != len(set(self.model_version_ids)):
            raise ValueError("model version IDs must be unique")
        return self


class InclusionDecision(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED_EXPECTED = "EXCLUDED_EXPECTED"
    BLOCKED_LEAKAGE = "BLOCKED_LEAKAGE"


class InformationRecordDecision(EvaluationModel):
    record_id: StrictStr
    decision: InclusionDecision
    reason_code: StrictStr
    explanation: StrictStr


class InformationBundle(EvaluationModel):
    schema_version: Literal["evaluation-information-bundle-v1"] = "evaluation-information-bundle-v1"
    bundle_id: StrictStr
    dataset_mode: DatasetMode
    forecast_origin: datetime
    information_cutoff: datetime
    records: tuple[FeatureRecord, ...]
    decisions: tuple[InformationRecordDecision, ...]
    blocking_violations: tuple[StrictStr, ...]
    bundle_sha256: Sha256

    @model_validator(mode="after")
    def bundle_is_canonical(self) -> InformationBundle:
        require_utc(self.forecast_origin, field_name="forecast_origin")
        require_utc(self.information_cutoff, field_name="information_cutoff")
        ids = tuple(item.record_id for item in self.records)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("information records must be sorted and unique")
        decision_ids = tuple(item.record_id for item in self.decisions)
        if decision_ids != tuple(sorted(decision_ids)) or len(decision_ids) != len(
            set(decision_ids)
        ):
            raise ValueError("information decisions must be sorted and unique")
        if self.blocking_violations != tuple(sorted(set(self.blocking_violations))):
            raise ValueError("blocking violations must be sorted and unique")
        decision_map = {item.record_id: item.decision for item in self.decisions}
        included_ids = {item.record_id for item in self.records}
        declared_included = {
            record_id
            for record_id, decision in decision_map.items()
            if decision is InclusionDecision.INCLUDED
        }
        if included_ids != declared_included:
            raise ValueError("included information records and inclusion decisions disagree")
        declared_blocked = {
            record_id
            for record_id, decision in decision_map.items()
            if decision is InclusionDecision.BLOCKED_LEAKAGE
        }
        if declared_blocked != set(self.blocking_violations):
            raise ValueError("blocking violations and blocking decisions disagree")
        return self


class FoldWindow(StrEnum):
    EXPANDING = "EXPANDING"
    ROLLING = "ROLLING"


class InnerFold(EvaluationModel):
    fold_id: StrictStr
    training_origin_ids: tuple[StrictStr, ...]
    validation_origin_id: StrictStr
    training_cutoff: datetime
    validation_origin: datetime
    fold_sha256: Sha256

    @model_validator(mode="after")
    def inner_fold_is_temporally_ordered(self) -> InnerFold:
        cutoff = require_utc(self.training_cutoff, field_name="training_cutoff")
        validation = require_utc(self.validation_origin, field_name="validation_origin")
        if cutoff > validation:
            raise ValueError("inner-fold training cutoff cannot follow validation origin")
        if len(self.training_origin_ids) != len(set(self.training_origin_ids)):
            raise ValueError("inner-fold training origin IDs must be unique")
        if self.validation_origin_id in self.training_origin_ids:
            raise ValueError("inner-fold validation origin cannot appear in training origins")
        return self


class EvaluationFold(EvaluationModel):
    schema_version: Literal["evaluation-fold-v1"] = "evaluation-fold-v1"
    fold_id: StrictStr
    ordinal: NonNegativeInt
    forecast_origin_id: StrictStr
    forecast_origin: datetime
    information_cutoff: datetime
    training_origin_ids: tuple[StrictStr, ...]
    inner_folds: tuple[InnerFold, ...]
    dataset_mode: DatasetMode
    window: FoldWindow
    holdout: StrictBool = False
    fold_sha256: Sha256

    @model_validator(mode="after")
    def fold_is_temporally_ordered(self) -> EvaluationFold:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        if cutoff > origin:
            raise ValueError("fold information cutoff cannot follow forecast origin")
        if len(self.training_origin_ids) != len(set(self.training_origin_ids)):
            raise ValueError("training origin IDs must be unique")
        return self


class ForecastArtifact(EvaluationModel):
    schema_version: Literal["frozen-forecast-v1"] = "frozen-forecast-v1"
    forecast_id: StrictStr
    benchmark_id: StrictStr
    dataset_mode: DatasetMode
    target_id: StrictStr
    horizon: PositiveInt
    point_forecast: Decimal | None = None
    probability_forecast: Probability | None = None
    pmf: dict[StrictStr, Probability] = Field(default_factory=dict)
    scenario_samples: tuple[tuple[Decimal, ...], ...] = ()
    scenario_weights: tuple[Probability, ...] = ()
    scenario_dimension_ids: tuple[StrictStr, ...] = ()
    lineage: EvaluationLineage
    issued_at: datetime
    forecast_sha256: Sha256

    @model_validator(mode="after")
    def forecast_is_valid(self) -> ForecastArtifact:
        issued = require_utc(self.issued_at, field_name="issued_at")
        if issued > self.lineage.forecast_origin:
            raise ValueError("forecast must be issued no later than its declared origin")
        if issued < self.lineage.information_cutoff:
            raise ValueError("forecast cannot be issued before its information cutoff")
        if self.pmf and sum(self.pmf.values(), Decimal(0)) != Decimal(1):
            raise ValueError("forecast PMF must sum exactly to one")
        if self.scenario_samples:
            width = len(self.scenario_samples[0])
            if width == 0 or any(len(item) != width for item in self.scenario_samples):
                raise ValueError("scenario samples must have a fixed nonzero dimension")
            if len(self.scenario_weights) != len(self.scenario_samples):
                raise ValueError("scenario weights require one value per scenario sample")
            if sum(self.scenario_weights, Decimal(0)) != Decimal(1):
                raise ValueError("scenario weights must sum exactly to one")
            if len(self.scenario_dimension_ids) != width:
                raise ValueError("scenario dimensions require one stable ID per vector component")
            if len(self.scenario_dimension_ids) != len(set(self.scenario_dimension_ids)):
                raise ValueError("scenario dimension IDs must be unique")
        elif self.scenario_weights or self.scenario_dimension_ids:
            raise ValueError("scenario metadata cannot exist without scenario samples")
        if (
            self.point_forecast is None
            and self.probability_forecast is None
            and not self.pmf
            and not self.scenario_samples
        ):
            raise ValueError(
                "forecast requires a point, probability, PMF or joint scenario payload"
            )
        if (
            self.benchmark_id.startswith("B5")
            and self.dataset_mode is not DatasetMode.COUNTERFACTUAL
        ):
            raise ValueError("B5 frozen forecasts must use COUNTERFACTUAL dataset mode")
        return self


class OutcomeLabel(EvaluationModel):
    label_id: StrictStr
    target_id: StrictStr
    dataset_mode: Literal[DatasetMode.FINAL_OUTCOME]
    outcome: Decimal
    finalized_at: datetime
    label_sha256: Sha256

    @model_validator(mode="after")
    def finalized_is_utc(self) -> OutcomeLabel:
        require_utc(self.finalized_at, field_name="finalized_at")
        return self


class TargetFunctional(StrEnum):
    MEAN = "MEAN"
    MEDIAN = "MEDIAN"
    QUANTILE = "QUANTILE"


class PointMetricResult(EvaluationModel):
    mae: Decimal
    rmse: Decimal
    signed_bias: Decimal
    median_absolute_error: Decimal
    pinball_loss: Decimal | None = None
    target_functional: TargetFunctional
    quantile: Probability | None = None
    count: PositiveInt


class ProbabilityBoundaryPolicy(StrEnum):
    EXACT = "EXACT"
    DECLARED_EPSILON = "DECLARED_EPSILON"


class ProbabilityMetricResult(EvaluationModel):
    brier_score: Decimal
    log_loss: Decimal | None
    status: Literal["FINITE", "UNBOUNDED"]
    boundary_policy: ProbabilityBoundaryPolicy
    epsilon: Decimal | None = None
    count: PositiveInt


class MulticlassProbabilityMetricResult(EvaluationModel):
    brier_score: Decimal
    log_loss: Decimal | None
    status: Literal["FINITE", "UNBOUNDED"]
    boundary_policy: ProbabilityBoundaryPolicy
    epsilon: Decimal | None = None
    count: PositiveInt
    class_count: PositiveInt


class DistributionMetricResult(EvaluationModel):
    ranked_probability_score: Decimal
    log_score: Decimal | None
    log_score_status: Literal["FINITE", "UNBOUNDED"]
    randomized_pit: Decimal
    interval_coverage: Probability
    interval_width: Decimal
    interval_score: Decimal
    quantile_loss: Decimal


class MultivariateMetricResult(EvaluationModel):
    energy_score: Decimal
    variogram_score: Decimal
    covariance_error: Decimal
    joint_threshold_brier: Decimal
    sample_count: PositiveInt


class CalibrationResult(EvaluationModel):
    intercept: Decimal | None
    slope: Decimal | None
    status: Literal["FITTED", "INSUFFICIENT_VARIATION", "NUMERICAL_FAILURE"]
    reliability: tuple[dict[StrictStr, object], ...]
    count: PositiveInt

    @model_validator(mode="after")
    def reliability_is_canonical(self) -> CalibrationResult:
        require_canonical_payload(self.reliability, field_name="calibration reliability")
        return self


class CalibrationArtifact(EvaluationModel):
    schema_version: Literal["calibration-artifact-v1"] = "calibration-artifact-v1"
    calibration_id: StrictStr
    method: Literal["IDENTITY", "LOGISTIC", "ISOTONIC"]
    training_cutoff: datetime
    training_record_ids: tuple[StrictStr, ...]
    excluded_outer_origin_ids: tuple[StrictStr, ...]
    parameters: dict[StrictStr, Decimal]
    artifact_sha256: Sha256

    @model_validator(mode="after")
    def training_is_canonical(self) -> CalibrationArtifact:
        require_utc(self.training_cutoff, field_name="training_cutoff")
        for name in ("training_record_ids", "excluded_outer_origin_ids"):
            values = getattr(self, name)
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"{name} must be sorted and unique")
        if set(self.training_record_ids) & set(self.excluded_outer_origin_ids):
            raise ValueError("outer evaluation origins cannot train their own calibrator")
        if self.method == "IDENTITY":
            if self.parameters != {"intercept": Decimal(0), "slope": Decimal(1)}:
                raise ValueError("IDENTITY calibration parameters must be exactly (0, 1)")
        elif self.method == "LOGISTIC":
            if set(self.parameters) != {"intercept", "slope"}:
                raise ValueError("LOGISTIC calibration requires intercept and slope parameters")
        else:
            if not self.parameters or len(self.parameters) % 2:
                raise ValueError("ISOTONIC calibration requires threshold/value parameter pairs")
            pair_count = len(self.parameters) // 2
            expected = {
                key
                for index in range(pair_count)
                for key in (f"threshold_{index}", f"value_{index}")
            }
            if set(self.parameters) != expected:
                raise ValueError("ISOTONIC calibration parameter indices must be contiguous")
            thresholds = tuple(self.parameters[f"threshold_{index}"] for index in range(pair_count))
            values = tuple(self.parameters[f"value_{index}"] for index in range(pair_count))
            if any(not Decimal(0) <= item <= Decimal(1) for item in (*thresholds, *values)):
                raise ValueError("ISOTONIC thresholds and values must lie in [0, 1]")
            if any(left >= right for left, right in pairwise(thresholds)):
                raise ValueError("ISOTONIC thresholds must be strictly increasing")
            if values != tuple(sorted(values)):
                raise ValueError("ISOTONIC values must be nondecreasing")
        return self


class BenchmarkFamily(StrEnum):
    B0 = "B0"
    B1 = "B1"
    B2 = "B2"
    B3 = "B3"
    B4 = "B4"
    B5 = "B5"


class BenchmarkDefinition(EvaluationModel):
    benchmark_id: StrictStr
    family: BenchmarkFamily
    name: StrictStr
    feasible: StrictBool
    oracle: StrictBool
    required_inputs: tuple[ObservationKind, ...]
    prohibited_inputs: tuple[ObservationKind, ...]
    description: StrictStr

    @model_validator(mode="after")
    def oracle_is_not_feasible(self) -> BenchmarkDefinition:
        if self.oracle and self.feasible:
            raise ValueError("hindsight oracle cannot be labelled feasible")
        if self.family is BenchmarkFamily.B5 and not self.oracle:
            raise ValueError("B5 must be labelled as an oracle")
        if self.family is not BenchmarkFamily.B5 and (self.oracle or not self.feasible):
            raise ValueError("B0-B4 benchmarks must remain feasible and non-oracle")
        if set(self.required_inputs) & set(self.prohibited_inputs):
            raise ValueError("benchmark input cannot be both required and prohibited")
        return self


class BenchmarkProjection(EvaluationModel):
    benchmark: BenchmarkDefinition
    dataset_mode: DatasetMode
    target_id: StrictStr
    point_forecast: Decimal
    evidence_record_ids: tuple[StrictStr, ...]
    forecast_origin: datetime
    information_cutoff: datetime
    information_bundle_sha256: Sha256
    projection_sha256: Sha256

    @model_validator(mode="after")
    def evidence_is_canonical(self) -> BenchmarkProjection:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        if cutoff > origin:
            raise ValueError("benchmark information cutoff cannot follow forecast origin")
        if self.evidence_record_ids != tuple(sorted(self.evidence_record_ids)):
            raise ValueError("benchmark evidence IDs must be sorted")
        if len(self.evidence_record_ids) != len(set(self.evidence_record_ids)):
            raise ValueError("benchmark evidence IDs must be unique")
        if self.benchmark.oracle and self.dataset_mode is not DatasetMode.COUNTERFACTUAL:
            raise ValueError("oracle benchmark projections must use COUNTERFACTUAL mode")
        return self


class PolicyDecisionArtifact(EvaluationModel):
    schema_version: Literal["frozen-policy-decision-v1"] = "frozen-policy-decision-v1"
    decision_id: StrictStr
    gameweek: PositiveInt
    forecast_origin: datetime
    current_action: dict[StrictStr, object]
    future_policy: tuple[dict[StrictStr, object], ...] = ()
    expected_utility: Decimal
    dataset_mode: DatasetMode
    lineage: EvaluationLineage
    decision_sha256: Sha256

    @model_validator(mode="after")
    def decision_time_is_valid(self) -> PolicyDecisionArtifact:
        require_utc(self.forecast_origin, field_name="forecast_origin")
        if self.forecast_origin != self.lineage.forecast_origin:
            raise ValueError("decision and lineage forecast origins differ")
        if not self.current_action:
            raise ValueError("policy decision requires one non-empty current/root action")
        require_canonical_payload(self.current_action, field_name="current action")
        require_canonical_payload(self.future_policy, field_name="future policy")
        return self


class PolicyTrajectoryStep(EvaluationModel):
    gameweek: PositiveInt
    forecast_origin: datetime
    information_bundle_sha256: Sha256
    forecast_sha256: Sha256
    decision_sha256: Sha256
    executed_action: dict[StrictStr, object]
    realised_utility: Decimal
    utility_includes_hit_costs: Literal[True]
    outcome_revealed_at: datetime
    state_before_sha256: Sha256
    state_after_sha256: Sha256
    outcome_revealed_after_freeze: StrictBool

    @model_validator(mode="after")
    def step_time_is_utc(self) -> PolicyTrajectoryStep:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        revealed = require_utc(self.outcome_revealed_at, field_name="outcome_revealed_at")
        if revealed <= origin:
            raise ValueError("outcome must be revealed after forecast freeze")
        require_canonical_payload(self.executed_action, field_name="executed action")
        return self


class PolicyTrajectory(EvaluationModel):
    schema_version: Literal["policy-trajectory-v1"] = "policy-trajectory-v1"
    trajectory_id: StrictStr
    dataset_mode: DatasetMode
    initial_state_sha256: Sha256
    steps: tuple[PolicyTrajectoryStep, ...]
    cumulative_utility: Decimal
    root_action_only: Literal[True] = True
    trajectory_sha256: Sha256

    @model_validator(mode="after")
    def trajectory_reconciles(self) -> PolicyTrajectory:
        if not self.steps:
            raise ValueError("policy trajectory requires at least one step")
        if (
            sum((item.realised_utility for item in self.steps), Decimal(0))
            != self.cumulative_utility
        ):
            raise ValueError("trajectory utility does not reconcile")
        if not all(item.outcome_revealed_after_freeze for item in self.steps):
            raise ValueError("every outcome must be revealed after forecast/decision freeze")
        ordered = tuple(sorted(self.steps, key=lambda item: (item.forecast_origin, item.gameweek)))
        if self.steps != ordered:
            raise ValueError("policy trajectory steps must be chronologically ordered")
        if len({item.gameweek for item in self.steps}) != len(self.steps):
            raise ValueError("policy trajectory gameweeks must be unique")
        if self.initial_state_sha256 != self.steps[0].state_before_sha256:
            raise ValueError("trajectory initial state does not match the first step")
        for previous, current in zip(self.steps, self.steps[1:], strict=False):
            if previous.state_after_sha256 != current.state_before_sha256:
                raise ValueError("policy trajectory state hashes do not form a continuous chain")
            if previous.gameweek >= current.gameweek:
                raise ValueError("policy trajectory gameweeks must be strictly increasing")
            if previous.outcome_revealed_at > current.forecast_origin:
                raise ValueError("policy outcome was unavailable before the next forecast")
        return self


class ComparatorInformationSet(StrEnum):
    SAME_HISTORICAL_INFORMATION = "SAME_HISTORICAL_INFORMATION"
    COUNTERFACTUAL_HINDSIGHT = "COUNTERFACTUAL_HINDSIGHT"


class DecisionRegret(EvaluationModel):
    schema_version: Literal["decision-regret-v1"] = "decision-regret-v1"
    decision_id: StrictStr
    comparator_id: StrictStr
    comparator_information_set: ComparatorInformationSet
    comparator_is_oracle: StrictBool
    horizon_gameweeks: PositiveInt = 1
    outcome_convention: Literal["REALISED_PATH", "COUNTERFACTUAL_PATH"] = "REALISED_PATH"
    utilities_include_hit_costs: Literal[True] = True
    realised_decision_utility: Decimal
    realised_comparator_utility: Decimal
    regret: Decimal
    transfer_hit_points: Decimal = Field(ge=Decimal(0))
    hit_adjusted_transfer_value: Decimal | None
    no_transfer_utility: Decimal | None = None
    regret_sha256: Sha256

    @model_validator(mode="after")
    def regret_reconciles(self) -> DecisionRegret:
        expected = self.realised_comparator_utility - self.realised_decision_utility
        if expected != self.regret:
            raise ValueError("decision regret does not reconcile")
        if self.comparator_is_oracle != (
            self.comparator_information_set is ComparatorInformationSet.COUNTERFACTUAL_HINDSIGHT
        ):
            raise ValueError("oracle label and comparator information set disagree")
        if (self.no_transfer_utility is None) != (self.hit_adjusted_transfer_value is None):
            raise ValueError("hit-adjusted transfer value requires a no-transfer comparator")
        if self.no_transfer_utility is not None and self.hit_adjusted_transfer_value != (
            self.realised_decision_utility - self.no_transfer_utility
        ):
            raise ValueError("hit-adjusted transfer value does not reconcile")
        return self


class LeakageKind(StrEnum):
    FUTURE_LEAKAGE_CANARY = "FUTURE_LEAKAGE_CANARY"
    FIXTURE_MOVED_AFTER_CUTOFF = "FIXTURE_MOVED_AFTER_CUTOFF"
    PRICE_CORRECTION_AFTER_CUTOFF = "PRICE_CORRECTION_AFTER_CUTOFF"
    CLOSING_ODDS_AFTER_CUTOFF = "CLOSING_ODDS_AFTER_CUTOFF"
    POSTDEADLINE_LINEUP = "POSTDEADLINE_LINEUP"
    LATE_ENTITY_MAPPING = "LATE_ENTITY_MAPPING"
    LATE_PROVIDER_CORRECTION = "LATE_PROVIDER_CORRECTION"
    FUTURE_RESULT_IN_RECENT_WINDOW = "FUTURE_RESULT_IN_RECENT_WINDOW"
    OUTER_FOLD_CONTAMINATION = "OUTER_FOLD_CONTAMINATION"
    CURRENT_VINTAGE_CONTAMINATION = "CURRENT_VINTAGE_CONTAMINATION"
    USABLE_AT_AFTER_CUTOFF = "USABLE_AT_AFTER_CUTOFF"
    RAW_OBSERVED_IN_STRICT_LIVE = "RAW_OBSERVED_IN_STRICT_LIVE"
    NON_LIVE_EVIDENCE_IN_STRICT_LIVE = "NON_LIVE_EVIDENCE_IN_STRICT_LIVE"
    MISSING_STRICT_LINEAGE = "MISSING_STRICT_LINEAGE"
    SOURCE_TIMESTAMP_AFTER_CUTOFF = "SOURCE_TIMESTAMP_AFTER_CUTOFF"
    TARGET_OUTCOME_AS_FEATURE = "TARGET_OUTCOME_AS_FEATURE"


class LeakageFinding(EvaluationModel):
    finding_id: StrictStr
    kind: LeakageKind
    record_ids: tuple[StrictStr, ...]
    blocking: Literal[True] = True
    explanation: StrictStr


class LeakageReport(EvaluationModel):
    schema_version: Literal["leakage-report-v1"] = "leakage-report-v1"
    status: Literal["PASS", "BLOCKED"]
    dataset_mode: DatasetMode
    forecast_origin: datetime
    findings: tuple[LeakageFinding, ...]
    checked_record_count: NonNegativeInt
    report_sha256: Sha256

    @model_validator(mode="after")
    def status_matches_findings(self) -> LeakageReport:
        require_utc(self.forecast_origin, field_name="forecast_origin")
        if (self.status == "BLOCKED") != bool(self.findings):
            raise ValueError("leakage status and findings disagree")
        finding_ids = tuple(item.finding_id for item in self.findings)
        if finding_ids != tuple(sorted(finding_ids)) or len(finding_ids) != len(set(finding_ids)):
            raise ValueError("leakage findings must be sorted and unique")
        return self


class MetricFamily(StrEnum):
    POINT = "POINT"
    PROBABILITY = "PROBABILITY"
    DISTRIBUTION = "DISTRIBUTION"
    MULTIVARIATE = "MULTIVARIATE"
    DECISION = "DECISION"
    OPERATIONAL = "OPERATIONAL"


class ScorecardRow(EvaluationModel):
    layer: Literal["FORECAST", "DISTRIBUTION", "DECISION", "OPERATIONAL"]
    metric_family: MetricFamily
    dataset_mode: DatasetMode
    forecast_origin: datetime
    information_cutoff: datetime
    horizon: PositiveInt
    subgroup: StrictStr
    benchmark_id: StrictStr
    metric_name: StrictStr
    metric_value: Decimal | None
    status: StrictStr
    limitations: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def scorecard_row_is_temporally_valid(self) -> ScorecardRow:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        if cutoff > origin:
            raise ValueError("scorecard information cutoff cannot follow forecast origin")
        if self.limitations != tuple(sorted(set(self.limitations))):
            raise ValueError("scorecard limitations must be sorted and unique")
        allowed_layers = {
            MetricFamily.POINT: "FORECAST",
            MetricFamily.PROBABILITY: "DISTRIBUTION",
            MetricFamily.DISTRIBUTION: "DISTRIBUTION",
            MetricFamily.MULTIVARIATE: "DISTRIBUTION",
            MetricFamily.DECISION: "DECISION",
            MetricFamily.OPERATIONAL: "OPERATIONAL",
        }
        if self.layer != allowed_layers[self.metric_family]:
            raise ValueError("scorecard metric family is assigned to the wrong reporting panel")
        if self.benchmark_id.startswith("B5"):
            labels = " ".join(self.limitations).upper()
            if self.dataset_mode is not DatasetMode.COUNTERFACTUAL:
                raise ValueError("B5 report rows must use COUNTERFACTUAL dataset mode")
            if "HINDSIGHT" not in labels or "UNATTAINABLE" not in labels:
                raise ValueError("B5 report rows must declare hindsight and unattainable status")
        return self


class EvaluationReport(EvaluationModel):
    schema_version: Literal["evaluation-report-v1"] = "evaluation-report-v1"
    report_id: StrictStr
    rows: tuple[ScorecardRow, ...]
    dataset_modes: tuple[DatasetMode, ...]
    headline_mode: DatasetMode | None
    forecast_rows: NonNegativeInt
    distribution_rows: NonNegativeInt
    decision_rows: NonNegativeInt
    operational_rows: NonNegativeInt
    limitations: tuple[StrictStr, ...]
    lineage: EvaluationLineage
    report_sha256: Sha256

    @model_validator(mode="after")
    def report_is_separated(self) -> EvaluationReport:
        if not self.rows:
            raise ValueError("evaluation report requires at least one scorecard row")
        if len(self.rows) != len(set(self.rows)):
            raise ValueError("evaluation report rows must be unique")
        if self.limitations != tuple(sorted(set(self.limitations))):
            raise ValueError("evaluation report limitations must be sorted and unique")
        row_modes = tuple(sorted({row.dataset_mode for row in self.rows}, key=str))
        if row_modes != self.dataset_modes:
            raise ValueError("report dataset modes do not match row modes")
        if len(self.dataset_modes) > 1 and self.headline_mode is not None:
            raise ValueError("mixed dataset modes cannot have one headline mode")
        if len(self.dataset_modes) == 1 and self.headline_mode != self.dataset_modes[0]:
            raise ValueError("single-mode report must identify its headline mode")
        counts = {
            "FORECAST": self.forecast_rows,
            "DISTRIBUTION": self.distribution_rows,
            "DECISION": self.decision_rows,
            "OPERATIONAL": self.operational_rows,
        }
        for layer, expected in counts.items():
            if sum(row.layer == layer for row in self.rows) != expected:
                raise ValueError(f"{layer.lower()} row count does not reconcile")
        return self
