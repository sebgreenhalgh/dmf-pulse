"""The top-level console delegates to the existing enrolled worker runtime."""

from types import SimpleNamespace

import pytest
from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner

from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.cli import pulse as pulse_module
from dmf_pulse.cli.app import app
from dmf_pulse.credentials.service import CredentialService

runner = CliRunner()


def test_help_offers_an_installed_approval_identifier_and_no_secret_input():
    result = runner.invoke(app, ["pulse", "--help"], color=False)
    assert result.exit_code == 0
    root = get_command(app)
    assert isinstance(root, TyperGroup)
    options = {
        option
        for parameter in root.commands["pulse"].params
        for option in getattr(parameter, "opts", ())
    }
    assert options == {"--entry-id", "--horizon-gameweeks", "--no-progress", "--refresh-approval"}


def test_no_approval_refuses_before_credential_resolution_or_worker(monkeypatch):
    monkeypatch.setattr(CredentialService, "resolve", lambda *a: pytest.fail("vault accessed"))
    monkeypatch.setattr(
        pulse_module, "run_enrolled_current", lambda **kw: pytest.fail("worker launched")
    )
    result = runner.invoke(app, ["pulse", "--entry-id", "42", "--no-progress"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "reviewed refresh approval is required" in result.stderr


def test_unenrolled_id_refuses_before_vault_or_current_source(monkeypatch):
    monkeypatch.setattr(CredentialService, "resolve", lambda *a: pytest.fail("vault accessed"))
    result = runner.invoke(app, ["pulse", "--entry-id", "42", "--refresh-approval", "NOT-ENROLLED"])
    assert result.exit_code == 2
    assert "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED" in result.stderr
    assert "Traceback" not in result.output


@pytest.mark.parametrize("horizon", [1, 3])
@pytest.mark.parametrize("no_progress", [False, True])
def test_valid_console_delegates_scope_and_publishes_runtime_report(
    monkeypatch, horizon, no_progress
):
    calls = []

    def run(**kwargs):
        calls.append(kwargs)
        if kwargs["progress"] is not None:
            kwargs["progress"]("FPL state ready")
        kwargs["publish"](SimpleNamespace(team=SimpleNamespace(report="VALIDATED REPORT")))

    monkeypatch.setattr(pulse_module, "run_enrolled_current", run)
    args = [
        "pulse",
        "--entry-id",
        "42",
        "--refresh-approval",
        "OWNED-TEST",
        "--horizon-gameweeks",
        str(horizon),
    ]
    if no_progress:
        args.append("--no-progress")
    result = runner.invoke(app, args)
    assert result.exit_code == 0
    assert result.stdout == "VALIDATED REPORT\n"
    assert result.stderr == ("" if no_progress else "FPL state ready\n")
    assert calls[0]["entry_id"] == 42
    assert calls[0]["horizon"] == horizon
    assert calls[0]["authorization_id"] == "OWNED-TEST"
    assert set(calls[0]) == {"entry_id", "horizon", "authorization_id", "publish", "progress"}


@pytest.mark.parametrize("horizon", [0, 2, 4, -1])
def test_invalid_horizon_cannot_launch_worker(monkeypatch, horizon):
    monkeypatch.setattr(pulse_module, "run_enrolled_current", lambda **kw: pytest.fail("launched"))
    result = runner.invoke(app, ["pulse", "--entry-id", "42", "--horizon-gameweeks", str(horizon)])
    assert result.exit_code == 2
    assert "must be exactly 1 or 3" in result.stderr


def test_injected_authorization_error_cannot_echo_raw_message(monkeypatch):
    marker = "synthetic-private-canary-never-output"

    def deny(**kwargs):
        raise AuthorizationError(marker)

    monkeypatch.setattr(pulse_module, "run_enrolled_current", deny)
    result = runner.invoke(app, ["pulse", "--entry-id", "42", "--refresh-approval", "OWNED-TEST"])
    assert result.exit_code == 2
    assert marker not in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "code,action",
    [
        ("QUALIFIED_QUOTA_EVIDENCE_STALE", "remaining-credit evidence"),
        ("AUTHORIZATION_DEADLINE_INVALID", "official deadline evidence"),
        ("USAGE_LEDGER_SCHEMA_NOT_READY", "control migration"),
        ("SOURCE_PROFILE_CHANGED", "provider terms/profile"),
        ("OFFICIAL_DEADLINE_SCOPE_MISMATCH", "target Gameweek"),
        ("CREDENTIAL_EXPIRED", "set-fpl-token --replace"),
    ],
)
def test_known_operational_blocker_keeps_typed_reason_and_required_action(
    monkeypatch, code, action
):
    def deny(**kwargs):
        raise AuthorizationError(code)

    monkeypatch.setattr(pulse_module, "run_enrolled_current", deny)
    result = runner.invoke(app, ["pulse", "--entry-id", "42", "--refresh-approval", "OWNED-TEST"])
    assert result.exit_code == 2 and result.stdout == ""
    assert code in result.stderr and action in result.stderr
