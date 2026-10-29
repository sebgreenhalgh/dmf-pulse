"""Installed dashboard checks tolerate Rich styling but require a real bool flag."""

from __future__ import annotations

import importlib
import json
import runpy
from pathlib import Path
from typing import Any

import pytest
import typer
from rich.console import Console
from typer import rich_utils
from typer.testing import CliRunner

pytestmark = pytest.mark.unit


@pytest.fixture
def verifier(repository_root: Path) -> dict[str, Any]:
    return runpy.run_path(str(repository_root / "scripts/verify_wheel.py"))


def _valid_dashboard(calls: list[bool]) -> typer.Typer:
    app = typer.Typer()

    @app.command("dashboard")
    def dashboard(demo: bool = False) -> None:
        calls.append(demo)

    # A second command retains the same group/subcommand structure as dmf.
    @app.command("other")
    def other() -> None:
        raise AssertionError("parser verification must not invoke callbacks")

    return app


def test_github_actions_rich_help_can_split_the_demo_option(
    verifier: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []

    def terminal_console(**kwargs: Any) -> Console:
        # Exercise genuine Rich SGR rendering on every OS, including Windows
        # where the legacy console otherwise consumes styling before capture.
        kwargs.update(force_terminal=True, color_system="standard", legacy_windows=False)
        return Console(**kwargs)

    monkeypatch.setattr(rich_utils, "Console", terminal_console)
    result = CliRunner().invoke(_valid_dashboard(calls), ["dashboard", "--help"], color=True)
    assert result.exit_code == 0
    assert "\x1b[" in result.stdout
    assert "--demo" not in result.stdout  # Reproduces the former verifier failure.
    verifier["_require_dashboard_demo_help"](result.stdout)
    assert calls == []


def test_plain_help_accepts_the_complete_option(verifier: dict[str, Any]) -> None:
    verifier["_require_dashboard_demo_help"]("Options: --demo  --no-demo  --help")


@pytest.mark.parametrize("help_text", ["", "--demonstration", "--demo-extra", "--no-demo"])
def test_help_rejects_a_missing_or_different_demo_option(
    verifier: dict[str, Any], help_text: str
) -> None:
    with pytest.raises(verifier["VerificationError"], match="missing its demo option"):
        verifier["_require_dashboard_demo_help"](help_text)


def test_installed_parser_probe_checks_values_without_starting_the_server(
    verifier: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[bool] = []
    module = importlib.import_module("dmf_pulse.cli.app")
    monkeypatch.setattr(module, "app", _valid_dashboard(calls))
    exec(verifier["_DASHBOARD_PARSER_PROBE"], {})
    assert json.loads(capsys.readouterr().out) == {
        "demo": True,
        "no_demo": False,
        "unknown_option_rejected": True,
    }
    assert calls == []


@pytest.mark.parametrize("kind", ["missing", "different-name", "value-option", "allows-unknown"])
def test_installed_parser_probe_rejects_a_missing_or_wrong_option(
    verifier: dict[str, Any], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    calls: list[object] = []
    app = typer.Typer()
    if kind == "missing":

        @app.command("dashboard")
        def missing() -> None:
            calls.append(True)

    elif kind == "different-name":

        @app.command("dashboard")
        def different(simulation: bool = False) -> None:
            calls.append(simulation)

    elif kind == "value-option":

        @app.command("dashboard")
        def value_option(demo: str = "default") -> None:
            calls.append(demo)

    else:

        @app.command(
            "dashboard", context_settings={"ignore_unknown_options": True, "allow_extra_args": True}
        )
        def allows_unknown(demo: bool = False) -> None:
            calls.append(demo)

    @app.command("other")
    def other() -> None:
        calls.append(True)

    module = importlib.import_module("dmf_pulse.cli.app")
    monkeypatch.setattr(module, "app", app)
    with pytest.raises(Exception) as raised:
        exec(verifier["_DASHBOARD_PARSER_PROBE"], {})
    assert (
        type(raised.value).__name__
        == {
            "missing": "NoSuchOption",
            "different-name": "NoSuchOption",
            "value-option": "BadOptionUsage",
            "allows-unknown": "RuntimeError",
        }[kind]
    )
    assert calls == []
