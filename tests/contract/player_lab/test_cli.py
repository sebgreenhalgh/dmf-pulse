"""Two-phase owned exports and fail-closed external input through installed APIs."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.player_lab import player_lab_app
from dmf_pulse.player_lab.contracts import seal
from dmf_pulse.player_lab.runner import freeze_owned_cohort, operational_synthetic_evaluation

pytestmark = pytest.mark.contract


def test_export_freeze_then_labels_then_score_and_demo_match(tmp_path):
    runner = CliRunner()
    cohort, labels, report = (
        tmp_path / name for name in ("cohort.json", "labels.json", "report.json")
    )
    for args in (
        ["freeze-owned", "--output", str(cohort)],
        ["labels-owned", "--cohort", str(cohort), "--output", str(labels)],
        ["score", "--cohort", str(cohort), "--labels", str(labels), "--output", str(report)],
    ):
        result = runner.invoke(player_lab_app, args)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["status"] == "WRITTEN"
    expected = operational_synthetic_evaluation().model_dump(mode="json")
    assert json.loads(report.read_bytes()) == expected
    assert json.loads(runner.invoke(player_lab_app, ["demo"]).output) == expected
    original = cohort.read_bytes()
    denied = runner.invoke(player_lab_app, ["freeze-owned", "--output", str(cohort)])
    assert denied.exit_code == 2
    assert cohort.read_bytes() == original


@pytest.mark.parametrize(
    "body",
    [b"private-source-input", b'{"x":1,"x":2}', b"[" * 1100 + b"]" * 1100, b"x" * 4_000_001],
    ids=["malformed", "duplicate-key", "deep", "oversize"],
)
def test_unqualified_malformed_duplicate_oversize_input_never_writes(body, tmp_path):
    path, output = tmp_path / "bad.json", tmp_path / "no-write.json"
    path.write_bytes(body)
    result = CliRunner().invoke(
        player_lab_app, ["labels-owned", "--cohort", str(path), "--output", str(output)]
    )
    assert result.exit_code == 2
    assert "PLAYER_COHORT_INVALID_OR_UNQUALIFIED" in result.output
    assert "private-source-input" not in result.output
    assert not output.exists()


def test_self_resealed_forecast_metadata_is_not_original_custody(tmp_path):
    phase = freeze_owned_cohort()
    original = phase.cohort
    changed_protocol = seal(
        original.protocol.model_copy(update={"cohort_id": "posthoc-private-wrapper"})
    )
    changed = seal(original.model_copy(update={"protocol": changed_protocol}))
    cohort, output = tmp_path / "cohort.json", tmp_path / "never.json"
    cohort.write_text(changed.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        player_lab_app, ["labels-owned", "--cohort", str(cohort), "--output", str(output)]
    )
    assert result.exit_code == 2 and not output.exists()
    assert "posthoc-private-wrapper" not in result.output


def test_wrong_labels_cannot_emit_report_and_missing_file_is_typed(tmp_path):
    runner = CliRunner()
    cohort, labels, output = (
        tmp_path / name for name in ("cohort.json", "labels.json", "never.json")
    )
    assert runner.invoke(player_lab_app, ["freeze-owned", "--output", str(cohort)]).exit_code == 0
    assert (
        runner.invoke(
            player_lab_app, ["labels-owned", "--cohort", str(cohort), "--output", str(labels)]
        ).exit_code
        == 0
    )
    payload = json.loads(labels.read_bytes())
    payload["forecast_cohort_sha256"] = "0" * 64
    labels.write_text(json.dumps(payload), encoding="utf-8")
    result = runner.invoke(
        player_lab_app,
        ["score", "--cohort", str(cohort), "--labels", str(labels), "--output", str(output)],
    )
    assert result.exit_code == 2 and not output.exists()
    result = runner.invoke(
        player_lab_app,
        ["score", "--cohort", str(tmp_path / "absent.json"), "--labels", str(labels)],
    )
    assert result.exit_code == 2 and "PLAYER_COHORT_INVALID_OR_UNQUALIFIED" in result.output


def test_cli_freeze_stdout_contains_no_outcomes_and_proposal_never_authorizes():
    runner = CliRunner()
    result = runner.invoke(player_lab_app, ["freeze-owned"])
    payload = json.loads(result.output)
    assert "labels" not in payload and "outcomes" not in payload
    assert len(payload["forecasts"]) == 16
    proposal = json.loads(runner.invoke(player_lab_app, ["proposal"]).output)
    assert proposal["execution_authorized"] is proposal["freeze_attempted"] is False
