from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.private_v1.errors import PrivateV1Error


def test_private_v1_run_and_replay_are_public_commands() -> None:
    runner = CliRunner()
    root = runner.invoke(app, ["private-v1", "--help"])
    run = runner.invoke(app, ["private-v1", "run", "--help"])
    replay = runner.invoke(app, ["private-v1", "replay", "--help"])

    assert root.exit_code == run.exit_code == replay.exit_code == 0
    assert "run" in root.stdout
    assert "replay" in root.stdout

    root_command = get_command(app)
    assert isinstance(root_command, TyperGroup)
    private_command = root_command.commands["private-v1"]
    assert isinstance(private_command, TyperGroup)
    run_options = {
        option
        for parameter in private_command.commands["run"].params
        for option in getattr(parameter, "opts", ())
    }
    replay_options = {
        option
        for parameter in private_command.commands["replay"].params
        for option in getattr(parameter, "opts", ())
    }
    assert {"--input", "--freeze-dir", "--output"} <= run_options
    assert {"--bundle", "--output"} <= replay_options


def test_private_v1_cli_rejects_malformed_input_without_disclosure(tmp_path: Path) -> None:
    source = tmp_path / "private.json"
    source.write_text('{"schema_version":"wrong"}', encoding="utf-8")

    result = CliRunner().invoke(app, ["private-v1", "run", "--input", str(source)])

    assert result.exit_code == 2
    assert "PRIVATE_INPUT_INVALID" in result.stdout
    assert str(source) not in result.stdout


def test_private_v1_cli_rejects_real_freeze_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _Execution:
        retention_class = "REAL_TRANSIENT_ONLY"

    def _unexpected_run(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("execution must not begin")

    monkeypatch.setattr("dmf_pulse.cli.private_v1.load_execution_input", lambda path: _Execution())
    monkeypatch.setattr(
        "dmf_pulse.cli.private_v1.PrivateV1RecommendationService.run", _unexpected_run
    )
    source = tmp_path / "private.json"
    source.write_text("{}", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "private-v1",
            "run",
            "--input",
            str(source),
            "--freeze-dir",
            str(tmp_path / "bundle"),
        ],
    )

    assert result.exit_code == 2
    assert "REPLAY_RETENTION_FORBIDDEN" in result.stdout


def test_private_v1_cli_emits_machine_json_and_report_bundle_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    execution = SimpleNamespace(retention_class="SYNTHETIC_REPLAY_ALLOWED")
    decision = {"schema_version": "private-v1-decision-v1", "status": "SUCCESS"}
    run = SimpleNamespace(decision=decision, report="PRIVATE REPORT\n")
    monkeypatch.setattr("dmf_pulse.cli.private_v1.load_execution_input", lambda path: execution)
    monkeypatch.setattr(
        "dmf_pulse.cli.private_v1.PrivateV1RecommendationService.run",
        lambda self, value: run,
    )
    monkeypatch.setattr(
        "dmf_pulse.cli.private_v1.write_synthetic_replay_bundle",
        lambda *args: SimpleNamespace(manifest_sha256="a" * 64),
    )
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")

    machine = CliRunner().invoke(
        app,
        ["private-v1", "run", "--input", str(source), "--output", "json"],
    )
    bundle = tmp_path / "bundle"
    report = CliRunner().invoke(
        app,
        ["private-v1", "run", "--input", str(source), "--freeze-dir", str(bundle)],
    )

    assert machine.exit_code == report.exit_code == 0
    assert json.loads(machine.stdout) == decision
    assert report.stdout.startswith("PRIVATE REPORT\n")
    assert f"Replay manifest: {'a' * 64}" in report.stdout
    assert f"dmf private-v1 replay --bundle {bundle}" in report.stdout


def test_private_v1_cli_replay_supports_both_outputs_and_typed_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    decision = {"schema_version": "private-v1-decision-v1", "status": "SUCCESS"}
    replay = SimpleNamespace(
        run=SimpleNamespace(decision=decision, report="REPLAY REPORT\n"),
        manifest_sha256="b" * 64,
    )
    monkeypatch.setattr(
        "dmf_pulse.cli.private_v1.PrivateV1RecommendationService.replay",
        lambda self, path: replay,
    )
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    machine = CliRunner().invoke(
        app,
        ["private-v1", "replay", "--bundle", str(bundle), "--output", "json"],
    )
    report = CliRunner().invoke(
        app,
        ["private-v1", "replay", "--bundle", str(bundle)],
    )

    assert machine.exit_code == report.exit_code == 0
    assert json.loads(machine.stdout) == decision
    assert report.stdout == f"REPLAY REPORT\nReplay verified: {'b' * 64}\n"

    def _typed_failure(*args: object) -> None:
        del args
        raise PrivateV1Error("REPLAY_INTEGRITY_FAILED", "replay rejected")

    monkeypatch.setattr(
        "dmf_pulse.cli.private_v1.PrivateV1RecommendationService.replay", _typed_failure
    )
    failed = CliRunner().invoke(app, ["private-v1", "replay", "--bundle", str(bundle)])
    assert failed.exit_code == 2
    assert json.loads(failed.stdout)["error"]["code"] == "REPLAY_INTEGRITY_FAILED"


@pytest.mark.parametrize(
    ("command", "expected_code"),
    [
        ("run", "PRIVATE_V1_FAILED"),
        ("replay", "REPLAY_FAILED"),
    ],
)
def test_private_v1_cli_redacts_unexpected_validation_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
    expected_code: str,
) -> None:
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(
        "dmf_pulse.cli.private_v1.load_execution_input",
        lambda path: SimpleNamespace(retention_class="SYNTHETIC_REPLAY_ALLOWED"),
    )

    def _unexpected(*args: object) -> None:
        del args
        raise ValueError("sensitive underlying value")

    if command == "run":
        monkeypatch.setattr(
            "dmf_pulse.cli.private_v1.PrivateV1RecommendationService.run", _unexpected
        )
        arguments = ["private-v1", "run", "--input", str(source)]
    else:
        monkeypatch.setattr(
            "dmf_pulse.cli.private_v1.PrivateV1RecommendationService.replay", _unexpected
        )
        arguments = ["private-v1", "replay", "--bundle", str(bundle)]

    result = CliRunner().invoke(app, arguments)

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == expected_code
    assert "sensitive underlying value" not in result.stdout
