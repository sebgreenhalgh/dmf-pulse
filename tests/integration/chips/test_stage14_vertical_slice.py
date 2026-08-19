from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.chips.artifacts import (
    load_decision_artifact,
    persist_decision_artifact,
    seal_decision_artifact,
)
from dmf_pulse.chips.replay import ChipReplayRequest, replay_chip_policy
from dmf_pulse.chips.service import evaluate_chip_opportunities
from dmf_pulse.chips.service_models import ChipServiceRequest
from dmf_pulse.cli.chips import chips_app

pytestmark = pytest.mark.integration

FIXTURE_ROOT = Path("fixtures/chips/stage14")
runner = CliRunner()


def test_service_artifact_cli_vertical_slice_has_one_semantic_answer(tmp_path: Path) -> None:
    request = ChipServiceRequest.model_validate_json(
        (FIXTURE_ROOT / "service_request.json").read_bytes()
    )
    expected = evaluate_chip_opportunities(request)
    artifact = seal_decision_artifact(request, expected)
    path = persist_decision_artifact(artifact, artifact_root=tmp_path)

    loaded = load_decision_artifact(path)
    compare = runner.invoke(
        chips_app,
        ["compare", "--input", str(FIXTURE_ROOT / "service_request.json")],
    )
    schedule = runner.invoke(
        chips_app,
        ["schedule", "--input", str(FIXTURE_ROOT / "service_request.json")],
    )
    validate = runner.invoke(chips_app, ["validate", "--artifact", str(path)])

    assert loaded.decision_set == expected
    assert compare.exit_code == schedule.exit_code == validate.exit_code == 0
    assert json.loads(compare.stdout)["decision_set_hash"] == expected.decision_set_hash
    assert json.loads(schedule.stdout)["policy_hash"] == expected.schedule_policy.policy_hash
    assert json.loads(validate.stdout)["artifact_hash"] == artifact.artifact_hash


def test_replay_cli_and_library_freeze_same_root_only_trajectory(tmp_path: Path) -> None:
    request = ChipReplayRequest.model_validate_json(
        (FIXTURE_ROOT / "replay_request.json").read_bytes()
    )

    expected = replay_chip_policy(request, artifact_root=tmp_path / "library")
    cli = runner.invoke(
        chips_app,
        [
            "backtest",
            "--input",
            str(FIXTURE_ROOT / "replay_request.json"),
            "--artifact-root",
            str(tmp_path / "cli"),
        ],
    )

    assert cli.exit_code == 0
    payload = json.loads(cli.stdout)
    assert payload["result_hash"] == expected.result_hash
    assert [item["executed_action"] for item in payload["steps"]] == ["WAIT", "USE"]
    assert all(item["advisory_schedule_not_executed"] for item in payload["steps"])
    assert len(list((tmp_path / "library").rglob("*.json"))) == 2
    assert len(list((tmp_path / "cli").rglob("*.json"))) == 2
