from __future__ import annotations

from typing import Any

import pytest

from dmf_pulse.chips.compiler import compile_synthetic_bundle
from dmf_pulse.chips.definitions import ActivationRoute, ChipDefinition, ChipEffect, InventoryGrant

RULESET_HASH = "1" * 64


def definition(
    key: str,
    *,
    start: int = 1,
    end: int = 10,
    acquired: int | None = None,
    copies: int = 1,
    duration: int = 1,
    group: str = "SQUAD_CHIP",
    effect: tuple[str, str, dict[str, Any]] = ("SCORING", "ADD_POINTS", {"points": 1}),
    cancellable: bool = True,
    route: ActivationRoute = ActivationRoute.PICK_TEAM_SAVE,
    minimum_gap: int = 0,
    excluded: tuple[int, ...] = (),
) -> ChipDefinition:
    return ChipDefinition(
        chip_key=key,
        definition_version=f"SYNTHETIC:{key}:V1",
        grants=(
            InventoryGrant(
                grant_id="window-1",
                copies=copies,
                acquired_gameweek=acquired or start,
                activation_start_gameweek=start,
                activation_end_gameweek=end,
                expires_after_gameweek=end,
            ),
        ),
        duration_gameweeks=duration,
        concurrency_group=group,
        activation_route=route,
        cancellable_before_lock=cancellable,
        lock_after_confirmed_transfer_count=(
            1 if route == ActivationRoute.CONFIRMED_TRANSFERS else None
        ),
        excluded_gameweeks=excluded,
        minimum_gap_gameweeks=minimum_gap,
        effects=(ChipEffect(surface=effect[0], operation=effect[1], parameters=effect[2]),),
    )


def bundle(*definitions: ChipDefinition, concurrency_limit: int = 1):
    return compile_synthetic_bundle(
        ruleset_id="SYNTHETIC-CHIP-RULESET",
        ruleset_version="1.0",
        ruleset_hash=RULESET_HASH,
        concurrency_limit=concurrency_limit,
        definitions=tuple(definitions),
    )


@pytest.fixture
def make_definition():
    return definition


@pytest.fixture
def make_bundle():
    return bundle
