from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.errors import PriceError
from dmf_pulse.prices.latent_pressure import initial_latent_pressure
from dmf_pulse.prices.models import (
    FlowAnomalyKind,
    ObservationKind,
    OwnershipRegime,
    PriceStatus,
)
from dmf_pulse.prices.transfer_flows import (
    build_transfer_flow_features,
    transfer_features_to_vector,
)
from tests.prices_helpers import BASE, config, flow_context, observation

pytestmark = pytest.mark.unit


def _features(observations, *, strict_temporal: bool = True, **context_updates):
    return build_transfer_flow_features(
        observations,
        player_id="player-1",
        cutoff=BASE + timedelta(hours=12),
        dataset_mode=DatasetMode.RECONSTRUCTED,
        context=flow_context(**context_updates),
        config=config(),
        strict_temporal=strict_temporal,
    )


def test_raw_velocity_momentum_and_ownership_features_reconcile() -> None:
    values = (
        observation("a", hour=0, transfers_in_total=1000, transfers_out_total=500),
        observation("b", hour=2, transfers_in_total=1300, transfers_out_total=600),
        observation("c", hour=4, transfers_in_total=1800, transfers_out_total=650),
    )
    features = _features(values)
    assert (features.transfer_in_increment, features.transfer_out_increment) == (500, 50)
    assert features.net_increment == 450
    assert features.gross_increment == 550
    assert features.acceleration > 0
    assert features.buy_rate_nonowners is not None
    assert features.sell_rate_owners is not None
    assert features.ownership_regime is OwnershipRegime.MEDIUM
    assert features.global_activity_regime == "NORMAL"


def test_gameweek_reset_and_stale_interval_are_anomalies_not_transfer_events() -> None:
    first = observation(
        "gw1",
        hour=0,
        gameweek=1,
        transfers_in_total=1000,
        transfers_out_total=500,
        transfers_in_event=900,
        transfers_out_event=400,
    )
    reset = observation(
        "gw2",
        hour=10,
        gameweek=2,
        transfers_in_total=1100,
        transfers_out_total=550,
        transfers_in_event=50,
        transfers_out_event=25,
    )
    features = _features((first, reset))
    kinds = {item.kind for item in features.anomalies}
    assert FlowAnomalyKind.GAMEWEEK_COUNTER_RESET in kinds
    assert FlowAnomalyKind.STALE_SNAPSHOT in kinds
    assert features.net_increment == 50


def test_source_correction_drop_is_clamped_and_classified() -> None:
    first = observation("before", hour=0, transfers_in_total=1000, transfers_out_total=500)
    correction = observation(
        "correction",
        hour=2,
        transfers_in_total=900,
        transfers_out_total=450,
        kind=ObservationKind.SOURCE_CORRECTION,
        supersedes="before",
    )
    features = _features((first, correction))
    assert features.transfer_in_increment == 0
    assert features.transfer_out_increment == 0
    assert {item.kind for item in features.anomalies} == {
        FlowAnomalyKind.SOURCE_CORRECTION_COUNTER_DROP
    }


def test_ordinary_counter_drop_and_out_of_order_are_audited() -> None:
    first = observation("first", hour=0, transfers_in_total=1000, transfers_out_total=500)
    second = observation("second", hour=2, transfers_in_total=900, transfers_out_total=450)
    features = _features((second, first))
    kinds = {item.kind for item in features.anomalies}
    assert FlowAnomalyKind.CUMULATIVE_COUNTER_DECREASE in kinds
    assert FlowAnomalyKind.OUT_OF_ORDER_SNAPSHOT in kinds


def test_duplicate_payload_and_timestamp_collision_are_deterministic() -> None:
    first = observation("first", hour=0, transfers_in_total=1000, transfers_out_total=500)
    duplicate = observation("duplicate", hour=1, transfers_in_total=1100, transfers_out_total=550)
    duplicate = duplicate.model_copy(update={"payload_hash": first.payload_hash})
    collision = observation("collision", hour=0, transfers_in_total=1200, transfers_out_total=600)
    final = observation("final", hour=2, transfers_in_total=1300, transfers_out_total=650)
    # Reseal after the explicit synthetic payload-identity mutation.
    duplicate = duplicate.model_copy(update={"semantic_hash": "0" * 64})
    from dmf_pulse.prices.artifacts import seal_observation

    duplicate = seal_observation(duplicate)
    features = _features((first, collision, duplicate, final))
    kinds = {item.kind for item in features.anomalies}
    assert FlowAnomalyKind.DUPLICATE_SNAPSHOT in kinds
    assert FlowAnomalyKind.TIMESTAMP_COLLISION in kinds


def test_low_ownership_unknown_denominators_and_injury_sales_fail_closed() -> None:
    values = (
        observation(
            "healthy",
            hour=0,
            ownership="1.9",
            transfers_in_total=1000,
            transfers_out_total=500,
        ),
        observation(
            "injury",
            hour=2,
            ownership="1.9",
            transfers_in_total=1010,
            transfers_out_total=1500,
            status=PriceStatus.INJURED,
        ),
    )
    features = _features(values, active_manager_count=None, global_transfer_activity=None)
    assert features.ownership_regime is OwnershipRegime.LOW
    assert features.net_increment == -990
    assert features.estimated_owner_pool is None
    assert features.denominator_uncertainty == Decimal(1)
    assert features.global_activity_regime == "UNKNOWN"
    assert features.status_transition == "AVAILABLE->INJURED"


def test_feature_vector_matches_versioned_schema() -> None:
    features = _features(
        (
            observation("a", hour=0),
            observation("b", hour=2, transfers_in_total=1200, transfers_out_total=550),
        )
    )
    pressure = initial_latent_pressure(
        state_id="initial", player_id="player-1", as_of=features.information_cutoff, config=config()
    )
    value = transfer_features_to_vector(features, pressure=pressure, config=config())
    assert tuple(item.name for item in value.values) == config().competing_logit.feature_names
    assert value.information_cutoff == features.information_cutoff


def test_insufficient_or_duplicate_only_history_is_rejected() -> None:
    with pytest.raises(PriceError, match="at least two"):
        _features((observation("only", hour=0),))
    first = observation("first", hour=0)
    second = observation("second", hour=1)
    second = second.model_copy(
        update={
            "payload_hash": first.payload_hash,
            "semantic_hash": semantic_sha256({"synthetic": "still-sealed-below"}),
        }
    )
    from dmf_pulse.prices.artifacts import seal_observation

    second = seal_observation(second.model_copy(update={"semantic_hash": "0" * 64}))
    with pytest.raises(PriceError, match="two distinct"):
        _features((first, second))
