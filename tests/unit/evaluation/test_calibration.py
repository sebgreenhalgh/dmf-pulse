from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from dmf_pulse.evaluation.calibration import (
    calibration_intercept_slope,
    fit_calibration_artifact,
    reliability_summary,
)
from tests.evaluation_helpers import BASE

pytestmark = pytest.mark.unit


def test_reliability_is_reproducible_and_complete() -> None:
    summary = reliability_summary(
        (Decimal("0.1"), Decimal("0.2"), Decimal("0.8"), Decimal("0.9")),
        (0, 0, 1, 1),
        bins=2,
    )
    assert len(summary) == 2
    assert sum(int(item["count"]) for item in summary) == 4
    assert summary[0]["mean_forecast"] == Decimal("0.15")
    assert summary[1]["observed_rate"] == Decimal(1)


def test_logistic_calibration_reports_status_truthfully() -> None:
    fitted = calibration_intercept_slope(
        (
            Decimal("0.1"),
            Decimal("0.2"),
            Decimal("0.4"),
            Decimal("0.6"),
            Decimal("0.8"),
            Decimal("0.9"),
        ),
        (0, 0, 0, 1, 1, 1),
    )
    assert fitted.status in {"FITTED", "NUMERICAL_FAILURE"}
    flat = calibration_intercept_slope((Decimal("0.5"), Decimal("0.5")), (0, 1))
    assert flat.status == "INSUFFICIENT_VARIATION"

    exactly_calibrated = calibration_intercept_slope(
        (Decimal("0.25"),) * 4 + (Decimal("0.75"),) * 4,
        (0, 0, 0, 1, 0, 1, 1, 1),
    )
    assert exactly_calibrated.status == "FITTED"
    assert exactly_calibrated.intercept == Decimal(0)
    assert exactly_calibrated.slope == Decimal(1)


def test_calibration_artifact_excludes_outer_fold_and_future_training() -> None:
    records = (
        ("r1", BASE - timedelta(days=2), "inner-1", Decimal("0.2"), 0),
        ("r2", BASE - timedelta(days=1), "inner-2", Decimal("0.8"), 1),
        ("future", BASE + timedelta(days=1), "future", Decimal("0.9"), 1),
    )
    artifact = fit_calibration_artifact(
        calibration_id="cal",
        method="IDENTITY",
        training_cutoff=BASE,
        records=records,
        outer_origin_ids=("outer",),
    )
    assert artifact.training_record_ids == ("r1", "r2")
    assert artifact.parameters == {"intercept": Decimal(0), "slope": Decimal(1)}
    contaminated = (
        *records,
        ("outer-row", BASE - timedelta(hours=1), "outer", Decimal("0.5"), 1),
    )
    with pytest.raises(ValueError, match="outer-fold"):
        fit_calibration_artifact(
            calibration_id="bad",
            method="IDENTITY",
            training_cutoff=BASE,
            records=contaminated,
            outer_origin_ids=("outer",),
        )
    with pytest.raises(ValueError, match="record IDs"):
        fit_calibration_artifact(
            calibration_id="duplicate",
            method="IDENTITY",
            training_cutoff=BASE,
            records=(records[0], records[0]),
            outer_origin_ids=(),
        )


def test_isotonic_artifact_is_monotone_and_method_validation() -> None:
    artifact = fit_calibration_artifact(
        calibration_id="iso",
        method="ISOTONIC",
        training_cutoff=BASE,
        records=(
            ("a", BASE, "i1", Decimal("0.2"), 1),
            ("b", BASE, "i2", Decimal("0.4"), 0),
            ("c", BASE, "i3", Decimal("0.8"), 1),
        ),
        outer_origin_ids=("outer",),
    )
    values = [value for key, value in artifact.parameters.items() if key.startswith("value_")]
    assert values == sorted(values)
    with pytest.raises(ValueError, match="unsupported"):
        fit_calibration_artifact(
            calibration_id="bad",
            method="PLATTISH",
            training_cutoff=BASE,
            records=(("a", BASE, "i", Decimal("0.5"), 1),),
            outer_origin_ids=(),
        )


def test_isotonic_calibration_aggregates_tied_forecasts_deterministically() -> None:
    artifact = fit_calibration_artifact(
        calibration_id="ties",
        method="ISOTONIC",
        training_cutoff=BASE,
        records=(
            ("a", BASE, "i1", Decimal("0.5"), 0),
            ("b", BASE, "i2", Decimal("0.5"), 1),
        ),
        outer_origin_ids=(),
    )
    assert artifact.parameters == {
        "threshold_0": Decimal("0.5"),
        "value_0": Decimal("0.5"),
    }
