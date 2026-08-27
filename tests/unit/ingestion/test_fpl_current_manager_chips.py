"""Configured chip-inventory reconciliation tests for CURRENT-FPL-STATE-001C."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from tests.unit.ingestion.current_manager_test_support import (
    CurrentManagerTestContext,
    build_context,
    compile_manager,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def context(repository_root: Path, tmp_path: Path) -> CurrentManagerTestContext:
    return build_context(repository_root, tmp_path)


def _token(value: dict[str, Any], prefix: str) -> dict[str, Any]:
    return next(item for item in value["chip_tokens"] if item["token_id"].startswith(prefix))


def _fails(context: CurrentManagerTestContext, value: object, code: str) -> None:
    with pytest.raises(IngestionError) as caught:
        compile_manager(context, value)
    assert caught.value.code == code


def test_pending_and_active_non_restoring_chips_reconcile_exactly(
    context: CurrentManagerTestContext,
) -> None:
    pending = deepcopy(context.declaration)
    pending_token = _token(pending, "BENCH_BOOST:window-1")
    pending_token.update({"status": "PENDING_CANCELLABLE", "selected_at_gameweek": 2})
    pending_bundle = compile_manager(context, pending, name="pending-chip.json")
    assert pending_bundle.selected_chip_token_id == pending_token["token_id"]
    assert pending_bundle.chip_inventory.token(pending_token["token_id"]).status.value == (
        "PENDING_CANCELLABLE"
    )

    active = deepcopy(context.declaration)
    active_token = _token(active, "TRIPLE_CAPTAIN:window-1")
    active_token.update({"status": "ACTIVE", "active_from_gameweek": 2})
    active_bundle = compile_manager(context, active, name="active-chip.json")
    assert active_bundle.selected_chip_token_id == active_token["token_id"]
    assert active_bundle.chip_inventory.token(active_token["token_id"]).status.value == "ACTIVE"


def test_prior_used_chip_reconstructs_through_the_accepted_inventory_engine(
    context: CurrentManagerTestContext,
) -> None:
    value = deepcopy(context.declaration)
    used = _token(value, "BENCH_BOOST:window-1")
    used.update({"status": "USED", "used_at_gameweek": 1})
    bundle = compile_manager(context, value)
    resolved = bundle.chip_inventory.token(used["token_id"])
    assert resolved.status.value == "USED"
    assert resolved.used_at_gameweek == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-token",
        "missing-copy",
        "duplicate-copy",
        "used-without-date",
        "available-with-date",
        "future-used-date",
        "impossible-window-status",
    ],
)
def test_invalid_chip_declarations_fail_closed(
    context: CurrentManagerTestContext,
    mutation: str,
) -> None:
    value = deepcopy(context.declaration)
    first = value["chip_tokens"][0]
    if mutation == "unknown-token":
        first["token_id"] = "UNKNOWN:window-1:1"
    elif mutation == "missing-copy":
        value["chip_tokens"].pop()
    elif mutation == "duplicate-copy":
        value["chip_tokens"][1] = deepcopy(first)
    elif mutation == "used-without-date":
        first["status"] = "USED"
    elif mutation == "available-with-date":
        first["selected_at_gameweek"] = 2
    elif mutation == "future-used-date":
        first.update({"status": "USED", "used_at_gameweek": 99})
    else:
        unavailable = _token(value, "BENCH_BOOST:window-2")
        unavailable.update({"status": "ACTIVE", "active_from_gameweek": 2})
    _fails(context, value, "VALIDATION_FAILED")


def test_simultaneous_chip_selection_is_rejected(
    context: CurrentManagerTestContext,
) -> None:
    value = deepcopy(context.declaration)
    for prefix in ("BENCH_BOOST:window-1", "TRIPLE_CAPTAIN:window-1"):
        _token(value, prefix).update({"status": "PENDING_CANCELLABLE", "selected_at_gameweek": 2})
    _fails(context, value, "VALIDATION_FAILED")


@pytest.mark.parametrize("status", ["PENDING_CANCELLABLE", "ACTIVE"])
def test_free_hit_without_restoration_state_is_explicitly_blocked(
    context: CurrentManagerTestContext,
    status: str,
) -> None:
    value = deepcopy(context.declaration)
    free_hit = _token(value, "FREE_HIT:window-1")
    if status == "PENDING_CANCELLABLE":
        free_hit.update({"status": status, "selected_at_gameweek": 2})
    else:
        free_hit.update({"status": status, "active_from_gameweek": 2})
    _fails(context, value, "USAGE_INVALID")
