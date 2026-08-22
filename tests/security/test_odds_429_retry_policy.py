"""Frozen NRM-006 proofs for bounded, quota-aware HTTP 429 retry behavior."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.ingestion.odds.client import (
    OddsClient,
    OddsFetchFailure,
    OddsHttpRequest,
    OddsHttpResponse,
    StaticCredentialProvider,
)
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.models import ProviderFailureCode

NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)
CANARY_ROOT = Path("fixtures/odds/NRM-006")

pytestmark = pytest.mark.security


class _ScriptedClock:
    def __init__(self, values: list[datetime]) -> None:
        self._values = iter(values)
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        try:
            return next(self._values)
        except StopIteration:
            raise AssertionError("scripted UTC clock was sampled too many times") from None


class _ScriptedMonotonic:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        try:
            return next(self._values)
        except StopIteration:
            raise AssertionError("scripted monotonic clock was sampled too many times") from None


class _SequenceTransport:
    def __init__(
        self,
        responses: list[OddsHttpResponse],
        order: list[str] | None = None,
    ) -> None:
        self._responses = iter(responses)
        self.order = order
        self.calls = 0
        self.requests: list[OddsHttpRequest] = []

    def send(self, request: OddsHttpRequest, _credential: str) -> OddsHttpResponse:
        self.calls += 1
        self.requests.append(request)
        if self.order is not None:
            self.order.append(f"transport:{self.calls}")
        try:
            return next(self._responses)
        except StopIteration:
            raise AssertionError("transport was invoked beyond its frozen script") from None


def _load_json(root: Path, relative_path: Path) -> dict[str, object]:
    value = json.loads((root / relative_path).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _response(
    *,
    status: int,
    headers: Mapping[str, str],
    body: bytes = b"{}",
) -> OddsHttpResponse:
    return OddsHttpResponse(
        status_code=status,
        content_type="application/json",
        headers=headers,
        body=body,
    )


def _client(
    transport: _SequenceTransport,
    *,
    clock: Callable[[], datetime],
    sleeper: Callable[[float], None],
    monotonic: Callable[[], float],
) -> OddsClient:
    return OddsClient(
        load_rights_profiles()["the_odds_api_private_analytics_v1"],
        credential_provider=StaticCredentialProvider("synthetic-nrm006-credential"),
        transport_factory=lambda: transport,
        clock=clock,
        sleeper=sleeper,
        monotonic=monotonic,
    )


def test_frozen_429_canary_uses_one_injected_delay_then_succeeds(
    repository_root: Path,
) -> None:
    fixture = _load_json(repository_root, CANARY_ROOT / "rate_limit_retry.json")
    expected = _load_json(
        repository_root,
        CANARY_ROOT / "expected_outputs/rate_limit_retry.json",
    )
    scripted_responses = fixture["responses"]
    assert isinstance(scripted_responses, list)
    first, second = scripted_responses
    assert isinstance(first, dict) and isinstance(second, dict)
    first_headers = first["headers"]
    second_headers = second["headers"]
    assert isinstance(first_headers, dict) and isinstance(second_headers, dict)
    body = (repository_root / CANARY_ROOT / str(second["fixture"])).read_bytes()
    order: list[str] = []
    sleeper_calls: list[float] = []
    transport = _SequenceTransport(
        [
            _response(
                status=int(first["status"]),
                headers={str(key): str(value) for key, value in first_headers.items()},
            ),
            _response(
                status=int(second["status"]),
                headers={str(key): str(value) for key, value in second_headers.items()},
                body=body,
            ),
        ],
        order,
    )
    clock = _ScriptedClock([NOW] * 5)

    def record_sleep(seconds: float) -> None:
        sleeper_calls.append(seconds)
        order.append(f"sleep:{seconds:g}")

    result = _client(
        transport,
        clock=clock,
        sleeper=record_sleep,
        monotonic=_ScriptedMonotonic([0.0, 0.0, 0.0, 0.0]),
    ).fetch()

    assert result.transport_call_count == fixture["expected_transport_calls"]
    assert result.transport_call_count == expected["transport_calls"]
    assert sleeper_calls == fixture["expected_sleeper_calls_seconds"]
    assert sleeper_calls == expected["sleeper_calls_seconds"]
    assert fixture["real_sleep_allowed"] is expected["real_sleep_performed"] is False
    assert expected["final_status"] == "COMPLETE"
    assert order == ["transport:1", "sleep:2", "transport:2"]
    assert clock.calls == 5
    assert transport.requests[0].total_timeout_seconds == 30
    assert transport.requests[1].total_timeout_seconds == 28
    assert transport.requests[1].connect_timeout_seconds == 10
    assert transport.requests[1].read_timeout_seconds == 20
    assert result.body == body
    assert result.quota.remaining == 497
    assert result.quota.used == 3
    assert result.quota.last_cost == 1
    assert len(result.attempts) == 2
    first_attempt, second_attempt = result.attempts
    assert first_attempt.quota_header_state == "VALID"
    assert first_attempt.failure_code is ProviderFailureCode.HTTP_429
    assert first_attempt.requested_delay_seconds == 2
    assert first_attempt.applied_delay_seconds == 2
    assert first_attempt.attempt_outcome == "RETRY_SCHEDULED"
    assert second_attempt.quota_header_state == "VALID"
    assert second_attempt.failure_code is None
    assert second_attempt.requested_delay_seconds is None
    assert second_attempt.applied_delay_seconds is None
    assert second_attempt.attempt_outcome == "SUCCESS"


def test_partial_429_quota_headers_fail_closed_without_retry() -> None:
    sleeper_calls: list[float] = []
    transport = _SequenceTransport(
        [
            _response(
                status=429,
                headers={
                    "Retry-After": "2",
                    "x-requests-remaining": "498",
                    "x-requests-used": "2",
                },
            ),
            _response(
                status=200,
                headers={
                    "x-requests-remaining": "497",
                    "x-requests-used": "3",
                    "x-requests-last": "1",
                },
            ),
        ]
    )
    client = _client(
        transport,
        clock=_ScriptedClock([NOW] * 3),
        sleeper=sleeper_calls.append,
        monotonic=_ScriptedMonotonic([0.0, 0.0]),
    )

    with pytest.raises(OddsFetchFailure) as raised:
        client.fetch()

    assert raised.value.code == "SOURCE_UNAVAILABLE"
    assert raised.value.retryable is False
    assert client.transport_call_count == transport.calls == 1
    assert sleeper_calls == []
    assert len(raised.value.attempts) == 1
    attempt = raised.value.attempts[0]
    assert attempt.quota_header_state == "INVALID"
    assert attempt.quota is None
    assert attempt.requested_delay_seconds is None
    assert attempt.applied_delay_seconds is None
    assert attempt.attempt_outcome == "TERMINAL_FAILURE"


@pytest.mark.parametrize("status", (200, 400, 429, 503))
@pytest.mark.parametrize(
    ("headers", "expected_state"),
    (
        ({}, "ABSENT"),
        ({"x-requests-remaining": "498"}, "INVALID"),
    ),
)
def test_every_response_without_complete_quota_fails_closed_without_retry(
    status: int,
    headers: Mapping[str, str],
    expected_state: str,
) -> None:
    sleeper_calls: list[float] = []
    transport = _SequenceTransport([_response(status=status, headers=headers)])
    client = _client(
        transport,
        clock=_ScriptedClock([NOW] * 3),
        sleeper=sleeper_calls.append,
        monotonic=_ScriptedMonotonic([0.0, 0.0]),
    )

    with pytest.raises(OddsFetchFailure) as raised:
        client.fetch()

    assert raised.value.code == "SOURCE_UNAVAILABLE"
    assert raised.value.retryable is False
    assert client.transport_call_count == transport.calls == 1
    assert sleeper_calls == []
    assert len(raised.value.attempts) == 1
    attempt = raised.value.attempts[0]
    assert attempt.quota_header_state == expected_state
    assert attempt.quota is None
    assert attempt.failure_code is ProviderFailureCode.SOURCE_UNAVAILABLE
    assert attempt.attempt_outcome == "TERMINAL_FAILURE"


@pytest.mark.parametrize(
    ("retry_after", "expected_requested"),
    ((None, None), ("0", 0), ("61", 61), ("1.5", None), ("nonsense", None)),
)
def test_invalid_or_missing_retry_after_uses_one_second_default(
    retry_after: str | None,
    expected_requested: int | None,
) -> None:
    first_headers = {
        "x-requests-remaining": "498",
        "x-requests-used": "2",
        "x-requests-last": "1",
    }
    if retry_after is not None:
        first_headers["Retry-After"] = retry_after
    sleeper_calls: list[float] = []
    transport = _SequenceTransport(
        [
            _response(status=429, headers=first_headers),
            _response(
                status=200,
                headers={
                    "x-requests-remaining": "497",
                    "x-requests-used": "3",
                    "x-requests-last": "1",
                },
            ),
        ]
    )

    result = _client(
        transport,
        clock=_ScriptedClock([NOW] * 5),
        sleeper=sleeper_calls.append,
        monotonic=_ScriptedMonotonic([0.0, 0.0, 0.0, 0.0]),
    ).fetch()

    assert sleeper_calls == [1.0]
    assert result.attempts[0].requested_delay_seconds == expected_requested
    assert result.attempts[0].applied_delay_seconds == 1
    assert result.attempts[0].attempt_outcome == "RETRY_SCHEDULED"


def test_retry_is_suppressed_when_delay_would_exhaust_total_deadline() -> None:
    sleeper_calls: list[float] = []
    transport = _SequenceTransport(
        [
            _response(
                status=429,
                headers={
                    "Retry-After": "2",
                    "x-requests-remaining": "498",
                    "x-requests-used": "2",
                    "x-requests-last": "1",
                },
            )
        ]
    )
    client = _client(
        transport,
        clock=_ScriptedClock([NOW] * 3),
        sleeper=sleeper_calls.append,
        monotonic=_ScriptedMonotonic([0.0, 29.0]),
    )

    with pytest.raises(OddsFetchFailure) as raised:
        client.fetch()

    assert raised.value.code == "HTTP_429"
    assert raised.value.retryable is False
    assert client.transport_call_count == transport.calls == 1
    assert sleeper_calls == []
    attempt = raised.value.attempts[0]
    assert attempt.requested_delay_seconds == 2
    assert attempt.applied_delay_seconds is None
    assert attempt.attempt_outcome == "TERMINAL_FAILURE"


def test_retry_deadline_is_rechecked_after_injected_sleep() -> None:
    sleeper_calls: list[float] = []
    transport = _SequenceTransport(
        [
            _response(
                status=429,
                headers={
                    "Retry-After": "2",
                    "x-requests-remaining": "498",
                    "x-requests-used": "2",
                    "x-requests-last": "1",
                },
            ),
            _response(
                status=200,
                headers={
                    "x-requests-remaining": "497",
                    "x-requests-used": "3",
                    "x-requests-last": "1",
                },
            ),
        ]
    )
    client = _client(
        transport,
        clock=_ScriptedClock([NOW] * 3),
        sleeper=sleeper_calls.append,
        monotonic=_ScriptedMonotonic([0.0, 0.0, 31.0]),
    )

    with pytest.raises(OddsFetchFailure) as raised:
        client.fetch()

    assert raised.value.code == "HTTP_429"
    assert raised.value.retryable is False
    assert client.transport_call_count == transport.calls == 1
    assert sleeper_calls == [2.0]
    assert len(raised.value.attempts) == 1
    attempt = raised.value.attempts[0]
    assert attempt.requested_delay_seconds == 2
    assert attempt.applied_delay_seconds == 2
    assert attempt.attempt_outcome == "TERMINAL_FAILURE"


def test_transport_success_after_total_deadline_is_rejected() -> None:
    transport = _SequenceTransport(
        [
            _response(
                status=200,
                headers={
                    "x-requests-remaining": "498",
                    "x-requests-used": "2",
                    "x-requests-last": "1",
                },
            )
        ]
    )
    client = _client(
        transport,
        clock=_ScriptedClock([NOW] * 3),
        sleeper=lambda _seconds: None,
        monotonic=_ScriptedMonotonic([0.0, 30.0]),
    )

    with pytest.raises(OddsFetchFailure) as raised:
        client.fetch()

    assert raised.value.code == "TOTAL_TIMEOUT"
    assert raised.value.retryable is False
    assert client.transport_call_count == transport.calls == 1
    assert len(raised.value.attempts) == 1
    assert raised.value.attempts[0].failure_code is ProviderFailureCode.TOTAL_TIMEOUT
    assert raised.value.attempts[0].attempt_outcome == "TERMINAL_FAILURE"
