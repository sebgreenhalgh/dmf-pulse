from datetime import UTC, datetime
from decimal import Decimal

import pytest

from dmf_pulse.football_events.market_constraints import MarketConstraintSet
from dmf_pulse.football_events.score_prior import build_score_prior
from dmf_pulse.football_events.score_projection import (
    _reshape,
    _solve_linear_system,
    constraint_probabilities,
    project_to_markets,
)

pytestmark = pytest.mark.unit


def _prior():
    return build_score_prior(
        Decimal("1.2"),
        Decimal("0.9"),
        minimum_max_goals=6,
        maximum_max_goals=18,
        tail_tolerance=Decimal("1e-10"),
        hard_tail_limit=Decimal("1e-8"),
    )


def _empty():
    return MarketConstraintSet.model_validate(
        {"as_of": datetime(2026, 8, 20, 12, tzinfo=UTC), "constraints": ()}
    )


def test_empty_linear_system_and_pivoting() -> None:
    assert _solve_linear_system((), ()) == ()
    solution = _solve_linear_system(
        ((Decimal(0), Decimal(1)), (Decimal(1), Decimal(1))),
        (Decimal(1), Decimal(2)),
    )
    assert solution == (Decimal(1), Decimal(1))
    with pytest.raises(ArithmeticError, match="singular"):
        _solve_linear_system(
            ((Decimal(1), Decimal(1)), (Decimal(2), Decimal(2))),
            (Decimal(1), Decimal(2)),
        )


def test_projection_argument_boundaries_fail_closed() -> None:
    with pytest.raises(ValueError, match="max_iterations"):
        project_to_markets(
            _prior(),
            _empty(),
            max_iterations=0,
            gradient_tolerance=Decimal("1e-12"),
            line_search_min_step=Decimal("1e-6"),
            allow_prior_fallback=True,
        )
    with pytest.raises(ValueError, match="line_search_min_step"):
        project_to_markets(
            _prior(),
            _empty(),
            max_iterations=1,
            gradient_tolerance=Decimal("1e-12"),
            line_search_min_step=Decimal(1),
            allow_prior_fallback=True,
        )


def test_matrix_shape_validation() -> None:
    with pytest.raises(ValueError, match="support"):
        _reshape((Decimal(1),), home_max=1, away_max=1)
    with pytest.raises(ValueError, match="empty"):
        constraint_probabilities((), ())
    with pytest.raises(ValueError, match="inconsistent width"):
        constraint_probabilities(((Decimal(1),), (Decimal(0), Decimal(0))), ())
