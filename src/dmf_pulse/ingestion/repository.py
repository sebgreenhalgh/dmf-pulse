"""Strict PostgreSQL persistence primitives for source envelopes and rights."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.models import require_utc
from dmf_pulse.data_model.repositories import SourceObservationRepository
from dmf_pulse.data_model.tables import (
    ingestion_run,
    raw_blob,
    raw_blob_deletion,
    raw_storage_deletion,
    raw_storage_object,
    rights_decision,
    rights_profile,
    source_processing_event,
    source_snapshot,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsDecision, RightsProfile


def _uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise IngestionError("INTERNAL_INVARIANT", "database returned an invalid identifier")
    return value


def register_rights_profile(session: Session, profile: RightsProfile) -> UUID:
    values = {
        "rights_profile_id": profile.rights_profile_id,
        "provider_key": profile.provider_key,
        "profile_version": profile.profile_version,
        "status": profile.status.value,
        "capabilities": {
            capability.value: value.value for capability, value in profile.capabilities.items()
        },
        "retention_seconds": profile.retention_seconds,
        "retention_reason": profile.retention_reason,
        "termination_deletion_required": profile.termination_deletion_required,
        "attribution_required": profile.attribution_required,
        "attribution_text": profile.attribution_text,
        "geography_scope": profile.geography_scope,
        "account_scope": profile.account_scope,
        "approved_purpose": profile.approved_purpose,
        "terms_source": profile.terms_source,
        "terms_version": profile.terms_version,
        "checked_at": require_utc(profile.checked_at),
        "human_approval_id": profile.human_approval_id,
        "approved_by": profile.approved_by,
        "approved_at": require_utc(profile.approved_at),
        "notes": profile.notes,
        "unresolved_rights": list(profile.unresolved_rights),
    }
    created = session.execute(
        postgresql_insert(rights_profile)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[rights_profile.c.rights_profile_id, rights_profile.c.profile_version]
        )
        .returning(rights_profile.c.rights_profile_record_id)
    ).scalar_one_or_none()
    if created is not None:
        return _uuid(created)
    existing = (
        session.execute(
            select(rights_profile).where(
                rights_profile.c.rights_profile_id == profile.rights_profile_id,
                rights_profile.c.profile_version == profile.profile_version,
            )
        )
        .mappings()
        .one()
    )
    for key, value in values.items():
        existing_value = existing[key]
        if key in {"checked_at", "approved_at"}:
            existing_value = require_utc(existing_value)
        if existing_value != value:
            raise IngestionError(
                "RIGHTS_BLOCKED", "stored rights profile conflicts with configured authority"
            )
    return _uuid(existing["rights_profile_record_id"])


def record_rights_decision(
    session: Session,
    *,
    rights_profile_record_id: UUID,
    source_snapshot_id: UUID | None,
    decision: RightsDecision,
    context: dict[str, object],
) -> UUID:
    if decision.checked_at is None:
        raise IngestionError("INTERNAL_INVARIANT", "rights decision lacks a check time")
    context_sha256 = canonical_sha256(context)
    value = session.execute(
        postgresql_insert(rights_decision)
        .values(
            rights_profile_record_id=rights_profile_record_id,
            source_snapshot_id=source_snapshot_id,
            capability=decision.capability,
            decision=decision.decision,
            reason_code=decision.reason,
            checked_at=require_utc(decision.checked_at),
            context_sha256=context_sha256,
        )
        .on_conflict_do_nothing()
        .returning(rights_decision.c.rights_decision_id)
    ).scalar_one_or_none()
    if value is not None:
        return _uuid(value)

    snapshot_predicate = (
        rights_decision.c.source_snapshot_id.is_(None)
        if source_snapshot_id is None
        else rights_decision.c.source_snapshot_id == source_snapshot_id
    )
    existing = (
        session.execute(
            select(rights_decision).where(
                rights_decision.c.rights_profile_record_id == rights_profile_record_id,
                snapshot_predicate,
                rights_decision.c.capability == decision.capability,
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is None:
        raise IngestionError("INTERNAL_INVARIANT", "rights decision conflict is unavailable")
    if (
        existing["decision"] != decision.decision
        or existing["reason_code"] != decision.reason
        or existing["context_sha256"] != context_sha256
    ):
        raise IngestionError(
            "RIGHTS_BLOCKED", "stored rights decision conflicts with configured authority"
        )
    return _uuid(existing["rights_decision_id"])


def record_ingestion_run(
    session: Session,
    *,
    provider_id: UUID,
    pair_key: str,
    started_at: datetime,
    attempt_number: int = 1,
    logical_prefix: str = "fpl004",
    resource: str = "bootstrap+fixtures",
    adapter_version: str = "fpl-reference-v1",
    code_commit: str | None = None,
) -> UUID:
    if attempt_number <= 0:
        raise IngestionError("INTERNAL_INVARIANT", "ingestion attempt must be positive")
    logical_run_key = f"{logical_prefix}:{pair_key}"
    values = {
        "provider_id": provider_id,
        "resource": resource,
        "logical_run_key": logical_run_key,
        "status": "RUNNING",
        "started_at": require_utc(started_at),
        "adapter_version": adapter_version,
        "code_commit": code_commit,
        "counts": {"attempt_number": attempt_number},
    }
    created = session.execute(
        postgresql_insert(ingestion_run)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[ingestion_run.c.provider_id, ingestion_run.c.logical_run_key]
        )
        .returning(ingestion_run.c.ingestion_run_id)
    ).scalar_one_or_none()
    if created is not None:
        return _uuid(created)
    existing = (
        session.execute(
            select(ingestion_run).where(
                ingestion_run.c.provider_id == provider_id,
                ingestion_run.c.logical_run_key == logical_run_key,
            )
        )
        .mappings()
        .one()
    )
    if any(existing[key] != value for key, value in values.items()):
        raise IngestionError("LIFECYCLE_INVARIANT", "ingestion run identity conflicts")
    return _uuid(existing["ingestion_run_id"])


def get_or_create_raw_content(session: Session, body: bytes) -> tuple[UUID, str]:
    body_sha256 = hashlib.sha256(body).hexdigest()
    created = session.execute(
        postgresql_insert(raw_blob)
        .values(body_sha256=body_sha256, byte_size=len(body))
        .on_conflict_do_nothing(index_elements=[raw_blob.c.body_sha256])
        .returning(raw_blob.c.raw_blob_id)
    ).scalar_one_or_none()
    if created is not None:
        raw_blob_id = _uuid(created)
    else:
        existing = (
            session.execute(
                select(raw_blob.c.raw_blob_id, raw_blob.c.byte_size).where(
                    raw_blob.c.body_sha256 == body_sha256
                )
            )
            .mappings()
            .one()
        )
        if int(existing["byte_size"]) != len(body):
            raise IngestionError("INTERNAL_INVARIANT", "raw content identity conflicts")
        raw_blob_id = _uuid(existing["raw_blob_id"])
    deleted = session.execute(
        select(raw_blob_deletion.c.deletion_id).where(
            raw_blob_deletion.c.raw_blob_id == raw_blob_id
        )
    ).first()
    if deleted is not None:
        raise IngestionError("RIGHTS_BLOCKED", "raw content has a retention tombstone")
    return raw_blob_id, body_sha256


def get_or_create_raw_storage_object(
    session: Session,
    *,
    raw_blob_id: UUID,
    rights_profile_record_id: UUID,
    body_sha256: str,
    storage_uri: str,
    content_type: str,
    retention_seconds: int | None,
    access_allowed: bool,
    export_allowed: bool,
    backup_allowed: bool,
) -> UUID:
    values = {
        "raw_blob_id": raw_blob_id,
        "rights_profile_record_id": rights_profile_record_id,
        "stored_blob_sha256": body_sha256,
        "storage_uri": storage_uri,
        "storage_policy": "ALLOWED",
        "content_type": content_type,
        "retention_seconds": retention_seconds,
        "access_allowed": access_allowed,
        "export_allowed": export_allowed,
        "backup_allowed": backup_allowed,
    }
    created = session.execute(
        postgresql_insert(raw_storage_object)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[raw_storage_object.c.raw_blob_id, raw_storage_object.c.storage_uri]
        )
        .returning(raw_storage_object.c.raw_storage_object_id)
    ).scalar_one_or_none()
    if created is not None:
        return _uuid(created)
    existing = (
        session.execute(
            select(raw_storage_object).where(
                raw_storage_object.c.raw_blob_id == raw_blob_id,
                raw_storage_object.c.storage_uri == storage_uri,
            )
        )
        .mappings()
        .one()
    )
    if any(existing[key] != value for key, value in values.items()):
        raise IngestionError(
            "RIGHTS_BLOCKED", "physical raw storage has a conflicting rights context"
        )
    deleted = session.execute(
        select(raw_storage_deletion.c.raw_storage_deletion_id).where(
            raw_storage_deletion.c.raw_storage_object_id == existing["raw_storage_object_id"]
        )
    ).first()
    if deleted is not None:
        raise IngestionError("RIGHTS_BLOCKED", "raw storage object has been deleted")
    return _uuid(existing["raw_storage_object_id"])


def record_received_snapshot(
    session: Session,
    *,
    provider_id: UUID,
    ingestion_run_id: UUID,
    attempt_number: int,
    resource: str,
    captured_at: datetime,
    body: bytes | None,
    raw_blob_id: UUID | None,
    raw_storage_object_id: UUID | None,
    rights_profile_record_id: UUID,
    profile: RightsProfile,
    sanitized_target: str,
    context: dict[str, object],
    schema_fingerprint: str | None = None,
    raw_storage_policy: str = "ALLOWED",
    adapter_version: str = "fpl-reference-v1",
    contract_version: str = "fpl-reference-v1",
    actor: str = "fpl-reference-adapter",
    request_fingerprint_override: str | None = None,
    body_sha256_override: str | None = None,
    body_size_override: int | None = None,
    request_started_at: datetime | None = None,
    http_status: int | None = None,
    content_type: str | None = "application/json",
) -> UUID:
    captured = require_utc(captured_at)
    started = require_utc(request_started_at) if request_started_at is not None else captured
    if started > captured:
        raise IngestionError("INTERNAL_INVARIANT", "snapshot request time exceeds receipt time")
    body_sha256: str | None
    body_size: int | None
    if body is not None:
        body_sha256 = hashlib.sha256(body).hexdigest()
        body_size = len(body)
        if body_sha256_override is not None and body_sha256_override != body_sha256:
            raise IngestionError("INTERNAL_INVARIANT", "snapshot body hash conflicts")
        if body_size_override is not None and body_size_override != body_size:
            raise IngestionError("INTERNAL_INVARIANT", "snapshot body size conflicts")
    else:
        body_sha256 = body_sha256_override
        body_size = body_size_override
    if (body_sha256 is None) != (body_size is None):
        raise IngestionError("INTERNAL_INVARIANT", "snapshot body metadata is incomplete")
    if body_sha256 is not None and (
        len(body_sha256) != 64
        or any(character not in "0123456789abcdef" for character in body_sha256)
        or body_size is None
        or body_size < 0
    ):
        raise IngestionError("INTERNAL_INVARIANT", "snapshot body metadata is invalid")
    if http_status is not None and not 100 <= http_status <= 599:
        raise IngestionError("INTERNAL_INVARIANT", "snapshot HTTP status is invalid")
    if request_fingerprint_override is not None and (
        len(request_fingerprint_override) != 64
        or any(character not in "0123456789abcdef" for character in request_fingerprint_override)
    ):
        raise IngestionError("INTERNAL_INVARIANT", "request fingerprint is invalid")
    request_fingerprint = request_fingerprint_override or canonical_sha256(
        {"resource": resource, "target": sanitized_target, "captured_at": captured.isoformat()}
    )
    envelope_sha256 = canonical_sha256(
        {
            "body_sha256": body_sha256,
            "body_size": body_size,
            "captured_at": captured.isoformat(),
            "context": context,
            "profile_id": profile.rights_profile_id,
            "profile_version": profile.profile_version,
            "resource": resource,
            "target": sanitized_target,
        }
    )
    snapshot_id = _uuid(
        session.execute(
            insert(source_snapshot)
            .values(
                ingestion_run_id=ingestion_run_id,
                attempt_number=attempt_number,
                provider_id=provider_id,
                resource=resource,
                request_fingerprint=request_fingerprint,
                request_started_at=started,
                received_at=captured,
                http_status=http_status,
                content_type=content_type,
                raw_blob_id=raw_blob_id,
                raw_storage_policy=raw_storage_policy,
                body_sha256=body_sha256,
                schema_fingerprint=schema_fingerprint,
                terms_version=profile.terms_version,
                rights_profile_key=profile.rights_profile_id,
                validation_status="RECEIVED",
                dataset_mode="RAW_OBSERVED",
                body_size=body_size,
                sanitized_target=sanitized_target,
                raw_storage_object_id=raw_storage_object_id,
                rights_profile_version=profile.profile_version,
                rights_profile_record_id=rights_profile_record_id,
                adapter_version=adapter_version,
                contract_version=contract_version,
                envelope_sha256=envelope_sha256,
            )
            .returning(source_snapshot.c.source_snapshot_id)
        ).scalar_one()
    )
    append_processing_event_idempotent(
        session,
        snapshot_id=snapshot_id,
        stage="RECEIVED",
        event_at=captured,
        input_sha256=body_sha256,
        output_sha256=envelope_sha256,
        safe_details=context,
        stage_version=contract_version,
        actor=actor,
    )
    return snapshot_id


def append_processing_event_idempotent(
    session: Session,
    *,
    snapshot_id: UUID,
    stage: str,
    event_at: datetime,
    input_sha256: str | None = None,
    output_sha256: str | None = None,
    safe_details: dict[str, object] | None = None,
    error_code: str | None = None,
    operation_id: UUID | None = None,
    stage_version: str = "fpl-reference-v1",
    actor: str = "fpl-reference-adapter",
) -> UUID:
    session.execute(
        select(source_snapshot.c.source_snapshot_id)
        .where(source_snapshot.c.source_snapshot_id == snapshot_id)
        .with_for_update()
    ).scalar_one()
    existing = None
    if stage != "FAILED_RETRYABLE":
        existing = (
            session.execute(
                select(source_processing_event).where(
                    source_processing_event.c.source_snapshot_id == snapshot_id,
                    source_processing_event.c.stage == stage,
                    source_processing_event.c.stage_version == stage_version,
                )
            )
            .mappings()
            .one_or_none()
        )
    if existing is not None:
        if (
            existing["input_sha256"] == input_sha256
            and existing["output_sha256"] == output_sha256
            and dict(existing["safe_details"]) == dict(safe_details or {})
            and existing["error_code"] == error_code
        ):
            return _uuid(existing["processing_event_id"])
        raise IngestionError(
            "LIFECYCLE_INVARIANT", "processing stage was already recorded with other content"
        )
    return SourceObservationRepository(session).append_processing_event(
        snapshot_id=snapshot_id,
        stage=stage,
        event_at=require_utc(event_at),
        stage_version=stage_version,
        input_sha256=input_sha256,
        output_sha256=output_sha256,
        safe_details=safe_details,
        error_code=error_code,
        operation_id=operation_id,
        actor=actor,
    )


def lifecycle_state(session: Session, snapshot_id: UUID) -> dict[str, object]:
    row = (
        session.execute(
            text(
                """
                SELECT current_state, usable_at, event_count, terminal
                FROM provenance.source_snapshot_lifecycle
                WHERE source_snapshot_id = :snapshot_id
                """
            ),
            {"snapshot_id": snapshot_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise IngestionError("LIFECYCLE_INVARIANT", "source snapshot was not found")
    return dict(row)


def received_context(session: Session, snapshot_id: UUID) -> dict[str, object]:
    value = session.execute(
        select(source_processing_event.c.safe_details).where(
            source_processing_event.c.source_snapshot_id == snapshot_id,
            source_processing_event.c.stage == "RECEIVED",
        )
    ).scalar_one_or_none()
    if not isinstance(value, dict):
        raise IngestionError("LIFECYCLE_INVARIANT", "snapshot resume context is unavailable")
    return dict(value)
