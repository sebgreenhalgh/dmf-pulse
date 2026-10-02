"""Independent finite-distribution oracle and malformed input checks."""

from decimal import Decimal, localcontext

import pytest

from dmf_pulse.evaluation.team_strength_mixture_analysis import (
    compare_distributions,
    distribution_features,
)


def test_disjoint_point_masses_have_known_divergence_and_movement():
    left = ((Decimal(1),),)
    right = ((Decimal(0), Decimal(1)),)
    movement = compare_distributions(left, right)
    reverse = compare_distributions(right, left)
    assert (
        movement.exact_score_total_variation == movement.exact_score_max_probability_movement == 1
    )
    with localcontext() as context:
        context.prec = 60
        assert abs(movement.exact_score_jensen_shannon - Decimal(2).ln()) < Decimal("1e-58")
    assert reverse.exact_score_jensen_shannon == movement.exact_score_jensen_shannon
    assert dict(movement.metric_deltas)["away_expected_goals"] == 1
    assert dict(reverse.metric_deltas)["away_expected_goals"] == -1
    assert compare_distributions(left, left).exact_score_jensen_shannon == 0


@pytest.mark.parametrize(
    "matrix",
    [
        (),
        ((),),
        ((Decimal(1),), (Decimal(0), Decimal(0))),
        ((Decimal("NaN"),),),
        ((Decimal(-1),),),
        ((Decimal("0.9"),),),
    ],
)
def test_invalid_distribution_inputs_fail(matrix):
    with pytest.raises(ValueError):
        distribution_features(matrix)
