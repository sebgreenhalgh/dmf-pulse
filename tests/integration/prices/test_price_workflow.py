from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.early_transfer import evaluate_act_now_vs_wait
from dmf_pulse.prices.evaluation import evaluate_price_forecasts
from dmf_pulse.prices.latent_pressure import initial_latent_pressure, update_latent_pressure
from dmf_pulse.prices.models import (
    ActivationStatus,
    EarlyTransferAction,
    PriceEvaluationRow,
    PriceEvent,
    PriceProbabilityVector,
)
from dmf_pulse.prices.selling_value import build_optimiser_price_scenarios
from dmf_pulse.prices.service import PriceService, predict_price
from dmf_pulse.prices.transfer_flows import (
    build_transfer_flow_features,
    transfer_features_to_vector,
)
from tests.prices_helpers import (
    BASE,
    ZERO,
    alternative,
    config,
    fitted_model_for_config,
    flow_context,
    observation,
)

pytestmark = pytest.mark.integration


def _small_config():
    paths = config().price_paths.model_copy(
        update={
            "updates_24h": 1,
            "updates_72h": 2,
            "updates_7d": 3,
            "maximum_exact_scenarios": 27,
        }
    )
    return config().model_copy(update={"price_paths": paths})


def test_synthetic_observation_to_decision_and_scorecard_vertical_slice() -> None:
    price_config = _small_config()
    observations = (
        observation("flow-0", hour=0, transfers_in_total=1000, transfers_out_total=500),
        observation("flow-1", hour=2, transfers_in_total=1400, transfers_out_total=550),
        observation("flow-2", hour=4, transfers_in_total=2100, transfers_out_total=600),
    )
    cutoff = BASE + timedelta(hours=4)
    features = build_transfer_flow_features(
        observations,
        player_id="player-1",
        cutoff=cutoff,
        dataset_mode=DatasetMode.RECONSTRUCTED,
        context=flow_context(),
        config=price_config,
    )
    initial = initial_latent_pressure(
        state_id="initial",
        player_id="player-1",
        as_of=BASE,
        config=price_config,
    )
    pressure = update_latent_pressure(
        initial,
        features,
        state_id="after-flow",
        config=price_config,
    )
    vector = transfer_features_to_vector(features, pressure=pressure, config=price_config)
    projection = predict_price(
        player_id="player-1",
        current_price_units=75,
        feature_vector=vector,
        model=fitted_model_for_config(price_config),
        pressure_state=pressure,
        source_observation_ids=tuple(item.observation_id for item in observations),
        source_semantic_hashes=tuple(item.semantic_hash for item in observations),
        ruleset_id="synthetic-rules",
        ruleset_hash=ZERO,
        dataset_mode=DatasetMode.RECONSTRUCTED,
        config=price_config,
    )
    assert projection.price_pmf_7d.expected_price_units == projection.expected_price_7d
    assert ActivationStatus.SHADOW_ONLY in projection.activation_statuses
    scenarios = build_optimiser_price_scenarios(
        player_id="player-1",
        horizon="7d",
        market_price_pmf=projection.price_pmf_7d,
        maximum_support=7,
        route_budget_units=75,
    )
    assert any(item.route_affordable is False for item in scenarios.scenarios)
    decision = evaluate_act_now_vs_wait(
        (
            alternative(EarlyTransferAction.ACT_NOW, "3"),
            alternative(
                EarlyTransferAction.WAIT_FOR_INFORMATION,
                "4",
                information_value="2",
            ),
            alternative(EarlyTransferAction.DO_NOT_TRANSFER, "0"),
        ),
        projection=projection,
        dataset_mode=DatasetMode.RECONSTRUCTED,
        config=price_config,
    )
    assert decision.recommended_action is EarlyTransferAction.WAIT_FOR_INFORMATION
    report = evaluate_price_forecasts(
        (
            PriceEvaluationRow(
                row_id="vertical-row",
                forecast_origin=cutoff,
                label_available_at=cutoff + timedelta(hours=4),
                probabilities=PriceProbabilityVector(
                    probability_fall=projection.probability_fall_next_update,
                    probability_no_change=projection.probability_no_change_next_update,
                    probability_rise=projection.probability_rise_next_update,
                ),
                observed_event=PriceEvent.RISE,
                price_pmf=projection.price_pmf_24h,
                observed_price_units=76,
                expected_decision_utility=decision.expected_utility,
                realised_decision_utility=Decimal("3"),
                realised_comparator_utility=Decimal("4"),
            ),
        ),
        evaluation_cutoff=cutoff + timedelta(days=1),
        alert_probability=price_config.evaluation.alert_probability,
        probability_epsilon=price_config.evaluation.probability_epsilon,
    )
    assert report.row_count == 1
    assert report.mean_decision_regret == Decimal(1)


def test_service_and_cli_execute_the_physical_replay_fixture(repository_root) -> None:
    path = repository_root / "fixtures/prices/simulate_path.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    direct = PriceService().simulate(payload)
    result = CliRunner().invoke(app, ["prices", "simulate-path", "--input", str(path)])
    assert result.exit_code == 0
    cli_payload = json.loads(result.stdout)
    assert cli_payload == direct.model_dump(mode="json")
    assert len(cli_payload["scenarios_7d"]) == 2187
    assert cli_payload["distribution_sha256"] == direct.distribution_sha256
