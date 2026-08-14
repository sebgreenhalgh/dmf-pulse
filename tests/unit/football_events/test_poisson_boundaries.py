from decimal import Decimal

import pytest

from dmf_pulse.football_events.poisson import adaptive_poisson_support, poisson_pmf

pytestmark = pytest.mark.unit


def test_poisson_support_argument_failures() -> None:
    with pytest.raises(ValueError, match="max_goals"):
        poisson_pmf(Decimal(1), -1)
    with pytest.raises(ValueError, match="minimum_max_goals"):
        adaptive_poisson_support(
            Decimal(1),
            minimum_max_goals=-1,
            maximum_max_goals=5,
            tail_tolerance=Decimal("0.01"),
        )
    with pytest.raises(ValueError, match="maximum_max_goals"):
        adaptive_poisson_support(
            Decimal(1),
            minimum_max_goals=5,
            maximum_max_goals=4,
            tail_tolerance=Decimal("0.01"),
        )


def test_support_returns_visible_tail_when_maximum_is_reached() -> None:
    maximum, pmf, tail = adaptive_poisson_support(
        Decimal(6),
        minimum_max_goals=2,
        maximum_max_goals=3,
        tail_tolerance=Decimal("0.000001"),
    )
    assert maximum == 3
    assert len(pmf) == 4
    assert tail > Decimal("0.1")
