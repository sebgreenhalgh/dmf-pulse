"""Safe public research surfaces; no activation or raw-data disclosure."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli import team_strength as cli
from dmf_pulse.cli.app import app
from dmf_pulse.evaluation.team_strength_replay import load_replay_golden
from dmf_pulse.football_events.team_strength_model import fit_team_strength
from dmf_pulse.football_events.team_strength_numerics import StrengthFitError
from tests.unit.football_events.team_strength_support import synthetic_dataset
from tests.unit.ingestion.openfootball.test_team_strength_data import STAMP

runner = CliRunner()


def command(name: str, root: Path) -> list[str]:
    return [
        "events",
        "team-strength",
        name,
        "--corpus-root",
        str(root / "synthetic-input"),
        "--private-artifact-root",
        str(root / "private-output"),
    ]


def test_reconstructed_fit_cli_uses_real_math_and_safe_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = synthetic_dataset()
    monkeypatch.setattr(
        cli, "load_reconstructed_corpus", lambda root: (dataset.fixture_registry, dataset.sources)
    )
    monkeypatch.setattr(
        cli,
        "fit_team_strength",
        lambda data: fit_team_strength(data, clock=lambda: STAMP + timedelta(seconds=1)),
    )
    result = runner.invoke(app, command("fit-reconstructed", tmp_path))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert (
        payload["status"] == "SHADOW_NOT_MODEL_INPUT" and payload["dataset_mode"] == "RECONSTRUCTED"
    )
    assert payload["eligible_matches"] == 6080 and payload["fitted_teams"] == 41
    assert payload["production_active"] is False and payload["current_live_refit_claimed"] is False
    assert "source_row_sha256" not in result.output and "effects" not in payload
    assert len(tuple((tmp_path / "private-output").rglob("*.json"))) == 1


def test_prevalidated_replay_aggregate_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli, "run_reconstructed_replay", lambda *args, **kwargs: load_replay_golden()
    )
    result = runner.invoke(app, command("replay", tmp_path))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["classification"] == "RECONSTRUCTED" and payload["fixtures"] == 380
    assert (
        payload["parameter_mixture_active"] is False
        and payload["historical_live_availability_claimed"] is False
    )
    assert "source_resources" not in payload and "model_state_sha256s" not in payload


@pytest.mark.parametrize(
    "error",
    [
        ValueError("sentinel-private-error"),
        OSError("sentinel-private-error"),
        StrengthFitError("sentinel-private-error"),
        RuntimeError("sentinel-private-error"),
    ],
)
def test_safe_failure_never_dumps_exception_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def fail(root: Path) -> None:
        raise error

    monkeypatch.setattr(cli, "load_reconstructed_corpus", fail)
    result = runner.invoke(app, command("fit-reconstructed", tmp_path))
    assert result.exit_code == 2
    assert "sentinel-private-error" not in result.output
    assert "error" in json.loads(result.output)


@pytest.mark.parametrize("name", ["fit-reconstructed", "replay"])
def test_no_raw_output_mode(tmp_path: Path, name: str) -> None:
    result = runner.invoke(app, [*command(name, tmp_path), "--output", "raw"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["code"] == "SHADOW_EVIDENCE_INVALID"
