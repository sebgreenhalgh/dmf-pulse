"""Explicit shadow fixture boundary, governed preparation and local uncertainty.

There is no import/registration into private-v1 or ordinary recommendation paths.
The existing ScorePriorRequest and Stage-8 mathematics remain unchanged.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from functools import lru_cache
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from dmf_pulse.football_events.score_prior_request import ScorePriorRequest
from dmf_pulse.football_events.team_strength_model import (
    InsufficientStrengthEvidence,
    Number,
    TeamStrengthModelArtifactV1,
    fit_team_strength,
    memberships,
    number,
)
from dmf_pulse.football_events.team_strength_numerics import StrengthFitError, _features
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    MODE,
    SEASON,
    SHA,
    FixtureRegistration,
    FrozenEvidence,
    SealedEvidence,
    StrengthEvidenceError,
    TeamStrengthHistoricalDatasetV1,
    authenticate,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    SourceFreshnessState,
    classify_source_freshness,
)


class TeamStrengthSourceAssessmentV1(SealedEvidence):
    """Compact authenticated current-source assessment, not a model refit."""

    dataset_sha256: SHA
    competition_id: UUID
    fixture_registry_sha256: SHA
    forecast_season: SEASON
    dataset_mode: MODE
    information_cutoff: datetime
    source_usable_at: datetime
    latest_received_at: datetime
    missing_due: int = Field(ge=0)
    status_unambiguous: bool
    freshness: SourceFreshnessState
    source_snapshot_sha256s: tuple[SHA, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_assessment(self) -> Self:
        if not self.latest_received_at <= self.source_usable_at <= self.information_cutoff:
            raise ValueError("source assessment has post-cutoff evidence")
        if self.freshness != _assessment_freshness(self, self.information_cutoff):
            raise ValueError("source assessment freshness differs from P0 state machine")
        return self


def _assessment_freshness(
    assessment: TeamStrengthSourceAssessmentV1, cutoff: datetime
) -> SourceFreshnessState:
    return classify_source_freshness(
        cutoff=cutoff,
        latest_successful_usable_retrieval=assessment.latest_received_at,
        missing_due=assessment.missing_due,
        canonical_mapping_valid=True,
        status_unambiguous=assessment.status_unambiguous,
        schema_valid=True,
        source_lineage_valid=True,
    )


def _source_assessment(dataset: TeamStrengthHistoricalDatasetV1) -> TeamStrengthSourceAssessmentV1:
    # Called only after full dataset authentication in preparation.
    return seal(
        TeamStrengthSourceAssessmentV1,
        dataset_sha256=dataset.semantic_sha256,
        competition_id=dataset.competition_id,
        fixture_registry_sha256=dataset.fixture_registry.semantic_sha256,
        forecast_season=dataset.forecast_season,
        dataset_mode=dataset.dataset_mode,
        information_cutoff=dataset.information_cutoff,
        source_usable_at=max(source.lineage.usable_at for source in dataset.sources),
        latest_received_at=max(source.lineage.received_at for source in dataset.sources),
        missing_due=dataset.missing_due,
        status_unambiguous=all(
            row.finality != "UNKNOWN_STATUS" for source in dataset.sources for row in source.matches
        ),
        freshness=dataset.freshness,
        source_snapshot_sha256s=tuple(source.semantic_sha256 for source in dataset.sources),
    )


@lru_cache(maxsize=17)
def _forecast_clubs(season: str) -> frozenset[UUID]:
    return memberships()[season]


@lru_cache(maxsize=8)
def _validated_artifact_json(payload: str) -> TeamStrengthModelArtifactV1:
    """Cache by complete immutable serialized content, including decimal spelling."""
    return TeamStrengthModelArtifactV1.model_validate_json(payload)


def _authenticated_artifact(artifact: TeamStrengthModelArtifactV1) -> TeamStrengthModelArtifactV1:
    # Never cache by a mutable model reference or equality-normalized Decimal
    # values. The private validated copy must not escape through public returns.
    return _validated_artifact_json(artifact.model_dump_json())


def _context(
    artifact: TeamStrengthModelArtifactV1,
    fixture: FixtureRegistration,
    as_of: datetime,
    expected_artifact_sha256: str,
    source_assessment: TeamStrengthSourceAssessmentV1 | None = None,
) -> tuple[
    TeamStrengthModelArtifactV1, SourceFreshnessState, TeamStrengthSourceAssessmentV1 | None
]:
    artifact = _authenticated_artifact(artifact)
    if artifact.semantic_sha256 != expected_artifact_sha256:
        raise StrengthEvidenceError("fixture adapter model identity differs from expected artifact")
    fixture = FixtureRegistration.model_validate(fixture.model_dump(mode="python"))
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise StrengthEvidenceError("fixture cutoff must be timezone-aware")
    model = artifact.model
    if model.competition_id != fixture.competition_id or model.forecast_season != fixture.season:
        raise StrengthEvidenceError("fixture competition or forecast season differs from model")
    if (
        artifact.usable_at > as_of
        or model.information_cutoff > as_of
        or model.training_cutoff > as_of
    ):
        raise StrengthEvidenceError("post-cutoff model artifact is not usable")
    if not {fixture.home_team_id, fixture.away_team_id} <= {
        effect.team_id for effect in model.effects
    }:
        raise StrengthEvidenceError("fixture club is outside governed fitted team universe")
    if not {fixture.home_team_id, fixture.away_team_id} <= _forecast_clubs(fixture.season):
        raise StrengthEvidenceError(
            "fixture club is outside governed forecast-season EPL membership"
        )
    # This assesses retrieval age only from the sealed model evidence. Due-result
    # completeness remains explicitly assessed at model.information_cutoff;
    # callers needing a new current assessment must use prepare_team_strength.
    freshness = classify_source_freshness(
        cutoff=as_of,
        latest_successful_usable_retrieval=max(source.received_at for source in model.sources),
        missing_due=0,
        canonical_mapping_valid=True,
        status_unambiguous=True,
        schema_valid=True,
        source_lineage_valid=True,
    )
    if source_assessment is not None:
        source_assessment = authenticate(source_assessment)
        if (
            source_assessment.competition_id != model.competition_id
            or source_assessment.fixture_registry_sha256 != model.fixture_registry_sha256
            or source_assessment.forecast_season != model.forecast_season
            or source_assessment.dataset_mode != model.dataset_mode
        ):
            raise StrengthEvidenceError("current source assessment and model identity differ")
        if not model.information_cutoff <= source_assessment.information_cutoff <= as_of:
            raise StrengthEvidenceError(
                "source assessment cutoff is incompatible with fixture/model"
            )
        freshness = _assessment_freshness(source_assessment, as_of)
    if freshness is SourceFreshnessState.STALE_BLOCKED:
        raise StrengthEvidenceError("sealed model source is stale; governed preparation required")
    return artifact, freshness, source_assessment


def _rates(
    artifact: TeamStrengthModelArtifactV1, fixture: FixtureRegistration
) -> tuple[float, float]:
    model = artifact.model
    effects = {row.team_id: row for row in model.effects}
    home, away = effects[fixture.home_team_id], effects[fixture.away_team_id]
    try:
        h = math.exp(
            float(model.mu)
            + float(model.global_home_effect)
            + float(home.attack)
            - float(away.defence)
        )
        a = math.exp(float(model.mu) + float(away.attack) - float(home.defence))
    except OverflowError as exc:
        raise StrengthEvidenceError("fixture model rate is nonfinite") from exc
    if any(not math.isfinite(rate) or rate <= 0 or rate > 8.0 for rate in (h, a)):
        raise StrengthEvidenceError("fixture model rate is outside (0, 8]; no clamping")
    return h, a


def _request(home: float, away: float) -> ScorePriorRequest:
    with localcontext() as context:
        context.prec = 40
        rates = tuple(
            Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)
            for value in (home, away)
        )
    if any(rate <= 0 or rate > 8 for rate in rates):
        raise StrengthEvidenceError("six-place serialized fixture rate is not strictly positive")
    return ScorePriorRequest(home_goal_rate=rates[0], away_goal_rate=rates[1])


class TeamStrengthFixtureBundleV1(SealedEvidence):
    schema_version: Literal["team-strength-fixture-bundle-v1"] = "team-strength-fixture-bundle-v1"
    fixture: FixtureRegistration
    as_of: datetime
    artifact_sha256: SHA
    model_state_sha256: SHA
    fixture_registry_sha256: SHA
    score_prior: ScorePriorRequest
    model_family: Literal["INDEPENDENT_POISSON_V1"] = "INDEPENDENT_POISSON_V1"
    source_model_family: Literal[
        "REGULARISED_TIME_WEIGHTED_INDEPENDENT_POISSON_TEAM_STRENGTH_V1"
    ] = "REGULARISED_TIME_WEIGHTED_INDEPENDENT_POISSON_TEAM_STRENGTH_V1"
    source_usable_at: datetime
    model_usable_at: datetime
    model_information_cutoff: datetime
    training_cutoff: datetime
    dataset_mode: MODE
    retrieval_freshness_at_as_of: Literal["FRESH", "DEGRADED"]
    due_completeness_assessed_at: datetime
    source_assessment: TeamStrengthSourceAssessmentV1 | None = None
    status: Literal["SHADOW_NOT_MODEL_INPUT"] = "SHADOW_NOT_MODEL_INPUT"
    warning: Literal["PLUGIN_SHADOW_ONLY", "REUSED_SEALED_MODEL_NO_CURRENT_REFIT_CLAIM"]

    @model_validator(mode="after")
    def check_bundle(self) -> Self:
        if (
            not self.training_cutoff
            <= self.model_information_cutoff
            <= self.model_usable_at
            <= self.as_of
        ):
            raise ValueError("fixture bundle contains post-cutoff model evidence")
        if (
            self.source_usable_at > self.model_information_cutoff
            or not self.model_information_cutoff <= self.due_completeness_assessed_at <= self.as_of
        ):
            raise ValueError("fixture bundle source assessment differs from model cutoff")
        expected_cutoff = (
            self.source_assessment.information_cutoff
            if self.source_assessment
            else self.model_information_cutoff
        )
        if self.due_completeness_assessed_at != expected_cutoff:
            raise ValueError("fixture bundle due-completeness assessment is not bound")
        for rate in (self.score_prior.home_goal_rate, self.score_prior.away_goal_rate):
            if rate <= 0 or rate > 8 or rate.as_tuple().exponent != -6:
                raise ValueError("fixture bundle rates require six-place decimals in (0, 8]")
        expected_warning = (
            "REUSED_SEALED_MODEL_NO_CURRENT_REFIT_CLAIM"
            if self.retrieval_freshness_at_as_of == "DEGRADED"
            else "PLUGIN_SHADOW_ONLY"
        )
        if self.warning != expected_warning:
            raise ValueError("fixture bundle must expose degraded sealed-model reuse")
        return self


def fixture_prior_bundle(
    *,
    artifact: TeamStrengthModelArtifactV1,
    fixture: FixtureRegistration,
    as_of: datetime,
    expected_artifact_sha256: str,
    source_assessment: TeamStrengthSourceAssessmentV1 | None = None,
) -> TeamStrengthFixtureBundleV1:
    artifact, freshness, source_assessment = _context(
        artifact, fixture, as_of, expected_artifact_sha256, source_assessment
    )
    home, away = _rates(artifact, fixture)
    model = artifact.model
    return seal(
        TeamStrengthFixtureBundleV1,
        fixture=fixture,
        as_of=as_of.astimezone(UTC),
        artifact_sha256=artifact.semantic_sha256,
        model_state_sha256=model.semantic_sha256,
        fixture_registry_sha256=model.fixture_registry_sha256,
        score_prior=_request(home, away),
        source_usable_at=model.source_usable_at,
        model_usable_at=artifact.usable_at,
        model_information_cutoff=model.information_cutoff,
        training_cutoff=model.training_cutoff,
        dataset_mode=model.dataset_mode,
        retrieval_freshness_at_as_of=freshness.value,
        due_completeness_assessed_at=source_assessment.information_cutoff
        if source_assessment
        else model.information_cutoff,
        source_assessment=source_assessment,
        warning="REUSED_SEALED_MODEL_NO_CURRENT_REFIT_CLAIM"
        if freshness is SourceFreshnessState.DEGRADED
        else "PLUGIN_SHADOW_ONLY",
    )


def authenticate_fixture_bundle(
    bundle: TeamStrengthFixtureBundleV1,
    *,
    artifact: TeamStrengthModelArtifactV1,
    expected_artifact_sha256: str,
) -> TeamStrengthFixtureBundleV1:
    bundle = authenticate(bundle)
    expected = fixture_prior_bundle(
        artifact=artifact,
        fixture=bundle.fixture,
        as_of=bundle.as_of,
        expected_artifact_sha256=expected_artifact_sha256,
        source_assessment=bundle.source_assessment,
    )
    if bundle != expected:
        raise StrengthEvidenceError("fixture bundle differs from authenticated model prediction")
    return bundle


class FixtureRateUncertainty(FrozenEvidence):
    classification: Literal["ASYMPTOTIC_LOCAL_PENALISED_V1"] = "ASYMPTOTIC_LOCAL_PENALISED_V1"
    log_home_rate_variance: Number
    log_away_rate_variance: Number
    log_rate_covariance: Number
    home_rate_delta_variance: Number
    away_rate_delta_variance: Number
    status: Literal["DIAGNOSTIC_ONLY_NO_PARAMETER_MIXTURE"] = "DIAGNOSTIC_ONLY_NO_PARAMETER_MIXTURE"


def fixture_rate_uncertainty(
    *,
    artifact: TeamStrengthModelArtifactV1,
    fixture: FixtureRegistration,
    as_of: datetime,
    expected_artifact_sha256: str,
    source_assessment: TeamStrengthSourceAssessmentV1 | None = None,
) -> FixtureRateUncertainty:
    artifact, _, _ = _context(artifact, fixture, as_of, expected_artifact_sha256, source_assessment)
    home, away = _rates(artifact, fixture)
    teams = tuple(row.team_id for row in artifact.model.effects)
    h, a = teams.index(fixture.home_team_id), teams.index(fixture.away_team_id)
    xh, xa = _features(len(teams), h, a, home=True), _features(len(teams), a, h, home=False)
    covariance = artifact.model.uncertainty.covariance

    def form(x: tuple[tuple[int, float], ...], y: tuple[tuple[int, float], ...]) -> float:
        return math.fsum(
            a * b * float(covariance[max(i, j) * (max(i, j) + 1) // 2 + min(i, j)])
            for i, a in x
            for j, b in y
        )

    vh, va, cross = form(xh, xh), form(xa, xa), form(xh, xa)
    if vh < 0 or va < 0:
        raise StrengthEvidenceError("local covariance yields a negative fixture variance")
    return FixtureRateUncertainty(
        log_home_rate_variance=number(vh),
        log_away_rate_variance=number(va),
        log_rate_covariance=number(cross),
        home_rate_delta_variance=number(home * home * vh),
        away_rate_delta_variance=number(away * away * va),
    )


@dataclass(frozen=True)
class TeamStrengthPreparation:
    status: Literal["TEAM_STRENGTH_PRIOR_READY", "LEAGUE_LEVEL_SUPPORT_PRIOR_FALLBACK"]
    reason: Literal[
        "FRESH_FIT",
        "DEGRADED_SEALED_REUSE",
        "SOURCE_STALE",
        "EVIDENCE_INSUFFICIENT",
        "FIT_FAILURE",
        "CURRENT_ARTIFACT_UNAVAILABLE",
    ]
    freshness: SourceFreshnessState
    artifact: TeamStrengthModelArtifactV1 | None = field(repr=False)
    warning: str
    source_assessment: TeamStrengthSourceAssessmentV1 | None = None


def prepare_team_strength(
    dataset: TeamStrengthHistoricalDatasetV1,
    *,
    latest_artifact: TeamStrengthModelArtifactV1 | None = None,
    clock: Callable[[], datetime] | None = None,
) -> TeamStrengthPreparation:
    """Return a typed choice; never calculate or silently substitute a league prior."""
    dataset = authenticate(dataset)
    assessment = _source_assessment(dataset)
    if latest_artifact is not None:
        latest_artifact = _authenticated_artifact(latest_artifact)
        if latest_artifact.usable_at > dataset.information_cutoff:
            raise StrengthEvidenceError("post-cutoff retained model cannot be reused")
        if (
            latest_artifact.model.competition_id != dataset.competition_id
            or latest_artifact.model.dataset_mode != dataset.dataset_mode
            or latest_artifact.model.fixture_registry_sha256
            != dataset.fixture_registry.semantic_sha256
        ):
            raise StrengthEvidenceError("retained model identity or evidence mode differs")
    state = dataset.freshness
    if state is SourceFreshnessState.STALE_BLOCKED:
        return TeamStrengthPreparation(
            "LEAGUE_LEVEL_SUPPORT_PRIOR_FALLBACK",
            "SOURCE_STALE",
            state,
            None,
            "No new current model; caller must govern any league-prior fallback",
            assessment,
        )
    if state is SourceFreshnessState.DEGRADED:
        if (
            latest_artifact is None
            or latest_artifact.model.forecast_season != dataset.forecast_season
        ):
            return TeamStrengthPreparation(
                "LEAGUE_LEVEL_SUPPORT_PRIOR_FALLBACK",
                "CURRENT_ARTIFACT_UNAVAILABLE",
                state,
                None,
                "No current refit and no compatible sealed artifact",
                assessment,
            )
        return TeamStrengthPreparation(
            "TEAM_STRENGTH_PRIOR_READY",
            "DEGRADED_SEALED_REUSE",
            state,
            authenticate(latest_artifact),
            "Reuse only; no current-refit claim",
            assessment,
        )
    try:
        artifact = fit_team_strength(dataset, clock=clock)
    except InsufficientStrengthEvidence:
        return TeamStrengthPreparation(
            "LEAGUE_LEVEL_SUPPORT_PRIOR_FALLBACK",
            "EVIDENCE_INSUFFICIENT",
            state,
            None,
            "Full governed training evidence is unavailable",
            assessment,
        )
    except StrengthFitError:
        return TeamStrengthPreparation(
            "LEAGUE_LEVEL_SUPPORT_PRIOR_FALLBACK",
            "FIT_FAILURE",
            state,
            None,
            "Numerical fit failed; no model artifact emitted",
            assessment,
        )
    return TeamStrengthPreparation(
        "TEAM_STRENGTH_PRIOR_READY",
        "FRESH_FIT",
        state,
        artifact,
        "Plug-in prediction remains shadow only",
        assessment,
    )
