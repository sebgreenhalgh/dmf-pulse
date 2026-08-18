"""Strict public contracts for Stage-13 price prediction."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from dmf_pulse.evaluation.models import CalibrationArtifact, DatasetMode

Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
Probability = Annotated[Decimal, Field(ge=Decimal(0), le=Decimal(1))]
Percentage = Annotated[Decimal, Field(ge=Decimal(0), le=Decimal(100))]


def require_utc(value: datetime, *, field_name: str) -> datetime:
    """Require an explicitly UTC timestamp; display-zone conversion is downstream."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must be expressed in UTC")
    return value.astimezone(UTC)


def _reject_binary_floats(value: object, *, field_name: str = "payload") -> None:
    if isinstance(value, float):
        raise ValueError(f"{field_name} binary floats are prohibited; use Decimal or a string")
    if isinstance(value, dict):
        for item in value.values():
            _reject_binary_floats(item, field_name=field_name)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_binary_floats(item, field_name=field_name)


class PriceModel(BaseModel):
    """Frozen and strict base model with exact-decimal boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def binary_floats_are_forbidden(cls, value: object) -> object:
        _reject_binary_floats(value)
        return value


class PriceEvent(StrEnum):
    FALL = "FALL"
    NO_CHANGE = "NO_CHANGE"
    RISE = "RISE"
    AMBIGUOUS = "AMBIGUOUS"
    MISSING = "MISSING"


MODELED_EVENTS = (PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE)


class PriceStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    DOUBTFUL = "DOUBTFUL"
    INJURED = "INJURED"
    SUSPENDED = "SUSPENDED"
    UNAVAILABLE = "UNAVAILABLE"
    LEFT_LEAGUE = "LEFT_LEAGUE"
    UNKNOWN = "UNKNOWN"


class ObservationKind(StrEnum):
    ORDINARY = "ORDINARY"
    SOURCE_CORRECTION = "SOURCE_CORRECTION"
    SUPERSESSION = "SUPERSESSION"


class LabelConfidence(StrEnum):
    EXACT = "EXACT"
    INTERVAL_CENSORED = "INTERVAL_CENSORED"
    AMBIGUOUS = "AMBIGUOUS"
    MISSING = "MISSING"


class FlowAnomalyKind(StrEnum):
    GAMEWEEK_COUNTER_RESET = "GAMEWEEK_COUNTER_RESET"
    SOURCE_CORRECTION_COUNTER_DROP = "SOURCE_CORRECTION_COUNTER_DROP"
    CUMULATIVE_COUNTER_DECREASE = "CUMULATIVE_COUNTER_DECREASE"
    DUPLICATE_SNAPSHOT = "DUPLICATE_SNAPSHOT"
    MISSING_SNAPSHOT = "MISSING_SNAPSHOT"
    STALE_SNAPSHOT = "STALE_SNAPSHOT"
    OUT_OF_ORDER_SNAPSHOT = "OUT_OF_ORDER_SNAPSHOT"
    TIMESTAMP_COLLISION = "TIMESTAMP_COLLISION"


class ChipContaminationState(StrEnum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class OwnershipRegime(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class ConfidenceGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class ActivationStatus(StrEnum):
    ENGINEERING_READY = "ENGINEERING_READY"
    SHADOW_ONLY = "SHADOW_ONLY"
    TARGET_SEASON_UNCALIBRATED = "TARGET_SEASON_UNCALIBRATED"
    RIGHTS_BLOCKED = "RIGHTS_BLOCKED"
    INSUFFICIENT_EVENTS = "INSUFFICIENT_EVENTS"
    CALIBRATION_BLOCKED = "CALIBRATION_BLOCKED"
    PRODUCTION_ELIGIBLE = "PRODUCTION_ELIGIBLE"


class ModelFamily(StrEnum):
    P0_NO_CHANGE = "P0_NO_CHANGE"
    P1_REGULARIZED_COMPETING_LOGIT = "P1_REGULARIZED_COMPETING_LOGIT"
    P2_RECURRENT_LATENT_PRESSURE = "P2_RECURRENT_LATENT_PRESSURE"
    P3_GBDT_CHALLENGER = "P3_GBDT_CHALLENGER"


class ChallengerStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DEPENDENCY_NOT_APPROVED = "DEPENDENCY_NOT_APPROVED"
    DEFERRED = "DEFERRED"


class ModelDisagreementStatus(StrEnum):
    AGREEMENT = "AGREEMENT"
    MATERIAL_DISAGREEMENT = "MATERIAL_DISAGREEMENT"
    CHALLENGER_DEFERRED = "CHALLENGER_DEFERRED"


class ExternalPredictorProvider(StrEnum):
    OFFICIAL_FPL_PREDICTOR = "OFFICIAL_FPL_PREDICTOR"
    LIVEFPL = "LIVEFPL"
    FANTASY_FOOTBALL_FIX = "FANTASY_FOOTBALL_FIX"
    OTHER_APPROVED_EXTERNAL = "OTHER_APPROVED_EXTERNAL"


class EarlyTransferAction(StrEnum):
    ACT_NOW = "ACT_NOW"
    WAIT_FOR_INFORMATION = "WAIT_FOR_INFORMATION"
    DO_NOT_TRANSFER = "DO_NOT_TRANSFER"
    ALTERNATIVE_ROUTE = "ALTERNATIVE_ROUTE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class PriceObservation(PriceModel):
    schema_version: Literal["price-observation-v1"] = "price-observation-v1"
    observation_id: StrictStr = Field(min_length=1, max_length=200)
    player_id: StrictStr = Field(min_length=1, max_length=100)
    season: StrictStr = Field(min_length=1, max_length=20)
    gameweek: PositiveInt
    source_snapshot_id: StrictStr = Field(min_length=1, max_length=200)
    observed_at: datetime
    received_at: datetime
    usable_at: datetime
    current_price_units: NonNegativeInt
    ownership_percent: Percentage
    transfers_in_total: NonNegativeInt
    transfers_out_total: NonNegativeInt
    transfers_in_event: NonNegativeInt
    transfers_out_event: NonNegativeInt
    player_status: PriceStatus
    status_observed_at: datetime
    source: StrictStr = Field(min_length=1, max_length=100)
    rights_profile_id: StrictStr = Field(min_length=1, max_length=200)
    dataset_mode: DatasetMode
    payload_hash: Sha256
    semantic_hash: Sha256
    observation_kind: ObservationKind = ObservationKind.ORDINARY
    supersedes_observation_id: StrictStr | None = None

    @model_validator(mode="after")
    def temporal_and_mode_contract(self) -> PriceObservation:
        observed = require_utc(self.observed_at, field_name="observed_at")
        received = require_utc(self.received_at, field_name="received_at")
        usable = require_utc(self.usable_at, field_name="usable_at")
        status_time = require_utc(self.status_observed_at, field_name="status_observed_at")
        if observed > received or received > usable:
            raise ValueError("price observation times must satisfy observed <= received <= usable")
        if status_time > usable:
            raise ValueError("status observation cannot become known after usable_at")
        if self.dataset_mode is DatasetMode.FINAL_OUTCOME:
            raise ValueError("price observations are features, not FINAL_OUTCOME labels")
        if self.observation_kind is ObservationKind.ORDINARY and self.supersedes_observation_id:
            raise ValueError("ordinary observations cannot declare supersession lineage")
        if (
            self.observation_kind is not ObservationKind.ORDINARY
            and not self.supersedes_observation_id
        ):
            raise ValueError("correction/supersession observations require predecessor lineage")
        return self


class ExternalPredictorObservation(PriceModel):
    schema_version: Literal["external-price-predictor-observation-v1"] = (
        "external-price-predictor-observation-v1"
    )
    observation_id: StrictStr
    external_predictor_key: StrictStr
    provider: ExternalPredictorProvider
    player_id: StrictStr
    direction: Literal[PriceEvent.RISE, PriceEvent.FALL]
    displayed_progress: Decimal | None = Field(default=None, ge=Decimal(0))
    predicted_progress: Decimal | None = Field(default=None, ge=Decimal(0))
    displayed_categorical_signal: StrictStr | None = None
    predicted_progress_available_at: datetime | None = None
    observed_at: datetime
    received_at: datetime
    usable_at: datetime
    source: StrictStr
    source_snapshot_id: StrictStr
    rights_profile_id: StrictStr
    schema_revision: StrictStr
    dataset_mode: DatasetMode
    payload_hash: Sha256
    semantic_hash: Sha256

    @model_validator(mode="after")
    def temporal_contract(self) -> ExternalPredictorObservation:
        observed = require_utc(self.observed_at, field_name="observed_at")
        received = require_utc(self.received_at, field_name="received_at")
        usable = require_utc(self.usable_at, field_name="usable_at")
        if observed > received or received > usable:
            raise ValueError("predictor times must satisfy observed <= received <= usable")
        if self.predicted_progress_available_at is not None:
            available = require_utc(
                self.predicted_progress_available_at,
                field_name="predicted_progress_available_at",
            )
            if self.predicted_progress is not None and observed < available:
                raise ValueError(
                    "predicted progress cannot be backfilled before field availability"
                )
        if (
            self.displayed_progress is None
            and self.predicted_progress is None
            and self.displayed_categorical_signal is None
        ):
            raise ValueError("external predictor observation requires an observed signal")
        if self.dataset_mode is DatasetMode.FINAL_OUTCOME:
            raise ValueError("predictor observations cannot be FINAL_OUTCOME labels")
        return self


class PriceUpdateWindow(PriceModel):
    cycle_id: StrictStr
    cycle_start: datetime
    cycle_end: datetime
    information_cutoff: datetime
    event_effective_at: datetime | None = None

    @model_validator(mode="after")
    def valid_window(self) -> PriceUpdateWindow:
        start = require_utc(self.cycle_start, field_name="cycle_start")
        end = require_utc(self.cycle_end, field_name="cycle_end")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        if start >= end:
            raise ValueError("price update window must have positive duration")
        if cutoff > start:
            raise ValueError("cycle information cutoff cannot follow cycle start")
        if self.event_effective_at is not None:
            effective = require_utc(self.event_effective_at, field_name="event_effective_at")
            if not start <= effective <= end:
                raise ValueError("known event effective time must lie inside its cycle")
        return self


class PriceUpdateCycle(PriceModel):
    schema_version: Literal["price-update-cycle-v1"] = "price-update-cycle-v1"
    cycle_id: StrictStr
    player_id: StrictStr
    season: StrictStr
    gameweek: PositiveInt
    cycle_start: datetime
    cycle_end: datetime
    information_cutoff: datetime
    pre_update_observation_id: StrictStr | None
    post_update_observation_id: StrictStr | None
    prior_price_units: NonNegativeInt | None
    resulting_price_units: NonNegativeInt | None
    event: PriceEvent
    event_effective_at: datetime | None
    event_effective_interval_start: datetime | None
    event_effective_interval_end: datetime | None
    event_first_observed_at: datetime | None
    label_confidence: LabelConfidence
    correction_lineage: tuple[StrictStr, ...] = ()
    dataset_mode: DatasetMode

    @model_validator(mode="after")
    def cycle_contract(self) -> PriceUpdateCycle:
        start = require_utc(self.cycle_start, field_name="cycle_start")
        end = require_utc(self.cycle_end, field_name="cycle_end")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        if not cutoff <= start < end:
            raise ValueError("cycle cutoff/start/end ordering is invalid")
        for name in (
            "event_effective_at",
            "event_effective_interval_start",
            "event_effective_interval_end",
            "event_first_observed_at",
        ):
            value = getattr(self, name)
            if value is not None:
                require_utc(value, field_name=name)
        if self.correction_lineage != tuple(sorted(set(self.correction_lineage))):
            raise ValueError("correction lineage must be sorted and unique")
        if self.event is PriceEvent.MISSING:
            if self.label_confidence is not LabelConfidence.MISSING:
                raise ValueError("missing cycle requires missing confidence")
        elif self.prior_price_units is None or self.resulting_price_units is None:
            raise ValueError("non-missing cycle requires both prices")
        if self.event in MODELED_EVENTS and self.label_confidence is LabelConfidence.AMBIGUOUS:
            raise ValueError("modeled event cannot have ambiguous confidence")
        if (
            self.event is PriceEvent.AMBIGUOUS
            and self.label_confidence is not LabelConfidence.AMBIGUOUS
        ):
            raise ValueError("ambiguous event requires ambiguous confidence")
        if self.prior_price_units is not None and self.resulting_price_units is not None:
            difference = self.resulting_price_units - self.prior_price_units
            expected_difference = {
                PriceEvent.FALL: -1,
                PriceEvent.NO_CHANGE: 0,
                PriceEvent.RISE: 1,
            }
            if self.event in expected_difference and difference != expected_difference[self.event]:
                raise ValueError("price-cycle event does not match its integer price transition")
        interval_values = (
            self.event_effective_interval_start,
            self.event_effective_interval_end,
            self.event_first_observed_at,
        )
        changed = self.event in {PriceEvent.FALL, PriceEvent.RISE, PriceEvent.AMBIGUOUS}
        if changed and any(value is None for value in interval_values):
            raise ValueError("changed/ambiguous cycle requires a complete observation interval")
        if not changed and any(value is not None for value in interval_values):
            raise ValueError("unchanged/missing cycle cannot declare a change interval")
        if all(value is not None for value in interval_values):
            interval_start, interval_end, first_observed = interval_values
            assert interval_start is not None
            assert interval_end is not None
            assert first_observed is not None
            if not interval_start < interval_end or first_observed != interval_end:
                raise ValueError("price-cycle observation interval is inconsistent")
        if self.event_effective_at is not None:
            if self.label_confidence is not LabelConfidence.EXACT or not changed:
                raise ValueError("exact event time requires an exact changed-cycle label")
            if not start <= self.event_effective_at <= end:
                raise ValueError("exact event time lies outside the declared update cycle")
        return self


class FlowAnomaly(PriceModel):
    kind: FlowAnomalyKind
    observation_ids: tuple[StrictStr, ...]
    detail: StrictStr


class TransferFlowContext(PriceModel):
    active_manager_count: PositiveInt | None = None
    global_transfer_activity: NonNegativeInt | None = None
    previous_event: PriceEvent = PriceEvent.NO_CHANGE
    hours_since_last_rise: Decimal | None = Field(default=None, ge=Decimal(0))
    hours_since_last_fall: Decimal | None = Field(default=None, ge=Decimal(0))
    hours_since_any_change: Decimal | None = Field(default=None, ge=Decimal(0))
    net_since_deadline: StrictInt = 0
    net_since_last_rise: StrictInt = 0
    net_since_last_fall: StrictInt = 0
    net_since_any_change: StrictInt = 0
    hours_since_deadline: Decimal = Field(ge=Decimal(0))
    hours_to_next_deadline: Decimal = Field(ge=Decimal(0))
    player_match_complete: StrictBool | None = None
    chip_contamination: ChipContaminationState = ChipContaminationState.UNKNOWN
    chip_contamination_confidence: Probability = Decimal(0)

    @model_validator(mode="after")
    def previous_event_is_observed(self) -> TransferFlowContext:
        if self.previous_event not in MODELED_EVENTS:
            raise ValueError("feature context previous event must be a modeled observed event")
        return self


class TransferFlowFeatures(PriceModel):
    schema_version: Literal["transfer-flow-features-v1"] = "transfer-flow-features-v1"
    player_id: StrictStr
    season: StrictStr
    gameweek: PositiveInt
    information_cutoff: datetime
    observation_ids: tuple[StrictStr, ...]
    transfer_in_increment: NonNegativeInt
    transfer_out_increment: NonNegativeInt
    net_increment: StrictInt
    gross_increment: NonNegativeInt
    elapsed_hours: Decimal = Field(gt=Decimal(0))
    buys_per_hour: Decimal = Field(ge=Decimal(0))
    sells_per_hour: Decimal = Field(ge=Decimal(0))
    net_per_hour: Decimal
    ewma_short_net_per_hour: Decimal
    ewma_long_net_per_hour: Decimal
    short_long_momentum: Decimal
    acceleration: Decimal
    persistence_fraction: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    consecutive_positive_intervals: NonNegativeInt
    consecutive_negative_intervals: NonNegativeInt
    net_since_deadline: StrictInt
    net_since_last_rise: StrictInt
    net_since_last_fall: StrictInt
    net_since_any_change: StrictInt
    previous_event: PriceEvent
    hours_since_last_rise: Decimal | None
    hours_since_last_fall: Decimal | None
    hours_since_any_change: Decimal | None
    ownership_percent: Percentage
    ownership_regime: OwnershipRegime
    estimated_owner_pool: Decimal | None = Field(default=None, ge=Decimal(0))
    estimated_nonowner_pool: Decimal | None = Field(default=None, ge=Decimal(0))
    buy_rate_nonowners: Decimal | None = Field(default=None, ge=Decimal(0))
    sell_rate_owners: Decimal | None = Field(default=None, ge=Decimal(0))
    denominator_uncertainty: Probability
    global_activity_share: Decimal | None = Field(default=None, ge=Decimal(0))
    global_activity_regime: Literal["LOW", "NORMAL", "HIGH", "UNKNOWN"]
    current_status: PriceStatus
    status_transition: StrictStr
    status_age_hours: Decimal = Field(ge=Decimal(0))
    status_uncertainty: Probability
    hours_since_deadline: Decimal = Field(ge=Decimal(0))
    hours_to_next_deadline: Decimal = Field(ge=Decimal(0))
    player_match_complete: StrictBool | None
    chip_contamination: ChipContaminationState
    chip_contamination_confidence: Probability
    anomalies: tuple[FlowAnomaly, ...]
    dataset_mode: DatasetMode

    @model_validator(mode="after")
    def feature_contract(self) -> TransferFlowFeatures:
        require_utc(self.information_cutoff, field_name="information_cutoff")
        if len(self.observation_ids) < 2 or len(self.observation_ids) != len(
            set(self.observation_ids)
        ):
            raise ValueError("flow features require at least two unique observations")
        if self.net_increment != self.transfer_in_increment - self.transfer_out_increment:
            raise ValueError("net transfer increment does not reconcile")
        if self.gross_increment != self.transfer_in_increment + self.transfer_out_increment:
            raise ValueError("gross transfer increment does not reconcile")
        if self.previous_event not in MODELED_EVENTS:
            raise ValueError("previous event must be rise, fall or no-change")
        return self


class FeatureValue(PriceModel):
    name: StrictStr = Field(min_length=1, max_length=100)
    value: Decimal


class PriceFeatureVector(PriceModel):
    schema_version: Literal["price-feature-vector-v1"] = "price-feature-vector-v1"
    vector_id: StrictStr
    player_id: StrictStr
    information_cutoff: datetime
    values: tuple[FeatureValue, ...]

    @model_validator(mode="after")
    def canonical_vector(self) -> PriceFeatureVector:
        require_utc(self.information_cutoff, field_name="information_cutoff")
        names = tuple(item.name for item in self.values)
        if not names or names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("feature names must be non-empty, sorted and unique")
        return self

    def as_mapping(self) -> dict[str, Decimal]:
        return {item.name: item.value for item in self.values}


class PriceTrainingExample(PriceModel):
    example_id: StrictStr
    feature_vector: PriceFeatureVector
    event: Literal[PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE]
    label_available_at: datetime
    dataset_mode: DatasetMode

    @model_validator(mode="after")
    def label_follows_prediction(self) -> PriceTrainingExample:
        label = require_utc(self.label_available_at, field_name="label_available_at")
        if label <= self.feature_vector.information_cutoff:
            raise ValueError("price label must become available after its feature cutoff")
        return self


class EventCoefficients(PriceModel):
    event: Literal[PriceEvent.FALL, PriceEvent.RISE]
    intercept: Decimal
    coefficients: tuple[FeatureValue, ...]

    @model_validator(mode="after")
    def canonical_coefficients(self) -> EventCoefficients:
        names = tuple(item.name for item in self.coefficients)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("coefficient feature names must be sorted and unique")
        return self


class CompetingLogitArtifact(PriceModel):
    schema_version: Literal["competing-logit-artifact-v1"] = "competing-logit-artifact-v1"
    model_id: StrictStr
    model_family: Literal[ModelFamily.P1_REGULARIZED_COMPETING_LOGIT] = (
        ModelFamily.P1_REGULARIZED_COMPETING_LOGIT
    )
    model_version: StrictStr
    feature_schema_version: StrictStr
    feature_names: tuple[StrictStr, ...]
    event_coefficients: tuple[EventCoefficients, EventCoefficients]
    regularization_l2: Decimal = Field(ge=Decimal(0))
    learning_rate: Decimal = Field(gt=Decimal(0))
    epochs: PositiveInt
    score_cap: Decimal = Field(gt=Decimal(0))
    training_cutoff: datetime
    training_example_ids: tuple[StrictStr, ...]
    dataset_modes: tuple[DatasetMode, ...]
    calibration_version: StrictStr
    configuration_sha256: Sha256
    artifact_sha256: Sha256

    @model_validator(mode="after")
    def artifact_contract(self) -> CompetingLogitArtifact:
        require_utc(self.training_cutoff, field_name="training_cutoff")
        if self.feature_names != tuple(sorted(set(self.feature_names))) or not self.feature_names:
            raise ValueError("model feature names must be sorted, unique and non-empty")
        if self.training_example_ids != tuple(sorted(set(self.training_example_ids))):
            raise ValueError("training example IDs must be sorted and unique")
        if tuple(item.event for item in self.event_coefficients) != (
            PriceEvent.FALL,
            PriceEvent.RISE,
        ):
            raise ValueError("competing-logit coefficients must be ordered FALL, RISE")
        expected = self.feature_names
        if any(
            tuple(value.name for value in item.coefficients) != expected
            for item in self.event_coefficients
        ):
            raise ValueError("coefficient vectors must match the declared feature schema")
        if self.dataset_modes != tuple(sorted(set(self.dataset_modes), key=str)):
            raise ValueError("dataset modes must be sorted and unique")
        return self


class PriceCalibrationArtifact(PriceModel):
    schema_version: Literal["price-calibration-artifact-v1"] = "price-calibration-artifact-v1"
    calibration_id: StrictStr
    calibration_version: StrictStr
    method: Literal["IDENTITY", "LOGISTIC", "ISOTONIC"]
    training_cutoff: datetime
    probability_epsilon: Decimal = Field(gt=Decimal(0), lt=Decimal("0.5"))
    fall: CalibrationArtifact
    no_change: CalibrationArtifact
    rise: CalibrationArtifact
    artifact_sha256: Sha256

    @model_validator(mode="after")
    def calibration_contract(self) -> PriceCalibrationArtifact:
        require_utc(self.training_cutoff, field_name="training_cutoff")
        values = (self.fall, self.no_change, self.rise)
        if any(item.method != self.method for item in values):
            raise ValueError("class calibrators must use the declared common method")
        if any(item.training_cutoff != self.training_cutoff for item in values):
            raise ValueError("class calibrators must share one chronological training cutoff")
        return self


class PriceProbabilityVector(PriceModel):
    probability_fall: Probability
    probability_no_change: Probability
    probability_rise: Probability

    @model_validator(mode="after")
    def simplex(self) -> PriceProbabilityVector:
        if self.probability_fall + self.probability_no_change + self.probability_rise != Decimal(1):
            raise ValueError("fall/no-change/rise probabilities must sum exactly to one")
        return self

    def for_event(self, event: PriceEvent) -> Decimal:
        if event is PriceEvent.FALL:
            return self.probability_fall
        if event is PriceEvent.RISE:
            return self.probability_rise
        if event is PriceEvent.NO_CHANGE:
            return self.probability_no_change
        raise ValueError("probability is defined only for modeled events")


class LatentPressureState(PriceModel):
    schema_version: Literal["latent-pressure-state-v1"] = "latent-pressure-state-v1"
    state_id: StrictStr
    player_id: StrictStr
    as_of: datetime
    rise_pressure: Decimal
    fall_pressure: Decimal
    uncertainty: Decimal = Field(ge=Decimal(0))
    previous_event: Literal[PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE]
    updates_since_rise: NonNegativeInt
    updates_since_fall: NonNegativeInt
    updates_since_any_change: NonNegativeInt
    rises_this_gameweek: NonNegativeInt
    falls_this_gameweek: NonNegativeInt
    state_version: StrictStr

    @model_validator(mode="after")
    def utc_state(self) -> LatentPressureState:
        require_utc(self.as_of, field_name="as_of")
        return self


class ThresholdDistance(PriceModel):
    schema_version: Literal["threshold-distance-v1"] = "threshold-distance-v1"
    unit: Literal["LATENT_PRESSURE_SD"] = "LATENT_PRESSURE_SD"
    rise_distance_median: Decimal
    rise_distance_p10: Decimal
    rise_distance_p90: Decimal
    fall_distance_median: Decimal
    fall_distance_p10: Decimal
    fall_distance_p90: Decimal
    probability_rise_boundary_crossed: Probability
    probability_fall_boundary_crossed: Probability
    estimated_effective_transfers_remaining: None = None
    status: Literal["MODEL_INFERRED"] = "MODEL_INFERRED"

    @model_validator(mode="after")
    def intervals_are_ordered(self) -> ThresholdDistance:
        if not self.rise_distance_p10 <= self.rise_distance_median <= self.rise_distance_p90:
            raise ValueError("rise threshold interval must be ordered")
        if not self.fall_distance_p10 <= self.fall_distance_median <= self.fall_distance_p90:
            raise ValueError("fall threshold interval must be ordered")
        return self


class PriceMass(PriceModel):
    price_units: NonNegativeInt
    probability: Probability


class PricePmf(PriceModel):
    support: tuple[PriceMass, ...]

    @model_validator(mode="after")
    def proper_distribution(self) -> PricePmf:
        prices = tuple(item.price_units for item in self.support)
        if not prices or prices != tuple(sorted(prices)) or len(prices) != len(set(prices)):
            raise ValueError("price PMF support must be non-empty, sorted and unique")
        if sum((item.probability for item in self.support), Decimal(0)) != Decimal(1):
            raise ValueError("price PMF probabilities must sum exactly to one")
        return self

    @property
    def expected_price_units(self) -> Decimal:
        return sum(
            (Decimal(item.price_units) * item.probability for item in self.support),
            Decimal(0),
        )


class PricePathScenario(PriceModel):
    events: tuple[Literal[PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE], ...]
    prices_units: tuple[NonNegativeInt, ...]
    probability: Probability

    @model_validator(mode="after")
    def path_lengths_match(self) -> PricePathScenario:
        if len(self.prices_units) != len(self.events) + 1:
            raise ValueError("path prices must include the initial price and every event result")
        return self


class HorizonPriceDistribution(PriceModel):
    horizon: Literal["24h", "72h", "7d"]
    update_count: PositiveInt
    price_pmf: PricePmf
    expected_price_units: Decimal
    probability_any_rise: Probability
    probability_any_fall: Probability

    @model_validator(mode="after")
    def expected_price_reconciles(self) -> HorizonPriceDistribution:
        if self.expected_price_units != self.price_pmf.expected_price_units:
            raise ValueError("expected price must be derived from the discrete PMF")
        return self


class PricePathDistribution(PriceModel):
    schema_version: Literal["price-path-distribution-v1"] = "price-path-distribution-v1"
    current_price_units: NonNegativeInt
    price_step_units: PositiveInt
    minimum_price_units: NonNegativeInt
    maximum_price_units: PositiveInt
    initial_rises_this_gameweek: NonNegativeInt
    initial_falls_this_gameweek: NonNegativeInt
    information_cutoff: datetime
    horizons: tuple[HorizonPriceDistribution, HorizonPriceDistribution, HorizonPriceDistribution]
    scenarios_7d: tuple[PricePathScenario, ...]
    probability_multiple_rises_gameweek: Probability
    probability_multiple_falls_gameweek: Probability
    deterministic_seed: NonNegativeInt
    model_lineage: tuple[StrictStr, ...]
    distribution_sha256: Sha256

    @model_validator(mode="after")
    def path_contract(self) -> PricePathDistribution:
        require_utc(self.information_cutoff, field_name="information_cutoff")
        if not self.minimum_price_units < self.maximum_price_units:
            raise ValueError("price path bounds must be ordered")
        if not self.minimum_price_units <= self.current_price_units <= self.maximum_price_units:
            raise ValueError("price path current price lies outside its declared support")
        if tuple(item.horizon for item in self.horizons) != ("24h", "72h", "7d"):
            raise ValueError("price path horizons must be ordered 24h, 72h, 7d")
        update_counts = tuple(item.update_count for item in self.horizons)
        if update_counts != tuple(sorted(update_counts)):
            raise ValueError("price path horizon update counts must be nondecreasing")
        if any(
            not self.minimum_price_units <= mass.price_units <= self.maximum_price_units
            for horizon in self.horizons
            for mass in horizon.price_pmf.support
        ):
            raise ValueError("price horizon PMF escapes configured legal support")
        if sum((item.probability for item in self.scenarios_7d), Decimal(0)) != Decimal(1):
            raise ValueError("7d path scenario probabilities must sum exactly to one")
        if not self.model_lineage or self.model_lineage != tuple(sorted(set(self.model_lineage))):
            raise ValueError("model lineage must be non-empty, sorted and unique")
        scenario_keys = tuple((item.events, item.prices_units) for item in self.scenarios_7d)
        if len(scenario_keys) != len(set(scenario_keys)):
            raise ValueError("7d price path scenarios must be unique")
        final_update_count = self.horizons[-1].update_count
        final_masses: dict[int, Decimal] = {}
        any_rise = Decimal(0)
        any_fall = Decimal(0)
        multiple_rises = Decimal(0)
        multiple_falls = Decimal(0)
        expected_delta = {
            PriceEvent.FALL: -self.price_step_units,
            PriceEvent.NO_CHANGE: 0,
            PriceEvent.RISE: self.price_step_units,
        }
        for scenario in self.scenarios_7d:
            if len(scenario.events) != final_update_count:
                raise ValueError("7d scenario length differs from its declared update count")
            if scenario.prices_units[0] != self.current_price_units:
                raise ValueError("price path scenario does not begin at the current price")
            for event, previous, current in zip(
                scenario.events,
                scenario.prices_units[:-1],
                scenario.prices_units[1:],
                strict=True,
            ):
                if current - previous != expected_delta[event]:
                    raise ValueError("price path event does not match its configured price step")
                if not self.minimum_price_units <= current <= self.maximum_price_units:
                    raise ValueError("price path scenario escapes configured legal support")
            final_price = scenario.prices_units[-1]
            final_masses[final_price] = (
                final_masses.get(final_price, Decimal(0)) + scenario.probability
            )
            if PriceEvent.RISE in scenario.events:
                any_rise += scenario.probability
            if PriceEvent.FALL in scenario.events:
                any_fall += scenario.probability
            if self.initial_rises_this_gameweek + scenario.events.count(PriceEvent.RISE) >= 2:
                multiple_rises += scenario.probability
            if self.initial_falls_this_gameweek + scenario.events.count(PriceEvent.FALL) >= 2:
                multiple_falls += scenario.probability
        ordered_final_masses = tuple(sorted(final_masses.items()))
        final_total = sum((value for _, value in ordered_final_masses), Decimal(0))
        normalized_final = [value / final_total for _, value in ordered_final_masses]
        normalized_final[-1] = Decimal(1) - sum(normalized_final[:-1], Decimal(0))
        normalized_masses = {
            price: probability
            for (price, _), probability in zip(ordered_final_masses, normalized_final, strict=True)
        }
        declared_masses = {
            item.price_units: item.probability for item in self.horizons[-1].price_pmf.support
        }
        if normalized_masses != declared_masses:
            raise ValueError("7d price PMF does not match the exact recurrent scenarios")
        if (
            self.horizons[-1].probability_any_rise != any_rise
            or self.horizons[-1].probability_any_fall != any_fall
        ):
            raise ValueError("7d any-change probabilities do not match recurrent scenarios")
        if (
            self.probability_multiple_rises_gameweek != multiple_rises
            or self.probability_multiple_falls_gameweek != multiple_falls
        ):
            raise ValueError("multiple-change probabilities do not match recurrent scenarios")
        return self


class ProjectionLineage(PriceModel):
    source_observation_ids: tuple[StrictStr, ...]
    source_semantic_hashes: tuple[Sha256, ...]
    model_version_ids: tuple[StrictStr, ...]
    calibration_version_ids: tuple[StrictStr, ...]
    model_artifact_sha256: Sha256
    calibration_artifact_sha256: Sha256 | None
    price_path_distribution_sha256: Sha256
    configuration_sha256: Sha256
    ruleset_id: StrictStr
    ruleset_hash: Sha256
    dataset_mode: DatasetMode
    information_cutoff: datetime

    @model_validator(mode="after")
    def canonical_lineage(self) -> ProjectionLineage:
        require_utc(self.information_cutoff, field_name="information_cutoff")
        for name in (
            "source_observation_ids",
            "model_version_ids",
            "calibration_version_ids",
        ):
            values = getattr(self, name)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} must be sorted and unique")
        if not self.source_observation_ids or len(self.source_observation_ids) != len(
            self.source_semantic_hashes
        ):
            raise ValueError("projection lineage requires one semantic hash per source observation")
        if not self.model_version_ids:
            raise ValueError("projection lineage requires at least one model version")
        if bool(self.calibration_version_ids) != (self.calibration_artifact_sha256 is not None):
            raise ValueError(
                "projection calibration version/hash lineage must be supplied together"
            )
        return self


class PriceProjection(PriceModel):
    schema_version: Literal["price-projection-v1"] = "price-projection-v1"
    projection_id: StrictStr
    player_id: StrictStr
    current_price_units: NonNegativeInt
    probability_rise_next_update: Probability
    probability_fall_next_update: Probability
    probability_no_change_next_update: Probability
    expected_price_24h: Decimal
    expected_price_72h: Decimal
    expected_price_7d: Decimal
    price_pmf_24h: PricePmf
    price_pmf_72h: PricePmf
    price_pmf_7d: PricePmf
    probability_any_rise_24h: Probability
    probability_any_rise_72h: Probability
    probability_any_rise_7d: Probability
    probability_any_fall_24h: Probability
    probability_any_fall_72h: Probability
    probability_any_fall_7d: Probability
    probability_multiple_rises_gameweek: Probability
    probability_multiple_falls_gameweek: Probability
    confidence: ConfidenceGrade
    model_disagreement_status: ModelDisagreementStatus
    activation_statuses: tuple[ActivationStatus, ...]
    threshold_distance: ThresholdDistance
    lineage: ProjectionLineage
    projection_sha256: Sha256

    @model_validator(mode="after")
    def projection_reconciles(self) -> PriceProjection:
        if (
            self.probability_rise_next_update
            + self.probability_fall_next_update
            + self.probability_no_change_next_update
            != Decimal(1)
        ):
            raise ValueError("next-update probabilities must sum exactly to one")
        expected = (
            self.price_pmf_24h.expected_price_units,
            self.price_pmf_72h.expected_price_units,
            self.price_pmf_7d.expected_price_units,
        )
        if expected != (
            self.expected_price_24h,
            self.expected_price_72h,
            self.expected_price_7d,
        ):
            raise ValueError("projection expected prices must equal their PMF expectations")
        if not self.activation_statuses or self.activation_statuses != tuple(
            sorted(set(self.activation_statuses), key=str)
        ):
            raise ValueError("activation statuses must be sorted, unique and non-empty")
        return self


class OptimiserPriceScenario(PriceModel):
    scenario_id: StrictStr
    probability: Probability
    player_id: StrictStr
    market_price_units: NonNegativeInt
    selling_price_units: NonNegativeInt | None = None
    route_affordable: StrictBool | None = None


class PriceScenarioSet(PriceModel):
    schema_version: Literal["optimiser-price-scenario-set-v1"] = "optimiser-price-scenario-set-v1"
    horizon: Literal["24h", "72h", "7d"]
    focus_player_ids: tuple[StrictStr, ...]
    reduction_policy: Literal["EXACT_BOUNDED_SUPPORT"] = "EXACT_BOUNDED_SUPPORT"
    scenarios: tuple[OptimiserPriceScenario, ...]

    @model_validator(mode="after")
    def scenario_contract(self) -> PriceScenarioSet:
        if self.focus_player_ids != tuple(sorted(set(self.focus_player_ids))):
            raise ValueError("focus player IDs must be sorted and unique")
        if not self.scenarios or sum(
            (item.probability for item in self.scenarios), Decimal(0)
        ) != Decimal(1):
            raise ValueError("optimiser price scenarios must form a proper distribution")
        ids = tuple(item.scenario_id for item in self.scenarios)
        if len(ids) != len(set(ids)):
            raise ValueError("optimiser price scenario IDs must be unique")
        return self


class UtilityComponents(PriceModel):
    football_expected_value: Decimal
    affordability_route_value: Decimal
    price_scenario_value: Decimal
    outgoing_selling_value_risk: Decimal
    free_transfer_value: Decimal
    future_recourse_value: Decimal
    information_value: Decimal
    transfer_hit_cost: Decimal = Field(ge=Decimal(0))
    injury_rotation_cost: Decimal = Field(ge=Decimal(0))
    reversal_cost: Decimal = Field(ge=Decimal(0))
    lost_purchase_position_cost: Decimal = Field(ge=Decimal(0))
    execution_risk_cost: Decimal = Field(ge=Decimal(0))

    @property
    def net_utility(self) -> Decimal:
        return (
            self.football_expected_value
            + self.affordability_route_value
            + self.price_scenario_value
            + self.outgoing_selling_value_risk
            + self.free_transfer_value
            + self.future_recourse_value
            + self.information_value
            - self.transfer_hit_cost
            - self.injury_rotation_cost
            - self.reversal_cost
            - self.lost_purchase_position_cost
            - self.execution_risk_cost
        )


class EarlyTransferAlternative(PriceModel):
    action: Literal[
        EarlyTransferAction.ACT_NOW,
        EarlyTransferAction.WAIT_FOR_INFORMATION,
        EarlyTransferAction.DO_NOT_TRANSFER,
        EarlyTransferAction.ALTERNATIVE_ROUTE,
    ]
    route_id: StrictStr
    components: UtilityComponents


class EarlyTransferDecision(PriceModel):
    schema_version: Literal["early-transfer-decision-v1"] = "early-transfer-decision-v1"
    decision_id: StrictStr
    recommended_action: EarlyTransferAction
    selected_route_id: StrictStr | None
    actionable: StrictBool
    expected_utility: Decimal
    second_best_utility: Decimal
    utility_gap: Decimal = Field(ge=Decimal(0))
    alternatives: tuple[EarlyTransferAlternative, ...]
    price_probability_used_as_component_only: Literal[True] = True
    activation_statuses: tuple[ActivationStatus, ...]
    dataset_mode: DatasetMode
    information_cutoff: datetime
    rationale_codes: tuple[StrictStr, ...]
    decision_sha256: Sha256

    @model_validator(mode="after")
    def decision_contract(self) -> EarlyTransferDecision:
        require_utc(self.information_cutoff, field_name="information_cutoff")
        required = {
            EarlyTransferAction.ACT_NOW,
            EarlyTransferAction.WAIT_FOR_INFORMATION,
            EarlyTransferAction.DO_NOT_TRANSFER,
        }
        if not required <= {item.action for item in self.alternatives}:
            raise ValueError("ACT, WAIT and DO_NOT_TRANSFER alternatives are required")
        keys = tuple((item.action, item.route_id) for item in self.alternatives)
        if len(keys) != len(set(keys)):
            raise ValueError("ACT/WAIT alternatives must be unique")
        ranked = tuple(
            sorted(
                self.alternatives,
                key=lambda item: (-item.components.net_utility, item.action.value, item.route_id),
            )
        )
        utilities = tuple(item.components.net_utility for item in ranked)
        if self.expected_utility != utilities[0] or self.second_best_utility != utilities[1]:
            raise ValueError("decision utility summary does not match alternatives")
        if self.utility_gap != self.expected_utility - self.second_best_utility:
            raise ValueError("decision utility gap does not reconcile")
        if self.actionable:
            if self.recommended_action is EarlyTransferAction.MANUAL_REVIEW:
                raise ValueError("manual review cannot be actionable")
            if (
                self.recommended_action is not ranked[0].action
                or self.selected_route_id != ranked[0].route_id
            ):
                raise ValueError("actionable decision must select the complete-utility maximum")
        elif (
            self.recommended_action is not EarlyTransferAction.MANUAL_REVIEW
            or self.selected_route_id is not None
        ):
            raise ValueError("non-actionable decision must fail closed to manual review")
        if not self.activation_statuses or self.activation_statuses != tuple(
            sorted(set(self.activation_statuses), key=str)
        ):
            raise ValueError("decision activation statuses must be sorted, unique and non-empty")
        if ActivationStatus.PRODUCTION_ELIGIBLE in self.activation_statuses:
            raise ValueError("Stage-13 ACT/WAIT decision cannot claim production eligibility")
        return self


class PriceEvaluationRow(PriceModel):
    row_id: StrictStr
    horizon: Literal["24h", "72h", "7d"] = "24h"
    forecast_origin: datetime
    label_available_at: datetime
    probabilities: PriceProbabilityVector
    observed_event: Literal[PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE]
    price_pmf: PricePmf
    observed_price_units: NonNegativeInt
    expected_decision_utility: Decimal | None = None
    realised_decision_utility: Decimal | None = None
    realised_comparator_utility: Decimal | None = None

    @model_validator(mode="after")
    def row_is_prequential(self) -> PriceEvaluationRow:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        label = require_utc(self.label_available_at, field_name="label_available_at")
        if label <= origin:
            raise ValueError("evaluation label must be revealed after forecast freeze")
        decision_values = (
            self.expected_decision_utility,
            self.realised_decision_utility,
            self.realised_comparator_utility,
        )
        if any(item is not None for item in decision_values) and not all(
            item is not None for item in decision_values
        ):
            raise ValueError("decision evaluation fields must be supplied together")
        return self


class PriceEvaluationReport(PriceModel):
    schema_version: Literal["price-evaluation-report-v1"] = "price-evaluation-report-v1"
    row_count: PositiveInt
    price_horizon: Literal["24h", "72h", "7d"]
    multiclass_log_loss: Decimal | None
    multiclass_brier: Decimal
    rise_precision: Decimal | None
    rise_recall: Decimal | None
    rise_pr_auc: Decimal | None
    fall_precision: Decimal | None
    fall_recall: Decimal | None
    fall_pr_auc: Decimal | None
    alert_precision: Decimal | None
    rise_calibration_status: StrictStr
    rise_calibration_intercept: Decimal | None
    rise_calibration_slope: Decimal | None
    fall_calibration_status: StrictStr
    fall_calibration_intercept: Decimal | None
    fall_calibration_slope: Decimal | None
    no_change_calibration_status: StrictStr
    no_change_calibration_intercept: Decimal | None
    no_change_calibration_slope: Decimal | None
    mean_ranked_probability_score: Decimal
    expected_price_mae: Decimal
    expected_price_rmse: Decimal
    interval_coverage: Decimal
    interval_width: Decimal
    mean_decision_regret: Decimal | None
    stage12_metric_lineage: tuple[StrictStr, ...]


class ArtifactReceipt(PriceModel):
    artifact_path: StrictStr
    artifact_sha256: Sha256
    semantic_sha256: Sha256


class PriceValidationReport(PriceModel):
    schema_version: Literal["price-validation-report-v1"] = "price-validation-report-v1"
    status: Literal["ENGINEERING_READY"] = "ENGINEERING_READY"
    configuration_id: StrictStr
    configuration_sha256: Sha256
    configuration_role: Literal["POLICY_CONFIGURATION"]
    parameter_status: Literal["PROVISIONAL_MODEL_PARAMETER"]
    evidence_status: Literal["SYNTHETIC_REFERENCE"]
    implemented_models: tuple[ModelFamily, ...]
    challenger_status: ChallengerStatus
    activation_statuses: tuple[ActivationStatus, ...]
    automated_provider_capture: Literal[False] = False
    production_actionable: Literal[False] = False

    @model_validator(mode="after")
    def validation_is_fail_closed(self) -> PriceValidationReport:
        if self.implemented_models != (
            ModelFamily.P0_NO_CHANGE,
            ModelFamily.P1_REGULARIZED_COMPETING_LOGIT,
            ModelFamily.P2_RECURRENT_LATENT_PRESSURE,
        ):
            raise ValueError("validation report must declare the implemented P0/P1/P2 ladder")
        if ActivationStatus.PRODUCTION_ELIGIBLE in self.activation_statuses:
            raise ValueError("default Stage-13 validation cannot claim production eligibility")
        return self
