from __future__ import annotations

from decimal import Decimal

import pytest

from dmf_pulse.evaluation.distribution_metrics import (
    discrete_quantile,
    interval_score,
    randomized_pit,
    ranked_probability_score,
    score_distribution,
)
from dmf_pulse.evaluation.multivariate_metrics import (
    energy_score,
    score_multivariate,
    variogram_score,
)

pytestmark = pytest.mark.unit

PMF = {Decimal(0): Decimal("0.2"), Decimal(1): Decimal("0.5"), Decimal(2): Decimal("0.3")}


def test_discrete_distribution_conventions_are_audited() -> None:
    assert discrete_quantile(PMF, Decimal("0.5")) == Decimal(1)
    assert ranked_probability_score(PMF, Decimal(1)) == Decimal("0.13")
    assert randomized_pit(PMF, Decimal(1), uniform_draw=Decimal("0.5")) == Decimal("0.45")
    scored = score_distribution(PMF, Decimal(1), central_coverage=Decimal("0.8"))
    assert scored.interval_coverage == Decimal(1)
    assert scored.interval_width == Decimal(2)
    assert scored.log_score is not None


def test_distribution_edge_cases_are_explicit() -> None:
    zero_mass = score_distribution(PMF, Decimal(3), central_coverage=Decimal("0.8"))
    assert zero_mass.log_score is None
    assert randomized_pit(PMF, Decimal(3), uniform_draw=Decimal("0.5")) == Decimal(1)
    with pytest.raises(ValueError, match="sum"):
        ranked_probability_score({Decimal(0): Decimal("0.9")}, Decimal(0))
    with pytest.raises(ValueError, match="lower"):
        interval_score(Decimal(2), Decimal(1), Decimal(0), miscoverage=Decimal("0.2"))
    assert interval_score(
        Decimal(1), Decimal(2), Decimal(0), miscoverage=Decimal("0.2")
    ) == Decimal(11)
    assert interval_score(
        Decimal(1), Decimal(2), Decimal(3), miscoverage=Decimal("0.2")
    ) == Decimal(11)
    with pytest.raises(ValueError, match="probabilities"):
        score_distribution(
            {Decimal(0): Decimal("-0.1"), Decimal(1): Decimal("1.1")},
            Decimal(0),
        )
    with pytest.raises(ValueError, match="uniform draw"):
        randomized_pit(PMF, Decimal(1), uniform_draw=Decimal("1.1"))
    with pytest.raises(ValueError, match="observed"):
        ranked_probability_score(PMF, Decimal("NaN"))


def test_joint_scores_preserve_scenario_dependence() -> None:
    samples = (
        (Decimal(0), Decimal(2)),
        (Decimal(1), Decimal(1)),
        (Decimal(2), Decimal(0)),
    )
    observed = (Decimal(1), Decimal(1))
    assert energy_score(samples, observed) >= 0
    assert variogram_score(samples, observed) >= 0
    covariance = Decimal(2) / Decimal(3)
    result = score_multivariate(
        samples,
        observed,
        reference_covariance=((covariance, -covariance), (-covariance, covariance)),
        joint_thresholds=(Decimal(1), Decimal(1)),
    )
    assert result.sample_count == 3
    assert result.covariance_error <= Decimal("1e-50")
    assert result.joint_threshold_brier == Decimal("0.4444444444444444444444444445")


def test_joint_metric_shapes_and_parameters_are_validated() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        energy_score(((Decimal(1),),), (Decimal(1), Decimal(2)))
    with pytest.raises(ValueError, match="power"):
        variogram_score(((Decimal(1), Decimal(2)),), (Decimal(1), Decimal(2)), power=Decimal(0))
    with pytest.raises(ValueError, match="at least two"):
        score_multivariate(
            ((Decimal(1), Decimal(2)),),
            (Decimal(1), Decimal(2)),
            reference_covariance=((Decimal(0), Decimal(0)), (Decimal(0), Decimal(0))),
            joint_thresholds=(Decimal(1), Decimal(1)),
        )


def test_distribution_log_score_boundary_and_weighted_joint_metrics_are_explicit() -> None:
    finite = score_distribution(PMF, Decimal(1))
    unbounded = score_distribution(PMF, Decimal(3))
    assert finite.log_score_status == "FINITE"
    assert unbounded.log_score_status == "UNBOUNDED"

    samples = ((Decimal(0), Decimal(0)), (Decimal(2), Decimal(2)))
    weights = (Decimal("0.75"), Decimal("0.25"))
    result = score_multivariate(
        samples,
        (Decimal(0), Decimal(0)),
        weights=weights,
        reference_covariance=(
            (Decimal("0.75"), Decimal("0.75")),
            (Decimal("0.75"), Decimal("0.75")),
        ),
        joint_thresholds=(Decimal(1), Decimal(1)),
    )
    assert result.covariance_error == Decimal(0)
    assert result.joint_threshold_brier == Decimal("0.0625")


def test_joint_metric_weights_are_validated() -> None:
    samples = ((Decimal(0), Decimal(0)), (Decimal(1), Decimal(1)))
    with pytest.raises(ValueError, match="one value"):
        energy_score(samples, (Decimal(0), Decimal(0)), weights=(Decimal(1),))
    with pytest.raises(ValueError, match="sum exactly"):
        variogram_score(
            samples,
            (Decimal(0), Decimal(0)),
            weights=(Decimal("0.4"), Decimal("0.4")),
        )
    with pytest.raises(ValueError, match="probabilities"):
        energy_score(
            samples,
            (Decimal(0), Decimal(0)),
            weights=(Decimal("-0.1"), Decimal("1.1")),
        )
    with pytest.raises(ValueError, match="power"):
        variogram_score(samples, (Decimal(0), Decimal(0)), power=Decimal("NaN"))


def test_explicit_uniform_weights_match_implicit_scenario_distribution() -> None:
    samples = ((Decimal(0), Decimal(0)), (Decimal(2), Decimal(2)))
    observed = (Decimal(1), Decimal(1))
    reference = ((Decimal(0), Decimal(0)), (Decimal(0), Decimal(0)))
    thresholds = (Decimal(1), Decimal(1))
    implicit = score_multivariate(
        samples,
        observed,
        reference_covariance=reference,
        joint_thresholds=thresholds,
    )
    explicit = score_multivariate(
        samples,
        observed,
        weights=(Decimal("0.5"), Decimal("0.5")),
        reference_covariance=reference,
        joint_thresholds=thresholds,
    )
    assert implicit == explicit
