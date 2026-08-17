"""Versioned Stage-12 evaluation configuration and default loader."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import Field, StrictInt, StrictStr, model_validator
from yaml.constructor import ConstructorError  # type: ignore[import-untyped]
from yaml.nodes import MappingNode, ScalarNode  # type: ignore[import-untyped]
from yaml.tokens import AliasToken, AnchorToken, TagToken  # type: ignore[import-untyped]

from dmf_pulse.evaluation.benchmarks import benchmark_suite
from dmf_pulse.evaluation.folds import WalkForwardConfig
from dmf_pulse.evaluation.models import (
    DatasetMode,
    EvaluationModel,
    FoldWindow,
    ProbabilityBoundaryPolicy,
)


class _EvaluationConfigLoader(yaml.SafeLoader):  # type: ignore[misc]
    """Safe YAML loader with deterministic mapping semantics."""


def _construct_mapping(
    loader: _EvaluationConfigLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
            raise ConstructorError(None, None, "mapping keys must be strings", key_node.start_mark)
        key = key_node.value
        if key == "<<":
            raise ConstructorError(
                None, None, "YAML merge keys are prohibited", key_node.start_mark
            )
        if key in result:
            raise ConstructorError(None, None, "duplicate mapping key", key_node.start_mark)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_EvaluationConfigLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _validate_yaml_value(value: object) -> None:
    if isinstance(value, (float, dt.date, dt.datetime)):
        raise ValueError("binary floats and implicit timestamps are prohibited")
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("mapping keys must be strings")
        for item in value.values():
            _validate_yaml_value(item)
    elif isinstance(value, list):
        for item in value:
            _validate_yaml_value(item)


class WalkForwardDefaults(EvaluationModel):
    window: FoldWindow
    minimum_training_origins: StrictInt = Field(gt=0)
    inner_minimum_training_origins: StrictInt = Field(gt=0)
    rolling_window_origins: StrictInt | None = Field(default=None, gt=0)
    holdout_origins: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def window_is_coherent(self) -> WalkForwardDefaults:
        if self.window is FoldWindow.ROLLING and self.rolling_window_origins is None:
            raise ValueError("rolling evaluation requires rolling_window_origins")
        if self.window is FoldWindow.EXPANDING and self.rolling_window_origins is not None:
            raise ValueError("expanding evaluation cannot set rolling_window_origins")
        return self

    def compile(self, *, dataset_mode: DatasetMode) -> WalkForwardConfig:
        return WalkForwardConfig(
            dataset_mode=dataset_mode,
            window=self.window,
            minimum_training_origins=self.minimum_training_origins,
            rolling_window_origins=self.rolling_window_origins,
            inner_minimum_training_origins=self.inner_minimum_training_origins,
            holdout_origins=self.holdout_origins,
        )


class ProbabilityScoringConfig(EvaluationModel):
    boundary_policy: ProbabilityBoundaryPolicy
    declared_epsilon: Decimal | None = None

    @model_validator(mode="after")
    def boundary_is_explicit(self) -> ProbabilityScoringConfig:
        if self.boundary_policy is ProbabilityBoundaryPolicy.EXACT:
            if self.declared_epsilon is not None:
                raise ValueError("EXACT probability scoring cannot declare epsilon")
        elif self.declared_epsilon is None or not Decimal(0) < self.declared_epsilon < Decimal(
            "0.5"
        ):
            raise ValueError("DECLARED_EPSILON requires epsilon in (0, 0.5)")
        return self


class CalibrationConfig(EvaluationModel):
    reliability_bins: StrictInt = Field(gt=0)
    method: Literal["IDENTITY", "LOGISTIC", "ISOTONIC"]


class DistributionScoringConfig(EvaluationModel):
    central_coverage: Decimal = Field(gt=Decimal(0), lt=Decimal(1))
    quantile_alpha: Decimal = Field(ge=Decimal(0), le=Decimal(1))


class MultivariateScoringConfig(EvaluationModel):
    variogram_power: Decimal = Field(gt=Decimal(0), le=Decimal(2))


class PolicyReplayConfig(EvaluationModel):
    execute_root_action_only: Literal[True]
    freeze_forecast_before_outcome: Literal[True]


class EvaluationConfig(EvaluationModel):
    schema_version: Literal["evaluation-config-v1"] = "evaluation-config-v1"
    dataset_mode: DatasetMode
    walk_forward: WalkForwardDefaults
    probability_scoring: ProbabilityScoringConfig
    calibration: CalibrationConfig
    distribution_scoring: DistributionScoringConfig
    multivariate_scoring: MultivariateScoringConfig
    policy_replay: PolicyReplayConfig
    benchmark_ids: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def benchmarks_are_canonical(self) -> EvaluationConfig:
        if not self.benchmark_ids:
            raise ValueError("evaluation configuration requires at least one benchmark")
        if len(self.benchmark_ids) != len(set(self.benchmark_ids)):
            raise ValueError("benchmark IDs must be unique")
        canonical = {item.benchmark_id for item in benchmark_suite()}
        if not set(self.benchmark_ids) <= canonical:
            raise ValueError("benchmark IDs must come from the canonical Stage-12 suite")
        return self


def load_evaluation_config(path: Path | None = None) -> EvaluationConfig:
    """Load and validate an explicit config or the wheel-packaged default."""

    try:
        if path is None:
            resource = files("dmf_pulse.evaluation").joinpath("resources/default.yaml")
            text = resource.read_text(encoding="utf-8")
        else:
            text = path.read_text(encoding="utf-8")
        for token in yaml.scan(text):
            if isinstance(token, (AnchorToken, AliasToken, TagToken)):
                raise ValueError("YAML anchors, aliases and explicit tags are prohibited")
        payload = yaml.load(text, Loader=_EvaluationConfigLoader)
        _validate_yaml_value(payload)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("evaluation configuration is unavailable or invalid YAML") from exc
    if not isinstance(payload, dict):
        raise ValueError("evaluation configuration root must be a mapping")
    return EvaluationConfig.model_validate(payload)
