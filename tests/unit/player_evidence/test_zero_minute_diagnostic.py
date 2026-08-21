"""Synthetic-only tests for the single-row zero-minute diagnostic."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.request import Request

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence import zero_minute_diagnostic as diagnostic_module
from dmf_pulse.player_evidence.approvals import load_player_history_rights_approval
from dmf_pulse.player_evidence.diagnostic_approval import (
    DIAGNOSTIC_APPROVAL_SHA256,
    DIAGNOSTIC_INFORMATION_CUTOFF,
    DIAGNOSTIC_TERMS_FINGERPRINT,
    ZeroMinuteDiagnosticApproval,
    load_zero_minute_diagnostic_approval,
)
from dmf_pulse.player_evidence.history import HistoryHttpResponse
from dmf_pulse.player_evidence.zero_minute_diagnostic import (
    ApprovedZeroMinuteDiagnosticRequest,
    execute_zero_minute_diagnostic,
    parse_zero_minute_diagnostic_bytes,
    resolve_zero_minute_diagnostic_target,
)
from tests.unit.player_evidence.support import catalogue


def _row(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "season_name": "2025/26",
        "minutes": 900,
        "goals_scored": 0,
        "assists": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "saves": 0,
        "SOURCE_VALUE_DO_NOT_LEAK": 91,
    }
    value.update(updates)
    return value


def _parse(*rows: dict[str, object]):
    return parse_zero_minute_diagnostic_bytes(
        json.dumps({"history_past": list(rows)}).encode("utf-8")
    )


@pytest.mark.parametrize(
    ("events", "yellow", "red"),
    (
        ({"yellow_cards": 1}, True, False),
        ({"red_cards": 1}, False, True),
        ({"yellow_cards": 1, "red_cards": 1}, True, True),
    ),
)
def test_zero_minute_discipline_only_is_true_and_rate_event_is_false(
    events: dict[str, object], yellow: bool, red: bool
) -> None:
    result = _parse(_row(minutes=0, **events))
    assert result.zero_minute_row_count == 1
    assert result.zero_minute_positive_yellow_present is yellow
    assert result.zero_minute_positive_red_present is red
    assert result.zero_minute_discipline_only_present is True
    assert result.zero_minute_rate_event_present is False


@pytest.mark.parametrize(
    ("field", "attribute"),
    (
        ("saves", "zero_minute_positive_saves_present"),
        ("goals_scored", "zero_minute_positive_goal_present"),
        ("assists", "zero_minute_positive_assist_present"),
    ),
)
def test_zero_minute_goal_assist_or_save_is_a_rate_event(field: str, attribute: str) -> None:
    result = _parse(_row(minutes=0, **{field: 1}))
    assert getattr(result, attribute) is True
    assert result.zero_minute_rate_event_present is True
    assert result.zero_minute_discipline_only_present is False


def test_mixed_card_and_save_is_rate_event_not_discipline_only() -> None:
    result = _parse(_row(minutes=0, yellow_cards=1, red_cards=1, saves=1))
    assert result.zero_minute_positive_yellow_present is True
    assert result.zero_minute_positive_red_present is True
    assert result.zero_minute_positive_saves_present is True
    assert result.zero_minute_rate_event_present is True
    assert result.zero_minute_discipline_only_present is False


def test_no_zero_minute_anomaly_has_both_classifiers_false() -> None:
    result = _parse(_row(minutes=900, yellow_cards=2), _row(minutes=0))
    assert result.zero_minute_row_count == 1
    assert result.zero_minute_rate_event_present is False
    assert result.zero_minute_discipline_only_present is False
    assert result.all_nonzero_minute_rows_basic_schema_valid is True


def _approval(repository_root: Path) -> ZeroMinuteDiagnosticApproval:
    return load_zero_minute_diagnostic_approval(
        repository_root
        / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_ZERO_MINUTE_DIAGNOSTIC_APPROVAL.json",
        expected_approval_sha256=DIAGNOSTIC_APPROVAL_SHA256,
    )


def _synthetic_request(
    repository_root: Path, monkeypatch: pytest.MonkeyPatch
) -> ApprovedZeroMinuteDiagnosticRequest:
    synthetic = catalogue()
    goalkeeper = next(player for player in synthetic.players if player.position.value == "GK")
    ordinal = synthetic.players.index(goalkeeper) + 1
    identity = sha256(goalkeeper.player_id.bytes).hexdigest()
    semantic = "c" * 64
    synthetic = synthetic.model_copy(update={"semantic_sha256": semantic})
    monkeypatch.setattr(diagnostic_module, "DIAGNOSTIC_CATALOGUE_SHA256", semantic)
    monkeypatch.setattr(diagnostic_module, "DIAGNOSTIC_TARGET_IDENTITY_SHA256", identity)
    monkeypatch.setattr(diagnostic_module, "DIAGNOSTIC_TARGET_ORDINAL", ordinal)
    target = resolve_zero_minute_diagnostic_target(synthetic)
    approved = _approval(repository_root)
    approved = approved.model_copy(
        update={
            "diagnostic_binding": approved.diagnostic_binding.model_copy(
                update={
                    "expected_catalogue_semantic_sha256": semantic,
                    "failed_request_ordinal": ordinal,
                    "transient_player_identity_sha256": identity,
                }
            )
        }
    )
    return ApprovedZeroMinuteDiagnosticRequest(
        approval=approved,
        target=target,
        catalogue=synthetic,
        information_cutoff=DIAGNOSTIC_INFORMATION_CUTOFF,
        terms_fingerprint=DIAGNOSTIC_TERMS_FINGERPRINT,
    )


class _Transport:
    def __init__(self, response: HistoryHttpResponse) -> None:
        self.response = response
        self.calls = 0

    def get(self, url: str) -> HistoryHttpResponse:
        assert url.startswith("https://fantasy.premierleague.com/api/element-summary/")
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("diagnostic transport must never retry")
        return self.response


def test_exact_target_identity_and_ordinal_are_required_before_transport(
    repository_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _synthetic_request(repository_root, monkeypatch)
    other = next(
        player
        for player in request.catalogue.players
        if player.player_id != request.target.player_id
    )
    forged = replace(
        request.target, player_id=other.player_id, source_player_id=other.source_player_id
    )
    transport = _Transport(
        HistoryHttpResponse(status_code=200, body=json.dumps({"history_past": []}).encode())
    )
    with pytest.raises(IngestionError) as raised:
        execute_zero_minute_diagnostic(
            replace(request, target=forged),
            transport=transport,
            clock=lambda: datetime(2026, 8, 21, 13, tzinfo=UTC),
        )
    assert raised.value.code == "DIAGNOSTIC_TARGET_MISMATCH"
    assert transport.calls == 0


def test_request_bound_is_exactly_one_and_no_retry_exists(
    repository_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _synthetic_request(repository_root, monkeypatch)
    transport = _Transport(HistoryHttpResponse(status_code=500, body=b"SOURCE_VALUE_DO_NOT_LEAK"))
    with pytest.raises(IngestionError) as raised:
        execute_zero_minute_diagnostic(
            replace(request, maximum_official_history_requests=2),
            transport=transport,
            clock=lambda: datetime(2026, 8, 21, 13, tzinfo=UTC),
        )
    assert raised.value.code == "DIAGNOSTIC_REQUEST_BOUND_INVALID"
    assert transport.calls == 0

    with pytest.raises(IngestionError) as failed_response:
        execute_zero_minute_diagnostic(
            request,
            transport=transport,
            clock=lambda: datetime(2026, 8, 21, 13, tzinfo=UTC),
        )
    assert failed_response.value.code == "DIAGNOSTIC_HTTP_BLOCKED"
    assert transport.calls == 1


def test_production_diagnostic_transport_refuses_redirects() -> None:
    handler = diagnostic_module._RejectRedirects()
    request = Request("https://fantasy.premierleague.com/api/element-summary/1/")
    assert (
        handler.redirect_request(request, None, 302, "redirect", {}, "https://example.test") is None
    )


def test_safe_result_and_errors_contain_no_raw_values() -> None:
    result = _parse(_row(minutes=0, yellow_cards=91))
    rendered = json.dumps(result.safe_dict(), sort_keys=True)
    assert "SOURCE_VALUE_DO_NOT_LEAK" not in rendered
    assert '"yellow_cards"' not in rendered
    assert ": 91" not in rendered
    with pytest.raises(IngestionError) as raised:
        parse_zero_minute_diagnostic_bytes(
            json.dumps({"history_past": [_row(minutes="SOURCE_VALUE_DO_NOT_LEAK")]}).encode()
        )
    assert "SOURCE_VALUE_DO_NOT_LEAK" not in json.dumps(raised.value.as_error_object())


def test_diagnostic_loader_is_exact_and_cannot_authorize_bulk_capture(
    repository_root: Path, tmp_path: Path
) -> None:
    approved = _approval(repository_root)
    assert approved.capture_constraints.maximum_official_history_requests == 1
    assert approved.bulk_capture_authority == "NONE"
    source = (
        repository_root
        / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_ZERO_MINUTE_DIAGNOSTIC_APPROVAL.json"
    )
    altered = json.loads(source.read_text(encoding="utf-8"))
    altered["capture_constraints"]["maximum_official_history_requests"] = 599
    altered_path = tmp_path / "altered-diagnostic.json"
    altered_path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(IngestionError) as altered_error:
        load_zero_minute_diagnostic_approval(
            altered_path, expected_approval_sha256=DIAGNOSTIC_APPROVAL_SHA256
        )
    assert altered_error.value.code == "DIAGNOSTIC_APPROVAL_INVALID"
    with pytest.raises(IngestionError) as bulk_error:
        load_player_history_rights_approval(
            source, expected_approval_sha256=DIAGNOSTIC_APPROVAL_SHA256
        )
    assert bulk_error.value.code == "RIGHTS_APPROVAL_HASH_MISMATCH"


def test_safe_live_diagnostic_receipt_is_hash_bound_and_contains_no_raw_rows(
    repository_root: Path,
) -> None:
    path = (
        repository_root
        / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_ZERO_MINUTE_DIAGNOSTIC_RESULT.json"
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = value.pop("diagnostic_result_sha256")
    assert canonical_sha256(value) == expected
    assert value["diagnostic_request_count"] == 1
    assert value["live_requests_after_diagnostic"] == 0
    assert value["raw_fpl_history_persisted"] is False
    assert value["current_fpl_catalogue_persisted"] is False
    rendered = path.read_text(encoding="utf-8")
    assert '"history_past"' not in rendered
    assert '"season_name"' not in rendered
    assert '"minutes"' not in rendered
    assert '"yellow_cards"' not in rendered
