"""Soft constrained KL projection of a score prior onto market evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from dmf_pulse.football_events._decimal import (
    DECIMAL_PRECISION,
    positive_decimal,
)
from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketConstraintSet,
    build_design_matrix,
)
from dmf_pulse.football_events.score_prior import ScorePrior


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    status: str
    probabilities: tuple[tuple[Decimal, ...], ...]
    iterations: int
    converged: bool
    dual_objective: Decimal
    prior_to_projected_kl: Decimal
    projected_market_probabilities: tuple[Decimal, ...]
    error_code: str | None


def _solve_linear_system(
    matrix: tuple[tuple[Decimal, ...], ...],
    vector: tuple[Decimal, ...],
) -> tuple[Decimal, ...]:
    size = len(vector)
    if size == 0:
        return ()
    work = [[*matrix[row], vector[row]] for row in range(size)]
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        for column in range(size):
            pivot = max(range(column, size), key=lambda row: abs(work[row][column]))
            if work[pivot][column] == 0:
                raise ArithmeticError("projection Hessian is singular")
            if pivot != column:
                work[column], work[pivot] = work[pivot], work[column]
            divisor = work[column][column]
            work[column] = [value / divisor for value in work[column]]
            for row in range(size):
                if row == column:
                    continue
                factor = work[row][column]
                if factor == 0:
                    continue
                work[row] = [
                    work[row][item] - factor * work[column][item] for item in range(size + 1)
                ]
        return tuple(work[row][-1] for row in range(size))


def _flatten(matrix: tuple[tuple[Decimal, ...], ...]) -> tuple[Decimal, ...]:
    return tuple(value for row in matrix for value in row)


def _reshape(
    values: tuple[Decimal, ...],
    *,
    home_max: int,
    away_max: int,
) -> tuple[tuple[Decimal, ...], ...]:
    width = away_max + 1
    expected = (home_max + 1) * width
    if len(values) != expected:
        raise ValueError("score vector does not match support")
    return tuple(
        tuple(values[home_goals * width + away_goals] for away_goals in range(width))
        for home_goals in range(home_max + 1)
    )


def _market_probabilities(
    design: tuple[tuple[Decimal, ...], ...],
    probabilities: tuple[Decimal, ...],
) -> tuple[Decimal, ...]:
    return tuple(
        sum(
            (indicator * value for indicator, value in zip(row, probabilities, strict=True)),
            Decimal(0),
        )
        for row in design
    )


def _kl_divergence(
    probabilities: tuple[Decimal, ...],
    prior: tuple[Decimal, ...],
) -> Decimal:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return sum(
            (
                value * (value / base).ln()
                for value, base in zip(probabilities, prior, strict=True)
                if value > 0
            ),
            Decimal(0),
        )


def _state(
    dual: tuple[Decimal, ...],
    *,
    prior: tuple[Decimal, ...],
    design: tuple[tuple[Decimal, ...], ...],
    targets: tuple[Decimal, ...],
    inverse_weights: tuple[Decimal, ...],
    include_hessian: bool,
) -> tuple[
    Decimal,
    tuple[Decimal, ...],
    tuple[Decimal, ...],
    tuple[Decimal, ...],
    tuple[tuple[Decimal, ...], ...],
]:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        log_weights = tuple(
            base.ln()
            - sum(
                (dual[index] * design[index][cell] for index in range(len(dual))),
                Decimal(0),
            )
            for cell, base in enumerate(prior)
        )
        maximum = max(log_weights)
        scaled = tuple((value - maximum).exp() for value in log_weights)
        normalizer = sum(scaled, Decimal(0))
        probabilities = tuple(value / normalizer for value in scaled)
        log_normalizer = maximum + normalizer.ln()
        projected = _market_probabilities(design, probabilities)
        gradient = tuple(
            targets[index] - projected[index] + inverse_weights[index] * dual[index]
            for index in range(len(dual))
        )
        objective = (
            log_normalizer
            + sum(
                (targets[index] * dual[index] for index in range(len(dual))),
                Decimal(0),
            )
            + Decimal("0.5")
            * sum(
                (inverse_weights[index] * dual[index] * dual[index] for index in range(len(dual))),
                Decimal(0),
            )
        )
        if not include_hessian:
            return objective, probabilities, projected, gradient, ()
        second_moments = tuple(
            tuple(
                sum(
                    (
                        design[row][cell] * design[column][cell] * probabilities[cell]
                        for cell in range(len(probabilities))
                    ),
                    Decimal(0),
                )
                for column in range(len(dual))
            )
            for row in range(len(dual))
        )
        hessian = tuple(
            tuple(
                second_moments[row][column]
                - projected[row] * projected[column]
                + (inverse_weights[row] if row == column else Decimal(0))
                for column in range(len(dual))
            )
            for row in range(len(dual))
        )
        return objective, probabilities, projected, gradient, hessian


def project_to_markets(
    prior: ScorePrior,
    constraint_set: MarketConstraintSet,
    *,
    max_iterations: int,
    gradient_tolerance: Decimal,
    line_search_min_step: Decimal,
    allow_prior_fallback: bool,
) -> ProjectionResult:
    """Solve the convex soft information projection in a deterministic dual space."""

    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")
    tolerance = positive_decimal(gradient_tolerance, label="gradient_tolerance")
    minimum_step = positive_decimal(line_search_min_step, label="line_search_min_step")
    if minimum_step >= 1:
        raise ValueError("line_search_min_step must be below one")
    constraints = constraint_set.constraints
    if not constraints:
        return ProjectionResult(
            status="PRIOR_ONLY",
            probabilities=prior.grid.probabilities,
            iterations=0,
            converged=True,
            dual_objective=Decimal(0),
            prior_to_projected_kl=Decimal(0),
            projected_market_probabilities=(),
            error_code=None,
        )
    design = build_design_matrix(
        constraints,
        home_max=prior.grid.home_max,
        away_max=prior.grid.away_max,
    )
    flat_prior = _flatten(prior.grid.probabilities)
    if any(value <= 0 for value in flat_prior):
        raise ValueError("KL projection requires strictly positive prior support")
    targets = tuple(item.target_probability for item in constraints)
    inverse_weights = tuple(
        (item.uncertainty * item.uncertainty) / item.weight for item in constraints
    )
    dual = tuple(Decimal(0) for _ in constraints)
    best_probabilities = flat_prior
    best_projected = _market_probabilities(design, flat_prior)
    best_objective: Decimal | None = None
    converged = False
    iterations = 0
    try:
        for iteration in range(1, max_iterations + 1):
            iterations = iteration
            objective, probabilities, projected, gradient, hessian = _state(
                dual,
                prior=flat_prior,
                design=design,
                targets=targets,
                inverse_weights=inverse_weights,
                include_hessian=True,
            )
            if best_objective is None or objective < best_objective:
                best_objective = objective
                best_probabilities = probabilities
                best_projected = projected
            if max(abs(value) for value in gradient) <= tolerance:
                converged = True
                break
            direction = _solve_linear_system(
                hessian,
                tuple(-value for value in gradient),
            )
            step = Decimal(1)
            accepted = False
            directional_derivative = sum(
                (gradient[index] * direction[index] for index in range(len(direction))),
                Decimal(0),
            )
            while step >= minimum_step:
                candidate = tuple(
                    dual[index] + step * direction[index] for index in range(len(dual))
                )
                candidate_objective, candidate_probabilities, candidate_projected, _, _ = _state(
                    candidate,
                    prior=flat_prior,
                    design=design,
                    targets=targets,
                    inverse_weights=inverse_weights,
                    include_hessian=False,
                )
                armijo = objective + Decimal("0.0001") * step * directional_derivative
                if candidate_objective <= armijo:
                    dual = candidate
                    best_objective = candidate_objective
                    best_probabilities = candidate_probabilities
                    best_projected = candidate_projected
                    accepted = True
                    break
                step /= Decimal(2)
            if not accepted:
                break
        if not converged:
            _, final_probabilities, final_projected, final_gradient, _ = _state(
                dual,
                prior=flat_prior,
                design=design,
                targets=targets,
                inverse_weights=inverse_weights,
                include_hessian=False,
            )
            if max(abs(value) for value in final_gradient) <= tolerance:
                converged = True
                best_probabilities = final_probabilities
                best_projected = final_projected
    except (ArithmeticError, ValueError):
        if not allow_prior_fallback:
            raise
        best_probabilities = flat_prior
        best_projected = _market_probabilities(design, flat_prior)
        return ProjectionResult(
            status="DEGRADED",
            probabilities=prior.grid.probabilities,
            iterations=iterations,
            converged=False,
            dual_objective=Decimal(0),
            prior_to_projected_kl=Decimal(0),
            projected_market_probabilities=best_projected,
            error_code="NUMERICAL_FALLBACK_TO_PRIOR",
        )
    if not converged and allow_prior_fallback:
        return ProjectionResult(
            status="DEGRADED",
            probabilities=prior.grid.probabilities,
            iterations=iterations,
            converged=False,
            dual_objective=best_objective or Decimal(0),
            prior_to_projected_kl=Decimal(0),
            projected_market_probabilities=_market_probabilities(design, flat_prior),
            error_code="PROJECTION_DID_NOT_CONVERGE",
        )
    if not converged:
        raise ArithmeticError("soft KL projection did not converge")
    if best_objective is None:
        raise ArithmeticError("projection converged without an objective")
    projected_matrix = _reshape(
        best_probabilities,
        home_max=prior.grid.home_max,
        away_max=prior.grid.away_max,
    )
    return ProjectionResult(
        status="PROJECTED",
        probabilities=projected_matrix,
        iterations=iterations,
        converged=True,
        dual_objective=best_objective,
        prior_to_projected_kl=_kl_divergence(best_probabilities, flat_prior),
        projected_market_probabilities=best_projected,
        error_code=None,
    )


def constraint_probabilities(
    probabilities: tuple[tuple[Decimal, ...], ...],
    constraints: tuple[MarketConstraint, ...],
) -> tuple[Decimal, ...]:
    if not probabilities or not probabilities[0]:
        raise ValueError("score matrix is empty")
    home_max = len(probabilities) - 1
    away_max = len(probabilities[0]) - 1
    if any(len(row) != away_max + 1 for row in probabilities):
        raise ValueError("score matrix rows have inconsistent width")
    design = build_design_matrix(
        constraints,
        home_max=home_max,
        away_max=away_max,
    )
    return _market_probabilities(design, _flatten(probabilities))


__all__ = ["ProjectionResult", "constraint_probabilities", "project_to_markets"]
