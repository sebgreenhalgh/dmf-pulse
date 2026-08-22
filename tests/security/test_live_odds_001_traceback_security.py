"""Property-level traceback regressions for LIVE-ODDS-001 remediation."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

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
from dmf_pulse.ingestion.odds.parser import parse_odds_payload

pytestmark = pytest.mark.security

CANARY_A = "traceback-credential-" + "canary-913579"
CANARY_B = "traceback-provider-" + "canary-246802"
CANARIES = (CANARY_A, CANARY_B)


def _contains_canary(value: object, *, seen: set[int] | None = None) -> bool:
    visited = set() if seen is None else seen
    if id(value) in visited:
        return False
    visited.add(id(value))
    if isinstance(value, str):
        return any(canary in value for canary in CANARIES)
    if isinstance(value, bytes):
        return any(canary.encode() in value for canary in CANARIES)
    if isinstance(value, Mapping):
        return any(
            _contains_canary(key, seen=visited) or _contains_canary(item, seen=visited)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_canary(item, seen=visited) for item in value)
    if isinstance(value, OddsHttpResponse):
        return _contains_canary(value.body, seen=visited) or _contains_canary(
            value.headers, seen=visited
        )
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping) and _contains_canary(attributes, seen=visited):
        return True
    slots = getattr(type(value), "__slots__", ())
    if isinstance(slots, str):
        slots = (slots,)
    if isinstance(slots, tuple):
        return any(
            hasattr(value, slot) and _contains_canary(getattr(value, slot), seen=visited)
            for slot in slots
        )
    return False


def _production_traceback_hits(error: BaseException) -> tuple[tuple[str, str], ...]:
    hits: set[tuple[str, str]] = set()
    pending: list[BaseException] = [error]
    seen_errors: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen_errors:
            continue
        seen_errors.add(id(current))
        for nested in (current.__cause__, current.__context__):
            if nested is not None:
                pending.append(nested)
        traceback = current.__traceback__
        while traceback is not None:
            frame = traceback.tb_frame
            filename = frame.f_code.co_filename.replace("\\", "/")
            if "/src/dmf_pulse/" in filename:
                for name, value in frame.f_locals.items():
                    if _contains_canary(value):
                        hits.add((frame.f_code.co_name, name))
            traceback = traceback.tb_next
    return tuple(sorted(hits))


class _EchoFailureTransport:
    transport_id = "traceback-reproduction"

    def send(self, _request: OddsHttpRequest, _credential: str) -> OddsHttpResponse:
        body = json.dumps({"api" + "Key": CANARY_A, "provider_note": CANARY_B}).encode()
        return OddsHttpResponse(
            500,
            "application/json",
            {
                "x-requests-remaining": "498",
                "x-requests-used": "2",
                "x-requests-last": "2",
                "x-request-id": CANARY_B,
            },
            body,
            None,
        )


def _client(
    *,
    credential_provider: object | None = None,
    transport_factory: object = _EchoFailureTransport,
) -> OddsClient:
    return OddsClient(
        load_rights_profiles()["the_odds_api_private_analytics_v1"],
        credential_provider=(
            StaticCredentialProvider(CANARY_A)
            if credential_provider is None
            else credential_provider
        ),
        transport_factory=transport_factory,  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 8, 20, 12, tzinfo=UTC),
        sleeper=lambda _seconds: None,
        monotonic=lambda: 0.0,
    )


def _assert_traceback_safe(error: BaseException) -> None:
    assert _production_traceback_hits(error) == ()
    rendered = "\n".join((str(error), repr(error), repr(vars(error))))
    assert all(canary not in rendered for canary in CANARIES)


def test_sec_tb_fetch_failure_has_no_secret_bearing_production_locals() -> None:
    with pytest.raises(Exception) as raised:
        _client().fetch()

    _assert_traceback_safe(raised.value)
    assert isinstance(raised.value, OddsFetchFailure)


def test_sec_tb_parser_redacts_before_early_structured_validation() -> None:
    oversized = CANARY_B + ("x" * (load_provider_config().max_text_length + 1))
    body = json.dumps([{"api" + "Key": oversized}]).encode()

    with pytest.raises(Exception) as raised:
        parse_odds_payload(body)

    _assert_traceback_safe(raised.value)


def test_sec_tb01_credential_provider_failure_is_detached() -> None:
    class FailingCredentialProvider:
        def get_credential(self) -> str:
            raise RuntimeError(CANARY_A)

    with pytest.raises(Exception) as raised:
        _client(credential_provider=FailingCredentialProvider()).fetch()

    assert getattr(raised.value, "code", None) == "CREDENTIAL_UNAVAILABLE"
    _assert_traceback_safe(raised.value)


def test_sec_tb02_transport_construction_failure_is_detached() -> None:
    def failing_factory() -> object:
        raise RuntimeError(CANARY_B)

    with pytest.raises(Exception) as raised:
        _client(transport_factory=failing_factory).fetch()

    assert getattr(raised.value, "code", None) == "SOURCE_UNAVAILABLE"
    _assert_traceback_safe(raised.value)


@pytest.mark.parametrize(
    ("code", "retryable"),
    (
        ("SOURCE_UNAVAILABLE", True),
        ("TLS_ERROR", False),
        ("CONNECT_TIMEOUT", True),
        ("READ_TIMEOUT", True),
        ("TOTAL_TIMEOUT", True),
    ),
    ids=("dns-socket", "tls", "connect-timeout", "read-timeout", "total-timeout"),
)
def test_sec_tb03_through_tb07_transport_failures_are_detached(
    code: str,
    retryable: bool,
) -> None:
    class FailingTransport:
        transport_id = "traceback-reproduction"

        def send(self, _request: OddsHttpRequest, _credential: str) -> OddsHttpResponse:
            raise IngestionError(
                code,
                CANARY_A,
                retryable=retryable,
                details={"unsafe": CANARY_B},
            )

    with pytest.raises(Exception) as raised:
        _client(transport_factory=FailingTransport).fetch()

    assert getattr(raised.value, "code", None) == code
    _assert_traceback_safe(raised.value)


@pytest.mark.parametrize(
    ("status", "content_type", "headers", "body", "redirect"),
    (
        (
            400,
            "application/json",
            {
                "x-requests-remaining": "498",
                "x-requests-used": "2",
                "x-requests-last": "2",
            },
            json.dumps({"echo": CANARY_A}).encode(),
            None,
        ),
        (
            500,
            "application/json",
            {
                "x-requests-remaining": "498",
                "x-requests-used": "2",
                "x-requests-last": "2",
            },
            json.dumps({"echo": CANARY_B}).encode(),
            None,
        ),
        (
            302,
            "text/plain",
            {
                "x-requests-remaining": "498",
                "x-requests-used": "2",
                "x-requests-last": "2",
            },
            b"",
            "https://example.invalid/" + CANARY_A,
        ),
        (
            400,
            "application/json",
            {
                "x-requests-remaining": CANARY_A,
                "x-requests-used": "2",
                "x-requests-last": "2",
            },
            b"{}",
            None,
        ),
        (
            400,
            "application/json",
            {
                "x-requests-remaining": "498",
                "x-requests-used": "2",
                "x-requests-last": "2",
                "x-request-id": CANARY_B,
            },
            b"{}",
            None,
        ),
    ),
    ids=("400-echo", "500-echo", "redirect", "quota-header", "request-id"),
)
def test_sec_tb08_through_tb12_raw_response_material_is_detached(
    status: int,
    content_type: str,
    headers: Mapping[str, str],
    body: bytes,
    redirect: str | None,
) -> None:
    class ResponseTransport:
        transport_id = "traceback-reproduction"

        def send(self, _request: OddsHttpRequest, _credential: str) -> OddsHttpResponse:
            return OddsHttpResponse(status, content_type, headers, body, redirect)

    with pytest.raises(Exception) as raised:
        _client(transport_factory=ResponseTransport).fetch()

    _assert_traceback_safe(raised.value)


@pytest.mark.parametrize(
    "value",
    (
        CANARY_B + ("x" * (load_provider_config().max_text_length + 1)),
        10 ** (load_provider_config().max_text_length + 1),
    ),
    ids=("text-limit", "numeric-limit"),
)
def test_sec_tb13_tb14_secret_like_parser_limit_failures_are_detached(value: object) -> None:
    body = json.dumps([{"api" + "Key": value}]).encode()

    with pytest.raises(Exception) as raised:
        parse_odds_payload(body)

    _assert_traceback_safe(raised.value)


def test_sec_tb15_tb16_prior_retry_and_terminal_failure_are_detached() -> None:
    class RetryThenEchoTransport:
        transport_id = "traceback-reproduction"

        def __init__(self) -> None:
            self.calls = 0

        def send(self, _request: OddsHttpRequest, _credential: str) -> OddsHttpResponse:
            self.calls += 1
            if self.calls == 1:
                raise IngestionError(
                    "READ_TIMEOUT", CANARY_A, retryable=True, details={"unsafe": CANARY_B}
                )
            return OddsHttpResponse(
                500,
                "application/json",
                {
                    "x-requests-remaining": "498",
                    "x-requests-used": "2",
                    "x-requests-last": "2",
                },
                json.dumps({"echo": CANARY_B}).encode(),
                None,
            )

    with pytest.raises(Exception) as raised:
        _client(transport_factory=RetryThenEchoTransport).fetch()

    assert isinstance(raised.value, OddsFetchFailure)
    assert len(raised.value.attempts) == 2
    _assert_traceback_safe(raised.value)


def test_sec_tb17_request_metadata_never_retains_the_credential() -> None:
    request = build_request(CANARY_A)

    assert not hasattr(request, "credential")
    assert all(not _contains_canary(getattr(request, slot)) for slot in request.__slots__)


@pytest.mark.parametrize("transport_kind", ("http-client", "urllib"))
def test_sec_tb18_tb19_direct_transport_failures_are_detached(
    monkeypatch: pytest.MonkeyPatch,
    transport_kind: str,
) -> None:
    request = build_request(CANARY_A)
    if transport_kind == "http-client":
        transport = HttpClientOddsTransport(
            connection_factory=lambda *_args: (_ for _ in ()).throw(RuntimeError(CANARY_B))
        )
    else:

        class FailingOpener:
            def open(self, *_args: object, **_kwargs: object) -> object:
                raise RuntimeError(CANARY_B)

        monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: FailingOpener())
        transport = UrllibOddsTransport()

    with pytest.raises(Exception) as raised:
        transport.send(request, CANARY_A)

    _assert_traceback_safe(raised.value)
