from __future__ import annotations

import json

from typer.testing import CliRunner

from dmf_pulse.cli.app import app


def test_cli_stable_fixture(monkeypatch) -> None:
    monkeypatch.setenv("DMF_ENVIRONMENT", "TEST")
    result = CliRunner().invoke(
        app,
        [
            "availability",
            "predict",
            "--fixture-external-provider",
            "synthetic_availability",
            "--fixture-external-id",
            "701",
            "--season-code",
            "2026/27",
            "--team-side",
            "HOME",
            "--as-of",
            "2026-08-14T17:30:00Z",
            "--model-key",
            "min007-baseline-v1",
            "--seed",
            "MIN-007-COHERENCE-V1",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["status"] == "PROJECTED"
