"""Owned no-I/O witnesses for the diagnostic release boundary."""

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.credentials.service import _MESSAGES as CREDENTIAL_MESSAGES
from dmf_pulse.credentials.service import CredentialError
from dmf_pulse.dashboard.current import CurrentRefreshSession
from dmf_pulse.dashboard.runtime import DeskRuntime, PipeProgress
from dmf_pulse.dashboard.synthetic import DEMO_TIME
from dmf_pulse.operation.diagnostics import DiagnosticLog, safe_failure
from tests.unit.dashboard.test_current_mode import _Worker

CANARY = "owned-sensitive-ascii-progress-canary"


def test_parent_progress_does_not_disclose_non_code_owned_string(tmp_path):
    worker = _Worker([("progress", CANARY), ("error", "SOURCE_NOT_AVAILABLE")])
    runtime = DeskRuntime(
        current_session=CurrentRefreshSession.owned(tmp_path / "owned-ledger"),
        current_worker_factory=lambda _: worker,
        clock=lambda: DEMO_TIME,
    )
    try:
        runtime.refresh(1)
        state = runtime.tick()
        assert CANARY not in state.model_dump_json()
    finally:
        runtime.close()


def test_progress_failure_preserves_current_unexpected_exception():
    log = DiagnosticLog()
    log.enter("MANAGER_STATE")
    progress = PipeProgress(lambda _: None, diagnostics=log)
    try:
        raise KeyError(CANARY)
    except KeyError:
        # This is exactly the protected one_command.py except callback shape.
        progress.failure("one-command recommendation", "ONE_COMMAND_INPUT_INVALID")
    failure = log.report().failure
    assert failure.exception_family == "KEY"
    assert failure.category == "INTERNAL_EXCEPTION"
    assert CANARY not in failure.model_dump_json()


def test_cleanup_refusal_preserves_observed_partial_diagnostic_report(tmp_path):
    def factory(launch):
        log = DiagnosticLog()
        route = next(s for s in launch.grant.request.source_scopes if s.provider == "FPL").routes[0]
        log.enter("FPL_ACQUISITION")
        log.admitted("FPL", route.method, route.host, route.path)
        log.transport_started()
        log.response_completed(200)

        class CleanupRefused(_Worker):
            def close(self):
                raise RuntimeError(CANARY)

        return CleanupRefused(
            [
                *(("diagnostic", event.model_dump_json()) for event in log.events),
                ("error", "SOURCE_NOT_AVAILABLE"),
            ]
        )

    runtime = DeskRuntime(
        current_session=CurrentRefreshSession.owned(tmp_path / "owned-ledger"),
        current_worker_factory=factory,
        clock=lambda: DEMO_TIME,
    )
    try:
        runtime.refresh(1)
        state = runtime.tick()
        assert state.error_code == "WORKER_CLEANUP_FAILED"
        assert state.diagnostics is not None
        assert len(state.diagnostics.requests) == 1
        assert state.diagnostics.requests[0].response_completed_at is not None
        assert CANARY not in state.model_dump_json()
    finally:
        runtime.close()


def test_conflicting_child_failure_and_terminal_code_refused(tmp_path):
    def factory(_):
        log = DiagnosticLog()
        log.enter("MANAGER_STATE")
        log.failed(KeyError(CANARY))
        return _Worker(
            [
                *(("diagnostic", event.model_dump_json()) for event in log.events),
                ("error", "SOURCE_NOT_AVAILABLE"),
            ]
        )

    runtime = DeskRuntime(
        current_session=CurrentRefreshSession.owned(tmp_path / "owned-ledger"),
        current_worker_factory=factory,
        clock=lambda: DEMO_TIME,
    )
    try:
        runtime.refresh(1)
        state = runtime.tick()
        assert state.error_code == "DIAGNOSTIC_PROTOCOL_INVALID"
        assert CANARY not in state.model_dump_json()
    finally:
        runtime.close()


@pytest.mark.parametrize("code", tuple(CREDENTIAL_MESSAGES))
def test_known_credential_codes_are_retained_without_credentials(monkeypatch, code):
    def fail(**kwargs):
        raise CredentialError(code)

    monkeypatch.setattr("dmf_pulse.operation.start.run_start", fail)
    result = CliRunner().invoke(app, ["start"])
    assert result.exit_code == 2 and code in result.output
    assert "CURRENT_TYPED_FAILURE_UNRECOGNIZED" not in result.output


def test_os_error_is_transport_only_during_provider_acquisition():
    error = OSError(CANARY)
    source = safe_failure(error, "FPL_ACQUISITION")
    model = safe_failure(error, "SCORE_PRIOR_BINDING")
    assert source.category == "TRANSPORT" and source.code == "CURRENT_TRANSPORT_FAILED"
    assert model.category == "INTERNAL_EXCEPTION" and model.code == "CURRENT_INTERNAL_EXCEPTION"
    assert CANARY not in source.model_dump_json() + model.model_dump_json()
