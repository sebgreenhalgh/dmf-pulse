"""Non-disclosing Odds API credential diagnostic contract."""

from __future__ import annotations

import json
import logging

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.ingestion.odds.credentials import ODDS_API_ENVIRONMENT_VARIABLE

pytestmark = pytest.mark.unit
runner = CliRunner()


def _secret() -> str:
    return "F" * 32


@pytest.mark.parametrize(
    ("value", "configured"),
    ((None, False), ("", False), ("malformed", False), (_secret(), True)),
)
def test_credential_status_reports_only_boolean(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    value: str | None,
    configured: bool,
) -> None:
    if value is None:
        monkeypatch.delenv(ODDS_API_ENVIRONMENT_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(ODDS_API_ENVIRONMENT_VARIABLE, value)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)

    with caplog.at_level(logging.DEBUG):
        result = runner.invoke(
            app,
            ["ingest", "odds", "credential-status", "--output", "json"],
        )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"configured": configured}
    rendered = result.stdout + result.stderr + caplog.text
    if value:
        assert value not in rendered
    assert set(json.loads(result.stdout)) == {"configured"}


def test_credential_status_rejects_non_json_without_resolving_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = _secret()
    monkeypatch.setenv(ODDS_API_ENVIRONMENT_VARIABLE, secret)
    result = runner.invoke(
        app,
        ["ingest", "odds", "credential-status", "--output", "text"],
    )

    assert result.exit_code == 3
    assert secret not in result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "USAGE_INVALID"
