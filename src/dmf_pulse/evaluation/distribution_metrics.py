"""Proper univariate distribution scores and diagnostics."""

from __future__ import annotations

from decimal import Decimal, localcontext

from dmf_pulse.evaluation.models import DistributionMetricResult, Probability


def _canonical_pmf(pmf: dict[Decimal, Probability]) -> tuple[tuple[Decimal, Decimal], ...]:
    if not pmf:
        raise ValueError("PMF cannot be empty")
    if any(not key.is_finite() for key in pmf):
        raise ValueError("PMF support values must be finite")
    values = tuple(sorted((key, Decimal(value)) for key, value in pmf.items()))
    if any(not value.is_finite() or not Decimal(0) <= value <= Decimal(1) for _, value in values):
        raise ValueError("PMF probabilities must be finite and lie in [0, 1]")
    if sum((value for _, value in values), Decimal(0)) != Decimal(1):
        raise ValueError("PMF probabilities must sum exactly to one")
    return values


def discrete_quantile(pmf: dict[Decimal, Probability], alpha: Decimal) -> Decimal:
    if not alpha.is_finite() or not Decimal(0) <= alpha <= Decimal(1):
        raise ValueError("quantile level must lie in [0, 1]")
    cumulative = Decimal(0)
    for outcome, probability in _canonical_pmf(pmf):
        cumulative += probability
        if cumulative >= alpha:
            return outcome
    raise ArithmeticError("proper PMF did not reach the requested quantile")


def ranked_probability_score(pmf: dict[Decimal, Probability], observed: Decimal) -> Decimal:
    if not observed.is_finite():
        raise ValueError("observed outcome must be finite")
    values = _canonical_pmf(pmf)
    cumulative = Decimal(0)
    total = Decimal(0)
    for outcome, probability in values[:-1]:
        cumulative += probability
        observed_cdf = Decimal(observed <= outcome)
        total += (cumulative - observed_cdf) ** 2
    return total


def randomized_pit(
    pmf: dict[Decimal, Probability],
    observed: Decimal,
    *,
    uniform_draw: Probability,
) -> Decimal:
    if not observed.is_finite():
        raise ValueError("observed outcome must be finite")
    draw = Decimal(uniform_draw)
    if not draw.is_finite() or not Decimal(0) <= draw <= Decimal(1):
        raise ValueError("uniform draw must lie in [0, 1]")
    values = _canonical_pmf(pmf)
    below = sum((probability for value, probability in values if value < observed), Decimal(0))
    mass = sum((probability for value, probability in values if value == observed), Decimal(0))
    return below + draw * mass


def interval_score(
    lower: Decimal,
    upper: Decimal,
    observed: Decimal,
    *,
    miscoverage: Decimal,
) -> Decimal:
    if not lower.is_finite() or not upper.is_finite() or not observed.is_finite():
        raise ValueError("interval inputs must be finite")
    if lower > upper:
        raise ValueError("interval lower bound cannot exceed upper bound")
    if not miscoverage.is_finite() or not Decimal(0) < miscoverage < Decimal(1):
        raise ValueError("miscoverage must lie in (0, 1)")
    score = upper - lower
    if observed < lower:
        score += Decimal(2) / miscoverage * (lower - observed)
    elif observed > upper:
        score += Decimal(2) / miscoverage * (observed - upper)
    return score


def quantile_loss(forecast: Decimal, observed: Decimal, alpha: Decimal) -> Decimal:
    if not forecast.is_finite() or not observed.is_finite() or not alpha.is_finite():
        raise ValueError("quantile inputs must be finite")
    if not Decimal(0) <= alpha <= Decimal(1):
        raise ValueError("quantile level must lie in [0, 1]")
    error = observed - forecast
    return alpha * error if error >= 0 else (alpha - Decimal(1)) * error


def score_distribution(
    pmf: dict[Decimal, Probability],
    observed: Decimal,
    *,
    central_coverage: Probability = Decimal("0.8"),
    uniform_draw: Probability = Decimal("0.5"),
    quantile_alpha: Probability = Decimal("0.5"),
) -> DistributionMetricResult:
    """Score one complete discrete forecast under recorded mathematical conventions."""

    if not observed.is_finite():
        raise ValueError("observed outcome must be finite")
    coverage = Decimal(central_coverage)
    if not coverage.is_finite() or not Decimal(0) < coverage < Decimal(1):
        raise ValueError("central coverage must lie in (0, 1)")
    miscoverage = Decimal(1) - coverage
    lower_alpha = miscoverage / Decimal(2)
    upper_alpha = Decimal(1) - lower_alpha
    lower = discrete_quantile(pmf, lower_alpha)
    upper = discrete_quantile(pmf, upper_alpha)
    probability_at_outcome = sum(
        (Decimal(probability) for value, probability in pmf.items() if value == observed),
        Decimal(0),
    )
    log_score_value: Decimal | None
    if probability_at_outcome == 0:
        log_score_value = None
    else:
        with localcontext() as context:
            context.prec = 50
            log_score_value = -probability_at_outcome.ln()
    quantile = discrete_quantile(pmf, Decimal(quantile_alpha))
    return DistributionMetricResult(
        ranked_probability_score=ranked_probability_score(pmf, observed),
        log_score=log_score_value,
        log_score_status="UNBOUNDED" if log_score_value is None else "FINITE",
        randomized_pit=randomized_pit(pmf, observed, uniform_draw=uniform_draw),
        interval_coverage=Probability(lower <= observed <= upper),
        interval_width=upper - lower,
        interval_score=interval_score(
            lower,
            upper,
            observed,
            miscoverage=miscoverage,
        ),
        quantile_loss=quantile_loss(quantile, observed, Decimal(quantile_alpha)),
    )
