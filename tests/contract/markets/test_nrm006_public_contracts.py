"""Frozen NRM-006 public schema and library-surface contract proofs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from dmf_pulse.markets import (
    ExclusionReason,
    MarketConsensus,
    MarketNormalisationResult,
    NormalisationMethod,
    NormalisationStatus,
    NormalisedOperatorMarket,
    build_market_consensus,
    normalise_complete_market,
    raw_implied_probability,
)

pytestmark = pytest.mark.contract

SCHEMA_HASHES = {
    "probability.schema.json": "b2900cdbdb3c6d5dd4300eaa14508c8eb09852dc917d7fa95b5df15cfcba63df",
    "normalised_operator_market.schema.json": "b2c9e4fe19edeec5dd45debc14de159a7233cc97b9b00edd14e37312977fc06e",
    "market_consensus.schema.json": "2a44943bf1e6fc0530c390d7da30a043c8ad1d3af528ee30fd6f35df5c6ba306",
    "market_normalisation_result.schema.json": "4a8fb4925fede0b569913ad252fd483f1f04d28f2167c328ebefe3fa12cc7164",
}


def test_supplied_nrm006_public_schemas_are_byte_frozen(repository_root: Path) -> None:
    for name, expected_hash in SCHEMA_HASHES.items():
        body = (repository_root / "public_contracts" / name).read_bytes()
        assert hashlib.sha256(body).hexdigest() == expected_hash
        schema = json.loads(body)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


@pytest.mark.parametrize(
    ("schema_name", "model"),
    (
        ("normalised_operator_market.schema.json", NormalisedOperatorMarket),
        ("market_consensus.schema.json", MarketConsensus),
        ("market_normalisation_result.schema.json", MarketNormalisationResult),
    ),
)
def test_runtime_model_fields_match_frozen_schema(
    repository_root: Path, schema_name: str, model: type[object]
) -> None:
    schema = json.loads(
        (repository_root / "public_contracts" / schema_name).read_text(encoding="utf-8")
    )
    fields = model.model_fields  # type: ignore[attr-defined]
    assert set(schema["required"]) == set(fields)
    assert set(schema["properties"]) == set(fields)


def test_probability_contract_is_exactly_twelve_decimal_places(repository_root: Path) -> None:
    schema = json.loads(
        (repository_root / "public_contracts/probability.schema.json").read_text(encoding="utf-8")
    )
    pattern = schema["pattern"]
    for valid in ("0.000000000000", "0.500000000000", "0.999999999999", "1.000000000000"):
        assert re.fullmatch(pattern, valid)
    for invalid in ("0", "0.5", "0.50000000000", "0.5000000000000", "1.000000000001"):
        assert re.fullmatch(pattern, invalid) is None


def test_frozen_library_surface_and_enums_are_exposed() -> None:
    assert callable(raw_implied_probability)
    assert callable(normalise_complete_market)
    assert callable(build_market_consensus)
    assert tuple(item.value for item in NormalisationMethod) == ("POWER", "PROPORTIONAL")
    assert tuple(item.value for item in NormalisationStatus) == (
        "NORMALISED",
        "DEGRADED",
        "INSUFFICIENT",
        "BLOCKED",
    )
    assert {
        "INCOMPLETE",
        "STALE",
        "UNSUPPORTED",
        "SUSPENDED",
        "RIGHTS_BLOCKED",
        "QUALITY_BLOCKED",
        "MAPPING_UNAVAILABLE",
        "FUTURE_OBSERVATION",
    } <= {item.value for item in ExclusionReason}
