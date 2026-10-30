"""Shared-runtime console and explicit CLI metadata boundaries, all owned/injected."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from dmf_pulse.dashboard.authorization import AuthorizationError
from dmf_pulse.dashboard.runtime import JobState
from dmf_pulse.operation import console
from dmf_pulse.operation.cli import operation_app
from dmf_pulse.operation.control import ControlRecoveryRequest, ControlSetupRequest
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.packages import OwnerPackage, read_metadata

pytestmark = pytest.mark.unit


class Runtime:
    def __init__(self, *, terminal="COMPLETE", view=None):
        self.calls = []
        self.terminal = terminal
        self._view = view or SimpleNamespace(
            dataset_mode="PRIVATE_TRANSIENT", gameweeks=(10,), job_id="a" * 32
        )

    def refresh(self, horizon):
        self.calls.append("refresh")
        return JobState(status="RUNNING", job_id="a" * 32, stages=("Starting",))

    def tick(self):
        self.calls.append("tick")
        return JobState(
            status=self.terminal,
            job_id="a" * 32,
            error_code=None if self.terminal == "COMPLETE" else "AUTHORIZATION_EXPIRED",
        )

    def view(self):
        self.calls.append("view")
        return self._view

    def close(self):
        self.calls.append("close")


def test_console_drives_existing_runtime_once_and_publishes_only_after_checked_view():
    runtime = Runtime()
    publications, progress = [], []
    receipt = console.publish_runtime(
        runtime,
        horizon=1,
        publish=publications.append,
        progress=progress.append,
        wait=lambda _: None,
    )
    assert runtime.calls == ["refresh", "tick", "view", "close"]
    assert publications == [runtime._view] and progress == ["Starting"]
    assert receipt.dataset_mode == "PRIVATE_TRANSIENT" and not receipt.production_active
    assert not any(
        field in type(receipt).model_fields
        for field in ("report", "players", "token", "quota", "decision")
    )


@pytest.mark.parametrize("terminal", ["BLOCKED", "EXPIRED", "CANCELLED"])
def test_console_failure_never_publishes_and_always_closes(terminal):
    runtime = Runtime(terminal=terminal)
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_EXPIRED"):
        console.publish_runtime(
            runtime,
            horizon=1,
            publish=lambda _: pytest.fail("blocked publication"),
            wait=lambda _: None,
        )
    assert runtime.calls == ["refresh", "tick", "close"]


@pytest.mark.parametrize("attack", ["wrong_job", "wrong_horizon", "wrong_mode", "missing_view"])
def test_console_rejects_inconsistent_publication(attack):
    runtime = Runtime()
    if attack == "wrong_job":
        runtime._view.job_id = "b" * 32
    elif attack == "wrong_horizon":
        runtime._view.gameweeks = (1, 2, 3)
    elif attack == "wrong_mode":
        runtime._view.dataset_mode = "SYNTHETIC_DEMONSTRATION"
    else:
        runtime._view = None
    with pytest.raises(AuthorizationError, match="RUN_OR_PUBLICATION_INVALID"):
        console.publish_runtime(
            runtime,
            horizon=1,
            publish=lambda _: pytest.fail("invalid publication"),
            wait=lambda _: None,
        )
    assert runtime.calls[-1] == "close"


def test_console_callback_failure_and_keyboard_interrupt_close_runtime():
    for failure in (OperationError("OWNED_CALLBACK_FAILURE"), KeyboardInterrupt()):
        runtime = Runtime()

        def publish(_, failure=failure):
            raise failure

        with pytest.raises(type(failure)):
            console.publish_runtime(runtime, horizon=1, publish=publish, wait=lambda _: None)
        assert runtime.calls[-1] == "close"


def test_console_elapsed_guard_closes_even_if_runtime_never_finishes():
    runtime = Runtime()
    times = iter((0.0, 900.0))
    with pytest.raises(AuthorizationError, match="RUN_TIMEOUT"):
        console.publish_runtime(
            runtime,
            horizon=1,
            publish=lambda _: pytest.fail("timed-out publication"),
            elapsed=lambda: next(times),
            wait=lambda _: None,
        )
    assert runtime.calls == ["refresh", "close"]


@pytest.mark.parametrize("horizon", [True, 0, 2, 4, "1"])
def test_console_strict_horizon_rejects_before_refresh(horizon):
    runtime = Runtime()
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_HORIZON_NOT_APPROVED"):
        console.publish_runtime(runtime, horizon=horizon, publish=lambda _: None)
    assert runtime.calls == ["close"]


def test_enrolled_console_default_denies_before_session_worker_or_credentials(monkeypatch):
    monkeypatch.setattr(console, "production_approvals", lambda: ())
    monkeypatch.setattr(
        console.CurrentRefreshSession,
        "enrolled",
        lambda **_: pytest.fail("unapproved console created a session"),
    )
    with pytest.raises(AuthorizationError, match="RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED"):
        console.run_enrolled_current(
            authorization_id="not-enrolled",
            entry_id=42,
            horizon=1,
            publish=lambda _: pytest.fail("unapproved publication"),
        )


def test_status_cli_is_read_free_until_explicit_credential_option(monkeypatch):
    from dmf_pulse.credentials.service import CredentialService, CredentialStatus

    calls = []

    def status(self, provider):
        calls.append(provider)
        return CredentialStatus(True, "CONFIGURED")

    monkeypatch.setattr(CredentialService, "status", status)
    app = typer.Typer()
    app.add_typer(operation_app, name="operation")
    initial = CliRunner().invoke(app, ["operation", "status"])
    assert initial.exit_code == 0 and calls == []
    assert all(
        row["state"] == "NOT_CHECKED" for row in json.loads(initial.stdout)["payload"]["checks"]
    )
    explicit = CliRunner().invoke(app, ["operation", "status", "--check-credentials"])
    assert explicit.exit_code == 0 and calls == ["odds", "fpl"]
    rows = json.loads(explicit.stdout)["payload"]["checks"]
    assert rows[1]["state"] == "VERIFIED" and all(row["state"] == "NOT_CHECKED" for row in rows[2:])


def test_owner_package_command_creates_immutable_pending_package(tmp_path):
    output = tmp_path / "owner.json"
    response = CliRunner().invoke(
        operation_app,
        [
            "prepare-pilot",
            "--authorization-id",
            "ACCEL004-PILOT-owned-test",
            "--output",
            str(output),
        ],
    )
    assert response.exit_code == 0, response.output
    result = json.loads(response.stdout)
    assert result["runtime_authority"] == "NOT_GRANTED" and result["state"] == "INCOMPLETE"
    package = read_metadata(output, OwnerPackage)
    assert package.proposal.entry_id is None and package.proposal.plan_quota is None
    again = CliRunner().invoke(
        operation_app,
        [
            "prepare-pilot",
            "--authorization-id",
            "ACCEL004-PILOT-owned-test",
            "--output",
            str(output),
        ],
    )
    assert again.exit_code == 2 and "OPERATOR_ARTIFACT_WRITE_FAILED" in again.output


@pytest.mark.parametrize(
    "command",
    [
        ["validate-installed", "--refresh-approval", "not-enrolled", "--entry-id", "42"],
        ["prepare-pilot", "--authorization-id", "A02-consumed", "--output", "never-created.json"],
        [
            "recover-control",
            "--request",
            "missing-owned-request.json",
            "--output",
            "never-created.json",
        ],
    ],
)
def test_cli_errors_are_bounded_and_do_not_claim_success(command, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response = CliRunner().invoke(operation_app, command)
    assert response.exit_code == 2
    assert "Traceback" not in response.output and "ValidationError" not in response.output
    assert not (tmp_path / "never-created.json").exists()


@pytest.mark.parametrize("recover", [False, True])
def test_prepare_control_cli_creates_metadata_only_and_requires_explicit_permission(
    tmp_path, recover
):
    path = tmp_path / "control-request.json"
    args = [
        "prepare-control",
        "--account-ref",
        "owned-account",
        "--operator-ref",
        "owned-operator",
        "--control-evidence",
        "a" * 64,
        "--output",
        str(path),
        "--owned-synthetic",
    ]
    if recover:
        args += ["--ledger-id", "b" * 64]
    denied = CliRunner().invoke(operation_app, args)
    assert denied.exit_code == 2 and not path.exists()
    response = CliRunner().invoke(operation_app, [*args, "--approve-control-metadata"])
    assert response.exit_code == 0, response.output
    contract = ControlRecoveryRequest if recover else ControlSetupRequest
    request = read_metadata(path, contract)
    assert (
        request.classification == "OWNED_SYNTHETIC"
        and request.database_ref == "SYNTHETIC_TEST_DATABASE"
    )
    assert json.loads(response.stdout)["provider_authority"] == "NOT_GRANTED"
