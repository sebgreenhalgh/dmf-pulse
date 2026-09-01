"""Operator UX proofs for the top-level one-command surface."""

from __future__ import annotations

from typer.testing import CliRunner

from dmf_pulse.cli.app import app

runner = CliRunner()


def test_pulse_help_exposes_only_the_entry_identifier() -> None:
    result = runner.invoke(app, ["pulse", "--help"])

    assert result.exit_code == 0
    assert "--entry-id" in result.stdout
    assert "token" not in result.stdout.casefold()
    assert "bootstrap" not in result.stdout.casefold()
    assert "fixtures" not in result.stdout.casefold()
    assert "score-prior" not in result.stdout.casefold()


def test_missing_odds_key_is_the_first_actionable_blocker(monkeypatch) -> None:
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    marker = "secret-that-must-not-appear"
    monkeypatch.setenv("DMF_FPL_BEARER_TOKEN", marker)

    result = runner.invoke(app, ["pulse", "--entry-id", "42"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "THE_ODDS_API_KEY is missing."
    assert marker not in result.output
    assert "Traceback" not in result.output
