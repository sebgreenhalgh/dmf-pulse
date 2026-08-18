"""Public CLI contract for the Checkpoint-1.2 transient current FPL route."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app

pytestmark = pytest.mark.unit
runner = CliRunner()


def _args(repository_root: Path) -> list[str]:
    root = repository_root / "fixtures/fpl/FPL-004/happy_path"
    return [
        "ingest",
        "fpl",
        "current",
        "validate",
        "--bootstrap",
        str(root / "bootstrap.json"),
        "--fixtures",
        str(root / "fixtures.json"),
        "--competition-key",
        "PL",
        "--season-code",
        "2026/27",
        "--captured-at",
        "2026-08-18T12:00:00Z",
        "--information-cutoff",
        "2026-08-21T17:30:00Z",
        "--rights-profile",
        "fpl_official_private_manual_v1",
        "--gameweek",
        "1",
        "--output",
        "json",
    ]


def test_current_fpl_cli_emits_only_safe_nonpersisting_summary(
    repository_root: Path,
) -> None:
    result = runner.invoke(app, _args(repository_root))

    assert result.exit_code == 0, result.stdout
    value = json.loads(result.stdout)
    assert value["provider"] == "official_fpl"
    assert value["target_gameweek"] == 1
    assert value["deadline_at"] == "2026-08-21T17:30:00Z"
    assert value["player_count"] == 4
    assert value["team_count"] == 2
    assert value["target_gameweek_fixture_count"] == 1
    assert value["automated_access"] == "DENY"
    assert value["raw_storage"] == "DENY"
    assert value["derived_storage"] == "DENY"
    assert value["database_accessed"] is False
    assert value["raw_storage_performed"] is False
    assert value["derived_storage_performed"] is False
    assert value["transport_called"] is False
    assert value["operator_delete_required"] is True
    assert value["next_action"] == "CHECKPOINT 1.3 — LIVE THE ODDS API INPUT FOUNDATION"
    assert "Alice" not in result.stdout
    assert "A. Keeper" not in result.stdout
    assert "news" not in result.stdout.casefold()
    assert "database_url" not in result.stdout.casefold()


def test_current_fpl_cli_rejects_post_cutoff_and_wrong_rights_profile(
    repository_root: Path,
) -> None:
    post_cutoff = _args(repository_root)
    post_cutoff[post_cutoff.index("2026-08-18T12:00:00Z")] = "2026-08-21T17:31:00Z"
    result = runner.invoke(app, post_cutoff)
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "POST_CUTOFF"

    wrong_profile = _args(repository_root)
    wrong_profile[wrong_profile.index("fpl_official_private_manual_v1")] = "synthetic_test_v1"
    result = runner.invoke(app, wrong_profile)
    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "RIGHTS_BLOCKED"


def test_current_fpl_cli_rejects_invalid_timestamp_and_non_json_output(
    repository_root: Path,
) -> None:
    invalid_time = _args(repository_root)
    invalid_time[invalid_time.index("2026-08-18T12:00:00Z")] = "invalid"
    result = runner.invoke(app, invalid_time)
    assert result.exit_code == 3
    assert json.loads(result.stdout)["error"]["code"] == "USAGE_INVALID"

    non_json = _args(repository_root)
    non_json[-1] = "text"
    result = runner.invoke(app, non_json)
    assert result.exit_code == 3
    assert json.loads(result.stdout)["error"]["code"] == "USAGE_INVALID"
