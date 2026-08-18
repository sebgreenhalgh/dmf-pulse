"""Cutoff-safe raw, velocity, momentum and recurrent transfer-flow features."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from itertools import pairwise

from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.configuration import PriceConfig
from dmf_pulse.prices.errors import PriceError
from dmf_pulse.prices.models import (
    ChipContaminationState,
    FeatureValue,
    FlowAnomaly,
    FlowAnomalyKind,
    LatentPressureState,
    ObservationKind,
    PriceEvent,
    PriceFeatureVector,
    PriceObservation,
    TransferFlowContext,
    TransferFlowFeatures,
)
from dmf_pulse.prices.observations import eligible_price_observations
from dmf_pulse.prices.ownership import (
    global_activity_features,
    ownership_adjusted_rates,
    ownership_regime,
)
from dmf_pulse.prices.status import status_features


@dataclass(frozen=True)
class _Interval:
    previous: PriceObservation
    current: PriceObservation
    hours: Decimal
    buys: int
    sells: int
    net_per_hour: Decimal


def _hours(previous: PriceObservation, current: PriceObservation) -> Decimal:
    seconds = Decimal(str((current.observed_at - previous.observed_at).total_seconds()))
    return seconds / Decimal(3600)


def _append_anomaly(
    anomalies: list[FlowAnomaly],
    kind: FlowAnomalyKind,
    observations: tuple[PriceObservation, ...],
    detail: str,
) -> None:
    anomalies.append(
        FlowAnomaly(
            kind=kind,
            observation_ids=tuple(item.observation_id for item in observations),
            detail=detail,
        )
    )


def _intervals(
    observations: tuple[PriceObservation, ...],
    *,
    maximum_interval_hours: Decimal,
    anomalies: list[FlowAnomaly],
) -> tuple[_Interval, ...]:
    values: list[_Interval] = []
    for previous, current in pairwise(observations):
        hours = _hours(previous, current)
        if hours == 0:
            _append_anomaly(
                anomalies,
                FlowAnomalyKind.TIMESTAMP_COLLISION,
                (previous, current),
                "different snapshots share one observed_at value",
            )
            continue
        if hours > maximum_interval_hours:
            _append_anomaly(
                anomalies,
                FlowAnomalyKind.STALE_SNAPSHOT,
                (previous, current),
                "snapshot interval exceeds the configured freshness window",
            )
        raw_buys = current.transfers_in_total - previous.transfers_in_total
        raw_sells = current.transfers_out_total - previous.transfers_out_total
        event_reset = current.gameweek != previous.gameweek and (
            current.transfers_in_event < previous.transfers_in_event
            or current.transfers_out_event < previous.transfers_out_event
        )
        if event_reset:
            _append_anomaly(
                anomalies,
                FlowAnomalyKind.GAMEWEEK_COUNTER_RESET,
                (previous, current),
                "event counters reset across a declared Gameweek boundary",
            )
        for raw, counter_name in (
            (raw_buys, "transfers_in_total"),
            (raw_sells, "transfers_out_total"),
        ):
            if raw >= 0:
                continue
            if current.observation_kind is not ObservationKind.ORDINARY:
                kind = FlowAnomalyKind.SOURCE_CORRECTION_COUNTER_DROP
                detail = f"{counter_name} decreased in a correction/supersession observation"
            else:
                kind = FlowAnomalyKind.CUMULATIVE_COUNTER_DECREASE
                detail = f"{counter_name} decreased without an authorised reset classification"
            _append_anomaly(anomalies, kind, (previous, current), detail)
        buys = max(raw_buys, 0)
        sells = max(raw_sells, 0)
        values.append(
            _Interval(
                previous=previous,
                current=current,
                hours=hours,
                buys=buys,
                sells=sells,
                net_per_hour=Decimal(buys - sells) / hours,
            )
        )
    return tuple(values)


def _ewma(intervals: tuple[_Interval, ...], half_life_hours: Decimal) -> Decimal:
    latest = intervals[-1].current.observed_at
    numerator = Decimal(0)
    denominator = Decimal(0)
    with localcontext() as context:
        context.prec = 50
        ln_two = Decimal(2).ln()
        for interval in intervals:
            age_seconds = Decimal(str((latest - interval.current.observed_at).total_seconds()))
            age_hours = age_seconds / Decimal(3600)
            weight = (-ln_two * age_hours / half_life_hours).exp()
            numerator += interval.net_per_hour * weight
            denominator += weight
    return numerator / denominator


def _consecutive_sign(intervals: tuple[_Interval, ...], *, positive: bool) -> int:
    count = 0
    for interval in reversed(intervals):
        net = interval.buys - interval.sells
        if (net > 0) is positive and net != 0:
            count += 1
        else:
            break
    return count


def build_transfer_flow_features(
    observations: tuple[PriceObservation, ...],
    *,
    player_id: str,
    cutoff: datetime,
    dataset_mode: DatasetMode,
    context: TransferFlowContext,
    config: PriceConfig,
    strict_temporal: bool = True,
) -> TransferFlowFeatures:
    """Build normalized features; future/late records are blocked by Stage 12."""

    eligible = eligible_price_observations(
        observations,
        player_id=player_id,
        cutoff=cutoff,
        dataset_mode=dataset_mode,
        strict=strict_temporal,
    )
    anomalies: list[FlowAnomaly] = []
    original = tuple(item.observation_id for item in observations if item.player_id == player_id)
    if original and original != tuple(
        item.observation_id
        for item in sorted(
            (item for item in observations if item.player_id == player_id),
            key=lambda item: (item.observed_at, item.received_at, item.observation_id),
        )
    ):
        _append_anomaly(
            anomalies,
            FlowAnomalyKind.OUT_OF_ORDER_SNAPSHOT,
            tuple(item for item in observations if item.player_id == player_id),
            "input snapshots were not supplied in chronological canonical order",
        )
    deduplicated: list[PriceObservation] = []
    seen_payload_hashes: set[str] = set()
    for item in eligible:
        if item.payload_hash in seen_payload_hashes:
            _append_anomaly(
                anomalies,
                FlowAnomalyKind.DUPLICATE_SNAPSHOT,
                (item,),
                "semantic duplicate ignored for interval construction",
            )
            continue
        seen_payload_hashes.add(item.payload_hash)
        deduplicated.append(item)
    canonical = tuple(deduplicated)
    if len(canonical) < 2:
        if canonical:
            _append_anomaly(
                anomalies,
                FlowAnomalyKind.MISSING_SNAPSHOT,
                canonical,
                "at least two cutoff-eligible snapshots are required",
            )
        raise PriceError(
            "PRICE_FEATURE_HISTORY_INSUFFICIENT",
            "at least two distinct cutoff-eligible price snapshots are required",
        )
    intervals = _intervals(
        canonical,
        maximum_interval_hours=config.transfer_features.maximum_interval_hours,
        anomalies=anomalies,
    )
    if not intervals:
        raise PriceError(
            "PRICE_FEATURE_INTERVAL_INVALID",
            "eligible observations do not form a positive-time transfer interval",
        )
    latest = intervals[-1]
    buys = latest.buys
    sells = latest.sells
    short = _ewma(intervals, config.transfer_features.short_half_life_hours)
    long = _ewma(intervals, config.transfer_features.long_half_life_hours)
    acceleration = (
        latest.net_per_hour - intervals[-2].net_per_hour if len(intervals) > 1 else Decimal(0)
    )
    positive_count = sum((interval.buys - interval.sells) > 0 for interval in intervals)
    negative_count = sum((interval.buys - interval.sells) < 0 for interval in intervals)
    last_net = buys - sells
    same_sign_count = positive_count if last_net > 0 else negative_count if last_net < 0 else 0
    owners, nonowners, buy_rate, sell_rate, denominator_uncertainty = ownership_adjusted_rates(
        ownership_percent=latest.current.ownership_percent,
        active_manager_count=context.active_manager_count,
        buys=buys,
        sells=sells,
        policy=config.transfer_features,
    )
    global_share, global_regime = global_activity_features(
        gross_increment=buys + sells,
        global_transfer_activity=context.global_transfer_activity,
        policy=config.transfer_features,
    )
    previous_status = canonical[-2] if len(canonical) > 1 else None
    status_transition, status_age, status_uncertainty = status_features(
        previous_status,
        latest.current,
        cutoff=cutoff,
        policy=config.transfer_features,
    )
    return TransferFlowFeatures(
        player_id=player_id,
        season=latest.current.season,
        gameweek=latest.current.gameweek,
        information_cutoff=cutoff,
        observation_ids=tuple(item.observation_id for item in canonical),
        transfer_in_increment=buys,
        transfer_out_increment=sells,
        net_increment=last_net,
        gross_increment=buys + sells,
        elapsed_hours=latest.hours,
        buys_per_hour=Decimal(buys) / latest.hours,
        sells_per_hour=Decimal(sells) / latest.hours,
        net_per_hour=latest.net_per_hour,
        ewma_short_net_per_hour=short,
        ewma_long_net_per_hour=long,
        short_long_momentum=short - long,
        acceleration=acceleration,
        persistence_fraction=Decimal(same_sign_count) / Decimal(len(intervals)),
        consecutive_positive_intervals=_consecutive_sign(intervals, positive=True),
        consecutive_negative_intervals=_consecutive_sign(intervals, positive=False),
        net_since_deadline=context.net_since_deadline,
        net_since_last_rise=context.net_since_last_rise,
        net_since_last_fall=context.net_since_last_fall,
        net_since_any_change=context.net_since_any_change,
        previous_event=context.previous_event,
        hours_since_last_rise=context.hours_since_last_rise,
        hours_since_last_fall=context.hours_since_last_fall,
        hours_since_any_change=context.hours_since_any_change,
        ownership_percent=latest.current.ownership_percent,
        ownership_regime=ownership_regime(
            latest.current.ownership_percent,
            policy=config.transfer_features,
        ),
        estimated_owner_pool=owners,
        estimated_nonowner_pool=nonowners,
        buy_rate_nonowners=buy_rate,
        sell_rate_owners=sell_rate,
        denominator_uncertainty=denominator_uncertainty,
        global_activity_share=global_share,
        global_activity_regime=global_regime,
        current_status=latest.current.player_status,
        status_transition=status_transition,
        status_age_hours=status_age,
        status_uncertainty=status_uncertainty,
        hours_since_deadline=context.hours_since_deadline,
        hours_to_next_deadline=context.hours_to_next_deadline,
        player_match_complete=context.player_match_complete,
        chip_contamination=context.chip_contamination,
        chip_contamination_confidence=context.chip_contamination_confidence,
        anomalies=tuple(
            sorted(
                anomalies,
                key=lambda item: (item.kind.value, item.observation_ids, item.detail),
            )
        ),
        dataset_mode=dataset_mode,
    )


def transfer_features_to_vector(
    features: TransferFlowFeatures,
    *,
    pressure: LatentPressureState,
    config: PriceConfig,
) -> PriceFeatureVector:
    """Create the versioned deterministic P1 feature vector on stable numeric scales."""

    raw_values = {
        "acceleration": features.acceleration,
        "buy_rate_nonowners": features.buy_rate_nonowners or Decimal(0),
        "buys_per_hour": features.buys_per_hour,
        "chip_contamination_unknown": Decimal(
            features.chip_contamination is ChipContaminationState.UNKNOWN
        ),
        "consecutive_negative_intervals": Decimal(features.consecutive_negative_intervals),
        "consecutive_positive_intervals": Decimal(features.consecutive_positive_intervals),
        "fall_pressure": pressure.fall_pressure,
        "global_activity_share": features.global_activity_share or Decimal(0),
        "hours_since_any_change": features.hours_since_any_change or Decimal(0),
        "hours_since_deadline": features.hours_since_deadline,
        "hours_to_next_deadline": features.hours_to_next_deadline,
        "net_per_hour": features.net_per_hour,
        "ownership_percent": features.ownership_percent,
        "previous_event_fall": Decimal(features.previous_event is PriceEvent.FALL),
        "previous_event_rise": Decimal(features.previous_event is PriceEvent.RISE),
        "rise_pressure": pressure.rise_pressure,
        "sell_rate_owners": features.sell_rate_owners or Decimal(0),
        "sells_per_hour": features.sells_per_hour,
        "status_uncertainty": features.status_uncertainty,
    }
    expected = config.competing_logit.feature_names
    if tuple(sorted(raw_values)) != expected:
        raise PriceError(
            "PRICE_FEATURE_SCHEMA_MISMATCH",
            "computed features do not match the configured P1 feature schema",
        )
    return PriceFeatureVector(
        vector_id=f"{features.player_id}:{features.information_cutoff.isoformat()}",
        player_id=features.player_id,
        information_cutoff=features.information_cutoff,
        values=tuple(
            FeatureValue(
                name=name,
                value=raw_values[name] / config.competing_logit.feature_scales[name],
            )
            for name in expected
        ),
    )
