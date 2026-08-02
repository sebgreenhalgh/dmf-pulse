"""Frozen ODD-005 public-schema and CLI contract proofs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.ingestion.odds.models import (
    OddsIngestionResult,
    ProviderFailure,
    QuotaState,
)
from dmf_pulse.markets.models import MarketObservation, MarketQueryResult

pytestmark = pytest.mark.contract

SCHEMA_HASHES = {
    "odds_ingestion_result.schema.json": "4b64765a95b3ce05ec4f0170baa069f871aec98c170232c1e97a6d029f7014d3",
    "market_observation.schema.json": "be1e753ad192368fbd8a2b82383cd86e07be2104ba5595e1ea81b5581144f217",
    "market_query_result.schema.json": "24b5268c4e22a2b99ac7eefc4073045f2f95a71071556c74e3394a7472aafa46",
    "quota_state.schema.json": "d4510bda339b0cb8992305daff9794f681735f281840623175a7b96739df79c9",
    "provider_failure.schema.json": "3e6cc5975ed408e3fc027887f1b0aff834b2ccbae381679798e957f56856854b",
}


def test_five_supplied_public_schemas_are_byte_frozen(repository_root: Path) -> None:
    contract_root = repository_root / "public_contracts"
    for name, expected in SCHEMA_HASHES.items():
        body = (contract_root / name).read_bytes()
        assert hashlib.sha256(body).hexdigest() == expected
        value = json.loads(body)
        assert value["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert value["additionalProperties"] is False


def test_market_observation_decimal_lexemes_match_pack_1_1_policy(
    repository_root: Path,
) -> None:
    schema = json.loads(
        (repository_root / "public_contracts/market_observation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    pattern = schema["properties"]["decimal_odds"]["pattern"]
    for valid in ("1.01", "1.8", "1.80", "2", "2.00", "10.000"):
        assert re.fullmatch(pattern, valid), valid
    for invalid in (
        "1",
        "1.0",
        "1.00",
        "0.99",
        "0",
        "01.80",
        "+1.80",
        "-1.80",
        "1.8e0",
        "1E+1",
    ):
        assert re.fullmatch(pattern, invalid) is None, invalid


@pytest.mark.parametrize(
    ("name", "model"),
    (
        ("odds_ingestion_result.schema.json", OddsIngestionResult),
        ("market_observation.schema.json", MarketObservation),
        ("market_query_result.schema.json", MarketQueryResult),
        ("quota_state.schema.json", QuotaState),
        ("provider_failure.schema.json", ProviderFailure),
    ),
)
def test_runtime_model_fields_match_frozen_schema(
    repository_root: Path, name: str, model: type[object]
) -> None:
    frozen = json.loads((repository_root / "public_contracts" / name).read_text(encoding="utf-8"))
    model_fields = model.model_fields  # type: ignore[attr-defined]
    assert set(frozen["required"]) == set(model_fields)
    assert set(frozen["properties"]) == set(model_fields)


def test_cli_validate_emits_deterministic_contract_json(repository_root: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "odds",
            "validate",
            "--provider",
            "the_odds_api",
            "--input",
            str(repository_root / "fixtures/odds/ODD-005/happy_path.json"),
            "--contract-version",
            "the-odds-api-v4-reference-v1",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0
    value = json.loads(result.stdout)
    assert value["status"] == "VALID"
    assert value["provider"] == "the_odds_api"
    assert value["events_seen"] == 1
    assert value["operator_books_seen"] == 2
    assert set(value).isdisjoint({"probability", "implied_probability", "overround"})


def test_cli_invalid_payload_uses_odd_quarantine_exit_three(repository_root: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "odds",
            "validate",
            "--provider",
            "the_odds_api",
            "--input",
            str(repository_root / "fixtures/odds/ODD-005/duplicate_conflict.json"),
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 3
    value = json.loads(result.stdout)
    assert value["status"] == "FAILED"
    assert value["error"]["code"] == "VALIDATION_FAILED"


def test_live_shaped_cli_refuses_without_credential_and_never_needs_database() -> None:
    result = CliRunner().invoke(
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
            "2026-08-20T12:05:00Z",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 4
    value = json.loads(result.stdout)
    assert value["status"] == "BLOCKED"
    assert value["error"] == {
        "code": "CREDENTIAL_UNAVAILABLE",
        "message": "approved runtime credential is unavailable",
        "retryable": False,
        "transport_called": False,
    }


def test_odds_cli_rejects_non_allowlisted_options_without_transport() -> None:
    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "odds",
            "snapshot",
            "--provider",
            "the_odds_api",
            "--competition-key",
            "NOT_PL",
            "--sport-key",
            "soccer_epl",
            "--region",
            "uk",
            "--market",
            "h2h",
            "--as-of",
            "2026-08-20T12:05:00Z",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 3
    assert json.loads(result.stdout)["error"]["code"] == "USAGE_INVALID"
