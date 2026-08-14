from decimal import Decimal, localcontext

import pytest

from dmf_pulse.football_events.score_grid import build_adaptive_score_grid

pytestmark = pytest.mark.unit


def _grid(home: str, away: str, maximum: int = 18):
    return build_adaptive_score_grid(
        Decimal(home),
        Decimal(away),
        minimum_max_goals=6,
        maximum_max_goals=maximum,
        tail_tolerance=Decimal("0.0000000001"),
        hard_tail_limit=Decimal("0.00000001"),
    )


def test_joint_grid_is_positive_and_normalized() -> None:
    grid = _grid("1.8", "0.9")
    assert grid.home_max >= 6
    assert grid.away_max >= 6
    assert all(value > 0 for row in grid.probabilities for value in row)
    assert sum((sum(row, Decimal(0)) for row in grid.probabilities), Decimal(0)) == Decimal(1)
    assert grid.omitted_tail_mass <= Decimal("0.0000000001")


def test_joint_grid_residual_is_exact_for_property_regression() -> None:
    grid = _grid("0", "1.4")
    with localcontext() as context:
        context.prec = 120
        assert sum(grid.flattened(), Decimal(0)) == Decimal(1)


def test_larger_support_preserves_low_score_probability() -> None:
    small = _grid("1.4", "1.1", maximum=16)
    large = _grid("1.4", "1.1", maximum=18)
    assert abs(small.probabilities[1][1] - large.probabilities[1][1]) < Decimal("1e-20")


def test_hard_tail_limit_fails_closed() -> None:
    with pytest.raises(ValueError, match="hard_tail_limit"):
        build_adaptive_score_grid(
            Decimal("8"),
            Decimal("8"),
            minimum_max_goals=2,
            maximum_max_goals=3,
            tail_tolerance=Decimal("0.0001"),
            hard_tail_limit=Decimal("0.001"),
        )


def test_configured_maximum_prior_rate_fits_hard_tail_limit() -> None:
    grid = _grid("8", "8", maximum=36)
    assert grid.home_max <= 36
    assert grid.away_max <= 36
    assert grid.omitted_tail_mass <= Decimal("0.0000000001")


def test_unrepresented_tail_above_configured_tolerance_fails_closed() -> None:
    with pytest.raises(ValueError, match="tail_tolerance"):
        build_adaptive_score_grid(
            Decimal("8"),
            Decimal("8"),
            minimum_max_goals=2,
            maximum_max_goals=10,
            tail_tolerance=Decimal("0.000000000000000001"),
            hard_tail_limit=Decimal("1"),
        )
