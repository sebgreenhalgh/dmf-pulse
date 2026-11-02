"""Owned bootstrap bytes and transports only; no native credential or FPL calls."""

from __future__ import annotations

import copy
import hashlib
import json
import traceback
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.ingestion.fpl import direct
from dmf_pulse.ingestion.fpl.direct import DirectHttpResponse, DirectUrllibTransport
from dmf_pulse.ingestion.rights import load_rights_profiles
from dmf_pulse.operation.discovery import EventDiscovery, discover_event, fpl_routes
from dmf_pulse.operation.models import OperationError

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)


def bootstrap(target=10):
    return {
        "events": [
            {
                "id": value,
                "name": f"Owned Gameweek {value}",
                "deadline_time": (NOW + timedelta(days=value - target + 1)).isoformat(),
                "finished": value < target,
                "data_checked": value < target,
                "is_current": value == target - 1,
                "is_next": value == target,
            }
            for value in range(1, target + 2)
        ],
        "game_settings": {},
        "teams": [],
        "elements": [],
        "element_types": [],
    }


class OwnedTransport:
    def __init__(self, payload=None, *, status=200):
        self.body = json.dumps(bootstrap() if payload is None else payload).encode()
        self.status = status
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return DirectHttpResponse(self.status, "application/json", self.body)


def profile():
    return load_rights_profiles()[direct.DIRECT_FPL_PROFILE_ID]


def discover(transport, *, admission=lambda: None, before_send=lambda: None, clock=lambda: NOW):
    return discover_event(
        profile=profile(),
        admission=admission,
        before_send=before_send,
        transport=transport,
        clock=clock,
    )


def test_one_public_bootstrap_actual_clock_hash_and_exact_upcoming_deadline(monkeypatch):
    monkeypatch.setattr(
        direct.DirectFplCredentialProvider, "get", lambda _: pytest.fail("token read")
    )
    transport = OwnedTransport()
    clock = [NOW]
    order = []

    def admit():
        order.append("admission")

    def before_send():
        order.append("before_send")
        clock[0] += timedelta(microseconds=321)

    value = discover(transport, admission=admit, before_send=before_send, clock=lambda: clock[0])
    assert value.target_gameweek == 10 and value.deadline_at == NOW + timedelta(days=1)
    assert value.history_gameweeks == tuple(range(1, 10))
    assert value.request_started_at == NOW and value.received_at == NOW + timedelta(
        microseconds=321
    )
    assert value.bootstrap_sha256 == hashlib.sha256(transport.body).hexdigest()
    assert value.request_count == 1 and len(transport.requests) == 1
    request = transport.requests[0]
    assert (request.method, request.host, request.path) == (
        "GET",
        "fantasy.premierleague.com",
        "/api/bootstrap-static/",
    )
    assert "X-API-Authorization" not in request.headers
    assert order[-2:] == ["admission", "before_send"]


def test_admission_is_required_before_any_transport_construction(monkeypatch):
    monkeypatch.setattr(
        "dmf_pulse.operation.discovery.DirectUrllibTransport", lambda: pytest.fail("constructed")
    )

    def denied():
        raise OperationError("STANDING_PERMISSION_REQUIRED")

    with pytest.raises(OperationError) as error:
        discover_event(
            profile=profile(), admission=denied, before_send=lambda: None, clock=lambda: NOW
        )
    assert error.value.code == "STANDING_PERMISSION_REQUIRED"


def test_recheck_immediately_before_send_blocks_revoked_admission():
    transport = OwnedTransport()
    calls = []

    def admit():
        calls.append(1)
        if len(calls) == 4:
            raise AuthorizationError("AUTHORIZATION_REVOKED")

    with pytest.raises(OperationError) as error:
        discover(transport, admission=admit)
    assert error.value.code == "AUTHORIZATION_REVOKED" and transport.requests == []


def test_native_supplier_permission_gate_cannot_be_replaced_by_noop_admission(monkeypatch):
    sent = []

    class NativeDouble(DirectUrllibTransport):
        def send(self, request):
            sent.append(request)
            pytest.fail("unqualified native send")

    def denied(*args, **kwargs):
        raise OperationError("SOURCE_PERMISSION_REQUIRED")

    monkeypatch.setattr("dmf_pulse.operation.enrollment.require_fpl_route", denied)
    with pytest.raises(OperationError) as error:
        discover(NativeDouble())
    assert error.value.code == "FPL_SUPPLIER_PERMISSION_REQUIRED" and sent == []


@pytest.mark.parametrize("status", [429, 500, 503])
def test_one_attempt_no_retry_even_when_source_marks_failure_retryable(status):
    transport = OwnedTransport(status=status)
    with pytest.raises(OperationError):
        discover(transport)
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "boolean",
        "unordered",
        "two_next",
        "two_current",
        "stale_next",
        "naive_deadline",
        "finished_next",
    ],
)
def test_ambiguous_or_invalid_official_events_fail_closed(kind):
    payload = bootstrap()
    if kind == "duplicate":
        payload["events"].append(copy.deepcopy(payload["events"][0]))
    elif kind == "boolean":
        payload["events"][0]["id"] = True
    elif kind == "unordered":
        payload["events"][0], payload["events"][1] = payload["events"][1], payload["events"][0]
    elif kind == "two_next":
        payload["events"][-1]["is_next"] = True
    elif kind == "two_current":
        payload["events"][0]["is_current"] = True
    elif kind == "stale_next":
        payload["events"][9]["deadline_time"] = NOW.isoformat()
    elif kind == "naive_deadline":
        payload["events"][9]["deadline_time"] = NOW.replace(tzinfo=None).isoformat()
    else:
        payload["events"][9]["finished"] = True
    with pytest.raises(OperationError):
        discover(OwnedTransport(payload))


def test_existing_twelve_history_selection_and_exact_route_budget_are_preserved():
    discovery = discover(OwnedTransport(bootstrap(30)))
    assert discovery.history_gameweeks == tuple(range(18, 30))
    routes = fpl_routes(42, discovery)
    paths = [route.path for route in routes]
    assert len(routes) == len(set(paths)) == 19 and len(routes) + discovery.request_count == 20
    assert all(route.method == "GET" and route.maximum_calls == 1 for route in routes)
    assert all(route.host == "fantasy.premierleague.com" for route in routes)
    assert paths[:5] == [
        "/api/bootstrap-static/",
        "/api/fixtures/",
        "/api/entry/42/",
        "/api/entry/42/history/",
        "/api/entry/42/transfers/",
    ]
    assert paths[5:7] == ["/api/entry/42/event/29/picks/", "/api/my-team/42/"]
    assert paths[7:] == [f"/api/event/{value}/live/" for value in range(18, 30)]


def test_history_only_includes_finished_data_checked_earlier_events():
    payload = bootstrap()
    payload["events"][0]["data_checked"] = False
    payload["events"][1]["finished"] = False
    value = discover(OwnedTransport(payload))
    assert value.history_gameweeks == tuple(range(3, 10))


def test_first_gameweek_does_not_invent_picks_or_history_routes():
    value = discover(OwnedTransport(bootstrap(1)))
    assert value.history_gameweeks == ()
    assert len(fpl_routes(42, value)) == 6
    assert not any("/event/" in route.path for route in fpl_routes(42, value))


@pytest.mark.parametrize("entry", [True, 0, -1, "42", 42.5])
def test_route_derivation_refuses_nonliteral_manager_id(entry):
    with pytest.raises(OperationError):
        fpl_routes(entry, discover(OwnedTransport()))


def test_discovery_metadata_refuses_naive_time_duplicates_and_boolean_count():
    value = discover(OwnedTransport())
    for changes in (
        {"request_count": True},
        {"request_started_at": NOW.replace(tzinfo=None)},
        {"deadline_at": NOW},
        {"history_gameweeks": (1, 1)},
        {"history_gameweeks": (10,)},
        {"history_gameweeks": tuple(range(1, 14))},
    ):
        with pytest.raises(ValidationError):
            EventDiscovery.model_validate({**value.model_dump(), **changes})


def test_failure_drops_raw_source_body_and_callback_exception_graph():
    marker = "owned_source_body_must_not_escape"

    class Broken:
        def send(self, request):
            raise RuntimeError(marker)

    with pytest.raises(OperationError) as error:
        discover(Broken())
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert marker not in "".join(traceback.format_exception(error.value))
    frame = error.value.__traceback__
    while frame:
        if frame.tb_frame.f_code.co_name == "discover_event":
            assert not {"profile", "transport", "admission", "before_send", "body"} & set(
                frame.tb_frame.f_locals.keys()
            )
        frame = frame.tb_next


def test_parser_failure_drops_raw_response_from_public_exception():
    transport = OwnedTransport()
    marker = b"owned_invalid_bootstrap_body_marker"
    transport.body = marker
    with pytest.raises(OperationError) as error:
        discover(transport)
    assert error.value.code == "MALFORMED_JSON"
    assert marker.decode() not in "".join(traceback.format_exception(error.value))
    assert error.value.__context__ is None


@pytest.mark.parametrize("naive", [False, True])
def test_invalid_or_reversed_discovery_clock_fails_closed(naive):
    values = iter((NOW.replace(tzinfo=None),)) if naive else iter((NOW, NOW - timedelta(seconds=1)))
    with pytest.raises(OperationError) as error:
        discover(OwnedTransport(), clock=lambda: next(values))
    assert error.value.code == "DISCOVERY_CLOCK_INVALID"
