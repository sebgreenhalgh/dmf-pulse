from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from dmf_pulse.evaluation.artifacts import seal
from dmf_pulse.evaluation.errors import LeakageError
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.models import (
    ExternalPredictorObservation,
    ExternalPredictorProvider,
    LabelConfidence,
    PriceEvent,
    PriceObservation,
    PriceUpdateWindow,
)
from dmf_pulse.prices.observations import (
    eligible_external_predictor_observations,
    eligible_price_observations,
)
from dmf_pulse.prices.update_cycles import build_price_update_cycles
from tests.prices_helpers import BASE, ZERO, config, observation

pytestmark = pytest.mark.unit


def _external(
    observation_id: str,
    *,
    observed_hour: int,
    usable_hour: int,
    predicted_progress: str | None = "75",
    available_hour: int | None = None,
) -> ExternalPredictorObservation:
    value = ExternalPredictorObservation(
        observation_id=observation_id,
        external_predictor_key=f"external:{observation_id}",
        provider=ExternalPredictorProvider.OFFICIAL_FPL_PREDICTOR,
        player_id="player-1",
        direction=PriceEvent.RISE,
        displayed_progress=Decimal("70"),
        predicted_progress=(
            Decimal(predicted_progress) if predicted_progress is not None else None
        ),
        predicted_progress_available_at=(
            BASE + timedelta(hours=available_hour) if available_hour is not None else None
        ),
        observed_at=BASE + timedelta(hours=observed_hour),
        received_at=BASE + timedelta(hours=observed_hour),
        usable_at=BASE + timedelta(hours=usable_hour),
        source="synthetic-external",
        source_snapshot_id=f"snapshot:{observation_id}",
        rights_profile_id="SYNTHETIC-TEST-ONLY",
        schema_revision="synthetic-v1",
        dataset_mode=DatasetMode.RECONSTRUCTED,
        payload_hash=ZERO,
        semantic_hash=ZERO,
    )
    return seal(value, "semantic_hash")


def test_price_observation_is_immutable_and_rejects_naive_time_and_float() -> None:
    value = observation("immutable", hour=0)
    with pytest.raises(ValidationError, match="frozen"):
        value.current_price_units = 76  # type: ignore[misc]
    payload = value.model_dump()
    payload["observed_at"] = BASE.replace(tzinfo=None)
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        PriceObservation.model_validate(payload)
    payload = value.model_dump()
    payload["ownership_percent"] = 10.5
    with pytest.raises(ValidationError, match="binary floats"):
        PriceObservation.model_validate(payload)


def test_post_cutoff_and_late_usable_price_snapshots_are_blocked() -> None:
    eligible = observation("eligible", hour=-2)
    post_midnight = observation("post-midnight", hour=1)
    late = observation("late", hour=-1, received_delay=1, usable_delay=1)
    values = (eligible, post_midnight, late)
    with pytest.raises(LeakageError, match="cross observed/received/usable cutoff"):
        eligible_price_observations(
            values,
            player_id="player-1",
            cutoff=BASE,
            dataset_mode=DatasetMode.RECONSTRUCTED,
        )
    admitted = eligible_price_observations(
        values,
        player_id="player-1",
        cutoff=BASE,
        dataset_mode=DatasetMode.RECONSTRUCTED,
        strict=False,
    )
    assert tuple(item.observation_id for item in admitted) == ("eligible",)


def test_external_predictor_future_and_field_availability_are_guarded() -> None:
    eligible = _external("eligible-external", observed_hour=-2, usable_hour=-1)
    future = _external("future-external", observed_hour=1, usable_hour=1)
    with pytest.raises(LeakageError):
        eligible_external_predictor_observations(
            (eligible, future),
            player_id="player-1",
            gameweek=1,
            cutoff=BASE,
            dataset_mode=DatasetMode.RECONSTRUCTED,
        )
    admitted = eligible_external_predictor_observations(
        (eligible, future),
        player_id="player-1",
        gameweek=1,
        cutoff=BASE,
        dataset_mode=DatasetMode.RECONSTRUCTED,
        strict=False,
    )
    assert admitted == (eligible,)
    with pytest.raises(ValidationError, match="cannot be backfilled"):
        _external(
            "premature-field",
            observed_hour=-2,
            usable_hour=-1,
            available_hour=0,
        )


def test_clean_rise_no_change_fall_cycle_sequence() -> None:
    observations = (
        observation("o0", hour=0, price=75),
        observation("o1", hour=2, price=76),
        observation("o2", hour=4, price=76),
        observation("o3", hour=6, price=75),
    )
    windows = tuple(
        PriceUpdateWindow(
            cycle_id=f"cycle-{index}",
            cycle_start=BASE + timedelta(hours=start),
            cycle_end=BASE + timedelta(hours=start + 2),
            information_cutoff=BASE + timedelta(hours=start),
            event_effective_at=BASE + timedelta(hours=start + 1),
        )
        for index, start in enumerate((1, 3, 5))
    )
    cycles = build_price_update_cycles(
        observations,
        windows,
        player_id="player-1",
        dataset_mode=DatasetMode.RECONSTRUCTED,
        maximum_label_interval=timedelta(
            minutes=config().update_cycles.maximum_label_interval_minutes
        ),
    )
    assert tuple(item.event for item in cycles) == (
        PriceEvent.RISE,
        PriceEvent.NO_CHANGE,
        PriceEvent.FALL,
    )
    assert cycles[0].label_confidence is LabelConfidence.EXACT
    assert cycles[1].label_confidence is LabelConfidence.INTERVAL_CENSORED


def test_ambiguous_and_missing_update_windows_are_explicit() -> None:
    pre = observation("pre", hour=0, price=75)
    far = observation("far", hour=10, price=77)
    ambiguous_window = PriceUpdateWindow(
        cycle_id="ambiguous",
        cycle_start=BASE + timedelta(hours=1),
        cycle_end=BASE + timedelta(hours=11),
        information_cutoff=BASE + timedelta(hours=1),
    )
    missing_window = PriceUpdateWindow(
        cycle_id="missing",
        cycle_start=BASE + timedelta(hours=20),
        cycle_end=BASE + timedelta(hours=21),
        information_cutoff=BASE + timedelta(hours=20),
    )
    ambiguous, missing = build_price_update_cycles(
        (pre, far),
        (ambiguous_window, missing_window),
        player_id="player-1",
        dataset_mode=DatasetMode.RECONSTRUCTED,
        maximum_label_interval=timedelta(
            minutes=config().update_cycles.maximum_label_interval_minutes
        ),
    )
    assert (ambiguous.event, ambiguous.label_confidence) == (
        PriceEvent.AMBIGUOUS,
        LabelConfidence.AMBIGUOUS,
    )
    assert (missing.event, missing.label_confidence) == (
        PriceEvent.MISSING,
        LabelConfidence.MISSING,
    )


def test_cycle_rejects_mixed_dataset_modes() -> None:
    with pytest.raises(ValueError, match="share the requested dataset mode"):
        build_price_update_cycles(
            (observation("raw", hour=0, dataset_mode=DatasetMode.RAW_OBSERVED),),
            (),
            player_id="player-1",
            dataset_mode=DatasetMode.RECONSTRUCTED,
            maximum_label_interval=timedelta(
                minutes=config().update_cycles.maximum_label_interval_minutes
            ),
        )
