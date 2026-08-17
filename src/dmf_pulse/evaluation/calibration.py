"""Time-safe calibration fitting and reporting."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext
from typing import Literal, cast

from dmf_pulse.evaluation.artifacts import seal
from dmf_pulse.evaluation.models import (
    CalibrationArtifact,
    CalibrationResult,
    Probability,
    require_utc,
)


def _validate_calibration_inputs(
    probabilities: tuple[Probability, ...],
    outcomes: tuple[int, ...],
) -> tuple[Decimal, ...]:
    if not probabilities or len(probabilities) != len(outcomes):
        raise ValueError("calibration inputs require equal nonzero length")
    if any(isinstance(item, bool) or item not in {0, 1} for item in outcomes):
        raise ValueError("calibration outcomes must be binary")
    values = tuple(Decimal(item) for item in probabilities)
    if any(not item.is_finite() or not Decimal(0) <= item <= Decimal(1) for item in values):
        raise ValueError("calibration probabilities must be finite and lie in [0, 1]")
    return values


def _logit(probability: Decimal, epsilon: Decimal) -> Decimal:
    bounded = min(max(probability, epsilon), Decimal(1) - epsilon)
    with localcontext() as context:
        context.prec = 50
        return (bounded / (Decimal(1) - bounded)).ln()


def _sigmoid(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        if value >= 0:
            exponent = (-value).exp()
            return Decimal(1) / (Decimal(1) + exponent)
        exponent = value.exp()
        return exponent / (Decimal(1) + exponent)


def _canonical_calibration_parameters(
    intercept: Decimal, slope: Decimal, *, tolerance: Decimal
) -> tuple[Decimal, Decimal]:
    """Remove insignificant Newton residue around the exact identity calibrator."""

    canonical_intercept = Decimal(0) if abs(intercept) <= tolerance else intercept
    canonical_slope = Decimal(1) if abs(slope - Decimal(1)) <= tolerance else slope
    return canonical_intercept, canonical_slope


def reliability_summary(
    probabilities: tuple[Probability, ...],
    outcomes: tuple[int, ...],
    *,
    bins: int = 10,
) -> tuple[dict[str, object], ...]:
    values = _validate_calibration_inputs(probabilities, outcomes)
    if bins <= 0:
        raise ValueError("bins must be positive")
    ordered = sorted(
        (
            (probability, outcome, index)
            for index, (probability, outcome) in enumerate(zip(values, outcomes, strict=True))
        ),
        key=lambda item: (item[0], item[2]),
    )
    result: list[dict[str, object]] = []
    count = len(ordered)
    for bin_index in range(min(bins, count)):
        start = bin_index * count // min(bins, count)
        end = (bin_index + 1) * count // min(bins, count)
        chunk = ordered[start:end]
        if not chunk:
            continue
        result.append(
            {
                "bin": bin_index,
                "count": len(chunk),
                "mean_forecast": sum((item[0] for item in chunk), Decimal(0)) / Decimal(len(chunk)),
                "observed_rate": sum((Decimal(item[1]) for item in chunk), Decimal(0))
                / Decimal(len(chunk)),
                "minimum_forecast": chunk[0][0],
                "maximum_forecast": chunk[-1][0],
            }
        )
    return tuple(result)


def calibration_intercept_slope(
    probabilities: tuple[Probability, ...],
    outcomes: tuple[int, ...],
    *,
    epsilon: Decimal = Decimal("0.000001"),
    bins: int = 10,
    max_iterations: int = 50,
    tolerance: Decimal = Decimal("0.000000000001"),
) -> CalibrationResult:
    """Fit outcome ~ intercept + slope*logit(p) by deterministic Newton updates."""

    values = _validate_calibration_inputs(probabilities, outcomes)
    if not epsilon.is_finite() or not Decimal(0) < epsilon < Decimal("0.5"):
        raise ValueError("calibration epsilon must lie in (0, 0.5)")
    if max_iterations <= 0 or tolerance <= 0:
        raise ValueError("calibration iteration limit and tolerance must be positive")
    reliability = reliability_summary(probabilities, outcomes, bins=bins)
    if len(set(outcomes)) < 2 or len(set(values)) < 2:
        return CalibrationResult(
            intercept=None,
            slope=None,
            status="INSUFFICIENT_VARIATION",
            reliability=reliability,
            count=len(outcomes),
        )
    x_values = tuple(_logit(item, epsilon) for item in values)
    intercept = Decimal(0)
    slope = Decimal(1)
    try:
        for _ in range(max_iterations):
            probabilities_fit = tuple(_sigmoid(intercept + slope * x) for x in x_values)
            gradient_0 = sum(
                (Decimal(outcome) - fitted)
                for outcome, fitted in zip(outcomes, probabilities_fit, strict=True)
            )
            gradient_1 = sum(
                (Decimal(outcome) - fitted) * x
                for outcome, fitted, x in zip(outcomes, probabilities_fit, x_values, strict=True)
            )
            weight = tuple(item * (Decimal(1) - item) for item in probabilities_fit)
            h00 = -sum(weight, Decimal(0))
            h01 = -sum((w * x for w, x in zip(weight, x_values, strict=True)), Decimal(0))
            h11 = -sum((w * x * x for w, x in zip(weight, x_values, strict=True)), Decimal(0))
            determinant = h00 * h11 - h01 * h01
            if determinant == 0:
                raise ArithmeticError("singular calibration Hessian")
            delta_0 = (h11 * gradient_0 - h01 * gradient_1) / determinant
            delta_1 = (-h01 * gradient_0 + h00 * gradient_1) / determinant
            intercept -= delta_0
            slope -= delta_1
            if max(abs(delta_0), abs(delta_1)) <= tolerance:
                intercept, slope = _canonical_calibration_parameters(
                    intercept, slope, tolerance=tolerance
                )
                return CalibrationResult(
                    intercept=intercept,
                    slope=slope,
                    status="FITTED",
                    reliability=reliability,
                    count=len(outcomes),
                )
    except (ArithmeticError, OverflowError):
        return CalibrationResult(
            intercept=None,
            slope=None,
            status="NUMERICAL_FAILURE",
            reliability=reliability,
            count=len(outcomes),
        )
    return CalibrationResult(
        intercept=None,
        slope=None,
        status="NUMERICAL_FAILURE",
        reliability=reliability,
        count=len(outcomes),
    )


def fit_calibration_artifact(
    *,
    calibration_id: str,
    method: str,
    training_cutoff: datetime,
    records: tuple[tuple[str, datetime, str, Decimal, int], ...],
    outer_origin_ids: tuple[str, ...],
) -> CalibrationArtifact:
    """Freeze a calibrator using records strictly available before the training cutoff.

    Each input row is ``(record_id, usable_at, origin_id, probability, outcome)``.
    Outer-origin rows are prohibited rather than silently filtered.
    """

    require_utc(training_cutoff, field_name="training_cutoff")
    method_upper = method.upper()
    if method_upper not in {"IDENTITY", "LOGISTIC", "ISOTONIC"}:
        raise ValueError("unsupported calibration method")
    outer = set(outer_origin_ids)
    record_ids = tuple(row[0] for row in records)
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("calibration record IDs must be unique")
    if len(outer_origin_ids) != len(outer):
        raise ValueError("outer origin IDs must be unique")
    for _record_id, available_at, _origin_id, probability, binary_outcome in records:
        require_utc(available_at, field_name="calibration_available_at")
        if not probability.is_finite() or not Decimal(0) <= probability <= Decimal(1):
            raise ValueError("calibration probabilities must be finite and lie in [0, 1]")
        if isinstance(binary_outcome, bool) or binary_outcome not in {0, 1}:
            raise ValueError("calibration outcomes must be binary")
    contaminated = tuple(sorted(row[0] for row in records if row[2] in outer))
    if contaminated:
        raise ValueError("outer-fold records cannot fit their reported calibrator")
    eligible = tuple(row for row in records if row[1] <= training_cutoff)
    if not eligible:
        raise ValueError("calibration requires at least one eligible training row")
    parameters: dict[str, Decimal]
    if method_upper == "IDENTITY":
        parameters = {"intercept": Decimal(0), "slope": Decimal(1)}
    elif method_upper == "LOGISTIC":
        result = calibration_intercept_slope(
            tuple(row[3] for row in eligible),
            tuple(row[4] for row in eligible),
        )
        if result.status != "FITTED" or result.intercept is None or result.slope is None:
            raise ValueError("logistic calibration could not be fitted on eligible history")
        parameters = {"intercept": result.intercept, "slope": result.slope}
    else:
        # The exact isotonic step function is represented by sorted threshold/value parameters.
        ordered = sorted((row[3], Decimal(row[4])) for row in eligible)
        grouped: list[tuple[Decimal, Decimal, int]] = []
        for probability, outcome_value in ordered:
            if grouped and grouped[-1][0] == probability:
                point, outcome_sum, count = grouped[-1]
                grouped[-1] = (point, outcome_sum + outcome_value, count + 1)
            else:
                grouped.append((probability, outcome_value, 1))
        blocks: list[tuple[list[Decimal], Decimal, int]] = []
        for probability, outcome_sum, count in grouped:
            blocks.append(([probability], outcome_sum / Decimal(count), count))
            while len(blocks) >= 2 and blocks[-2][1] > blocks[-1][1]:
                left_points, left_mean, left_count = blocks[-2]
                right_points, right_mean, right_count = blocks[-1]
                merged_count = left_count + right_count
                merged_mean = (
                    left_mean * Decimal(left_count) + right_mean * Decimal(right_count)
                ) / Decimal(merged_count)
                blocks[-2:] = [(left_points + right_points, merged_mean, merged_count)]
        parameters = {}
        for index, (points, mean, _count) in enumerate(blocks):
            parameters[f"threshold_{index}"] = max(points)
            parameters[f"value_{index}"] = mean
    value = CalibrationArtifact(
        calibration_id=calibration_id,
        method=cast(Literal["IDENTITY", "LOGISTIC", "ISOTONIC"], method_upper),
        training_cutoff=training_cutoff,
        training_record_ids=tuple(sorted(row[0] for row in eligible)),
        excluded_outer_origin_ids=tuple(sorted(outer_origin_ids)),
        parameters=parameters,
        artifact_sha256="0" * 64,
    )
    return seal(value, "artifact_sha256")
