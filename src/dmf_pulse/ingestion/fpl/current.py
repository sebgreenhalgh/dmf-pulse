"""Governed, DB-free current official-FPL input compilation.

This module deliberately performs only bounded manual-file reads and transient
in-memory transformation.  It has no network, database, raw-storage, cache, or
artifact-write boundary.  The public CLI exposes a non-disclosing summary; the
full typed bundle exists only for the immediate caller.
"""

from __future__ import annotations

import stat
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.config import load_provider_config, provider_config_sha256
from dmf_pulse.ingestion.fpl.parser import (
    CONTRACT_VERSION,
    BootstrapPayload,
    ElementType,
    Event,
    Fixture,
    FixturePayload,
    FplResource,
    ParsedFplResource,
    PlayerElement,
    Team,
    parse_fpl_payload,
)
from dmf_pulse.ingestion.models import (
    DriftClassification,
    FrozenModel,
    QualityIssue,
    QualityReport,
    RightsCapability,
    RightsDecision,
)
from dmf_pulse.ingestion.rights import (
    decide_rights,
    load_rights_profiles,
    require_rights,
    rights_config_sha256,
)
from dmf_pulse.rules.models import FPLPosition

TARGET_COMPETITION_KEY = "PL"
TARGET_SEASON_CODE = "2026/27"
DEFAULT_TARGET_GAMEWEEK = 1
OFFICIAL_MANUAL_PROFILE_ID = "fpl_official_private_manual_v1"

_POSITION_CODES: Mapping[str, FPLPosition] = {
    "GK": FPLPosition.GK,
    "GKP": FPLPosition.GK,
    "DEF": FPLPosition.DEF,
    "MID": FPLPosition.MID,
    "FWD": FPLPosition.FWD,
}


class CurrentFplInputRequest(FrozenModel):
    """Operator-declared metadata for one current bootstrap/fixtures pair."""

    bootstrap_path: Path
    fixtures_path: Path
    competition_key: str = Field(min_length=1, max_length=40)
    season_code: str = Field(pattern=r"^\d{4}/\d{2}$")
    captured_at: datetime
    information_cutoff: datetime
    rights_profile_id: str = Field(min_length=1, max_length=120)
    gameweek: int = Field(default=DEFAULT_TARGET_GAMEWEEK, gt=0)

    @model_validator(mode="after")
    def normalize_times(self) -> CurrentFplInputRequest:
        for name, value in (
            ("captured_at", self.captured_at),
            ("information_cutoff", self.information_cutoff),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
            object.__setattr__(self, name, value.astimezone(UTC))
        return self


class CurrentFplIdentity(FrozenModel):
    """Season-scoped provider identity prepared for central canonical resolution."""

    provider_key: Literal["official_fpl"] = "official_fpl"
    provider_product: Literal["fantasy_premierleague"] = "fantasy_premierleague"
    season_code: str
    entity_type: Literal["PLAYER", "TEAM", "FIXTURE", "GAMEWEEK"]
    identifier_namespace: Literal["fpl.element.id", "fpl.team.id", "fpl.fixture.id", "fpl.event.id"]
    external_id_text: str = Field(min_length=1, max_length=100)
    canonical_lookup_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_reference_is_exact(self) -> CurrentFplIdentity:
        expected = canonical_sha256(
            {
                "entity_type": self.entity_type,
                "external_id_text": self.external_id_text,
                "identifier_namespace": self.identifier_namespace,
                "provider_key": self.provider_key,
                "provider_product": self.provider_product,
                "season_code": self.season_code,
            }
        )
        if self.canonical_lookup_sha256 != expected:
            raise ValueError("canonical lookup digest is inconsistent")
        return self


class CurrentFplPositionDefinition(FrozenModel):
    source_resource: Literal["bootstrap"] = "bootstrap"
    source_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_element_type_id: int = Field(gt=0)
    provider_short_name: str = Field(min_length=1)
    canonical_position: FPLPosition
    squad_select: int = Field(gt=0)
    squad_min_play: int = Field(ge=0)
    squad_max_play: int = Field(gt=0)


class CurrentFplTeam(FrozenModel):
    source_resource: Literal["bootstrap"] = "bootstrap"
    source_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: CurrentFplIdentity
    provider_team_id: int = Field(gt=0)
    provider_code: int = Field(gt=0)
    official_name: str = Field(min_length=1)
    short_name: str = Field(min_length=1)


class CurrentFplPlayer(FrozenModel):
    source_resource: Literal["bootstrap"] = "bootstrap"
    source_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: CurrentFplIdentity
    provider_element_id: int = Field(gt=0)
    provider_code: int = Field(gt=0)
    first_name: str
    second_name: str = Field(min_length=1)
    web_name: str = Field(min_length=1)
    team_identity: CurrentFplIdentity
    position: FPLPosition
    current_price_tenths: int = Field(gt=0)
    status: str = Field(min_length=1)
    chance_of_playing_next_round: int | None = Field(default=None, ge=0, le=100)
    chance_of_playing_this_round: int | None = Field(default=None, ge=0, le=100)
    news: str | None = None
    news_added: datetime | None = None


class CurrentFplEvent(FrozenModel):
    source_resource: Literal["bootstrap"] = "bootstrap"
    source_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: CurrentFplIdentity
    provider_event_id: int = Field(gt=0)
    name: str = Field(min_length=1)
    deadline_at: datetime
    finished: bool | None = None
    data_checked: bool | None = None
    is_previous: bool | None = None
    is_current: bool | None = None
    is_next: bool | None = None


class CurrentFplFixture(FrozenModel):
    source_resource: Literal["fixtures"] = "fixtures"
    source_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: CurrentFplIdentity
    provider_fixture_id: int = Field(gt=0)
    provider_code: int = Field(gt=0)
    event_identity: CurrentFplIdentity | None
    home_team_identity: CurrentFplIdentity
    away_team_identity: CurrentFplIdentity
    kickoff_at: datetime | None
    finished: bool
    started: bool | None = None
    finished_provisional: bool | None = None


class CurrentFplProvenance(FrozenModel):
    provider_key: Literal["official_fpl"] = "official_fpl"
    contract_version: Literal["fpl-reference-v1"] = "fpl-reference-v1"
    acquisition_mode: Literal["MANUAL_OPERATOR_CAPTURE"] = "MANUAL_OPERATOR_CAPTURE"
    captured_at: datetime
    received_at: datetime
    information_cutoff: datetime
    usable_at: datetime
    bootstrap_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bootstrap_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixtures_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixtures_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rights_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transport_called: Literal[False] = False


class CurrentFplRightsBoundary(FrozenModel):
    rights_profile_id: str
    rights_profile_version: str
    decisions: tuple[RightsDecision, ...]
    unresolved_rights: tuple[str, ...]
    automated_access: Literal["DENY"]
    raw_storage: Literal["DENY"]
    derived_storage: Literal["DENY"]
    database_accessed: Literal[False] = False
    raw_storage_performed: Literal[False] = False
    derived_storage_performed: Literal[False] = False
    operator_delete_required: Literal[True] = True
    disclosure_mode: Literal["SAFE_SUMMARY_ONLY"] = "SAFE_SUMMARY_ONLY"


class CurrentFplInputSummary(FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["VALID", "VALID_WITH_WARNINGS"]
    provider: Literal["official_fpl"] = "official_fpl"
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: int = Field(gt=0)
    gameweek_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deadline_at: datetime
    captured_at: datetime
    received_at: datetime
    information_cutoff: datetime
    usable_at: datetime
    player_count: int = Field(gt=0)
    team_count: int = Field(gt=0)
    fixture_count: int = Field(ge=0)
    target_gameweek_fixture_count: int = Field(gt=0)
    position_counts: dict[str, int]
    status_counts: dict[str, int]
    current_price_tenths_min: int = Field(gt=0)
    current_price_tenths_max: int = Field(gt=0)
    bootstrap_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bootstrap_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixtures_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixtures_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_bundle_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_quality_status: Literal["PASS", "PASS_WITH_WARNINGS"]
    data_quality_warning_count: int = Field(ge=0)
    rights_profile_id: Literal["fpl_official_private_manual_v1"] = "fpl_official_private_manual_v1"
    manual_import: Literal["ALLOW"] = "ALLOW"
    transient_processing: Literal["ALLOW"] = "ALLOW"
    private_internal_use: Literal["ALLOW"] = "ALLOW"
    automated_access: Literal["DENY"] = "DENY"
    raw_storage: Literal["DENY"] = "DENY"
    derived_storage: Literal["DENY"] = "DENY"
    database_accessed: Literal[False] = False
    raw_storage_performed: Literal[False] = False
    derived_storage_performed: Literal[False] = False
    transport_called: Literal[False] = False
    operator_delete_required: Literal[True] = True
    next_action: Literal["CHECKPOINT 1.3 — LIVE THE ODDS API INPUT FOUNDATION"] = (
        "CHECKPOINT 1.3 — LIVE THE ODDS API INPUT FOUNDATION"
    )


class CurrentFplInputBundle(FrozenModel):
    """Complete transient current-input contract for immediate downstream use."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    provider: Literal["official_fpl"] = "official_fpl"
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: int = Field(gt=0)
    target_event: CurrentFplEvent
    events: tuple[CurrentFplEvent, ...]
    teams: tuple[CurrentFplTeam, ...]
    positions: tuple[CurrentFplPositionDefinition, ...]
    players: tuple[CurrentFplPlayer, ...]
    fixtures: tuple[CurrentFplFixture, ...]
    game_settings: dict[str, Any]
    game_settings_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: CurrentFplProvenance
    rights: CurrentFplRightsBoundary
    quality: QualityReport
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def safe_summary(self) -> CurrentFplInputSummary:
        """Return the only representation intended for CLI disclosure."""

        position_counts = Counter(player.position.value for player in self.players)
        status_counts = Counter(player.status for player in self.players)
        prices = [player.current_price_tenths for player in self.players]
        target_fixture_count = sum(
            fixture.event_identity is not None
            and fixture.event_identity.external_id_text == str(self.target_gameweek)
            for fixture in self.fixtures
        )
        quality_status: Literal["PASS", "PASS_WITH_WARNINGS"] = (
            "PASS_WITH_WARNINGS" if self.quality.warning_count else "PASS"
        )
        return CurrentFplInputSummary(
            status="VALID_WITH_WARNINGS" if self.quality.warning_count else "VALID",
            target_gameweek=self.target_gameweek,
            gameweek_identity_sha256=self.target_event.identity.canonical_lookup_sha256,
            deadline_at=self.target_event.deadline_at,
            captured_at=self.provenance.captured_at,
            received_at=self.provenance.received_at,
            information_cutoff=self.provenance.information_cutoff,
            usable_at=self.provenance.usable_at,
            player_count=len(self.players),
            team_count=len(self.teams),
            fixture_count=len(self.fixtures),
            target_gameweek_fixture_count=target_fixture_count,
            position_counts=dict(sorted(position_counts.items())),
            status_counts=dict(sorted(status_counts.items())),
            current_price_tenths_min=min(prices),
            current_price_tenths_max=max(prices),
            bootstrap_payload_sha256=self.provenance.bootstrap_payload_sha256,
            bootstrap_semantic_sha256=self.provenance.bootstrap_semantic_sha256,
            fixtures_payload_sha256=self.provenance.fixtures_payload_sha256,
            fixtures_semantic_sha256=self.provenance.fixtures_semantic_sha256,
            input_bundle_semantic_sha256=self.semantic_sha256,
            data_quality_status=quality_status,
            data_quality_warning_count=self.quality.warning_count,
        )


def _identity(
    *,
    season_code: str,
    entity_type: Literal["PLAYER", "TEAM", "FIXTURE", "GAMEWEEK"],
    namespace: Literal["fpl.element.id", "fpl.team.id", "fpl.fixture.id", "fpl.event.id"],
    external_id: int,
) -> CurrentFplIdentity:
    material = {
        "entity_type": entity_type,
        "external_id_text": str(external_id),
        "identifier_namespace": namespace,
        "provider_key": "official_fpl",
        "provider_product": "fantasy_premierleague",
        "season_code": season_code,
    }
    return CurrentFplIdentity(
        season_code=season_code,
        entity_type=entity_type,
        identifier_namespace=namespace,
        external_id_text=str(external_id),
        canonical_lookup_sha256=canonical_sha256(material),
    )


def _safe_read(path: Path) -> bytes:
    """Read one bounded regular operator-owned file without following a symlink."""

    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError("input is not a regular file")
        maximum = load_provider_config().max_response_bytes
        with path.open("rb") as handle:
            body = handle.read(maximum + 1)
    except OSError:
        raise IngestionError("SOURCE_UNAVAILABLE", "manual FPL input is unavailable") from None
    if len(body) > maximum:
        raise IngestionError("PAYLOAD_TOO_LARGE", "manual FPL input exceeds the byte limit")
    return body


def _parsed_payloads(
    request: CurrentFplInputRequest,
) -> tuple[ParsedFplResource, ParsedFplResource]:
    try:
        bootstrap_resolved = request.bootstrap_path.resolve(strict=True)
        fixtures_resolved = request.fixtures_path.resolve(strict=True)
    except OSError:
        raise IngestionError("SOURCE_UNAVAILABLE", "manual FPL input is unavailable") from None
    if bootstrap_resolved == fixtures_resolved:
        raise IngestionError("USAGE_INVALID", "bootstrap and fixtures must be distinct files")
    bootstrap = parse_fpl_payload(
        FplResource.BOOTSTRAP,
        _safe_read(request.bootstrap_path),
        contract_version=CONTRACT_VERSION,
    )
    fixtures = parse_fpl_payload(
        FplResource.FIXTURES,
        _safe_read(request.fixtures_path),
        contract_version=CONTRACT_VERSION,
    )
    return bootstrap, fixtures


def _payload_pair(
    bootstrap: ParsedFplResource,
    fixtures: ParsedFplResource,
) -> tuple[BootstrapPayload, FixturePayload]:
    if not isinstance(bootstrap.payload, BootstrapPayload) or not isinstance(
        fixtures.payload, FixturePayload
    ):
        raise IngestionError("INTERNAL_INVARIANT", "current FPL payload types are invalid")
    return bootstrap.payload, fixtures.payload


def _position_map(
    definitions: list[ElementType],
    *,
    source_semantic_sha256: str,
) -> tuple[dict[int, FPLPosition], tuple[CurrentFplPositionDefinition, ...]]:
    by_provider_id: dict[int, FPLPosition] = {}
    canonical_seen: set[FPLPosition] = set()
    contract: list[CurrentFplPositionDefinition] = []
    for definition in definitions:
        provider_code = definition.singular_name_short.strip().upper()
        position = _POSITION_CODES.get(provider_code)
        if position is None or position in canonical_seen:
            raise IngestionError(
                "VALIDATION_FAILED", "target-season FPL position mapping is invalid"
            )
        if definition.squad_min_play > definition.squad_max_play:
            raise IngestionError(
                "VALIDATION_FAILED", "target-season FPL position bounds are invalid"
            )
        by_provider_id[definition.id] = position
        canonical_seen.add(position)
        contract.append(
            CurrentFplPositionDefinition(
                source_semantic_sha256=source_semantic_sha256,
                provider_element_type_id=definition.id,
                provider_short_name=provider_code,
                canonical_position=position,
                squad_select=definition.squad_select,
                squad_min_play=definition.squad_min_play,
                squad_max_play=definition.squad_max_play,
            )
        )
    if canonical_seen != set(FPLPosition):
        raise IngestionError("VALIDATION_FAILED", "target-season FPL positions are incomplete")
    return by_provider_id, tuple(sorted(contract, key=lambda item: item.canonical_position.value))


def _target_event(events: list[Event], gameweek: int) -> Event:
    matches = [event for event in events if event.id == gameweek]
    if len(matches) != 1:
        raise IngestionError("VALIDATION_FAILED", "target Gameweek is missing or ambiguous")
    target = matches[0]
    if target.finished:
        raise IngestionError("VALIDATION_FAILED", "target Gameweek is already finished")
    if not bool(target.is_current or target.is_next):
        raise IngestionError("VALIDATION_FAILED", "target Gameweek is not marked current or next")
    if (
        sum(event.is_current is True for event in events) > 1
        or sum(event.is_next is True for event in events) > 1
    ):
        raise IngestionError("VALIDATION_FAILED", "Gameweek state flags are inconsistent")
    return target


def _validate_pair(
    bootstrap: BootstrapPayload,
    fixtures: FixturePayload,
    *,
    target: Event,
    information_cutoff: datetime,
) -> None:
    if not bootstrap.events or not bootstrap.teams or not bootstrap.elements:
        raise IngestionError("VALIDATION_FAILED", "current FPL catalogue is incomplete")
    if not bootstrap.game_settings:
        raise IngestionError("VALIDATION_FAILED", "FPL game settings are missing")
    team_ids = {team.id for team in bootstrap.teams}
    event_ids = {event.id for event in bootstrap.events}
    target_fixtures = 0
    for fixture in fixtures.fixtures:
        if fixture.team_h not in team_ids or fixture.team_a not in team_ids:
            raise IngestionError("MAPPING_CONFLICT", "fixture references an unresolved team")
        if fixture.event is not None and fixture.event not in event_ids:
            raise IngestionError("MAPPING_CONFLICT", "fixture references an unresolved Gameweek")
        if fixture.event == target.id:
            target_fixtures += 1
            if fixture.kickoff_time is None:
                raise IngestionError(
                    "VALIDATION_FAILED", "target Gameweek fixture kickoff is missing"
                )
            if fixture.kickoff_time <= target.deadline_time:
                raise IngestionError(
                    "VALIDATION_FAILED", "target Gameweek fixture precedes its deadline"
                )
    if target_fixtures == 0:
        raise IngestionError("VALIDATION_FAILED", "target Gameweek has no fixtures")
    if any(player.now_cost <= 0 for player in bootstrap.elements):
        raise IngestionError("VALIDATION_FAILED", "current FPL price must be positive")
    if any(
        player.news_added is not None and player.news_added > information_cutoff
        for player in bootstrap.elements
    ):
        raise IngestionError("POST_CUTOFF", "player availability evidence is post-cutoff")


def _quality(
    bootstrap: ParsedFplResource,
    fixtures: ParsedFplResource,
    *,
    observed_at: datetime,
) -> QualityReport:
    issues: list[QualityIssue] = []
    for parsed in (bootstrap, fixtures):
        classification = parsed.drift.classification
        if classification is DriftClassification.ADDITIVE_UNKNOWN:
            issues.append(
                QualityIssue(
                    severity="P2",
                    code="FPL_SCHEMA_ADDITIVE_UNKNOWN",
                    stage="SCHEMA",
                    subject_scope=parsed.resource.value.upper(),
                    message="provider published additive fields outside the frozen contract",
                    observed_at=observed_at,
                    safe_details={"path_count": len(parsed.drift.unknown_paths)},
                )
            )
        elif classification is DriftClassification.MISSING_OPTIONAL:
            issues.append(
                QualityIssue(
                    severity="P3",
                    code="FPL_SCHEMA_OPTIONAL_MISSING",
                    stage="SCHEMA",
                    subject_scope=parsed.resource.value.upper(),
                    message="optional provider fields were not published",
                    observed_at=observed_at,
                    safe_details={"path_count": len(parsed.drift.missing_optional_paths)},
                )
            )
    return QualityReport(
        status="PASS_WITH_WARNINGS" if issues else "PASS",
        warning_count=len(issues),
        blocker_count=0,
        issues=tuple(issues),
    )


def _rights_boundary(
    request: CurrentFplInputRequest,
    *,
    checked_at: datetime,
) -> CurrentFplRightsBoundary:
    profiles = load_rights_profiles()
    profile = profiles.get(request.rights_profile_id)
    if (
        profile is None
        or profile.rights_profile_id != OFFICIAL_MANUAL_PROFILE_ID
        or profile.provider_key != "official_fpl"
    ):
        raise IngestionError(
            "RIGHTS_BLOCKED", "current FPL input requires the approved official manual profile"
        )
    required = (
        RightsCapability.MANUAL_IMPORT,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.PRIVATE_INTERNAL_USE,
    )
    decisions = [
        require_rights(profile, capability, checked_at=checked_at) for capability in required
    ]
    observed = (
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.RAW_STORAGE,
        RightsCapability.DERIVED_STORAGE,
    )
    denied = [decide_rights(profile, capability, checked_at=checked_at) for capability in observed]
    decisions.extend(denied)
    if any(decision.decision != "DENY" for decision in denied):
        raise IngestionError(
            "CONFIGURATION_INVALID", "official FPL manual rights boundary has drifted"
        )
    return CurrentFplRightsBoundary(
        rights_profile_id=profile.rights_profile_id,
        rights_profile_version=profile.profile_version,
        decisions=tuple(decisions),
        unresolved_rights=profile.unresolved_rights,
        automated_access="DENY",
        raw_storage="DENY",
        derived_storage="DENY",
    )


def _event_contract(
    event: Event,
    season_code: str,
    *,
    source_semantic_sha256: str,
) -> CurrentFplEvent:
    return CurrentFplEvent(
        source_semantic_sha256=source_semantic_sha256,
        identity=_identity(
            season_code=season_code,
            entity_type="GAMEWEEK",
            namespace="fpl.event.id",
            external_id=event.id,
        ),
        provider_event_id=event.id,
        name=event.name,
        deadline_at=event.deadline_time,
        finished=event.finished,
        data_checked=event.data_checked,
        is_previous=event.is_previous,
        is_current=event.is_current,
        is_next=event.is_next,
    )


def _team_contract(
    team: Team,
    season_code: str,
    *,
    source_semantic_sha256: str,
) -> CurrentFplTeam:
    identity = _identity(
        season_code=season_code,
        entity_type="TEAM",
        namespace="fpl.team.id",
        external_id=team.id,
    )
    return CurrentFplTeam(
        source_semantic_sha256=source_semantic_sha256,
        identity=identity,
        provider_team_id=team.id,
        provider_code=team.code,
        official_name=team.name,
        short_name=team.short_name,
    )


def _player_contract(
    player: PlayerElement,
    *,
    season_code: str,
    teams: Mapping[int, CurrentFplTeam],
    positions: Mapping[int, FPLPosition],
    source_semantic_sha256: str,
) -> CurrentFplPlayer:
    return CurrentFplPlayer(
        source_semantic_sha256=source_semantic_sha256,
        identity=_identity(
            season_code=season_code,
            entity_type="PLAYER",
            namespace="fpl.element.id",
            external_id=player.id,
        ),
        provider_element_id=player.id,
        provider_code=player.code,
        first_name=player.first_name,
        second_name=player.second_name,
        web_name=player.web_name,
        team_identity=teams[player.team].identity,
        position=positions[player.element_type],
        current_price_tenths=player.now_cost,
        status=player.status,
        chance_of_playing_next_round=player.chance_of_playing_next_round,
        chance_of_playing_this_round=player.chance_of_playing_this_round,
        news=player.news,
        news_added=player.news_added,
    )


def _fixture_contract(
    fixture: Fixture,
    *,
    season_code: str,
    teams: Mapping[int, CurrentFplTeam],
    events: Mapping[int, CurrentFplEvent],
    source_semantic_sha256: str,
) -> CurrentFplFixture:
    return CurrentFplFixture(
        source_semantic_sha256=source_semantic_sha256,
        identity=_identity(
            season_code=season_code,
            entity_type="FIXTURE",
            namespace="fpl.fixture.id",
            external_id=fixture.id,
        ),
        provider_fixture_id=fixture.id,
        provider_code=fixture.code,
        event_identity=events[fixture.event].identity if fixture.event is not None else None,
        home_team_identity=teams[fixture.team_h].identity,
        away_team_identity=teams[fixture.team_a].identity,
        kickoff_at=fixture.kickoff_time,
        finished=fixture.finished,
        started=fixture.started,
        finished_provisional=fixture.finished_provisional,
    )


class CurrentFplInputService:
    """Compile a manual official-FPL pair through a transient fail-closed boundary."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._clock = clock

    def compile(self, request: CurrentFplInputRequest) -> CurrentFplInputBundle:
        if request.competition_key != TARGET_COMPETITION_KEY:
            raise IngestionError("VALIDATION_FAILED", "competition metadata is not EPL")
        if request.season_code != TARGET_SEASON_CODE:
            raise IngestionError("VALIDATION_FAILED", "season metadata is not 2026/27")
        received_at = self._clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise IngestionError("INTERNAL_INVARIANT", "current FPL clock must be timezone-aware")
        received_at = received_at.astimezone(UTC)
        if request.captured_at > request.information_cutoff:
            raise IngestionError("POST_CUTOFF", "current FPL capture is post-cutoff")
        if request.captured_at > received_at:
            raise IngestionError("VALIDATION_FAILED", "captured_at is after receipt time")
        if received_at > request.information_cutoff:
            raise IngestionError("POST_CUTOFF", "current FPL input became usable post-cutoff")

        rights = _rights_boundary(request, checked_at=received_at)
        parsed_bootstrap, parsed_fixtures = _parsed_payloads(request)
        bootstrap, fixtures = _payload_pair(parsed_bootstrap, parsed_fixtures)
        target = _target_event(bootstrap.events, request.gameweek)
        if request.information_cutoff > target.deadline_time:
            raise IngestionError("POST_CUTOFF", "information cutoff exceeds the official deadline")
        position_map, positions = _position_map(
            bootstrap.element_types,
            source_semantic_sha256=parsed_bootstrap.semantic_sha256,
        )
        _validate_pair(
            bootstrap,
            fixtures,
            target=target,
            information_cutoff=request.information_cutoff,
        )

        events = tuple(
            sorted(
                (
                    _event_contract(
                        event,
                        request.season_code,
                        source_semantic_sha256=parsed_bootstrap.semantic_sha256,
                    )
                    for event in bootstrap.events
                ),
                key=lambda item: item.provider_event_id,
            )
        )
        event_by_id = {event.provider_event_id: event for event in events}
        teams = tuple(
            sorted(
                (
                    _team_contract(
                        team,
                        request.season_code,
                        source_semantic_sha256=parsed_bootstrap.semantic_sha256,
                    )
                    for team in bootstrap.teams
                ),
                key=lambda item: item.provider_team_id,
            )
        )
        team_by_id = {team.provider_team_id: team for team in teams}
        players = tuple(
            sorted(
                (
                    _player_contract(
                        player,
                        season_code=request.season_code,
                        teams=team_by_id,
                        positions=position_map,
                        source_semantic_sha256=parsed_bootstrap.semantic_sha256,
                    )
                    for player in bootstrap.elements
                ),
                key=lambda item: item.provider_element_id,
            )
        )
        fixture_contracts = tuple(
            sorted(
                (
                    _fixture_contract(
                        fixture,
                        season_code=request.season_code,
                        teams=team_by_id,
                        events=event_by_id,
                        source_semantic_sha256=parsed_fixtures.semantic_sha256,
                    )
                    for fixture in fixtures.fixtures
                ),
                key=lambda item: item.provider_fixture_id,
            )
        )
        quality = _quality(parsed_bootstrap, parsed_fixtures, observed_at=received_at)
        provenance = CurrentFplProvenance(
            captured_at=request.captured_at,
            received_at=received_at,
            information_cutoff=request.information_cutoff,
            usable_at=received_at,
            bootstrap_payload_sha256=parsed_bootstrap.payload_sha256,
            bootstrap_semantic_sha256=parsed_bootstrap.semantic_sha256,
            fixtures_payload_sha256=parsed_fixtures.payload_sha256,
            fixtures_semantic_sha256=parsed_fixtures.semantic_sha256,
            provider_config_sha256=provider_config_sha256(),
            rights_config_sha256=rights_config_sha256(),
        )
        game_settings_semantic_sha256 = canonical_sha256(bootstrap.game_settings)
        semantic_material = {
            "bootstrap_semantic_sha256": parsed_bootstrap.semantic_sha256,
            "captured_at": request.captured_at.isoformat(),
            "competition_key": request.competition_key,
            "fixtures_semantic_sha256": parsed_fixtures.semantic_sha256,
            "game_settings_semantic_sha256": game_settings_semantic_sha256,
            "information_cutoff": request.information_cutoff.isoformat(),
            "provider": "official_fpl",
            "season_code": request.season_code,
            "target_gameweek": request.gameweek,
        }
        return CurrentFplInputBundle(
            target_gameweek=request.gameweek,
            target_event=event_by_id[target.id],
            events=events,
            teams=teams,
            positions=positions,
            players=players,
            fixtures=fixture_contracts,
            game_settings=dict(bootstrap.game_settings),
            game_settings_semantic_sha256=game_settings_semantic_sha256,
            provenance=provenance,
            rights=rights,
            quality=quality,
            semantic_sha256=canonical_sha256(semantic_material),
        )
