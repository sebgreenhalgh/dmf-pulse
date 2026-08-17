"""Joint-distribution metrics that retain Stage-9 scenario dependence."""

from __future__ import annotations

from decimal import Decimal, localcontext

from dmf_pulse.evaluation.models import MultivariateMetricResult, Probability


def _validate_samples(
    samples: tuple[tuple[Decimal, ...], ...],
    observed: tuple[Decimal, ...],
) -> None:
    if not samples:
        raise ValueError("joint metrics require scenario samples")
    if not observed or any(len(sample) != len(observed) for sample in samples):
        raise ValueError("scenario and observed dimensions differ")
    if any(not value.is_finite() for sample in samples for value in sample) or any(
        not value.is_finite() for value in observed
    ):
        raise ValueError("scenario and observed values must be finite")


def _validated_weights(
    samples: tuple[tuple[Decimal, ...], ...],
    weights: tuple[Probability, ...] | None,
) -> tuple[Decimal, ...] | None:
    if weights is None:
        return None
    if len(weights) != len(samples):
        raise ValueError("scenario weights require one value per sample")
    values = tuple(Decimal(item) for item in weights)
    if any(not item.is_finite() or not Decimal(0) <= item <= Decimal(1) for item in values):
        raise ValueError("scenario probabilities must be finite and lie in [0, 1]")
    if sum(values, Decimal(0)) != Decimal(1):
        raise ValueError("scenario weights must sum exactly to one")
    return values


def _euclidean(left: tuple[Decimal, ...], right: tuple[Decimal, ...]) -> Decimal:
    if len(left) != len(right) or not left:
        raise ValueError("vectors require equal nonzero dimension")
    with localcontext() as context:
        context.prec = 50
        return sum(((a - b) ** 2 for a, b in zip(left, right, strict=True)), Decimal(0)).sqrt()


def energy_score(
    samples: tuple[tuple[Decimal, ...], ...],
    observed: tuple[Decimal, ...],
    *,
    weights: tuple[Probability, ...] | None = None,
) -> Decimal:
    """Calculate the empirical or explicitly weighted energy score."""

    _validate_samples(samples, observed)
    scenario_weights = _validated_weights(samples, weights)
    if scenario_weights is None:
        first = sum((_euclidean(sample, observed) for sample in samples), Decimal(0)) / Decimal(
            len(samples)
        )
        pairwise = sum(
            (_euclidean(left, right) for left in samples for right in samples),
            Decimal(0),
        ) / Decimal(len(samples) * len(samples))
    else:
        first = sum(
            (
                weight * _euclidean(sample, observed)
                for sample, weight in zip(samples, scenario_weights, strict=True)
            ),
            Decimal(0),
        )
        pairwise = sum(
            (
                left_weight * right_weight * _euclidean(left, right)
                for left, left_weight in zip(samples, scenario_weights, strict=True)
                for right, right_weight in zip(samples, scenario_weights, strict=True)
            ),
            Decimal(0),
        )
    return first - pairwise / Decimal(2)


def variogram_score(
    samples: tuple[tuple[Decimal, ...], ...],
    observed: tuple[Decimal, ...],
    *,
    power: Decimal = Decimal("0.5"),
    weights: tuple[Probability, ...] | None = None,
) -> Decimal:
    """Calculate the pairwise variogram score without marginalising scenarios."""

    if not power.is_finite() or not Decimal(0) < power <= Decimal(2):
        raise ValueError("variogram power must lie in (0, 2]")
    _validate_samples(samples, observed)
    if len(observed) < 2:
        raise ValueError("variogram score requires samples with at least two dimensions")
    scenario_weights = _validated_weights(samples, weights)
    score = Decimal(0)
    with localcontext() as context:
        context.prec = 50
        for left_index in range(len(observed)):
            for right_index in range(left_index + 1, len(observed)):
                observed_difference = abs(observed[left_index] - observed[right_index]) ** power
                if scenario_weights is None:
                    expected_difference = sum(
                        (
                            abs(sample[left_index] - sample[right_index]) ** power
                            for sample in samples
                        ),
                        Decimal(0),
                    ) / Decimal(len(samples))
                else:
                    expected_difference = sum(
                        (
                            weight * abs(sample[left_index] - sample[right_index]) ** power
                            for sample, weight in zip(samples, scenario_weights, strict=True)
                        ),
                        Decimal(0),
                    )
                score += (observed_difference - expected_difference) ** 2
    return score


def _covariance_matrix(
    samples: tuple[tuple[Decimal, ...], ...],
    *,
    weights: tuple[Probability, ...] | None = None,
) -> tuple[tuple[Decimal, ...], ...]:
    if len(samples) < 2:
        raise ValueError("covariance diagnostics require at least two scenarios")
    width = len(samples[0])
    if width == 0 or any(len(sample) != width for sample in samples):
        raise ValueError("scenario samples require fixed nonzero dimension")
    scenario_weights = _validated_weights(samples, weights)
    if scenario_weights is None:
        uniform = Decimal(1) / Decimal(len(samples))
        scenario_weights = tuple(uniform for _ in samples)
    means = tuple(
        sum(
            (
                weight * sample[index]
                for sample, weight in zip(samples, scenario_weights, strict=True)
            ),
            Decimal(0),
        )
        for index in range(width)
    )
    return tuple(
        tuple(
            sum(
                (
                    weight * (sample[left] - means[left]) * (sample[right] - means[right])
                    for sample, weight in zip(samples, scenario_weights, strict=True)
                ),
                Decimal(0),
            )
            for right in range(width)
        )
        for left in range(width)
    )


def score_multivariate(
    samples: tuple[tuple[Decimal, ...], ...],
    observed: tuple[Decimal, ...],
    *,
    reference_covariance: tuple[tuple[Decimal, ...], ...],
    joint_thresholds: tuple[Decimal, ...],
    weights: tuple[Probability, ...] | None = None,
) -> MultivariateMetricResult:
    """Score scenarios using their retained joint paths and optional Stage-9 weights."""

    _validate_samples(samples, observed)
    scenario_weights = _validated_weights(samples, weights)
    covariance = _covariance_matrix(samples, weights=weights)
    if len(reference_covariance) != len(covariance) or any(
        len(row) != len(covariance) for row in reference_covariance
    ):
        raise ValueError("reference covariance shape differs from scenario covariance")
    if any(not value.is_finite() for row in reference_covariance for value in row):
        raise ValueError("reference covariance values must be finite")
    covariance_error = sum(
        (
            (covariance[left][right] - reference_covariance[left][right]) ** 2
            for left in range(len(covariance))
            for right in range(len(covariance))
        ),
        Decimal(0),
    )
    if len(joint_thresholds) != len(observed):
        raise ValueError("joint thresholds require one threshold per dimension")
    if any(not value.is_finite() for value in joint_thresholds):
        raise ValueError("joint thresholds must be finite")
    indicators = tuple(
        Decimal(
            all(
                value >= threshold
                for value, threshold in zip(sample, joint_thresholds, strict=True)
            )
        )
        for sample in samples
    )
    if scenario_weights is None:
        predicted = sum(indicators, Decimal(0)) / Decimal(len(samples))
    else:
        predicted = sum(
            (
                weight * indicator
                for weight, indicator in zip(scenario_weights, indicators, strict=True)
            ),
            Decimal(0),
        )
    actual = Decimal(
        all(value >= threshold for value, threshold in zip(observed, joint_thresholds, strict=True))
    )
    return MultivariateMetricResult(
        energy_score=energy_score(samples, observed, weights=weights),
        variogram_score=variogram_score(samples, observed, weights=weights),
        covariance_error=covariance_error,
        joint_threshold_brier=(predicted - actual) ** 2,
        sample_count=len(samples),
    )
