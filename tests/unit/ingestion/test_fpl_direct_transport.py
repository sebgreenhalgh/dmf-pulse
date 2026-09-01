"""Cross-platform transport proofs for direct official-FPL reads."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.message import Message
from types import SimpleNamespace

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl import direct as direct_module
from dmf_pulse.ingestion.fpl.direct import (
    DIRECT_FPL_HOST,
    DIRECT_FPL_USER_AGENT,
    DirectFplClient,
    DirectFplResource,
    DirectFplRunAttestation,
    DirectHttpRequest,
    DirectHttpResponse,
    DirectUrllibTransport,
)

pytestmark = pytest.mark.unit

_CREDENTIAL_MARKER = "synthetic-credential-never-disclose"
_READ_FAILURE = "synthetic-read-failure-never-disclose"


class _Headers(Message):
    def __init__(
        self, content_type: str = "application/json", *, content_length: int | str | None = None
    ) -> None:
        super().__init__()
        self["Content-Type"] = content_type
        if content_length is not None:
            self["Content-Length"] = str(content_length)


class _LifecycleSocket:
    def __init__(self, *, descriptor: int = 42, timeout_error: OSError | None = None) -> None:
        self.descriptor = descriptor
        self.timeout_error = timeout_error
        self.timeout_calls: list[float] = []
        self.failed_timeout_calls = 0

    def close(self) -> None:
        self.descriptor = -1

    def fileno(self) -> int:
        return self.descriptor

    def settimeout(self, value: float) -> None:
        self.timeout_calls.append(value)
        if self.descriptor < 0:
            self.failed_timeout_calls += 1
            raise OSError("synthetic closed socket")
        if self.timeout_error is not None:
            self.failed_timeout_calls += 1
            raise self.timeout_error


class _UnavailableDescriptorSocket(_LifecycleSocket):
    def fileno(self) -> int:
        raise OSError("synthetic detached descriptor")


class _MissingDescriptorSocket:
    def settimeout(self, value: float) -> None:
        del value
        raise OSError("synthetic socket without descriptor")


class _LifecycleResponse:
    def __init__(
        self,
        body: bytes,
        *,
        chunk_size: int = 2,
        detach_after_body: bool = False,
        read_failure: BaseException | None = None,
        fail_on_read: int = 1,
        socket: _LifecycleSocket | None = None,
        status: int = 200,
        content_type: str = "application/json",
        declared_length: int | str | None = None,
        include_content_length: bool = True,
    ) -> None:
        self.status = status
        content_length = len(body) if declared_length is None else declared_length
        self.headers = _Headers(
            content_type,
            content_length=content_length if include_content_length else None,
        )
        self._body = body
        self._chunk_size = chunk_size
        self._detach_after_body = detach_after_body
        self._read_failure = read_failure
        self._fail_on_read = fail_on_read
        self._offset = 0
        self.read_calls = 0
        self.socket = socket or _LifecycleSocket()
        self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=self.socket))

    def __enter__(self) -> _LifecycleResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        self.read_calls += 1
        if self._read_failure is not None and self.read_calls == self._fail_on_read:
            raise self._read_failure
        if self._offset >= len(self._body):
            return b""
        width = min(limit, self._chunk_size)
        chunk = self._body[self._offset : self._offset + width]
        self._offset += len(chunk)
        if self._detach_after_body and self._offset == len(self._body):
            self.socket.close()
        return chunk


class _Opener:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def open(self, request: urllib.request.Request, *, timeout: float) -> _LifecycleResponse:
        self.calls.append((request, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        assert isinstance(self.outcome, _LifecycleResponse)
        return self.outcome


class _StaticTransport:
    def __init__(self, response: DirectHttpResponse) -> None:
        self.response = response

    def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
        del request
        return self.response


def _request(*, authenticated: bool = False) -> DirectHttpRequest:
    headers = {"Accept": "application/json", "User-Agent": DIRECT_FPL_USER_AGENT}
    if authenticated:
        headers["X-API-Authorization"] = f"Bearer {_CREDENTIAL_MARKER}"
    return DirectHttpRequest(
        method="GET",
        host=DIRECT_FPL_HOST,
        path="/api/my-team/42/" if authenticated else "/api/bootstrap-static/",
        headers=headers,
        connect_timeout_seconds=1.0,
        read_timeout_seconds=2.0,
        total_timeout_seconds=4.0,
    )


def _attestation() -> DirectFplRunAttestation:
    return DirectFplRunAttestation(attested_at=datetime(2026, 9, 1, tzinfo=UTC))


def _set_limit(monkeypatch: pytest.MonkeyPatch, limit: int) -> None:
    config = direct_module.load_provider_config().model_copy(update={"max_response_bytes": limit})
    monkeypatch.setattr(direct_module, "load_provider_config", lambda: config)


def test_complete_multichunk_body_survives_socket_detach_before_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _LifecycleResponse(b'{"ok":true}', chunk_size=3, detach_after_body=True)
    opener = _Opener(response)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: opener)

    result = DirectUrllibTransport(monotonic=lambda: 0.0).send(_request())

    assert result.body == b'{"ok":true}'
    assert response.read_calls == 5
    assert response.socket.failed_timeout_calls == 1
    assert len(response.socket.timeout_calls) == response.read_calls
    assert opener.calls[0][1] == 1.0


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [(b"1234", None), (b"12345", "PAYLOAD_TOO_LARGE")],
)
def test_bounded_reader_accepts_exact_limit_and_rejects_one_byte_over(
    monkeypatch: pytest.MonkeyPatch, body: bytes, expected_code: str | None
) -> None:
    _set_limit(monkeypatch, 4)
    transport = DirectUrllibTransport(monotonic=lambda: 0.0)
    response = _LifecycleResponse(body, chunk_size=2)

    if expected_code is None:
        assert transport._body(response, _request(), started_at=0.0) == body
    else:
        with pytest.raises(IngestionError) as raised:
            transport._body(response, _request(), started_at=0.0)
        assert raised.value.code == expected_code


@pytest.mark.parametrize(
    ("failure", "expected_code", "retryable"),
    [
        (OSError(_READ_FAILURE), "SOURCE_UNAVAILABLE", True),
        (TimeoutError(_READ_FAILURE), "READ_TIMEOUT", True),
        (ssl.SSLError(_READ_FAILURE), "TLS_ERROR", False),
    ],
)
def test_body_reader_preserves_genuine_failures_without_disclosure(
    failure: BaseException, expected_code: str, retryable: bool
) -> None:
    response = _LifecycleResponse(
        b"partial-body", read_failure=failure, fail_on_read=2, chunk_size=3
    )

    with pytest.raises(IngestionError) as raised:
        DirectUrllibTransport(monotonic=lambda: 0.0)._body(
            response, _request(authenticated=True), started_at=0.0
        )

    assert raised.value.code == expected_code
    assert raised.value.retryable is retryable
    assert _READ_FAILURE not in raised.value.message
    assert _CREDENTIAL_MARKER not in raised.value.message


def test_open_socket_timeout_adjustment_failure_is_not_swallowed() -> None:
    socket = _LifecycleSocket(timeout_error=OSError(_READ_FAILURE))
    response = _LifecycleResponse(b"unread", socket=socket)

    with pytest.raises(IngestionError) as raised:
        DirectUrllibTransport(monotonic=lambda: 0.0)._body(response, _request(), started_at=0.0)

    assert raised.value.code == "SOURCE_UNAVAILABLE"
    assert response.read_calls == 0
    assert _READ_FAILURE not in raised.value.message


def test_detached_descriptor_failure_defers_to_the_reader() -> None:
    socket = _UnavailableDescriptorSocket(timeout_error=OSError("synthetic detached socket"))
    response = _LifecycleResponse(b"complete", chunk_size=8, socket=socket)

    assert (
        DirectUrllibTransport(monotonic=lambda: 0.0)._body(response, _request(), started_at=0.0)
        == b"complete"
    )
    assert response.read_calls == 2


def test_clean_eof_before_declared_body_is_complete_remains_a_failure() -> None:
    response = _LifecycleResponse(
        b"partial", chunk_size=7, detach_after_body=True, declared_length=20
    )

    with pytest.raises(IngestionError) as raised:
        DirectUrllibTransport(monotonic=lambda: 0.0)._body(response, _request(), started_at=0.0)

    assert raised.value.code == "SOURCE_UNAVAILABLE"
    assert "partial" not in raised.value.message


@pytest.mark.parametrize("declared_length", ["not-an-integer", -1])
def test_invalid_declared_content_length_is_rejected(declared_length: int | str) -> None:
    response = _LifecycleResponse(b"body", declared_length=declared_length)

    with pytest.raises(IngestionError) as raised:
        DirectUrllibTransport(monotonic=lambda: 0.0)._body(response, _request(), started_at=0.0)

    assert raised.value.code == "SOURCE_UNAVAILABLE"
    assert response.read_calls == 0


def test_missing_content_length_retains_bounded_eof_reading() -> None:
    response = _LifecycleResponse(b"body", chunk_size=2, include_content_length=False)

    assert (
        DirectUrllibTransport(monotonic=lambda: 0.0)._body(response, _request(), started_at=0.0)
        == b"body"
    )


def test_unknown_socket_adjustment_failure_is_not_swallowed() -> None:
    response = _LifecycleResponse(b"unread", socket=_MissingDescriptorSocket())  # type: ignore[arg-type]

    with pytest.raises(IngestionError) as raised:
        DirectUrllibTransport(monotonic=lambda: 0.0)._body(response, _request(), started_at=0.0)

    assert raised.value.code == "SOURCE_UNAVAILABLE"
    assert response.read_calls == 0


def test_total_response_deadline_remains_bounded() -> None:
    request = _request()
    response = _LifecycleResponse(b"unread")

    with pytest.raises(IngestionError) as raised:
        DirectUrllibTransport(monotonic=lambda: request.total_timeout_seconds)._body(
            response, request, started_at=0.0
        )

    assert raised.value.code == "READ_TIMEOUT"
    assert response.read_calls == 0


@pytest.mark.parametrize("response", [object(), SimpleNamespace(read="not-callable")])
def test_malformed_response_reader_is_rejected(response: object) -> None:
    with pytest.raises(IngestionError) as raised:
        DirectUrllibTransport(monotonic=lambda: 0.0)._body(response, _request(), started_at=0.0)
    assert raised.value.code == "SOURCE_UNAVAILABLE"


def test_nonbytes_response_reader_is_rejected() -> None:
    response = SimpleNamespace(read=lambda _limit: "not-bytes")
    with pytest.raises(IngestionError) as raised:
        DirectUrllibTransport(monotonic=lambda: 0.0)._body(response, _request(), started_at=0.0)
    assert raised.value.code == "SOURCE_UNAVAILABLE"


@pytest.mark.parametrize(
    ("failure", "expected_code", "retryable"),
    [
        (urllib.error.URLError(TimeoutError(_READ_FAILURE)), "CONNECT_TIMEOUT", True),
        (urllib.error.URLError(OSError(_READ_FAILURE)), "SOURCE_UNAVAILABLE", True),
        (ssl.SSLError(_READ_FAILURE), "TLS_ERROR", False),
    ],
)
def test_connect_and_tls_failures_remain_typed_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    expected_code: str,
    retryable: bool,
) -> None:
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: _Opener(failure))

    with pytest.raises(IngestionError) as raised:
        DirectUrllibTransport().send(_request(authenticated=True))

    assert raised.value.code == expected_code
    assert raised.value.retryable is retryable
    assert _READ_FAILURE not in raised.value.message
    assert _CREDENTIAL_MARKER not in raised.value.message


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (
            DirectHttpResponse(
                302,
                "application/json",
                b"redirect-private-body",
                redirect_location="https://example.invalid/",
            ),
            "REDIRECT_BLOCKED",
        ),
        (DirectHttpResponse(200, "text/html", b"content-private-body"), "CONTENT_TYPE_INVALID"),
    ],
)
def test_redirect_and_content_type_rejections_remain_closed(
    response: DirectHttpResponse, expected_code: str
) -> None:
    client = DirectFplClient(
        _attestation(),
        transport=_StaticTransport(response),
        maximum_attempts=1,
        pace_seconds=0,
    )

    with pytest.raises(IngestionError) as raised:
        client.fetch(DirectFplResource.BOOTSTRAP)

    assert raised.value.code == expected_code
    assert response.body.decode() not in raised.value.message
