"""Authenticated private identity bridge for the explicit 001P shadow experiment.

No provider, fitting, persistence, ordinary construction or activation lives here.
The baseline execution stays unchanged. Public UUIDv7 evidence is never relabelled
as private transient UUIDs: the exact approved FPL crosswalk binds both identities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from dmf_pulse.availability.current_model import CurrentModelFixtureMinutesInput
from dmf_pulse.availability.manual_override import ManualFixtureMinutesInput
from dmf_pulse.football_events.market_constraints import MarketConstraint
from dmf_pulse.football_events.score_prior_request import ScorePriorRequest
from dmf_pulse.football_events.team_strength_adapter import (
    TeamStrengthFixtureBundleV1,
    TeamStrengthSourceAssessmentV1,
    authenticate_fixture_bundle,
    fixture_prior_bundle,
)
from dmf_pulse.football_events.team_strength_model import TeamStrengthModelArtifactV1
from dmf_pulse.ingestion.fpl.current import CurrentFplFixture
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FixtureRegistry,
    SealedEvidence,
    StrengthEvidenceError,
    authenticate,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    SourceFreshnessState,
    classify_source_freshness,
    load_historical_team_identity,
)
from dmf_pulse.private_v1.models import PrivateFixtureScorePrior
from dmf_pulse.private_v1.rolling_models import PrivateV1RollingExecutionInput

_PRIVATE_EPL = uuid5(UUID("760aa9a3-56a8-57e7-8c3d-924141214e47"), "PL:2026/27")


@dataclass(frozen=True, slots=True)
class HorizonFixture:
    gameweek: int
    official: CurrentFplFixture
    prior: PrivateFixtureScorePrior
    constraints: tuple[MarketConstraint, ...]
    stage7: ManualFixtureMinutesInput | CurrentModelFixtureMinutesInput


def horizon_fixtures(execution: PrivateV1RollingExecutionInput) -> tuple[HorizonFixture, ...]:
    """Read the complete sealed horizon, retaining literal baseline inputs."""
    current = execution.current_execution
    official = {row.provider_fixture_id: row for row in current.current_state.fpl_input.fixtures}
    priors = {row.fixture_id: row for row in current.score_priors}
    minutes = {row.fixture_id: row for row in current.manual_minutes}
    markets = {
        row.canonical_fixture_id: row.constraint_set.constraints
        for row in current.market_constraints.fixtures
    }
    rows = [
        HorizonFixture(
            execution.horizon_gameweeks[0],
            official[row.official_fpl_fixture_id],
            priors[row.canonical_fixture_id],
            markets[row.canonical_fixture_id],
            minutes[str(row.canonical_fixture_id)],
        )
        for row in current.market_identity_view.fixtures
    ]
    rows.extend(
        HorizonFixture(
            gameweek.gameweek,
            official[row.official_fpl_fixture_id],
            row.score_prior,
            row.market_constraints,
            row.stage7,
        )
        for gameweek in execution.future_gameweeks
        for row in gameweek.fixtures
    )
    return tuple(sorted(rows, key=lambda row: (row.gameweek, str(row.prior.fixture_id))))


def _p0_club(official_id: int, season: str) -> UUID:
    matches = tuple(
        club.canonical_team_id
        for club in load_historical_team_identity().canonical_clubs
        if (external := club.current_fpl_external_identifier) is not None
        and external.provider_key == "official_fpl"
        and external.season_scope == season
        and external.external_id_text == str(official_id)
    )
    if len(matches) != 1:
        raise StrengthEvidenceError("exact season-scoped P0 club mapping is unavailable")
    return matches[0]


class PrivateTeamStrengthFixturePrior(SealedEvidence):
    """Two identity representations joined by the existing approved external IDs."""

    gameweek: int = Field(gt=0)
    official_fixture_id: int = Field(gt=0)
    official_fixture_lookup_sha256: SHA
    official_home_team_id: int = Field(gt=0)
    official_away_team_id: int = Field(gt=0)
    private_identity_map_sha256: SHA
    baseline_prior: PrivateFixtureScorePrior
    public_bundle: TeamStrengthFixtureBundleV1

    @model_validator(mode="after")
    def check_binding(self) -> Self:
        fixture = self.public_bundle.fixture
        if (
            self.baseline_prior.as_of != self.public_bundle.as_of
            or fixture.home_team_id != _p0_club(self.official_home_team_id, fixture.season)
            or fixture.away_team_id != _p0_club(self.official_away_team_id, fixture.season)
        ):
            raise ValueError("private/public oriented fixture binding differs")
        return self


class TeamStrengthShadowInput(SealedEvidence):
    schema_version: Literal["private-team-strength-shadow-input-v1"] = (
        "private-team-strength-shadow-input-v1"
    )
    baseline_execution_sha256: SHA
    artifact: TeamStrengthModelArtifactV1
    fixture_registry: FixtureRegistry
    fixtures: tuple[PrivateTeamStrengthFixturePrior, ...] = Field(min_length=1)
    status: Literal["SHADOW_NOT_MODEL_INPUT"] = "SHADOW_NOT_MODEL_INPUT"

    @model_validator(mode="after")
    def check_shadow_input(self) -> Self:
        registry = self.fixture_registry
        if registry.semantic_sha256 != self.artifact.model.fixture_registry_sha256:
            raise ValueError("shadow fixture registry differs from model")
        keys = tuple((row.gameweek, str(row.baseline_prior.fixture_id)) for row in self.fixtures)
        private_ids = tuple(row.baseline_prior.fixture_id for row in self.fixtures)
        public_ids = tuple(row.public_bundle.fixture.fixture_id for row in self.fixtures)
        if keys != tuple(sorted(set(keys))) or any(
            len(set(ids)) != len(ids) for ids in (private_ids, public_ids)
        ):
            raise ValueError("shadow fixture coverage must be canonical and bijective")
        if len({row.official_fixture_id for row in self.fixtures}) != len(self.fixtures) or any(
            len(values) != 1
            for values in (
                {row.baseline_prior.as_of for row in self.fixtures},
                {row.baseline_prior.competition_id for row in self.fixtures},
                {row.private_identity_map_sha256 for row in self.fixtures},
                {
                    row.public_bundle.source_assessment.semantic_sha256
                    if row.public_bundle.source_assessment
                    else None
                    for row in self.fixtures
                },
            )
        ):
            raise ValueError("shadow fixtures do not share one frozen source context")
        registered = {row.fixture_id: row for row in registry.fixtures}
        for row in self.fixtures:
            bundle = authenticate_fixture_bundle(
                row.public_bundle,
                artifact=self.artifact,
                expected_artifact_sha256=self.artifact.semantic_sha256,
            )
            if (
                registered.get(bundle.fixture.fixture_id) != bundle.fixture
                or registry.registered_at > bundle.as_of
                or load_historical_team_identity().decided_at > bundle.as_of
            ):
                raise ValueError("shadow mapping is absent or post-cutoff")
        return self


class TeamStrengthShadowPreparation(SealedEvidence):
    status: Literal[
        "TEAM_STRENGTH_PRIOR_READY",
        "TEAM_STRENGTH_WORLD_UNAVAILABLE",
        "TEAM_STRENGTH_COMPARISON_BLOCKED_INCOMPLETE_FIXTURE_COVERAGE",
    ]
    reason: Literal[
        "FRESH_SEALED_MODEL",
        "DEGRADED_SEALED_REUSE",
        "SOURCE_STALE",
        "CURRENT_ARTIFACT_UNAVAILABLE",
        "CURRENT_SOURCE_ASSESSMENT_UNAVAILABLE",
        "INCOMPLETE_FIXTURE_COVERAGE",
    ]
    shadow_input: TeamStrengthShadowInput | None = None

    @model_validator(mode="after")
    def check_outcome(self) -> Self:
        ready = self.status == "TEAM_STRENGTH_PRIOR_READY"
        if ready != (self.shadow_input is not None) or ready != (
            self.reason in {"FRESH_SEALED_MODEL", "DEGRADED_SEALED_REUSE"}
        ):
            raise ValueError("shadow preparation status and content disagree")
        if (self.reason == "INCOMPLETE_FIXTURE_COVERAGE") != (
            self.status == "TEAM_STRENGTH_COMPARISON_BLOCKED_INCOMPLETE_FIXTURE_COVERAGE"
        ):
            raise ValueError("shadow fixture coverage blocker disagrees")
        if self.shadow_input is not None:
            expected = (
                "FRESH_SEALED_MODEL"
                if self.reason == "FRESH_SEALED_MODEL"
                else "DEGRADED_SEALED_REUSE"
            )
            for row in self.shadow_input.fixtures:
                actual = (
                    "FRESH_SEALED_MODEL"
                    if row.public_bundle.retrieval_freshness_at_as_of == "FRESH"
                    else "DEGRADED_SEALED_REUSE"
                )
                if actual != expected:
                    raise ValueError("shadow preparation freshness claim differs from bundles")
        return self


def _source_context(
    execution: PrivateV1RollingExecutionInput,
    artifact: TeamStrengthModelArtifactV1,
    registry: FixtureRegistry,
    assessment: TeamStrengthSourceAssessmentV1 | None,
) -> SourceFreshnessState:
    current = execution.current_execution
    cutoff = current.current_state.information_cutoff
    model = artifact.model
    if (
        model.forecast_season != current.current_state.season_code
        or model.competition_id != registry.competition_id
        or artifact.usable_at > cutoff
        or model.information_cutoff > cutoff
        or registry.registered_at > cutoff
        or load_historical_team_identity().decided_at > cutoff
    ):
        raise StrengthEvidenceError("shadow model season, competition or cutoff differs")
    if (
        current.retention_class != "SYNTHETIC_REPLAY_ALLOWED"
        and model.dataset_mode != "LIVE_OBSERVED"
    ):
        raise StrengthEvidenceError("reconstructed model cannot claim a current private world")
    if assessment is not None and (
        assessment.competition_id != model.competition_id
        or assessment.fixture_registry_sha256 != registry.semantic_sha256
        or assessment.forecast_season != model.forecast_season
        or assessment.dataset_mode != model.dataset_mode
        or not model.information_cutoff <= assessment.information_cutoff <= cutoff
    ):
        raise StrengthEvidenceError("shadow source assessment identity or cutoff differs")
    return classify_source_freshness(
        cutoff=cutoff,
        latest_successful_usable_retrieval=(
            assessment.latest_received_at
            if assessment
            else max(row.received_at for row in model.sources)
        ),
        missing_due=assessment.missing_due if assessment else 0,
        canonical_mapping_valid=True,
        status_unambiguous=assessment.status_unambiguous if assessment else True,
        schema_valid=True,
        source_lineage_valid=True,
    )


def prepare_team_strength_shadow(
    execution: PrivateV1RollingExecutionInput,
    *,
    artifact: TeamStrengthModelArtifactV1 | None,
    expected_artifact_sha256: str,
    fixture_registry: FixtureRegistry,
    source_assessment: TeamStrengthSourceAssessmentV1 | None = None,
) -> TeamStrengthShadowPreparation:
    """Prepare all priors or a typed unavailable result; integrity errors propagate."""
    execution = PrivateV1RollingExecutionInput.model_validate_json(execution.model_dump_json())
    registry = authenticate(fixture_registry)
    assessment = authenticate(source_assessment) if source_assessment is not None else None
    if artifact is None:
        return seal(
            TeamStrengthShadowPreparation,
            status="TEAM_STRENGTH_WORLD_UNAVAILABLE",
            reason="CURRENT_ARTIFACT_UNAVAILABLE",
        )
    artifact = authenticate(artifact, expected_artifact_sha256)
    registry = authenticate(registry, artifact.model.fixture_registry_sha256)
    freshness = _source_context(execution, artifact, registry, assessment)
    if freshness is SourceFreshnessState.STALE_BLOCKED:
        return seal(
            TeamStrengthShadowPreparation,
            status="TEAM_STRENGTH_WORLD_UNAVAILABLE",
            reason="SOURCE_STALE",
        )
    current = execution.current_execution
    cutoff = current.current_state.information_cutoff
    if artifact.model.dataset_mode == "LIVE_OBSERVED" and (
        assessment is None or assessment.information_cutoff != cutoff
    ):
        return seal(
            TeamStrengthShadowPreparation,
            status="TEAM_STRENGTH_WORLD_UNAVAILABLE",
            reason="CURRENT_SOURCE_ASSESSMENT_UNAVAILABLE",
        )
    teams = {
        row.official_fpl_team_id: row.canonical_team_id for row in current.player_identity_map.teams
    }
    lookup = {(row.season, row.home_team_id, row.away_team_id): row for row in registry.fixtures}
    bindings = []
    for row in horizon_fixtures(execution):
        home = int(row.official.home_team_identity.external_id_text)
        away = int(row.official.away_team_identity.external_id_text)
        if (
            row.prior.home_team_id != teams.get(home)
            or row.prior.away_team_id != teams.get(away)
            or row.prior.as_of != cutoff
            or (
                current.retention_class != "SYNTHETIC_REPLAY_ALLOWED"
                and row.prior.competition_id != _PRIVATE_EPL
            )
        ):
            raise StrengthEvidenceError("baseline fixture identity differs from frozen FPL mapping")
        public_fixture = lookup.get(
            (
                current.current_state.season_code,
                _p0_club(home, "2026/27"),
                _p0_club(away, "2026/27"),
            )
        )
        if public_fixture is None:
            return seal(
                TeamStrengthShadowPreparation,
                status="TEAM_STRENGTH_COMPARISON_BLOCKED_INCOMPLETE_FIXTURE_COVERAGE",
                reason="INCOMPLETE_FIXTURE_COVERAGE",
            )
        bundle = fixture_prior_bundle(
            artifact=artifact,
            fixture=public_fixture,
            as_of=cutoff,
            expected_artifact_sha256=expected_artifact_sha256,
            source_assessment=assessment,
        )
        bindings.append(
            seal(
                PrivateTeamStrengthFixturePrior,
                gameweek=row.gameweek,
                official_fixture_id=row.official.provider_fixture_id,
                official_fixture_lookup_sha256=row.official.identity.canonical_lookup_sha256,
                official_home_team_id=home,
                official_away_team_id=away,
                private_identity_map_sha256=current.player_identity_map.semantic_sha256,
                baseline_prior=row.prior,
                public_bundle=bundle,
            )
        )
    return seal(
        TeamStrengthShadowPreparation,
        status="TEAM_STRENGTH_PRIOR_READY",
        reason="FRESH_SEALED_MODEL"
        if freshness is SourceFreshnessState.FRESH
        else "DEGRADED_SEALED_REUSE",
        shadow_input=seal(
            TeamStrengthShadowInput,
            baseline_execution_sha256=execution.semantic_sha256,
            artifact=artifact,
            fixture_registry=registry,
            fixtures=tuple(bindings),
        ),
    )


@dataclass(frozen=True, slots=True)
class _TeamStrengthShadowResolver:
    """Private-only resolver; never attached by an ordinary service factory."""

    shadow: TeamStrengthShadowInput
    _expected_sha256: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        checked = authenticate(self.shadow)
        object.__setattr__(self, "shadow", checked)
        object.__setattr__(self, "_expected_sha256", checked.semantic_sha256)

    @property
    def input_sha256(self) -> str:
        return self._expected_sha256

    def validate_execution(self, execution: PrivateV1RollingExecutionInput) -> None:
        checked = authenticate(self.shadow, self._expected_sha256)
        if checked.baseline_execution_sha256 != execution.semantic_sha256:
            raise StrengthEvidenceError("shadow resolver belongs to a different frozen execution")
        assessment = checked.fixtures[0].public_bundle.source_assessment
        rebuilt = prepare_team_strength_shadow(
            execution,
            artifact=checked.artifact,
            expected_artifact_sha256=checked.artifact.semantic_sha256,
            fixture_registry=checked.fixture_registry,
            source_assessment=assessment,
        )
        if rebuilt.shadow_input != checked:
            raise StrengthEvidenceError("shadow input does not cover the exact frozen horizon")

    def resolve(self, prior: PrivateFixtureScorePrior, gameweek: int) -> ScorePriorRequest:
        checked = authenticate(self.shadow, self._expected_sha256)
        rows = tuple(
            row
            for row in checked.fixtures
            if row.gameweek == gameweek and row.baseline_prior == prior
        )
        if len(rows) != 1:
            raise StrengthEvidenceError("shadow resolver fixture identity or coverage differs")
        # Reauthenticate at use; a caller cannot alter nested Pydantic objects
        # between whole-input verification and projection.
        row = authenticate(rows[0])
        return authenticate_fixture_bundle(
            row.public_bundle,
            artifact=self.shadow.artifact,
            expected_artifact_sha256=self.shadow.artifact.semantic_sha256,
        ).score_prior
