"""Owned native formation -> authenticated output -> temporal features -> CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from dmf_pulse.cli.player_evidence import player_evidence_app
from dmf_pulse.player_evidence.wyscout import owned_wyscout_demo

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("before_release", [False, True])
def test_cli_uses_complete_owned_pipeline_with_explicit_vintage_and_denominators(
    before_release, monkeypatch
):
    import dmf_pulse.availability.pipeline as accepted

    def denied(*_, **__):
        pytest.fail("offline adapter invoked a write, fit or production prediction")

    monkeypatch.setattr(Path, "write_bytes", denied)
    monkeypatch.setattr(Path, "write_text", denied)
    monkeypatch.setattr(accepted, "fit_projection_artifact", denied)
    monkeypatch.setattr(accepted, "predict_minutes_baseline", denied)
    app = typer.Typer()
    app.add_typer(player_evidence_app, name="player-evidence")
    response = CliRunner().invoke(
        app, ["player-evidence", "wyscout-demo", *(["--before-release"] if before_release else [])]
    )
    assert response.exit_code == 0, response.output
    body = json.loads(response.stdout)
    expected = owned_wyscout_demo(
        cutoff=datetime(2018, 5, 1, tzinfo=UTC) if before_release else None
    )
    assert body.pop("semantic_sha256") == expected.semantic_sha256
    assert body == expected.model_dump(mode="json")
    assert body["mode"] == "SYNTHETIC"
    assert body["features"]["production_activation"] is False
    assert (
        body["features"]["predictive_uncertainty_status"] == "NOT_ESTIMATED_EMPIRICAL_SUPPORT_ONLY"
    )
    assert sum(row["selected_count"] for row in body["features"]["players"]) == (
        0 if before_release else 8
    )
