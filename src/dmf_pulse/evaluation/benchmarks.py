"""Reproducible B0-B5 benchmark contracts and implementations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from dmf_pulse.availability import PlayerMinutesProjection
from dmf_pulse.evaluation.artifacts import seal
from dmf_pulse.evaluation.models import (
    BenchmarkDefinition,
    BenchmarkFamily,
    BenchmarkProjection,
    DatasetMode,
    FeatureRecord,
    InformationBundle,
    ObservationKind,
)

STAGE12_PARENT_COMMIT = "4f1274ccef419a7c0bde335c48bd4070e248b2e6"
B4_ACCEPTED_PARENT_MODULES = (
    "MARKETS",
    "MINUTES",
    "EVENTS",
    "FPL_POINTS",
    "ONE_GW_OPTIMISER",
    "MULTI_GW_OPTIMISER",
)


def benchmark_suite() -> tuple[BenchmarkDefinition, ...]:
    """Return the complete Stage-12 benchmark ladder with oracle labels."""

    no_outcomes = (ObservationKind.OUTCOME,)
    definitions = (
        BenchmarkDefinition(
            benchmark_id="B0A_RECENT_POINTS_LAST_3",
            family=BenchmarkFamily.B0,
            name="Naive recent points — last 3 appearances",
            feasible=True,
            oracle=False,
            required_inputs=(ObservationKind.RECENT_POINTS,),
            prohibited_inputs=no_outcomes,
            description="Arithmetic mean of the last three completed appearances before cutoff.",
        ),
        BenchmarkDefinition(
            benchmark_id="B0B_RECENT_POINTS_LAST_5",
            family=BenchmarkFamily.B0,
            name="Naive recent points — last 5 appearances",
            feasible=True,
            oracle=False,
            required_inputs=(ObservationKind.RECENT_POINTS,),
            prohibited_inputs=no_outcomes,
            description="Arithmetic mean of the last five completed appearances before cutoff.",
        ),
        BenchmarkDefinition(
            benchmark_id="B0C_RECENT_POINTS_EWMA",
            family=BenchmarkFamily.B0,
            name="Naive recent points — inner-fold-selected EWMA",
            feasible=True,
            oracle=False,
            required_inputs=(ObservationKind.RECENT_POINTS, ObservationKind.MODEL_SELECTION),
            prohibited_inputs=no_outcomes,
            description="EWMA whose alpha is selected only on earlier inner folds.",
        ),
        BenchmarkDefinition(
            benchmark_id="B1_OFFICIAL_FPL_FORM",
            family=BenchmarkFamily.B1,
            name="Official historical FPL form",
            feasible=True,
            oracle=False,
            required_inputs=(ObservationKind.OFFICIAL_FPL_FORM,),
            prohibited_inputs=no_outcomes,
            description="Consumes the official form value captured at the historical cutoff.",
        ),
        BenchmarkDefinition(
            benchmark_id="B2_MARKET_ONLY",
            family=BenchmarkFamily.B2,
            name="Market-only generic allocation",
            feasible=True,
            oracle=False,
            required_inputs=(ObservationKind.MARKET,),
            prohibited_inputs=(ObservationKind.MINUTES_DISTRIBUTION, ObservationKind.OUTCOME),
            description="Accepted market evidence with generic allocation and no bespoke minutes model.",
        ),
        BenchmarkDefinition(
            benchmark_id="B3_MARKET_PLUS_MINUTES",
            family=BenchmarkFamily.B3,
            name="Market plus accepted minutes",
            feasible=True,
            oracle=False,
            required_inputs=(ObservationKind.MARKET, ObservationKind.MINUTES_DISTRIBUTION),
            prohibited_inputs=no_outcomes,
            description="Market evidence plus the accepted Stage-7 minutes/start contract.",
        ),
        BenchmarkDefinition(
            benchmark_id="B4_ACCEPTED_PULSE_BASELINE",
            family=BenchmarkFamily.B4,
            name="Complete accepted Pulse baseline",
            feasible=True,
            oracle=False,
            required_inputs=(ObservationKind.PULSE_PROJECTION,),
            prohibited_inputs=no_outcomes,
            description="Only modules accepted at the Stage-12 parent are composed.",
        ),
        BenchmarkDefinition(
            benchmark_id="B5A_PERFECT_LINEUP_MINUTES",
            family=BenchmarkFamily.B5,
            name="Perfect lineup/minutes upper bound",
            feasible=False,
            oracle=True,
            required_inputs=(ObservationKind.OUTCOME,),
            prohibited_inputs=(),
            description="Counterfactual oracle with actual lineup/minutes.",
        ),
        BenchmarkDefinition(
            benchmark_id="B5B_PERFECT_FOOTBALL_OUTCOMES",
            family=BenchmarkFamily.B5,
            name="Perfect football-outcome upper bound",
            feasible=False,
            oracle=True,
            required_inputs=(ObservationKind.OUTCOME,),
            prohibited_inputs=(),
            description="Counterfactual oracle with realised football outcomes.",
        ),
        BenchmarkDefinition(
            benchmark_id="B5C_PERFECT_GAMEWEEK_TRANSFERS",
            family=BenchmarkFamily.B5,
            name="Perfect Gameweek-transfer upper bound",
            feasible=False,
            oracle=True,
            required_inputs=(ObservationKind.OUTCOME,),
            prohibited_inputs=(),
            description="Counterfactual single-Gameweek transfer oracle.",
        ),
        BenchmarkDefinition(
            benchmark_id="B5D_PERFECT_SEASON_POLICY",
            family=BenchmarkFamily.B5,
            name="Perfect-season-policy upper bound",
            feasible=False,
            oracle=True,
            required_inputs=(ObservationKind.OUTCOME,),
            prohibited_inputs=(),
            description="Unattainable full-season hindsight policy.",
        ),
    )
    return definitions


def _records(
    bundle: InformationBundle,
    *,
    target_id: str,
    kind: ObservationKind,
) -> tuple[FeatureRecord, ...]:
    return tuple(
        record for record in bundle.records if record.target_id == target_id and record.kind is kind
    )


def _decimal_value(record: FeatureRecord, field: str) -> Decimal:
    value = record.values.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise ValueError(f"record {record.record_id} requires numeric field {field}")
    converted = Decimal(value)
    if not converted.is_finite():
        raise ValueError(f"record {record.record_id} requires finite numeric field {field}")
    return converted


def accepted_pulse_point_forecast(record: FeatureRecord) -> Decimal:
    """Validate the immutable B4 composition and return its point projection."""

    if record.kind is not ObservationKind.PULSE_PROJECTION:
        raise ValueError("B4 requires a Pulse projection record")
    accepted_modules = record.values.get("accepted_modules")
    if not isinstance(accepted_modules, list) or any(
        not isinstance(item, str) for item in accepted_modules
    ):
        raise ValueError("B4 must declare the accepted module composition")
    if len(accepted_modules) != len(set(accepted_modules)):
        raise ValueError("B4 accepted parent modules must be unique")
    if set(accepted_modules) != set(B4_ACCEPTED_PARENT_MODULES):
        raise ValueError("B4 must contain the complete accepted Stage-12 parent module set")
    if record.values.get("accepted_parent_commit") != STAGE12_PARENT_COMMIT:
        raise ValueError("B4 must bind its composition to the exact Stage-12 parent")
    return _decimal_value(record, "expected_points")


def _recent_points(
    records: tuple[FeatureRecord, ...],
    *,
    count: int,
) -> tuple[FeatureRecord, ...]:
    if any(item.target_outcome_at is None for item in records):
        raise ValueError("B0 history requires an explicit appearance completion time")
    ordered = tuple(
        sorted(
            records,
            key=lambda item: (item.target_outcome_at, item.record_id),
        )
    )
    if len(ordered) < count:
        raise ValueError(f"benchmark requires at least {count} completed appearances")
    return ordered[-count:]


def project_benchmark(
    definition: BenchmarkDefinition,
    *,
    bundle: InformationBundle,
    target_id: str,
    forecast_origin: datetime,
    oracle_value: Decimal | None = None,
) -> BenchmarkProjection:
    """Execute one distinct benchmark from the frozen information bundle."""

    canonical = {item.benchmark_id: item for item in benchmark_suite()}
    if canonical.get(definition.benchmark_id) != definition:
        raise ValueError("benchmark definition must exactly match the canonical Stage-12 suite")
    if forecast_origin != bundle.forecast_origin:
        raise ValueError("benchmark forecast origin must match its frozen information bundle")
    evidence: tuple[FeatureRecord, ...]
    forecast: Decimal
    if definition.family is BenchmarkFamily.B5:
        if not definition.oracle or definition.feasible:
            raise ValueError("B5 must remain an explicitly infeasible oracle")
        if oracle_value is None:
            raise ValueError("B5 oracle requires an explicitly supplied counterfactual value")
        if bundle.dataset_mode is not DatasetMode.COUNTERFACTUAL:
            raise ValueError("B5 oracle projections must use COUNTERFACTUAL dataset mode")
        evidence = ()
        forecast = oracle_value
    elif definition.benchmark_id == "B0A_RECENT_POINTS_LAST_3":
        evidence = _recent_points(
            _records(bundle, target_id=target_id, kind=ObservationKind.RECENT_POINTS),
            count=3,
        )
        forecast = sum((_decimal_value(item, "points") for item in evidence), Decimal(0)) / Decimal(
            3
        )
    elif definition.benchmark_id == "B0B_RECENT_POINTS_LAST_5":
        evidence = _recent_points(
            _records(bundle, target_id=target_id, kind=ObservationKind.RECENT_POINTS),
            count=5,
        )
        forecast = sum((_decimal_value(item, "points") for item in evidence), Decimal(0)) / Decimal(
            5
        )
    elif definition.benchmark_id == "B0C_RECENT_POINTS_EWMA":
        history = _records(bundle, target_id=target_id, kind=ObservationKind.RECENT_POINTS)
        selection = _records(bundle, target_id=target_id, kind=ObservationKind.MODEL_SELECTION)
        if (
            len(selection) != 1
            or selection[0].values.get("selected_on") != "INNER_FOLDS"
            or bool(selection[0].values.get("uses_outer_fold_outcome", False))
        ):
            raise ValueError("EWMA alpha requires one uncontaminated inner-fold selection record")
        alpha = _decimal_value(selection[0], "ewma_alpha")
        if not Decimal(0) < alpha <= Decimal(1):
            raise ValueError("EWMA alpha must lie in (0, 1]")
        evidence = tuple(sorted((*history, selection[0]), key=lambda item: item.record_id))
        if any(item.target_outcome_at is None for item in history):
            raise ValueError("B0 history requires an explicit appearance completion time")
        ordered = tuple(sorted(history, key=lambda item: (item.target_outcome_at, item.record_id)))
        if not ordered:
            raise ValueError("EWMA benchmark requires completed appearance history")
        forecast = _decimal_value(ordered[0], "points")
        for item in ordered[1:]:
            forecast = alpha * _decimal_value(item, "points") + (Decimal(1) - alpha) * forecast
    elif definition.family is BenchmarkFamily.B1:
        evidence = _records(bundle, target_id=target_id, kind=ObservationKind.OFFICIAL_FPL_FORM)
        if len(evidence) != 1:
            raise ValueError("B1 requires exactly one historical captured FPL form value")
        if evidence[0].values.get("captured_at_historical_cutoff") is not True:
            raise ValueError("B1 requires form captured at the historical cutoff")
        forecast = _decimal_value(evidence[0], "form")
    elif definition.family is BenchmarkFamily.B2:
        evidence = _records(bundle, target_id=target_id, kind=ObservationKind.MARKET)
        if len(evidence) != 1:
            raise ValueError("B2 requires exactly one accepted market-only projection record")
        allocation_method = evidence[0].values.get("allocation_method")
        allowed_methods = {
            "GENERIC_POSITION_PRIOR",
            "GENERIC_PRICE_PRIOR",
            "GENERIC_MARKET_LISTING_PRIOR",
            "GENERIC_COMPOSITE_PRIOR",
        }
        if allocation_method not in allowed_methods:
            raise ValueError("B2 requires a declared generic authorised allocation method")
        if bool(evidence[0].values.get("uses_bespoke_minutes_model", False)):
            raise ValueError("B2 cannot invoke the bespoke Pulse minutes model")
        forecast = _decimal_value(evidence[0], "market_only_xp")
    elif definition.family is BenchmarkFamily.B3:
        market = _records(bundle, target_id=target_id, kind=ObservationKind.MARKET)
        minutes = _records(bundle, target_id=target_id, kind=ObservationKind.MINUTES_DISTRIBUTION)
        if len(market) != 1 or len(minutes) != 1:
            raise ValueError("B3 requires one market record and one Stage-7 minutes record")
        generic_full_match_xp = _decimal_value(market[0], "full_match_xp")
        projection_payload = minutes[0].values.get("player_minutes_projection")
        try:
            projection = PlayerMinutesProjection.model_validate(projection_payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "B3 requires an immutable accepted Stage-7 player minutes projection"
            ) from exc
        if projection.player_id != minutes[0].entity_id:
            raise ValueError("B3 Stage-7 projection player_id must match the evidence entity")
        expected_minutes = Decimal(projection.expected_minutes)
        forecast = generic_full_match_xp * expected_minutes / Decimal(90)
        evidence = tuple(sorted((*market, *minutes), key=lambda item: item.record_id))
    elif definition.family is BenchmarkFamily.B4:
        evidence = _records(bundle, target_id=target_id, kind=ObservationKind.PULSE_PROJECTION)
        if len(evidence) != 1:
            raise ValueError("B4 requires exactly one frozen accepted Pulse projection")
        forecast = accepted_pulse_point_forecast(evidence[0])
    else:
        raise ValueError(f"unsupported benchmark definition: {definition.benchmark_id}")
    value = BenchmarkProjection(
        benchmark=definition,
        dataset_mode=bundle.dataset_mode,
        target_id=target_id,
        point_forecast=forecast,
        evidence_record_ids=tuple(sorted(item.record_id for item in evidence)),
        forecast_origin=forecast_origin,
        information_cutoff=bundle.information_cutoff,
        information_bundle_sha256=bundle.bundle_sha256,
        projection_sha256="0" * 64,
    )
    return seal(value, "projection_sha256")
