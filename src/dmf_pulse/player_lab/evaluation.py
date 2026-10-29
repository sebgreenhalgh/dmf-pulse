"""Prospective player scoring composed from existing Stage-12 metric kernels."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol

from dmf_pulse.evaluation.artifacts import seal as seal_stage12
from dmf_pulse.evaluation.calibration import calibration_intercept_slope
from dmf_pulse.evaluation.distribution_metrics import score_distribution
from dmf_pulse.evaluation.models import (
    CalibrationResult,
    DatasetMode,
    DistributionMetricResult,
    EvaluationLineage,
    ForecastArtifact,
    OutcomeLabel,
    PointMetricResult,
    ProbabilityMetricResult,
)
from dmf_pulse.evaluation.point_metrics import score_frozen_point_forecasts
from dmf_pulse.evaluation.probability_metrics import score_probabilities
from dmf_pulse.ingestion.models import RightsCapability
from dmf_pulse.player_lab.contracts import (
    Experiment,
    FinalPlayerOutcome,
    FrozenForecast,
    LabModel,
    PlayerForecast,
    Sealed,
    seal,
)
from dmf_pulse.player_lab.rights import (
    require_qualified_forecast,
    require_qualified_outcome,
    require_sources,
)


class ForecastCustody(Protocol):
    def verify_frozen(self, value: FrozenForecast) -> None: ...
    def verify_experiment(self, value: Experiment) -> None: ...


class MemoryLedger:
    """Append-only in-memory test/research custody; its clock supplies freeze time."""

    def __init__(self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock
        self._forecasts: dict[tuple[str, str], FrozenForecast] = {}
        self._outcomes: dict[str, FinalPlayerOutcome] = {}
        self._experiments: dict[str, Experiment] = {}
        self._last_clock: datetime | None = None

    def _now(self) -> datetime:
        now = self._clock()
        if (
            now.tzinfo is None
            or now.utcoffset() is None
            or (self._last_clock is not None and now < self._last_clock)
        ):
            raise ValueError("ledger clock invalid/reversed")
        self._last_clock = now
        return now

    def register_experiment(self, value: Experiment) -> None:
        experiment = Experiment.model_validate_json(value.model_dump_json())
        if experiment.dataset_mode != "SYNTHETIC" or experiment.registered_at != self._now():
            raise ValueError("experiment must be registered at the custody clock")
        if experiment.experiment_id in self._experiments:
            raise ValueError("experiment already registered")
        self._experiments[experiment.experiment_id] = experiment

    def verify_experiment(self, value: Experiment) -> None:
        if self._experiments.get(value.experiment_id) != value:
            raise ValueError("experiment lacks original registered custody")

    def verify_frozen(self, value: FrozenForecast) -> None:
        key = (value.forecast.model_id, value.forecast.key.target_id())
        if self._forecasts.get(key) != value:
            raise ValueError("forecast differs from original frozen custody")

    def freeze(self, value: PlayerForecast) -> FrozenForecast:
        forecast = PlayerForecast.model_validate_json(value.model_dump_json())
        require_qualified_forecast(forecast)
        require_sources(forecast.sources, RightsCapability.DERIVED_STORAGE)
        if forecast.dataset_mode != "SYNTHETIC":
            raise ValueError("no real prospective source qualified")
        key = (forecast.model_id, forecast.key.target_id())
        existing = self._forecasts.get(key)
        if existing is not None:
            if existing.forecast != forecast:
                raise ValueError("frozen forecast substitution forbidden")
            return existing
        frozen = seal(
            FrozenForecast.model_construct(
                forecast=forecast, recorded_at=self._now(), semantic_sha256="0" * 64
            )
        )
        self._forecasts[key] = frozen
        return frozen

    def record_outcome(self, value: FinalPlayerOutcome) -> None:
        label = FinalPlayerOutcome.model_validate_json(value.model_dump_json())
        require_sources((label.source,), RightsCapability.DERIVED_STORAGE)
        require_qualified_outcome(label)
        if label.dataset_mode != "SYNTHETIC" or self._now() < label.usable_at:
            raise ValueError("outcome is not yet usable/qualified")
        if label.revision:
            old = self._outcomes.get(label.supersedes_sha256 or "")
            if (
                old is None
                or old.key != label.key
                or old.dataset_mode != label.dataset_mode
                or old.revision + 1 != label.revision
                or old.usable_at >= label.usable_at
                or old.original_points_lock_at != label.original_points_lock_at
            ):
                raise ValueError("correction graph is invalid")
            if any(
                item.supersedes_sha256 == old.semantic_sha256 for item in self._outcomes.values()
            ):
                raise ValueError("correction fork forbidden")
        elif any(item.key == label.key for item in self._outcomes.values()):
            raise ValueError("label substitution requires append-only correction")
        self._outcomes[label.semantic_sha256] = label


class PairDiagnostic(LabModel):
    target_id: str
    gameweek: int
    position: str
    minutes_band: str
    predicted: Decimal
    actual: int
    error: Decimal
    distribution: DistributionMetricResult


class PlayerScorecard(Sealed):
    schema_version: Literal["player-scorecard-v1"] = "player-scorecard-v1"
    dataset_mode: Literal["SYNTHETIC", "PROSPECTIVE_REAL"]
    real_cohort_status: Literal["NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT"] = (
        "NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT"
    )
    model_id: str
    count: int
    missing_count: Literal[0] = 0
    point_metrics: PointMetricResult
    zero_baseline: PointMetricResult
    probability_5plus: ProbabilityMetricResult
    calibration_5plus: CalibrationResult
    mean_ranked_probability_score: Decimal
    central_80_coverage: Decimal
    by_gameweek: dict[str, PointMetricResult]
    by_position: dict[str, PointMetricResult]
    by_minutes_band: dict[str, PointMetricResult]
    pairs: tuple[PairDiagnostic, ...]
    forecast_hashes: tuple[str, ...]
    label_hashes: tuple[str, ...]
    promotion: Literal["FORBIDDEN"] = "FORBIDDEN"
    decision_quality: Literal["NOT_INFERRED_FROM_FORECAST_ACCURACY"] = (
        "NOT_INFERRED_FROM_FORECAST_ACCURACY"
    )


def _stage12(
    value: FrozenForecast, label: FinalPlayerOutcome, *, zero: bool = False
) -> tuple[ForecastArtifact, OutcomeLabel]:
    forecast = value.forecast
    lineage = EvaluationLineage(
        forecast_origin=value.recorded_at,
        information_cutoff=forecast.information_cutoff,
        usable_at_cutoff=forecast.information_cutoff,
        label_finality_cutoff=forecast.label_finality_cutoff,
        model_version_ids=forecast.model_version_ids,
        ruleset_id="PLAYER_LAB_EXPLICIT_RULESET",
        training_cutoff=forecast.training_cutoff,
        ruleset_hash=forecast.ruleset_sha256,
        code_commit=forecast.code_sha,
        dataset_manifest_sha256=forecast.sources[0].payload_sha256,
        input_manifest_sha256=forecast.input_sha256,
    )
    stage_forecast = seal_stage12(
        ForecastArtifact(
            forecast_id=value.semantic_sha256,
            benchmark_id="PREDECLARED_ZERO_POINTS_V1" if zero else forecast.model_id,
            dataset_mode=DatasetMode.RECONSTRUCTED,
            target_id=forecast.key.target_id(),
            horizon=1,
            point_forecast=Decimal(0) if zero else forecast.mean,
            pmf={} if zero else {str(key): mass for key, mass in forecast.pmf.items()},
            lineage=lineage,
            issued_at=forecast.generated_at,
            forecast_sha256="0" * 64,
        ),
        "forecast_sha256",
    )
    stage_label = seal_stage12(
        OutcomeLabel(
            label_id=label.semantic_sha256,
            target_id=label.key.target_id(),
            dataset_mode=DatasetMode.FINAL_OUTCOME,
            outcome=Decimal(label.total_points),
            finalized_at=label.finalized_at,
            label_sha256="0" * 64,
        ),
        "label_sha256",
    )
    return stage_forecast, stage_label


def evaluate_players(
    forecasts: tuple[FrozenForecast, ...],
    labels: tuple[FinalPlayerOutcome, ...],
    *,
    custody: ForecastCustody,
) -> PlayerScorecard:
    forecasts = tuple(
        FrozenForecast.model_validate_json(item.model_dump_json()) for item in forecasts
    )
    labels = tuple(
        FinalPlayerOutcome.model_validate_json(item.model_dump_json()) for item in labels
    )
    for frozen in forecasts:
        custody.verify_frozen(frozen)
        require_qualified_forecast(frozen.forecast)
    if not forecasts or len(forecasts) != len(labels):
        raise ValueError("nonzero exact forecast/label cohort required")
    targets = tuple(item.forecast.key.target_id() for item in forecasts)
    label_targets = tuple(item.key.target_id() for item in labels)
    if (
        len(set(targets)) != len(targets)
        or len(set(label_targets)) != len(label_targets)
        or set(targets) != set(label_targets)
    ):
        raise ValueError("missing/duplicate/mismatched labels")
    if len({item.forecast.model_id for item in forecasts}) != 1:
        raise ValueError("one model per scorecard")
    if {item.forecast.dataset_mode for item in forecasts} != {"SYNTHETIC"} or {
        item.dataset_mode for item in labels
    } != {"SYNTHETIC"}:
        raise ValueError("no rights-qualified real prospective cohort")
    require_sources(
        (source for item in forecasts for source in item.forecast.sources),
        RightsCapability.DERIVED_STORAGE,
    )
    require_sources((item.source for item in labels), RightsCapability.DERIVED_STORAGE)
    for label in labels:
        require_qualified_outcome(label)
    by_target = {item.key.target_id(): item for item in labels}
    ordered = tuple(sorted(forecasts, key=lambda item: item.forecast.key.target_id()))
    aligned = tuple(by_target[item.forecast.key.target_id()] for item in ordered)
    converted = tuple(
        _stage12(forecast, label) for forecast, label in zip(ordered, aligned, strict=True)
    )
    stage_forecasts = tuple(item[0] for item in converted)
    stage_labels = tuple(item[1] for item in converted)
    metric = score_frozen_point_forecasts(stage_forecasts, stage_labels)
    pairs = []
    probabilities = []
    events = []
    for frozen, label in zip(ordered, aligned, strict=True):
        forecast = frozen.forecast
        if label.finalized_at <= forecast.deadline_at or frozen.recorded_at >= label.finalized_at:
            raise ValueError("outcome leakage/invalid chronology")
        probability = sum(
            (mass for points, mass in forecast.pmf.items() if points >= 5), Decimal(0)
        )
        probabilities.append(probability)
        events.append(int(label.total_points >= 5))
        minutes = forecast.expected_minutes
        pairs.append(
            PairDiagnostic(
                target_id=forecast.key.target_id(),
                gameweek=forecast.key.gameweek,
                position=forecast.position,
                minutes_band="UNKNOWN"
                if minutes is None
                else "UNDER_60"
                if minutes < 60
                else "60_PLUS",
                predicted=forecast.mean,
                actual=label.total_points,
                error=forecast.mean - label.total_points,
                distribution=score_distribution(
                    {Decimal(key): mass for key, mass in forecast.pmf.items()},
                    Decimal(label.total_points),
                ),
            )
        )

    def breakdown(attribute: str) -> dict[str, PointMetricResult]:
        result = {}
        for category in sorted({str(getattr(pair, attribute)) for pair in pairs}):
            indices = tuple(
                index
                for index, pair in enumerate(pairs)
                if str(getattr(pair, attribute)) == category
            )
            result[category] = score_frozen_point_forecasts(
                tuple(stage_forecasts[index] for index in indices),
                tuple(stage_labels[index] for index in indices),
            )
        return result

    zero_forecasts = tuple(
        _stage12(forecast, label, zero=True)[0]
        for forecast, label in zip(ordered, aligned, strict=True)
    )
    return seal(
        PlayerScorecard.model_construct(
            dataset_mode="SYNTHETIC",
            model_id=ordered[0].forecast.model_id,
            count=len(pairs),
            point_metrics=metric,
            zero_baseline=score_frozen_point_forecasts(zero_forecasts, stage_labels),
            probability_5plus=score_probabilities(tuple(probabilities), tuple(events)),
            calibration_5plus=calibration_intercept_slope(tuple(probabilities), tuple(events)),
            mean_ranked_probability_score=sum(
                (pair.distribution.ranked_probability_score for pair in pairs), Decimal(0)
            )
            / len(pairs),
            central_80_coverage=sum(
                (pair.distribution.interval_coverage for pair in pairs), Decimal(0)
            )
            / len(pairs),
            by_gameweek=breakdown("gameweek"),
            by_position=breakdown("position"),
            by_minutes_band=breakdown("minutes_band"),
            pairs=tuple(pairs),
            forecast_hashes=tuple(item.semantic_sha256 for item in ordered),
            label_hashes=tuple(item.semantic_sha256 for item in aligned),
            semantic_sha256="0" * 64,
        )
    )


class PairedHoldout(Sealed):
    experiment_sha256: str
    development_count: int
    holdout_count: int
    champion: PlayerScorecard
    challenger: PlayerScorecard
    paired_absolute_error_delta: Decimal
    promotion: Literal["FORBIDDEN"] = "FORBIDDEN"


def compare_holdout(
    experiment: Experiment,
    champion: tuple[FrozenForecast, ...],
    challenger: tuple[FrozenForecast, ...],
    labels: tuple[FinalPlayerOutcome, ...],
    *,
    custody: ForecastCustody,
) -> PairedHoldout:
    experiment = Experiment.model_validate_json(experiment.model_dump_json())
    custody.verify_experiment(experiment)
    for frozen in (*champion, *challenger):
        custody.verify_frozen(frozen)
    if {item.forecast.model_id for item in champion} != {experiment.champion_id} or {
        item.forecast.model_id for item in challenger
    } != {experiment.challenger_id}:
        raise ValueError("models differ from preregistration")
    for cohort in (champion, challenger):
        if tuple(sorted(item.forecast.key.target_id() for item in cohort)) != experiment.target_ids:
            raise ValueError("paired cohort differs from preregistration")
        if any(
            experiment.registered_at > item.forecast.generated_at
            or experiment.dataset_mode != item.forecast.dataset_mode
            for item in cohort
        ):
            raise ValueError("post-hoc or incompatible experiment")
    left = {item.forecast.key.target_id(): item.forecast for item in champion}
    for item in challenger:
        original = left[item.forecast.key.target_id()]
        if (
            original.information_cutoff,
            original.deadline_at,
            original.ruleset_sha256,
            original.sources,
        ) != (
            item.forecast.information_cutoff,
            item.forecast.deadline_at,
            item.forecast.ruleset_sha256,
            item.forecast.sources,
        ):
            raise ValueError("paired information sets differ")
    development = tuple(
        item for item in champion if item.forecast.key.gameweek < experiment.holdout_start_gameweek
    )
    holdout = tuple(
        item for item in champion if item.forecast.key.gameweek >= experiment.holdout_start_gameweek
    )
    if (
        not development
        or not holdout
        or max(item.forecast.deadline_at for item in development)
        >= min(item.forecast.deadline_at for item in holdout)
    ):
        raise ValueError("chronological holdout requires earlier development window")
    target_set = {item.forecast.key.target_id() for item in holdout}
    if {item.key.target_id() for item in labels} != set(experiment.target_ids):
        raise ValueError("holdout label coverage differs")
    holdout_labels = tuple(item for item in labels if item.key.target_id() in target_set)
    c = evaluate_players(holdout, holdout_labels, custody=custody)
    r = evaluate_players(
        tuple(item for item in challenger if item.forecast.key.target_id() in target_set),
        holdout_labels,
        custody=custody,
    )
    return seal(
        PairedHoldout.model_construct(
            experiment_sha256=experiment.semantic_sha256,
            development_count=len(development),
            holdout_count=len(holdout),
            champion=c,
            challenger=r,
            paired_absolute_error_delta=sum(
                (
                    abs(right.error) - abs(left.error)
                    for left, right in zip(c.pairs, r.pairs, strict=True)
                ),
                Decimal(0),
            )
            / len(c.pairs),
            semantic_sha256="0" * 64,
        )
    )
