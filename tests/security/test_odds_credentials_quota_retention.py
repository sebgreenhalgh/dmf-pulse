"""Credential, quota, raw-retention, and immutable-evidence security proofs."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import cast, func, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    data_quality_issue,
    metadata,
    odds_observation,
    provider_quota_observation,
    raw_blob,
    raw_storage_object,
    source_processing_event,
    source_snapshot,
)
from dmf_pulse.database.engine import create_database_engine, session_factory
from dmf_pulse.database.models import DatabaseSettings
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.ingestion.odds.client import (
    OddsClient,
    OddsFetchFailure,
    OddsHttpRequest,
    OddsHttpResponse,
    StaticCredentialProvider,
    UrllibOddsTransport,
)
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.models import ProviderFailureCode
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.ingestion.odds.service import OddsIngestionService

CAPTURED = datetime(2026, 8, 20, 12, tzinfo=UTC)


@pytest.fixture
def postgres_session_factory() -> Iterator[sessionmaker[Session]]:
    database_url = os.environ.get("DMF_TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail("DMF_TEST_DATABASE_URL is required for PostgreSQL security tests")
    engine = create_database_engine(
        database_url,
        DatabaseSettings(
            url_secret_ref=DATABASE_REF,
            application_name="dmf-pulse-odd005-security-tests",
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


class _CountingCredentialProvider:
    def __init__(self, credential: str | None) -> None:
        self._credential = credential
        self.calls = 0

    def get_credential(self) -> str | None:
        self.calls += 1
        return self._credential

    def __repr__(self) -> str:
        return "_CountingCredentialProvider(<redacted>)"


class _SequenceTransport:
    def __init__(self, responses: list[OddsHttpResponse]) -> None:
        self.responses = responses
        self.calls = 0
        self.requests: list[OddsHttpRequest] = []

    def send(self, request: OddsHttpRequest, _credential: str) -> OddsHttpResponse:
        self.calls += 1
        self.requests.append(request)
        return self.responses.pop(0)


def _exception_rendering(error: BaseException) -> str:
    values: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        values.extend((str(current), repr(current), repr(vars(current))))
        current = current.__cause__ or current.__context__
    return "\n".join(values)


def _credential(root: Path) -> str:
    return (
        (root / "fixtures/odds/ODD-005/security_fake_credential.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def _raw_body(root: Path) -> bytes:
    return (root / "fixtures/odds/ODD-005/raw_forbidden_canary.json").read_bytes()


def _response(root: Path, *, remaining: int = 499, status: int = 200) -> OddsHttpResponse:
    used = 500 - remaining
    return OddsHttpResponse(
        status_code=status,
        content_type="application/json; charset=utf-8",
        headers={
            "x-requests-remaining": str(remaining),
            "x-requests-used": str(used),
            "x-requests-last": "1",
            "x-request-id": "synthetic-request-id",
        },
        body=_raw_body(root),
    )


def _snapshot(service: OddsIngestionService):
    return service.snapshot(
        provider="the_odds_api",
        competition_key="PL",
        sport_key="soccer_epl",
        region="uk",
        market="h2h",
        as_of=datetime(2026, 8, 20, 12, 5, tzinfo=UTC),
        database_url_ref=DATABASE_REF,
    )


@pytest.mark.security
def test_missing_credential_refuses_before_transport_construction() -> None:
    credential = _CountingCredentialProvider(None)
    constructions = 0

    def forbidden_transport() -> _SequenceTransport:
        nonlocal constructions
        constructions += 1
        raise AssertionError("transport must not be constructed")

    client = OddsClient(
        load_rights_profiles()["the_odds_api_private_analytics_v1"],
        credential_provider=credential,
        transport_factory=forbidden_transport,
        clock=lambda: CAPTURED,
    )

    with pytest.raises(IngestionError) as raised:
        client.fetch()

    assert raised.value.code == "CREDENTIAL_UNAVAILABLE"
    assert raised.value.details["transport_call_count"] == 0
    assert client.transport_call_count == 0
    assert credential.calls == 1
    assert constructions == 0


@pytest.mark.security
@pytest.mark.parametrize("certificate_error", (False, True), ids=("ssl", "certificate"))
def test_wrapped_tls_errors_are_typed_redacted_and_never_reach_network(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    certificate_error: bool,
) -> None:
    credential_value = _credential(repository_root)
    open_timeouts: list[float] = []

    class FailingOpener:
        def open(self, _request: object, *, timeout: float) -> object:
            open_timeouts.append(timeout)
            reason: BaseException = (
                ssl.CertificateError(credential_value)
                if certificate_error
                else ssl.SSLError(credential_value)
            )
            raise urllib.error.URLError(reason)

    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *_handlers: FailingOpener(),
    )
    client = OddsClient(
        load_rights_profiles()["the_odds_api_private_analytics_v1"],
        credential_provider=StaticCredentialProvider(credential_value),
        transport_factory=UrllibOddsTransport,
        clock=lambda: CAPTURED,
    )

    with pytest.raises(OddsFetchFailure) as raised:
        client.fetch()

    assert raised.value.code == "TLS_ERROR"
    assert raised.value.retryable is False
    assert client.transport_call_count == 1
    assert len(open_timeouts) == 1
    assert raised.value.attempts[0].failure_code is ProviderFailureCode.TLS_ERROR
    assert credential_value not in _exception_rendering(raised.value)


@pytest.mark.security
def test_credential_transport_and_parser_failures_drop_sensitive_exception_chains(
    repository_root: Path,
) -> None:
    credential_value = _credential(repository_root)
    raw_canary = json.loads(_raw_body(repository_root))[0]["synthetic_cleanup_marker"]
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]

    class FailingCredential:
        def get_credential(self) -> str:
            raise RuntimeError(credential_value)

    credential_client = OddsClient(
        profile,
        credential_provider=FailingCredential(),
        transport_factory=lambda: (_ for _ in ()).throw(RuntimeError(credential_value)),
        clock=lambda: CAPTURED,
    )
    with pytest.raises(IngestionError) as credential_failure:
        credential_client.fetch()
    assert credential_failure.value.code == "CREDENTIAL_UNAVAILABLE"
    assert credential_client.transport_call_count == 0
    assert credential_value not in _exception_rendering(credential_failure.value)

    class FailingTransport:
        def send(self, _request: OddsHttpRequest, _credential: str) -> OddsHttpResponse:
            raise IngestionError(
                "READ_TIMEOUT",
                credential_value,
                retryable=True,
                details={"unsafe": raw_canary},
            )

    transport_client = OddsClient(
        profile,
        credential_provider=StaticCredentialProvider(credential_value),
        transport_factory=FailingTransport,
        clock=lambda: CAPTURED,
    )
    with pytest.raises(OddsFetchFailure) as transport_failure:
        transport_client.fetch()
    rendered = _exception_rendering(transport_failure.value)
    assert transport_failure.value.code == "READ_TIMEOUT"
    assert transport_client.transport_call_count == 2
    assert credential_value not in rendered
    assert raw_canary not in rendered
    assert transport_failure.value.__cause__ is None
    assert transport_failure.value.__context__ is None

    bodies = (
        raw_canary.encode("utf-8") + b"\xff",
        ('[{"unsafe":"' + raw_canary).encode("utf-8"),
        (
            '[{"id":"event","sport_key":"soccer_epl","commence_time":'
            '"2026-08-22T14:00:00Z","home_team":"Home","away_team":"Away",'
            '"bookmakers":[{"key":"book","title":"Book","last_update":'
            '"2026-08-20T12:00:00Z","markets":[{"key":"h2h","outcomes":'
            f'[{{"name":"Home","price":"{raw_canary}"}}]}}]}}]}}]'
        ).encode(),
    )
    for body in bodies:
        with pytest.raises(IngestionError) as parser_failure:
            parse_odds_payload(body)
        rendered = _exception_rendering(parser_failure.value)
        assert raw_canary not in rendered
        assert parser_failure.value.__cause__ is None
        assert parser_failure.value.__context__ is None


@pytest.mark.postgres
def test_raw_forbidden_success_persists_only_hash_metadata_and_quota(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    canary = json.loads(_raw_body(repository_root))[0]["synthetic_cleanup_marker"]
    credential_value = _credential(repository_root)
    credential = _CountingCredentialProvider(credential_value)
    transport = _SequenceTransport([_response(repository_root)])
    outcome = _snapshot(
        OddsIngestionService(
            repository_root=repository_root,
            credential_provider=credential,
            transport_factory=lambda: transport,
            clock=lambda: CAPTURED,
        )
    )

    assert outcome.exit_code == 2
    assert outcome.result.status == "OBSERVED_NOT_USABLE"
    assert outcome.result.error is None
    assert outcome.result.source_snapshot_id is not None
    assert outcome.result.quota is not None
    assert outcome.result.quota.remaining == 499
    assert transport.calls == credential.calls == 1
    assert credential_value not in transport.requests[0].sanitized_target
    rendered = json.dumps(outcome.result.model_dump(mode="json"), sort_keys=True)
    assert canary not in rendered
    assert credential_value not in rendered

    with postgres_session_factory() as session:
        snapshot = (
            session.execute(
                select(source_snapshot).where(
                    source_snapshot.c.source_snapshot_id == outcome.result.source_snapshot_id
                )
            )
            .mappings()
            .one()
        )
        assert snapshot["http_status"] == 200
        assert snapshot["content_type"] == "application/json"
        assert snapshot["raw_storage_policy"] == "FORBIDDEN"
        assert snapshot["raw_blob_id"] is None
        assert snapshot["raw_storage_object_id"] is None
        assert snapshot["body_sha256"] is not None
        assert snapshot["body_size"] == len(_raw_body(repository_root))
        assert session.scalar(select(func.count()).select_from(raw_blob)) == 0
        assert session.scalar(select(func.count()).select_from(raw_storage_object)) == 0
        assert session.scalar(select(func.count()).select_from(provider_quota_observation)) == 1
        state = (
            session.execute(
                select(source_processing_event.c.stage)
                .where(
                    source_processing_event.c.source_snapshot_id
                    == outcome.result.source_snapshot_id
                )
                .order_by(source_processing_event.c.sequence_number)
            )
            .scalars()
            .all()
        )
        assert state[-1] == "REJECTED"
        persisted_text = "\n".join(
            str(value)
            for value in (
                snapshot["sanitized_target"],
                snapshot["content_type"],
                *session.scalars(
                    select(cast(source_processing_event.c.safe_details, JSONB)).where(
                        source_processing_event.c.source_snapshot_id
                        == outcome.result.source_snapshot_id
                    )
                ),
                *session.scalars(
                    select(cast(data_quality_issue.c.details, JSONB)).where(
                        data_quality_issue.c.source_snapshot_id == outcome.result.source_snapshot_id
                    )
                ),
            )
        )
        assert canary not in persisted_text
        assert credential_value not in persisted_text
        assert session.scalar(select(func.count()).select_from(odds_observation)) == 0


@pytest.mark.postgres
def test_http_failure_attempt_and_quota_are_retained_without_raw_body(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    credential_value = _credential(repository_root)
    transport = _SequenceTransport([_response(repository_root, remaining=0, status=429)])
    outcome = _snapshot(
        OddsIngestionService(
            repository_root=repository_root,
            credential_provider=_CountingCredentialProvider(credential_value),
            transport_factory=lambda: transport,
            clock=lambda: CAPTURED,
        )
    )

    assert outcome.exit_code == 5
    assert outcome.result.status == "FAILED"
    assert outcome.result.error is not None
    assert outcome.result.error.code == "HTTP_429"
    assert outcome.result.error.transport_called is True
    assert outcome.result.error.retryable is False
    assert outcome.result.source_snapshot_id is not None
    assert outcome.result.quota is not None and outcome.result.quota.remaining == 0
    assert transport.calls == 1
    with postgres_session_factory() as session:
        snapshot = (
            session.execute(
                select(source_snapshot).where(
                    source_snapshot.c.source_snapshot_id == outcome.result.source_snapshot_id
                )
            )
            .mappings()
            .one()
        )
        assert snapshot["http_status"] == 429
        assert snapshot["body_sha256"] is not None
        assert snapshot["body_size"] == len(_raw_body(repository_root))
        assert snapshot["raw_blob_id"] is None
        assert snapshot["raw_storage_object_id"] is None
        assert session.scalar(select(func.count()).select_from(provider_quota_observation)) == 1
        assert session.scalar(select(func.count()).select_from(data_quality_issue)) == 1


@pytest.mark.postgres
def test_persisted_quota_depletion_blocks_next_credential_and_transport_call(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    assert postgres_session_factory is not None
    credential = _CountingCredentialProvider(_credential(repository_root))
    first_transport = _SequenceTransport([_response(repository_root, remaining=0, status=429)])
    first = _snapshot(
        OddsIngestionService(
            repository_root=repository_root,
            credential_provider=credential,
            transport_factory=lambda: first_transport,
            clock=lambda: CAPTURED,
        )
    )
    assert first.exit_code == 5
    assert credential.calls == first_transport.calls == 1

    constructions = 0

    def forbidden_transport() -> _SequenceTransport:
        nonlocal constructions
        constructions += 1
        raise AssertionError("depleted quota must block transport")

    second = _snapshot(
        OddsIngestionService(
            repository_root=repository_root,
            credential_provider=credential,
            transport_factory=forbidden_transport,
            clock=lambda: CAPTURED,
        )
    )
    assert second.exit_code == 4
    assert second.result.status == "BLOCKED"
    assert second.result.error is not None
    assert second.result.error.code == "QUOTA_EXHAUSTED"
    assert second.result.error.transport_called is False
    assert credential.calls == 1
    assert constructions == 0


@pytest.mark.postgres
def test_odds_and_quota_evidence_are_database_immutable(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from dmf_pulse.ingestion.odds.service import OddsReplayRequest

    outcome = OddsIngestionService(repository_root=repository_root).replay(
        OddsReplayRequest(
            fixture_set=repository_root / "fixtures/odds/ODD-005",
            scenario="happy_path",
        )
    )
    assert outcome.exit_code == 0

    with (
        pytest.raises(DBAPIError, match="immutable"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(update(odds_observation).values(decimal_odds=2))
    with (
        pytest.raises(DBAPIError, match="immutable"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(update(provider_quota_observation).values(remaining=1))
    with (
        pytest.raises(DBAPIError, match="immutable"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(update(source_snapshot).values(content_type="text/plain"))
