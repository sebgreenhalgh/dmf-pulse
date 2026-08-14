from __future__ import annotations

import time

from dmf_pulse.fpl_points.service import FplPointsService
from tests.support.factories import make_request, mc_policy, reference_engine


def test_1000_scenario_smoke_completes_within_generous_local_budget() -> None:
    started = time.perf_counter()
    result = FplPointsService(reference_engine(), mc_policy()).project(
        make_request(scenario_count=1000, root_seed=909)
    )
    elapsed = time.perf_counter() - started
    assert result.status.value == "SUCCESS"
    assert len(result.scenarios) == 1000
    assert elapsed < 20.0
