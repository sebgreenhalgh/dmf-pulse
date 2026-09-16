"""Offline-only R9C A1 binding of compiled R9B shadows to a fixture universe.

This module deliberately has no route from ordinary service construction.  Its
resolver is injected only by synthetic comparison code and carries non-active
provenance separately from :class:`PlayerPriorIdentity`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.current_player_posterior import (
    CurrentPlayerAllocationShadow,
    World,
)
from dmf_pulse.fpl_points.models import PlayerAllocationProfile
from dmf_pulse.private_v1.service import _FixtureAllocationResolution


@dataclass(frozen=True, slots=True)
class ShadowFixtureAllocationProvenance:
    """Non-active lineage for one synthetic shadow fixture resolution."""

    schema_version: str
    sensitivity_world: World
    source_shadow_sha256: str
    source_posterior_sha256: str
    current_binding_sha256: str
    information_cutoff_utc: str
    participant_ids: tuple[str, ...]
    semantic_sha256: str
    model_input_status: str = "SHADOW_NOT_MODEL_INPUT"
    production_activation: bool = False


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class ShadowFixtureAllocationProfileResolver:
    """Resolve exactly one compiled, non-active R9B world without I/O or fitting."""

    def __init__(self, *, shadow: CurrentPlayerAllocationShadow, world: World) -> None:
        shadow = CurrentPlayerAllocationShadow.model_validate(shadow.model_dump(mode="python"))
        worlds = {item.posterior.sensitivity_world: item for item in shadow.worlds}
        selected = worlds.get(world)
        if selected is None:
            raise ValueError("shadow sensitivity world is unavailable")
        self._shadow = shadow
        self._world = world
        self._selected = selected

    def __call__(
        self,
        *,
        fixture_id: str,
        gameweek_id: str,
        home_team_id: str,
        away_team_id: str,
        participant_ids: frozenset[str],
        participation: tuple[Any, ...],
        source_player_map: dict[int, str],
        source_team_map: dict[int, str],
        information_cutoff_utc: str,
    ) -> _FixtureAllocationResolution:
        del fixture_id, gameweek_id
        if (
            not participant_ids
            or len(source_player_map) != len(participant_ids)
            or set(source_player_map.values()) != set(participant_ids)
        ):
            raise ValueError("shadow participant/source-player mapping is incomplete or ambiguous")
        if set(source_team_map.values()) != {home_team_id, away_team_id}:
            raise ValueError("shadow fixture team mapping differs from fixture context")
        if information_cutoff_utc != _utc_text(self._selected.posterior.information_cutoff):
            raise ValueError("shadow cutoff differs from fixture cutoff")

        expected: dict[str, tuple[str, Any]] = {}
        for scenario in participation:
            for participant in scenario.participants:
                identity = (participant.team_id, participant.position)
                if participant.team_id not in (home_team_id, away_team_id):
                    raise ValueError("shadow participant belongs to another fixture team")
                previous = expected.setdefault(participant.player_id, identity)
                if previous != identity:
                    raise ValueError("shadow participant identity differs between scenarios")
        if set(expected) != set(participant_ids):
            raise ValueError("shadow participant universe differs from Stage-7")

        entries = {
            entry.binding.current_player_id: entry for entry in self._selected.posterior.entries
        }
        profiles = {profile.player_id: profile for profile in self._selected.profiles}
        if len(entries) != len(self._selected.posterior.entries) or len(profiles) != len(
            self._selected.profiles
        ):
            raise ValueError("shadow current-player identity is ambiguous")
        selected_profiles: list[PlayerAllocationProfile] = []
        fallback_player_ids: set[str] = set()
        for player_id in sorted(participant_ids):
            entry = entries.get(player_id)
            profile = profiles.get(player_id)
            if entry is None or profile is None:
                raise ValueError("shadow lacks a required current player")
            expected_team, expected_position = expected[player_id]
            if (
                entry.binding.current_team_id != expected_team
                or entry.binding.position is not expected_position
                or profile.team_id != expected_team
            ):
                raise ValueError("shadow current-player identity differs from Stage-7")
            source_id = next(
                (key for key, value in source_player_map.items() if value == player_id), None
            )
            if source_id != entry.binding.source_player_id:
                raise ValueError("shadow current-player source identity differs")
            if source_team_map.get(entry.binding.source_team_id) != expected_team:
                raise ValueError("shadow current-team source identity differs")
            selected_profiles.append(profile)
            if entry.binding.assignment_level == "FPL_POSITION_FALLBACK":
                fallback_player_ids.add(player_id)

        profile_payload = tuple(profile.model_dump(mode="json") for profile in selected_profiles)
        provenance_payload = {
            "schema_version": "r9c-a1-shadow-fixture-allocation-provenance-v1",
            "sensitivity_world": self._world,
            "source_shadow_sha256": self._shadow.semantic_sha256,
            "source_posterior_sha256": self._selected.posterior.semantic_sha256,
            "current_binding_sha256": self._selected.posterior.current_binding_sha256,
            "information_cutoff_utc": information_cutoff_utc,
            "participant_ids": tuple(sorted(participant_ids)),
            "profiles": profile_payload,
            "model_input_status": "SHADOW_NOT_MODEL_INPUT",
            "production_activation": False,
        }
        resolution_sha256 = canonical_sha256(provenance_payload)
        provenance = ShadowFixtureAllocationProvenance(
            schema_version="r9c-a1-shadow-fixture-allocation-provenance-v1",
            sensitivity_world=self._world,
            source_shadow_sha256=self._shadow.semantic_sha256,
            source_posterior_sha256=self._selected.posterior.semantic_sha256,
            current_binding_sha256=self._selected.posterior.current_binding_sha256,
            information_cutoff_utc=information_cutoff_utc,
            participant_ids=tuple(sorted(participant_ids)),
            semantic_sha256=resolution_sha256,
        )
        return _FixtureAllocationResolution(
            profiles=tuple(selected_profiles),
            prior_identity=None,
            binding_sha256=resolution_sha256,
            fallback_player_ids=frozenset(fallback_player_ids),
            shadow_provenance=provenance,
        )


__all__ = ["ShadowFixtureAllocationProfileResolver", "ShadowFixtureAllocationProvenance"]
