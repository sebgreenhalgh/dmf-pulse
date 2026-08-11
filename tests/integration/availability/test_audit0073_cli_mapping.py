from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.data_model.tables import player_minutes_projection, prediction_run

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _args(
    external_id: int, *, as_of: str = "2026-08-14T17:30:00Z", seed: str = "MIN-007-COHERENCE-V1"
) -> list[str]:
    return [
        "availability",
        "predict",
        "--fixture-external-provider",
        "synthetic_availability",
        "--fixture-external-id",
        str(external_id),
        "--season-code",
        "2026/27",
        "--team-side",
        "HOME",
        "--as-of",
        as_of,
        "--model-key",
        "min007-baseline-v1",
        "--seed",
        seed,
        "--output",
        "json",
    ]


def test_mapping_plan_covers_all_nine_ids_and_invalid_inputs_publish_nothing(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DMF_ENVIRONMENT", "TEST")
    plan = json.loads(
        (repository_root / "fixtures/availability/MIN-007/external_mapping_plan.json").read_text()
    )
    runner = CliRunner()
    for fixture in plan["target_fixtures"]:
        external_id = int(fixture["external_id"])
        result = runner.invoke(app, _args(external_id))
        value = json.loads(result.stdout)
        if external_id == 709:
            assert result.exit_code == 42
            assert value["status"] == "BLOCKED"
        else:
            assert result.exit_code == 0, result.stderr
            assert value["status"] == "PROJECTED"
            assert value["fixture_id"] == fixture["fixture_id"]

    before = None
    with postgres_session_factory.begin() as session:
        before = (
            session.scalar(select(func.count()).select_from(prediction_run)),
            session.scalar(select(func.count()).select_from(player_minutes_projection)),
        )
    invalid = runner.invoke(app, _args(701, as_of="2099-01-01T00:00:00Z"))
    assert invalid.exit_code == 3
    assert invalid.stdout == ""
    with postgres_session_factory.begin() as session:
        assert (
            session.scalar(select(func.count()).select_from(prediction_run)),
            session.scalar(select(func.count()).select_from(player_minutes_projection)),
        ) == before
