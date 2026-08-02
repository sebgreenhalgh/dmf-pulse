"""Strict ODD-005 model and configuration boundary oracles."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.config import (
    load_provider_config,
    load_rights_profiles,
    provider_config_sha256,
    rights_config_sha256,
)
from dmf_pulse.ingestion.odds.models import (
    OddsIngestionResult,
    OddsQuality,
    OddsValidationResult,
    ProviderFailure,
    ProviderFailureCode,
    QuotaSource,
    QuotaState,
)
from dmf_pulse.markets.models import (
    MarketBook,
    MarketObservation,
    MarketOutcome,
    MarketQueryResult,
    MarketState,
    source_decimal_text,
)

pytestmark = pytest.mark.unit
NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)
FIXTURE_ID = UUID(int=1)
MARKET_ID = UUID(int=2)
OPERATOR_ID = UUID(int=4)


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    return path


def _provider_value(repository_root: Path) -> dict[str, object]:
    return json.loads(
        (repository_root / "config/providers/the_odds_api.json").read_text(encoding="utf-8")
    )


def _rights_value(repository_root: Path) -> dict[str, object]:
    return json.loads(
        (repository_root / "config/rights/odds_profiles.json").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("timeouts_seconds", "total"), 1),
        (("sport_keys",), ["soccer_epl", "soccer_epl"]),
        (("regions",), ["uk", "uk"]),
        (("markets",), ["h2h", "h2h"]),
    ),
)
def test_provider_configuration_rejects_budget_and_allowlist_drift(
    repository_root: Path,
    tmp_path: Path,
    path: tuple[str, ...],
    value: object,
) -> None:
    config = _provider_value(repository_root)
    target = config
    for part in path[:-1]:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value
    with pytest.raises(IngestionError) as raised:
        load_provider_config(_write_json(tmp_path / "invalid-provider.json", config))
    assert raised.value.code == "CONFIGURATION_INVALID"


@pytest.mark.parametrize(
    "raw",
    (
        b'{"provider_key":"the_odds_api","provider_key":"the_odds_api"}',
        b'{"provider_key":NaN}',
        b"\xff",
    ),
)
def test_provider_configuration_rejects_ambiguous_or_nonfinite_json(
    tmp_path: Path,
    raw: bytes,
) -> None:
    path = tmp_path / "invalid-provider.json"
    path.write_bytes(raw)
    with pytest.raises(IngestionError) as load_error:
        load_provider_config(path)
    assert load_error.value.code == "CONFIGURATION_INVALID"
    with pytest.raises(IngestionError) as hash_error:
        provider_config_sha256(path)
    assert hash_error.value.code == "CONFIGURATION_INVALID"


def test_explicit_missing_configuration_paths_fail_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(IngestionError) as provider_error:
        load_provider_config(missing)
    assert provider_error.value.code == "CONFIGURATION_INVALID"
    with pytest.raises(IngestionError) as rights_error:
        load_rights_profiles(missing)
    assert rights_error.value.code == "CONFIGURATION_INVALID"


@pytest.mark.parametrize("mutation", ("schema", "profiles", "profile", "duplicate"))
def test_rights_registry_rejects_shape_profile_and_identity_drift(
    repository_root: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    registry = _rights_value(repository_root)
    profiles = registry["profiles"]
    assert isinstance(profiles, list)
    if mutation == "schema":
        registry["schema_version"] = "2.0.0"
    elif mutation == "profiles":
        registry["profiles"] = {}
    elif mutation == "profile":
        profiles[0] = {"rights_profile_id": "incomplete"}
    else:
        profiles.append(deepcopy(profiles[0]))
    path = _write_json(tmp_path / "invalid-rights.json", registry)
    with pytest.raises(IngestionError) as raised:
        load_rights_profiles(path)
    assert raised.value.code == "CONFIGURATION_INVALID"
    if mutation != "duplicate":
        with pytest.raises(IngestionError) as hash_error:
            rights_config_sha256(path)
        assert hash_error.value.code == "CONFIGURATION_INVALID"


def test_quota_and_failure_models_reject_temporal_and_retry_contradictions() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        QuotaState(
            remaining=1,
            used=1,
            last_cost=1,
            observed_at=datetime(2026, 8, 20, 12),
            source=QuotaSource.SYNTHETIC_FIXTURE,
        )
    with pytest.raises(ValidationError, match="non-retryable"):
        ProviderFailure(
            code=ProviderFailureCode.TLS_ERROR,
            message="safe TLS failure",
            retryable=True,
            transport_called=True,
        )
    with pytest.raises(ValidationError, match="transport call"):
        ProviderFailure(
            code=ProviderFailureCode.CREDENTIAL_UNAVAILABLE,
            message="credential unavailable",
            retryable=False,
            transport_called=True,
        )


def _ingestion_value() -> dict[str, object]:
    return {
        "status": "COMPLETE",
        "source_snapshot_id": UUID(int=1),
        "events_seen": 1,
        "operator_books_seen": 1,
        "complete_books_created": 1,
        "incomplete_books_created": 0,
        "observations_created": 3,
        "observations_reused": 0,
        "quarantined": 0,
        "quota": None,
        "quality": OddsQuality(status="PASS"),
        "error": None,
    }


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"operator_books_seen": 0}, "book counts"),
        ({"observations_created": 2}, "quote effects"),
        ({"status": "FAILED", "source_snapshot_id": None}, "requires a provider failure"),
        (
            {
                "status": "BLOCKED",
                "error": ProviderFailure(
                    code=ProviderFailureCode.CREDENTIAL_UNAVAILABLE,
                    message="credential unavailable",
                    retryable=False,
                    transport_called=False,
                ),
            },
            "pre-transport block",
        ),
        (
            {
                "status": "QUARANTINED",
                "complete_books_created": 0,
                "observations_created": 0,
                "quarantined": 0,
            },
            "quarantined result",
        ),
        (
            {
                "status": "OBSERVED_NOT_USABLE",
                "complete_books_created": 0,
                "observations_created": 0,
                "source_snapshot_id": None,
            },
            "observed result",
        ),
    ),
)
def test_ingestion_result_rejects_status_count_and_effect_contradictions(
    updates: dict[str, object],
    message: str,
) -> None:
    value = _ingestion_value()
    value.update(updates)
    with pytest.raises(ValidationError, match=message):
        OddsIngestionResult(**value)  # type: ignore[arg-type]


def test_validation_result_rejects_quality_status_contradiction() -> None:
    with pytest.raises(ValidationError, match="validation status"):
        OddsValidationResult(
            status="VALID",
            contract_version="the-odds-api-v4-reference-v1",
            events_seen=1,
            operator_books_seen=1,
            payload_semantic_sha256="a" * 64,
            schema_fingerprint="b" * 64,
            quality=OddsQuality(status="WARNING", warnings=("SYNTHETIC_WARNING",)),
        )


def _observation(
    *,
    outcome: MarketOutcome = MarketOutcome.HOME,
    market_id: UUID = MARKET_ID,
    operator_id: UUID = OPERATOR_ID,
    fixture_id: UUID = FIXTURE_ID,
    usable_at: datetime = NOW + timedelta(minutes=2),
    state: MarketState = MarketState.INCOMPLETE,
) -> MarketObservation:
    return MarketObservation(
        fixture_id=fixture_id,
        market_id=market_id,
        selection_id=UUID(int=10 + list(MarketOutcome).index(outcome)),
        operator_id=operator_id,
        outcome=outcome,
        decimal_odds=Decimal("1.80"),
        observed_at=NOW,
        received_at=NOW + timedelta(minutes=1),
        usable_at=usable_at,
        source_snapshot_id=UUID(int=5),
        market_state=state,
        contract_version="the-odds-api-v4-reference-v1",
    )


def test_market_observation_rejects_nonfinite_scale_time_and_naive_values() -> None:
    with pytest.raises(ValueError, match="finite"):
        source_decimal_text(Decimal("NaN"))
    value = _observation().model_dump(mode="python")
    value["observed_at"] = datetime(2026, 8, 20, 12)
    with pytest.raises(ValidationError, match="timezone-aware"):
        MarketObservation(**value)
    value = _observation().model_dump(mode="python")
    value["usable_at"] = NOW - timedelta(minutes=1)
    with pytest.raises(ValidationError, match="timestamps"):
        MarketObservation(**value)
    for lexeme in ("1", "1.0", "1.00", 1.8):
        value = _observation().model_dump(mode="python")
        value["decimal_odds"] = lexeme
        with pytest.raises(ValidationError, match="decimal odds"):
            MarketObservation(**value)


def test_market_book_rejects_parent_identity_unique_set_and_state_contradictions() -> None:
    home = _observation()
    with pytest.raises(ValidationError, match="parent"):
        MarketBook(
            operator_id=UUID(int=99),
            operator_key="BOOK",
            market_state=MarketState.INCOMPLETE,
            observations=(home,),
        )
    with pytest.raises(ValidationError, match="unique market"):
        MarketBook(
            operator_id=UUID(int=4),
            operator_key="BOOK",
            market_state=MarketState.INCOMPLETE,
            observations=(home, _observation(market_id=UUID(int=99))),
        )
    with pytest.raises(ValidationError, match="HOME, DRAW, and AWAY"):
        MarketBook(
            operator_id=UUID(int=4),
            operator_key="BOOK",
            market_state=MarketState.COMPLETE,
            observations=(),
        )
    with pytest.raises(ValidationError, match="one or two outcomes"):
        MarketBook(
            operator_id=UUID(int=4),
            operator_key="BOOK",
            market_state=MarketState.INCOMPLETE,
            observations=(),
        )
    with pytest.raises(ValidationError, match="cannot contain quotes"):
        MarketBook(
            operator_id=UUID(int=4),
            operator_key="BOOK",
            market_state=MarketState.SUSPENDED,
            observations=(_observation(state=MarketState.SUSPENDED),),
        )


def test_market_query_rejects_count_duplicate_and_asof_ineligibility() -> None:
    first = MarketBook(
        operator_id=UUID(int=4),
        operator_key="BOOK",
        market_state=MarketState.INCOMPLETE,
        observations=(_observation(),),
    )
    with pytest.raises(ValidationError, match="observation_count"):
        MarketQueryResult(
            fixture_id=UUID(int=1),
            as_of=NOW + timedelta(minutes=5),
            books=(first,),
            observation_count=0,
        )
    with pytest.raises(ValidationError, match="duplicated"):
        MarketQueryResult(
            fixture_id=UUID(int=1),
            as_of=NOW + timedelta(minutes=5),
            books=(first, first),
            observation_count=2,
        )
    with pytest.raises(ValidationError, match="ineligible"):
        MarketQueryResult(
            fixture_id=UUID(int=1),
            as_of=NOW + timedelta(minutes=1),
            books=(first,),
            observation_count=1,
        )
