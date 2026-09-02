"""Actual accepted Odds acquisition wrapper tests for one-command assembly."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.client import OddsFetchResult, OddsRetrievalAttempt
from dmf_pulse.ingestion.odds.credentials import EnvironmentOddsCredentialProvider
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.transient import CurrentOddsTransientService

pytestmark = pytest.mark.unit

STARTED = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
RECEIVED = datetime(2026, 8, 20, 12, 1, tzinfo=UTC)
USABLE = datetime(2026, 8, 20, 12, 2, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 20, 12, 5, tzinfo=UTC)
TARGET = (
    "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?regions=uk&"
    "markets=h2h%2Ctotals&oddsFormat=decimal&dateFormat=iso&"
    "commenceTimeFrom=2026-08-20T12%3A05%3A00Z&"
    "commenceTimeTo=2026-08-23T00%3A00%3A00Z"
)


def _result(body: bytes) -> OddsFetchResult:
    quota = QuotaState(
        remaining=498,
        used=2,
        last_cost=2,
        observed_at=RECEIVED,
        source=QuotaSource.RESPONSE_HEADERS,
    )
    attempt = OddsRetrievalAttempt(
        attempt_number=1,
        request_started_at=STARTED,
        received_at=RECEIVED,
        request_fingerprint="1" * 64,
        sanitized_target=TARGET,
        transport_id="injected",
        http_status=200,
        content_type="application/json",
        body_sha256="2" * 64,
        body_size=len(body),
        body_capture_state="COMPLETE",
        captured_prefix_sha256=None,
        captured_prefix_size=None,
        quota_header_state="VALID",
        quota=quota,
        provider_request_id_sha256="3" * 64,
        failure_code=None,
        requested_delay_seconds=None,
        applied_delay_seconds=None,
        attempt_outcome="SUCCESS",
    )
    return OddsFetchResult(
        body=body,
        quota=quota,
        request_fingerprint="1" * 64,
        sanitized_target=TARGET,
        transport_call_count=1,
        transport_id="injected",
        provider_request_id_sha256="3" * 64,
        attempts=(attempt,),
    )


def test_transient_service_invokes_existing_client_parser_and_current_builder(
    repository_root: Path,
) -> None:
    fetched = _result((repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes())
    marker = "synthetic-key-1234"
    ranges: list[tuple[datetime, datetime]] = []

    class Client:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def fetch(self, *, commence_from: datetime, commence_to: datetime) -> OddsFetchResult:
            ranges.append((commence_from, commence_to))
            return fetched

    service = CurrentOddsTransientService(
        credential_provider=EnvironmentOddsCredentialProvider(
            environment={"THE_ODDS_API_KEY": marker}
        ),
        client_factory=Client,
        clock=lambda: USABLE,
    )
    result = service.acquire(
        information_cutoff=CUTOFF,
        commence_to=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert ranges == [(CUTOFF, datetime(2026, 8, 23, tzinfo=UTC))]
    assert result.provenance.transport_call_count == 1
    assert "commenceTimeTo" in result.provenance.sanitized_target
    assert result.provenance.raw_payload_retained is False
    assert result.rights.raw_payload_retained is False
    assert result.temporal.information_cutoff == CUTOFF
    assert result.temporal.usable_at == USABLE
    assert result.events[0].provider_event_id == "todapi-event-001"


def test_transient_service_fails_before_client_when_key_is_missing() -> None:
    called = False

    class Client:
        def __init__(self, *args, **kwargs) -> None:
            nonlocal called
            del args, kwargs
            called = True

    service = CurrentOddsTransientService(
        credential_provider=EnvironmentOddsCredentialProvider(environment={}),
        client_factory=Client,
        clock=lambda: USABLE,
    )
    with pytest.raises(IngestionError) as caught:
        service.acquire(
            information_cutoff=CUTOFF,
            commence_to=datetime(2026, 8, 23, tzinfo=UTC),
        )
    assert caught.value.code == "CREDENTIAL_UNAVAILABLE"
    assert called is False
