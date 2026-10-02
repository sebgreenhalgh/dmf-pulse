"""Joint covariance, reproducibility, ordering and fail-closed uncertainty tests."""

import math
from decimal import Decimal, localcontext

import pytest

from dmf_pulse.football_events.team_strength_model import parameter_order
from dmf_pulse.football_events.team_strength_numerics import reconstruct
from dmf_pulse.football_events.team_strength_parameter_draws import (
    ParameterDrawSetV1,
    ParameterMixtureUnavailable,
    covariance_factor,
    draw_policy,
    joint_parameter_draws,
    normal_vector,
    outcome_identity,
    unpack_triangle,
)
from tests.unit.football_events.team_strength_support import synthetic_artifact


def test_joint_draws_reproducible_serialized_and_identified():
    artifact = synthetic_artifact()
    policy = draw_policy(seed=17, draw_count=16)
    first = joint_parameter_draws(artifact, policy=policy)
    assert first == joint_parameter_draws(artifact, policy=policy)
    assert ParameterDrawSetV1.model_validate_json(first.model_dump_json()) == first
    assert first.parameter_order == parameter_order(first.teams)
    assert len(first.parameter_order) == 2 * len(first.teams)
    assert first.fit_artifact_sha256 == artifact.semantic_sha256
    assert first.model_sha256 == artifact.model.semantic_sha256
    assert first.draws[0] != first.draws[1]
    n = len(first.teams)
    for row in first.draws:
        beta = tuple(float(x) for x in row.free_parameters)
        assert abs(math.fsum(reconstruct(beta[2 : n + 1]))) < 1e-12
        assert abs(math.fsum(reconstruct(beta[n + 1 :]))) < 1e-12
    identity = outcome_identity(first, parameter_index=0, outcome_draw_id="outcome-7")
    assert identity.parameter_draw_id == first.draws[0].parameter_draw_id
    assert identity.outcome_draw_id == "outcome-7"
    assert identity.structural_world_id == first.structural_world_id


def test_zero_scale_preserves_plugin_free_vector():
    artifact = synthetic_artifact()
    draws = joint_parameter_draws(
        artifact, policy=draw_policy(seed=7, draw_count=2, scale=Decimal(0))
    )
    expected = (
        artifact.model.mu,
        artifact.model.global_home_effect,
        *(row.attack for row in artifact.model.effects[:-1]),
        *(row.defence for row in artifact.model.effects[:-1]),
    )
    assert all(row.free_parameters == expected for row in draws.draws)


@pytest.mark.parametrize("count", [3, 11, 13])
def test_non_power_of_two_weights_and_ambient_context_reproducibility(count):
    artifact = synthetic_artifact()
    policy = draw_policy(seed=23, draw_count=count)
    expected = joint_parameter_draws(artifact, policy=policy)
    with localcontext() as context:
        context.prec = 6
        assert joint_parameter_draws(artifact, policy=policy) == expected
    with localcontext() as context:
        context.prec = 120
        assert sum((row.draw_weight for row in expected.draws), Decimal(0)) == 1


def test_full_covariance_factor_and_empirical_joint_covariance():
    target = ((1.0, 0.7), (0.7, 2.0))
    factor = covariance_factor(target)
    assert all(
        abs(math.fsum(factor[i][k] * factor[j][k] for k in range(2)) - target[i][j]) < 1e-12
        for i in range(2)
        for j in range(2)
    )
    samples = [
        tuple(math.fsum(factor[i][k] * z[k] for k in range(2)) for i in range(2))
        for z in (normal_vector(22, index, 2) for index in range(16384))
    ]
    means = tuple(math.fsum(row[i] for row in samples) / len(samples) for i in range(2))
    for i in range(2):
        for j in range(2):
            empirical = math.fsum(
                (row[i] - means[i]) * (row[j] - means[j]) for row in samples
            ) / len(samples)
            assert abs(empirical - target[i][j]) < 0.04


def test_zero_covariance_and_exact_singular_psd():
    assert covariance_factor(((0.0, 0.0), (0.0, 0.0))) == ((0.0, 0.0), (0.0, 0.0))
    assert covariance_factor(((1.0, 1.0), (1.0, 1.0))) == ((1.0, 0.0), (1.0, 0.0))


@pytest.mark.parametrize(
    "matrix",
    [
        (),
        ((1.0,), (0.0, 1.0)),
        ((float("nan"),),),
        ((float("inf"),),),
        ((1.0, 0.5), (0.1, 1.0)),
        ((1.0, 2.0), (2.0, 1.0)),
        ((-0.0001,),),
        ((0.0, 1.0), (1.0, 1.0)),
    ],
)
def test_malformed_nonfinite_asymmetric_non_psd_fail(matrix):
    with pytest.raises(ParameterMixtureUnavailable):
        covariance_factor(matrix)


def test_only_documented_tiny_asymmetry_is_normalized():
    covariance_factor(((1.0, 0.5), (0.5 + 1e-13, 1.0)))


def test_triangle_dimension_and_finiteness():
    with pytest.raises(ParameterMixtureUnavailable):
        unpack_triangle((Decimal(1),), 2)
    with pytest.raises(ParameterMixtureUnavailable):
        unpack_triangle((Decimal("NaN"),), 1)


def test_counter_normal_prefixes_and_seed_independence():
    assert normal_vector(1, 0, 3) == normal_vector(1, 0, 4)[:3]
    assert normal_vector(1, 0, 3) != normal_vector(2, 0, 3)


def test_rehashed_wrong_covariance_and_order_are_rejected():
    artifact = synthetic_artifact()
    from dmf_pulse.ingestion.openfootball.team_strength_data import seal

    uncertainty = artifact.model.uncertainty.model_copy(
        update={"covariance": tuple(x * 2 for x in artifact.model.uncertainty.covariance)}
    )
    values = {
        name: getattr(artifact.model, name)
        for name in type(artifact.model).model_fields
        if name != "semantic_sha256"
    }
    values["uncertainty"] = uncertainty
    model = seal(type(artifact.model), **values)
    corrupt = seal(
        type(artifact), model=model, fitted_at=artifact.fitted_at, usable_at=artifact.usable_at
    )
    with pytest.raises(ParameterMixtureUnavailable, match="information inverse"):
        joint_parameter_draws(corrupt, policy=draw_policy(seed=0, draw_count=2))
    values["uncertainty"] = artifact.model.uncertainty.model_copy(
        update={"parameter_order": tuple(reversed(artifact.model.uncertainty.parameter_order))}
    )
    with pytest.raises(ValueError, match="ordering"):
        seal(type(artifact.model), **values)
