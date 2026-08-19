"""Governed live The Odds API provider-native current-input service."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import insert, update

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.models import require_utc
from dmf_pulse.data_model.tables import data_quality_issue, source_snapshot
from dmf_pulse.database.engine import session_factory
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    _validate_database_reference,
)
from dmf_pulse.ingestion.models import RightsCapability, RightsProfile
from dmf_pulse.ingestion.odds.client import (
    CredentialProvider,
    OddsClient,
    OddsFetchFailure,
    OddsRetrievalAttempt,
    OddsTransport,
    UrllibOddsTransport,
)
from dmf_pulse.ingestion.odds.config import (
    load_provider_config,
    load_rights_profiles,
)
from dmf_pulse.ingestion.odds.credentials import (
    RuntimeOddsCredentialProvider,
    credential_is_configured,
)
from dmf_pulse.ingestion.odds.current import (
    OddsProviderCurrentInput,
    build_current_odds_input,
)
from dmf_pulse.ingestion.odds.models import (
    OddsQuality,
    ProviderFailure,
    ProviderFailureCode,
    QuotaState,
)
from dmf_pulse.ingestion.odds.parser import ParsedOddsPayload, parse_odds_payload
from dmf_pulse.ingestion.odds.service import OddsIngestionService, _Envelope
from dmf_pulse.ingestion.repository import (
    append_processing_event_idempotent,
    record_rights_decision,
)
from dmf_pulse.ingestion.rights import decide_rights, require_rights


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


class LiveOddsSnapshotResult(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal[
        "COMPLETE",
        "OBSERVED_NOT_USABLE",
        "QUARANTINED",
        "BLOCKED",
        "FAILED",
    ]
    provider: Literal["the_odds_api"] = "the_odds_api"
    source_snapshot_id: UUID | None
    events_seen: int = Field(ge=0)
    bookmaker_observations_seen: int = Field(ge=0)
    market_observations_seen: int = Field(ge=0)
    outcomes_seen: int = Field(ge=0)
    current_input: OddsProviderCurrentInput | None
    quota: QuotaState | None
    quality: OddsQuality
    error: ProviderFailure | None

    @model_validator(mode="after")
    def validate_outcome(self) -> LiveOddsSnapshotResult:
        if self.status == "COMPLETE":
            if (
                self.source_snapshot_id is None
                or self.current_input is None
                or self.error is not None
                or self.quality.blockers
            ):
                raise ValueError("complete live odds result is contradictory")
            if self.current_input.provenance.source_snapshot_id != self.source_snapshot_id:
                raise ValueError("current input source contradicts retrieval evidence")
        elif self.status == "BLOCKED":
            if (
                self.source_snapshot_id is not None
                or self.current_input is not None
                or self.error is None
                or self.error.transport_called
            ):
                raise ValueError("pre-transport block is contradictory")
        elif self.status == "FAILED":
            if self.current_input is not None or self.error is None:
                raise ValueError("failed live odds result is contradictory")
        elif self.status in {"OBSERVED_NOT_USABLE", "QUARANTINED"}:
            if (
                self.source_snapshot_id is None
                or self.current_input is not None
                or not self.quality.blockers
            ):
                raise ValueError("observed rejection is contradictory")
        return self


@dataclass(frozen=True, slots=True)
class LiveOddsOperationOutcome:
    result: LiveOddsSnapshotResult
    exit_code: int


@dataclass(frozen=True, slots=True)
class LiveEvidenceHandle:
    source_snapshot_id: UUID
    internal: object | None = None


class LiveOddsEvidenceStore(Protocol):
    def latest_quota(self, database_url_ref: str) -> QuotaState | None: ...

    def record_attempts(
        self,
        *,
        profile: RightsProfile,
        attempts: tuple[OddsRetrievalAttempt, ...],
        successful_body: bytes | None = None,
    ) -> LiveEvidenceHandle: ...

    def record_rejected(
        self,
        handle: LiveEvidenceHandle,
        *,
        observed_at: datetime,
        error: IngestionError,
        parsed: ParsedOddsPayload | None = None,
    ) -> None: ...

    def record_usable(
        self,
        handle: LiveEvidenceHandle,
        *,
        parsed: ParsedOddsPayload,
        current_input: OddsProviderCurrentInput,
    ) -> None: ...


class DatabaseLiveOddsEvidenceStore:
    """Reuse the ODD-005 quota and envelope repositories without raw retention."""

    def __init__(
        self,
        service: OddsIngestionService,
        database_url_ref: str,
    ) -> None:
        self._service = service
        self._database_url_ref = database_url_ref

    def latest_quota(self, database_url_ref: str) -> QuotaState | None:
        if database_url_ref != self._database_url_ref:
            raise IngestionError(
                "DATABASE_REFERENCE_INVALID",
                "live odds evidence store reference changed unexpectedly",
            )
        return self._service._latest_provider_quota(database_url_ref)

    def record_attempts(
        self,
        *,
        profile: RightsProfile,
        attempts: tuple[OddsRetrievalAttempt, ...],
        successful_body: bytes | None = None,
    ) -> LiveEvidenceHandle:
        engine = self._service._engine(self._database_url_ref)
        try:
            envelope = self._service._record_live_attempts(
                session_factory(engine),
                profile=profile,
                attempts=attempts,
                successful_body=successful_body,
            )
            return LiveEvidenceHandle(envelope.source_snapshot_id, envelope)
        finally:
            engine.dispose()

    def record_rejected(
        self,
        handle: LiveEvidenceHandle,
        *,
        observed_at: datetime,
        error: IngestionError,
        parsed: ParsedOddsPayload | None = None,
    ) -> None:
        if not isinstance(handle.internal, _Envelope):
            raise IngestionError(
                "INTERNAL_INVARIANT",
                "live odds evidence handle is invalid",
            )
        envelope = handle.internal
        rejected_at = require_utc(observed_at)
        engine = self._service._engine(self._database_url_ref)
        try:
            factory = session_factory(engine)
            if parsed is not None:
                with factory.begin() as session:
                    append_processing_event_idempotent(
                        session,
                        snapshot_id=handle.source_snapshot_id,
                        stage="PARSED",
                        event_at=rejected_at,
                        input_sha256=parsed.body_sha256,
                        output_sha256=parsed.semantic_sha256,
                        safe_details={
                            "schema_fingerprint": parsed.schema_fingerprint,
                        },
                        stage_version="the-odds-api-v4-reference-v1",
                        actor="the-odds-api-current-input-v1",
                    )
            if error.code != "POST_CUTOFF":
                self._service._quarantine(
                    factory,
                    envelope,
                    rejected_at,
                    error,
                )
                return
            with factory.begin() as session:
                session.execute(
                    insert(data_quality_issue).values(
                        source_snapshot_id=handle.source_snapshot_id,
                        issue_type="POST_CUTOFF",
                        severity="P1",
                        status="OPEN",
                        detected_at=rejected_at,
                        decision_impact="BLOCKING",
                        details={"error_code": "POST_CUTOFF"},
                        subject_scope="SOURCE_SNAPSHOT",
                        stage="TEMPORAL_VALIDATION",
                        message="live odds evidence was received but not usable by cutoff",
                    )
                )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=handle.source_snapshot_id,
                    stage="REJECTED",
                    event_at=rejected_at,
                    input_sha256=(parsed.semantic_sha256 if parsed is not None else None),
                    output_sha256=canonical_sha256("POST_CUTOFF"),
                    error_code="POST_CUTOFF",
                    safe_details={"reason": "POST_CUTOFF"},
                    stage_version="the-odds-api-v4-reference-v1",
                    actor="the-odds-api-current-input-v1",
                )
        finally:
            engine.dispose()

    def record_usable(
        self,
        handle: LiveEvidenceHandle,
        *,
        parsed: ParsedOddsPayload,
        current_input: OddsProviderCurrentInput,
    ) -> None:
        if not isinstance(handle.internal, _Envelope):
            raise IngestionError(
                "INTERNAL_INVARIANT",
                "live odds evidence handle is invalid",
            )
        envelope = handle.internal
        profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
        engine = self._service._engine(self._database_url_ref)
        try:
            factory = session_factory(engine)
            current_input_sha256 = canonical_sha256(current_input.model_dump(mode="json"))
            with factory.begin() as session:
                for capability in (
                    RightsCapability.PUBLIC_DISPLAY,
                    RightsCapability.REDISTRIBUTION,
                    RightsCapability.BACKUP,
                    RightsCapability.MODEL_TRAINING,
                ):
                    record_rights_decision(
                        session,
                        rights_profile_record_id=(envelope.rights_profile_record_id),
                        source_snapshot_id=handle.source_snapshot_id,
                        decision=decide_rights(
                            profile,
                            capability,
                            checked_at=current_input.temporal.received_at,
                        ),
                        context={
                            "capability": capability.value,
                            "operation": "provider_native_current_input",
                        },
                    )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=handle.source_snapshot_id,
                    stage="PARSED",
                    event_at=current_input.temporal.usable_at,
                    input_sha256=parsed.body_sha256,
                    output_sha256=parsed.semantic_sha256,
                    safe_details={
                        "schema_fingerprint": parsed.schema_fingerprint,
                    },
                    stage_version="the-odds-api-v4-reference-v1",
                    actor="the-odds-api-current-input-v1",
                )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=handle.source_snapshot_id,
                    stage="VALIDATED",
                    event_at=current_input.temporal.usable_at,
                    input_sha256=parsed.semantic_sha256,
                    output_sha256=(current_input.provenance.effective_config_sha256),
                    safe_details={
                        "contract": current_input.contract,
                        "identity_scope": current_input.identity_scope,
                        "warning_count": len(current_input.quality.warnings),
                    },
                    stage_version="the-odds-api-v4-reference-v1",
                    actor="the-odds-api-current-input-v1",
                )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=handle.source_snapshot_id,
                    stage="MAPPED",
                    event_at=current_input.temporal.usable_at,
                    input_sha256=(current_input.provenance.effective_config_sha256),
                    output_sha256=current_input_sha256,
                    safe_details={
                        "identity_scope": current_input.identity_scope,
                        "mapping_scope": "PROVIDER_NATIVE_ONLY",
                        "canonical_fpl_fixture_mapping_performed": False,
                        "fuzzy_team_matching_performed": False,
                    },
                    stage_version="the-odds-api-v4-reference-v1",
                    actor="the-odds-api-current-input-v1",
                )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=handle.source_snapshot_id,
                    stage="PROMOTED",
                    event_at=current_input.temporal.usable_at,
                    input_sha256=current_input_sha256,
                    output_sha256=current_input_sha256,
                    safe_details={
                        "promotion_target": current_input.contract,
                        "canonical_rows_created": 0,
                        "raw_payload_retained": False,
                    },
                    stage_version="the-odds-api-v4-reference-v1",
                    actor="the-odds-api-current-input-v1",
                )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=handle.source_snapshot_id,
                    stage="QUALITY_PASSED",
                    event_at=current_input.temporal.usable_at,
                    input_sha256=current_input_sha256,
                    output_sha256=current_input_sha256,
                    safe_details={
                        "provider_native": True,
                        "raw_payload_retained": False,
                        "canonical_fpl_fixture_mapping_performed": False,
                    },
                    stage_version="the-odds-api-v4-reference-v1",
                    actor="the-odds-api-current-input-v1",
                )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=handle.source_snapshot_id,
                    stage="USABLE",
                    event_at=current_input.temporal.usable_at,
                    input_sha256=current_input_sha256,
                    output_sha256=current_input_sha256,
                    safe_details={
                        "contract": current_input.contract,
                        "identity_scope": current_input.identity_scope,
                        "publication_state": ("PROVIDER_NATIVE_CURRENT_INPUT"),
                    },
                    stage_version="the-odds-api-v4-reference-v1",
                    actor="the-odds-api-current-input-v1",
                )
                for warning in current_input.quality.warnings:
                    session.execute(
                        insert(data_quality_issue).values(
                            source_snapshot_id=handle.source_snapshot_id,
                            issue_type=warning.partition(":")[0][:80],
                            severity="P2",
                            status="OPEN",
                            detected_at=current_input.temporal.usable_at,
                            decision_impact="NONBLOCKING",
                            details={
                                "warning_sha256": canonical_sha256(warning),
                            },
                            subject_scope="SOURCE_SNAPSHOT",
                            stage="VALIDATION",
                            message=("live odds source has bounded nonblocking drift"),
                        )
                    )
                session.execute(
                    update(source_snapshot)
                    .where(source_snapshot.c.source_snapshot_id == handle.source_snapshot_id)
                    .values(
                        parsed_at=current_input.temporal.usable_at,
                        usable_at=current_input.temporal.usable_at,
                        validation_status="USABLE",
                        schema_fingerprint=parsed.schema_fingerprint,
                    )
                )
        finally:
            engine.dispose()


def _quality(
    warnings: tuple[str, ...] = (),
    blockers: tuple[str, ...] = (),
) -> OddsQuality:
    return OddsQuality(
        status="BLOCKING" if blockers else "WARNING" if warnings else "PASS",
        warnings=tuple(sorted(set(warnings))),
        blockers=tuple(sorted(set(blockers))),
    )


def _provider_failure(
    error: IngestionError,
    *,
    transport_called: bool,
) -> ProviderFailure:
    try:
        code = ProviderFailureCode(error.code)
    except ValueError:
        code = ProviderFailureCode.SOURCE_UNAVAILABLE
    return ProviderFailure(
        code=code,
        message=error.message,
        retryable=error.retryable,
        transport_called=transport_called,
    )


def _attempt_failure_code(attempt: OddsRetrievalAttempt) -> ProviderFailureCode:
    code = attempt.failure_code or ProviderFailureCode.SOURCE_UNAVAILABLE
    if code is not ProviderFailureCode.SOURCE_UNAVAILABLE:
        return code
    status = attempt.http_status
    if status == 429:
        return ProviderFailureCode.HTTP_429
    if status is not None and 500 <= status < 600:
        return ProviderFailureCode.HTTP_5XX
    if status is not None and 400 <= status < 500:
        return ProviderFailureCode.HTTP_4XX
    return code


def _attempt_failure_message(
    code: ProviderFailureCode,
    fallback: str,
) -> str:
    messages = {
        ProviderFailureCode.HTTP_429: "odds provider rate limited the request",
        ProviderFailureCode.HTTP_4XX: "odds provider rejected the request",
        ProviderFailureCode.HTTP_5XX: "odds provider returned a server error",
    }
    return messages.get(code, fallback)


def _counts(parsed: ParsedOddsPayload) -> tuple[int, int, int, int]:
    bookmakers = sum(len(event.bookmakers) for event in parsed.events)
    markets = sum(
        len(bookmaker.markets) for event in parsed.events for bookmaker in event.bookmakers
    )
    outcomes = sum(
        len(market.outcomes)
        for event in parsed.events
        for bookmaker in event.bookmakers
        for market in bookmaker.markets
    )
    return len(parsed.events), bookmakers, markets, outcomes


def _blockers(error: IngestionError) -> tuple[str, ...]:
    value = error.details.get("blockers")
    if not isinstance(value, list):
        return (error.code,)
    blockers = tuple(item for item in value if isinstance(item, str) and 0 < len(item) <= 120)
    return blockers or (error.code,)


class LiveOddsSnapshotService:
    """Fetch provider-native EPL odds without cross-provider identity mapping."""

    def __init__(
        self,
        *,
        database_url_ref: str = DATABASE_REF,
        credential_provider: CredentialProvider | None = None,
        transport_factory: Callable[[], OddsTransport] = UrllibOddsTransport,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        processing_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        evidence_store: LiveOddsEvidenceStore | None = None,
    ) -> None:
        self.database_url_ref = database_url_ref
        self.credential_provider = credential_provider or RuntimeOddsCredentialProvider()
        self.transport_factory = transport_factory
        self.clock = clock
        self.processing_clock = processing_clock
        self.sleeper = sleeper
        self.monotonic = monotonic
        self._injected_evidence_store = evidence_store

    def _evidence_store(self, database_url_ref: str) -> LiveOddsEvidenceStore:
        if self._injected_evidence_store is not None:
            return self._injected_evidence_store
        delegate = OddsIngestionService(
            credential_provider=self.credential_provider,
            transport_factory=self.transport_factory,
            clock=self.clock,
            processing_clock=self.processing_clock,
            sleeper=self.sleeper,
            monotonic=self.monotonic,
        )
        return DatabaseLiveOddsEvidenceStore(delegate, database_url_ref)

    def snapshot(
        self,
        *,
        provider: str,
        competition_key: str,
        sport_key: str,
        region: str,
        market: str,
        as_of: datetime,
        database_url_ref: str | None = None,
        quota: QuotaState | None = None,
    ) -> LiveOddsOperationOutcome:
        config = load_provider_config()
        selected_database_ref = database_url_ref or self.database_url_ref
        _validate_database_reference(selected_database_ref)
        cutoff = require_utc(as_of)
        now = require_utc(self.clock())
        if now > cutoff:
            raise IngestionError(
                "POST_CUTOFF",
                "odds snapshot cannot start after the information cutoff",
                details={"transport_call_count": 0},
            )
        if (
            provider != config.provider_key
            or competition_key != "PL"
            or sport_key not in config.sport_keys
            or region not in config.regions
            or market not in config.markets
        ):
            raise IngestionError(
                "USAGE_INVALID",
                "odds snapshot options are not allowlisted",
            )

        profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
        try:
            for capability in (
                RightsCapability.AUTOMATED_ACCESS,
                RightsCapability.TRANSIENT_PROCESSING,
                RightsCapability.DERIVED_STORAGE,
                RightsCapability.PRIVATE_INTERNAL_USE,
            ):
                require_rights(profile, capability, checked_at=now)
        except IngestionError as exc:
            failure = _provider_failure(exc, transport_called=False)
            return LiveOddsOperationOutcome(
                LiveOddsSnapshotResult(
                    status="BLOCKED",
                    source_snapshot_id=None,
                    events_seen=0,
                    bookmaker_observations_seen=0,
                    market_observations_seen=0,
                    outcomes_seen=0,
                    current_input=None,
                    quota=quota,
                    quality=_quality(blockers=(failure.code.value,)),
                    error=failure,
                ),
                exit_code=4,
            )

        evidence_store = self._evidence_store(selected_database_ref)
        try:
            effective_quota = (
                quota if quota is not None else evidence_store.latest_quota(selected_database_ref)
            )
        except Exception:
            if not credential_is_configured(self.credential_provider):
                code = ProviderFailureCode.CREDENTIAL_UNAVAILABLE
                return LiveOddsOperationOutcome(
                    LiveOddsSnapshotResult(
                        status="BLOCKED",
                        source_snapshot_id=None,
                        events_seen=0,
                        bookmaker_observations_seen=0,
                        market_observations_seen=0,
                        outcomes_seen=0,
                        current_input=None,
                        quota=None,
                        quality=_quality(blockers=(code.value,)),
                        error=ProviderFailure(
                            code=code,
                            message=("approved runtime credential is unavailable"),
                            retryable=False,
                            transport_called=False,
                        ),
                    ),
                    exit_code=4,
                )
            raise IngestionError(
                "DATABASE_UNAVAILABLE",
                "quota evidence is unavailable before odds transport",
            ) from None

        client = OddsClient(
            profile,
            credential_provider=self.credential_provider,
            transport_factory=self.transport_factory,
            clock=self.clock,
            sleeper=self.sleeper,
            monotonic=self.monotonic,
        )
        try:
            fetched = client.fetch(
                quota=effective_quota,
                commence_from=cutoff,
            )
        except OddsFetchFailure as exc:
            handle = evidence_store.record_attempts(
                profile=profile,
                attempts=exc.attempts,
            )
            final_attempt = exc.attempts[-1]
            failure_code = _attempt_failure_code(final_attempt)
            return LiveOddsOperationOutcome(
                LiveOddsSnapshotResult(
                    status="FAILED",
                    source_snapshot_id=handle.source_snapshot_id,
                    events_seen=0,
                    bookmaker_observations_seen=0,
                    market_observations_seen=0,
                    outcomes_seen=0,
                    current_input=None,
                    quota=final_attempt.quota or effective_quota,
                    quality=_quality(blockers=(failure_code.value,)),
                    error=ProviderFailure(
                        code=failure_code,
                        message=_attempt_failure_message(
                            failure_code,
                            exc.message,
                        ),
                        retryable=exc.retryable,
                        transport_called=True,
                    ),
                ),
                exit_code=5,
            )
        except IngestionError as exc:
            failure = _provider_failure(
                exc,
                transport_called=client.transport_call_count > 0,
            )
            controlled = failure.code in {
                ProviderFailureCode.RIGHTS_BLOCKED,
                ProviderFailureCode.CREDENTIAL_UNAVAILABLE,
                ProviderFailureCode.QUOTA_EXHAUSTED,
            }
            return LiveOddsOperationOutcome(
                LiveOddsSnapshotResult(
                    status="BLOCKED" if controlled else "FAILED",
                    source_snapshot_id=None,
                    events_seen=0,
                    bookmaker_observations_seen=0,
                    market_observations_seen=0,
                    outcomes_seen=0,
                    current_input=None,
                    quota=effective_quota,
                    quality=_quality(blockers=(failure.code.value,)),
                    error=failure,
                ),
                exit_code=4 if controlled else 5,
            )

        try:
            handle = evidence_store.record_attempts(
                profile=profile,
                attempts=fetched.attempts,
                successful_body=fetched.body,
            )
        except IngestionError:
            raise
        except Exception:
            raise IngestionError(
                "DATABASE_UNAVAILABLE",
                "live odds retrieval evidence could not be recorded",
            ) from None

        try:
            parsed = parse_odds_payload(fetched.body)
        except IngestionError as exc:
            evidence_store.record_rejected(
                handle,
                observed_at=fetched.quota.observed_at,
                error=exc,
            )
            return LiveOddsOperationOutcome(
                LiveOddsSnapshotResult(
                    status="QUARANTINED",
                    source_snapshot_id=handle.source_snapshot_id,
                    events_seen=0,
                    bookmaker_observations_seen=0,
                    market_observations_seen=0,
                    outcomes_seen=0,
                    current_input=None,
                    quota=fetched.quota,
                    quality=_quality(blockers=(exc.code,)),
                    error=None,
                ),
                exit_code=3,
            )

        counts = _counts(parsed)
        try:
            usable_at = require_utc(self.processing_clock())
            current_input = build_current_odds_input(
                parsed,
                profile=profile,
                source_snapshot_id=handle.source_snapshot_id,
                request_started_at=(fetched.attempts[0].request_started_at),
                received_at=fetched.attempts[-1].received_at,
                information_cutoff=cutoff,
                usable_at=usable_at,
                quota=fetched.quota,
                request_fingerprint=fetched.request_fingerprint,
                sanitized_target=fetched.sanitized_target,
                attempt_count=len(fetched.attempts),
                transport_call_count=fetched.transport_call_count,
                provider_request_id_sha256=(fetched.provider_request_id_sha256),
            )
        except IngestionError as exc:
            evidence_store.record_rejected(
                handle,
                observed_at=fetched.quota.observed_at,
                error=exc,
                parsed=parsed,
            )
            return LiveOddsOperationOutcome(
                LiveOddsSnapshotResult(
                    status=("OBSERVED_NOT_USABLE" if exc.code == "POST_CUTOFF" else "QUARANTINED"),
                    source_snapshot_id=handle.source_snapshot_id,
                    events_seen=counts[0],
                    bookmaker_observations_seen=counts[1],
                    market_observations_seen=counts[2],
                    outcomes_seen=counts[3],
                    current_input=None,
                    quota=fetched.quota,
                    quality=_quality(blockers=_blockers(exc)),
                    error=None,
                ),
                exit_code=2 if exc.code == "POST_CUTOFF" else 3,
            )

        evidence_store.record_usable(
            handle,
            parsed=parsed,
            current_input=current_input,
        )
        return LiveOddsOperationOutcome(
            LiveOddsSnapshotResult(
                status="COMPLETE",
                source_snapshot_id=handle.source_snapshot_id,
                events_seen=counts[0],
                bookmaker_observations_seen=counts[1],
                market_observations_seen=counts[2],
                outcomes_seen=counts[3],
                current_input=current_input,
                quota=fetched.quota,
                quality=_quality(current_input.quality.warnings),
                error=None,
            ),
            exit_code=0,
        )
