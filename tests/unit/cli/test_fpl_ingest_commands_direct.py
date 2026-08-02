"""In-process FPL CLI coverage for typed requests and fail-closed guards."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict
from typer.testing import CliRunner

from dmf_pulse.cli import ingest_cmd
from dmf_pulse.cli.app import app
from dmf_pulse.ingestion.fpl.service import DATABASE_REF, FplOperationOutcome

pytestmark = pytest.mark.unit
runner = CliRunner()


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str = "USABLE"


def _outcome(exit_code: int = 0) -> FplOperationOutcome:
    return FplOperationOutcome(result=_Result(), exit_code=exit_code)  # type: ignore[arg-type]


def test_fpl_validate_cli_parses_frozen_bootstrap(repository_root: Path) -> None:
    result = runner.invoke(
        app,
        [
            "ingest",
            "fpl",
            "validate",
            "--resource",
            "bootstrap",
            "--input",
            str(repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"),
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] in {"VALID", "VALID_WITH_WARNINGS"}


def test_fpl_import_cli_builds_exact_typed_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def import_pair(_self: object, request: object) -> FplOperationOutcome:
        captured["request"] = request
        return _outcome()

    monkeypatch.setattr(ingest_cmd.FplIngestionService, "import_pair", import_pair)
    result = runner.invoke(
        app,
        [
            "ingest",
            "fpl",
            "import",
            "--bootstrap",
            str(tmp_path / "bootstrap.json"),
            "--fixtures",
            str(tmp_path / "fixtures.json"),
            "--competition-key",
            "SYNTHETIC_PL",
            "--season-code",
            "2026/27",
            "--captured-at",
            "2026-08-21T17:00:00Z",
            "--information-cutoff",
            "2026-08-21T17:30:00Z",
            "--rights-profile",
            "synthetic_test_v1",
        ],
    )
    assert result.exit_code == 0
    request = captured["request"]
    assert request.captured_at == datetime(2026, 8, 21, 17, tzinfo=UTC)
    assert request.information_cutoff == datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    assert request.database_url_ref == DATABASE_REF


def test_fpl_replay_resume_bundle_and_snapshot_cli_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object]] = []

    def replay(_self: object, request: object) -> FplOperationOutcome:
        calls.append(("replay", request))
        return _outcome()

    def resume(_self: object, snapshot_id: UUID, **kwargs: object) -> FplOperationOutcome:
        calls.append(("resume", (snapshot_id, kwargs)))
        return _outcome()

    def show_bundle(_self: object, bundle_id: UUID, **kwargs: object) -> BaseModel:
        calls.append(("bundle", (bundle_id, kwargs)))
        return _Result()

    def snapshot(_self: object, **kwargs: object) -> FplOperationOutcome:
        calls.append(("snapshot", kwargs))
        return _outcome(2)

    monkeypatch.setattr(ingest_cmd.FplIngestionService, "replay", replay)
    monkeypatch.setattr(ingest_cmd.FplIngestionService, "resume", resume)
    monkeypatch.setattr(ingest_cmd.FplIngestionService, "show_bundle", show_bundle)
    monkeypatch.setattr(ingest_cmd.FplIngestionService, "snapshot", snapshot)
    replay_result = runner.invoke(
        app,
        [
            "ingest",
            "fpl",
            "replay",
            "--fixture-set",
            str(tmp_path),
            "--scenario",
            "happy_path",
        ],
    )
    snapshot_id = UUID(int=1)
    resume_result = runner.invoke(
        app,
        ["ingest", "fpl", "resume", "--snapshot-id", str(snapshot_id)],
    )
    bundle_id = UUID(int=2)
    bundle_result = runner.invoke(
        app,
        ["ingest", "fpl", "bundle", "show", "--bundle-id", str(bundle_id)],
    )
    snapshot_result = runner.invoke(
        app,
        [
            "ingest",
            "fpl",
            "snapshot",
            "--resource",
            "all",
            "--competition-key",
            "SYNTHETIC_PL",
            "--season-code",
            "2026/27",
            "--rights-profile",
            "synthetic_test_v1",
        ],
    )
    assert [
        replay_result.exit_code,
        resume_result.exit_code,
        bundle_result.exit_code,
        snapshot_result.exit_code,
    ] == [0, 0, 0, 2]
    assert [name for name, _value in calls] == ["replay", "resume", "bundle", "snapshot"]
    assert json.loads(snapshot_result.stdout)["status"] == "USABLE"


@pytest.mark.parametrize(
    ("args", "message"),
    (
        (
            [
                "ingest",
                "fpl",
                "replay",
                "--fixture-set",
                ".",
                "--scenario",
                "happy_path",
                "--information-cutoff",
                "invalid",
            ],
            "RFC3339",
        ),
        (
            [
                "ingest",
                "fpl",
                "snapshot",
                "--resource",
                "invalid",
                "--competition-key",
                "PL",
                "--season-code",
                "2026/27",
                "--rights-profile",
                "synthetic_test_v1",
            ],
            "--resource is invalid",
        ),
        (
            [
                "ingest",
                "fpl",
                "replay",
                "--fixture-set",
                ".",
                "--scenario",
                "happy_path",
                "--output",
                "text",
            ],
            "--output must be json",
        ),
    ),
)
def test_fpl_cli_rejects_usage_before_service(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    message: str,
) -> None:
    monkeypatch.setattr(
        ingest_cmd.FplIngestionService,
        "replay",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    monkeypatch.setattr(
        ingest_cmd.FplIngestionService,
        "snapshot",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    result = runner.invoke(app, args)
    assert result.exit_code == 3
    assert message in json.loads(result.stdout)["error"]["message"]


@pytest.mark.parametrize(
    ("method", "args"),
    (
        (
            "validate",
            [
                "ingest",
                "fpl",
                "validate",
                "--resource",
                "bootstrap",
                "--input",
                "unused.json",
            ],
        ),
        (
            "resume",
            ["ingest", "fpl", "resume", "--snapshot-id", str(UUID(int=3))],
        ),
        (
            "show_bundle",
            ["ingest", "fpl", "bundle", "show", "--bundle-id", str(UUID(int=4))],
        ),
        (
            "snapshot",
            [
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
                "synthetic_test_v1",
            ],
        ),
    ),
)
def test_fpl_cli_rejects_internal_result_type_drift(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    args: list[str],
) -> None:
    monkeypatch.setattr(ingest_cmd.FplIngestionService, method, lambda *_a, **_k: object())
    result = runner.invoke(app, args)
    assert result.exit_code == 8
    assert json.loads(result.stdout)["error"]["code"] == "INTERNAL_INVARIANT"
