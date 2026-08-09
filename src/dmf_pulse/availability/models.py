"""Typed synthetic history and training-dataset contracts for MIN-007B."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

Position = Literal["GK", "DEF", "MID", "FWD"]
RoleLabel = Literal["START", "BENCH", "OUT"]
Split = Literal["TRAIN", "EVAL"]

POSITION_RANK: dict[str, int] = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}

_RFC3339_UTC_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)


class DatasetValidationError(ValueError):
    """A supplied history row or dataset violates the frozen contract."""


def parse_utc(value: object, *, field_name: str) -> datetime:
    """Parse an explicitly UTC timestamp and reject naive/non-UTC values."""

    if isinstance(value, str):
        if _RFC3339_UTC_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{field_name} must be an RFC3339 UTC timestamp")
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an RFC3339 UTC timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{field_name} must be an RFC3339 UTC timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return parsed.astimezone(UTC)


def format_utc(value: datetime) -> str:
    """Render a canonical UTC timestamp without changing source precision."""

    normalized = value.astimezone(UTC)
    rendered = normalized.isoformat(
        timespec="microseconds" if normalized.microsecond else "seconds"
    )
    return rendered.replace("+00:00", "Z")


def _parse_uuid(value: object, *, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a UUID") from exc
    raise ValueError(f"{field_name} must be a UUID")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class HistoryRow(_FrozenModel):
    """One explicit player-fixture role/minutes label from canonical history."""

    evidence_type: str = Field(min_length=1)
    example_id: UUID
    feature_cutoff: datetime
    fixture_id: UUID
    fixture_key: str = Field(min_length=1)
    label_usable_at: datetime
    manager_regime_id: UUID
    minutes_label: Annotated[int, Field(ge=0, le=90)]
    player_id: UUID
    player_key: str = Field(min_length=1)
    position: Position
    role_label: RoleLabel
    sequence_index: Annotated[int, Field(ge=1)]
    split: Split
    team_id: UUID
    team_key: str = Field(min_length=1)

    @field_validator(
        "example_id",
        "fixture_id",
        "manager_regime_id",
        "player_id",
        "team_id",
        mode="before",
    )
    @classmethod
    def validate_uuid(cls, value: object, info: ValidationInfo) -> UUID:
        return _parse_uuid(value, field_name=info.field_name or "identifier")

    @field_validator("feature_cutoff", "label_usable_at", mode="before")
    @classmethod
    def validate_timestamp(cls, value: object, info: ValidationInfo) -> datetime:
        return parse_utc(value, field_name=info.field_name or "timestamp")

    @field_serializer("feature_cutoff", "label_usable_at")
    def serialize_timestamp(self, value: datetime) -> str:
        return format_utc(value)

    @model_validator(mode="after")
    def validate_role_minutes(self) -> Self:
        if self.role_label == "START" and self.minutes_label == 0:
            raise ValueError("START requires minutes in the range 1..90")
        if self.role_label == "OUT" and self.minutes_label != 0:
            raise ValueError("OUT requires zero minutes")
        return self


class TrainingDataset(_FrozenModel):
    """The exact semantic body emitted by the cutoff-safe builder."""

    rows: tuple[HistoryRow, ...]
    schema_version: Literal["minutes-training-dataset-v1"]
    training_cutoff: datetime

    @field_validator("training_cutoff", mode="before")
    @classmethod
    def validate_cutoff(cls, value: object) -> datetime:
        return parse_utc(value, field_name="training_cutoff")

    @field_serializer("training_cutoff")
    def serialize_cutoff(self, value: datetime) -> str:
        return format_utc(value)

    @model_validator(mode="after")
    def validate_rows(self) -> Self:
        for row in self.rows:
            if row.split != "TRAIN":
                raise ValueError("training dataset cannot contain EVAL rows")
            if row.feature_cutoff > self.training_cutoff:
                raise ValueError("training row feature cutoff is after training cutoff")
            if row.label_usable_at > self.training_cutoff:
                raise ValueError("training row label is not usable at training cutoff")
        return self


__all__ = [
    "POSITION_RANK",
    "DatasetValidationError",
    "HistoryRow",
    "Position",
    "RoleLabel",
    "Split",
    "TrainingDataset",
    "format_utc",
    "parse_utc",
]
