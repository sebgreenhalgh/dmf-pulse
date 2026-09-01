"""Strict transient parsing and bounded acquisition for direct official-FPL facts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    OFFICIAL_DIRECT_PROFILE_ID,
    CurrentFplDirectInputRequest,
    CurrentFplInputBundle,
    CurrentFplInputService,
)
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplResource,
)
from dmf_pulse.ingestion.fpl.manager_provider import (
    ProviderCurrentTeam,
    parse_provider_current_team,
)
from dmf_pulse.ingestion.fpl.parser import BootstrapPayload, FplResource, parse_fpl_payload

PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class DirectEntry(_ProviderModel):
    id: PositiveInt
    started_event: PositiveInt
    summary_overall_points: NonNegativeInt | None = None
    summary_overall_rank: PositiveInt | None = None


class DirectEntryHistoryRow(_ProviderModel):
    event: PositiveInt
    points: StrictInt
    total_points: StrictInt
    overall_rank: PositiveInt | None = None
    bank: NonNegativeInt
    value: PositiveInt
    event_transfers: NonNegativeInt
    event_transfers_cost: NonNegativeInt


class DirectEntryHistory(_ProviderModel):
    current: tuple[DirectEntryHistoryRow, ...]


class DirectTransfer(_ProviderModel):
    element_in: PositiveInt
    element_in_cost: PositiveInt
    element_out: PositiveInt
    element_out_cost: PositiveInt
    event: PositiveInt
    time: datetime

    @field_validator("time")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("transfer time must be aware")
        return value.astimezone(UTC)


class DirectPublicPick(_ProviderModel):
    element: PositiveInt
    position: PositiveInt
    multiplier: NonNegativeInt


class DirectPublicPicks(_ProviderModel):
    picks: tuple[DirectPublicPick, ...] = Field(min_length=1)


class DirectLiveStats(_ProviderModel):
    minutes: NonNegativeInt | None = None
    starts: NonNegativeInt | None = None


class DirectLiveElement(_ProviderModel):
    id: PositiveInt
    stats: DirectLiveStats


class DirectEventLive(_ProviderModel):
    elements: tuple[DirectLiveElement, ...]


class DirectFplSnapshot(_ProviderModel):
    captured_at: datetime
    target_gameweek: PositiveInt
    fpl_input: CurrentFplInputBundle
    entry: DirectEntry
    history: DirectEntryHistory
    transfers: tuple[DirectTransfer, ...]
    latest_public_picks: DirectPublicPicks | None
    current_team: ProviderCurrentTeam
    live_by_gameweek: dict[int, DirectEventLive]
    request_count: PositiveInt
    endpoint_classes: tuple[str, ...]

    @field_validator("captured_at")
    @classmethod
    def normalize_captured_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("capture time must be aware")
        return value.astimezone(UTC)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate provider key")
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise ValueError(f"non-finite provider constant is forbidden: {value}")


def _parse_json[ProviderValue: BaseModel](
    body: bytes, model: type[ProviderValue], *, label: str
) -> ProviderValue:
    try:
        json.loads(body.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        return model.model_validate_json(body)
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise IngestionError(
            "VALIDATION_FAILED", f"official FPL {label} failed schema validation"
        ) from None


def parse_direct_entry(body: bytes) -> DirectEntry:
    return _parse_json(body, DirectEntry, label="entry")


def parse_direct_history(body: bytes) -> DirectEntryHistory:
    value = _parse_json(body, DirectEntryHistory, label="history")
    events = tuple(item.event for item in value.current)
    if events != tuple(sorted(events)) or len(events) != len(set(events)):
        raise IngestionError("VALIDATION_FAILED", "official FPL history is not canonical")
    return value


def parse_direct_transfers(body: bytes) -> tuple[DirectTransfer, ...]:
    try:
        raw = json.loads(body.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        if not isinstance(raw, list):
            raise ValueError("transfers must be a list")
        values = TypeAdapter(tuple[DirectTransfer, ...]).validate_json(body)
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise IngestionError(
            "VALIDATION_FAILED", "official FPL transfers failed schema validation"
        ) from None
    if len({(item.time, item.element_in, item.element_out) for item in values}) != len(values):
        raise IngestionError("VALIDATION_FAILED", "official FPL transfers are duplicated")
    return tuple(sorted(values, key=lambda item: (item.time, item.element_in, item.element_out)))


def parse_direct_public_picks(body: bytes) -> DirectPublicPicks:
    value = _parse_json(body, DirectPublicPicks, label="public picks")
    if len(value.picks) != 15 or len({item.element for item in value.picks}) != 15:
        raise IngestionError("VALIDATION_FAILED", "official FPL public picks are incomplete")
    return value


def parse_direct_event_live(body: bytes) -> DirectEventLive:
    value = _parse_json(body, DirectEventLive, label="event live")
    ids = tuple(item.id for item in value.elements)
    if len(ids) != len(set(ids)):
        raise IngestionError("VALIDATION_FAILED", "official FPL live elements are duplicated")
    return value


def _target_gameweek(
    bootstrap_body: bytes, *, captured_at: datetime
) -> tuple[int, tuple[int, ...]]:
    parsed = parse_fpl_payload(FplResource.BOOTSTRAP, bootstrap_body)
    if not isinstance(parsed.payload, BootstrapPayload):
        raise IngestionError("INTERNAL_INVARIANT", "official FPL bootstrap type is invalid")
    events = parsed.payload.events
    next_events = tuple(item for item in events if item.is_next is True)
    current_events = tuple(item for item in events if item.is_current is True)
    if len(next_events) > 1 or len(current_events) > 1:
        raise IngestionError("TARGET_GAMEWEEK_UNRESOLVED", "target Gameweek flags conflict")
    unfinished = tuple(
        item for item in events if item.finished is not True and item.deadline_time > captured_at
    )
    selected = next_events if len(next_events) == 1 else unfinished[:1]
    if len(selected) != 1:
        raise IngestionError("TARGET_GAMEWEEK_UNRESOLVED", "target Gameweek is ambiguous")
    target = selected[0]
    if target.deadline_time <= captured_at:
        raise IngestionError("TARGET_DEADLINE_PASSED", "target Gameweek deadline has passed")
    if current_events and target.id <= current_events[0].id:
        raise IngestionError("TARGET_GAMEWEEK_UNRESOLVED", "current and next Gameweeks conflict")
    finished = tuple(
        item.id
        for item in events
        if item.id < target.id and item.finished is True and item.data_checked is True
    )
    return target.id, finished[-12:]


def acquire_direct_fpl_snapshot(
    client: DirectFplClient,
    *,
    entry_id: int,
    captured_at: datetime,
) -> DirectFplSnapshot:
    """Acquire one public-first current snapshot and discard all response bytes after parsing."""

    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise IngestionError("VALIDATION_FAILED", "capture time must be aware")
    captured = captured_at.astimezone(UTC)
    bootstrap = client.fetch(DirectFplResource.BOOTSTRAP)
    target_gameweek, live_gameweeks = _target_gameweek(bootstrap, captured_at=captured)
    fixtures = client.fetch(DirectFplResource.FIXTURES)
    fpl_input = CurrentFplInputService(clock=lambda: captured).compile_direct(
        CurrentFplDirectInputRequest(
            competition_key="PL",
            season_code="2026/27",
            target_gameweek=target_gameweek,
            captured_at=captured,
            information_cutoff=captured,
            rights_profile_id=OFFICIAL_DIRECT_PROFILE_ID,
        ),
        bootstrap_body=bootstrap,
        fixtures_body=fixtures,
    )
    del bootstrap, fixtures
    entry = parse_direct_entry(client.fetch(DirectFplResource.ENTRY, entry_id=entry_id))
    if entry.id != entry_id:
        raise IngestionError("MAPPING_CONFLICT", "official FPL entry identity differs")
    history = parse_direct_history(client.fetch(DirectFplResource.HISTORY, entry_id=entry_id))
    transfers = parse_direct_transfers(client.fetch(DirectFplResource.TRANSFERS, entry_id=entry_id))
    latest_public_picks = None
    if live_gameweeks:
        latest_public_picks = parse_direct_public_picks(
            client.fetch(DirectFplResource.PICKS, entry_id=entry_id, gameweek=live_gameweeks[-1])
        )
    current_team = parse_provider_current_team(
        client.fetch(DirectFplResource.MY_TEAM, entry_id=entry_id)
    )
    live = {
        gameweek: parse_direct_event_live(
            client.fetch(DirectFplResource.EVENT_LIVE, gameweek=gameweek)
        )
        for gameweek in live_gameweeks
    }
    return DirectFplSnapshot(
        captured_at=captured,
        target_gameweek=target_gameweek,
        fpl_input=fpl_input,
        entry=entry,
        history=history,
        transfers=transfers,
        latest_public_picks=latest_public_picks,
        current_team=current_team,
        live_by_gameweek=live,
        request_count=client.request_count,
        endpoint_classes=tuple(item.value for item in client.endpoint_classes),
    )


__all__ = [
    "DirectEntry",
    "DirectEntryHistory",
    "DirectEntryHistoryRow",
    "DirectEventLive",
    "DirectFplSnapshot",
    "DirectLiveElement",
    "DirectLiveStats",
    "DirectPublicPicks",
    "DirectTransfer",
    "acquire_direct_fpl_snapshot",
    "parse_direct_entry",
    "parse_direct_event_live",
    "parse_direct_history",
    "parse_direct_public_picks",
    "parse_direct_transfers",
]
