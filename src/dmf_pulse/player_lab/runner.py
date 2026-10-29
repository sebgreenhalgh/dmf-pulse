"""Operational complete-cohort orchestration, without a second evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Literal

from dmf_pulse.evaluation.models import PointMetricResult
from dmf_pulse.player_lab.cohort import (
    CohortCustody,
    CohortProtocol,
    FinalCohort,
    ForecastCohort,
    SyntheticCohortLedger,
)
from dmf_pulse.player_lab.contracts import LabModel, Sealed, seal
from dmf_pulse.player_lab.demo import synthetic_forecasts
from dmf_pulse.player_lab.diagnostics import (
    MinutesDiagnostics,
    component_metrics,
    minutes_diagnostics,
)
from dmf_pulse.player_lab.evaluation import (
    PairedHoldout,
    PlayerScorecard,
    compare_holdout,
    evaluate_players,
)
from dmf_pulse.player_lab.rights import ingest_offline_actuals

BenchmarkId = Literal["B0", "B1", "B2", "B3", "B4", "B5"]


class BenchmarkAvailability(LabModel):
    benchmark_id: BenchmarkId
    status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    reason: str


class CohortEvaluationReport(Sealed):
    schema_version: Literal["player-cohort-evaluation-v1"] = "player-cohort-evaluation-v1"
    classification: Literal["OWNED_SYNTHETIC_ENGINEERING_ONLY"] = "OWNED_SYNTHETIC_ENGINEERING_ONLY"
    real_cohort_status: Literal["NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT"] = (
        "NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT"
    )
    real_cohort_size: Literal[0] = 0
    evaluated_at: datetime
    forecast_cohort_sha256: str
    final_cohort_sha256: str
    population_players: int
    gameweek_count: int
    expected_targets: int
    scored_targets: int
    attrition_count: Literal[0] = 0
    champion: PlayerScorecard
    challenger: PlayerScorecard
    holdout: PairedHoldout
    champion_components: dict[str, PointMetricResult]
    challenger_components: dict[str, PointMetricResult]
    champion_minutes: MinutesDiagnostics
    challenger_minutes: MinutesDiagnostics
    benchmarks: tuple[BenchmarkAvailability, ...]
    diagnostic_zero_baseline: Literal["NOT_A_B0_B5_BENCHMARK"] = "NOT_A_B0_B5_BENCHMARK"
    uncertainty_status: Literal["NOT_ESTIMATED_SMALL_SYNTHETIC_ENGINEERING_SAMPLE"] = (
        "NOT_ESTIMATED_SMALL_SYNTHETIC_ENGINEERING_SAMPLE"
    )
    predictive_skill_claim: Literal["NONE"] = "NONE"
    decision_quality_claim: Literal["NONE_NO_SEQUENTIAL_POLICY_REPLAY"] = (
        "NONE_NO_SEQUENTIAL_POLICY_REPLAY"
    )
    promotion: Literal["FORBIDDEN"] = "FORBIDDEN"
    limitations: tuple[str, ...] = (
        "Complete means all four preregistered owned players across two synthetic Gameweeks, not the current EPL catalogue.",
        "No genuine prospective player cohort or real predictive accuracy has been observed.",
        "Synthetic historical clocks demonstrate custody mechanics; they do not authenticate a real issue time.",
        "Start labels and frozen fixture-level start/60-plus probabilities are unavailable; minutes never imply a start.",
        "Repeated players and fixture dependence preclude treating target rows as independent samples.",
        "B0-B5 qualification is incomplete; zero points is only a diagnostic baseline.",
        "Tiny synthetic samples cannot establish calibration, superiority, confidence or promotion.",
    )


class PlayerEvaluationService:
    """Authenticate first, then compose the existing custody and Stage-12 services."""

    def __init__(self) -> None:
        self._last_evaluated_at: datetime | None = None

    def run(
        self,
        cohort: ForecastCohort,
        outcomes: FinalCohort,
        *,
        custody: CohortCustody,
        evaluated_at: datetime,
    ) -> CohortEvaluationReport:
        if (
            evaluated_at.tzinfo is None
            or evaluated_at.utcoffset() is None
            or (self._last_evaluated_at is not None and evaluated_at < self._last_evaluated_at)
        ):
            raise ValueError("evaluation clock invalid or reversed")
        cohort = ForecastCohort.model_validate_json(cohort.model_dump_json())
        outcomes = FinalCohort.model_validate_json(outcomes.model_dump_json())
        custody.verify_cohort(cohort)
        custody.verify_experiment(cohort.experiment)
        targets = tuple(item.target_id() for item in cohort.protocol.targets)
        if (
            outcomes.forecast_cohort_sha256 != cohort.semantic_sha256
            or tuple(item.key.target_id() for item in outcomes.labels) != targets
            or any(item.usable_at > evaluated_at for item in outcomes.labels)
        ):
            raise ValueError("later complete final outcomes must bind the exact frozen cohort")
        experiment = cohort.experiment
        champion = tuple(
            item for item in cohort.forecasts if item.forecast.model_id == experiment.champion_id
        )
        challenger = tuple(
            item for item in cohort.forecasts if item.forecast.model_id == experiment.challenger_id
        )
        c = evaluate_players(champion, outcomes.labels, custody=custody)
        r = evaluate_players(challenger, outcomes.labels, custody=custody)
        holdout = compare_holdout(
            experiment, champion, challenger, outcomes.labels, custody=custody
        )
        reasons: tuple[tuple[BenchmarkId, str], ...] = (
            ("B0", "NO_QUALIFIED_PRE_CUTOFF_RECENT_POINT_HISTORY"),
            ("B1", "NO_QUALIFIED_PRE_CUTOFF_OFFICIAL_FORM_HISTORY"),
            ("B2", "NO_QUALIFIED_MATCHED_MARKET_ONLY_FORECAST"),
            ("B3", "NO_QUALIFIED_MATCHED_MARKET_PLUS_MINUTES_FORECAST"),
            ("B4", "ANALYTIC_SYNTHETIC_PMF_IS_NOT_COMPLETE_PULSE_BENCHMARK"),
            ("B5", "NO_QUALIFIED_SEPARATELY_LABELLED_HINDSIGHT_POLICY"),
        )
        report = seal(
            CohortEvaluationReport.model_construct(
                evaluated_at=evaluated_at,
                forecast_cohort_sha256=cohort.semantic_sha256,
                final_cohort_sha256=outcomes.semantic_sha256,
                population_players=len({item.player_id for item in cohort.protocol.targets}),
                gameweek_count=len({item.gameweek for item in cohort.protocol.targets}),
                expected_targets=len(targets),
                scored_targets=c.count,
                champion=c,
                challenger=r,
                holdout=holdout,
                champion_components=component_metrics(champion, outcomes.labels),
                challenger_components=component_metrics(challenger, outcomes.labels),
                champion_minutes=minutes_diagnostics(champion, outcomes.labels),
                challenger_minutes=minutes_diagnostics(challenger, outcomes.labels),
                benchmarks=tuple(
                    BenchmarkAvailability(benchmark_id=key, reason=reason)
                    for key, reason in reasons
                ),
                semantic_sha256="0" * 64,
            )
        )
        self._last_evaluated_at = evaluated_at.astimezone(UTC)
        return report


@dataclass(frozen=True)
class OwnedForecastPhase:
    cohort: ForecastCohort
    custody: SyntheticCohortLedger
    clock: list[datetime]


def freeze_owned_cohort() -> OwnedForecastPhase:
    """Freeze the entire registered owned population before opening outcome bodies."""
    experiment, forecasts, _contexts = synthetic_forecasts()
    protocol = seal(
        CohortProtocol.model_construct(
            cohort_id="ACCEL003_OWNED_COMPLETE_PLAYER_COHORT_V1",
            registered_at=experiment.registered_at,
            experiment_sha256=experiment.semantic_sha256,
            targets=tuple(
                sorted(
                    {item.key.target_id(): item.key for item in forecasts}.values(),
                    key=lambda key: key.target_id(),
                )
            ),
            model_ids=tuple(sorted((experiment.champion_id, experiment.challenger_id))),
            sources=forecasts[0].sources,
            semantic_sha256="0" * 64,
        )
    )
    clock = [experiment.registered_at]
    custody = SyntheticCohortLedger(clock=lambda: clock[0])
    custody.register(protocol, experiment)
    frozen = []
    for forecast in forecasts:
        clock[0] = forecast.generated_at + timedelta(minutes=1)
        frozen.append(custody.freeze(forecast))
    cohort = seal(
        ForecastCohort.model_construct(
            protocol=protocol,
            experiment=experiment,
            forecasts=tuple(
                sorted(
                    frozen, key=lambda item: (item.forecast.model_id, item.forecast.key.target_id())
                )
            ),
            semantic_sha256="0" * 64,
        )
    )
    custody.close(cohort)
    return OwnedForecastPhase(cohort=cohort, custody=custody, clock=clock)


def finalize_owned_cohort(phase: OwnedForecastPhase) -> FinalCohort:
    """Later qualified labels are read only after original forecast custody closes."""
    phase.custody.verify_cohort(phase.cohort)
    _experiment, _forecasts, contexts = synthetic_forecasts()
    phase.clock[0] = max(item.usable_at for item in contexts)
    root = files("dmf_pulse.player_lab.resources")
    labels = tuple(
        sorted(
            (
                label
                for context in contexts
                for label in ingest_offline_actuals(
                    root.joinpath(f"actuals-gw{context.gameweek}.json").read_bytes(), context
                ).labels
            ),
            key=lambda item: item.key.target_id(),
        )
    )
    for label in labels:
        phase.custody.record_outcome(label)
    return seal(
        FinalCohort.model_construct(
            forecast_cohort_sha256=phase.cohort.semantic_sha256,
            labels=labels,
            semantic_sha256="0" * 64,
        )
    )


def operational_synthetic_evaluation() -> CohortEvaluationReport:
    phase = freeze_owned_cohort()
    labels = finalize_owned_cohort(phase)
    return PlayerEvaluationService().run(
        phase.cohort, labels, custody=phase.custody, evaluated_at=phase.clock[0]
    )
