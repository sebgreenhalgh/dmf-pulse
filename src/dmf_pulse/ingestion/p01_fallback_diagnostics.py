"""Closed, disclosure-safe diagnostics; no provider I/O or execution authority."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FrozenEvidence,
    SealedEvidence,
    StrengthEvidenceError,
    seal,
)


class ExecutionStage(StrEnum):
    LOAD_CONTEXT = "LOAD_CONTEXT"
    AUTHENTICATE_RIGHTS = "AUTHENTICATE_RIGHTS"
    AUTHENTICATE_REVIEW = "AUTHENTICATE_REVIEW"
    AUTHENTICATE_FORECAST = "AUTHENTICATE_FORECAST"
    VALIDATE_ACQUISITION_ROOT = "VALIDATE_ACQUISITION_ROOT"
    SEAL_ONE_ATTEMPT_MARKER = "SEAL_ONE_ATTEMPT_MARKER"
    FETCH_GLOBAL_RESULT_TYPES = "FETCH_GLOBAL_RESULT_TYPES"
    FETCH_LEAGUE_RESULT_INFO = "FETCH_LEAGUE_RESULT_INFO"
    RESOLVE_REGULATION_RESULT_TYPE = "RESOLVE_REGULATION_RESULT_TYPE"
    FETCH_MATCHDAY_RESPONSE = "FETCH_MATCHDAY_RESPONSE"
    PROJECT_FINAL_FACTS = "PROJECT_FINAL_FACTS"
    ADMIT_EXACT_TEN = "ADMIT_EXACT_TEN"
    PERSIST_OUTCOME_ARTIFACT = "PERSIST_OUTCOME_ARTIFACT"
    VALIDATE_D_PLUS_2 = "VALIDATE_D_PLUS_2"
    COMPLETE = "COMPLETE"


class FailureReason(StrEnum):
    CONTEXT_INVALID = "CONTEXT_INVALID"
    RIGHTS_IDENTITY_MISMATCH = "RIGHTS_IDENTITY_MISMATCH"
    REVIEW_INVALID = "REVIEW_INVALID"
    FORECAST_IDENTITY_MISMATCH = "FORECAST_IDENTITY_MISMATCH"
    ACQUISITION_ROOT_INVALID = "ACQUISITION_ROOT_INVALID"
    ONE_ATTEMPT_ALREADY_CONSUMED = "ONE_ATTEMPT_ALREADY_CONSUMED"
    MARKER_PERSISTENCE_FAILED = "MARKER_PERSISTENCE_FAILED"
    TRANSPORT_ROUTE_REFUSED = "TRANSPORT_ROUTE_REFUSED"
    TRANSPORT_STATUS_OR_CONTENT_TYPE_REFUSED = "TRANSPORT_STATUS_OR_CONTENT_TYPE_REFUSED"
    TRANSPORT_RESPONSE_TOO_LARGE = "TRANSPORT_RESPONSE_TOO_LARGE"
    TRANSPORT_TIMEOUT = "TRANSPORT_TIMEOUT"
    TRANSPORT_UNAVAILABLE = "TRANSPORT_UNAVAILABLE"
    TRANSPORT_TRUNCATED = "TRANSPORT_TRUNCATED"
    PROVIDER_JSON_INVALID = "PROVIDER_JSON_INVALID"
    REGULATION_METADATA_AMBIGUOUS = "REGULATION_METADATA_AMBIGUOUS"
    REGULATION_METADATA_DISAGREEMENT = "REGULATION_METADATA_DISAGREEMENT"
    MATCHDAY_RESPONSE_INVALID = "MATCHDAY_RESPONSE_INVALID"
    MATCHDAY_FIXTURE_COUNT_INVALID = "MATCHDAY_FIXTURE_COUNT_INVALID"
    METADATA_LEAGUE_ID_INVALID = "METADATA_LEAGUE_ID_INVALID"
    METADATA_LEAGUE_SHORTCUT_INVALID = "METADATA_LEAGUE_SHORTCUT_INVALID"
    METADATA_LEAGUE_SEASON_INVALID = "METADATA_LEAGUE_SEASON_INVALID"
    METADATA_DISPLAY_NAME_INVALID = "METADATA_DISPLAY_NAME_INVALID"
    METADATA_MATCHDAY_INVALID = "METADATA_MATCHDAY_INVALID"
    MATCH_NOT_FINISHED = "MATCH_NOT_FINISHED"
    REGULATION_RESULT_MISSING_OR_AMBIGUOUS = "REGULATION_RESULT_MISSING_OR_AMBIGUOUS"
    REGULATION_RESULT_TYPE_MISMATCH = "REGULATION_RESULT_TYPE_MISMATCH"
    EXCEPTIONAL_RESULT_REFUSED = "EXCEPTIONAL_RESULT_REFUSED"
    PLAYED_TIMESTAMP_MISSING_OR_INVALID = "PLAYED_TIMESTAMP_MISSING_OR_INVALID"
    PROVIDER_FIELD_TYPE_INVALID = "PROVIDER_FIELD_TYPE_INVALID"
    EXACT_TEN_INCOMPLETE = "EXACT_TEN_INCOMPLETE"
    ORIENTED_MAPPING_AMBIGUOUS = "ORIENTED_MAPPING_AMBIGUOUS"
    PROVIDER_CLUB_IDENTITY_AMBIGUOUS = "PROVIDER_CLUB_IDENTITY_AMBIGUOUS"
    FALLBACK_ADMISSION_INVALID = "FALLBACK_ADMISSION_INVALID"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
    D_PLUS_2_NOT_COMPLETE = "D_PLUS_2_NOT_COMPLETE"
    UNKNOWN_P01_OUTCOME_FAILURE = "UNKNOWN_P01_OUTCOME_FAILURE"


class RouteClass(StrEnum):
    GLOBAL_RESULT_TYPES = "GLOBAL_RESULT_TYPES"
    LEAGUE_RESULT_INFO = "LEAGUE_RESULT_INFO"
    MATCHDAY_DATA = "MATCHDAY_DATA"


class ContentTypeClass(StrEnum):
    JSON = "JSON"
    TEXT_JSON = "TEXT_JSON"
    TEXT_PLAIN = "TEXT_PLAIN"
    MISSING = "MISSING"
    OTHER = "OTHER"


class SafeRequestReceipt(FrozenEvidence):
    route_class: RouteClass
    request_started_at: datetime
    response_received_at: datetime | None = None
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    content_type_class: ContentTypeClass | None = None
    response_bytes: int = Field(default=0, ge=0, le=524289)
    response_sha256: SHA | None = None
    digest_scope: Literal["OBSERVED_BYTES"] = "OBSERVED_BYTES"
    response_complete: bool = False
    strict_json_valid: bool | None = None

    @model_validator(mode="after")
    def receipt_consistency(self) -> SafeRequestReceipt:
        if (
            self.response_received_at is not None
            and self.response_received_at < self.request_started_at
        ):
            raise ValueError("diagnostic receipt time order differs")
        if self.response_complete and (
            self.response_received_at is None or self.response_sha256 is None
        ):
            raise ValueError("complete diagnostic receipt requires time and digest")
        if self.strict_json_valid is not None and not self.response_complete:
            raise ValueError("JSON validation requires complete observed body")
        return self


class MetadataField(StrEnum):
    LEAGUE_ID = "leagueId"
    LEAGUE_SHORTCUT = "leagueShortcut"
    LEAGUE_SEASON = "leagueSeason"
    DISPLAY_NAME = "leagueName"
    GROUP = "group"
    MATCHDAY = "group.groupOrderID"


class MetadataCategory(StrEnum):
    MISSING = "MISSING"
    WRONG_TYPE = "WRONG_TYPE"
    MISMATCH = "MISMATCH"


METADATA_REASONS = {
    MetadataField.LEAGUE_ID: FailureReason.METADATA_LEAGUE_ID_INVALID,
    MetadataField.LEAGUE_SHORTCUT: FailureReason.METADATA_LEAGUE_SHORTCUT_INVALID,
    MetadataField.LEAGUE_SEASON: FailureReason.METADATA_LEAGUE_SEASON_INVALID,
    MetadataField.DISPLAY_NAME: FailureReason.METADATA_DISPLAY_NAME_INVALID,
    MetadataField.GROUP: FailureReason.METADATA_MATCHDAY_INVALID,
    MetadataField.MATCHDAY: FailureReason.METADATA_MATCHDAY_INVALID,
}


class SafeMetadataFailure(FrozenEvidence):
    classification: Literal["METADATA_VALIDATION_FAILED"] = "METADATA_VALIDATION_FAILED"
    field: MetadataField
    category: MetadataCategory


class SafeDiagnostics(FrozenEvidence):
    provider_requests_attempted: int = Field(default=0, ge=0, le=3)
    provider_requests_completed: int = Field(default=0, ge=0, le=3)
    last_route_class: RouteClass | None = None
    request_receipts: tuple[SafeRequestReceipt, ...] = Field(default=(), max_length=3)
    regulation_global_candidate_count: int | None = Field(default=None, ge=0, le=524288)
    regulation_league_candidate_count: int | None = Field(default=None, ge=0, le=524288)
    regulation_metadata_resolved: bool = False
    provider_match_rows: int | None = Field(default=None, ge=0, le=524288)
    finished_match_rows: int = Field(default=0, ge=0, le=10)
    regulation_result_rows: int = Field(default=0, ge=0, le=524288)
    projected_fact_count: int = Field(default=0, ge=0, le=10)
    uniquely_mapped_fixture_count: int = Field(default=0, ge=0, le=10)
    admitted_outcome_count: int = Field(default=0, ge=0, le=10)
    metadata_failure: SafeMetadataFailure | None = None

    @model_serializer(mode="wrap")
    def omit_absent_metadata(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Additive v1 extension: old records retain their exact semantic representation."""
        result: dict[str, Any] = handler(self)
        if self.metadata_failure is None:
            result.pop("metadata_failure", None)
        return result

    @model_validator(mode="after")
    def request_consistency(self) -> SafeDiagnostics:
        if (
            self.provider_requests_attempted != len(self.request_receipts)
            or self.provider_requests_completed
            != sum(row.response_complete for row in self.request_receipts)
            or self.last_route_class
            != (self.request_receipts[-1].route_class if self.request_receipts else None)
            or len({row.route_class for row in self.request_receipts}) != len(self.request_receipts)
        ):
            raise ValueError("diagnostic request counters differ")
        return self


class ReasonFailure(StrengthEvidenceError):
    """Low-level finite reason; never constructed from provider/exception text."""

    def __init__(self, reason: FailureReason) -> None:
        self.reason = reason
        legacy = {
            FailureReason.D_PLUS_2_NOT_COMPLETE: "P01_D_PLUS_2_NOT_COMPLETE",
            FailureReason.ONE_ATTEMPT_ALREADY_CONSUMED: "P01_SOURCE_POLICY_LOCKED_ONE_ATTEMPT_CONSUMED",
            FailureReason.TRANSPORT_ROUTE_REFUSED: "undeclared OpenLigaDB route refused",
        }
        super().__init__(legacy.get(reason, reason.value))


class P01FallbackExecutionFailure(StrengthEvidenceError):
    def __init__(
        self, stage: ExecutionStage, reason: FailureReason, diagnostics: SafeDiagnostics
    ) -> None:
        require_metadata_binding(stage, reason, diagnostics)
        self.stage, self.reason, self.diagnostics = stage, reason, diagnostics
        super().__init__(reason.value)


def require_metadata_binding(
    stage: ExecutionStage, reason: FailureReason, diagnostics: SafeDiagnostics
) -> None:
    issue = diagnostics.metadata_failure
    if issue is not None:
        if stage != ExecutionStage.PROJECT_FINAL_FACTS or reason != METADATA_REASONS[issue.field]:
            raise ValueError("metadata diagnostic stage/reason differs")
    elif reason in METADATA_REASONS.values():
        raise ValueError("metadata reason requires field/category")


@dataclass
class DiagnosticProgress:
    stage: ExecutionStage = ExecutionStage.LOAD_CONTEXT
    safe: SafeDiagnostics = field(default_factory=SafeDiagnostics)

    def update(self, **values: Any) -> None:
        self.safe = self.safe.model_copy(update=values)

    def begin(self, route: RouteClass, at: datetime) -> None:
        receipts = (
            *self.safe.request_receipts,
            SafeRequestReceipt(route_class=route, request_started_at=at),
        )
        self.update(
            provider_requests_attempted=len(receipts),
            last_route_class=route,
            request_receipts=receipts,
        )

    def receipt(self, **values: Any) -> None:
        receipts = self.safe.request_receipts
        updated = (*receipts[:-1], receipts[-1].model_copy(update=values))
        self.update(
            request_receipts=updated,
            provider_requests_completed=sum(row.response_complete for row in updated),
        )

    def json_valid(self, route: RouteClass, valid: bool) -> None:
        receipts = tuple(
            row.model_copy(update={"strict_json_valid": valid}) if row.route_class == route else row
            for row in self.safe.request_receipts
        )
        self.update(request_receipts=receipts)

    def run[T](self, stage: ExecutionStage, reason: FailureReason, operation: Callable[[], T]) -> T:
        self.stage = stage
        try:
            return operation()
        except P01FallbackExecutionFailure:
            raise
        except ReasonFailure as exc:
            raise P01FallbackExecutionFailure(stage, exc.reason, self.safe) from None
        except (ValueError, OSError, TypeError):
            raise P01FallbackExecutionFailure(stage, reason, self.safe) from None
        except Exception:
            raise P01FallbackExecutionFailure(
                stage, FailureReason.UNKNOWN_P01_OUTCOME_FAILURE, self.safe
            ) from None


class StoppedExecutionDiagnostic(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-fallback-stopped-diagnostic-v1"] = (
        "public-team-strength-p01-fallback-stopped-diagnostic-v1"
    )
    stage: ExecutionStage
    reason: FailureReason
    diagnostics: SafeDiagnostics
    started_at: datetime
    stopped_at: datetime
    context_sha256: SHA | None = None
    source: Literal["OpenLigaDB"] = "OpenLigaDB"
    rights_profile_id: Literal["openligadb_public_final_score_labels_v1"] = (
        "openligadb_public_final_score_labels_v1"
    )
    rights_profile_sha256: Literal[
        "31261d9304c20a178d730e57e7d06c82423b68a816bac73d517887d58b3caaf2"
    ] = "31261d9304c20a178d730e57e7d06c82423b68a816bac73d517887d58b3caaf2"
    attribution: Literal[
        "Contains OpenLigaDB information made available under ODbL 1.0: https://www.openligadb.de/ ; https://opendatacommons.org/licenses/odbl/1-0/"
    ] = "Contains OpenLigaDB information made available under ODbL 1.0: https://www.openligadb.de/ ; https://opendatacommons.org/licenses/odbl/1-0/"
    internal_evidence_only: Literal[True] = True
    redistribution_permitted: Literal[False] = False
    one_attempt_consumed: bool
    historical_a02_exact_cause: Literal["NOT_RETAINED"] = "NOT_RETAINED"
    scoring_performed: Literal[False] = False
    production_active: Literal[False] = False
    separate_fresh_human_authorization_required: Literal[True] = True

    @model_validator(mode="after")
    def stopped_consistency(self) -> StoppedExecutionDiagnostic:
        require_metadata_binding(self.stage, self.reason, self.diagnostics)
        if self.stopped_at < self.started_at or self.stage == ExecutionStage.COMPLETE:
            raise ValueError("invalid stopped execution chronology/stage")
        if self.diagnostics.provider_requests_attempted and not self.one_attempt_consumed:
            raise ValueError("requests cannot precede consumed attempt")
        return self


def persist_stopped(value: StoppedExecutionDiagnostic, *, root: Path) -> Path:
    """Exclusive minimal internal evidence; no raw data or arbitrary failure text."""
    from dmf_pulse.evaluation.p01_fallback_context import require_openligadb_rights

    require_openligadb_rights()
    value = StoppedExecutionDiagnostic.model_validate_json(value.model_dump_json())
    if root.is_symlink():
        raise ReasonFailure(FailureReason.PERSISTENCE_FAILED)
    destination = root.resolve() / value.schema_version / f"{value.semantic_sha256}.json"
    if destination.is_symlink() or not destination.resolve().is_relative_to(root.resolve()):
        raise ReasonFailure(FailureReason.PERSISTENCE_FAILED)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or not destination.resolve().is_relative_to(root.resolve()):
        raise ReasonFailure(FailureReason.PERSISTENCE_FAILED)
    payload = pretty_json(value).encode("utf-8")
    descriptor, name = tempfile.mkstemp(prefix=".p01-diagnostic-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        temporary.unlink()
    if StoppedExecutionDiagnostic.model_validate_json(destination.read_bytes()) != value:
        raise ReasonFailure(FailureReason.PERSISTENCE_FAILED)
    return destination


def stopped_record(
    failure: P01FallbackExecutionFailure,
    *,
    started_at: datetime,
    stopped_at: datetime,
    context_sha256: str | None,
    one_attempt_consumed: bool,
) -> StoppedExecutionDiagnostic:
    return seal(
        StoppedExecutionDiagnostic,
        stage=failure.stage,
        reason=failure.reason,
        diagnostics=failure.diagnostics,
        started_at=started_at,
        stopped_at=stopped_at,
        context_sha256=context_sha256,
        one_attempt_consumed=one_attempt_consumed,
    )
