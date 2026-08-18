from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.evaluation.artifacts import verify_sealed
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.artifacts import (
    load_price_artifact,
    persist_price_artifact,
    seal_projection,
)
from dmf_pulse.prices.configuration import load_price_config
from dmf_pulse.prices.early_transfer import evaluate_act_now_vs_wait
from dmf_pulse.prices.evaluation import evaluate_price_forecasts
from dmf_pulse.prices.models import (
    ActivationStatus,
    EarlyTransferAction,
    PriceEvaluationRow,
    PriceEvent,
    PriceMass,
    PricePmf,
    PriceProbabilityVector,
)
from dmf_pulse.prices.service import PriceService
from tests.prices_helpers import (
    BASE,
    ZERO,
    alternative,
    config,
    fitted_model,
    projection,
)

pytestmark = pytest.mark.unit


def _alternatives(*, act: str = "4", wait: str = "6", no_transfer: str = "0"):
    return (
        alternative(EarlyTransferAction.ACT_NOW, act),
        alternative(
            EarlyTransferAction.WAIT_FOR_INFORMATION,
            wait,
            information_value="1",
        ),
        alternative(EarlyTransferAction.DO_NOT_TRANSFER, no_transfer),
    )


def _row(index: int, event: PriceEvent, probabilities: tuple[str, str, str]):
    price = 74 if event is PriceEvent.FALL else 76 if event is PriceEvent.RISE else 75
    return PriceEvaluationRow(
        row_id=f"row-{index}",
        forecast_origin=BASE + timedelta(days=index),
        label_available_at=BASE + timedelta(days=index, hours=2),
        probabilities=PriceProbabilityVector(
            probability_fall=Decimal(probabilities[0]),
            probability_no_change=Decimal(probabilities[1]),
            probability_rise=Decimal(probabilities[2]),
        ),
        observed_event=event,
        price_pmf=PricePmf(
            support=(
                PriceMass(price_units=74, probability=Decimal(probabilities[0])),
                PriceMass(price_units=75, probability=Decimal(probabilities[1])),
                PriceMass(price_units=76, probability=Decimal(probabilities[2])),
            )
        ),
        observed_price_units=price,
        expected_decision_utility=Decimal("3"),
        realised_decision_utility=Decimal("2"),
        realised_comparator_utility=Decimal("5"),
    )


def test_act_wait_uses_complete_utility_not_probability_threshold() -> None:
    decision = evaluate_act_now_vs_wait(
        _alternatives(),
        projection=projection(),
        dataset_mode=DatasetMode.RECONSTRUCTED,
        config=config(),
    )
    assert decision.recommended_action is EarlyTransferAction.WAIT_FOR_INFORMATION
    assert decision.actionable is True
    assert decision.price_probability_used_as_component_only is True
    assert decision.rationale_codes == (
        "COMPLETE_UTILITY_MAXIMUM",
        "PRICE_PROBABILITY_COMPONENT_ONLY",
    )


def test_live_mode_fails_closed_even_when_act_has_highest_utility() -> None:
    base_projection = projection()
    live_projection = seal_projection(
        base_projection.model_copy(
            update={
                "lineage": base_projection.lineage.model_copy(
                    update={"dataset_mode": DatasetMode.LIVE_OBSERVED}
                ),
                "projection_sha256": ZERO,
            }
        )
    )
    decision = evaluate_act_now_vs_wait(
        _alternatives(act="20", wait="1"),
        projection=live_projection,
        dataset_mode=DatasetMode.LIVE_OBSERVED,
        config=config(),
    )
    assert decision.recommended_action is EarlyTransferAction.MANUAL_REVIEW
    assert decision.selected_route_id is None
    assert decision.actionable is False
    assert ActivationStatus.TARGET_SEASON_UNCALIBRATED in decision.activation_statuses


def test_price_only_hit_false_alarm_does_not_force_act_now() -> None:
    alternatives = (
        alternative(EarlyTransferAction.ACT_NOW, "7", hit="4"),
        alternative(
            EarlyTransferAction.WAIT_FOR_INFORMATION,
            "5",
            information_value="2",
            free_transfer_value="1",
        ),
        alternative(EarlyTransferAction.DO_NOT_TRANSFER, "0"),
    )
    decision = evaluate_act_now_vs_wait(
        alternatives,
        projection=projection(),
        dataset_mode=DatasetMode.RECONSTRUCTED,
        config=config(),
    )
    assert decision.recommended_action is EarlyTransferAction.WAIT_FOR_INFORMATION


def test_decision_rejects_missing_or_duplicate_core_alternatives() -> None:
    with pytest.raises(ValueError, match="mandatory"):
        evaluate_act_now_vs_wait(
            _alternatives()[:-1],
            projection=projection(),
            dataset_mode=DatasetMode.RECONSTRUCTED,
            config=config(),
        )
    duplicate = (*_alternatives(), _alternatives()[0])
    with pytest.raises(ValueError, match="unique"):
        evaluate_act_now_vs_wait(
            duplicate,
            projection=projection(),
            dataset_mode=DatasetMode.RECONSTRUCTED,
            config=config(),
        )


def test_stage12_price_scorecard_includes_probability_distribution_and_regret() -> None:
    rows = (
        _row(0, PriceEvent.FALL, ("0.7", "0.2", "0.1")),
        _row(1, PriceEvent.NO_CHANGE, ("0.1", "0.8", "0.1")),
        _row(2, PriceEvent.RISE, ("0.1", "0.2", "0.7")),
    )
    report = evaluate_price_forecasts(
        rows,
        evaluation_cutoff=BASE + timedelta(days=4),
        alert_probability=config().evaluation.alert_probability,
        probability_epsilon=config().evaluation.probability_epsilon,
    )
    assert report.row_count == 3
    assert report.price_horizon == "24h"
    assert report.multiclass_brier >= 0
    assert report.rise_precision == Decimal(1)
    assert report.fall_recall == Decimal(1)
    assert report.no_change_calibration_status
    assert report.mean_decision_regret == Decimal(3)
    assert len(report.stage12_metric_lineage) == 4


def test_evaluation_rejects_future_labels_and_nonchronological_rows() -> None:
    first = _row(0, PriceEvent.FALL, ("0.7", "0.2", "0.1"))
    second = _row(1, PriceEvent.RISE, ("0.1", "0.2", "0.7"))
    with pytest.raises(ValueError, match="chronologically ordered"):
        evaluate_price_forecasts(
            (second, first),
            evaluation_cutoff=BASE + timedelta(days=3),
            alert_probability=config().evaluation.alert_probability,
            probability_epsilon=config().evaluation.probability_epsilon,
        )
    with pytest.raises(ValueError, match="precedes"):
        evaluate_price_forecasts(
            (first,),
            evaluation_cutoff=BASE,
            alert_probability=config().evaluation.alert_probability,
            probability_epsilon=config().evaluation.probability_epsilon,
        )
    mixed_horizon = second.model_copy(update={"horizon": "7d"})
    with pytest.raises(ValueError, match="mix forecast horizons"):
        evaluate_price_forecasts(
            (first, mixed_horizon),
            evaluation_cutoff=BASE + timedelta(days=3),
            alert_probability=config().evaluation.alert_probability,
            probability_epsilon=config().evaluation.probability_epsilon,
        )


def test_write_once_price_artifact_round_trip_and_collision(tmp_path) -> None:
    artifact = fitted_model()
    receipt = persist_price_artifact(
        artifact,
        hash_field="artifact_sha256",
        artifact_root=tmp_path,
        category="models",
        identity=artifact.model_id,
    )
    loaded = load_price_artifact(
        Path(receipt.artifact_path),
        type(artifact),
        hash_field="artifact_sha256",
    )
    assert loaded == artifact
    verify_sealed(loaded, "artifact_sha256")
    repeated = persist_price_artifact(
        artifact,
        hash_field="artifact_sha256",
        artifact_root=tmp_path,
        category="models",
        identity=artifact.model_id,
    )
    assert repeated == receipt


def test_configuration_and_validation_declare_p0_p1_p2_and_block_production() -> None:
    loaded = load_price_config()
    report = PriceService(loaded).validate()
    assert report.status == "ENGINEERING_READY"
    assert tuple(item.value for item in report.implemented_models) == (
        "P0_NO_CHANGE",
        "P1_REGULARIZED_COMPETING_LOGIT",
        "P2_RECURRENT_LATENT_PRESSURE",
    )
    assert report.challenger_status.value == "DEPENDENCY_NOT_APPROVED"
    assert report.production_actionable is False
    assert report.automated_provider_capture is False
    assert report.configuration_role == "POLICY_CONFIGURATION"
    assert report.parameter_status == "PROVISIONAL_MODEL_PARAMETER"
    assert report.evidence_status == "SYNTHETIC_REFERENCE"
