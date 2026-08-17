from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.availability.projection import compose_player_minutes_projection
from dmf_pulse.evaluation.benchmarks import benchmark_suite, project_benchmark
from dmf_pulse.evaluation.information_sets import build_information_set
from dmf_pulse.evaluation.models import (
    BenchmarkFamily,
    DatasetMode,
    ObservationKind,
    OperationalUsability,
)
from dmf_pulse.evaluation.service import EvaluationService, load_json
from tests.evaluation_helpers import BASE, feature

pytestmark = pytest.mark.unit


def test_full_benchmark_fixture_produces_distinct_b0_to_b5() -> None:
    projections = EvaluationService().benchmark(
        load_json(Path("fixtures/historical/benchmark_player_histories/benchmark_input.json"))
    )
    values = {item.benchmark.benchmark_id: item.point_forecast for item in projections}
    assert values["B0A_RECENT_POINTS_LAST_3"] == Decimal(8)
    assert values["B0B_RECENT_POINTS_LAST_5"] == Decimal(6)
    assert values["B0C_RECENT_POINTS_EWMA"] == Decimal("7.8750")
    assert values["B1_OFFICIAL_FPL_FORM"] == Decimal("6.2")
    assert values["B2_MARKET_ONLY"] == Decimal("5.5")
    assert values["B3_MARKET_PLUS_MINUTES"] == Decimal("5.6")
    assert values["B4_ACCEPTED_PULSE_BASELINE"] == Decimal("6.1")
    assert values["B5D_PERFECT_SEASON_POLICY"] == Decimal(15)


def test_suite_keeps_every_b5_oracle_infeasible() -> None:
    suite = benchmark_suite()
    assert {item.family for item in suite} == set(BenchmarkFamily)
    b5 = tuple(item for item in suite if item.family is BenchmarkFamily.B5)
    assert len(b5) == 4
    assert all(item.oracle and not item.feasible for item in b5)


def test_b0_rejects_insufficient_or_future_history() -> None:
    records = tuple(
        feature(
            f"history-{index}",
            kind=ObservationKind.RECENT_POINTS,
            mode=DatasetMode.COUNTERFACTUAL,
            values={"points": str(index)},
            origin=BASE - timedelta(days=index),
            target_outcome_at=BASE - timedelta(days=index + 1),
        )
        for index in range(2)
    )
    bundle = build_information_set(
        records,
        bundle_id="b",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    definition = next(item for item in benchmark_suite() if item.benchmark_id.startswith("B0A"))
    with pytest.raises(ValueError, match="at least 3"):
        project_benchmark(definition, bundle=bundle, target_id="target", forecast_origin=BASE)

    missing_completion_time = tuple(
        feature(
            f"undated-{index}",
            kind=ObservationKind.RECENT_POINTS,
            mode=DatasetMode.COUNTERFACTUAL,
            usability=OperationalUsability.COUNTERFACTUAL_ONLY,
            values={"points": str(index)},
            origin=BASE - timedelta(days=index),
        )
        for index in range(3)
    )
    bundle = build_information_set(
        missing_completion_time,
        bundle_id="undated",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    with pytest.raises(ValueError, match="completion time"):
        project_benchmark(definition, bundle=bundle, target_id="target", forecast_origin=BASE)


def test_b4_blocks_future_stage_module_smuggling() -> None:
    pulse = feature(
        "pulse",
        kind=ObservationKind.PULSE_PROJECTION,
        mode=DatasetMode.COUNTERFACTUAL,
        values={"expected_points": "5", "accepted_modules": ["PRICE_PREDICTION"]},
    )
    bundle = build_information_set(
        (pulse,),
        bundle_id="b",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    definition = next(item for item in benchmark_suite() if item.family is BenchmarkFamily.B4)
    with pytest.raises(ValueError, match="complete accepted"):
        project_benchmark(definition, bundle=bundle, target_id="target", forecast_origin=BASE)


def test_b5_requires_explicit_counterfactual_value() -> None:
    bundle = build_information_set(
        (feature(mode=DatasetMode.COUNTERFACTUAL),),
        bundle_id="b",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    definition = next(item for item in benchmark_suite() if item.family is BenchmarkFamily.B5)
    with pytest.raises(ValueError, match="requires"):
        project_benchmark(definition, bundle=bundle, target_id="target", forecast_origin=BASE)

    live_bundle = build_information_set(
        (feature(),),
        bundle_id="live",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.LIVE_OBSERVED,
    )
    with pytest.raises(ValueError, match="COUNTERFACTUAL"):
        project_benchmark(
            definition,
            bundle=live_bundle,
            target_id="target",
            forecast_origin=BASE,
            oracle_value=Decimal(10),
        )


def test_b2_requires_declared_generic_allocation_and_no_bespoke_minutes() -> None:
    definition = next(item for item in benchmark_suite() if item.family is BenchmarkFamily.B2)
    missing_method = feature(
        "market",
        kind=ObservationKind.MARKET,
        mode=DatasetMode.COUNTERFACTUAL,
        values={"market_only_xp": "5"},
    )
    bundle = build_information_set(
        (missing_method,),
        bundle_id="b",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    with pytest.raises(ValueError, match="generic authorised"):
        project_benchmark(definition, bundle=bundle, target_id="target", forecast_origin=BASE)

    contaminated = missing_method.model_copy(
        update={
            "values": {
                "market_only_xp": "5",
                "allocation_method": "GENERIC_POSITION_PRIOR",
                "uses_bespoke_minutes_model": True,
            }
        }
    )
    bundle = build_information_set(
        (contaminated,),
        bundle_id="b2",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    with pytest.raises(ValueError, match="cannot invoke"):
        project_benchmark(definition, bundle=bundle, target_id="target", forecast_origin=BASE)


def test_benchmark_origin_and_selection_are_fail_closed() -> None:
    payload = load_json(Path("fixtures/historical/benchmark_player_histories/benchmark_input.json"))
    payload["benchmark_ids"] = ["NOT_A_BENCHMARK"]
    with pytest.raises(ValueError, match="unknown benchmark"):
        EvaluationService().benchmark(payload)

    payload["benchmark_ids"] = ["B0A_RECENT_POINTS_LAST_3"] * 2
    with pytest.raises(ValueError, match="unique"):
        EvaluationService().benchmark(payload)

    payload = load_json(Path("fixtures/historical/benchmark_player_histories/benchmark_input.json"))
    payload["benchmark_ids"] = ["B0A_RECENT_POINTS_LAST_3"]
    payload["oracle_values"] = {"B5D_PERFECT_SEASON_POLICY": "15"}
    with pytest.raises(ValueError, match="selected canonical B5"):
        EvaluationService().benchmark(payload)

    payload = load_json(Path("fixtures/historical/benchmark_player_histories/benchmark_input.json"))
    records = payload["records"]
    assert isinstance(records, list)
    selection = next(item for item in records if item["kind"] == "MODEL_SELECTION")
    selection["values"]["selected_on"] = "OUTER_FOLD"
    payload["benchmark_ids"] = ["B0C_RECENT_POINTS_EWMA"]
    payload["oracle_values"] = {}
    with pytest.raises(ValueError, match="inner-fold"):
        EvaluationService().benchmark(payload)

    bundle = build_information_set(
        (
            feature(
                mode=DatasetMode.COUNTERFACTUAL, usability=OperationalUsability.COUNTERFACTUAL_ONLY
            ),
        ),
        bundle_id="origin",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    definition = next(item for item in benchmark_suite() if item.family is BenchmarkFamily.B5)
    with pytest.raises(ValueError, match="forecast origin"):
        project_benchmark(
            definition,
            bundle=bundle,
            target_id="target",
            forecast_origin=BASE + timedelta(minutes=1),
            oracle_value=Decimal(1),
        )

    altered = next(item for item in benchmark_suite() if item.family is BenchmarkFamily.B0)
    with pytest.raises(ValueError, match="exactly match"):
        project_benchmark(
            altered.model_copy(update={"description": "rewritten"}),
            bundle=bundle,
            target_id="target",
            forecast_origin=BASE,
        )


def test_b1_b3_and_b4_require_authoritative_boundary_markers() -> None:
    b1 = next(item for item in benchmark_suite() if item.family is BenchmarkFamily.B1)
    uncaptured = feature(
        "form",
        kind=ObservationKind.OFFICIAL_FPL_FORM,
        mode=DatasetMode.COUNTERFACTUAL,
        usability=OperationalUsability.COUNTERFACTUAL_ONLY,
        values={"form": "5", "captured_at_historical_cutoff": False},
    )
    bundle = build_information_set(
        (uncaptured,),
        bundle_id="form",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    with pytest.raises(ValueError, match="captured"):
        project_benchmark(b1, bundle=bundle, target_id="target", forecast_origin=BASE)

    b3 = next(item for item in benchmark_suite() if item.family is BenchmarkFamily.B3)
    market = feature(
        "market",
        kind=ObservationKind.MARKET,
        mode=DatasetMode.COUNTERFACTUAL,
        usability=OperationalUsability.COUNTERFACTUAL_ONLY,
        values={"full_match_xp": "5"},
    )
    role = {
        "player_id": "00000000-0000-0000-0000-000000000001",
        "position": "MID",
        "p_start": Decimal(1),
        "p_bench": Decimal(0),
        "p_out": Decimal(0),
    }
    pmf = tuple(Decimal(1) if index == 90 else Decimal(0) for index in range(91))
    projection = compose_player_minutes_projection(
        role,
        {"minute_pmf": pmf},
        {"minute_pmf": pmf},
        confidence_grade="B",
        confidence_reasons=("BASELINE_MODEL_CAP_B",),
    )
    minutes = feature(
        "minutes",
        kind=ObservationKind.MINUTES_DISTRIBUTION,
        mode=DatasetMode.COUNTERFACTUAL,
        usability=OperationalUsability.COUNTERFACTUAL_ONLY,
        values={
            "player_minutes_projection": projection.model_dump(mode="json")
            | {"expected_minutes": "91.000000"}
        },
    )
    bundle = build_information_set(
        (market, minutes),
        bundle_id="minutes",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    with pytest.raises(ValueError, match="accepted Stage-7"):
        project_benchmark(b3, bundle=bundle, target_id="target", forecast_origin=BASE)

    valid_minutes = minutes.model_copy(
        update={
            "entity_id": projection.player_id,
            "values": {"player_minutes_projection": projection.model_dump(mode="json")},
        }
    )
    mismatched = valid_minutes.model_copy(update={"entity_id": "another-player"})
    bundle = build_information_set(
        (market, mismatched),
        bundle_id="minutes-player-mismatch",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    with pytest.raises(ValueError, match="player_id"):
        project_benchmark(b3, bundle=bundle, target_id="target", forecast_origin=BASE)

    b4 = next(item for item in benchmark_suite() if item.family is BenchmarkFamily.B4)
    pulse = feature(
        "pulse-unknown",
        kind=ObservationKind.PULSE_PROJECTION,
        mode=DatasetMode.COUNTERFACTUAL,
        usability=OperationalUsability.COUNTERFACTUAL_ONLY,
        values={
            "expected_points": "5",
            "accepted_modules": ["MARKETS", "PRICE_MODEL_V2"],
            "accepted_parent_commit": "4f1274ccef419a7c0bde335c48bd4070e248b2e6",
        },
    )
    bundle = build_information_set(
        (pulse,),
        bundle_id="b4",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    with pytest.raises(ValueError, match="complete accepted"):
        project_benchmark(b4, bundle=bundle, target_id="target", forecast_origin=BASE)
