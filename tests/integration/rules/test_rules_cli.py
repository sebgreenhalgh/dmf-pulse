"""End-to-end rules CLI contracts and stable exit semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app

runner = CliRunner()


@pytest.mark.integration
def test_validate_compile_hash_show_and_score_commands(
    repository_root: Path, tmp_path: Path
) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    source = root / "synthetic_complete"
    output = tmp_path / "compiled.json"
    validated = runner.invoke(app, ["rules", "validate", str(source), "--json"])
    assert validated.exit_code == 0
    assert json.loads(validated.stdout)["valid"] is True
    compiled = runner.invoke(
        app, ["rules", "compile", str(source), "--output", str(output), "--json"]
    )
    assert compiled.exit_code == 0
    compiled_value = json.loads(compiled.stdout)
    hashed = runner.invoke(app, ["rules", "hash", str(output), "--json"])
    assert hashed.exit_code == 0
    assert json.loads(hashed.stdout)["ruleset_hash"] == compiled_value["ruleset_hash"]
    shown = runner.invoke(app, ["rules", "show", str(output), "--json"])
    assert json.loads(shown.stdout)["rule_families"] == sorted(
        json.loads(shown.stdout)["rule_families"]
    )

    fixture = runner.invoke(
        app,
        ["rules", "score-fixture", str(output), str(root / "golden_fixture_001.json"), "--json"],
    )
    assert fixture.exit_code == 0
    assert json.loads(fixture.stdout)["sum_player_totals"] == 38
    gameweek = runner.invoke(
        app,
        ["rules", "score-gameweek", str(output), str(root / "golden_gameweek_001.json"), "--json"],
    )
    assert gameweek.exit_code == 0
    assert json.loads(gameweek.stdout)["player_totals"]["home-fwd"] == 14


@pytest.mark.integration
def test_diff_and_expected_activation_block_exit(repository_root: Path) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    difference = runner.invoke(
        app,
        [
            "rules",
            "diff",
            str(root / "reference_2025_26"),
            str(root / "target_2026_27_partial"),
            "--json",
        ],
    )
    assert difference.exit_code == 0
    assert json.loads(difference.stdout)["changes"]
    activated = runner.invoke(
        app,
        [
            "rules",
            "activate",
            str(root / "target_2026_27_partial"),
            "--approval",
            str(root / "invalid_target_approval.json"),
            "--json",
        ],
    )
    assert activated.exit_code == 4
    error = json.loads(activated.stderr)["error"]
    assert error["code"] == "RULESET_ACTIVATION_BLOCKED"
    assert "production_eligible:false" in error["blockers"]


@pytest.mark.integration
def test_cli_validation_and_collision_errors_are_stable_and_non_disclosing(
    repository_root: Path, tmp_path: Path
) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    invalid = runner.invoke(
        app, ["rules", "validate", str(tmp_path / "private-user/missing"), "--json"]
    )
    assert invalid.exit_code == 3
    assert "private-user" not in invalid.stderr
    output = tmp_path / "compiled.json"
    output.write_text("{}\n", encoding="utf-8")
    collision = runner.invoke(
        app,
        ["rules", "compile", str(root / "synthetic_complete"), "--output", str(output), "--json"],
    )
    assert collision.exit_code == 5
    assert json.loads(collision.stderr)["error"]["code"] == "RULESET_OUTPUT_COLLISION"
