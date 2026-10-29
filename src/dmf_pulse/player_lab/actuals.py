"""Offline FPL-style GW-wide points adapter. This module enables no live route."""

from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field, StrictInt, StrictStr, ValidationError, field_validator, model_validator

from dmf_pulse.fpl_points.models import POINT_COMPONENT_NAMES
from dmf_pulse.player_lab.contracts import (
    FinalPlayerOutcome,
    LabModel,
    PlayerKey,
    Positive,
    SourceRef,
    seal,
)

IDENTIFIERS = {
    "minutes": "appearance",
    "goals_scored": "goals",
    "assists": "assists",
    "clean_sheets": "clean_sheet",
    "saves": "saves",
    "penalties_saved": "penalty_saves",
    "defensive_contribution": "defensive_contributions",
    "goals_conceded": "goals_conceded",
    "penalties_missed": "penalty_misses",
    "yellow_cards": "yellow_cards",
    "red_cards": "red_cards",
    "own_goals": "own_goals",
    "bonus": "bonus",
}


class ActualsError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ExplainStat(LabModel):
    identifier: StrictStr
    points: StrictInt
    value: Annotated[StrictInt, Field(ge=0)]


class FixtureExplain(LabModel):
    fixture: Positive
    stats: Annotated[tuple[ExplainStat, ...], Field(min_length=13, max_length=13)]


class LiveStats(LabModel):
    """Candidate schema: explicit official counts plus official total; additive drift blocks."""

    total_points: StrictInt
    minutes: Annotated[StrictInt, Field(ge=0)]
    goals_scored: Annotated[StrictInt, Field(ge=0)]
    assists: Annotated[StrictInt, Field(ge=0)]
    clean_sheets: Annotated[StrictInt, Field(ge=0)]
    saves: Annotated[StrictInt, Field(ge=0)]
    penalties_saved: Annotated[StrictInt, Field(ge=0)]
    defensive_contribution: Annotated[StrictInt, Field(ge=0)]
    goals_conceded: Annotated[StrictInt, Field(ge=0)]
    penalties_missed: Annotated[StrictInt, Field(ge=0)]
    yellow_cards: Annotated[StrictInt, Field(ge=0)]
    red_cards: Annotated[StrictInt, Field(ge=0)]
    own_goals: Annotated[StrictInt, Field(ge=0)]
    bonus: Annotated[StrictInt, Field(ge=0)]


class LiveElement(LabModel):
    id: Positive
    stats: LiveStats
    explain: Annotated[tuple[FixtureExplain, ...], Field(max_length=3)]


class LivePayload(LabModel):
    elements: Annotated[tuple[LiveElement, ...], Field(min_length=1, max_length=2000)]


class CanonicalOutcomePlayer(LabModel):
    official_id: Positive
    key: PlayerKey
    official_fixture_ids: tuple[Positive, ...]


class FinalityContext(LabModel):
    schema_version: Literal["offline-fpl-gw-actuals-candidate-v1"] = (
        "offline-fpl-gw-actuals-candidate-v1"
    )
    season: Literal["2026/27"]
    gameweek: Annotated[StrictInt, Field(ge=1, le=38)]
    request_path: StrictStr
    dataset_mode: Literal["SYNTHETIC", "PROSPECTIVE_REAL"]
    all_fixtures_finished: Literal[True]
    event_data_checked: Literal[True]
    last_final_whistle_at: datetime
    points_lock_at: datetime
    retrieved_at: datetime
    usable_at: datetime
    source: SourceRef
    players: Annotated[tuple[CanonicalOutcomePlayer, ...], Field(min_length=1, max_length=2000)]
    fixture_mapping: dict[Positive, UUID]
    finality_evidence_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    revision: Annotated[StrictInt, Field(ge=0)] = 0
    supersedes_by_official_id: dict[
        Positive, Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    ] = Field(default_factory=dict)
    correction_finalized_at: datetime | None = None

    @field_validator("all_fixtures_finished", "event_data_checked", mode="before")
    @classmethod
    def exactly_true(cls, value: object) -> object:
        if value is not True:
            raise ValueError("explicit true finality evidence required")
        return value

    @model_validator(mode="after")
    def qualified_context(self) -> Self:
        local_last = self.last_final_whistle_at.astimezone(ZoneInfo("Europe/London"))
        expected_lock = datetime.combine(
            local_last.date() + timedelta(days=1), time(9), ZoneInfo("Europe/London")
        ).astimezone(UTC)
        if (
            self.points_lock_at != expected_lock
            or not self.points_lock_at <= self.retrieved_at <= self.usable_at
        ):
            raise ValueError("interim or invalid official lock evidence")
        if self.request_path != f"/api/event/{self.gameweek}/live/":
            raise ValueError("request route/Gameweek differs")
        if self.source.observed_at != self.retrieved_at or self.source.usable_at != self.usable_at:
            raise ValueError("source vintage differs")
        ids = tuple(item.official_id for item in self.players)
        canonical = tuple(item.key.player_id for item in self.players)
        if len(ids) != len(set(ids)) or len(canonical) != len(set(canonical)):
            raise ValueError("player mapping is not bijective")
        if (self.revision == 0 and self.supersedes_by_official_id) or (
            self.revision > 0 and set(self.supersedes_by_official_id) != set(ids)
        ):
            raise ValueError("correction snapshot requires complete predecessor coverage")
        if (self.revision == 0) != (self.correction_finalized_at is None):
            raise ValueError("correction requires explicit later finalization time")
        if (
            self.correction_finalized_at is not None
            and not self.points_lock_at < self.correction_finalized_at <= self.retrieved_at
        ):
            raise ValueError("correction finalization chronology invalid")
        if len(set(self.fixture_mapping.values())) != len(self.fixture_mapping):
            raise ValueError("fixture mapping is not bijective")
        for player in self.players:
            if player.key.season != self.season or player.key.gameweek != self.gameweek:
                raise ValueError("canonical season/Gameweek differs")
            fixture_ids = player.official_fixture_ids
            if fixture_ids != tuple(sorted(set(fixture_ids))):
                raise ValueError("fixture coverage missing or ambiguous")
            if not set(fixture_ids) <= set(self.fixture_mapping) or player.key.fixture_ids != tuple(
                sorted((self.fixture_mapping[value] for value in fixture_ids), key=str)
            ):
                raise ValueError("canonical fixture mapping differs")
        return self


class ActualsQuality(LabModel):
    expected_players: int
    observed_players: int
    matched_players: int
    missing_players: Literal[0] = 0
    duplicate_players: Literal[0] = 0
    component_count: Literal[13] = 13
    labels: tuple[FinalPlayerOutcome, ...]


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def parse_actuals(body: bytes, context: FinalityContext) -> ActualsQuality:
    """Pure candidate-schema validation, not permission to acquire or retain the result."""
    if len(body) > 4_000_000:
        raise ActualsError("ACTUALS_RESOURCE_LIMIT")
    try:
        # Explicit duplicate/depth/nonfinite rejection before typed decoding.
        def reject_constant(value: str) -> object:
            raise ValueError(value)

        json.loads(body, object_pairs_hook=_object, parse_constant=reject_constant)
        context = FinalityContext.model_validate_json(context.model_dump_json())
        payload = LivePayload.model_validate_json(body)
    except (ValueError, TypeError, RecursionError, UnicodeError, ValidationError):
        raise ActualsError("ACTUALS_SCHEMA_OR_FINALITY_INVALID") from None
    expected = {item.official_id: item for item in context.players}
    observed = tuple(item.id for item in payload.elements)
    if len(observed) != len(set(observed)):
        raise ActualsError("ACTUALS_DUPLICATE_PLAYER")
    if set(observed) != set(expected):
        raise ActualsError("ACTUALS_COHORT_MISMATCH")
    labels = []
    for player in payload.elements:
        mapped = expected[player.id]
        fixtures = tuple(item.fixture for item in player.explain)
        if len(fixtures) != len(set(fixtures)) or set(fixtures) != set(mapped.official_fixture_ids):
            raise ActualsError("ACTUALS_FIXTURE_MISMATCH")
        component_lists: dict[str, list[int]] = {name: [] for name in POINT_COMPONENT_NAMES}
        values: dict[str, list[int]] = {name: [] for name in IDENTIFIERS}
        for fixture in player.explain:
            identifiers = tuple(item.identifier for item in fixture.stats)
            if len(set(identifiers)) != 13 or set(identifiers) != set(IDENTIFIERS):
                raise ActualsError("ACTUALS_COMPONENT_SCHEMA_DRIFT")
            for item in fixture.stats:
                component_lists[IDENTIFIERS[item.identifier]].append(item.points)
                values[item.identifier].append(item.value)
        if any(sum(counts) != getattr(player.stats, name) for name, counts in values.items()):
            raise ActualsError("ACTUALS_COUNT_RECONCILIATION_FAILED")
        components = {name: sum(points) for name, points in component_lists.items()}
        if sum(components.values()) != player.stats.total_points:
            raise ActualsError("ACTUALS_TOTAL_RECONCILIATION_FAILED")
        labels.append(
            seal(
                FinalPlayerOutcome.model_construct(
                    key=mapped.key,
                    dataset_mode=context.dataset_mode,
                    total_points=player.stats.total_points,
                    components=components,
                    finalized_at=context.correction_finalized_at or context.points_lock_at,
                    original_points_lock_at=context.points_lock_at,
                    finality_evidence_sha256=context.finality_evidence_sha256,
                    retrieved_at=context.retrieved_at,
                    usable_at=context.usable_at,
                    source=context.source,
                    semantic_sha256="0" * 64,
                    revision=context.revision,
                    supersedes_sha256=context.supersedes_by_official_id.get(player.id),
                )
            )
        )
    return ActualsQuality(
        expected_players=len(expected),
        observed_players=len(observed),
        matched_players=len(labels),
        labels=tuple(sorted(labels, key=lambda item: item.key.target_id())),
    )
