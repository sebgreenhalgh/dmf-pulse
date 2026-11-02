"""The parent retains bounded worker evidence without trusting it as authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.dashboard import current
from dmf_pulse.dashboard.current import CurrentRefreshSession, current_worker
from dmf_pulse.dashboard.runtime import DeskRuntime
from dmf_pulse.dashboard.synthetic import DEMO_TIME
from dmf_pulse.operation.diagnostics import DiagnosticLog
from dmf_pulse.operation.models import OperationError
from dmf_pulse.private_v1.errors import PrivateV1Error
from tests.unit.dashboard.test_current_mode import _Pipe, _Worker

CANARY = "owned-cookie-header-exception-canary-never-publish"


@pytest.mark.parametrize("typed", [False, True])
def test_full_worker_parent_keeps_named_failure_family_and_no_raw_error(
    tmp_path, monkeypatch, typed
):
    def fail(launch, progress):
        with progress.stage(
            started="Acquiring current FPL state...",
            completed="FPL state ready",
            failed="current FPL state",
        ):
            if typed:
                raise PrivateV1Error(CANARY, CANARY)
            raise KeyError(CANARY)

    monkeypatch.setattr(current, "run_current_recommendation", fail)
    workers = []

    def factory(launch):
        pipe = _Pipe()
        current_worker(pipe, 1, launch)
        worker = _Worker(pipe.messages)
        workers.append(worker)
        return worker

    runtime = DeskRuntime(
        current_session=CurrentRefreshSession.owned(tmp_path / "ledger"),
        current_worker_factory=factory,
        clock=lambda: DEMO_TIME,
    )
    try:
        runtime.refresh(1)
        state = runtime.tick()
        assert state.status == "BLOCKED" and workers[0].closed
        assert state.error_code == (
            "CURRENT_TYPED_FAILURE_UNRECOGNIZED" if typed else "CURRENT_INTERNAL_EXCEPTION"
        )
        assert state.diagnostics.failure.stage == "FPL_ACQUISITION"
        assert state.diagnostics.failure.exception_family == ("PRIVATE_MODEL" if typed else "KEY")
        assert state.diagnostics.worker_terminal_received
        assert CANARY not in state.model_dump_json()
        assert runtime.view() is None
    finally:
        runtime.close()


@pytest.mark.parametrize("attack", ["payload", "unbound-route", "future", "repeated-admission"])
def test_invalid_diagnostic_cannot_enter_report_or_keep_worker_running(tmp_path, attack):
    workers = []

    def factory(launch):
        if attack == "payload":
            messages = [("diagnostic", json.dumps({"body": CANARY}))]
        else:
            log = DiagnosticLog()
            scope = next(row for row in launch.grant.request.source_scopes if row.provider == "FPL")
            route = scope.routes[0]
            log.admitted("FPL", route.method, route.host, route.path)
            event = log.events[0]
            if attack == "unbound-route":
                event = event.model_copy(
                    update={"request": event.request.model_copy(update={"route_sha256": "e" * 64})}
                )
            elif attack == "future":
                event = event.model_copy(update={"at": datetime.now(UTC) + timedelta(days=1)})
            messages = [("diagnostic", event.model_dump_json())]
            if attack == "repeated-admission":
                log.admitted("FPL", route.method, route.host, route.path)
                messages.append(("diagnostic", log.events[-1].model_dump_json()))
        worker = _Worker(messages)
        workers.append(worker)
        return worker

    runtime = DeskRuntime(
        current_session=CurrentRefreshSession.owned(tmp_path / "ledger"),
        current_worker_factory=factory,
        clock=lambda: DEMO_TIME,
    )
    try:
        runtime.refresh(1)
        state = runtime.tick()
        assert state.status == "BLOCKED" and state.error_code == "DIAGNOSTIC_PROTOCOL_INVALID"
        assert workers[0].closed and runtime.view() is None
        assert CANARY not in state.model_dump_json()
    finally:
        runtime.close()


def test_premature_worker_exit_keeps_known_completions_and_marks_partial(tmp_path):
    class Exited(_Worker):
        def alive(self):
            return bool(self.messages)

    def factory(launch):
        log = DiagnosticLog()
        routes = next(
            row for row in launch.grant.request.source_scopes if row.provider == "FPL"
        ).routes
        first, second = routes[:2]
        log.admitted("FPL", first.method, first.host, first.path)
        log.transport_started()
        log.response_completed(200)
        log.admitted("FPL", second.method, second.host, second.path)
        log.transport_started()
        return Exited([("diagnostic", event.model_dump_json()) for event in log.events])

    runtime = DeskRuntime(
        current_session=CurrentRefreshSession.owned(tmp_path / "ledger"),
        current_worker_factory=factory,
        clock=lambda: DEMO_TIME,
    )
    try:
        runtime.refresh(1)
        state = runtime.tick()
        assert state.status == "BLOCKED" and state.error_code == "WORKER_STOPPED"
        assert not state.diagnostics.worker_terminal_received
        assert len(state.diagnostics.requests) == 2
        assert sum(row.response_completed_at is not None for row in state.diagnostics.requests) == 1
    finally:
        runtime.close()


def test_start_boundary_does_not_echo_unrecognized_operator_error(monkeypatch):
    def fail(**kwargs):
        raise OperationError(CANARY)

    monkeypatch.setattr("dmf_pulse.operation.start.run_start", fail)
    result = CliRunner().invoke(app, ["start"])
    assert result.exit_code == 2 and CANARY not in result.output
    assert "CURRENT_TYPED_FAILURE_UNRECOGNIZED" in result.output
