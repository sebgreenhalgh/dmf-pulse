"""Installed command options cannot enroll rights or select a production file ledger."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.dashboard.authorization import AuthorizationError
from dmf_pulse.dashboard.current_sources import (
    GuardedFplTransport,
    GuardedOddsTransport,
    GuardedScoreTransport,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "options",
    [
        ["--demo", "--current-demo"],
        ["--demo", "--refresh-approval", "UNENROLLED"],
        ["--current-demo", "--entry-id", "42"],
        ["--control-dir", "owned-only"],
        ["--entry-id", "42"],
        ["--deadline-at", "2026-10-31T11:00:00Z"],
        ["--refresh-approval", "UNENROLLED"],
        ["--refresh-approval", "UNENROLLED", "--entry-id", "42", "--deadline-at", "bad"],
        [
            "--refresh-approval",
            "UNENROLLED",
            "--entry-id",
            "42",
            "--deadline-at",
            "2026-10-31T11:00:00",
        ],
        [
            "--refresh-approval",
            "UNENROLLED",
            "--entry-id",
            "42",
            "--deadline-at",
            "2026-10-31T11:00:00Z",
        ],
    ],
)
def test_dashboard_invalid_or_unenrolled_options_do_not_start_server(monkeypatch, options):
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("server started"))
    result = CliRunner().invoke(app, ["dashboard", *options])
    assert result.exit_code == 2, result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("mode", ["default", "demo", "current-demo"])
def test_dashboard_command_source_labels_and_shutdown(tmp_path, monkeypatch, mode):
    import uvicorn

    module = importlib.import_module("dmf_pulse.dashboard.app")
    original = module.create_app
    runtimes, listeners = [], []

    def create_app(**kwargs):
        runtimes.append(kwargs["runtime"])
        return original(**kwargs)

    monkeypatch.setattr(module, "create_app", create_app)
    monkeypatch.setattr(uvicorn, "run", lambda application, **kwargs: listeners.append(kwargs))
    options = [] if mode == "default" else [f"--{mode}"]
    if mode == "current-demo":
        options += ["--control-dir", str(tmp_path)]
    result = CliRunner().invoke(app, ["dashboard", *options])
    assert result.exit_code == 0, result.output
    assert listeners[0]["host"] == "127.0.0.1" and not listeners[0]["access_log"]
    assert runtimes[0].synthetic_sources == (mode != "default")
    assert runtimes[0].refresh(1).error_code == "SESSION_CLOSED"
    if mode == "current-demo":
        assert "owned and injected" in result.output
        assert (tmp_path / "usage" / "identity.json").is_file()
    elif mode == "default":
        assert "rights-blocked" in result.output


@pytest.mark.parametrize(
    "provider,wrapper",
    [
        ("FPL", GuardedFplTransport),
        ("ODDS", GuardedOddsTransport),
        ("OPENFOOTBALL", GuardedScoreTransport),
    ],
)
def test_transport_denial_precedes_delegate_even_with_constructed_request(provider, wrapper):
    attempts = []

    class Guard:
        def before_send(self, *scope):
            attempts.append(scope)
            raise AuthorizationError("OWNED_TEST_DENIAL")

    class Delegate:
        def send(self, *args):
            pytest.fail("unauthorized delegate reached")

    request = SimpleNamespace(method="GET", host="owned.example", path="/owned")
    transport = wrapper(Guard(), Delegate())
    with pytest.raises(AuthorizationError, match="OWNED_TEST_DENIAL"):
        transport.send(request, "placeholder") if provider == "ODDS" else transport.send(request)
    assert attempts == [(provider, "GET", "owned.example", "/owned")]
