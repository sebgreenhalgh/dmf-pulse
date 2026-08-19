from __future__ import annotations

from time import perf_counter

import pytest

from dmf_pulse.chips.artifacts import seal_decision_artifact, verify_decision_artifact
from dmf_pulse.chips.service import evaluate_chip_opportunities
from tests.support.stage14_chip_fixtures import service_request

pytestmark = pytest.mark.performance


def test_four_chip_service_and_artifact_validation_complete_within_smoke_budget() -> None:
    request = service_request(
        keys=("TRIPLE_CAPTAIN", "BENCH_BOOST", "FREE_HIT", "WILDCARD"),
        current_values={
            "TRIPLE_CAPTAIN": (6.0, 5.0),
            "BENCH_BOOST": (3.0, 2.0),
            "FREE_HIT": (8.0, 7.0),
            "WILDCARD": (4.0, 4.0),
        },
        future_values={
            "TRIPLE_CAPTAIN": (7.0, 7.0),
            "BENCH_BOOST": (5.0, 5.0),
            "FREE_HIT": (2.0, 2.0),
            "WILDCARD": (6.0, 6.0),
        },
    )

    started = perf_counter()
    for _ in range(25):
        decision = evaluate_chip_opportunities(request)
    artifact = seal_decision_artifact(request, decision)
    verify_decision_artifact(artifact)
    elapsed = perf_counter() - started

    assert elapsed < 5.0
