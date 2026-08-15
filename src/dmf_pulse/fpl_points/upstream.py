"""Narrow adapters over the final accepted Stage-7 and Stage-8 contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from dmf_pulse.availability import MinutesPredictionResult, TeamMinutesProjection
from dmf_pulse.football_events import JointScoreDistribution, Stage7MinutesContext
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import (
    OnPitchInterval,
    ParticipantState,
    ParticipationScenario,
    PlayerPosition,
    ScorelineCell,
)


def _read(value: object, name: str) -> Any:
    if isinstance(value, Mapping):
        if name not in value:
            raise FplPointsError("UPSTREAM_FIELD_MISSING", f"missing upstream field: {name}")
        return value[name]
    if not hasattr(value, name):
        raise FplPointsError("UPSTREAM_FIELD_MISSING", f"missing upstream field: {name}")
    return getattr(value, name)


def _optional(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def adapt_stage8_score_distribution(value: object) -> JointScoreDistribution:
    """Validate and retain the final GCS-008 public object without lossy aliases."""

    try:
        if isinstance(value, JointScoreDistribution):
            return value
        if isinstance(value, Mapping):
            payload: object = dict(value)
        else:
            dump = getattr(value, "model_dump", None)
            if not callable(dump):
                raise TypeError("Stage-8 value must be a public model or mapping")
            payload = dump(mode="python")
        return JointScoreDistribution.model_validate(payload)
    except (ValidationError, TypeError, ValueError) as exc:
        raise FplPointsError(
            "STAGE8_CONTRACT_INVALID",
            "final Stage-8 joint score distribution is invalid",
        ) from exc


def scoreline_cells(distribution: JointScoreDistribution) -> tuple[ScorelineCell, ...]:
    """Expose the canonical matrix as exact positive 12-place score cells."""

    return tuple(
        ScorelineCell(
            home_goals=home_goals,
            away_goals=away_goals,
            probability=probability,
        )
        for home_goals, row in enumerate(distribution.probabilities)
        for away_goals, probability in enumerate(row)
        if probability != "0.000000000000"
    )


def _position(value: object) -> PlayerPosition:
    raw = value.value if hasattr(value, "value") else value
    try:
        return PlayerPosition(str(raw))
    except ValueError as exc:
        raise FplPointsError("STAGE7_POSITION_INVALID", f"unsupported FPL position: {raw}") from exc


def _team_projection(value: object, *, label: str) -> TeamMinutesProjection:
    if isinstance(value, MinutesPredictionResult):
        if value.status != "PROJECTED" or value.projection is None:
            raise FplPointsError("STAGE7_PROJECTION_BLOCKED", f"{label} projection is blocked")
        return value.projection
    if isinstance(value, TeamMinutesProjection):
        return value
    try:
        if isinstance(value, Mapping) and "status" in value:
            result = MinutesPredictionResult.model_validate(dict(value))
            if result.status != "PROJECTED" or result.projection is None:
                raise FplPointsError("STAGE7_PROJECTION_BLOCKED", f"{label} projection is blocked")
            return result.projection
        return TeamMinutesProjection.model_validate(value)
    except FplPointsError:
        raise
    except (ValidationError, TypeError, ValueError) as exc:
        raise FplPointsError(
            "STAGE7_CONTRACT_INVALID", f"{label} does not satisfy the accepted Stage-7 contract"
        ) from exc


def build_participation_scenario(
    *,
    scenario_id: str,
    probability: float,
    fixture_id: str,
    gameweek_id: str,
    home_team_id: str,
    away_team_id: str,
    participant_rows: Iterable[object],
    home_projection: object,
    away_projection: object,
    information_cutoff_utc: str,
) -> ParticipationScenario:
    """Bind explicit coherent path rows to accepted team/player projection identities.

    Stage 7 intentionally exposes no public coherent cross-stage path class.  The path rows
    are therefore explicit Stage-9 inputs, while every team and player identity is extracted
    from the accepted immutable Stage-7 projections.
    """

    home = _team_projection(home_projection, label="home Stage-7")
    away = _team_projection(away_projection, label="away Stage-7")
    if (home.fixture_id, away.fixture_id) != (fixture_id, fixture_id):
        raise FplPointsError("STAGE7_FIXTURE_MISMATCH", "Stage-7 projection fixture differs")
    if (home.team_id, away.team_id) != (home_team_id, away_team_id):
        raise FplPointsError("STAGE7_TEAM_MISMATCH", "Stage-7 projection teams differ")
    context = Stage7MinutesContext.from_projections(home, away)
    projections: dict[str, tuple[str, Any]] = {}
    for projection in (home, away):
        for player in projection.players:
            if player.player_id in projections:
                raise FplPointsError(
                    "STAGE7_PLAYER_ID_COLLISION",
                    "home and away projections share a player identity",
                )
            projections[player.player_id] = (projection.team_id, player)
    participants: list[ParticipantState] = []
    for row in participant_rows:
        player_id = str(_read(row, "player_id"))
        team_id = str(_read(row, "team_id"))
        position = _position(_read(row, "position"))
        raw_minutes = _read(row, "official_minutes")
        if isinstance(raw_minutes, bool) or not isinstance(raw_minutes, int):
            raise FplPointsError(
                "STAGE7_MINUTES_INVALID", "official minutes must be an integer in [0, 90]"
            )
        minutes = raw_minutes
        if not 0 <= minutes <= 90:
            raise FplPointsError(
                "STAGE7_MINUTES_INVALID", "official minutes must be an integer in [0, 90]"
            )
        bound = projections.get(player_id)
        if bound is None:
            raise FplPointsError(
                "STAGE7_PLAYER_MISMATCH", "participation row is not bound to a Stage-7 player"
            )
        expected_team, projection = bound
        if team_id != expected_team:
            raise FplPointsError(
                "STAGE7_PLAYER_TEAM_MISMATCH", "participation team differs from projection"
            )
        if position.value != projection.position:
            raise FplPointsError(
                "STAGE7_PLAYER_POSITION_MISMATCH", "participation position differs from projection"
            )
        try:
            pmf_at_minutes = Decimal(projection.minute_pmf[minutes])
            p_start = Decimal(projection.p_start)
            p_bench = Decimal(projection.p_bench)
            p_out = Decimal(projection.p_out_of_squad)
        except (InvalidOperation, IndexError) as exc:
            raise FplPointsError(
                "STAGE7_PROJECTION_INVALID", "Stage-7 minute probabilities are invalid"
            ) from exc
        if pmf_at_minutes <= 0:
            raise FplPointsError(
                "STAGE7_MINUTE_PMF_ZERO", "selected official minutes have zero Stage-7 probability"
            )
        start = _optional(row, "entry_minute")
        end = _optional(row, "exit_minute")
        hard_ineligible = _optional(row, "hard_ineligible", False)
        starter = _optional(row, "starter", False)
        if not isinstance(hard_ineligible, bool) or not isinstance(starter, bool):
            raise FplPointsError(
                "STAGE7_BOOLEAN_INVALID", "hard_ineligible and starter must be booleans"
            )
        interval = None
        if minutes > 0:
            if start is None or end is None:
                raise FplPointsError(
                    "STAGE7_INTERVAL_MISSING", "positive minutes require entry and exit minutes"
                )
            try:
                start_decimal = Decimal(str(start))
                end_decimal = Decimal(str(end))
            except (InvalidOperation, ValueError) as exc:
                raise FplPointsError(
                    "STAGE7_INTERVAL_INVALID", "participation interval is not numeric"
                ) from exc
            if (
                not start_decimal.is_finite()
                or not end_decimal.is_finite()
                or start_decimal < 0
                or end_decimal > 90
                or end_decimal <= start_decimal
                or end_decimal - start_decimal != minutes
            ):
                raise FplPointsError(
                    "STAGE7_INTERVAL_INVALID",
                    "participation interval must exactly cover official minutes inside [0, 90]",
                )
            if starter and start_decimal != 0:
                raise FplPointsError("STAGE7_INTERVAL_INVALID", "starter must begin at kickoff")
            if not starter and start_decimal <= 0:
                raise FplPointsError(
                    "STAGE7_INTERVAL_INVALID", "bench appearance must begin after kickoff"
                )
            if hard_ineligible or (starter and p_start <= 0) or (not starter and p_bench <= 0):
                raise FplPointsError(
                    "STAGE7_ROLE_MISMATCH",
                    "positive-minute row is incompatible with projection role",
                )
            interval = OnPitchInterval(start_minute=float(start), end_minute=float(end))
        else:
            if start is not None or end is not None or starter or (hard_ineligible and p_out <= 0):
                raise FplPointsError(
                    "STAGE7_INTERVAL_INVALID",
                    "zero-minute row cannot carry an on-pitch interval or starter role",
                )
            if p_bench <= 0 and p_out <= 0:
                raise FplPointsError(
                    "STAGE7_ROLE_MISMATCH", "zero-minute row is incompatible with projection role"
                )
        participants.append(
            ParticipantState(
                player_id=player_id,
                team_id=team_id,
                position=position,
                official_minutes=minutes,
                interval=interval,
                hard_ineligible=hard_ineligible,
                starter=starter,
            )
        )
    player_hashes = {
        player.player_id: player.projection_sha256 for player in (*home.players, *away.players)
    }
    if len(player_hashes) != len(home.players) + len(away.players):
        raise FplPointsError(
            "STAGE7_PLAYER_ID_COLLISION", "home and away projections share a player identity"
        )
    try:
        return ParticipationScenario(
            scenario_id=scenario_id,
            fixture_id=fixture_id,
            gameweek_id=gameweek_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            probability=probability,
            participant_universe_complete=True,
            participants=tuple(participants),
            stage7_minutes_context=context,
            stage7_player_projection_sha256s=player_hashes,
            stage7_home_projection=home,
            stage7_away_projection=away,
            information_cutoff_utc=information_cutoff_utc,
        )
    except ValidationError as exc:
        raise FplPointsError(
            "STAGE7_PARTICIPATION_INVALID", "Stage-7 participation path is invalid"
        ) from exc


__all__ = [
    "adapt_stage8_score_distribution",
    "build_participation_scenario",
    "scoreline_cells",
]
