"""Checkpoint-1.3C operator contract acceptance oracles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.ingestion.odds.credentials import ODDS_API_ENVIRONMENT_VARIABLE

pytestmark = (pytest.mark.unit, pytest.mark.contract)
runner = CliRunner()

DOCUMENT = Path("docs/operations/odds_runtime_credential.md")
EXACT_SETTER = '$env:DMF_PULSE_ODDS_API_KEY = "<YOUR_KEY_HERE>"'
EXACT_DIAGNOSTIC = "dmf ingest odds credential-status --output json"
EXACT_SNAPSHOT = (
    "dmf ingest odds snapshot --provider the_odds_api --competition-key PL "
    "--sport-key soccer_epl --region uk --market h2h --as-of $AsOf "
    "--database-url-ref env:DMF_TEST_DATABASE_URL --output json"
)


def test_operator_document_freezes_exact_secret_safe_commands(repository_root: Path) -> None:
    text = (repository_root / DOCUMENT).read_text(encoding="utf-8")

    assert EXACT_SETTER in text
    assert EXACT_DIAGNOSTIC in text
    assert EXACT_SNAPSHOT in text
    assert "$env:DMF_TEST_DATABASE_URL = \"<POSTGRESQL_URL>\"" in text
    assert "REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT" in text
    assert "canonical_fpl_fixture_mapping_performed = false" in text
    assert "PROVIDER_NATIVE_UNMAPPED" in text
    assert "apiKey=" not in text
    assert "--api-key" not in text

    for code in (
        "CREDENTIAL_UNAVAILABLE",
        "QUOTA_EXHAUSTED",
        "HTTP_429",
        "HTTP_4XX",
        "HTTP_5XX",
        "CONNECT_TIMEOUT",
        "READ_TIMEOUT",
        "TOTAL_TIMEOUT",
        "TLS_ERROR",
        "REDIRECT_BLOCKED",
        "CONTENT_TYPE_INVALID",
        "SOURCE_UNAVAILABLE",
        "POST_CUTOFF",
        "QUALITY_BLOCKED",
    ):
        assert code in text


def test_documented_provider_and_rights_configuration_is_repository_authoritative(
    repository_root: Path,
) -> None:
    provider = json.loads(
        (repository_root / "config/providers/the_odds_api.json").read_text(encoding="utf-8")
    )
    assert provider["provider_key"] == "the_odds_api"
    assert provider["scheme"] == "https"
    assert provider["host"] == "api.the-odds-api.com"
    assert provider["path"] == "/v4/sports/soccer_epl/odds"
    assert provider["sport_keys"] == ["soccer_epl"]
    assert provider["regions"] == ["uk"]
    assert provider["markets"] == ["h2h"]
    assert provider["odds_format"] == "decimal"
    assert provider["request_cost"] == 1
    assert provider["retry"]["max_attempts"] == 2
    assert provider["timeouts_seconds"] == {"connect": 10, "read": 20, "total": 30}

    rights = json.loads(
        (repository_root / "config/rights/odds_profiles.json").read_text(encoding="utf-8")
    )
    profile = next(
        item
        for item in rights["profiles"]
        if item["rights_profile_id"] == "the_odds_api_private_analytics_v1"
    )
    capabilities = profile["capabilities"]
    assert capabilities["automated_access"] == "ALLOW"
    assert capabilities["transient_processing"] == "ALLOW"
    assert capabilities["derived_storage"] == "ALLOW"
    assert capabilities["private_internal_use"] == "ALLOW"
    assert capabilities["raw_storage"] == "UNKNOWN"
    assert capabilities["public_display"] == "DENY"
    assert capabilities["redistribution"] == "DENY"
    assert capabilities["backup"] == "UNKNOWN"
    assert capabilities["model_training"] == "UNKNOWN"
    assert profile["retention_seconds"] == 0


def test_snapshot_help_matches_documented_option_contract() -> None:
    result = runner.invoke(app, ["ingest", "odds", "snapshot", "--help"])

    assert result.exit_code == 0
    normalized = result.stdout.casefold().replace("_", "-")
    for option in (
        "--provider",
        "--competition-key",
        "--sport-key",
        "--region",
        "--market",
        "--as-of",
        "--database-url-ref",
        "--output",
    ):
        assert option in normalized
    assert "--api-key" not in normalized


def test_snapshot_missing_credential_is_controlled_and_transport_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ODDS_API_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.delenv("DMF_TEST_DATABASE_URL", raising=False)

    result = runner.invoke(
        app,
        [
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
            "2099-01-01T00:00:00Z",
            "--database-url-ref",
            "env:DMF_TEST_DATABASE_URL",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED"
    assert payload["current_input"] is None
    assert payload["error"] == {
        "code": "CREDENTIAL_UNAVAILABLE",
        "message": "approved runtime credential is unavailable",
        "retryable": False,
        "transport_called": False,
    }
    assert payload["quality"]["blockers"] == ["CREDENTIAL_UNAVAILABLE"]
