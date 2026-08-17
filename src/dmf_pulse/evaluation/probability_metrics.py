"""Proper probability scoring with explicit boundary semantics."""

from __future__ import annotations

from decimal import Decimal, localcontext

from dmf_pulse.evaluation.models import (
    MulticlassProbabilityMetricResult,
    Probability,
    ProbabilityBoundaryPolicy,
    ProbabilityMetricResult,
)


def _validated_probability(value: Decimal) -> Decimal:
    if not value.is_finite() or not Decimal(0) <= value <= Decimal(1):
        raise ValueError("probabilities must be finite and lie in [0, 1]")
    return value


def _effective_probability(
    value: Decimal,
    *,
    boundary_policy: ProbabilityBoundaryPolicy,
    epsilon: Decimal | None,
) -> Decimal:
    value = _validated_probability(value)
    if boundary_policy is ProbabilityBoundaryPolicy.EXACT:
        if epsilon is not None:
            raise ValueError("EXACT boundary policy cannot declare epsilon")
        return value
    if epsilon is None or not epsilon.is_finite() or not Decimal(0) < epsilon < Decimal("0.5"):
        raise ValueError("DECLARED_EPSILON requires epsilon in (0, 0.5)")
    return min(max(value, epsilon), Decimal(1) - epsilon)


def score_probabilities(
    probabilities: tuple[Probability, ...],
    outcomes: tuple[int, ...],
    *,
    boundary_policy: ProbabilityBoundaryPolicy = ProbabilityBoundaryPolicy.EXACT,
    epsilon: Decimal | None = None,
) -> ProbabilityMetricResult:
    """Calculate binary Brier/log loss; exact impossible events remain unbounded."""

    if not probabilities or len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes require the same nonzero length")
    if any(isinstance(item, bool) or item not in {0, 1} for item in outcomes):
        raise ValueError("binary outcomes must be zero or one")
    raw_probabilities = tuple(_validated_probability(Decimal(item)) for item in probabilities)
    count = Decimal(len(probabilities))
    brier = (
        sum(
            (probability - Decimal(outcome)) ** 2
            for probability, outcome in zip(raw_probabilities, outcomes, strict=True)
        )
        / count
    )
    losses: list[Decimal] = []
    for raw, outcome in zip(raw_probabilities, outcomes, strict=True):
        probability = _effective_probability(
            Decimal(raw),
            boundary_policy=boundary_policy,
            epsilon=epsilon,
        )
        if (outcome == 1 and probability == 0) or (outcome == 0 and probability == 1):
            return ProbabilityMetricResult(
                brier_score=brier,
                log_loss=None,
                status="UNBOUNDED",
                boundary_policy=boundary_policy,
                epsilon=epsilon,
                count=len(probabilities),
            )
        with localcontext() as context:
            context.prec = 50
            likelihood = probability if outcome == 1 else Decimal(1) - probability
            losses.append(-likelihood.ln())
    return ProbabilityMetricResult(
        brier_score=brier,
        log_loss=sum(losses, Decimal(0)) / count,
        status="FINITE",
        boundary_policy=boundary_policy,
        epsilon=epsilon,
        count=len(probabilities),
    )


def multiclass_brier(
    probability_vectors: tuple[tuple[Probability, ...], ...],
    observed_indices: tuple[int, ...],
) -> Decimal:
    if not probability_vectors or len(probability_vectors) != len(observed_indices):
        raise ValueError("multiclass forecasts and outcomes require equal nonzero length")
    widths = {len(row) for row in probability_vectors}
    if len(widths) != 1 or next(iter(widths)) < 2:
        raise ValueError("multiclass probability vectors require one common width of at least two")
    width = next(iter(widths))
    validated = tuple(
        tuple(_validated_probability(Decimal(item)) for item in row) for row in probability_vectors
    )
    total = Decimal(0)
    for raw, observed in zip(validated, observed_indices, strict=True):
        if sum(raw, Decimal(0)) != Decimal(1):
            raise ValueError("multiclass probabilities must sum exactly to one")
        if isinstance(observed, bool) or not 0 <= observed < width:
            raise ValueError("observed class index is outside forecast support")
        total += sum(
            (probability - Decimal(index == observed)) ** 2 for index, probability in enumerate(raw)
        )
    return total / Decimal(len(probability_vectors))


def score_multiclass_probabilities(
    probability_vectors: tuple[tuple[Probability, ...], ...],
    observed_indices: tuple[int, ...],
    *,
    boundary_policy: ProbabilityBoundaryPolicy = ProbabilityBoundaryPolicy.EXACT,
    epsilon: Decimal | None = None,
) -> MulticlassProbabilityMetricResult:
    """Calculate complete-vector multiclass Brier and logarithmic scores."""

    if not probability_vectors or len(probability_vectors) != len(observed_indices):
        raise ValueError("multiclass forecasts and outcomes require equal nonzero length")
    widths = {len(row) for row in probability_vectors}
    if len(widths) != 1 or next(iter(widths)) < 2:
        raise ValueError("multiclass probability vectors require one common width of at least two")
    width = next(iter(widths))
    validated = tuple(
        tuple(_validated_probability(Decimal(item)) for item in row) for row in probability_vectors
    )
    brier_rows: list[Decimal] = []
    for raw, observed in zip(validated, observed_indices, strict=True):
        if sum(raw, Decimal(0)) != Decimal(1):
            raise ValueError("multiclass probabilities must sum exactly to one")
        if isinstance(observed, bool) or not 0 <= observed < width:
            raise ValueError("observed class index is outside forecast support")
        brier_rows.append(
            sum(
                (
                    (probability - Decimal(index == observed)) ** 2
                    for index, probability in enumerate(raw)
                ),
                Decimal(0),
            )
        )
    brier = sum(brier_rows, Decimal(0)) / Decimal(len(brier_rows))
    log_losses: list[Decimal] = []
    for raw, observed in zip(validated, observed_indices, strict=True):
        if boundary_policy is ProbabilityBoundaryPolicy.EXACT:
            if epsilon is not None:
                raise ValueError("EXACT boundary policy cannot declare epsilon")
            effective = raw
        else:
            if (
                epsilon is None
                or not epsilon.is_finite()
                or not Decimal(0) < epsilon < Decimal(1) / Decimal(width)
            ):
                raise ValueError("DECLARED_EPSILON requires epsilon in (0, 1 / class_count)")
            clipped = tuple(max(item, epsilon) for item in raw)
            total = sum(clipped, Decimal(0))
            effective = tuple(item / total for item in clipped)
        likelihood = effective[observed]
        if likelihood == 0:
            return MulticlassProbabilityMetricResult(
                brier_score=brier,
                log_loss=None,
                status="UNBOUNDED",
                boundary_policy=boundary_policy,
                epsilon=epsilon,
                count=len(probability_vectors),
                class_count=width,
            )
        with localcontext() as context:
            context.prec = 50
            log_losses.append(-likelihood.ln())
    return MulticlassProbabilityMetricResult(
        brier_score=brier,
        log_loss=sum(log_losses, Decimal(0)) / Decimal(len(log_losses)),
        status="FINITE",
        boundary_policy=boundary_policy,
        epsilon=epsilon,
        count=len(probability_vectors),
        class_count=width,
    )
