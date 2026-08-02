"""Strict data-model enums and public bitemporal result contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


class DataModelContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EntityType(StrEnum):
    COMPETITION = "COMPETITION"
    SEASON = "SEASON"
    GAMEWEEK = "GAMEWEEK"
    TEAM = "TEAM"
    PLAYER = "PLAYER"
    FIXTURE = "FIXTURE"
    DATA_PROVIDER = "DATA_PROVIDER"
    BETTING_OPERATOR = "BETTING_OPERATOR"
    MARKET = "MARKET"
    SELECTION = "SELECTION"


class MappingStatus(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    CANDIDATE = "CANDIDATE"
    AUTO_MATCHED = "AUTO_MATCHED"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"
    CONFLICTED = "CONFLICTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class MappingMethod(StrEnum):
    PROVIDER_MAPPING = "PROVIDER_MAPPING"
    DETERMINISTIC = "DETERMINISTIC"
    EXACT_EXTERNAL_ID = "EXACT_EXTERNAL_ID"
    RULE_BASED = "RULE_BASED"
    PROBABILISTIC = "PROBABILISTIC"
    MANUAL = "MANUAL"


class AliasType(StrEnum):
    OFFICIAL = "OFFICIAL"
    DISPLAY = "DISPLAY"
    SHORT = "SHORT"
    PROVIDER = "PROVIDER"
    HISTORICAL = "HISTORICAL"
    MANUAL = "MANUAL"


class RegistrationType(StrEnum):
    PERMANENT = "PERMANENT"
    LOAN = "LOAN"
    YOUTH = "YOUTH"
    TEMPORARY = "TEMPORARY"
    UNKNOWN = "UNKNOWN"


class SquadStatus(StrEnum):
    REGISTERED = "REGISTERED"
    UNREGISTERED = "UNREGISTERED"
    LEFT = "LEFT"
    UNKNOWN = "UNKNOWN"


class FixtureStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    STARTED = "STARTED"
    FINISHED = "FINISHED"
    ABANDONED = "ABANDONED"
    UNKNOWN = "UNKNOWN"


class AssignmentStatus(StrEnum):
    ASSIGNED = "ASSIGNED"
    UNASSIGNED = "UNASSIGNED"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class DataQualitySeverity(StrEnum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    BLOCKING = "BLOCKING"


class DataQualityStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"


class DataValueState(StrEnum):
    PRESENT = "PRESENT"
    NULL = "NULL"
    ZERO = "ZERO"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MISSING_SOURCE = "MISSING_SOURCE"


class DataQualityValue(DataModelContract):
    """A typed value envelope that never conflates absence semantics."""

    state: DataValueState
    value: StrictBool | StrictInt | StrictFloat | StrictStr | None = None
    reason: StrictStr | None = None

    @model_validator(mode="after")
    def state_matches_value(self) -> DataQualityValue:
        is_numeric_zero = (
            not isinstance(self.value, bool)
            and isinstance(self.value, (int, float))
            and self.value == 0
        )
        if self.state is DataValueState.PRESENT and (
            self.value is None or is_numeric_zero or self.reason is not None
        ):
            raise ValueError("present data requires a nonzero value and no absence reason")
        if self.state is DataValueState.ZERO and (not is_numeric_zero or self.reason is not None):
            raise ValueError("zero data requires an explicit numeric zero")
        if self.state is DataValueState.NULL and (
            self.value is not None or self.reason is not None
        ):
            raise ValueError("null data carries neither value nor reason")
        reason_states = {
            DataValueState.UNKNOWN,
            DataValueState.NOT_APPLICABLE,
            DataValueState.MISSING_SOURCE,
        }
        if self.state in reason_states and (self.value is not None or not self.reason):
            raise ValueError("absence data requires a nonempty reason and no value")
        return self


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is not UTC:
        raise ValueError("datetime must be timezone-aware UTC")
    return value


class AsOfScope(DataModelContract):
    valid_at: datetime
    known_at: datetime

    @field_validator("valid_at", "known_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class TemporalRange(DataModelContract):
    start: datetime
    end: datetime | None = None

    @field_validator("start", "end")
    @classmethod
    def range_timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @model_validator(mode="after")
    def range_is_nonempty(self) -> TemporalRange:
        if self.end is not None and self.end <= self.start:
            raise ValueError("temporal range must be nonempty and ordered")
        return self


class AsOfQueryResult(DataModelContract):
    query_id: StrictStr
    valid_at: datetime
    known_at: datetime
    result: dict[str, Any] | None

    @field_validator("valid_at", "known_at")
    @classmethod
    def query_timestamps_are_utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class AsOfResult(DataModelContract):
    fixture_id: StrictStr
    queries: tuple[AsOfQueryResult, ...]
    assertions: tuple[dict[str, Any], ...]


class DemoResult(DataModelContract):
    fixture_id: StrictStr
    aliases: dict[str, StrictStr]
    counts: dict[str, int]
    assertions: tuple[dict[str, Any], ...]


INGESTION_TRANSITIONS: dict[str, frozenset[str]] = {
    "PLANNED": frozenset({"RUNNING", "CANCELLED"}),
    "RUNNING": frozenset(
        {
            "SUCCEEDED",
            "SUCCEEDED_WITH_WARNINGS",
            "FAILED_RETRYABLE",
            "FAILED_PERMANENT",
            "CANCELLED",
        }
    ),
    "FAILED_RETRYABLE": frozenset({"RUNNING", "FAILED_PERMANENT", "CANCELLED"}),
    "SUCCEEDED": frozenset(),
    "SUCCEEDED_WITH_WARNINGS": frozenset(),
    "FAILED_PERMANENT": frozenset(),
    "CANCELLED": frozenset(),
}


def validate_ingestion_transition(current: str, requested: str) -> None:
    allowed = INGESTION_TRANSITIONS.get(current)
    if allowed is None or requested not in allowed:
        from dmf_pulse.data_model.errors import DataModelError

        raise DataModelError("INGESTION_STATE_INVALID", "ingestion state transition is invalid")
