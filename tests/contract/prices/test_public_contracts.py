from __future__ import annotations

import inspect
from decimal import Decimal

import pytest
from pydantic import ValidationError

import dmf_pulse.prices as prices
from dmf_pulse.evaluation.artifacts import verify_sealed
from dmf_pulse.evaluation.errors import EvaluationError
from dmf_pulse.prices.benchmarks import configured_benchmark_ids, gbdt_challenger_status
from dmf_pulse.prices.configuration import load_price_config, price_config_sha256
from dmf_pulse.prices.models import PriceMass, PricePmf
from tests.prices_helpers import fitted_model

pytestmark = pytest.mark.contract


def test_public_price_surface_is_explicit_and_stable() -> None:
    assert prices.__all__ == [
        "EarlyTransferDecision",
        "PricePathDistribution",
        "PriceProjection",
        "PriceUpdateCycle",
        "ThresholdDistance",
        "TransferFlowFeatures",
        "evaluate_act_now_vs_wait",
        "predict_price",
        "simulate_price_paths",
    ]
    assert set(inspect.signature(prices.predict_price).parameters) == {
        "player_id",
        "current_price_units",
        "feature_vector",
        "model",
        "pressure_state",
        "source_observation_ids",
        "source_semantic_hashes",
        "ruleset_id",
        "ruleset_hash",
        "dataset_mode",
        "config",
        "calibration",
    }


def test_price_contracts_are_frozen_extra_forbid_and_exact_decimal() -> None:
    value = PricePmf(support=(PriceMass(price_units=75, probability=Decimal(1)),))
    with pytest.raises(ValidationError, match="frozen"):
        value.support = ()  # type: ignore[misc]
    payload = value.model_dump()
    payload["unknown"] = "blocked"
    with pytest.raises(ValidationError, match="Extra inputs"):
        PricePmf.model_validate(payload)
    with pytest.raises(ValidationError, match="binary floats"):
        PriceMass(price_units=75, probability=1.0)


def test_benchmark_contract_includes_p0_p1_p2_and_external_only_by_identity() -> None:
    value = configured_benchmark_ids(load_price_config())
    assert set(value) >= {
        "P0_NO_CHANGE",
        "P1_REGULARIZED_COMPETING_LOGIT",
        "P2_RECURRENT_LATENT_PRESSURE",
        "OFFICIAL_FPL_PREDICTOR",
        "LIVEFPL",
        "FANTASY_FOOTBALL_FIX",
        "OTHER_APPROVED_EXTERNAL",
    }
    assert gbdt_challenger_status(load_price_config()).value == "DEPENDENCY_NOT_APPROVED"


def test_repository_and_packaged_configuration_are_semantically_identical(repository_root) -> None:
    packaged = load_price_config()
    repository = load_price_config(repository_root / "config/models/price_baseline.yaml")
    assert repository == packaged
    assert price_config_sha256(repository) == price_config_sha256(packaged)


def test_fitted_artifact_hash_detects_tampering() -> None:
    artifact = fitted_model()
    verify_sealed(artifact, "artifact_sha256")
    tampered = artifact.model_copy(update={"epochs": artifact.epochs + 1})
    with pytest.raises(EvaluationError, match="does not match"):
        verify_sealed(tampered, "artifact_sha256")
