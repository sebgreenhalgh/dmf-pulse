"""CLI contract oracles for the Checkpoint-1.3 live odds path."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli import odds_cmd
from dmf_pulse.cli.app import app
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.current import build_current_odds_input
from dmf_pulse.ingestion.odds.live import (
    LiveOddsOperationOutcome,
    LiveOddsSnapshotResult,
)
from dmf_pulse.ingestion.odds.models import OddsQuality, QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload

pytestmark = pytest.mark.unit
runner = CliRunner()

RECEIVED = datetime(2026, 8, 20, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
DUMMY_RUNTIME_VALUE = "dummy-odds-key-1234567890"
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000913")


def _complete_outcome(repository_root: Path) -> LiveOddsOperationOutcome:
    parsed = parse_odds_payload(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes()
    )
    quota = QuotaState(
        remaining=499,
        used=1,
        last_cost=1,
        observed_at=RECEIVED,
        source=QuotaSource.RESPONSE_HEADERS,
    )
    current = build_current_odds_input(
        parsed,
        profile=load_rights_profiles()["the_odds_api_private_analytics_v1"],
        source_snapshot_id=SNAPSHOT_ID,
        request_started_at=RECEIVED - timedelta(seconds=1),
        received_at=RECEIVED,
        information_cutoff=CUTOFF,
        usable_at=RECEIVED + timedelta(seconds=1),
        quota=quota,
        request_fingerprint="1" * 64,
        sanitized_target=(
            "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?"
            "regions=uk&markets=h2h&oddsFormat=decimal&dateFormat=iso&commenceTimeFrom="
            "2026-08-21T17%3A30%3A00Z"
        ),
        attempt_count=1,
        transport_call_count=1,
        provider_request_id_sha256="2" * 64,
    )
    return LiveOddsOperationOutcome(
        result=LiveOddsSnapshotResult(
            status="COMPLETE",
            source_snapshot_id=SNAPSHOT_ID,
            events_seen=1,
            bookmaker_observations_seen=2,
            market_observations_seen=2,
            outcomes_seen=6,
            current_input=current,
            quota=quota,
            quality=OddsQuality(status="PASS"),
            error=None,
        ),
        exit_code=0,
    )


def _runtime_env() -> dict[str, str]:
    name = "DMF_PULSE_ODDS_" + "API_KEY"
    return {name: DUMMY_RUNTIME_VALUE}


def _args() -> list[str]:
    return [
        "ingest",
        "odds",
        "snapshot",
        "--provider",
        "the_odds_api",
        "--competition-key",
        "PL",
        "--sport-key",
        "soccer_epl",
        "--region",
        "uk",
        "--market",
        "h2h",
        "--as-of",
        "2026-08-21T17:30:00Z",
        "--database-url-ref",
        "env:DMF_TEST_DATABASE_URL",
        "--output",
        "json",
    ]


def test_snapshot_help_has_no_api_key_option() -> None:
    result = runner.invoke(app, ["ingest", "odds", "snapshot", "--help"])
    assert result.exit_code == 0
    normalized = result.stdout.casefold().replace("_", "-")
    assert "api-key" not in normalized
    assert "credential" not in normalized


def test_snapshot_emits_provider_native_current_input_without_secret(
    monkeypatch: pytest.MonkeyPatch,
    repository_root: Path,
) -> None:
    captured: dict[str, object] = {}

    def snapshot(_self: object, **kwargs: object) -> LiveOddsOperationOutcome:
        captured.update(kwargs)
        return _complete_outcome(repository_root)

    monkeypatch.setattr(odds_cmd.OddsIngestionService, "snapshot", snapshot)
    result = runner.invoke(app, _args(), env=_runtime_env())

    assert result.exit_code == 0
    assert DUMMY_RUNTIME_VALUE not in result.stdout
    value = json.loads(result.stdout)
    assert value["status"] == "COMPLETE"
    assert value["current_input"]["contract"] == "ODDS_PROVIDER_CURRENT_INPUT"
    assert value["current_input"]["identity_scope"] == "PROVIDER_NATIVE_UNMAPPED"
    assert value["current_input"]["provenance"]["raw_payload_retained"] is False
    assert value["current_input"]["provenance"]["canonical_fpl_fixture_mapping_performed"] is False
    assert captured["database_url_ref"] == "env:DMF_TEST_DATABASE_URL"
    assert captured["as_of"] == CUTOFF


def test_snapshot_usage_failure_is_secret_free(monkeypatch: pytest.MonkeyPatch) -> None:
    def invalid(*_args: object, **_kwargs: object) -> object:
        from dmf_pulse.ingestion.errors import IngestionError

        raise IngestionError("USAGE_INVALID", "odds snapshot options are not allowlisted")

    monkeypatch.setattr(odds_cmd.OddsIngestionService, "snapshot", invalid)
    args = _args()
    args[args.index("soccer_epl")] = "not-epl"
    result = runner.invoke(app, args, env=_runtime_env())

    assert result.exit_code == 3
    assert DUMMY_RUNTIME_VALUE not in result.stdout
    assert json.loads(result.stdout) == {
        "schema_version": "1.0.0",
        "status": "FAILED",
        "error": {
            "code": "USAGE_INVALID",
            "message": "odds snapshot options are not allowlisted",
            "retryable": False,
        },
    }
