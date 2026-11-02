"""Disclosure, completion and chronology contracts for real worker evidence."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.operation.diagnostics import (
    MAX_EVENTS,
    DiagnosticEvent,
    DiagnosticLog,
    SafeFailure,
    route_identity,
    safe_failure,
)
from dmf_pulse.operation.models import OperationError
from dmf_pulse.private_v1.errors import PrivateV1Error

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)
CANARY = "owned-credential-cookie-body-exception-canary"


@pytest.mark.parametrize(
    "error,code,category",
    [
        (IngestionError("READ_TIMEOUT", CANARY), "SOURCE_NOT_AVAILABLE", "TRANSPORT"),
        (IngestionError("HTTP_429", CANARY), "HTTP_429", "HTTP_RESPONSE"),
        (
            IngestionError("VALIDATION_FAILED", CANARY),
            "SOURCE_RESPONSE_INVALID",
            "RESPONSE_CONTRACT",
        ),
        (IngestionError("FPL_AUTH_REQUIRED", CANARY), "FPL_AUTH_REQUIRED", "CREDENTIAL"),
        (
            PrivateV1Error("ONE_COMMAND_INPUT_INVALID", CANARY),
            "ONE_COMMAND_INPUT_INVALID",
            "INPUT_CONTRACT",
        ),
    ],
)
def test_allowlisted_typed_failures_keep_reason_without_message(error, code, category):
    failure = safe_failure(error, "FPL_ACQUISITION")
    assert failure.code == code and failure.category == category
    assert failure.typed_code_recognized
    assert CANARY not in failure.model_dump_json()


@pytest.mark.parametrize(
    "error",
    [IngestionError(CANARY, CANARY), PrivateV1Error(CANARY, CANARY), OperationError(CANARY)],
)
def test_unknown_typed_codes_are_distinct_and_discarded(error):
    failure = safe_failure(error, "MANAGER_STATE")
    assert failure.code == "CURRENT_TYPED_FAILURE_UNRECOGNIZED"
    assert failure.category == "UNRECOGNIZED_TYPED_FAILURE"
    assert not failure.typed_code_recognized
    assert CANARY not in failure.model_dump_json()


def test_unexpected_exception_is_not_formatted_or_named_dynamically():
    class OwnedSensitiveException(Exception):
        def __str__(self):
            raise AssertionError("exception text was accessed")

    failure = safe_failure(OwnedSensitiveException(CANARY), "STAGE12_DECISION")
    assert failure.code == "CURRENT_INTERNAL_EXCEPTION"
    assert failure.exception_family == "OTHER" and failure.stage == "STAGE12_DECISION"
    assert CANARY not in failure.model_dump_json()
    assert "OwnedSensitiveException" not in failure.model_dump_json()


def test_admission_and_transport_invocation_do_not_prove_completed_response():
    log = DiagnosticLog(clock=lambda: NOW)
    log.admitted("FPL", "GET", "fantasy.premierleague.com", "/api/my-team/17/")
    request = log.report().requests[0]
    assert request.transport_started_at is None and request.response_completed_at is None
    log.transport_started()
    request = log.report().requests[0]
    assert request.transport_started_at == NOW and request.response_completed_at is None
    log.response_completed(401)
    request = log.report().requests[0]
    assert request.response_completed_at == NOW and request.http_category == "CLIENT_ERROR"
    assert request.http_status == 401
    with pytest.raises(ValueError, match="unique transport"):
        log.response_completed(200)


def test_failed_transport_keeps_incomplete_request_and_safe_failure():
    log = DiagnosticLog(clock=lambda: NOW)
    log.enter("FPL_ACQUISITION")
    log.admitted("FPL", "GET", "fantasy.premierleague.com", "/api/fixtures/")
    log.transport_started()
    log.failed(IngestionError("CONNECT_TIMEOUT", CANARY))
    report = log.report()
    assert report.requests[0].response_completed_at is None
    assert report.failure.category == "TRANSPORT"
    assert CANARY not in report.model_dump_json()


@pytest.mark.parametrize(
    "path",
    ["/api/my-team/17/?token=" + CANARY, "/api/" + CANARY + "/", "/api/entry/17/\n" + CANARY],
)
def test_untrusted_route_is_rejected_before_it_can_be_hashed(monkeypatch, path):
    def forbidden(_):
        raise AssertionError("untrusted route was hashed")

    monkeypatch.setattr("dmf_pulse.operation.diagnostics.canonical_sha256", forbidden)
    with pytest.raises(OperationError, match="DIAGNOSTIC_ROUTE_IDENTITY_INVALID"):
        route_identity("FPL", "GET", "fantasy.premierleague.com", path, 1)


def test_unknown_public_failure_and_extra_payload_cannot_enter_contract():
    with pytest.raises(ValidationError):
        SafeFailure(
            stage="WORKER_START",
            category="INTERNAL_EXCEPTION",
            exception_family="OTHER",
            code=CANARY,
            typed_code_recognized=False,
        )
    with pytest.raises(ValidationError):
        DiagnosticEvent(sequence=0, at=NOW, kind="STAGE_STARTED", stage="WORKER_START", body=CANARY)


def test_reversed_or_naive_time_is_rejected():
    log = DiagnosticLog(clock=lambda: NOW)
    log.enter("WORKER_START")
    with pytest.raises(ValueError, match="chronology"):
        log.accept(
            DiagnosticEvent(
                sequence=1,
                at=NOW - timedelta(seconds=1),
                kind="STAGE_STARTED",
                stage="FPL_ACQUISITION",
            )
        )
    with pytest.raises(ValidationError):
        DiagnosticEvent(
            sequence=1, at=NOW.replace(tzinfo=None), kind="STAGE_STARTED", stage="FPL_ACQUISITION"
        )


def test_bounded_history_preserves_terminal_failure_and_request_outcomes():
    log = DiagnosticLog(clock=lambda: NOW)
    log.admitted("ODDS", "GET", "api.the-odds-api.com", "/v4/sports/soccer_epl/odds")
    log.transport_started()
    log.response_completed(200)
    for _ in range(MAX_EVENTS + 10):
        log.enter("STAGE9_POINTS")
    log.failed(KeyError(CANARY))
    report = log.report()
    assert len(report.events) == MAX_EVENTS and report.history_truncated
    assert report.failure.exception_family == "KEY"
    assert report.requests[0].response_completed_at == NOW
    assert report.events[-1].kind == "FAILURE"
    assert CANARY not in report.model_dump_json()


def test_malformed_http_status_is_completed_transport_but_invalid_response_contract():
    log = DiagnosticLog(clock=lambda: NOW)
    log.admitted("FPL", "GET", "fantasy.premierleague.com", "/api/fixtures/")
    log.transport_started()
    log.response_completed(CANARY)
    outcome = log.report().requests[0]
    assert outcome.response_completed_at == NOW
    assert outcome.http_status is None and outcome.http_category == "INVALID_STATUS"
    assert CANARY not in log.report().model_dump_json()


def test_invalid_completion_cannot_partially_advance_reducer():
    log = DiagnosticLog(clock=lambda: NOW)
    log.admitted("FPL", "GET", "fantasy.premierleague.com", "/api/fixtures/")
    before = log.report().model_dump_json()
    with pytest.raises(ValueError, match="unique transport"):
        log.response_completed(200)
    assert log.report().model_dump_json() == before
    log.transport_started()
    log.response_completed(200)


def test_clock_reversal_preserves_failure_without_inventing_event_time():
    now = [NOW]
    log = DiagnosticLog(clock=lambda: now[0])
    log.enter("FPL_ACQUISITION")
    now[0] = NOW - timedelta(seconds=1)
    log.failed(KeyError(CANARY))
    report = log.report()
    assert not report.chronology_complete
    assert report.failure.exception_family == "KEY"
    assert len(report.events) == 1 and report.events[0].at == NOW
