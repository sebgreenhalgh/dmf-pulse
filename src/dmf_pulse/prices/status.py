"""Time-safe status transition features without folklore protection rules."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from dmf_pulse.prices.configuration import TransferFeaturePolicy
from dmf_pulse.prices.models import PriceObservation


def status_features(
    previous: PriceObservation | None,
    current: PriceObservation,
    *,
    cutoff: datetime,
    policy: TransferFeaturePolicy,
) -> tuple[str, Decimal, Decimal]:
    if previous is None:
        transition = f"INITIAL->{current.player_status.value}"
    else:
        transition = f"{previous.player_status.value}->{current.player_status.value}"
    elapsed_seconds = Decimal(str((cutoff - current.status_observed_at).total_seconds()))
    if elapsed_seconds < 0:
        raise ValueError("status observation cannot follow the feature cutoff")
    status_age_hours = elapsed_seconds / Decimal(3600)
    uncertainty = policy.status_uncertainty[current.player_status.value]
    return transition, status_age_hours, uncertainty
