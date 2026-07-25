"""PostgreSQL negative controls for repository conflict and tombstone guards."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.tables import (
    raw_blob_deletion,
    raw_storage_object,
    source_processing_event,
    team_observation,
    team_season,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.persistence import ensure_synthetic_provider
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    FplIngestionService,
    FplReplayRequest,
    IngestionInterrupted,
)
from dmf_pulse.ingestion.models import RightsDecision
from dmf_pulse.ingestion.repository import (
    append_processing_event_idempotent,
    get_or_create_raw_content,
    get_or_create_raw_storage_object,
    lifecycle_state,
    received_context,
    record_rights_decision,
    register_rights_profile,
)
from dmf_pulse.ingestion.rights import load_rights_profiles

pytestmark = [pytest.mark.integration, pytest.mark.postgres]
CAPTURED = datetime(2026, 8, 21, 17, tzinfo=UTC)


def _seed(
    repository_root: Path, postgres_session_factory: sessionmaker[Session]
) -> tuple[UUID, UUID]:
    outcome = FplIngestionService(repository_root=repository_root).replay(
        FplReplayRequest(
            fixture_set=repository_root / "fixtures/fpl/FPL-004",
            scenario="happy_path",
            database_url_ref=DATABASE_REF,
        )
    )
    assert outcome.result.source_bundle is not None
    return tuple(item.source_snapshot_id for item in outcome.result.resources)  # type: ignore[return-value]


def test_profile_event_and_missing_snapshot_conflicts_are_fail_closed(
    repository_root: Path, postgres_session_factory: sessionmaker[Session]
) -> None:
    bootstrap_id, _ = _seed(repository_root, postgres_session_factory)
    profile = load_rights_profiles()["synthetic_test_v1"]
    with postgres_session_factory.begin() as session:
        stored = register_rights_profile(session, profile)
        assert isinstance(stored, UUID)
        with pytest.raises(IngestionError, match="conflicts with configured authority"):
            register_rights_profile(session, profile.model_copy(update={"notes": "conflict"}))

        existing = (
            session.execute(
                select(source_processing_event).where(
                    source_processing_event.c.source_snapshot_id == bootstrap_id,
                    source_processing_event.c.stage == "RECEIVED",
                )
            )
            .mappings()
            .one()
        )
        with pytest.raises(IngestionError, match="other content"):
            append_processing_event_idempotent(
                session,
                snapshot_id=bootstrap_id,
                stage="RECEIVED",
                event_at=CAPTURED,
                input_sha256="f" * 64,
                output_sha256=str(existing["output_sha256"]),
                safe_details=dict(existing["safe_details"]),
            )

        unknown = uuid4()
        with pytest.raises(IngestionError, match="snapshot was not found"):
            lifecycle_state(session, unknown)
        with pytest.raises(IngestionError, match="resume context"):
            received_context(session, unknown)


def test_decision_without_check_time_is_rejected_before_database_use() -> None:
    decision = RightsDecision(
        profile_id="synthetic_test_v1",
        profile_version="1.0.0",
        capability="raw_storage",
        decision="ALLOW",
        reason="test",
        checked_at=None,
    )
    with pytest.raises(IngestionError, match="lacks a check time"):
        record_rights_decision(
            None,  # type: ignore[arg-type]
            rights_profile_record_id=UUID(int=1),
            source_snapshot_id=None,
            decision=decision,
            context={},
        )


def test_raw_content_tombstone_and_storage_context_cannot_be_reused(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    profile = load_rights_profiles()["synthetic_test_v1"]
    body = b'{"synthetic":"repository-negative-control"}'
    with postgres_session_factory.begin() as session:
        ensure_synthetic_provider(session)
        profile_record_id = register_rights_profile(session, profile)
        raw_blob_id, body_sha256 = get_or_create_raw_content(session, body)
        storage_id = get_or_create_raw_storage_object(
            session,
            raw_blob_id=raw_blob_id,
            rights_profile_record_id=profile_record_id,
            body_sha256=body_sha256,
            storage_uri="fixture://FPL-004/repository-negative-control",
            content_type="application/json",
            retention_seconds=None,
            access_allowed=True,
            export_allowed=True,
            backup_allowed=True,
        )
        assert (
            session.scalar(
                select(raw_storage_object.c.raw_storage_object_id).where(
                    raw_storage_object.c.raw_storage_object_id == storage_id
                )
            )
            == storage_id
        )
        with pytest.raises(IngestionError, match="conflicting rights context"):
            get_or_create_raw_storage_object(
                session,
                raw_blob_id=raw_blob_id,
                rights_profile_record_id=profile_record_id,
                body_sha256=body_sha256,
                storage_uri="fixture://FPL-004/repository-negative-control",
                content_type="application/problem+json",
                retention_seconds=None,
                access_allowed=True,
                export_allowed=True,
                backup_allowed=True,
            )

        session.execute(
            insert(raw_blob_deletion).values(
                raw_blob_id=raw_blob_id,
                deleted_at=CAPTURED,
                reason="synthetic negative control",
                tombstone_sha256=canonical_sha256(
                    {"raw_blob_id": str(raw_blob_id), "reason": "negative-control"}
                ),
                approved_by="FPL-004 synthetic test",
            )
        )
        with pytest.raises(IngestionError, match="retention tombstone"):
            get_or_create_raw_content(session, body)


def test_database_rejects_observation_before_source_snapshot_is_usable(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    service = FplIngestionService(repository_root=repository_root)
    service.replay(
        FplReplayRequest(
            fixture_set=repository_root / "fixtures/fpl/FPL-004",
            scenario="happy_path",
            database_url_ref=DATABASE_REF,
        )
    )
    request = FplReplayRequest(
        fixture_set=repository_root / "fixtures/fpl/FPL-004",
        scenario="happy_path",
        database_url_ref=DATABASE_REF,
        halt_after_stage="PROMOTED",
    )
    with pytest.raises(IngestionInterrupted) as interrupted:
        service.replay(request)
    bootstrap_snapshot_id = interrupted.value.snapshot_ids[0]
    with postgres_session_factory() as session:
        before = int(session.scalar(select(func.count()).select_from(team_observation)) or 0)
    assert before > 0
    with pytest.raises(DBAPIError) as blocked, postgres_session_factory.begin() as session:
        team_season_id = session.scalar(select(team_season.c.team_season_id).limit(1))
        assert team_season_id is not None
        session.execute(
            insert(team_observation).values(
                team_season_id=team_season_id,
                display_name="Synthetic blocked observation",
                short_name="SBO",
                observed_at=CAPTURED,
                received_at=CAPTURED,
                usable_at=CAPTURED,
                source_snapshot_id=bootstrap_snapshot_id,
                contract_version="fpl-reference-v1",
                semantic_sha256="4" * 64,
            )
        )
    assert "FPL_OBSERVATION_SOURCE_NOT_USABLE" in str(blocked.value.orig)
    with postgres_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(team_observation)) == before
