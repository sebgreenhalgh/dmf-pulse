"""Fail-closed target/history/cutoff checks for the A1.03 resolver."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from dmf_pulse.fpl_points.current_player_posterior import (
    CurrentPlayerAllocationShadow,
    CurrentPlayerAllocationShadowWorld,
    CurrentPlayerPosteriorArtifact,
    seal,
)
from dmf_pulse.private_v1.shadow_adapter import ShadowFixtureAllocationProfileResolver
from tests.unit.fpl_points.current_shadow_support import synthetic_shadow, synthetic_stage9_request


def _resolution_inputs(request: Any, shadow: CurrentPlayerAllocationShadow) -> dict[str, Any]:
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


def _mutate_shadow(
    shadow: CurrentPlayerAllocationShadow,
    *,
    target_gameweek: int | None = None,
    source_gameweeks: tuple[int, ...] | None = None,
    cutoff_delta: timedelta | None = None,
) -> CurrentPlayerAllocationShadow:
    worlds = []
    for world in shadow.worlds:
        posterior_payload = {
            field_name: getattr(world.posterior, field_name)
            for field_name in type(world.posterior).model_fields
        }
        if target_gameweek is not None:
            posterior_payload["target_gameweek"] = target_gameweek
        if source_gameweeks is not None:
            posterior_payload["source_gameweeks"] = source_gameweeks
        if cutoff_delta is not None:
            posterior_payload["information_cutoff"] += cutoff_delta
        posterior_payload["semantic_sha256"] = "0" * 64
        posterior = seal(CurrentPlayerPosteriorArtifact.model_construct(**posterior_payload))
        world_payload = {
            field_name: getattr(world, field_name) for field_name in type(world).model_fields
        }
        world_payload.update(posterior=posterior, semantic_sha256="0" * 64)
        worlds.append(seal(CurrentPlayerAllocationShadowWorld.model_construct(**world_payload)))
    shadow_payload = {
        field_name: getattr(shadow, field_name) for field_name in type(shadow).model_fields
    }
    shadow_payload.update(worlds=tuple(worlds), semantic_sha256="0" * 64)
    return seal(CurrentPlayerAllocationShadow.model_construct(**shadow_payload))


@pytest.fixture(scope="module")
def base(repository_root) -> tuple[CurrentPlayerAllocationShadow, Any, dict[str, Any]]:
    shadow = synthetic_shadow(repository_root, count=120, gameweeks=4)
    request = synthetic_stage9_request(shadow, scenario_count=1)
    return shadow, request, _resolution_inputs(request, shadow)


def test_exact_gw1_4_history_binds_to_target_gw5_and_horizon_gw5_7(base) -> None:
    shadow, _request, inputs = base
    resolver = ShadowFixtureAllocationProfileResolver(shadow=shadow, world="CENTRAL_TEMPORARY")
    for gameweek in (5, 6, 7):
        resolution = resolver(**(inputs | {"gameweek_id": f"GW-{gameweek}"}))
        assert resolution.profiles


def test_incomplete_history_and_another_target_fail_closed(base) -> None:
    shadow, _request, inputs = base
    incomplete = _mutate_shadow(shadow, source_gameweeks=(1, 2, 4))
    with pytest.raises(ValueError, match="incomplete"):
        ShadowFixtureAllocationProfileResolver(shadow=incomplete, world="CENTRAL_TEMPORARY")(
            **inputs
        )
    other_target = _mutate_shadow(
        shadow,
        target_gameweek=6,
        source_gameweeks=(1, 2, 3, 4, 5),
    )
    with pytest.raises(ValueError, match="rolling horizon"):
        ShadowFixtureAllocationProfileResolver(shadow=other_target, world="CENTRAL_TEMPORARY")(
            **inputs
        )


def test_wrong_horizon_gameweek_and_cutoff_fail_closed(base) -> None:
    shadow, _request, inputs = base
    resolver = ShadowFixtureAllocationProfileResolver(shadow=shadow, world="CENTRAL_TEMPORARY")
    with pytest.raises(ValueError, match="rolling horizon"):
        resolver(**(inputs | {"gameweek_id": "GW-8"}))
    changed_cutoff = _mutate_shadow(shadow, cutoff_delta=timedelta(minutes=1))
    with pytest.raises(ValueError, match="cutoff"):
        ShadowFixtureAllocationProfileResolver(shadow=changed_cutoff, world="CENTRAL_TEMPORARY")(
            **inputs
        )


@pytest.mark.parametrize("source_gameweeks", [(1, 2, 3, 4, 5), (1, 2, 3, 4, 6)])
def test_target_or_future_history_row_is_rejected_by_sealed_shadow_contract(
    base,
    source_gameweeks: tuple[int, ...],
) -> None:
    shadow, _request, _inputs = base
    with pytest.raises(ValueError, match="source window"):
        _mutate_shadow(shadow, source_gameweeks=source_gameweeks)
