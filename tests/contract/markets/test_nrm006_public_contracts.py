"""Frozen NRM-006 public schema and library-surface contract proofs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

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
    "normalised_operator_market.schema.json": "c2851ca0c051c61aaa404fb290f6974640b2b1453f8c5a43e8d89502d0ee21fb",
    "market_consensus.schema.json": "60e59a14cb5c3a9abdbac5c7b4c929c9a38993a07a0b71cdc80704517fc56ad4",
    "market_normalisation_result.schema.json": "b9a39f8f2a612645ddde141f8e9c8df340d65d1b1a8a4e01b42bb2f64a1eb789",
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


def test_min007a_schema_constraints_reject_supplied_negative_cases(repository_root: Path) -> None:
    cases = json.loads(
        (repository_root / "fixtures" / "contracts" / "nrm_schema_negative_cases.json").read_text(
            encoding="utf-8"
        )
    )["cases"]
    schemas: dict[str, dict[str, Any]] = {
        name: json.loads((repository_root / "public_contracts" / name).read_text(encoding="utf-8"))
        for name in {
            "normalised_operator_market.schema.json",
            "market_consensus.schema.json",
            "market_normalisation_result.schema.json",
        }
    }
    assert all(case["must_validate"] is False for case in cases)

    operator = schemas["normalised_operator_market.schema.json"]
    assert operator["properties"]["source_observation_ids"]["maxItems"] == 3
    assert operator["properties"]["source_observation_ids"]["uniqueItems"] is True
    assert [
        item["properties"]["outcome"]["const"]
        for item in operator["properties"]["outcomes"]["prefixItems"]
    ] == [
        "HOME",
        "DRAW",
        "AWAY",
    ]
    consensus = schemas["market_consensus.schema.json"]
    assert consensus["properties"]["operator_markets"]["uniqueItems"] is True
    assert [
        item["properties"]["outcome"]["const"]
        for item in consensus["properties"]["outcomes"]["prefixItems"]
    ] == [
        "HOME",
        "DRAW",
        "AWAY",
    ]
    result = schemas["market_normalisation_result.schema.json"]
    assert result["properties"]["excluded_books"]["uniqueItems"] is True
    assert result["properties"]["warnings"]["uniqueItems"] is True
    assert len(result["allOf"]) == 2
    assert result["allOf"][0]["then"]["properties"]["error_code"] == {"type": "null"}
    assert result["allOf"][1]["then"]["properties"]["consensus"] == {"type": "null"}
