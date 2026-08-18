from __future__ import annotations

from decimal import Decimal

import pytest

from dmf_pulse.prices.classifier import predict_no_change
from dmf_pulse.prices.latent_pressure import initial_latent_pressure
from dmf_pulse.prices.models import PriceEvent, PriceMass, PricePmf, PriceProbabilityVector
from dmf_pulse.prices.price_paths import simulate_price_paths
from dmf_pulse.prices.selling_value import (
    build_optimiser_price_scenarios,
    selling_value_distribution,
)
from tests.prices_helpers import BASE, config, selling_rule, spell

pytestmark = pytest.mark.unit


def _state():
    return initial_latent_pressure(
        state_id="state", player_id="player-1", as_of=BASE, config=config()
    )


def _small_config(*, maximum_exact_scenarios: int = 27):
    policy = config().price_paths.model_copy(
        update={
            "updates_24h": 1,
            "updates_72h": 2,
            "updates_7d": 3,
            "maximum_exact_scenarios": maximum_exact_scenarios,
        }
    )
    return config().model_copy(update={"price_paths": policy})


def test_complete_recurrent_path_distribution_is_deterministic_and_integer() -> None:
    probabilities = PriceProbabilityVector(
        probability_fall=Decimal("0.2"),
        probability_no_change=Decimal("0.5"),
        probability_rise=Decimal("0.3"),
    )
    first = simulate_price_paths(
        current_price_units=75,
        state=_state(),
        baseline=probabilities,
        config=_small_config(),
        model_lineage=("p2", "p1"),
    )
    second = simulate_price_paths(
        current_price_units=75,
        state=_state(),
        baseline=probabilities,
        config=_small_config(),
        model_lineage=("p1", "p2"),
    )
    assert first == second
    assert len(first.scenarios_7d) == 27
    assert sum((item.probability for item in first.scenarios_7d), Decimal(0)) == 1
    assert all(isinstance(price, int) for item in first.scenarios_7d for price in item.prices_units)
    assert any(item.events[:2] == (PriceEvent.RISE, PriceEvent.FALL) for item in first.scenarios_7d)
    assert first.probability_multiple_rises_gameweek > 0
    assert first.probability_multiple_falls_gameweek > 0
    for horizon in first.horizons:
        assert horizon.expected_price_units == horizon.price_pmf.expected_price_units


def test_legal_price_boundaries_move_impossible_mass_to_no_change() -> None:
    probabilities = PriceProbabilityVector(
        probability_fall=Decimal("0.4"),
        probability_no_change=Decimal("0.2"),
        probability_rise=Decimal("0.4"),
    )
    lower = simulate_price_paths(
        current_price_units=config().price_paths.minimum_price_units,
        state=_state(),
        baseline=probabilities,
        config=_small_config(),
        model_lineage=("p2",),
    )
    upper = simulate_price_paths(
        current_price_units=config().price_paths.maximum_price_units,
        state=_state(),
        baseline=probabilities,
        config=_small_config(),
        model_lineage=("p2",),
    )
    assert min(m.price_units for m in lower.horizons[-1].price_pmf.support) >= 1
    assert max(m.price_units for m in upper.horizons[-1].price_pmf.support) <= 200


def test_recurrent_hazard_keeps_change_possible_from_p0_and_invalid_caps_fail() -> None:
    values = simulate_price_paths(
        current_price_units=75,
        state=_state(),
        baseline=predict_no_change(),
        config=_small_config(),
        model_lineage=("p0",),
    )
    assert len(values.scenarios_7d) == 27
    assert values.probability_multiple_rises_gameweek > 0
    assert values.probability_multiple_falls_gameweek > 0
    with pytest.raises(ValueError, match="configured cap"):
        simulate_price_paths(
            current_price_units=75,
            state=_state(),
            baseline=PriceProbabilityVector(
                probability_fall=Decimal("0.2"),
                probability_no_change=Decimal("0.5"),
                probability_rise=Decimal("0.3"),
            ),
            config=_small_config(maximum_exact_scenarios=2),
            model_lineage=("p2",),
        )
    with pytest.raises(ValueError, match="outside configured legal support"):
        simulate_price_paths(
            current_price_units=0,
            state=_state(),
            baseline=predict_no_change(),
            config=_small_config(),
            model_lineage=("p0",),
        )


def test_stage11_selling_value_is_exact_across_profit_and_loss_paths() -> None:
    market = PricePmf(
        support=(
            PriceMass(price_units=48, probability=Decimal("0.2")),
            PriceMass(price_units=54, probability=Decimal("0.3")),
            PriceMass(price_units=55, probability=Decimal("0.5")),
        )
    )
    selling = selling_value_distribution(spell(purchase=50), market, rule=selling_rule())
    assert tuple((item.price_units, item.probability) for item in selling.support) == (
        (48, Decimal("0.2")),
        (52, Decimal("0.8")),
    )


def test_repurchase_uses_new_cohort_purchase_price() -> None:
    market = PricePmf(support=(PriceMass(price_units=55, probability=Decimal(1)),))
    old_cohort = selling_value_distribution(
        spell(purchase=50, spell_id="old"), market, rule=selling_rule()
    )
    repurchased = selling_value_distribution(
        spell(purchase=53, spell_id="repurchased"), market, rule=selling_rule()
    )
    assert old_cohort.support[0].price_units == 52
    assert repurchased.support[0].price_units == 54


def test_optimiser_scenarios_preserve_exact_affordability_branches() -> None:
    market = PricePmf(
        support=(
            PriceMass(price_units=75, probability=Decimal("0.6")),
            PriceMass(price_units=76, probability=Decimal("0.4")),
        )
    )
    scenarios = build_optimiser_price_scenarios(
        player_id="player-1",
        horizon="24h",
        market_price_pmf=market,
        maximum_support=2,
        route_budget_units=75,
    )
    assert tuple(item.route_affordable for item in scenarios.scenarios) == (True, False)
    with pytest.raises(ValueError, match="exceeds exact bounded"):
        build_optimiser_price_scenarios(
            player_id="player-1",
            horizon="24h",
            market_price_pmf=market,
            maximum_support=1,
        )
    with pytest.raises(ValueError, match="supplied together"):
        build_optimiser_price_scenarios(
            player_id="player-1",
            horizon="24h",
            market_price_pmf=market,
            maximum_support=2,
            ownership_spell=spell(),
        )
