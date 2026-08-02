"""Offline request-boundary tests for the FPL client."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from email.message import Message
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl import client as client_module
from dmf_pulse.ingestion.fpl.client import (
    APPROVED_HOST,
    FplClient,
    HttpRequest,
    HttpResponse,
    UrllibTransport,
    build_request,
)
from dmf_pulse.ingestion.fpl.parser import MAX_PAYLOAD_BYTES, FplResource
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability, RightsProfile
from dmf_pulse.ingestion.rights import load_rights_profiles

pytestmark = pytest.mark.unit


class FakeTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.calls: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.calls.append(request)
        return self.response


class FakeHeaders(Message):
    def __init__(self, content_type: str, *, location: str | None = None) -> None:
        super().__init__()
        self["Content-Type"] = content_type
        if location is not None:
            self["Location"] = location


class FakeUrlResponse:
    def __init__(self, status: int, content_type: str, body: bytes) -> None:
        self.status = status
        self.headers = FakeHeaders(content_type)
        self.body = body
        self.offset = 0
        self.read_limits: list[int] = []

    def __enter__(self) -> FakeUrlResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        self.read_limits.append(limit)
        chunk = self.body[self.offset : self.offset + limit]
        self.offset += len(chunk)
        return chunk


class FakeOpener:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def open(self, request: urllib.request.Request, *, timeout: float) -> FakeUrlResponse:
        self.calls.append((request, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        assert isinstance(self.outcome, FakeUrlResponse)
        return self.outcome


class FailingReadResponse(FakeUrlResponse):
    def read(self, limit: int) -> bytes:
        del limit
        raise ConnectionResetError("synthetic body-read failure")


def _profiles(root: Path) -> dict[str, RightsProfile]:
    return load_rights_profiles(root / "config" / "rights" / "fpl_profiles.json")


def _automated_profile(root: Path) -> RightsProfile:
    profile = _profiles(root)["synthetic_test_v1"]
    capabilities = dict(profile.capabilities)
    capabilities[RightsCapability.AUTOMATED_ACCESS] = CapabilityValue.ALLOW
    return profile.model_copy(update={"capabilities": capabilities})


def _client(repository_root: Path, response: HttpResponse) -> tuple[FplClient, FakeTransport]:
    transport = FakeTransport(response)
    return FplClient(_automated_profile(repository_root), lambda: transport), transport


def test_build_request_is_fixed_allowlisted_and_secret_free() -> None:
    bootstrap = build_request(FplResource.BOOTSTRAP)
    fixtures = build_request(FplResource.FIXTURES)
    assert bootstrap == HttpRequest(
        method="GET",
        host="fantasy.premierleague.com",
        path="/api/bootstrap-static/",
        headers={"Accept": "application/json", "User-Agent": "dmf-pulse-private/0.2.0"},
        connect_timeout_seconds=3.0,
        read_timeout_seconds=10.0,
        total_timeout_seconds=15.0,
    )
    assert fixtures.path == "/api/fixtures/"
    assert "?" not in fixtures.path
    assert bootstrap.host == APPROVED_HOST
    assert "Authorization" not in bootstrap.headers
    assert "Cookie" not in bootstrap.headers


def test_rights_denial_occurs_before_transport_construction(repository_root: Path) -> None:
    profile = _profiles(repository_root)["fpl_official_private_manual_v1"]
    construction_count = 0

    def forbidden_factory() -> FakeTransport:
        nonlocal construction_count
        construction_count += 1
        raise AssertionError("transport must not be constructed")

    with pytest.raises(IngestionError) as raised:
        FplClient(profile, forbidden_factory).fetch(FplResource.BOOTSTRAP)
    assert raised.value.code == "RIGHTS_BLOCKED"
    assert raised.value.exit_code == 4
    assert raised.value.details["transport_call_count"] == 0
    assert construction_count == 0


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        "application/json; charset=utf-8",
        "application/problem+json",
        "application/vnd.fpl+json",
    ],
)
def test_json_compatible_success_is_returned_verbatim(
    repository_root: Path, content_type: str
) -> None:
    body = b'{"safe":"synthetic"}'
    client, transport = _client(repository_root, HttpResponse(200, content_type, body))
    assert client.fetch(FplResource.BOOTSTRAP) == body
    assert len(transport.calls) == 1
    assert transport.calls[0] == build_request(FplResource.BOOTSTRAP)


@pytest.mark.parametrize(
    ("response", "code", "retryable"),
    [
        (
            HttpResponse(302, "application/json", b"", "https://example.invalid"),
            "REDIRECT_BLOCKED",
            False,
        ),
        (HttpResponse(304, "application/json", b""), "REDIRECT_BLOCKED", False),
        (HttpResponse(429, "application/json", b""), "HTTP_429", True),
        (HttpResponse(404, "application/json", b""), "HTTP_4XX", False),
        (HttpResponse(503, "application/json", b""), "HTTP_5XX", True),
        (HttpResponse(204, "application/json", b""), "SOURCE_UNAVAILABLE", False),
        (HttpResponse(200, "text/html", b"<html>synthetic</html>"), "CONTENT_TYPE_INVALID", False),
        (
            HttpResponse(200, "application/json", b"x" * (MAX_PAYLOAD_BYTES + 1)),
            "PAYLOAD_TOO_LARGE",
            False,
        ),
    ],
)
def test_client_maps_failures_without_exposing_bodies(
    repository_root: Path,
    response: HttpResponse,
    code: str,
    retryable: bool,
) -> None:
    client, transport = _client(repository_root, response)
    with pytest.raises(IngestionError) as raised:
        client.fetch(FplResource.FIXTURES)
    error = raised.value
    assert error.code == code
    assert error.retryable is retryable
    assert len(transport.calls) == 1
    body_marker = response.body[:20].decode("utf-8", errors="ignore")
    if body_marker:
        assert body_marker not in error.message


def test_transport_rejects_nonallowlisted_requests_without_network() -> None:
    request = HttpRequest(
        method="POST",
        host="example.invalid",
        path="/api/bootstrap-static/",
        headers={},
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        total_timeout_seconds=2,
    )
    with pytest.raises(IngestionError) as raised:
        UrllibTransport().send(request)
    assert raised.value.code == "INTERNAL_INVARIANT"


@pytest.mark.parametrize(
    "path",
    (
        "/api/entry/1/",
        "@attacker.invalid/api/bootstrap-static/",
        "/api/bootstrap-static/?" + "to" + "ken=synthetic",
        "/api/bootstrap-static/#fragment",
    ),
)
def test_transport_rejects_every_nonfrozen_path_before_opener_construction(
    path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *_handlers: pytest.fail("opener must not be constructed"),
    )
    request = HttpRequest(
        method="GET",
        host=APPROVED_HOST,
        path=path,
        headers={},
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        total_timeout_seconds=2,
    )

    with pytest.raises(IngestionError) as caught:
        UrllibTransport().send(request)

    assert caught.value.code == "INTERNAL_INVARIANT"


def test_redirect_handler_never_constructs_a_followup_request() -> None:
    handler = client_module._NoRedirect()
    assert (
        handler.redirect_request(
            urllib.request.Request("https://fantasy.premierleague.com/api/fixtures/"),
            object(),
            302,
            "Found",
            object(),
            "https://example.invalid/",
        )
        is None
    )


def test_urllib_transport_builds_one_bounded_tls_url_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeUrlResponse(200, "application/json", b'{"synthetic":true}')
    opener = FakeOpener(response)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: opener)

    request = build_request(FplResource.BOOTSTRAP)
    result = UrllibTransport().send(request)

    assert result == HttpResponse(200, "application/json", b'{"synthetic":true}')
    assert len(opener.calls) == 1
    outbound, timeout = opener.calls[0]
    assert outbound.full_url == "https://fantasy.premierleague.com/api/bootstrap-static/"
    assert outbound.method == "GET"
    assert timeout == 3.0
    assert request.read_timeout_seconds == 10.0
    assert request.total_timeout_seconds == 15.0
    assert response.read_limits
    assert max(response.read_limits) <= 64 * 1024


def test_urllib_transport_enforces_one_total_monotonic_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeUrlResponse(200, "application/json", b"synthetic")
    opener = FakeOpener(response)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: opener)
    times = iter((0.0, 0.0, 0.6, 1.1))
    request = HttpRequest(
        method="GET",
        host=APPROVED_HOST,
        path="/api/bootstrap-static/",
        headers={},
        connect_timeout_seconds=0.2,
        read_timeout_seconds=0.2,
        total_timeout_seconds=1.0,
    )

    with pytest.raises(IngestionError) as caught:
        UrllibTransport(monotonic=lambda: next(times)).send(request)

    assert caught.value.code == "READ_TIMEOUT"
    assert caught.value.retryable is True


@pytest.mark.parametrize(
    ("status", "headers", "body", "expected_type", "expected_location"),
    [
        (
            302,
            FakeHeaders("text/plain", location="https://example.invalid"),
            b"marker",
            "text/plain",
            "https://example.invalid",
        ),
        (404, None, b"", "", None),
    ],
)
def test_urllib_transport_returns_http_errors_as_bounded_responses(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    headers: Message | None,
    body: bytes,
    expected_type: str,
    expected_location: str | None,
) -> None:
    error = urllib.error.HTTPError(
        "https://fantasy.premierleague.com/api/fixtures/",
        status,
        "synthetic",
        headers,
        BytesIO(body) if body else None,
    )
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: FakeOpener(error))
    response = UrllibTransport().send(build_request(FplResource.FIXTURES))
    assert response.status_code == status
    assert response.content_type == expected_type
    assert response.body == body
    assert response.redirect_location == expected_location


@pytest.mark.parametrize(
    ("failure", "code", "retryable"),
    [
        (TimeoutError("synthetic HTTP error-body timeout"), "READ_TIMEOUT", True),
        (ConnectionResetError("synthetic HTTP error-body reset"), "SOURCE_UNAVAILABLE", True),
    ],
)
def test_urllib_transport_types_http_error_body_read_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    code: str,
    retryable: bool,
) -> None:
    error = urllib.error.HTTPError(
        "https://fantasy.premierleague.com/api/fixtures/",
        503,
        "synthetic",
        FakeHeaders("application/json"),
        BytesIO(b"bounded error body"),
    )
    transport = UrllibTransport()

    def fail_read(*_args: object, **_kwargs: object) -> bytes:
        raise failure

    monkeypatch.setattr(transport, "_read_bounded", fail_read)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: FakeOpener(error))
    with pytest.raises(IngestionError) as raised:
        transport.send(build_request(FplResource.FIXTURES))
    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert "synthetic HTTP error-body" not in raised.value.message


@pytest.mark.parametrize(
    ("exception", "code", "retryable"),
    [
        (TimeoutError("synthetic"), "READ_TIMEOUT", True),
        (ssl.SSLError("synthetic"), "TLS_ERROR", False),
        (urllib.error.URLError(TimeoutError("synthetic")), "CONNECT_TIMEOUT", True),
        (urllib.error.URLError(OSError("synthetic")), "SOURCE_UNAVAILABLE", True),
    ],
)
def test_urllib_transport_maps_local_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
    exception: BaseException,
    code: str,
    retryable: bool,
) -> None:
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: FakeOpener(exception))
    with pytest.raises(IngestionError) as raised:
        UrllibTransport().send(build_request(FplResource.FIXTURES))
    assert raised.value.code == code
    assert raised.value.retryable is retryable


def test_urllib_transport_maps_stream_read_failures_without_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FailingReadResponse(200, "application/json", b"")
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *_handlers: FakeOpener(response),
    )
    with pytest.raises(IngestionError) as raised:
        UrllibTransport().send(build_request(FplResource.BOOTSTRAP))
    assert raised.value.code == "SOURCE_UNAVAILABLE"
    assert raised.value.retryable is True
    assert "synthetic body-read failure" not in raised.value.message


def test_fake_transport_response_is_not_implicitly_parsed(repository_root: Path) -> None:
    malformed = b"{not-json"
    client, _transport = _client(repository_root, HttpResponse(200, "application/json", malformed))
    assert client.fetch(FplResource.BOOTSTRAP) == malformed
    with pytest.raises(json.JSONDecodeError):
        json.loads(malformed)


def test_bounded_reader_rejects_missing_and_nonbytes_readers() -> None:
    request = build_request(FplResource.BOOTSTRAP)
    transport = UrllibTransport(monotonic=lambda: 0.0)
    with pytest.raises(IngestionError, match="response is invalid"):
        transport._read_bounded(object(), request, started_at=0.0)

    class NonBytesResponse:
        def read(self, _limit: int) -> str:
            return "not-bytes"

    with pytest.raises(IngestionError, match="response is invalid"):
        transport._read_bounded(NonBytesResponse(), request, started_at=0.0)


def test_bounded_reader_enforces_post_read_deadline_and_size_loop_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = build_request(FplResource.BOOTSTRAP)
    times = iter((0.0, request.total_timeout_seconds))
    with pytest.raises(TimeoutError, match="deadline"):
        UrllibTransport(monotonic=lambda: next(times))._read_bounded(
            FakeUrlResponse(200, "application/json", b"x"),
            request,
            started_at=0.0,
        )

    config = client_module.load_provider_config().model_copy(update={"max_response_bytes": 0})
    monkeypatch.setattr(client_module, "load_provider_config", lambda: config)
    assert (
        UrllibTransport(monotonic=lambda: 0.0)._read_bounded(
            FakeUrlResponse(200, "application/json", b"x"),
            request,
            started_at=0.0,
        )
        == b"x"
    )


def test_transport_rechecks_the_rendered_url_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urllib.parse,
        "urlsplit",
        lambda _url: SimpleNamespace(
            scheme="https",
            hostname="different.invalid",
            path="/api/bootstrap-static/",
            username=None,
            password=None,
            query="",
            fragment="",
        ),
    )
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *_handlers: pytest.fail("opener must not be constructed"),
    )
    with pytest.raises(IngestionError, match="URL is not allowlisted"):
        UrllibTransport().send(build_request(FplResource.BOOTSTRAP))
