"""Checkpoint 1.3A oracles for the secret-safe live Odds API transport."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.ingestion.odds.client import (
    OddsClient,
    OddsFetchFailure,
    OddsHttpRequest,
    OddsHttpResponse,
)
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.credentials import RuntimeOddsCredentialProvider
from dmf_pulse.ingestion.odds.models import ProviderFailureCode, QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.service import OddsIngestionService

pytestmark = pytest.mark.unit

CAPTURED = datetime(2026, 8, 20, 12, tzinfo=UTC)
DUMMY_RUNTIME_VALUE = "dummy-live-odds-key-1234567890"
QUOTA_HEADERS = {
    "x-requests-remaining": "499",
    "x-requests-used": "1",
    "x-requests-last": "1",
}


class _CredentialProvider:
    def __init__(self, value: str | None) -> None:
        self.value = value
        self.calls = 0

    def get_credential(self) -> str | None:
        self.calls += 1
        return self.value


class _Transport:
    def __init__(self, responses: list[OddsHttpResponse]) -> None:
        self.responses = responses
        self.requests: list[OddsHttpRequest] = []

    def send(self, request: OddsHttpRequest) -> OddsHttpResponse:
        self.requests.append(request)
        return self.responses.pop(0)


def _profile() -> RightsProfile:
    return load_rights_profiles()["the_odds_api_private_analytics_v1"]


def _client(provider: _CredentialProvider, transport: _Transport) -> OddsClient:
    return OddsClient(
        _profile(),
        credential_provider=provider,
        transport_factory=lambda: transport,
        clock=lambda: CAPTURED,
        sleeper=lambda _seconds: None,
        monotonic=lambda: 0.0,
    )


def test_live_service_defaults_to_runtime_credential_provider() -> None:
    service = OddsIngestionService()

    assert isinstance(service.credential_provider, RuntimeOddsCredentialProvider)


def test_local_quota_gate_precedes_credential_resolution_and_transport() -> None:
    provider = _CredentialProvider(DUMMY_RUNTIME_VALUE)
    transport = _Transport([])
    client = _client(provider, transport)
    exhausted = QuotaState(
        remaining=0,
        used=500,
        last_cost=1,
        observed_at=CAPTURED,
        source=QuotaSource.SYNTHETIC_FIXTURE,
    )

    with pytest.raises(IngestionError) as raised:
        client.fetch(quota=exhausted)

    assert raised.value.code == "QUOTA_EXHAUSTED"
    assert provider.calls == 0
    assert transport.requests == []
    assert DUMMY_RUNTIME_VALUE not in repr(raised.value)


@pytest.mark.parametrize("value", (None, "", "short", "contains space 1234567890"))
def test_unavailable_or_malformed_runtime_credential_is_controlled(value: str | None) -> None:
    provider = _CredentialProvider(value)
    transport = _Transport([])
    client = _client(provider, transport)

    with pytest.raises(IngestionError) as raised:
        client.fetch()

    assert raised.value.code == "CREDENTIAL_UNAVAILABLE"
    assert raised.value.details.get("transport_call_count", 0) == 0
    assert transport.requests == []
    if value:
        assert value not in repr(raised.value)


def test_valid_dummy_credential_reaches_only_transport_boundary_without_leakage(
    repository_root: Path,
) -> None:
    body = (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes()
    provider = _CredentialProvider(DUMMY_RUNTIME_VALUE)
    transport = _Transport(
        [
            OddsHttpResponse(
                status_code=200,
                content_type="application/json",
                headers=QUOTA_HEADERS,
                body=body,
            )
        ]
    )
    client = _client(provider, transport)

    fetched = client.fetch()

    assert provider.calls == 1
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.credential == DUMMY_RUNTIME_VALUE
    assert request.scheme == "https"
    assert request.host == "api.the-odds-api.com"
    assert request.path == "/v4/sports/soccer_epl/odds"
    assert "apiKey" not in request.sanitized_target
    assert DUMMY_RUNTIME_VALUE not in request.sanitized_target
    assert DUMMY_RUNTIME_VALUE not in request.request_fingerprint
    assert DUMMY_RUNTIME_VALUE not in repr(request)
    assert DUMMY_RUNTIME_VALUE not in repr(fetched)
    assert DUMMY_RUNTIME_VALUE not in repr(fetched.attempts)


@pytest.mark.parametrize(
    "location",
    (
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
        "https://unapproved.example/v4/sports/soccer_epl/odds",
        "http://api.the-odds-api.com/v4/sports/soccer_epl/odds",
        "https://api.the-odds-api.com/redirect/again/again/again",
    ),
)
def test_redirects_are_blocked_on_first_response_without_credential_forwarding(
    location: str,
) -> None:
    provider = _CredentialProvider(DUMMY_RUNTIME_VALUE)
    transport = _Transport(
        [
            OddsHttpResponse(
                status_code=302,
                content_type="text/plain",
                headers=QUOTA_HEADERS,
                body=b"",
                redirect_location=location,
            )
        ]
    )
    client = _client(provider, transport)

    with pytest.raises(OddsFetchFailure) as raised:
        client.fetch()

    assert raised.value.code == "REDIRECT_BLOCKED"
    assert raised.value.retryable is False
    assert len(transport.requests) == 1
    assert len(raised.value.attempts) == 1
    assert raised.value.attempts[0].failure_code is ProviderFailureCode.REDIRECT_BLOCKED
    assert DUMMY_RUNTIME_VALUE not in repr(raised.value)
    assert DUMMY_RUNTIME_VALUE not in repr(raised.value.attempts)
