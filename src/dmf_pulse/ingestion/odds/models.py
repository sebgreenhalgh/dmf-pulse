"""Public provider, quota, validation, and ingestion result contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class QuotaSource(StrEnum):
    RESPONSE_HEADERS = "RESPONSE_HEADERS"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"


class QuotaState(_FrozenModel):
    remaining: int = Field(ge=0)
    used: int = Field(ge=0)
    last_cost: int = Field(ge=0)
    observed_at: datetime
    source: QuotaSource

    @model_validator(mode="after")
    def validate_consistency(self) -> QuotaState:
        if self.last_cost > self.used:
            raise ValueError("quota last cost exceeds total used")
        return self


class ProviderFailureCode(StrEnum):
    RIGHTS_BLOCKED = "RIGHTS_BLOCKED"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    READ_TIMEOUT = "READ_TIMEOUT"
    TOTAL_TIMEOUT = "TOTAL_TIMEOUT"
    HTTP_429 = "HTTP_429"
    HTTP_4XX = "HTTP_4XX"
    HTTP_5XX = "HTTP_5XX"
    CONTENT_TYPE_INVALID = "CONTENT_TYPE_INVALID"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    MALFORMED_JSON = "MALFORMED_JSON"
    REDIRECT_BLOCKED = "REDIRECT_BLOCKED"
    TLS_ERROR = "TLS_ERROR"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    CANCELLED = "CANCELLED"


class ProviderFailure(_FrozenModel):
    code: ProviderFailureCode
    message: str = Field(min_length=1, max_length=240)
    retryable: bool
    transport_called: bool

    @model_validator(mode="after")
    def validate_failure(self) -> ProviderFailure:
        pretransport = {
            ProviderFailureCode.RIGHTS_BLOCKED,
            ProviderFailureCode.CREDENTIAL_UNAVAILABLE,
            ProviderFailureCode.QUOTA_EXHAUSTED,
        }
        nonretryable = pretransport | {
            ProviderFailureCode.HTTP_4XX,
            ProviderFailureCode.CONTENT_TYPE_INVALID,
            ProviderFailureCode.PAYLOAD_TOO_LARGE,
            ProviderFailureCode.MALFORMED_JSON,
            ProviderFailureCode.REDIRECT_BLOCKED,
            ProviderFailureCode.TLS_ERROR,
            ProviderFailureCode.CANCELLED,
        }
        if self.code in pretransport and self.transport_called:
            raise ValueError("pre-transport refusal cannot report a transport call")
        if self.code in nonretryable and self.retryable:
            raise ValueError("failure code is non-retryable")
        return self


class OddsQuality(_FrozenModel):
    status: Literal["PASS", "WARNING", "BLOCKING"]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> OddsQuality:
        expected = "BLOCKING" if self.blockers else "WARNING" if self.warnings else "PASS"
        if self.status != expected:
            raise ValueError("quality status contradicts findings")
        return self


class OddsIngestionResult(_FrozenModel):
    status: Literal["COMPLETE", "OBSERVED_NOT_USABLE", "QUARANTINED", "BLOCKED", "FAILED"]
    provider: Literal["the_odds_api"] = "the_odds_api"
    source_snapshot_id: UUID | None
    events_seen: int = Field(ge=0)
    operator_books_seen: int = Field(ge=0)
    complete_books_created: int = Field(ge=0)
    incomplete_books_created: int = Field(ge=0)
    observations_created: int = Field(ge=0)
    observations_reused: int = Field(ge=0)
    quarantined: int = Field(ge=0)
    quota: QuotaState | None
    quality: OddsQuality
    error: ProviderFailure | None

    @model_validator(mode="after")
    def validate_outcome(self) -> OddsIngestionResult:
        total_effects = self.observations_created + self.observations_reused
        if self.complete_books_created + self.incomplete_books_created > self.operator_books_seen:
            raise ValueError("book counts exceed observed operator books")
        if self.complete_books_created * 3 > total_effects:
            raise ValueError("complete book count contradicts quote effects")
        if self.status == "COMPLETE":
            if self.source_snapshot_id is None or self.error is not None or self.quality.blockers:
                raise ValueError("complete result has contradictory evidence")
        elif self.status in {"BLOCKED", "FAILED"}:
            if self.error is None:
                raise ValueError("failed result requires a provider failure")
            if self.status == "BLOCKED" and (
                self.source_snapshot_id is not None
                or any(
                    (
                        self.events_seen,
                        self.operator_books_seen,
                        self.complete_books_created,
                        self.incomplete_books_created,
                        total_effects,
                        self.quarantined,
                    )
                )
            ):
                raise ValueError("pre-transport block cannot report persisted effects")
        elif self.status == "QUARANTINED":
            if self.source_snapshot_id is None or self.quarantined < 1 or not self.quality.blockers:
                raise ValueError("quarantined result has contradictory evidence")
        elif self.source_snapshot_id is None:
            raise ValueError("observed result requires a source snapshot")
        return self


class OddsValidationResult(_FrozenModel):
    status: Literal["VALID", "VALID_WITH_WARNINGS"]
    provider: Literal["the_odds_api"] = "the_odds_api"
    contract_version: Literal["the-odds-api-v4-reference-v1"]
    events_seen: int = Field(ge=0)
    operator_books_seen: int = Field(ge=0)
    payload_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: OddsQuality

    @model_validator(mode="after")
    def validate_quality(self) -> OddsValidationResult:
        expected = "VALID_WITH_WARNINGS" if self.quality.warnings else "VALID"
        if self.quality.blockers or self.status != expected:
            raise ValueError("validation status contradicts quality evidence")
        return self
