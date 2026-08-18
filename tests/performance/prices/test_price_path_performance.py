from __future__ import annotations

import json
from time import perf_counter

import pytest

from dmf_pulse.prices.service import PriceService

pytestmark = pytest.mark.performance


def test_full_2187_path_replay_completes_within_smoke_budget(repository_root) -> None:
    payload = json.loads(
        (repository_root / "fixtures/prices/simulate_path.json").read_text(encoding="utf-8")
    )
    started = perf_counter()
    value = PriceService().simulate(payload)
    elapsed = perf_counter() - started
    assert len(value.scenarios_7d) == 2187
    assert elapsed < 5
