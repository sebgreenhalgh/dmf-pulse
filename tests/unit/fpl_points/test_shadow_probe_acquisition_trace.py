"""Offline R9C-D2 tests for the probe's closed acquisition trace."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import DirectFplResource
from tests.unit.fpl_points.current_shadow_support import load_r9b_script

probe = load_r9b_script("probe_current_player_posterior_shadow")

pytestmark = pytest.mark.unit

SENTINELS = (
    "SECRET_TOKEN_XYZ",
    "PRIVATE_ENTRY_999999",
    "PLAYER_DO_NOT_LEAK",
    "/api/entry/999999/event/4/picks/",
    '{"private":"response body"}',
)


class TraceDelegate:
    """Synthetic transport-attempt counter; it never reaches a provider."""

    def __init__(self, actions: dict[DirectFplResource, tuple[int, bool]]) -> None:
        self._actions = actions
        self.request_count = 0
        self.endpoint_classes: list[DirectFplResource] = []

    def fetch(
        self,
        resource: DirectFplResource,
        *,
        entry_id: int | None = None,
        gameweek: int | None = None,
    ) -> bytes:
        del entry_id, gameweek
        attempts, fails = self._actions[resource]
        self.request_count += attempts
        self.endpoint_classes.extend([resource] * attempts)
        if fails:
            raise IngestionError("SOURCE_UNAVAILABLE", SENTINELS[0])
        return SENTINELS[-1].encode()


def _clock() -> datetime:
    return datetime(2026, 9, 16, 12, tzinfo=UTC)


def _profile_reference() -> str:
    return probe.load_rights_profiles()[probe.DIRECT_FPL_PROFILE_ID].human_approval_id


def _safe(result: dict[str, object], capsys, caplog) -> None:
    rendered = json.dumps(result, sort_keys=True)
    captured = capsys.readouterr()
    for sentinel in SENTINELS:
        assert sentinel not in rendered
        assert sentinel not in captured.out
        assert sentinel not in captured.err
        assert sentinel not in caplog.text
    assert result["diagnostic_schema_version"] == "r9c-shadow-probe-diagnostics-v2"
    assert "http" not in rendered.casefold()
    assert "status_code" not in result


@pytest.mark.parametrize(
    ("attempts", "fails", "completed"),
    ((1, False, True), (3, False, True), (3, True, False)),
)
def test_trace_records_logical_transport_attempts(attempts, fails, completed):
    delegate = TraceDelegate({DirectFplResource.FIXTURES: (attempts, fails)})
    trace = probe._AcquisitionTraceClient(delegate)

    if fails:
        with pytest.raises(IngestionError):
            trace.fetch(DirectFplResource.FIXTURES, entry_id=999999, gameweek=4)
    else:
        assert trace.fetch(DirectFplResource.FIXTURES, entry_id=999999, gameweek=4)

    assert trace.request_count == attempts
    assert trace.endpoint_classes == (DirectFplResource.FIXTURES,) * attempts
    assert trace.last_logical_resource is DirectFplResource.FIXTURES
    assert trace.last_logical_fetch_completed is completed
    assert trace.last_logical_transport_attempts == attempts
    assert not hasattr(trace, "__dict__")
    assert all(sentinel not in repr(trace) for sentinel in SENTINELS)


def test_trace_before_any_fetch_has_no_resource_or_identifier_surface():
    trace = probe._AcquisitionTraceClient(TraceDelegate({}))
    assert trace.last_logical_resource is None
    assert trace.last_logical_fetch_completed is None
    assert trace.last_logical_transport_attempts == trace.request_count == 0
    assert trace.endpoint_classes == ()
    assert not hasattr(trace, "__dict__")


def _blocked_after_sequence(
    monkeypatch,
    sequence: tuple[DirectFplResource, ...],
    actions: dict[DirectFplResource, tuple[int, bool]],
    *,
    caplog,
):
    delegate = TraceDelegate(actions)
    monkeypatch.setattr(probe, "DirectFplClient", lambda *args, **kwargs: delegate)

    def acquire(client, *args, **kwargs):
        del args, kwargs
        for resource in sequence:
            client.fetch(resource, entry_id=999999, gameweek=4)
        try:
            raise RuntimeError(SENTINELS[2])
        except RuntimeError as cause:
            raise ValueError(SENTINELS[1]) from cause

    monkeypatch.setattr(probe, "acquire_direct_fpl_snapshot", acquire)
    caplog.set_level(logging.DEBUG)
    result = probe.run_operator(42, _profile_reference(), True, clock=_clock)
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "FPL_ACQUISITION_FAILED"
    assert result["failure_stage"] == "ACQUIRE_FPL_SNAPSHOT"
    return result


def test_six_distinct_fetches_then_parse_failure_reports_sixth_completed(
    monkeypatch, capsys, caplog
):
    sequence = (
        DirectFplResource.BOOTSTRAP,
        DirectFplResource.FIXTURES,
        DirectFplResource.ENTRY,
        DirectFplResource.HISTORY,
        DirectFplResource.TRANSFERS,
        DirectFplResource.MY_TEAM,
    )
    result = _blocked_after_sequence(
        monkeypatch, sequence, {resource: (1, False) for resource in sequence}, caplog=caplog
    )
    assert result["fpl_acquisition_requests"] == 6
    assert result["fpl_endpoint_classes"] == [resource.value for resource in sequence]
    assert result["last_logical_resource"] == "MY_TEAM"
    assert result["last_logical_fetch_completed"] is True
    assert result["last_logical_transport_attempts"] == 1
    _safe(result, capsys, caplog)


def test_six_transport_attempts_do_not_imply_six_logical_resources(monkeypatch, capsys, caplog):
    sequence = (
        DirectFplResource.BOOTSTRAP,
        DirectFplResource.FIXTURES,
        DirectFplResource.ENTRY,
        DirectFplResource.HISTORY,
    )
    actions = {
        DirectFplResource.BOOTSTRAP: (1, False),
        DirectFplResource.FIXTURES: (3, False),
        DirectFplResource.ENTRY: (1, False),
        DirectFplResource.HISTORY: (1, False),
    }
    result = _blocked_after_sequence(monkeypatch, sequence, actions, caplog=caplog)
    assert result["fpl_acquisition_requests"] == 6
    assert result["fpl_endpoint_classes"] == [
        "BOOTSTRAP",
        "FIXTURES",
        "FIXTURES",
        "FIXTURES",
        "ENTRY",
        "HISTORY",
    ]
    assert result["last_logical_resource"] == "HISTORY"
    assert result["last_logical_fetch_completed"] is True
    assert result["last_logical_transport_attempts"] == 1
    _safe(result, capsys, caplog)


def test_sixth_transport_attempt_failure_reports_uncompleted_resource(monkeypatch, capsys, caplog):
    first_five = (
        DirectFplResource.BOOTSTRAP,
        DirectFplResource.FIXTURES,
        DirectFplResource.ENTRY,
        DirectFplResource.HISTORY,
        DirectFplResource.TRANSFERS,
    )
    sequence = (*first_five, DirectFplResource.PICKS)
    actions = {resource: (1, False) for resource in first_five} | {
        DirectFplResource.PICKS: (1, True)
    }
    delegate = TraceDelegate(actions)
    monkeypatch.setattr(probe, "DirectFplClient", lambda *args, **kwargs: delegate)

    def acquire(client, *args, **kwargs):
        del args, kwargs
        for resource in sequence:
            client.fetch(resource, entry_id=999999, gameweek=4)
        raise AssertionError("unreachable")

    monkeypatch.setattr(probe, "acquire_direct_fpl_snapshot", acquire)
    caplog.set_level(logging.DEBUG)
    result = probe.run_operator(42, _profile_reference(), True, clock=_clock)
    assert result["fpl_acquisition_requests"] == 6
    assert result["last_logical_resource"] == "PICKS"
    assert result["last_logical_fetch_completed"] is False
    assert result["last_logical_transport_attempts"] == 1
    _safe(result, capsys, caplog)


def test_picks_success_then_local_parse_failure_is_safe(monkeypatch, capsys, caplog):
    sequence = (
        DirectFplResource.BOOTSTRAP,
        DirectFplResource.FIXTURES,
        DirectFplResource.ENTRY,
        DirectFplResource.HISTORY,
        DirectFplResource.TRANSFERS,
        DirectFplResource.PICKS,
    )
    result = _blocked_after_sequence(
        monkeypatch, sequence, {resource: (1, False) for resource in sequence}, caplog=caplog
    )
    assert result["fpl_acquisition_requests"] == 6
    assert result["last_logical_resource"] == "PICKS"
    assert result["last_logical_fetch_completed"] is True
    assert result["last_logical_transport_attempts"] == 1
    _safe(result, capsys, caplog)
