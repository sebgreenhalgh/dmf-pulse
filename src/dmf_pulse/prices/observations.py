"""Cutoff-safe price and external-predictor observations."""

from __future__ import annotations

from datetime import datetime

from dmf_pulse.evaluation.artifacts import verify_sealed
from dmf_pulse.evaluation.errors import LeakageError
from dmf_pulse.evaluation.information_sets import build_information_set
from dmf_pulse.evaluation.models import (
    DatasetMode,
    FeatureRecord,
    ObservationKind,
    ObservationRole,
    OperationalUsability,
)
from dmf_pulse.prices.models import (
    ExternalPredictorObservation,
    PriceObservation,
    require_utc,
)


def _operational_usability(mode: DatasetMode) -> OperationalUsability:
    if mode is DatasetMode.LIVE_OBSERVED:
        return OperationalUsability.LIVE_OPERATIONAL
    if mode is DatasetMode.RAW_OBSERVED:
        return OperationalUsability.RECEIVED_NOT_OPERATIONAL
    if mode is DatasetMode.RECONSTRUCTED:
        return OperationalUsability.RECONSTRUCTED_ONLY
    return OperationalUsability.COUNTERFACTUAL_ONLY


def to_stage12_feature_record(value: PriceObservation) -> FeatureRecord:
    """Adapt Stage-13 observations to the accepted Stage-12 information boundary."""

    return FeatureRecord(
        record_id=value.observation_id,
        entity_id=value.player_id,
        target_id=f"price:{value.player_id}:{value.gameweek}",
        gameweek=value.gameweek,
        dataset_mode=value.dataset_mode,
        operational_usability=_operational_usability(value.dataset_mode),
        role=ObservationRole.FEATURE,
        kind=ObservationKind.PRICE,
        source_timestamp=value.observed_at,
        received_at=value.received_at,
        usable_at=value.usable_at,
        corrected_at=(value.received_at if value.supersedes_observation_id is not None else None),
        current_vintage=False,
        feature_intended=True,
        values={
            "current_price_units": value.current_price_units,
            "ownership_percent": value.ownership_percent,
            "transfers_in_total": value.transfers_in_total,
            "transfers_out_total": value.transfers_out_total,
            "transfers_in_event": value.transfers_in_event,
            "transfers_out_event": value.transfers_out_event,
            "player_status": value.player_status.value,
            "semantic_hash": value.semantic_hash,
        },
        source_snapshot_id=value.source_snapshot_id,
    )


def external_to_stage12_feature_record(
    value: ExternalPredictorObservation,
    *,
    gameweek: int,
) -> FeatureRecord:
    return FeatureRecord(
        record_id=value.observation_id,
        entity_id=value.player_id,
        target_id=f"external-price-predictor:{value.player_id}:{gameweek}",
        gameweek=gameweek,
        dataset_mode=value.dataset_mode,
        operational_usability=_operational_usability(value.dataset_mode),
        role=ObservationRole.FEATURE,
        kind=ObservationKind.OTHER,
        source_timestamp=value.observed_at,
        received_at=value.received_at,
        usable_at=value.usable_at,
        current_vintage=False,
        feature_intended=True,
        values={
            "provider": value.provider.value,
            "direction": value.direction.value,
            "displayed_progress": value.displayed_progress,
            "predicted_progress": value.predicted_progress,
            "displayed_categorical_signal": value.displayed_categorical_signal,
            "semantic_hash": value.semantic_hash,
        },
        source_snapshot_id=value.source_snapshot_id,
    )


def eligible_price_observations(
    observations: tuple[PriceObservation, ...],
    *,
    player_id: str,
    cutoff: datetime,
    dataset_mode: DatasetMode,
    strict: bool = True,
) -> tuple[PriceObservation, ...]:
    """Return only observations admitted by Stage 12's `usable_at` information set."""

    cutoff = require_utc(cutoff, field_name="information_cutoff")
    relevant = tuple(item for item in observations if item.player_id == player_id)
    for item in relevant:
        verify_sealed(item, "semantic_hash")
    blocked = tuple(
        item.observation_id
        for item in relevant
        if item.observed_at > cutoff or item.received_at > cutoff or item.usable_at > cutoff
    )
    if blocked and strict:
        raise LeakageError(
            "HISTORICAL_INFORMATION_LEAKAGE_BLOCKED",
            "price observations cross observed/received/usable cutoff: "
            + ", ".join(sorted(blocked)),
        )
    relevant = tuple(
        item
        for item in relevant
        if item.observed_at <= cutoff and item.received_at <= cutoff and item.usable_at <= cutoff
    )
    bundle = build_information_set(
        tuple(to_stage12_feature_record(item) for item in relevant),
        bundle_id=f"price:{player_id}:{cutoff.isoformat()}",
        forecast_origin=cutoff,
        information_cutoff=cutoff,
        dataset_mode=dataset_mode,
        block_on_leakage=strict,
    )
    allowed = {item.record_id for item in bundle.records}
    return tuple(
        sorted(
            (item for item in relevant if item.observation_id in allowed),
            key=lambda item: (item.observed_at, item.received_at, item.observation_id),
        )
    )


def eligible_external_predictor_observations(
    observations: tuple[ExternalPredictorObservation, ...],
    *,
    player_id: str,
    gameweek: int,
    cutoff: datetime,
    dataset_mode: DatasetMode,
    strict: bool = True,
) -> tuple[ExternalPredictorObservation, ...]:
    cutoff = require_utc(cutoff, field_name="information_cutoff")
    relevant = tuple(item for item in observations if item.player_id == player_id)
    for item in relevant:
        verify_sealed(item, "semantic_hash")
    blocked = tuple(
        item.observation_id
        for item in relevant
        if item.observed_at > cutoff or item.received_at > cutoff or item.usable_at > cutoff
    )
    if blocked and strict:
        raise LeakageError(
            "HISTORICAL_INFORMATION_LEAKAGE_BLOCKED",
            "external predictor observations cross observed/received/usable cutoff: "
            + ", ".join(sorted(blocked)),
        )
    relevant = tuple(
        item
        for item in relevant
        if item.observed_at <= cutoff and item.received_at <= cutoff and item.usable_at <= cutoff
    )
    bundle = build_information_set(
        tuple(external_to_stage12_feature_record(item, gameweek=gameweek) for item in relevant),
        bundle_id=f"external-price:{player_id}:{cutoff.isoformat()}",
        forecast_origin=cutoff,
        information_cutoff=cutoff,
        dataset_mode=dataset_mode,
        block_on_leakage=strict,
    )
    allowed = {item.record_id for item in bundle.records}
    return tuple(
        sorted(
            (item for item in relevant if item.observation_id in allowed),
            key=lambda item: (item.observed_at, item.received_at, item.observation_id),
        )
    )
