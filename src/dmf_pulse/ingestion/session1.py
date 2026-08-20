"""Transient Session-1 current-input and reviewed-identity application service."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplFixture,
    CurrentFplInputBundle,
    CurrentFplInputRequest,
    CurrentFplInputService,
)
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.ingestion.odds.current import (
    OddsProviderCurrentInput,
    current_odds_market_semantic_sha256,
)
from dmf_pulse.ingestion.odds.identity import (
    FplOddsIdentityMap,
    bind_current_fixture_resolution_request,
    bind_current_team_resolution_request,
    current_fpl_identity_view_sha256,
    current_fpl_input_semantic_sha256,
    current_odds_identity_semantic_sha256,
    current_odds_provider_provenance_sha256,
    resolve_current_fixture_identities,
    resolve_current_team_identities,
)
from dmf_pulse.ingestion.odds.live import LiveOddsSnapshotService
from dmf_pulse.ingestion.odds.mapping import (
    CurrentFixtureBinding,
    CurrentFixtureMappingPlan,
    CurrentTeamAliasMapping,
    CurrentTeamAliasPlan,
)


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


class Session1CurrentInputRequest(_FrozenModel):
    """Operator-declared inputs for one current Session-1 preparation."""

    bootstrap_path: Path
    fixtures_path: Path
    captured_at: datetime
    information_cutoff: datetime
    database_url_ref: str = DATABASE_REF
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: Literal[1] = 1
    fpl_rights_profile_id: Literal["fpl_official_private_manual_v1"] = (
        "fpl_official_private_manual_v1"
    )
    odds_provider: Literal["the_odds_api"] = "the_odds_api"
    odds_sport_key: Literal["soccer_epl"] = "soccer_epl"
    odds_region: Literal["uk"] = "uk"
    odds_market: Literal["h2h"] = "h2h"


class Session1TeamReviewRow(_FrozenModel):
    provider_team_text: str = Field(min_length=1, max_length=500)
    exact_name_candidate_team_ids: tuple[int, ...]


class Session1OfficialTeamOption(_FrozenModel):
    official_fpl_team_id: int = Field(gt=0)
    official_name: str = Field(min_length=1, max_length=500)
    short_name: str = Field(min_length=1, max_length=100)


class Session1FixtureReviewRow(_FrozenModel):
    provider_event_id: str = Field(min_length=1, max_length=500)
    provider_home_team: str = Field(min_length=1, max_length=500)
    provider_away_team: str = Field(min_length=1, max_length=500)
    provider_commence_time: datetime
    exact_text_and_kickoff_candidate_fixture_ids: tuple[int, ...]


class Session1OfficialFixtureOption(_FrozenModel):
    official_fpl_fixture_id: int = Field(gt=0)
    official_home_team_id: int = Field(gt=0)
    official_home_team_name: str = Field(min_length=1, max_length=500)
    official_away_team_id: int = Field(gt=0)
    official_away_team_name: str = Field(min_length=1, max_length=500)
    official_kickoff_at: datetime


def _review_template_sha256(value: Session1ReviewTemplate) -> str:
    material = value.model_dump(mode="json", exclude={"template_sha256"})
    return canonical_sha256(material)


class Session1ReviewTemplate(_FrozenModel):
    """Deterministic private display used for explicit, non-fuzzy review."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["SESSION1_IDENTITY_REVIEW_TEMPLATE"] = "SESSION1_IDENTITY_REVIEW_TEMPLATE"
    status: Literal["REVIEW_REQUIRED"] = "REVIEW_REQUIRED"
    usage_scope: Literal["TRANSIENT_PRIVATE_OPERATOR_REVIEW"] = "TRANSIENT_PRIVATE_OPERATOR_REVIEW"
    persistence_authorized: Literal[False] = False
    match_policy: Literal["EXACT_CASE_SENSITIVE_ONLY_NO_AUTO_APPROVAL"] = (
        "EXACT_CASE_SENSITIVE_ONLY_NO_AUTO_APPROVAL"
    )
    event_scope_policy: Literal["OFFICIAL_TARGET_GW_MIN_MAX_KICKOFF_WINDOW"] = (
        "OFFICIAL_TARGET_GW_MIN_MAX_KICKOFF_WINDOW"
    )
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: Literal[1] = 1
    information_cutoff: datetime
    fpl_input_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_identity_view_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_provider_event_count: int = Field(gt=0)
    excluded_provider_event_count: int = Field(ge=0)
    provider_teams: tuple[Session1TeamReviewRow, ...] = Field(min_length=2)
    official_team_options: tuple[Session1OfficialTeamOption, ...] = Field(min_length=2)
    provider_events: tuple[Session1FixtureReviewRow, ...] = Field(min_length=1)
    official_fixture_options: tuple[Session1OfficialFixtureOption, ...] = Field(min_length=1)
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_review_template(self) -> Session1ReviewTemplate:
        provider_teams = [row.provider_team_text for row in self.provider_teams]
        official_teams = [row.official_fpl_team_id for row in self.official_team_options]
        provider_events = [row.provider_event_id for row in self.provider_events]
        official_fixtures = [row.official_fpl_fixture_id for row in self.official_fixture_options]
        if any(
            len(values) != len(set(values))
            for values in (provider_teams, official_teams, provider_events, official_fixtures)
        ):
            raise ValueError("Session-1 review choices are duplicated")
        official_team_ids = set(official_teams)
        official_fixture_ids = set(official_fixtures)
        if any(
            not set(row.exact_name_candidate_team_ids) <= official_team_ids
            for row in self.provider_teams
        ) or any(
            not set(row.exact_text_and_kickoff_candidate_fixture_ids) <= official_fixture_ids
            for row in self.provider_events
        ):
            raise ValueError("Session-1 exact candidates are outside the review options")
        if (
            self.source_provider_event_count
            != len(self.provider_events) + self.excluded_provider_event_count
        ):
            raise ValueError("Session-1 provider event-scope counts are inconsistent")
        if self.template_sha256 != _review_template_sha256(self):
            raise ValueError("Session-1 review-template hash is inconsistent")
        return self


class Session1TeamApproval(_FrozenModel):
    provider_team_text: str = Field(min_length=1, max_length=500)
    official_fpl_team_id: int = Field(gt=0)


class Session1FixtureApproval(_FrozenModel):
    provider_event_id: str = Field(min_length=1, max_length=500)
    official_fpl_fixture_id: int = Field(gt=0)


class Session1OperatorApproval(_FrozenModel):
    """Explicit operator decisions bound to one exact transient template."""

    contract: Literal["SESSION1_OPERATOR_IDENTITY_APPROVAL"] = "SESSION1_OPERATOR_IDENTITY_APPROVAL"
    reviewer: str = Field(min_length=1, max_length=160)
    approved_at: datetime
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_approvals: tuple[Session1TeamApproval, ...] = Field(min_length=2)
    fixture_approvals: tuple[Session1FixtureApproval, ...] = Field(min_length=1)
    status: Literal["APPROVED_BY_OPERATOR"] = "APPROVED_BY_OPERATOR"

    @model_validator(mode="after")
    def validate_explicit_approval(self) -> Session1OperatorApproval:
        provider_teams = [row.provider_team_text for row in self.team_approvals]
        official_teams = [row.official_fpl_team_id for row in self.team_approvals]
        provider_events = [row.provider_event_id for row in self.fixture_approvals]
        official_fixtures = [row.official_fpl_fixture_id for row in self.fixture_approvals]
        if self.confirmed_template_sha256 != self.template_sha256:
            raise ValueError("operator did not confirm the exact review-template hash")
        if any(
            len(values) != len(set(values))
            for values in (provider_teams, official_teams, provider_events, official_fixtures)
        ):
            raise ValueError("operator identity approval is duplicate or ambiguous")
        return self


class Session1PreparedInputs(_FrozenModel):
    """Transient sources and their deterministic private review template."""

    fpl_input: CurrentFplInputBundle
    odds_input: OddsProviderCurrentInput
    review_template: Session1ReviewTemplate


def _downstream_semantic_sha256(value: Session1DownstreamInput) -> str:
    return canonical_sha256(
        {
            "contract": value.contract,
            "decision_information_at": value.decision_information_at.isoformat(),
            "excluded_provider_event_count": value.excluded_provider_event_count,
            "fpl_input_semantic_sha256": value.fpl_input.semantic_sha256,
            "identity_map_semantic_sha256": value.identity_map.semantic_sha256,
            "information_cutoff": value.information_cutoff.isoformat(),
            "odds_identity_semantic_sha256": current_odds_identity_semantic_sha256(
                value.odds_input
            ),
            "odds_market_semantic_sha256": current_odds_market_semantic_sha256(value.odds_input),
            "odds_provider_provenance_sha256": current_odds_provider_provenance_sha256(
                value.odds_input
            ),
            "review_template_sha256": value.review_template_sha256,
            "run_classification": value.run_classification,
            "source_provider_event_count": value.source_provider_event_count,
        }
    )


class Session1DownstreamSummary(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["COMPLETE"] = "COMPLETE"
    contract: Literal["SESSION1_DOWNSTREAM_INPUT"] = "SESSION1_DOWNSTREAM_INPUT"
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: Literal[1] = 1
    information_cutoff: datetime
    decision_information_at: datetime
    fpl_player_count: int = Field(gt=0)
    fpl_team_count: int = Field(gt=0)
    target_fixture_count: int = Field(gt=0)
    source_provider_event_count: int = Field(gt=0)
    excluded_provider_event_count: int = Field(ge=0)
    mapped_provider_event_count: int = Field(gt=0)
    fpl_input_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity_map_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    downstream_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity_coverage: Literal["COMPLETE"] = "COMPLETE"
    fpl_raw_storage: Literal["DENY"] = "DENY"
    fpl_derived_storage: Literal["DENY"] = "DENY"
    fpl_persistence_performed: Literal[False] = False
    fpl_database_accessed: Literal[False] = False
    odds_raw_payload_retained: Literal[False] = False
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    next_checkpoint: Literal["2.1_MARKET_CONSENSUS_CURRENT_INTEGRATION"] = (
        "2.1_MARKET_CONSENSUS_CURRENT_INTEGRATION"
    )


class Session1DownstreamInput(_FrozenModel):
    """Complete current input passed in memory to later modelling services."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["SESSION1_DOWNSTREAM_INPUT"] = "SESSION1_DOWNSTREAM_INPUT"
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    information_cutoff: datetime
    decision_information_at: datetime
    source_provider_event_count: int = Field(gt=0)
    excluded_provider_event_count: int = Field(ge=0)
    review_template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_input: CurrentFplInputBundle
    odds_input: OddsProviderCurrentInput
    identity_map: FplOddsIdentityMap
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_downstream_input(self) -> Session1DownstreamInput:
        if (
            self.information_cutoff != self.fpl_input.provenance.information_cutoff
            or self.information_cutoff != self.odds_input.temporal.information_cutoff
            or self.information_cutoff != self.identity_map.information_cutoff
            or self.fpl_input.semantic_sha256 != current_fpl_input_semantic_sha256(self.fpl_input)
            or self.identity_map.fpl_input_semantic_sha256 != self.fpl_input.semantic_sha256
            or self.identity_map.fpl_identity_view_sha256
            != current_fpl_identity_view_sha256(self.fpl_input)
            or self.identity_map.odds_provider_provenance_sha256
            != current_odds_provider_provenance_sha256(self.odds_input)
            or self.identity_map.odds_identity_semantic_sha256
            != current_odds_identity_semantic_sha256(self.odds_input)
            or self.review_template_sha256
            != build_session1_review_template(
                self.fpl_input,
                self.odds_input,
                source_provider_event_count=self.source_provider_event_count,
            ).template_sha256
            or self.decision_information_at != self.identity_map.mapping_decided_at
            or self.decision_information_at
            < max(
                self.fpl_input.provenance.usable_at,
                self.odds_input.temporal.usable_at,
            )
            or self.decision_information_at > self.information_cutoff
            or self.source_provider_event_count
            != len(self.odds_input.events) + self.excluded_provider_event_count
        ):
            raise ValueError("Session-1 downstream lineage is inconsistent")
        if (
            self.fpl_input.rights.raw_storage != "DENY"
            or self.fpl_input.rights.derived_storage != "DENY"
            or self.fpl_input.rights.database_accessed
            or self.fpl_input.rights.raw_storage_performed
            or self.fpl_input.rights.derived_storage_performed
            or self.identity_map.persistence_performed
            or self.identity_map.database_accessed
            or self.odds_input.provenance.raw_payload_retained
        ):
            raise ValueError("Session-1 downstream input violates source retention rights")
        if self.semantic_sha256 != _downstream_semantic_sha256(self):
            raise ValueError("Session-1 downstream semantic hash is inconsistent")
        return self

    def safe_summary(self) -> Session1DownstreamSummary:
        return Session1DownstreamSummary(
            information_cutoff=self.information_cutoff,
            decision_information_at=self.decision_information_at,
            fpl_player_count=len(self.fpl_input.players),
            fpl_team_count=len(self.fpl_input.teams),
            target_fixture_count=self.identity_map.coverage.target_fpl_fixture_count,
            source_provider_event_count=self.source_provider_event_count,
            excluded_provider_event_count=self.excluded_provider_event_count,
            mapped_provider_event_count=self.identity_map.coverage.mapped_event_count,
            fpl_input_semantic_sha256=self.fpl_input.semantic_sha256,
            odds_identity_semantic_sha256=self.identity_map.odds_identity_semantic_sha256,
            identity_map_semantic_sha256=self.identity_map.semantic_sha256,
            downstream_semantic_sha256=self.semantic_sha256,
            review_template_sha256=self.review_template_sha256,
        )


def _target_fixtures(fpl_input: CurrentFplInputBundle) -> tuple[CurrentFplFixture, ...]:
    return tuple(
        sorted(
            (
                fixture
                for fixture in fpl_input.fixtures
                if fixture.event_identity == fpl_input.target_event.identity
                and fixture.kickoff_at is not None
            ),
            key=lambda item: item.provider_fixture_id,
        )
    )


def build_session1_review_template(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    *,
    source_provider_event_count: int | None = None,
) -> Session1ReviewTemplate:
    """Build deterministic exact-equality hints without selecting or approving them."""

    provider_team_texts = sorted(
        {
            text
            for event in odds_input.events
            for text in (event.provider_home_team, event.provider_away_team)
        }
    )
    official_teams = tuple(sorted(fpl_input.teams, key=lambda item: item.provider_team_id))
    target_fixtures = _target_fixtures(fpl_input)
    team_by_identity = {team.identity: team for team in official_teams}

    provider_teams = tuple(
        Session1TeamReviewRow(
            provider_team_text=text,
            exact_name_candidate_team_ids=tuple(
                team.provider_team_id for team in official_teams if team.official_name == text
            ),
        )
        for text in provider_team_texts
    )
    team_options = tuple(
        Session1OfficialTeamOption(
            official_fpl_team_id=team.provider_team_id,
            official_name=team.official_name,
            short_name=team.short_name,
        )
        for team in official_teams
    )
    event_rows = tuple(
        Session1FixtureReviewRow(
            provider_event_id=event.provider_event_id,
            provider_home_team=event.provider_home_team,
            provider_away_team=event.provider_away_team,
            provider_commence_time=event.commence_time,
            exact_text_and_kickoff_candidate_fixture_ids=tuple(
                fixture.provider_fixture_id
                for fixture in target_fixtures
                if team_by_identity[fixture.home_team_identity].official_name
                == event.provider_home_team
                and team_by_identity[fixture.away_team_identity].official_name
                == event.provider_away_team
                and fixture.kickoff_at == event.commence_time
            ),
        )
        for event in sorted(odds_input.events, key=lambda item: item.provider_event_id)
    )
    fixture_options = tuple(
        Session1OfficialFixtureOption(
            official_fpl_fixture_id=fixture.provider_fixture_id,
            official_home_team_id=team_by_identity[fixture.home_team_identity].provider_team_id,
            official_home_team_name=team_by_identity[fixture.home_team_identity].official_name,
            official_away_team_id=team_by_identity[fixture.away_team_identity].provider_team_id,
            official_away_team_name=team_by_identity[fixture.away_team_identity].official_name,
            official_kickoff_at=fixture.kickoff_at,
        )
        for fixture in target_fixtures
        if fixture.kickoff_at is not None
    )
    provisional = Session1ReviewTemplate.model_construct(
        information_cutoff=fpl_input.provenance.information_cutoff,
        fpl_input_semantic_sha256=fpl_input.semantic_sha256,
        fpl_identity_view_sha256=current_fpl_identity_view_sha256(fpl_input),
        odds_provider_provenance_sha256=current_odds_provider_provenance_sha256(odds_input),
        odds_identity_semantic_sha256=current_odds_identity_semantic_sha256(odds_input),
        source_provider_event_count=(
            source_provider_event_count
            if source_provider_event_count is not None
            else len(odds_input.events)
        ),
        excluded_provider_event_count=(
            source_provider_event_count - len(odds_input.events)
            if source_provider_event_count is not None
            else 0
        ),
        provider_teams=provider_teams,
        official_team_options=team_options,
        provider_events=event_rows,
        official_fixture_options=fixture_options,
        template_sha256="0" * 64,
    )
    payload = provisional.model_dump(mode="python")
    payload["template_sha256"] = _review_template_sha256(provisional)
    return Session1ReviewTemplate.model_validate(payload)


def _scope_odds_to_target_gameweek(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
) -> OddsProviderCurrentInput:
    fixtures = tuple(
        fixture
        for fixture in fpl_input.fixtures
        if fixture.event_identity == fpl_input.target_event.identity
    )
    if not fixtures or any(fixture.kickoff_at is None for fixture in fixtures):
        raise IngestionError("QUALITY_BLOCKED", "target-Gameweek fixture window is incomplete")
    kickoffs = tuple(fixture.kickoff_at for fixture in fixtures)
    window_start = min(kickoff for kickoff in kickoffs if kickoff is not None)
    window_end = max(kickoff for kickoff in kickoffs if kickoff is not None)
    selected = tuple(
        event for event in odds_input.events if window_start <= event.commence_time <= window_end
    )
    if not selected:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "live odds input has no event in the official target-Gameweek kickoff window",
        )
    values = {name: getattr(odds_input, name) for name in OddsProviderCurrentInput.model_fields}
    values["events"] = selected
    values["market_semantic_sha256"] = "0" * 64
    provisional = OddsProviderCurrentInput.model_construct(**values)
    payload = provisional.model_dump(mode="python")
    payload["market_semantic_sha256"] = current_odds_market_semantic_sha256(provisional)
    return OddsProviderCurrentInput.model_validate(payload)


class Session1CurrentInputService:
    """Prepare, explicitly approve, and validate one transient Session-1 input."""

    def __init__(
        self,
        *,
        fpl_service: CurrentFplInputService | None = None,
        odds_service: LiveOddsSnapshotService | None = None,
    ) -> None:
        self._fpl_service = fpl_service or CurrentFplInputService()
        self._odds_service = odds_service

    def prepare(self, request: Session1CurrentInputRequest) -> Session1PreparedInputs:
        fpl_input = self._fpl_service.compile(
            CurrentFplInputRequest(
                bootstrap_path=request.bootstrap_path,
                fixtures_path=request.fixtures_path,
                competition_key=request.competition_key,
                season_code=request.season_code,
                captured_at=request.captured_at,
                information_cutoff=request.information_cutoff,
                rights_profile_id=request.fpl_rights_profile_id,
                gameweek=request.target_gameweek,
            )
        )
        if request.information_cutoff != fpl_input.target_event.deadline_at:
            raise IngestionError(
                "QUALITY_BLOCKED",
                "Session-1 information cutoff must equal the official target-Gameweek deadline",
            )

        odds_service = self._odds_service or LiveOddsSnapshotService(
            database_url_ref=request.database_url_ref
        )
        outcome = odds_service.snapshot(
            provider=request.odds_provider,
            competition_key=request.competition_key,
            sport_key=request.odds_sport_key,
            region=request.odds_region,
            market=request.odds_market,
            as_of=request.information_cutoff,
            database_url_ref=request.database_url_ref,
        )
        if outcome.exit_code or outcome.result.status != "COMPLETE":
            if outcome.result.error is not None:
                raise IngestionError(
                    outcome.result.error.code.value,
                    outcome.result.error.message,
                    retryable=outcome.result.error.retryable,
                    details={"transport_called": outcome.result.error.transport_called},
                )
            raise IngestionError(
                "QUALITY_BLOCKED",
                "live odds input is not usable for Session-1",
                details={
                    "provider_status": outcome.result.status,
                    "blockers": list(outcome.result.quality.blockers),
                },
            )
        odds_input = outcome.result.current_input
        if odds_input is None:
            raise IngestionError("INTERNAL_INVARIANT", "complete odds result has no current input")
        source_provider_event_count = len(odds_input.events)
        odds_input = _scope_odds_to_target_gameweek(fpl_input, odds_input)
        template = build_session1_review_template(
            fpl_input,
            odds_input,
            source_provider_event_count=source_provider_event_count,
        )
        return Session1PreparedInputs(
            fpl_input=fpl_input,
            odds_input=odds_input,
            review_template=template,
        )

    def complete(
        self,
        prepared: Session1PreparedInputs,
        approval: Session1OperatorApproval,
    ) -> Session1DownstreamInput:
        expected_template = build_session1_review_template(
            prepared.fpl_input,
            prepared.odds_input,
            source_provider_event_count=prepared.review_template.source_provider_event_count,
        )
        if (
            prepared.review_template != expected_template
            or approval.template_sha256 != expected_template.template_sha256
        ):
            raise IngestionError(
                "MAPPING_CONFLICT", "operator approval is not bound to the current inputs"
            )
        earliest = max(
            prepared.fpl_input.provenance.usable_at,
            prepared.odds_input.temporal.usable_at,
        )
        if (
            approval.approved_at < earliest
            or approval.approved_at > expected_template.information_cutoff
        ):
            raise IngestionError("POST_CUTOFF", "operator approval is outside the usable window")

        provider_team_texts = {row.provider_team_text for row in expected_template.provider_teams}
        provider_event_ids = {row.provider_event_id for row in expected_template.provider_events}
        if {row.provider_team_text for row in approval.team_approvals} != provider_team_texts:
            raise IngestionError("MAPPING_CONFLICT", "team review coverage is incomplete")
        if {row.provider_event_id for row in approval.fixture_approvals} != provider_event_ids:
            raise IngestionError("MAPPING_CONFLICT", "fixture review coverage is incomplete")

        fpl_team_by_id = {team.provider_team_id: team for team in prepared.fpl_input.teams}
        team_mappings: list[CurrentTeamAliasMapping] = []
        for row in sorted(approval.team_approvals, key=lambda item: item.provider_team_text):
            team = fpl_team_by_id.get(row.official_fpl_team_id)
            if team is None:
                raise IngestionError(
                    "MAPPING_CONFLICT", "team review selected no current official FPL team"
                )
            team_mappings.append(
                CurrentTeamAliasMapping(
                    provider_team_text=row.provider_team_text,
                    official_fpl_team_id=team.provider_team_id,
                    canonical_team_identity=team.identity,
                    official_fpl_team_name=team.official_name,
                    evidence_class="APPROVED_MANUAL",
                    reviewer=approval.reviewer,
                    approved_at=approval.approved_at,
                )
            )
        team_plan = CurrentTeamAliasPlan(
            plan_id=(f"gw1-2026-27-session1-{expected_template.template_sha256[:12]}-teams"),
            plan_version="1.0.0",
            approved_at=approval.approved_at,
            evidence_class="APPROVED_MANUAL",
            reviewer=approval.reviewer,
            team_mappings=tuple(team_mappings),
        )
        team_request = bind_current_team_resolution_request(
            prepared.fpl_input,
            prepared.odds_input,
            team_plan,
            mapping_decided_at=approval.approved_at,
        )
        team_map = resolve_current_team_identities(
            prepared.fpl_input, prepared.odds_input, team_plan, team_request
        )

        event_by_id = {event.provider_event_id: event for event in prepared.odds_input.events}
        fixture_by_id = {
            fixture.provider_fixture_id: fixture for fixture in _target_fixtures(prepared.fpl_input)
        }
        fixture_mappings: list[CurrentFixtureBinding] = []
        for fixture_approval in sorted(
            approval.fixture_approvals, key=lambda item: item.provider_event_id
        ):
            event = event_by_id[fixture_approval.provider_event_id]
            fixture = fixture_by_id.get(fixture_approval.official_fpl_fixture_id)
            if fixture is None:
                raise IngestionError(
                    "MAPPING_CONFLICT", "fixture review selected no target-Gameweek fixture"
                )
            home = team_map.team(event.provider_home_team)
            away = team_map.team(event.provider_away_team)
            fixture_mappings.append(
                CurrentFixtureBinding(
                    provider_event_id=event.provider_event_id,
                    target_gameweek=prepared.fpl_input.target_gameweek,
                    official_fpl_fixture_id=fixture.provider_fixture_id,
                    canonical_fixture_identity=fixture.identity,
                    expected_home_team_id=home.official_fpl_team_id,
                    expected_home_team_identity=home.official_fpl_team_identity,
                    expected_away_team_id=away.official_fpl_team_id,
                    expected_away_team_identity=away.official_fpl_team_identity,
                    expected_commence_time=event.commence_time,
                    evidence_class="APPROVED_MANUAL",
                    reviewer=approval.reviewer,
                    approved_at=approval.approved_at,
                )
            )
        fixture_plan = CurrentFixtureMappingPlan(
            plan_id=(f"gw1-2026-27-session1-{expected_template.template_sha256[:12]}-fixtures"),
            plan_version="1.0.0",
            approved_at=approval.approved_at,
            evidence_class="APPROVED_MANUAL",
            reviewer=approval.reviewer,
            target_gameweek=prepared.fpl_input.target_gameweek,
            team_alias_plan_version=team_plan.plan_version,
            team_alias_plan_sha256=team_plan.sha256,
            fixture_mappings=tuple(fixture_mappings),
        )
        fixture_request = bind_current_fixture_resolution_request(
            prepared.fpl_input,
            prepared.odds_input,
            team_plan,
            team_map,
            fixture_plan,
            mapping_decided_at=approval.approved_at,
        )
        identity_map = resolve_current_fixture_identities(
            prepared.fpl_input,
            prepared.odds_input,
            team_plan,
            team_map,
            fixture_plan,
            fixture_request,
        )
        provisional = Session1DownstreamInput.model_construct(
            information_cutoff=prepared.fpl_input.provenance.information_cutoff,
            decision_information_at=approval.approved_at,
            source_provider_event_count=expected_template.source_provider_event_count,
            excluded_provider_event_count=expected_template.excluded_provider_event_count,
            review_template_sha256=expected_template.template_sha256,
            fpl_input=prepared.fpl_input,
            odds_input=prepared.odds_input,
            identity_map=identity_map,
            semantic_sha256="0" * 64,
        )
        payload = provisional.model_dump(mode="python")
        payload["semantic_sha256"] = _downstream_semantic_sha256(provisional)
        return Session1DownstreamInput.model_validate(payload)
