"""Credential, transport, redirect, retry, and quota oracles for live odds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.client import (
    OddsHttpRequest,
    OddsHttpResponse,
    StaticCredentialProvider,
    UnavailableCredentialProvider,
)
from dmf_pulse.ingestion.odds.config import load_provider_config
from dmf_pulse.ingestion.odds.live import (
    LiveEvidenceHandle,
    LiveOddsSnapshotService,
)
from dmf_pulse.ingestion.odds.models import ProviderFailureCode, QuotaSource, QuotaState

pytestmark = pytest.mark.unit

RECEIVED = datetime(2026, 8, 20, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
DUMMY_RUNTIME_VALUE = "dummy-odds-key-1234567890"
SOURCE_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000913")


class FakeEvidenceStore:
    def __init__(self, quota: QuotaState | None = None) -> None:
        self.quota = quota
        self.attempts: list[tuple[object, ...]] = []
        self.rejections: list[str] = []
        self.usable = 0

    def latest_quota(self, database_url_ref: str) -> QuotaState | None:
        assert database_url_ref == "env:DMF_TEST_DATABASE_URL"
        return self.quota

    def record_attempts(
        self,
        *,
        profile: object,
        attempts: tuple[object, ...],
        successful_body: bytes | None = None,
    ) -> LiveEvidenceHandle:
        del profile, successful_body
        self.attempts.append(attempts)
        return LiveEvidenceHandle(SOURCE_SNAPSHOT_ID)

    def record_rejected(
        self,
        handle: LiveEvidenceHandle,
        *,
        observed_at: datetime,
        error: IngestionError,
        parsed: object | None = None,
    ) -> None:
        del parsed
        assert handle.source_snapshot_id == SOURCE_SNAPSHOT_ID
        assert observed_at.tzinfo is not None
        self.rejections.append(error.code)

    def record_usable(
        self,
        handle: LiveEvidenceHandle,
        *,
        parsed: object,
        current_input: object,
    ) -> None:
        del parsed, current_input
        assert handle.source_snapshot_id == SOURCE_SNAPSHOT_ID
        self.usable += 1


class FakeTransport:
    def __init__(self, responses: list[OddsHttpResponse | IngestionError]) -> None:
        self.responses = responses
        self.requests: list[OddsHttpRequest] = []

    def send(self, request: OddsHttpRequest) -> OddsHttpResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, IngestionError):
            raise response
        return response


def _fixture(repository_root: Path) -> bytes:
    return (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes()


def _response(
    repository_root: Path,
    *,
    status: int = 200,
    content_type: str = "application/json",
    remaining: str = "499",
    used: str = "1",
    last: str = "1",
    body: bytes | None = None,
    redirect_location: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> OddsHttpResponse:
    headers = {
        "x-requests-remaining": remaining,
        "x-requests-used": used,
        "x-requests-last": last,
        "x-request-id": "provider-request-913",
    }
    headers.update(extra_headers or {})
    return OddsHttpResponse(
        status_code=status,
        content_type=content_type,
        headers=headers,
        body=_fixture(repository_root) if body is None else body,
        redirect_location=redirect_location,
    )


def _service(
    transport: FakeTransport,
    store: FakeEvidenceStore,
    *,
    credential: str | None = DUMMY_RUNTIME_VALUE,
    processing_at: datetime = RECEIVED + timedelta(seconds=1),
) -> LiveOddsSnapshotService:
    provider = (
        UnavailableCredentialProvider()
        if credential is None
        else StaticCredentialProvider(credential)
    )
    return LiveOddsSnapshotService(
        database_url_ref="env:DMF_TEST_DATABASE_URL",
        credential_provider=provider,
        transport_factory=lambda: transport,
        clock=lambda: RECEIVED,
        processing_clock=lambda: processing_at,
        sleeper=lambda _seconds: None,
        monotonic=lambda: 0.0,
        evidence_store=store,
    )


def _snapshot(service: LiveOddsSnapshotService):
    return service.snapshot(
        provider="the_odds_api",
        competition_key="PL",
        sport_key="soccer_epl",
        region="uk",
        market="h2h",
        as_of=CUTOFF,
        database_url_ref="env:DMF_TEST_DATABASE_URL",
    )


def test_valid_dummy_runtime_credential_reaches_only_transport_boundary(
    repository_root: Path,
) -> None:
    transport = FakeTransport([_response(repository_root)])
    store = FakeEvidenceStore()

    outcome = _snapshot(_service(transport, store))

    assert outcome.exit_code == 0
    assert outcome.result.status == "COMPLETE"
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.credential == DUMMY_RUNTIME_VALUE
    assert request.scheme == "https"
    assert request.host == "api.the-odds-api.com"
    assert request.path == "/v4/sports/soccer_epl/odds"
    assert request.connect_timeout_seconds == 10
    assert request.read_timeout_seconds == 20
    assert request.total_timeout_seconds == 30
    assert "apiKey" not in request.sanitized_target
    assert DUMMY_RUNTIME_VALUE not in request.sanitized_target
    assert DUMMY_RUNTIME_VALUE not in request.request_fingerprint
    assert DUMMY_RUNTIME_VALUE not in repr(request)
    assert DUMMY_RUNTIME_VALUE not in outcome.result.model_dump_json()
    assert store.usable == 1


@pytest.mark.parametrize("credential", (None, "", "short", "contains space 123456"))
def test_missing_blank_or_malformed_credential_is_controlled_before_transport(
    repository_root: Path,
    credential: str | None,
) -> None:
    transport = FakeTransport([_response(repository_root)])
    outcome = _snapshot(_service(transport, FakeEvidenceStore(), credential=credential))

    assert outcome.exit_code == 4
    assert outcome.result.status == "BLOCKED"
    assert outcome.result.error is not None
    assert outcome.result.error.code is ProviderFailureCode.CREDENTIAL_UNAVAILABLE
    assert outcome.result.error.transport_called is False
    assert transport.requests == []
    assert DUMMY_RUNTIME_VALUE not in outcome.result.model_dump_json()


def test_local_quota_exhaustion_blocks_before_transport(repository_root: Path) -> None:
    exhausted = QuotaState(
        remaining=0,
        used=500,
        last_cost=1,
        observed_at=RECEIVED,
        source=QuotaSource.RESPONSE_HEADERS,
    )
    transport = FakeTransport([_response(repository_root)])
    outcome = _snapshot(_service(transport, FakeEvidenceStore(exhausted)))

    assert outcome.exit_code == 4
    assert outcome.result.error is not None
    assert outcome.result.error.code is ProviderFailureCode.QUOTA_EXHAUSTED
    assert outcome.result.error.transport_called is False
    assert transport.requests == []


@pytest.mark.parametrize(
    "location",
    (
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
        "https://unapproved.example/odds",
        "http://api.the-odds-api.com/v4/sports/soccer_epl/odds",
        "https://api.the-odds-api.com/redirect/again",
    ),
)
def test_every_redirect_shape_is_fail_closed_without_credential_forwarding(
    repository_root: Path,
    location: str,
) -> None:
    transport = FakeTransport(
        [
            _response(
                repository_root,
                status=302,
                content_type="text/plain",
                redirect_location=location,
            )
        ]
    )
    outcome = _snapshot(_service(transport, FakeEvidenceStore()))

    assert outcome.exit_code == 5
    assert outcome.result.error is not None
    assert outcome.result.error.code is ProviderFailureCode.REDIRECT_BLOCKED
    assert len(transport.requests) == 1
    assert DUMMY_RUNTIME_VALUE not in outcome.result.model_dump_json()


@pytest.mark.parametrize(
    ("status", "code", "attempts"),
    (
        (401, ProviderFailureCode.HTTP_4XX, 1),
        (403, ProviderFailureCode.HTTP_4XX, 1),
        (429, ProviderFailureCode.HTTP_429, 2),
        (500, ProviderFailureCode.HTTP_5XX, 2),
        (503, ProviderFailureCode.HTTP_5XX, 2),
    ),
)
def test_http_failure_matrix_is_typed_and_bounded(
    repository_root: Path,
    status: int,
    code: ProviderFailureCode,
    attempts: int,
) -> None:
    response = _response(repository_root, status=status)
    transport = FakeTransport([response] * attempts)
    outcome = _snapshot(_service(transport, FakeEvidenceStore()))

    assert outcome.exit_code == 5
    assert outcome.result.error is not None
    assert outcome.result.error.code is code
    assert len(transport.requests) == attempts
    assert len(transport.requests) <= load_provider_config().retry.max_attempts


def test_quota_exhaustion_header_prevents_blind_429_retry(repository_root: Path) -> None:
    response = _response(repository_root, status=429, remaining="0", used="500", last="1")
    transport = FakeTransport([response])
    outcome = _snapshot(_service(transport, FakeEvidenceStore()))

    assert outcome.result.error is not None
    assert outcome.result.error.code is ProviderFailureCode.HTTP_429
    assert outcome.result.error.retryable is False
    assert len(transport.requests) == 1
    assert outcome.result.quota is not None
    assert outcome.result.quota.remaining == 0


@pytest.mark.parametrize(
    ("response", "code"),
    (
        (
            OddsHttpResponse(200, "application/json", {}, b"[]"),
            ProviderFailureCode.SOURCE_UNAVAILABLE,
        ),
        (
            OddsHttpResponse(
                200,
                "application/json",
                {
                    "x-requests-remaining": "bad",
                    "x-requests-used": "1",
                    "x-requests-last": "1",
                },
                b"[]",
            ),
            ProviderFailureCode.SOURCE_UNAVAILABLE,
        ),
        (
            OddsHttpResponse(
                200,
                "text/html",
                {
                    "x-requests-remaining": "1",
                    "x-requests-used": "1",
                    "x-requests-last": "1",
                },
                b"<html>",
            ),
            ProviderFailureCode.CONTENT_TYPE_INVALID,
        ),
    ),
)
def test_response_contract_failures_are_secret_free(
    response: OddsHttpResponse,
    code: ProviderFailureCode,
) -> None:
    transport = FakeTransport([response])
    outcome = _snapshot(_service(transport, FakeEvidenceStore()))

    assert outcome.result.error is not None
    assert outcome.result.error.code is code
    assert DUMMY_RUNTIME_VALUE not in outcome.result.model_dump_json()


def test_oversized_response_is_rejected(repository_root: Path) -> None:
    config = load_provider_config()
    transport = FakeTransport(
        [_response(repository_root, body=b"[" + b" " * config.max_response_bytes + b"]")]
    )
    outcome = _snapshot(_service(transport, FakeEvidenceStore()))

    assert outcome.result.error is not None
    assert outcome.result.error.code is ProviderFailureCode.PAYLOAD_TOO_LARGE
    assert len(transport.requests) == 1


@pytest.mark.parametrize("code", ("CONNECT_TIMEOUT", "READ_TIMEOUT", "TOTAL_TIMEOUT", "TLS_ERROR"))
def test_transport_timeout_and_tls_classes_are_bounded(
    repository_root: Path,
    code: str,
) -> None:
    retryable = code != "TLS_ERROR"
    failure = IngestionError(code, "provider transport failed safely", retryable=retryable)
    attempts = 2 if retryable else 1
    transport = FakeTransport([failure] * attempts)
    outcome = _snapshot(_service(transport, FakeEvidenceStore()))

    assert outcome.result.error is not None
    assert outcome.result.error.code.value == code
    assert len(transport.requests) == attempts
    assert len(transport.requests) <= 2
    assert DUMMY_RUNTIME_VALUE not in outcome.result.model_dump_json()


def test_provider_quota_and_request_cost_are_exposed_without_secret(
    repository_root: Path,
) -> None:
    transport = FakeTransport([_response(repository_root, remaining="417", used="83", last="1")])
    outcome = _snapshot(_service(transport, FakeEvidenceStore()))

    assert outcome.result.quota is not None
    assert outcome.result.quota.remaining == 417
    assert outcome.result.quota.used == 83
    assert outcome.result.quota.last_cost == 1
    assert outcome.result.current_input is not None
    assert outcome.result.current_input.quota.configured_request_cost == 1
    assert outcome.result.current_input.quota.provider_last_request_cost == 1
    assert DUMMY_RUNTIME_VALUE not in outcome.result.model_dump_json()


@pytest.mark.parametrize(
    ("status", "code"),
    (
        (401, ProviderFailureCode.HTTP_4XX),
        (429, ProviderFailureCode.HTTP_429),
        (500, ProviderFailureCode.HTTP_5XX),
    ),
)
def test_http_status_is_preserved_when_quota_headers_are_absent(
    status: int,
    code: ProviderFailureCode,
) -> None:
    response = OddsHttpResponse(status, "application/json", {}, b"{}")
    max_attempts = load_provider_config().retry.max_attempts
    transport = FakeTransport([response] * max_attempts)

    outcome = _snapshot(_service(transport, FakeEvidenceStore()))

    assert outcome.result.error is not None
    assert outcome.result.error.code is code
    assert 1 <= len(transport.requests) <= max_attempts


def test_post_cutoff_processing_is_observed_but_not_usable(
    repository_root: Path,
) -> None:
    transport = FakeTransport([_response(repository_root)])
    store = FakeEvidenceStore()

    outcome = _snapshot(
        _service(
            transport,
            store,
            processing_at=CUTOFF + timedelta(seconds=1),
        )
    )

    assert outcome.exit_code == 2
    assert outcome.result.status == "OBSERVED_NOT_USABLE"
    assert outcome.result.current_input is None
    assert outcome.result.quality.blockers == ("POST_CUTOFF",)
    assert store.rejections == ["POST_CUTOFF"]
    assert store.usable == 0


def test_malformed_json_is_quarantined_without_raw_body_output() -> None:
    transport = FakeTransport(
        [
            OddsHttpResponse(
                200,
                "application/json",
                {
                    "x-requests-remaining": "499",
                    "x-requests-used": "1",
                    "x-requests-last": "1",
                },
                b"{not-json",
            )
        ]
    )
    store = FakeEvidenceStore()

    outcome = _snapshot(_service(transport, store))

    assert outcome.exit_code == 3
    assert outcome.result.status == "QUARANTINED"
    assert outcome.result.quality.blockers == ("MALFORMED_JSON",)
    assert store.rejections == ["MALFORMED_JSON"]
    assert "not-json" not in outcome.result.model_dump_json()
