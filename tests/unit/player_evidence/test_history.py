"""Offline parser and fail-closed future-capture tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.error import URLError

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence import history as history_module
from dmf_pulse.player_evidence.history import (
    ApprovedCaptureRequest,
    HistoryHttpResponse,
    bind_posterior_to_deletion_manifest,
    capture_approved_history,
    history_past_schema_fingerprint,
    parse_history_bytes,
    parse_history_past,
)
from dmf_pulse.player_evidence.models import PlayerHistoryEvidence, RetentionMode
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
    ("body", "code"),
    (
        (b"{not-json", "HISTORY_JSON_INVALID"),
        (json.dumps([]).encode(), "HISTORY_ROOT_INVALID"),
        (json.dumps({"history_past": {}}).encode(), "HISTORY_NODE_INVALID"),
        (
            json.dumps({"history_past": [{"season_name": "2025/26"}]}).encode(),
            "HISTORY_REQUIRED_FIELD_MISSING",
        ),
        (
            json.dumps(
                {
                    "history_past": [
                        {**_payload()["history_past"][0], "minutes": "SOURCE_VALUE_DO_NOT_LEAK"}
                    ]
                }
            ).encode(),
            "HISTORY_FIELD_TYPE_INVALID",
        ),
        (
            json.dumps(
                {"history_past": [{**_payload()["history_past"][0], "season_name": "not-a-season"}]}
            ).encode(),
            "HISTORY_SEASON_INVALID",
        ),
        (
            json.dumps(
                {"history_past": [{**_payload()["history_past"][0], "season_name": "2028/29"}]}
            ).encode(),
            "HISTORY_FUTURE_SEASON",
        ),
    ),
)
def test_parser_emits_exact_safe_failure_taxonomy(body: bytes, code: str) -> None:
    with pytest.raises(IngestionError) as raised:
        parse_history_bytes(body, current_season="2026/27", is_goalkeeper=False)
    assert raised.value.code == code
    serialized = json.dumps(raised.value.as_error_object(), sort_keys=True)
    assert "SOURCE_VALUE_DO_NOT_LEAK" not in serialized


def test_parser_rejects_duplicate_season_and_goalkeeper_without_saves() -> None:
    row = _payload()["history_past"][0]
    assert isinstance(row, dict)
    with pytest.raises(IngestionError) as duplicate:
        parse_history_past(
            {"history_past": [row, dict(row)]},
            current_season="2026/27",
            is_goalkeeper=False,
        )
    assert duplicate.value.code == "HISTORY_DUPLICATE_SEASON"
    without_saves = {key: value for key, value in row.items() if key != "saves"}
    with pytest.raises(IngestionError) as goalkeeper:
        parse_history_past(
            {"history_past": [without_saves]}, current_season="2026/27", is_goalkeeper=True
        )
    assert goalkeeper.value.code == "HISTORY_GOALKEEPER_SAVES_MISSING"


@pytest.mark.parametrize("event_field", ("goals_scored", "assists", "saves"))
def test_zero_minute_rate_event_remains_a_distinct_model_failure(event_field: str) -> None:
    row = dict(_payload()["history_past"][0])
    row["minutes"] = 0
    for field in ("goals_scored", "assists", "yellow_cards", "red_cards", "saves"):
        row[field] = 0
    row[event_field] = 1
    with pytest.raises(IngestionError) as raised:
        parse_history_past(
            {"history_past": [row]},
            current_season="2026/27",
            is_goalkeeper=event_field == "saves",
        )
    assert raised.value.code == "HISTORY_MODEL_VALIDATION_FAILED"
    assert raised.value.details == {"model_validation_reason": "ZERO_MINUTE_RATE_EVENT"}


@pytest.mark.parametrize(
    "discipline",
    (
        {"yellow_cards": 1},
        {"red_cards": 1},
        {"yellow_cards": 1, "red_cards": 1},
    ),
)
def test_zero_exposure_discipline_row_is_accepted_but_excluded_from_rate_model(
    discipline: dict[str, int],
) -> None:
    excluded = dict(_payload()["history_past"][0])
    excluded.update(
        {
            "season_name": "2024/25",
            "minutes": 0,
            "goals_scored": 0,
            "assists": 0,
            "yellow_cards": 0,
            "red_cards": 0,
            "saves": 0,
            **discipline,
        }
    )
    valid = dict(_payload()["history_past"][0])
    parsed = parse_history_past(
        {"history_past": [excluded, valid]},
        current_season="2026/27",
        is_goalkeeper=True,
    )
    assert parsed.zero_exposure_discipline_rows_excluded_count == 1
    assert tuple(row.season for row in parsed.seasons) == ("2025/26",)
    assert parsed.seasons[0].minutes == 900
    assert parsed.seasons[0].yellow_cards == 3


def test_zero_minute_mixed_discipline_and_rate_event_still_fails_closed() -> None:
    row = dict(_payload()["history_past"][0])
    row.update(
        {
            "minutes": 0,
            "goals_scored": 1,
            "assists": 0,
            "yellow_cards": 1,
            "red_cards": 0,
            "saves": 0,
        }
    )
    with pytest.raises(IngestionError) as raised:
        parse_history_past({"history_past": [row]}, current_season="2026/27", is_goalkeeper=True)
    assert raised.value.details == {"model_validation_reason": "ZERO_MINUTE_RATE_EVENT"}


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


class _SequenceTransport:
    def __init__(self, responses: tuple[HistoryHttpResponse | Exception, ...]) -> None:
        self._responses = responses
        self.calls = 0

    def get(self, url: str) -> HistoryHttpResponse:
        assert url.startswith("https://fantasy.premierleague.com/api/element-summary/")
        response = self._responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


def _request(
    *,
    expected_hash: str | None = None,
    fingerprint: str | None = None,
    maximum_player_count: int = 1,
) -> ApprovedCaptureRequest:
    payload = _payload()
    schema = fingerprint or history_past_schema_fingerprint(payload["history_past"])
    accepted = approval(schema_fingerprint=schema)
    return ApprovedCaptureRequest(
        approval=accepted,
        expected_approval_sha256=expected_hash or accepted.approval_sha256,
        catalogue=catalogue(),
        information_cutoff=NOW,
        maximum_player_count=maximum_player_count,
        terms_fingerprint=accepted.terms_fingerprint,
        retention_mode=RetentionMode.POSTERIOR_ONLY,
    )


def _safe_failure(raised: pytest.ExceptionInfo[IngestionError], *, code: str) -> dict[str, object]:
    assert raised.value.code == code
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    payload = raised.value.as_error_object()
    serialized = json.dumps(payload, sort_keys=True)
    assert "SOURCE_VALUE_DO_NOT_LEAK" not in serialized
    assert 'history_past": [{' not in serialized
    return payload["error"]["details"]  # type: ignore[index, no-any-return]


def _assert_capture_failure(
    raised: pytest.ExceptionInfo[IngestionError],
    *,
    code: str,
    ordinal: int = 1,
    successes: int = 0,
    stage: str,
) -> None:
    details = _safe_failure(raised, code=code)
    assert details["request_ordinal"] == ordinal
    assert details["failed_request_ordinal"] == ordinal
    assert details["requests_attempted_before_stop"] == ordinal
    assert details["successful_responses_before_stop"] == successes
    assert details["failure_code"] == code
    assert details["failure_stage"] == stage
    assert details["raw_persistence"] is False
    assert details["current_catalogue_persisted"] is False
    assert details["deletion_outcome"] == "SUCCESS"
    assert isinstance(details["deletion_run_id"], str)
    assert len(str(details["transient_player_identity_sha256"])) == 64


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


@pytest.mark.parametrize(
    ("status", "code"),
    (
        (401, "HISTORY_AUTHENTICATION_BLOCKED"),
        (403, "HISTORY_AUTHENTICATION_BLOCKED"),
        (429, "HISTORY_RATE_LIMITED"),
        (500, "HISTORY_HTTP_BLOCKED"),
    ),
)
def test_http_rights_and_rate_limit_responses_stop_without_raw_persistence(
    status: int, code: str
) -> None:
    request = _request()
    transport = _ResponseTransport(
        HistoryHttpResponse(status_code=status, body=b'{"SOURCE_VALUE_DO_NOT_LEAK": true}')
    )
    with pytest.raises(IngestionError) as raised:
        capture_approved_history(request, transport=transport, clock=lambda: NOW)
    _assert_capture_failure(raised, code=code, stage="HTTP")
    assert transport.calls == 1


@pytest.mark.parametrize(
    ("body", "code", "stage"),
    (
        (b"{not-json", "HISTORY_JSON_INVALID", "JSON"),
        (json.dumps([]).encode(), "HISTORY_ROOT_INVALID", "JSON"),
        (json.dumps({"history_past": {}}).encode(), "HISTORY_NODE_INVALID", "SCHEMA"),
        (
            json.dumps({"history_past": [{"season_name": "2025/26"}]}).encode(),
            "HISTORY_REQUIRED_FIELD_MISSING",
            "SCHEMA",
        ),
        (
            json.dumps(
                {
                    "history_past": [
                        {**_payload()["history_past"][0], "minutes": "SOURCE_VALUE_DO_NOT_LEAK"}
                    ]
                }
            ).encode(),
            "HISTORY_FIELD_TYPE_INVALID",
            "SCHEMA",
        ),
        (
            json.dumps(
                {"history_past": [{**_payload()["history_past"][0], "season_name": "not-a-season"}]}
            ).encode(),
            "HISTORY_SEASON_INVALID",
            "SCHEMA",
        ),
        (
            json.dumps(
                {"history_past": [{**_payload()["history_past"][0], "season_name": "2028/29"}]}
            ).encode(),
            "HISTORY_FUTURE_SEASON",
            "SCHEMA",
        ),
    ),
)
def test_capture_binds_parser_failures_to_safe_per_player_progress(
    body: bytes, code: str, stage: str
) -> None:
    request = _request()
    transport = _ResponseTransport(HistoryHttpResponse(status_code=200, body=body))
    with pytest.raises(IngestionError) as raised:
        capture_approved_history(request, transport=transport, clock=lambda: NOW)
    _assert_capture_failure(raised, code=code, stage=stage)
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
    with pytest.raises(IngestionError) as raised:
        capture_approved_history(request, transport=transport, clock=lambda: NOW)
    _assert_capture_failure(raised, code="HISTORY_SCHEMA_DRIFT", stage="SCHEMA")
    assert transport.calls == 1


def test_successful_receipt_after_cutoff_is_rejected() -> None:
    request = _request()
    transport = _ResponseTransport(
        HistoryHttpResponse(status_code=200, body=json.dumps(_payload()).encode())
    )
    with pytest.raises(IngestionError) as raised:
        capture_approved_history(
            request,
            transport=transport,
            clock=lambda: datetime(2026, 8, 20, 12, 1, tzinfo=UTC),
        )
    _assert_capture_failure(raised, code="POST_CUTOFF", stage="HTTP")
    assert transport.calls == 1


def test_network_unavailable_is_typed_and_safe() -> None:
    request = _request()
    transport = _SequenceTransport((URLError("offline"),))
    with pytest.raises(IngestionError) as raised:
        capture_approved_history(request, transport=transport, clock=lambda: NOW)
    _assert_capture_failure(raised, code="NETWORK_UNAVAILABLE", stage="HTTP")
    assert transport.calls == 1


def test_player_history_evidence_model_validation_is_typed_and_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = PlayerHistoryEvidence

    def invalid_evidence(**values: object) -> PlayerHistoryEvidence:
        return original(
            player_id=values["player_id"],  # type: ignore[arg-type]
            source_player_id=0,
            seasons=values["seasons"],  # type: ignore[arg-type]
        )

    monkeypatch.setattr(history_module, "PlayerHistoryEvidence", invalid_evidence)
    request = _request()
    transport = _ResponseTransport(
        HistoryHttpResponse(status_code=200, body=json.dumps(_payload()).encode())
    )
    with pytest.raises(IngestionError) as raised:
        capture_approved_history(request, transport=transport, clock=lambda: NOW)
    _assert_capture_failure(raised, code="HISTORY_MODEL_VALIDATION_FAILED", stage="MODEL")
    assert raised.value.details["model_validation_reason"] == "PLAYER_HISTORY_EVIDENCE"
    assert transport.calls == 1


def test_serial_model_failure_stops_once_and_retains_only_safe_progress() -> None:
    valid = HistoryHttpResponse(status_code=200, body=json.dumps(_payload()).encode())
    invalid_row = dict(_payload()["history_past"][0])
    invalid_row["minutes"] = 0
    invalid_row["goals_scored"] = 1
    invalid = HistoryHttpResponse(
        status_code=200,
        body=json.dumps({"history_past": [invalid_row], "SOURCE_VALUE_DO_NOT_LEAK": True}).encode(),
    )
    request = _request(maximum_player_count=3)
    transport = _SequenceTransport((valid, valid, invalid))
    with pytest.raises(IngestionError) as raised:
        capture_approved_history(
            request,
            transport=transport,
            clock=lambda: NOW,
            sleeper=lambda _: None,
        )
    _assert_capture_failure(
        raised,
        code="HISTORY_MODEL_VALIDATION_FAILED",
        ordinal=3,
        successes=2,
        stage="MODEL",
    )
    assert raised.value.details["model_validation_reason"] == "ZERO_MINUTE_RATE_EVENT"
    assert transport.calls == 3
