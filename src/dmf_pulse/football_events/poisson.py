"""Pure independent-Poisson primitives for the GCS-008 score prior."""

from __future__ import annotations

from decimal import Decimal, localcontext

from dmf_pulse.football_events._decimal import (
    DECIMAL_PRECISION,
    nonnegative_decimal,
    probability,
)


def poisson_pmf(rate: Decimal, max_goals: int) -> tuple[Decimal, ...]:
    """Return P(G=k), k=0..max_goals, without silently absorbing tail mass."""

    lam = nonnegative_decimal(rate, label="Poisson rate")
    if max_goals < 0:
        raise ValueError("max_goals must be nonnegative")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        first = (-lam).exp()
        values = [first]
        for goal_count in range(1, max_goals + 1):
            values.append(values[-1] * lam / Decimal(goal_count))
        if any(value < 0 or not value.is_finite() for value in values):
            raise ArithmeticError("Poisson PMF produced an invalid value")
        return tuple(values)


def poisson_tail_mass(rate: Decimal, max_goals: int) -> Decimal:
    """Return P(G>max_goals) at the current exact Decimal precision."""

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        tail = Decimal(1) - sum(poisson_pmf(rate, max_goals), Decimal(0))
        if tail < 0 and abs(tail) <= Decimal("1e-50"):
            return Decimal(0)
        return probability(tail, label="Poisson tail mass")


def adaptive_poisson_support(
    rate: Decimal,
    *,
    minimum_max_goals: int,
    maximum_max_goals: int,
    tail_tolerance: Decimal,
) -> tuple[int, tuple[Decimal, ...], Decimal]:
    """Choose the smallest bounded support satisfying the configured tail tolerance."""

    lam = nonnegative_decimal(rate, label="Poisson rate")
    tolerance = probability(tail_tolerance, label="tail_tolerance")
    if minimum_max_goals < 0:
        raise ValueError("minimum_max_goals must be nonnegative")
    if maximum_max_goals < minimum_max_goals:
        raise ValueError("maximum_max_goals is below minimum_max_goals")
    selected = minimum_max_goals
    pmf = poisson_pmf(lam, selected)
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        tail = Decimal(1) - sum(pmf, Decimal(0))
        while tail > tolerance and selected < maximum_max_goals:
            selected += 1
            next_value = pmf[-1] * lam / Decimal(selected)
            pmf = (*pmf, next_value)
            tail -= next_value
        if tail < 0 and abs(tail) <= Decimal("1e-50"):
            tail = Decimal(0)
        return selected, pmf, probability(tail, label="Poisson tail mass")


__all__ = ["adaptive_poisson_support", "poisson_pmf", "poisson_tail_mass"]
