"""Audited deterministic point-forecast metrics."""

from __future__ import annotations

from decimal import Decimal, localcontext

from dmf_pulse.evaluation.artifacts import verify_sealed
from dmf_pulse.evaluation.benchmarks import STAGE12_PARENT_COMMIT
from dmf_pulse.evaluation.models import (
    ForecastArtifact,
    OutcomeLabel,
    PointMetricResult,
    Probability,
    TargetFunctional,
)


def pinball_loss(forecast: Decimal, outcome: Decimal, quantile: Decimal) -> Decimal:
    if not forecast.is_finite() or not outcome.is_finite() or not quantile.is_finite():
        raise ValueError("pinball inputs must be finite")
    if not Decimal(0) <= quantile <= Decimal(1):
        raise ValueError("quantile must lie in [0, 1]")
    error = outcome - forecast
    return quantile * error if error >= 0 else (quantile - Decimal(1)) * error


def _median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def score_forecast(
    forecasts: tuple[Decimal, ...],
    outcomes: tuple[Decimal, ...],
    *,
    target_functional: TargetFunctional = TargetFunctional.MEAN,
    quantile: Probability | None = None,
) -> PointMetricResult:
    """Score aligned point forecasts without conflating mean and median targets."""

    if not forecasts or len(forecasts) != len(outcomes):
        raise ValueError("forecasts and outcomes require the same nonzero length")
    if any(not item.is_finite() for item in (*forecasts, *outcomes)):
        raise ValueError("forecasts and outcomes must be finite")
    if target_functional is TargetFunctional.QUANTILE and quantile is None:
        raise ValueError("quantile forecasts require an explicit quantile")
    if target_functional is not TargetFunctional.QUANTILE and quantile is not None:
        raise ValueError("quantile is only valid for QUANTILE target forecasts")
    errors = tuple(
        forecast - outcome for forecast, outcome in zip(forecasts, outcomes, strict=True)
    )
    absolute = tuple(abs(item) for item in errors)
    squared = tuple(item * item for item in errors)
    count = Decimal(len(errors))
    with localcontext() as context:
        context.prec = 50
        rmse = (sum(squared, Decimal(0)) / count).sqrt()
    quantile_loss = None
    if quantile is not None:
        quantile_loss = (
            sum(
                (
                    pinball_loss(forecast, outcome, Decimal(quantile))
                    for forecast, outcome in zip(forecasts, outcomes, strict=True)
                ),
                Decimal(0),
            )
            / count
        )
    return PointMetricResult(
        mae=sum(absolute, Decimal(0)) / count,
        rmse=rmse,
        signed_bias=sum(errors, Decimal(0)) / count,
        median_absolute_error=_median(absolute),
        pinball_loss=quantile_loss,
        target_functional=target_functional,
        quantile=quantile,
        count=len(errors),
    )


def score_frozen_point_forecasts(
    forecasts: tuple[ForecastArtifact, ...],
    labels: tuple[OutcomeLabel, ...],
    *,
    target_functional: TargetFunctional = TargetFunctional.MEAN,
    quantile: Probability | None = None,
) -> PointMetricResult:
    """Score sealed forecasts against later, sealed final labels with exact alignment."""

    if not forecasts or len(forecasts) != len(labels):
        raise ValueError("frozen forecasts and labels require the same nonzero length")
    forecasts = tuple(
        ForecastArtifact.model_validate(item.model_dump(mode="python")) for item in forecasts
    )
    labels = tuple(OutcomeLabel.model_validate(item.model_dump(mode="python")) for item in labels)
    forecast_ids = tuple(item.forecast_id for item in forecasts)
    label_ids = tuple(item.label_id for item in labels)
    forecast_targets = tuple(item.target_id for item in forecasts)
    label_targets = tuple(item.target_id for item in labels)
    for name, identifiers in (
        ("forecast IDs", forecast_ids),
        ("label IDs", label_ids),
        ("forecast targets", forecast_targets),
        ("label targets", label_targets),
    ):
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"{name} must be unique")
    label_by_target = {item.target_id: item for item in labels}
    if set(forecast_targets) != set(label_targets):
        raise ValueError("frozen forecast and final-label targets differ")
    if len({item.dataset_mode for item in forecasts}) != 1:
        raise ValueError("point scoring cannot aggregate incompatible dataset modes")
    if len({item.benchmark_id for item in forecasts}) != 1:
        raise ValueError("point scoring cannot aggregate different benchmarks")
    if len({item.horizon for item in forecasts}) != 1:
        raise ValueError("point scoring cannot aggregate different horizons")
    ordered = tuple(sorted(forecasts, key=lambda item: item.target_id))
    outcomes: list[Decimal] = []
    point_values: list[Decimal] = []
    for forecast in ordered:
        verify_sealed(forecast, "forecast_sha256")
        label = label_by_target[forecast.target_id]
        verify_sealed(label, "label_sha256")
        if forecast.point_forecast is None:
            raise ValueError("point scoring requires a point payload in every frozen forecast")
        if (
            forecast.benchmark_id == "B4_ACCEPTED_PULSE_BASELINE"
            and forecast.lineage.code_commit != STAGE12_PARENT_COMMIT
        ):
            raise ValueError("B4 frozen forecast must bind to the exact Stage-12 parent")
        if label.finalized_at <= forecast.lineage.forecast_origin:
            raise ValueError("final outcome label must be revealed after the forecast origin")
        finality_cutoff = forecast.lineage.label_finality_cutoff
        if finality_cutoff is None or label.finalized_at > finality_cutoff:
            raise ValueError("final outcome label exceeds the forecast's declared finality cutoff")
        point_values.append(forecast.point_forecast)
        outcomes.append(label.outcome)
    return score_forecast(
        tuple(point_values),
        tuple(outcomes),
        target_functional=target_functional,
        quantile=quantile,
    )
