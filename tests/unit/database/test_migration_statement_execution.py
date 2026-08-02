"""Offline migration statement-order and downgrade execution oracles."""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "module_name",
    (
        "20260723_0001_dat003_foundation",
        "20260724_0002_fpl004_ingestion",
        "20260725_0003_fpl_bundle_authority",
        "20260725_0004_odd005_market_observations",
    ),
)
def test_migration_upgrade_and_downgrade_execute_every_frozen_statement(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    module: ModuleType = importlib.import_module(
        f"dmf_pulse.database.migrations.versions.{module_name}"
    )
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append)

    module.upgrade()
    assert executed == list(module.UPGRADE_STATEMENTS)

    executed.clear()
    module.downgrade()
    assert executed == list(module.DOWNGRADE_STATEMENTS)
