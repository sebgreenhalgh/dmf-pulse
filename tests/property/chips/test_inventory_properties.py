from __future__ import annotations

import pytest

from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import (
    TokenStatus,
    activate_token,
    advance_inventory,
    build_chip_inventory,
)


def test_advancement_is_idempotent_at_same_gameweek(make_definition, make_bundle) -> None:
    for gameweek in range(1, 11):
        bundle = make_bundle(make_definition("IDEMPOTENT", start=1, end=10))
        inventory = build_chip_inventory(bundle, current_gameweek=gameweek)
        assert advance_inventory(inventory, to_gameweek=gameweek) == inventory


def test_expiry_monotonicity(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("MONOTONE", start=2, end=5))
    inventory = build_chip_inventory(bundle, current_gameweek=1)
    statuses = []
    for gameweek in range(1, 9):
        inventory = advance_inventory(inventory, to_gameweek=gameweek)
        statuses.append(inventory.token("MONOTONE:window-1:1").status)
    assert statuses[:1] == [TokenStatus.UNAVAILABLE]
    assert TokenStatus.AVAILABLE in statuses
    first_expired = statuses.index(TokenStatus.EXPIRED)
    assert all(status == TokenStatus.EXPIRED for status in statuses[first_expired:])


def test_active_interval_never_allows_second_token_under_limit_one(
    make_definition, make_bundle
) -> None:
    for duration in range(1, 5):
        bundle = make_bundle(
            make_definition("A", duration=duration),
            make_definition("B", duration=duration),
            concurrency_limit=1,
        )
        inventory = build_chip_inventory(bundle, current_gameweek=2)
        active = activate_token(inventory, bundle, token_id="A:window-1:1")
        with pytest.raises(ChipError):
            activate_token(active, bundle, token_id="B:window-1:1")


def test_same_semantic_transition_reproduces_hash(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("HASH", duration=2))
    first = build_chip_inventory(bundle, current_gameweek=2)
    second = build_chip_inventory(bundle, current_gameweek=2)
    first = advance_inventory(
        activate_token(first, bundle, token_id="HASH:window-1:1"),
        to_gameweek=5,
    )
    second = advance_inventory(
        activate_token(second, bundle, token_id="HASH:window-1:1"),
        to_gameweek=5,
    )
    assert first.inventory_hash == second.inventory_hash
    assert first == second
