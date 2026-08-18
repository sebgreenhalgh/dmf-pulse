"""Ownership-pool features with explicit denominator uncertainty."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from dmf_pulse.prices.configuration import TransferFeaturePolicy
from dmf_pulse.prices.models import OwnershipRegime


def ownership_regime(
    ownership_percent: Decimal,
    *,
    policy: TransferFeaturePolicy,
) -> OwnershipRegime:
    if ownership_percent < policy.low_ownership_percent:
        return OwnershipRegime.LOW
    if ownership_percent >= policy.high_ownership_percent:
        return OwnershipRegime.HIGH
    return OwnershipRegime.MEDIUM


def ownership_adjusted_rates(
    *,
    ownership_percent: Decimal,
    active_manager_count: int | None,
    buys: int,
    sells: int,
    policy: TransferFeaturePolicy,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None, Decimal]:
    """Return owner/nonowner pools, separate rates and denominator uncertainty."""

    if active_manager_count is None:
        return (None, None, None, None, policy.unknown_denominator_uncertainty)
    managers = Decimal(active_manager_count)
    owners = managers * ownership_percent / Decimal(100)
    nonowners = managers - owners
    floor = Decimal(policy.denominator_floor)
    buy_rate = Decimal(buys) / max(nonowners, floor)
    sell_rate = Decimal(sells) / max(owners, floor)
    return (
        owners,
        nonowners,
        buy_rate,
        sell_rate,
        policy.rounded_ownership_uncertainty,
    )


def global_activity_features(
    *,
    gross_increment: int,
    global_transfer_activity: int | None,
    policy: TransferFeaturePolicy,
) -> tuple[Decimal | None, Literal["LOW", "NORMAL", "HIGH", "UNKNOWN"]]:
    if global_transfer_activity is None or global_transfer_activity <= 0:
        return None, "UNKNOWN"
    share = Decimal(gross_increment) / Decimal(global_transfer_activity)
    regime: Literal["LOW", "NORMAL", "HIGH", "UNKNOWN"]
    if global_transfer_activity < policy.low_global_transfer_activity:
        regime = "LOW"
    elif global_transfer_activity > policy.high_global_transfer_activity:
        regime = "HIGH"
    else:
        regime = "NORMAL"
    return share, regime
