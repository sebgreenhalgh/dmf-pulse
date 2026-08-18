"""Stage-11 selling-value reuse and bounded discrete price scenarios."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, cast

from dmf_pulse.optimisation.manager_state import OwnershipSpell, selling_price_tenths
from dmf_pulse.optimisation.multi_gameweek_models import SellingPriceRule
from dmf_pulse.prices.models import (
    OptimiserPriceScenario,
    PriceMass,
    PricePmf,
    PriceScenarioSet,
)


def selling_value_distribution(
    spell: OwnershipSpell,
    market_price_pmf: PricePmf,
    *,
    rule: SellingPriceRule,
) -> PricePmf:
    """Map market-price branches through Stage 11's accepted integer rule."""

    if not spell.active:
        raise ValueError("selling-value paths require the active ownership spell")
    masses: dict[int, Decimal] = {}
    for item in market_price_pmf.support:
        selling = selling_price_tenths(
            purchase_price_tenths=spell.purchase_price_tenths,
            current_price_tenths=item.price_units,
            rule=rule,
        )
        masses[selling] = masses.get(selling, Decimal(0)) + item.probability
    ordered = tuple(sorted(masses.items()))
    probabilities = [value for _, value in ordered]
    probabilities[-1] = Decimal(1) - sum(probabilities[:-1], Decimal(0))
    return PricePmf(
        support=tuple(
            PriceMass(price_units=price, probability=probability)
            for (price, _), probability in zip(ordered, probabilities, strict=True)
        )
    )


def build_optimiser_price_scenarios(
    *,
    player_id: str,
    horizon: str,
    market_price_pmf: PricePmf,
    maximum_support: int,
    ownership_spell: OwnershipSpell | None = None,
    selling_price_rule: SellingPriceRule | None = None,
    route_budget_units: int | None = None,
) -> PriceScenarioSet:
    """Expose exact legal price branches; reject rather than average excess support."""

    if len(market_price_pmf.support) > maximum_support:
        raise ValueError("price PMF exceeds exact bounded Stage-11 scenario support")
    if (ownership_spell is None) != (selling_price_rule is None):
        raise ValueError("ownership spell and selling rule must be supplied together")
    if ownership_spell is not None:
        if not ownership_spell.active:
            raise ValueError("optimiser price scenarios require the active ownership spell")
        if ownership_spell.player_id != player_id:
            raise ValueError(
                "optimiser price scenarios and ownership spell must refer to same player"
            )
    scenarios = tuple(
        OptimiserPriceScenario(
            scenario_id=f"{player_id}:{horizon}:{item.price_units}",
            probability=item.probability,
            player_id=player_id,
            market_price_units=item.price_units,
            selling_price_units=(
                selling_price_tenths(
                    purchase_price_tenths=ownership_spell.purchase_price_tenths,
                    current_price_tenths=item.price_units,
                    rule=selling_price_rule,
                )
                if ownership_spell is not None and selling_price_rule is not None
                else None
            ),
            route_affordable=(
                item.price_units <= route_budget_units if route_budget_units is not None else None
            ),
        )
        for item in market_price_pmf.support
    )
    return PriceScenarioSet(
        horizon=cast(Literal["24h", "72h", "7d"], horizon),
        focus_player_ids=(player_id,),
        scenarios=scenarios,
    )
