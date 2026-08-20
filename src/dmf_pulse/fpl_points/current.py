"""Transient current-fixture handoff from accepted Stages 6-8 to Stage 9.

The adapter does not estimate a missing current-season prior.  It requires an
immutable, governance-accepted score/player-allocation artifact and binds it
to the exact reviewed FPL fixtures, Stage-6 markets and Stage-7 paths.  Official
FPL material and all combined derivatives remain in memory.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from math import isclose
from typing import Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability import CurrentAvailabilityBundle
from dmf_pulse.availability.current import CurrentTeamAvailabilityProjection
from dmf_pulse.football_events import (
    JointScoreDistribution,
    MarketConstraint,
    ScoreDistributionRequest,
    ScoreDistributionService,
    Stage7MinutesContext,
    assert_score_coherence,
    combine_market_constraint_sets,
    constraints_from_market_consensus,
    constraints_from_totals_consensus,
    load_score_baseline_policy,
)
from dmf_pulse.football_events.service import ScoreDistributionError, ScorePriorRequest
from dmf_pulse.fpl_points.allocation import (
    validate_assist_share_constraints,
    validate_goal_share_simplex,
)
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import (
    EventAllocationConfig,
    ParticipationScenario,
    PlayerAllocationProfile,
)
from dmf_pulse.fpl_points.seed import rng_for, stable_identifier
from dmf_pulse.fpl_points.upstream import build_participation_scenario
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplFixture
from dmf_pulse.markets.current import CurrentFixtureMarketConsensus
from dmf_pulse.markets.models import MarketConsensus

CURRENT_FOOTBALL_EVENT_ADAPTER_VERSION = "gw1-current-football-events-stage8-v2"
_IDENTITY_NAMESPACE = UUID("891aa5e8-08d5-56ee-aab4-8fc547d10f77")
_PARTICIPATION_SCENARIO_COUNT = 256


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


def _uuid(kind: str, *parts: object) -> UUID:
    material = "\x1f".join(
        (CURRENT_FOOTBALL_EVENT_ADAPTER_VERSION, kind, *(str(part) for part in parts))
    )
    return uuid5(_IDENTITY_NAMESPACE, material)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class CurrentFootballEventReviewFixture(_FrozenModel):
    official_fpl_fixture_id: int = Field(gt=0)
    transient_fixture_id: UUID
    transient_home_team_id: UUID
    transient_away_team_id: UUID
    kickoff_at: datetime
    source_market_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_market_consensus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_home_availability_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_away_availability_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_home_minutes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_away_minutes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_home_player_ids: tuple[UUID, ...] = Field(min_length=11)
    expected_away_player_ids: tuple[UUID, ...] = Field(min_length=11)

    @model_validator(mode="after")
    def validate_fixture_review(self) -> CurrentFootballEventReviewFixture:
        home = self.expected_home_player_ids
        away = self.expected_away_player_ids
        if (
            self.transient_home_team_id == self.transient_away_team_id
            or tuple(sorted(set(home), key=str)) != home
            or tuple(sorted(set(away), key=str)) != away
            or set(home) & set(away)
        ):
            raise ValueError("current event-review fixture identity is inconsistent")
        return self


class CurrentFootballEventReviewTemplate(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_FOOTBALL_EVENT_REVIEW"] = "GW1_CURRENT_FOOTBALL_EVENT_REVIEW"
    status: Literal["ACCEPTED_PRIOR_ARTIFACT_REQUIRED"] = "ACCEPTED_PRIOR_ARTIFACT_REQUIRED"
    disclosure_mode: Literal["PRIVATE_TRANSIENT_OPERATOR_REVIEW"] = (
        "PRIVATE_TRANSIENT_OPERATOR_REVIEW"
    )
    generated_at: datetime
    information_cutoff: datetime
    source_availability_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixtures: tuple[CurrentFootballEventReviewFixture, ...] = Field(min_length=1)
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_review_template(self) -> CurrentFootballEventReviewTemplate:
        fixture_ids = [row.official_fpl_fixture_id for row in self.fixtures]
        if (
            fixture_ids != sorted(fixture_ids)
            or len(fixture_ids) != len(set(fixture_ids))
            or self.generated_at > self.information_cutoff
            or self.template_sha256 != _template_sha256(self)
        ):
            raise ValueError("current football-event review template is inconsistent")
        return self


def _template_sha256(value: CurrentFootballEventReviewTemplate) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"template_sha256"}))


class CurrentFixtureEventPrior(_FrozenModel):
    official_fpl_fixture_id: int = Field(gt=0)
    transient_fixture_id: UUID
    transient_home_team_id: UUID
    transient_away_team_id: UUID
    score_prior: ScorePriorRequest
    allocation_profiles: tuple[PlayerAllocationProfile, ...] = Field(min_length=22)

    @model_validator(mode="after")
    def validate_fixture_prior(self) -> CurrentFixtureEventPrior:
        ids = [row.player_id for row in self.allocation_profiles]
        if self.transient_home_team_id == self.transient_away_team_id:
            raise ValueError("current fixture prior teams must be distinct")
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("allocation profiles must be unique and sorted by player_id")
        valid_teams = {str(self.transient_home_team_id), str(self.transient_away_team_id)}
        if any(row.team_id not in valid_teams for row in self.allocation_profiles):
            raise ValueError("allocation profile belongs to neither fixture team")
        try:
            for team_id in sorted(valid_teams):
                validate_goal_share_simplex(self.allocation_profiles, team_id)
                validate_assist_share_constraints(self.allocation_profiles, team_id)
        except FplPointsError as exc:
            raise ValueError("allocation profile shares are invalid") from exc
        return self


class CurrentFootballEventPriorArtifact(_FrozenModel):
    """Externally produced and governance-accepted current modelling input."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_FOOTBALL_EVENT_PRIOR_ARTIFACT"] = (
        "GW1_CURRENT_FOOTBALL_EVENT_PRIOR_ARTIFACT"
    )
    evidence_class: Literal["ACCEPTED_MODEL_ARTIFACT"] = "ACCEPTED_MODEL_ARTIFACT"
    acceptance_status: Literal["ACCEPTED"] = "ACCEPTED"
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_eligible: Literal[False] = False
    source_model_key: str = Field(min_length=1, max_length=200)
    source_model_version: str = Field(min_length=1, max_length=200)
    source_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_locator: str = Field(min_length=1, max_length=1000)
    acceptance_reference: str = Field(min_length=1, max_length=1000)
    accepted_by: str = Field(min_length=1, max_length=200)
    information_cutoff: datetime
    produced_at: datetime
    accepted_at: datetime
    expires_at: datetime
    allocation_config: EventAllocationConfig
    fixtures: tuple[CurrentFixtureEventPrior, ...] = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_prior_artifact(self) -> CurrentFootballEventPriorArtifact:
        fixture_ids = [row.official_fpl_fixture_id for row in self.fixtures]
        if (
            fixture_ids != sorted(fixture_ids)
            or len(fixture_ids) != len(set(fixture_ids))
            or not self.information_cutoff <= self.produced_at <= self.accepted_at
            or self.accepted_at > self.expires_at
            or self.allocation_config.source_tag != "TEMP-EVT-002"
            or self.allocation_config.auxiliary_source_tag != "TEMP-PTS-001"
            or self.artifact_sha256 != _artifact_sha256(self)
        ):
            raise ValueError("current football-event prior artifact is inconsistent")
        return self


def _artifact_sha256(value: CurrentFootballEventPriorArtifact) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"artifact_sha256"}))


class CurrentFootballEventApproval(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_FOOTBALL_EVENT_APPROVAL"] = "GW1_CURRENT_FOOTBALL_EVENT_APPROVAL"
    reviewer: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    reviewed_all_fixtures: Literal[True]
    accepted_model_artifact_confirmed: Literal[True]
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prior_artifact: CurrentFootballEventPriorArtifact
    confirmed_prior_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CurrentFixtureEventInputs(_FrozenModel):
    """Exact coherent material needed to construct one Stage-9 request."""

    official_fpl_fixture_id: int = Field(gt=0)
    transient_fixture_id: UUID
    gameweek_id: UUID
    transient_home_team_id: UUID
    transient_away_team_id: UUID
    fixture_readiness: Literal["SCHEDULED"] = "SCHEDULED"
    score_distribution: JointScoreDistribution
    participation_scenarios: tuple[ParticipationScenario, ...] = Field(
        min_length=_PARTICIPATION_SCENARIO_COUNT,
        max_length=_PARTICIPATION_SCENARIO_COUNT,
    )
    allocation_profiles: tuple[PlayerAllocationProfile, ...] = Field(min_length=22)
    allocation_config: EventAllocationConfig
    source_market_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_home_availability_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_away_availability_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_prior_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_allocation_status: Literal["STAGE9_REQUEST_READY_NOT_EXECUTED"] = (
        "STAGE9_REQUEST_READY_NOT_EXECUTED"
    )
    limitations: tuple[
        Literal[
            "STAGE7_CURRENT_ROSTER_COLD_START",
            "STAGE7_SYNTHETIC_TEST_REPLAY_TRAINING_EVIDENCE",
            "CURRENT_EVENT_PRIOR_EXTERNALLY_ACCEPTED_NON_PRODUCTION",
            "STAGE7_BENCH_90_MASS_CONDITIONED_TO_STAGE9_INTERVAL_SUPPORT",
            "PLAYER_EVENTS_ALLOCATED_ONLY_INSIDE_ACCEPTED_STAGE9",
        ],
        ...,
    ]
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_fixture_inputs(self) -> CurrentFixtureEventInputs:
        scenario_ids = [row.scenario_id for row in self.participation_scenarios]
        players = {row.player_id for row in self.allocation_profiles}
        profile_teams = {row.player_id: row.team_id for row in self.allocation_profiles}
        participant_teams = {
            row.player_id: row.team_id for row in self.participation_scenarios[0].participants
        }
        if (
            self.score_distribution.fixture_id != str(self.transient_fixture_id)
            or self.score_distribution.home_team_id != str(self.transient_home_team_id)
            or self.score_distribution.away_team_id != str(self.transient_away_team_id)
            or len(scenario_ids) != len(set(scenario_ids))
            or len(profile_teams) != len(self.allocation_profiles)
            or profile_teams != participant_teams
            or not isclose(
                sum(row.probability for row in self.participation_scenarios),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-10,
            )
            or any(
                row.fixture_id != str(self.transient_fixture_id)
                or row.gameweek_id != str(self.gameweek_id)
                or row.home_team_id != str(self.transient_home_team_id)
                or row.away_team_id != str(self.transient_away_team_id)
                or {participant.player_id for participant in row.participants} != players
                for row in self.participation_scenarios
            )
            or self.result_sha256 != _fixture_inputs_sha256(self)
        ):
            raise ValueError("current fixture event inputs are inconsistent")
        try:
            assert_score_coherence(self.score_distribution)
        except ValueError as exc:
            raise ValueError("current Stage-8 score distribution is incoherent") from exc
        return self


def _fixture_inputs_sha256(value: CurrentFixtureEventInputs) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"result_sha256"}))


class CurrentFootballEventSummary(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["READY_FOR_STAGE9_WITH_MATERIAL_LIMITATIONS"] = (
        "READY_FOR_STAGE9_WITH_MATERIAL_LIMITATIONS"
    )
    contract: Literal["GW1_CURRENT_FOOTBALL_EVENT_DISTRIBUTIONS"] = (
        "GW1_CURRENT_FOOTBALL_EVENT_DISTRIBUTIONS"
    )
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    decision_information_at: datetime
    fixture_count: int = Field(gt=0)
    participation_scenario_count: int = Field(gt=0)
    allocation_profile_count: int = Field(gt=0)
    stage8_confidence_grades: dict[str, int]
    event_allocation_status: Literal["STAGE9_REQUEST_READY_NOT_EXECUTED"] = (
        "STAGE9_REQUEST_READY_NOT_EXECUTED"
    )
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    production_calibration_claim: Literal[False] = False
    source_availability_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_prior_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage8_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    next_checkpoint: Literal["2.4_FPL_POINTS_DISTRIBUTIONS"] = "2.4_FPL_POINTS_DISTRIBUTIONS"


class CurrentFootballEventBundle(_FrozenModel):
    """Hash-bound transient Stage-8 result and exact Stage-9 handoff."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_FOOTBALL_EVENT_DISTRIBUTIONS"] = (
        "GW1_CURRENT_FOOTBALL_EVENT_DISTRIBUTIONS"
    )
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    fpl_raw_storage: Literal["DENY"] = "DENY"
    fpl_derived_storage: Literal["DENY"] = "DENY"
    production_calibration_claim: Literal[False] = False
    decision_information_at: datetime
    adapter_version: Literal["gw1-current-football-events-stage8-v2"] = (
        "gw1-current-football-events-stage8-v2"
    )
    stage8_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_availability_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_availability: CurrentAvailabilityBundle
    review_template: CurrentFootballEventReviewTemplate
    approval: CurrentFootballEventApproval
    fixtures: tuple[CurrentFixtureEventInputs, ...] = Field(min_length=1)
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_bundle(self) -> CurrentFootballEventBundle:
        source = _revalidate_availability(self.source_availability)
        template = _build_review_template(source)
        approval = _revalidate_approval(self.approval)
        _validate_approval(source, template, approval)
        expected = _build_fixture_inputs(source, approval)
        policy_sha256 = load_score_baseline_policy().sha256
        if (
            source != self.source_availability
            or template != self.review_template
            or approval != self.approval
            or self.decision_information_at != approval.approved_at
            or self.stage8_policy_sha256 != policy_sha256
            or self.source_availability_semantic_sha256 != source.semantic_sha256
            or self.fixtures != expected
            or self.semantic_sha256 != _bundle_sha256(self)
        ):
            raise ValueError("current football-event bundle lineage is inconsistent")
        return self

    def safe_summary(self) -> CurrentFootballEventSummary:
        grades = Counter(row.score_distribution.confidence_grade for row in self.fixtures)
        return CurrentFootballEventSummary(
            decision_information_at=self.decision_information_at,
            fixture_count=len(self.fixtures),
            participation_scenario_count=sum(
                len(row.participation_scenarios) for row in self.fixtures
            ),
            allocation_profile_count=sum(len(row.allocation_profiles) for row in self.fixtures),
            stage8_confidence_grades=dict(sorted(grades.items())),
            source_availability_semantic_sha256=self.source_availability_semantic_sha256,
            source_prior_artifact_sha256=self.approval.prior_artifact.artifact_sha256,
            stage8_policy_sha256=self.stage8_policy_sha256,
            semantic_sha256=self.semantic_sha256,
        )


def _revalidate_availability(value: CurrentAvailabilityBundle) -> CurrentAvailabilityBundle:
    try:
        return CurrentAvailabilityBundle.model_validate_json(value.model_dump_json())
    except (ValueError, IngestionError) as exc:
        raise IngestionError(
            "SOURCE_LINEAGE_INVALID",
            "Checkpoint-2.2 availability input failed independent revalidation",
        ) from exc


def _revalidate_approval(value: CurrentFootballEventApproval) -> CurrentFootballEventApproval:
    try:
        return CurrentFootballEventApproval.model_validate_json(value.model_dump_json())
    except ValueError as exc:
        raise IngestionError(
            "QUALITY_BLOCKED", "current football-event approval failed revalidation"
        ) from exc


def _target_fixtures(source: CurrentAvailabilityBundle) -> tuple[CurrentFplFixture, ...]:
    expected_ids = {row.official_fpl_fixture_id for row in source.team_projections}
    fixtures = tuple(
        sorted(
            (
                row
                for row in source.source_market.source_input.fpl_input.fixtures
                if row.provider_fixture_id in expected_ids
            ),
            key=lambda row: row.provider_fixture_id,
        )
    )
    if (
        len(fixtures) != len(expected_ids)
        or {row.provider_fixture_id for row in fixtures} != expected_ids
        or any(row.kickoff_at is None or row.finished or row.started is True for row in fixtures)
    ):
        raise IngestionError(
            "QUALITY_BLOCKED", "current target fixtures are not complete future fixtures"
        )
    return fixtures


def _team_provider_ids(source: CurrentAvailabilityBundle) -> dict[str, int]:
    return {
        row.identity.canonical_lookup_sha256: row.provider_team_id
        for row in source.source_market.source_input.fpl_input.teams
    }


def _fixture_parts(
    source: CurrentAvailabilityBundle,
    fixture: CurrentFplFixture,
) -> tuple[
    CurrentTeamAvailabilityProjection,
    CurrentTeamAvailabilityProjection,
    Any,
]:
    team_ids = _team_provider_ids(source)
    home_official = team_ids[fixture.home_team_identity.canonical_lookup_sha256]
    away_official = team_ids[fixture.away_team_identity.canonical_lookup_sha256]
    projections = {
        row.official_fpl_team_id: row
        for row in source.team_projections
        if row.official_fpl_fixture_id == fixture.provider_fixture_id
    }
    markets = {row.official_fpl_fixture_id: row for row in source.source_market.fixture_markets}
    try:
        home = projections[home_official]
        away = projections[away_official]
        market = markets[fixture.provider_fixture_id]
    except KeyError as exc:
        raise IngestionError(
            "MAPPING_CONFLICT", "current event fixture orientation is incomplete"
        ) from exc
    if (
        home.transient_fixture_id != away.transient_fixture_id
        or home.transient_fixture_id != market.transient_fixture_id
    ):
        raise IngestionError("MAPPING_CONFLICT", "Stage-6 and Stage-7 fixture identities disagree")
    return home, away, market


def _build_review_template(
    source: CurrentAvailabilityBundle,
) -> CurrentFootballEventReviewTemplate:
    fixture_rows: list[CurrentFootballEventReviewFixture] = []
    for fixture in _target_fixtures(source):
        home, away, market = _fixture_parts(source, fixture)
        assert fixture.kickoff_at is not None
        home_player_ids = tuple(
            sorted((UUID(row.player_id) for row in home.posterior_projection.players), key=str)
        )
        away_player_ids = tuple(
            sorted((UUID(row.player_id) for row in away.posterior_projection.players), key=str)
        )
        fixture_rows.append(
            CurrentFootballEventReviewFixture(
                official_fpl_fixture_id=fixture.provider_fixture_id,
                transient_fixture_id=market.transient_fixture_id,
                transient_home_team_id=home.transient_team_id,
                transient_away_team_id=away.transient_team_id,
                kickoff_at=fixture.kickoff_at,
                source_market_result_sha256=market.result_sha256,
                source_market_consensus_sha256=market.consensus.result_sha256,
                source_home_availability_sha256=home.result_sha256,
                source_away_availability_sha256=away.result_sha256,
                source_home_minutes_sha256=home.posterior_projection.result_sha256,
                source_away_minutes_sha256=away.posterior_projection.result_sha256,
                expected_home_player_ids=home_player_ids,
                expected_away_player_ids=away_player_ids,
            )
        )
    fpl = source.source_market.source_input.fpl_input
    provisional = CurrentFootballEventReviewTemplate.model_construct(
        generated_at=source.decision_information_at,
        information_cutoff=fpl.provenance.information_cutoff,
        source_availability_semantic_sha256=source.semantic_sha256,
        fixtures=tuple(fixture_rows),
        template_sha256="0" * 64,
    )
    return CurrentFootballEventReviewTemplate(
        generated_at=source.decision_information_at,
        information_cutoff=fpl.provenance.information_cutoff,
        source_availability_semantic_sha256=source.semantic_sha256,
        fixtures=tuple(fixture_rows),
        template_sha256=_template_sha256(provisional),
    )


def build_current_football_event_review(
    source: CurrentAvailabilityBundle,
) -> CurrentFootballEventReviewTemplate:
    """Return the exact private review required before any current Stage-8 run."""

    validated = _revalidate_availability(source)
    fpl = validated.source_market.source_input.fpl_input
    if (
        fpl.rights.derived_storage != "DENY"
        or fpl.rights.database_accessed
        or fpl.rights.raw_storage_performed
        or fpl.rights.derived_storage_performed
    ):
        raise IngestionError("RIGHTS_BLOCKED", "official FPL retention boundary is invalid")
    return _build_review_template(validated)


def _validate_approval(
    source: CurrentAvailabilityBundle,
    template: CurrentFootballEventReviewTemplate,
    approval: CurrentFootballEventApproval,
) -> None:
    artifact = approval.prior_artifact
    if (
        approval.template_sha256 != template.template_sha256
        or approval.confirmed_template_sha256 != template.template_sha256
        or approval.confirmed_prior_artifact_sha256 != artifact.artifact_sha256
    ):
        raise IngestionError(
            "MAPPING_CONFLICT", "football-event approval is not bound to current inputs"
        )
    if not template.generated_at <= approval.approved_at <= template.information_cutoff:
        raise IngestionError("POST_CUTOFF", "football-event approval is outside the usable window")
    if artifact.information_cutoff > approval.approved_at:
        raise IngestionError(
            "POST_CUTOFF", "event-prior information exceeds the event decision information set"
        )
    if artifact.accepted_at > approval.approved_at:
        raise IngestionError("POST_CUTOFF", "event prior was not accepted at decision time")

    expected = {row.official_fpl_fixture_id: row for row in template.fixtures}
    supplied = {row.official_fpl_fixture_id: row for row in artifact.fixtures}
    if len(supplied) != len(artifact.fixtures) or set(supplied) != set(expected):
        raise IngestionError(
            "QUALITY_BLOCKED", "accepted event prior does not exactly cover target fixtures"
        )
    for fixture_id, review in expected.items():
        prior = supplied[fixture_id]
        expected_player_teams = {
            **{
                player_id: str(review.transient_home_team_id)
                for player_id in review.expected_home_player_ids
            },
            **{
                player_id: str(review.transient_away_team_id)
                for player_id in review.expected_away_player_ids
            },
        }
        supplied_player_teams = {
            UUID(row.player_id): row.team_id for row in prior.allocation_profiles
        }
        if (
            prior.transient_fixture_id != review.transient_fixture_id
            or prior.transient_home_team_id != review.transient_home_team_id
            or prior.transient_away_team_id != review.transient_away_team_id
            or supplied_player_teams != expected_player_teams
            or artifact.expires_at < review.kickoff_at
        ):
            raise IngestionError(
                "MAPPING_CONFLICT", "accepted event prior identity or validity window disagrees"
            )


def _sample_minutes(
    projection: CurrentTeamAvailabilityProjection,
    *,
    player_id: str,
    role: Literal["START", "BENCH"],
    artifact_sha256: str,
    scenario_index: int,
) -> int:
    pmfs = {
        (row.player_id, row.role): row.minute_pmf
        for row in projection.posterior_conditional_minute_pmfs
    }
    values = pmfs[(player_id, role)]
    support = values if role == "START" else values[:90]
    support_mass = sum(support, Decimal(0))
    if support_mass <= 0:
        raise IngestionError(
            "QUALITY_BLOCKED", "Stage-7 minute PMF has no Stage-9-representable support"
        )
    root_seed = int(artifact_sha256[:16], 16)
    draw = support_mass * Decimal(
        str(
            rng_for(
                root_seed,
                "current-stage7-minute",
                projection.transient_fixture_id,
                projection.transient_team_id,
                scenario_index,
                player_id,
                role,
            ).random()
        )
    )
    cumulative = Decimal(0)
    for minute, probability in enumerate(support):
        cumulative += probability
        if draw < cumulative:
            return minute
    return len(support) - 1


def _participation_rows(
    projection: CurrentTeamAvailabilityProjection,
    *,
    scenario_index: int,
    artifact_sha256: str,
) -> tuple[dict[str, object], ...]:
    scenario = projection.posterior_lineup_scenarios[scenario_index]
    hard_ids = {
        str(row.transient_player_id)
        for row in projection.applied_decisions
        if row.direct_model_effect == "HARD_ZERO"
    }
    rows: list[dict[str, object]] = []
    for member in scenario.members:
        minutes = 0
        starter = member.role == "START"
        entry: int | None = None
        exit_minute: int | None = None
        if member.role in {"START", "BENCH"}:
            minute_role: Literal["START", "BENCH"] = "START" if member.role == "START" else "BENCH"
            minutes = _sample_minutes(
                projection,
                player_id=member.player_id,
                role=minute_role,
                artifact_sha256=artifact_sha256,
                scenario_index=scenario_index,
            )
            if minutes > 0:
                entry = 0 if starter else 90 - minutes
                exit_minute = minutes if starter else 90
                if not starter and entry <= 0:
                    raise IngestionError(
                        "QUALITY_BLOCKED",
                        "Stage-7 bench minute PMF produced an impossible substitution interval",
                    )
        rows.append(
            {
                "player_id": member.player_id,
                "team_id": str(projection.transient_team_id),
                "position": member.position,
                "official_minutes": minutes,
                "entry_minute": entry,
                "exit_minute": exit_minute,
                "hard_ineligible": member.player_id in hard_ids,
                "starter": starter,
            }
        )
    return tuple(rows)


def _participation_scenarios(
    *,
    source: CurrentAvailabilityBundle,
    home: CurrentTeamAvailabilityProjection,
    away: CurrentTeamAvailabilityProjection,
    artifact_sha256: str,
    as_of: datetime,
) -> tuple[ParticipationScenario, ...]:
    gameweek_id = _uuid(
        "gameweek", source.source_market.source_input.fpl_input.target_event.identity
    )
    root_seed = int(artifact_sha256[:16], 16)
    probability = 1.0 / _PARTICIPATION_SCENARIO_COUNT
    scenarios: list[ParticipationScenario] = []
    for index in range(_PARTICIPATION_SCENARIO_COUNT):
        rows = (
            *_participation_rows(home, scenario_index=index, artifact_sha256=artifact_sha256),
            *_participation_rows(away, scenario_index=index, artifact_sha256=artifact_sha256),
        )
        scenarios.append(
            build_participation_scenario(
                scenario_id=stable_identifier(
                    "participation", root_seed, home.transient_fixture_id, index
                ),
                probability=probability,
                fixture_id=str(home.transient_fixture_id),
                gameweek_id=str(gameweek_id),
                home_team_id=str(home.transient_team_id),
                away_team_id=str(away.transient_team_id),
                participant_rows=rows,
                home_projection=home.posterior_projection,
                away_projection=away.posterior_projection,
                information_cutoff_utc=_utc_text(as_of),
            )
        )
    return tuple(scenarios)


def _stage8_market_evidence(
    source: CurrentAvailabilityBundle,
    fixture: CurrentFplFixture,
    *,
    market: CurrentFixtureMarketConsensus,
    as_of: datetime,
) -> tuple[tuple[MarketConstraint, ...], MarketConsensus | None]:
    """Use optional totals with 1X2 in the one existing Stage-8 request.

    The frozen 1X2 public contract remains the H2H-only fallback.  When a
    fresh, complete 2.5-goal consensus is present, both independently
    normalised families become native constraints on the same score matrix.
    No second score, player, or optimisation path is created.
    """

    totals_by_fixture = {
        row.official_fpl_fixture_id: row for row in source.source_market.fixture_totals
    }
    totals = totals_by_fixture[fixture.provider_fixture_id]
    if totals.consensus is None:
        return (), market.consensus
    policy = load_score_baseline_policy()
    try:
        one_x_two = constraints_from_market_consensus(
            market.consensus,
            fixture_id=market.transient_fixture_id,
            as_of=as_of,
            uncertainty_floor=policy.projection.market_uncertainty_floor,
        )
        totals_constraints = constraints_from_totals_consensus(
            totals.consensus,
            fixture_id=market.transient_fixture_id,
            as_of=as_of,
            uncertainty_floor=policy.projection.market_uncertainty_floor,
        )
        combined = combine_market_constraint_sets(one_x_two, totals_constraints)
    except ValueError as exc:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "current Stage-6 1X2/totals evidence cannot be adapted for Stage-8",
            details={"official_fpl_fixture_id": fixture.provider_fixture_id},
        ) from exc
    return combined.constraints, None


def _build_fixture_inputs(
    source: CurrentAvailabilityBundle,
    approval: CurrentFootballEventApproval,
) -> tuple[CurrentFixtureEventInputs, ...]:
    artifact = approval.prior_artifact
    prior_by_fixture = {row.official_fpl_fixture_id: row for row in artifact.fixtures}
    service = ScoreDistributionService()
    results: list[CurrentFixtureEventInputs] = []
    gameweek_id = _uuid(
        "gameweek", source.source_market.source_input.fpl_input.target_event.identity
    )
    for fixture in _target_fixtures(source):
        home, away, market = _fixture_parts(source, fixture)
        prior = prior_by_fixture[fixture.provider_fixture_id]
        context = Stage7MinutesContext.from_projections(
            home.posterior_projection, away.posterior_projection
        )
        constraints, market_consensus = _stage8_market_evidence(
            source,
            fixture,
            market=market,
            as_of=approval.approved_at,
        )
        request = ScoreDistributionRequest(
            schema_version="score-distribution-request-v1",
            fixture_id=home.transient_fixture_id,
            home_team_id=home.transient_team_id,
            away_team_id=away.transient_team_id,
            as_of=approval.approved_at,
            fixture_status="SCHEDULED",
            minutes_context=context,
            prior=prior.score_prior,
            constraints=constraints,
            market_consensus=market_consensus,
        )
        try:
            projected = service.project(request)
        except ScoreDistributionError as exc:
            raise IngestionError(
                "QUALITY_BLOCKED",
                "accepted current score prior is outside the Stage-8 validated boundary",
                details={
                    "official_fpl_fixture_id": fixture.provider_fixture_id,
                    "error_code": exc.code,
                },
            ) from exc
        if projected.status != "PROJECTED" or projected.distribution is None:
            raise IngestionError(
                "QUALITY_BLOCKED",
                "accepted Stage-8 service did not project a current scheduled fixture",
                details={
                    "official_fpl_fixture_id": fixture.provider_fixture_id,
                    "error_code": projected.error_code,
                },
            )
        participation = _participation_scenarios(
            source=source,
            home=home,
            away=away,
            artifact_sha256=artifact.artifact_sha256,
            as_of=approval.approved_at,
        )
        values: dict[str, Any] = {
            "official_fpl_fixture_id": fixture.provider_fixture_id,
            "transient_fixture_id": home.transient_fixture_id,
            "gameweek_id": gameweek_id,
            "transient_home_team_id": home.transient_team_id,
            "transient_away_team_id": away.transient_team_id,
            "score_distribution": projected.distribution,
            "participation_scenarios": participation,
            "allocation_profiles": prior.allocation_profiles,
            "allocation_config": artifact.allocation_config,
            "source_market_result_sha256": market.result_sha256,
            "source_home_availability_sha256": home.result_sha256,
            "source_away_availability_sha256": away.result_sha256,
            "source_prior_artifact_sha256": artifact.artifact_sha256,
            "limitations": (
                "STAGE7_CURRENT_ROSTER_COLD_START",
                "STAGE7_SYNTHETIC_TEST_REPLAY_TRAINING_EVIDENCE",
                "CURRENT_EVENT_PRIOR_EXTERNALLY_ACCEPTED_NON_PRODUCTION",
                "STAGE7_BENCH_90_MASS_CONDITIONED_TO_STAGE9_INTERVAL_SUPPORT",
                "PLAYER_EVENTS_ALLOCATED_ONLY_INSIDE_ACCEPTED_STAGE9",
            ),
        }
        provisional = CurrentFixtureEventInputs.model_construct(**values, result_sha256="0" * 64)
        results.append(
            CurrentFixtureEventInputs(**values, result_sha256=_fixture_inputs_sha256(provisional))
        )
    return tuple(sorted(results, key=lambda row: row.official_fpl_fixture_id))


def _bundle_sha256(value: CurrentFootballEventBundle) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


def build_current_football_events(
    source: CurrentAvailabilityBundle,
    approval: CurrentFootballEventApproval,
) -> CurrentFootballEventBundle:
    """Build the transient current Stage-8 result and exact Stage-9 handoff."""

    validated = _revalidate_availability(source)
    template = _build_review_template(validated)
    checked_approval = _revalidate_approval(approval)
    _validate_approval(validated, template, checked_approval)
    fixtures = _build_fixture_inputs(validated, checked_approval)
    values: dict[str, Any] = {
        "decision_information_at": checked_approval.approved_at,
        "stage8_policy_sha256": load_score_baseline_policy().sha256,
        "source_availability_semantic_sha256": validated.semantic_sha256,
        "source_availability": validated,
        "review_template": template,
        "approval": checked_approval,
        "fixtures": fixtures,
    }
    provisional = CurrentFootballEventBundle.model_construct(**values, semantic_sha256="0" * 64)
    return CurrentFootballEventBundle(**values, semantic_sha256=_bundle_sha256(provisional))


__all__ = [
    "CURRENT_FOOTBALL_EVENT_ADAPTER_VERSION",
    "CurrentFixtureEventInputs",
    "CurrentFixtureEventPrior",
    "CurrentFootballEventApproval",
    "CurrentFootballEventBundle",
    "CurrentFootballEventPriorArtifact",
    "CurrentFootballEventReviewFixture",
    "CurrentFootballEventReviewTemplate",
    "CurrentFootballEventSummary",
    "build_current_football_event_review",
    "build_current_football_events",
]
