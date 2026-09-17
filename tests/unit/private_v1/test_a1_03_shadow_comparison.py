"""R9C-A1.03: four isolated worlds use the real canonical rolling service."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.private_v1.shadow_comparison import (
    FourWorldShadowComparison,
    _pair,
    _seal_world_result,
    run_four_world_shadow_comparison,
)
from tests.unit.private_v1.a1_03_support import build_a1_03_inputs


@pytest.fixture(scope="module")
def comparison(tmp_path_factory: pytest.TempPathFactory) -> FourWorldShadowComparison:
    execution, shadow = build_a1_03_inputs(Path.cwd(), tmp_path_factory.mktemp("a1-03"))
    return run_four_world_shadow_comparison(execution, shadow)


def test_four_world_comparison_preserves_stage7_stage8_and_scenario_alignment(
    comparison: FourWorldShadowComparison,
) -> None:
    assert comparison.stage7_stage8_equal is True
    assert comparison.model_input_status == "SHADOW_NOT_MODEL_INPUT"
    assert comparison.production_activation is False
    assert comparison.new_network_requests == 0
    assert comparison.persistence_performed is False
    assert tuple(item.world for item in comparison.results) == (
        "STALE",
        "CENTRAL_TEMPORARY",
        "LOW_SHRINKAGE",
        "HIGH_SHRINKAGE",
    )
    assert len(comparison.pairs) == 6
    assert all(item.candidate_screen_node_count > 0 for item in comparison.results)
    assert comparison.semantic_sha256


def test_pair_classification_distinguishes_root_and_continuation_sensitivity(
    comparison: FourWorldShadowComparison,
) -> None:
    stale = comparison.results[0]
    robust = replace(stale, world="CENTRAL_TEMPORARY")
    root_sensitive = replace(
        stale,
        world="LOW_SHRINKAGE",
        decision_signature=replace(stale.decision_signature, root_action_signature="a" * 64),
    )
    continuation_sensitive = replace(
        stale,
        world="HIGH_SHRINKAGE",
        decision_signature=replace(
            stale.decision_signature,
            by_gameweek_action_signatures=(
                stale.decision_signature.by_gameweek_action_signatures[0],
                "b" * 64,
                stale.decision_signature.by_gameweek_action_signatures[2],
            ),
        ),
    )

    assert _pair(stale, robust).classification == "ROBUST"
    assert _pair(stale, root_sensitive).classification == "ROOT_SENSITIVE"
    assert _pair(stale, continuation_sensitive).classification == "CONTINUATION_SENSITIVE"
    assert (
        _seal_world_result(
            replace(stale, timing_ms_by_stage=(("diagnostic", Decimal(0)),), semantic_sha256="")
        ).semantic_sha256
        == stale.semantic_sha256
    )
