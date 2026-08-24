"""Safe CLI contract for CURRENT-FPL-STATE-001A."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli import ingest_cmd
from dmf_pulse.cli.app import app
from dmf_pulse.ingestion.fpl.current import CurrentFplInputService

pytestmark = pytest.mark.unit
runner = CliRunner()

RECEIVED = datetime(2026, 8, 18, 12, 5, tzinfo=UTC)


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


@pytest.fixture(autouse=True)
def deterministic_current_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ingest_cmd,
        "CurrentFplInputService",
        lambda: CurrentFplInputService(clock=lambda: RECEIVED),
    )


def test_current_fpl_cli_emits_only_safe_nonpersisting_summary(repository_root: Path) -> None:
    result = runner.invoke(app, _args(repository_root))

    assert result.exit_code == 0, result.output
    value = json.loads(result.stdout)
    assert value["contract"] == "CURRENT_FPL_INPUT_SUMMARY"
    assert value["provider"] == "official_fpl"
    assert value["target_gameweek"] == 1
    assert value["target_deadline_at"] == "2026-08-21T17:30:00Z"
    assert value["player_count"] == 4
    assert value["team_count"] == 2
    assert value["target_gameweek_fixture_count"] == 1
    assert value["automated_access"] == "DENY"
    assert value["raw_storage"] == "DENY"
    assert value["derived_storage_profile_value"] == "UNKNOWN"
    assert value["derived_storage"] == "DENY"
    assert value["database_accessed"] is False
    assert value["raw_storage_performed"] is False
    assert value["derived_storage_performed"] is False
    assert value["transport_called"] is False
    assert value["operator_delete_required"] is True
    for forbidden in (
        "Alice",
        "A. Keeper",
        "news",
        str(repository_root),
        "database_url",
        "credential",
    ):
        assert forbidden.casefold() not in result.stdout.casefold()


def test_current_fpl_cli_supports_gameweek_greater_than_one(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap = json.loads((source / "bootstrap.json").read_text(encoding="utf-8"))
    fixtures = json.loads((source / "fixtures.json").read_text(encoding="utf-8"))
    fixture = deepcopy(fixtures[0])
    fixture.update(
        {
            "id": 102,
            "code": 900102,
            "event": 2,
            "kickoff_time": "2026-08-29T14:00:00Z",
            "team_h": 2,
            "team_a": 1,
        }
    )
    fixtures.append(fixture)
    bootstrap_path = tmp_path / "bootstrap.json"
    fixtures_path = tmp_path / "fixtures.json"
    bootstrap_path.write_text(json.dumps(bootstrap), encoding="utf-8")
    fixtures_path.write_text(json.dumps(fixtures), encoding="utf-8")
    monkeypatch.setattr(
        ingest_cmd,
        "CurrentFplInputService",
        lambda: CurrentFplInputService(clock=lambda: datetime(2026, 8, 24, 12, 5, tzinfo=UTC)),
    )
    args = _args(repository_root)
    args[args.index(str(source / "bootstrap.json"))] = str(bootstrap_path)
    args[args.index(str(source / "fixtures.json"))] = str(fixtures_path)
    args[args.index("2026-08-18T12:00:00Z")] = "2026-08-24T12:00:00Z"
    args[args.index("2026-08-21T17:30:00Z")] = "2026-08-28T17:30:00Z"
    gameweek_index = args.index("--gameweek") + 1
    args[gameweek_index] = "2"

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["target_gameweek"] == 2


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


@pytest.mark.parametrize(
    "mutation",
    ("invalid_time", "invalid_gameweek", "invalid_season", "non_json"),
)
def test_current_fpl_cli_rejects_invalid_arguments(
    repository_root: Path,
    mutation: str,
) -> None:
    args = _args(repository_root)
    if mutation == "invalid_time":
        args[args.index("2026-08-18T12:00:00Z")] = "invalid"
    elif mutation == "invalid_gameweek":
        args[args.index("--gameweek") + 1] = "0"
    elif mutation == "invalid_season":
        args[args.index("2026/27")] = "not-a-season"
    elif mutation == "non_json":
        args[-1] = "text"
    else:  # pragma: no cover - parameter contract
        raise AssertionError(mutation)

    result = runner.invoke(app, args)

    assert result.exit_code == 3
    assert json.loads(result.stdout)["error"]["code"] == "USAGE_INVALID"


def test_cli_failure_does_not_disclose_payload_path_news_or_traceback(tmp_path: Path) -> None:
    private_bootstrap = tmp_path / "private-bootstrap-SENSITIVE-PATH.json"
    private_fixtures = tmp_path / "private-fixtures-SENSITIVE-PATH.json"
    private_bootstrap.write_text(
        '{"news":"SENSITIVE-NEWS-TEXT","first_name":"SENSITIVE-PLAYER"',
        encoding="utf-8",
    )
    private_fixtures.write_text("[]", encoding="utf-8")
    args = _args(tmp_path)
    args[args.index(str(tmp_path / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"))] = str(
        private_bootstrap
    )
    args[args.index(str(tmp_path / "fixtures/fpl/FPL-004/happy_path/fixtures.json"))] = str(
        private_fixtures
    )

    result = runner.invoke(app, args)

    assert result.exit_code == 2
    value = json.loads(result.stdout)
    assert value["error"]["code"] == "MALFORMED_JSON"
    for forbidden in (
        "SENSITIVE-PATH",
        "SENSITIVE-NEWS-TEXT",
        "SENSITIVE-PLAYER",
        "Traceback",
        str(tmp_path),
    ):
        assert forbidden not in result.output


def test_current_command_surface_has_no_network_database_or_credentials() -> None:
    result = runner.invoke(app, ["ingest", "fpl", "current", "validate", "--help"])

    assert result.exit_code == 0, result.output
    rendered = result.output.casefold()
    for forbidden in (
        "url",
        "credential",
        "password",
        "cookie",
        "database",
        "output-path",
        "persist",
    ):
        assert forbidden not in rendered


def test_current_command_fails_safely_if_summary_contract_is_broken(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingest_cmd, "_safe", lambda _operation: object())

    result = runner.invoke(app, _args(repository_root))

    assert result.exit_code == 8
    assert json.loads(result.stdout)["error"] == {
        "code": "INTERNAL_INVARIANT",
        "message": "current FPL summary is invalid",
        "retryable": False,
    }
