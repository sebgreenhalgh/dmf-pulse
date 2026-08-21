"""Offline operator-command tests; none may construct a live transport."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.cli.app import app
from dmf_pulse.ingestion.fpl.current import CurrentFplInputService
from tests.unit.player_evidence.support import replay

RUNNER = CliRunner()


def _write_replay(tmp_path):
    path = tmp_path / "synthetic-replay.json"
    path.write_text(pretty_json(replay()), encoding="utf-8")
    return path


def test_rights_status_is_safe_metadata_only() -> None:
    result = RUNNER.invoke(app, ["player-evidence", "rights-status"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["approval_present"] is False
    assert payload["allowed_node"] == "history_past"
    assert payload["raw_persistence"] is False
    assert payload["next_state"] == "READY_FOR_PLAYER_HISTORY_RIGHTS_APPROVAL_AND_CAPTURE"


def test_synthetic_commands_only_emit_or_write_derived_artifacts(tmp_path) -> None:
    fixture = _write_replay(tmp_path)
    dry_run = RUNNER.invoke(app, ["player-evidence", "synthetic-dry-run", "--replay", str(fixture)])
    assert dry_run.exit_code == 0, dry_run.output
    dry_payload = json.loads(dry_run.output)
    assert dry_payload["rights_mode"] == "SYNTHETIC_REPLAY_ONLY"
    assert dry_payload["raw_persistence"] is False

    output = tmp_path / "posterior-only.json"
    compiled = RUNNER.invoke(
        app,
        ["player-evidence", "posterior-compile", "--replay", str(fixture), "--output", str(output)],
    )
    assert compiled.exit_code == 0, compiled.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["raw_history_persisted"] is False
    assert "history_past" not in output.read_text(encoding="utf-8")
    assert "goals_scored" not in output.read_text(encoding="utf-8")

    degraded = RUNNER.invoke(
        app, ["player-evidence", "emergency-degraded", "--replay", str(fixture)]
    )
    assert degraded.exit_code == 0, degraded.output
    degraded_payload = json.loads(degraded.output)
    assert degraded_payload["degraded_player_allocation"] is True
    assert degraded_payload["fallback_count"] > 0


def test_capture_command_fails_closed_before_network_construction(monkeypatch) -> None:
    import dmf_pulse.cli.player_evidence as command_module

    called = False

    class _ForbiddenTransport:
        def __init__(self) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(command_module, "UrllibHistoryTransport", _ForbiddenTransport)
    result = RUNNER.invoke(app, ["player-evidence", "capture-history"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "RIGHTS_APPROVAL_REQUIRED"
    assert called is False


def test_current_capture_command_requires_governed_manual_inputs_before_transport(
    monkeypatch,
) -> None:
    import dmf_pulse.cli.player_evidence as command_module

    called = False

    class _ForbiddenTransport:
        def __init__(self) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(command_module, "UrllibHistoryTransport", _ForbiddenTransport)
    result = RUNNER.invoke(app, ["player-evidence", "capture-current-history"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "RIGHTS_APPROVAL_REQUIRED"
    assert called is False


def test_current_capture_builds_only_an_in_memory_catalogue_before_execute_network(
    repository_root: Path, tmp_path: Path, monkeypatch
) -> None:
    import dmf_pulse.cli.player_evidence as command_module

    called = False

    class _ForbiddenTransport:
        def __init__(self) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(command_module, "UrllibHistoryTransport", _ForbiddenTransport)
    monkeypatch.setattr(
        command_module,
        "CurrentFplInputService",
        lambda: CurrentFplInputService(clock=lambda: datetime(2026, 8, 18, 12, 5, tzinfo=UTC)),
    )
    current_input = repository_root / "fixtures/fpl/FPL-004/happy_path"
    rights = (
        repository_root / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_RIGHTS_APPROVAL.json"
    )
    role_prior = (
        repository_root / "evidence/tickets/GW1-PLY-002/GW1_PLAYER_ROLE_PRIOR_CANDIDATE.json"
    )
    outputs = [
        tmp_path / "central.json",
        tmp_path / "low.json",
        tmp_path / "high.json",
        tmp_path / "allocation.json",
        tmp_path / "deletion.json",
    ]
    result = RUNNER.invoke(
        app,
        [
            "player-evidence",
            "capture-current-history",
            "--approval",
            str(rights),
            "--expected-approval-sha256",
            "d946552f2a55df7ed400bb43cff6bf85b4bdf8cbfe804044d08d9c9a96f8e2fd",
            "--bootstrap",
            str(current_input / "bootstrap.json"),
            "--fixtures",
            str(current_input / "fixtures.json"),
            "--captured-at",
            "2026-08-18T12:00:00Z",
            "--information-cutoff",
            "2026-08-21T17:30:00Z",
            "--terms-fingerprint",
            "ad62cb745459df3282f8900117b85352a01d75754e080d06aa3836dcd2b2b246",
            "--maximum-player-count",
            "4",
            "--retention-mode",
            "POSTERIOR_ONLY",
            "--role-prior",
            str(role_prior),
            "--central-posterior-output",
            str(outputs[0]),
            "--low-posterior-output",
            str(outputs[1]),
            "--high-posterior-output",
            str(outputs[2]),
            "--allocation-output",
            str(outputs[3]),
            "--deletion-manifest-output",
            str(outputs[4]),
        ],
    )
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "NETWORK_EXECUTION_DISABLED"
    assert called is False
    assert not any(path.exists() for path in outputs)
