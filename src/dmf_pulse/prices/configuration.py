"""Versioned Stage-13 configuration loaded through the strict rules YAML subset."""

from __future__ import annotations

from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, ValidationError, model_validator

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.errors import PriceError
from dmf_pulse.prices.models import (
    ActivationStatus,
    ChipContaminationState,
    ConfidenceGrade,
    PriceModel,
    PriceStatus,
    Sha256,
)
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.yaml_loader import load_rules_yaml_bytes


class TransferFeaturePolicy(PriceModel):
    short_half_life_hours: Decimal = Field(gt=Decimal(0))
    long_half_life_hours: Decimal = Field(gt=Decimal(0))
    maximum_interval_hours: Decimal = Field(gt=Decimal(0))
    low_ownership_percent: Decimal = Field(ge=Decimal(0), le=Decimal(100))
    high_ownership_percent: Decimal = Field(ge=Decimal(0), le=Decimal(100))
    denominator_floor: StrictInt = Field(gt=0)
    unknown_denominator_uncertainty: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    rounded_ownership_uncertainty: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    low_global_transfer_activity: StrictInt = Field(gt=0)
    high_global_transfer_activity: StrictInt = Field(gt=0)
    status_uncertainty: dict[StrictStr, Decimal]
    chip_uncertainty: dict[ChipContaminationState, Decimal]

    @model_validator(mode="after")
    def feature_policy_is_coherent(self) -> TransferFeaturePolicy:
        if self.short_half_life_hours >= self.long_half_life_hours:
            raise ValueError("short flow half-life must be shorter than long half-life")
        if self.low_ownership_percent >= self.high_ownership_percent:
            raise ValueError("ownership regime thresholds must be ordered")
        if self.low_global_transfer_activity >= self.high_global_transfer_activity:
            raise ValueError("global transfer-activity thresholds must be ordered")
        if any(not Decimal(0) <= value <= Decimal(1) for value in self.status_uncertainty.values()):
            raise ValueError("status uncertainty values must lie in [0, 1]")
        if set(self.status_uncertainty) != {item.value for item in PriceStatus}:
            raise ValueError("status uncertainty must cover every price status")
        if set(self.chip_uncertainty) != set(ChipContaminationState):
            raise ValueError("chip uncertainty must cover every contamination state")
        return self


class CompetingLogitPolicy(PriceModel):
    model_version: StrictStr
    feature_schema_version: StrictStr
    feature_names: tuple[StrictStr, ...]
    feature_scales: dict[StrictStr, Decimal]
    regularization_l2: Decimal = Field(ge=Decimal(0))
    learning_rate: Decimal = Field(gt=Decimal(0))
    epochs: StrictInt = Field(gt=0)
    calibration_version: StrictStr
    calibration_probability_epsilon: Decimal = Field(gt=Decimal(0), lt=Decimal("0.5"))
    disagreement_threshold: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    score_cap: Decimal = Field(gt=Decimal(0))

    @model_validator(mode="after")
    def feature_schema_is_canonical(self) -> CompetingLogitPolicy:
        if self.feature_names != tuple(sorted(set(self.feature_names))) or not self.feature_names:
            raise ValueError("configured feature names must be sorted, unique and non-empty")
        if set(self.feature_scales) != set(self.feature_names) or any(
            value <= 0 for value in self.feature_scales.values()
        ):
            raise ValueError("feature scales must positively cover the configured feature schema")
        return self


class RecurrentPressurePolicy(PriceModel):
    state_version: StrictStr
    persistence: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    flow_scale: Decimal = Field(gt=Decimal(0))
    momentum_scale: Decimal = Field(gt=Decimal(0))
    ownership_rate_scale: Decimal = Field(gt=Decimal(0))
    event_reset_retention: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    opposite_direction_retention: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    rise_boundary: Decimal
    fall_boundary: Decimal
    uncertainty_floor: Decimal = Field(gt=Decimal(0))
    uncertainty_missing_chip_increment: Decimal = Field(ge=Decimal(0))
    recurrent_same_direction_bonus: Decimal
    opposite_direction_penalty: Decimal
    gap_decay: Decimal = Field(gt=Decimal(0))
    default_event_logit: Decimal
    probability_epsilon: Decimal = Field(gt=Decimal(0), lt=Decimal("0.5"))
    score_cap: Decimal = Field(gt=Decimal(0))
    threshold_interval_z: Decimal = Field(gt=Decimal(0))


class UpdateCyclePolicy(PriceModel):
    maximum_label_interval_minutes: StrictInt = Field(gt=0)


class PricePathPolicy(PriceModel):
    price_step_units: StrictInt = Field(gt=0)
    minimum_price_units: StrictInt = Field(ge=0)
    maximum_price_units: StrictInt = Field(gt=0)
    updates_24h: StrictInt = Field(gt=0)
    updates_72h: StrictInt = Field(gt=0)
    updates_7d: StrictInt = Field(gt=0)
    maximum_exact_scenarios: StrictInt = Field(gt=0)
    maximum_optimiser_support: StrictInt = Field(gt=0)
    deterministic_seed: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def horizons_are_ordered(self) -> PricePathPolicy:
        if not self.minimum_price_units < self.maximum_price_units:
            raise ValueError("price bounds must be ordered")
        if not self.updates_24h <= self.updates_72h <= self.updates_7d:
            raise ValueError("price path update horizons must be ordered")
        if 3**self.updates_7d > self.maximum_exact_scenarios:
            raise ValueError("configured exact price paths exceed the declared scenario cap")
        return self


class ActivationPolicy(PriceModel):
    engineering_status: ActivationStatus
    production_statuses: tuple[ActivationStatus, ...]
    maximum_confidence: ConfidenceGrade
    challenger_status: Literal["DEPENDENCY_NOT_APPROVED", "DEFERRED"]
    automated_capture_allowed: Literal[False] = False
    confidence_c_max_uncertainty: Decimal = Field(ge=Decimal(0))

    @model_validator(mode="after")
    def activation_is_fail_closed(self) -> ActivationPolicy:
        if ActivationStatus.PRODUCTION_ELIGIBLE in self.production_statuses:
            raise ValueError("default Stage-13 policy cannot be production eligible")
        if self.production_statuses != tuple(sorted(set(self.production_statuses), key=str)):
            raise ValueError("production statuses must be sorted and unique")
        return self


class EarlyTransferPolicy(PriceModel):
    schema_version: Literal["early-transfer-policy-v1"] = "early-transfer-policy-v1"
    actionable_dataset_modes: tuple[DatasetMode, ...]
    require_all_core_alternatives: Literal[True] = True
    price_probability_is_component_only: Literal[True] = True
    manual_review_when_not_actionable: Literal[True] = True

    @model_validator(mode="after")
    def modes_are_canonical(self) -> EarlyTransferPolicy:
        if self.actionable_dataset_modes != tuple(
            sorted(set(self.actionable_dataset_modes), key=str)
        ):
            raise ValueError("actionable dataset modes must be sorted and unique")
        if DatasetMode.LIVE_OBSERVED in self.actionable_dataset_modes:
            raise ValueError("default uncalibrated policy cannot action LIVE_OBSERVED inputs")
        return self


class PriceEvaluationPolicy(PriceModel):
    alert_probability: Decimal = Field(gt=Decimal(0), lt=Decimal(1))
    probability_epsilon: Decimal = Field(gt=Decimal(0), lt=Decimal("0.5"))


class PriceConfig(PriceModel):
    schema_version: Literal["price-config-v1"] = "price-config-v1"
    configuration_id: StrictStr
    transfer_features: TransferFeaturePolicy
    update_cycles: UpdateCyclePolicy
    competing_logit: CompetingLogitPolicy
    recurrent_pressure: RecurrentPressurePolicy
    price_paths: PricePathPolicy
    activation: ActivationPolicy
    early_transfer: EarlyTransferPolicy
    evaluation: PriceEvaluationPolicy
    benchmark_ids: tuple[StrictStr, ...]
    rights_profile_required: StrictBool = True

    @model_validator(mode="after")
    def benchmark_contract(self) -> PriceConfig:
        required = {
            "P0_NO_CHANGE",
            "P1_REGULARIZED_COMPETING_LOGIT",
            "P2_RECURRENT_LATENT_PRESSURE",
            "OFFICIAL_FPL_PREDICTOR",
            "LIVEFPL",
            "FANTASY_FOOTBALL_FIX",
            "OTHER_APPROVED_EXTERNAL",
        }
        if not required <= set(self.benchmark_ids):
            raise ValueError("price configuration omits a mandatory model/external benchmark")
        if self.benchmark_ids != tuple(sorted(set(self.benchmark_ids))):
            raise ValueError("benchmark IDs must be sorted and unique")
        return self


def load_price_config(path: Path | None = None) -> PriceConfig:
    """Load a strict wheel-packaged default or an explicit repository config."""

    try:
        raw = (
            path.read_bytes()
            if path is not None
            else files("dmf_pulse.prices.resources").joinpath("default.yaml").read_bytes()
        )
        return PriceConfig.model_validate(load_rules_yaml_bytes(raw))
    except (OSError, RulesValidationError, ValidationError, ValueError) as exc:
        raise PriceError(
            "PRICE_CONFIGURATION_INVALID",
            "Stage-13 configuration is unavailable or violates the strict contract",
        ) from exc


def price_config_sha256(config: PriceConfig) -> Sha256:
    return semantic_sha256(config.model_dump(mode="json"))
