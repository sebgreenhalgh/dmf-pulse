"""Stage-13 scorecard composed directly from accepted Stage-12 metrics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext

from dmf_pulse.evaluation.calibration import calibration_intercept_slope
from dmf_pulse.evaluation.decision_regret import calculate_decision_regret
from dmf_pulse.evaluation.distribution_metrics import score_distribution
from dmf_pulse.evaluation.models import ProbabilityBoundaryPolicy
from dmf_pulse.evaluation.probability_metrics import score_multiclass_probabilities
from dmf_pulse.prices.models import (
    PriceEvaluationReport,
    PriceEvaluationRow,
    PriceEvent,
    require_utc,
)


def _precision_recall(
    rows: tuple[PriceEvaluationRow, ...],
    event: PriceEvent,
) -> tuple[Decimal | None, Decimal | None]:
    predicted = tuple(
        row
        for row in rows
        if max(
            (PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE),
            key=lambda value: (row.probabilities.for_event(value), value.value),
        )
        is event
    )
    positives = tuple(row for row in rows if row.observed_event is event)
    true_positive = sum(row.observed_event is event for row in predicted)
    precision = Decimal(true_positive) / Decimal(len(predicted)) if predicted else None
    recall = Decimal(true_positive) / Decimal(len(positives)) if positives else None
    return precision, recall


def _average_precision(
    rows: tuple[PriceEvaluationRow, ...],
    event: PriceEvent,
) -> Decimal | None:
    positives = sum(row.observed_event is event for row in rows)
    if positives == 0 or positives == len(rows):
        return None
    ordered = sorted(
        rows,
        key=lambda row: (-row.probabilities.for_event(event), row.row_id),
    )
    found = 0
    precision_sum = Decimal(0)
    for index, row in enumerate(ordered, start=1):
        if row.observed_event is event:
            found += 1
            precision_sum += Decimal(found) / Decimal(index)
    return precision_sum / Decimal(positives)


def evaluate_price_forecasts(
    rows: tuple[PriceEvaluationRow, ...],
    *,
    evaluation_cutoff: datetime,
    alert_probability: Decimal,
    probability_epsilon: Decimal,
) -> PriceEvaluationReport:
    """Score frozen price forecasts only after their labels are available."""

    evaluation_cutoff = require_utc(evaluation_cutoff, field_name="evaluation_cutoff")
    if not rows:
        raise ValueError("price evaluation requires forecast rows")
    canonical = tuple(sorted(rows, key=lambda row: (row.forecast_origin, row.row_id)))
    if rows != canonical:
        raise ValueError("price evaluation rows must be chronologically ordered")
    horizons = {row.horizon for row in rows}
    if len(horizons) != 1:
        raise ValueError("one price evaluation report cannot mix forecast horizons")
    if any(row.label_available_at > evaluation_cutoff for row in rows):
        raise ValueError("evaluation cutoff precedes one or more outcome labels")
    vectors = tuple(
        (
            row.probabilities.probability_fall,
            row.probabilities.probability_no_change,
            row.probabilities.probability_rise,
        )
        for row in rows
    )
    event_index = {PriceEvent.FALL: 0, PriceEvent.NO_CHANGE: 1, PriceEvent.RISE: 2}
    observed = tuple(event_index[row.observed_event] for row in rows)
    multiclass = score_multiclass_probabilities(
        vectors,
        observed,
        boundary_policy=ProbabilityBoundaryPolicy.DECLARED_EPSILON,
        epsilon=probability_epsilon,
    )
    distribution_scores = tuple(
        score_distribution(
            {Decimal(item.price_units): item.probability for item in row.price_pmf.support},
            Decimal(row.observed_price_units),
        )
        for row in rows
    )
    errors = tuple(
        row.price_pmf.expected_price_units - Decimal(row.observed_price_units) for row in rows
    )
    count = Decimal(len(rows))
    mae = sum((abs(item) for item in errors), Decimal(0)) / count
    with localcontext() as context:
        context.prec = 50
        rmse = (sum((item * item for item in errors), Decimal(0)) / count).sqrt()
    alerts = tuple(
        row
        for row in rows
        if max(row.probabilities.probability_rise, row.probabilities.probability_fall)
        >= alert_probability
    )
    alert_correct = sum(
        (
            row.observed_event is PriceEvent.RISE
            if row.probabilities.probability_rise >= row.probabilities.probability_fall
            else row.observed_event is PriceEvent.FALL
        )
        for row in alerts
    )
    alert_precision = Decimal(alert_correct) / Decimal(len(alerts)) if alerts else None
    rise_calibration = calibration_intercept_slope(
        tuple(row.probabilities.probability_rise for row in rows),
        tuple(int(row.observed_event is PriceEvent.RISE) for row in rows),
    )
    fall_calibration = calibration_intercept_slope(
        tuple(row.probabilities.probability_fall for row in rows),
        tuple(int(row.observed_event is PriceEvent.FALL) for row in rows),
    )
    no_change_calibration = calibration_intercept_slope(
        tuple(row.probabilities.probability_no_change for row in rows),
        tuple(int(row.observed_event is PriceEvent.NO_CHANGE) for row in rows),
    )
    regrets = tuple(
        calculate_decision_regret(
            decision_id=row.row_id,
            comparator_id=f"{row.row_id}:comparator",
            realised_decision_utility=row.realised_decision_utility,
            realised_comparator_utility=row.realised_comparator_utility,
        ).regret
        for row in rows
        if row.realised_decision_utility is not None and row.realised_comparator_utility is not None
    )
    rise_precision, rise_recall = _precision_recall(rows, PriceEvent.RISE)
    fall_precision, fall_recall = _precision_recall(rows, PriceEvent.FALL)
    return PriceEvaluationReport(
        row_count=len(rows),
        price_horizon=rows[0].horizon,
        multiclass_log_loss=multiclass.log_loss,
        multiclass_brier=multiclass.brier_score,
        rise_precision=rise_precision,
        rise_recall=rise_recall,
        rise_pr_auc=_average_precision(rows, PriceEvent.RISE),
        fall_precision=fall_precision,
        fall_recall=fall_recall,
        fall_pr_auc=_average_precision(rows, PriceEvent.FALL),
        alert_precision=alert_precision,
        rise_calibration_status=rise_calibration.status,
        rise_calibration_intercept=rise_calibration.intercept,
        rise_calibration_slope=rise_calibration.slope,
        fall_calibration_status=fall_calibration.status,
        fall_calibration_intercept=fall_calibration.intercept,
        fall_calibration_slope=fall_calibration.slope,
        no_change_calibration_status=no_change_calibration.status,
        no_change_calibration_intercept=no_change_calibration.intercept,
        no_change_calibration_slope=no_change_calibration.slope,
        mean_ranked_probability_score=sum(
            (item.ranked_probability_score for item in distribution_scores), Decimal(0)
        )
        / count,
        expected_price_mae=mae,
        expected_price_rmse=rmse,
        interval_coverage=sum(
            (Decimal(item.interval_coverage) for item in distribution_scores), Decimal(0)
        )
        / count,
        interval_width=sum((item.interval_width for item in distribution_scores), Decimal(0))
        / count,
        mean_decision_regret=(
            sum(regrets, Decimal(0)) / Decimal(len(regrets)) if regrets else None
        ),
        stage12_metric_lineage=(
            "dmf_pulse.evaluation.calibration.calibration_intercept_slope",
            "dmf_pulse.evaluation.decision_regret.calculate_decision_regret",
            "dmf_pulse.evaluation.distribution_metrics.score_distribution",
            "dmf_pulse.evaluation.probability_metrics.score_multiclass_probabilities",
        ),
    )
