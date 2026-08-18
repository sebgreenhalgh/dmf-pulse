"""Rights-gated synthetic replay and controlled live-shaped odds operations."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.models import require_utc
from dmf_pulse.data_model.tables import (
    data_provider,
    data_quality_issue,
    odds_publication_attestation,
    odds_publication_batch,
    provider_quota_observation,
    source_processing_event,
    source_snapshot,
)
from dmf_pulse.database.engine import session_factory
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fixtures import ApprovedFixture, approve_synthetic_fixture
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    FplImportRequest,
    FplIngestionService,
    FplReplayRequest,
    _validate_database_reference,
)
from dmf_pulse.ingestion.fpl.service import (
    _engine as _fpl_database_engine,
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
from dmf_pulse.ingestion.odds.config import load_provider_config, load_rights_profiles
from dmf_pulse.ingestion.odds.credentials import (
    RuntimeOddsCredentialProvider,
    credential_is_configured,
)
from dmf_pulse.ingestion.odds.mapping import OddsMappingPlan, load_mapping_plan
from dmf_pulse.ingestion.odds.models import (
    OddsIngestionResult,
    OddsQuality,
    OddsValidationResult,
    ProviderFailure,
    ProviderFailureCode,
    QuotaSource,
    QuotaState,
)
from dmf_pulse.ingestion.odds.parser import CONTRACT_VERSION, ParsedOddsPayload, parse_odds_payload
from dmf_pulse.ingestion.odds.persistence import (
    OddsPersistence,
    PreparedOddsPublication,
    PublishCounts,
    attest_publication_batch,
    create_publication_batch,
    ensure_odds_provider,
    ensure_synthetic_odds_provider,
)
from dmf_pulse.ingestion.repository import (
    append_processing_event_idempotent,
    get_or_create_raw_content,
    get_or_create_raw_storage_object,
    record_ingestion_run,
    record_received_snapshot,
    record_rights_decision,
    register_rights_profile,
)
from dmf_pulse.ingestion.rights import decide_rights, require_rights

MAX_INPUT_BYTES = 5 * 1024 * 1024
DEFAULT_CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


class _FrozenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class OddsImportRequest(_FrozenRequest):
    input_path: Path
    mapping_plan_path: Path
    captured_at: datetime
    information_cutoff: datetime
    rights_profile_id: str
    database_url_ref: str = DATABASE_REF
    quota: QuotaState | None = None
    processing_at: datetime | None = None


class OddsReplayRequest(_FrozenRequest):
    fixture_set: Path
    scenario: str = Field(min_length=1, max_length=80)
    information_cutoff: datetime = DEFAULT_CUTOFF
    rights_profile_id: str = "synthetic_the_odds_api_v1"
    database_url_ref: str = DATABASE_REF


@dataclass(frozen=True, slots=True)
class OddsOperationOutcome:
    result: OddsIngestionResult
    exit_code: int


@dataclass(frozen=True, slots=True)
class _Envelope:
    source_snapshot_id: UUID
    rights_profile_record_id: UUID


@dataclass(frozen=True, slots=True)
class _PromotionOutcome:
    counts: PublishCounts
    publication_batch_id: UUID
    usable_at: datetime | None
    attestation_error: str | None = None
    temporal_integrity_blocker: bool = False


def _read_bounded(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            body = handle.read(MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise IngestionError("FIXTURE_NOT_APPROVED", "odds input is unavailable") from exc
    if len(body) > MAX_INPUT_BYTES:
        raise IngestionError("PAYLOAD_TOO_LARGE", "odds input exceeds the byte limit")
    return body


def _quality(warnings: tuple[str, ...] = (), blockers: tuple[str, ...] = ()) -> OddsQuality:
    return OddsQuality(
        status="BLOCKING" if blockers else "WARNING" if warnings else "PASS",
        warnings=tuple(sorted(set(warnings))),
        blockers=tuple(sorted(set(blockers))),
    )


def _empty_result(
    *,
    status: Literal["COMPLETE", "OBSERVED_NOT_USABLE", "QUARANTINED", "BLOCKED", "FAILED"],
    quality: OddsQuality,
    source_snapshot_id: UUID | None = None,
    quota: QuotaState | None = None,
    error: ProviderFailure | None = None,
) -> OddsIngestionResult:
    return OddsIngestionResult(
        status=status,
        source_snapshot_id=source_snapshot_id,
        events_seen=0,
        operator_books_seen=0,
        complete_books_created=0,
        incomplete_books_created=0,
        observations_created=0,
        observations_reused=0,
        quarantined=1 if status == "QUARANTINED" else 0,
        quota=quota,
        quality=quality,
        error=error,
    )


class OddsIngestionService:
    def __init__(
        self,
        *,
        repository_root: Path | None = None,
        credential_provider: CredentialProvider | None = None,
        transport_factory: Callable[[], OddsTransport] = UrllibOddsTransport,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        processing_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.repository_root = (repository_root or Path.cwd()).resolve()
        self.credential_provider = credential_provider or RuntimeOddsCredentialProvider()
        self.transport_factory = transport_factory
        self.clock = clock
        self.processing_clock = processing_clock
        self.sleeper = sleeper
        self.monotonic = monotonic

    def validate(
        self,
        input_path: Path,
        *,
        provider: str = "the_odds_api",
        contract_version: str = CONTRACT_VERSION,
    ) -> OddsValidationResult:
        if provider != "the_odds_api" or contract_version != CONTRACT_VERSION:
            raise IngestionError("USAGE_INVALID", "odds provider contract is unsupported")
        parsed = parse_odds_payload(_read_bounded(input_path))
        quality = _quality(parsed.warnings)
        return OddsValidationResult(
            status="VALID_WITH_WARNINGS" if parsed.warnings else "VALID",
            contract_version="the-odds-api-v4-reference-v1",
            events_seen=len(parsed.events),
            operator_books_seen=parsed.operator_books_seen,
            payload_semantic_sha256=parsed.semantic_sha256,
            schema_fingerprint=parsed.schema_fingerprint,
            quality=quality,
        )

    def replay(self, request: OddsReplayRequest) -> OddsOperationOutcome:
        if request.rights_profile_id != "synthetic_the_odds_api_v1":
            raise IngestionError("RIGHTS_BLOCKED", "odds replay requires synthetic authority")
        fixture_root = request.fixture_set.resolve()
        scenarios_path = fixture_root / "scenarios.json"
        approved_scenarios = approve_synthetic_fixture(
            scenarios_path, profile_id=request.rights_profile_id
        )
        try:
            scenarios_value = json.loads(approved_scenarios.path.read_text(encoding="utf-8"))
            scenario = scenarios_value["scenarios"][request.scenario]
            payload_name = scenario["payload"]
            mapping_name = scenario["mapping_plan"]
            captured_at = datetime.fromisoformat(
                str(scenario["captured_at"]).replace("Z", "+00:00")
            ).astimezone(UTC)
            processing_at = datetime.fromisoformat(
                str(scenario["processing_at"]).replace("Z", "+00:00")
            ).astimezone(UTC)
            post_commit_usable_at = datetime.fromisoformat(
                str(scenario["post_commit_usable_at"]).replace("Z", "+00:00")
            ).astimezone(UTC)
            headers = scenario["response_headers"]
            quota = QuotaState(
                remaining=int(headers["x-requests-remaining"]),
                used=int(headers["x-requests-used"]),
                last_cost=int(headers["x-requests-last"]),
                observed_at=captured_at,
                source=QuotaSource.SYNTHETIC_FIXTURE,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise IngestionError("FIXTURE_NOT_APPROVED", "odds scenario is invalid") from exc
        payload = fixture_root / str(payload_name)
        mapping = fixture_root / str(mapping_name)
        approve_synthetic_fixture(payload, profile_id=request.rights_profile_id)
        approve_synthetic_fixture(mapping, profile_id=request.rights_profile_id)
        mapping_plan = load_mapping_plan(mapping)
        fixture_repository_root = next(
            (
                parent.parent
                for parent in approved_scenarios.path.parents
                if parent.name == "fixtures"
            ),
            None,
        )
        if fixture_repository_root is None:
            raise IngestionError(
                "FIXTURE_NOT_APPROVED", "odds fixture root is outside the repository"
            )
        self._seed_fpl_fixture(
            request.database_url_ref,
            request.information_cutoff,
            repository_root=fixture_repository_root,
            schedule_evidence_at=mapping_plan.approved_at,
        )
        return self._import_payload(
            OddsImportRequest(
                input_path=payload,
                mapping_plan_path=mapping,
                captured_at=captured_at,
                information_cutoff=request.information_cutoff,
                rights_profile_id=request.rights_profile_id,
                database_url_ref=request.database_url_ref,
                quota=quota,
                processing_at=processing_at,
            ),
            post_commit_clock=lambda: post_commit_usable_at,
        )

    def _seed_fpl_fixture(
        self,
        database_url_ref: str,
        information_cutoff: datetime,
        *,
        repository_root: Path | None = None,
        schedule_evidence_at: datetime | None = None,
    ) -> None:
        """Seed synthetic schedule evidence, honoring an explicit historical knowledge time."""

        selected_root = (repository_root or self.repository_root).resolve()
        if schedule_evidence_at is None:
            outcome = FplIngestionService(repository_root=selected_root).replay(
                FplReplayRequest(
                    fixture_set=selected_root / "fixtures/fpl/FPL-004",
                    scenario="happy_path",
                    information_cutoff=information_cutoff,
                    rights_profile_id="synthetic_test_v1",
                    database_url_ref=database_url_ref,
                    competition_key="SYNTHETIC_PL",
                    season_code="2026/27",
                )
            )
        else:
            evidence_at = require_utc(schedule_evidence_at)
            outcome = FplIngestionService(
                repository_root=selected_root,
                clock=lambda: evidence_at,
            ).import_pair(
                FplImportRequest(
                    bootstrap_path=(
                        selected_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"
                    ),
                    fixtures_path=(selected_root / "fixtures/fpl/FPL-004/happy_path/fixtures.json"),
                    competition_key="SYNTHETIC_PL",
                    season_code="2026/27",
                    captured_at=evidence_at,
                    information_cutoff=information_cutoff,
                    rights_profile_id="synthetic_test_v1",
                    database_url_ref=database_url_ref,
                )
            )
        if outcome.exit_code != 0:
            raise IngestionError("MAPPING_CONFLICT", "FPL fixture seed is not usable")

    def import_payload(self, request: OddsImportRequest) -> OddsOperationOutcome:
        """Import an approved payload using only the injected post-commit clock."""

        return self._import_payload(request, post_commit_clock=self.clock)

    def _import_payload(
        self,
        request: OddsImportRequest,
        *,
        post_commit_clock: Callable[[], datetime],
    ) -> OddsOperationOutcome:
        _validate_database_reference(request.database_url_ref)
        profiles = load_rights_profiles()
        profile = profiles.get(request.rights_profile_id)
        if profile is None:
            raise IngestionError("RIGHTS_BLOCKED", "odds rights profile is unavailable")
        if profile.rights_profile_id != "synthetic_the_odds_api_v1":
            raise IngestionError("RIGHTS_BLOCKED", "manual odds import is not synthetic")
        approved_payload = approve_synthetic_fixture(
            request.input_path, profile_id=profile.rights_profile_id
        )
        approve_synthetic_fixture(request.mapping_plan_path, profile_id=profile.rights_profile_id)
        body = _read_bounded(approved_payload.path)
        mapping_plan = load_mapping_plan(request.mapping_plan_path)
        return self._ingest(
            body=body,
            approved_fixture=approved_payload,
            mapping_plan=mapping_plan,
            profile=profile,
            captured_at=request.captured_at,
            information_cutoff=request.information_cutoff,
            database_url_ref=request.database_url_ref,
            quota=request.quota,
            operation="synthetic_import",
            processing_at=request.processing_at,
            post_commit_clock=post_commit_clock,
        )

    def _engine(self, database_url_ref: str) -> Engine:
        return _fpl_database_engine(database_url_ref)

    def _latest_provider_quota(self, database_url_ref: str) -> QuotaState | None:
        engine = self._engine(database_url_ref)
        try:
            with session_factory(engine)() as session:
                row = (
                    session.execute(
                        select(provider_quota_observation)
                        .join(
                            data_provider,
                            data_provider.c.provider_id == provider_quota_observation.c.provider_id,
                        )
                        .where(data_provider.c.provider_key == "the_odds_api")
                        .order_by(
                            provider_quota_observation.c.observed_at.desc(),
                            provider_quota_observation.c.quota_observation_id.desc(),
                        )
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
            if row is None:
                return None
            return QuotaState(
                remaining=int(row["remaining"]),
                used=int(row["used"]),
                last_cost=int(row["last_cost"]),
                observed_at=require_utc(row["observed_at"]),
                source=QuotaSource(str(row["source"])),
            )
        finally:
            engine.dispose()

    def _create_envelope(
        self,
        session: Session,
        *,
        body: bytes | None,
        approved_fixture: ApprovedFixture | None,
        mapping_plan: OddsMappingPlan | None,
        profile: RightsProfile,
        captured_at: datetime,
        quota: QuotaState | None,
        operation: str,
        sanitized_target: str | None = None,
        transport_request_fingerprint: str | None = None,
        provider_request_id_sha256: str | None = None,
        ingestion_run_id: UUID | None = None,
        attempt_number: int = 1,
        request_started_at: datetime | None = None,
        http_status: int | None = None,
        content_type: str | None = "application/json",
        body_sha256_override: str | None = None,
        body_size_override: int | None = None,
        body_capture_state: str = "COMPLETE",
        captured_prefix_sha256: str | None = None,
        captured_prefix_size: int | None = None,
        quota_header_state: str = "VALID",
        requested_delay_seconds: int | None = None,
        applied_delay_seconds: int | None = None,
        attempt_outcome: str | None = None,
    ) -> _Envelope:
        source_provider_id = ensure_synthetic_odds_provider(session)
        if profile.provider_key != "synthetic_the_odds_api":
            from dmf_pulse.ingestion.odds.persistence import ensure_odds_provider

            source_provider_id = ensure_odds_provider(session)
        profile_record_id = register_rights_profile(session, profile)
        raw_decision = decide_rights(profile, RightsCapability.RAW_STORAGE, checked_at=captured_at)
        body_sha256 = hashlib.sha256(body).hexdigest() if body is not None else body_sha256_override
        body_size = len(body) if body is not None else body_size_override
        raw_blob_id: UUID | None = None
        storage_id: UUID | None = None
        raw_policy = "FORBIDDEN"
        if raw_decision.decision == "ALLOW" and approved_fixture is not None and body is not None:
            raw_blob_id, raw_hash = get_or_create_raw_content(session, body)
            storage_id = get_or_create_raw_storage_object(
                session,
                raw_blob_id=raw_blob_id,
                rights_profile_record_id=profile_record_id,
                body_sha256=raw_hash,
                storage_uri=f"fixture:{approved_fixture.relative_path}",
                content_type="application/json",
                retention_seconds=profile.retention_seconds,
                access_allowed=True,
                export_allowed=True,
                backup_allowed=True,
            )
            raw_policy = "ALLOWED"
        if ingestion_run_id is None:
            operation_id = str(uuid4())
            run_id = record_ingestion_run(
                session,
                provider_id=source_provider_id,
                pair_key=operation_id,
                started_at=request_started_at or captured_at,
                logical_prefix="odd005",
                resource="soccer_epl/h2h",
                adapter_version=CONTRACT_VERSION,
            )
        else:
            run_id = ingestion_run_id
        safe_context: dict[str, object] = {
            "mapping_plan_sha256": mapping_plan.sha256 if mapping_plan is not None else None,
            "operation": operation,
            "provider_family": "the_odds_api",
            "provider_request_id_sha256": provider_request_id_sha256,
            "raw_storage_policy": raw_policy,
            "transport_request_fingerprint": transport_request_fingerprint,
            "body_capture_state": body_capture_state,
            "captured_prefix_sha256": captured_prefix_sha256,
            "captured_prefix_size": captured_prefix_size,
            "http_status": http_status,
            "quota_header_state": quota_header_state,
            "requested_delay_seconds": requested_delay_seconds,
            "applied_delay_seconds": applied_delay_seconds,
            "attempt_outcome": attempt_outcome,
        }
        snapshot_id = record_received_snapshot(
            session,
            provider_id=source_provider_id,
            ingestion_run_id=run_id,
            attempt_number=attempt_number,
            resource="soccer_epl/h2h",
            captured_at=captured_at,
            body=body,
            raw_blob_id=raw_blob_id,
            raw_storage_object_id=storage_id,
            rights_profile_record_id=profile_record_id,
            profile=profile,
            sanitized_target=(
                sanitized_target
                or ("fixture:odds" if approved_fixture is not None else "provider:odds")
            ),
            context=safe_context,
            raw_storage_policy=raw_policy,
            adapter_version=CONTRACT_VERSION,
            contract_version=CONTRACT_VERSION,
            actor="the-odds-api-reference-adapter",
            request_fingerprint_override=transport_request_fingerprint,
            body_sha256_override=body_sha256,
            body_size_override=body_size,
            request_started_at=request_started_at,
            http_status=http_status,
            content_type=content_type,
        )
        access_capability = (
            RightsCapability.AUTOMATED_ACCESS
            if operation == "controlled_snapshot"
            else RightsCapability.MANUAL_IMPORT
        )
        for capability in (
            access_capability,
            RightsCapability.TRANSIENT_PROCESSING,
            RightsCapability.RAW_STORAGE,
            RightsCapability.DERIVED_STORAGE,
            RightsCapability.PRIVATE_INTERNAL_USE,
        ):
            decision = decide_rights(profile, capability, checked_at=captured_at)
            record_rights_decision(
                session,
                rights_profile_record_id=profile_record_id,
                source_snapshot_id=snapshot_id,
                decision=decision,
                context={"capability": capability.value, "operation": operation},
            )
        append_processing_event_idempotent(
            session,
            snapshot_id=snapshot_id,
            stage="STORED" if raw_policy == "ALLOWED" else "RAW_DISCARDED",
            event_at=captured_at,
            input_sha256=body_sha256,
            output_sha256=body_sha256,
            safe_details={"raw_storage_policy": raw_policy},
            stage_version=CONTRACT_VERSION,
            actor="the-odds-api-reference-adapter",
        )
        if quota is not None:
            session.execute(
                insert(provider_quota_observation).values(
                    source_snapshot_id=snapshot_id,
                    provider_id=source_provider_id,
                    remaining=quota.remaining,
                    used=quota.used,
                    last_cost=quota.last_cost,
                    observed_at=quota.observed_at,
                    source=quota.source.value,
                    request_fingerprint=(
                        transport_request_fingerprint
                        or canonical_sha256(
                            {
                                "markets": "h2h",
                                "provider": "the_odds_api",
                                "regions": "uk",
                                "sport": "soccer_epl",
                            }
                        )
                    ),
                )
            )
        return _Envelope(snapshot_id, profile_record_id)

    def _record_live_attempts(
        self,
        factory: sessionmaker[Session],
        *,
        profile: RightsProfile,
        attempts: tuple[OddsRetrievalAttempt, ...],
        successful_body: bytes | None = None,
    ) -> _Envelope:
        if not attempts:
            raise IngestionError("INTERNAL_INVARIANT", "transport evidence is unavailable")
        final_envelope: _Envelope | None = None
        with factory.begin() as session:
            provider_id = ensure_odds_provider(session)
            run_id = record_ingestion_run(
                session,
                provider_id=provider_id,
                pair_key=str(uuid4()),
                started_at=attempts[0].request_started_at,
                logical_prefix="odd005",
                resource="soccer_epl/h2h",
                adapter_version=CONTRACT_VERSION,
            )
            for attempt in attempts:
                is_success = attempt.failure_code is None
                envelope = self._create_envelope(
                    session,
                    body=successful_body if is_success else None,
                    approved_fixture=None,
                    mapping_plan=None,
                    profile=profile,
                    captured_at=attempt.received_at,
                    quota=attempt.quota,
                    operation="controlled_snapshot",
                    sanitized_target=attempt.sanitized_target,
                    transport_request_fingerprint=attempt.request_fingerprint,
                    provider_request_id_sha256=attempt.provider_request_id_sha256,
                    ingestion_run_id=run_id,
                    attempt_number=attempt.attempt_number,
                    request_started_at=attempt.request_started_at,
                    http_status=attempt.http_status,
                    content_type=attempt.content_type,
                    body_sha256_override=attempt.body_sha256,
                    body_size_override=attempt.body_size,
                    body_capture_state=attempt.body_capture_state,
                    captured_prefix_sha256=attempt.captured_prefix_sha256,
                    captured_prefix_size=attempt.captured_prefix_size,
                    quota_header_state=attempt.quota_header_state,
                    requested_delay_seconds=attempt.requested_delay_seconds,
                    applied_delay_seconds=attempt.applied_delay_seconds,
                    attempt_outcome=attempt.attempt_outcome,
                )
                final_envelope = envelope
                if attempt.failure_code is None:
                    continue
                session.execute(
                    insert(data_quality_issue).values(
                        source_snapshot_id=envelope.source_snapshot_id,
                        issue_type=attempt.failure_code.value,
                        severity="P1",
                        status="OPEN",
                        detected_at=attempt.received_at,
                        decision_impact="BLOCKING",
                        details={
                            "body_capture_state": attempt.body_capture_state,
                            "error_code": attempt.failure_code.value,
                            "http_status": attempt.http_status,
                            "quota_header_state": attempt.quota_header_state,
                            "requested_delay_seconds": attempt.requested_delay_seconds,
                            "applied_delay_seconds": attempt.applied_delay_seconds,
                            "attempt_outcome": attempt.attempt_outcome,
                        },
                        subject_scope="SOURCE_SNAPSHOT",
                        stage="RETRIEVAL",
                        message="odds provider retrieval failed safely",
                    )
                )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=envelope.source_snapshot_id,
                    stage="REJECTED",
                    event_at=attempt.received_at,
                    input_sha256=attempt.body_sha256,
                    output_sha256=canonical_sha256(attempt.failure_code.value),
                    error_code=attempt.failure_code.value,
                    safe_details={
                        "body_capture_state": attempt.body_capture_state,
                        "http_status": attempt.http_status,
                        "quota_header_state": attempt.quota_header_state,
                        "requested_delay_seconds": attempt.requested_delay_seconds,
                        "applied_delay_seconds": attempt.applied_delay_seconds,
                        "attempt_outcome": attempt.attempt_outcome,
                    },
                    stage_version=CONTRACT_VERSION,
                    actor="the-odds-api-reference-adapter",
                )
        if final_envelope is None:  # pragma: no cover - non-empty tuple invariant
            raise IngestionError("INTERNAL_INVARIANT", "transport envelope was not recorded")
        return final_envelope

    def _quarantine(
        self,
        factory: sessionmaker[Session],
        envelope: _Envelope,
        captured_at: datetime,
        error: IngestionError,
    ) -> None:
        with factory.begin() as session:
            session.execute(
                insert(data_quality_issue).values(
                    source_snapshot_id=envelope.source_snapshot_id,
                    issue_type=error.code[:80],
                    severity="P1",
                    status="OPEN",
                    detected_at=captured_at,
                    decision_impact="BLOCKING",
                    details={"error_code": error.code},
                    subject_scope="SOURCE_SNAPSHOT",
                    stage="VALIDATION",
                    message="odds source failed bounded validation or explicit mapping",
                )
            )
            append_processing_event_idempotent(
                session,
                snapshot_id=envelope.source_snapshot_id,
                stage="QUARANTINED",
                event_at=captured_at,
                error_code=error.code,
                safe_details={"error_code": error.code},
                stage_version=CONTRACT_VERSION,
                actor="the-odds-api-reference-adapter",
            )

    def _record_retryable_failure(
        self,
        factory: sessionmaker[Session],
        envelope: _Envelope,
        captured_at: datetime,
        error: IngestionError,
    ) -> None:
        with factory.begin() as session:
            append_processing_event_idempotent(
                session,
                snapshot_id=envelope.source_snapshot_id,
                stage="FAILED_RETRYABLE",
                event_at=captured_at,
                error_code=error.code,
                safe_details={"error_code": error.code},
                stage_version=CONTRACT_VERSION,
                actor="the-odds-api-reference-adapter",
            )

    def _ingest(
        self,
        *,
        body: bytes,
        approved_fixture: ApprovedFixture | None,
        mapping_plan: OddsMappingPlan,
        profile: RightsProfile,
        captured_at: datetime,
        information_cutoff: datetime,
        database_url_ref: str,
        quota: QuotaState | None,
        operation: str,
        processing_at: datetime | None,
        post_commit_clock: Callable[[], datetime],
    ) -> OddsOperationOutcome:
        captured = require_utc(captured_at)
        cutoff = require_utc(information_cutoff)
        processing = require_utc(processing_at or self.processing_clock())
        if processing < captured:
            raise IngestionError("CLOCK_REGRESSION", "processing clock precedes receipt")
        require_rights(profile, RightsCapability.MANUAL_IMPORT, checked_at=captured)
        require_rights(profile, RightsCapability.TRANSIENT_PROCESSING, checked_at=captured)
        require_rights(profile, RightsCapability.DERIVED_STORAGE, checked_at=captured)
        require_rights(profile, RightsCapability.PRIVATE_INTERNAL_USE, checked_at=captured)
        engine = self._engine(database_url_ref)
        try:
            factory = session_factory(engine)
            with factory.begin() as session:
                envelope = self._create_envelope(
                    session,
                    body=body,
                    approved_fixture=approved_fixture,
                    mapping_plan=mapping_plan,
                    profile=profile,
                    captured_at=captured,
                    quota=quota,
                    operation=operation,
                )
            try:
                parsed = parse_odds_payload(body)
            except IngestionError as exc:
                self._quarantine(factory, envelope, processing, exc)
                return OddsOperationOutcome(
                    _empty_result(
                        status="QUARANTINED",
                        source_snapshot_id=envelope.source_snapshot_id,
                        quota=quota,
                        quality=_quality(blockers=(exc.code,)),
                    ),
                    exit_code=3,
                )
            try:
                promotion = self._promote(
                    factory,
                    envelope=envelope,
                    parsed=parsed,
                    mapping_plan=mapping_plan,
                    captured_at=captured,
                    processing_at=processing,
                    mapping_cutoff=cutoff,
                    post_commit_clock=post_commit_clock,
                )
            except IngestionError as exc:
                if exc.code == "DATABASE_RETRYABLE":
                    self._record_retryable_failure(factory, envelope, processing, exc)
                    raise
                self._quarantine(factory, envelope, processing, exc)
                return OddsOperationOutcome(
                    OddsIngestionResult(
                        status="QUARANTINED",
                        source_snapshot_id=envelope.source_snapshot_id,
                        events_seen=len(parsed.events),
                        operator_books_seen=parsed.operator_books_seen,
                        complete_books_created=0,
                        incomplete_books_created=0,
                        observations_created=0,
                        observations_reused=0,
                        quarantined=1,
                        quota=quota,
                        quality=_quality(parsed.warnings, (exc.code,)),
                        error=None,
                    ),
                    exit_code=3,
                )
            counts = promotion.counts
            post_cutoff = promotion.usable_at is None or promotion.usable_at > cutoff
            warnings = list(parsed.warnings)
            if counts.incomplete_books_created:
                warnings.append("INCOMPLETE_BOOK")
            if post_cutoff:
                warnings.append("POST_CUTOFF")
            blockers: list[str] = []
            if promotion.attestation_error is not None:
                if promotion.temporal_integrity_blocker:
                    blockers.append(promotion.attestation_error)
                else:
                    warnings.append(promotion.attestation_error)
            return OddsOperationOutcome(
                OddsIngestionResult(
                    status="OBSERVED_NOT_USABLE" if post_cutoff else "COMPLETE",
                    source_snapshot_id=envelope.source_snapshot_id,
                    events_seen=len(parsed.events),
                    operator_books_seen=counts.operator_books_seen,
                    complete_books_created=counts.complete_books_created,
                    incomplete_books_created=counts.incomplete_books_created,
                    observations_created=counts.observations_created,
                    observations_reused=counts.observations_reused,
                    quarantined=0,
                    quota=quota,
                    quality=_quality(tuple(warnings), tuple(blockers)),
                    error=None,
                ),
                exit_code=4 if blockers else 2 if post_cutoff else 0,
            )
        finally:
            engine.dispose()

    def _promote(
        self,
        factory: sessionmaker[Session],
        *,
        envelope: _Envelope,
        parsed: ParsedOddsPayload,
        mapping_plan: OddsMappingPlan,
        captured_at: datetime,
        processing_at: datetime,
        mapping_cutoff: datetime,
        post_commit_clock: Callable[[], datetime],
    ) -> _PromotionOutcome:
        prepared: PreparedOddsPublication
        with factory.begin() as session:
            append_processing_event_idempotent(
                session,
                snapshot_id=envelope.source_snapshot_id,
                stage="PARSED",
                event_at=processing_at,
                input_sha256=parsed.body_sha256,
                output_sha256=parsed.semantic_sha256,
                safe_details={"schema_fingerprint": parsed.schema_fingerprint},
                stage_version=CONTRACT_VERSION,
                actor="the-odds-api-reference-adapter",
            )
            append_processing_event_idempotent(
                session,
                snapshot_id=envelope.source_snapshot_id,
                stage="VALIDATED",
                event_at=processing_at,
                input_sha256=parsed.semantic_sha256,
                output_sha256=parsed.schema_fingerprint,
                safe_details={"warnings": list(parsed.warnings)},
                stage_version=CONTRACT_VERSION,
                actor="the-odds-api-reference-adapter",
            )
            persistence = OddsPersistence(
                session,
                snapshot_id=envelope.source_snapshot_id,
                rights_profile_record_id=envelope.rights_profile_record_id,
                captured_at=captured_at,
                mapping_cutoff=mapping_cutoff,
                mapping_plan=mapping_plan,
            )
            prepared = persistence.prepare(parsed)
            append_processing_event_idempotent(
                session,
                snapshot_id=envelope.source_snapshot_id,
                stage="MAPPED",
                event_at=processing_at,
                input_sha256=parsed.semantic_sha256,
                output_sha256=mapping_plan.sha256,
                safe_details={
                    "approved_at": mapping_plan.approved_at.isoformat(),
                    "evidence_class": mapping_plan.evidence_class,
                    "mapping_cutoff": mapping_cutoff.isoformat(),
                    "mapping_plan_id": mapping_plan.plan_id,
                    "mapping_plan_sha256": mapping_plan.sha256,
                    "reviewer": mapping_plan.reviewer,
                    "status": mapping_plan.status,
                },
                stage_version=CONTRACT_VERSION,
                actor="the-odds-api-reference-adapter",
            )
            append_processing_event_idempotent(
                session,
                snapshot_id=envelope.source_snapshot_id,
                stage="PROMOTED",
                event_at=processing_at,
                input_sha256=mapping_plan.sha256,
                output_sha256=parsed.semantic_sha256,
                safe_details={"semantics": "MATCH_RESULT_1X2/FULL_TIME"},
                stage_version=CONTRACT_VERSION,
                actor="the-odds-api-reference-adapter",
            )
            for warning in parsed.warnings:
                session.execute(
                    insert(data_quality_issue).values(
                        source_snapshot_id=envelope.source_snapshot_id,
                        issue_type=warning.partition(":")[0][:80],
                        severity="P2",
                        status="OPEN",
                        detected_at=processing_at,
                        decision_impact="NONBLOCKING",
                        details=(
                            {
                                "duplicate_outcomes": [
                                    {
                                        "bookmaker_key": item.bookmaker_key,
                                        "duplicate_count": item.duplicate_count,
                                        "event_external_id_sha256": item.event_external_id_sha256,
                                        "market_key": item.market_key,
                                        "outcome": item.outcome,
                                    }
                                    for item in parsed.duplicate_outcomes
                                ],
                                "warning_sha256": canonical_sha256(warning),
                            }
                            if warning == "DUPLICATE_OUTCOME_DEDUPED"
                            else {"warning_sha256": canonical_sha256(warning)}
                        ),
                        subject_scope="SOURCE_SNAPSHOT",
                        stage="VALIDATION",
                        message="odds source has bounded nonblocking drift",
                    )
                )
            append_processing_event_idempotent(
                session,
                snapshot_id=envelope.source_snapshot_id,
                stage="QUALITY_PASSED",
                event_at=processing_at,
                input_sha256=parsed.schema_fingerprint,
                output_sha256=canonical_sha256(parsed.warnings),
                safe_details={"blocking_issues": 0, "warning_count": len(parsed.warnings)},
                stage_version=CONTRACT_VERSION,
                actor="the-odds-api-reference-adapter",
            )
        with factory.begin() as session:
            activation_event_id = append_processing_event_idempotent(
                session,
                snapshot_id=envelope.source_snapshot_id,
                stage="USABLE",
                event_at=processing_at,
                input_sha256=parsed.semantic_sha256,
                output_sha256=parsed.semantic_sha256,
                safe_details={"publication_state": "ACTIVATED_UNATTESTED"},
                stage_version=CONTRACT_VERSION,
                actor="the-odds-api-reference-adapter",
            )
            publication_batch_id = create_publication_batch(
                session,
                snapshot_id=envelope.source_snapshot_id,
                activation_event_id=activation_event_id,
                mapping_cutoff=mapping_cutoff,
                mapping_plan=mapping_plan,
            )
            counts = OddsPersistence.publish_prepared(
                session,
                prepared=prepared,
                snapshot_id=envelope.source_snapshot_id,
                rights_profile_record_id=envelope.rights_profile_record_id,
                captured_at=captured_at,
                publication_batch_id=publication_batch_id,
            )

        try:
            sampled = post_commit_clock()
            usable_at = require_utc(sampled)
        except Exception:
            return _PromotionOutcome(
                counts,
                publication_batch_id,
                None,
                "PUBLICATION_CLOCK_INVALID",
                True,
            )
        if usable_at < captured_at or usable_at < processing_at:
            return _PromotionOutcome(
                counts,
                publication_batch_id,
                None,
                "PUBLICATION_CLOCK_REGRESSION",
                True,
            )
        try:
            with factory.begin() as session:
                attested = attest_publication_batch(
                    session,
                    publication_batch_id=publication_batch_id,
                    usable_at=usable_at,
                )
        except (DBAPIError, IngestionError):
            return _PromotionOutcome(
                counts,
                publication_batch_id,
                None,
                "PUBLICATION_ATTESTATION_PENDING",
            )
        return _PromotionOutcome(counts, publication_batch_id, attested)

    def repair_publication_attestation(
        self,
        *,
        source_snapshot_id: UUID,
        database_url_ref: str = DATABASE_REF,
    ) -> datetime:
        """Conservatively attest an already committed, still-unattested batch."""

        _validate_database_reference(database_url_ref)
        engine = self._engine(database_url_ref)
        try:
            factory = session_factory(engine)
            with factory() as session:
                row = (
                    session.execute(
                        select(
                            odds_publication_batch.c.publication_batch_id,
                            source_processing_event.c.event_at.label("activation_event_at"),
                            source_snapshot.c.received_at,
                            odds_publication_attestation.c.usable_at,
                        )
                        .join(
                            source_snapshot,
                            source_snapshot.c.source_snapshot_id
                            == odds_publication_batch.c.source_snapshot_id,
                        )
                        .join(
                            source_processing_event,
                            source_processing_event.c.processing_event_id
                            == odds_publication_batch.c.activation_event_id,
                        )
                        .outerjoin(
                            odds_publication_attestation,
                            odds_publication_attestation.c.publication_batch_id
                            == odds_publication_batch.c.publication_batch_id,
                        )
                        .where(odds_publication_batch.c.source_snapshot_id == source_snapshot_id)
                    )
                    .mappings()
                    .one_or_none()
                )
            if row is None:
                raise IngestionError("ATTESTATION_UNAVAILABLE", "publication batch is unavailable")
            existing = row["usable_at"]
            if isinstance(existing, datetime):
                return require_utc(existing)
            try:
                sampled = require_utc(self.clock())
            except Exception as exc:
                raise IngestionError(
                    "CLOCK_INVALID",
                    "publication repair clock must be timezone-aware UTC",
                ) from exc
            captured = require_utc(row["received_at"])
            activation_event_at = require_utc(row["activation_event_at"])
            if sampled < captured or sampled < activation_event_at:
                raise IngestionError(
                    "CLOCK_REGRESSION",
                    "publication repair clock precedes receipt or activation event",
                )
            with factory.begin() as session:
                return attest_publication_batch(
                    session,
                    publication_batch_id=row["publication_batch_id"],
                    usable_at=sampled,
                )
        finally:
            engine.dispose()

    def snapshot(
        self,
        *,
        provider: str,
        competition_key: str,
        sport_key: str,
        region: str,
        market: str,
        as_of: datetime,
        database_url_ref: str = DATABASE_REF,
        quota: QuotaState | None = None,
    ) -> OddsOperationOutcome:
        config = load_provider_config()
        _validate_database_reference(database_url_ref)
        require_utc(as_of)
        if (
            provider != config.provider_key
            or competition_key != "PL"
            or sport_key not in config.sport_keys
            or region not in config.regions
            or market not in config.markets
        ):
            raise IngestionError("USAGE_INVALID", "odds snapshot options are not allowlisted")
        profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
        require_rights(profile, RightsCapability.AUTOMATED_ACCESS, checked_at=self.clock())
        quota_lookup_failed = False
        try:
            effective_quota = (
                quota if quota is not None else self._latest_provider_quota(database_url_ref)
            )
        except Exception:
            # Discard the database exception before deciding the safe public
            # outcome.  Credential providers are arbitrary secret-bearing
            # boundaries and must never be called from an error handler.
            effective_quota = None
            quota_lookup_failed = True
        if quota_lookup_failed:
            # The default credential-free command remains a deterministic,
            # offline refusal when its referenced database is unavailable.
            if not credential_is_configured(self.credential_provider):
                code = ProviderFailureCode.CREDENTIAL_UNAVAILABLE
                return OddsOperationOutcome(
                    _empty_result(
                        status="BLOCKED",
                        quality=_quality(blockers=(code.value,)),
                        error=ProviderFailure(
                            code=code,
                            message="approved runtime credential is unavailable",
                            retryable=False,
                            transport_called=False,
                        ),
                    ),
                    exit_code=4,
                )
            raise IngestionError(
                "DATABASE_UNAVAILABLE", "quota evidence is unavailable before transport"
            )
        client = OddsClient(
            profile,
            credential_provider=self.credential_provider,
            transport_factory=self.transport_factory,
            clock=self.clock,
            sleeper=self.sleeper,
            monotonic=self.monotonic,
        )
        try:
            fetched = client.fetch(quota=effective_quota)
        except OddsFetchFailure as exc:
            engine = self._engine(database_url_ref)
            try:
                factory = session_factory(engine)
                envelope = self._record_live_attempts(
                    factory,
                    profile=profile,
                    attempts=exc.attempts,
                )
            finally:
                engine.dispose()
            code = exc.attempts[-1].failure_code or ProviderFailureCode.SOURCE_UNAVAILABLE
            failure = ProviderFailure(
                code=code,
                message=exc.message,
                retryable=exc.retryable,
                transport_called=True,
            )
            return OddsOperationOutcome(
                _empty_result(
                    status="FAILED",
                    source_snapshot_id=envelope.source_snapshot_id,
                    quality=_quality(blockers=(code.value,)),
                    quota=exc.attempts[-1].quota or effective_quota,
                    error=failure,
                ),
                exit_code=5,
            )
        except IngestionError as exc:
            try:
                code = ProviderFailureCode(exc.code)
            except ValueError:
                code = ProviderFailureCode.SOURCE_UNAVAILABLE
            failure = ProviderFailure(
                code=code,
                message=exc.message,
                retryable=exc.retryable,
                transport_called=client.transport_call_count > 0,
            )
            controlled = code in {
                ProviderFailureCode.RIGHTS_BLOCKED,
                ProviderFailureCode.CREDENTIAL_UNAVAILABLE,
                ProviderFailureCode.QUOTA_EXHAUSTED,
            }
            return OddsOperationOutcome(
                _empty_result(
                    status="BLOCKED" if controlled else "FAILED",
                    quality=_quality(blockers=(code.value,)),
                    quota=effective_quota,
                    error=failure,
                ),
                exit_code=4 if controlled else 5,
            )
        captured_at = fetched.quota.observed_at
        engine = self._engine(database_url_ref)
        try:
            factory = session_factory(engine)
            envelope = self._record_live_attempts(
                factory,
                profile=profile,
                attempts=fetched.attempts,
                successful_body=fetched.body,
            )
            try:
                parsed = parse_odds_payload(fetched.body)
            except IngestionError as exc:
                self._quarantine(factory, envelope, captured_at, exc)
                try:
                    failure_code = ProviderFailureCode(exc.code)
                except ValueError:
                    parse_failure: ProviderFailure | None = None
                else:
                    parse_failure = ProviderFailure(
                        code=failure_code,
                        message=exc.message,
                        retryable=False,
                        transport_called=True,
                    )
                return OddsOperationOutcome(
                    _empty_result(
                        status="QUARANTINED",
                        source_snapshot_id=envelope.source_snapshot_id,
                        quota=fetched.quota,
                        quality=_quality(blockers=(exc.code,)),
                        error=parse_failure,
                    ),
                    exit_code=3,
                )
            with factory.begin() as session:
                append_processing_event_idempotent(
                    session,
                    snapshot_id=envelope.source_snapshot_id,
                    stage="PARSED",
                    event_at=captured_at,
                    input_sha256=parsed.body_sha256,
                    output_sha256=parsed.semantic_sha256,
                    safe_details={"schema_fingerprint": parsed.schema_fingerprint},
                    stage_version=CONTRACT_VERSION,
                    actor="the-odds-api-reference-adapter",
                )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=envelope.source_snapshot_id,
                    stage="VALIDATED",
                    event_at=captured_at,
                    input_sha256=parsed.semantic_sha256,
                    output_sha256=parsed.schema_fingerprint,
                    safe_details={"warnings": list(parsed.warnings)},
                    stage_version=CONTRACT_VERSION,
                    actor="the-odds-api-reference-adapter",
                )
                session.execute(
                    insert(data_quality_issue).values(
                        source_snapshot_id=envelope.source_snapshot_id,
                        issue_type="MAPPING_PLAN_REQUIRED",
                        severity="P1",
                        status="OPEN",
                        detected_at=captured_at,
                        decision_impact="BLOCKING",
                        details={"provider": "the_odds_api"},
                        subject_scope="SOURCE_SNAPSHOT",
                        stage="MAPPING",
                        message="controlled snapshot has no approved mapping plan",
                    )
                )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=envelope.source_snapshot_id,
                    stage="REJECTED",
                    event_at=captured_at,
                    input_sha256=parsed.semantic_sha256,
                    output_sha256=canonical_sha256("MAPPING_PLAN_REQUIRED"),
                    error_code="MAPPING_PLAN_REQUIRED",
                    safe_details={"reason": "MAPPING_PLAN_REQUIRED"},
                    stage_version=CONTRACT_VERSION,
                    actor="the-odds-api-reference-adapter",
                )
            return OddsOperationOutcome(
                OddsIngestionResult(
                    status="OBSERVED_NOT_USABLE",
                    source_snapshot_id=envelope.source_snapshot_id,
                    events_seen=len(parsed.events),
                    operator_books_seen=parsed.operator_books_seen,
                    complete_books_created=0,
                    incomplete_books_created=0,
                    observations_created=0,
                    observations_reused=0,
                    quarantined=0,
                    quota=fetched.quota,
                    quality=_quality(parsed.warnings, ("MAPPING_PLAN_REQUIRED",)),
                    error=None,
                ),
                exit_code=2,
            )
        finally:
            engine.dispose()
