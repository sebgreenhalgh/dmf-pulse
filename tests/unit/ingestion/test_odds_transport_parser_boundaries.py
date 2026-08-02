"""Offline transport and parser boundary oracles for ODD-005."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds import client as client_module
from dmf_pulse.ingestion.odds import parser as parser_module
from dmf_pulse.ingestion.odds.client import (
    OddsClient,
    OddsHttpResponse,
    StaticCredentialProvider,
    UrllibOddsTransport,
    _normalized_content_type,
    _response_failure,
    _validate_request,
    build_request,
)
from dmf_pulse.ingestion.odds.config import load_provider_config, load_rights_profiles
from dmf_pulse.ingestion.odds.parser import parse_odds_payload

pytestmark = pytest.mark.unit
NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)


def _fake_credential() -> str:
    repository_root = Path(__file__).resolve().parents[3]
    return (
        (repository_root / "fixtures/odds/ODD-005/security_fake_credential.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


class _Socket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)


class _Raw:
    def __init__(self, socket: _Socket) -> None:
        self._sock = socket


class _Fp:
    def __init__(self, socket: _Socket) -> None:
        self.raw = _Raw(socket)


class _ChunkResponse:
    def __init__(self, chunks: list[object], *, socket: _Socket | None = None) -> None:
        self.chunks = chunks
        if socket is not None:
            self.fp = _Fp(socket)

    def read(self, _size: int) -> object:
        value = self.chunks.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class _FailingOpener:
    def __init__(self, failure: BaseException) -> None:
        self.failure = failure
        self.calls = 0

    def open(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        raise self.failure


class _StaticTransport:
    def __init__(self, value: OddsHttpResponse | BaseException) -> None:
        self.value = value

    def send(self, _request: object) -> OddsHttpResponse:
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


def _request() -> client_module.OddsHttpRequest:
    return build_request(_fake_credential())


def test_read_body_applies_timeout_and_stops_on_empty_chunk() -> None:
    socket = _Socket()
    response = _ChunkResponse([b"abc", b""], socket=socket)
    body = UrllibOddsTransport(monotonic=lambda: 0.0)._read_body(
        response,
        _request(),
        started_at=0.0,
    )
    assert body == b"abc"
    assert socket.timeouts == [20.0, 20.0]


@pytest.mark.parametrize(
    ("response", "monotonic", "code"),
    (
        (_ChunkResponse([b"value"]), lambda: 31.0, "TOTAL_TIMEOUT"),
        (object(), lambda: 0.0, "SOURCE_UNAVAILABLE"),
        (_ChunkResponse(["not-bytes"]), lambda: 0.0, "SOURCE_UNAVAILABLE"),
        (_ChunkResponse([TimeoutError()]), lambda: 0.0, "READ_TIMEOUT"),
        (_ChunkResponse([ssl.SSLError("synthetic")]), lambda: 0.0, "TLS_ERROR"),
        (_ChunkResponse([OSError("synthetic")]), lambda: 0.0, "SOURCE_UNAVAILABLE"),
    ),
)
def test_read_body_classifies_bounded_failures(
    response: object,
    monotonic: Any,
    code: str,
) -> None:
    with pytest.raises(IngestionError) as raised:
        UrllibOddsTransport(monotonic=monotonic)._read_body(
            response,
            _request(),
            started_at=0.0,
        )
    assert raised.value.code == code


def test_read_body_stops_after_the_configured_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_provider_config().model_copy(update={"max_response_bytes": 3})
    monkeypatch.setattr(client_module, "load_provider_config", lambda: config)
    response = _ChunkResponse([b"1234"])
    assert (
        UrllibOddsTransport(monotonic=lambda: 0.0)._read_body(
            response,
            _request(),
            started_at=0.0,
        )
        == b"1234"
    )


@pytest.mark.parametrize(
    ("failure", "code"),
    (
        (TimeoutError(), "CONNECT_TIMEOUT"),
        (urllib.error.URLError(TimeoutError()), "CONNECT_TIMEOUT"),
        (urllib.error.URLError(OSError("synthetic")), "SOURCE_UNAVAILABLE"),
        (OSError("synthetic"), "SOURCE_UNAVAILABLE"),
    ),
)
def test_urllib_transport_classifies_connect_failures_without_network(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    code: str,
) -> None:
    opener = _FailingOpener(failure)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: opener)
    with pytest.raises(IngestionError) as raised:
        UrllibOddsTransport().send(_request())
    assert raised.value.code == code
    assert opener.calls == 1


def test_urllib_transport_converts_http_error_without_reading_absent_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = urllib.error.HTTPError(
        "https://invalid.example",
        429,
        "synthetic",
        {"content-type": "application/json", "x-requests-remaining": "0"},
        None,
    )
    opener = _FailingOpener(error)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: opener)
    response = UrllibOddsTransport().send(_request())
    assert response.status_code == 429
    assert response.body == b""
    assert response.content_type == "application/json"


@pytest.mark.parametrize(
    "credential",
    ("", "contains space", "x" * 513),
)
def test_request_builder_rejects_unavailable_credential_shapes(credential: str) -> None:
    with pytest.raises(IngestionError) as raised:
        build_request(credential)
    assert raised.value.code == "CREDENTIAL_UNAVAILABLE"


def test_request_validator_rejects_parameter_order_drift() -> None:
    request = _request()
    drifted = replace(
        request,
        safe_parameters=tuple(reversed(request.safe_parameters)),
    )
    with pytest.raises(IngestionError, match="parameters drifted"):
        _validate_request(drifted, load_provider_config())


@pytest.mark.parametrize("value", ("x" * 201, "application/json\nunsafe"))
def test_content_type_normalization_rejects_unsafe_metadata(value: str) -> None:
    assert _normalized_content_type(value) is None


def test_response_validation_covers_json_suffix_size_and_missing_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        _response_failure(
            OddsHttpResponse(200, "application/problem+json", {}, b"{}"),
            media_type="application/problem+json",
            quota=None,
        ).code
        == "SOURCE_UNAVAILABLE"
    )
    config = load_provider_config().model_copy(update={"max_response_bytes": 1})
    monkeypatch.setattr(client_module, "load_provider_config", lambda: config)
    assert (
        _response_failure(
            OddsHttpResponse(200, "application/json", {}, b"{}"),
            media_type="application/json",
            quota=client_module.parse_quota_headers(
                {
                    "x-requests-remaining": "1",
                    "x-requests-used": "1",
                    "x-requests-last": "1",
                },
                NOW,
            ),
        ).code
        == "PAYLOAD_TOO_LARGE"
    )


def test_parser_private_limits_cover_text_numeric_type_and_cardinality(
    repository_root: Path,
) -> None:
    assert parser_module._json_type(object()) == "object"
    with pytest.raises(IngestionError, match="text exceeds"):
        parser_module._check_text_limits({"long-key": "ok"}, 3)
    with pytest.raises(IngestionError, match="invalid Unicode"):
        parser_module._check_text_limits({"\ud800": "ok"}, 10)
    with pytest.raises(IngestionError, match="number exceeds"):
        parser_module._check_numeric_limits(10**20, 2)
    with pytest.raises(ValueError, match="finite"):
        parser_module._decimal(Decimal("NaN"), 10)
    with pytest.raises(ValueError, match="magnitude"):
        parser_module._decimal(Decimal("123456"), 3)

    parsed = parse_odds_payload(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes()
    )
    config = load_provider_config()
    for field in (
        "max_events",
        "max_bookmakers_per_event",
        "max_markets_per_bookmaker",
        "max_outcomes_per_market",
    ):
        with pytest.raises(IngestionError) as raised:
            parser_module._validate_limits(
                parsed.events,
                config.model_copy(update={field: 0}),
            )
        assert raised.value.code == "PAYLOAD_TOO_LARGE"


def test_parser_rejects_body_before_decode_when_byte_limit_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_provider_config().model_copy(update={"max_response_bytes": 1})
    monkeypatch.setattr(parser_module, "load_provider_config", lambda: config)
    with pytest.raises(IngestionError) as raised:
        parse_odds_payload(b"[]")
    assert raised.value.code == "PAYLOAD_TOO_LARGE"


def test_transport_metadata_and_construction_fail_closed_without_network() -> None:
    assert UrllibOddsTransport._safe_headers(object()) == {}
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    client = OddsClient(
        profile,
        credential_provider=StaticCredentialProvider(_fake_credential()),
        transport_factory=lambda: (_ for _ in ()).throw(RuntimeError("synthetic")),
        clock=lambda: NOW,
    )
    with pytest.raises(IngestionError) as raised:
        client.fetch()
    assert raised.value.code == "SOURCE_UNAVAILABLE"
    assert client.transport_call_count == 0


@pytest.mark.parametrize("failure_phase", ("start", "failed-finish", "success-finish"))
def test_client_rejects_naive_clock_values_at_every_transport_phase(
    failure_phase: str,
) -> None:
    naive = datetime(2026, 8, 20, 12)
    if failure_phase == "start":
        clock_values = iter((NOW, naive))
        transport: _StaticTransport = _StaticTransport(
            OddsHttpResponse(200, "application/json", {}, b"[]")
        )
    elif failure_phase == "failed-finish":
        clock_values = iter((NOW, NOW, naive))
        transport = _StaticTransport(IngestionError("READ_TIMEOUT", "synthetic", retryable=True))
    else:
        clock_values = iter((NOW, NOW, naive))
        transport = _StaticTransport(
            OddsHttpResponse(
                200,
                "application/json",
                {
                    "x-requests-remaining": "499",
                    "x-requests-used": "1",
                    "x-requests-last": "1",
                },
                b"[]",
            )
        )
    client = OddsClient(
        load_rights_profiles()["the_odds_api_private_analytics_v1"],
        credential_provider=StaticCredentialProvider(_fake_credential()),
        transport_factory=lambda: transport,
        clock=lambda: next(clock_values),
    )
    with pytest.raises(IngestionError) as raised:
        client.fetch()
    assert raised.value.code == "INTERNAL_INVARIANT"
