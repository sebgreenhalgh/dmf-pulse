"""Qualified real point forecasts and complete chronological evaluation contracts.

Point-only historical predictions remain point-only. No distribution, component,
minutes or custody fact is reconstructed to satisfy a richer schema.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.evaluation.artifacts import seal as stage12_seal
from dmf_pulse.evaluation.artifacts import verify_sealed
from dmf_pulse.evaluation.benchmarks import benchmark_suite
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
from dmf_pulse.evaluation.point_metrics import score_forecast, score_frozen_point_forecasts
from dmf_pulse.evaluation.probability_metrics import score_probabilities
from dmf_pulse.operation.models import MetadataTime
from dmf_pulse.player_lab.contracts import (
    FinalPlayerOutcome,
    LabModel,
    PlayerForecast,
    PlayerKey,
    Sealed,
    Sha,
    SourceRef,
    seal,
)


class DeadlinePopulation(LabModel):
    gameweek: int = Field(ge=1, le=38)
    deadline_at: datetime
    official_deadline_evidence_sha256: Sha
    catalogue_source: SourceRef
    targets: tuple[PlayerKey, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_population(self) -> Self:
        ids = tuple(row.target_id() for row in self.targets)
        if ids != tuple(sorted(set(ids))) or any(
            row.gameweek != self.gameweek for row in self.targets
        ):
            raise ValueError("complete canonical deadline population required")
        if len({row.player_id for row in self.targets}) != len(self.targets):
            raise ValueError("one player target per Gameweek, including blank/double fixtures")
        if len({row.season for row in self.targets}) != 1:
            raise ValueError("one season per deadline population")
        if self.catalogue_source.usable_at >= self.deadline_at:
            raise ValueError("catalogue was not available before the deadline")
        return self


class ModelBinding(LabModel):
    model_id: str
    code_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    model_version_ids: tuple[str, ...] = Field(min_length=1)
    ruleset_sha256: Sha

    @model_validator(mode="after")
    def canonical_versions(self) -> Self:
        if not self.model_id or self.model_version_ids != tuple(
            sorted(set(self.model_version_ids))
        ):
            raise ValueError("canonical model identity required")
        return self


class RealPlayerProtocol(Sealed):
    schema_version: Literal["qualified-real-player-protocol-v1"] = (
        "qualified-real-player-protocol-v1"
    )
    cohort_id: str
    season: str = Field(pattern=r"^20\d{2}/\d{2}$")
    registered_at: datetime
    gameweeks: tuple[int, ...] = Field(min_length=1)
    evaluation_classification: Literal["PREREGISTERED_PROSPECTIVE", "POST_ORIGIN_DESCRIPTIVE"] = (
        "PREREGISTERED_PROSPECTIVE"
    )
    first_deadline_at: datetime
    first_deadline_evidence_sha256: Sha
    model_ids: tuple[str, ...] = Field(min_length=1)
    model_bindings: tuple[ModelBinding, ...]
    selection_policy: Literal["FIXED_ACCEPTED_VERSIONS_NO_SELECTION_OR_TUNING"] = (
        "FIXED_ACCEPTED_VERSIONS_NO_SELECTION_OR_TUNING"
    )
    metric_policy: Literal["STAGE12_POINT_PMF_5PLUS_80COVERAGE_V1"] = (
        "STAGE12_POINT_PMF_5PLUS_80COVERAGE_V1"
    )
    inner_gameweeks: tuple[int, ...]
    holdout_gameweeks: tuple[int, ...]
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    source_manifest_sha256: Sha
    source_scope: Literal["FIXED_PROFILE_PURPOSE_NEW_VINTAGES_QUALIFIED_PER_DEADLINE"] = (
        "FIXED_PROFILE_PURPOSE_NEW_VINTAGES_QUALIFIED_PER_DEADLINE"
    )
    benchmark_definitions_sha256: Sha
    information_grade: Literal["LIVE_OBSERVED", "RAW_OBSERVED"]
    inclusion: Literal[
        "ALL_CATALOGUE_PLAYERS_AT_EACH_DEADLINE_INCLUDING_NEW_TRANSFERS_SPARSE_HISTORY_BLANK_DGW"
    ] = "ALL_CATALOGUE_PLAYERS_AT_EACH_DEADLINE_INCLUDING_NEW_TRANSFERS_SPARSE_HISTORY_BLANK_DGW"
    missingness: Literal["REPORT_ALL_EXPECTED_CELLS_BLOCK_INCOMPLETE_COMPARISON"] = (
        "REPORT_ALL_EXPECTED_CELLS_BLOCK_INCOMPLETE_COMPARISON"
    )
    uncertainty: Literal["CLUSTER_BY_GAMEWEEK_NO_PLAYER_ROW_INDEPENDENCE_CLAIM"] = (
        "CLUSTER_BY_GAMEWEEK_NO_PLAYER_ROW_INDEPENDENCE_CLAIM"
    )
    promotion: Literal["FORBIDDEN"] = "FORBIDDEN"

    @model_validator(mode="after")
    def chronological_registration(self) -> Self:
        weeks = self.gameweeks
        if any(not 1 <= week <= 38 for week in weeks):
            raise ValueError("Gameweek outside official season support")
        if weeks != tuple(sorted(set(weeks))) or self.model_ids != tuple(
            sorted(set(self.model_ids))
        ):
            raise ValueError("unique chronological populations and models required")
        if tuple(row.model_id for row in self.model_bindings) != self.model_ids:
            raise ValueError("exact predeclared code/model/rules bindings required")
        if self.evaluation_classification == "PREREGISTERED_PROSPECTIVE" and (
            not self.inner_gameweeks
            or not self.holdout_gameweeks
            or self.inner_gameweeks != tuple(sorted(set(self.inner_gameweeks)))
            or self.holdout_gameweeks != tuple(sorted(set(self.holdout_gameweeks)))
            or max(self.inner_gameweeks) >= min(self.holdout_gameweeks)
            or tuple(sorted((*self.inner_gameweeks, *self.holdout_gameweeks))) != weeks
        ):
            raise ValueError("earlier inner folds and locked later holdout required")
        if self.evaluation_classification == "POST_ORIGIN_DESCRIPTIVE" and (
            self.inner_gameweeks or self.holdout_gameweeks != weeks
        ):
            raise ValueError("post-origin recovery cannot claim a new confirmatory holdout")
        if (
            self.evaluation_classification == "PREREGISTERED_PROSPECTIVE"
            and self.registered_at >= self.first_deadline_at
        ):
            raise ValueError("prospective protocol cannot be registered after a target deadline")
        if any(source.usable_at > self.registered_at for source in self.sources):
            raise ValueError("registration includes future sources")
        if self.source_manifest_sha256 != canonical_sha256(
            [row.model_dump(mode="json") for row in self.sources]
        ):
            raise ValueError("full dependency manifest differs")
        if self.benchmark_definitions_sha256 != canonical_sha256(
            [row.model_dump(mode="json") for row in benchmark_suite()]
        ):
            raise ValueError("accepted B0-B5 definitions differ")
        return self


class RealDeadlineRegistration(Sealed):
    schema_version: Literal["qualified-real-player-deadline-registration-v1"] = (
        "qualified-real-player-deadline-registration-v1"
    )
    protocol_sha256: Sha
    population: DeadlinePopulation
    registered_at: datetime
    custody: Literal["DATABASE_PREDEADLINE", "QUALIFIED_EXTERNAL_HISTORICAL_IMPORT"] = (
        "DATABASE_PREDEADLINE"
    )
    original_population_frozen_at: datetime
    external_custody_sha256: Sha | None = None

    @model_validator(mode="after")
    def original_catalogue_before_deadline(self) -> Self:
        if (
            not self.population.catalogue_source.usable_at
            <= self.original_population_frozen_at
            < self.population.deadline_at
        ) or self.registered_at < self.original_population_frozen_at:
            raise ValueError("deadline population must be captured and registered prospectively")
        if self.custody == "DATABASE_PREDEADLINE" and (
            self.original_population_frozen_at != self.registered_at
            or self.external_custody_sha256 is not None
        ):
            raise ValueError("native population registration cannot be backdated")
        if (
            self.custody == "QUALIFIED_EXTERNAL_HISTORICAL_IMPORT"
            and self.external_custody_sha256 is None
        ):
            raise ValueError("historical population needs independently qualified external proof")
        return self


class RealPointForecast(Sealed):
    schema_version: Literal["qualified-real-player-point-forecast-v1"] = (
        "qualified-real-player-point-forecast-v1"
    )
    dataset_mode: Literal["PROSPECTIVE_REAL"] = "PROSPECTIVE_REAL"
    key: PlayerKey
    model_id: str
    stage12: ForecastArtifact
    generated_at: datetime
    information_cutoff: datetime
    deadline_at: datetime
    label_finality_cutoff: datetime
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    expected_minutes: Decimal | None = None
    original_full_forecast: PlayerForecast | None = None

    @model_validator(mode="after")
    def preserve_original_point_lineage(self) -> Self:
        artifact = self.stage12
        verify_sealed(artifact, "forecast_sha256")
        if (
            artifact.dataset_mode not in {DatasetMode.LIVE_OBSERVED, DatasetMode.RAW_OBSERVED}
            or artifact.horizon != 1
            or artifact.target_id != self.key.target_id()
            or artifact.benchmark_id != self.model_id
            or artifact.point_forecast is None
            or artifact.probability_forecast is not None
            or artifact.scenario_samples
            or artifact.scenario_weights
            or artifact.scenario_dimension_ids
            or artifact.issued_at != self.generated_at
            or artifact.lineage.information_cutoff != self.information_cutoff
            or not self.information_cutoff
            <= self.generated_at
            < self.deadline_at
            < self.label_finality_cutoff
            or artifact.lineage.forecast_origin >= self.deadline_at
            or artifact.lineage.label_finality_cutoff != self.label_finality_cutoff
            or any(row.usable_at > self.information_cutoff for row in self.sources)
            or artifact.lineage.dataset_manifest_sha256
            != canonical_sha256([row.model_dump(mode="json") for row in self.sources])
        ):
            raise ValueError("authentic original point forecast and full lineage required")
        if artifact.pmf:
            if any(str(int(key)) != key for key in artifact.pmf):
                raise ValueError("canonical integer player-point support required")
            pmf_mean = sum((Decimal(key) * mass for key, mass in artifact.pmf.items()), Decimal(0))
            # Preserve the accepted PlayerForecast v1 reconciliation tolerance.
            if abs(pmf_mean - artifact.point_forecast) > Decimal("1e-10"):
                raise ValueError("original player PMF and point mean do not reconcile")
        if self.expected_minutes is not None and not Decimal(
            0
        ) <= self.expected_minutes <= 90 * len(self.key.fixture_ids):
            raise ValueError("expected minutes outside exact fixture support")
        if self.original_full_forecast is not None:
            original = PlayerForecast.model_validate_json(
                self.original_full_forecast.model_dump_json()
            )
            if (
                original.dataset_mode != "PROSPECTIVE_REAL"
                or original.key != self.key
                or original.model_id != self.model_id
                or original.mean != artifact.point_forecast
                or {str(key): mass for key, mass in original.pmf.items()} != artifact.pmf
                or original.sources != self.sources
                or original.generated_at != self.generated_at
                or original.information_cutoff != self.information_cutoff
                or original.deadline_at != self.deadline_at
                or original.label_finality_cutoff != self.label_finality_cutoff
                or original.expected_minutes != self.expected_minutes
                or original.training_cutoff != artifact.lineage.training_cutoff
                or original.input_sha256 != artifact.lineage.input_manifest_sha256
                or original.ruleset_sha256 != artifact.lineage.ruleset_hash
                or original.model_version_ids != artifact.lineage.model_version_ids
                or original.code_sha != artifact.lineage.code_commit
            ):
                raise ValueError("full forecast adapter changed original predictions or lineage")
        return self


def adapt_qualified_full_forecast(
    value: PlayerForecast,
    *,
    information_grade: Literal["LIVE_OBSERVED", "RAW_OBSERVED"],
    now: datetime,
) -> RealPointForecast:
    """Preserve the existing full prediction; do not generate missing components."""
    from dmf_pulse.player_lab.real_rights import require_real_sources

    require_real_sources(value.sources, now=now)
    value = PlayerForecast.model_validate_json(value.model_dump_json())
    if value.dataset_mode != "PROSPECTIVE_REAL":
        raise ValueError("synthetic forecast cannot enter real evaluation")
    lineage = EvaluationLineage(
        forecast_origin=value.generated_at,
        information_cutoff=value.information_cutoff,
        usable_at_cutoff=value.information_cutoff,
        training_cutoff=value.training_cutoff,
        label_finality_cutoff=value.label_finality_cutoff,
        model_version_ids=value.model_version_ids,
        ruleset_id="PLAYER_LAB_EXPLICIT_RULESET",
        ruleset_hash=value.ruleset_sha256,
        code_commit=value.code_sha,
        dataset_manifest_sha256=canonical_sha256(
            [row.model_dump(mode="json") for row in value.sources]
        ),
        input_manifest_sha256=value.input_sha256,
    )
    stage = stage12_seal(
        ForecastArtifact(
            forecast_id=value.semantic_sha256,
            benchmark_id=value.model_id,
            dataset_mode=DatasetMode(information_grade),
            target_id=value.key.target_id(),
            horizon=1,
            point_forecast=value.mean,
            pmf={str(key): mass for key, mass in value.pmf.items()},
            lineage=lineage,
            issued_at=value.generated_at,
            forecast_sha256="0" * 64,
        ),
        "forecast_sha256",
    )
    return seal(
        RealPointForecast.model_construct(
            key=value.key,
            model_id=value.model_id,
            stage12=stage,
            generated_at=value.generated_at,
            information_cutoff=value.information_cutoff,
            deadline_at=value.deadline_at,
            label_finality_cutoff=value.label_finality_cutoff,
            sources=value.sources,
            expected_minutes=value.expected_minutes,
            original_full_forecast=value,
            semantic_sha256="0" * 64,
        )
    )


class RealPointFreeze(Sealed):
    forecast: RealPointForecast
    population_registration_sha256: Sha
    recorded_at: datetime
    original_frozen_at: datetime
    custody: Literal["DATABASE_PREDEADLINE", "QUALIFIED_EXTERNAL_HISTORICAL_IMPORT"]
    external_custody_sha256: Sha | None = None

    @model_validator(mode="after")
    def genuine_custody(self) -> Self:
        if not self.forecast.generated_at <= self.original_frozen_at < self.forecast.deadline_at:
            raise ValueError("original forecast must be frozen before deadline")
        if self.recorded_at < self.original_frozen_at:
            raise ValueError("database import predates original freeze")
        if self.custody == "DATABASE_PREDEADLINE":
            if (
                self.original_frozen_at != self.recorded_at
                or self.external_custody_sha256 is not None
            ):
                raise ValueError("native database custody cannot be backdated")
        elif self.external_custody_sha256 is None:
            raise ValueError("historical import needs independently accepted external byte proof")
        return self


class RealCoverage(LabModel):
    expected_cells: int | None
    present_cells: int
    missing_cells: tuple[tuple[str, str], ...]
    extra_cells: tuple[tuple[str, str], ...]
    duplicate_cells: tuple[tuple[str, str], ...]
    unregistered_gameweeks: tuple[int, ...]
    complete: bool


def real_coverage(
    protocol: RealPlayerProtocol,
    registrations: tuple[RealDeadlineRegistration, ...],
    forecasts: tuple[RealPointFreeze, ...],
) -> RealCoverage:
    allowed_profiles = {(row.profile_id, row.profile_sha256) for row in protocol.sources}
    all_sources = (
        *(row.population.catalogue_source for row in registrations),
        *(source for row in forecasts for source in row.forecast.sources),
    )
    if any((row.profile_id, row.profile_sha256) not in allowed_profiles for row in all_sources):
        raise ValueError("forecast/catalogue profile differs from predeclared source scope")
    weeks = tuple(row.population.gameweek for row in registrations)
    if (
        weeks != tuple(sorted(set(weeks)))
        or not set(weeks) <= set(protocol.gameweeks)
        or any(row.protocol_sha256 != protocol.semantic_sha256 for row in registrations)
    ):
        raise ValueError("deadline populations differ from registered protocol")
    unregistered = tuple(sorted(set(protocol.gameweeks) - set(weeks)))
    targets = tuple(
        target.target_id() for row in registrations for target in row.population.targets
    )
    by_week = {row.population.gameweek: row for row in registrations}
    for row in registrations:
        if row.registered_at < protocol.registered_at or any(
            target.season != protocol.season for target in row.population.targets
        ):
            raise ValueError("population season or registration chronology differs")
        if row.population.gameweek == protocol.gameweeks[0] and (
            row.population.deadline_at != protocol.first_deadline_at
            or row.population.official_deadline_evidence_sha256
            != protocol.first_deadline_evidence_sha256
        ):
            raise ValueError("first population differs from exact registered official deadline")
    if any(
        left.population.deadline_at >= right.population.deadline_at
        for left, right in pairwise(registrations)
    ):
        raise ValueError("deadline chronology differs from inner/later Gameweek order")
    for frozen in forecasts:
        value = frozen.forecast
        binding = next(
            (row for row in protocol.model_bindings if row.model_id == value.model_id), None
        )
        if binding is None or (
            value.stage12.lineage.code_commit,
            value.stage12.lineage.model_version_ids,
            value.stage12.lineage.ruleset_hash,
        ) != (binding.code_sha, binding.model_version_ids, binding.ruleset_sha256):
            raise ValueError("forecast changed predeclared model/code/rules identity")
        population = by_week.get(value.key.gameweek)
        if population is None or (
            frozen.population_registration_sha256 != population.semantic_sha256
            or value.key not in population.population.targets
            or value.key.season != protocol.season
            or value.deadline_at != population.population.deadline_at
            or population.population.catalogue_source not in value.sources
            or not population.original_population_frozen_at
            <= value.generated_at
            <= frozen.original_frozen_at
        ):
            raise ValueError("forecast differs from its authenticated deadline population")
    expected = {(model, target) for model in protocol.model_ids for target in targets}
    cells = [(row.forecast.model_id, row.forecast.key.target_id()) for row in forecasts]
    present = set(cells)
    missing, extra = tuple(sorted(expected - present)), tuple(sorted(present - expected))
    duplicates = tuple(sorted(cell for cell in present if cells.count(cell) != 1))
    return RealCoverage(
        expected_cells=len(expected) if not unregistered else None,
        present_cells=len(cells),
        missing_cells=missing,
        extra_cells=extra,
        duplicate_cells=duplicates,
        unregistered_gameweeks=unregistered,
        complete=not (missing or extra or duplicates or unregistered),
    )


class RealPointScorecard(Sealed):
    schema_version: Literal["qualified-real-player-point-scorecard-v1"] = (
        "qualified-real-player-point-scorecard-v1"
    )
    dataset_mode: Literal["PROSPECTIVE_REAL"] = "PROSPECTIVE_REAL"
    evaluation_classification: Literal["PREREGISTERED_PROSPECTIVE", "POST_ORIGIN_DESCRIPTIVE"]
    model_id: str
    count: int = Field(ge=1)
    point_metrics: PointMetricResult
    holdout_metrics: PointMetricResult
    probability_5plus: ProbabilityMetricResult | None = None
    calibration_5plus: CalibrationResult | None = None
    distribution_metrics: tuple[DistributionMetricResult, ...] | None = None
    component_metrics: dict[str, PointMetricResult] | None = None
    forecast_hashes: tuple[Sha, ...]
    label_hashes: tuple[Sha, ...]
    information_grade: Literal["LIVE_OBSERVED", "RAW_OBSERVED"]
    full_dependency_manifest_sha256: Sha
    uncertainty: Literal["DESCRIPTIVE_CLUSTERED_GAMEWEEK_INFERENCE_NOT_COMPUTED"] = (
        "DESCRIPTIVE_CLUSTERED_GAMEWEEK_INFERENCE_NOT_COMPUTED"
    )
    unavailable_from_point_only: tuple[str, ...] = (
        "PMF_CALIBRATION",
        "START_PROBABILITY",
        "SIXTY_MINUTE_PROBABILITY",
        "GOAL_ASSIST_COMPONENTS",
        "CLEAN_SHEET_COMPONENT",
        "BONUS_DEFENSIVE_COMPONENTS",
    )
    promotion: Literal["FORBIDDEN"] = "FORBIDDEN"

    @model_validator(mode="after")
    def complete_metric_cohort(self) -> Self:
        from dmf_pulse.fpl_points.models import POINT_COMPONENT_NAMES

        if (
            self.point_metrics.count != self.count
            or self.holdout_metrics.count > self.count
            or len(self.forecast_hashes) != self.count
            or len(set(self.forecast_hashes)) != self.count
            or len(self.label_hashes) != self.count
            or len(set(self.label_hashes)) != self.count
            or any(
                row is not None and row.count != self.count
                for row in (self.probability_5plus, self.calibration_5plus)
            )
            or (
                self.distribution_metrics is not None
                and len(self.distribution_metrics) != self.count
            )
            or len(
                {
                    self.probability_5plus is None,
                    self.calibration_5plus is None,
                    self.distribution_metrics is None,
                }
            )
            != 1
            or (
                self.component_metrics is not None
                and (
                    set(self.component_metrics) != set(POINT_COMPONENT_NAMES)
                    or any(row.count != self.count for row in self.component_metrics.values())
                )
            )
        ):
            raise ValueError("scorecard diagnostics must cover the exact complete cohort")
        return self


class RealCustody(Protocol):
    def verify_protocol(self, value: RealPlayerProtocol) -> None: ...
    def verify_population(self, value: RealDeadlineRegistration) -> None: ...
    def verify_forecast(self, value: RealPointFreeze) -> None: ...


def _score_real_points(
    protocol: RealPlayerProtocol,
    registrations: tuple[RealDeadlineRegistration, ...],
    forecasts: tuple[RealPointFreeze, ...],
    labels: tuple[FinalPlayerOutcome, ...],
    *,
    model_id: str,
    custody: RealCustody,
    evaluated_at: datetime,
) -> RealPointScorecard:
    """Called only by authenticated PostgreSQL custody after complete source checks."""
    from dmf_pulse.player_lab.real_rights import (
        require_real_outcome,
        require_real_population,
        require_real_sources,
    )

    evaluated_at = MetadataTime(checked_at=evaluated_at).checked_at
    require_real_sources(protocol.sources, now=evaluated_at)
    custody.verify_protocol(protocol)
    for registration in registrations:
        require_real_population(
            registration.population.catalogue_source,
            canonical_sha256(registration.population.model_dump(mode="json")),
            now=evaluated_at,
        )
        custody.verify_population(registration)
    for frozen in forecasts:
        require_real_sources(frozen.forecast.sources, now=evaluated_at)
        custody.verify_forecast(frozen)
    for label in labels:
        if (label.source.profile_id, label.source.profile_sha256) not in {
            (row.profile_id, row.profile_sha256) for row in protocol.sources
        }:
            raise ValueError("outcome profile differs from predeclared source scope")
        require_real_outcome(label, now=evaluated_at)
        if label.usable_at > evaluated_at:
            raise ValueError("real label is not yet usable")
    coverage = real_coverage(protocol, registrations, forecasts)
    if not coverage.complete or model_id not in protocol.model_ids:
        raise ValueError("complete registered real cohort required")
    by_target = {row.key.target_id(): row for row in labels}
    target_ids = {target.target_id() for row in registrations for target in row.population.targets}
    if len(by_target) != len(labels) or set(by_target) != target_ids:
        raise ValueError("complete exact final labels required; no outcome-dependent drops")
    for week in protocol.gameweeks:
        vintage = {
            (row.revision, canonical_sha256(row.source.model_dump(mode="json")), row.finalized_at)
            for row in labels
            if row.key.gameweek == week
        }
        if len(vintage) != 1:
            raise ValueError(
                "one complete correction/source/finalization vintage per Gameweek required"
            )
    chosen = tuple(
        sorted(
            (row for row in forecasts if row.forecast.model_id == model_id),
            key=lambda row: row.forecast.key.target_id(),
        )
    )
    stage_forecasts, stage_labels = [], []
    for frozen in chosen:
        value = frozen.forecast
        label = by_target[value.key.target_id()]
        if (
            label.dataset_mode != "PROSPECTIVE_REAL"
            or label.key != value.key
            or not value.deadline_at < label.finalized_at <= value.label_finality_cutoff
        ):
            raise ValueError("real forecast/final label identity or finality differs")
        if value.stage12.dataset_mode.value != protocol.information_grade:
            raise ValueError("actual information grade differs from registered protocol")
        lineage = value.stage12.lineage.model_copy(
            update={"forecast_origin": frozen.original_frozen_at}
        )
        stage_forecasts.append(
            stage12_seal(
                value.stage12.model_copy(update={"lineage": lineage, "forecast_sha256": "0" * 64}),
                "forecast_sha256",
            )
        )
        stage_labels.append(
            stage12_seal(
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
        )
    metrics = score_frozen_point_forecasts(tuple(stage_forecasts), tuple(stage_labels))
    held = tuple(
        index
        for index, row in enumerate(chosen)
        if row.forecast.key.gameweek in protocol.holdout_gameweeks
    )
    holdout_metrics = score_frozen_point_forecasts(
        tuple(stage_forecasts[index] for index in held),
        tuple(stage_labels[index] for index in held),
    )
    full_sources = {
        canonical_sha256(source.model_dump(mode="json")): source
        for source in (
            *protocol.sources,
            *(row.population.catalogue_source for row in registrations),
            *(source for row in forecasts for source in row.forecast.sources),
            *(row.source for row in labels),
        )
    }
    probability_result = None
    calibration_result = None
    distributions = None
    components = None
    unavailable = ["EXPECTED_MINUTES_ACTUALS", "START_PROBABILITY", "SIXTY_MINUTE_PROBABILITY"]
    if all(row.forecast.stage12.pmf for row in chosen):
        probabilities = tuple(
            sum(
                (mass for points, mass in row.forecast.stage12.pmf.items() if Decimal(points) >= 5),
                Decimal(0),
            )
            for row in chosen
        )
        events = tuple(
            int(by_target[row.forecast.key.target_id()].total_points >= 5) for row in chosen
        )
        probability_result = score_probabilities(probabilities, events)
        calibration_result = calibration_intercept_slope(probabilities, events)
        distributions = tuple(
            score_distribution(
                {Decimal(key): mass for key, mass in row.forecast.stage12.pmf.items()},
                Decimal(by_target[row.forecast.key.target_id()].total_points),
            )
            for row in chosen
        )
    else:
        unavailable.append("COMPLETE_COHORT_PMF_CALIBRATION")
    originals = tuple(row.forecast.original_full_forecast for row in chosen)
    if all(row is not None for row in originals):
        from dmf_pulse.fpl_points.models import POINT_COMPONENT_NAMES

        components = {
            name: score_forecast(
                tuple(row.components[name] for row in originals if row is not None),
                tuple(
                    Decimal(by_target[row.forecast.key.target_id()].components[name])
                    for row in chosen
                ),
            )
            for name in POINT_COMPONENT_NAMES
        }
    else:
        unavailable.extend(
            ("GOAL_ASSIST_COMPONENTS", "CLEAN_SHEET_COMPONENT", "BONUS_DEFENSIVE_COMPONENTS")
        )
    return seal(
        RealPointScorecard.model_construct(
            model_id=model_id,
            evaluation_classification=protocol.evaluation_classification,
            count=len(chosen),
            point_metrics=metrics,
            holdout_metrics=holdout_metrics,
            probability_5plus=probability_result,
            calibration_5plus=calibration_result,
            distribution_metrics=distributions,
            component_metrics=components,
            unavailable_from_point_only=tuple(unavailable),
            forecast_hashes=tuple(row.semantic_sha256 for row in chosen),
            label_hashes=tuple(
                by_target[row.forecast.key.target_id()].semantic_sha256 for row in chosen
            ),
            information_grade=protocol.information_grade,
            full_dependency_manifest_sha256=canonical_sha256(
                [full_sources[key].model_dump(mode="json") for key in sorted(full_sources)]
            ),
            semantic_sha256="0" * 64,
        )
    )
