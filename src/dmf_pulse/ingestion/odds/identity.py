"""Fail-closed current official-FPL to provider identity resolution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplIdentity,
    CurrentFplInputBundle,
    CurrentFplTeam,
)
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
from dmf_pulse.ingestion.odds.mapping import CurrentTeamAliasMapping, CurrentTeamAliasPlan


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
