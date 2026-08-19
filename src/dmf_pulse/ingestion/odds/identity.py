"""Fail-closed current official-FPL to provider identity resolution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplFixture,
    CurrentFplIdentity,
    CurrentFplInputBundle,
    CurrentFplTeam,
)
from dmf_pulse.ingestion.odds.current import CurrentOddsEvent, OddsProviderCurrentInput
from dmf_pulse.ingestion.odds.mapping import (
    CurrentFixtureBinding,
    CurrentFixtureMappingPlan,
    CurrentTeamAliasMapping,
    CurrentTeamAliasPlan,
)


class _FrozenIdentityModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


class CurrentTeamResolutionRequest(_FrozenIdentityModel):
    """Hash-bound request that prevents post-binding input or plan substitution."""

    contract_version: Literal["gw1-fpl-odds-team-resolution-request-v1"] = (
        "gw1-fpl-odds-team-resolution-request-v1"
    )
    mapping_decided_at: datetime
    fpl_input_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_identity_view_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_alias_plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    team_alias_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResolvedCurrentTeam(_FrozenIdentityModel):
    provider: Literal["the_odds_api"] = "the_odds_api"
    provider_team_text: str = Field(min_length=1, max_length=500)
    official_fpl_team_id: int = Field(gt=0)
    official_fpl_team_identity: CurrentFplIdentity
    official_fpl_team_name: str = Field(min_length=1, max_length=500)
    mapping_evidence_class: Literal["OFFICIAL", "APPROVED_MANUAL"]
    mapping_status: Literal["APPROVED"] = "APPROVED"
    mapping_reviewer: str = Field(min_length=1, max_length=160)
    mapping_approved_at: datetime
    team_alias_mapping_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CurrentTeamIdentityMap(_FrozenIdentityModel):
    """Transient exact team bridge; no fixture or market semantics are implied."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["FPL_ODDS_TEAM_IDENTITY_MAP"] = "FPL_ODDS_TEAM_IDENTITY_MAP"
    usage_scope: Literal["CURRENT_DECISION"] = "CURRENT_DECISION"
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    provider: Literal["the_odds_api"] = "the_odds_api"
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: int = Field(gt=0)
    mapping_decided_at: datetime
    information_cutoff: datetime
    fpl_input_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_identity_view_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_alias_plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    team_alias_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_algorithm_version: Literal["gw1-fpl-odds-exact-v1"] = "gw1-fpl-odds-exact-v1"
    team_mappings: tuple[ResolvedCurrentTeam, ...] = Field(min_length=2)
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_identity_map(self) -> CurrentTeamIdentityMap:
        provider_texts = [mapping.provider_team_text for mapping in self.team_mappings]
        if len(provider_texts) != len(set(provider_texts)):
            raise ValueError("resolved provider team identity is duplicated")
        for mapping in self.team_mappings:
            identity = mapping.official_fpl_team_identity
            if (
                identity.provider_key != "official_fpl"
                or identity.provider_product != "fantasy_premierleague"
                or identity.entity_type != "TEAM"
                or identity.identifier_namespace != "fpl.team.id"
                or identity.external_id_text != str(mapping.official_fpl_team_id)
                or identity.season_code != self.season_code
            ):
                raise ValueError("resolved official FPL team identity is inconsistent")
        if self.semantic_sha256 != _team_identity_map_sha256(self):
            raise ValueError("team identity-map semantic hash is inconsistent")
        return self

    def team(self, provider_team_text: str) -> ResolvedCurrentTeam:
        matches = [
            mapping
            for mapping in self.team_mappings
            if mapping.provider_team_text == provider_team_text
        ]
        if len(matches) != 1:
            raise IngestionError(
                "MAPPING_CONFLICT",
                "provider team text lacks one resolved current mapping",
            )
        return matches[0]


def current_fpl_input_semantic_sha256(fpl_input: CurrentFplInputBundle) -> str:
    """Recompute the accepted Checkpoint-1.2 bundle semantic identity."""

    material = {
        "bootstrap_semantic_sha256": fpl_input.provenance.bootstrap_semantic_sha256,
        "captured_at": fpl_input.provenance.captured_at.isoformat(),
        "competition_key": fpl_input.competition_key,
        "fixtures_semantic_sha256": fpl_input.provenance.fixtures_semantic_sha256,
        "game_settings_semantic_sha256": fpl_input.game_settings_semantic_sha256,
        "information_cutoff": fpl_input.provenance.information_cutoff.isoformat(),
        "provider": fpl_input.provider,
        "season_code": fpl_input.season_code,
        "target_gameweek": fpl_input.target_gameweek,
    }
    return canonical_sha256(material)


def current_fpl_identity_view_sha256(fpl_input: CurrentFplInputBundle) -> str:
    """Bind the exact current team, target-event, and fixture identity view."""

    teams = [
        {
            "identity": team.identity.model_dump(mode="json"),
            "official_name": team.official_name,
            "provider_team_id": team.provider_team_id,
            "source_semantic_sha256": team.source_semantic_sha256,
        }
        for team in sorted(fpl_input.teams, key=lambda item: item.provider_team_id)
    ]
    fixtures = [
        {
            "away_team_identity": fixture.away_team_identity.model_dump(mode="json"),
            "event_identity": (
                fixture.event_identity.model_dump(mode="json")
                if fixture.event_identity is not None
                else None
            ),
            "fixture_identity": fixture.identity.model_dump(mode="json"),
            "home_team_identity": fixture.home_team_identity.model_dump(mode="json"),
            "kickoff_at": fixture.kickoff_at.isoformat() if fixture.kickoff_at else None,
            "provider_fixture_id": fixture.provider_fixture_id,
            "source_semantic_sha256": fixture.source_semantic_sha256,
        }
        for fixture in sorted(
            fpl_input.fixtures,
            key=lambda item: item.provider_fixture_id,
        )
    ]
    return canonical_sha256(
        {
            "competition_key": fpl_input.competition_key,
            "fixtures": fixtures,
            "season_code": fpl_input.season_code,
            "target_event": fpl_input.target_event.model_dump(mode="json"),
            "target_gameweek": fpl_input.target_gameweek,
            "teams": teams,
        }
    )


def current_odds_provider_provenance_sha256(odds_input: OddsProviderCurrentInput) -> str:
    """Hash the accepted provider-current provenance without storing its source body."""

    return canonical_sha256(odds_input.provenance.model_dump(mode="json"))


def current_odds_identity_semantic_sha256(odds_input: OddsProviderCurrentInput) -> str:
    """Hash only event identity material; prices and bookmaker ordering are excluded."""

    events = sorted(
        (
            {
                "commence_time": event.commence_time.isoformat(),
                "provider_away_team": event.provider_away_team,
                "provider_event_id": event.provider_event_id,
                "provider_home_team": event.provider_home_team,
                "sport_key": event.sport_key,
            }
            for event in odds_input.events
        ),
        key=lambda item: item["provider_event_id"],
    )
    return canonical_sha256(
        {
            "events": events,
            "information_cutoff": odds_input.temporal.information_cutoff.isoformat(),
            "provider": odds_input.provider,
            "sport_key": odds_input.sport_key,
        }
    )


def bind_current_team_resolution_request(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    plan: CurrentTeamAliasPlan,
    *,
    mapping_decided_at: datetime,
) -> CurrentTeamResolutionRequest:
    """Freeze exact input and plan identities before resolution."""

    return CurrentTeamResolutionRequest(
        mapping_decided_at=mapping_decided_at,
        fpl_input_semantic_sha256=fpl_input.semantic_sha256,
        fpl_identity_view_sha256=current_fpl_identity_view_sha256(fpl_input),
        odds_provider_provenance_sha256=current_odds_provider_provenance_sha256(odds_input),
        odds_identity_semantic_sha256=current_odds_identity_semantic_sha256(odds_input),
        team_alias_plan_version=plan.plan_version,
        team_alias_plan_sha256=plan.sha256,
    )


def _require_exact_bound_hashes(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    plan: CurrentTeamAliasPlan,
    request: CurrentTeamResolutionRequest,
) -> None:
    recomputed_fpl = current_fpl_input_semantic_sha256(fpl_input)
    checks = {
        "accepted FPL input semantic hash": (
            fpl_input.semantic_sha256,
            recomputed_fpl,
        ),
        "bound FPL input semantic hash": (
            request.fpl_input_semantic_sha256,
            recomputed_fpl,
        ),
        "bound FPL identity-view hash": (
            request.fpl_identity_view_sha256,
            current_fpl_identity_view_sha256(fpl_input),
        ),
        "bound odds provider provenance hash": (
            request.odds_provider_provenance_sha256,
            current_odds_provider_provenance_sha256(odds_input),
        ),
        "bound odds identity semantic hash": (
            request.odds_identity_semantic_sha256,
            current_odds_identity_semantic_sha256(odds_input),
        ),
        "bound team alias plan hash": (
            request.team_alias_plan_sha256,
            plan.sha256,
        ),
        "bound team alias plan version": (
            request.team_alias_plan_version,
            plan.plan_version,
        ),
    }
    for label, (observed, expected) in checks.items():
        if observed != expected:
            raise IngestionError("MAPPING_CONFLICT", f"{label} is inconsistent")


def _require_current_context(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    plan: CurrentTeamAliasPlan,
    request: CurrentTeamResolutionRequest,
) -> datetime:
    if (
        fpl_input.provider != "official_fpl"
        or odds_input.provider != "the_odds_api"
        or odds_input.identity_scope != "PROVIDER_NATIVE_UNMAPPED"
        or odds_input.provenance.canonical_fpl_fixture_mapping_performed is not False
    ):
        raise IngestionError("MAPPING_CONFLICT", "current provider identity scope is invalid")
    if (
        fpl_input.competition_key != plan.competition_key
        or fpl_input.season_code != plan.season_code
        or fpl_input.target_gameweek <= 0
        or plan.provider != odds_input.provider
    ):
        raise IngestionError("MAPPING_CONFLICT", "mapping plan context contradicts current input")
    fpl_cutoff = fpl_input.provenance.information_cutoff
    odds_cutoff = odds_input.temporal.information_cutoff
    if fpl_cutoff != odds_cutoff:
        raise IngestionError("MAPPING_CONFLICT", "current input cutoffs are not identical")
    decided_at = request.mapping_decided_at
    earliest = max(
        fpl_input.provenance.usable_at,
        odds_input.temporal.usable_at,
        plan.approved_at,
    )
    if decided_at < earliest or decided_at > fpl_cutoff:
        raise IngestionError("POST_CUTOFF", "mapping decision time is outside its usable window")
    if any(mapping.approved_at > decided_at for mapping in plan.team_mappings):
        raise IngestionError("POST_CUTOFF", "team alias was approved after the mapping decision")
    fpl_rights = {
        str(decision.capability): decision.decision for decision in fpl_input.rights.decisions
    }
    if (
        fpl_rights.get("manual_import") != "ALLOW"
        or fpl_rights.get("transient_processing") != "ALLOW"
        or fpl_rights.get("private_internal_use") != "ALLOW"
        or fpl_input.rights.derived_storage != "DENY"
        or fpl_input.rights.database_accessed is not False
        or fpl_input.rights.raw_storage_performed is not False
        or fpl_input.rights.derived_storage_performed is not False
        or odds_input.rights.transient_processing != "ALLOW"
        or odds_input.rights.private_internal_use != "ALLOW"
        or odds_input.provenance.raw_payload_retained is not False
    ):
        raise IngestionError("RIGHTS_BLOCKED", "cross-source identity use violates source rights")
    return fpl_cutoff


def _team_by_id(fpl_input: CurrentFplInputBundle) -> dict[int, CurrentFplTeam]:
    by_id: dict[int, CurrentFplTeam] = {}
    identity_hashes: set[str] = set()
    for team in fpl_input.teams:
        if (
            team.provider_team_id in by_id
            or team.identity.canonical_lookup_sha256 in identity_hashes
            or team.source_semantic_sha256 != fpl_input.provenance.bootstrap_semantic_sha256
        ):
            raise IngestionError("MAPPING_CONFLICT", "official FPL team identity is duplicated")
        by_id[team.provider_team_id] = team
        identity_hashes.add(team.identity.canonical_lookup_sha256)
    return by_id


def _resolved_team(
    mapping: CurrentTeamAliasMapping,
    *,
    fpl_team: CurrentFplTeam,
) -> ResolvedCurrentTeam:
    if (
        mapping.canonical_team_identity != fpl_team.identity
        or mapping.official_fpl_team_name != fpl_team.official_name
    ):
        raise IngestionError("MAPPING_CONFLICT", "team alias is stale against current FPL input")
    return ResolvedCurrentTeam(
        provider_team_text=mapping.provider_team_text,
        official_fpl_team_id=fpl_team.provider_team_id,
        official_fpl_team_identity=fpl_team.identity,
        official_fpl_team_name=fpl_team.official_name,
        mapping_evidence_class=mapping.evidence_class,
        mapping_reviewer=mapping.reviewer,
        mapping_approved_at=mapping.approved_at,
        team_alias_mapping_sha256=mapping.sha256,
    )


def _team_identity_map_sha256(value: CurrentTeamIdentityMap) -> str:
    mappings = sorted(
        (mapping.model_dump(mode="json") for mapping in value.team_mappings),
        key=lambda item: (item["provider_team_text"], item["official_fpl_team_id"]),
    )
    return canonical_sha256(
        {
            "competition_key": value.competition_key,
            "contract": value.contract,
            "fpl_identity_view_sha256": value.fpl_identity_view_sha256,
            "fpl_input_semantic_sha256": value.fpl_input_semantic_sha256,
            "information_cutoff": value.information_cutoff.isoformat(),
            "mapping_algorithm_version": value.mapping_algorithm_version,
            "mapping_decided_at": value.mapping_decided_at.isoformat(),
            "odds_identity_semantic_sha256": value.odds_identity_semantic_sha256,
            "odds_provider_provenance_sha256": value.odds_provider_provenance_sha256,
            "persistence_performed": value.persistence_performed,
            "provider": value.provider,
            "schema_version": value.schema_version,
            "season_code": value.season_code,
            "storage_mode": value.storage_mode,
            "target_gameweek": value.target_gameweek,
            "team_alias_plan_sha256": value.team_alias_plan_sha256,
            "team_alias_plan_version": value.team_alias_plan_version,
            "team_mappings": mappings,
            "usage_scope": value.usage_scope,
        }
    )


def resolve_current_team_identities(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    plan: CurrentTeamAliasPlan,
    request: CurrentTeamResolutionRequest,
) -> CurrentTeamIdentityMap:
    """Resolve all current provider team strings by exact explicit mapping only."""

    _require_exact_bound_hashes(fpl_input, odds_input, plan, request)
    cutoff = _require_current_context(fpl_input, odds_input, plan, request)
    fpl_teams = _team_by_id(fpl_input)

    provider_texts = sorted(
        {
            team_text
            for event in odds_input.events
            for team_text in (event.provider_home_team, event.provider_away_team)
        }
    )
    resolved: list[ResolvedCurrentTeam] = []
    for provider_text in provider_texts:
        alias = plan.team(provider_text)
        fpl_team = fpl_teams.get(alias.official_fpl_team_id)
        if fpl_team is None:
            raise IngestionError(
                "MAPPING_CONFLICT", "team alias references no current official FPL team"
            )
        resolved.append(_resolved_team(alias, fpl_team=fpl_team))

    for event in odds_input.events:
        home = next(
            item for item in resolved if item.provider_team_text == event.provider_home_team
        )
        away = next(
            item for item in resolved if item.provider_team_text == event.provider_away_team
        )
        if home.official_fpl_team_id == away.official_fpl_team_id:
            raise IngestionError("MAPPING_CONFLICT", "event participants resolve to one FPL team")

    team_mappings = tuple(resolved)
    provisional = CurrentTeamIdentityMap.model_construct(
        schema_version="1.0.0",
        contract="FPL_ODDS_TEAM_IDENTITY_MAP",
        usage_scope="CURRENT_DECISION",
        storage_mode="TRANSIENT_IN_MEMORY",
        persistence_performed=False,
        provider="the_odds_api",
        competition_key="PL",
        season_code="2026/27",
        target_gameweek=fpl_input.target_gameweek,
        mapping_decided_at=request.mapping_decided_at,
        information_cutoff=cutoff,
        fpl_input_semantic_sha256=request.fpl_input_semantic_sha256,
        fpl_identity_view_sha256=request.fpl_identity_view_sha256,
        odds_provider_provenance_sha256=request.odds_provider_provenance_sha256,
        odds_identity_semantic_sha256=request.odds_identity_semantic_sha256,
        team_alias_plan_version=plan.plan_version,
        team_alias_plan_sha256=plan.sha256,
        mapping_algorithm_version="gw1-fpl-odds-exact-v1",
        team_mappings=team_mappings,
        semantic_sha256="0" * 64,
    )
    return CurrentTeamIdentityMap(
        target_gameweek=fpl_input.target_gameweek,
        mapping_decided_at=request.mapping_decided_at,
        information_cutoff=cutoff,
        fpl_input_semantic_sha256=request.fpl_input_semantic_sha256,
        fpl_identity_view_sha256=request.fpl_identity_view_sha256,
        odds_provider_provenance_sha256=request.odds_provider_provenance_sha256,
        odds_identity_semantic_sha256=request.odds_identity_semantic_sha256,
        team_alias_plan_version=plan.plan_version,
        team_alias_plan_sha256=plan.sha256,
        team_mappings=team_mappings,
        semantic_sha256=_team_identity_map_sha256(provisional),
    )


class CurrentFixtureResolutionRequest(_FrozenIdentityModel):
    """Hash-bound request for exact target-Gameweek fixture resolution."""

    contract_version: Literal["gw1-fpl-odds-fixture-resolution-request-v1"] = (
        "gw1-fpl-odds-fixture-resolution-request-v1"
    )
    mapping_decided_at: datetime
    fpl_input_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_identity_view_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_alias_plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    team_alias_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_identity_map_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_mapping_plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    fixture_mapping_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResolvedCurrentFixture(_FrozenIdentityModel):
    """One provider event mapped to one official target-Gameweek FPL fixture."""

    mapping_status: Literal["MAPPED"] = "MAPPED"
    provider_event_id: str = Field(min_length=1, max_length=500)
    provider_event_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_fpl_fixture_id: int = Field(gt=0)
    official_fpl_fixture_identity: CurrentFplIdentity
    official_fpl_gameweek_identity: CurrentFplIdentity
    provider_home_team: str = Field(min_length=1, max_length=500)
    provider_away_team: str = Field(min_length=1, max_length=500)
    official_home_team_id: int = Field(gt=0)
    official_home_team_identity: CurrentFplIdentity
    official_home_team_name: str = Field(min_length=1, max_length=500)
    official_away_team_id: int = Field(gt=0)
    official_away_team_identity: CurrentFplIdentity
    official_away_team_name: str = Field(min_length=1, max_length=500)
    provider_commence_time: datetime
    official_fpl_kickoff_at: datetime
    official_deadline_at: datetime
    source_fixture_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_evidence_class: Literal["OFFICIAL", "APPROVED_MANUAL"]
    binding_status: Literal["APPROVED"] = "APPROVED"
    binding_reviewer: str = Field(min_length=1, max_length=160)
    binding_approved_at: datetime
    fixture_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_resolved_fixture(self) -> ResolvedCurrentFixture:
        fixture_identity = self.official_fpl_fixture_identity
        gameweek_identity = self.official_fpl_gameweek_identity
        if (
            fixture_identity.provider_key != "official_fpl"
            or fixture_identity.provider_product != "fantasy_premierleague"
            or fixture_identity.entity_type != "FIXTURE"
            or fixture_identity.identifier_namespace != "fpl.fixture.id"
            or fixture_identity.external_id_text != str(self.official_fpl_fixture_id)
        ):
            raise ValueError("resolved official FPL fixture identity is inconsistent")
        if (
            gameweek_identity.provider_key != "official_fpl"
            or gameweek_identity.provider_product != "fantasy_premierleague"
            or gameweek_identity.entity_type != "GAMEWEEK"
            or gameweek_identity.identifier_namespace != "fpl.event.id"
            or gameweek_identity.season_code != fixture_identity.season_code
        ):
            raise ValueError("resolved official FPL gameweek identity is inconsistent")
        home_identity = self.official_home_team_identity
        if (
            home_identity.provider_key != "official_fpl"
            or home_identity.provider_product != "fantasy_premierleague"
            or home_identity.entity_type != "TEAM"
            or home_identity.identifier_namespace != "fpl.team.id"
            or home_identity.external_id_text != str(self.official_home_team_id)
            or home_identity.season_code != fixture_identity.season_code
        ):
            raise ValueError("resolved official FPL home team identity is inconsistent")
        away_identity = self.official_away_team_identity
        if (
            away_identity.provider_key != "official_fpl"
            or away_identity.provider_product != "fantasy_premierleague"
            or away_identity.entity_type != "TEAM"
            or away_identity.identifier_namespace != "fpl.team.id"
            or away_identity.external_id_text != str(self.official_away_team_id)
            or away_identity.season_code != fixture_identity.season_code
        ):
            raise ValueError("resolved official FPL away team identity is inconsistent")
        if self.official_home_team_id == self.official_away_team_id:
            raise ValueError("resolved fixture home and away teams must differ")
        if self.provider_home_team == self.provider_away_team:
            raise ValueError("resolved provider home and away teams must differ")
        if self.provider_commence_time != self.official_fpl_kickoff_at:
            raise ValueError("provider commence time and FPL kickoff must match exactly")
        if self.provider_commence_time < self.official_deadline_at:
            raise ValueError("resolved fixture starts before the official deadline")
        return self


class CurrentFixtureCoverage(_FrozenIdentityModel):
    """Complete one-to-one target-Gameweek coverage evidence."""

    status: Literal["COMPLETE"] = "COMPLETE"
    provider_event_count: int = Field(gt=0)
    target_fpl_fixture_count: int = Field(gt=0)
    mapped_event_count: int = Field(gt=0)
    unmapped_provider_event_ids: tuple[str, ...] = ()
    unmapped_official_fpl_fixture_ids: tuple[int, ...] = ()
    ambiguous_provider_event_ids: tuple[str, ...] = ()
    duplicate_provider_event_ids: tuple[str, ...] = ()
    duplicate_official_fpl_fixture_ids: tuple[int, ...] = ()
    extra_plan_provider_event_ids: tuple[str, ...] = ()
    extra_plan_official_fpl_fixture_ids: tuple[int, ...] = ()

    @model_validator(mode="after")
    def validate_complete_coverage(self) -> CurrentFixtureCoverage:
        if (
            self.provider_event_count != self.target_fpl_fixture_count
            or self.mapped_event_count != self.provider_event_count
            or self.unmapped_provider_event_ids
            or self.unmapped_official_fpl_fixture_ids
            or self.ambiguous_provider_event_ids
            or self.duplicate_provider_event_ids
            or self.duplicate_official_fpl_fixture_ids
            or self.extra_plan_provider_event_ids
            or self.extra_plan_official_fpl_fixture_ids
        ):
            raise ValueError("complete fixture coverage evidence is inconsistent")
        return self


class FplOddsIdentityMap(_FrozenIdentityModel):
    """Usable, transient and exact FPL/Odds identity bridge for one Gameweek."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["FPL_ODDS_IDENTITY_MAP"] = "FPL_ODDS_IDENTITY_MAP"
    quality_status: Literal["USABLE"] = "USABLE"
    mapping_outcome: Literal["COMPLETE"] = "COMPLETE"
    usage_scope: Literal["CURRENT_DECISION"] = "CURRENT_DECISION"
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    fpl_derived_storage: Literal["DENY"] = "DENY"
    odds_raw_payload_retained: Literal[False] = False
    provider: Literal["the_odds_api"] = "the_odds_api"
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: int = Field(gt=0)
    official_deadline_at: datetime
    mapping_decided_at: datetime
    information_cutoff: datetime
    fpl_input_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_identity_view_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_alias_plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    team_alias_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_identity_map_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_mapping_plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    fixture_mapping_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_algorithm_version: Literal["gw1-fpl-odds-exact-v1"] = "gw1-fpl-odds-exact-v1"
    fixture_match_policy: Literal["TARGET_GW_HOME_AWAY_EXACT_UTC_PLUS_EXPLICIT_BINDING"] = (
        "TARGET_GW_HOME_AWAY_EXACT_UTC_PLUS_EXPLICIT_BINDING"
    )
    kickoff_policy: Literal["EXACT_UTC_EQUALITY"] = "EXACT_UTC_EQUALITY"
    team_mappings: tuple[ResolvedCurrentTeam, ...] = Field(min_length=2)
    fixture_mappings: tuple[ResolvedCurrentFixture, ...] = Field(min_length=1)
    coverage: CurrentFixtureCoverage
    limitations: tuple[str, ...] = Field(min_length=1)
    source_lineage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_final_identity_map(self) -> FplOddsIdentityMap:
        provider_ids = [mapping.provider_event_id for mapping in self.fixture_mappings]
        fixture_ids = [mapping.official_fpl_fixture_id for mapping in self.fixture_mappings]
        team_by_provider = {mapping.provider_team_text: mapping for mapping in self.team_mappings}
        if len(team_by_provider) != len(self.team_mappings):
            raise ValueError("resolved provider team mapping is duplicated")
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("mapped provider event identity is duplicated")
        if len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("mapped official FPL fixture identity is duplicated")
        if self.official_deadline_at != self.information_cutoff:
            raise ValueError("official deadline and information cutoff must be identical")
        if self.mapping_decided_at > self.information_cutoff:
            raise ValueError("mapping decision is after the information cutoff")
        if (
            self.coverage.provider_event_count != len(self.fixture_mappings)
            or self.coverage.target_fpl_fixture_count != len(self.fixture_mappings)
            or self.coverage.mapped_event_count != len(self.fixture_mappings)
        ):
            raise ValueError("fixture coverage counts contradict mapped output")
        for team_mapping in self.team_mappings:
            identity = team_mapping.official_fpl_team_identity
            if (
                identity.provider_key != "official_fpl"
                or identity.provider_product != "fantasy_premierleague"
                or identity.entity_type != "TEAM"
                or identity.identifier_namespace != "fpl.team.id"
                or identity.external_id_text != str(team_mapping.official_fpl_team_id)
                or identity.season_code != self.season_code
            ):
                raise ValueError("resolved team identity contradicts map context")
            if team_mapping.mapping_approved_at > self.mapping_decided_at:
                raise ValueError("team mapping approval is after mapping decision")
        used_provider_teams: set[str] = set()
        for mapping in self.fixture_mappings:
            fixture_identity = mapping.official_fpl_fixture_identity
            gameweek_identity = mapping.official_fpl_gameweek_identity
            if (
                fixture_identity.season_code != self.season_code
                or gameweek_identity.season_code != self.season_code
                or gameweek_identity.external_id_text != str(self.target_gameweek)
            ):
                raise ValueError("mapped fixture is outside the target season or Gameweek")
            if mapping.official_deadline_at != self.official_deadline_at:
                raise ValueError("mapped fixture official deadline is inconsistent")
            if mapping.binding_approved_at > self.mapping_decided_at:
                raise ValueError("fixture binding approval is after mapping decision")
            home = team_by_provider.get(mapping.provider_home_team)
            away = team_by_provider.get(mapping.provider_away_team)
            if (
                home is None
                or home.official_fpl_team_id != mapping.official_home_team_id
                or home.official_fpl_team_identity != mapping.official_home_team_identity
                or home.official_fpl_team_name != mapping.official_home_team_name
                or away is None
                or away.official_fpl_team_id != mapping.official_away_team_id
                or away.official_fpl_team_identity != mapping.official_away_team_identity
                or away.official_fpl_team_name != mapping.official_away_team_name
            ):
                raise ValueError("resolved fixture team mapping is inconsistent")
            used_provider_teams.update((mapping.provider_home_team, mapping.provider_away_team))
        if used_provider_teams != set(team_by_provider):
            raise ValueError("resolved team map contains unused or missing provider teams")
        if self.source_lineage_sha256 != _identity_source_lineage_sha256(self):
            raise ValueError("identity source-lineage hash is inconsistent")
        if self.semantic_sha256 != _fpl_odds_identity_map_sha256(self):
            raise ValueError("FPL/Odds identity-map semantic hash is inconsistent")
        return self

    def fixture(self, provider_event_id: str) -> ResolvedCurrentFixture:
        matches = [
            mapping
            for mapping in self.fixture_mappings
            if mapping.provider_event_id == provider_event_id
        ]
        if len(matches) != 1:
            raise IngestionError(
                "MAPPING_CONFLICT",
                "provider event lacks one resolved official FPL fixture",
                details={"mapping_outcome": "UNKNOWN"},
            )
        return matches[0]


def bind_current_fixture_resolution_request(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    team_plan: CurrentTeamAliasPlan,
    team_map: CurrentTeamIdentityMap,
    fixture_plan: CurrentFixtureMappingPlan,
    *,
    mapping_decided_at: datetime,
) -> CurrentFixtureResolutionRequest:
    """Freeze all source, team-map, and fixture-plan identities before resolution."""

    return CurrentFixtureResolutionRequest(
        mapping_decided_at=mapping_decided_at,
        fpl_input_semantic_sha256=fpl_input.semantic_sha256,
        fpl_identity_view_sha256=current_fpl_identity_view_sha256(fpl_input),
        odds_provider_provenance_sha256=current_odds_provider_provenance_sha256(odds_input),
        odds_identity_semantic_sha256=current_odds_identity_semantic_sha256(odds_input),
        team_alias_plan_version=team_plan.plan_version,
        team_alias_plan_sha256=team_plan.sha256,
        team_identity_map_semantic_sha256=team_map.semantic_sha256,
        fixture_mapping_plan_version=fixture_plan.plan_version,
        fixture_mapping_plan_sha256=fixture_plan.sha256,
    )


def _require_fixture_bound_hashes(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    team_plan: CurrentTeamAliasPlan,
    team_map: CurrentTeamIdentityMap,
    fixture_plan: CurrentFixtureMappingPlan,
    request: CurrentFixtureResolutionRequest,
) -> None:
    recomputed_fpl = current_fpl_input_semantic_sha256(fpl_input)
    checks = {
        "accepted FPL input semantic hash": (fpl_input.semantic_sha256, recomputed_fpl),
        "bound FPL input semantic hash": (request.fpl_input_semantic_sha256, recomputed_fpl),
        "bound FPL identity-view hash": (
            request.fpl_identity_view_sha256,
            current_fpl_identity_view_sha256(fpl_input),
        ),
        "bound odds provider provenance hash": (
            request.odds_provider_provenance_sha256,
            current_odds_provider_provenance_sha256(odds_input),
        ),
        "bound odds identity semantic hash": (
            request.odds_identity_semantic_sha256,
            current_odds_identity_semantic_sha256(odds_input),
        ),
        "bound team alias plan version": (
            request.team_alias_plan_version,
            team_plan.plan_version,
        ),
        "bound team alias plan hash": (request.team_alias_plan_sha256, team_plan.sha256),
        "accepted team identity-map hash": (
            team_map.semantic_sha256,
            _team_identity_map_sha256(team_map),
        ),
        "bound team identity-map hash": (
            request.team_identity_map_semantic_sha256,
            team_map.semantic_sha256,
        ),
        "bound fixture plan version": (
            request.fixture_mapping_plan_version,
            fixture_plan.plan_version,
        ),
        "bound fixture plan hash": (
            request.fixture_mapping_plan_sha256,
            fixture_plan.sha256,
        ),
    }
    for label, (observed, expected) in checks.items():
        if observed != expected:
            raise IngestionError("MAPPING_CONFLICT", f"{label} is inconsistent")


def _require_fixture_context(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    team_plan: CurrentTeamAliasPlan,
    team_map: CurrentTeamIdentityMap,
    fixture_plan: CurrentFixtureMappingPlan,
    request: CurrentFixtureResolutionRequest,
) -> datetime:
    team_request = CurrentTeamResolutionRequest(
        mapping_decided_at=request.mapping_decided_at,
        fpl_input_semantic_sha256=request.fpl_input_semantic_sha256,
        fpl_identity_view_sha256=request.fpl_identity_view_sha256,
        odds_provider_provenance_sha256=request.odds_provider_provenance_sha256,
        odds_identity_semantic_sha256=request.odds_identity_semantic_sha256,
        team_alias_plan_version=request.team_alias_plan_version,
        team_alias_plan_sha256=request.team_alias_plan_sha256,
    )
    _require_exact_bound_hashes(fpl_input, odds_input, team_plan, team_request)
    cutoff = _require_current_context(fpl_input, odds_input, team_plan, team_request)
    if (
        fixture_plan.provider != odds_input.provider
        or fixture_plan.competition_key != fpl_input.competition_key
        or fixture_plan.season_code != fpl_input.season_code
        or fixture_plan.target_gameweek != fpl_input.target_gameweek
        or fixture_plan.team_alias_plan_version != team_plan.plan_version
        or fixture_plan.team_alias_plan_sha256 != team_plan.sha256
    ):
        raise IngestionError("MAPPING_CONFLICT", "fixture mapping plan context is inconsistent")
    if (
        team_map.provider != odds_input.provider
        or team_map.competition_key != fpl_input.competition_key
        or team_map.season_code != fpl_input.season_code
        or team_map.target_gameweek != fpl_input.target_gameweek
        or team_map.mapping_decided_at != request.mapping_decided_at
        or team_map.information_cutoff != cutoff
        or team_map.fpl_input_semantic_sha256 != request.fpl_input_semantic_sha256
        or team_map.fpl_identity_view_sha256 != request.fpl_identity_view_sha256
        or team_map.odds_provider_provenance_sha256 != request.odds_provider_provenance_sha256
        or team_map.odds_identity_semantic_sha256 != request.odds_identity_semantic_sha256
        or team_map.team_alias_plan_sha256 != team_plan.sha256
        or team_map.team_alias_plan_version != team_plan.plan_version
    ):
        raise IngestionError("MAPPING_CONFLICT", "team identity map context is inconsistent")
    if fixture_plan.approved_at > request.mapping_decided_at or any(
        mapping.approved_at > request.mapping_decided_at
        for mapping in fixture_plan.fixture_mappings
    ):
        raise IngestionError("POST_CUTOFF", "fixture mapping was approved after decision time")
    target_identity = fpl_input.target_event.identity
    if (
        target_identity.entity_type != "GAMEWEEK"
        or target_identity.identifier_namespace != "fpl.event.id"
        or target_identity.external_id_text != str(fpl_input.target_gameweek)
        or target_identity.season_code != fpl_input.season_code
        or fpl_input.target_event.source_semantic_sha256
        != fpl_input.provenance.bootstrap_semantic_sha256
    ):
        raise IngestionError("MAPPING_CONFLICT", "target Gameweek identity is inconsistent")
    if fpl_input.target_event.deadline_at != cutoff:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "official FPL deadline and current information cutoff differ",
            details={
                "mapping_outcome": "QUALITY_BLOCKED",
                "reason": "DEADLINE_CUTOFF_MISMATCH",
            },
        )
    return cutoff


def _target_gameweek_fixtures(
    fpl_input: CurrentFplInputBundle,
) -> tuple[CurrentFplFixture, ...]:
    fixtures = tuple(
        fixture
        for fixture in fpl_input.fixtures
        if fixture.event_identity == fpl_input.target_event.identity
    )
    if not fixtures:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "official FPL input has no target-Gameweek fixtures",
            details={
                "mapping_outcome": "QUALITY_BLOCKED",
                "reason": "NO_TARGET_GAMEWEEK_FIXTURES",
            },
        )
    fixture_ids = [fixture.provider_fixture_id for fixture in fixtures]
    identity_hashes = [fixture.identity.canonical_lookup_sha256 for fixture in fixtures]
    if len(fixture_ids) != len(set(fixture_ids)) or len(identity_hashes) != len(
        set(identity_hashes)
    ):
        raise IngestionError(
            "MAPPING_CONFLICT",
            "target-Gameweek FPL fixture identity is ambiguous",
            details={
                "mapping_outcome": "AMBIGUOUS",
                "reason": "DUPLICATE_OFFICIAL_FIXTURE_IDENTITY",
            },
        )
    for fixture in fixtures:
        identity = fixture.identity
        if (
            fixture.source_semantic_sha256 != fpl_input.provenance.fixtures_semantic_sha256
            or identity.provider_key != "official_fpl"
            or identity.entity_type != "FIXTURE"
            or identity.identifier_namespace != "fpl.fixture.id"
            or identity.external_id_text != str(fixture.provider_fixture_id)
            or identity.season_code != fpl_input.season_code
        ):
            raise IngestionError(
                "MAPPING_CONFLICT", "official target-Gameweek fixture identity is inconsistent"
            )
        if fixture.kickoff_at is None:
            raise IngestionError(
                "QUALITY_BLOCKED",
                "target-Gameweek fixture has no published kickoff",
                details={
                    "mapping_outcome": "QUALITY_BLOCKED",
                    "reason": "KICKOFF_NOT_PUBLISHED",
                    "official_fpl_fixture_id": fixture.provider_fixture_id,
                },
            )
    return tuple(sorted(fixtures, key=lambda item: item.provider_fixture_id))


def _event_identity_sha256(event: CurrentOddsEvent) -> str:
    return canonical_sha256(
        {
            "commence_time": event.commence_time.isoformat(),
            "provider_away_team": event.provider_away_team,
            "provider_event_id": event.provider_event_id,
            "provider_home_team": event.provider_home_team,
            "sport_key": event.sport_key,
        }
    )


def _unknown_fixture(
    event: CurrentOddsEvent,
    *,
    reason: str,
) -> IngestionError:
    return IngestionError(
        "MAPPING_CONFLICT",
        "provider event has no exact target-Gameweek fixture mapping",
        details={
            "mapping_outcome": "UNKNOWN",
            "provider_event_id": event.provider_event_id,
            "reason": reason,
        },
    )


def _exact_fixture_candidate(
    fpl_input: CurrentFplInputBundle,
    target_fixtures: tuple[CurrentFplFixture, ...],
    event: CurrentOddsEvent,
    home: ResolvedCurrentTeam,
    away: ResolvedCurrentTeam,
) -> CurrentFplFixture:
    candidates = [
        fixture
        for fixture in target_fixtures
        if fixture.home_team_identity == home.official_fpl_team_identity
        and fixture.away_team_identity == away.official_fpl_team_identity
        and fixture.kickoff_at == event.commence_time
    ]
    if len(candidates) > 1:
        raise IngestionError(
            "MAPPING_CONFLICT",
            "provider event has multiple exact target-Gameweek fixture candidates",
            details={
                "mapping_outcome": "AMBIGUOUS",
                "provider_event_id": event.provider_event_id,
                "official_fpl_fixture_ids": sorted(
                    fixture.provider_fixture_id for fixture in candidates
                ),
                "reason": "MULTIPLE_EXACT_CANDIDATES",
            },
        )
    if candidates:
        return candidates[0]
    outside_target = any(
        fixture.event_identity != fpl_input.target_event.identity
        and fixture.home_team_identity == home.official_fpl_team_identity
        and fixture.away_team_identity == away.official_fpl_team_identity
        and fixture.kickoff_at == event.commence_time
        for fixture in fpl_input.fixtures
    )
    if outside_target:
        raise _unknown_fixture(event, reason="OUTSIDE_TARGET_GAMEWEEK")
    reversed_orientation = any(
        fixture.home_team_identity == away.official_fpl_team_identity
        and fixture.away_team_identity == home.official_fpl_team_identity
        and fixture.kickoff_at == event.commence_time
        for fixture in target_fixtures
    )
    if reversed_orientation:
        raise _unknown_fixture(event, reason="HOME_AWAY_ORIENTATION_MISMATCH")
    kickoff_mismatch = any(
        fixture.home_team_identity == home.official_fpl_team_identity
        and fixture.away_team_identity == away.official_fpl_team_identity
        for fixture in target_fixtures
    )
    if kickoff_mismatch:
        raise _unknown_fixture(event, reason="EXACT_KICKOFF_MISMATCH")
    raise _unknown_fixture(event, reason="EXACT_FIXTURE_NOT_FOUND")


def _validate_explicit_binding(
    event: CurrentOddsEvent,
    home: ResolvedCurrentTeam,
    away: ResolvedCurrentTeam,
    fixture: CurrentFplFixture,
    binding: CurrentFixtureBinding,
) -> None:
    if (
        binding.expected_home_team_id != home.official_fpl_team_id
        or binding.expected_home_team_identity != home.official_fpl_team_identity
        or binding.expected_away_team_id != away.official_fpl_team_id
        or binding.expected_away_team_identity != away.official_fpl_team_identity
        or binding.expected_commence_time != event.commence_time
    ):
        raise _unknown_fixture(event, reason="EXPLICIT_BINDING_CONTRADICTS_PROVIDER_EVENT")
    if (
        binding.official_fpl_fixture_id != fixture.provider_fixture_id
        or binding.canonical_fixture_identity != fixture.identity
        or binding.expected_home_team_identity != fixture.home_team_identity
        or binding.expected_away_team_identity != fixture.away_team_identity
        or binding.expected_commence_time != fixture.kickoff_at
    ):
        raise _unknown_fixture(event, reason="EXPLICIT_BINDING_STALE_AGAINST_FPL")


def _resolved_fixture(
    fpl_input: CurrentFplInputBundle,
    event: CurrentOddsEvent,
    home: ResolvedCurrentTeam,
    away: ResolvedCurrentTeam,
    fixture: CurrentFplFixture,
    binding: CurrentFixtureBinding,
) -> ResolvedCurrentFixture:
    kickoff_at = fixture.kickoff_at
    if kickoff_at is None:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "mapped official FPL fixture has no published kickoff",
            details={"mapping_outcome": "QUALITY_BLOCKED"},
        )
    return ResolvedCurrentFixture(
        provider_event_id=event.provider_event_id,
        provider_event_identity_sha256=_event_identity_sha256(event),
        official_fpl_fixture_id=fixture.provider_fixture_id,
        official_fpl_fixture_identity=fixture.identity,
        official_fpl_gameweek_identity=fpl_input.target_event.identity,
        provider_home_team=event.provider_home_team,
        provider_away_team=event.provider_away_team,
        official_home_team_id=home.official_fpl_team_id,
        official_home_team_identity=home.official_fpl_team_identity,
        official_home_team_name=home.official_fpl_team_name,
        official_away_team_id=away.official_fpl_team_id,
        official_away_team_identity=away.official_fpl_team_identity,
        official_away_team_name=away.official_fpl_team_name,
        provider_commence_time=event.commence_time,
        official_fpl_kickoff_at=kickoff_at,
        official_deadline_at=fpl_input.target_event.deadline_at,
        source_fixture_semantic_sha256=fixture.source_semantic_sha256,
        binding_evidence_class=binding.evidence_class,
        binding_reviewer=binding.reviewer,
        binding_approved_at=binding.approved_at,
        fixture_binding_sha256=binding.sha256,
    )


def _identity_source_lineage_sha256(value: FplOddsIdentityMap) -> str:
    return canonical_sha256(
        {
            "fixture_mapping_plan_sha256": value.fixture_mapping_plan_sha256,
            "fixture_mapping_plan_version": value.fixture_mapping_plan_version,
            "fpl_identity_view_sha256": value.fpl_identity_view_sha256,
            "fpl_input_semantic_sha256": value.fpl_input_semantic_sha256,
            "odds_identity_semantic_sha256": value.odds_identity_semantic_sha256,
            "odds_provider_provenance_sha256": value.odds_provider_provenance_sha256,
            "team_alias_plan_sha256": value.team_alias_plan_sha256,
            "team_alias_plan_version": value.team_alias_plan_version,
            "team_identity_map_semantic_sha256": value.team_identity_map_semantic_sha256,
        }
    )


def _fpl_odds_identity_map_sha256(value: FplOddsIdentityMap) -> str:
    team_mappings = sorted(
        (mapping.model_dump(mode="json") for mapping in value.team_mappings),
        key=lambda item: (item["provider_team_text"], item["official_fpl_team_id"]),
    )
    fixture_mappings = sorted(
        (mapping.model_dump(mode="json") for mapping in value.fixture_mappings),
        key=lambda item: (item["provider_event_id"], item["official_fpl_fixture_id"]),
    )
    return canonical_sha256(
        {
            "competition_key": value.competition_key,
            "contract": value.contract,
            "coverage": value.coverage.model_dump(mode="json"),
            "fixture_mapping_plan_sha256": value.fixture_mapping_plan_sha256,
            "fixture_mapping_plan_version": value.fixture_mapping_plan_version,
            "fixture_match_policy": value.fixture_match_policy,
            "fixture_mappings": fixture_mappings,
            "fpl_derived_storage": value.fpl_derived_storage,
            "fpl_identity_view_sha256": value.fpl_identity_view_sha256,
            "fpl_input_semantic_sha256": value.fpl_input_semantic_sha256,
            "information_cutoff": value.information_cutoff.isoformat(),
            "kickoff_policy": value.kickoff_policy,
            "limitations": sorted(value.limitations),
            "mapping_algorithm_version": value.mapping_algorithm_version,
            "mapping_decided_at": value.mapping_decided_at.isoformat(),
            "mapping_outcome": value.mapping_outcome,
            "odds_identity_semantic_sha256": value.odds_identity_semantic_sha256,
            "official_deadline_at": value.official_deadline_at.isoformat(),
            "persistence_performed": value.persistence_performed,
            "provider": value.provider,
            "quality_status": value.quality_status,
            "schema_version": value.schema_version,
            "season_code": value.season_code,
            "storage_mode": value.storage_mode,
            "target_gameweek": value.target_gameweek,
            "team_alias_plan_sha256": value.team_alias_plan_sha256,
            "team_alias_plan_version": value.team_alias_plan_version,
            "team_mappings": team_mappings,
            "usage_scope": value.usage_scope,
        }
    )


def resolve_current_fixture_identities(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    team_plan: CurrentTeamAliasPlan,
    team_map: CurrentTeamIdentityMap,
    fixture_plan: CurrentFixtureMappingPlan,
    request: CurrentFixtureResolutionRequest,
) -> FplOddsIdentityMap:
    """Resolve every current provider event to one exact target-Gameweek FPL fixture."""

    _require_fixture_bound_hashes(
        fpl_input,
        odds_input,
        team_plan,
        team_map,
        fixture_plan,
        request,
    )
    cutoff = _require_fixture_context(
        fpl_input,
        odds_input,
        team_plan,
        team_map,
        fixture_plan,
        request,
    )
    target_fixtures = _target_gameweek_fixtures(fpl_input)
    provider_event_ids = [event.provider_event_id for event in odds_input.events]
    if len(provider_event_ids) != len(set(provider_event_ids)):
        raise IngestionError(
            "MAPPING_CONFLICT",
            "provider event identity is duplicated",
            details={
                "mapping_outcome": "AMBIGUOUS",
                "reason": "DUPLICATE_PROVIDER_EVENT_IDENTITY",
            },
        )

    resolved: list[ResolvedCurrentFixture] = []
    for event in sorted(odds_input.events, key=lambda item: item.provider_event_id):
        if event.commence_time < fpl_input.target_event.deadline_at:
            raise IngestionError(
                "QUALITY_BLOCKED",
                "provider event starts before the official FPL deadline",
                details={
                    "mapping_outcome": "QUALITY_BLOCKED",
                    "provider_event_id": event.provider_event_id,
                    "reason": "EVENT_BEFORE_OFFICIAL_DEADLINE",
                },
            )
        home = team_map.team(event.provider_home_team)
        away = team_map.team(event.provider_away_team)
        binding = fixture_plan.fixture(event.provider_event_id)
        fixture = _exact_fixture_candidate(
            fpl_input,
            target_fixtures,
            event,
            home,
            away,
        )
        _validate_explicit_binding(event, home, away, fixture, binding)
        resolved.append(_resolved_fixture(fpl_input, event, home, away, fixture, binding))

    mapped_provider_ids = {mapping.provider_event_id for mapping in resolved}
    mapped_fixture_ids = {mapping.official_fpl_fixture_id for mapping in resolved}
    target_fixture_ids = {fixture.provider_fixture_id for fixture in target_fixtures}
    provider_ids = set(provider_event_ids)
    plan_provider_ids = {mapping.provider_event_id for mapping in fixture_plan.fixture_mappings}
    plan_fixture_ids = {
        mapping.official_fpl_fixture_id for mapping in fixture_plan.fixture_mappings
    }
    if len(mapped_fixture_ids) != len(resolved):
        raise IngestionError(
            "MAPPING_CONFLICT",
            "multiple provider events map to one official FPL fixture",
            details={
                "mapping_outcome": "AMBIGUOUS",
                "reason": "MANY_TO_ONE_FIXTURE_MAPPING",
            },
        )

    unmapped_provider = tuple(sorted(provider_ids - mapped_provider_ids))
    unmapped_fpl = tuple(sorted(target_fixture_ids - mapped_fixture_ids))
    extra_plan_provider = tuple(sorted(plan_provider_ids - provider_ids))
    extra_plan_fpl = tuple(sorted(plan_fixture_ids - target_fixture_ids))
    complete = (
        provider_ids == mapped_provider_ids == plan_provider_ids
        and target_fixture_ids == mapped_fixture_ids == plan_fixture_ids
        and len(provider_ids) == len(target_fixture_ids)
    )
    if not complete:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "target-Gameweek identity coverage is incomplete",
            details={
                "mapping_outcome": "QUALITY_BLOCKED",
                "reason": "INCOMPLETE_ONE_TO_ONE_COVERAGE",
                "unmapped_provider_event_ids": unmapped_provider,
                "unmapped_official_fpl_fixture_ids": unmapped_fpl,
                "extra_plan_provider_event_ids": extra_plan_provider,
                "extra_plan_official_fpl_fixture_ids": extra_plan_fpl,
            },
        )

    fixture_mappings = tuple(resolved)
    coverage = CurrentFixtureCoverage(
        provider_event_count=len(provider_ids),
        target_fpl_fixture_count=len(target_fixture_ids),
        mapped_event_count=len(fixture_mappings),
    )
    limitations = (
        "IDENTITY_ONLY_NO_MARKET_PROBABILITIES",
        "OPERATOR_SUPPLIED_REVIEWED_BINDINGS",
        "PRIVATE_TRANSIENT_CURRENT_DECISION_USE_ONLY",
    )
    provisional = FplOddsIdentityMap.model_construct(
        schema_version="1.0.0",
        contract="FPL_ODDS_IDENTITY_MAP",
        quality_status="USABLE",
        mapping_outcome="COMPLETE",
        usage_scope="CURRENT_DECISION",
        storage_mode="TRANSIENT_IN_MEMORY",
        persistence_performed=False,
        database_accessed=False,
        fpl_derived_storage="DENY",
        odds_raw_payload_retained=False,
        provider="the_odds_api",
        competition_key="PL",
        season_code="2026/27",
        mapping_algorithm_version="gw1-fpl-odds-exact-v1",
        fixture_match_policy="TARGET_GW_HOME_AWAY_EXACT_UTC_PLUS_EXPLICIT_BINDING",
        kickoff_policy="EXACT_UTC_EQUALITY",
        target_gameweek=fpl_input.target_gameweek,
        official_deadline_at=fpl_input.target_event.deadline_at,
        mapping_decided_at=request.mapping_decided_at,
        information_cutoff=cutoff,
        fpl_input_semantic_sha256=request.fpl_input_semantic_sha256,
        fpl_identity_view_sha256=request.fpl_identity_view_sha256,
        odds_provider_provenance_sha256=request.odds_provider_provenance_sha256,
        odds_identity_semantic_sha256=request.odds_identity_semantic_sha256,
        team_alias_plan_version=team_plan.plan_version,
        team_alias_plan_sha256=team_plan.sha256,
        team_identity_map_semantic_sha256=team_map.semantic_sha256,
        fixture_mapping_plan_version=fixture_plan.plan_version,
        fixture_mapping_plan_sha256=fixture_plan.sha256,
        team_mappings=team_map.team_mappings,
        fixture_mappings=fixture_mappings,
        coverage=coverage,
        limitations=limitations,
        source_lineage_sha256="0" * 64,
        semantic_sha256="0" * 64,
    )
    source_lineage_sha256 = _identity_source_lineage_sha256(provisional)
    with_lineage = provisional.model_copy(update={"source_lineage_sha256": source_lineage_sha256})
    payload = with_lineage.model_dump(mode="python")
    payload["semantic_sha256"] = _fpl_odds_identity_map_sha256(with_lineage)
    return FplOddsIdentityMap.model_validate(payload)
