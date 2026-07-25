"""Installed-entrypoint usage errors are stable JSON rather than Click prose."""

from __future__ import annotations

import json
import sys

import pytest

from dmf_pulse.cli.app import main

pytestmark = pytest.mark.contract


@pytest.mark.parametrize(
    "arguments",
    (
        ["dmf", "ingest", "fpl", "validate"],
        [
            "dmf",
            "ingest",
            "fpl",
            "validate",
            "--resource",
            "invalid",
            "--input",
            "unused.json",
        ],
        ["dmf", "ingest", "fpl", "resume", "--snapshot-id", "not-a-uuid"],
    ),
)
def test_parse_time_usage_failures_are_json_exit_three(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", arguments)
    with pytest.raises(SystemExit) as exited:
        main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exited.value.code == 3
    assert captured.err == ""
    assert payload == {
        "error": {
            "code": "USAGE_INVALID",
            "message": "command arguments are invalid",
            "retryable": False,
        },
        "schema_version": "1.0.0",
        "status": "FAILED",
    }


def test_installed_boundary_preserves_rights_blocked_exit_four(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dmf",
            "ingest",
            "fpl",
            "snapshot",
            "--resource",
            "all",
            "--competition-key",
            "PL",
            "--season-code",
            "2026/27",
            "--rights-profile",
            "fpl_official_private_manual_v1",
            "--output",
            "json",
        ],
    )
    with pytest.raises(SystemExit) as exited:
        main()
    payload = json.loads(capsys.readouterr().out)
    assert exited.value.code == 4
    assert payload["status"] == "RIGHTS_BLOCKED"
    assert payload["canonical_effects"]["transport_call_count"] == 0


@pytest.mark.parametrize(
    "captured_at",
    (
        "2026-08-21 17:00:00+00:00",
        "2026-W34-5T17:00:00+00:00",
        "2026-08-21T17:00:00+00:00:30",
    ),
)
def test_import_cli_rejects_non_rfc3339_timestamps_before_database_resolution(
    captured_at: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dmf",
            "ingest",
            "fpl",
            "import",
            "--bootstrap",
            "unused-bootstrap.json",
            "--fixtures",
            "unused-fixtures.json",
            "--competition-key",
            "SYNTHETIC_PL",
            "--season-code",
            "2026/27",
            "--captured-at",
            captured_at,
            "--information-cutoff",
            "2026-08-21T17:30:00Z",
            "--rights-profile",
            "synthetic_test_v1",
            "--output",
            "json",
        ],
    )
    with pytest.raises(SystemExit) as exited:
        main()
    payload = json.loads(capsys.readouterr().out)
    assert exited.value.code == 3
    assert payload["error"]["code"] == "USAGE_INVALID"
