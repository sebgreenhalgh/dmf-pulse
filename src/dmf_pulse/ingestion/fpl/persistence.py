"""Season-scoped canonical mapping, typed observations, and source bundles."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from psycopg.types.range import Range
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Table, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.models import require_utc
from dmf_pulse.data_model.tables import (
    canonical_entity,
    competition,
    data_provider,
    entity_alias,
    external_identifier,
    fixture,
    fixture_gameweek_assignment,
    fixture_observation,
    fixture_revision,
    gameweek,
    gameweek_observation,
    player,
    player_observation,
    player_season,
    player_team_membership,
    season,
    semantic_effect_source,
    semantic_observation_claim,
    source_bundle,
    source_bundle_member,
    source_mapping_candidate,
    source_processing_event,
    source_snapshot,
    team,
    team_observation,
    team_season,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.parser import BootstrapPayload, FixturePayload, ParsedFplResource
from dmf_pulse.ingestion.models import (
    SourceBundleMember,
    SourceBundleSummary,
)

CONTRACT_VERSION = "fpl-reference-v1"
POSITION_CODES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
MappingEntityType = Literal["COMPETITION", "SEASON", "TEAM", "PLAYER", "GAMEWEEK", "FIXTURE"]


class MappingPlanEntry(BaseModel):
    """One immutable, exact canonical identity reservation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_product: str = Field(min_length=1, max_length=64)
    identifier_namespace: str = Field(min_length=1, max_length=96)
    entity_type: MappingEntityType
    external_id_text: str = Field(min_length=1)
    canonical_entity_id: UUID


class FplMappingPlan(BaseModel):
    """Frozen mapping artifact produced before canonical publication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_version: Literal["fpl-mapping-plan-v1"] = "fpl-mapping-plan-v1"
    competition_key: str = Field(min_length=1, max_length=80)
    season_code: str = Field(min_length=1, max_length=32)
    resource_semantic_sha256: tuple[str, str]
    entries: tuple[MappingPlanEntry, ...]

    @model_validator(mode="after")
    def validate_identity_reservations(self) -> FplMappingPlan:
        keys = [
            (
                entry.provider_product,
                entry.identifier_namespace,
                entry.entity_type,
                entry.external_id_text,
            )
            for entry in self.entries
        ]
        if len(keys) != len(set(keys)) or tuple(keys) != tuple(sorted(keys)):
            raise ValueError("mapping plan entries must be unique and sorted")
        if len(self.resource_semantic_sha256) != 2 or any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in self.resource_semantic_sha256
        ):
            raise ValueError("mapping plan resource hashes are invalid")
        self.resolve("context", "dmf.competition_key", "COMPETITION", self.competition_key)
        self.resolve(
            "context",
            "dmf.season_code",
            "SEASON",
            f"{self.competition_key}:{self.season_code}",
        )
        return self

    def resolve(
        self,
        product: str,
        namespace: str,
        entity_type: MappingEntityType,
        external_value: str,
    ) -> UUID:
        matches = [
            entry.canonical_entity_id
            for entry in self.entries
            if (
                entry.provider_product,
                entry.identifier_namespace,
                entry.entity_type,
                entry.external_id_text,
            )
            == (product, namespace, entity_type, external_value)
        ]
        if len(matches) != 1:
            raise ValueError("mapping plan does not contain exactly one requested identity")
        return matches[0]


def _uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise IngestionError("CANONICAL_INVARIANT", "database returned an invalid identifier")
    return value


def _utc_text(value: datetime) -> str:
    return require_utc(value).isoformat().replace("+00:00", "Z")


def _range_lower(value: Range[datetime]) -> datetime:
    lower = value.lower
    if lower is None:
        raise IngestionError("CANONICAL_INVARIANT", "temporal range has no lower bound")
    return require_utc(lower)


def _semantic_fields(values: dict[str, object]) -> dict[str, object]:
    return {
        key: _utc_text(value)
        if isinstance(value, datetime)
        else str(value)
        if hasattr(value, "as_tuple")
        else value
        for key, value in values.items()
    }


def _field_missingness(source: Any, fields: dict[str, str]) -> dict[str, str]:
    present: set[str] = getattr(source, "model_fields_set", set())
    return {
        target: "NOT_PUBLISHED"
        for target, source_name in sorted(fields.items())
        if source_name not in present
    }


def _advisory_lock(session: Session, key: str) -> None:
    session.execute(text("SET LOCAL lock_timeout = '5s'"))
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": key},
    )


def _source_captured_at(session: Session, snapshot_id: object) -> datetime:
    if not isinstance(snapshot_id, UUID):
        raise IngestionError("MAPPING_CONFLICT", "canonical fact lacks source chronology")
    captured_at = session.scalar(
        select(source_snapshot.c.request_started_at).where(
            source_snapshot.c.source_snapshot_id == snapshot_id
        )
    )
    if not isinstance(captured_at, datetime):
        raise IngestionError("MAPPING_CONFLICT", "canonical fact lacks source chronology")
    return require_utc(captured_at)


def _successor_system_at(system_at: datetime, current: Range[datetime]) -> datetime:
    current_start = _range_lower(current)
    return max(require_utc(system_at), current_start + timedelta(microseconds=1))


def _ensure_provider(
    session: Session,
    *,
    provider_key: str,
    display_name: str,
    provider_type: str,
    rights_profile_key: str,
) -> tuple[UUID, bool]:
    _advisory_lock(session, f"provider:{provider_key}")
    existing = (
        session.execute(select(data_provider).where(data_provider.c.provider_key == provider_key))
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        if (
            existing["display_name"] != display_name
            or existing["provider_type"] != provider_type
            or existing["rights_profile_key"] != rights_profile_key
        ):
            raise IngestionError(
                "CONFIGURATION_INVALID", "provider record conflicts with configured authority"
            )
        return _uuid(existing["provider_id"]), False
    entity_id = _uuid(
        session.execute(
            insert(canonical_entity)
            .values(entity_type="DATA_PROVIDER")
            .returning(canonical_entity.c.entity_id)
        ).scalar_one()
    )
    session.execute(
        insert(data_provider).values(
            provider_id=entity_id,
            entity_type="DATA_PROVIDER",
            provider_key=provider_key,
            display_name=display_name,
            provider_type=provider_type,
            rights_profile_key=rights_profile_key,
        )
    )
    return entity_id, True


def ensure_synthetic_provider(session: Session) -> tuple[UUID, bool]:
    """Return the governed synthetic provider, creating it under a transaction lock."""

    return _ensure_provider(
        session,
        provider_key="synthetic_fpl",
        display_name="Synthetic FPL reference provider",
        provider_type="INTERNAL",
        rights_profile_key="synthetic_test_v1",
    )


def ensure_official_provider(session: Session) -> tuple[UUID, bool]:
    """Return the metadata-only official provider used by transient manual imports."""

    return _ensure_provider(
        session,
        provider_key="official_fpl",
        display_name="Official FPL transient manual source",
        provider_type="OFFICIAL",
        rights_profile_key="fpl_official_private_manual_v1",
    )


def _season_dates(season_code: str) -> tuple[date, date]:
    if season_code != "2026/27":
        raise IngestionError(
            "CONFIGURATION_INVALID", "FPL-004 supports only the explicit 2026/27 season"
        )
    return date(2026, 8, 1), date(2027, 5, 31)


def _valid_range(season_code: str) -> Range[datetime]:
    starts_on, ends_on = _season_dates(season_code)
    return Range(
        datetime.combine(starts_on, datetime.min.time(), tzinfo=UTC),
        datetime.combine(ends_on + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
        bounds="[)",
    )


class EffectCounts:
    def __init__(self) -> None:
        self.created: dict[str, int] = {}
        self.reused: dict[str, int] = {}
        self.changed: dict[str, int] = {}

    def add(self, category: str, state: str) -> None:
        target = (
            self.created
            if state == "created"
            else self.changed
            if state == "changed"
            else self.reused
        )
        target[category] = target.get(category, 0) + 1

    def as_dict(self) -> dict[str, dict[str, int]]:
        return {
            "changed": dict(sorted(self.changed.items())),
            "created": dict(sorted(self.created.items())),
            "reused": dict(sorted(self.reused.items())),
        }


class FplPersistence:
    def __init__(
        self,
        session: Session,
        *,
        captured_at: datetime,
        system_at: datetime | None = None,
        competition_key: str,
        season_code: str,
        bootstrap_snapshot_id: UUID,
        fixtures_snapshot_id: UUID,
    ) -> None:
        self.session = session
        self.captured_at = require_utc(captured_at)
        self.system_at = require_utc(system_at or captured_at)
        if self.system_at < self.captured_at:
            raise IngestionError(
                "LIFECYCLE_INVARIANT", "system knowledge time precedes source receipt"
            )
        self.competition_key = competition_key
        self.season_code = season_code
        self.bootstrap_snapshot_id = bootstrap_snapshot_id
        self.fixtures_snapshot_id = fixtures_snapshot_id
        self.counts = EffectCounts()

    def ensure_provider(self) -> UUID:
        provider_id, created = ensure_synthetic_provider(self.session)
        self.counts.add("data_provider", "created" if created else "reused")
        return provider_id

    def _reserve_identity(
        self,
        *,
        provider_id: UUID,
        season_id: UUID,
        keys: tuple[tuple[str, str, str], ...],
        entity_type: MappingEntityType,
        snapshot_id: UUID,
        current_ids: set[UUID] | None = None,
    ) -> tuple[MappingPlanEntry, ...]:
        lock_keys: list[str] = []
        for product, namespace, external_value in keys:
            lock_keys.extend(
                (
                    f"candidate:{provider_id}:{self.competition_key}:{self.season_code}:"
                    f"{product}:{namespace}:{entity_type}:{external_value}",
                    f"external:{provider_id}:{season_id}:{product}:{namespace}:"
                    f"{entity_type}:{external_value}",
                )
            )
        for lock_key in sorted(lock_keys):
            _advisory_lock(self.session, lock_key)

        resolved_ids = set(current_ids or set())
        for product, namespace, external_value in keys:
            current = self.session.execute(
                select(external_identifier.c.canonical_entity_id).where(
                    external_identifier.c.provider_id == provider_id,
                    external_identifier.c.season_id == season_id,
                    external_identifier.c.provider_product == product,
                    external_identifier.c.identifier_namespace == namespace,
                    external_identifier.c.entity_type == entity_type,
                    external_identifier.c.external_id_text == external_value,
                    external_identifier.c.mapping_status.in_(("AUTO_MATCHED", "HUMAN_VERIFIED")),
                    func.upper_inf(external_identifier.c.system_during),
                )
            ).scalar_one_or_none()
            if current is not None:
                resolved_ids.add(_uuid(current))
            candidate = self.session.execute(
                select(source_mapping_candidate.c.planned_entity_id).where(
                    source_mapping_candidate.c.provider_id == provider_id,
                    source_mapping_candidate.c.competition_key == self.competition_key,
                    source_mapping_candidate.c.season_code == self.season_code,
                    source_mapping_candidate.c.provider_product == product,
                    source_mapping_candidate.c.identifier_namespace == namespace,
                    source_mapping_candidate.c.entity_type == entity_type,
                    source_mapping_candidate.c.external_id_text == external_value,
                )
            ).scalar_one_or_none()
            if candidate is not None:
                resolved_ids.add(_uuid(candidate))
        if len(resolved_ids) > 1:
            raise IngestionError(
                "MAPPING_CONFLICT", "mapping candidates resolve to different canonical identities"
            )
        if resolved_ids:
            planned_id = resolved_ids.pop()
        else:
            planned_id = _uuid(self.session.execute(text("SELECT uuidv7()")).scalar_one())

        entries: list[MappingPlanEntry] = []
        for product, namespace, external_value in keys:
            self.session.execute(
                postgresql_insert(source_mapping_candidate)
                .values(
                    provider_id=provider_id,
                    competition_key=self.competition_key,
                    season_code=self.season_code,
                    provider_product=product,
                    identifier_namespace=namespace,
                    entity_type=entity_type,
                    external_id_text=external_value,
                    planned_entity_id=planned_id,
                    evidence_source_snapshot_id=snapshot_id,
                )
                .on_conflict_do_nothing(constraint="uq_mapping_candidate_scope")
            )
            persisted = _uuid(
                self.session.execute(
                    select(source_mapping_candidate.c.planned_entity_id).where(
                        source_mapping_candidate.c.provider_id == provider_id,
                        source_mapping_candidate.c.competition_key == self.competition_key,
                        source_mapping_candidate.c.season_code == self.season_code,
                        source_mapping_candidate.c.provider_product == product,
                        source_mapping_candidate.c.identifier_namespace == namespace,
                        source_mapping_candidate.c.entity_type == entity_type,
                        source_mapping_candidate.c.external_id_text == external_value,
                    )
                ).scalar_one()
            )
            if persisted != planned_id:
                raise IngestionError(
                    "MAPPING_CONFLICT", "mapping candidate reservation changed concurrently"
                )
            entries.append(
                MappingPlanEntry(
                    provider_product=product,
                    identifier_namespace=namespace,
                    entity_type=entity_type,
                    external_id_text=external_value,
                    canonical_entity_id=planned_id,
                )
            )
        return tuple(entries)

    def stage_mapping(
        self,
        bootstrap: ParsedFplResource,
        fixtures: ParsedFplResource,
    ) -> FplMappingPlan:
        """Reserve every exact identity without publishing a canonical row."""

        if not isinstance(bootstrap.payload, BootstrapPayload) or not isinstance(
            fixtures.payload, FixturePayload
        ):
            raise IngestionError("INTERNAL_INVARIANT", "parsed FPL resource types differ")
        provider_id = self.ensure_provider()
        entries: list[MappingPlanEntry] = []

        _advisory_lock(self.session, f"competition:{self.competition_key}")
        current_competition = self.session.execute(
            select(competition.c.competition_id).where(
                competition.c.competition_key == self.competition_key
            )
        ).scalar_one_or_none()
        entries.extend(
            self._reserve_identity(
                provider_id=provider_id,
                season_id=UUID(int=0),
                keys=(("context", "dmf.competition_key", self.competition_key),),
                entity_type="COMPETITION",
                snapshot_id=self.bootstrap_snapshot_id,
                current_ids=(
                    {_uuid(current_competition)} if current_competition is not None else set()
                ),
            )
        )
        competition_id = entries[-1].canonical_entity_id
        _advisory_lock(self.session, f"season:{competition_id}:{self.season_code}")
        current_season = self.session.execute(
            select(season.c.season_id).where(
                season.c.competition_id == competition_id,
                season.c.season_code == self.season_code,
            )
        ).scalar_one_or_none()
        entries.extend(
            self._reserve_identity(
                provider_id=provider_id,
                season_id=UUID(int=0),
                keys=(
                    (
                        "context",
                        "dmf.season_code",
                        f"{self.competition_key}:{self.season_code}",
                    ),
                ),
                entity_type="SEASON",
                snapshot_id=self.bootstrap_snapshot_id,
                current_ids={_uuid(current_season)} if current_season is not None else set(),
            )
        )
        season_id = entries[-1].canonical_entity_id

        for source_team in bootstrap.payload.teams:
            entries.extend(
                self._reserve_identity(
                    provider_id=provider_id,
                    season_id=season_id,
                    keys=(
                        ("bootstrap", "fpl.team.id", str(source_team.id)),
                        ("bootstrap", "fpl.team.code", str(source_team.code)),
                    ),
                    entity_type="TEAM",
                    snapshot_id=self.bootstrap_snapshot_id,
                )
            )
        for source_player in bootstrap.payload.elements:
            entries.extend(
                self._reserve_identity(
                    provider_id=provider_id,
                    season_id=season_id,
                    keys=(
                        ("bootstrap", "fpl.element.id", str(source_player.id)),
                        ("bootstrap", "fpl.element.code", str(source_player.code)),
                    ),
                    entity_type="PLAYER",
                    snapshot_id=self.bootstrap_snapshot_id,
                )
            )
        for source_event in bootstrap.payload.events:
            entries.extend(
                self._reserve_identity(
                    provider_id=provider_id,
                    season_id=season_id,
                    keys=(("bootstrap", "fpl.event.id", str(source_event.id)),),
                    entity_type="GAMEWEEK",
                    snapshot_id=self.bootstrap_snapshot_id,
                )
            )
        for source_fixture in fixtures.payload.fixtures:
            entries.extend(
                self._reserve_identity(
                    provider_id=provider_id,
                    season_id=season_id,
                    keys=(
                        ("fixtures", "fpl.fixture.id", str(source_fixture.id)),
                        ("fixtures", "fpl.fixture.code", str(source_fixture.code)),
                    ),
                    entity_type="FIXTURE",
                    snapshot_id=self.fixtures_snapshot_id,
                )
            )
        return FplMappingPlan(
            competition_key=self.competition_key,
            season_code=self.season_code,
            resource_semantic_sha256=(bootstrap.semantic_sha256, fixtures.semantic_sha256),
            entries=tuple(
                sorted(
                    entries,
                    key=lambda item: (
                        item.provider_product,
                        item.identifier_namespace,
                        item.entity_type,
                        item.external_id_text,
                    ),
                )
            ),
        )

    def verify_mapping_plan(self, plan: FplMappingPlan) -> None:
        if plan.competition_key != self.competition_key or plan.season_code != self.season_code:
            raise IngestionError("LIFECYCLE_INVARIANT", "mapping context changed")
        provider_id = self.ensure_provider()
        for entry in plan.entries:
            persisted = self.session.execute(
                select(source_mapping_candidate.c.planned_entity_id).where(
                    source_mapping_candidate.c.provider_id == provider_id,
                    source_mapping_candidate.c.competition_key == self.competition_key,
                    source_mapping_candidate.c.season_code == self.season_code,
                    source_mapping_candidate.c.provider_product == entry.provider_product,
                    source_mapping_candidate.c.identifier_namespace == entry.identifier_namespace,
                    source_mapping_candidate.c.entity_type == entry.entity_type,
                    source_mapping_candidate.c.external_id_text == entry.external_id_text,
                )
            ).scalar_one_or_none()
            if persisted is None or _uuid(persisted) != entry.canonical_entity_id:
                raise IngestionError(
                    "LIFECYCLE_INVARIANT", "mapping reservation no longer matches its artifact"
                )

    def ensure_competition_and_season(self, plan: FplMappingPlan) -> tuple[UUID, UUID]:
        self.verify_mapping_plan(plan)
        _advisory_lock(self.session, f"competition:{self.competition_key}")
        competition_id = self.session.execute(
            select(competition.c.competition_id).where(
                competition.c.competition_key == self.competition_key
            )
        ).scalar_one_or_none()
        planned_competition_id = plan.resolve(
            "context", "dmf.competition_key", "COMPETITION", self.competition_key
        )
        if competition_id is None:
            competition_id = self._canonical_entity("COMPETITION", entity_id=planned_competition_id)
            self.session.execute(
                insert(competition).values(
                    competition_id=competition_id,
                    entity_type="COMPETITION",
                    competition_key=self.competition_key,
                    canonical_name="Synthetic Premier League",
                    country_code="GB",
                )
            )
            self.counts.add("competition", "created")
        else:
            if _uuid(competition_id) != planned_competition_id:
                raise IngestionError("MAPPING_CONFLICT", "competition identity changed")
            self.counts.add("competition", "reused")
        competition_uuid = _uuid(competition_id)
        _advisory_lock(self.session, f"season:{competition_uuid}:{self.season_code}")
        season_id = self.session.execute(
            select(season.c.season_id).where(
                season.c.competition_id == competition_uuid,
                season.c.season_code == self.season_code,
            )
        ).scalar_one_or_none()
        planned_season_id = plan.resolve(
            "context",
            "dmf.season_code",
            "SEASON",
            f"{self.competition_key}:{self.season_code}",
        )
        if season_id is None:
            starts_on, ends_on = _season_dates(self.season_code)
            season_id = self._canonical_entity("SEASON", entity_id=planned_season_id)
            self.session.execute(
                insert(season).values(
                    season_id=season_id,
                    entity_type="SEASON",
                    competition_id=competition_uuid,
                    season_code=self.season_code,
                    starts_on=starts_on,
                    ends_on=ends_on,
                )
            )
            self.counts.add("season", "created")
        else:
            if _uuid(season_id) != planned_season_id:
                raise IngestionError("MAPPING_CONFLICT", "season identity changed")
            self.counts.add("season", "reused")
        return competition_uuid, _uuid(season_id)

    def promote(
        self,
        bootstrap: ParsedFplResource,
        fixtures: ParsedFplResource,
        plan: FplMappingPlan,
    ) -> tuple[UUID, UUID]:
        if not isinstance(bootstrap.payload, BootstrapPayload) or not isinstance(
            fixtures.payload, FixturePayload
        ):
            raise IngestionError("INTERNAL_INVARIANT", "parsed FPL resource types differ")
        if plan.resource_semantic_sha256 != (
            bootstrap.semantic_sha256,
            fixtures.semantic_sha256,
        ):
            raise IngestionError("LIFECYCLE_INVARIANT", "mapping plan inputs changed")
        provider_id = self.ensure_provider()
        competition_id, season_id = self.ensure_competition_and_season(plan)
        team_ids: dict[int, UUID] = {}
        team_season_ids: dict[int, UUID] = {}
        for source_team in bootstrap.payload.teams:
            team_id, created = self._external_entity(
                provider_id=provider_id,
                season_id=season_id,
                product="bootstrap",
                namespace="fpl.team.id",
                external_value=str(source_team.id),
                entity_type="TEAM",
                typed_table=team,
                id_column="team_id",
                attributes={
                    "canonical_name": source_team.name,
                    "short_name": source_team.short_name,
                },
                fallback_identifier=("fpl.team.code", str(source_team.code)),
                snapshot_id=self.bootstrap_snapshot_id,
                planned_id=plan.resolve("bootstrap", "fpl.team.id", "TEAM", str(source_team.id)),
            )
            self._ensure_secondary_identifier(
                canonical_id=team_id,
                provider_id=provider_id,
                season_id=season_id,
                product="bootstrap",
                namespace="fpl.team.code",
                entity_type="TEAM",
                external_value=str(source_team.code),
                snapshot_id=self.bootstrap_snapshot_id,
            )
            self._ensure_alias(
                entity_id=team_id,
                raw_text=source_team.name,
                alias_type="OFFICIAL",
                provider_id=provider_id,
                snapshot_id=self.bootstrap_snapshot_id,
            )
            team_ids[source_team.id] = team_id
            team_season_id = self._team_season(team_id, season_id, self.bootstrap_snapshot_id)
            team_season_ids[source_team.id] = team_season_id
            self.counts.add("team", "created" if created else "reused")

        gameweek_ids: dict[int, UUID] = {}
        for source_event in bootstrap.payload.events:
            gameweek_id, created = self._external_entity(
                provider_id=provider_id,
                season_id=season_id,
                product="bootstrap",
                namespace="fpl.event.id",
                external_value=str(source_event.id),
                entity_type="GAMEWEEK",
                typed_table=gameweek,
                id_column="gameweek_id",
                attributes={
                    "season_id": season_id,
                    "number": source_event.id,
                    "display_name": source_event.name,
                    "official_deadline_at": source_event.deadline_time,
                    "status": "FINAL" if source_event.finished else "OPEN",
                },
                identity_attributes=("season_id", "number"),
                snapshot_id=self.bootstrap_snapshot_id,
                planned_id=plan.resolve(
                    "bootstrap", "fpl.event.id", "GAMEWEEK", str(source_event.id)
                ),
            )
            gameweek_ids[source_event.id] = gameweek_id
            self.counts.add("gameweek", "created" if created else "reused")

        type_codes = {
            source_type.id: source_type.singular_name_short.upper()
            for source_type in bootstrap.payload.element_types
        }
        for source_player in bootstrap.payload.elements:
            player_id, created = self._external_entity(
                provider_id=provider_id,
                season_id=season_id,
                product="bootstrap",
                namespace="fpl.element.id",
                external_value=str(source_player.id),
                entity_type="PLAYER",
                typed_table=player,
                id_column="player_id",
                attributes={
                    "canonical_name": " ".join(
                        part
                        for part in (source_player.first_name, source_player.second_name)
                        if part
                    )
                },
                fallback_identifier=("fpl.element.code", str(source_player.code)),
                snapshot_id=self.bootstrap_snapshot_id,
                planned_id=plan.resolve(
                    "bootstrap", "fpl.element.id", "PLAYER", str(source_player.id)
                ),
            )
            self._ensure_secondary_identifier(
                canonical_id=player_id,
                provider_id=provider_id,
                season_id=season_id,
                product="bootstrap",
                namespace="fpl.element.code",
                entity_type="PLAYER",
                external_value=str(source_player.code),
                snapshot_id=self.bootstrap_snapshot_id,
            )
            self._ensure_alias(
                entity_id=player_id,
                raw_text=source_player.web_name,
                alias_type="PROVIDER",
                provider_id=provider_id,
                snapshot_id=self.bootstrap_snapshot_id,
            )
            position_code = type_codes.get(
                source_player.element_type,
                POSITION_CODES.get(source_player.element_type, "UNKNOWN"),
            )
            self._player_season(player_id, season_id, position_code, self.bootstrap_snapshot_id)
            self._membership(
                player_id,
                team_ids[source_player.team],
                season_id,
                self.bootstrap_snapshot_id,
            )
            self.counts.add("player", "created" if created else "reused")

        for source_fixture in fixtures.payload.fixtures:
            if source_fixture.team_h not in team_ids or source_fixture.team_a not in team_ids:
                raise IngestionError("MAPPING_CONFLICT", "fixture references an unresolved team")
            if source_fixture.event is not None and source_fixture.event not in gameweek_ids:
                raise IngestionError(
                    "MAPPING_CONFLICT", "fixture references an unresolved Gameweek"
                )
            fixture_id, created = self._external_entity(
                provider_id=provider_id,
                season_id=season_id,
                product="fixtures",
                namespace="fpl.fixture.id",
                external_value=str(source_fixture.id),
                entity_type="FIXTURE",
                typed_table=fixture,
                id_column="fixture_id",
                attributes={
                    "competition_id": competition_id,
                    "season_id": season_id,
                    "home_team_id": team_ids[source_fixture.team_h],
                    "away_team_id": team_ids[source_fixture.team_a],
                },
                identity_attributes=(
                    "competition_id",
                    "season_id",
                    "home_team_id",
                    "away_team_id",
                ),
                fallback_identifier=("fpl.fixture.code", str(source_fixture.code)),
                snapshot_id=self.fixtures_snapshot_id,
                planned_id=plan.resolve(
                    "fixtures", "fpl.fixture.id", "FIXTURE", str(source_fixture.id)
                ),
            )
            self._ensure_secondary_identifier(
                canonical_id=fixture_id,
                provider_id=provider_id,
                season_id=season_id,
                product="fixtures",
                namespace="fpl.fixture.code",
                entity_type="FIXTURE",
                external_value=str(source_fixture.code),
                snapshot_id=self.fixtures_snapshot_id,
            )
            self._fixture_revision(fixture_id, source_fixture)
            self._fixture_assignment(
                fixture_id,
                season_id,
                gameweek_ids.get(source_fixture.event) if source_fixture.event else None,
                source_fixture,
            )
            self.counts.add("fixture", "created" if created else "reused")
        return competition_id, season_id

    def preflight_observation_conflicts(
        self,
        bootstrap: ParsedFplResource,
        fixtures: ParsedFplResource,
        plan: FplMappingPlan,
    ) -> None:
        """Claim subject-time semantics before canonical promotion can commit."""

        self._process_observations(
            bootstrap,
            fixtures,
            plan,
            bootstrap_usable_at=self.system_at,
            fixtures_usable_at=self.system_at,
            preflight=True,
        )

    def record_observations(
        self,
        bootstrap: ParsedFplResource,
        fixtures: ParsedFplResource,
        plan: FplMappingPlan,
        *,
        bootstrap_usable_at: datetime,
        fixtures_usable_at: datetime,
    ) -> None:
        """Append observations only after both source snapshots reached USABLE."""

        self._process_observations(
            bootstrap,
            fixtures,
            plan,
            bootstrap_usable_at=bootstrap_usable_at,
            fixtures_usable_at=fixtures_usable_at,
            preflight=False,
        )

    def _process_observations(
        self,
        bootstrap: ParsedFplResource,
        fixtures: ParsedFplResource,
        plan: FplMappingPlan,
        *,
        bootstrap_usable_at: datetime,
        fixtures_usable_at: datetime,
        preflight: bool,
    ) -> None:

        if not isinstance(bootstrap.payload, BootstrapPayload) or not isinstance(
            fixtures.payload, FixturePayload
        ):
            raise IngestionError("INTERNAL_INVARIANT", "parsed FPL resource types differ")
        provider_id = self.ensure_provider()
        _competition_id, season_id = self.ensure_competition_and_season(plan)
        team_seasons: dict[int, UUID] = {}
        for source_team in bootstrap.payload.teams:
            team_id = self._mapped_entity(
                provider_id,
                season_id,
                product="bootstrap",
                namespace="fpl.team.id",
                entity_type="TEAM",
                external_value=str(source_team.id),
            )
            team_season_id = _uuid(
                self.session.execute(
                    select(team_season.c.team_season_id).where(
                        team_season.c.team_id == team_id,
                        team_season.c.season_id == season_id,
                    )
                ).scalar_one()
            )
            team_seasons[source_team.id] = team_season_id
            self._team_observation(
                source_team,
                team_season_id,
                bootstrap_usable_at,
                preflight=preflight,
            )

        for source_event in bootstrap.payload.events:
            gameweek_id = self._mapped_entity(
                provider_id,
                season_id,
                product="bootstrap",
                namespace="fpl.event.id",
                entity_type="GAMEWEEK",
                external_value=str(source_event.id),
            )
            self._gameweek_observation(
                source_event,
                gameweek_id,
                bootstrap_usable_at,
                preflight=preflight,
            )

        type_codes = {
            source_type.id: source_type.singular_name_short.upper()
            for source_type in bootstrap.payload.element_types
        }
        for source_player in bootstrap.payload.elements:
            player_id = self._mapped_entity(
                provider_id,
                season_id,
                product="bootstrap",
                namespace="fpl.element.id",
                entity_type="PLAYER",
                external_value=str(source_player.id),
            )
            player_fpl_season_id = _uuid(
                self.session.execute(
                    select(player_season.c.player_fpl_season_id).where(
                        player_season.c.player_id == player_id,
                        player_season.c.season_id == season_id,
                    )
                ).scalar_one()
            )
            self._player_observation(
                source_player,
                player_fpl_season_id,
                team_seasons[source_player.team],
                type_codes.get(
                    source_player.element_type,
                    POSITION_CODES.get(source_player.element_type, "UNKNOWN"),
                ),
                bootstrap_usable_at,
                preflight=preflight,
            )

        for source_fixture in fixtures.payload.fixtures:
            fixture_id = self._mapped_entity(
                provider_id,
                season_id,
                product="fixtures",
                namespace="fpl.fixture.id",
                entity_type="FIXTURE",
                external_value=str(source_fixture.id),
            )
            self._fixture_observation(
                source_fixture,
                fixture_id,
                fixtures_usable_at,
                preflight=preflight,
            )

    def freeze_bundle(
        self,
        *,
        competition_id: UUID,
        season_id: UUID,
        information_cutoff: datetime,
        bootstrap: ParsedFplResource,
        fixtures: ParsedFplResource,
        profile_id: str,
        profile_version: str,
        config_sha256: str,
        mapping_plan_sha256: str,
        quality_status: str,
    ) -> SourceBundleSummary:
        cutoff = require_utc(information_cutoff)
        _advisory_lock(
            self.session,
            f"bundle:FPL_BOOTSTRAP_FIXTURES:{season_id}:{_utc_text(cutoff)}",
        )
        member_rows: list[dict[str, Any]] = []
        for role, snapshot_id, parsed in (
            ("BOOTSTRAP", self.bootstrap_snapshot_id, bootstrap),
            ("FIXTURES", self.fixtures_snapshot_id, fixtures),
        ):
            row = (
                self.session.execute(
                    text(
                        """
                        SELECT snapshot.envelope_sha256, lifecycle.current_state,
                               lifecycle.usable_at
                        FROM provenance.source_snapshot AS snapshot
                        JOIN provenance.source_snapshot_lifecycle AS lifecycle
                          ON lifecycle.source_snapshot_id = snapshot.source_snapshot_id
                        WHERE snapshot.source_snapshot_id = :snapshot_id
                        """
                    ),
                    {"snapshot_id": snapshot_id},
                )
                .mappings()
                .one()
            )
            usable_at = row["usable_at"]
            if row["current_state"] != "USABLE" or usable_at is None:
                raise IngestionError("NO_USABLE_BUNDLE", "source snapshot is not usable")
            usable = require_utc(usable_at)
            if usable > cutoff:
                raise IngestionError("POST_CUTOFF", "source snapshot became usable after cutoff")
            events = self.session.execute(
                select(source_processing_event.c.event_sha256)
                .where(source_processing_event.c.source_snapshot_id == snapshot_id)
                .order_by(source_processing_event.c.sequence_number)
            ).scalars()
            member_rows.append(
                {
                    "role": role,
                    "snapshot_id": snapshot_id,
                    "usable_at": usable,
                    "payload_semantic_sha256": parsed.semantic_sha256,
                    "envelope_sha256": row["envelope_sha256"],
                    "lifecycle_sha256": canonical_sha256(list(events)),
                    "schema_drift": parsed.drift.model_dump(mode="json"),
                }
            )
        semantic_sha256 = canonical_sha256(
            {
                "adapter_version": CONTRACT_VERSION,
                "bundle_type": "FPL_BOOTSTRAP_FIXTURES",
                "competition_key": self.competition_key,
                "contract_version": CONTRACT_VERSION,
                "information_cutoff": _utc_text(cutoff),
                "mapping": {
                    "identity_sha256": self.mapping_identity_sha256(season_id, bootstrap, fixtures),
                    "plan_sha256": mapping_plan_sha256,
                    "version": "fpl-mapping-v1",
                },
                "members": [
                    {
                        "payload_semantic_sha256": item["payload_semantic_sha256"],
                        "role": item["role"],
                        "schema_fingerprint": item["schema_drift"]["schema_fingerprint"],
                    }
                    for item in member_rows
                ],
                "quality_status": quality_status,
                "effective_config_sha256": config_sha256,
                "rights_profiles": [{"id": profile_id, "version": profile_version}],
                "season_code": self.season_code,
            }
        )
        manifest_sha256 = canonical_sha256(
            {
                "bundle_semantic_sha256": semantic_sha256,
                "members": [
                    {
                        "envelope_sha256": item["envelope_sha256"],
                        "lifecycle_sha256": item["lifecycle_sha256"],
                        "payload_semantic_sha256": item["payload_semantic_sha256"],
                        "role": item["role"],
                        "schema_drift": item["schema_drift"],
                        "source_snapshot_id": str(item["snapshot_id"]),
                        "usable_at": _utc_text(item["usable_at"]),
                    }
                    for item in member_rows
                ],
            }
        )
        existing = self.session.execute(
            select(source_bundle.c.source_bundle_id).where(
                source_bundle.c.manifest_sha256 == manifest_sha256
            )
        ).scalar_one_or_none()
        if existing is not None:
            self.counts.add("source_bundle", "reused")
            return self.bundle_summary(_uuid(existing))
        created_at = max(item["usable_at"] for item in member_rows)
        bundle_id = _uuid(
            self.session.execute(
                insert(source_bundle)
                .values(
                    bundle_type="FPL_BOOTSTRAP_FIXTURES",
                    competition_id=competition_id,
                    season_id=season_id,
                    information_cutoff=cutoff,
                    created_at=created_at,
                    rights_profiles=[{"id": profile_id, "version": profile_version}],
                    adapter_version=CONTRACT_VERSION,
                    contract_version=CONTRACT_VERSION,
                    quality_status=quality_status,
                    semantic_sha256=semantic_sha256,
                    manifest_sha256=manifest_sha256,
                    code_commit=None,
                    config_sha256=config_sha256,
                )
                .returning(source_bundle.c.source_bundle_id)
            ).scalar_one()
        )
        for item in member_rows:
            self.session.execute(
                insert(source_bundle_member).values(
                    source_bundle_id=bundle_id,
                    source_snapshot_id=item["snapshot_id"],
                    role=item["role"],
                    usable_at=item["usable_at"],
                    payload_semantic_sha256=item["payload_semantic_sha256"],
                    envelope_sha256=item["envelope_sha256"],
                    lifecycle_sha256=item["lifecycle_sha256"],
                    schema_drift=item["schema_drift"],
                )
            )
        self.counts.add("source_bundle", "created")
        return self.bundle_summary(bundle_id)

    def bundle_summary(self, bundle_id: UUID) -> SourceBundleSummary:
        bundle = (
            self.session.execute(
                select(source_bundle).where(source_bundle.c.source_bundle_id == bundle_id)
            )
            .mappings()
            .one_or_none()
        )
        if bundle is None:
            raise IngestionError("NO_USABLE_BUNDLE", "source bundle was not found")
        rows = (
            self.session.execute(
                select(source_bundle_member).where(
                    source_bundle_member.c.source_bundle_id == bundle_id
                )
            )
            .mappings()
            .all()
        )
        by_role = {row["role"]: row for row in rows}
        if set(by_role) != {"BOOTSTRAP", "FIXTURES"}:
            raise IngestionError("CANONICAL_INVARIANT", "source bundle membership is invalid")
        members = (
            SourceBundleMember(
                role="BOOTSTRAP",
                source_snapshot_id=_uuid(by_role["BOOTSTRAP"]["source_snapshot_id"]),
                usable_at=require_utc(by_role["BOOTSTRAP"]["usable_at"]),
            ),
            SourceBundleMember(
                role="FIXTURES",
                source_snapshot_id=_uuid(by_role["FIXTURES"]["source_snapshot_id"]),
                usable_at=require_utc(by_role["FIXTURES"]["usable_at"]),
            ),
        )
        return SourceBundleSummary(
            bundle_id=bundle_id,
            competition_id=_uuid(bundle["competition_id"]),
            season_id=_uuid(bundle["season_id"]),
            information_cutoff=require_utc(bundle["information_cutoff"]),
            members=members,
            semantic_sha256=str(bundle["semantic_sha256"]),
            quality_status=bundle["quality_status"],
        )

    def _canonical_entity(self, entity_type: str, *, entity_id: UUID | None = None) -> UUID:
        return _uuid(
            self.session.execute(
                insert(canonical_entity)
                .values(entity_type=entity_type, **({"entity_id": entity_id} if entity_id else {}))
                .returning(canonical_entity.c.entity_id)
            ).scalar_one()
        )

    def _mapped_entity(
        self,
        provider_id: UUID,
        season_id: UUID,
        *,
        product: str,
        namespace: str,
        entity_type: str,
        external_value: str,
    ) -> UUID:
        value = self.session.execute(
            select(external_identifier.c.canonical_entity_id).where(
                external_identifier.c.provider_id == provider_id,
                external_identifier.c.season_id == season_id,
                external_identifier.c.provider_product == product,
                external_identifier.c.identifier_namespace == namespace,
                external_identifier.c.entity_type == entity_type,
                external_identifier.c.external_id_text == external_value,
                external_identifier.c.mapping_status.in_(("AUTO_MATCHED", "HUMAN_VERIFIED")),
                func.upper_inf(external_identifier.c.system_during),
            )
        ).scalar_one_or_none()
        if value is None:
            raise IngestionError("MAPPING_CONFLICT", "required provider mapping is unavailable")
        return _uuid(value)

    def mapping_identity_sha256(
        self,
        season_id: UUID,
        bootstrap: ParsedFplResource,
        fixtures: ParsedFplResource,
    ) -> str:
        if not isinstance(bootstrap.payload, BootstrapPayload) or not isinstance(
            fixtures.payload, FixturePayload
        ):
            raise IngestionError("INTERNAL_INVARIANT", "mapping identity inputs are invalid")
        provider_id = self.ensure_provider()
        keys: set[tuple[str, str, str, str]] = set()
        for team_source in bootstrap.payload.teams:
            keys.add(("bootstrap", "fpl.team.id", "TEAM", str(team_source.id)))
            keys.add(("bootstrap", "fpl.team.code", "TEAM", str(team_source.code)))
        for player_source in bootstrap.payload.elements:
            keys.add(("bootstrap", "fpl.element.id", "PLAYER", str(player_source.id)))
            keys.add(("bootstrap", "fpl.element.code", "PLAYER", str(player_source.code)))
        for event_source in bootstrap.payload.events:
            keys.add(("bootstrap", "fpl.event.id", "GAMEWEEK", str(event_source.id)))
        for fixture_source in fixtures.payload.fixtures:
            keys.add(("fixtures", "fpl.fixture.id", "FIXTURE", str(fixture_source.id)))
            keys.add(("fixtures", "fpl.fixture.code", "FIXTURE", str(fixture_source.code)))
        identity: list[dict[str, str]] = []
        for product, namespace, entity_type, external_value in sorted(keys):
            row = (
                self.session.execute(
                    select(
                        external_identifier.c.canonical_entity_id,
                        external_identifier.c.mapping_status,
                    ).where(
                        external_identifier.c.provider_id == provider_id,
                        external_identifier.c.season_id == season_id,
                        external_identifier.c.provider_product == product,
                        external_identifier.c.identifier_namespace == namespace,
                        external_identifier.c.entity_type == entity_type,
                        external_identifier.c.external_id_text == external_value,
                        external_identifier.c.mapping_status.in_(
                            ("AUTO_MATCHED", "HUMAN_VERIFIED")
                        ),
                        func.upper_inf(external_identifier.c.system_during),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise IngestionError("MAPPING_CONFLICT", "bundle mapping identity is incomplete")
            identity.append(
                {
                    "canonical_entity_id": str(row["canonical_entity_id"]),
                    "entity_type": entity_type,
                    "external_id_text": external_value,
                    "mapping_status": str(row["mapping_status"]),
                    "namespace": namespace,
                    "product": product,
                }
            )
        return canonical_sha256(identity)

    def _external_entity(
        self,
        *,
        provider_id: UUID,
        season_id: UUID,
        product: str,
        namespace: str,
        external_value: str,
        entity_type: str,
        typed_table: Table,
        id_column: str,
        attributes: dict[str, object],
        snapshot_id: UUID,
        planned_id: UUID,
        identity_attributes: tuple[str, ...] = (),
        fallback_identifier: tuple[str, str] | None = None,
    ) -> tuple[UUID, bool]:
        lock_keys = [
            f"external:{provider_id}:{season_id}:{product}:{namespace}:"
            f"{entity_type}:{external_value}"
        ]
        if fallback_identifier is not None:
            fallback_namespace, fallback_value = fallback_identifier
            lock_keys.append(
                f"external:{provider_id}:{season_id}:{product}:{fallback_namespace}:"
                f"{entity_type}:{fallback_value}"
            )
        for lock_key in sorted(lock_keys):
            _advisory_lock(self.session, lock_key)
        existing = self.session.execute(
            select(external_identifier.c.canonical_entity_id).where(
                external_identifier.c.provider_id == provider_id,
                external_identifier.c.season_id == season_id,
                external_identifier.c.provider_product == product,
                external_identifier.c.identifier_namespace == namespace,
                external_identifier.c.entity_type == entity_type,
                external_identifier.c.external_id_text == external_value,
                external_identifier.c.mapping_status.in_(("AUTO_MATCHED", "HUMAN_VERIFIED")),
                func.upper_inf(external_identifier.c.system_during),
            )
        ).scalar_one_or_none()
        if existing is None and fallback_identifier is not None:
            fallback_namespace, fallback_value = fallback_identifier
            existing = self.session.execute(
                select(external_identifier.c.canonical_entity_id).where(
                    external_identifier.c.provider_id == provider_id,
                    external_identifier.c.season_id == season_id,
                    external_identifier.c.provider_product == product,
                    external_identifier.c.identifier_namespace == fallback_namespace,
                    external_identifier.c.entity_type == entity_type,
                    external_identifier.c.external_id_text == fallback_value,
                    external_identifier.c.mapping_status.in_(("AUTO_MATCHED", "HUMAN_VERIFIED")),
                    func.upper_inf(external_identifier.c.system_during),
                )
            ).scalar_one_or_none()
            if existing is not None:
                self._insert_identifier(
                    canonical_id=_uuid(existing),
                    provider_id=provider_id,
                    season_id=season_id,
                    product=product,
                    namespace=namespace,
                    entity_type=entity_type,
                    external_value=external_value,
                    snapshot_id=snapshot_id,
                )
        if existing is not None:
            existing_id = _uuid(existing)
            if existing_id != planned_id:
                raise IngestionError(
                    "MAPPING_CONFLICT", "resolved mapping differs from its immutable plan"
                )
            if identity_attributes:
                identity = (
                    self.session.execute(
                        select(*(typed_table.c[name] for name in identity_attributes)).where(
                            typed_table.c[id_column] == existing_id
                        )
                    )
                    .mappings()
                    .one()
                )
                if any(identity[name] != attributes[name] for name in identity_attributes):
                    raise IngestionError(
                        "MAPPING_CONFLICT",
                        "provider identifier contradicts immutable canonical identity",
                    )
            return existing_id, False
        entity_id = self._canonical_entity(entity_type, entity_id=planned_id)
        self.session.execute(
            insert(typed_table).values(
                **{id_column: entity_id, "entity_type": entity_type, **attributes}
            )
        )
        self._insert_identifier(
            canonical_id=entity_id,
            provider_id=provider_id,
            season_id=season_id,
            product=product,
            namespace=namespace,
            entity_type=entity_type,
            external_value=external_value,
            snapshot_id=snapshot_id,
        )
        return entity_id, True

    def _ensure_secondary_identifier(
        self,
        *,
        canonical_id: UUID,
        provider_id: UUID,
        season_id: UUID,
        product: str,
        namespace: str,
        entity_type: str,
        external_value: str,
        snapshot_id: UUID,
    ) -> None:
        _advisory_lock(
            self.session,
            f"external:{provider_id}:{season_id}:{product}:{namespace}:{external_value}",
        )
        existing = self.session.execute(
            select(external_identifier.c.canonical_entity_id).where(
                external_identifier.c.provider_id == provider_id,
                external_identifier.c.season_id == season_id,
                external_identifier.c.provider_product == product,
                external_identifier.c.identifier_namespace == namespace,
                external_identifier.c.entity_type == entity_type,
                external_identifier.c.external_id_text == external_value,
                external_identifier.c.mapping_status.in_(("AUTO_MATCHED", "HUMAN_VERIFIED")),
                func.upper_inf(external_identifier.c.system_during),
            )
        ).scalar_one_or_none()
        if existing is not None:
            if _uuid(existing) != canonical_id:
                raise IngestionError(
                    "MAPPING_CONFLICT", "provider identifiers resolve to different entities"
                )
            return
        self._insert_identifier(
            canonical_id=canonical_id,
            provider_id=provider_id,
            season_id=season_id,
            product=product,
            namespace=namespace,
            entity_type=entity_type,
            external_value=external_value,
            snapshot_id=snapshot_id,
        )

    def _insert_identifier(
        self,
        *,
        canonical_id: UUID,
        provider_id: UUID,
        season_id: UUID,
        product: str,
        namespace: str,
        entity_type: str,
        external_value: str,
        snapshot_id: UUID,
    ) -> None:
        self.session.execute(
            insert(external_identifier).values(
                canonical_entity_id=canonical_id,
                provider_id=provider_id,
                provider_product=product,
                identifier_namespace=namespace,
                entity_type=entity_type,
                external_id_text=external_value,
                valid_during=_valid_range(self.season_code),
                system_during=Range(self.system_at, None, bounds="[)"),
                mapping_status="AUTO_MATCHED",
                mapping_method="EXACT_EXTERNAL_ID",
                evidence_source_snapshot_id=snapshot_id,
                first_seen_at=self.captured_at,
                last_seen_at=self.captured_at,
                is_provider_primary=namespace.endswith(".id"),
                season_id=season_id,
            )
        )

    def _ensure_alias(
        self,
        *,
        entity_id: UUID,
        raw_text: str,
        alias_type: str,
        provider_id: UUID,
        snapshot_id: UUID,
    ) -> None:
        existing = (
            self.session.execute(
                select(
                    entity_alias.c.alias_id,
                    entity_alias.c.raw_text,
                    entity_alias.c.alias_type,
                    entity_alias.c.provider_id,
                    entity_alias.c.source_snapshot_id,
                    entity_alias.c.system_during,
                )
                .where(
                    entity_alias.c.canonical_entity_id == entity_id,
                    entity_alias.c.is_preferred.is_(True),
                    func.upper_inf(entity_alias.c.system_during),
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        transition_at = self.system_at
        if existing is not None:
            if (
                existing["raw_text"] == raw_text
                and existing["alias_type"] == alias_type
                and existing["provider_id"] == provider_id
            ):
                return
            current_system: Range[datetime] = existing["system_during"]
            current_captured_at = _source_captured_at(self.session, existing["source_snapshot_id"])
            if self.captured_at < current_captured_at:
                return
            if self.captured_at == current_captured_at:
                raise IngestionError(
                    "MAPPING_CONFLICT", "preferred alias contradicts an equal-time fact"
                )
            transition_at = _successor_system_at(self.system_at, current_system)
            self.session.execute(
                text("SET CONSTRAINTS core.ex_entity_alias_current_preferred DEFERRED")
            )
        normalized = raw_text.strip()
        new_id = _uuid(
            self.session.execute(
                insert(entity_alias)
                .values(
                    canonical_entity_id=entity_id,
                    raw_text=raw_text,
                    normalized_nfc=normalized,
                    match_key=normalized.casefold(),
                    alias_type=alias_type,
                    provider_id=provider_id,
                    valid_during=_valid_range(self.season_code),
                    system_during=Range(transition_at, None, bounds="[)"),
                    source_snapshot_id=snapshot_id,
                    confidence=1,
                    is_preferred=True,
                )
                .returning(entity_alias.c.alias_id)
            ).scalar_one()
        )
        if existing is not None:
            current_system = existing["system_during"]
            self.session.execute(
                update(entity_alias)
                .where(entity_alias.c.alias_id == existing["alias_id"])
                .values(
                    system_during=Range(_range_lower(current_system), transition_at, bounds="[)"),
                    superseded_by_alias_id=new_id,
                )
            )
            self.counts.add("entity_alias", "changed")
        else:
            self.counts.add("entity_alias", "created")

    def _team_season(self, team_id: UUID, season_id: UUID, snapshot_id: UUID) -> UUID:
        created = self.session.execute(
            postgresql_insert(team_season)
            .values(team_id=team_id, season_id=season_id, source_snapshot_id=snapshot_id)
            .on_conflict_do_nothing(index_elements=[team_season.c.team_id, team_season.c.season_id])
            .returning(team_season.c.team_season_id)
        ).scalar_one_or_none()
        if created is not None:
            self.counts.add("team_season", "created")
            return _uuid(created)
        self.counts.add("team_season", "reused")
        return _uuid(
            self.session.execute(
                select(team_season.c.team_season_id).where(
                    team_season.c.team_id == team_id,
                    team_season.c.season_id == season_id,
                )
            ).scalar_one()
        )

    def _player_season(
        self, player_id: UUID, season_id: UUID, position_code: str, snapshot_id: UUID
    ) -> UUID:
        created = self.session.execute(
            postgresql_insert(player_season)
            .values(
                player_id=player_id,
                season_id=season_id,
                position_code=position_code,
                source_snapshot_id=snapshot_id,
            )
            .on_conflict_do_nothing(
                index_elements=[player_season.c.player_id, player_season.c.season_id]
            )
            .returning(player_season.c.player_fpl_season_id)
        ).scalar_one_or_none()
        if created is not None:
            self.counts.add("player_fpl_season", "created")
            return _uuid(created)
        existing = (
            self.session.execute(
                select(
                    player_season.c.player_fpl_season_id,
                    player_season.c.position_code,
                ).where(
                    player_season.c.player_id == player_id,
                    player_season.c.season_id == season_id,
                )
            )
            .mappings()
            .one()
        )
        if existing["position_code"] != position_code:
            raise IngestionError("MAPPING_CONFLICT", "player position identity conflicts")
        self.counts.add("player_fpl_season", "reused")
        return _uuid(existing["player_fpl_season_id"])

    def _membership(
        self, player_id: UUID, team_id: UUID, season_id: UUID, snapshot_id: UUID
    ) -> None:
        current = (
            self.session.execute(
                select(
                    player_team_membership.c.membership_id,
                    player_team_membership.c.team_id,
                    player_team_membership.c.source_snapshot_id,
                    player_team_membership.c.system_during,
                )
                .where(
                    player_team_membership.c.player_id == player_id,
                    player_team_membership.c.season_id == season_id,
                    player_team_membership.c.registration_type == "UNKNOWN",
                    func.upper_inf(player_team_membership.c.system_during),
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        transition_at = self.system_at
        if current is not None:
            if current["team_id"] == team_id:
                return
            current_system: Range[datetime] = current["system_during"]
            current_captured_at = _source_captured_at(self.session, current["source_snapshot_id"])
            if self.captured_at < current_captured_at:
                return
            if self.captured_at == current_captured_at:
                raise IngestionError(
                    "MAPPING_CONFLICT", "player membership contradicts an equal-time fact"
                )
            transition_at = _successor_system_at(self.system_at, current_system)
            self.session.execute(
                text("SET CONSTRAINTS football.ex_player_team_membership_current DEFERRED")
            )
        new_id = _uuid(
            self.session.execute(
                insert(player_team_membership)
                .values(
                    player_id=player_id,
                    team_id=team_id,
                    season_id=season_id,
                    registration_type="UNKNOWN",
                    squad_status="REGISTERED",
                    valid_during=_valid_range(self.season_code),
                    system_during=Range(transition_at, None, bounds="[)"),
                    source_snapshot_id=snapshot_id,
                )
                .returning(player_team_membership.c.membership_id)
            ).scalar_one()
        )
        if current is not None:
            current_system = current["system_during"]
            self.session.execute(
                update(player_team_membership)
                .where(player_team_membership.c.membership_id == current["membership_id"])
                .values(
                    system_during=Range(_range_lower(current_system), transition_at, bounds="[)"),
                    superseded_by_membership_id=new_id,
                )
            )
            self.counts.add("player_team_membership", "changed")
        else:
            self.counts.add("player_team_membership", "created")

    def _claim_observation_semantic(
        self,
        *,
        effect_type: str,
        subject_key: UUID,
        observed_at: datetime,
        semantic_sha256: str,
        snapshot_id: UUID,
    ) -> None:
        claimed = self.session.execute(
            postgresql_insert(semantic_observation_claim)
            .values(
                effect_type=effect_type.upper(),
                subject_key=subject_key,
                observed_at=require_utc(observed_at),
                semantic_sha256=semantic_sha256,
                source_snapshot_id=snapshot_id,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    semantic_observation_claim.c.effect_type,
                    semantic_observation_claim.c.subject_key,
                    semantic_observation_claim.c.observed_at,
                ]
            )
            .returning(semantic_observation_claim.c.semantic_sha256)
        ).scalar_one_or_none()
        if claimed is not None:
            return
        existing = self.session.scalar(
            select(semantic_observation_claim.c.semantic_sha256)
            .where(
                semantic_observation_claim.c.effect_type == effect_type.upper(),
                semantic_observation_claim.c.subject_key == subject_key,
                semantic_observation_claim.c.observed_at == observed_at,
            )
            .with_for_update()
        )
        if existing != semantic_sha256:
            raise IngestionError(
                "SEMANTIC_CONTRADICTION",
                "same subject has conflicting observations at one captured time",
            )

    def _observation(
        self,
        *,
        table: Table,
        id_column: str,
        effect_type: str,
        subject_key: UUID,
        subject_clause: Any,
        values: dict[str, object],
        snapshot_id: UUID,
        preflight: bool,
    ) -> None:
        semantic_sha256 = str(values["semantic_sha256"])
        observed_at = values["observed_at"]
        if not isinstance(observed_at, datetime):
            raise IngestionError("INTERNAL_INVARIANT", "observation time has an invalid type")
        _advisory_lock(
            self.session,
            f"observation:{effect_type}:{subject_key}",
        )
        self._claim_observation_semantic(
            effect_type=effect_type,
            subject_key=subject_key,
            observed_at=observed_at,
            semantic_sha256=semantic_sha256,
            snapshot_id=snapshot_id,
        )
        subject_semantics = select(table.c.semantic_sha256).where(subject_clause)
        same_time_hashes = set(
            self.session.scalars(
                select(table.c.semantic_sha256).where(
                    subject_clause,
                    table.c.observed_at == observed_at,
                )
            )
        )
        same_time_hashes.update(
            self.session.scalars(
                select(semantic_effect_source.c.semantic_sha256).where(
                    semantic_effect_source.c.effect_type == effect_type.upper(),
                    semantic_effect_source.c.observed_at == observed_at,
                    semantic_effect_source.c.semantic_sha256.in_(subject_semantics),
                )
            )
        )
        if same_time_hashes and same_time_hashes != {semantic_sha256}:
            raise IngestionError(
                "SEMANTIC_CONTRADICTION",
                "same subject has conflicting observations at one captured time",
            )
        if preflight:
            return
        latest_semantic = self.session.scalar(
            select(table.c.semantic_sha256)
            .where(subject_clause)
            .order_by(
                table.c.observed_at.desc(),
                table.c.usable_at.desc(),
                table.c[id_column].desc(),
            )
            .limit(1)
        )
        created = None
        if not same_time_hashes and latest_semantic != semantic_sha256:
            created = self.session.execute(
                postgresql_insert(table)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=[table.c.semantic_sha256, table.c.source_snapshot_id]
                )
                .returning(table.c[id_column])
            ).scalar_one_or_none()
        state = (
            "reused" if created is None else "changed" if latest_semantic is not None else "created"
        )
        self.counts.add(effect_type, state)
        self.session.execute(
            postgresql_insert(semantic_effect_source)
            .values(
                effect_type=effect_type.upper(),
                semantic_sha256=semantic_sha256,
                source_snapshot_id=snapshot_id,
                observed_at=self.captured_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    semantic_effect_source.c.effect_type,
                    semantic_effect_source.c.semantic_sha256,
                    semantic_effect_source.c.source_snapshot_id,
                ]
            )
        )

    def _team_observation(
        self,
        source: Any,
        team_season_id: UUID,
        usable_at: datetime,
        *,
        preflight: bool,
    ) -> None:
        typed = {
            "display_name": source.name,
            "draw": source.draw,
            "loss": source.loss,
            "played": source.played,
            "points": source.points,
            "position": source.position,
            "short_name": source.short_name,
            "strength": source.strength,
            "strength_attack_away": source.strength_attack_away,
            "strength_attack_home": source.strength_attack_home,
            "strength_defence_away": source.strength_defence_away,
            "strength_defence_home": source.strength_defence_home,
            "strength_overall_away": source.strength_overall_away,
            "strength_overall_home": source.strength_overall_home,
            "win": source.win,
        }
        missingness = _field_missingness(
            source,
            {name: name for name in typed if name not in {"display_name", "short_name"}},
        )
        semantic = canonical_sha256(
            {
                "canonical_subject": str(team_season_id),
                "competition_key": self.competition_key,
                "contract_version": CONTRACT_VERSION,
                "missingness": missingness,
                "observed_fields": _semantic_fields(typed),
                "season_code": self.season_code,
                "source_role": "BOOTSTRAP",
                "valid_time": {"missingness": "SOURCE_UNAVAILABLE"},
            }
        )
        self._observation(
            table=team_observation,
            id_column="team_observation_id",
            effect_type="team_observation",
            subject_key=team_season_id,
            subject_clause=team_observation.c.team_season_id == team_season_id,
            values={
                "team_season_id": team_season_id,
                **typed,
                "observed_at": self.captured_at,
                "received_at": self.captured_at,
                "usable_at": require_utc(usable_at),
                "source_snapshot_id": self.bootstrap_snapshot_id,
                "contract_version": CONTRACT_VERSION,
                "missingness": missingness,
                "semantic_sha256": semantic,
            },
            snapshot_id=self.bootstrap_snapshot_id,
            preflight=preflight,
        )

    def _player_observation(
        self,
        source: Any,
        player_fpl_season_id: UUID,
        team_season_id: UUID,
        position_code: str,
        usable_at: datetime,
        *,
        preflight: bool,
    ) -> None:
        typed = {
            "chance_next_round": source.chance_of_playing_next_round,
            "chance_this_round": source.chance_of_playing_this_round,
            "cost_change_event": source.cost_change_event,
            "cost_change_event_fall": source.cost_change_event_fall,
            "cost_change_start": source.cost_change_start,
            "cost_change_start_fall": source.cost_change_start_fall,
            "minutes": source.minutes,
            "news": source.news,
            "news_added_at": source.news_added,
            "position_code": position_code,
            "price_tenths": source.now_cost,
            "selected_by_percent": source.selected_by_percent,
            "status": source.status,
            "total_points": source.total_points,
            "transfers_in": source.transfers_in,
            "transfers_in_event": source.transfers_in_event,
            "transfers_out": source.transfers_out,
            "transfers_out_event": source.transfers_out_event,
        }
        missingness = _field_missingness(
            source,
            {
                "chance_next_round": "chance_of_playing_next_round",
                "chance_this_round": "chance_of_playing_this_round",
                "cost_change_event": "cost_change_event",
                "cost_change_event_fall": "cost_change_event_fall",
                "cost_change_start": "cost_change_start",
                "cost_change_start_fall": "cost_change_start_fall",
                "minutes": "minutes",
                "news": "news",
                "news_added_at": "news_added",
                "selected_by_percent": "selected_by_percent",
                "total_points": "total_points",
                "transfers_in": "transfers_in",
                "transfers_in_event": "transfers_in_event",
                "transfers_out": "transfers_out",
                "transfers_out_event": "transfers_out_event",
            },
        )
        semantic = canonical_sha256(
            {
                "canonical_subject": str(player_fpl_season_id),
                "competition_key": self.competition_key,
                "contract_version": CONTRACT_VERSION,
                "missingness": missingness,
                "observed_fields": _semantic_fields(typed),
                "season_code": self.season_code,
                "source_role": "BOOTSTRAP",
                "team_season_id": str(team_season_id),
                "valid_time": {"missingness": "SOURCE_UNAVAILABLE"},
            }
        )
        self._observation(
            table=player_observation,
            id_column="player_observation_id",
            effect_type="player_observation",
            subject_key=player_fpl_season_id,
            subject_clause=(player_observation.c.player_fpl_season_id == player_fpl_season_id),
            values={
                "player_fpl_season_id": player_fpl_season_id,
                "team_season_id": team_season_id,
                **typed,
                "observed_at": self.captured_at,
                "received_at": self.captured_at,
                "usable_at": require_utc(usable_at),
                "source_snapshot_id": self.bootstrap_snapshot_id,
                "contract_version": CONTRACT_VERSION,
                "missingness": missingness,
                "semantic_sha256": semantic,
            },
            snapshot_id=self.bootstrap_snapshot_id,
            preflight=preflight,
        )

    def _gameweek_observation(
        self,
        source: Any,
        gameweek_id: UUID,
        usable_at: datetime,
        *,
        preflight: bool,
    ) -> None:
        typed = {
            "average_entry_score": source.average_entry_score,
            "data_checked": source.data_checked,
            "deadline_at": source.deadline_time,
            "display_name": source.name,
            "finished": source.finished,
            "highest_score": source.highest_score,
            "is_current": source.is_current,
            "is_next": source.is_next,
            "is_previous": source.is_previous,
            "source_event_id": str(source.id),
        }
        missingness = _field_missingness(
            source,
            {
                name: name
                for name in typed
                if name not in {"deadline_at", "display_name", "source_event_id"}
            },
        )
        semantic = canonical_sha256(
            {
                "canonical_subject": str(gameweek_id),
                "competition_key": self.competition_key,
                "contract_version": CONTRACT_VERSION,
                "missingness": missingness,
                "observed_fields": _semantic_fields(typed),
                "season_code": self.season_code,
                "source_role": "BOOTSTRAP",
                "valid_time": {"missingness": "SOURCE_UNAVAILABLE"},
            }
        )
        self._observation(
            table=gameweek_observation,
            id_column="gameweek_observation_id",
            effect_type="gameweek_observation",
            subject_key=gameweek_id,
            subject_clause=gameweek_observation.c.gameweek_id == gameweek_id,
            values={
                "gameweek_id": gameweek_id,
                **typed,
                "observed_at": self.captured_at,
                "received_at": self.captured_at,
                "usable_at": require_utc(usable_at),
                "source_snapshot_id": self.bootstrap_snapshot_id,
                "contract_version": CONTRACT_VERSION,
                "missingness": missingness,
                "semantic_sha256": semantic,
            },
            snapshot_id=self.bootstrap_snapshot_id,
            preflight=preflight,
        )

    def _fixture_observation(
        self,
        source: Any,
        fixture_id: UUID,
        usable_at: datetime,
        *,
        preflight: bool,
    ) -> None:
        typed = {
            "finished": source.finished,
            "finished_provisional": source.finished_provisional,
            "kickoff_at": source.kickoff_time,
            "minutes": source.minutes,
            "provisional_start_time": source.provisional_start_time,
            "source_fixture_code": str(source.code),
            "source_fixture_id": str(source.id),
            "started": source.started,
            "team_a_difficulty": source.team_a_difficulty,
            "team_a_score": source.team_a_score,
            "team_h_difficulty": source.team_h_difficulty,
            "team_h_score": source.team_h_score,
        }
        missingness = _field_missingness(
            source,
            {
                name: name
                for name in typed
                if name
                not in {"finished", "kickoff_at", "source_fixture_code", "source_fixture_id"}
            }
            | {"kickoff_at": "kickoff_time"},
        )
        semantic = canonical_sha256(
            {
                "canonical_subject": str(fixture_id),
                "competition_key": self.competition_key,
                "contract_version": CONTRACT_VERSION,
                "missingness": missingness,
                "observed_fields": _semantic_fields(typed),
                "season_code": self.season_code,
                "source_role": "FIXTURES",
                "valid_time": {"missingness": "SOURCE_UNAVAILABLE"},
            }
        )
        self._observation(
            table=fixture_observation,
            id_column="fixture_observation_id",
            effect_type="fixture_observation",
            subject_key=fixture_id,
            subject_clause=fixture_observation.c.fixture_id == fixture_id,
            values={
                "fixture_id": fixture_id,
                **typed,
                "observed_at": self.captured_at,
                "received_at": self.captured_at,
                "usable_at": require_utc(usable_at),
                "source_snapshot_id": self.fixtures_snapshot_id,
                "contract_version": CONTRACT_VERSION,
                "missingness": missingness,
                "semantic_sha256": semantic,
            },
            snapshot_id=self.fixtures_snapshot_id,
            preflight=preflight,
        )

    def _fixture_revision(self, fixture_id: UUID, source: Any) -> None:
        status = "FINISHED" if source.finished else "STARTED" if source.started else "SCHEDULED"
        current = (
            self.session.execute(
                select(fixture_revision)
                .where(
                    fixture_revision.c.fixture_id == fixture_id,
                    func.upper_inf(fixture_revision.c.system_during),
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if current is not None and (
            current["kickoff_at"] == source.kickoff_time and current["fixture_status"] == status
        ):
            self.counts.add("fixture_revision", "reused")
            return
        if current is not None:
            current_captured_at = require_utc(current["observed_at"])
            if self.captured_at < current_captured_at:
                self.counts.add("fixture_revision", "reused")
                return
            if self.captured_at == current_captured_at:
                raise IngestionError(
                    "MAPPING_CONFLICT", "fixture revision contradicts an equal-time fact"
                )
        transition_at = (
            _successor_system_at(self.system_at, current["system_during"])
            if current is not None
            else self.system_at
        )
        valid_start = source.kickoff_time or _valid_range(self.season_code).lower
        revision_number = 1 if current is None else int(current["revision_number"]) + 1
        if current is not None:
            self.session.execute(
                text("SET CONSTRAINTS football.ex_fixture_revision_current DEFERRED")
            )
        new_id = _uuid(
            self.session.execute(
                insert(fixture_revision)
                .values(
                    fixture_id=fixture_id,
                    revision_number=revision_number,
                    kickoff_at=source.kickoff_time,
                    fixture_status=status,
                    valid_during=Range(valid_start, None, bounds="[)"),
                    system_during=Range(transition_at, None, bounds="[)"),
                    observed_at=self.captured_at,
                    source_snapshot_id=self.fixtures_snapshot_id,
                )
                .returning(fixture_revision.c.fixture_revision_id)
            ).scalar_one()
        )
        if current is not None:
            system_range: Range[datetime] = current["system_during"]
            self.session.execute(
                update(fixture_revision)
                .where(fixture_revision.c.fixture_revision_id == current["fixture_revision_id"])
                .values(
                    system_during=Range(system_range.lower, transition_at, bounds="[)"),
                    superseded_by_revision_id=new_id,
                )
            )
            self.session.execute(
                text("SET CONSTRAINTS football.ex_fixture_revision_current IMMEDIATE")
            )
        self.counts.add("fixture_revision", "changed" if current is not None else "created")

    def _fixture_assignment(
        self, fixture_id: UUID, season_id: UUID, gameweek_id: UUID | None, source: Any
    ) -> None:
        status = "ASSIGNED" if gameweek_id is not None else "UNASSIGNED"
        current = (
            self.session.execute(
                select(fixture_gameweek_assignment)
                .where(
                    fixture_gameweek_assignment.c.fixture_id == fixture_id,
                    func.upper_inf(fixture_gameweek_assignment.c.system_during),
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if current is not None and (
            current["gameweek_id"] == gameweek_id and current["assignment_status"] == status
        ):
            self.counts.add("fixture_gameweek_assignment", "reused")
            return
        transition_at = self.system_at
        if current is not None:
            current_system: Range[datetime] = current["system_during"]
            current_captured_at = _source_captured_at(self.session, current["source_snapshot_id"])
            if self.captured_at < current_captured_at:
                self.counts.add("fixture_gameweek_assignment", "reused")
                return
            if self.captured_at == current_captured_at:
                raise IngestionError(
                    "MAPPING_CONFLICT", "Gameweek assignment contradicts an equal-time fact"
                )
            transition_at = _successor_system_at(self.system_at, current_system)
        if current is not None:
            self.session.execute(
                text("SET CONSTRAINTS football.ex_fixture_gameweek_assignment_current DEFERRED")
            )
        valid_start = source.kickoff_time or _valid_range(self.season_code).lower
        new_id = _uuid(
            self.session.execute(
                insert(fixture_gameweek_assignment)
                .values(
                    fixture_id=fixture_id,
                    gameweek_id=gameweek_id,
                    assignment_status=status,
                    valid_during=Range(valid_start, None, bounds="[)"),
                    system_during=Range(transition_at, None, bounds="[)"),
                    source_snapshot_id=self.fixtures_snapshot_id,
                    season_id=season_id,
                )
                .returning(fixture_gameweek_assignment.c.assignment_id)
            ).scalar_one()
        )
        if current is not None:
            system_range: Range[datetime] = current["system_during"]
            self.session.execute(
                update(fixture_gameweek_assignment)
                .where(fixture_gameweek_assignment.c.assignment_id == current["assignment_id"])
                .values(
                    system_during=Range(system_range.lower, transition_at, bounds="[)"),
                    superseded_by_assignment_id=new_id,
                )
            )
            self.session.execute(
                text("SET CONSTRAINTS football.ex_fixture_gameweek_assignment_current IMMEDIATE")
            )
        self.counts.add(
            "fixture_gameweek_assignment", "changed" if current is not None else "created"
        )
