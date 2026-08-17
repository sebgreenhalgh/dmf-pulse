"""Nested walk-forward fold construction with immutable deterministic identities."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, StrictStr, model_validator

from dmf_pulse.evaluation.artifacts import seal
from dmf_pulse.evaluation.models import (
    DatasetMode,
    EvaluationFold,
    EvaluationModel,
    FoldWindow,
    InnerFold,
    NonNegativeInt,
    PositiveInt,
    require_utc,
)


class ForecastOrigin(EvaluationModel):
    origin_id: StrictStr = Field(min_length=1, max_length=200)
    forecast_origin: datetime
    information_cutoff: datetime
    label_available_at: datetime

    @model_validator(mode="after")
    def origin_is_valid(self) -> ForecastOrigin:
        forecast = require_utc(self.forecast_origin, field_name="forecast_origin")
        information = require_utc(self.information_cutoff, field_name="information_cutoff")
        label = require_utc(self.label_available_at, field_name="label_available_at")
        if information > forecast:
            raise ValueError("information cutoff cannot follow forecast origin")
        if label <= forecast:
            raise ValueError("outcome label must be revealed after forecast origin")
        return self


class WalkForwardConfig(EvaluationModel):
    schema_version: Literal["walk-forward-config-v1"] = "walk-forward-config-v1"
    dataset_mode: DatasetMode
    window: FoldWindow = FoldWindow.EXPANDING
    minimum_training_origins: PositiveInt = 1
    rolling_window_origins: PositiveInt | None = None
    inner_minimum_training_origins: PositiveInt = 1
    holdout_origins: NonNegativeInt = 0

    @model_validator(mode="after")
    def config_is_coherent(self) -> WalkForwardConfig:
        if self.window is FoldWindow.ROLLING and self.rolling_window_origins is None:
            raise ValueError("rolling folds require rolling_window_origins")
        if self.window is FoldWindow.EXPANDING and self.rolling_window_origins is not None:
            raise ValueError("expanding folds cannot declare a rolling window")
        if self.rolling_window_origins is not None and (
            self.rolling_window_origins < self.minimum_training_origins
            or self.rolling_window_origins <= self.inner_minimum_training_origins
        ):
            raise ValueError(
                "rolling window must cover outer training and leave history for an inner fold"
            )
        if self.holdout_origins < 0:
            raise ValueError("holdout_origins cannot be negative")
        return self


def _eligible_training(
    prior: tuple[ForecastOrigin, ...],
    *,
    outer_origin: ForecastOrigin,
    config: WalkForwardConfig,
) -> tuple[ForecastOrigin, ...]:
    eligible = tuple(
        item for item in prior if item.label_available_at <= outer_origin.information_cutoff
    )
    if config.window is FoldWindow.ROLLING:
        assert config.rolling_window_origins is not None
        eligible = eligible[-config.rolling_window_origins :]
    return eligible


def _inner_folds(
    training: tuple[ForecastOrigin, ...],
    *,
    outer_id: str,
    config: WalkForwardConfig,
) -> tuple[InnerFold, ...]:
    values: list[InnerFold] = []
    for index in range(config.inner_minimum_training_origins, len(training)):
        validation = training[index]
        available = tuple(
            item
            for item in training[:index]
            if item.label_available_at <= validation.information_cutoff
        )
        if config.window is FoldWindow.ROLLING:
            assert config.rolling_window_origins is not None
            available = available[-config.rolling_window_origins :]
        if len(available) < config.inner_minimum_training_origins:
            continue
        value = InnerFold(
            fold_id=f"{outer_id}:inner:{validation.origin_id}",
            training_origin_ids=tuple(item.origin_id for item in available),
            validation_origin_id=validation.origin_id,
            training_cutoff=validation.information_cutoff,
            validation_origin=validation.forecast_origin,
            fold_sha256="0" * 64,
        )
        values.append(seal(value, "fold_sha256"))
    return tuple(values)


def build_walk_forward_folds(
    origins: tuple[ForecastOrigin, ...],
    *,
    config: WalkForwardConfig,
) -> tuple[EvaluationFold, ...]:
    """Build outer deadline folds whose nested selection data are strictly earlier."""

    ordered = tuple(sorted(origins, key=lambda item: (item.forecast_origin, item.origin_id)))
    if not origins:
        raise ValueError("walk-forward evaluation requires forecast origins")
    if origins != ordered:
        raise ValueError("forecast origins must be supplied in chronological canonical order")
    ids = tuple(item.origin_id for item in origins)
    if len(ids) != len(set(ids)):
        raise ValueError("forecast origin IDs must be unique")
    if config.holdout_origins > len(origins):
        raise ValueError("holdout block cannot exceed origin count")
    holdout_start = len(origins) - config.holdout_origins
    folds: list[EvaluationFold] = []
    for index, origin in enumerate(origins):
        training = _eligible_training(origins[:index], outer_origin=origin, config=config)
        if len(training) < config.minimum_training_origins:
            continue
        fold_id = f"outer:{origin.origin_id}"
        value = EvaluationFold(
            fold_id=fold_id,
            ordinal=len(folds),
            forecast_origin_id=origin.origin_id,
            forecast_origin=origin.forecast_origin,
            information_cutoff=origin.information_cutoff,
            training_origin_ids=tuple(item.origin_id for item in training),
            inner_folds=_inner_folds(training, outer_id=fold_id, config=config),
            dataset_mode=config.dataset_mode,
            window=config.window,
            holdout=config.holdout_origins > 0 and index >= holdout_start,
            fold_sha256="0" * 64,
        )
        folds.append(seal(value, "fold_sha256"))
    if not folds:
        raise ValueError("walk-forward configuration produced no evaluable outer folds")
    return tuple(folds)
