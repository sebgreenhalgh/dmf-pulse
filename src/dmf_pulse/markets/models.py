"""Frozen public models for exact raw market observations."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

SOURCE_DECIMAL_PATTERN = re.compile(r"^(?:1\.\d*[1-9]\d*|(?:[2-9]\d*|1\d+)(?:\.\d+)?)$")


def canonical_decimal_text(value: Decimal) -> str:
    """Render a finite Decimal by numeric value for public semantic identity."""

    if not value.is_finite():
        raise ValueError("decimal value must be finite")
    if value == 0:
        return "0"
    # Decimal.normalize() applies the ambient context precision and can round
    # long provider values.  Fixed-point formatting is context independent.
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def source_decimal_text(value: Decimal) -> str:
    """Render the exact source/database Decimal, including significant scale."""

    if not value.is_finite():
        raise ValueError("decimal value must be finite")
    return format(value, "f")


class MarketState(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    SUSPENDED = "SUSPENDED"
    UNSUPPORTED = "UNSUPPORTED"
    UNAVAILABLE = "UNAVAILABLE"


class MarketOutcome(StrEnum):
    HOME = "HOME"
    DRAW = "DRAW"
    AWAY = "AWAY"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


class MarketObservation(_FrozenModel):
    fixture_id: UUID
    market_id: UUID
    selection_id: UUID
    operator_id: UUID
    outcome: MarketOutcome
    decimal_odds: Decimal = Field(gt=Decimal("1"))
    observed_at: datetime
    received_at: datetime
    usable_at: datetime
    source_snapshot_id: UUID
    market_state: MarketState
    contract_version: Literal["the-odds-api-v4-reference-v1"]

    @field_validator("decimal_odds", mode="before")
    @classmethod
    def validate_decimal_lexeme(cls, value: object) -> Decimal:
        if isinstance(value, str):
            if SOURCE_DECIMAL_PATTERN.fullmatch(value) is None:
                raise ValueError("decimal odds string violates the source-scale contract")
            return Decimal(value)
        if isinstance(value, Decimal):
            return value
        raise ValueError("decimal odds must be a source-scale string or exact Decimal")

    @field_serializer("decimal_odds")
    def serialize_decimal_odds(self, value: Decimal) -> str:
        return source_decimal_text(value)

    @model_validator(mode="after")
    def validate_time_order(self) -> MarketObservation:
        if not self.decimal_odds.is_finite():
            raise ValueError("decimal odds must be finite")
        if not self.observed_at <= self.received_at <= self.usable_at:
            raise ValueError("observation timestamps are inconsistent")
        return self


class MarketBook(_FrozenModel):
    operator_id: UUID
    operator_key: str = Field(min_length=1)
    market_state: MarketState
    observations: tuple[MarketObservation, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def validate_book(self) -> MarketBook:
        if any(
            item.operator_id != self.operator_id or item.market_state != self.market_state
            for item in self.observations
        ):
            raise ValueError("book observations contradict their parent")
        market_ids = {item.market_id for item in self.observations}
        outcomes = {item.outcome for item in self.observations}
        if len(market_ids) > 1 or len(outcomes) != len(self.observations):
            raise ValueError("book observations are not one unique market set")
        if self.market_state is MarketState.COMPLETE and outcomes != set(MarketOutcome):
            raise ValueError("complete book must contain HOME, DRAW, and AWAY")
        if self.market_state is MarketState.INCOMPLETE and not 0 < len(outcomes) < 3:
            raise ValueError("incomplete book must contain one or two outcomes")
        if (
            self.market_state
            in {
                MarketState.SUSPENDED,
                MarketState.UNSUPPORTED,
                MarketState.UNAVAILABLE,
            }
            and self.observations
        ):
            raise ValueError("non-offered book cannot contain quotes")
        return self


class MarketQueryResult(_FrozenModel):
    fixture_id: UUID
    as_of: datetime
    books: tuple[MarketBook, ...]
    observation_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_count(self) -> MarketQueryResult:
        if self.observation_count != sum(len(book.observations) for book in self.books):
            raise ValueError("observation_count does not match books")
        if len({book.operator_id for book in self.books}) != len(self.books):
            raise ValueError("operator book is duplicated")
        if any(
            item.fixture_id != self.fixture_id or item.usable_at > self.as_of
            for book in self.books
            for item in book.observations
        ):
            raise ValueError("query contains ineligible observations")
        return self
