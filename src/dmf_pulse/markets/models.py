"""Frozen public models for exact raw market observations."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_serializer,
    field_validator,
    model_validator,
)

SOURCE_DECIMAL_PATTERN = re.compile(r"^(?:1\.\d*[1-9]\d*|(?:[2-9]\d*|1\d+)(?:\.\d+)?)$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PUBLIC_SCALE = Decimal("0.000000000001")


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


def public_decimal_text(value: Decimal) -> str:
    """Render a previously quantised public Decimal at exactly 12 places."""

    if not value.is_finite():
        raise ValueError("public decimal value must be finite")
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_EVEN
        return format(value.quantize(PUBLIC_SCALE), ".12f")


Probability = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1")),
    PlainSerializer(public_decimal_text, return_type=str, when_used="json"),
]
PublicDecimal12 = Annotated[
    Decimal,
    PlainSerializer(public_decimal_text, return_type=str, when_used="json"),
]


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


class NormalisationMethod(StrEnum):
    POWER = "POWER"
    PROPORTIONAL = "PROPORTIONAL"


class NormalisationStatus(StrEnum):
    NORMALISED = "NORMALISED"
    DEGRADED = "DEGRADED"
    INSUFFICIENT = "INSUFFICIENT"
    BLOCKED = "BLOCKED"


class ExclusionReason(StrEnum):
    INCOMPLETE = "INCOMPLETE"
    STALE = "STALE"
    UNSUPPORTED = "UNSUPPORTED"
    SUSPENDED = "SUSPENDED"
    UNAVAILABLE = "UNAVAILABLE"
    RIGHTS_BLOCKED = "RIGHTS_BLOCKED"
    QUALITY_BLOCKED = "QUALITY_BLOCKED"
    MAPPING_UNAVAILABLE = "MAPPING_UNAVAILABLE"
    FUTURE_OBSERVATION = "FUTURE_OBSERVATION"
    DUPLICATE_OPERATOR = "DUPLICATE_OPERATOR"


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


class ExclusiveOutcomeQuote(MarketObservation):
    """Canonical observation enriched with immutable normalisation lineage."""

    book_observation_id: UUID
    odds_observation_id: UUID
    provider_id: UUID
    operator_key: str = Field(min_length=1)


class NormalisedOutcome(_FrozenModel):
    outcome: MarketOutcome
    decimal_odds: Decimal = Field(gt=Decimal("1"))
    raw_implied_probability: Probability
    proportional_probability: Probability
    market_probability: Probability

    @field_serializer("decimal_odds")
    def serialize_decimal_odds(self, value: Decimal) -> str:
        return source_decimal_text(value)

    @model_validator(mode="after")
    def validate_values(self) -> NormalisedOutcome:
        if not self.decimal_odds.is_finite():
            raise ValueError("decimal odds must be finite")
        return self


class NormalisedOperatorMarket(_FrozenModel):
    fixture_id: UUID
    market_id: UUID
    provider_id: UUID
    operator_id: UUID
    operator_key: str = Field(min_length=1)
    as_of: datetime
    observed_at: datetime
    usable_at: datetime
    market_state: Literal[MarketState.COMPLETE]
    primary_method: NormalisationMethod
    fallback_used: bool
    raw_booksum: PublicDecimal12
    overround: PublicDecimal12
    power_exponent: PublicDecimal12 | None
    outcomes: tuple[NormalisedOutcome, NormalisedOutcome, NormalisedOutcome]
    policy_id: Literal["market-normalisation-v1"]
    policy_sha256: str
    input_signature_sha256: str
    result_sha256: str
    source_observation_ids: tuple[UUID, UUID, UUID]

    @field_validator("policy_sha256", "input_signature_sha256", "result_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("hash must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_operator_result(self) -> NormalisedOperatorMarket:
        if tuple(item.outcome for item in self.outcomes) != tuple(MarketOutcome):
            raise ValueError("normalised outcomes must be HOME, DRAW, AWAY")
        if len(set(self.source_observation_ids)) != 3:
            raise ValueError("normalised source observations must be unique")
        if self.observed_at > self.usable_at or self.usable_at > self.as_of:
            raise ValueError("normalised market timestamps are inconsistent")
        if sum(item.proportional_probability for item in self.outcomes) != Decimal(1):
            raise ValueError("public proportional vector must sum exactly to one")
        if sum(item.market_probability for item in self.outcomes) != Decimal(1):
            raise ValueError("public market vector must sum exactly to one")
        if self.fallback_used:
            if self.primary_method is not NormalisationMethod.PROPORTIONAL:
                raise ValueError("power fallback must use proportional as primary")
            if self.power_exponent is not None:
                raise ValueError("power fallback cannot publish an exponent")
            if any(
                item.market_probability != item.proportional_probability for item in self.outcomes
            ):
                raise ValueError("power fallback vector must equal proportional")
        return self


class ConsensusOutcome(_FrozenModel):
    outcome: MarketOutcome
    consensus_probability: Probability
    lower_bound: Probability
    upper_bound: Probability

    @model_validator(mode="after")
    def validate_bounds(self) -> ConsensusOutcome:
        if not self.lower_bound <= self.consensus_probability <= self.upper_bound:
            raise ValueError("consensus probability is outside its public envelope")
        return self


class MarketFreshness(_FrozenModel):
    minimum_age_seconds: int = Field(ge=0)
    maximum_age_seconds: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> MarketFreshness:
        if self.minimum_age_seconds > self.maximum_age_seconds:
            raise ValueError("freshness range is reversed")
        return self


class MarketConsensus(_FrozenModel):
    fixture_id: UUID
    as_of: datetime
    mapping_cutoff: datetime
    market_definition: Literal["FULL_TIME_1X2"]
    provider_count: int = Field(ge=1)
    operator_count: int = Field(ge=1)
    eligible_operator_count: int = Field(ge=1)
    operator_markets: tuple[NormalisedOperatorMarket, ...] = Field(min_length=1)
    outcomes: tuple[ConsensusOutcome, ConsensusOutcome, ConsensusOutcome]
    operator_disagreement: Probability
    method_disagreement: Probability
    market_disagreement: Probability
    freshness: MarketFreshness
    confidence_grade: Literal["A", "B", "C", "D"]
    policy_id: Literal["market-normalisation-v1"]
    policy_sha256: str
    input_signature_sha256: str
    result_sha256: str

    @field_validator("policy_sha256", "input_signature_sha256", "result_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("hash must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_consensus(self) -> MarketConsensus:
        if tuple(item.outcome for item in self.outcomes) != tuple(MarketOutcome):
            raise ValueError("consensus outcomes must be HOME, DRAW, AWAY")
        if sum(item.consensus_probability for item in self.outcomes) != Decimal(1):
            raise ValueError("public consensus vector must sum exactly to one")
        if self.operator_count != len({item.operator_id for item in self.operator_markets}):
            raise ValueError("operator_count contradicts contributing markets")
        if self.eligible_operator_count != len(self.operator_markets):
            raise ValueError("eligible_operator_count contradicts contributing markets")
        if self.provider_count != len({item.provider_id for item in self.operator_markets}):
            raise ValueError("provider_count contradicts contributing markets")
        if self.market_disagreement != max(self.operator_disagreement, self.method_disagreement):
            raise ValueError("market disagreement is inconsistent")
        return self


class ExcludedBook(_FrozenModel):
    operator_key: str = Field(min_length=1)
    reason: ExclusionReason


class MarketNormalisationResult(_FrozenModel):
    status: NormalisationStatus
    fixture_id: UUID | None
    as_of: datetime
    consensus: MarketConsensus | None
    excluded_books: tuple[ExcludedBook, ...]
    warnings: tuple[str, ...]
    error_code: str | None

    @model_validator(mode="after")
    def validate_status(self) -> MarketNormalisationResult:
        has_consensus = self.consensus is not None
        if self.status in {NormalisationStatus.NORMALISED, NormalisationStatus.DEGRADED}:
            if not has_consensus or self.fixture_id is None or self.error_code is not None:
                raise ValueError("successful status requires consensus and no error")
        elif has_consensus:
            raise ValueError("blocked or insufficient result cannot contain consensus")
        if self.status is NormalisationStatus.NORMALISED and (self.excluded_books or self.warnings):
            raise ValueError("clean normalised status cannot contain degradations")
        if self.status is NormalisationStatus.INSUFFICIENT and self.error_code is None:
            raise ValueError("insufficient result requires a typed error")
        if self.status is NormalisationStatus.BLOCKED and self.error_code is None:
            raise ValueError("blocked result requires a typed error")
        return self
