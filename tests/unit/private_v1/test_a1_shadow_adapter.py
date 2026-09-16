"""Offline A1.02 tests for the R9B shadow-to-fixture adapter."""

from __future__ import annotations

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.current_player_posterior import ALLOWED_PROFILE_FIELDS
from dmf_pulse.fpl_points.service import generate_fixture_scenarios
from dmf_pulse.private_v1.shadow_adapter import ShadowFixtureAllocationProfileResolver
from tests.support.factories import reference_engine
from tests.unit.fpl_points.current_shadow_support import synthetic_shadow, synthetic_stage9_request


def _resolution_inputs(request, shadow):
    participants = request.participation_scenarios[0].participants
    participant_ids = frozenset(item.player_id for item in participants)
    entries = {
        entry.binding.current_player_id: entry
        for entry in shadow.worlds[0].posterior.entries
        if entry.binding.current_player_id in participant_ids
    }
    return {
        "fixture_id": request.score_distribution.fixture_id,
        "gameweek_id": request.gameweek_id,
        "home_team_id": request.score_distribution.home_team_id,
        "away_team_id": request.score_distribution.away_team_id,
        "participant_ids": participant_ids,
        "participation": request.participation_scenarios,
        "source_player_map": {
            entry.binding.source_player_id: player_id for player_id, entry in entries.items()
        },
        "source_team_map": {
            entry.binding.source_team_id: entry.binding.current_team_id
            for entry in entries.values()
        },
        "information_cutoff_utc": request.information_cutoff_utc,
    }


def test_a1_shadow_adapter_preserves_upstream_and_mutates_only_supported_fields(repository_root):
    shadow = synthetic_shadow(repository_root, count=120)
    request = synthetic_stage9_request(shadow, scenario_count=8)
    inputs = _resolution_inputs(request, shadow)
    stale = {profile.player_id: profile for profile in request.allocation_profiles}
    resolutions = {}

    for world in ("CENTRAL_TEMPORARY", "LOW_SHRINKAGE", "HIGH_SHRINKAGE"):
        resolution = ShadowFixtureAllocationProfileResolver(shadow=shadow, world=world)(**inputs)
        resolutions[world] = resolution
        assert resolution.prior_identity is None
        assert resolution.binding_sha256 == resolution.shadow_provenance.semantic_sha256
        assert tuple(profile.player_id for profile in resolution.profiles) == tuple(
            sorted(inputs["participant_ids"])
        )
        for profile in resolution.profiles:
            before = stale[profile.player_id].model_dump(mode="python")
            after = profile.model_dump(mode="python")
            for field, value in before.items():
                if field not in ALLOWED_PROFILE_FIELDS:
                    assert after[field] == value
        shadow_request = request.model_copy(
            update={"allocation_profiles": resolution.profiles, "player_prior_identity": None}
        )
        assert shadow_request.participation_scenarios == request.participation_scenarios
        assert shadow_request.score_distribution == request.score_distribution

    assert len({item.binding_sha256 for item in resolutions.values()}) == 3


def test_a1_shadow_adapter_is_deterministic_and_stage9_can_move(repository_root):
    shadow = synthetic_shadow(repository_root, count=120)
    request = synthetic_stage9_request(shadow, scenario_count=16)
    inputs = _resolution_inputs(request, shadow)
    outputs = {}
    for world in ("CENTRAL_TEMPORARY", "LOW_SHRINKAGE", "HIGH_SHRINKAGE"):
        first = ShadowFixtureAllocationProfileResolver(shadow=shadow, world=world)(**inputs)
        second = ShadowFixtureAllocationProfileResolver(shadow=shadow, world=world)(**inputs)
        assert first == second
        shadow_request = request.model_copy(
            update={"allocation_profiles": first.profiles, "player_prior_identity": None}
        )
        scenarios = generate_fixture_scenarios(
            shadow_request, reference_engine(), range(shadow_request.scenario_count)
        )
        outputs[world] = canonical_sha256(
            [
                [
                    scenario.players[player_id].total
                    for player_id in sorted(inputs["participant_ids"])
                ]
                for scenario in scenarios
            ]
        )
    stale = generate_fixture_scenarios(request, reference_engine(), range(request.scenario_count))
    stale_hash = canonical_sha256(
        [
            [scenario.players[player_id].total for player_id in sorted(inputs["participant_ids"])]
            for scenario in stale
        ]
    )
    assert any(value != stale_hash for value in outputs.values())


def test_a1_shadow_adapter_fails_closed_for_missing_or_wrong_world(repository_root):
    shadow = synthetic_shadow(repository_root, count=120)
    request = synthetic_stage9_request(shadow, scenario_count=4)
    inputs = _resolution_inputs(request, shadow)
    resolver = ShadowFixtureAllocationProfileResolver(shadow=shadow, world="CENTRAL_TEMPORARY")
    missing = dict(inputs)
    missing["source_player_map"] = dict(list(inputs["source_player_map"].items())[1:])
    try:
        resolver(**missing)
    except ValueError as exc:
        assert "incomplete or ambiguous" in str(exc)
    else:  # pragma: no cover - the invariant above is the assertion
        raise AssertionError("missing shadow participant was accepted")
    try:
        ShadowFixtureAllocationProfileResolver(shadow=shadow, world="STALE")
    except ValueError as exc:
        assert "unavailable" in str(exc)
    else:  # pragma: no cover - the invariant above is the assertion
        raise AssertionError("STALE was accepted as an injected shadow world")
