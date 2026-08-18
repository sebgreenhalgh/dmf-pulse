from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from dmf_pulse.evaluation.models import CalibrationArtifact, DatasetMode
from dmf_pulse.prices.artifacts import seal_price_calibration
from dmf_pulse.prices.calibration import apply_price_calibration, fit_price_calibration
from dmf_pulse.prices.classifier import (
    fit_competing_logit,
    predict_competing_logit,
    predict_no_change,
)
from dmf_pulse.prices.errors import PriceLeakageError
from dmf_pulse.prices.latent_pressure import (
    initial_latent_pressure,
    transition_after_price_event,
    update_latent_pressure,
)
from dmf_pulse.prices.models import (
    ChipContaminationState,
    PriceCalibrationArtifact,
    PriceEvaluationRow,
    PriceEvent,
    PriceMass,
    PricePmf,
    PriceProbabilityVector,
    PriceTrainingExample,
)
from dmf_pulse.prices.recurrent_hazard import predict_recurrent_hazard, threshold_distance
from dmf_pulse.prices.transfer_flows import build_transfer_flow_features
from tests.prices_helpers import (
    BASE,
    ZERO,
    config,
    fitted_model,
    flow_context,
    observation,
    vector,
)

pytestmark = pytest.mark.unit


def test_p0_is_honest_no_change_and_probability_contract_is_exact() -> None:
    null = predict_no_change()
    assert (
        null.probability_fall,
        null.probability_no_change,
        null.probability_rise,
    ) == (Decimal(0), Decimal(1), Decimal(0))
    with pytest.raises(ValidationError, match="sum exactly"):
        PriceProbabilityVector(
            probability_fall=Decimal("0.1"),
            probability_no_change=Decimal("0.8"),
            probability_rise=Decimal("0.2"),
        )


def test_regularized_competing_logit_is_deterministic_and_proper() -> None:
    artifact = fitted_model()
    first = predict_competing_logit(artifact, vector("prediction"))
    second = predict_competing_logit(artifact, vector("prediction"))
    assert first == second
    assert sum(
        (
            first.probability_fall,
            first.probability_no_change,
            first.probability_rise,
        ),
        Decimal(0),
    ) == Decimal(1)
    assert artifact.training_example_ids == tuple(sorted(artifact.training_example_ids))


def test_training_blocks_future_labels_unsorted_rows_and_schema_drift() -> None:
    example = PriceTrainingExample(
        example_id="future-label",
        feature_vector=vector("future-vector", at=BASE - timedelta(hours=2)),
        event=PriceEvent.RISE,
        label_available_at=BASE + timedelta(hours=1),
        dataset_mode=DatasetMode.RECONSTRUCTED,
    )
    with pytest.raises(PriceLeakageError, match="training cutoff precedes"):
        fit_competing_logit((example,), training_cutoff=BASE, config=config())
    earlier = example.model_copy(
        update={
            "example_id": "earlier",
            "feature_vector": vector("earlier-vector", at=BASE - timedelta(days=2)),
            "label_available_at": BASE - timedelta(days=1),
        }
    )
    later = earlier.model_copy(
        update={
            "example_id": "later",
            "feature_vector": vector("later-vector", at=BASE - timedelta(hours=4)),
            "label_available_at": BASE - timedelta(hours=3),
        }
    )
    with pytest.raises(ValueError, match="chronological canonical order"):
        fit_competing_logit((later, earlier), training_cutoff=BASE, config=config())
    broken_vector = earlier.feature_vector.model_copy(
        update={"values": earlier.feature_vector.values[:-1]}
    )
    broken = earlier.model_copy(update={"feature_vector": broken_vector})
    with pytest.raises(ValueError, match="configured schema"):
        fit_competing_logit((broken,), training_cutoff=BASE, config=config())


def test_latent_pressure_reacts_recurs_and_resets_after_events() -> None:
    cutoff = BASE + timedelta(hours=4)
    features = build_transfer_flow_features(
        (
            observation("start", hour=0, transfers_in_total=1000, transfers_out_total=500),
            observation("surge", hour=4, transfers_in_total=3000, transfers_out_total=550),
        ),
        player_id="player-1",
        cutoff=cutoff,
        dataset_mode=DatasetMode.RECONSTRUCTED,
        context=flow_context(),
        config=config(),
    )
    initial = initial_latent_pressure(
        state_id="initial", player_id="player-1", as_of=BASE, config=config()
    )
    updated = update_latent_pressure(
        initial,
        features,
        observed_event=PriceEvent.NO_CHANGE,
        state_id="updated",
        config=config(),
    )
    assert updated.rise_pressure > updated.fall_pressure
    after_rise = transition_after_price_event(
        updated,
        PriceEvent.RISE,
        state_id="after-rise",
        as_of=cutoff + timedelta(days=1),
        config=config(),
    )
    assert after_rise.rise_pressure < updated.rise_pressure
    assert after_rise.rises_this_gameweek == 1
    assert after_rise.updates_since_rise == 0
    hazard = predict_recurrent_hazard(after_rise, config=config(), baseline=predict_no_change())
    assert hazard.probability_rise > 0
    assert hazard.probability_fall > 0


def test_unknown_chip_state_increases_uncertainty_and_threshold_is_model_inferred() -> None:
    features = build_transfer_flow_features(
        (
            observation("start", hour=0),
            observation("next", hour=2, transfers_in_total=1100, transfers_out_total=550),
        ),
        player_id="player-1",
        cutoff=BASE + timedelta(hours=2),
        dataset_mode=DatasetMode.RECONSTRUCTED,
        context=flow_context(
            active_manager_count=None,
            chip_contamination=ChipContaminationState.UNKNOWN,
            chip_contamination_confidence="0",
        ),
        config=config(),
    )
    state = update_latent_pressure(
        initial_latent_pressure(
            state_id="initial", player_id="player-1", as_of=BASE, config=config()
        ),
        features,
        state_id="unknown-chip",
        config=config(),
    )
    distance = threshold_distance(state, config=config())
    assert state.uncertainty > config().recurrent_pressure.uncertainty_floor
    assert distance.status == "MODEL_INFERRED"
    assert distance.estimated_effective_transfers_remaining is None


def test_identity_calibration_preserves_normalized_probabilities() -> None:
    rows = tuple(
        PriceEvaluationRow(
            row_id=f"row-{index}",
            forecast_origin=BASE + timedelta(days=index),
            label_available_at=BASE + timedelta(days=index, hours=1),
            probabilities=PriceProbabilityVector(
                probability_fall=Decimal("0.2"),
                probability_no_change=Decimal("0.5"),
                probability_rise=Decimal("0.3"),
            ),
            observed_event=event,
            price_pmf=PricePmf(support=(PriceMass(price_units=75, probability=Decimal(1)),)),
            observed_price_units=75,
        )
        for index, event in enumerate((PriceEvent.FALL, PriceEvent.NO_CHANGE, PriceEvent.RISE))
    )
    artifact = fit_price_calibration(
        rows,
        calibration_id="identity",
        calibration_version="identity-v1",
        method="IDENTITY",
        training_cutoff=BASE + timedelta(days=4),
        probability_epsilon=config().competing_logit.calibration_probability_epsilon,
    )
    value = apply_price_calibration(rows[0].probabilities, artifact)
    assert value == rows[0].probabilities


def test_recurrent_transition_rejects_unmodeled_event_and_time_reversal() -> None:
    state = initial_latent_pressure(
        state_id="initial", player_id="player-1", as_of=BASE, config=config()
    )
    with pytest.raises(ValueError, match="modeled event"):
        transition_after_price_event(
            state,
            PriceEvent.AMBIGUOUS,
            state_id="bad",
            as_of=BASE + timedelta(days=1),
            config=config(),
        )


def _binary_calibrator(method: str, parameters: dict[str, Decimal]) -> CalibrationArtifact:
    return CalibrationArtifact(
        calibration_id=f"binary-{method.lower()}",
        method=method,
        training_cutoff=BASE,
        training_record_ids=("row",),
        excluded_outer_origin_ids=(),
        parameters=parameters,
        artifact_sha256=ZERO,
    )


def _multiclass_calibrator(binary: CalibrationArtifact) -> PriceCalibrationArtifact:
    return seal_price_calibration(
        PriceCalibrationArtifact(
            calibration_id=f"multi-{binary.method.lower()}",
            calibration_version="test-v1",
            method=binary.method,
            training_cutoff=BASE,
            probability_epsilon=config().competing_logit.calibration_probability_epsilon,
            fall=binary,
            no_change=binary,
            rise=binary,
            artifact_sha256=ZERO,
        )
    )


def test_logistic_and_isotonic_calibration_paths_are_normalized() -> None:
    logistic = _multiclass_calibrator(
        _binary_calibrator(
            "LOGISTIC",
            {"intercept": Decimal("0.1"), "slope": Decimal("1.2")},
        )
    )
    probabilities = PriceProbabilityVector(
        probability_fall=Decimal("0.2"),
        probability_no_change=Decimal(0),
        probability_rise=Decimal("0.8"),
    )
    logistic_value = apply_price_calibration(probabilities, logistic)
    assert (
        logistic_value.probability_fall
        + logistic_value.probability_no_change
        + logistic_value.probability_rise
        == 1
    )
    isotonic = _multiclass_calibrator(
        _binary_calibrator(
            "ISOTONIC",
            {
                "threshold_0": Decimal("0.3"),
                "value_0": Decimal("0.1"),
                "threshold_1": Decimal("0.7"),
                "value_1": Decimal("0.9"),
            },
        )
    )
    isotonic_value = apply_price_calibration(probabilities, isotonic)
    assert isotonic_value.probability_fall == Decimal("0.1") / Decimal("1.1")
    assert isotonic_value.probability_rise == Decimal(1) - (
        isotonic_value.probability_fall + isotonic_value.probability_no_change
    )


def test_calibration_rejects_empty_rows_and_zero_resulting_mass() -> None:
    with pytest.raises(ValueError, match="requires prior forecast rows"):
        fit_price_calibration(
            (),
            calibration_id="empty",
            calibration_version="v1",
            method="IDENTITY",
            training_cutoff=BASE,
            probability_epsilon=config().competing_logit.calibration_probability_epsilon,
        )
    zero = _multiclass_calibrator(
        _binary_calibrator(
            "ISOTONIC",
            {"threshold_0": Decimal(1), "value_0": Decimal(0)},
        )
    )
    with pytest.raises(ValueError, match="no probability mass"):
        apply_price_calibration(
            PriceProbabilityVector(
                probability_fall=Decimal("0.2"),
                probability_no_change=Decimal("0.5"),
                probability_rise=Decimal("0.3"),
            ),
            zero,
        )


def test_price_calibration_blocks_labels_not_available_at_training_cutoff() -> None:
    row = PriceEvaluationRow(
        row_id="future-calibration-row",
        forecast_origin=BASE,
        label_available_at=BASE + timedelta(hours=2),
        probabilities=PriceProbabilityVector(
            probability_fall=Decimal("0.2"),
            probability_no_change=Decimal("0.5"),
            probability_rise=Decimal("0.3"),
        ),
        observed_event=PriceEvent.RISE,
        price_pmf=PricePmf(support=(PriceMass(price_units=76, probability=Decimal(1)),)),
        observed_price_units=76,
    )
    with pytest.raises(PriceLeakageError, match="precedes label availability"):
        fit_price_calibration(
            (row,),
            calibration_id="future-blocked",
            calibration_version="v1",
            method="IDENTITY",
            training_cutoff=BASE + timedelta(hours=1),
            probability_epsilon=config().competing_logit.calibration_probability_epsilon,
        )
