"""Frozen policy authentication and semantic-drift boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import dmf_pulse.markets.policy as policy_module
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.markets.policy import (
    CONFIDENCE_GATE_POLICY_SHA256,
    CONFIDENCE_GRADES,
    POLICY_SHA256,
    MarketNormalisationPolicy,
    canonical_json_sha256,
    confidence_gate,
    load_confidence_gate_policy,
    load_market_normalisation_policy,
)

pytestmark = pytest.mark.unit


def _document() -> dict[str, object]:
    return json.loads(policy_module._policy_resource())


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (("vector_residual_outcome_order", ["AWAY", "DRAW", "HOME"]), "residual order"),
        (("sensitivity_methods", []), "sensitivity methods"),
    ),
)
def test_policy_rejects_frozen_sequence_drift(
    mutation: tuple[str, object],
    message: str,
) -> None:
    value = _document()
    value[mutation[0]] = mutation[1]
    with pytest.raises(ValidationError, match=message):
        MarketNormalisationPolicy.model_validate_json(json.dumps(value))


def test_policy_rejects_any_confidence_threshold_drift() -> None:
    value = _document()
    confidence = value["confidence"]
    assert isinstance(confidence, dict)
    grade_b = confidence["B"]
    assert isinstance(grade_b, dict)
    grade_b["maximum_age_seconds"] = 1799
    with pytest.raises(ValidationError, match="confidence thresholds"):
        MarketNormalisationPolicy.model_validate_json(json.dumps(value))


def test_confidence_gates_are_typed_and_bound_to_the_frozen_policy_hash() -> None:
    expected = {
        "A": (False, "NONE"),
        "B": (False, "NONBLOCKING"),
        "C": (True, "BLOCKING"),
        "D": (True, "BLOCKING"),
    }
    assert set(CONFIDENCE_GRADES) == set(expected)
    assert {
        grade: (
            confidence_gate(POLICY_SHA256, grade).fallback_allowed,
            confidence_gate(POLICY_SHA256, grade).maximum_warning_level,
        )
        for grade in CONFIDENCE_GRADES
    } == expected
    with pytest.raises(IngestionError) as caught:
        confidence_gate("0" * 64, "A")
    assert caught.value.code == "POLICY_INVALID"


def test_confidence_gate_policy_is_versioned_and_matches_repository_config(
    repository_root: Path,
) -> None:
    loaded = load_confidence_gate_policy()
    config = json.loads(
        (repository_root / "config/markets/confidence_gate_policy.json").read_text(encoding="utf-8")
    )
    assert loaded.policy_id == "market-normalisation-confidence-gates-v1"
    assert loaded.normalisation_policy_sha256 == POLICY_SHA256
    assert loaded.sha256 == CONFIDENCE_GATE_POLICY_SHA256
    assert canonical_json_sha256(config) == CONFIDENCE_GATE_POLICY_SHA256
    assert loaded.model_dump(mode="json", exclude={"sha256"}) == config


def test_loader_rejects_non_object_and_hash_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy_module, "_policy_resource", lambda: b"[]")
    with pytest.raises(IngestionError) as non_object:
        load_market_normalisation_policy()
    assert non_object.value.code == "POLICY_INVALID"

    monkeypatch.setattr(policy_module, "_policy_resource", lambda: b"{}")
    with pytest.raises(IngestionError) as hash_drift:
        load_market_normalisation_policy()
    assert hash_drift.value.code == "POLICY_INVALID"


def test_confidence_gate_loader_rejects_non_object_and_hash_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy_module, "_confidence_gate_policy_resource", lambda: b"[]")
    with pytest.raises(IngestionError) as non_object:
        load_confidence_gate_policy()
    assert non_object.value.code == "POLICY_INVALID"

    monkeypatch.setattr(policy_module, "_confidence_gate_policy_resource", lambda: b"{}")
    with pytest.raises(IngestionError) as hash_drift:
        load_confidence_gate_policy()
    assert hash_drift.value.code == "POLICY_INVALID"


def test_loader_separately_authenticates_embedded_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _document()
    value["sha256"] = "0" * 64
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    monkeypatch.setattr(policy_module, "_policy_resource", lambda: raw)
    monkeypatch.setattr(policy_module, "POLICY_SHA256", canonical_json_sha256(value))
    with pytest.raises(IngestionError) as caught:
        load_market_normalisation_policy()
    assert caught.value.code == "POLICY_INVALID"
