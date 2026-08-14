import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.events import events_app

pytestmark = pytest.mark.integration
RUNNER = CliRunner()
FIXTURES = Path("fixtures/events/score/GCS-008")


def test_score_distribution_cli_persists_and_reuses_artifact(tmp_path: Path) -> None:
    arguments = [
        "score-distribution",
        "--fixture",
        str(FIXTURES / "balanced_fixture.json"),
        "--artifact-root",
        str(tmp_path),
        "--output",
        "json",
    ]
    first = RUNNER.invoke(events_app, arguments)
    second = RUNNER.invoke(events_app, arguments)
    assert first.exit_code == 0, first.stdout
    assert second.exit_code == 0, second.stdout
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload == second_payload
    artifact = Path(first_payload["artifact_path"])
    assert artifact.exists()
    assert first_payload["result"]["distribution"]["result_sha256"] == (
        "31d41317c0cf06002edd8e8fb47c4702706661f2227304182e3c4b8995e06b7e"
    )


def test_explain_market_fit_cli_reports_measured_residuals() -> None:
    result = RUNNER.invoke(
        events_app,
        [
            "explain-market-fit",
            "--fixture",
            str(FIXTURES / "balanced_fixture.json"),
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "score-market-fit-explanation-v1"
    assert len(payload["market_residuals"]) == 4
    assert payload["diagnostics"]["solver_converged"] is True
    assert payload["source_minutes_context_sha256"]
    assert payload["source_home_minutes_sha256"]
    assert payload["source_away_minutes_sha256"]


def test_postponed_fixture_cli_blocks_without_plausible_output() -> None:
    result = RUNNER.invoke(
        events_app,
        [
            "score-distribution",
            "--fixture",
            str(FIXTURES / "postponed_fixture.json"),
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["result"]["status"] == "BLOCKED"
    assert payload["result"]["distribution"] is None
    assert payload["result"]["error_code"] == "FIXTURE_POSTPONED"


def test_evaluation_cli_scores_frozen_artifact(tmp_path: Path) -> None:
    build = RUNNER.invoke(
        events_app,
        [
            "score-distribution",
            "--fixture",
            str(FIXTURES / "balanced_fixture.json"),
            "--artifact-root",
            str(tmp_path),
            "--output",
            "json",
        ],
    )
    artifact = json.loads(build.stdout)["artifact_path"]
    result = RUNNER.invoke(
        events_app,
        [
            "evaluate",
            "--distribution",
            artifact,
            "--home-goals",
            "2",
            "--away-goals",
            "1",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["home_goals"] == 2
    assert payload["away_goals"] == 1
    assert payload["exact_score_log_loss"] != "0.000000"
