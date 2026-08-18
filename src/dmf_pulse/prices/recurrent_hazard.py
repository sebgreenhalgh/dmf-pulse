"""P2 recurrent competing hazard and model-inferred threshold diagnostics."""

from __future__ import annotations

from decimal import Decimal, localcontext

from dmf_pulse.prices.configuration import PriceConfig
from dmf_pulse.prices.models import (
    LatentPressureState,
    PriceEvent,
    PriceProbabilityVector,
    ThresholdDistance,
)


def _logit(probability: Decimal, *, epsilon: Decimal) -> Decimal:
    bounded = min(max(probability, epsilon), Decimal(1) - epsilon)
    with localcontext() as context:
        context.prec = 50
        return (bounded / (Decimal(1) - bounded)).ln()


def _softmax(
    fall_score: Decimal, rise_score: Decimal, *, score_cap: Decimal
) -> PriceProbabilityVector:
    with localcontext() as context:
        context.prec = 50
        fall_exp = min(max(fall_score, -score_cap), score_cap).exp()
        rise_exp = min(max(rise_score, -score_cap), score_cap).exp()
    denominator = Decimal(1) + fall_exp + rise_exp
    fall = fall_exp / denominator
    raw_rise = rise_exp / denominator
    no_change = Decimal(1) - fall - raw_rise
    rise = Decimal(1) - (fall + no_change)
    return PriceProbabilityVector(
        probability_fall=fall,
        probability_no_change=no_change,
        probability_rise=rise,
    )


def threshold_distance(
    state: LatentPressureState,
    *,
    config: PriceConfig,
) -> ThresholdDistance:
    policy = config.recurrent_pressure
    scale = max(state.uncertainty, policy.uncertainty_floor)
    rise = (state.rise_pressure - policy.rise_boundary) / scale
    fall = (state.fall_pressure - policy.fall_boundary) / scale
    spread = policy.threshold_interval_z

    def crossed(distance: Decimal) -> Decimal:
        with localcontext() as context:
            context.prec = 50
            if distance >= 0:
                exp_value = (-distance).exp()
                return Decimal(1) / (Decimal(1) + exp_value)
            exp_value = distance.exp()
            return exp_value / (Decimal(1) + exp_value)

    return ThresholdDistance(
        rise_distance_median=rise,
        rise_distance_p10=rise - spread,
        rise_distance_p90=rise + spread,
        fall_distance_median=fall,
        fall_distance_p10=fall - spread,
        fall_distance_p90=fall + spread,
        probability_rise_boundary_crossed=crossed(rise),
        probability_fall_boundary_crossed=crossed(fall),
    )


def predict_recurrent_hazard(
    state: LatentPressureState,
    *,
    config: PriceConfig,
    baseline: PriceProbabilityVector | None = None,
) -> PriceProbabilityVector:
    """Adjust the P1 baseline with recurrent state; no hidden threshold is claimed."""

    policy = config.recurrent_pressure
    distance = threshold_distance(state, config=config)
    if baseline is None:
        base_fall = policy.default_event_logit
        base_rise = policy.default_event_logit
    else:
        base_no = max(baseline.probability_no_change, policy.probability_epsilon)
        base_fall = _logit(
            baseline.probability_fall / (baseline.probability_fall + base_no),
            epsilon=policy.probability_epsilon,
        )
        base_rise = _logit(
            baseline.probability_rise / (baseline.probability_rise + base_no),
            epsilon=policy.probability_epsilon,
        )
    fall_score = base_fall + distance.fall_distance_median
    rise_score = base_rise + distance.rise_distance_median
    if state.previous_event is PriceEvent.FALL:
        fall_score += policy.recurrent_same_direction_bonus
        rise_score -= policy.opposite_direction_penalty
    elif state.previous_event is PriceEvent.RISE:
        rise_score += policy.recurrent_same_direction_bonus
        fall_score -= policy.opposite_direction_penalty
    fall_score -= policy.gap_decay * Decimal(state.updates_since_fall)
    rise_score -= policy.gap_decay * Decimal(state.updates_since_rise)
    return _softmax(fall_score, rise_score, score_cap=policy.score_cap)
