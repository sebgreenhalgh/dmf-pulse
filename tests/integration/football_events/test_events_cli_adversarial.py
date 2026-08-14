import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.events import events_app
from dmf_pulse.football_events._decimal import canonical_json_sha256

pytestmark = pytest.mark.integration
RUNNER = CliRunner()
FIXTURES = Path("fixtures/events/score/GCS-008")


def test_invalid_output_and_invalid_request_are_typed(tmp_path: Path) -> None:
    invalid_output = RUNNER.invoke(
        events_app,
        [
            "score-distribution",
            "--fixture",
            str(FIXTURES / "balanced_fixture.json"),
            "--output",
            "text",
        ],
    )
    assert invalid_output.exit_code == 2
    assert json.loads(invalid_output.stdout)["error"]["code"] == "USAGE_INVALID"
    invalid_request = tmp_path / "invalid.json"
    invalid_request.write_text("{}", encoding="utf-8")
    invalid = RUNNER.invoke(
        events_app,
        ["score-distribution", "--fixture", str(invalid_request), "--output", "json"],
    )
    assert invalid.exit_code == 2
    assert json.loads(invalid.stdout)["error"]["code"] == "REQUEST_INVALID"


def test_explanation_blocks_postponed_fixture() -> None:
    result = RUNNER.invoke(
        events_app,
        [
            "explain-market-fit",
            "--fixture",
            str(FIXTURES / "postponed_fixture.json"),
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "FIXTURE_POSTPONED"


def test_validate_command_accepts_valid_and_rejects_mutated_artifact(tmp_path: Path) -> None:
    build = RUNNER.invoke(
        events_app,
        [
            "score-distribution",
            "--fixture",
            str(FIXTURES / "balanced_fixture.json"),
            "--artifact-root",
            str(tmp_path),
        ],
    )
    artifact = Path(json.loads(build.stdout)["artifact_path"])
    valid = RUNNER.invoke(events_app, ["validate", "--distribution", str(artifact)])
    assert valid.exit_code == 0
    assert json.loads(valid.stdout)["status"] == "VALID"
    body = json.loads(artifact.read_text(encoding="utf-8"))
    body["result_sha256"] = "0" * 64
    artifact.write_text(json.dumps(body), encoding="utf-8")
    invalid = RUNNER.invoke(events_app, ["validate", "--distribution", str(artifact)])
    assert invalid.exit_code == 2
    assert json.loads(invalid.stdout)["error"]["code"] == "ARTIFACT_INVALID"


def test_validate_rejects_self_hashed_market_fit_claim_that_disagrees_with_matrix(
    tmp_path: Path,
) -> None:
    build = RUNNER.invoke(
        events_app,
        [
            "score-distribution",
            "--fixture",
            str(FIXTURES / "balanced_fixture.json"),
            "--artifact-root",
            str(tmp_path),
        ],
    )
    artifact = Path(json.loads(build.stdout)["artifact_path"])
    body = json.loads(artifact.read_text(encoding="utf-8"))
    body["market_residuals"][0].update(
        {
            "projected_probability": "0.900000000000",
            "residual": "0.100000000000",
            "standardized_residual": "5.000000",
            "target_probability": "0.800000000000",
        }
    )
    body_without_hash = dict(body)
    body_without_hash.pop("result_sha256")
    body["result_sha256"] = canonical_json_sha256(body_without_hash)
    artifact.write_text(json.dumps(body), encoding="utf-8")

    invalid = RUNNER.invoke(events_app, ["validate", "--distribution", str(artifact)])
    assert invalid.exit_code == 2
    payload = json.loads(invalid.stdout)
    assert payload["error"]["code"] == "ARTIFACT_INVALID"


def test_evaluation_outside_support_is_typed(tmp_path: Path) -> None:
    build = RUNNER.invoke(
        events_app,
        [
            "score-distribution",
            "--fixture",
            str(FIXTURES / "balanced_fixture.json"),
            "--artifact-root",
            str(tmp_path),
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
            "99",
            "--away-goals",
            "0",
        ],
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "EVALUATION_INVALID"


def test_score_distribution_cli_rejects_post_cutoff_stage7_minutes(
    tmp_path: Path,
) -> None:
    payload = json.loads((FIXTURES / "balanced_fixture.json").read_text(encoding="utf-8"))
    for side in ("home", "away"):
        payload["minutes_context"][side]["as_of"] = "2026-08-20T12:00:01Z"
    invalid = tmp_path / "post-cutoff-minutes.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    result = RUNNER.invoke(
        events_app,
        ["score-distribution", "--fixture", str(invalid), "--output", "json"],
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "REQUEST_INVALID"
