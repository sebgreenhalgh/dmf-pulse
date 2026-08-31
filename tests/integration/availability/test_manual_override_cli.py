from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from tests.unit.availability.manual_override_test_support import deep_copy_input

pytestmark = pytest.mark.integration


def test_manual_override_cli_writes_deterministic_private_transient_artifacts(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "synthetic-manual-input.json"
    input_path.write_text(json.dumps(deep_copy_input(), sort_keys=True), encoding="utf-8")
    output_dir = tmp_path / "dmf-private-transient"
    runner = CliRunner()
    first = runner.invoke(
        app,
        [
            "availability",
            "manual-override",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
    )
    assert first.exit_code == 0, first.output
    names = sorted(path.name for path in output_dir.iterdir())
    assert names == [
        "away-team-minutes-projection.json",
        "home-team-minutes-projection.json",
        "manual-input.canonical.json",
        "manual-override-manifest.json",
        "stage7-minutes-context.json",
    ]
    before = {path.name: path.read_bytes() for path in output_dir.iterdir()}
    second = runner.invoke(
        app,
        [
            "availability",
            "manual-override",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
    )
    assert second.exit_code == 0, second.output
    assert before == {path.name: path.read_bytes() for path in output_dir.iterdir()}
    manifest = json.loads((output_dir / "manual-override-manifest.json").read_text("utf-8"))
    assert manifest["classification"] == "PRIVATE_TRANSIENT"
    assert manifest["model_derived"] is False
    assert manifest["production_suitable"] is False
    assert manifest["model_family"] == "PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1"


def test_manual_override_cli_fails_closed_for_invalid_input_and_conflicting_output(
    tmp_path: Path,
) -> None:
    body = deep_copy_input()
    body["home"]["scenarios"][0]["count"] = 63
    input_path = tmp_path / "invalid.json"
    input_path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    output_dir = tmp_path / "dmf-private-transient"
    result = CliRunner().invoke(
        app,
        [
            "availability",
            "manual-override",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
    )
    assert result.exit_code == 2
    assert "MANUAL_OVERRIDE_INPUT_INVALID" in result.output
    assert not output_dir.exists()

    valid_path = tmp_path / "valid.json"
    valid_path.write_text(json.dumps(deep_copy_input(), sort_keys=True), encoding="utf-8")
    output_dir.mkdir()
    (output_dir / "home-team-minutes-projection.json").write_text("conflict", encoding="utf-8")
    conflict = CliRunner().invoke(
        app,
        [
            "availability",
            "manual-override",
            "--input",
            str(valid_path),
            "--output-dir",
            str(output_dir),
        ],
    )
    assert conflict.exit_code == 2
    assert "PRIVATE_OUTPUT_CONFLICT" in conflict.output
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "home-team-minutes-projection.json"
    ]


def test_manual_override_cli_requires_explicit_private_output_marker(tmp_path: Path) -> None:
    input_path = tmp_path / "valid.json"
    input_path.write_text(json.dumps(deep_copy_input(), sort_keys=True), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "availability",
            "manual-override",
            "--input",
            str(input_path),
            "--output-dir",
            str(tmp_path / "ordinary-output"),
        ],
    )
    assert result.exit_code == 2
    assert "PRIVATE_OUTPUT_REQUIRED" in result.output

    escaped = tmp_path / "dmf-private-transient" / ".." / "ordinary-output"
    result = CliRunner().invoke(
        app,
        [
            "availability",
            "manual-override",
            "--input",
            str(input_path),
            "--output-dir",
            str(escaped),
        ],
    )
    assert result.exit_code == 2
    assert "PRIVATE_OUTPUT_REQUIRED" in result.output
    assert not (tmp_path / "ordinary-output").exists()

    unsafe = tmp_path / "dmf-private-transient"
    unsafe.write_text("not a directory", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "availability",
            "manual-override",
            "--input",
            str(input_path),
            "--output-dir",
            str(unsafe),
        ],
    )
    assert result.exit_code == 2
    assert "PRIVATE_OUTPUT_UNSAFE" in result.output
