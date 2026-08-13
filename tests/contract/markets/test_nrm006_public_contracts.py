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
from tests.contract.markets._draft2020 import SchemaValidationError, validate_instance

pytestmark = pytest.mark.contract

SCHEMA_HASHES = {
    "probability.schema.json": "6a0dcfb79f5e8939dd54f889b61236783d8c4e05a4bd0272eae25599c2373f9b",
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
        (repository_root / "fixtures" / "nrm_schema_negative_instances.json").read_text(
            encoding="utf-8"
        )
    )["cases"]
    schemas: dict[str, dict[str, Any]] = {
        name: json.loads((repository_root / "public_contracts" / name).read_text(encoding="utf-8"))
        for name in {
            "probability.schema.json",
            "normalised_operator_market.schema.json",
            "market_consensus.schema.json",
            "market_normalisation_result.schema.json",
        }
    }
    assert [case["name"] for case in cases] == [
        "operator_source_ids_too_many",
        "operator_source_ids_duplicate",
        "operator_duplicate_home_outcome",
        "consensus_wrong_outcome_order",
        "normalised_null_consensus",
        "blocked_with_consensus",
    ]
    for case in cases:
        assert case["must_validate"] is False
        with pytest.raises(SchemaValidationError):
            validate_instance(case["instance"], schemas[case["target"]], registry=schemas)
