from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from dmf_pulse.evaluation.errors import LeakageError
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.calibration import fit_price_calibration
from dmf_pulse.prices.early_transfer import evaluate_act_now_vs_wait
from dmf_pulse.prices.models import (
    ActivationStatus,
    EarlyTransferAction,
    FlowAnomalyKind,
    ObservationKind,
    PriceEvaluationRow,
    PriceEvent,
    PriceMass,
    PricePmf,
    PriceProbabilityVector,
    PriceStatus,
)
from dmf_pulse.prices.observations import eligible_price_observations
from dmf_pulse.prices.selling_value import build_optimiser_price_scenarios
from dmf_pulse.prices.service import PriceService
from dmf_pulse.prices.transfer_flows import build_transfer_flow_features
from tests.prices_helpers import (
    BASE,
    alternative,
    config,
    flow_context,
    observation,
    projection,
)


def _fixture(repository_root):
    return json.loads(
        (repository_root / "fixtures/prices/adversarial_cases.json").read_text(encoding="utf-8")
    )


def _features(observations, **context):
    return build_transfer_flow_features(
        observations,
        player_id="player-1",
        cutoff=BASE + timedelta(hours=12),
        dataset_mode=DatasetMode.RECONSTRUCTED,
        context=flow_context(**context),
        config=config(),
    )


def test_physical_fixture_manifest_covers_all_required_adversarial_and_ordinary_cases(
    repository_root,
) -> None:
    fixture = _fixture(repository_root)
    ids = tuple(item["id"] for item in fixture["cases"])
    required = {
        "post_midnight_snapshot_leak",
        "future_price_event_canary",
        "late_received_transfer_snapshot",
        "ambiguous_price_window",
        "gw_counter_reset",
        "source_correction_counter_drop",
        "double_rise_recurrent",
        "rise_then_fall",
        "external_predictor_future_leak",
        "external_predictor_field_not_yet_available",
        "wildcard_activity_spike",
        "flag_transition_folklore",
        "ownership_rounding_boundary",
        "integer_price_support",
        "repurchase_resets_cohort",
        "profit_retention_path",
        "outer_fold_calibration_leak",
        "regime_drift_2026",
        "route_blocked_by_price_rise",
        "act_now_false_alarm",
    }
    assert required <= set(ids)
    assert len(ids) == 27
    assert len(ids) == len(set(ids))
    assert all(item["expected"] for item in fixture["cases"])


def test_post_midnight_future_event_and_late_received_canaries_are_blocked() -> None:
    values = (
        observation("eligible", hour=-2),
        observation("post-midnight", hour=1),
        observation("late-received", hour=-1, received_delay=2),
    )
    with pytest.raises(LeakageError):
        eligible_price_observations(
            values,
            player_id="player-1",
            cutoff=BASE,
            dataset_mode=DatasetMode.RECONSTRUCTED,
        )


def test_gw_reset_correction_and_stale_snapshot_are_distinct_anomalies() -> None:
    start = observation(
        "start",
        hour=0,
        transfers_in_total=1000,
        transfers_out_total=500,
        transfers_in_event=900,
        transfers_out_event=400,
    )
    reset = observation(
        "reset",
        hour=9,
        gameweek=2,
        transfers_in_total=1100,
        transfers_out_total=550,
        transfers_in_event=10,
        transfers_out_event=5,
    )
    correction = observation(
        "correction",
        hour=11,
        gameweek=2,
        transfers_in_total=1050,
        transfers_out_total=540,
        transfers_in_event=10,
        transfers_out_event=5,
        kind=ObservationKind.SOURCE_CORRECTION,
        supersedes="reset",
    )
    features = _features((start, reset, correction))
    kinds = {item.kind for item in features.anomalies}
    assert {
        FlowAnomalyKind.GAMEWEEK_COUNTER_RESET,
        FlowAnomalyKind.SOURCE_CORRECTION_COUNTER_DROP,
        FlowAnomalyKind.STALE_SNAPSHOT,
    } <= kinds


def test_wildcard_spike_flag_transition_and_ownership_rounding_do_not_invent_rules() -> None:
    features = _features(
        (
            observation("available", hour=0, ownership="1.99"),
            observation(
                "flagged",
                hour=2,
                ownership="1.99",
                transfers_in_total=1010,
                transfers_out_total=2500,
                status=PriceStatus.DOUBTFUL,
            ),
        ),
        active_manager_count=None,
        global_transfer_activity=3_000_000,
        chip_contamination="HIGH",
        chip_contamination_confidence="0.6",
    )
    assert features.ownership_regime.value == "LOW"
    assert features.denominator_uncertainty == Decimal(1)
    assert features.status_transition == "AVAILABLE->DOUBTFUL"
    assert features.status_uncertainty == config().transfer_features.status_uncertainty["DOUBTFUL"]
    assert features.chip_contamination.value == "HIGH"
    assert features.net_increment < 0


def test_outer_fold_calibration_leak_is_blocked() -> None:
    row = PriceEvaluationRow(
        row_id="outer-row",
        forecast_origin=BASE,
        label_available_at=BASE + timedelta(hours=1),
        probabilities=PriceProbabilityVector(
            probability_fall=Decimal("0.2"),
            probability_no_change=Decimal("0.5"),
            probability_rise=Decimal("0.3"),
        ),
        observed_event=PriceEvent.RISE,
        price_pmf=PricePmf(support=(PriceMass(price_units=76, probability=Decimal(1)),)),
        observed_price_units=76,
    )
    with pytest.raises(ValueError, match="outer-fold"):
        fit_price_calibration(
            (row,),
            calibration_id="blocked",
            calibration_version="v1",
            method="IDENTITY",
            training_cutoff=BASE + timedelta(days=1),
            probability_epsilon=config().competing_logit.calibration_probability_epsilon,
            outer_origin_ids=("outer-row",),
        )


def test_regime_drift_2026_remains_shadow_uncalibrated_and_rights_blocked() -> None:
    report = PriceService().validate()
    assert set(report.activation_statuses) == {
        ActivationStatus.RIGHTS_BLOCKED,
        ActivationStatus.SHADOW_ONLY,
        ActivationStatus.TARGET_SEASON_UNCALIBRATED,
    }
    assert report.production_actionable is False


def test_route_blocked_by_price_rise_is_preserved_as_a_discrete_branch() -> None:
    scenarios = build_optimiser_price_scenarios(
        player_id="player-1",
        horizon="24h",
        market_price_pmf=PricePmf(
            support=(
                PriceMass(price_units=75, probability=Decimal("0.5")),
                PriceMass(price_units=76, probability=Decimal("0.5")),
            )
        ),
        maximum_support=2,
        route_budget_units=75,
    )
    assert tuple(item.route_affordable for item in scenarios.scenarios) == (True, False)


def test_act_now_false_alarm_press_information_price_hit_and_expiring_ft_use_full_utility() -> None:
    decision = evaluate_act_now_vs_wait(
        (
            alternative(EarlyTransferAction.ACT_NOW, "8", hit="4"),
            alternative(
                EarlyTransferAction.WAIT_FOR_INFORMATION,
                "5",
                information_value="2",
                free_transfer_value="2",
            ),
            alternative(EarlyTransferAction.DO_NOT_TRANSFER, "0"),
        ),
        projection=projection(),
        dataset_mode=DatasetMode.RECONSTRUCTED,
        config=config(),
    )
    assert decision.recommended_action is EarlyTransferAction.WAIT_FOR_INFORMATION
    assert decision.expected_utility == Decimal(9)
    assert decision.price_probability_used_as_component_only is True
