from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.prices.classifier import predict_no_change
from dmf_pulse.prices.latent_pressure import initial_latent_pressure
from dmf_pulse.prices.models import LatentPressureState, PriceMass, PricePmf, PriceProbabilityVector
from dmf_pulse.prices.price_paths import simulate_price_paths
from dmf_pulse.prices.recurrent_hazard import predict_recurrent_hazard
from dmf_pulse.prices.selling_value import selling_value_distribution
from tests.prices_helpers import BASE, config, selling_rule, spell

pytestmark = pytest.mark.property


def _small_config():
    policy = config().price_paths.model_copy(
        update={
            "updates_24h": 1,
            "updates_72h": 2,
            "updates_7d": 3,
            "maximum_exact_scenarios": 27,
        }
    )
    return config().model_copy(update={"price_paths": policy})


@given(
    fall_weight=st.integers(min_value=1, max_value=1000),
    no_change_weight=st.integers(min_value=1, max_value=1000),
    rise_weight=st.integers(min_value=1, max_value=1000),
)
def test_probability_vector_is_a_closed_simplex(
    fall_weight: int, no_change_weight: int, rise_weight: int
) -> None:
    total = Decimal(fall_weight + no_change_weight + rise_weight)
    fall = Decimal(fall_weight) / total
    no_change = Decimal(no_change_weight) / total
    rise = Decimal(1) - (fall + no_change)
    value = PriceProbabilityVector(
        probability_fall=fall,
        probability_no_change=no_change,
        probability_rise=rise,
    )
    assert sum(
        (value.probability_fall, value.probability_no_change, value.probability_rise),
        Decimal(0),
    ) == Decimal(1)
    assert all(
        Decimal(0) <= item <= Decimal(1)
        for item in (
            value.probability_fall,
            value.probability_no_change,
            value.probability_rise,
        )
    )


@given(
    rise_pressure=st.integers(min_value=-50, max_value=100),
    fall_pressure=st.integers(min_value=-50, max_value=100),
    uncertainty=st.integers(min_value=1, max_value=20),
)
def test_recurrent_hazard_always_returns_proper_nonzero_competing_events(
    rise_pressure: int, fall_pressure: int, uncertainty: int
) -> None:
    initial = initial_latent_pressure(
        state_id="property", player_id="player-1", as_of=BASE, config=config()
    )
    state = initial.model_copy(
        update={
            "rise_pressure": Decimal(rise_pressure) / Decimal(10),
            "fall_pressure": Decimal(fall_pressure) / Decimal(10),
            "uncertainty": Decimal(uncertainty) / Decimal(10),
        }
    )
    value = predict_recurrent_hazard(state, config=config(), baseline=predict_no_change())
    assert value.probability_fall > 0
    assert value.probability_rise > 0
    assert value.probability_no_change > 0
    assert value.probability_fall + value.probability_no_change + value.probability_rise == 1


@given(current_price=st.integers(min_value=2, max_value=199))
def test_price_paths_are_integer_proper_and_expectation_reconciles(current_price: int) -> None:
    baseline = PriceProbabilityVector(
        probability_fall=Decimal("0.2"),
        probability_no_change=Decimal("0.5"),
        probability_rise=Decimal("0.3"),
    )
    state: LatentPressureState = initial_latent_pressure(
        state_id="path-property", player_id="player-1", as_of=BASE, config=config()
    )
    value = simulate_price_paths(
        current_price_units=current_price,
        state=state,
        baseline=baseline,
        config=_small_config(),
        model_lineage=("property",),
    )
    assert sum((item.probability for item in value.scenarios_7d), Decimal(0)) == 1
    for horizon in value.horizons:
        assert sum((item.probability for item in horizon.price_pmf.support), Decimal(0)) == 1
        assert horizon.expected_price_units == horizon.price_pmf.expected_price_units
        assert all(isinstance(item.price_units, int) for item in horizon.price_pmf.support)


@given(
    purchase=st.integers(min_value=1, max_value=150),
    current=st.integers(min_value=1, max_value=200),
)
def test_selling_distribution_matches_stage11_integer_rule(purchase: int, current: int) -> None:
    value = selling_value_distribution(
        spell(purchase=purchase, current=current),
        PricePmf(support=(PriceMass(price_units=current, probability=Decimal(1)),)),
        rule=selling_rule(),
    )
    expected = current if current <= purchase else purchase + (current - purchase) // 2
    assert value.support[0].price_units == expected
    assert value.support[0].probability == 1


@given(binary_float=st.floats(allow_nan=False, allow_infinity=False))
def test_public_probability_contract_never_accepts_binary_float(binary_float: float) -> None:
    with pytest.raises(ValueError, match="binary floats"):
        PriceProbabilityVector(
            probability_fall=binary_float,
            probability_no_change=Decimal(1),
            probability_rise=Decimal(0),
        )
