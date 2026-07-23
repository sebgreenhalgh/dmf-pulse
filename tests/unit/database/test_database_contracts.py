"""Strict configuration, redaction, and temporal model unit contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from dmf_pulse.data_model.errors import DataModelError, translate_database_error
from dmf_pulse.data_model.models import (
    AsOfScope,
    DataQualityValue,
    DataValueState,
    TemporalRange,
    require_utc,
    validate_ingestion_transition,
)
from dmf_pulse.database.engine import (
    create_database_engine,
    database_location,
    resolve_test_database_url,
    validate_database_url,
)
from dmf_pulse.database.errors import DatabaseError
from dmf_pulse.database.models import DatabaseSettings


class _Diagnostic:
    def __init__(self, constraint_name: str | None, message_primary: str = "") -> None:
        self.constraint_name = constraint_name
        self.message_primary = message_primary


class _DriverFailure(Exception):
    def __init__(
        self, *, constraint: str | None = None, message: str = "", sqlstate: str | None = None
    ) -> None:
        super().__init__("driver detail must never escape")
        self.diag = _Diagnostic(constraint, message)
        self.sqlstate = sqlstate


def _integrity(*, constraint: str | None = None, message: str = "") -> IntegrityError:
    return IntegrityError("statement", {}, _DriverFailure(constraint=constraint, message=message))


def test_database_settings_are_strict_reference_only() -> None:
    settings = DatabaseSettings(url_secret_ref="vault:dmf/test/database")
    assert settings.model_dump() == {
        "application_name": "dmf-pulse",
        "connect_timeout_seconds": 5,
        "url_secret_ref": "vault:dmf/test/database",
    }
    with pytest.raises(ValidationError):
        DatabaseSettings(url_secret_ref="postgresql://name:" + "secret@host/db")
    with pytest.raises(ValidationError):
        DatabaseSettings(url_secret_ref="vault:database-password")
    with pytest.raises(ValidationError):
        DatabaseSettings.model_validate(
            {"url_secret_ref": "vault:dmf/db", "connect_timeout_seconds": "5"}
        )
    with pytest.raises(ValidationError):
        DatabaseSettings.model_validate({"url_secret_ref": "vault:dmf/db", "extra": True})


def test_database_url_validation_and_location_redact_credentials() -> None:
    raw = "postgresql://user:" + "fake-secret@127.0.0.1:55432/dmf_test?sslmode=disable"
    normalized = validate_database_url(raw)
    assert normalized.drivername == "postgresql+psycopg"
    assert database_location(raw).model_dump() == {
        "host": "127.0.0.1",
        "name": "dmf_test",
        "port": 55432,
    }
    engine = create_database_engine(raw, DatabaseSettings(url_secret_ref="env:DMF_TEST_URL"))
    assert engine.echo is False
    assert engine.hide_parameters is True
    engine.dispose()
    for invalid in ("sqlite:///db.sqlite", "postgresql:///missing-host", "not a URL"):
        with pytest.raises(DatabaseError) as caught:
            validate_database_url(invalid)
        assert caught.value.code == "DATABASE_CONFIGURATION_INVALID"
        assert "fake-secret" not in caught.value.message


def test_test_database_url_is_environment_gated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DMF_TEST_DATABASE_URL", "postgresql://u:p@127.0.0.1/db")
    assert resolve_test_database_url(environment="TEST").endswith("127.0.0.1/db")
    with pytest.raises(DatabaseError) as production:
        resolve_test_database_url(environment="PRODUCTION")
    assert production.value.code == "DATABASE_CONFIGURATION_INVALID"
    monkeypatch.delenv("DMF_TEST_DATABASE_URL")
    with pytest.raises(DatabaseError) as missing:
        resolve_test_database_url(environment="TEST")
    assert missing.value.code == "DATABASE_CONFIGURATION_INVALID"


def test_utc_and_temporal_models_fail_closed() -> None:
    valid = datetime(2026, 7, 1, tzinfo=UTC)
    assert require_utc(valid) is valid
    assert AsOfScope(valid_at=valid, known_at=valid).valid_at == valid
    assert TemporalRange(start=valid, end=None).end is None
    with pytest.raises(ValueError, match="UTC"):
        require_utc(datetime(2026, 7, 1))
    with pytest.raises(ValueError, match="UTC"):
        require_utc(datetime(2026, 7, 1, tzinfo=timezone(timedelta(hours=1))))
    with pytest.raises(ValueError, match="UTC"):
        require_utc(datetime(2026, 1, 1, tzinfo=ZoneInfo("Europe/London")))
    with pytest.raises(ValidationError):
        TemporalRange(start=valid, end=valid)
    with pytest.raises(ValidationError):
        AsOfScope.model_validate({"valid_at": datetime(2026, 7, 1), "known_at": valid}, strict=True)


def test_ingestion_transitions_are_explicit() -> None:
    validate_ingestion_transition("PLANNED", "RUNNING")
    validate_ingestion_transition("FAILED_RETRYABLE", "RUNNING")
    for current, requested in (("SUCCEEDED", "RUNNING"), ("UNKNOWN", "RUNNING")):
        with pytest.raises(DataModelError) as caught:
            validate_ingestion_transition(current, requested)
        assert caught.value.code == "INGESTION_STATE_INVALID"


def test_data_quality_absence_states_are_typed_and_distinct() -> None:
    values = (
        DataQualityValue(state=DataValueState.NULL),
        DataQualityValue(state=DataValueState.ZERO, value=0),
        DataQualityValue(state=DataValueState.UNKNOWN, reason="provider value unknown"),
        DataQualityValue(state=DataValueState.NOT_APPLICABLE, reason="metric does not apply"),
        DataQualityValue(state=DataValueState.MISSING_SOURCE, reason="source field absent"),
    )
    serialized = {value.model_dump_json() for value in values}
    assert len(serialized) == len(values)
    with pytest.raises(ValidationError):
        DataQualityValue(state=DataValueState.UNKNOWN)
    with pytest.raises(ValidationError):
        DataQualityValue(state=DataValueState.PRESENT, value=0)


def test_canonical_repository_rejects_identity_override_without_writing() -> None:
    from unittest.mock import Mock

    from dmf_pulse.data_model.models import EntityType
    from dmf_pulse.data_model.repositories import CanonicalRepository

    session = Mock(spec=Session)
    with pytest.raises(DataModelError) as caught:
        CanonicalRepository(session).create_entity(
            EntityType.TEAM,
            team_id=UUID("00000000-0000-7000-8000-000000000001"),
            canonical_name="Override",
        )
    assert caught.value.code == "ENTITY_ATTRIBUTES_INVALID"
    session.execute.assert_not_called()


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (_integrity(constraint="ex_fixture_revision_current"), "TEMPORAL_OVERLAP"),
        (_integrity(constraint="fk_team_canonical_type"), "ENTITY_TYPE_MISMATCH"),
        (_integrity(constraint="ck_membership_valid_range"), "TEMPORAL_RANGE_INVALID"),
        (_integrity(message="TEMPORAL_SUPERSESSION_CONFLICT"), "TEMPORAL_SUPERSESSION_CONFLICT"),
        (_integrity(message="IMMUTABLE_RECORD"), "IMMUTABLE_RECORD"),
        (_integrity(), "DATABASE_CONSTRAINT_VIOLATION"),
        (
            OperationalError("statement", {}, _DriverFailure(sqlstate="08006")),
            "DATABASE_UNAVAILABLE",
        ),
    ],
)
def test_database_errors_translate_without_driver_detail(
    error: OperationalError | IntegrityError, code: str
) -> None:
    translated = translate_database_error(error)
    assert translated.code == code
    assert "driver detail" not in translated.message
    assert translated.as_error_object() == {"error": {"code": code, "message": translated.message}}
