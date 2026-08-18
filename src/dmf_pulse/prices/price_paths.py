"""Exact bounded recurrent market-price path construction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Literal, cast

from dmf_pulse.prices.artifacts import seal_path_distribution
from dmf_pulse.prices.configuration import PriceConfig
from dmf_pulse.prices.latent_pressure import transition_after_price_event
from dmf_pulse.prices.models import (
    HorizonPriceDistribution,
    LatentPressureState,
    PriceEvent,
    PriceMass,
    PricePathDistribution,
    PricePathScenario,
    PricePmf,
    PriceProbabilityVector,
)
from dmf_pulse.prices.recurrent_hazard import predict_recurrent_hazard


@dataclass(frozen=True)
class _Path:
    events: tuple[Literal[PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE], ...]
    prices: tuple[int, ...]
    probability: Decimal
    state: LatentPressureState


def _bounded_probabilities(
    probabilities: PriceProbabilityVector,
    *,
    price_units: int,
    minimum: int,
    maximum: int,
) -> PriceProbabilityVector:
    fall = probabilities.probability_fall
    no_change = probabilities.probability_no_change
    rise = probabilities.probability_rise
    if price_units <= minimum:
        no_change += fall
        fall = Decimal(0)
    if price_units >= maximum:
        no_change += rise
        rise = Decimal(0)
    return PriceProbabilityVector(
        probability_fall=fall,
        probability_no_change=no_change,
        probability_rise=rise,
    )


def _normalized(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    total = sum(values, Decimal(0))
    if total <= 0:
        raise ValueError("probability distribution contains no mass")
    normalized = [value / total for value in values]
    normalized[-1] = Decimal(1) - sum(normalized[:-1], Decimal(0))
    return tuple(normalized)


def _price_pmf(paths: tuple[_Path, ...]) -> PricePmf:
    masses: dict[int, Decimal] = {}
    for path in paths:
        masses[path.prices[-1]] = masses.get(path.prices[-1], Decimal(0)) + path.probability
    ordered = tuple(sorted(masses.items()))
    probabilities = _normalized(tuple(value for _, value in ordered))
    return PricePmf(
        support=tuple(
            PriceMass(price_units=price, probability=probability)
            for (price, _), probability in zip(ordered, probabilities, strict=True)
        )
    )


def _horizon(
    label: str,
    paths: tuple[_Path, ...],
    update_count: int,
) -> HorizonPriceDistribution:
    pmf = _price_pmf(paths)
    total = sum((item.probability for item in paths), Decimal(0))
    any_rise = (
        sum((item.probability for item in paths if PriceEvent.RISE in item.events), Decimal(0))
        / total
    )
    any_fall = (
        sum((item.probability for item in paths if PriceEvent.FALL in item.events), Decimal(0))
        / total
    )
    return HorizonPriceDistribution(
        horizon=cast(Literal["24h", "72h", "7d"], label),
        update_count=update_count,
        price_pmf=pmf,
        expected_price_units=pmf.expected_price_units,
        probability_any_rise=any_rise,
        probability_any_fall=any_fall,
    )


def simulate_price_paths(
    *,
    current_price_units: int,
    state: LatentPressureState,
    baseline: PriceProbabilityVector,
    config: PriceConfig,
    model_lineage: tuple[str, ...],
) -> PricePathDistribution:
    """Enumerate every configured recurrent path and recompute hazard after each event."""

    policy = config.price_paths
    if not policy.minimum_price_units <= current_price_units <= policy.maximum_price_units:
        raise ValueError("current price lies outside configured legal support")
    paths: tuple[_Path, ...] = (
        _Path(events=(), prices=(current_price_units,), probability=Decimal(1), state=state),
    )
    horizons: dict[int, tuple[_Path, ...]] = {}
    event_order: tuple[
        Literal[PriceEvent.FALL],
        Literal[PriceEvent.NO_CHANGE],
        Literal[PriceEvent.RISE],
    ] = (PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE)
    for update in range(1, policy.updates_7d + 1):
        next_paths: list[_Path] = []
        for ordinal, path in enumerate(paths):
            probabilities = _bounded_probabilities(
                predict_recurrent_hazard(path.state, config=config, baseline=baseline),
                price_units=path.prices[-1],
                minimum=policy.minimum_price_units,
                maximum=policy.maximum_price_units,
            )
            event_probabilities = (
                probabilities.probability_fall,
                probabilities.probability_no_change,
                probabilities.probability_rise,
            )
            for event, event_probability in zip(event_order, event_probabilities, strict=True):
                if event_probability == 0:
                    continue
                price = path.prices[-1]
                if event is PriceEvent.FALL:
                    price -= policy.price_step_units
                elif event is PriceEvent.RISE:
                    price += policy.price_step_units
                next_state = transition_after_price_event(
                    path.state,
                    event,
                    state_id=f"{state.state_id}:u{update}:p{ordinal}:{event.value}",
                    as_of=state.as_of + timedelta(days=update),
                    config=config,
                )
                next_paths.append(
                    _Path(
                        events=(*path.events, event),
                        prices=(*path.prices, price),
                        probability=path.probability * event_probability,
                        state=next_state,
                    )
                )
        paths = tuple(next_paths)
        if len(paths) > policy.maximum_exact_scenarios:
            raise ValueError("exact price path count exceeds configured cap")
        if update in {policy.updates_24h, policy.updates_72h, policy.updates_7d}:
            horizons[update] = paths
    horizon_values = (
        _horizon("24h", horizons[policy.updates_24h], policy.updates_24h),
        _horizon("72h", horizons[policy.updates_72h], policy.updates_72h),
        _horizon("7d", horizons[policy.updates_7d], policy.updates_7d),
    )
    path_probabilities = _normalized(tuple(item.probability for item in paths))
    scenarios = tuple(
        PricePathScenario(
            events=path.events,
            prices_units=path.prices,
            probability=probability,
        )
        for path, probability in zip(paths, path_probabilities, strict=True)
    )
    multiple_rises = sum(
        (item.probability for item in scenarios if item.events.count(PriceEvent.RISE) >= 2),
        Decimal(0),
    )
    multiple_falls = sum(
        (item.probability for item in scenarios if item.events.count(PriceEvent.FALL) >= 2),
        Decimal(0),
    )
    value = PricePathDistribution(
        current_price_units=current_price_units,
        information_cutoff=state.as_of,
        horizons=horizon_values,
        scenarios_7d=scenarios,
        probability_multiple_rises_gameweek=multiple_rises,
        probability_multiple_falls_gameweek=multiple_falls,
        deterministic_seed=policy.deterministic_seed,
        model_lineage=tuple(sorted(set(model_lineage))),
        distribution_sha256="0" * 64,
    )
    return seal_path_distribution(value)
