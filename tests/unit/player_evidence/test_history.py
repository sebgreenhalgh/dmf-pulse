"""Offline parser and fail-closed future-capture tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.history import (
    ApprovedCaptureRequest,
    HistoryHttpResponse,
    bind_posterior_to_deletion_manifest,
    capture_approved_history,
    history_past_schema_fingerprint,
    parse_history_past,
)
from dmf_pulse.player_evidence.models import RetentionMode
from tests.unit.player_evidence.support import NOW, approval, catalogue


def _payload(*, extra: bool = False, current: bool = False) -> dict[str, object]:
    row: dict[str, object] = {
        "season_name": "2026/27" if current else "2025/26",
        "minutes": 900,
        "goals_scored": 4,
        "assists": 2,
        "yellow_cards": 3,
        "red_cards": 0,
        "saves": 20,
    }
    if extra:
        row["unknown_diagnostic"] = 1
    return {"history_past": [row]}


def test_parser_accepts_allowed_fields_and_excludes_current_season() -> None:
    parsed = parse_history_past(_payload(), current_season="2026/27", is_goalkeeper=True)
    assert parsed.seasons[0].season == "2025/26"
    current = parse_history_past(
        _payload(current=True), current_season="2026/27", is_goalkeeper=False
    )
    assert current.seasons == ()
    unknown = parse_history_past(
        _payload(extra=True), current_season="2026/27", is_goalkeeper=False
    )
    assert unknown.unknown_fields == ("unknown_diagnostic",)
    assert (
        parse_history_past(
            {"history_past": []}, current_season="2026/27", is_goalkeeper=False
        ).seasons
        == ()
    )


@pytest.mark.parametrize(
    "payload",
    (
        {"history_past": [{"season_name": "2025/26"}]},
        {"history_past": [{**_payload()["history_past"][0], "minutes": "900"}]},
        {"history_past": [{**_payload()["history_past"][0], "season_name": "2028/29"}]},
        {"history_past": [{**_payload()["history_past"][0], "season_name": "not-a-season"}]},
    ),
)
def test_parser_rejects_malformed_or_future_history(payload: dict[str, object]) -> None:
    with pytest.raises(IngestionError):
        parse_history_past(payload, current_season="2026/27", is_goalkeeper=False)


class _NeverTransport:
    calls = 0

    def get(self, url: str) -> HistoryHttpResponse:
        del url
        self.calls += 1
        raise AssertionError("transport must not be called")


class _ResponseTransport:
    def __init__(self, response: HistoryHttpResponse) -> None:
        self.response = response
        self.calls = 0

    def get(self, url: str) -> HistoryHttpResponse:
        assert url.startswith("https://fantasy.premierleague.com/api/element-summary/")
        self.calls += 1
        return self.response


def _request(
    *, expected_hash: str | None = None, fingerprint: str | None = None
) -> ApprovedCaptureRequest:
    payload = _payload()
    schema = fingerprint or history_past_schema_fingerprint(payload["history_past"])
    accepted = approval(schema_fingerprint=schema)
    return ApprovedCaptureRequest(
        approval=accepted,
        expected_approval_sha256=expected_hash or accepted.approval_sha256,
        catalogue=catalogue(),
        information_cutoff=NOW,
        maximum_player_count=1,
        terms_fingerprint=accepted.terms_fingerprint,
        retention_mode=RetentionMode.POSTERIOR_ONLY,
    )


def test_rights_hash_mismatch_blocks_before_any_network() -> None:
    request = _request(expected_hash="0" * 64)
    transport = _NeverTransport()
    with pytest.raises(IngestionError, match="rights approval hash"):
        capture_approved_history(request, transport=transport, clock=lambda: NOW)
    assert transport.calls == 0


def test_terms_drift_and_request_bound_block_before_any_network() -> None:
    accepted = approval(
        schema_fingerprint=history_past_schema_fingerprint(_payload()["history_past"])
    )
    transport = _NeverTransport()
    for request in (
        ApprovedCaptureRequest(
            approval=accepted,
            expected_approval_sha256=accepted.approval_sha256,
            catalogue=catalogue(),
            information_cutoff=NOW,
            maximum_player_count=1,
            terms_fingerprint="d" * 64,
        ),
        ApprovedCaptureRequest(
            approval=accepted,
            expected_approval_sha256=accepted.approval_sha256,
            catalogue=catalogue(),
            information_cutoff=NOW,
            maximum_player_count=len(catalogue().players) + 1,
            terms_fingerprint=accepted.terms_fingerprint,
        ),
    ):
        with pytest.raises(IngestionError):
            capture_approved_history(request, transport=transport, clock=lambda: NOW)
    assert transport.calls == 0


@pytest.mark.parametrize("status", (403, 429, 401))
def test_http_rights_and_rate_limit_responses_stop_without_raw_persistence(status: int) -> None:
    request = _request()
    transport = _ResponseTransport(HistoryHttpResponse(status_code=status, body=b"{}"))
    with pytest.raises(IngestionError):
        capture_approved_history(request, transport=transport, clock=lambda: NOW)
    assert transport.calls == 1


def test_synthetic_transport_is_serial_and_returns_derived_evidence_only() -> None:
    payload = _payload()
    request = _request()
    transport = _ResponseTransport(
        HistoryHttpResponse(status_code=200, body=json.dumps(payload).encode())
    )
    result = capture_approved_history(
        request,
        transport=transport,
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )
    assert transport.calls == 1
    assert result.evidence[0].seasons[0].goals == 4
    assert result.source_hashes[next(iter(result.source_hashes))] is None
    assert result.source_observed_at[next(iter(result.source_observed_at))] == NOW
    assert result.deletion_manifest.raw_history_persisted is False
    assert not hasattr(result, "body")
    bound = bind_posterior_to_deletion_manifest(
        result.deletion_manifest, posterior_artifact_sha256="f" * 64
    )
    assert bound.posterior_artifact_sha256 == "f" * 64


def test_schema_drift_stops_after_the_first_synthetic_response() -> None:
    request = _request(fingerprint="e" * 64)
    transport = _ResponseTransport(
        HistoryHttpResponse(status_code=200, body=json.dumps(_payload()).encode())
    )
    with pytest.raises(IngestionError, match="schema fingerprint"):
        capture_approved_history(request, transport=transport, clock=lambda: NOW)
    assert transport.calls == 1


def test_successful_receipt_after_cutoff_is_rejected() -> None:
    request = _request()
    transport = _ResponseTransport(
        HistoryHttpResponse(status_code=200, body=json.dumps(_payload()).encode())
    )
    with pytest.raises(IngestionError, match="after the information cutoff"):
        capture_approved_history(
            request,
            transport=transport,
            clock=lambda: datetime(2026, 8, 20, 12, 1, tzinfo=UTC),
        )
    assert transport.calls == 1
