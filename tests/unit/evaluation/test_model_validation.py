from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from dmf_pulse.evaluation.models import (
    BenchmarkDefinition,
    BenchmarkFamily,
    BenchmarkProjection,
    CalibrationArtifact,
    ComparatorInformationSet,
    DatasetMode,
    DecisionRegret,
    EvaluationFold,
    EvaluationReport,
    FeatureRecord,
    FoldWindow,
    ForecastArtifact,
    InclusionDecision,
    InformationBundle,
    InformationRecordDecision,
    LeakageFinding,
    LeakageKind,
    LeakageReport,
    MetricFamily,
    ObservationKind,
    ObservationRole,
    PolicyDecisionArtifact,
    PolicyTrajectory,
    PolicyTrajectoryStep,
    ScorecardRow,
    require_utc,
)
from tests.evaluation_helpers import BASE, ZERO, feature, lineage

pytestmark = pytest.mark.unit


def invalid(model: object, **updates: object) -> dict[str, object]:
    assert hasattr(model, "model_dump")
    payload = model.model_dump(mode="python")  # type: ignore[attr-defined]
    payload.update(updates)
    return payload


def test_utc_and_feature_role_invariants() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        require_utc(datetime(2026, 1, 1), field_name="x")
    with pytest.raises(ValueError, match="expressed in UTC"):
        require_utc(datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))), field_name="x")
    normal = feature()
    with pytest.raises(ValidationError, match="label records"):
        FeatureRecord.model_validate(
            invalid(normal, role=ObservationRole.LABEL, feature_intended=True)
        )
    with pytest.raises(ValidationError, match="feature records"):
        FeatureRecord.model_validate(invalid(normal, feature_intended=False))
    with pytest.raises(ValidationError, match="FINAL_OUTCOME"):
        FeatureRecord.model_validate(invalid(normal, dataset_mode=DatasetMode.FINAL_OUTCOME))
    with pytest.raises(ValidationError, match="binary floats"):
        FeatureRecord.model_validate(invalid(normal, values={"value": 0.1}))
    with pytest.raises(ValidationError, match="non-canonical"):
        FeatureRecord.model_validate(invalid(normal, values={"value": {"unordered"}}))


def test_lineage_cutoff_and_version_invariants() -> None:
    value = lineage()
    with pytest.raises(ValidationError, match="after forecast"):
        type(value).model_validate(invalid(value, information_cutoff=BASE + timedelta(seconds=1)))
    with pytest.raises(ValidationError, match="must be identical"):
        type(value).model_validate(invalid(value, usable_at_cutoff=BASE - timedelta(seconds=1)))
    with pytest.raises(ValidationError, match="training cutoff"):
        type(value).model_validate(invalid(value, training_cutoff=BASE + timedelta(seconds=1)))
    with pytest.raises(ValidationError, match="information cutoff"):
        type(value).model_validate(
            invalid(
                value,
                training_cutoff=BASE - timedelta(seconds=1),
                information_cutoff=BASE - timedelta(days=2),
                usable_at_cutoff=BASE - timedelta(days=2),
            )
        )
    with pytest.raises(ValidationError, match="label finality"):
        type(value).model_validate(invalid(value, label_finality_cutoff=BASE))
    with pytest.raises(ValidationError, match="sorted"):
        type(value).model_validate(invalid(value, model_version_ids=("z", "a")))
    with pytest.raises(ValidationError, match="unique"):
        type(value).model_validate(invalid(value, model_version_ids=("a", "a")))


def _bundle() -> InformationBundle:
    record = feature("a")
    decision = InformationRecordDecision(
        record_id="a",
        decision=InclusionDecision.INCLUDED,
        reason_code="OK",
        explanation="ok",
    )
    return InformationBundle(
        bundle_id="b",
        dataset_mode=DatasetMode.LIVE_OBSERVED,
        forecast_origin=BASE,
        information_cutoff=BASE,
        records=(record,),
        decisions=(decision,),
        blocking_violations=(),
        bundle_sha256=ZERO,
    )


def test_bundle_and_fold_canonical_invariants() -> None:
    bundle = _bundle()
    duplicate_record = feature("a")
    with pytest.raises(ValidationError, match="records"):
        InformationBundle.model_validate(
            invalid(bundle, records=(duplicate_record, duplicate_record))
        )
    duplicate_decision = bundle.decisions[0]
    with pytest.raises(ValidationError, match="decisions"):
        InformationBundle.model_validate(
            invalid(bundle, decisions=(duplicate_decision, duplicate_decision))
        )
    with pytest.raises(ValidationError, match="blocking"):
        InformationBundle.model_validate(invalid(bundle, blocking_violations=("z", "a")))
    fold = EvaluationFold(
        fold_id="f",
        ordinal=0,
        forecast_origin_id="o",
        forecast_origin=BASE,
        information_cutoff=BASE,
        training_origin_ids=("a", "b"),
        inner_folds=(),
        dataset_mode=DatasetMode.LIVE_OBSERVED,
        window=FoldWindow.EXPANDING,
        fold_sha256=ZERO,
    )
    with pytest.raises(ValidationError, match="cutoff"):
        EvaluationFold.model_validate(invalid(fold, information_cutoff=BASE + timedelta(seconds=1)))
    assert EvaluationFold.model_validate(
        invalid(fold, training_origin_ids=("b", "a"))
    ).training_origin_ids == ("b", "a")
    with pytest.raises(ValidationError, match="unique"):
        EvaluationFold.model_validate(invalid(fold, training_origin_ids=("a", "a")))


def _forecast() -> ForecastArtifact:
    return ForecastArtifact(
        forecast_id="f",
        benchmark_id="b",
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        target_id="t",
        horizon=1,
        point_forecast=Decimal(1),
        lineage=lineage(),
        issued_at=BASE,
        forecast_sha256=ZERO,
    )


def test_forecast_payload_invariants() -> None:
    forecast = _forecast()
    with pytest.raises(ValidationError, match="issued"):
        ForecastArtifact.model_validate(invalid(forecast, issued_at=BASE + timedelta(seconds=1)))
    earlier_issue = forecast.model_dump(mode="python")
    earlier_issue["lineage"] = lineage().model_copy(
        update={
            "information_cutoff": BASE - timedelta(hours=1),
            "usable_at_cutoff": BASE - timedelta(hours=1),
            "training_cutoff": BASE - timedelta(days=1),
        }
    )
    earlier_issue["issued_at"] = BASE - timedelta(hours=2)
    with pytest.raises(ValidationError, match="information cutoff"):
        ForecastArtifact.model_validate(earlier_issue)
    with pytest.raises(ValidationError, match="sum"):
        ForecastArtifact.model_validate(
            invalid(forecast, point_forecast=None, pmf={"0": Decimal("0.9")})
        )
    with pytest.raises(ValidationError, match="fixed"):
        ForecastArtifact.model_validate(
            invalid(forecast, scenario_samples=((Decimal(1),), (Decimal(1), Decimal(2))))
        )
    with pytest.raises(ValidationError, match="one value"):
        ForecastArtifact.model_validate(
            invalid(
                forecast,
                scenario_samples=((Decimal(1),), (Decimal(2),)),
                scenario_weights=(Decimal(1),),
            )
        )
    with pytest.raises(ValidationError, match="sum exactly"):
        ForecastArtifact.model_validate(
            invalid(
                forecast,
                scenario_samples=((Decimal(1),), (Decimal(2),)),
                scenario_weights=(Decimal("0.4"), Decimal("0.4")),
            )
        )
    with pytest.raises(ValidationError, match="without scenario"):
        ForecastArtifact.model_validate(invalid(forecast, scenario_weights=(Decimal(1),)))
    joint = ForecastArtifact.model_validate(
        invalid(
            forecast,
            point_forecast=None,
            scenario_samples=((Decimal(1), Decimal(2)),),
            scenario_weights=(Decimal(1),),
            scenario_dimension_ids=("player-a", "player-b"),
        )
    )
    assert joint.scenario_dimension_ids == ("player-a", "player-b")
    with pytest.raises(ValidationError, match="requires"):
        ForecastArtifact.model_validate(
            invalid(forecast, point_forecast=None, probability_forecast=None, pmf={})
        )
    with pytest.raises(ValidationError, match="COUNTERFACTUAL"):
        ForecastArtifact.model_validate(
            invalid(
                forecast,
                benchmark_id="B5D_PERFECT_SEASON_POLICY",
                dataset_mode=DatasetMode.LIVE_OBSERVED,
            )
        )


def test_calibration_benchmark_and_projection_invariants() -> None:
    calibration = CalibrationArtifact(
        calibration_id="c",
        method="IDENTITY",
        training_cutoff=BASE,
        training_record_ids=("a", "b"),
        excluded_outer_origin_ids=("z",),
        parameters={"intercept": Decimal(0), "slope": Decimal(1)},
        artifact_sha256=ZERO,
    )
    with pytest.raises(ValidationError, match="sorted"):
        CalibrationArtifact.model_validate(invalid(calibration, training_record_ids=("b", "a")))
    with pytest.raises(ValidationError, match="cannot train"):
        CalibrationArtifact.model_validate(invalid(calibration, excluded_outer_origin_ids=("b",)))
    with pytest.raises(ValidationError, match="exactly"):
        CalibrationArtifact.model_validate(invalid(calibration, parameters={"slope": Decimal(1)}))
    base = BenchmarkDefinition(
        benchmark_id="b",
        family=BenchmarkFamily.B0,
        name="b",
        feasible=True,
        oracle=False,
        required_inputs=(ObservationKind.RECENT_POINTS,),
        prohibited_inputs=(ObservationKind.OUTCOME,),
        description="b",
    )
    with pytest.raises(ValidationError, match="hindsight"):
        BenchmarkDefinition.model_validate(invalid(base, oracle=True))
    with pytest.raises(ValidationError, match="B5"):
        BenchmarkDefinition.model_validate(
            invalid(base, family=BenchmarkFamily.B5, feasible=False, oracle=False)
        )
    with pytest.raises(ValidationError, match="both"):
        BenchmarkDefinition.model_validate(
            invalid(base, prohibited_inputs=(ObservationKind.RECENT_POINTS,))
        )
    projection = BenchmarkProjection(
        benchmark=base,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        target_id="t",
        point_forecast=Decimal(1),
        evidence_record_ids=("a", "b"),
        forecast_origin=BASE,
        information_cutoff=BASE,
        information_bundle_sha256=ZERO,
        projection_sha256=ZERO,
    )
    with pytest.raises(ValidationError, match="sorted"):
        BenchmarkProjection.model_validate(invalid(projection, evidence_record_ids=("b", "a")))
    with pytest.raises(ValidationError, match="unique"):
        BenchmarkProjection.model_validate(invalid(projection, evidence_record_ids=("a", "a")))


def _decision() -> PolicyDecisionArtifact:
    return PolicyDecisionArtifact(
        decision_id="d",
        gameweek=1,
        forecast_origin=BASE,
        current_action={"action": "HOLD"},
        expected_utility=Decimal(1),
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        lineage=lineage(),
        decision_sha256=ZERO,
    )


def test_decision_trajectory_and_regret_invariants() -> None:
    decision = _decision()
    with pytest.raises(ValidationError, match="differ"):
        PolicyDecisionArtifact.model_validate(
            invalid(decision, forecast_origin=BASE - timedelta(seconds=1))
        )
    step = PolicyTrajectoryStep(
        gameweek=1,
        forecast_origin=BASE,
        information_bundle_sha256=ZERO,
        forecast_sha256=ZERO,
        decision_sha256=ZERO,
        executed_action={"action": "HOLD"},
        realised_utility=Decimal(2),
        utility_includes_hit_costs=True,
        outcome_revealed_at=BASE + timedelta(hours=1),
        state_before_sha256=ZERO,
        state_after_sha256="1" * 64,
        outcome_revealed_after_freeze=True,
    )
    trajectory = PolicyTrajectory(
        trajectory_id="t",
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        initial_state_sha256=ZERO,
        steps=(step,),
        cumulative_utility=Decimal(2),
        trajectory_sha256=ZERO,
    )
    with pytest.raises(ValidationError, match="at least"):
        PolicyTrajectory.model_validate(invalid(trajectory, steps=()))
    with pytest.raises(ValidationError, match="reconcile"):
        PolicyTrajectory.model_validate(invalid(trajectory, cumulative_utility=Decimal(3)))
    with pytest.raises(ValidationError, match="revealed"):
        PolicyTrajectory.model_validate(
            invalid(
                trajectory,
                steps=(step.model_copy(update={"outcome_revealed_after_freeze": False}),),
            )
        )
    regret = DecisionRegret(
        decision_id="d",
        comparator_id="c",
        comparator_information_set=ComparatorInformationSet.SAME_HISTORICAL_INFORMATION,
        comparator_is_oracle=False,
        realised_decision_utility=Decimal(1),
        realised_comparator_utility=Decimal(2),
        regret=Decimal(1),
        transfer_hit_points=Decimal(0),
        hit_adjusted_transfer_value=Decimal(1),
        no_transfer_utility=Decimal(0),
        regret_sha256=ZERO,
    )
    with pytest.raises(ValidationError, match="reconcile"):
        DecisionRegret.model_validate(invalid(regret, regret=Decimal(0)))
    with pytest.raises(ValidationError, match="oracle"):
        DecisionRegret.model_validate(invalid(regret, comparator_is_oracle=True))
    with pytest.raises(ValidationError, match="hit-adjusted"):
        DecisionRegret.model_validate(invalid(regret, hit_adjusted_transfer_value=Decimal(99)))


def _row(mode: DatasetMode = DatasetMode.COUNTERFACTUAL) -> ScorecardRow:
    return ScorecardRow(
        layer="FORECAST",
        metric_family=MetricFamily.POINT,
        dataset_mode=mode,
        forecast_origin=BASE,
        information_cutoff=BASE,
        horizon=1,
        subgroup="all",
        benchmark_id="b",
        metric_name="mae",
        metric_value=Decimal(1),
        status="PASS",
        limitations=(),
    )


def test_leakage_and_report_status_invariants() -> None:
    finding = LeakageFinding(
        finding_id="f",
        kind=LeakageKind.FUTURE_LEAKAGE_CANARY,
        record_ids=("r",),
        explanation="bad",
    )
    report = LeakageReport(
        status="BLOCKED",
        dataset_mode=DatasetMode.LIVE_OBSERVED,
        forecast_origin=BASE,
        findings=(finding,),
        checked_record_count=1,
        report_sha256=ZERO,
    )
    with pytest.raises(ValidationError, match="disagree"):
        LeakageReport.model_validate(invalid(report, status="PASS"))
    evaluation = EvaluationReport(
        report_id="r",
        rows=(_row(),),
        dataset_modes=(DatasetMode.COUNTERFACTUAL,),
        headline_mode=DatasetMode.COUNTERFACTUAL,
        forecast_rows=1,
        distribution_rows=0,
        decision_rows=0,
        operational_rows=0,
        limitations=(),
        lineage=lineage(),
        report_sha256=ZERO,
    )
    with pytest.raises(ValidationError, match="row modes"):
        EvaluationReport.model_validate(
            invalid(evaluation, dataset_modes=(DatasetMode.RECONSTRUCTED,))
        )
    mixed_rows = (_row(), _row(DatasetMode.RECONSTRUCTED))
    with pytest.raises(ValidationError, match="mixed"):
        EvaluationReport.model_validate(
            invalid(
                evaluation,
                rows=mixed_rows,
                dataset_modes=(DatasetMode.COUNTERFACTUAL, DatasetMode.RECONSTRUCTED),
                headline_mode=DatasetMode.COUNTERFACTUAL,
                forecast_rows=2,
            )
        )
    with pytest.raises(ValidationError, match="single-mode"):
        EvaluationReport.model_validate(invalid(evaluation, headline_mode=None))
    with pytest.raises(ValidationError, match="row count"):
        EvaluationReport.model_validate(invalid(evaluation, forecast_rows=0))


def test_bundle_decisions_inner_fold_scorecard_and_trajectory_chain_are_bound() -> None:
    bundle = _bundle()
    with pytest.raises(ValidationError, match="inclusion decisions disagree"):
        InformationBundle.model_validate(
            invalid(
                bundle,
                decisions=(
                    InformationRecordDecision(
                        record_id="a",
                        decision=InclusionDecision.EXCLUDED_EXPECTED,
                        reason_code="NO",
                        explanation="no",
                    ),
                ),
            )
        )
    with pytest.raises(ValidationError, match="blocking decisions disagree"):
        InformationBundle.model_validate(invalid(bundle, blocking_violations=("a",)))

    from dmf_pulse.evaluation.models import InnerFold

    inner = InnerFold(
        fold_id="inner",
        training_origin_ids=("a",),
        validation_origin_id="b",
        training_cutoff=BASE,
        validation_origin=BASE + timedelta(hours=1),
        fold_sha256=ZERO,
    )
    with pytest.raises(ValidationError, match="cannot follow"):
        InnerFold.model_validate(invalid(inner, training_cutoff=BASE + timedelta(hours=2)))
    with pytest.raises(ValidationError, match="validation origin"):
        InnerFold.model_validate(invalid(inner, validation_origin_id="a"))

    row = ScorecardRow(
        layer="FORECAST",
        metric_family=MetricFamily.POINT,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        forecast_origin=BASE,
        information_cutoff=BASE,
        horizon=1,
        subgroup="all",
        benchmark_id="B0",
        metric_name="MAE",
        metric_value=Decimal(1),
        status="OK",
        limitations=(),
    )
    with pytest.raises(ValidationError, match="cannot follow"):
        ScorecardRow.model_validate(invalid(row, information_cutoff=BASE + timedelta(seconds=1)))
    with pytest.raises(ValidationError, match="sorted"):
        ScorecardRow.model_validate(invalid(row, limitations=("z", "a")))
    with pytest.raises(ValidationError, match="wrong reporting panel"):
        ScorecardRow.model_validate(invalid(row, metric_family=MetricFamily.MULTIVARIATE))

    first = PolicyTrajectoryStep(
        gameweek=1,
        forecast_origin=BASE,
        information_bundle_sha256=ZERO,
        forecast_sha256=ZERO,
        decision_sha256=ZERO,
        executed_action={"action": "HOLD"},
        realised_utility=Decimal(1),
        utility_includes_hit_costs=True,
        outcome_revealed_at=BASE + timedelta(hours=1),
        state_before_sha256=ZERO,
        state_after_sha256="1" * 64,
        outcome_revealed_after_freeze=True,
    )
    second = first.model_copy(
        update={
            "gameweek": 2,
            "forecast_origin": BASE + timedelta(days=1),
            "outcome_revealed_at": BASE + timedelta(days=1, hours=1),
            "state_before_sha256": "2" * 64,
            "state_after_sha256": "3" * 64,
        }
    )
    with pytest.raises(ValidationError, match="continuous chain"):
        PolicyTrajectory(
            trajectory_id="bad-chain",
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            initial_state_sha256=ZERO,
            steps=(first, second),
            cumulative_utility=Decimal(2),
            trajectory_sha256=ZERO,
        )
    with pytest.raises(ValidationError, match="initial state"):
        PolicyTrajectory(
            trajectory_id="bad-initial",
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            initial_state_sha256="f" * 64,
            steps=(first,),
            cumulative_utility=Decimal(1),
            trajectory_sha256=ZERO,
        )
