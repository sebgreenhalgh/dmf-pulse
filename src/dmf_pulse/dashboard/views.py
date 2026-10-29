"""Versioned browser contracts derived from one coherent completed run."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from dmf_pulse.fpl_points.models import GameweekPlayerProjectionSummary
from dmf_pulse.private_v1.models import PrivateV1Decision
from dmf_pulse.private_v1.one_command import OneCommandResult
from dmf_pulse.private_v1.presentation import (
    CataloguePlayer,
    FixturePresentation,
    PresentationModel,
    SourceVintage,
)
from dmf_pulse.private_v1.rolling_models import PrivateV1RollingDecision


class PlayerRow(PresentationModel):
    catalogue: CataloguePlayer
    expected_points: float | None
    three_gameweek_expected_points: float | None
    points_per_price: float | None
    expected_minutes: str | None
    p_start: str | None
    p_60_plus: str | None
    confidence: str | None
    fallback: bool
    fixtures: tuple[str, ...]
    goals_contribution: float | None
    assists_contribution: float | None
    clean_sheet_contribution: float | None
    bonus_contribution: float | None


class TeamView(PresentationModel):
    current_squad: tuple[str, ...]
    decision: PrivateV1Decision | PrivateV1RollingDecision
    report: str


class DeskView(PresentationModel):
    schema_version: Literal["sebs-desk-v1"] = "sebs-desk-v1"
    job_id: str
    dataset_mode: Literal["SYNTHETIC_DEMONSTRATION", "SYNTHETIC_CURRENT_MODE", "PRIVATE_TRANSIENT"]
    generated_at: datetime
    deadline_at: datetime
    expires_at: datetime
    expires_in_seconds: float
    source_captured_at: datetime
    information_cutoff: datetime
    gameweeks: tuple[int, ...]
    catalogue_count: int
    projected_count: int
    blocked_count: int
    players: tuple[PlayerRow, ...]
    team: TeamView
    restrictions: tuple[str, ...] = (
        "NO_CHIP_EXPLICIT",
        "POINTS_MODE_ONLY",
        "NOT_PRODUCTION_ACTIVE",
        "TRANSIENT_SESSION_NO_RETENTION",
        "Component decomposition is not causal sensitivity; component uncertainty is correlated.",
    )
    source_vintages: tuple[SourceVintage, ...]
    market_quota_remaining: int | None


class PlayerDetail(PresentationModel):
    schema_version: Literal["player-lab-v1"] = "player-lab-v1"
    job_id: str
    catalogue: CataloguePlayer
    gameweeks: dict[int, GameweekPlayerProjectionSummary]
    fixtures: tuple[FixturePresentation, ...]
    warnings: tuple[str, ...]
    role: Literal["RECOMMENDED_SQUAD", "CURRENT_SQUAD", "PROJECTED", "UNAVAILABLE"]
    frontier_transfer_counts: tuple[int, ...]


class PlayerComparison(PresentationModel):
    schema_version: Literal["player-comparison-v1"] = "player-comparison-v1"
    left: PlayerDetail
    right: PlayerDetail


def desk_view(
    result: OneCommandResult,
    *,
    job_id: str,
    mode: Literal["SYNTHETIC_DEMONSTRATION", "SYNTHETIC_CURRENT_MODE", "PRIVATE_TRANSIENT"],
    generated_at: datetime,
    expires_at: datetime,
) -> DeskView:
    presentation = result.presentation
    if presentation is None:
        raise ValueError("completed run lacks presentation")
    current = presentation.gameweeks[0]
    fallback_ids = (
        result.decision.player_prior_fallback_player_ids
        if isinstance(result.decision, PrivateV1Decision)
        else result.decision.lineage.player_prior_fallback_ids
    )
    rows = []
    for player in presentation.catalogue:
        summary = current.summaries.get(player.player_id or "")
        fixture_minutes = [
            value.minutes[player.player_id]
            for value in presentation.fixtures
            if value.gameweek == current.gameweek and player.player_id in value.minutes
        ]
        single = fixture_minutes[0] if len(fixture_minutes) == 1 else None
        horizon_summaries = [
            value.summaries.get(player.player_id or "") for value in presentation.gameweeks
        ]
        rows.append(
            PlayerRow(
                catalogue=player,
                expected_points=None if summary is None else summary.expected_points,
                three_gameweek_expected_points=(
                    sum(item.expected_points for item in horizon_summaries if item is not None)
                    if len(horizon_summaries) == 3
                    and all(item is not None for item in horizon_summaries)
                    else None
                ),
                points_per_price=(
                    None
                    if summary is None
                    else summary.expected_points / (player.price_tenths / 10)
                ),
                expected_minutes=None if single is None else single.expected_minutes,
                p_start=None if single is None else single.p_start,
                p_60_plus=None if single is None else single.p_60_plus,
                confidence=None if summary is None else str(summary.confidence_grade),
                fallback=player.player_id in fallback_ids,
                fixtures=tuple(
                    f"GW {value.gameweek}: {value.home} v {value.away}"
                    for value in presentation.fixtures
                    if player.player_id in value.summaries
                ),
                goals_contribution=None
                if summary is None
                else summary.component_breakdown["goals"].expected_points,
                assists_contribution=None
                if summary is None
                else summary.component_breakdown["assists"].expected_points,
                clean_sheet_contribution=None
                if summary is None
                else summary.component_breakdown["clean_sheet"].expected_points,
                bonus_contribution=None
                if summary is None
                else summary.component_breakdown["bonus"].expected_points,
            )
        )
    projected = sum(item.expected_points is not None for item in rows)
    return DeskView(
        job_id=job_id,
        dataset_mode=mode,
        generated_at=generated_at,
        deadline_at=result.actionability.deadline_at,
        expires_at=expires_at,
        expires_in_seconds=(expires_at - generated_at).total_seconds(),
        source_captured_at=presentation.source_captured_at,
        information_cutoff=result.decision.information_cutoff,
        gameweeks=tuple(item.gameweek for item in presentation.gameweeks),
        catalogue_count=len(rows),
        projected_count=projected,
        blocked_count=len(rows) - projected,
        players=tuple(rows),
        team=TeamView(
            current_squad=presentation.current_squad, decision=result.decision, report=result.report
        ),
        source_vintages=presentation.source_vintages,
        market_quota_remaining=presentation.market_quota_remaining,
    )


def player_detail(result: OneCommandResult, job_id: str, official_id: int) -> PlayerDetail:
    presentation = result.presentation
    if presentation is None:
        raise ValueError("completed run lacks presentation")
    player = next(item for item in presentation.catalogue if item.official_id == official_id)
    summaries = {
        item.gameweek: item.summaries[player.player_id]
        for item in presentation.gameweeks
        if player.player_id in item.summaries
    }
    decision = result.decision
    squad = (
        decision.resulting_squad
        if isinstance(decision, PrivateV1Decision)
        else decision.do_now.squad_after
    )
    return PlayerDetail(
        job_id=job_id,
        catalogue=player,
        gameweeks=summaries,
        fixtures=tuple(
            item.model_copy(
                update={
                    "summaries": {player.player_id: item.summaries[player.player_id]},
                    "minutes": {player.player_id: item.minutes[player.player_id]}
                    if player.player_id in item.minutes
                    else {},
                }
            )
            for item in presentation.fixtures
            if player.player_id in item.summaries
        ),
        warnings=tuple(sorted(set(decision.warnings))),
        role=(
            "UNAVAILABLE"
            if not summaries
            else "RECOMMENDED_SQUAD"
            if player.player_id in squad
            else "CURRENT_SQUAD"
            if player.player_id in presentation.current_squad
            else "PROJECTED"
        ),
        frontier_transfer_counts=tuple(
            item.transfer_count
            for item in decision.transfer_frontier.points
            if any(
                player.player_id in {move.player_in_id, move.player_out_id}
                for move in item.transfers
            )
        )
        if decision.transfer_frontier is not None
        else (),
    )
