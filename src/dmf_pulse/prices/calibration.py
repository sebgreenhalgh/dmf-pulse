"""Multiclass calibration composed from Stage-12 chronological calibrators."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext
from typing import Literal

from dmf_pulse.evaluation.artifacts import verify_sealed
from dmf_pulse.evaluation.calibration import fit_calibration_artifact
from dmf_pulse.evaluation.models import CalibrationArtifact
from dmf_pulse.prices.artifacts import seal_price_calibration
from dmf_pulse.prices.errors import PriceLeakageError
from dmf_pulse.prices.models import (
    PriceCalibrationArtifact,
    PriceEvaluationRow,
    PriceEvent,
    PriceProbabilityVector,
    require_utc,
)


def fit_price_calibration(
    rows: tuple[PriceEvaluationRow, ...],
    *,
    calibration_id: str,
    calibration_version: str,
    method: Literal["IDENTITY", "LOGISTIC", "ISOTONIC"],
    training_cutoff: datetime,
    probability_epsilon: Decimal,
    outer_origin_ids: tuple[str, ...] = (),
) -> PriceCalibrationArtifact:
    """Fit all class calibrators from prior labels only; Stage 12 blocks outer rows."""

    training_cutoff = require_utc(training_cutoff, field_name="training_cutoff")
    if not rows:
        raise ValueError("price calibration requires prior forecast rows")
    future = tuple(sorted(row.row_id for row in rows if row.label_available_at > training_cutoff))
    if future:
        raise PriceLeakageError(
            "PRICE_CALIBRATION_FUTURE_LABEL_BLOCKED",
            "calibration cutoff precedes label availability for: " + ", ".join(future),
        )

    def build(event: PriceEvent) -> CalibrationArtifact:
        records = tuple(
            (
                row.row_id,
                row.label_available_at,
                row.row_id,
                row.probabilities.for_event(event),
                int(row.observed_event is event),
            )
            for row in rows
        )
        return fit_calibration_artifact(
            calibration_id=f"{calibration_id}:{event.value}",
            method=method,
            training_cutoff=training_cutoff,
            records=records,
            outer_origin_ids=outer_origin_ids,
        )

    value = PriceCalibrationArtifact(
        calibration_id=calibration_id,
        calibration_version=calibration_version,
        method=method,
        training_cutoff=training_cutoff,
        probability_epsilon=probability_epsilon,
        fall=build(PriceEvent.FALL),
        no_change=build(PriceEvent.NO_CHANGE),
        rise=build(PriceEvent.RISE),
        artifact_sha256="0" * 64,
    )
    return seal_price_calibration(value)


def _sigmoid(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        if value >= 0:
            exponent = (-value).exp()
            return Decimal(1) / (Decimal(1) + exponent)
        exponent = value.exp()
        return exponent / (Decimal(1) + exponent)


def _apply_binary(
    probability: Decimal,
    artifact: CalibrationArtifact,
    *,
    probability_epsilon: Decimal,
) -> Decimal:
    if artifact.method == "IDENTITY":
        return probability
    if artifact.method == "LOGISTIC":
        bounded = min(
            max(probability, probability_epsilon),
            Decimal(1) - probability_epsilon,
        )
        with localcontext() as context:
            context.prec = 50
            logit = (bounded / (Decimal(1) - bounded)).ln()
        return _sigmoid(artifact.parameters["intercept"] + artifact.parameters["slope"] * logit)
    pair_count = len(artifact.parameters) // 2
    for index in range(pair_count):
        if probability <= artifact.parameters[f"threshold_{index}"]:
            return artifact.parameters[f"value_{index}"]
    return artifact.parameters[f"value_{pair_count - 1}"]


def apply_price_calibration(
    probabilities: PriceProbabilityVector,
    artifact: PriceCalibrationArtifact,
) -> PriceProbabilityVector:
    verify_sealed(artifact, "artifact_sha256")
    values = (
        _apply_binary(
            probabilities.probability_fall,
            artifact.fall,
            probability_epsilon=artifact.probability_epsilon,
        ),
        _apply_binary(
            probabilities.probability_no_change,
            artifact.no_change,
            probability_epsilon=artifact.probability_epsilon,
        ),
        _apply_binary(
            probabilities.probability_rise,
            artifact.rise,
            probability_epsilon=artifact.probability_epsilon,
        ),
    )
    total = sum(values, Decimal(0))
    if total <= 0:
        raise ValueError("calibration produced no probability mass")
    fall = values[0] / total
    raw_rise = values[2] / total
    no_change = Decimal(1) - fall - raw_rise
    rise = Decimal(1) - (fall + no_change)
    return PriceProbabilityVector(
        probability_fall=fall,
        probability_no_change=no_change,
        probability_rise=rise,
    )
