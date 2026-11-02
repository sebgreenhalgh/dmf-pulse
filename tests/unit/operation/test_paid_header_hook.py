"""Actual header callback precedes a failed body read; no live transport/key."""

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.client import HttpClientOddsTransport, build_request
from tests.unit.ingestion.test_live_odds_001_transport import (
    CUTOFF,
    _Connection,
    _ConnectionFactory,
    _Response,
)


def test_actual_cost_headers_survive_body_read_timeout():
    response = _Response(read_error=TimeoutError("OWNED_BODY_TIMEOUT"))
    connection = _Connection(response)
    calls = []
    transport = HttpClientOddsTransport(
        connection_factory=_ConnectionFactory([connection]),
        on_response_headers=lambda status, headers: calls.append((status, dict(headers))),
    )
    with pytest.raises(IngestionError, match="read timed out"):
        transport.send(
            build_request("OWNED_HOOK_TEST_KEY_20261101", commence_from=CUTOFF),
            "OWNED_HOOK_TEST_KEY_20261101",
        )
    assert len(calls) == 1
    assert calls[0][0] == 200
    assert calls[0][1]["x-requests-last"] == "2"
    assert connection.closed == 1 and connection.connected == 1
    assert len(connection.requests) == 1


def test_callback_refusal_closes_transport_and_skips_body():
    response = _Response()
    connection = _Connection(response)

    def reject(status, headers):
        assert headers["x-requests-used"] == "2"
        raise ValueError("OWNED_POLICY_REFUSAL")

    transport = HttpClientOddsTransport(
        connection_factory=_ConnectionFactory([connection]), on_response_headers=reject
    )
    with pytest.raises(IngestionError):
        transport.send(
            build_request("OWNED_HOOK_TEST_KEY_20261101", commence_from=CUTOFF),
            "OWNED_HOOK_TEST_KEY_20261101",
        )
    assert response.read_sizes == []
    assert connection.closed == 1
