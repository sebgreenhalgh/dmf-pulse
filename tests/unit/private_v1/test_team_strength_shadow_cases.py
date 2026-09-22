"""Five locked cases, all through real Stage 7/8/9/10/11, zero network."""

from decimal import Decimal
from time import perf_counter

import pytest

from dmf_pulse.private_v1.team_strength_comparison import (
    TeamStrengthComparisonRun,
    run_team_strength_shadow_comparison,
)
from dmf_pulse.private_v1.team_strength_shadow_inputs import prepare_team_strength_shadow
from tests.unit.private_v1.team_strength_case_support import CASES, assert_case, case_prepared
from tests.unit.private_v1.team_strength_shadow_support import (
    synthetic_model_prepared,
    synthetic_strength,
)


@pytest.fixture(scope="module")
def frozen_model_preparation(repository_root, tmp_path_factory):
    started = perf_counter()
    prepared = synthetic_model_prepared(repository_root, tmp_path_factory.mktemp("001p-cases"))
    return prepared, Decimal(str((perf_counter() - started) * 1000))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_locked_real_canonical_case(frozen_model_preparation, case):
    prepared, elapsed = frozen_model_preparation
    prepared = case_prepared(prepared, case)
    dataset, artifact = synthetic_strength(case.source_variant)
    preparation = prepare_team_strength_shadow(
        prepared.rolling_execution,
        artifact=artifact,
        expected_artifact_sha256=artifact.semantic_sha256,
        fixture_registry=dataset.fixture_registry,
    )
    # Exercise world-order isolation in a real acceptance case as well.
    order = (
        ("TEAM_STRENGTH_SHADOW", "LEAGUE_BASELINE")
        if case.name == "A_ROBUST"
        else ("LEAGUE_BASELINE", "TEAM_STRENGTH_SHADOW")
    )
    result = run_team_strength_shadow_comparison(
        prepared, preparation, preparation_ms=elapsed, _world_order=order
    )
    assert isinstance(result, TeamStrengthComparisonRun)
    assert_case(case, result.comparison)
