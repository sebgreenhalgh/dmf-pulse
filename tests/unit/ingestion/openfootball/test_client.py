from __future__ import annotations

import ssl
from dataclasses import replace

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.client import (
    HttpClientOpenFootballTransport,
    OpenFootballHttpRequest,
    OpenFootballHttpResponse,
    build_request,
    fetch_resource,
)
from dmf_pulse.ingestion.openfootball.config import load_provider_config


class RecordingTransport:
    transport_id = "recording"

    def __init__(self) -> None:
        self.request: OpenFootballHttpRequest | None = None

    def send(self, request: OpenFootballHttpRequest) -> OpenFootballHttpResponse:
        self.request = request
        return OpenFootballHttpResponse(
            status_code=200,
            content_type="text/plain",
            headers={},
            body=b"safe",
        )


class _Socket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)


class _HttpResponse:
    def __init__(self, *, status: int, body: bytes, headers: list[tuple[str, str]]) -> None:
        self.status = status
        self._body = body
        self._headers = headers

    def getheaders(self) -> list[tuple[str, str]]:
        return self._headers

    def read(self, amount: int) -> bytes:
        chunk, self._body = self._body[:amount], self._body[amount:]
        return chunk


class _Connection:
    def __init__(self, response: _HttpResponse) -> None:
        self.response = response
        self.sock = _Socket()
        self.request_args: tuple[object, ...] | None = None
        self.closed = False

    def request(self, *args: object, **kwargs: object) -> None:
        self.request_args = (*args, kwargs)

    def getresponse(self) -> _HttpResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


@pytest.mark.security
def test_request_is_https_commit_pinned_query_free_and_bounded() -> None:
    config = load_provider_config()

    request = build_request(config, config.licence.path)

    assert request.method == "GET"
    assert request.scheme == "https"
    assert request.host == "raw.githubusercontent.com"
    assert request.path == f"/{config.repository}/{config.commit_sha}/LICENSE.md"
    assert "?" not in request.path
    assert request.max_response_bytes == 131072
    assert request.total_timeout_seconds == 30


@pytest.mark.security
def test_fetch_refuses_non_allowlisted_path_without_a_call() -> None:
    config = load_provider_config()
    transport = RecordingTransport()

    with pytest.raises(IngestionError, match="allowlisted"):
        fetch_resource(config=config, resource_path="master/en.1.json", transport=transport)

    assert transport.request is None


@pytest.mark.unit
def test_response_repr_never_discloses_body() -> None:
    response = OpenFootballHttpResponse(
        status_code=200,
        content_type="application/json",
        headers={"x-source-metadata": "private-value"},
        body=b"sensitive raw body",
    )

    rendered = repr(response)

    assert "sensitive" not in rendered
    assert "x-source-metadata" not in rendered
    assert "body_size=18" in rendered


@pytest.mark.security
def test_stdlib_transport_refuses_redirect_without_reading_body() -> None:
    response = _HttpResponse(
        status=302,
        body=b"redirect body",
        headers=[("location", "https://example.invalid/elsewhere")],
    )
    connection = _Connection(response)
    transport = HttpClientOpenFootballTransport(
        connection_factory=lambda *args, **kwargs: connection,
        monotonic=lambda: 0.0,
    )
    request = build_request(load_provider_config(), "LICENSE.md")

    with pytest.raises(IngestionError) as caught:
        transport.send(request)

    assert caught.value.code == "REDIRECT_BLOCKED"
    assert response._body == b"redirect body"
    assert connection.closed is True


@pytest.mark.security
def test_stdlib_transport_refuses_declared_oversize_before_body_read() -> None:
    config = load_provider_config()
    response = _HttpResponse(
        status=200,
        body=b"not read",
        headers=[
            ("content-type", "application/json"),
            ("content-length", str(config.max_response_bytes + 1)),
        ],
    )
    connection = _Connection(response)
    transport = HttpClientOpenFootballTransport(
        connection_factory=lambda *args, **kwargs: connection,
        monotonic=lambda: 0.0,
    )

    with pytest.raises(IngestionError) as caught:
        transport.send(build_request(config, "LICENSE.md"))

    assert caught.value.code == "PAYLOAD_TOO_LARGE"
    assert response._body == b"not read"
    assert connection.closed is True


def _transport(response: _HttpResponse) -> tuple[HttpClientOpenFootballTransport, _Connection]:
    connection = _Connection(response)
    return (
        HttpClientOpenFootballTransport(
            connection_factory=lambda *args, **kwargs: connection,
            monotonic=lambda: 0.0,
        ),
        connection,
    )


@pytest.mark.parametrize(("status", "code"), [(404, "HTTP_4XX"), (500, "HTTP_5XX")])
def test_stdlib_transport_maps_unsuccessful_status(status: int, code: str) -> None:
    transport, connection = _transport(_HttpResponse(status=status, body=b"", headers=[]))

    with pytest.raises(IngestionError) as caught:
        transport.send(build_request(load_provider_config(), "LICENSE.md"))

    assert caught.value.code == code
    assert connection.closed is True


@pytest.mark.parametrize(
    ("headers", "body", "code"),
    [
        ([("content-type", "text/html")], b"x", "CONTENT_TYPE_INVALID"),
        (
            [("content-type", "application/json"), ("content-length", "not-an-int")],
            b"x",
            "SOURCE_UNAVAILABLE",
        ),
        (
            [("content-type", "application/json"), ("content-length", "10")],
            b"short",
            "SOURCE_UNAVAILABLE",
        ),
    ],
)
def test_stdlib_transport_refuses_invalid_response_envelope(
    headers: list[tuple[str, str]], body: bytes, code: str
) -> None:
    transport, _ = _transport(_HttpResponse(status=200, body=body, headers=headers))

    with pytest.raises(IngestionError) as caught:
        transport.send(build_request(load_provider_config(), "LICENSE.md"))

    assert caught.value.code == code


def test_stdlib_transport_returns_bounded_immutable_response() -> None:
    body = b"approved"
    transport, connection = _transport(
        _HttpResponse(
            status=200,
            body=body,
            headers=[
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ],
        )
    )

    result = transport.send(build_request(load_provider_config(), "LICENSE.md"))

    assert result.body == body
    assert result.headers["content-type"] == "application/json; charset=utf-8"
    assert connection.request_args is not None
    assert connection.sock.timeouts == [20.0, 20.0]
    with pytest.raises(AttributeError):
        result.status_code = 500


def test_stdlib_transport_enforces_streamed_size_limit() -> None:
    config = load_provider_config()
    body = b"x" * (config.max_response_bytes + 1)
    transport, _ = _transport(
        _HttpResponse(status=200, body=body, headers=[("content-type", "application/json")])
    )

    with pytest.raises(IngestionError) as caught:
        transport.send(build_request(config, "LICENSE.md"))

    assert caught.value.code == "PAYLOAD_TOO_LARGE"


def test_stdlib_transport_enforces_total_deadline() -> None:
    values = iter((0.0, 31.0))
    response = _HttpResponse(
        status=200,
        body=b"x",
        headers=[("content-type", "application/json")],
    )
    connection = _Connection(response)
    transport = HttpClientOpenFootballTransport(
        connection_factory=lambda *args, **kwargs: connection,
        monotonic=lambda: next(values),
    )

    with pytest.raises(IngestionError) as caught:
        transport.send(build_request(load_provider_config(), "LICENSE.md"))

    assert caught.value.code == "READ_TIMEOUT"


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (TimeoutError(), "CONNECT_TIMEOUT"),
        (ssl.SSLError(), "TLS_ERROR"),
        (OSError(), "SOURCE_UNAVAILABLE"),
    ],
)
def test_stdlib_transport_maps_connection_failures(failure: Exception, code: str) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise failure

    transport = HttpClientOpenFootballTransport(connection_factory=fail)

    with pytest.raises(IngestionError) as caught:
        transport.send(build_request(load_provider_config(), "LICENSE.md"))

    assert caught.value.code == code


@pytest.mark.parametrize(
    "update",
    [
        {"scheme": "http"},
        {"method": "POST"},
        {"path": "relative"},
    ],
)
def test_stdlib_transport_refuses_invalid_request_before_connection(
    update: dict[str, object],
) -> None:
    request = replace(build_request(load_provider_config(), "LICENSE.md"), **update)
    transport = HttpClientOpenFootballTransport(
        connection_factory=lambda *args, **kwargs: pytest.fail("connection attempted")
    )

    with pytest.raises(IngestionError) as caught:
        transport.send(request)

    assert caught.value.code == "INTERNAL_INVARIANT"


def test_request_sanitized_target_contains_no_query_or_credentials() -> None:
    request = build_request(load_provider_config(), "LICENSE.md")

    assert request.sanitized_target.startswith("https://raw.githubusercontent.com/")
    assert "?" not in request.sanitized_target
    assert "@" not in request.sanitized_target
