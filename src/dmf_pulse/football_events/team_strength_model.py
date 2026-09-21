"""Authenticated shadow fit, cutoff-safe historical entrant centre and uncertainty.

The model semantic identity excludes execution timestamps. A separately hashed
execution envelope binds the stable model to its real fitted/usable timestamps.
Neither reconstructed evidence nor this plug-in fit is a production model input.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BeforeValidator, Field, model_validator

from dmf_pulse.football_events.team_strength_numerics import (
    NumericalFit,
    Observation,
    StrengthFitError,
    fit_cohort_season,
    fit_strength,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    MODE,
    SEASON,
    SHA,
    FrozenEvidence,
    SealedEvidence,
    SourceLineage,
    StrengthEvidenceError,
    TeamStrengthHistoricalDatasetV1,
    authenticate,
    require_team_strength_rights,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    SourceFreshnessState,
    eligibility_not_before,
    load_historical_team_identity,
)

FAMILY = "REGULARISED_TIME_WEIGHTED_INDEPENDENT_POISSON_TEAM_STRENGTH_V1"
LIMITATIONS = (
    "PLUGIN_PREDICTION_SHADOW_ONLY",
    "PARAMETER_MIXTURE_NOT_PROPAGATED",
    "CURRENT-TEAM-STRENGTH-001U_REQUIRED_BEFORE_PRODUCTION",
)


def _decimal_only(value: object) -> Decimal:
    if not isinstance(value, (str, Decimal)):
        raise ValueError("numerical artifact values require Decimal or decimal strings")
    result = Decimal(value)
    if not result.is_finite() or not math.isfinite(float(result)):
        raise ValueError("nonfinite serialized numerical artifact")
    return result


Number = Annotated[Decimal, BeforeValidator(_decimal_only)]


def number(value: float) -> Decimal:
    """Only serialization converts binary64 to a round-trip decimal representation."""
    if not math.isfinite(value):
        raise StrengthFitError("cannot serialize a nonfinite model value")
    return Decimal(repr(value))


class InsufficientStrengthEvidence(StrengthFitError):
    """Governed evidence is incomplete; caller may select the existing league prior."""


class CohortMember(FrozenEvidence):
    season: SEASON
    team_id: UUID


class EntrantCohort(FrozenEvidence):
    algorithm: Literal["COMPLETE_EPL_SEASON_NEUTRAL_4_MATCH_UNWEIGHTED_MEAN_V1"] = (
        "COMPLETE_EPL_SEASON_NEUTRAL_4_MATCH_UNWEIGHTED_MEAN_V1"
    )
    attack_centre: Number
    defence_centre: Number
    contributors: tuple[CohortMember, ...]


def memberships() -> dict[str, frozenset[UUID]]:
    identity = load_historical_team_identity()
    return {
        season: frozenset(
            club.canonical_team_id
            for club in identity.canonical_clubs
            if season in club.season_membership
        )
        for season in identity.seasons_covered
    }


def entrants(season: str, membership: dict[str, frozenset[UUID]]) -> frozenset[UUID]:
    previous = f"{int(season[:4]) - 1}/{int(season[:4]) % 100:02d}"
    if season not in membership:
        raise InsufficientStrengthEvidence("forecast membership is unavailable")
    return membership[season] - membership[previous] if previous in membership else frozenset()


def historical_cohort(
    rows: tuple[Observation, ...],
    *,
    forecast_season: str,
    cutoff: datetime,
) -> EntrantCohort:
    """Only complete, D+2-eligible seasons strictly before the forecast season.

    Current entrants' first-season outcomes never enter their own prior centre.
    Missing/partial historical seasons cannot silently change the cohort.
    """
    membership = memberships()
    groups: dict[str, list[Observation]] = {}
    for row in rows:
        if row.season < forecast_season:
            groups.setdefault(row.season, []).append(row)
    attack, defence, contributors = [], [], []
    for season in sorted(s for s in membership if s < forecast_season):
        cohort_teams = entrants(season, membership)
        if not cohort_teams:  # 2010/11 has no prior EPL season in the governed corpus.
            continue
        eligible = tuple(groups.get(season, ()))
        expected = {(h, a) for h in membership[season] for a in membership[season] if h != a}
        if len(eligible) != len(expected) or {(row.home, row.away) for row in eligible} != expected:
            raise InsufficientStrengthEvidence(
                "entrant cohort requires complete governed prior seasons"
            )
        if any(eligibility_not_before(row.played_on) > cutoff for row in eligible):
            raise InsufficientStrengthEvidence("entrant cohort season is not available by cutoff")
        fit = fit_cohort_season(eligible, cutoff)
        for i, team in enumerate(fit.teams):
            if team in cohort_teams:
                attack.append(fit.attack[i])
                defence.append(fit.defence[i])
                contributors.append(CohortMember(season=season, team_id=team))
    if not attack:
        raise InsufficientStrengthEvidence("historical entrant cohort is unavailable")
    return EntrantCohort(
        attack_centre=number(math.fsum(attack) / len(attack)),
        defence_centre=number(math.fsum(defence) / len(defence)),
        contributors=tuple(contributors),
    )


class TeamEffect(FrozenEvidence):
    team_id: UUID
    attack: Number
    defence: Number
    is_forecast_entrant: bool


class NumericalDiagnostics(FrozenEvidence):
    convergence: Literal["CONVERGED_BOTH_CRITERIA"] = "CONVERGED_BOTH_CRITERIA"
    iterations: int = Field(ge=1, le=100)
    objective: Number
    gradient_infinity: Number = Field(ge=0, le=Decimal("1e-8"))
    relative_objective_change: Number = Field(ge=0, le=Decimal("1e-12"))
    line_search_halvings: tuple[Annotated[int, Field(ge=0, le=40)], ...]
    attack_constraint_residual: Number
    defence_constraint_residual: Number
    implementation: Literal["PYTHON_BINARY64_ANALYTIC_DAMPED_NEWTON_V1"] = (
        "PYTHON_BINARY64_ANALYTIC_DAMPED_NEWTON_V1"
    )

    @model_validator(mode="after")
    def check_residuals(self) -> Self:
        if len(self.line_search_halvings) != self.iterations or any(
            abs(x) > Decimal("1e-12")
            for x in (self.attack_constraint_residual, self.defence_constraint_residual)
        ):
            raise ValueError("invalid numerical convergence diagnostics")
        return self


class ParameterUncertainty(FrozenEvidence):
    classification: Literal["ASYMPTOTIC_LOCAL_PENALISED_V1"] = "ASYMPTOTIC_LOCAL_PENALISED_V1"
    representation: Literal["LOWER_TRIANGLE_ROW_MAJOR"] = "LOWER_TRIANGLE_ROW_MAJOR"
    parameter_order: tuple[str, ...]
    information: tuple[Number, ...]
    covariance: tuple[Number, ...]
    excludes: tuple[Literal["MODEL_FAMILY", "HYPERPARAMETER_SELECTION", "SOURCE"], ...] = (
        "MODEL_FAMILY",
        "HYPERPARAMETER_SELECTION",
        "SOURCE",
    )

    @model_validator(mode="after")
    def check_dimensions(self) -> Self:
        n = len(self.parameter_order)
        if len(self.information) != n * (n + 1) // 2 or len(self.covariance) != len(
            self.information
        ):
            raise ValueError("uncertainty dimensions disagree with parameter ordering")
        if any(
            self.information[i * (i + 1) // 2 + i] <= 0
            or self.covariance[i * (i + 1) // 2 + i] <= 0
            for i in range(n)
        ):
            raise ValueError("uncertainty diagonals must be positive")
        if self.excludes != ("MODEL_FAMILY", "HYPERPARAMETER_SELECTION", "SOURCE"):
            raise ValueError("uncertainty limitations cannot be weakened")
        return self


def parameter_order(teams: tuple[UUID, ...]) -> tuple[str, ...]:
    return (
        "mu",
        "global_home",
        *(f"attack:{t}" for t in teams[:-1]),
        *(f"defence:{t}" for t in teams[:-1]),
    )


class TeamStrengthModelStateV1(SealedEvidence):
    schema_version: Literal["team-strength-model-state-v1"] = "team-strength-model-state-v1"
    model_family: Literal["REGULARISED_TIME_WEIGHTED_INDEPENDENT_POISSON_TEAM_STRENGTH_V1"] = (
        "REGULARISED_TIME_WEIGHTED_INDEPENDENT_POISSON_TEAM_STRENGTH_V1"
    )
    policy_sha256: Literal["e8d28521fcb90b625a8dbeff4f72de3b178d16ed7cae748a7429d0e42cdd9fd7"] = (
        "e8d28521fcb90b625a8dbeff4f72de3b178d16ed7cae748a7429d0e42cdd9fd7"
    )
    identity_registry_sha256: Literal[
        "55f36445b0aabc77add11560e3ea550cbc07ec114db48dbf664e7177c65331ef"
    ] = "55f36445b0aabc77add11560e3ea550cbc07ec114db48dbf664e7177c65331ef"
    competition: Literal["English Premier League"] = "English Premier League"
    competition_id: UUID
    fixture_registry_sha256: SHA
    training_dataset_sha256: SHA
    information_cutoff: datetime
    training_cutoff: datetime
    source_usable_at: datetime
    dataset_mode: MODE
    forecast_season: SEASON
    source_finality: Literal["FULL_TIME_D_PLUS_2_ELIGIBLE"] = "FULL_TIME_D_PLUS_2_ELIGIBLE"
    freshness: Literal["FRESH"] = "FRESH"
    sources: tuple[SourceLineage, ...]
    match_count: int = Field(gt=0)
    weighted_observation_count: Number = Field(gt=0)
    seasons_represented: tuple[SEASON, ...]
    mu: Number
    global_home_effect: Number
    effects: tuple[TeamEffect, ...] = Field(min_length=2)
    entrant_cohort: EntrantCohort
    half_life_days: Literal[365] = 365
    attack_effective_prior_matches: Literal[12] = 12
    defence_effective_prior_matches: Literal[12] = 12
    penalty_mean_definition: Literal["UNWEIGHTED_TEAM_SCORE_OBSERVATION_MEAN"] = (
        "UNWEIGHTED_TEAM_SCORE_OBSERVATION_MEAN"
    )
    unweighted_mean_goals: Number = Field(gt=0)
    kappa_attack: Number = Field(gt=0)
    kappa_defence: Number = Field(gt=0)
    numerics: NumericalDiagnostics
    uncertainty: ParameterUncertainty
    status: Literal["SHADOW_NOT_MODEL_INPUT"] = "SHADOW_NOT_MODEL_INPUT"
    limitations: tuple[str, ...] = LIMITATIONS

    @model_validator(mode="after")
    def check_model(self) -> Self:
        teams = tuple(effect.team_id for effect in self.effects)
        if teams != tuple(
            sorted(set(teams))
        ) or self.uncertainty.parameter_order != parameter_order(teams):
            raise ValueError("model teams or parameter ordering are not canonical")
        membership = memberships()
        allowed = frozenset().union(
            *(clubs for season, clubs in membership.items() if season <= self.forecast_season)
        )
        if not set(teams) <= allowed or not membership.get(
            self.forecast_season, frozenset()
        ) <= set(teams):
            raise ValueError("model universe differs from governed historical/forecast clubs")
        if any(
            effect.is_forecast_entrant
            != (effect.team_id in entrants(self.forecast_season, membership))
            for effect in self.effects
        ):
            raise ValueError("entrant classifications differ from governed EPL membership")
        if (
            not self.training_cutoff <= self.information_cutoff
            or self.source_usable_at > self.information_cutoff
        ):
            raise ValueError("model cutoffs are invalid")
        if self.dataset_mode == "LIVE_OBSERVED" and self.training_cutoff != self.information_cutoff:
            raise ValueError("live model cutoffs differ")
        if not self.sources or self.source_usable_at != max(
            source.usable_at for source in self.sources
        ):
            raise ValueError("model source usable time differs")
        if any(source.usable_at > self.information_cutoff for source in self.sources):
            raise ValueError("model has post-cutoff source evidence")
        source_seasons = tuple(source.resource.season for source in self.sources)
        expected_seasons = tuple(
            sorted(season for season in membership if season <= self.forecast_season)
        )
        if (
            source_seasons != expected_seasons
            or self.seasons_represented != tuple(sorted(set(self.seasons_represented)))
            or not set(self.seasons_represented) <= set(source_seasons)
        ):
            raise ValueError("model historical seasons are incomplete or unordered")
        expected_members = tuple(
            (season, team)
            for season in expected_seasons
            if season < self.forecast_season
            for team in sorted(entrants(season, membership))
        )
        if (
            tuple((row.season, row.team_id) for row in self.entrant_cohort.contributors)
            != expected_members
        ):
            raise ValueError("entrant cohort provenance differs from complete past seasons")
        if (
            abs(float(self.kappa_attack) - 12 * float(self.unweighted_mean_goals)) > 1e-12
            or self.kappa_defence != self.kappa_attack
        ):
            raise ValueError("penalty scale differs from the locked unweighted research definition")
        if any(
            abs(math.fsum(float(getattr(effect, name)) for effect in self.effects)) > 1e-12
            for name in ("attack", "defence")
        ):
            raise ValueError("model structural sum-to-zero identification failed")
        if (
            self.weighted_observation_count > 2 * self.match_count
            or self.limitations != LIMITATIONS
        ):
            raise ValueError("model training weight or limitations are invalid")
        return self


class TeamStrengthModelArtifactV1(SealedEvidence):
    """Execution envelope: its hash is distinct from the stable model state hash."""

    schema_version: Literal["team-strength-model-artifact-v1"] = "team-strength-model-artifact-v1"
    model: TeamStrengthModelStateV1
    fitted_at: datetime
    usable_at: datetime

    @model_validator(mode="after")
    def check_execution_times(self) -> Self:
        if not self.model.information_cutoff <= self.fitted_at <= self.usable_at:
            raise ValueError("model execution envelope predates its information cutoff")
        return self


def dataset_observations(dataset: TeamStrengthHistoricalDatasetV1) -> tuple[Observation, ...]:
    result = []
    for match in dataset.matches:
        row = match.observation
        if row.home_goals is None or row.away_goals is None:
            raise StrengthEvidenceError("eligible dataset row lacks full-time goals")
        result.append(
            Observation(
                row.fixture.fixture_id,
                row.fixture.season,
                row.source_match_date,
                row.fixture.home_team_id,
                row.fixture.away_team_id,
                row.home_goals,
                row.away_goals,
            )
        )
    return tuple(result)


def _model_state(
    dataset: TeamStrengthHistoricalDatasetV1,
    fit: NumericalFit,
    cohort: EntrantCohort,
    current_entrants: frozenset[UUID],
) -> TeamStrengthModelStateV1:
    return seal(
        TeamStrengthModelStateV1,
        competition_id=dataset.competition_id,
        fixture_registry_sha256=dataset.fixture_registry.semantic_sha256,
        training_dataset_sha256=dataset.semantic_sha256,
        information_cutoff=dataset.information_cutoff,
        training_cutoff=dataset.training_cutoff,
        source_usable_at=max(source.lineage.usable_at for source in dataset.sources),
        dataset_mode=dataset.dataset_mode,
        forecast_season=dataset.forecast_season,
        sources=tuple(source.lineage for source in dataset.sources),
        match_count=len(dataset.matches),
        weighted_observation_count=number(fit.weighted_observations),
        seasons_represented=tuple(
            sorted({row.observation.fixture.season for row in dataset.matches})
        ),
        mu=number(fit.beta[0]),
        global_home_effect=number(fit.beta[1]),
        effects=tuple(
            TeamEffect(
                team_id=team,
                attack=number(fit.attack[i]),
                defence=number(fit.defence[i]),
                is_forecast_entrant=team in current_entrants,
            )
            for i, team in enumerate(fit.teams)
        ),
        entrant_cohort=cohort,
        unweighted_mean_goals=number(fit.mean_goal),
        kappa_attack=number(fit.kappa),
        kappa_defence=number(fit.kappa),
        numerics=NumericalDiagnostics(
            iterations=fit.iterations,
            objective=number(fit.objective),
            gradient_infinity=number(fit.gradient_infinity),
            relative_objective_change=number(fit.relative_objective_change),
            line_search_halvings=fit.line_search_halvings,
            attack_constraint_residual=number(math.fsum(fit.attack)),
            defence_constraint_residual=number(math.fsum(fit.defence)),
        ),
        uncertainty=ParameterUncertainty(
            parameter_order=parameter_order(fit.teams),
            information=tuple(
                number(fit.information[i][j]) for i in range(len(fit.beta)) for j in range(i + 1)
            ),
            covariance=tuple(
                number(fit.covariance[i][j]) for i in range(len(fit.beta)) for j in range(i + 1)
            ),
        ),
    )


def fit_team_strength(
    dataset: TeamStrengthHistoricalDatasetV1, *, clock: Callable[[], datetime] | None = None
) -> TeamStrengthModelArtifactV1:
    require_team_strength_rights()
    dataset = authenticate(dataset)
    if dataset.freshness is not SourceFreshnessState.FRESH:
        raise InsufficientStrengthEvidence("fresh source required for a new model artifact")
    membership = memberships()
    expected = tuple(sorted(season for season in membership if season <= dataset.forecast_season))
    if tuple(source.lineage.resource.season for source in dataset.sources) != expected:
        raise InsufficientStrengthEvidence("model training requires the full corpus from 2010/11")
    for season in expected:
        fixtures = [row for row in dataset.fixture_registry.fixtures if row.season == season]
        pairs = {(row.home_team_id, row.away_team_id) for row in fixtures}
        if pairs != {(h, a) for h in membership[season] for a in membership[season] if h != a}:
            raise InsufficientStrengthEvidence("governed EPL schedule is incomplete")
    observations = dataset_observations(dataset)
    cohort = historical_cohort(
        observations, forecast_season=dataset.forecast_season, cutoff=dataset.training_cutoff
    )
    current_entrants = entrants(dataset.forecast_season, membership)
    teams = tuple(
        sorted(
            {team for row in observations for team in (row.home, row.away)}
            | membership[dataset.forecast_season]
        )
    )
    centres = {
        team: (float(cohort.attack_centre), float(cohort.defence_centre))
        for team in current_entrants
    }
    fit = fit_strength(
        observations,
        teams=teams,
        cutoff=dataset.training_cutoff,
        centres=centres,
        cold_entrants=current_entrants,
    )
    state = _model_state(dataset, fit, cohort, current_entrants)
    now = clock or (lambda: datetime.now(UTC))
    return seal(TeamStrengthModelArtifactV1, model=state, fitted_at=now(), usable_at=now())
