"""Offline A1.01 guards around the private fixture-allocation injection seam."""

from __future__ import annotations

import inspect
from dataclasses import dataclass

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.player_prior import (
    bind_fixture_allocation_profiles,
    build_player_prior_identity_binding,
    load_packaged_player_prior,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.rolling import PrivateV1RollingRecommendationService
from dmf_pulse.private_v1.service import _FixtureAllocationResolution

from .e2e_test_support import build_rolling_execution_input

pytestmark = pytest.mark.unit


@dataclass(frozen=True, slots=True)
class _SyntheticShadowProvenance:
    semantic_sha256: str


def _resolver_for(
    execution,
    *,
    assist_multiplier: float = 1.0,
    malformed: str | None = None,
    calls: list | None = None,
):
    """Synthetic replacement using the same governed profiles, never provider I/O."""

    current = execution.current_execution
    prior = load_packaged_player_prior()

    def resolve(
        *,
        participant_ids,
        participation,
        source_player_map,
        source_team_map,
        **context,
    ):
        if calls is not None:
            calls.append((context["fixture_id"], frozenset(participant_ids)))
        binding = build_player_prior_identity_binding(
            prior,
            current.current_state.fpl_input,
            canonical_player_ids_by_source_id=source_player_map,
            canonical_team_ids_by_source_id=source_team_map,
        )
        profiles, _identity = bind_fixture_allocation_profiles(prior, binding, participation)
        if malformed == "missing":
            profiles = profiles[1:]
        elif malformed == "extra":
            profiles = (*profiles, profiles[0].model_copy(update={"player_id": "extra"}))
        elif malformed == "duplicate":
            profiles = (*profiles, profiles[0])
        elif malformed == "team":
            profiles = (
                profiles[0].model_copy(update={"team_id": "not-the-stage7-team"}),
                *profiles[1:],
            )
        elif assist_multiplier != 1.0:
            profiles = (
                profiles[0].model_copy(
                    update={"assist_share": profiles[0].assist_share * assist_multiplier}
                ),
                *profiles[1:],
            )
        resolution_sha256 = canonical_sha256(
            tuple(profile.model_dump(mode="json") for profile in profiles)
        )
        return _FixtureAllocationResolution(
            profiles=profiles,
            prior_identity=None,
            binding_sha256=resolution_sha256,
            fallback_player_ids=frozenset(),
            shadow_provenance=_SyntheticShadowProvenance(resolution_sha256),
        )

    return resolve


def test_a1_default_service_remains_deterministically_identical(repository_root, tmp_path) -> None:
    execution = build_rolling_execution_input(repository_root, tmp_path / "input")

    first = PrivateV1RollingRecommendationService().run(execution)
    second = PrivateV1RollingRecommendationService().run(execution)

    assert first.decision == second.decision
    assert first.optimiser_request == second.optimiser_request
    assert first.optimiser_result == second.optimiser_result
    assert first.decision.lineage.stage7_input_sha256_by_gameweek == (
        second.decision.lineage.stage7_input_sha256_by_gameweek
    )
    assert first.decision.lineage.stage8_distribution_sha256_by_gameweek == (
        second.decision.lineage.stage8_distribution_sha256_by_gameweek
    )
    assert first.decision.lineage.player_prior_binding_sha256_by_gameweek == (
        second.decision.lineage.player_prior_binding_sha256_by_gameweek
    )


def test_a1_injected_resolver_uses_existing_projector_and_preserves_upstream_hashes(
    repository_root, tmp_path
) -> None:
    execution = build_rolling_execution_input(repository_root, tmp_path / "input")
    baseline = PrivateV1RollingRecommendationService().run(execution)
    calls: list = []
    injected = PrivateV1RollingRecommendationService(
        _allocation_profile_resolver=_resolver_for(execution, assist_multiplier=1.5, calls=calls)
    ).run(execution)

    expected_fixture_count = len(execution.current_execution.manual_minutes) + sum(
        len(item.fixtures) for item in execution.future_gameweeks
    )
    assert len(calls) == expected_fixture_count
    assert injected.decision.lineage.stage7_input_sha256_by_gameweek == (
        baseline.decision.lineage.stage7_input_sha256_by_gameweek
    )
    assert injected.decision.lineage.stage8_distribution_sha256_by_gameweek == (
        baseline.decision.lineage.stage8_distribution_sha256_by_gameweek
    )
    assert injected.decision.lineage.player_prior_binding_sha256_by_gameweek != (
        baseline.decision.lineage.player_prior_binding_sha256_by_gameweek
    )


@pytest.mark.parametrize("malformed", ("missing", "extra", "duplicate", "team"))
def test_a1_injected_profile_coverage_fails_closed(repository_root, tmp_path, malformed) -> None:
    execution = build_rolling_execution_input(repository_root, tmp_path / malformed)
    service = PrivateV1RollingRecommendationService(
        _allocation_profile_resolver=_resolver_for(execution, malformed=malformed)
    )

    with pytest.raises(PrivateV1Error):
        service.run(execution)


def test_a1_world_execution_order_isolated(repository_root, tmp_path) -> None:
    execution = build_rolling_execution_input(repository_root, tmp_path / "input")

    def run(multiplier: float):
        return (
            PrivateV1RollingRecommendationService(
                _allocation_profile_resolver=_resolver_for(execution, assist_multiplier=multiplier)
            )
            .run(execution)
            .decision
        )

    first_a, first_b = run(1.25), run(1.5)
    second_b, second_a = run(1.5), run(1.25)
    assert first_a == second_a
    assert first_b == second_b


def test_a1_ordinary_constructor_has_no_public_world_selector() -> None:
    parameters = inspect.signature(PrivateV1RollingRecommendationService).parameters
    assert tuple(parameters) == ("_allocation_profile_resolver", "_score_prior_resolver")
    assert all(name.startswith("_") for name in parameters)
    assert all(parameter.default is None for parameter in parameters.values())
