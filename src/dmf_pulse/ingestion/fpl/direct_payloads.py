"""Strict transient parsing and bounded acquisition for direct official-FPL facts."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from dmf_pulse.assurance.canonical import canonical_sha256
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


class DirectEntryOverallPointsStatus(StrEnum):
    DIRECT_UNAMBIGUOUS = "DIRECT_UNAMBIGUOUS"
    DUPLICATE_UNAMBIGUOUS = "DUPLICATE_UNAMBIGUOUS"


class DirectEntryOverallRankStatus(StrEnum):
    DIRECT_UNAMBIGUOUS = "DIRECT_UNAMBIGUOUS"
    DUPLICATE_UNAMBIGUOUS = "DUPLICATE_UNAMBIGUOUS"
    HISTORY_RECONCILED = "HISTORY_RECONCILED"
    AMBIGUOUS_UNAVAILABLE = "AMBIGUOUS_UNAVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


CURRENT_FPL_ENTRY_DUPLICATE_SUMMARY_FIELDS_OBSERVED = (
    "CURRENT_FPL_ENTRY_DUPLICATE_SUMMARY_FIELDS_OBSERVED"
)
CURRENT_FPL_ENTRY_EVENT_RANK_AMBIGUOUS_DISCARDED = (
    "CURRENT_FPL_ENTRY_EVENT_RANK_AMBIGUOUS_DISCARDED"
)
CURRENT_FPL_ENTRY_OVERALL_RANK_RECONCILED_FROM_HISTORY_V1 = (
    "CURRENT_FPL_ENTRY_OVERALL_RANK_RECONCILED_FROM_HISTORY_V1"
)
CURRENT_FPL_ENTRY_OVERALL_RANK_AMBIGUOUS_UNAVAILABLE = (
    "CURRENT_FPL_ENTRY_OVERALL_RANK_AMBIGUOUS_UNAVAILABLE"
)


class DirectEntryQuality(_ProviderModel):
    """Bounded source-quality facts; never provider values or response bytes."""

    duplicate_summary_fields: tuple[str, ...] = ()
    overall_points_status: DirectEntryOverallPointsStatus
    overall_rank_status: DirectEntryOverallRankStatus
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def quality_is_canonical(self) -> Self:
        allowed = {
            "summary_event_points",
            "summary_event_rank",
            "summary_overall_points",
            "summary_overall_rank",
        }
        if (
            self.duplicate_summary_fields != tuple(sorted(set(self.duplicate_summary_fields)))
            or not set(self.duplicate_summary_fields) <= allowed
            or self.warnings != tuple(sorted(set(self.warnings)))
        ):
            raise ValueError("entry source-quality facts are not canonical")
        return self


class DirectEntryResolution(_ProviderModel):
    entry: DirectEntry
    quality: DirectEntryQuality

    def require_known_overall_rank(self) -> int:
        """Guard future rank-aware callers against treating ambiguity as a real rank."""

        if self.entry.summary_overall_rank is None:
            raise IngestionError(
                "OVERALL_RANK_UNAVAILABLE", "official FPL overall rank is unavailable"
            )
        return self.entry.summary_overall_rank


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
    goals_scored: NonNegativeInt | None = None
    assists: NonNegativeInt | None = None
    own_goals: NonNegativeInt | None = None
    penalties_saved: NonNegativeInt | None = None
    penalties_missed: NonNegativeInt | None = None
    yellow_cards: NonNegativeInt | None = None
    red_cards: NonNegativeInt | None = None
    saves: NonNegativeInt | None = None
    clearances_blocks_interceptions: NonNegativeInt | None = None
    tackles: NonNegativeInt | None = None
    recoveries: NonNegativeInt | None = None
    defensive_contribution: NonNegativeInt | None = None
    bonus: NonNegativeInt | None = None
    bps: StrictInt | None = None


class DirectLiveElement(_ProviderModel):
    id: PositiveInt
    stats: DirectLiveStats


class _DirectEventLivePayload(_ProviderModel):
    elements: tuple[DirectLiveElement, ...]


class DirectEventLive(_DirectEventLivePayload):
    """Parsed event-live facts plus non-retained safe source lineage."""

    source_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def source_lineage_is_sealed(self) -> Self:
        if self.semantic_sha256 != canonical_sha256(
            {"elements": [item.model_dump(mode="json") for item in self.elements]}
        ):
            raise ValueError("event-live semantic hash does not match")
        return self


class _TransientContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CurrentPenaltyHierarchyEntry(_TransientContract):
    official_fpl_element_id: PositiveInt
    official_fpl_team_id: PositiveInt
    penalties_order: PositiveInt


class CurrentPenaltyHierarchyTeamStatus(StrEnum):
    """Whether provider rows can be used without inventing an ordinal tie-break."""

    USABLE_UNIQUE_ORDER = "USABLE_UNIQUE_ORDER"
    AMBIGUOUS_DUPLICATE_ORDER = "AMBIGUOUS_DUPLICATE_ORDER"
    NO_PUBLISHED_ORDER = "NO_PUBLISHED_ORDER"


class CurrentPenaltyHierarchyTeam(_TransientContract):
    official_fpl_team_id: PositiveInt
    status: CurrentPenaltyHierarchyTeamStatus


CURRENT_FPL_PENALTY_HIERARCHY_AMBIGUOUS = "CURRENT_FPL_PENALTY_HIERARCHY_AMBIGUOUS"
CURRENT_FPL_PENALTY_HIERARCHY_UNAVAILABLE = "CURRENT_FPL_PENALTY_HIERARCHY_UNAVAILABLE"


class CurrentPenaltyHierarchy(_TransientContract):
    """Memory-only provider-published current penalty-role hierarchy."""

    schema_version: Literal["current-fpl-penalty-hierarchy-v2"] = "current-fpl-penalty-hierarchy-v2"
    source_class: Literal["OFFICIAL_FPL_BOOTSTRAP_PROVIDER_PUBLISHED"] = (
        "OFFICIAL_FPL_BOOTSTRAP_PROVIDER_PUBLISHED"
    )
    observed_at: datetime
    information_cutoff: datetime
    source_bootstrap_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[CurrentPenaltyHierarchyEntry, ...]
    teams: Annotated[tuple[CurrentPenaltyHierarchyTeam, ...], Field(min_length=1)]
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def warnings(self) -> tuple[str, ...]:
        values: list[str] = []
        statuses = {item.status for item in self.teams}
        if CurrentPenaltyHierarchyTeamStatus.AMBIGUOUS_DUPLICATE_ORDER in statuses:
            values.append(CURRENT_FPL_PENALTY_HIERARCHY_AMBIGUOUS)
        if CurrentPenaltyHierarchyTeamStatus.NO_PUBLISHED_ORDER in statuses:
            values.append(CURRENT_FPL_PENALTY_HIERARCHY_UNAVAILABLE)
        return tuple(values)

    @field_validator("observed_at", "information_cutoff")
    @classmethod
    def normalize_times(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("current penalty hierarchy time must be aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def hierarchy_is_canonical_and_sealed(self) -> Self:
        if self.observed_at > self.information_cutoff:
            raise ValueError("current penalty hierarchy is post-cutoff")
        expected = tuple(
            sorted(
                self.entries,
                key=lambda item: (
                    item.official_fpl_team_id,
                    item.penalties_order,
                    item.official_fpl_element_id,
                ),
            )
        )
        player_ids = tuple(item.official_fpl_element_id for item in self.entries)
        if self.entries != expected or len(player_ids) != len(set(player_ids)):
            raise ValueError("current penalty hierarchy player rows are not unique and canonical")
        expected_teams = tuple(sorted(self.teams, key=lambda item: item.official_fpl_team_id))
        team_ids = tuple(item.official_fpl_team_id for item in self.teams)
        if self.teams != expected_teams or len(team_ids) != len(set(team_ids)):
            raise ValueError("current penalty hierarchy team records are not unique and canonical")
        if not {item.official_fpl_team_id for item in self.entries} <= set(team_ids):
            raise ValueError("current penalty hierarchy row is outside the team catalogue")
        for team in self.teams:
            orders = tuple(
                item.penalties_order
                for item in self.entries
                if item.official_fpl_team_id == team.official_fpl_team_id
            )
            expected_status = (
                CurrentPenaltyHierarchyTeamStatus.NO_PUBLISHED_ORDER
                if not orders
                else (
                    CurrentPenaltyHierarchyTeamStatus.USABLE_UNIQUE_ORDER
                    if len(orders) == len(set(orders))
                    else CurrentPenaltyHierarchyTeamStatus.AMBIGUOUS_DUPLICATE_ORDER
                )
            )
            if team.status is not expected_status:
                raise ValueError("current penalty hierarchy team usability status differs")
        if self.semantic_sha256 != current_penalty_hierarchy_sha256(self):
            raise ValueError("current penalty hierarchy semantic hash does not match")
        return self


def current_penalty_hierarchy_sha256(value: CurrentPenaltyHierarchy) -> str:
    return canonical_sha256(
        {
            "entries": [item.model_dump(mode="json") for item in value.entries],
            "information_cutoff": value.information_cutoff.isoformat(),
            "observed_at": value.observed_at.isoformat(),
            "schema_version": value.schema_version,
            "source_bootstrap_payload_sha256": value.source_bootstrap_payload_sha256,
            "source_class": value.source_class,
            "teams": [item.model_dump(mode="json") for item in value.teams],
        }
    )


def build_current_penalty_hierarchy(
    bootstrap: BootstrapPayload,
    *,
    observed_at: datetime,
    information_cutoff: datetime,
    source_bootstrap_payload_sha256: str,
) -> CurrentPenaltyHierarchy:
    """Extract additive ``penalties_order`` values without retaining the response body."""

    team_ids = {team.id for team in bootstrap.teams}
    entries: list[CurrentPenaltyHierarchyEntry] = []
    try:
        # Iterate the provider catalogue rather than assuming a fixed league-team count.
        for team_id in sorted(team_ids):
            for player in bootstrap.elements:
                if player.team != team_id:
                    continue
                extra = player.model_extra or {}
                if "penalties_order" not in extra or extra["penalties_order"] is None:
                    continue
                order = extra["penalties_order"]
                if isinstance(order, bool) or not isinstance(order, int):
                    raise ValueError("published penalty order must be an integer")
                if order == 0:
                    continue
                if order < 0:
                    raise ValueError("published penalty order must not be negative")
                entries.append(
                    CurrentPenaltyHierarchyEntry(
                        official_fpl_element_id=player.id,
                        official_fpl_team_id=player.team,
                        penalties_order=order,
                    )
                )
        ordered = tuple(
            sorted(
                entries,
                key=lambda item: (
                    item.official_fpl_team_id,
                    item.penalties_order,
                    item.official_fpl_element_id,
                ),
            )
        )
        teams = tuple(
            CurrentPenaltyHierarchyTeam(
                official_fpl_team_id=team_id,
                status=(
                    CurrentPenaltyHierarchyTeamStatus.NO_PUBLISHED_ORDER
                    if not (
                        orders := tuple(
                            item.penalties_order
                            for item in ordered
                            if item.official_fpl_team_id == team_id
                        )
                    )
                    else (
                        CurrentPenaltyHierarchyTeamStatus.USABLE_UNIQUE_ORDER
                        if len(orders) == len(set(orders))
                        else CurrentPenaltyHierarchyTeamStatus.AMBIGUOUS_DUPLICATE_ORDER
                    )
                ),
            )
            for team_id in sorted(team_ids)
        )
        provisional = CurrentPenaltyHierarchy.model_construct(
            observed_at=observed_at,
            information_cutoff=information_cutoff,
            source_bootstrap_payload_sha256=source_bootstrap_payload_sha256,
            entries=ordered,
            teams=teams,
            semantic_sha256="0" * 64,
        )
        sealed = provisional.model_copy(
            update={"semantic_sha256": current_penalty_hierarchy_sha256(provisional)}
        )
        return CurrentPenaltyHierarchy.model_validate(sealed.model_dump(mode="python"))
    except (ValidationError, ValueError):
        raise IngestionError(
            "VALIDATION_FAILED", "official FPL current penalty hierarchy failed validation"
        ) from None


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
    current_penalty_hierarchy: CurrentPenaltyHierarchy | None = None
    entry_quality: DirectEntryQuality | None = None

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
    return resolve_direct_entry(body).entry


class _EntryObjectPairs(list[tuple[str, object]]):
    """A JSON object whose occurrences have not yet been collapsed."""


def _entry_object_pairs(pairs: list[tuple[str, object]]) -> _EntryObjectPairs:
    return _EntryObjectPairs(pairs)


def _entry_value(value: object) -> object:
    if isinstance(value, _EntryObjectPairs):
        result: dict[str, object] = {}
        for key, nested in value:
            if key in result:
                raise ValueError("duplicate provider key")
            result[key] = _entry_value(nested)
        return result
    if isinstance(value, list):
        return [_entry_value(item) for item in value]
    return value


def _entry_summary_value(value: object, adapter: TypeAdapter[object]) -> object:
    return adapter.validate_python(value)


def _entry_top_level(
    pairs: _EntryObjectPairs,
) -> tuple[dict[str, object], dict[str, tuple[object, ...]]]:
    occurrences: dict[str, list[object]] = {}
    for key, value in pairs:
        occurrences.setdefault(key, []).append(_entry_value(value))
    allowed = {
        "summary_event_points",
        "summary_event_rank",
        "summary_overall_points",
        "summary_overall_rank",
    }
    result: dict[str, object] = {}
    retained: dict[str, tuple[object, ...]] = {}
    points_adapter: TypeAdapter[object] = TypeAdapter(NonNegativeInt | None)
    rank_adapter: TypeAdapter[object] = TypeAdapter(PositiveInt | None)
    for key, values_list in occurrences.items():
        values = tuple(values_list)
        adapter = (
            points_adapter
            if key in {"summary_event_points", "summary_overall_points"}
            else rank_adapter
        )
        if len(values) == 1:
            result[key] = _entry_summary_value(values[0], adapter) if key in allowed else values[0]
            continue
        if key not in allowed:
            raise ValueError("duplicate provider key")
        checked = tuple(_entry_summary_value(item, adapter) for item in values)
        if key in {"summary_event_points", "summary_overall_points"} and len(set(checked)) != 1:
            raise ValueError("conflicting provider summary points")
        if key == "summary_overall_rank" and len(set(checked)) == 1:
            result[key] = checked[0]
        elif key == "summary_event_rank":
            result[key] = checked[0] if len(set(checked)) == 1 else None
        elif key in {"summary_event_points", "summary_overall_points"}:
            result[key] = checked[0]
        retained[key] = checked
    return result, retained


def resolve_direct_entry(
    body: bytes,
    *,
    history: DirectEntryHistory | None = None,
    target_gameweek: int | None = None,
) -> DirectEntryResolution:
    """Resolve the sole documented entry-summary duplicate serialization, fail closed otherwise."""

    try:
        raw = json.loads(
            body.decode("utf-8"), object_pairs_hook=_entry_object_pairs, parse_constant=_constant
        )
        if not isinstance(raw, _EntryObjectPairs):
            raise ValueError("entry must be an object")
        payload, duplicates = _entry_top_level(raw)
        entry = DirectEntry.model_validate(payload)
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise IngestionError(
            "VALIDATION_FAILED", "official FPL entry failed schema validation"
        ) from None
    duplicate_fields = tuple(sorted(duplicates))
    warnings: set[str] = (
        {CURRENT_FPL_ENTRY_DUPLICATE_SUMMARY_FIELDS_OBSERVED} if duplicate_fields else set()
    )
    points_status = (
        DirectEntryOverallPointsStatus.DUPLICATE_UNAMBIGUOUS
        if "summary_overall_points" in duplicates
        else DirectEntryOverallPointsStatus.DIRECT_UNAMBIGUOUS
    )
    rank_status = DirectEntryOverallRankStatus.DIRECT_UNAMBIGUOUS
    rank_values = duplicates.get("summary_overall_rank")
    if rank_values is not None and len(set(rank_values)) == 1:
        rank_status = DirectEntryOverallRankStatus.DUPLICATE_UNAMBIGUOUS
    elif rank_values is not None:
        matching: tuple[DirectEntryHistoryRow, ...] = ()
        if history is not None and target_gameweek is not None and target_gameweek > 1:
            matching = tuple(
                row
                for row in history.current
                if row.event == target_gameweek - 1
                and row.total_points == entry.summary_overall_points
                and row.overall_rank is not None
            )
            if history.current[-1:] != matching:
                matching = ()
        candidates = set(rank_values)
        if len(matching) == 1 and matching[0].overall_rank in candidates:
            entry = entry.model_copy(update={"summary_overall_rank": matching[0].overall_rank})
            rank_status = DirectEntryOverallRankStatus.HISTORY_RECONCILED
            warnings.add(CURRENT_FPL_ENTRY_OVERALL_RANK_RECONCILED_FROM_HISTORY_V1)
        else:
            entry = entry.model_copy(update={"summary_overall_rank": None})
            rank_status = DirectEntryOverallRankStatus.AMBIGUOUS_UNAVAILABLE
            warnings.add(CURRENT_FPL_ENTRY_OVERALL_RANK_AMBIGUOUS_UNAVAILABLE)
    elif entry.summary_overall_rank is None:
        rank_status = DirectEntryOverallRankStatus.UNAVAILABLE
    if "summary_event_rank" in duplicates and len(set(duplicates["summary_event_rank"])) > 1:
        warnings.add(CURRENT_FPL_ENTRY_EVENT_RANK_AMBIGUOUS_DISCARDED)
    return DirectEntryResolution(
        entry=entry,
        quality=DirectEntryQuality(
            duplicate_summary_fields=duplicate_fields,
            overall_points_status=points_status,
            overall_rank_status=rank_status,
            warnings=tuple(sorted(warnings)),
        ),
    )


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
    value = _parse_json(body, _DirectEventLivePayload, label="event live")
    ids = tuple(item.id for item in value.elements)
    if len(ids) != len(set(ids)):
        raise IngestionError("VALIDATION_FAILED", "official FPL live elements are duplicated")
    return DirectEventLive(
        elements=value.elements,
        source_body_sha256=sha256(body).hexdigest(),
        semantic_sha256=canonical_sha256(
            {"elements": [item.model_dump(mode="json") for item in value.elements]}
        ),
    )


def _target_gameweek(
    bootstrap: BootstrapPayload, *, captured_at: datetime
) -> tuple[int, tuple[int, ...]]:
    events = bootstrap.events
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
    clock: Callable[[], datetime] | None = None,
) -> DirectFplSnapshot:
    """Acquire one public-first current snapshot and discard all response bytes after parsing."""

    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise IngestionError("VALIDATION_FAILED", "capture time must be aware")
    information_cutoff = captured_at.astimezone(UTC)
    active_clock = clock or (lambda: information_cutoff)
    bootstrap = client.fetch(DirectFplResource.BOOTSTRAP)
    observed_at = active_clock()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise IngestionError("INTERNAL_INVARIANT", "direct FPL clock must be aware")
    observed_at = observed_at.astimezone(UTC)
    if observed_at > information_cutoff:
        raise IngestionError("POST_CUTOFF", "official FPL response arrived after the cutoff")
    parsed_bootstrap = parse_fpl_payload(FplResource.BOOTSTRAP, bootstrap)
    if not isinstance(parsed_bootstrap.payload, BootstrapPayload):
        raise IngestionError("INTERNAL_INVARIANT", "official FPL bootstrap type is invalid")
    target_gameweek, live_gameweeks = _target_gameweek(
        parsed_bootstrap.payload, captured_at=observed_at
    )
    penalty_hierarchy = build_current_penalty_hierarchy(
        parsed_bootstrap.payload,
        observed_at=observed_at,
        information_cutoff=information_cutoff,
        source_bootstrap_payload_sha256=parsed_bootstrap.payload_sha256,
    )
    fixtures = client.fetch(DirectFplResource.FIXTURES)
    fpl_input = CurrentFplInputService(clock=active_clock).compile_direct(
        CurrentFplDirectInputRequest(
            competition_key="PL",
            season_code="2026/27",
            target_gameweek=target_gameweek,
            captured_at=observed_at,
            information_cutoff=information_cutoff,
            rights_profile_id=OFFICIAL_DIRECT_PROFILE_ID,
        ),
        bootstrap_body=bootstrap,
        fixtures_body=fixtures,
    )
    if (
        penalty_hierarchy.source_bootstrap_payload_sha256
        != fpl_input.provenance.bootstrap_payload_sha256
    ):
        raise IngestionError("INTERNAL_INVARIANT", "official FPL bootstrap hashes differ")
    del bootstrap, fixtures, parsed_bootstrap
    entry_body = client.fetch(DirectFplResource.ENTRY, entry_id=entry_id)
    history_body = client.fetch(DirectFplResource.HISTORY, entry_id=entry_id)
    history = parse_direct_history(history_body)
    entry_resolution = resolve_direct_entry(
        entry_body, history=history, target_gameweek=target_gameweek
    )
    del entry_body, history_body
    entry = entry_resolution.entry
    if entry.id != entry_id:
        raise IngestionError("MAPPING_CONFLICT", "official FPL entry identity differs")
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
        captured_at=observed_at,
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
        current_penalty_hierarchy=penalty_hierarchy,
        entry_quality=entry_resolution.quality,
    )


__all__ = [
    "CURRENT_FPL_ENTRY_DUPLICATE_SUMMARY_FIELDS_OBSERVED",
    "CURRENT_FPL_ENTRY_EVENT_RANK_AMBIGUOUS_DISCARDED",
    "CURRENT_FPL_ENTRY_OVERALL_RANK_AMBIGUOUS_UNAVAILABLE",
    "CURRENT_FPL_ENTRY_OVERALL_RANK_RECONCILED_FROM_HISTORY_V1",
    "CURRENT_FPL_PENALTY_HIERARCHY_AMBIGUOUS",
    "CURRENT_FPL_PENALTY_HIERARCHY_UNAVAILABLE",
    "CurrentPenaltyHierarchy",
    "CurrentPenaltyHierarchyEntry",
    "CurrentPenaltyHierarchyTeam",
    "CurrentPenaltyHierarchyTeamStatus",
    "DirectEntry",
    "DirectEntryHistory",
    "DirectEntryHistoryRow",
    "DirectEntryOverallPointsStatus",
    "DirectEntryOverallRankStatus",
    "DirectEntryQuality",
    "DirectEntryResolution",
    "DirectEventLive",
    "DirectFplSnapshot",
    "DirectLiveElement",
    "DirectLiveStats",
    "DirectPublicPicks",
    "DirectTransfer",
    "acquire_direct_fpl_snapshot",
    "build_current_penalty_hierarchy",
    "current_penalty_hierarchy_sha256",
    "parse_direct_entry",
    "parse_direct_event_live",
    "parse_direct_history",
    "parse_direct_public_picks",
    "parse_direct_transfers",
    "resolve_direct_entry",
]
