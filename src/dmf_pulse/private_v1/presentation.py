"""Allowlisted, transient presentation of completed model outputs; no new model."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from math import isclose
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from dmf_pulse.availability.current_model import CurrentModelFixtureMinutesInput
from dmf_pulse.availability.projection import PlayerMinutesProjection
from dmf_pulse.fpl_points.models import (
    POINT_COMPONENT_NAMES,
    FixtureProjectionResult,
    GameweekPlayerProjectionSummary,
    GameweekProjectionResult,
    MonteCarloDiagnostics,
    PlayerProjectionSummary,
)
from dmf_pulse.ingestion.fpl.direct_payloads import DirectFplSnapshot
from dmf_pulse.private_v1.models import PrivateCanonicalPlayerIdentityMap


class PresentationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class CataloguePlayer(PresentationModel):
    official_id: int
    player_id: str | None
    name: str
    team: str
    position: str
    price_tenths: int
    unavailable_reason: Literal["REMOVED_UNMAPPED", "NO_PROJECTION"] | None


class SourceVintage(PresentationModel):
    source: str
    identity_sha256: str
    received_at: datetime
    usable_at: datetime
    source_mode: Literal["CURRENT_TRANSIENT", "HISTORICAL_RECONSTRUCTED"]
    source_commit_at: datetime | None = None
    requests: int


class FixturePresentation(PresentationModel):
    fixture_id: str
    official_fixture_id: int
    gameweek: int
    home: str
    away: str
    kickoff_at: datetime | None
    result_sha256: str
    summaries: dict[str, PlayerProjectionSummary]
    minutes: dict[str, PlayerMinutesProjection]
    warnings: tuple[str, ...]


class GameweekPresentation(PresentationModel):
    gameweek: int
    result_sha256: str
    summaries: dict[str, GameweekPlayerProjectionSummary]
    diagnostics: MonteCarloDiagnostics
    warnings: tuple[str, ...]

    @model_validator(mode="after")
    def components_reconcile(self) -> Self:
        for player_id, summary in self.summaries.items():
            if player_id != summary.player_id or set(summary.component_breakdown) != set(
                POINT_COMPONENT_NAMES
            ):
                raise ValueError("projection player/component identity mismatch")
            if not isclose(
                sum(item.expected_points for item in summary.component_breakdown.values()),
                summary.expected_points,
                rel_tol=0,
                abs_tol=1e-10,
            ):
                raise ValueError("projection components do not reconcile")
        return self


class PrivatePresentation(PresentationModel):
    schema_version: Literal["private-presentation-v1"] = "private-presentation-v1"
    catalogue: tuple[CataloguePlayer, ...]
    gameweeks: tuple[GameweekPresentation, ...]
    fixtures: tuple[FixturePresentation, ...]
    current_squad: tuple[str, ...]
    deadline_at: datetime
    source_captured_at: datetime
    source_vintages: tuple[SourceVintage, ...]
    market_quota_remaining: int | None

    @model_validator(mode="after")
    def coverage_is_exact(self) -> Self:
        ids = tuple(item.official_id for item in self.catalogue)
        mapped = {item.player_id for item in self.catalogue if item.player_id is not None}
        if len(set(ids)) != len(ids) or not self.gameweeks:
            raise ValueError("catalogue must be unique with completed projections")
        for gameweek in self.gameweeks:
            if not set(gameweek.summaries) <= mapped:
                raise ValueError("projection absent from catalogue")
        if len(self.current_squad) != 15 or not set(self.current_squad) <= mapped:
            raise ValueError("current squad absent from catalogue")
        return self


def build_presentation(
    *,
    snapshot: DirectFplSnapshot,
    identities: PrivateCanonicalPlayerIdentityMap,
    current_squad: tuple[str, ...],
    projections: Mapping[int, GameweekProjectionResult],
    fixtures: tuple[FixtureProjectionResult, ...],
    minutes: Mapping[int, tuple[CurrentModelFixtureMinutesInput, ...]],
    fixture_mapping: Mapping[str, int],
    source_vintages: tuple[SourceVintage, ...],
    market_quota_remaining: int | None,
) -> PrivatePresentation:
    """Copy completed summaries only; exclude bodies, transports and scenario matrices."""
    player_ids = {
        item.official_fpl_element_id: str(item.canonical_player_id) for item in identities.players
    }
    team_names = {
        str(item.canonical_team_id): next(
            team.official_name
            for team in snapshot.fpl_input.teams
            if team.provider_team_id == item.official_fpl_team_id
        )
        for item in identities.teams
    }
    official_teams = {
        item.provider_team_id: item.official_name for item in snapshot.fpl_input.teams
    }
    projected = set(next(iter(projections.values())).player_summaries)
    catalogue = tuple(
        CataloguePlayer(
            official_id=player.provider_element_id,
            player_id=player_ids.get(player.provider_element_id),
            name=player.web_name,
            team=official_teams[int(player.team_identity.external_id_text)],
            position=player.position.value,
            price_tenths=player.current_price_tenths,
            unavailable_reason=(
                "REMOVED_UNMAPPED"
                if player.provider_element_id not in player_ids
                else "NO_PROJECTION"
                if player_ids[player.provider_element_id] not in projected
                else None
            ),
        )
        for player in snapshot.fpl_input.players
    )
    fixture_views = []
    for gameweek, inputs in minutes.items():
        for item in inputs:
            result = next(value for value in fixtures if value.fixture_id == item.fixture_id)
            official_home = next(
                value.official_fpl_team_id
                for value in identities.teams
                if str(value.canonical_team_id) == item.home_team_id
            )
            official_away = next(
                value.official_fpl_team_id
                for value in identities.teams
                if str(value.canonical_team_id) == item.away_team_id
            )
            candidates = [
                value
                for value in snapshot.fpl_input.fixtures
                if value.provider_fixture_id == fixture_mapping[item.fixture_id]
            ]
            if len(candidates) != 1:
                raise ValueError("presentation fixture mapping not unique")
            source_fixture = candidates[0]
            if (
                source_fixture.event_identity is None
                or source_fixture.event_identity.external_id_text != str(gameweek)
                or source_fixture.home_team_identity.external_id_text != str(official_home)
                or source_fixture.away_team_identity.external_id_text != str(official_away)
            ):
                raise ValueError("presentation fixture identity differs from core")
            fixture_views.append(
                FixturePresentation(
                    fixture_id=item.fixture_id,
                    official_fixture_id=source_fixture.provider_fixture_id,
                    gameweek=gameweek,
                    home=team_names[item.home_team_id],
                    away=team_names[item.away_team_id],
                    kickoff_at=source_fixture.kickoff_at,
                    result_sha256=str(result.result_sha256),
                    summaries=result.player_summaries,
                    minutes={
                        player.player_id: player
                        for team in (item.home_projection, item.away_projection)
                        for player in team.players
                    },
                    warnings=tuple(sorted(set((*result.warnings, *item.warnings)))),
                )
            )
    return PrivatePresentation(
        catalogue=catalogue,
        gameweeks=tuple(
            GameweekPresentation(
                gameweek=gameweek,
                result_sha256=str(projection.result_sha256),
                summaries=projection.player_summaries,
                diagnostics=projection.monte_carlo,
                warnings=projection.scenario_set.warnings,
            )
            for gameweek, projection in sorted(projections.items())
        ),
        fixtures=tuple(fixture_views),
        current_squad=current_squad,
        deadline_at=snapshot.fpl_input.target_event.deadline_at,
        source_captured_at=snapshot.captured_at,
        source_vintages=source_vintages,
        market_quota_remaining=market_quota_remaining,
    )
