"""Private transient current official-FPL to LIVE-ODDS identity resolution.

The accepted source objects remain unchanged and provider-native. This module consumes them with
operator-supplied in-memory mapping plans, uses exact equality only, and returns an immutable
private bridge. It has no network, database, persistence, cache, backup, CLI, or artifact-write
boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplFixture,
    CurrentFplIdentity,
    CurrentFplInputBundle,
    CurrentFplTeam,
)
from dmf_pulse.ingestion.odds.current import (
    CurrentOddsEvent,
    OddsProviderCurrentInput,
    current_odds_market_semantic_sha256,
)
from dmf_pulse.ingestion.odds.mapping import (
    CURRENT_MAPPING_ALGORITHM_VERSION,
    CurrentFixtureBinding,
    CurrentFixtureMappingPlan,
    CurrentTeamAliasMapping,
    CurrentTeamAliasPlan,
)

CURRENT_TEAM_RESOLUTION_REQUEST_VERSION: Literal["current-fpl-odds-team-resolution-request-v1"] = (
    "current-fpl-odds-team-resolution-request-v1"
)
CURRENT_FIXTURE_RESOLUTION_REQUEST_VERSION: Literal[
    "current-fpl-odds-fixture-resolution-request-v1"
] = "current-fpl-odds-fixture-resolution-request-v1"

_LIMITATIONS = (
    "EXACT_BINDINGS_INVALIDATED_BY_RESCHEDULE",
    "IDENTITY_ONLY_NO_MARKET_PROBABILITIES",
    "OPERATOR_SUPPLIED_REVIEWED_BINDINGS",
    "PRIVATE_TRANSIENT_CURRENT_DECISION_USE_ONLY",
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
    """Exact source and plan identities frozen before team resolution."""

    contract_version: Literal["current-fpl-odds-team-resolution-request-v1"] = (
        CURRENT_TEAM_RESOLUTION_REQUEST_VERSION
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

    @model_validator(mode="after")
    def validate_team_identity(self) -> ResolvedCurrentTeam:
        identity = self.official_fpl_team_identity
        if (
            identity.provider_key != "official_fpl"
            or identity.provider_product != "fantasy_premierleague"
            or identity.entity_type != "TEAM"
            or identity.identifier_namespace != "fpl.team.id"
            or identity.external_id_text != str(self.official_fpl_team_id)
        ):
            raise ValueError("resolved official FPL team identity is inconsistent")
        return self


class CurrentTeamIdentityMap(_FrozenIdentityModel):
    """Private exact team bridge bound to one source pair and transient plan."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["FPL_ODDS_TEAM_IDENTITY_MAP"] = "FPL_ODDS_TEAM_IDENTITY_MAP"
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
    mapping_decided_at: datetime
    information_cutoff: datetime
    fpl_usable_at: datetime
    odds_usable_at: datetime
    fpl_input_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_identity_view_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_alias_plan: CurrentTeamAliasPlan
    team_alias_plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    team_alias_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_algorithm_version: Literal["current-fpl-odds-exact-v1"] = (
        CURRENT_MAPPING_ALGORITHM_VERSION
    )
    observed_provider_team_texts: tuple[str, ...] = Field(min_length=2)
    team_mappings: tuple[ResolvedCurrentTeam, ...] = Field(min_length=2)
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_identity_map(self) -> CurrentTeamIdentityMap:
        if (
            self.team_alias_plan_version != self.team_alias_plan.plan_version
            or self.team_alias_plan_sha256 != self.team_alias_plan.sha256
            or self.team_alias_plan.provider != self.provider
            or self.team_alias_plan.competition_key != self.competition_key
            or self.team_alias_plan.season_code != self.season_code
            or self.team_alias_plan.mapping_algorithm_version != self.mapping_algorithm_version
        ):
            raise ValueError("team alias plan lineage contradicts identity-map context")
        if not (
            self.fpl_usable_at <= self.mapping_decided_at <= self.information_cutoff
            and self.odds_usable_at <= self.mapping_decided_at
            and self.team_alias_plan.approved_at <= self.mapping_decided_at
        ):
            raise ValueError("team identity-map temporal context is inconsistent")
        by_provider = {mapping.provider_team_text: mapping for mapping in self.team_mappings}
        by_team = {mapping.official_fpl_team_id: mapping for mapping in self.team_mappings}
        if len(by_provider) != len(self.team_mappings) or len(by_team) != len(self.team_mappings):
            raise ValueError("resolved team identities are duplicated or ambiguous")
        aliases = {
            mapping.provider_team_text: mapping for mapping in self.team_alias_plan.team_mappings
        }
        canonical_observed = tuple(sorted(set(self.observed_provider_team_texts)))
        if self.observed_provider_team_texts != canonical_observed:
            raise ValueError("observed provider team participants are not canonical")
        if set(canonical_observed) != set(aliases) or set(canonical_observed) != set(by_provider):
            raise ValueError(
                "resolved team identities differ from exact observed provider participants"
            )
        for provider_text, resolved in by_provider.items():
            alias = aliases[provider_text]
            if (
                resolved.provider != alias.provider
                or resolved.official_fpl_team_id != alias.official_fpl_team_id
                or resolved.official_fpl_team_identity != alias.canonical_team_identity
                or resolved.official_fpl_team_name != alias.official_fpl_team_name
                or resolved.mapping_evidence_class != alias.evidence_class
                or resolved.mapping_status != alias.status
                or resolved.mapping_reviewer != alias.reviewer
                or resolved.mapping_approved_at != alias.approved_at
                or resolved.team_alias_mapping_sha256 != alias.sha256
                or resolved.mapping_approved_at > self.mapping_decided_at
                or resolved.official_fpl_team_identity.season_code != self.season_code
            ):
                raise ValueError("resolved team mapping contradicts approved alias material")
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


def current_fpl_identity_view_sha256(fpl_input: CurrentFplInputBundle) -> str:
    """Hash only the exact accepted FPL identity view consumed by this bridge."""

    teams = [
        {
            "identity": team.identity.model_dump(mode="json"),
            "official_name": team.official_name,
            "provider_team_id": team.provider_team_id,
            "source_semantic_sha256": team.source_semantic_sha256,
        }
        for team in sorted(fpl_input.teams, key=lambda item: item.provider_team_id)
    ]
    target_fixtures = [
        fixture
        for fixture in fpl_input.fixtures
        if fixture.event_identity == fpl_input.target_event.identity
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
            "kickoff_at": (
                fixture.kickoff_at.isoformat() if fixture.kickoff_at is not None else None
            ),
            "provider_fixture_id": fixture.provider_fixture_id,
            "source_semantic_sha256": fixture.source_semantic_sha256,
        }
        for fixture in sorted(target_fixtures, key=lambda item: item.provider_fixture_id)
    ]
    return canonical_sha256(
        {
            "bootstrap_source_semantic_sha256": (fpl_input.provenance.bootstrap_semantic_sha256),
            "competition_key": fpl_input.competition_key,
            "contract_version": "current-fpl-odds-fpl-identity-view-v1",
            "fixtures_source_semantic_sha256": (fpl_input.provenance.fixtures_semantic_sha256),
            "fpl_input_semantic_sha256": fpl_input.semantic_sha256,
            "information_cutoff": fpl_input.provenance.information_cutoff.isoformat(),
            "season_code": fpl_input.season_code,
            "target_deadline_at": fpl_input.target_event.deadline_at.isoformat(),
            "target_event": fpl_input.target_event.model_dump(mode="json"),
            "target_fixtures": fixtures,
            "target_gameweek": fpl_input.target_gameweek,
            "teams": teams,
            "usable_at": fpl_input.provenance.usable_at.isoformat(),
        }
    )


def current_odds_provider_provenance_sha256(odds_input: OddsProviderCurrentInput) -> str:
    """Hash accepted acquisition provenance independently from event identity."""

    return canonical_sha256(odds_input.provenance.model_dump(mode="json"))


def current_odds_identity_semantic_sha256(odds_input: OddsProviderCurrentInput) -> str:
    """Hash provider event identity while excluding bookmaker and price material."""

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
        key=lambda item: (
            item["provider_event_id"],
            item["provider_home_team"],
            item["provider_away_team"],
            item["commence_time"],
        ),
    )
    return canonical_sha256(
        {
            "contract_version": "current-fpl-odds-event-identity-view-v1",
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
    """Bind exact inputs and alias authority before resolving any team."""

    return CurrentTeamResolutionRequest(
        mapping_decided_at=mapping_decided_at,
        fpl_input_semantic_sha256=fpl_input.semantic_sha256,
        fpl_identity_view_sha256=current_fpl_identity_view_sha256(fpl_input),
        odds_provider_provenance_sha256=current_odds_provider_provenance_sha256(odds_input),
        odds_identity_semantic_sha256=current_odds_identity_semantic_sha256(odds_input),
        team_alias_plan_version=plan.plan_version,
        team_alias_plan_sha256=plan.sha256,
    )


def _revalidate_source_structures(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
) -> None:
    try:
        CurrentFplInputBundle.model_validate(fpl_input.model_dump(mode="python"))
        OddsProviderCurrentInput.model_validate(odds_input.model_dump(mode="python"))
    except ValidationError as exc:
        raise IngestionError(
            "MAPPING_CONFLICT", "current source object failed structural revalidation"
        ) from exc
    if odds_input.market_semantic_sha256 != current_odds_market_semantic_sha256(odds_input):
        raise IngestionError(
            "MAPPING_CONFLICT", "accepted LIVE-ODDS market semantic hash is inconsistent"
        )


def _require_exact_bound_hashes(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    plan: CurrentTeamAliasPlan,
    request: CurrentTeamResolutionRequest,
) -> None:
    checks = {
        "accepted FPL input semantic hash": (
            fpl_input.semantic_sha256,
            fpl_input.provenance.input_bundle_semantic_sha256,
        ),
        "bound FPL input semantic hash": (
            request.fpl_input_semantic_sha256,
            fpl_input.semantic_sha256,
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
        "bound team alias plan hash": (request.team_alias_plan_sha256, plan.sha256),
        "bound team alias plan version": (
            request.team_alias_plan_version,
            plan.plan_version,
        ),
    }
    for label, (observed, expected) in checks.items():
        if observed != expected:
            raise IngestionError("MAPPING_CONFLICT", f"{label} is inconsistent")


def _require_source_rights(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
) -> None:
    fpl_decisions = tuple(
        (str(decision.capability), decision.decision) for decision in fpl_input.rights.decisions
    )
    direct = fpl_input.rights.rights_profile_id == "fpl_official_private_operator_initiated_read_v1"
    expected_fpl_decisions = (
        (
            ("automated_access", "ALLOW"),
            ("transient_processing", "ALLOW"),
            ("private_internal_use", "ALLOW"),
            ("raw_storage", "DENY"),
            ("derived_storage", "DENY"),
        )
        if direct
        else (
            ("manual_import", "ALLOW"),
            ("transient_processing", "ALLOW"),
            ("private_internal_use", "ALLOW"),
            ("automated_access", "DENY"),
            ("raw_storage", "DENY"),
            ("derived_storage", "DENY"),
        )
    )
    if (
        fpl_decisions != expected_fpl_decisions
        or fpl_input.rights.rights_profile_id
        not in {
            "fpl_official_private_manual_v1",
            "fpl_official_private_operator_initiated_read_v1",
        }
        or fpl_input.rights.rights_profile_version != "1.0.0"
        or fpl_input.rights.automated_access_profile_value != ("ALLOW" if direct else "DENY")
        or fpl_input.rights.raw_storage_profile_value != "DENY"
        or fpl_input.rights.derived_storage_profile_value not in {"UNKNOWN", "DENY"}
        or fpl_input.rights.automated_access != ("ALLOW" if direct else "DENY")
        or fpl_input.rights.raw_storage != "DENY"
        or fpl_input.rights.derived_storage != "DENY"
        or fpl_input.rights.cache != "DENY"
        or fpl_input.rights.backup != "DENY"
        or fpl_input.rights.database_accessed is not False
        or fpl_input.rights.raw_storage_performed is not False
        or fpl_input.rights.derived_storage_performed is not False
        or fpl_input.rights.operator_delete_required != (not direct)
        or fpl_input.rights.disclosure_mode != "SAFE_SUMMARY_ONLY"
        or fpl_input.provenance.transport_called is not direct
        or fpl_input.provenance.database_accessed is not False
        or fpl_input.provenance.raw_storage_performed is not False
        or fpl_input.provenance.derived_storage_performed is not False
    ):
        raise IngestionError("RIGHTS_BLOCKED", "current FPL identity use violates source rights")
    odds_rights = odds_input.rights
    if (
        odds_rights.rights_profile_id != "the_odds_api_private_analytics_v1"
        or odds_rights.rights_profile_version != "1.0.0"
        or odds_rights.automated_access_declared != "ALLOW"
        or odds_rights.automated_access != "ALLOW"
        or odds_rights.transient_processing_declared != "ALLOW"
        or odds_rights.transient_processing != "ALLOW"
        or odds_rights.derived_storage_declared != "ALLOW"
        or odds_rights.derived_storage != "ALLOW"
        or odds_rights.private_internal_use_declared != "ALLOW"
        or odds_rights.private_internal_use != "ALLOW"
        or odds_rights.raw_storage_declared != "UNKNOWN"
        or odds_rights.raw_storage != "DENY"
        or odds_rights.public_display_declared != "DENY"
        or odds_rights.public_display != "DENY"
        or odds_rights.redistribution_declared != "DENY"
        or odds_rights.redistribution != "DENY"
        or odds_rights.backup_declared != "UNKNOWN"
        or odds_rights.backup != "DENY"
        or odds_rights.model_training_declared != "UNKNOWN"
        or odds_rights.model_training != "DENY"
        or odds_rights.raw_retention_seconds != 0
        or odds_rights.termination_deletion_required is not True
        or odds_rights.raw_payload_retained is not False
        or odds_input.provenance.raw_payload_retained is not False
    ):
        raise IngestionError("RIGHTS_BLOCKED", "LIVE-ODDS identity use violates source rights")


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
        or fpl_input.competition_key != plan.competition_key
        or fpl_input.season_code != plan.season_code
        or plan.provider != odds_input.provider
        or fpl_input.target_gameweek <= 0
    ):
        raise IngestionError("MAPPING_CONFLICT", "mapping context contradicts current inputs")
    fpl_cutoff = fpl_input.provenance.information_cutoff
    odds_cutoff = odds_input.temporal.information_cutoff
    if fpl_cutoff != odds_cutoff:
        raise IngestionError("MAPPING_CONFLICT", "current input cutoffs are not identical")
    if fpl_cutoff > fpl_input.target_event.deadline_at:
        raise IngestionError("POST_CUTOFF", "common cutoff exceeds the official target deadline")
    decided_at = request.mapping_decided_at
    if decided_at > fpl_cutoff:
        raise IngestionError("POST_CUTOFF", "mapping decision is after the information cutoff")
    earliest = max(
        fpl_input.provenance.usable_at,
        odds_input.temporal.usable_at,
        plan.approved_at,
    )
    if decided_at < earliest or any(
        mapping.approved_at > decided_at for mapping in plan.team_mappings
    ):
        raise IngestionError("POST_CUTOFF", "mapping decision predates required usable authority")
    _require_source_rights(fpl_input, odds_input)
    return fpl_cutoff


def _team_by_id(fpl_input: CurrentFplInputBundle) -> dict[int, CurrentFplTeam]:
    by_id: dict[int, CurrentFplTeam] = {}
    identity_hashes: set[str] = set()
    for team in fpl_input.teams:
        if (
            team.provider_team_id in by_id
            or team.identity.canonical_lookup_sha256 in identity_hashes
            or team.source_semantic_sha256 != fpl_input.provenance.bootstrap_semantic_sha256
            or team.identity.season_code != fpl_input.season_code
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
            "database_accessed": value.database_accessed,
            "fpl_derived_storage": value.fpl_derived_storage,
            "fpl_identity_view_sha256": value.fpl_identity_view_sha256,
            "fpl_input_semantic_sha256": value.fpl_input_semantic_sha256,
            "fpl_usable_at": value.fpl_usable_at.isoformat(),
            "information_cutoff": value.information_cutoff.isoformat(),
            "mapping_algorithm_version": value.mapping_algorithm_version,
            "mapping_decided_at": value.mapping_decided_at.isoformat(),
            "odds_identity_semantic_sha256": value.odds_identity_semantic_sha256,
            "odds_provider_provenance_sha256": value.odds_provider_provenance_sha256,
            "odds_raw_payload_retained": value.odds_raw_payload_retained,
            "odds_usable_at": value.odds_usable_at.isoformat(),
            "observed_provider_team_texts": list(value.observed_provider_team_texts),
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
    """Resolve provider team strings by exact approved equality only."""

    _require_source_rights(fpl_input, odds_input)
    _revalidate_source_structures(fpl_input, odds_input)
    try:
        CurrentTeamAliasPlan.model_validate(plan.model_dump(mode="python"))
    except ValidationError as exc:
        raise IngestionError("MAPPING_CONFLICT", "team alias plan is invalid") from exc
    _require_exact_bound_hashes(fpl_input, odds_input, plan, request)
    cutoff = _require_current_context(fpl_input, odds_input, plan, request)
    fpl_teams = _team_by_id(fpl_input)

    observed_provider_team_texts = tuple(
        sorted(
            {
                text
                for event in odds_input.events
                for text in (event.provider_home_team, event.provider_away_team)
            }
        )
    )
    approved_texts = {mapping.provider_team_text for mapping in plan.team_mappings}
    if set(observed_provider_team_texts) != approved_texts:
        raise IngestionError(
            "MAPPING_CONFLICT",
            "team alias plan differs from exact observed provider participants",
        )

    resolved: list[ResolvedCurrentTeam] = []
    for alias in sorted(plan.team_mappings, key=lambda item: item.provider_team_text):
        fpl_team = fpl_teams.get(alias.official_fpl_team_id)
        if fpl_team is None:
            raise IngestionError(
                "MAPPING_CONFLICT", "team alias references no current official FPL team"
            )
        resolved.append(_resolved_team(alias, fpl_team=fpl_team))
    by_provider = {mapping.provider_team_text: mapping for mapping in resolved}
    for event in odds_input.events:
        if (
            by_provider[event.provider_home_team].official_fpl_team_id
            == by_provider[event.provider_away_team].official_fpl_team_id
        ):
            raise IngestionError("MAPPING_CONFLICT", "event participants resolve to one FPL team")

    team_mappings = tuple(resolved)
    provisional = CurrentTeamIdentityMap.model_construct(
        schema_version="1.0.0",
        contract="FPL_ODDS_TEAM_IDENTITY_MAP",
        usage_scope="CURRENT_DECISION",
        storage_mode="TRANSIENT_IN_MEMORY",
        persistence_performed=False,
        database_accessed=False,
        fpl_derived_storage="DENY",
        odds_raw_payload_retained=False,
        provider="the_odds_api",
        competition_key="PL",
        season_code="2026/27",
        mapping_algorithm_version=CURRENT_MAPPING_ALGORITHM_VERSION,
        semantic_sha256="0" * 64,
        target_gameweek=fpl_input.target_gameweek,
        mapping_decided_at=request.mapping_decided_at,
        information_cutoff=cutoff,
        fpl_usable_at=fpl_input.provenance.usable_at,
        odds_usable_at=odds_input.temporal.usable_at,
        fpl_input_semantic_sha256=request.fpl_input_semantic_sha256,
        fpl_identity_view_sha256=request.fpl_identity_view_sha256,
        odds_provider_provenance_sha256=request.odds_provider_provenance_sha256,
        odds_identity_semantic_sha256=request.odds_identity_semantic_sha256,
        team_alias_plan=plan,
        team_alias_plan_version=plan.plan_version,
        team_alias_plan_sha256=plan.sha256,
        observed_provider_team_texts=observed_provider_team_texts,
        team_mappings=team_mappings,
    )
    return CurrentTeamIdentityMap(
        semantic_sha256=_team_identity_map_sha256(provisional),
        target_gameweek=fpl_input.target_gameweek,
        mapping_decided_at=request.mapping_decided_at,
        information_cutoff=cutoff,
        fpl_usable_at=fpl_input.provenance.usable_at,
        odds_usable_at=odds_input.temporal.usable_at,
        fpl_input_semantic_sha256=request.fpl_input_semantic_sha256,
        fpl_identity_view_sha256=request.fpl_identity_view_sha256,
        odds_provider_provenance_sha256=request.odds_provider_provenance_sha256,
        odds_identity_semantic_sha256=request.odds_identity_semantic_sha256,
        team_alias_plan=plan,
        team_alias_plan_version=plan.plan_version,
        team_alias_plan_sha256=plan.sha256,
        observed_provider_team_texts=observed_provider_team_texts,
        team_mappings=team_mappings,
    )


class CurrentFixtureResolutionRequest(_FrozenIdentityModel):
    """Exact source, team-map, and fixture-plan identities frozen before resolution."""

    contract_version: Literal["current-fpl-odds-fixture-resolution-request-v1"] = (
        CURRENT_FIXTURE_RESOLUTION_REQUEST_VERSION
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
    """One bound provider event resolved to one exact target FPL fixture."""

    mapping_status: Literal["MAPPED"] = "MAPPED"
    provider_event_id: str = Field(min_length=1, max_length=500)
    provider_event_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sport_key: Literal["soccer_epl"] = "soccer_epl"
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
        home_identity = self.official_home_team_identity
        away_identity = self.official_away_team_identity
        if (
            fixture_identity.entity_type != "FIXTURE"
            or fixture_identity.identifier_namespace != "fpl.fixture.id"
            or fixture_identity.external_id_text != str(self.official_fpl_fixture_id)
            or gameweek_identity.entity_type != "GAMEWEEK"
            or gameweek_identity.identifier_namespace != "fpl.event.id"
            or home_identity.entity_type != "TEAM"
            or home_identity.identifier_namespace != "fpl.team.id"
            or home_identity.external_id_text != str(self.official_home_team_id)
            or away_identity.entity_type != "TEAM"
            or away_identity.identifier_namespace != "fpl.team.id"
            or away_identity.external_id_text != str(self.official_away_team_id)
            or len(
                {
                    fixture_identity.season_code,
                    gameweek_identity.season_code,
                    home_identity.season_code,
                    away_identity.season_code,
                }
            )
            != 1
        ):
            raise ValueError("resolved official FPL fixture context is inconsistent")
        if (
            self.official_home_team_id == self.official_away_team_id
            or self.provider_home_team == self.provider_away_team
        ):
            raise ValueError("resolved fixture participants are inconsistent")
        if self.provider_commence_time != self.official_fpl_kickoff_at:
            raise ValueError("provider commence time and FPL kickoff must match exactly")
        if self.official_deadline_at >= self.official_fpl_kickoff_at:
            raise ValueError("resolved fixture must start after the official deadline")
        if self.provider_event_identity_sha256 != _event_identity_sha256_from_values(
            provider_event_id=self.provider_event_id,
            sport_key=self.sport_key,
            commence_time=self.provider_commence_time,
            provider_home_team=self.provider_home_team,
            provider_away_team=self.provider_away_team,
        ):
            raise ValueError("provider event identity hash is inconsistent")
        return self


class CurrentFixtureCoverage(_FrozenIdentityModel):
    """Complete target coverage while retaining private outside-target classification."""

    status: Literal["COMPLETE"] = "COMPLETE"
    all_provider_event_count: int = Field(gt=0)
    bound_provider_event_count: int = Field(gt=0)
    outside_target_provider_event_count: int = Field(ge=0)
    target_fpl_fixture_count: int = Field(gt=0)
    mapped_event_count: int = Field(gt=0)
    outside_target_provider_event_ids: tuple[str, ...] = ()
    unmapped_official_fpl_fixture_ids: tuple[int, ...] = ()
    ambiguous_provider_event_ids: tuple[str, ...] = ()
    duplicate_provider_event_ids: tuple[str, ...] = ()
    duplicate_official_fpl_fixture_ids: tuple[int, ...] = ()

    @model_validator(mode="after")
    def validate_complete_coverage(self) -> CurrentFixtureCoverage:
        if (
            self.all_provider_event_count
            != self.bound_provider_event_count + self.outside_target_provider_event_count
            or self.bound_provider_event_count != self.target_fpl_fixture_count
            or self.mapped_event_count != self.target_fpl_fixture_count
            or self.outside_target_provider_event_count
            != len(self.outside_target_provider_event_ids)
            or self.outside_target_provider_event_ids
            != tuple(sorted(set(self.outside_target_provider_event_ids)))
            or self.unmapped_official_fpl_fixture_ids
            or self.ambiguous_provider_event_ids
            or self.duplicate_provider_event_ids
            or self.duplicate_official_fpl_fixture_ids
        ):
            raise ValueError("complete fixture coverage evidence is inconsistent")
        return self


class FplOddsIdentityMap(_FrozenIdentityModel):
    """Usable private non-persistent identity bridge for one target Gameweek."""

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
    fpl_usable_at: datetime
    odds_usable_at: datetime
    fpl_input_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_identity_view_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_alias_plan: CurrentTeamAliasPlan
    team_alias_plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    team_alias_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_identity_map_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_mapping_plan: CurrentFixtureMappingPlan
    fixture_mapping_plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    fixture_mapping_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_algorithm_version: Literal["current-fpl-odds-exact-v1"] = (
        CURRENT_MAPPING_ALGORITHM_VERSION
    )
    fixture_match_policy: Literal["TARGET_GW_HOME_AWAY_EXACT_UTC_PLUS_EXPLICIT_BINDING"] = (
        "TARGET_GW_HOME_AWAY_EXACT_UTC_PLUS_EXPLICIT_BINDING"
    )
    kickoff_policy: Literal["EXACT_UTC_EQUALITY"] = "EXACT_UTC_EQUALITY"
    observed_provider_team_texts: tuple[str, ...] = Field(min_length=2)
    team_mappings: tuple[ResolvedCurrentTeam, ...] = Field(min_length=2)
    fixture_mappings: tuple[ResolvedCurrentFixture, ...] = Field(min_length=1)
    coverage: CurrentFixtureCoverage
    limitations: tuple[str, ...] = Field(min_length=1)
    source_lineage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_final_identity_map(self) -> FplOddsIdentityMap:
        if (
            self.information_cutoff > self.official_deadline_at
            or self.mapping_decided_at > self.information_cutoff
            or self.fpl_usable_at > self.mapping_decided_at
            or self.odds_usable_at > self.mapping_decided_at
        ):
            raise ValueError("final identity-map temporal context is inconsistent")
        latest_usable = max(self.fpl_usable_at, self.odds_usable_at)
        if (
            self.fixture_mapping_plan.approved_at < latest_usable
            or self.fixture_mapping_plan.approved_at > self.mapping_decided_at
        ):
            raise ValueError("fixture mapping-plan approval time is inconsistent")
        if self.limitations != _LIMITATIONS:
            raise ValueError("identity-map limitations are inconsistent")
        canonical_observed = tuple(sorted(set(self.observed_provider_team_texts)))
        plan_provider_texts = {
            mapping.provider_team_text for mapping in self.team_alias_plan.team_mappings
        }
        resolved_provider_texts = {mapping.provider_team_text for mapping in self.team_mappings}
        if (
            self.observed_provider_team_texts != canonical_observed
            or set(canonical_observed) != plan_provider_texts
            or set(canonical_observed) != resolved_provider_texts
        ):
            raise ValueError("final identity map contains dormant or missing team authority")
        if (
            self.team_alias_plan_version != self.team_alias_plan.plan_version
            or self.team_alias_plan_sha256 != self.team_alias_plan.sha256
            or self.fixture_mapping_plan_version != self.fixture_mapping_plan.plan_version
            or self.fixture_mapping_plan_sha256 != self.fixture_mapping_plan.sha256
            or self.fixture_mapping_plan.team_alias_plan_version
            != self.team_alias_plan.plan_version
            or self.fixture_mapping_plan.team_alias_plan_sha256 != self.team_alias_plan.sha256
            or self.fixture_mapping_plan.fpl_input_semantic_sha256 != self.fpl_input_semantic_sha256
            or self.fixture_mapping_plan.fpl_identity_view_sha256 != self.fpl_identity_view_sha256
            or self.fixture_mapping_plan.odds_identity_semantic_sha256
            != self.odds_identity_semantic_sha256
            or self.fixture_mapping_plan.target_gameweek != self.target_gameweek
        ):
            raise ValueError("embedded mapping-plan lineage is inconsistent")
        reconstructed_team_map = CurrentTeamIdentityMap(
            target_gameweek=self.target_gameweek,
            mapping_decided_at=self.mapping_decided_at,
            information_cutoff=self.information_cutoff,
            fpl_usable_at=self.fpl_usable_at,
            odds_usable_at=self.odds_usable_at,
            fpl_input_semantic_sha256=self.fpl_input_semantic_sha256,
            fpl_identity_view_sha256=self.fpl_identity_view_sha256,
            odds_provider_provenance_sha256=self.odds_provider_provenance_sha256,
            odds_identity_semantic_sha256=self.odds_identity_semantic_sha256,
            team_alias_plan=self.team_alias_plan,
            team_alias_plan_version=self.team_alias_plan_version,
            team_alias_plan_sha256=self.team_alias_plan_sha256,
            observed_provider_team_texts=self.observed_provider_team_texts,
            team_mappings=self.team_mappings,
            semantic_sha256=self.team_identity_map_semantic_sha256,
        )
        if reconstructed_team_map.semantic_sha256 != self.team_identity_map_semantic_sha256:
            raise ValueError("team identity-map lineage is inconsistent")

        provider_ids = [mapping.provider_event_id for mapping in self.fixture_mappings]
        fixture_ids = [mapping.official_fpl_fixture_id for mapping in self.fixture_mappings]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("mapped provider event identity is duplicated")
        if len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("mapped official FPL fixture identity is duplicated")
        team_by_provider = {mapping.provider_team_text: mapping for mapping in self.team_mappings}
        plan_bindings = {
            binding.provider_event_id: binding
            for binding in self.fixture_mapping_plan.fixture_mappings
        }
        if set(provider_ids) != set(plan_bindings):
            raise ValueError("resolved fixtures differ from the explicit fixture plan")
        for mapping in self.fixture_mappings:
            binding = plan_bindings[mapping.provider_event_id]
            home = team_by_provider.get(mapping.provider_home_team)
            away = team_by_provider.get(mapping.provider_away_team)
            if (
                mapping.official_fpl_gameweek_identity.external_id_text != str(self.target_gameweek)
                or mapping.official_fpl_fixture_identity.season_code != self.season_code
                or mapping.official_deadline_at != self.official_deadline_at
                or mapping.binding_approved_at > self.mapping_decided_at
                or mapping.binding_approved_at < max(self.fpl_usable_at, self.odds_usable_at)
                or mapping.fixture_binding_sha256 != binding.sha256
                or mapping.official_fpl_fixture_id != binding.official_fpl_fixture_id
                or mapping.official_fpl_fixture_identity != binding.canonical_fixture_identity
                or mapping.official_home_team_id != binding.expected_home_team_id
                or mapping.official_home_team_identity != binding.expected_home_team_identity
                or mapping.official_away_team_id != binding.expected_away_team_id
                or mapping.official_away_team_identity != binding.expected_away_team_identity
                or mapping.provider_commence_time != binding.expected_commence_time
                or home is None
                or home.official_fpl_team_id != mapping.official_home_team_id
                or home.official_fpl_team_identity != mapping.official_home_team_identity
                or home.official_fpl_team_name != mapping.official_home_team_name
                or away is None
                or away.official_fpl_team_id != mapping.official_away_team_id
                or away.official_fpl_team_identity != mapping.official_away_team_identity
                or away.official_fpl_team_name != mapping.official_away_team_name
            ):
                raise ValueError("resolved fixture context contradicts its bound plans")
        outside_ids = set(self.coverage.outside_target_provider_event_ids)
        if (
            self.coverage.bound_provider_event_count != len(self.fixture_mappings)
            or self.coverage.target_fpl_fixture_count != len(self.fixture_mappings)
            or self.coverage.mapped_event_count != len(self.fixture_mappings)
            or outside_ids.intersection(provider_ids)
            or self.coverage.all_provider_event_count != len(outside_ids) + len(provider_ids)
        ):
            raise ValueError("fixture coverage counts contradict mapped output")
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
    """Bind sources and both transient mapping stages before fixture resolution."""

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
    checks = {
        "accepted team identity-map hash": (
            team_map.semantic_sha256,
            _team_identity_map_sha256(team_map),
        ),
        "bound team identity-map hash": (
            request.team_identity_map_semantic_sha256,
            team_map.semantic_sha256,
        ),
        "bound fixture mapping plan version": (
            request.fixture_mapping_plan_version,
            fixture_plan.plan_version,
        ),
        "bound fixture mapping plan hash": (
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
    cutoff = _require_current_context(fpl_input, odds_input, team_plan, team_request)
    if (
        fixture_plan.provider != odds_input.provider
        or fixture_plan.competition_key != fpl_input.competition_key
        or fixture_plan.season_code != fpl_input.season_code
        or fixture_plan.target_gameweek != fpl_input.target_gameweek
        or fixture_plan.team_alias_plan_version != team_plan.plan_version
        or fixture_plan.team_alias_plan_sha256 != team_plan.sha256
        or fixture_plan.fpl_input_semantic_sha256 != fpl_input.semantic_sha256
        or fixture_plan.fpl_identity_view_sha256 != current_fpl_identity_view_sha256(fpl_input)
        or fixture_plan.odds_identity_semantic_sha256
        != current_odds_identity_semantic_sha256(odds_input)
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
    latest_usable = max(fpl_input.provenance.usable_at, odds_input.temporal.usable_at)
    approval_times = (
        fixture_plan.approved_at,
        *(mapping.approved_at for mapping in fixture_plan.fixture_mappings),
    )
    if any(approved_at > request.mapping_decided_at for approved_at in approval_times):
        raise IngestionError("POST_CUTOFF", "fixture approval is after mapping decision")
    if any(approved_at < latest_usable for approved_at in approval_times):
        raise IngestionError(
            "MAPPING_CONFLICT", "fixture approval predates the bound source usability window"
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
    teams = _team_by_id(fpl_input)
    teams_by_identity = {team.identity.canonical_lookup_sha256: team for team in teams.values()}
    for fixture in fixtures:
        identity = fixture.identity
        home = teams_by_identity.get(fixture.home_team_identity.canonical_lookup_sha256)
        away = teams_by_identity.get(fixture.away_team_identity.canonical_lookup_sha256)
        if (
            fixture.source_semantic_sha256 != fpl_input.provenance.fixtures_semantic_sha256
            or identity.provider_key != "official_fpl"
            or identity.entity_type != "FIXTURE"
            or identity.identifier_namespace != "fpl.fixture.id"
            or identity.external_id_text != str(fixture.provider_fixture_id)
            or identity.season_code != fpl_input.season_code
            or fixture.event_identity != fpl_input.target_event.identity
            or home is None
            or away is None
            or home.identity != fixture.home_team_identity
            or away.identity != fixture.away_team_identity
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
                },
            )
        if fpl_input.target_event.deadline_at >= fixture.kickoff_at:
            raise IngestionError(
                "QUALITY_BLOCKED",
                "target-Gameweek fixture is not after the official deadline",
                details={
                    "mapping_outcome": "QUALITY_BLOCKED",
                    "reason": "FIXTURE_NOT_AFTER_OFFICIAL_DEADLINE",
                },
            )
    return tuple(sorted(fixtures, key=lambda item: item.provider_fixture_id))


def _event_identity_sha256_from_values(
    *,
    provider_event_id: str,
    sport_key: str,
    commence_time: datetime,
    provider_home_team: str,
    provider_away_team: str,
) -> str:
    return canonical_sha256(
        {
            "commence_time": commence_time.isoformat(),
            "provider_away_team": provider_away_team,
            "provider_event_id": provider_event_id,
            "provider_home_team": provider_home_team,
            "sport_key": sport_key,
        }
    )


def _event_identity_sha256(event: CurrentOddsEvent) -> str:
    return _event_identity_sha256_from_values(
        provider_event_id=event.provider_event_id,
        sport_key=event.sport_key,
        commence_time=event.commence_time,
        provider_home_team=event.provider_home_team,
        provider_away_team=event.provider_away_team,
    )


def _mapping_error(event: CurrentOddsEvent, *, reason: str) -> IngestionError:
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
                "reason": "MULTIPLE_EXACT_CANDIDATES",
            },
        )
    if candidates:
        return candidates[0]
    if any(
        fixture.home_team_identity == away.official_fpl_team_identity
        and fixture.away_team_identity == home.official_fpl_team_identity
        and fixture.kickoff_at == event.commence_time
        for fixture in target_fixtures
    ):
        raise _mapping_error(event, reason="HOME_AWAY_ORIENTATION_MISMATCH")
    if any(
        fixture.home_team_identity == home.official_fpl_team_identity
        and fixture.away_team_identity == away.official_fpl_team_identity
        for fixture in target_fixtures
    ):
        raise _mapping_error(event, reason="EXACT_KICKOFF_MISMATCH")
    raise _mapping_error(event, reason="EXACT_FIXTURE_NOT_FOUND")


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
        raise _mapping_error(event, reason="EXPLICIT_BINDING_CONTRADICTS_PROVIDER_EVENT")
    if (
        binding.official_fpl_fixture_id != fixture.provider_fixture_id
        or binding.canonical_fixture_identity != fixture.identity
        or binding.expected_home_team_identity != fixture.home_team_identity
        or binding.expected_away_team_identity != fixture.away_team_identity
        or binding.expected_commence_time != fixture.kickoff_at
    ):
        raise _mapping_error(event, reason="EXPLICIT_BINDING_STALE_AGAINST_FPL")


def _resolved_fixture(
    fpl_input: CurrentFplInputBundle,
    event: CurrentOddsEvent,
    home: ResolvedCurrentTeam,
    away: ResolvedCurrentTeam,
    fixture: CurrentFplFixture,
    binding: CurrentFixtureBinding,
) -> ResolvedCurrentFixture:
    if fixture.kickoff_at is None:
        raise IngestionError("QUALITY_BLOCKED", "mapped FPL fixture has no kickoff")
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
        official_fpl_kickoff_at=fixture.kickoff_at,
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
            "fpl_usable_at": value.fpl_usable_at.isoformat(),
            "odds_identity_semantic_sha256": value.odds_identity_semantic_sha256,
            "odds_provider_provenance_sha256": value.odds_provider_provenance_sha256,
            "odds_usable_at": value.odds_usable_at.isoformat(),
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
            "limitations": list(value.limitations),
            "mapping_algorithm_version": value.mapping_algorithm_version,
            "mapping_decided_at": value.mapping_decided_at.isoformat(),
            "mapping_outcome": value.mapping_outcome,
            "odds_identity_semantic_sha256": value.odds_identity_semantic_sha256,
            "observed_provider_team_texts": list(value.observed_provider_team_texts),
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
    """Resolve only explicitly bound provider events and require complete target coverage."""

    _require_source_rights(fpl_input, odds_input)
    _revalidate_source_structures(fpl_input, odds_input)
    try:
        CurrentTeamIdentityMap.model_validate(team_map.model_dump(mode="python"))
        CurrentFixtureMappingPlan.model_validate(fixture_plan.model_dump(mode="python"))
    except ValidationError as exc:
        raise IngestionError("MAPPING_CONFLICT", "bound identity material is invalid") from exc
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
    events_by_id = {event.provider_event_id: event for event in odds_input.events}
    target_by_id = {fixture.provider_fixture_id: fixture for fixture in target_fixtures}

    resolved: list[ResolvedCurrentFixture] = []
    for binding in sorted(
        fixture_plan.fixture_mappings,
        key=lambda item: (item.provider_event_id, item.official_fpl_fixture_id),
    ):
        event = events_by_id.get(binding.provider_event_id)
        if event is None:
            raise IngestionError(
                "MAPPING_CONFLICT",
                "fixture plan references an unknown provider event",
                details={
                    "mapping_outcome": "UNKNOWN",
                    "reason": "BOUND_PROVIDER_EVENT_NOT_FOUND",
                },
            )
        if event.commence_time <= fpl_input.target_event.deadline_at:
            raise IngestionError(
                "QUALITY_BLOCKED",
                "bound provider event is not after the official FPL deadline",
                details={
                    "mapping_outcome": "QUALITY_BLOCKED",
                    "reason": "EVENT_BEFORE_OR_AT_OFFICIAL_DEADLINE",
                },
            )
        if binding.official_fpl_fixture_id not in target_by_id:
            raise IngestionError(
                "MAPPING_CONFLICT",
                "fixture binding is outside the target Gameweek",
                details={
                    "mapping_outcome": "UNKNOWN",
                    "reason": "BINDING_OUTSIDE_TARGET_GAMEWEEK",
                },
            )
        home = team_map.team(event.provider_home_team)
        away = team_map.team(event.provider_away_team)
        fixture = _exact_fixture_candidate(target_fixtures, event, home, away)
        _validate_explicit_binding(event, home, away, fixture, binding)
        resolved.append(_resolved_fixture(fpl_input, event, home, away, fixture, binding))

    mapped_provider_ids = {mapping.provider_event_id for mapping in resolved}
    mapped_fixture_ids = {mapping.official_fpl_fixture_id for mapping in resolved}
    target_fixture_ids = set(target_by_id)
    if len(mapped_fixture_ids) != len(resolved):
        raise IngestionError(
            "MAPPING_CONFLICT",
            "multiple provider events map to one official FPL fixture",
            details={
                "mapping_outcome": "AMBIGUOUS",
                "reason": "MANY_TO_ONE_FIXTURE_MAPPING",
            },
        )

    outside_ids: list[str] = []
    for event in sorted(odds_input.events, key=lambda item: item.provider_event_id):
        if event.provider_event_id in mapped_provider_ids:
            continue
        home = team_map.team(event.provider_home_team)
        away = team_map.team(event.provider_away_team)
        exact_target = [
            fixture
            for fixture in target_fixtures
            if fixture.home_team_identity == home.official_fpl_team_identity
            and fixture.away_team_identity == away.official_fpl_team_identity
            and fixture.kickoff_at == event.commence_time
        ]
        if exact_target:
            raise IngestionError(
                "MAPPING_CONFLICT",
                "unbound provider event duplicates an exact target fixture candidate",
                details={
                    "mapping_outcome": "AMBIGUOUS",
                    "reason": "UNBOUND_EXACT_TARGET_CANDIDATE",
                },
            )
        outside_ids.append(event.provider_event_id)

    if mapped_fixture_ids != target_fixture_ids:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "target-Gameweek identity coverage is incomplete",
            details={
                "mapping_outcome": "QUALITY_BLOCKED",
                "reason": "INCOMPLETE_TARGET_FIXTURE_COVERAGE",
                "unmapped_official_fpl_fixture_ids": tuple(
                    sorted(target_fixture_ids - mapped_fixture_ids)
                ),
            },
        )

    fixture_mappings = tuple(resolved)
    coverage = CurrentFixtureCoverage(
        all_provider_event_count=len(provider_event_ids),
        bound_provider_event_count=len(mapped_provider_ids),
        outside_target_provider_event_count=len(outside_ids),
        target_fpl_fixture_count=len(target_fixture_ids),
        mapped_event_count=len(fixture_mappings),
        outside_target_provider_event_ids=tuple(outside_ids),
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
        mapping_algorithm_version=CURRENT_MAPPING_ALGORITHM_VERSION,
        fixture_match_policy="TARGET_GW_HOME_AWAY_EXACT_UTC_PLUS_EXPLICIT_BINDING",
        kickoff_policy="EXACT_UTC_EQUALITY",
        source_lineage_sha256="0" * 64,
        semantic_sha256="0" * 64,
        target_gameweek=fpl_input.target_gameweek,
        official_deadline_at=fpl_input.target_event.deadline_at,
        mapping_decided_at=request.mapping_decided_at,
        information_cutoff=cutoff,
        fpl_usable_at=fpl_input.provenance.usable_at,
        odds_usable_at=odds_input.temporal.usable_at,
        fpl_input_semantic_sha256=request.fpl_input_semantic_sha256,
        fpl_identity_view_sha256=request.fpl_identity_view_sha256,
        odds_provider_provenance_sha256=request.odds_provider_provenance_sha256,
        odds_identity_semantic_sha256=request.odds_identity_semantic_sha256,
        team_alias_plan=team_plan,
        team_alias_plan_version=team_plan.plan_version,
        team_alias_plan_sha256=team_plan.sha256,
        team_identity_map_semantic_sha256=team_map.semantic_sha256,
        fixture_mapping_plan=fixture_plan,
        fixture_mapping_plan_version=fixture_plan.plan_version,
        fixture_mapping_plan_sha256=fixture_plan.sha256,
        observed_provider_team_texts=team_map.observed_provider_team_texts,
        team_mappings=team_map.team_mappings,
        fixture_mappings=fixture_mappings,
        coverage=coverage,
        limitations=_LIMITATIONS,
    )
    source_lineage = _identity_source_lineage_sha256(provisional)
    with_lineage = provisional.model_copy(update={"source_lineage_sha256": source_lineage})
    payload = with_lineage.model_dump(mode="python")
    payload["semantic_sha256"] = _fpl_odds_identity_map_sha256(with_lineage)
    return FplOddsIdentityMap.model_validate(payload)


__all__ = [
    "CURRENT_FIXTURE_RESOLUTION_REQUEST_VERSION",
    "CURRENT_TEAM_RESOLUTION_REQUEST_VERSION",
    "CurrentFixtureCoverage",
    "CurrentFixtureResolutionRequest",
    "CurrentTeamIdentityMap",
    "CurrentTeamResolutionRequest",
    "FplOddsIdentityMap",
    "ResolvedCurrentFixture",
    "ResolvedCurrentTeam",
    "bind_current_fixture_resolution_request",
    "bind_current_team_resolution_request",
    "current_fpl_identity_view_sha256",
    "current_odds_identity_semantic_sha256",
    "current_odds_provider_provenance_sha256",
    "resolve_current_fixture_identities",
    "resolve_current_team_identities",
]
