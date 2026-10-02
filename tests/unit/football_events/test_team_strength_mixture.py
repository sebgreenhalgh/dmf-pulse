"""Coherent score mixtures and fixture-shared epistemic identities."""

from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from dmf_pulse.football_events.score_prior import build_score_prior
from dmf_pulse.football_events.service import load_score_baseline_policy
from dmf_pulse.football_events.team_strength_adapter import fixture_prior_bundle
from dmf_pulse.football_events.team_strength_mixture import (
    ParameterMixtureFixtureV1,
    build_parameter_mixture,
)
from dmf_pulse.football_events.team_strength_parameter_draws import (
    draw_policy,
    joint_parameter_draws,
)
from tests.unit.football_events.team_strength_support import synthetic_artifact, synthetic_dataset


def inputs(count=16, scale=Decimal(1)):
    artifact = synthetic_artifact()
    draws = joint_parameter_draws(
        artifact, policy=draw_policy(seed=23, draw_count=count, scale=scale)
    )
    fixtures = tuple(
        row
        for row in synthetic_dataset().fixture_registry.fixtures
        if row.season == artifact.model.forecast_season
    )
    return artifact, draws, fixtures


def mixture(artifact, draws, fixture):
    return build_parameter_mixture(
        artifact=artifact,
        draws=draws,
        fixture=fixture,
        as_of=artifact.usable_at + timedelta(seconds=1),
        expected_artifact_sha256=artifact.semantic_sha256,
    )


def test_mixture_normalization_weighted_moments_and_serialization():
    artifact, draws, fixtures = inputs()
    result = mixture(artifact, draws, fixtures[0])
    assert ParameterMixtureFixtureV1.model_validate_json(result.model_dump_json()) == result
    assert result.status == "SHADOW_NOT_MODEL_INPUT" and not result.production_active
    with localcontext() as context:
        context.prec = 120
        assert sum((p for row in result.probabilities for p in row), Decimal(0)) == 1
    assert result.epistemic_lambda_variance_home > 0
    assert (
        result.total_predictive_variance_home
        == result.weighted_lambda_home + result.epistemic_lambda_variance_home
    )
    assert result.home_truncation_mean_error < Decimal("1e-8")
    assert result.away_truncation_mean_error < Decimal("1e-8")
    assert result.omitted_tail_mass <= load_score_baseline_policy().grid.tail_tolerance


def test_zero_scale_is_exact_plugin_grid_with_separate_identity():
    artifact, draws, fixtures = inputs(scale=Decimal(0))
    result = mixture(artifact, draws, fixtures[0])
    bundle = fixture_prior_bundle(
        artifact=artifact,
        fixture=fixtures[0],
        as_of=result.as_of,
        expected_artifact_sha256=artifact.semantic_sha256,
    )
    policy = load_score_baseline_policy()
    plugin = build_score_prior(
        bundle.score_prior.home_goal_rate,
        bundle.score_prior.away_goal_rate,
        minimum_max_goals=policy.grid.minimum_max_goals,
        maximum_max_goals=policy.grid.maximum_max_goals,
        tail_tolerance=policy.grid.tail_tolerance,
        hard_tail_limit=policy.grid.hard_tail_limit,
    )
    assert result.score_prior().grid == plugin.grid
    assert result.semantic_sha256 != plugin.semantic_sha256
    assert result.epistemic_lambda_variance_home == result.epistemic_lambda_variance_away == 0


def test_one_joint_draw_index_reused_across_every_fixture():
    artifact, draws, fixtures = inputs()
    first, second = mixture(artifact, draws, fixtures[0]), mixture(artifact, draws, fixtures[1])
    assert tuple(row.parameter_draw_id for row in first.rates) == tuple(
        row.parameter_draw_id for row in second.rates
    )
    assert first.draw_set_sha256 == second.draw_set_sha256 == draws.semantic_sha256
    assert first.rates[0].lambda_home != second.rates[0].lambda_home
    assert mixture(artifact, draws, fixtures[0]) == first


def test_wrong_expected_fit_fails_closed():
    artifact, draws, fixtures = inputs()
    with pytest.raises(ValueError):
        build_parameter_mixture(
            artifact=artifact,
            draws=draws,
            fixture=fixtures[0],
            as_of=artifact.usable_at,
            expected_artifact_sha256="0" * 64,
        )
