"""Pure, transient current-player history evidence from acquired FPL event-live facts.

This module deliberately produces evidence only.  It neither performs transport nor
feeds DMFP-07/09 or the private recommendation path.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct_payloads import (
    DirectFplSnapshot,
    DirectLiveStats,
)
from dmf_pulse.ingestion.models import FrozenModel

Statistic = Literal[
    "minutes",
    "starts",
    "goals_scored",
    "assists",
    "own_goals",
    "penalties_saved",
    "penalties_missed",
    "yellow_cards",
    "red_cards",
    "saves",
    "combined_cbi",
    "tackles",
    "recoveries",
    "defensive_contribution",
    "bonus",
    "bps",
]

_STATISTICS: tuple[Statistic, ...] = (
    "minutes",
    "starts",
    "goals_scored",
    "assists",
    "own_goals",
    "penalties_saved",
    "penalties_missed",
    "yellow_cards",
    "red_cards",
    "saves",
    "combined_cbi",
    "tackles",
    "recoveries",
    "defensive_contribution",
    "bonus",
    "bps",
)


class CurrentPlayerHistoryQuality(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL_FIELD_COVERAGE = "PARTIAL_FIELD_COVERAGE"
    PLAYER_HISTORY_UNAVAILABLE = "PLAYER_HISTORY_UNAVAILABLE"
    BOOTSTRAP_RECONCILIATION_NOT_APPLICABLE = "BOOTSTRAP_RECONCILIATION_NOT_APPLICABLE"
    BOOTSTRAP_RECONCILIATION_FAILED = "BOOTSTRAP_RECONCILIATION_FAILED"
    CURRENT_PLAYER_IDENTITY_UNRESOLVED = "CURRENT_PLAYER_IDENTITY_UNRESOLVED"
    SOURCE_MALFORMED = "SOURCE_MALFORMED"


class _HistoryModel(FrozenModel):
    @field_validator("information_cutoff", check_fields=False)
    @classmethod
    def utc_cutoff(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("information cutoff must be timezone-aware")
        return value.astimezone(UTC)


class CurrentPlayerGameweekEvidence(_HistoryModel):
    """One official-FPL *Gameweek aggregate*, never a fixture attribution."""

    official_fpl_element_id: int = Field(gt=0)
    current_player_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_player_id: UUID | None = None
    gameweek: int = Field(gt=0)
    source_gameweek_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    information_cutoff: datetime
    source_granularity: Literal["OFFICIAL_FPL_GAMEWEEK_PLAYER_AGGREGATE"] = (
        "OFFICIAL_FPL_GAMEWEEK_PLAYER_AGGREGATE"
    )
    minutes: int | None = Field(default=None, ge=0)
    starts: int | None = Field(default=None, ge=0)
    goals_scored: int | None = Field(default=None, ge=0)
    assists: int | None = Field(default=None, ge=0)
    own_goals: int | None = Field(default=None, ge=0)
    penalties_saved: int | None = Field(default=None, ge=0)
    penalties_missed: int | None = Field(default=None, ge=0)
    yellow_cards: int | None = Field(default=None, ge=0)
    red_cards: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    combined_cbi: int | None = Field(default=None, ge=0)
    tackles: int | None = Field(default=None, ge=0)
    recoveries: int | None = Field(default=None, ge=0)
    defensive_contribution: int | None = Field(default=None, ge=0)
    bonus: int | None = Field(default=None, ge=0)
    bps: int | None = None
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def sealed(self) -> Self:
        if self.semantic_sha256 != _hash(self):
            raise ValueError("gameweek evidence semantic hash does not match")
        return self


class CurrentPlayerHistoryEntry(_HistoryModel):
    official_fpl_element_id: int = Field(gt=0)
    current_player_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_player_id: UUID | None = None
    observations: tuple[CurrentPlayerGameweekEvidence, ...]
    quality: tuple[CurrentPlayerHistoryQuality, ...]
    reconciliation_minutes: Literal["MATCH", "FAILED", "NOT_APPLICABLE"]
    reconciliation_starts: Literal["MATCH", "FAILED", "NOT_APPLICABLE"]
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_and_sealed(self) -> Self:
        gameweeks = tuple(value.gameweek for value in self.observations)
        if gameweeks != tuple(sorted(gameweeks)) or len(gameweeks) != len(set(gameweeks)):
            raise ValueError("history observations are not unique and ordered")
        if any(
            value.official_fpl_element_id != self.official_fpl_element_id
            or value.current_player_identity_sha256 != self.current_player_identity_sha256
            or value.canonical_player_id != self.canonical_player_id
            for value in self.observations
        ):
            raise ValueError("history observation player binding differs")
        if self.semantic_sha256 != _hash(self):
            raise ValueError("history entry semantic hash does not match")
        return self


class CurrentPlayerHistoryFieldCoverage(FrozenModel):
    statistic: Statistic
    observed_rows: int = Field(ge=0)
    historical_rows: int = Field(ge=0)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if self.observed_rows > self.historical_rows:
            raise ValueError("field coverage exceeds historical rows")
        return self


class CurrentPlayerHistoryCoverage(_HistoryModel):
    observed_gameweeks: tuple[int, ...]
    earliest_observed_gameweek: int | None = Field(default=None, gt=0)
    latest_observed_gameweek: int | None = Field(default=None, gt=0)
    gameweek_count: int = Field(ge=0)
    current_player_count: int = Field(ge=0)
    players_with_any_history: int = Field(ge=0)
    players_with_zero_history: int = Field(ge=0)
    historical_row_count: int = Field(ge=0)
    field_coverage: tuple[CurrentPlayerHistoryFieldCoverage, ...]
    full_minutes_reconciliation_count: int = Field(ge=0)
    failed_minutes_reconciliation_count: int = Field(ge=0)
    full_starts_reconciliation_count: int = Field(ge=0)
    failed_starts_reconciliation_count: int = Field(ge=0)

    @model_validator(mode="after")
    def canonical(self) -> Self:
        if self.observed_gameweeks != tuple(sorted(self.observed_gameweeks)) or len(
            self.observed_gameweeks
        ) != len(set(self.observed_gameweeks)):
            raise ValueError("observed Gameweeks are not canonical")
        if self.gameweek_count != len(self.observed_gameweeks):
            raise ValueError("Gameweek count differs")
        if (self.earliest_observed_gameweek, self.latest_observed_gameweek) != (
            self.observed_gameweeks[0] if self.observed_gameweeks else None,
            self.observed_gameweeks[-1] if self.observed_gameweeks else None,
        ):
            raise ValueError("Gameweek range differs")
        if (
            self.players_with_any_history + self.players_with_zero_history
            != self.current_player_count
        ):
            raise ValueError("player coverage differs")
        if tuple(item.statistic for item in self.field_coverage) != _STATISTICS:
            raise ValueError("field coverage is incomplete or unordered")
        return self


class CurrentPlayerHistoryEvidence(_HistoryModel):
    schema_version: Literal["current-player-history-evidence-v1"] = (
        "current-player-history-evidence-v1"
    )
    model_input_status: Literal["EVIDENCE_ONLY_NOT_MODEL_INPUT"] = "EVIDENCE_ONLY_NOT_MODEL_INPUT"
    persistence_performed: Literal[False] = False
    new_network_requests: Literal[0] = 0
    source_granularity: Literal["OFFICIAL_FPL_GAMEWEEK_PLAYER_AGGREGATE"] = (
        "OFFICIAL_FPL_GAMEWEEK_PLAYER_AGGREGATE"
    )
    limitations: tuple[str, ...] = (
        "DIAGNOSTIC_ONLY_NOT_ALLOCATION_COMPONENT_EVIDENCE",
        "OFFICIAL_FPL_CBI_NOT_COMPONENT_SPLIT",
        "HISTORICAL_TEAM_MEMBERSHIP_NOT_PROVEN_BY_CURRENT_BOOTSTRAP",
    )
    target_gameweek: int = Field(gt=0)
    information_cutoff: datetime
    entries: tuple[CurrentPlayerHistoryEntry, ...]
    coverage: CurrentPlayerHistoryCoverage
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_and_sealed(self) -> Self:
        ids = tuple(value.official_fpl_element_id for value in self.entries)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("history entries are not unique and ordered")
        if self.coverage.current_player_count != len(self.entries):
            raise ValueError("coverage player count differs")
        if self.semantic_sha256 != _hash(self):
            raise ValueError("history evidence semantic hash does not match")
        return self

    def safe_summary(self) -> dict[str, object]:
        """Names, player values, bodies, and credentials are deliberately absent."""
        return {
            "target_gameweek": self.target_gameweek,
            "completed_source_gameweeks": self.coverage.observed_gameweeks,
            "current_player_count": self.coverage.current_player_count,
            "players_with_any_history": self.coverage.players_with_any_history,
            "players_with_zero_history": self.coverage.players_with_zero_history,
            "per_field_coverage_counts": {
                value.statistic: value.observed_rows for value in self.coverage.field_coverage
            },
            "full_minutes_reconciliation_count": self.coverage.full_minutes_reconciliation_count,
            "failed_minutes_reconciliation_count": self.coverage.failed_minutes_reconciliation_count,
            "full_starts_reconciliation_count": self.coverage.full_starts_reconciliation_count,
            "failed_starts_reconciliation_count": self.coverage.failed_starts_reconciliation_count,
            "evidence_semantic_hash": self.semantic_sha256,
            "model_input_status": self.model_input_status,
            "persistence_performed": self.persistence_performed,
            "new_network_requests": self.new_network_requests,
        }


def _hash(value: FrozenModel) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


def _seal[T: FrozenModel](value: T) -> T:
    payload = value.model_dump(mode="python")
    payload["semantic_sha256"] = _hash(value)
    return type(value).model_validate(payload)


def _observation(
    *,
    element_id: int,
    identity_hash: str,
    canonical_player_id: UUID | None,
    gameweek: int,
    gameweek_identity_hash: str,
    source_body_sha256: str,
    source_semantic_sha256: str,
    cutoff: datetime,
    stats: DirectLiveStats,
) -> CurrentPlayerGameweekEvidence:
    return _seal(
        CurrentPlayerGameweekEvidence.model_construct(
            official_fpl_element_id=element_id,
            current_player_identity_sha256=identity_hash,
            canonical_player_id=canonical_player_id,
            gameweek=gameweek,
            source_gameweek_identity_sha256=gameweek_identity_hash,
            source_body_sha256=source_body_sha256,
            source_semantic_sha256=source_semantic_sha256,
            information_cutoff=cutoff,
            minutes=stats.minutes,
            starts=stats.starts,
            goals_scored=stats.goals_scored,
            assists=stats.assists,
            own_goals=stats.own_goals,
            penalties_saved=stats.penalties_saved,
            penalties_missed=stats.penalties_missed,
            yellow_cards=stats.yellow_cards,
            red_cards=stats.red_cards,
            saves=stats.saves,
            combined_cbi=stats.clearances_blocks_interceptions,
            tackles=stats.tackles,
            recoveries=stats.recoveries,
            defensive_contribution=stats.defensive_contribution,
            bonus=stats.bonus,
            bps=stats.bps,
            semantic_sha256="0" * 64,
        )
    )


def _complete_window(gameweeks: tuple[int, ...]) -> bool:
    return bool(gameweeks) and gameweeks == tuple(range(1, gameweeks[-1] + 1))


def _reconciliation(
    observations: tuple[CurrentPlayerGameweekEvidence, ...],
    gameweeks: tuple[int, ...],
    statistic: Literal["minutes", "starts"],
    bootstrap_total: int | None,
) -> Literal["MATCH", "FAILED", "NOT_APPLICABLE"]:
    if (
        bootstrap_total is None
        or not _complete_window(gameweeks)
        or len(observations) != len(gameweeks)
    ):
        return "NOT_APPLICABLE"
    values = tuple(getattr(item, statistic) for item in observations)
    if any(value is None for value in values):
        return "NOT_APPLICABLE"
    return "MATCH" if sum(int(value) for value in values) == bootstrap_total else "FAILED"


def _quality(
    observations: tuple[CurrentPlayerGameweekEvidence, ...],
    gameweeks: tuple[int, ...],
    minutes: Literal["MATCH", "FAILED", "NOT_APPLICABLE"],
    starts: Literal["MATCH", "FAILED", "NOT_APPLICABLE"],
) -> tuple[CurrentPlayerHistoryQuality, ...]:
    if not observations:
        return (CurrentPlayerHistoryQuality.PLAYER_HISTORY_UNAVAILABLE,)
    values: list[CurrentPlayerHistoryQuality] = []
    if len(observations) != len(gameweeks) or any(
        getattr(item, statistic) is None for item in observations for statistic in _STATISTICS
    ):
        values.append(CurrentPlayerHistoryQuality.PARTIAL_FIELD_COVERAGE)
    else:
        values.append(CurrentPlayerHistoryQuality.COMPLETE)
    if minutes == "FAILED" or starts == "FAILED":
        values.append(CurrentPlayerHistoryQuality.BOOTSTRAP_RECONCILIATION_FAILED)
    elif minutes == "NOT_APPLICABLE" or starts == "NOT_APPLICABLE":
        values.append(CurrentPlayerHistoryQuality.BOOTSTRAP_RECONCILIATION_NOT_APPLICABLE)
    return tuple(values)


def _field_coverage(
    entries: Iterable[CurrentPlayerHistoryEntry],
) -> tuple[CurrentPlayerHistoryFieldCoverage, ...]:
    observations = tuple(item for entry in entries for item in entry.observations)
    return tuple(
        CurrentPlayerHistoryFieldCoverage(
            statistic=statistic,
            observed_rows=sum(getattr(item, statistic) is not None for item in observations),
            historical_rows=len(observations),
        )
        for statistic in _STATISTICS
    )


def build_current_player_history_evidence(
    snapshot: DirectFplSnapshot, *, canonical_player_ids: dict[int, UUID] | None = None
) -> CurrentPlayerHistoryEvidence:
    """Assemble sealed evidence from the snapshot's already-acquired event-live objects.

    The optional mapping is caller-supplied transient identity only; no team history is
    inferred.  This function performs neither network, filesystem, nor model activity.
    """
    cutoff = snapshot.fpl_input.provenance.information_cutoff
    events = {item.provider_event_id: item for item in snapshot.fpl_input.events}
    gameweeks = tuple(sorted(snapshot.live_by_gameweek))
    if len(gameweeks) > 12 or any(
        gameweek >= snapshot.target_gameweek
        or (event := events.get(gameweek)) is None
        or event.finished is not True
        or event.data_checked is not True
        for gameweek in gameweeks
    ):
        raise IngestionError("VALIDATION_FAILED", "event-live history window is not finalized")
    players = tuple(sorted(snapshot.fpl_input.players, key=lambda item: item.provider_element_id))
    player_ids = {item.provider_element_id for item in players}
    rows: dict[int, dict[int, DirectLiveStats]] = {}
    for gameweek in gameweeks:
        live = snapshot.live_by_gameweek[gameweek]
        if len({item.id for item in live.elements}) != len(live.elements):
            raise IngestionError("VALIDATION_FAILED", "event-live player IDs are duplicated")
        rows[gameweek] = {item.id: item.stats for item in live.elements if item.id in player_ids}
    entries: list[CurrentPlayerHistoryEntry] = []
    for player in players:
        observations = tuple(
            _observation(
                element_id=player.provider_element_id,
                identity_hash=player.identity.canonical_lookup_sha256,
                canonical_player_id=(canonical_player_ids or {}).get(player.provider_element_id),
                gameweek=gameweek,
                gameweek_identity_hash=events[gameweek].identity.canonical_lookup_sha256,
                source_body_sha256=snapshot.live_by_gameweek[gameweek].source_body_sha256,
                source_semantic_sha256=snapshot.live_by_gameweek[gameweek].semantic_sha256,
                cutoff=cutoff,
                stats=rows[gameweek][player.provider_element_id],
            )
            for gameweek in gameweeks
            if player.provider_element_id in rows[gameweek]
        )
        minutes = _reconciliation(observations, gameweeks, "minutes", player.season_minutes)
        starts = _reconciliation(observations, gameweeks, "starts", player.season_starts)
        entries.append(
            _seal(
                CurrentPlayerHistoryEntry.model_construct(
                    official_fpl_element_id=player.provider_element_id,
                    current_player_identity_sha256=player.identity.canonical_lookup_sha256,
                    canonical_player_id=(canonical_player_ids or {}).get(
                        player.provider_element_id
                    ),
                    observations=observations,
                    quality=_quality(observations, gameweeks, minutes, starts),
                    reconciliation_minutes=minutes,
                    reconciliation_starts=starts,
                    semantic_sha256="0" * 64,
                )
            )
        )
    entry_tuple = tuple(entries)
    coverage = CurrentPlayerHistoryCoverage(
        observed_gameweeks=gameweeks,
        earliest_observed_gameweek=gameweeks[0] if gameweeks else None,
        latest_observed_gameweek=gameweeks[-1] if gameweeks else None,
        gameweek_count=len(gameweeks),
        current_player_count=len(entry_tuple),
        players_with_any_history=sum(bool(item.observations) for item in entry_tuple),
        players_with_zero_history=sum(not item.observations for item in entry_tuple),
        historical_row_count=sum(len(item.observations) for item in entry_tuple),
        field_coverage=_field_coverage(entry_tuple),
        full_minutes_reconciliation_count=sum(
            item.reconciliation_minutes == "MATCH" for item in entry_tuple
        ),
        failed_minutes_reconciliation_count=sum(
            item.reconciliation_minutes == "FAILED" for item in entry_tuple
        ),
        full_starts_reconciliation_count=sum(
            item.reconciliation_starts == "MATCH" for item in entry_tuple
        ),
        failed_starts_reconciliation_count=sum(
            item.reconciliation_starts == "FAILED" for item in entry_tuple
        ),
    )
    return _seal(
        CurrentPlayerHistoryEvidence.model_construct(
            target_gameweek=snapshot.target_gameweek,
            information_cutoff=cutoff,
            entries=entry_tuple,
            coverage=coverage,
            semantic_sha256="0" * 64,
        )
    )


__all__ = [
    "CurrentPlayerGameweekEvidence",
    "CurrentPlayerHistoryCoverage",
    "CurrentPlayerHistoryEntry",
    "CurrentPlayerHistoryEvidence",
    "CurrentPlayerHistoryFieldCoverage",
    "CurrentPlayerHistoryQuality",
    "build_current_player_history_evidence",
]
