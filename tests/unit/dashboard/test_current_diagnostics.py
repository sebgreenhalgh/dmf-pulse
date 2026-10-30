"""Known safe failures survive the actual worker, runtime and console boundaries."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.cli import pulse
from dmf_pulse.cli.app import app
from dmf_pulse.dashboard import current
from dmf_pulse.dashboard.authorization import UsageLedger
from dmf_pulse.dashboard.current import CurrentRefreshSession, current_worker
from dmf_pulse.dashboard.runtime import DeskRuntime, JobState
from dmf_pulse.dashboard.synthetic import DEMO_TIME
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.operation.console import publish_runtime
from tests.unit.dashboard.test_current_mode import _Pipe, _Worker

CANARY = "owned-private-error-canary-never-publish"


@pytest.mark.parametrize(
    "code",
    [
        "CREDENTIAL_EXPIRED",
        "CREDENTIAL_CORRUPT",
        "CREDENTIAL_NOT_CONFIGURED",
        "CREDENTIAL_BACKEND_UNAVAILABLE",
        "AUTHORIZATION_REVOKED",
        "USAGE_LEDGER_SCHEMA_NOT_READY",
        "REFRESH_GRANT_EXPIRED",
        "FPL_AUTH_REQUIRED",
        "HTTP_429",
    ],
)
def test_worker_runtime_console_keep_exact_actionable_reason(tmp_path, monkeypatch, code):
    def fail(*args):
        raise IngestionError(code, CANARY)

    monkeypatch.setattr(current, "run_current_recommendation", fail)
    session = CurrentRefreshSession.owned(tmp_path / "usage")
    workers = []
    messages = []

    def factory(launch):
        pipe = _Pipe()
        current_worker(pipe, 1, launch)
        assert pipe.closed and pipe.messages == [("error", code)]
        messages.extend(pipe.messages)
        worker = _Worker(pipe.messages)
        workers.append(worker)
        return worker

    runtime = DeskRuntime(
        current_session=session, current_worker_factory=factory, clock=lambda: DEMO_TIME
    )

    def enrolled(**kwargs):
        return publish_runtime(
            runtime, horizon=kwargs["horizon"], publish=kwargs["publish"], wait=lambda _: None
        )

    monkeypatch.setattr(pulse, "run_enrolled_current", enrolled)
    result = CliRunner().invoke(
        app, ["pulse", "--entry-id", "42", "--refresh-approval", "OWNED-TEST", "--no-progress"]
    )
    assert result.exit_code == 2 and result.stdout == ""
    assert code in result.stderr and CANARY not in result.output
    assert CANARY not in str(messages) and workers[0].closed
    assert runtime.view() is None


def test_actual_odds_guard_failure_survives_accepted_client_and_controller_wrapping(
    tmp_path, monkeypatch
):
    class Controller:
        def __init__(self, **kwargs):
            self.factory = kwargs["odds_service_factory"]

        def run(self, request):
            # This is the accepted Odds client path with owned transport/key,
            # not a mocked exception at the client boundary.
            return self.factory(lambda: DEMO_TIME).acquire(
                information_cutoff=request.run_at,
                commence_to=request.run_at.replace(day=request.run_at.day + 1),
            )

    original = UsageLedger.attempt

    def deny_odds(self, grant, worker_id, **kwargs):
        if kwargs["provider"] == "ODDS":
            raise AuthorizationError("ACQUISITION_CUTOFF_PASSED", "EXPIRED")
        return original(self, grant, worker_id, **kwargs)

    monkeypatch.setattr(UsageLedger, "attempt", deny_odds)
    monkeypatch.setattr(current, "PrivateV1OneCommandService", Controller)
    launch = CurrentRefreshSession.owned(tmp_path / "usage").prepare(1)
    pipe = _Pipe()
    current_worker(pipe, 1, launch)
    assert pipe.closed and pipe.messages == [("error", "ACQUISITION_CUTOFF_PASSED")]


def test_raw_sidecar_scope_discards_client_exception_graph():
    guard = SimpleNamespace(failure=current._GuardFailure("AUTHORIZATION_REVOKED", "BLOCKED"))

    class Controller:
        def run(self, request):
            raise ValueError(CANARY)

    value = current._current_service_scope(Controller(), object(), guard)
    assert value.code == "AUTHORIZATION_REVOKED" and CANARY not in repr(value)


def test_unrelated_controller_errors_are_not_masked():
    guard = SimpleNamespace(failure=None)

    class Controller:
        def run(self, request):
            raise ValueError("owned malformed input")

    with pytest.raises(ValueError, match="owned malformed input"):
        current._current_service_scope(Controller(), object(), guard)


def test_browser_state_exposes_fixed_expiry_remedy_without_any_lookup():
    value = JobState(status="BLOCKED", error_code="CREDENTIAL_EXPIRED").model_dump(mode="json")
    assert "set-fpl-token --replace" in value["error_action"]
    assert JobState(status="PENDING").model_dump(mode="json")["error_action"] is None
