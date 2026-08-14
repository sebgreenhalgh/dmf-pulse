"""Adaptive finite joint-score support with explicit renormalised tail treatment."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from dmf_pulse.football_events._decimal import (
    DECIMAL_PRECISION,
    nonnegative_decimal,
    probability,
)
from dmf_pulse.football_events.poisson import adaptive_poisson_support


@dataclass(frozen=True, slots=True)
class ScoreGrid:
    """Internal finite score matrix before public rounding."""

    home_max: int
    away_max: int
    probabilities: tuple[tuple[Decimal, ...], ...]
    omitted_tail_mass: Decimal
    home_marginal_tail: Decimal
    away_marginal_tail: Decimal

    def flattened(self) -> tuple[Decimal, ...]:
        return tuple(value for row in self.probabilities for value in row)


def build_adaptive_score_grid(
    home_rate: Decimal,
    away_rate: Decimal,
    *,
    minimum_max_goals: int,
    maximum_max_goals: int,
    tail_tolerance: Decimal,
    hard_tail_limit: Decimal,
) -> ScoreGrid:
    """Construct an independent-Poisson grid and renormalise its retained mass."""

    home = nonnegative_decimal(home_rate, label="home_rate")
    away = nonnegative_decimal(away_rate, label="away_rate")
    tolerance = probability(tail_tolerance, label="tail_tolerance")
    hard_limit = probability(hard_tail_limit, label="hard_tail_limit")
    if hard_limit < tolerance:
        raise ValueError("hard_tail_limit must be at least tail_tolerance")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        marginal_tolerance = tolerance / Decimal(2)
        home_max, home_pmf, home_tail = adaptive_poisson_support(
            home,
            minimum_max_goals=minimum_max_goals,
            maximum_max_goals=maximum_max_goals,
            tail_tolerance=marginal_tolerance,
        )
        away_max, away_pmf, away_tail = adaptive_poisson_support(
            away,
            minimum_max_goals=minimum_max_goals,
            maximum_max_goals=maximum_max_goals,
            tail_tolerance=marginal_tolerance,
        )
        retained_home = sum(home_pmf, Decimal(0))
        retained_away = sum(away_pmf, Decimal(0))
        retained_joint = retained_home * retained_away
        omitted_tail = Decimal(1) - retained_joint
        if omitted_tail < 0 and abs(omitted_tail) <= Decimal("1e-50"):
            omitted_tail = Decimal(0)
        omitted_tail = probability(omitted_tail, label="joint omitted tail mass")
        if omitted_tail > hard_limit:
            raise ValueError(
                "adaptive score support exceeded hard_tail_limit; "
                "increase maximum_max_goals or reduce the prior rates"
            )
        if omitted_tail > tolerance:
            raise ValueError(
                "adaptive score support exceeded tail_tolerance; "
                "explicit tail states are not implemented in the Stage-8 baseline"
            )
        if retained_joint <= 0:
            raise ArithmeticError("adaptive score grid retained no probability mass")
        matrix_rows = [
            [
                (home_probability * away_probability) / retained_joint
                for away_probability in away_pmf
            ]
            for home_probability in home_pmf
        ]

        # Division rounds each cell independently.  A tolerance check alone leaves
        # the stored Decimal coefficients a few ulps short of an exact simplex for
        # some rates (Hypothesis found home=0, away=1.4).  Sum the finite Decimal
        # coefficients at enough precision to be exact and place the residual on
        # the deterministic largest cell, mirroring the public-simplex boundary.
        with localcontext() as exact_context:
            exact_context.prec = DECIMAL_PRECISION * 2
            flattened = [value for row in matrix_rows for value in row]
            total = sum(flattened, Decimal(0))
            residual = Decimal(1) - total
            residual_index = max(
                range(len(flattened)),
                key=lambda index: (flattened[index], -index),
            )
            away_width = away_max + 1
            residual_home, residual_away = divmod(residual_index, away_width)
            matrix_rows[residual_home][residual_away] += residual
            corrected_total = sum(
                (value for row in matrix_rows for value in row),
                Decimal(0),
            )
        if corrected_total != Decimal(1):
            raise ArithmeticError("internal score matrix does not sum exactly to one")
        matrix = tuple(tuple(row) for row in matrix_rows)
        return ScoreGrid(
            home_max=home_max,
            away_max=away_max,
            probabilities=matrix,
            omitted_tail_mass=omitted_tail,
            home_marginal_tail=home_tail,
            away_marginal_tail=away_tail,
        )


__all__ = ["ScoreGrid", "build_adaptive_score_grid"]
