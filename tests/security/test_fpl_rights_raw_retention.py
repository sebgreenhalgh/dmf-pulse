"""Rights gates, raw-storage separation, retention, and leakage controls."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

import dmf_pulse.ingestion.fpl.service as service_module
from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.tables import (
    canonical_entity,
    data_provider,
    fixture_observation,
    gameweek_observation,
    metadata,
    player_observation,
    raw_blob,
    raw_storage_deletion,
    raw_storage_object,
    rights_decision,
    rights_profile,
    source_bundle,
    source_processing_event,
    source_snapshot,
    team_observation,
)
from dmf_pulse.database.engine import create_database_engine, session_factory
from dmf_pulse.database.models import DatabaseSettings
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.persistence import ensure_synthetic_provider
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    FplImportRequest,
    FplIngestionService,
)
from dmf_pulse.ingestion.models import RightsCapability
from dmf_pulse.ingestion.repository import (
    get_or_create_raw_content,
    get_or_create_raw_storage_object,
    register_rights_profile,
)
from dmf_pulse.ingestion.rights import decide_rights, load_rights_profiles, require_rights

FAKE_API_KEY = "DMF" + "_TEST" + "_API_KEY_DO_NOT_LOG_7e4df7f7"
FAKE_DATABASE_URL = (
    "postgresql://" + "dmf_test:" + "SUPER" + "_SECRET_DO_NOT_LOG" + "@localhost/dmf"
)
RAW_MARKER = "RAW_BODY_" + "MUST_NOT_SURVIVE_FPL004"
CAPTURED_AT = datetime(2026, 8, 21, 17, 0, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


@pytest.fixture
def postgres_session_factory() -> Iterator[sessionmaker[Session]]:
    """Provide the real PostgreSQL fixture outside the integration subtree."""

    database_url = os.environ.get("DMF_TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail("DMF_TEST_DATABASE_URL is required for PostgreSQL security tests")
    engine = create_database_engine(
        database_url,
        DatabaseSettings(
            url_secret_ref=DATABASE_REF,
            application_name="dmf-pulse-security-tests",
        ),
    )
    tables = ", ".join(table.fullname for table in metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    factory = session_factory(engine)
    yield factory
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    engine.dispose()


def _official_provider(session: Session) -> UUID:
    entity_id = session.execute(
        insert(canonical_entity)
        .values(entity_type="DATA_PROVIDER")
        .returning(canonical_entity.c.entity_id)
    ).scalar_one()
    assert isinstance(entity_id, UUID)
    session.execute(
        insert(data_provider).values(
            provider_id=entity_id,
            entity_type="DATA_PROVIDER",
            provider_key="official_fpl",
            display_name="Official FPL",
            provider_type="OFFICIAL",
            rights_profile_key="fpl_official_private_manual_v1",
        )
    )
    return entity_id


def _current_states(session: Session) -> tuple[str, ...]:
    return tuple(
        session.scalars(
            text(
                "SELECT current_state FROM provenance.source_snapshot_lifecycle "
                "ORDER BY source_snapshot_id"
            )
        )
    )


@pytest.mark.security
def test_supplied_profiles_fail_closed_for_every_unapproved_capability() -> None:
    profiles = load_rights_profiles()
    synthetic = profiles["synthetic_test_v1"]
    official = profiles["fpl_official_private_manual_v1"]

    assert decide_rights(synthetic, RightsCapability.RAW_STORAGE).decision == "ALLOW"
    assert decide_rights(synthetic, RightsCapability.MODEL_TRAINING).decision == "DENY"
    assert decide_rights(official, RightsCapability.MANUAL_IMPORT).decision == "ALLOW"
    assert decide_rights(official, RightsCapability.RAW_STORAGE).decision == "DENY"
    derived = decide_rights(official, RightsCapability.DERIVED_STORAGE)
    assert derived.decision == "DENY"
    assert derived.reason == "CAPABILITY_UNKNOWN_DENIED"

    with pytest.raises(IngestionError) as caught:
        require_rights(official, RightsCapability.DERIVED_STORAGE)
    assert caught.value.code == "RIGHTS_BLOCKED"
    assert caught.value.details["transport_call_count"] == 0


@pytest.mark.security
def test_automated_snapshot_is_blocked_before_transport_or_database_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden_transport_factory() -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("transport must not be constructed")

    def forbidden_database_resolution(_reference: str) -> str:
        raise AssertionError("database reference must not be resolved")

    monkeypatch.setattr(service_module, "resolve_database_reference", forbidden_database_resolution)
    outcome = FplIngestionService(
        transport_factory=forbidden_transport_factory  # type: ignore[arg-type]
    ).snapshot(
        resource="all",
        competition_key="PL",
        season_code="2026/27",
        rights_profile_id="fpl_official_private_manual_v1",
        database_url_ref=DATABASE_REF,
    )

    assert outcome.exit_code == 4
    assert outcome.result.status == "RIGHTS_BLOCKED"
    assert outcome.result.canonical_effects["transport_call_count"] == 0
    assert calls == 0


@pytest.mark.postgres
def test_official_manual_validation_leaves_no_raw_body_or_secret_in_result_or_logs(
    repository_root: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service_module.tempfile, "gettempdir", lambda: str(tmp_path / "service-temp")
    )
    fixture_root = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap_value = json.loads((fixture_root / "bootstrap.json").read_text(encoding="utf-8"))
    fixtures_value = json.loads((fixture_root / "fixtures.json").read_text(encoding="utf-8"))
    bootstrap_value["future_secret_probe"] = FAKE_API_KEY
    fixtures_value[0]["future_raw_probe"] = RAW_MARKER
    bootstrap_path = tmp_path / "ordinary-bootstrap-input.json"
    fixtures_path = tmp_path / "ordinary-fixtures-input.json"
    bootstrap_path.write_text(json.dumps(bootstrap_value), encoding="utf-8")
    fixtures_path.write_text(json.dumps(fixtures_value), encoding="utf-8")

    outcome = FplIngestionService(repository_root=repository_root).import_pair(
        FplImportRequest(
            bootstrap_path=bootstrap_path,
            fixtures_path=fixtures_path,
            competition_key="PL",
            season_code="2026/27",
            captured_at=CAPTURED_AT,
            information_cutoff=CUTOFF,
            rights_profile_id="fpl_official_private_manual_v1",
            database_url_ref=DATABASE_REF,
        )
    )

    serialized = outcome.result.model_dump_json()
    assert outcome.exit_code == 4
    assert outcome.result.status == "RIGHTS_BLOCKED"
    assert outcome.result.source_bundle is None
    for forbidden in (FAKE_API_KEY, FAKE_DATABASE_URL, RAW_MARKER):
        assert forbidden not in serialized
        assert forbidden not in caplog.text

    assert bootstrap_path.is_file()
    assert fixtures_path.is_file()
    volatile_root = service_module._volatile_root()
    remaining_text = "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in volatile_root.rglob("*")
        if path.is_file()
    )
    assert FAKE_API_KEY not in remaining_text
    assert RAW_MARKER not in remaining_text

    with postgres_session_factory() as session:
        snapshots = (
            session.execute(
                select(
                    source_snapshot.c.source_snapshot_id,
                    source_snapshot.c.body_sha256,
                    source_snapshot.c.body_size,
                    source_snapshot.c.raw_blob_id,
                    source_snapshot.c.raw_storage_object_id,
                    source_snapshot.c.raw_storage_policy,
                ).order_by(source_snapshot.c.resource)
            )
            .mappings()
            .all()
        )
        assert len(snapshots) == 2
        assert all(
            row["body_sha256"] is not None
            and row["body_size"] is not None
            and row["raw_blob_id"] is None
            and row["raw_storage_object_id"] is None
            and row["raw_storage_policy"] == "FORBIDDEN"
            for row in snapshots
        )
        for row in snapshots:
            assert tuple(
                session.scalars(
                    select(source_processing_event.c.stage)
                    .where(
                        source_processing_event.c.source_snapshot_id == row["source_snapshot_id"]
                    )
                    .order_by(source_processing_event.c.sequence_number)
                )
            ) == ("RECEIVED", "RAW_DISCARDED", "PARSED", "VALIDATED", "REJECTED")
        assert session.scalar(select(func.count()).select_from(rights_decision)) == 8
        assert session.scalar(select(func.count()).select_from(raw_blob)) == 0
        assert session.scalar(select(func.count()).select_from(source_bundle)) == 0
        for table in (
            team_observation,
            player_observation,
            gameweek_observation,
            fixture_observation,
        ):
            assert session.scalar(select(func.count()).select_from(table)) == 0


@pytest.mark.postgres
def test_official_manual_validation_retries_in_memory_then_reaches_terminal_rejection(
    repository_root: Path,
    tmp_path: Path,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service_module.tempfile, "gettempdir", lambda: str(tmp_path / "service-temp")
    )
    fixture_root = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap_path = tmp_path / "retry-bootstrap.json"
    fixtures_path = tmp_path / "retry-fixtures.json"
    bootstrap_path.write_bytes((fixture_root / "bootstrap.json").read_bytes())
    fixtures_path.write_bytes((fixture_root / "fixtures.json").read_bytes())
    original = FplIngestionService._finish_manual_validation
    attempts = 0

    def fail_once(self: FplIngestionService, *args: object, **kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise IngestionError(
                "DATABASE_RETRYABLE",
                "synthetic retryable manual transaction",
                retryable=True,
            )
        original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(FplIngestionService, "_finish_manual_validation", fail_once)
    outcome = FplIngestionService(repository_root=repository_root).import_pair(
        FplImportRequest(
            bootstrap_path=bootstrap_path,
            fixtures_path=fixtures_path,
            competition_key="PL",
            season_code="2026/27",
            captured_at=CAPTURED_AT,
            information_cutoff=CUTOFF,
            rights_profile_id="fpl_official_private_manual_v1",
            database_url_ref=DATABASE_REF,
        )
    )
    assert attempts == 2
    assert outcome.exit_code == 4
    assert {resource.lifecycle_state for resource in outcome.result.resources} == {"REJECTED"}
    assert bootstrap_path.is_file() and fixtures_path.is_file()
    assert not any(service_module._volatile_root().iterdir())
    with postgres_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(source_snapshot)) == 2


@pytest.mark.postgres
def test_exhausted_manual_validation_retry_is_terminal_and_keeps_no_raw_body(
    repository_root: Path,
    tmp_path: Path,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service_module.tempfile, "gettempdir", lambda: str(tmp_path / "service-temp")
    )
    fixture_root = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap_path = tmp_path / "failed-bootstrap.json"
    fixtures_path = tmp_path / "failed-fixtures.json"
    bootstrap_path.write_bytes((fixture_root / "bootstrap.json").read_bytes())
    fixtures_path.write_bytes((fixture_root / "fixtures.json").read_bytes())

    def always_retry(*_args: object, **_kwargs: object) -> None:
        raise IngestionError(
            "DATABASE_RETRYABLE",
            "synthetic exhausted manual transaction",
            retryable=True,
        )

    monkeypatch.setattr(FplIngestionService, "_finish_manual_validation", always_retry)
    with pytest.raises(IngestionError) as raised:
        FplIngestionService(repository_root=repository_root).import_pair(
            FplImportRequest(
                bootstrap_path=bootstrap_path,
                fixtures_path=fixtures_path,
                competition_key="PL",
                season_code="2026/27",
                captured_at=CAPTURED_AT,
                information_cutoff=CUTOFF,
                rights_profile_id="fpl_official_private_manual_v1",
                database_url_ref=DATABASE_REF,
            )
        )
    assert raised.value.code == "DATABASE_RETRYABLE"
    assert bootstrap_path.is_file() and fixtures_path.is_file()
    assert not any(service_module._volatile_root().iterdir())
    with postgres_session_factory() as session:
        assert _current_states(session) == ("FAILED_PERMANENT", "FAILED_PERMANENT")
        assert session.scalar(select(func.count()).select_from(raw_blob)) == 0


@pytest.mark.security
def test_volatile_orphan_cleanup_is_process_scoped_and_preserves_caller_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service_module.tempfile, "gettempdir", lambda: str(tmp_path / "service-temp")
    )
    monkeypatch.setattr(service_module, "_pid_is_running", lambda pid: pid == os.getpid())
    root = service_module._volatile_root()
    root.mkdir(parents=True)
    orphan = root / f"active-999999-{'a' * 32}"
    other_active = root / f"active-{os.getpid()}-{'b' * 32}"
    orphan.mkdir()
    other_active.mkdir()
    (orphan / "raw.json").write_text(RAW_MARKER, encoding="utf-8")
    (other_active / "owned-by-other-operation").write_text("safe", encoding="utf-8")
    unrelated = root / "unrelated.txt"
    unrelated.write_text("safe", encoding="utf-8")
    bootstrap_path = tmp_path / "bootstrap input.json"
    fixtures_path = tmp_path / "fixtures input.json"
    bootstrap_path.write_bytes(b'{"safe":"bootstrap"}')
    fixtures_path.write_bytes(b'[{"safe":"fixtures"}]')

    assert service_module._read_through_volatile_pair(bootstrap_path, fixtures_path) == (
        b'{"safe":"bootstrap"}',
        b'[{"safe":"fixtures"}]',
    )

    assert bootstrap_path.is_file() and fixtures_path.is_file()
    assert not orphan.exists()
    assert other_active.is_dir()
    assert unrelated.is_file()


@pytest.mark.postgres
def test_database_rejects_raw_storage_under_denied_profile_and_retains_only_hashes(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    profiles = load_rights_profiles()
    body = json.dumps({"api_" + "key": FAKE_API_KEY, "marker": RAW_MARKER}).encode()

    with postgres_session_factory.begin() as session:
        ensure_synthetic_provider(session)
        _official_provider(session)
        synthetic_record_id = register_rights_profile(session, profiles["synthetic_test_v1"])
        official_record_id = register_rights_profile(
            session, profiles["fpl_official_private_manual_v1"]
        )
        raw_blob_id, body_sha256 = get_or_create_raw_content(session, body)
        storage_id = get_or_create_raw_storage_object(
            session,
            raw_blob_id=raw_blob_id,
            rights_profile_record_id=synthetic_record_id,
            body_sha256=body_sha256,
            storage_uri="fixture://FPL-004/security/raw-body",
            content_type="application/json",
            retention_seconds=None,
            access_allowed=True,
            export_allowed=True,
            backup_allowed=True,
        )

        with pytest.raises(DBAPIError) as caught, session.begin_nested():
            get_or_create_raw_storage_object(
                session,
                raw_blob_id=raw_blob_id,
                rights_profile_record_id=official_record_id,
                body_sha256=body_sha256,
                storage_uri="volatile://FPL-004/forbidden-raw-body",
                content_type="application/json",
                retention_seconds=0,
                access_allowed=True,
                export_allowed=False,
                backup_allowed=False,
            )
        assert "RAW_STORAGE_RIGHTS_BLOCKED" in str(caught.value.orig)

        with pytest.raises(DBAPIError) as shared_object, session.begin_nested():
            get_or_create_raw_storage_object(
                session,
                raw_blob_id=raw_blob_id,
                rights_profile_record_id=official_record_id,
                body_sha256=body_sha256,
                storage_uri="fixture://FPL-004/security/raw-body",
                content_type="application/json",
                retention_seconds=0,
                access_allowed=True,
                export_allowed=False,
                backup_allowed=False,
            )
        assert "RAW_STORAGE_RIGHTS_BLOCKED" in str(shared_object.value.orig)

        raw_row = (
            session.execute(select(raw_blob).where(raw_blob.c.raw_blob_id == raw_blob_id))
            .mappings()
            .one()
        )
        storage_row = (
            session.execute(
                select(raw_storage_object).where(
                    raw_storage_object.c.raw_storage_object_id == storage_id
                )
            )
            .mappings()
            .one()
        )
        persisted = json.dumps(
            {"raw": dict(raw_row), "storage": dict(storage_row)},
            default=str,
            sort_keys=True,
        )
        assert raw_row["body_sha256"] == body_sha256
        assert raw_row["byte_size"] == len(body)
        assert set(raw_row).isdisjoint({"body", "content", "payload"})
        assert FAKE_API_KEY not in persisted
        assert RAW_MARKER not in persisted


@pytest.mark.postgres
def test_raw_storage_tombstone_hides_object_and_prevents_reuse(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    profile = load_rights_profiles()["synthetic_test_v1"]
    body = b'{"synthetic":"retention-test"}'

    with postgres_session_factory.begin() as session:
        ensure_synthetic_provider(session)
        record_id = register_rights_profile(session, profile)
        raw_blob_id, body_sha256 = get_or_create_raw_content(session, body)
        storage_id = get_or_create_raw_storage_object(
            session,
            raw_blob_id=raw_blob_id,
            rights_profile_record_id=record_id,
            body_sha256=body_sha256,
            storage_uri="fixture://FPL-004/security/deleted-object",
            content_type="application/json",
            retention_seconds=None,
            access_allowed=True,
            export_allowed=False,
            backup_allowed=False,
        )
        session.execute(
            insert(raw_storage_deletion).values(
                raw_storage_object_id=storage_id,
                deleted_at=CAPTURED_AT,
                reason="synthetic retention test",
                tombstone_sha256=canonical_sha256(
                    {"raw_storage_object_id": str(storage_id), "reason": "test"}
                ),
                approved_by="FPL-004 synthetic test",
            )
        )

        available = session.execute(
            text(
                "SELECT count(*) FROM provenance.available_raw_storage_object "
                "WHERE raw_storage_object_id = :storage_id"
            ),
            {"storage_id": storage_id},
        ).scalar_one()
        assert available == 0
        with pytest.raises(IngestionError, match="has been deleted"):
            get_or_create_raw_storage_object(
                session,
                raw_blob_id=raw_blob_id,
                rights_profile_record_id=record_id,
                body_sha256=body_sha256,
                storage_uri="fixture://FPL-004/security/deleted-object",
                content_type="application/json",
                retention_seconds=None,
                access_allowed=True,
                export_allowed=False,
                backup_allowed=False,
            )


@pytest.mark.postgres
def test_rights_profile_rows_are_immutable(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    profile = load_rights_profiles()["synthetic_test_v1"]

    with postgres_session_factory.begin() as session:
        ensure_synthetic_provider(session)
        record_id = register_rights_profile(session, profile)
        with pytest.raises(DBAPIError) as caught, session.begin_nested():
            session.execute(
                update(rights_profile)
                .where(rights_profile.c.rights_profile_record_id == record_id)
                .values(status="BLOCKED")
            )
        assert "IMMUTABLE_RECORD" in str(caught.value.orig)
