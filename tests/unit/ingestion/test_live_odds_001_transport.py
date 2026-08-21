"""LIVE-ODDS-001 offline transport, retry, and secret-boundary contract."""

from __future__ import annotations

import dataclasses
import inspect
import logging
import ssl
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.client import (
    HttpClientOddsTransport,
    OddsClient,
    OddsFetchFailure,
    OddsHttpRequest,
    OddsHttpResponse,
    StaticCredentialProvider,
    UrllibOddsTransport,
    build_request,
)
from dmf_pulse.ingestion.odds.config import load_provider_config, load_rights_profiles
from dmf_pulse.ingestion.odds.models import ProviderFailureCode, QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.ingestion.odds.service import OddsIngestionService

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
SENTINEL = "fixture-secret-sentinel-913579"
QUOTA_HEADERS = {
    "x-requests-remaining": "498",
    "x-requests-used": "2",
    "x-requests-last": "2",
}


class _Socket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)


class _Response:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"[]",
        read_error: BaseException | None = None,
    ) -> None:
        self.status = status
        self._headers = dict(headers or {"content-type": "application/json", **QUOTA_HEADERS})
        self._body = body
        self._offset = 0
        self._read_error = read_error
        self.read_sizes: list[int] = []

    def getheaders(self) -> list[tuple[str, str]]:
        return list(self._headers.items())

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        if self._read_error is not None:
            error = self._read_error
            self._read_error = None
            raise error
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _Connection:
    def __init__(
        self,
        response: _Response,
        *,
        connect_error: BaseException | None = None,
        request_error: BaseException | None = None,
        response_error: BaseException | None = None,
    ) -> None:
        self.response = response
        self.connect_error = connect_error
        self.request_error = request_error
        self.response_error = response_error
        self.sock = _Socket()
        self.connected = 0
        self.closed = 0
        self.requests: list[tuple[str, str, object, Mapping[str, str]]] = []

    def connect(self) -> None:
        self.connected += 1
        if self.connect_error is not None:
            raise self.connect_error

    def request(
        self,
        method: str,
        url: str,
        body: object = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.requests.append((method, url, body, dict(headers or {})))
        if self.request_error is not None:
            raise self.request_error

    def getresponse(self) -> _Response:
        if self.response_error is not None:
            raise self.response_error
        return self.response

    def close(self) -> None:
        self.closed += 1


class _ConnectionFactory:
    def __init__(self, connections: list[_Connection]) -> None:
        self.connections = connections
        self.calls: list[tuple[str, float, ssl.SSLContext]] = []

    def __call__(self, host: str, timeout: float, context: ssl.SSLContext) -> _Connection:
        self.calls.append((host, timeout, context))
        return self.connections.pop(0)


class _ProtocolTransport:
    transport_id = "injected"

    def __init__(self, responses: list[OddsHttpResponse | IngestionError]) -> None:
        self.responses = responses
        self.requests: list[OddsHttpRequest] = []

    def send(self, request: OddsHttpRequest) -> OddsHttpResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, IngestionError):
            raise response
        return response


class _Monotonic:
    def __init__(self, values: list[float]) -> None:
        self.values = values
        self.last = values[-1]

    def __call__(self) -> float:
        if self.values:
            self.last = self.values.pop(0)
        return self.last


def _request() -> OddsHttpRequest:
    return build_request(SENTINEL, commence_from=CUTOFF)


def _transport(
    connection: _Connection,
    *,
    monotonic: Callable[[], float] = lambda: 0.0,
    context_factory: Callable[[], ssl.SSLContext] = ssl.create_default_context,
) -> tuple[HttpClientOddsTransport, _ConnectionFactory]:
    factory = _ConnectionFactory([connection])
    return (
        HttpClientOddsTransport(
            connection_factory=factory,
            ssl_context_factory=context_factory,
            monotonic=monotonic,
        ),
        factory,
    )


def _client(transport: _ProtocolTransport) -> OddsClient:
    return OddsClient(
        load_rights_profiles()["the_odds_api_private_analytics_v1"],
        credential_provider=StaticCredentialProvider(SENTINEL),
        transport_factory=lambda: transport,
        clock=lambda: NOW,
        sleeper=lambda _seconds: None,
        monotonic=lambda: 0.0,
    )


def _http_response(
    status: int = 200,
    *,
    headers: Mapping[str, str] = QUOTA_HEADERS,
    body: bytes = b"[]",
    content_type: str = "application/json",
    redirect_location: str | None = None,
) -> OddsHttpResponse:
    return OddsHttpResponse(status, content_type, headers, body, redirect_location)


def test_tr01_tr02_exact_https_get_and_secret_free_request_contract() -> None:
    response = _Response()
    connection = _Connection(response)
    transport, factory = _transport(connection)
    request = _request()

    result = transport.send(request)

    assert result.status_code == 200
    assert factory.calls[0][0:2] == ("api.the-odds-api.com", 10.0)
    context = factory.calls[0][2]
    assert context.check_hostname is True
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert connection.requests == [
        (
            "GET",
            "/v4/sports/soccer_epl/odds?apiKey=fixture-secret-sentinel-913579&"
            "regions=uk&markets=h2h%2Ctotals&oddsFormat=decimal&dateFormat=iso&"
            "commenceTimeFrom=2026-08-21T17%3A30%3A00Z",
            None,
            {"Accept": "application/json", "User-Agent": "dmf-pulse-private/0.2.0"},
        )
    ]
    assert SENTINEL not in request.sanitized_target
    assert SENTINEL not in request.request_fingerprint
    assert SENTINEL not in repr(request)
    with pytest.raises(TypeError):
        dataclasses.asdict(request)
    with pytest.raises(TypeError):
        vars(request)


def test_tr03_redirect_is_not_followed_and_location_is_redacted() -> None:
    response = _Response(
        status=302,
        headers={"content-type": "text/plain", "location": f"https://elsewhere/{SENTINEL}"},
    )
    connection = _Connection(response)
    transport, factory = _transport(connection)

    result = transport.send(_request())

    assert len(factory.calls) == 1
    assert len(connection.requests) == 1
    assert result.redirect_location == "PRESENT"
    assert SENTINEL not in repr(result)
    assert "location" not in result.headers


def test_tr04_valid_json_response_envelope_keeps_only_safe_headers() -> None:
    response = _Response(
        headers={
            "Content-Type": "application/json; charset=utf-8",
            **QUOTA_HEADERS,
            "x-request-id": "request-913",
            "set-cookie": SENTINEL,
            "authorization": SENTINEL,
        },
        body=b"[]",
    )
    transport, _factory = _transport(_Connection(response))

    result = transport.send(_request())

    assert result.content_type == "application/json; charset=utf-8"
    assert result.body == b"[]"
    assert set(result.headers) == {
        "content-type",
        "x-requests-remaining",
        "x-requests-used",
        "x-requests-last",
        "x-request-id",
    }
    assert SENTINEL not in repr(result)
    with pytest.raises(TypeError):
        result.headers["x-request-id"] = SENTINEL  # type: ignore[index]


@pytest.mark.parametrize(
    ("status", "code", "attempts"),
    (
        (401, ProviderFailureCode.HTTP_4XX, 1),
        (429, ProviderFailureCode.HTTP_429, 2),
        (503, ProviderFailureCode.HTTP_5XX, 2),
    ),
)
def test_tr05_tr06_tr07_http_statuses_and_retries_are_typed(
    status: int,
    code: ProviderFailureCode,
    attempts: int,
) -> None:
    headers = {**QUOTA_HEADERS, "retry-after": "1"}
    transport = _ProtocolTransport([_http_response(status, headers=headers)] * attempts)

    with pytest.raises(OddsFetchFailure) as raised:
        _client(transport).fetch()

    assert raised.value.code == code.value
    assert len(transport.requests) == attempts
    assert len(raised.value.attempts) == attempts
    if status == 429:
        assert raised.value.attempts[0].requested_delay_seconds == 1
        assert raised.value.attempts[0].applied_delay_seconds == 1


@pytest.mark.parametrize(
    ("connection", "code"),
    (
        (_Connection(_Response(), connect_error=TimeoutError(SENTINEL)), "CONNECT_TIMEOUT"),
        (_Connection(_Response(), response_error=TimeoutError(SENTINEL)), "READ_TIMEOUT"),
        (_Connection(_Response(read_error=TimeoutError(SENTINEL))), "READ_TIMEOUT"),
        (_Connection(_Response(), connect_error=ssl.SSLError(SENTINEL)), "TLS_ERROR"),
        (_Connection(_Response(), connect_error=OSError(SENTINEL)), "SOURCE_UNAVAILABLE"),
    ),
)
def test_tr08_tr09_tr11_tr12_transport_failures_are_typed_and_secret_free(
    connection: _Connection,
    code: str,
) -> None:
    transport, _factory = _transport(connection)

    with pytest.raises(IngestionError) as raised:
        transport.send(_request())

    assert raised.value.code == code
    assert SENTINEL not in str(raised.value)
    assert SENTINEL not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert connection.closed == 1


def test_tr10_total_timeout_is_enforced_across_transport_phases() -> None:
    connection = _Connection(_Response())
    transport, _factory = _transport(connection, monotonic=_Monotonic([0.0, 0.0, 31.0]))

    with pytest.raises(IngestionError) as raised:
        transport.send(_request())

    assert raised.value.code == "TOTAL_TIMEOUT"
    assert connection.closed == 1


def test_td01_remaining_total_is_reapplied_before_response_headers() -> None:
    class HeaderTimeoutConnection(_Connection):
        timeout_at_getresponse: float | None = None

        def getresponse(self) -> _Response:
            self.timeout_at_getresponse = self.sock.timeouts[-1]
            return super().getresponse()

    connection = HeaderTimeoutConnection(_Response())
    transport, _factory = _transport(
        connection,
        monotonic=_Monotonic([0.0, 0.0, 0.0, 19.0, 19.0, 19.0, 19.0]),
    )

    transport.send(_request())

    assert connection.timeout_at_getresponse == 11.0


def test_tr13_response_read_is_bounded_to_maximum_plus_one() -> None:
    limit = load_provider_config().max_response_bytes
    response = _Response(body=b"x" * (limit + 100_000))
    transport, _factory = _transport(_Connection(response))

    result = transport.send(_request())

    assert len(result.body) == limit + 1
    assert sum(response.read_sizes) <= limit + 1 + 64 * 1024


def test_tr14_malformed_json_reaches_parser_as_typed_failure() -> None:
    transport, _factory = _transport(_Connection(_Response(body=b"{not-json")))
    result = transport.send(_request())

    with pytest.raises(IngestionError) as raised:
        parse_odds_payload(result.body)
    assert raised.value.code == "MALFORMED_JSON"


@pytest.mark.parametrize(
    "headers",
    (
        {},
        {"x-requests-remaining": "bad", "x-requests-used": "2", "x-requests-last": "2"},
    ),
)
def test_tr15_invalid_or_missing_quota_headers_are_typed(headers: Mapping[str, str]) -> None:
    transport = _ProtocolTransport([_http_response(headers=headers)])

    with pytest.raises(OddsFetchFailure) as raised:
        _client(transport).fetch()

    assert raised.value.code == "SOURCE_UNAVAILABLE"
    assert raised.value.attempts[-1].quota_header_state in {"ABSENT", "INVALID"}


def test_tr16_provider_request_id_is_exposed_only_as_hash() -> None:
    raw_request_id = f"provider-request-{SENTINEL}"
    transport = _ProtocolTransport(
        [_http_response(headers={**QUOTA_HEADERS, "x-request-id": raw_request_id})]
    )

    fetched = _client(transport).fetch()

    assert fetched.provider_request_id_sha256 == canonical_sha256(raw_request_id)
    assert raw_request_id not in repr(fetched)
    assert raw_request_id not in repr(fetched.attempts)


def test_tr17_lower_exception_error_body_headers_logging_and_serialization_do_not_leak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    response = _Response(
        status=500,
        headers={"content-type": "application/json", "x-request-id": SENTINEL},
        body=f'{{"apiKey":"{SENTINEL}"}}'.encode(),
    )
    transport, _factory = _transport(_Connection(response))
    result = transport.send(_request())

    assert SENTINEL not in repr(result)
    with pytest.raises(TypeError):
        dataclasses.asdict(result)
    with pytest.raises(TypeError):
        vars(result)
    assert SENTINEL not in caplog.text


def test_tr18_attempt_evidence_and_call_count_match_bounded_retry() -> None:
    transport = _ProtocolTransport(
        [
            IngestionError("SOURCE_UNAVAILABLE", SENTINEL, retryable=True),
            _http_response(),
        ]
    )

    fetched = _client(transport).fetch()

    assert fetched.transport_call_count == 2
    assert fetched.transport_id == "injected"
    assert [attempt.attempt_number for attempt in fetched.attempts] == [1, 2]
    assert [attempt.attempt_outcome for attempt in fetched.attempts] == [
        "RETRY_SCHEDULED",
        "SUCCESS",
    ]
    assert all(attempt.transport_id == "injected" for attempt in fetched.attempts)
    assert SENTINEL not in repr(fetched.attempts)


def test_tr19_default_transport_is_explicit_and_has_no_urllib_fallback() -> None:
    service = OddsIngestionService()

    assert service.transport_factory is HttpClientOddsTransport
    assert service.transport_factory is not UrllibOddsTransport
    assert "UrllibOddsTransport" not in inspect.getsource(HttpClientOddsTransport.send)


def test_tr20_http_client_transport_satisfies_approved_protocol() -> None:
    response = _Response()
    transport, _factory = _transport(_Connection(response))

    result = transport.send(_request())

    assert isinstance(result, OddsHttpResponse)
    assert result.status_code == 200
    assert result.content_type == "application/json"
    assert result.body == b"[]"


def test_tr21_tr22_transport_has_no_platform_or_filesystem_assumption() -> None:
    source = inspect.getsource(HttpClientOddsTransport)

    assert "os.name" not in source
    assert "sys.platform" not in source
    assert "Path(" not in source
    assert Path("windows\\style") != Path("posix/style")


def test_request_cost_gate_uses_the_two_approved_markets() -> None:
    quota = QuotaState(
        remaining=1,
        used=499,
        last_cost=1,
        observed_at=NOW,
        source=QuotaSource.RESPONSE_HEADERS,
    )
    transport = _ProtocolTransport([])

    with pytest.raises(IngestionError) as raised:
        _client(transport).fetch(quota=quota)

    assert raised.value.code == "QUOTA_EXHAUSTED"
    assert transport.requests == []
