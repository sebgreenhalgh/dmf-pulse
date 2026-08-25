"""Manual, transient current official-FPL catalogue and fixture compilation.

This module has no transport, database, persistence, cache, backup, or artifact-write
boundary. It reads two operator-owned files through a bounded regular-file gate, reuses the
accepted FPL parser, and returns an immutable private bundle. Only ``safe_summary`` is intended
for public or CLI disclosure.
"""

from __future__ import annotations

import json
import os
import stat
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
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
    CapabilityValue,
    DriftClassification,
    FrozenModel,
    QualityIssue,
    QualityReport,
    RightsCapability,
    RightsDecision,
    RightsProfile,
    RightsProfileStatus,
)
from dmf_pulse.ingestion.rights import (
    decide_rights,
    load_rights_profiles,
    require_rights,
    rights_config_sha256,
)
from dmf_pulse.rules.models import FPLPosition

CURRENT_FPL_CONTRACT_VERSION: Literal["current-fpl-input-v1"] = "current-fpl-input-v1"
SUPPORTED_COMPETITION_KEY: Literal["PL"] = "PL"
SUPPORTED_SEASON_CODE: Literal["2026/27"] = "2026/27"
OFFICIAL_MANUAL_PROFILE_ID: Literal["fpl_official_private_manual_v1"] = (
    "fpl_official_private_manual_v1"
)

_POSITION_CODES: Mapping[str, FPLPosition] = {
    "GK": FPLPosition.GK,
    "GKP": FPLPosition.GK,
    "DEF": FPLPosition.DEF,
    "MID": FPLPosition.MID,
    "FWD": FPLPosition.FWD,
}
_IDENTITY_NAMESPACE_BY_ENTITY: Mapping[
    str, Literal["fpl.element.id", "fpl.team.id", "fpl.fixture.id", "fpl.event.id"]
] = {
    "PLAYER": "fpl.element.id",
    "TEAM": "fpl.team.id",
    "FIXTURE": "fpl.fixture.id",
    "GAMEWEEK": "fpl.event.id",
}


def _normalize_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    """Return the canonical JSON representation used for bundle timestamps."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_game_setting(value: object) -> object:
    """Project parser-accepted settings to canonical JSON."""

    if isinstance(value, dict):
        return {str(key): _canonical_game_setting(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_canonical_game_setting(child) for child in value]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    raise IngestionError("INTERNAL_INVARIANT", "FPL game settings are invalid")


class CurrentFplInputRequest(FrozenModel):
    """Operator-declared metadata for one current bootstrap/fixtures pair."""

    bootstrap_path: Path
    fixtures_path: Path
    competition_key: str = Field(min_length=1, max_length=40)
    season_code: str = Field(pattern=r"^\d{4}/\d{2}$")
    target_gameweek: int = Field(gt=0)
    captured_at: datetime
    information_cutoff: datetime
    rights_profile_id: str = Field(min_length=1, max_length=120)

    @field_validator("captured_at", "information_cutoff")
    @classmethod
    def normalize_request_times(cls, value: datetime) -> datetime:
        return _normalize_utc(value, label="current FPL request timestamp")


class CurrentFplIdentity(FrozenModel):
    """Season-scoped official-FPL identity prepared for canonical resolution."""

    provider_key: Literal["official_fpl"] = "official_fpl"
    provider_product: Literal["fantasy_premierleague"] = "fantasy_premierleague"
    season_code: Literal["2026/27"] = "2026/27"
    entity_type: Literal["PLAYER", "TEAM", "FIXTURE", "GAMEWEEK"]
    identifier_namespace: Literal["fpl.element.id", "fpl.team.id", "fpl.fixture.id", "fpl.event.id"]
    external_id_text: str = Field(min_length=1, max_length=100)
    canonical_lookup_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_reference_is_exact(self) -> Self:
        if self.identifier_namespace != _IDENTITY_NAMESPACE_BY_ENTITY[self.entity_type]:
            raise ValueError("identity entity and namespace differ")
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
    provider_short_name: str = Field(min_length=1, max_length=20)
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

    @model_validator(mode="after")
    def identity_matches_team(self) -> Self:
        if self.identity.entity_type != "TEAM" or self.identity.external_id_text != str(
            self.provider_team_id
        ):
            raise ValueError("team identity is inconsistent")
        return self


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
    chance_of_playing_this_round: int | None = Field(default=None, ge=0, le=100)
    chance_of_playing_next_round: int | None = Field(default=None, ge=0, le=100)
    news: str | None = None
    news_added: datetime | None = None

    @field_validator("news_added")
    @classmethod
    def normalize_news_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _normalize_utc(value, label="news_added")

    @model_validator(mode="after")
    def identities_match_player(self) -> Self:
        if self.identity.entity_type != "PLAYER" or self.identity.external_id_text != str(
            self.provider_element_id
        ):
            raise ValueError("player identity is inconsistent")
        if self.team_identity.entity_type != "TEAM":
            raise ValueError("player team identity is inconsistent")
        return self


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

    @field_validator("deadline_at")
    @classmethod
    def normalize_deadline(cls, value: datetime) -> datetime:
        return _normalize_utc(value, label="deadline_at")

    @model_validator(mode="after")
    def identity_matches_event(self) -> Self:
        if self.identity.entity_type != "GAMEWEEK" or self.identity.external_id_text != str(
            self.provider_event_id
        ):
            raise ValueError("Gameweek identity is inconsistent")
        return self


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

    @field_validator("kickoff_at")
    @classmethod
    def normalize_kickoff(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _normalize_utc(value, label="kickoff_at")

    @model_validator(mode="after")
    def identities_match_fixture(self) -> Self:
        if self.identity.entity_type != "FIXTURE" or self.identity.external_id_text != str(
            self.provider_fixture_id
        ):
            raise ValueError("fixture identity is inconsistent")
        if self.event_identity is not None and self.event_identity.entity_type != "GAMEWEEK":
            raise ValueError("fixture event identity is inconsistent")
        if (
            self.home_team_identity.entity_type != "TEAM"
            or self.away_team_identity.entity_type != "TEAM"
            or self.home_team_identity == self.away_team_identity
        ):
            raise ValueError("fixture team identities are inconsistent")
        return self


class CurrentFplGameSettings(FrozenModel):
    """Canonical immutable representation of the provider game-settings object."""

    source_resource: Literal["bootstrap"] = "bootstrap"
    source_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_json: str = Field(min_length=2)
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_value_is_exact(self) -> Self:
        try:
            value = json.loads(self.canonical_json)
        except json.JSONDecodeError as exc:
            raise ValueError("game settings canonical JSON is invalid") from exc
        if not isinstance(value, dict):
            raise ValueError("game settings must be an object")
        if canonical_json_bytes(value).decode("utf-8") != self.canonical_json:
            raise ValueError("game settings JSON is not canonical")
        if canonical_sha256(value) != self.semantic_sha256:
            raise ValueError("game settings semantic digest is inconsistent")
        return self


class CurrentFplProvenance(FrozenModel):
    provider_key: Literal["official_fpl"] = "official_fpl"
    provider_product: Literal["fantasy_premierleague"] = "fantasy_premierleague"
    parser_contract_version: Literal["fpl-reference-v1"] = "fpl-reference-v1"
    current_contract_version: Literal["current-fpl-input-v1"] = CURRENT_FPL_CONTRACT_VERSION
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
    input_bundle_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transport_called: Literal[False] = False
    database_accessed: Literal[False] = False
    raw_storage_performed: Literal[False] = False
    derived_storage_performed: Literal[False] = False

    @field_validator("captured_at", "received_at", "information_cutoff", "usable_at")
    @classmethod
    def normalize_provenance_times(cls, value: datetime) -> datetime:
        return _normalize_utc(value, label="current FPL provenance timestamp")

    @model_validator(mode="after")
    def temporal_order_is_valid(self) -> Self:
        if not (self.captured_at <= self.received_at <= self.usable_at <= self.information_cutoff):
            raise ValueError("current FPL provenance timestamps are out of order")
        return self


class CurrentFplRightsBoundary(FrozenModel):
    rights_profile_id: Literal["fpl_official_private_manual_v1"] = OFFICIAL_MANUAL_PROFILE_ID
    rights_profile_version: Literal["1.0.0"] = "1.0.0"
    decisions: tuple[RightsDecision, ...]
    unresolved_rights: tuple[str, ...]
    automated_access_profile_value: Literal["DENY"] = "DENY"
    raw_storage_profile_value: Literal["DENY"] = "DENY"
    derived_storage_profile_value: Literal["UNKNOWN", "DENY"]
    automated_access: Literal["DENY"] = "DENY"
    raw_storage: Literal["DENY"] = "DENY"
    derived_storage: Literal["DENY"] = "DENY"
    cache: Literal["DENY"] = "DENY"
    backup: Literal["DENY"] = "DENY"
    database_accessed: Literal[False] = False
    raw_storage_performed: Literal[False] = False
    derived_storage_performed: Literal[False] = False
    operator_delete_required: Literal[True] = True
    disclosure_mode: Literal["SAFE_SUMMARY_ONLY"] = "SAFE_SUMMARY_ONLY"

    @model_validator(mode="after")
    def decision_set_is_exact(self) -> Self:
        expected = (
            ("manual_import", "ALLOW"),
            ("transient_processing", "ALLOW"),
            ("private_internal_use", "ALLOW"),
            ("automated_access", "DENY"),
            ("raw_storage", "DENY"),
            ("derived_storage", "DENY"),
        )
        actual = tuple((item.capability, item.decision) for item in self.decisions)
        if actual != expected:
            raise ValueError("current FPL rights decisions are inconsistent")
        return self


class CurrentFplInputSummary(FrozenModel):
    """Disclosure-minimized public representation of a valid private bundle."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["CURRENT_FPL_INPUT_SUMMARY"] = "CURRENT_FPL_INPUT_SUMMARY"
    status: Literal["VALID", "VALID_WITH_WARNINGS"]
    provider: Literal["official_fpl"] = "official_fpl"
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: int = Field(gt=0)
    gameweek_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_deadline_at: datetime
    captured_at: datetime
    received_at: datetime
    information_cutoff: datetime
    usable_at: datetime
    team_count: int = Field(gt=0)
    player_count: int = Field(gt=0)
    position_definition_count: int = Field(gt=0)
    event_count: int = Field(gt=0)
    fixture_count: int = Field(gt=0)
    target_gameweek_fixture_count: int = Field(gt=0)
    position_counts: dict[str, int]
    status_counts: dict[str, int]
    current_price_tenths_min: int = Field(gt=0)
    current_price_tenths_max: int = Field(gt=0)
    bootstrap_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bootstrap_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixtures_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixtures_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    game_settings_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rights_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_bundle_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_quality_status: Literal["PASS", "PASS_WITH_WARNINGS"]
    data_quality_warning_count: int = Field(ge=0)
    rights_profile_id: Literal["fpl_official_private_manual_v1"] = OFFICIAL_MANUAL_PROFILE_ID
    manual_import: Literal["ALLOW"] = "ALLOW"
    transient_processing: Literal["ALLOW"] = "ALLOW"
    private_internal_use: Literal["ALLOW"] = "ALLOW"
    automated_access: Literal["DENY"] = "DENY"
    raw_storage: Literal["DENY"] = "DENY"
    derived_storage_profile_value: Literal["UNKNOWN", "DENY"]
    derived_storage: Literal["DENY"] = "DENY"
    cache: Literal["DENY"] = "DENY"
    backup: Literal["DENY"] = "DENY"
    transport_called: Literal[False] = False
    database_accessed: Literal[False] = False
    raw_storage_performed: Literal[False] = False
    derived_storage_performed: Literal[False] = False
    operator_delete_required: Literal[True] = True


class CurrentFplInputBundle(FrozenModel):
    """Complete private current-input contract for immediate transient use."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["CURRENT_FPL_INPUT_BUNDLE"] = "CURRENT_FPL_INPUT_BUNDLE"
    provider: Literal["official_fpl"] = "official_fpl"
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: int = Field(gt=0)
    target_event: CurrentFplEvent
    events: tuple[CurrentFplEvent, ...] = Field(min_length=1)
    teams: tuple[CurrentFplTeam, ...] = Field(min_length=1)
    positions: tuple[CurrentFplPositionDefinition, ...] = Field(min_length=1)
    players: tuple[CurrentFplPlayer, ...] = Field(min_length=1)
    fixtures: tuple[CurrentFplFixture, ...] = Field(min_length=1)
    game_settings: CurrentFplGameSettings
    provenance: CurrentFplProvenance
    rights: CurrentFplRightsBoundary
    quality: QualityReport
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def bundle_lineage_is_consistent(self) -> Self:
        if self.semantic_sha256 != self.provenance.input_bundle_semantic_sha256:
            raise ValueError("bundle and provenance semantic digests differ")
        if self.target_event.provider_event_id != self.target_gameweek:
            raise ValueError("target event differs from target Gameweek")
        if self.target_event not in self.events:
            raise ValueError("target event is absent from the event catalogue")
        return self

    def safe_summary(self) -> CurrentFplInputSummary:
        """Return the only representation intended for public/CLI disclosure."""

        position_counts = Counter(player.position.value for player in self.players)
        status_counts = Counter(player.status for player in self.players)
        prices = tuple(player.current_price_tenths for player in self.players)
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
            target_deadline_at=self.target_event.deadline_at,
            captured_at=self.provenance.captured_at,
            received_at=self.provenance.received_at,
            information_cutoff=self.provenance.information_cutoff,
            usable_at=self.provenance.usable_at,
            team_count=len(self.teams),
            player_count=len(self.players),
            position_definition_count=len(self.positions),
            event_count=len(self.events),
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
            game_settings_semantic_sha256=self.game_settings.semantic_sha256,
            provider_config_sha256=self.provenance.provider_config_sha256,
            rights_config_sha256=self.provenance.rights_config_sha256,
            input_bundle_semantic_sha256=self.semantic_sha256,
            data_quality_status=quality_status,
            data_quality_warning_count=self.quality.warning_count,
            derived_storage_profile_value=self.rights.derived_storage_profile_value,
        )


def _identity(
    *,
    entity_type: Literal["PLAYER", "TEAM", "FIXTURE", "GAMEWEEK"],
    external_id: int,
) -> CurrentFplIdentity:
    namespace = _IDENTITY_NAMESPACE_BY_ENTITY[entity_type]
    material = {
        "entity_type": entity_type,
        "external_id_text": str(external_id),
        "identifier_namespace": namespace,
        "provider_key": "official_fpl",
        "provider_product": "fantasy_premierleague",
        "season_code": SUPPORTED_SEASON_CODE,
    }
    return CurrentFplIdentity(
        entity_type=entity_type,
        identifier_namespace=namespace,
        external_id_text=str(external_id),
        canonical_lookup_sha256=canonical_sha256(material),
    )


@dataclass(frozen=True)
class _OpenedManualInput:
    descriptor: int
    metadata: os.stat_result


def _manual_input_open_flags() -> int:
    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        flags |= int(getattr(os, name, 0))
    return flags


def _regular_file(metadata: os.stat_result) -> bool:
    return not stat.S_ISLNK(metadata.st_mode) and stat.S_ISREG(metadata.st_mode)


@contextmanager
def _open_verified_input(path: Path) -> Iterator[_OpenedManualInput]:
    """Open once and bind all validation and reads to the resulting descriptor."""

    descriptor: int | None = None
    try:
        before = os.lstat(path)
        if not _regular_file(before):
            raise OSError("input is not a regular file")
        descriptor = os.open(path, _manual_input_open_flags())
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
            raise OSError("opened input differs from validated path")
        after = os.lstat(path)
        if not _regular_file(after) or not os.path.samestat(after, opened):
            raise OSError("input path changed while opening")
        yield _OpenedManualInput(descriptor=descriptor, metadata=opened)
    except OSError:
        raise IngestionError("SOURCE_UNAVAILABLE", "manual FPL input is unavailable") from None
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


def _bounded_descriptor_read(source: _OpenedManualInput, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining:
        chunk = os.read(source.descriptor, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    body = b"".join(chunks)
    if len(body) > maximum:
        raise IngestionError("PAYLOAD_TOO_LARGE", "manual FPL input exceeds the byte limit")
    return body


def _safe_read(path: Path) -> bytes:
    """Read one bounded operator-owned file from its verified descriptor."""

    maximum = load_provider_config().max_response_bytes
    with _open_verified_input(path) as source:
        return _bounded_descriptor_read(source, maximum)


def _parsed_payloads(
    request: CurrentFplInputRequest,
) -> tuple[ParsedFplResource, ParsedFplResource]:
    maximum = load_provider_config().max_response_bytes
    with ExitStack() as stack:
        bootstrap_source = stack.enter_context(_open_verified_input(request.bootstrap_path))
        fixtures_source = stack.enter_context(_open_verified_input(request.fixtures_path))
        if os.path.samestat(bootstrap_source.metadata, fixtures_source.metadata):
            raise IngestionError("USAGE_INVALID", "bootstrap and fixtures must be distinct files")
        bootstrap_body = _bounded_descriptor_read(bootstrap_source, maximum)
        fixtures_body = _bounded_descriptor_read(fixtures_source, maximum)
    bootstrap = parse_fpl_payload(
        FplResource.BOOTSTRAP,
        bootstrap_body,
        contract_version=CONTRACT_VERSION,
    )
    fixtures = parse_fpl_payload(
        FplResource.FIXTURES,
        fixtures_body,
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


def _require_unique(values: Sequence[int], *, subject: str) -> None:
    if len(values) != len(set(values)):
        raise IngestionError(
            "VALIDATION_FAILED", f"current FPL {subject} identifiers are duplicated"
        )


def _position_map(
    definitions: list[ElementType],
    *,
    source_semantic_sha256: str,
) -> tuple[dict[int, FPLPosition], tuple[CurrentFplPositionDefinition, ...]]:
    _require_unique(tuple(item.id for item in definitions), subject="position")
    by_provider_id: dict[int, FPLPosition] = {}
    canonical_seen: set[FPLPosition] = set()
    contracts: list[CurrentFplPositionDefinition] = []
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
        contracts.append(
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
    return by_provider_id, tuple(sorted(contracts, key=lambda item: item.canonical_position.value))


def _target_event(events: list[Event], target_gameweek: int) -> Event:
    if any(
        sum(flag is True for flag in (event.is_previous, event.is_current, event.is_next)) > 1
        for event in events
    ):
        raise IngestionError("VALIDATION_FAILED", "Gameweek state flags are inconsistent")
    current = tuple(event for event in events if event.is_current is True)
    following = tuple(event for event in events if event.is_next is True)
    if len(current) > 1 or len(following) > 1:
        raise IngestionError("VALIDATION_FAILED", "Gameweek state flags are inconsistent")
    if current and following and current[0].id == following[0].id:
        raise IngestionError("VALIDATION_FAILED", "Gameweek state flags are inconsistent")
    matches = tuple(event for event in events if event.id == target_gameweek)
    if len(matches) != 1:
        raise IngestionError("VALIDATION_FAILED", "target Gameweek is missing or ambiguous")
    target = matches[0]
    if target.finished is not False:
        raise IngestionError("VALIDATION_FAILED", "target Gameweek is not explicitly unfinished")
    if (target.is_previous, target.is_current, target.is_next) not in (
        (False, True, False),
        (False, False, True),
    ):
        raise IngestionError("VALIDATION_FAILED", "target Gameweek state is inconsistent")
    return target


def _validate_pair(
    bootstrap: BootstrapPayload,
    fixtures: FixturePayload,
    *,
    positions: Mapping[int, FPLPosition],
    target: Event,
    information_cutoff: datetime,
) -> None:
    if (
        not bootstrap.events
        or not bootstrap.teams
        or not bootstrap.elements
        or not bootstrap.element_types
    ):
        raise IngestionError("VALIDATION_FAILED", "current FPL catalogue is incomplete")
    if not bootstrap.game_settings:
        raise IngestionError("VALIDATION_FAILED", "FPL game settings are missing")
    if not fixtures.fixtures:
        raise IngestionError("VALIDATION_FAILED", "current FPL fixtures are empty")

    _require_unique(tuple(team.id for team in bootstrap.teams), subject="team")
    _require_unique(tuple(player.id for player in bootstrap.elements), subject="player")
    _require_unique(tuple(event.id for event in bootstrap.events), subject="event")
    _require_unique(tuple(fixture.id for fixture in fixtures.fixtures), subject="fixture")

    team_ids = {team.id for team in bootstrap.teams}
    event_ids = {event.id for event in bootstrap.events}
    for player in bootstrap.elements:
        if player.team not in team_ids:
            raise IngestionError("MAPPING_CONFLICT", "player references an unresolved team")
        if player.element_type not in positions:
            raise IngestionError("MAPPING_CONFLICT", "player references an unresolved position")
        if player.now_cost <= 0:
            raise IngestionError("VALIDATION_FAILED", "current FPL price must be positive")
        if player.news_added is not None and player.news_added > information_cutoff:
            raise IngestionError("POST_CUTOFF", "player availability evidence is post-cutoff")

    target_fixture_count = 0
    for fixture in fixtures.fixtures:
        if fixture.team_h not in team_ids or fixture.team_a not in team_ids:
            raise IngestionError("MAPPING_CONFLICT", "fixture references an unresolved team")
        if fixture.team_h == fixture.team_a:
            raise IngestionError("MAPPING_CONFLICT", "fixture home and away teams must differ")
        if fixture.event is not None and fixture.event not in event_ids:
            raise IngestionError("MAPPING_CONFLICT", "fixture references an unresolved Gameweek")
        if fixture.event == target.id:
            target_fixture_count += 1
            if fixture.kickoff_time is None:
                raise IngestionError(
                    "VALIDATION_FAILED", "target Gameweek fixture kickoff is missing"
                )
            if fixture.kickoff_time <= target.deadline_time:
                raise IngestionError(
                    "VALIDATION_FAILED", "target Gameweek fixture is not after its deadline"
                )
    if target_fixture_count == 0:
        raise IngestionError("VALIDATION_FAILED", "target Gameweek has no fixtures")


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


def _rights_profile_is_bounded(profile: RightsProfile) -> bool:
    expected = {
        RightsCapability.MANUAL_IMPORT: CapabilityValue.ALLOW,
        RightsCapability.TRANSIENT_PROCESSING: CapabilityValue.ALLOW,
        RightsCapability.PRIVATE_INTERNAL_USE: CapabilityValue.ALLOW,
        RightsCapability.AUTOMATED_ACCESS: CapabilityValue.DENY,
        RightsCapability.RAW_STORAGE: CapabilityValue.DENY,
        RightsCapability.CACHE: CapabilityValue.DENY,
        RightsCapability.BACKUP: CapabilityValue.DENY,
        RightsCapability.MODEL_TRAINING: CapabilityValue.DENY,
        RightsCapability.PUBLIC_DISPLAY: CapabilityValue.DENY,
        RightsCapability.REDISTRIBUTION: CapabilityValue.DENY,
    }
    return (
        profile.rights_profile_id == OFFICIAL_MANUAL_PROFILE_ID
        and profile.profile_version == "1.0.0"
        and profile.provider_key == "official_fpl"
        and profile.status is RightsProfileStatus.HUMAN_APPROVED
        and profile.retention_seconds == 0
        and profile.termination_deletion_required
        and all(profile.capabilities[capability] is value for capability, value in expected.items())
        and profile.capabilities[RightsCapability.DERIVED_STORAGE]
        in {CapabilityValue.UNKNOWN, CapabilityValue.DENY}
    )


def _rights_boundary(
    request: CurrentFplInputRequest,
    *,
    checked_at: datetime,
) -> CurrentFplRightsBoundary:
    profile = load_rights_profiles().get(request.rights_profile_id)
    if profile is None or not _rights_profile_is_bounded(profile):
        raise IngestionError(
            "RIGHTS_BLOCKED", "current FPL input requires the approved bounded manual profile"
        )
    capabilities = (
        RightsCapability.MANUAL_IMPORT,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.PRIVATE_INTERNAL_USE,
    )
    decisions = [
        require_rights(profile, capability, checked_at=checked_at) for capability in capabilities
    ]
    denied = (
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.RAW_STORAGE,
        RightsCapability.DERIVED_STORAGE,
    )
    decisions.extend(
        decide_rights(profile, capability, checked_at=checked_at) for capability in denied
    )
    if any(decision.decision != "DENY" for decision in decisions[3:]):
        raise IngestionError("CONFIGURATION_INVALID", "official FPL rights boundary has drifted")
    derived_profile_value: Literal["UNKNOWN", "DENY"] = (
        "UNKNOWN"
        if profile.capabilities[RightsCapability.DERIVED_STORAGE] is CapabilityValue.UNKNOWN
        else "DENY"
    )
    return CurrentFplRightsBoundary(
        decisions=tuple(decisions),
        unresolved_rights=profile.unresolved_rights,
        derived_storage_profile_value=derived_profile_value,
    )


def _event_contract(event: Event, *, source_semantic_sha256: str) -> CurrentFplEvent:
    return CurrentFplEvent(
        source_semantic_sha256=source_semantic_sha256,
        identity=_identity(entity_type="GAMEWEEK", external_id=event.id),
        provider_event_id=event.id,
        name=event.name,
        deadline_at=event.deadline_time,
        finished=event.finished,
        data_checked=event.data_checked,
        is_previous=event.is_previous,
        is_current=event.is_current,
        is_next=event.is_next,
    )


def _team_contract(team: Team, *, source_semantic_sha256: str) -> CurrentFplTeam:
    return CurrentFplTeam(
        source_semantic_sha256=source_semantic_sha256,
        identity=_identity(entity_type="TEAM", external_id=team.id),
        provider_team_id=team.id,
        provider_code=team.code,
        official_name=team.name,
        short_name=team.short_name,
    )


def _player_contract(
    player: PlayerElement,
    *,
    teams: Mapping[int, CurrentFplTeam],
    positions: Mapping[int, FPLPosition],
    source_semantic_sha256: str,
) -> CurrentFplPlayer:
    return CurrentFplPlayer(
        source_semantic_sha256=source_semantic_sha256,
        identity=_identity(entity_type="PLAYER", external_id=player.id),
        provider_element_id=player.id,
        provider_code=player.code,
        first_name=player.first_name,
        second_name=player.second_name,
        web_name=player.web_name,
        team_identity=teams[player.team].identity,
        position=positions[player.element_type],
        current_price_tenths=player.now_cost,
        status=player.status,
        chance_of_playing_this_round=player.chance_of_playing_this_round,
        chance_of_playing_next_round=player.chance_of_playing_next_round,
        news=player.news,
        news_added=player.news_added,
    )


def _fixture_contract(
    fixture: Fixture,
    *,
    teams: Mapping[int, CurrentFplTeam],
    events: Mapping[int, CurrentFplEvent],
    source_semantic_sha256: str,
) -> CurrentFplFixture:
    return CurrentFplFixture(
        source_semantic_sha256=source_semantic_sha256,
        identity=_identity(entity_type="FIXTURE", external_id=fixture.id),
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

    def __init__(self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock

    def _clock_utc(self) -> datetime:
        value = self._clock()
        try:
            return _normalize_utc(value, label="current FPL clock")
        except ValueError as exc:
            raise IngestionError(
                "INTERNAL_INVARIANT", "current FPL clock must be timezone-aware"
            ) from exc

    def compile(self, request: CurrentFplInputRequest) -> CurrentFplInputBundle:
        if request.competition_key != SUPPORTED_COMPETITION_KEY:
            raise IngestionError("VALIDATION_FAILED", "competition metadata is not target EPL")
        if request.season_code != SUPPORTED_SEASON_CODE:
            raise IngestionError(
                "VALIDATION_FAILED", "season metadata is not the supported target season"
            )

        received_at = self._clock_utc()
        if request.captured_at > request.information_cutoff:
            raise IngestionError("POST_CUTOFF", "current FPL capture is post-cutoff")
        if request.captured_at > received_at:
            raise IngestionError("VALIDATION_FAILED", "captured_at is after receipt time")
        if received_at > request.information_cutoff:
            raise IngestionError("POST_CUTOFF", "current FPL input was received post-cutoff")

        rights = _rights_boundary(request, checked_at=received_at)
        parsed_bootstrap, parsed_fixtures = _parsed_payloads(request)
        bootstrap, fixtures = _payload_pair(parsed_bootstrap, parsed_fixtures)
        _require_unique(tuple(event.id for event in bootstrap.events), subject="event")
        target = _target_event(bootstrap.events, request.target_gameweek)
        if request.information_cutoff > target.deadline_time:
            raise IngestionError("POST_CUTOFF", "information cutoff exceeds the official deadline")
        position_map, position_contracts = _position_map(
            bootstrap.element_types,
            source_semantic_sha256=parsed_bootstrap.semantic_sha256,
        )
        _validate_pair(
            bootstrap,
            fixtures,
            positions=position_map,
            target=target,
            information_cutoff=request.information_cutoff,
        )

        events = tuple(
            sorted(
                (
                    _event_contract(event, source_semantic_sha256=parsed_bootstrap.semantic_sha256)
                    for event in bootstrap.events
                ),
                key=lambda item: item.provider_event_id,
            )
        )
        event_by_id = {event.provider_event_id: event for event in events}
        teams = tuple(
            sorted(
                (
                    _team_contract(team, source_semantic_sha256=parsed_bootstrap.semantic_sha256)
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
                        teams=team_by_id,
                        events=event_by_id,
                        source_semantic_sha256=parsed_fixtures.semantic_sha256,
                    )
                    for fixture in fixtures.fixtures
                ),
                key=lambda item: item.provider_fixture_id,
            )
        )
        serialized_settings = _canonical_game_setting(bootstrap.game_settings)
        if not isinstance(serialized_settings, dict):
            raise IngestionError("INTERNAL_INVARIANT", "FPL game settings are invalid")
        game_settings = CurrentFplGameSettings(
            source_semantic_sha256=parsed_bootstrap.semantic_sha256,
            canonical_json=canonical_json_bytes(serialized_settings).decode("utf-8"),
            semantic_sha256=canonical_sha256(serialized_settings),
        )
        quality = _quality(parsed_bootstrap, parsed_fixtures, observed_at=received_at)
        usable_at = self._clock_utc()
        if usable_at < received_at:
            raise IngestionError("INTERNAL_INVARIANT", "current FPL clock moved backwards")
        if usable_at > request.information_cutoff:
            raise IngestionError("POST_CUTOFF", "current FPL input became usable post-cutoff")

        provider_sha256 = provider_config_sha256()
        rights_sha256 = rights_config_sha256()
        semantic_sha256 = canonical_sha256(
            {
                "bootstrap_semantic_sha256": parsed_bootstrap.semantic_sha256,
                "captured_at": _utc_text(request.captured_at),
                "competition_key": request.competition_key,
                "current_contract_version": CURRENT_FPL_CONTRACT_VERSION,
                "fixtures_semantic_sha256": parsed_fixtures.semantic_sha256,
                "game_settings_semantic_sha256": game_settings.semantic_sha256,
                "information_cutoff": _utc_text(request.information_cutoff),
                "provider_config_sha256": provider_sha256,
                "received_at": _utc_text(received_at),
                "rights_config_sha256": rights_sha256,
                "rights_profile_id": rights.rights_profile_id,
                "season_code": request.season_code,
                "target_gameweek": request.target_gameweek,
                "usable_at": _utc_text(usable_at),
            }
        )
        provenance = CurrentFplProvenance(
            captured_at=request.captured_at,
            received_at=received_at,
            information_cutoff=request.information_cutoff,
            usable_at=usable_at,
            bootstrap_payload_sha256=parsed_bootstrap.payload_sha256,
            bootstrap_semantic_sha256=parsed_bootstrap.semantic_sha256,
            fixtures_payload_sha256=parsed_fixtures.payload_sha256,
            fixtures_semantic_sha256=parsed_fixtures.semantic_sha256,
            provider_config_sha256=provider_sha256,
            rights_config_sha256=rights_sha256,
            input_bundle_semantic_sha256=semantic_sha256,
        )
        return CurrentFplInputBundle(
            target_gameweek=request.target_gameweek,
            target_event=event_by_id[target.id],
            events=events,
            teams=teams,
            positions=position_contracts,
            players=players,
            fixtures=fixture_contracts,
            game_settings=game_settings,
            provenance=provenance,
            rights=rights,
            quality=quality,
            semantic_sha256=semantic_sha256,
        )


__all__ = [
    "CURRENT_FPL_CONTRACT_VERSION",
    "OFFICIAL_MANUAL_PROFILE_ID",
    "SUPPORTED_COMPETITION_KEY",
    "SUPPORTED_SEASON_CODE",
    "CurrentFplEvent",
    "CurrentFplFixture",
    "CurrentFplGameSettings",
    "CurrentFplIdentity",
    "CurrentFplInputBundle",
    "CurrentFplInputRequest",
    "CurrentFplInputService",
    "CurrentFplInputSummary",
    "CurrentFplPlayer",
    "CurrentFplPositionDefinition",
    "CurrentFplProvenance",
    "CurrentFplRightsBoundary",
    "CurrentFplTeam",
]
