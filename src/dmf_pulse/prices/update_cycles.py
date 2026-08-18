"""Interval-censored price update-cycle construction."""

from __future__ import annotations

from datetime import timedelta

from dmf_pulse.evaluation.artifacts import verify_sealed
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.models import (
    LabelConfidence,
    ObservationKind,
    PriceEvent,
    PriceObservation,
    PriceUpdateCycle,
    PriceUpdateWindow,
)


def _event_from_prices(prior: int, resulting: int) -> PriceEvent:
    difference = resulting - prior
    if difference == 1:
        return PriceEvent.RISE
    if difference == -1:
        return PriceEvent.FALL
    if difference == 0:
        return PriceEvent.NO_CHANGE
    return PriceEvent.AMBIGUOUS


def build_price_update_cycles(
    observations: tuple[PriceObservation, ...],
    windows: tuple[PriceUpdateWindow, ...],
    *,
    player_id: str,
    dataset_mode: DatasetMode,
    maximum_label_interval: timedelta,
) -> tuple[PriceUpdateCycle, ...]:
    """Build one immutable label per declared update opportunity without inventing time."""

    relevant = tuple(item for item in observations if item.player_id == player_id)
    for item in relevant:
        verify_sealed(item, "semantic_hash")
        if item.dataset_mode is not dataset_mode:
            raise ValueError("price-cycle observations must share the requested dataset mode")
    ordered = tuple(sorted(relevant, key=lambda item: (item.observed_at, item.observation_id)))
    values: list[PriceUpdateCycle] = []
    for window in sorted(windows, key=lambda item: (item.cycle_start, item.cycle_id)):
        before = tuple(
            item
            for item in ordered
            if item.observed_at <= window.cycle_start
            and item.usable_at <= window.information_cutoff
        )
        after = tuple(
            item for item in ordered if window.cycle_start < item.observed_at <= window.cycle_end
        )
        pre = before[-1] if before else None
        post = after[0] if after else None
        if pre is None or post is None:
            exemplar = pre if pre is not None else post
            values.append(
                PriceUpdateCycle(
                    cycle_id=window.cycle_id,
                    player_id=player_id,
                    season=exemplar.season if exemplar is not None else "UNKNOWN",
                    gameweek=exemplar.gameweek if exemplar is not None else 1,
                    cycle_start=window.cycle_start,
                    cycle_end=window.cycle_end,
                    information_cutoff=window.information_cutoff,
                    pre_update_observation_id=pre.observation_id if pre else None,
                    post_update_observation_id=post.observation_id if post else None,
                    prior_price_units=pre.current_price_units if pre else None,
                    resulting_price_units=post.current_price_units if post else None,
                    event=PriceEvent.MISSING,
                    event_effective_at=None,
                    event_effective_interval_start=None,
                    event_effective_interval_end=None,
                    event_first_observed_at=None,
                    label_confidence=LabelConfidence.MISSING,
                    correction_lineage=(),
                    dataset_mode=dataset_mode,
                )
            )
            continue
        event = _event_from_prices(pre.current_price_units, post.current_price_units)
        interval = post.observed_at - pre.observed_at
        ambiguous = event is PriceEvent.AMBIGUOUS or interval > maximum_label_interval
        if ambiguous:
            event = PriceEvent.AMBIGUOUS
            confidence = LabelConfidence.AMBIGUOUS
        elif window.event_effective_at is not None and event is not PriceEvent.NO_CHANGE:
            confidence = LabelConfidence.EXACT
        else:
            confidence = LabelConfidence.INTERVAL_CENSORED
        changed = event in {PriceEvent.RISE, PriceEvent.FALL, PriceEvent.AMBIGUOUS}
        corrections = tuple(
            sorted(
                {
                    item.supersedes_observation_id
                    for item in (pre, post)
                    if item.observation_kind is not ObservationKind.ORDINARY
                    and item.supersedes_observation_id is not None
                }
            )
        )
        values.append(
            PriceUpdateCycle(
                cycle_id=window.cycle_id,
                player_id=player_id,
                season=pre.season,
                gameweek=pre.gameweek,
                cycle_start=window.cycle_start,
                cycle_end=window.cycle_end,
                information_cutoff=window.information_cutoff,
                pre_update_observation_id=pre.observation_id,
                post_update_observation_id=post.observation_id,
                prior_price_units=pre.current_price_units,
                resulting_price_units=post.current_price_units,
                event=event,
                event_effective_at=(
                    window.event_effective_at if confidence is LabelConfidence.EXACT else None
                ),
                event_effective_interval_start=pre.observed_at if changed else None,
                event_effective_interval_end=post.observed_at if changed else None,
                event_first_observed_at=post.observed_at if changed else None,
                label_confidence=confidence,
                correction_lineage=corrections,
                dataset_mode=dataset_mode,
            )
        )
    return tuple(values)
