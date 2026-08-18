from __future__ import annotations

import copy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.prices.configuration import (
    load_price_config,
    reconcile_price_config_with_rules,
)
from dmf_pulse.prices.errors import PriceError
from dmf_pulse.prices.models import (
    ActivationStatus,
    ExternalPredictorObservation,
    ExternalPredictorProvider,
    PriceEvent,
    PriceMass,
    PricePmf,
)
from dmf_pulse.prices.selling_value import selling_value_distribution
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules
from tests.prices_helpers import ZERO, spell

pytestmark = pytest.mark.integration

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TARGET_RULES = REPOSITORY_ROOT / "config/rules/fpl-2026-27"


def test_stage13_reconciles_with_current_rules_without_model_activation() -> None:
    config = load_price_config()
    compiled = compile_ruleset(TARGET_RULES)

    binding = reconcile_price_config_with_rules(config, compiled)

    assert binding.ruleset_id == "fpl-2026-27"
    assert binding.ruleset_hash == compiled.ruleset_hash
    assert binding.price_unit == "TENTHS_OF_MILLION_GBP"
    assert binding.integer_only is True
    assert binding.price_step_units == 1
    assert binding.mechanics_authority == "DMFP-02_RULESET"
    assert binding.change_threshold_algorithm == "UNDISCLOSED"
    assert set(config.activation.production_statuses) == {
        ActivationStatus.RIGHTS_BLOCKED,
        ActivationStatus.SHADOW_ONLY,
        ActivationStatus.TARGET_SEASON_UNCALIBRATED,
    }


def test_stage13_uses_current_rules_selling_value_without_local_override() -> None:
    compiled = compile_ruleset(TARGET_RULES)
    transfer_rules = build_multi_gameweek_transfer_rules(
        compiled,
        projection_mode=ProjectionMode.TEST,
    )
    market = PricePmf(
        support=(
            PriceMass(price_units=47, probability=Decimal("0.25")),
            PriceMass(price_units=53, probability=Decimal("0.25")),
            PriceMass(price_units=54, probability=Decimal("0.5")),
        )
    )

    selling = selling_value_distribution(
        spell(purchase=50, current=50),
        market,
        rule=transfer_rules.selling_price_rule,
    )

    assert tuple((item.price_units, item.probability) for item in selling.support) == (
        (47, Decimal("0.25")),
        (51, Decimal("0.25")),
        (52, Decimal("0.5")),
    )


def test_official_predictor_progress_is_not_promoted_to_probability() -> None:
    observed_at = datetime(2026, 8, 21, 23, 45, tzinfo=UTC)
    observation = ExternalPredictorObservation(
        observation_id="official-progress-105",
        external_predictor_key="official:player-1:rise",
        provider=ExternalPredictorProvider.OFFICIAL_FPL_PREDICTOR,
        player_id="player-1",
        direction=PriceEvent.RISE,
        displayed_progress=Decimal("105"),
        displayed_categorical_signal="VERY_LIKELY_TO_RISE",
        observed_at=observed_at,
        received_at=observed_at,
        usable_at=observed_at,
        source="SRC-FPL-2026-PRICE-001",
        source_snapshot_id="official-price-predictor-capture",
        rights_profile_id="OFFICIAL-FIRST-PARTY-BENCHMARK-REVIEW-ONLY",
        schema_revision="official-2026-27-v1",
        dataset_mode=DatasetMode.RECONSTRUCTED,
        payload_hash=ZERO,
        semantic_hash=ZERO,
    )

    assert observation.displayed_progress == Decimal("105")
    assert observation.signal_semantics == "PROGRESS_SIGNAL_NOT_CALIBRATED_PROBABILITY"
    assert observation.threshold_algorithm_disclosed is False
    assert load_price_config().activation.automated_capture_allowed is False


def test_rules_reconciliation_rejects_tampered_compiled_mechanics() -> None:
    config = load_price_config()
    compiled = compile_ruleset(TARGET_RULES)
    rules = copy.deepcopy(compiled.rules)
    rules["prices"]["price_unit"] = "UNSUPPORTED"
    tampered = compiled.model_copy(update={"rules": rules})

    with pytest.raises(PriceError, match="hash does not match"):
        reconcile_price_config_with_rules(config, tampered)
