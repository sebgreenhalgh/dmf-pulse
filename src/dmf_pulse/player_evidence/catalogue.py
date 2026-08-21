"""In-memory bridge from governed current FPL input to the Stage-7 identity space."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.current import current_player_id, current_team_id
from dmf_pulse.fpl_points.models import PlayerPosition
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplInputBundle
from dmf_pulse.player_evidence.models import (
    CurrentPlayer,
    CurrentPlayerCatalogue,
    CurrentPlayerIdentityMode,
)


def build_current_player_history_catalogue(
    bundle: CurrentFplInputBundle,
    *,
    stage7_team_ids: Mapping[int, UUID] | None = None,
) -> CurrentPlayerCatalogue:
    """Build a transient, hash-bound catalogue without name or database resolution.

    ``stage7_team_ids`` is optional because Stage 7 requires reviewed current-market
    input.  If supplied, it must cover exactly the current FPL teams and agree with
    the UUID convention that Stage 7 itself uses.
    """

    if bundle.competition_key != "PL" or bundle.season_code != "2026/27":
        raise IngestionError("MAPPING_CONFLICT", "current FPL bundle is outside the GW1 scope")
    if bundle.target_gameweek != 1:
        raise IngestionError("MAPPING_CONFLICT", "current FPL bundle is not GW1")

    teams_by_identity = {team.identity.canonical_lookup_sha256: team for team in bundle.teams}
    expected_stage7_team_ids = {
        team.provider_team_id: current_team_id(team) for team in bundle.teams
    }
    if stage7_team_ids is not None and dict(stage7_team_ids) != expected_stage7_team_ids:
        raise IngestionError(
            "MAPPING_CONFLICT", "current FPL teams do not agree with Stage-7 transient identities"
        )

    players: list[CurrentPlayer] = []
    for player in bundle.players:
        team = teams_by_identity.get(player.team_identity.canonical_lookup_sha256)
        if team is None:
            raise IngestionError("MAPPING_CONFLICT", "current FPL player has no exact current team")
        players.append(
            CurrentPlayer(
                player_id=current_player_id(player),
                source_player_id=player.provider_element_id,
                team_id=current_team_id(team),
                position=PlayerPosition(player.position.value),
                current_price_tenths=player.current_price_tenths,
                source_player_identity_sha256=player.identity.canonical_lookup_sha256,
                source_team_identity_sha256=team.identity.canonical_lookup_sha256,
            )
        )
    ordered = tuple(sorted(players, key=lambda row: str(row.player_id)))
    provisional = CurrentPlayerCatalogue.model_construct(
        schema_version="gw1-player-history-catalogue-v2",
        identity_mode=CurrentPlayerIdentityMode.GW1_STAGE7_TRANSIENT_SURROGATE,
        source_catalogue_semantic_sha256=bundle.semantic_sha256,
        source_bundle_semantic_sha256=bundle.semantic_sha256,
        source_bootstrap_semantic_sha256=bundle.provenance.bootstrap_semantic_sha256,
        players=ordered,
        semantic_sha256="0" * 64,
    )
    return CurrentPlayerCatalogue(
        schema_version="gw1-player-history-catalogue-v2",
        identity_mode=CurrentPlayerIdentityMode.GW1_STAGE7_TRANSIENT_SURROGATE,
        source_catalogue_semantic_sha256=bundle.semantic_sha256,
        source_bundle_semantic_sha256=bundle.semantic_sha256,
        source_bootstrap_semantic_sha256=bundle.provenance.bootstrap_semantic_sha256,
        players=ordered,
        semantic_sha256=canonical_sha256(
            provisional.model_dump(mode="json", exclude={"semantic_sha256"})
        ),
    )


__all__ = ["build_current_player_history_catalogue"]
