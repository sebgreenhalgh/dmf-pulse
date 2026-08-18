from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from dmf_pulse.evaluation.artifacts import seal
from dmf_pulse.evaluation.errors import EvaluationError
from dmf_pulse.evaluation.models import CalibrationArtifact, DatasetMode
from dmf_pulse.optimisation.manager_state import OwnershipSpell
from dmf_pulse.prices.artifacts import (
    seal_competing_logit,
    seal_observation,
    seal_price_calibration,
    seal_projection,
)
from dmf_pulse.prices.early_transfer import evaluate_act_now_vs_wait
from dmf_pulse.prices.errors import PriceLeakageError
from dmf_pulse.prices.latent_pressure import (
    initial_latent_pressure,
    transition_after_price_event,
)
from dmf_pulse.prices.models import (
    EarlyTransferAction,
    FlowAnomalyKind,
    ObservationKind,
    PriceCalibrationArtifact,
    PriceEvent,
    PriceMass,
    PricePathDistribution,
    PricePmf,
    PriceProbabilityVector,
    PriceUpdateWindow,
    ProjectionLineage,
)
from dmf_pulse.prices.price_paths import simulate_price_paths
from dmf_pulse.prices.selling_value import (
    build_optimiser_price_scenarios,
    selling_value_distribution,
)
from dmf_pulse.prices.service import PriceService, predict_price
from dmf_pulse.prices.transfer_flows import build_transfer_flow_features
from dmf_pulse.prices.update_cycles import build_price_update_cycles
from tests.prices_helpers import (
    BASE,
    ZERO,
    alternative,
    config,
    fitted_model,
    flow_context,
    observation,
    projection,
    selling_rule,
    spell,
    vector,
)

pytestmark = pytest.mark.unit


def _state(*, state_id: str = "review-state"):
    return initial_latent_pressure(
        state_id=state_id,
        player_id="player-1",
        as_of=BASE,
        config=config(),
    )


def _predict(*, model=None, calibration=None, price_config=None):
    return predict_price(
        player_id="player-1",
        current_price_units=75,
        feature_vector=vector("review-vector"),
        model=model or fitted_model(),
        pressure_state=_state(),
        source_observation_ids=("review-source",),
        source_semantic_hashes=(ZERO,),
        ruleset_id="synthetic-rules",
        ruleset_hash=ZERO,
        dataset_mode=DatasetMode.RECONSTRUCTED,
        config=price_config or config(),
        calibration=calibration,
    )


def _one_update_paths():
    policy = config().price_paths.model_copy(
        update={
            "updates_24h": 1,
            "updates_72h": 1,
            "updates_7d": 1,
            "maximum_exact_scenarios": 3,
        }
    )
    return simulate_price_paths(
        current_price_units=75,
        state=_state(),
        baseline=PriceProbabilityVector(
            probability_fall=Decimal("0.4"),
            probability_no_change=Decimal("0.2"),
            probability_rise=Decimal("0.4"),
        ),
        config=config().model_copy(update={"price_paths": policy}),
        model_lineage=("review",),
    )


def test_prediction_rejects_future_trained_model_and_calibrator() -> None:
    future_model = seal_competing_logit(
        fitted_model().model_copy(
            update={
                "training_cutoff": BASE + timedelta(hours=1),
                "artifact_sha256": ZERO,
            }
        )
    )
    with pytest.raises(PriceLeakageError, match="model training cutoff"):
        _predict(model=future_model)

    binary = seal(
        CalibrationArtifact(
            calibration_id="future-binary",
            method="IDENTITY",
            training_cutoff=BASE + timedelta(hours=1),
            training_record_ids=("prior-row",),
            excluded_outer_origin_ids=(),
            parameters={"intercept": Decimal(0), "slope": Decimal(1)},
            artifact_sha256=ZERO,
        ),
        "artifact_sha256",
    )
    future_calibration = seal_price_calibration(
        PriceCalibrationArtifact(
            calibration_id="future-multiclass",
            calibration_version=config().competing_logit.calibration_version,
            method="IDENTITY",
            training_cutoff=BASE + timedelta(hours=1),
            probability_epsilon=config().competing_logit.calibration_probability_epsilon,
            fall=binary,
            no_change=binary,
            rise=binary,
            artifact_sha256=ZERO,
        )
    )
    with pytest.raises(PriceLeakageError, match="calibration training cutoff"):
        _predict(calibration=future_calibration)


def test_prediction_rejects_configuration_and_state_version_drift() -> None:
    changed = config().model_copy(update={"configuration_id": "OTHER-POLICY"})
    with pytest.raises(ValueError, match="configuration hash"):
        _predict(price_config=changed)
    stale_state = _state().model_copy(update={"state_version": "STALE-STATE"})
    with pytest.raises(ValueError, match="state version"):
        predict_price(
            player_id="player-1",
            current_price_units=75,
            feature_vector=vector("review-vector"),
            model=fitted_model(),
            pressure_state=stale_state,
            source_observation_ids=("review-source",),
            source_semantic_hashes=(ZERO,),
            ruleset_id="synthetic-rules",
            ruleset_hash=ZERO,
            dataset_mode=DatasetMode.RECONSTRUCTED,
            config=config(),
        )

    stale_model = seal_competing_logit(
        fitted_model().model_copy(update={"model_version": "STALE-MODEL", "artifact_sha256": ZERO})
    )
    with pytest.raises(ValueError, match="identity/schema"):
        _predict(model=stale_model)


def test_act_wait_rejects_dataset_mode_bypass_and_tampered_projection() -> None:
    alternatives = (
        alternative(EarlyTransferAction.ACT_NOW, "20"),
        alternative(EarlyTransferAction.WAIT_FOR_INFORMATION, "1"),
        alternative(EarlyTransferAction.DO_NOT_TRANSFER, "0"),
    )
    with pytest.raises(ValueError, match="dataset mode"):
        evaluate_act_now_vs_wait(
            alternatives,
            projection=projection(),
            dataset_mode=DatasetMode.LIVE_OBSERVED,
            config=config(),
        )
    changed_projection = seal_projection(
        projection().model_copy(
            update={
                "activation_statuses": (projection().activation_statuses[0],),
                "projection_sha256": ZERO,
            }
        )
    )
    with pytest.raises(ValueError, match="activation status"):
        evaluate_act_now_vs_wait(
            alternatives,
            projection=changed_projection,
            dataset_mode=DatasetMode.RECONSTRUCTED,
            config=config(),
        )
    changed_config = config().model_copy(update={"configuration_id": "OTHER-POLICY"})
    with pytest.raises(ValueError, match="active configuration"):
        evaluate_act_now_vs_wait(
            alternatives,
            projection=projection(),
            dataset_mode=DatasetMode.RECONSTRUCTED,
            config=changed_config,
        )
    tampered = projection().model_copy(update={"current_price_units": 99})
    with pytest.raises(EvaluationError, match="does not match"):
        evaluate_act_now_vs_wait(
            alternatives,
            projection=tampered,
            dataset_mode=DatasetMode.RECONSTRUCTED,
            config=config(),
        )


def test_repeated_identical_snapshot_is_retained_for_velocity_timing() -> None:
    first = observation(
        "repeat-first",
        hour=0,
        transfers_in_total=1000,
        transfers_out_total=500,
    )
    repeated = seal_observation(
        observation(
            "repeat-second",
            hour=1,
            transfers_in_total=1000,
            transfers_out_total=500,
        ).model_copy(update={"payload_hash": first.payload_hash, "semantic_hash": ZERO})
    )
    changed = observation(
        "repeat-change",
        hour=2,
        transfers_in_total=1200,
        transfers_out_total=500,
    )
    features = build_transfer_flow_features(
        (first, repeated, changed),
        player_id="player-1",
        cutoff=BASE + timedelta(hours=2),
        dataset_mode=DatasetMode.RECONSTRUCTED,
        context=flow_context(),
        config=config(),
    )
    assert features.buys_per_hour == Decimal(200)
    assert FlowAnomalyKind.DUPLICATE_SNAPSHOT in {item.kind for item in features.anomalies}
    assert features.observation_ids == (
        "repeat-first",
        "repeat-second",
        "repeat-change",
    )


def test_multi_unit_price_step_cannot_escape_configured_support() -> None:
    policy = config().price_paths.model_copy(
        update={
            "price_step_units": 2,
            "updates_24h": 1,
            "updates_72h": 1,
            "updates_7d": 1,
            "maximum_exact_scenarios": 3,
        }
    )
    changed = config().model_copy(update={"price_paths": policy})
    paths = simulate_price_paths(
        current_price_units=2,
        state=_state(),
        baseline=PriceProbabilityVector(
            probability_fall=Decimal("0.4"),
            probability_no_change=Decimal("0.2"),
            probability_rise=Decimal("0.4"),
        ),
        config=changed,
        model_lineage=("review",),
    )
    assert min(item.price_units for item in paths.horizons[-1].price_pmf.support) >= 1


def test_price_path_artifact_revalidates_scenario_transitions() -> None:
    policy = config().price_paths.model_copy(
        update={
            "updates_24h": 1,
            "updates_72h": 1,
            "updates_7d": 1,
            "maximum_exact_scenarios": 3,
        }
    )
    changed = config().model_copy(update={"price_paths": policy})
    paths = simulate_price_paths(
        current_price_units=75,
        state=_state(),
        baseline=PriceProbabilityVector(
            probability_fall=Decimal("0.4"),
            probability_no_change=Decimal("0.2"),
            probability_rise=Decimal("0.4"),
        ),
        config=changed,
        model_lineage=("review",),
    )
    payload = paths.model_dump(mode="python")
    scenario = next(
        item for item in payload["scenarios_7d"] if item["events"][0] is not PriceEvent.NO_CHANGE
    )
    scenario["prices_units"] = (
        scenario["prices_units"][0],
        paths.current_price_units,
    )
    with pytest.raises(ValidationError, match="configured price step"):
        PricePathDistribution.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("maximum_price_units", 1, "bounds must be ordered"),
        ("current_price_units", 201, "current price lies outside"),
        ("model_lineage", (), "model lineage must be non-empty"),
    ),
)
def test_price_path_envelope_rejects_invalid_artifact_metadata(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _one_update_paths().model_dump(mode="python")
    payload[field] = value
    with pytest.raises(ValidationError, match=message):
        PricePathDistribution.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("horizon_order", "horizons must be ordered"),
        ("update_count", "scenario length differs"),
        ("any_rise", "any-change probabilities"),
        ("multiple_rises", "multiple-change probabilities"),
    ),
)
def test_price_path_envelope_rejects_internally_inconsistent_artifacts(
    mutation: str,
    message: str,
) -> None:
    payload = deepcopy(_one_update_paths().model_dump(mode="python"))
    horizons = list(payload["horizons"])
    if mutation == "horizon_order":
        horizons[0], horizons[1] = horizons[1], horizons[0]
        horizons[0]["horizon"] = "72h"
        horizons[1]["horizon"] = "24h"
    elif mutation == "update_count":
        horizons[-1]["update_count"] = 2
    elif mutation == "any_rise":
        horizons[-1]["probability_any_rise"] = Decimal(0)
    else:
        payload["probability_multiple_rises_gameweek"] = Decimal(1)
    payload["horizons"] = tuple(horizons)
    with pytest.raises(ValidationError, match=message):
        PricePathDistribution.model_validate(payload)


def test_multiple_rise_probability_includes_existing_gameweek_count() -> None:
    policy = config().price_paths.model_copy(
        update={
            "updates_24h": 1,
            "updates_72h": 1,
            "updates_7d": 1,
            "maximum_exact_scenarios": 3,
        }
    )
    changed = config().model_copy(update={"price_paths": policy})
    state = _state().model_copy(update={"rises_this_gameweek": 1})
    paths = simulate_price_paths(
        current_price_units=75,
        state=state,
        baseline=PriceProbabilityVector(
            probability_fall=Decimal("0.4"),
            probability_no_change=Decimal("0.2"),
            probability_rise=Decimal("0.4"),
        ),
        config=changed,
        model_lineage=("review",),
    )
    assert paths.probability_multiple_rises_gameweek == paths.horizons[-1].probability_any_rise


def test_recurrent_transition_rejects_time_reversal() -> None:
    with pytest.raises(ValueError, match="backward"):
        transition_after_price_event(
            _state(),
            PriceEvent.NO_CHANGE,
            state_id="time-reversal",
            as_of=BASE - timedelta(seconds=1),
            config=config(),
        )


def test_nested_calibration_artifact_must_retain_its_own_seal() -> None:
    binary = seal(
        CalibrationArtifact(
            calibration_id="sealed-binary",
            method="LOGISTIC",
            training_cutoff=BASE,
            training_record_ids=("prior-row",),
            excluded_outer_origin_ids=(),
            parameters={"intercept": Decimal(0), "slope": Decimal(1)},
            artifact_sha256=ZERO,
        ),
        "artifact_sha256",
    )
    artifact = seal_price_calibration(
        PriceCalibrationArtifact(
            calibration_id="nested-seals",
            calibration_version=config().competing_logit.calibration_version,
            method="LOGISTIC",
            training_cutoff=BASE,
            probability_epsilon=config().competing_logit.calibration_probability_epsilon,
            fall=binary,
            no_change=binary,
            rise=binary,
            artifact_sha256=ZERO,
        )
    )
    bad_fall = artifact.fall.model_copy(update={"parameters": {"intercept": Decimal(9)}})
    with pytest.raises(EvaluationError, match="does not match"):
        seal_price_calibration(
            artifact.model_copy(update={"fall": bad_fall, "artifact_sha256": ZERO})
        )


def test_selling_paths_require_active_matching_ownership_spell() -> None:
    closed = OwnershipSpell.model_validate(
        {
            **spell().model_dump(mode="python"),
            "ended_gameweek": 2,
            "ended_at_node_id": "sold",
            "realised_selling_price_tenths": 52,
        }
    )
    market = PricePmf(support=(PriceMass(price_units=55, probability=Decimal(1)),))
    with pytest.raises(ValueError, match="active ownership spell"):
        selling_value_distribution(closed, market, rule=selling_rule())
    wrong_player = spell().model_copy(update={"player_id": "another-player"})
    with pytest.raises(ValueError, match="same player"):
        build_optimiser_price_scenarios(
            player_id="player-1",
            horizon="24h",
            market_price_pmf=market,
            maximum_support=1,
            ownership_spell=wrong_player,
            selling_price_rule=selling_rule(),
        )


def test_projection_lineage_requires_one_hash_per_source_observation() -> None:
    with pytest.raises(ValidationError, match="one semantic hash"):
        ProjectionLineage(
            source_observation_ids=("one", "two"),
            source_semantic_hashes=(ZERO,),
            model_version_ids=("model",),
            calibration_version_ids=(),
            model_artifact_sha256=ZERO,
            calibration_artifact_sha256=None,
            price_path_distribution_sha256=ZERO,
            configuration_sha256=ZERO,
            ruleset_id="rules",
            ruleset_hash=ZERO,
            dataset_mode=DatasetMode.RECONSTRUCTED,
            information_cutoff=BASE,
        )


def test_projection_lineage_canonicalization_preserves_id_hash_pairs() -> None:
    value = predict_price(
        player_id="player-1",
        current_price_units=75,
        feature_vector=vector("paired-lineage-vector"),
        model=fitted_model(),
        pressure_state=_state(),
        source_observation_ids=("z-source", "a-source"),
        source_semantic_hashes=("f" * 64, ZERO),
        ruleset_id="synthetic-rules",
        ruleset_hash=ZERO,
        dataset_mode=DatasetMode.RECONSTRUCTED,
        config=config(),
    )
    assert value.lineage.source_observation_ids == ("a-source", "z-source")
    assert value.lineage.source_semantic_hashes == (ZERO, "f" * 64)

    with pytest.raises(ValueError, match="IDs must be unique"):
        predict_price(
            player_id="player-1",
            current_price_units=75,
            feature_vector=vector("duplicate-lineage-vector"),
            model=fitted_model(),
            pressure_state=_state(),
            source_observation_ids=("same-source", "same-source"),
            source_semantic_hashes=(ZERO, "f" * 64),
            ruleset_id="synthetic-rules",
            ruleset_hash=ZERO,
            dataset_mode=DatasetMode.RECONSTRUCTED,
            config=config(),
        )


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"model_version_ids": ()}, "at least one model version"),
        (
            {"source_observation_ids": ("z", "a"), "source_semantic_hashes": (ZERO, ZERO)},
            "sorted and unique",
        ),
        (
            {"calibration_version_ids": ("calibration",)},
            "version/hash lineage",
        ),
    ),
)
def test_projection_lineage_rejects_incomplete_or_noncanonical_artifact_identity(
    updates: dict[str, object],
    message: str,
) -> None:
    payload = projection().lineage.model_dump(mode="python")
    payload.update(updates)
    with pytest.raises(ValidationError, match=message):
        ProjectionLineage.model_validate(payload)


def test_update_cycle_prefers_later_system_correction_at_same_observed_time() -> None:
    pre = observation("cycle-pre", hour=0, price=75)
    original = observation("a-cycle-original", hour=2, price=76)
    correction = observation(
        "z-cycle-correction",
        hour=2,
        price=75,
        received_delay=1,
        kind=ObservationKind.SOURCE_CORRECTION,
        supersedes="a-cycle-original",
    )
    cycle = build_price_update_cycles(
        (pre, original, correction),
        (
            PriceUpdateWindow(
                cycle_id="corrected-cycle",
                cycle_start=BASE + timedelta(hours=1),
                cycle_end=BASE + timedelta(hours=3),
                information_cutoff=BASE + timedelta(hours=1),
            ),
        ),
        player_id="player-1",
        dataset_mode=DatasetMode.RECONSTRUCTED,
        maximum_label_interval=timedelta(
            minutes=config().update_cycles.maximum_label_interval_minutes
        ),
    )[0]
    assert cycle.event is PriceEvent.NO_CHANGE
    assert cycle.post_update_observation_id == "z-cycle-correction"
    assert cycle.correction_lineage == ("a-cycle-original",)


def test_service_rejects_binary_float_integer_coercion() -> None:
    with pytest.raises(ValidationError):
        PriceService().simulate(
            {
                "current_price_units": 75.9,
                "pressure_state": _state().model_dump(mode="json"),
                "baseline": {
                    "probability_fall": "0.2",
                    "probability_no_change": "0.5",
                    "probability_rise": "0.3",
                },
                "model_lineage": ["review"],
            }
        )
