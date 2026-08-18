from __future__ import annotations

import pytest

from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import (
    TokenEventKind,
    TokenStatus,
    activate_token,
    advance_inventory,
    available_token_ids,
    build_chip_inventory,
    cancel_token,
    select_token,
)


def test_multiple_copies_are_distinct_and_deterministic(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("MULTI", copies=2))
    first = build_chip_inventory(bundle, current_gameweek=1)
    second = build_chip_inventory(bundle, current_gameweek=1)
    assert available_token_ids(first) == ("MULTI:window-1:1", "MULTI:window-1:2")
    assert first == second
    assert first.inventory_hash == second.inventory_hash


def test_future_acquisition_cannot_activate_early(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("FUTURE", start=5, end=9, acquired=5))
    inventory = build_chip_inventory(bundle, current_gameweek=3)
    token = inventory.token("FUTURE:window-1:1")
    assert token.status == TokenStatus.UNAVAILABLE
    with pytest.raises(ChipError, match="not available") as exc:
        activate_token(inventory, bundle, token_id=token.token_id)
    assert exc.value.code == "CHIP_TOKEN_UNAVAILABLE"
    acquired = advance_inventory(inventory, to_gameweek=5)
    assert acquired.token(token.token_id).status == TokenStatus.AVAILABLE


def test_expired_chip_cannot_activate(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("EXPIRING", start=1, end=2))
    inventory = build_chip_inventory(bundle, current_gameweek=1)
    expired = advance_inventory(inventory, to_gameweek=3)
    assert expired.token("EXPIRING:window-1:1").status == TokenStatus.EXPIRED
    with pytest.raises(ChipError) as exc:
        activate_token(expired, bundle, token_id="EXPIRING:window-1:1")
    assert exc.value.code == "CHIP_TOKEN_UNAVAILABLE"


def test_cancellation_returns_token_without_consuming_copy(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("CANCEL"))
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    selected = select_token(inventory, bundle, token_id="CANCEL:window-1:1")
    assert selected.token("CANCEL:window-1:1").status == TokenStatus.PENDING_CANCELLABLE
    cancelled = cancel_token(selected, token_id="CANCEL:window-1:1")
    token = cancelled.token("CANCEL:window-1:1")
    assert token.status == TokenStatus.AVAILABLE
    assert token.history[-1].event == TokenEventKind.CANCELLED
    activated = activate_token(cancelled, bundle, token_id=token.token_id)
    assert activated.token(token.token_id).status == TokenStatus.ACTIVE


def test_consumed_chip_cannot_be_reused(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("ONCE", duration=1))
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    active = activate_token(inventory, bundle, token_id="ONCE:window-1:1")
    completed = advance_inventory(active, to_gameweek=3)
    token = completed.token("ONCE:window-1:1")
    assert token.status == TokenStatus.USED
    assert token.used_at_gameweek == 2
    with pytest.raises(ChipError) as exc:
        activate_token(completed, bundle, token_id=token.token_id)
    assert exc.value.code == "CHIP_TOKEN_UNAVAILABLE"


def test_multiweek_occupancy_blocks_conflicting_chip(make_definition, make_bundle) -> None:
    bundle = make_bundle(
        make_definition("LONG", duration=3, group="SQUAD_CHIP"),
        make_definition("OTHER", duration=1, group="SQUAD_CHIP"),
    )
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    active = activate_token(inventory, bundle, token_id="LONG:window-1:1")
    with pytest.raises(ChipError) as exc:
        activate_token(active, bundle, token_id="OTHER:window-1:1")
    assert exc.value.code in {"CHIP_CONCURRENCY_LIMIT", "CHIP_CONCURRENCY_GROUP"}
    after = advance_inventory(active, to_gameweek=5)
    activated = activate_token(after, bundle, token_id="OTHER:window-1:1")
    assert activated.token("OTHER:window-1:1").status == TokenStatus.ACTIVE


def test_unknown_effect_token_is_blocked(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("UNKNOWN", effect=("NEW", "MYSTERY", {})))
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    with pytest.raises(ChipError) as exc:
        activate_token(inventory, bundle, token_id="UNKNOWN:window-1:1")
    assert exc.value.code == "CHIP_EFFECT_BLOCKED"


def test_excluded_gameweek_is_enforced(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("EXCLUDED", excluded=(2,)))
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    with pytest.raises(ChipError) as exc:
        activate_token(inventory, bundle, token_id="EXCLUDED:window-1:1")
    assert exc.value.code == "CHIP_GAMEWEEK_EXCLUDED"
