"""Offline proofs for the operator-initiated direct FPL boundary."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr, ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import (
    DIRECT_FPL_PROFILE_ID,
    DirectFplClient,
    DirectFplCredential,
    DirectFplCredentialProvider,
    DirectFplResource,
    DirectFplRunAttestation,
    DirectHttpRequest,
    DirectHttpResponse,
    DirectUrllibTransport,
    direct_path,
)
from dmf_pulse.ingestion.rights import load_rights_profiles

pytestmark = pytest.mark.unit


class FakeTransport:
    def __init__(self, responses: list[DirectHttpResponse]) -> None:
        self.responses = responses
        self.calls: list[DirectHttpRequest] = []

    def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
        self.calls.append(request)
        return self.responses.pop(0)


def _attestation() -> DirectFplRunAttestation:
    return DirectFplRunAttestation(attested_at=datetime(2026, 9, 1, tzinfo=UTC))


def _success() -> DirectHttpResponse:
    return DirectHttpResponse(200, "application/json", b'{"synthetic":true}')


def test_direct_profile_is_separate_and_legacy_manual_profile_is_unchanged() -> None:
    profiles = load_rights_profiles()
    direct = profiles[DIRECT_FPL_PROFILE_ID]
    manual = profiles["fpl_official_private_manual_v1"]

    assert direct.capabilities["automated_access"] == "ALLOW"
    assert direct.capabilities["raw_storage"] == "DENY"
    assert direct.capabilities["derived_storage"] == "DENY"
    assert direct.capabilities["redistribution"] == "DENY"
    assert direct.retention_seconds == 0
    assert manual.profile_version == "1.0.0"
    assert manual.capabilities["automated_access"] == "DENY"
    assert manual.capabilities["manual_import"] == "ALLOW"
    assert manual.capabilities["derived_storage"] == "UNKNOWN"
    assert manual.retention_seconds == 0
    assert manual.termination_deletion_required is True
    assert manual.terms_version == "checked-2026-07-23"
    assert manual.approved_at == datetime(2026, 7, 23, tzinfo=UTC)
    assert manual.unresolved_rights == ("persistent derived database rights require confirmation",)


@pytest.mark.parametrize(
    ("resource", "entry", "gameweek", "expected"),
    [
        (DirectFplResource.BOOTSTRAP, None, None, "/api/bootstrap-static/"),
        (DirectFplResource.FIXTURES, None, None, "/api/fixtures/"),
        (DirectFplResource.EVENT_LIVE, None, 3, "/api/event/3/live/"),
        (DirectFplResource.ENTRY, 42, None, "/api/entry/42/"),
        (DirectFplResource.HISTORY, 42, None, "/api/entry/42/history/"),
        (DirectFplResource.PICKS, 42, 2, "/api/entry/42/event/2/picks/"),
        (DirectFplResource.TRANSFERS, 42, None, "/api/entry/42/transfers/"),
        (DirectFplResource.MY_TEAM, 42, None, "/api/my-team/42/"),
    ],
)
def test_direct_path_is_closed(
    resource: DirectFplResource, entry: int | None, gameweek: int | None, expected: str
) -> None:
    assert direct_path(resource, entry_id=entry, gameweek=gameweek) == expected


def test_direct_client_is_sequential_paced_and_finitely_retries() -> None:
    transport = FakeTransport(
        [
            DirectHttpResponse(429, "application/json", b"private marker", retry_after="2"),
            DirectHttpResponse(503, "application/json", b"private marker"),
            _success(),
        ]
    )
    sleeps: list[float] = []
    client = DirectFplClient(
        _attestation(), transport=transport, sleeper=sleeps.append, pace_seconds=0.25
    )

    assert client.fetch(DirectFplResource.ENTRY, entry_id=42) == b'{"synthetic":true}'
    assert client.request_count == 3
    assert client.endpoint_classes == (DirectFplResource.ENTRY,) * 3
    assert sleeps == [2.0, 0.25, 2.0, 0.25]
    assert all(call.method == "GET" for call in transport.calls)
    assert all("Authorization" not in call.headers for call in transport.calls)
    assert all("Cookie" not in call.headers for call in transport.calls)


def test_my_team_uses_only_x_api_bearer_and_secret_is_redacted() -> None:
    marker = "synthetic-secret-never-print"
    transport = FakeTransport([_success()])
    provider = DirectFplCredentialProvider({"DMF_FPL_BEARER_TOKEN": marker})
    client = DirectFplClient(
        _attestation(), transport=transport, credential_provider=provider, sleeper=lambda _: None
    )

    client.fetch(DirectFplResource.MY_TEAM, entry_id=42)

    request = transport.calls[0]
    assert request.headers["X-API-Authorization"] == f"Bearer {marker}"
    assert "Authorization" not in request.headers
    assert "Cookie" not in request.headers
    assert marker not in repr(request)
    assert marker not in repr(provider.get())


def test_missing_token_fails_before_transport_and_does_not_fallback_to_public_picks() -> None:
    transport = FakeTransport([_success()])
    client = DirectFplClient(
        _attestation(),
        transport=transport,
        credential_provider=DirectFplCredentialProvider({}),
        sleeper=lambda _: None,
    )

    with pytest.raises(IngestionError) as caught:
        client.fetch(DirectFplResource.MY_TEAM, entry_id=42)

    assert caught.value.code == "CREDENTIAL_MISSING"
    assert caught.value.message == "DMF_FPL_BEARER_TOKEN is missing."
    assert transport.calls == []


def test_invalid_attestation_and_identifier_fail_closed() -> None:
    with pytest.raises(ValidationError):
        DirectFplRunAttestation.model_validate(
            {
                "operator_initiated": True,
                "private_use": True,
                "read_only": False,
                "non_commercial": True,
                "production_service": False,
                "accepted_contractual_risk": True,
                "attested_at": "2026-09-01T00:00:00Z",
            }
        )
    with pytest.raises(IngestionError, match="positive integer"):
        direct_path(DirectFplResource.ENTRY, entry_id=0)
    with pytest.raises(ValueError, match="invalid"):
        DirectFplCredential(source="ENVIRONMENT", bearer_token=SecretStr(" token "))


def test_request_budget_is_exact_and_error_does_not_disclose_body() -> None:
    marker = b"private-response-marker"
    transport = FakeTransport([DirectHttpResponse(503, "application/json", marker)])
    client = DirectFplClient(
        _attestation(),
        transport=transport,
        sleeper=lambda _: None,
        maximum_requests=1,
        maximum_attempts=1,
    )
    with pytest.raises(IngestionError) as caught:
        client.fetch(DirectFplResource.FIXTURES)
    assert caught.value.code == "HTTP_5XX"
    assert marker.decode() not in caught.value.message
    assert client.request_count == 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "FPL_AUTH_REQUIRED"), (403, "FPL_AUTH_REQUIRED"), (404, "HTTP_4XX")],
)
def test_terminal_http_denials_are_safe(status: int, expected: str) -> None:
    marker = b"private-response-never-disclose"
    client = DirectFplClient(
        _attestation(),
        transport=FakeTransport([DirectHttpResponse(status, "application/json", marker)]),
        sleeper=lambda _: None,
        maximum_attempts=1,
    )

    with pytest.raises(IngestionError) as caught:
        client.fetch(DirectFplResource.ENTRY, entry_id=42)

    assert caught.value.code == expected
    assert marker.decode() not in caught.value.message


def test_terminal_rate_limit_and_budget_exhaustion_are_bounded() -> None:
    transport = FakeTransport(
        [
            DirectHttpResponse(429, "application/json", b"private", retry_after="999"),
            DirectHttpResponse(429, "application/json", b"private", retry_after="999"),
        ]
    )
    sleeps: list[float] = []
    client = DirectFplClient(
        _attestation(),
        transport=transport,
        sleeper=sleeps.append,
        maximum_requests=2,
        maximum_attempts=2,
        pace_seconds=0,
    )

    with pytest.raises(IngestionError) as caught:
        client.fetch(DirectFplResource.FIXTURES)

    assert caught.value.code == "HTTP_429"
    assert client.request_count == 2
    assert sleeps == [10.0, 0]
    with pytest.raises(IngestionError) as exhausted:
        client.fetch(DirectFplResource.FIXTURES)
    assert exhausted.value.code == "REQUEST_BUDGET_EXHAUSTED"


def test_transport_timeout_is_safe_and_write_grammar_is_structurally_closed() -> None:
    class TimeoutTransport:
        def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
            del request
            raise IngestionError("CONNECT_TIMEOUT", "FPL source is unavailable", retryable=True)

    client = DirectFplClient(_attestation(), transport=TimeoutTransport(), sleeper=lambda _: None)
    with pytest.raises(IngestionError) as caught:
        client.fetch(DirectFplResource.BOOTSTRAP)
    assert caught.value.code == "CONNECT_TIMEOUT"
    assert client.request_count == 1
    assert not any(hasattr(client, method) for method in ("post", "put", "patch", "delete"))

    forged = DirectHttpRequest(
        method="POST",  # type: ignore[arg-type]
        host="fantasy.premierleague.com",
        path="/api/bootstrap-static/",
        headers={},
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        total_timeout_seconds=2,
    )
    with pytest.raises(IngestionError, match="not allowlisted"):
        DirectUrllibTransport().send(forged)
