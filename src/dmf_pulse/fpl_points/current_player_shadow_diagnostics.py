"""Aggregate-only shadow movement, sensitivity and unresolved model-gap diagnostics.

Movement is NOT accuracy. No data-driven choice of shrinkage world is made here.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from math import fsum
from typing import Literal

from pydantic import Field

from dmf_pulse.fpl_points.current_player_posterior import (
    ALLOWED_PROFILE_FIELDS,
    GOAL_STATUS,
    Count,
    CurrentPlayerAllocationShadow,
    CurrentPlayerPosteriorEntry,
    Rate,
    SealedModel,
    Sha256,
    StrictModel,
    seal,
)
from dmf_pulse.fpl_points.models import PlayerAllocationProfile
from dmf_pulse.ingestion.fpl.current_player_history import CurrentPlayerHistoryEvidence


class MovementQuantiles(StrictModel):
    count: Count
    median: Rate | None
    p75: Rate | None
    p90: Rate | None
    p95: Rate | None
    maximum: Rate | None


def quantile(values: tuple[float, ...], probability: float) -> float | None:
    """Deterministic linear interpolation at (n-1)*p; undefined for an empty set."""
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = int(index)
    fraction = index - lower
    return ordered[lower] + fraction * (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower])


def movement(values: tuple[float, ...]) -> MovementQuantiles:
    return MovementQuantiles(
        count=len(values),
        median=quantile(values, 0.5),
        p75=quantile(values, 0.75),
        p90=quantile(values, 0.9),
        p95=quantile(values, 0.95),
        maximum=max(values) if values else None,
    )


class FieldMovement(StrictModel):
    field: str
    absolute: MovementQuantiles
    relative: MovementQuantiles
    relative_denominator_unavailable_count: Count
    assist_threshold_counts: tuple[tuple[Rate, Count], ...] = ()


class MovementStratum(StrictModel):
    dimension: Literal["ALL", "POSITION", "ASSIGNMENT", "OBSERVED_MINUTES"]
    value: str
    player_count: Count
    fields: tuple[FieldMovement, ...]


class CurrentPlayerAllocationMovementSummary(SealedModel):
    source_shadow_sha256: Sha256
    world: str
    strata: tuple[MovementStratum, ...]
    status_counts: tuple[tuple[str, int], ...]
    zero_exposure_discipline_excluded_rows: Count
    zero_exposure_discipline_excluded_events: Count
    total_goal_rate_diagnostic: tuple[MovementStratum, ...]


class WorldComparison(StrictModel):
    left: str
    right: str
    fields: tuple[FieldMovement, ...]
    team_assist_tv: MovementQuantiles
    team_assist_tv_undefined_count: Count


class CurrentPlayerAllocationWorldSensitivity(SealedModel):
    source_shadow_sha256: Sha256
    comparisons: tuple[WorldComparison, ...]
    interpretation: Literal["MODEL_MOVEMENT_NOT_MODEL_ACCURACY"] = (
        "MODEL_MOVEMENT_NOT_MODEL_ACCURACY"
    )


class PositionEvidenceAggregate(StrictModel):
    position: str
    statistic: str
    available_rows: Count
    rows_with_observed_exposure: Count
    positive_exposure_rows: Count
    observed_exposure_minutes: Count
    observed_count_at_positive_exposure: int
    zero_exposure_count: int
    rate_per90: float | None = Field(allow_inf_nan=False)
    row_rate_variance: Rate | None
    inherited_expectation_at_observed_exposure: Rate | None
    limitation: str


class CurrentPlayerShadowModelGapSummary(SealedModel):
    source_shadow_sha256: Sha256
    source_history_sha256: Sha256
    completed_gameweek_count: Count
    gaps: tuple[str, ...]
    position_evidence: tuple[PositionEvidenceAggregate, ...]


def _field(field: str, before: tuple[float, ...], after: tuple[float, ...]) -> FieldMovement:
    deltas = tuple(abs(b - a) for a, b in zip(before, after, strict=True))
    relative = tuple(abs(b - a) / a for a, b in zip(before, after, strict=True) if a > 0)
    thresholds = (0.0025, 0.005, 0.010, 0.020, 0.050)
    return FieldMovement(
        field=field,
        absolute=movement(deltas),
        relative=movement(relative),
        relative_denominator_unavailable_count=len(before) - len(relative),
        assist_threshold_counts=tuple((v, sum(d >= v for d in deltas)) for v in thresholds)
        if field == "assist_share"
        else (),
    )


def _fields(
    before: tuple[PlayerAllocationProfile, ...], after: tuple[PlayerAllocationProfile, ...]
) -> tuple[FieldMovement, ...]:
    return tuple(
        _field(
            field,
            tuple(float(getattr(p, field)) for p in before),
            tuple(float(getattr(p, field)) for p in after),
        )
        for field in ALLOWED_PROFILE_FIELDS
    )


def _strata(
    entries: tuple[CurrentPlayerPosteriorEntry, ...],
) -> tuple[tuple[str, str, tuple[int, ...]], ...]:
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, entry in enumerate(entries):
        minutes = entry.observed_minutes
        bucket = (
            "0-89"
            if minutes < 90
            else "90-179"
            if minutes < 180
            else "180-269"
            if minutes < 270
            else "270-359"
            if minutes < 360
            else "360+"
        )
        for key in (
            ("ALL", "ALL"),
            ("POSITION", entry.binding.position.value),
            ("ASSIGNMENT", entry.binding.assignment_level),
            ("OBSERVED_MINUTES", bucket),
        ):
            groups[key].append(index)
    return tuple(
        (dimension, value, tuple(indices)) for (dimension, value), indices in sorted(groups.items())
    )


def _movements(
    shadow: CurrentPlayerAllocationShadow,
) -> tuple[CurrentPlayerAllocationMovementSummary, ...]:
    summaries = []
    for world in shadow.worlds:
        entries = world.posterior.entries
        strata = []
        goals = []
        for dimension, value, indices in _strata(entries):
            strata.append(
                MovementStratum.model_validate(
                    dict(
                        dimension=dimension,
                        value=value,
                        player_count=len(indices),
                        fields=_fields(
                            tuple(world.stale_profiles[i] for i in indices),
                            tuple(world.profiles[i] for i in indices),
                        ),
                    )
                )
            )
            goals.append(
                MovementStratum.model_validate(
                    dict(
                        dimension=dimension,
                        value=value,
                        player_count=len(indices),
                        fields=(
                            _field(
                                "TOTAL_GOAL_RATE_POSTERIOR_DIAGNOSTIC",
                                tuple(entries[i].rates[-1].historical_mean_per90 for i in indices),
                                tuple(entries[i].rates[-1].posterior_mean_per90 for i in indices),
                            ),
                        ),
                    )
                )
            )
        statuses = Counter(f"{rate.channel}:{rate.status}" for e in entries for rate in e.rates)
        summaries.append(
            seal(
                CurrentPlayerAllocationMovementSummary.model_construct(
                    source_shadow_sha256=shadow.semantic_sha256,
                    world=world.posterior.sensitivity_world,
                    strata=tuple(strata),
                    status_counts=tuple(sorted(statuses.items())),
                    zero_exposure_discipline_excluded_rows=sum(
                        r.zero_exposure_discipline_excluded_rows for e in entries for r in e.rates
                    ),
                    zero_exposure_discipline_excluded_events=sum(
                        r.zero_exposure_discipline_excluded_events for e in entries for r in e.rates
                    ),
                    total_goal_rate_diagnostic=tuple(goals),
                    semantic_sha256="0" * 64,
                )
            )
        )
    return tuple(summaries)


def _sensitivity(shadow: CurrentPlayerAllocationShadow) -> CurrentPlayerAllocationWorldSensitivity:
    variants = {"STALE": shadow.worlds[0].stale_profiles} | {
        w.posterior.sensitivity_world: w.profiles for w in shadow.worlds
    }
    team_indexes: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(shadow.worlds[0].stale_profiles):
        team_indexes[p.team_id].append(i)
    comparisons = []
    for left, right in combinations(variants, 2):
        before, after = variants[left], variants[right]
        tvs = []
        for indices in team_indexes.values():
            a = tuple(before[i].assist_share for i in indices)
            b = tuple(after[i].assist_share for i in indices)
            total_a, total_b = fsum(a), fsum(b)
            if total_a > 0 and total_b > 0:
                tvs.append(
                    0.5 * fsum(abs(x / total_a - y / total_b) for x, y in zip(a, b, strict=True))
                )
        comparisons.append(
            WorldComparison(
                left=left,
                right=right,
                fields=_fields(before, after),
                team_assist_tv=movement(tuple(tvs)),
                team_assist_tv_undefined_count=len(team_indexes) - len(tvs),
            )
        )
    return seal(
        CurrentPlayerAllocationWorldSensitivity.model_construct(
            source_shadow_sha256=shadow.semantic_sha256,
            comparisons=tuple(comparisons),
            semantic_sha256="0" * 64,
        )
    )


def _gaps(
    shadow: CurrentPlayerAllocationShadow, history: CurrentPlayerHistoryEvidence
) -> CurrentPlayerShadowModelGapSummary:
    central = shadow.worlds[0]
    evidence = {e.official_fpl_element_id: e for e in history.entries}
    entries_by_position: dict[str, list[int]] = defaultdict(list)
    for i, entry in enumerate(central.posterior.entries):
        entries_by_position[entry.binding.position.value].append(i)
    results = []
    for position, indices in sorted(entries_by_position.items()):
        for stat in (
            "combined_cbi",
            "tackles",
            "recoveries",
            "defensive_contribution",
            "bps",
            "bonus",
        ):
            rows = tuple(
                (row, central.stale_profiles[i])
                for i in indices
                for row in evidence[
                    central.posterior.entries[i].binding.source_player_id
                ].observations
                if getattr(row, stat) is not None
            )
            exposed = tuple((row, p) for row, p in rows if row.minutes is not None)
            positive = tuple(
                (row, p) for row, p in exposed if row.minutes is not None and row.minutes > 0
            )
            minutes = sum(row.minutes or 0 for row, _ in positive)
            counts = sum(int(getattr(row, stat)) for row, _ in positive)
            row_rates = tuple(
                float(getattr(row, stat)) * 90 / (row.minutes or 1) for row, _ in positive
            )
            mean = fsum(row_rates) / len(row_rates) if row_rates else 0.0
            # Only like-unit count sums; CBI is never split. No BPS inversion.
            inherited = (
                fsum(
                    (
                        p.clearances_per90 + p.blocks_per90 + p.interceptions_per90
                        if stat == "combined_cbi"
                        else p.tackles_per90
                        if stat == "tackles"
                        else p.ball_recoveries_per90
                    )
                    * (row.minutes or 0)
                    / 90
                    for row, p in positive
                )
                if stat in ("combined_cbi", "tackles", "recoveries")
                else None
            )
            results.append(
                PositionEvidenceAggregate(
                    position=position,
                    statistic=stat,
                    available_rows=len(rows),
                    rows_with_observed_exposure=len(exposed),
                    positive_exposure_rows=len(positive),
                    observed_exposure_minutes=minutes,
                    observed_count_at_positive_exposure=counts,
                    zero_exposure_count=sum(
                        int(getattr(row, stat)) for row, _ in exposed if row.minutes == 0
                    ),
                    rate_per90=counts * 90 / minutes if minutes else None,
                    row_rate_variance=fsum((v - mean) ** 2 for v in row_rates) / len(row_rates)
                    if row_rates
                    else None,
                    inherited_expectation_at_observed_exposure=inherited,
                    limitation="DESCRIPTIVE_ONLY_PROVIDER_DEFINITIONS_NOT_PROVEN_EQUIVALENT"
                    if inherited is not None
                    else "DIAGNOSTIC_ONLY_NOT_ALLOCATION_COMPONENT_EVIDENCE",
                )
            )
    gaps = [
        "GOAL_NONPENALTY_DECOMPOSITION_UNAVAILABLE",
        "CURRENT_FPL_ASSIST_HISTORICAL_ASSIST_SEMANTIC_BRIDGE",
        "CBI_COMPONENT_SPLIT_UNAVAILABLE",
        "CURRENT_TACKLE_KAPPA_NOT_GOVERNED",
        "CURRENT_RECOVERY_KAPPA_NOT_GOVERNED",
        "BPS_AUXILIARY_NOT_CURRENT_PLAYER_CALIBRATED",
        "SHRINKAGE_STRENGTH_NOT_CALIBRATED",
        "PENALTY_ROLE_SEPARATE_CURRENT_PATH",
        "NO_CURRENT_DATA_HYPERPARAMETER_FITTING",
    ]
    if history.coverage.gameweek_count == 4:
        gaps.append("CURRENT_PLAYER_HISTORY_ONLY_FOUR_COMPLETED_GWS")
    return seal(
        CurrentPlayerShadowModelGapSummary.model_construct(
            source_shadow_sha256=shadow.semantic_sha256,
            source_history_sha256=history.semantic_sha256,
            completed_gameweek_count=history.coverage.gameweek_count,
            gaps=tuple(sorted(gaps)),
            position_evidence=tuple(results),
            semantic_sha256="0" * 64,
        )
    )


def safe_shadow_summary(
    shadow: CurrentPlayerAllocationShadow, history: CurrentPlayerHistoryEvidence
) -> dict[str, object]:
    """Only aggregate metadata leaves this API. No names, IDs, profiles or player rows."""
    shadow = CurrentPlayerAllocationShadow.model_validate(shadow.model_dump(mode="python"))
    history = CurrentPlayerHistoryEvidence.model_validate(history.model_dump(mode="python"))
    central = shadow.worlds[0].posterior
    if history.semantic_sha256 != central.current_history_sha256:
        raise ValueError("diagnostic history differs from compiled shadow")
    individual = sum(e.binding.assignment_level == "INDIVIDUAL_SAME_TEAM" for e in central.entries)
    complete = sum(
        e.reconciliation_minutes == e.reconciliation_starts == "MATCH" for e in history.entries
    )
    return {
        "target_gameweek": central.target_gameweek,
        "source_gameweeks": central.source_gameweeks,
        "current_player_count": len(central.entries),
        "historical_donor_count": 599,
        "individual_prior_count": individual,
        "fallback_prior_count": len(central.entries) - individual,
        "history_rows": history.coverage.historical_row_count,
        "complete_reconciled_players": complete,
        "partial_reconciliation_players": len(central.entries) - complete,
        "reconciliation_failures": 0,
        "historical_resource_sha256": central.historical_resource_sha256,
        "current_history_evidence_sha256": history.semantic_sha256,
        "current_prior_binding_sha256": central.current_binding_sha256,
        "shadow_semantic_sha256": shadow.semantic_sha256,
        "movement": tuple(m.model_dump(mode="json") for m in _movements(shadow)),
        "world_sensitivity": _sensitivity(shadow).model_dump(mode="json"),
        "model_gaps": _gaps(shadow, history).model_dump(mode="json"),
        "goal_share_status": GOAL_STATUS,
        "model_input_status": shadow.model_input_status,
        "model_training_performed": False,
        "persistence_performed": False,
        "new_network_requests": 0,
        "interpretation": "MODEL_MOVEMENT_NOT_MODEL_ACCURACY",
        "assist_weight_interpretation": "PROPENSITY_WEIGHTS_NORMALIZED_ON_PITCH_BY_STAGE9; TEAM_TV_IS_CATALOGUE_DIAGNOSTIC_ONLY",
        "group_interpretation": "CURRENT_CATALOGUE_POSITION_AND_TEAM_NOT_HISTORICAL_MEMBERSHIP",
    }
