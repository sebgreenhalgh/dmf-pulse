"""Predeclared paired reports, cohort-block uncertainty and calibrated populations."""

from __future__ import annotations

import hashlib
from decimal import Decimal, localcontext
from statistics import median
from typing import Literal
from uuid import UUID

from dmf_pulse.evaluation.team_strength_campaign import verify_score_evidence
from dmf_pulse.evaluation.team_strength_prospective import (
    PublicCalibrationDiagnostic,
    PublicProspectiveScoreV1,
    PublicTeamStrengthForecastV1,
    prospective_calibration,
)
from dmf_pulse.evaluation.team_strength_protocol import (
    PRODUCTS,
    CampaignLedgerV1,
    CohortAssignment,
    InferencePolicy,
    ProspectiveProtocolV1,
)
from dmf_pulse.football_events.team_strength_model import Number
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FrozenEvidence,
    ParsedSnapshot,
    SealedEvidence,
    StrengthEvidenceError,
    authenticate,
    seal,
)


class PairedCohort(FrozenEvidence):
    cohort_id: str
    fixture_ids: tuple[UUID, ...]
    differences: tuple[Number, ...]


def paired_differences(
    score: PublicProspectiveScoreV1, *, challenger: str, baseline: str, metric: str
) -> tuple[tuple[UUID, Decimal], ...]:
    score = authenticate(score)
    left = {
        fixture: dict(values)[metric]
        for fixture, product, values in score.scores
        if product == challenger
    }
    right = {
        fixture: dict(values)[metric]
        for fixture, product, values in score.scores
        if product == baseline
    }
    if not left or set(left) != set(right):
        raise StrengthEvidenceError("unmatched comparison; identical paired fixture IDs required")
    with localcontext() as context:
        context.prec = 60
        return tuple((fixture, left[fixture] - right[fixture]) for fixture in sorted(left))


class PrimaryInference(FrozenEvidence):
    status: Literal[
        "DESCRIPTIVE_COHORT_BLOCK_INTERVAL", "INSUFFICIENT_PROSPECTIVE_COHORTS_FOR_STABLE_INFERENCE"
    ]
    n_fixtures: int
    n_cohorts: int
    paired_mean_difference: Number
    lower_95: Number | None
    upper_95: Number | None
    method: Literal["PAIRED_WHOLE_COHORT_BLOCK_BOOTSTRAP_SHA256_V1"] = (
        "PAIRED_WHOLE_COHORT_BLOCK_BOOTSTRAP_SHA256_V1"
    )
    independent_fixture_assumption: Literal[False] = False
    promotion_decision: Literal[False] = False


def primary_inference(
    cohorts: tuple[PairedCohort, ...], *, policy: InferencePolicy, population_identity: str
) -> PrimaryInference:
    if not cohorts or len({row.cohort_id for row in cohorts}) != len(cohorts):
        raise StrengthEvidenceError("inference requires distinct nonempty complete cohorts")
    used: set[UUID] = set()
    for row in cohorts:
        if (
            not row.differences
            or len(row.differences) != len(row.fixture_ids)
            or len(set(row.fixture_ids)) != len(row.fixture_ids)
            or used & set(row.fixture_ids)
        ):
            raise StrengthEvidenceError("inference fixture assignments overlap or do not match")
        used.update(row.fixture_ids)
    cohorts = tuple(sorted(cohorts, key=lambda row: int(row.cohort_id[1:])))
    with localcontext() as context:
        context.prec = 60
        sums = tuple(sum(row.differences, Decimal(0)) for row in cohorts)
        counts = tuple(len(row.differences) for row in cohorts)
        n = sum(counts)
        mean = sum(sums, Decimal(0)) / n
        if len(cohorts) < policy.minimum_complete_cohorts:
            return PrimaryInference(
                status="INSUFFICIENT_PROSPECTIVE_COHORTS_FOR_STABLE_INFERENCE",
                n_fixtures=n,
                n_cohorts=len(cohorts),
                paired_mean_difference=mean,
                lower_95=None,
                upper_95=None,
            )
        values = []
        for iteration in range(policy.resamples):
            indexes = tuple(
                int.from_bytes(
                    hashlib.sha256(
                        f"{policy.seed_domain}:{population_identity}:{iteration}:{block}".encode()
                    ).digest(),
                    "big",
                )
                % len(cohorts)
                for block in range(len(cohorts))
            )
            values.append(
                sum((sums[index] for index in indexes), Decimal(0))
                / sum(counts[index] for index in indexes)
            )
        values.sort()
        # Fixed nearest-rank quantiles; no post-result choice of interpolation.
        lower = values[(policy.resamples * 25 + 999) // 1000 - 1]
        upper = values[(policy.resamples * 975 + 999) // 1000 - 1]
        return PrimaryInference(
            status="DESCRIPTIVE_COHORT_BLOCK_INTERVAL",
            n_fixtures=n,
            n_cohorts=len(cohorts),
            paired_mean_difference=mean,
            lower_95=lower,
            upper_95=upper,
        )


class MetricSummary(FrozenEvidence):
    level: Literal["FIXTURE", "COHORT", "CAMPAIGN"]
    cohort_id: str | None
    fixture_id: UUID | None
    product: str
    metric: str
    population: str
    n_fixtures: int
    n_cohorts: int
    mean: Number
    median: Number
    cumulative_sum: Number


class CalibrationPopulation(FrozenEvidence):
    population: str
    n_fixtures: int
    n_cohorts: int
    status: Literal[
        "DIAGNOSTIC_NOT_PROMOTION", "INSUFFICIENT_PROSPECTIVE_COHORTS_FOR_STABLE_CALIBRATION"
    ]
    diagnostics: tuple[PublicCalibrationDiagnostic, ...]
    sampling_interpretation: Literal["FORECAST_ORIGIN_ROWS_NOT_INDEPENDENT_OUTCOMES"] = (
        "FORECAST_ORIGIN_ROWS_NOT_INDEPENDENT_OUTCOMES"
    )


class PopulationInference(FrozenEvidence):
    population: str
    inference: PrimaryInference


class CampaignReportV1(SealedEvidence):
    schema_version: Literal["public-team-strength-prospective-campaign-report-v1"] = (
        "public-team-strength-prospective-campaign-report-v1"
    )
    protocol_sha256: SHA
    ledger_sha256: SHA
    score_sha256s: tuple[SHA, ...]
    completed_scored_cohorts: int
    interim_review: Literal[5, 10]
    metric_summaries: tuple[MetricSummary, ...]
    inferences: tuple[PopulationInference, ...]
    calibration: tuple[CalibrationPopulation, ...]
    operational_states: tuple[tuple[str, str], ...]
    automatic_activation: Literal[False] = False
    production_active: Literal[False] = False
    promotion: Literal["SEPARATE_LATER_HUMAN_DECISION_REQUIRED"] = (
        "SEPARATE_LATER_HUMAN_DECISION_REQUIRED"
    )


def _population(assignment: CohortAssignment) -> str:
    return ":".join(
        (
            assignment.evaluation_epoch,
            assignment.dataset_mode,
            assignment.draw_policy_sha256,
            assignment.lead_time_class,
        )
    )


def _summary(
    *,
    level: Literal["FIXTURE", "COHORT", "CAMPAIGN"],
    cohort_id: str | None,
    fixture_id: UUID | None,
    product: str,
    metric: str,
    population: str,
    rows: tuple[tuple[str, Decimal], ...],
) -> MetricSummary:
    with localcontext() as context:
        context.prec = 60
        values = tuple(value for _, value in rows)
        return MetricSummary(
            level=level,
            cohort_id=cohort_id,
            fixture_id=fixture_id,
            product=product,
            metric=metric,
            population=population,
            n_fixtures=len(rows),
            n_cohorts=len({cohort for cohort, _ in rows}),
            mean=sum(values, Decimal(0)) / len(rows),
            median=median(values),
            cumulative_sum=sum(values, Decimal(0)),
        )


def _check_report(assignment: CohortAssignment, score: PublicProspectiveScoreV1) -> None:
    if (score.forecast_sha256, score.dataset_mode, score.draw_policy_sha256) != (
        assignment.forecast_sha256,
        assignment.dataset_mode,
        assignment.draw_policy_sha256,
    ):
        raise StrengthEvidenceError("report epoch/mode/draw-policy forecast mismatch")
    expected = {(fixture, product) for fixture in assignment.fixture_ids for product in PRODUCTS}
    if {(fixture, product) for fixture, product, _ in score.scores} != expected:
        raise StrengthEvidenceError("complete matched fixture/product scores required")


def review_checkpoint_count(ledger: CampaignLedgerV1) -> int:
    """Count completed standard cohorts in the active epoch, excluding the pilot."""
    ledger = authenticate(ledger)
    return sum(
        row.status == "SCORED"
        and row.assignment is not None
        and row.assignment.cohort_class == "STANDARD_PROSPECTIVE_COHORT"
        and row.assignment.evaluation_epoch == ledger.protocol.evaluation_epoch
        for row in ledger.events
    )


def campaign_report(
    *,
    ledger: CampaignLedgerV1,
    reports: tuple[PublicProspectiveScoreV1, ...],
    forecasts: tuple[PublicTeamStrengthForecastV1, ...],
    outcomes: tuple[ParsedSnapshot, ...],
) -> CampaignReportV1:
    ledger = authenticate(ledger)
    protocol: ProspectiveProtocolV1 = ledger.protocol
    scored = {row.cohort_id: row for row in ledger.events if row.status == "SCORED"}
    standard_count = review_checkpoint_count(ledger)
    if standard_count not in protocol.interim_review_policy:
        raise StrengthEvidenceError(
            "cumulative evidence is available only at predeclared 5/10-cohort reviews"
        )
    by_sha = {report.semantic_sha256: authenticate(report) for report in reports}
    if len(by_sha) != len(reports) or set(by_sha) != {row.score_sha256 for row in scored.values()}:
        raise StrengthEvidenceError(
            "campaign reports must match every completed ledger score exactly"
        )
    source_by_sha = {source.semantic_sha256: authenticate(source) for source in outcomes}
    forecast_by_sha = {forecast.semantic_sha256: authenticate(forecast) for forecast in forecasts}
    if set(source_by_sha) != {report.outcome_snapshot_sha256 for report in reports} or set(
        forecast_by_sha
    ) != {report.forecast_sha256 for report in reports}:
        raise StrengthEvidenceError("unbound subgroup outcome evidence")
    summaries: list[MetricSummary] = []
    cumulative: dict[tuple[str, str, str], list[tuple[str, Decimal]]] = {}
    populations: dict[str, list[tuple[str, CohortAssignment, PublicProspectiveScoreV1]]] = {}
    for cohort_id, event in sorted(scored.items(), key=lambda row: int(row[0][1:])):
        if event.assignment is None or event.score_sha256 is None:
            raise StrengthEvidenceError("completed event lacks assignment/score")
        assignment, report = event.assignment, by_sha[event.score_sha256]
        _check_report(assignment, report)
        verify_score_evidence(
            assignment,
            score=report,
            forecast=forecast_by_sha[report.forecast_sha256],
            outcomes=source_by_sha[report.outcome_snapshot_sha256],
        )
        population = _population(assignment)
        populations.setdefault(population, []).append((cohort_id, assignment, report))
        local: dict[tuple[str, str, str], list[tuple[str, Decimal]]] = {}
        metrics = ("exact_score_log_loss", *protocol.secondary_metrics)
        paired = {
            "PRIMARY_PLUGIN_MINUS_BASELINE": dict(
                paired_differences(
                    report,
                    challenger=PRODUCTS[1],
                    baseline=PRODUCTS[0],
                    metric="exact_score_log_loss",
                )
            ),
        }
        records: list[tuple[UUID, str, str, Decimal]] = [
            (fixture, product, metric, dict(values)[metric])
            for fixture, product, values in report.scores
            for metric in metrics
        ]
        records.extend(
            (fixture, comparison, "exact_score_log_loss", value)
            for comparison, values in paired.items()
            for fixture, value in values.items()
        )
        proper_metrics = tuple(
            metric for metric in metrics if metric not in {"home_bias", "away_bias"}
        )
        records.extend(
            (fixture, "EXPLORATORY_MIXTURE_MINUS_PLUGIN", metric, value)
            for metric in proper_metrics
            for fixture, value in paired_differences(
                report, challenger=PRODUCTS[2], baseline=PRODUCTS[1], metric=metric
            )
        )
        for fixture, product, metric, value in records:
            labels = [population]
            promoted = assignment.promoted_team_fixture_ids
            labels.append(
                population
                + (
                    ":PROMOTED_TEAM_INVOLVEMENT"
                    if promoted is not None and fixture in promoted
                    else ":NO_PROMOTED_TEAM_INVOLVEMENT"
                    if promoted is not None
                    else ":PROMOTED_SUBGROUP_NOT_AVAILABLE"
                )
            )
            source = source_by_sha.get(report.outcome_snapshot_sha256)
            match = (
                next((row for row in source.matches if row.fixture.fixture_id == fixture), None)
                if source is not None
                else None
            )
            if match is not None:
                original = assignment.scheduled_dates[assignment.fixture_ids.index(fixture)]
                labels.append(
                    population
                    + (
                        ":DATE_UNCHANGED"
                        if match.source_match_date == original
                        else ":DATE_CHANGED_AFTER_FREEZE"
                    )
                )
            else:
                labels.append(population + ":DATE_MOVE_SUBGROUP_NOT_AVAILABLE")
            for label in labels:
                summaries.append(
                    _summary(
                        level="FIXTURE",
                        cohort_id=cohort_id,
                        fixture_id=fixture,
                        product=product,
                        metric=metric,
                        population=label,
                        rows=((cohort_id, value),),
                    )
                )
                local.setdefault((label, product, metric), []).append((cohort_id, value))
                cumulative.setdefault((label, product, metric), []).append((cohort_id, value))
        for (label, product, metric), values in sorted(local.items()):
            summaries.append(
                _summary(
                    level="COHORT",
                    cohort_id=cohort_id,
                    fixture_id=None,
                    product=product,
                    metric=metric,
                    population=label,
                    rows=tuple(values),
                )
            )
    for (label, product, metric), values in sorted(cumulative.items()):
        summaries.append(
            _summary(
                level="CAMPAIGN",
                cohort_id=None,
                fixture_id=None,
                product=product,
                metric=metric,
                population=label,
                rows=tuple(values),
            )
        )
    intervals, calibration = [], []
    for population, items in sorted(populations.items()):
        paired_cohorts = tuple(
            PairedCohort(
                cohort_id=cohort_id,
                fixture_ids=assignment.fixture_ids,
                differences=tuple(
                    value
                    for _, value in paired_differences(
                        report,
                        challenger=PRODUCTS[1],
                        baseline=PRODUCTS[0],
                        metric="exact_score_log_loss",
                    )
                ),
            )
            for cohort_id, assignment, report in items
        )
        intervals.append(
            PopulationInference(
                population=population,
                inference=primary_inference(
                    paired_cohorts,
                    policy=protocol.inference_policy,
                    population_identity=protocol.semantic_sha256 + ":" + population,
                ),
            )
        )
        small = len(items) < protocol.inference_policy.minimum_complete_cohorts
        calibration.append(
            CalibrationPopulation(
                population=population,
                n_fixtures=sum(len(assignment.fixture_ids) for _, assignment, _ in items),
                n_cohorts=len(items),
                status="INSUFFICIENT_PROSPECTIVE_COHORTS_FOR_STABLE_CALIBRATION"
                if small
                else "DIAGNOSTIC_NOT_PROMOTION",
                diagnostics=()
                if small
                else prospective_calibration(tuple(report for _, _, report in items)),
            )
        )
    latest = {row.cohort_id: row.status for row in ledger.events}
    return seal(
        CampaignReportV1,
        protocol_sha256=protocol.semantic_sha256,
        ledger_sha256=ledger.semantic_sha256,
        score_sha256s=tuple(sorted(by_sha)),
        completed_scored_cohorts=len(scored),
        interim_review=standard_count,
        metric_summaries=tuple(summaries),
        inferences=tuple(intervals),
        calibration=tuple(calibration),
        operational_states=tuple(sorted(latest.items(), key=lambda row: int(row[0][1:]))),
    )
