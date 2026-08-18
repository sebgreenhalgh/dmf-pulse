"""Auditable deterministic latent-pressure state transitions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, cast

from dmf_pulse.prices.configuration import PriceConfig
from dmf_pulse.prices.models import (
    ChipContaminationState,
    LatentPressureState,
    PriceEvent,
    TransferFlowFeatures,
    require_utc,
)


def initial_latent_pressure(
    *,
    state_id: str,
    player_id: str,
    as_of: datetime,
    config: PriceConfig,
) -> LatentPressureState:
    return LatentPressureState(
        state_id=state_id,
        player_id=player_id,
        as_of=require_utc(as_of, field_name="as_of"),
        rise_pressure=Decimal(0),
        fall_pressure=Decimal(0),
        uncertainty=config.recurrent_pressure.uncertainty_floor,
        previous_event=PriceEvent.NO_CHANGE,
        updates_since_rise=0,
        updates_since_fall=0,
        updates_since_any_change=0,
        rises_this_gameweek=0,
        falls_this_gameweek=0,
        state_version=config.recurrent_pressure.state_version,
    )


def update_latent_pressure(
    previous: LatentPressureState,
    features: TransferFlowFeatures,
    *,
    observed_event: PriceEvent = PriceEvent.NO_CHANGE,
    state_id: str,
    config: PriceConfig,
) -> LatentPressureState:
    """Update separate rise/fall pressure and apply explicit post-event reset behavior."""

    if observed_event not in {PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE}:
        raise ValueError("latent pressure can advance only with a modeled event")
    if features.player_id != previous.player_id:
        raise ValueError("pressure state and flow features refer to different players")
    if features.information_cutoff < previous.as_of:
        raise ValueError("latent pressure cannot move backward in time")
    policy = config.recurrent_pressure
    rise_flow = Decimal(max(features.net_increment, 0)) * policy.flow_scale
    fall_flow = Decimal(max(-features.net_increment, 0)) * policy.flow_scale
    rise_rate = (features.buy_rate_nonowners or Decimal(0)) * policy.ownership_rate_scale
    fall_rate = (features.sell_rate_owners or Decimal(0)) * policy.ownership_rate_scale
    momentum = features.short_long_momentum * policy.momentum_scale
    rise = (
        policy.persistence * previous.rise_pressure
        + rise_flow
        + rise_rate
        + max(momentum, Decimal(0))
    )
    fall = (
        policy.persistence * previous.fall_pressure
        + fall_flow
        + fall_rate
        + max(-momentum, Decimal(0))
    )
    if observed_event is PriceEvent.RISE:
        rise *= policy.event_reset_retention
        fall *= policy.opposite_direction_retention
    elif observed_event is PriceEvent.FALL:
        fall *= policy.event_reset_retention
        rise *= policy.opposite_direction_retention
    uncertainty = max(
        policy.uncertainty_floor,
        features.denominator_uncertainty
        + features.status_uncertainty
        + config.transfer_features.chip_uncertainty[features.chip_contamination]
        * (Decimal(1) - features.chip_contamination_confidence),
    )
    if features.chip_contamination is ChipContaminationState.UNKNOWN:
        uncertainty += policy.uncertainty_missing_chip_increment
    return LatentPressureState(
        state_id=state_id,
        player_id=previous.player_id,
        as_of=features.information_cutoff,
        rise_pressure=rise,
        fall_pressure=fall,
        uncertainty=uncertainty,
        previous_event=cast(
            Literal[PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE], observed_event
        ),
        updates_since_rise=0
        if observed_event is PriceEvent.RISE
        else previous.updates_since_rise + 1,
        updates_since_fall=0
        if observed_event is PriceEvent.FALL
        else previous.updates_since_fall + 1,
        updates_since_any_change=(
            previous.updates_since_any_change + 1 if observed_event is PriceEvent.NO_CHANGE else 0
        ),
        rises_this_gameweek=previous.rises_this_gameweek + int(observed_event is PriceEvent.RISE),
        falls_this_gameweek=previous.falls_this_gameweek + int(observed_event is PriceEvent.FALL),
        state_version=policy.state_version,
    )


def transition_after_price_event(
    previous: LatentPressureState,
    event: PriceEvent,
    *,
    state_id: str,
    as_of: datetime,
    config: PriceConfig,
) -> LatentPressureState:
    """Advance a simulated recurrent state without inventing future transfer observations."""

    if event not in {PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE}:
        raise ValueError("simulated state requires a modeled event")
    as_of = require_utc(as_of, field_name="as_of")
    if as_of < previous.as_of:
        raise ValueError("recurrent price state cannot move backward in time")
    policy = config.recurrent_pressure
    rise = previous.rise_pressure * policy.persistence
    fall = previous.fall_pressure * policy.persistence
    if event is PriceEvent.RISE:
        rise *= policy.event_reset_retention
        fall *= policy.opposite_direction_retention
    elif event is PriceEvent.FALL:
        fall *= policy.event_reset_retention
        rise *= policy.opposite_direction_retention
    return LatentPressureState(
        state_id=state_id,
        player_id=previous.player_id,
        as_of=as_of,
        rise_pressure=rise,
        fall_pressure=fall,
        uncertainty=previous.uncertainty,
        previous_event=cast(Literal[PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE], event),
        updates_since_rise=0 if event is PriceEvent.RISE else previous.updates_since_rise + 1,
        updates_since_fall=0 if event is PriceEvent.FALL else previous.updates_since_fall + 1,
        updates_since_any_change=(
            previous.updates_since_any_change + 1 if event is PriceEvent.NO_CHANGE else 0
        ),
        rises_this_gameweek=previous.rises_this_gameweek + int(event is PriceEvent.RISE),
        falls_this_gameweek=previous.falls_this_gameweek + int(event is PriceEvent.FALL),
        state_version=policy.state_version,
    )
