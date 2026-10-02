"""Market and prior-only research mixtures use unchanged Stage-8 constraints."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.football_events.service import ScoreDistributionService
from dmf_pulse.football_events.team_strength_mixture_stage8 import (
    ParameterMixtureStage8V1,
    project_parameter_mixture,
)
from dmf_pulse.football_events.team_strength_parameter_draws import (
    ParameterMixtureUnavailable,
    draw_policy,
    joint_parameter_draws,
)
from tests.unit.football_events.team_strength_support import synthetic_artifact
from tests.unit.football_events.test_team_strength_adapter import bundle, stage8_request


@pytest.mark.parametrize("market", [False, True])
def test_mixture_stage8_golden_and_same_constraints(market):
    artifact = synthetic_artifact()
    bound = bundle()
    request = stage8_request(bound, market=market)
    before = request.model_dump_json()
    ordinary = ScoreDistributionService().project(request)
    draws = joint_parameter_draws(artifact, policy=draw_policy(seed=23, draw_count=16))
    result = project_parameter_mixture(
        request,
        artifact=artifact,
        draws=draws,
        fixture=bound.fixture,
        expected_artifact_sha256=artifact.semantic_sha256,
    )
    assert ParameterMixtureStage8V1.model_validate_json(result.model_dump_json()) == result
    assert request.model_dump_json() == before
    assert ScoreDistributionService().project(request) == ordinary
    assert result.research_only and not result.production_active
    assert result.diagnostics.projection_status == ("PROJECTED" if market else "PRIOR_ONLY")
    assert result.probabilities != ordinary.distribution.probabilities
    assert tuple(
        (row.constraint_id, row.target_probability, row.weight) for row in result.market_residuals
    ) == tuple(
        (row.constraint_id, row.target_probability, row.weight)
        for row in ordinary.distribution.market_residuals
    )
    golden = json.loads(
        Path("evidence/tickets/CURRENT-TEAM-STRENGTH-001U/STAGE8-GOLDEN.json").read_text()
    )
    assert result.semantic_sha256 == golden[str(market)]["semantic_sha256"]
    assert result.expected_home_goals == golden[str(market)]["expected_home_goals"]
    assert result.expected_away_goals == golden[str(market)]["expected_away_goals"]


@pytest.mark.parametrize("market", [False, True])
def test_zero_scale_reduces_exactly_to_plugin_outputs(market):
    artifact = synthetic_artifact()
    bound = bundle()
    request = stage8_request(bound, market=market)
    ordinary = ScoreDistributionService().project(request).distribution
    draws = joint_parameter_draws(
        artifact, policy=draw_policy(seed=23, draw_count=2, scale=Decimal(0))
    )
    result = project_parameter_mixture(
        request,
        artifact=artifact,
        draws=draws,
        fixture=bound.fixture,
        expected_artifact_sha256=artifact.semantic_sha256,
    )
    assert result.probabilities == ordinary.probabilities
    assert result.one_x_two == ordinary.one_x_two
    assert result.total_goals == ordinary.total_goals
    assert result.clean_sheets == ordinary.clean_sheets
    assert result.expected_home_goals == ordinary.expected_home_goals


def test_unavailable_mixture_is_typed_failure_without_plugin_fallback():
    artifact = synthetic_artifact()
    bound = bundle()
    with pytest.raises(ParameterMixtureUnavailable) as caught:
        project_parameter_mixture(
            stage8_request(bound, market=False),
            artifact=artifact,
            draws=None,
            fixture=bound.fixture,
            expected_artifact_sha256=artifact.semantic_sha256,
        )
    assert caught.value.code == "PARAMETER_MIXTURE_UNAVAILABLE"
