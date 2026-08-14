from decimal import Decimal, localcontext

import pytest

from dmf_pulse.football_events.poisson import (
    adaptive_poisson_support,
    poisson_pmf,
    poisson_tail_mass,
)

pytestmark = pytest.mark.unit


def test_zero_rate_is_degenerate_at_zero() -> None:
    assert poisson_pmf(Decimal(0), 4) == (
        Decimal(1),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
    )
    assert poisson_tail_mass(Decimal(0), 4) == Decimal(0)


def test_unit_rate_recurrence_and_tail() -> None:
    pmf = poisson_pmf(Decimal(1), 3)
    assert pmf[1] == pmf[0]
    with localcontext() as context:
        context.prec = 60
        assert abs(pmf[2] * 2 - pmf[1]) < Decimal("1e-58")
        assert abs(pmf[3] * 3 - pmf[2]) < Decimal("1e-58")
        assert poisson_tail_mass(Decimal(1), 3) == Decimal(1) - sum(pmf, Decimal(0))


def test_adaptive_support_respects_tolerance() -> None:
    maximum, pmf, tail = adaptive_poisson_support(
        Decimal("2.25"),
        minimum_max_goals=4,
        maximum_max_goals=18,
        tail_tolerance=Decimal("0.00000000005"),
    )
    assert 4 < maximum <= 18
    assert len(pmf) == maximum + 1
    assert tail <= Decimal("0.00000000005")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1])
def test_binary_float_or_negative_rate_is_rejected(bad: float) -> None:
    with pytest.raises(ValueError):
        poisson_pmf(bad, 5)  # type: ignore[arg-type]
