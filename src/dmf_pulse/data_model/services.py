"""Transactional synthetic-fixture services for DAT-003 acceptance."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.errors import DataModelError
from dmf_pulse.data_model.models import (
    AsOfQueryResult,
    AsOfResult,
    AsOfScope,
    AssignmentStatus,
    DemoResult,
    EntityType,
    FixtureStatus,
    MappingStatus,
    RegistrationType,
    SquadStatus,
    TemporalRange,
    require_utc,
)
from dmf_pulse.data_model.repositories import (
    CanonicalRepository,
    ExternalIdentifierRepository,
    FixtureRepository,
    PlayerMembershipRepository,
    SourceObservationRepository,
)
from dmf_pulse.data_model.tables import metadata, raw_blob_deletion


@dataclass(frozen=True)
class _SeedState:
    aliases: dict[str, UUID]
    fixture: dict[str, Any]


def _load_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        if len(raw) > 1024 * 1024:
            raise ValueError("fixture is too large")
        value = json.loads(raw)
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise ValueError("fixture root must be an object")
        return cast(dict[str, Any], value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise DataModelError("FIXTURE_INVALID", "fixture is unavailable or invalid") from exc


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DataModelError("FIXTURE_INVALID", f"fixture field {field} must be an object")
    return cast(dict[str, Any], value)


def _objects(value: object, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise DataModelError("FIXTURE_INVALID", f"fixture field {field} must be an array")
    return [_object(item, field) for item in value]


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DataModelError("FIXTURE_INVALID", f"fixture field {field} must be a string")
    return value


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DataModelError("FIXTURE_INVALID", f"fixture field {field} must be an integer")
    return value


def _datetime(value: object, field: str) -> datetime:
    raw = _string(value, field)
    if not raw.endswith("Z"):
        raise DataModelError("FIXTURE_INVALID", f"fixture field {field} must be UTC")
    try:
        return require_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError as exc:
        raise DataModelError("FIXTURE_INVALID", f"fixture field {field} is invalid") from exc


def _date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(_string(value, field))
    except ValueError as exc:
        raise DataModelError("FIXTURE_INVALID", f"fixture field {field} is invalid") from exc


def _range(item: Mapping[str, object]) -> TemporalRange:
    end_value = item.get("valid_until")
    return TemporalRange(
        start=_datetime(item.get("valid_from"), "valid_from"),
        end=_datetime(end_value, "valid_until") if end_value is not None else None,
    )


def _uuid_version_is_seven(values: Mapping[str, UUID]) -> bool:
    return bool(values) and all(value.version == 7 for value in values.values())


def _assertions(values: Mapping[str, bool]) -> tuple[dict[str, Any], ...]:
    failed = [name for name, passed in values.items() if not passed]
    if failed:
        raise DataModelError("FIXTURE_ASSERTION_FAILED", f"synthetic assertion failed: {failed[0]}")
    return tuple({"name": name, "passed": True} for name in sorted(values))


def _run_rollback[T](factory: sessionmaker[Session], operation: Callable[[Session], T]) -> T:
    session = factory()
    transaction = session.begin()
    try:
        result = operation(session)
        transaction.rollback()
        return result
    except Exception:
        if transaction.is_active:
            transaction.rollback()
        raise
    finally:
        session.close()


def _seed(session: Session, fixture_path: Path) -> _SeedState:
    fixture_data = _load_object(fixture_path)
    if fixture_data.get("rights") != "SYNTHETIC":
        raise DataModelError(
            "FIXTURE_RIGHTS_FORBIDDEN",
            "demo persistence requires an explicitly synthetic fixture",
        )
    entities = _object(fixture_data.get("entities"), "entities")
    aliases: dict[str, UUID] = {}
    canonical = CanonicalRepository(session)

    competition_data = _object(entities.get("competition"), "entities.competition")
    competition_key = _string(competition_data.get("key"), "competition.key")
    aliases[competition_key] = canonical.create_entity(
        EntityType.COMPETITION,
        competition_key=competition_key,
        canonical_name=_string(competition_data.get("name"), "competition.name"),
        country_code=_string(competition_data.get("country_code"), "competition.country_code"),
    )

    for item in _objects(entities.get("teams"), "entities.teams"):
        key = _string(item.get("key"), "team.key")
        aliases[key] = canonical.create_entity(
            EntityType.TEAM,
            canonical_name=_string(item.get("name"), "team.name"),
            short_name=_string(item.get("short_name"), "team.short_name"),
        )

    season_data = _object(entities.get("season"), "entities.season")
    season_alias = f"season-{_string(season_data.get('code'), 'season.code').replace('/', '-')}"
    aliases[season_alias] = canonical.create_entity(
        EntityType.SEASON,
        competition_id=aliases[competition_key],
        season_code=_string(season_data.get("code"), "season.code"),
        starts_on=_date(season_data.get("starts_on"), "season.starts_on"),
        ends_on=_date(season_data.get("ends_on"), "season.ends_on"),
    )

    player_data = _object(entities.get("player"), "entities.player")
    player_key = _string(player_data.get("key"), "player.key")
    aliases[player_key] = canonical.create_entity(
        EntityType.PLAYER,
        canonical_name=_string(player_data.get("name"), "player.name"),
        birth_date=_date(player_data.get("birth_date"), "player.birth_date"),
    )

    fixture_entity = _object(entities.get("fixture"), "entities.fixture")
    fixture_key = _string(fixture_entity.get("key"), "fixture.key")
    aliases[fixture_key] = canonical.create_entity(
        EntityType.FIXTURE,
        competition_id=aliases[competition_key],
        season_id=aliases[season_alias],
        home_team_id=aliases[_string(fixture_entity.get("home"), "fixture.home")],
        away_team_id=aliases[_string(fixture_entity.get("away"), "fixture.away")],
    )

    for item in _objects(entities.get("gameweeks"), "entities.gameweeks"):
        number = _integer(item.get("number"), "gameweek.number")
        key = f"gameweek-{number}"
        aliases[key] = canonical.create_entity(
            EntityType.GAMEWEEK,
            season_id=aliases[season_alias],
            number=number,
            display_name=_string(item.get("display_name"), "gameweek.display_name"),
            official_deadline_at=_datetime(item.get("deadline"), "gameweek.deadline"),
            status="DRAFT",
        )

    for item in _objects(entities.get("providers"), "entities.providers"):
        key = _string(item.get("key"), "provider.key")
        aliases[key] = canonical.create_entity(
            EntityType.DATA_PROVIDER,
            provider_key=key,
            display_name=_string(item.get("name"), "provider.name"),
            provider_type=_string(item.get("type"), "provider.type"),
            rights_profile_key=_string(item.get("rights_profile"), "provider.rights_profile"),
        )

    observations = _object(fixture_data.get("raw_observations"), "raw_observations")
    body = _string(observations.get("body_utf8"), "raw_observations.body_utf8").encode()
    source_repository = SourceObservationRepository(session)
    raw_id = source_repository.get_or_create_raw_blob(
        body, storage_policy="ALLOWED", content_type="application/json"
    )
    repeated_raw_id = source_repository.get_or_create_raw_blob(
        body, storage_policy="ALLOWED", content_type="application/json"
    )
    aliases["raw-blob"] = raw_id
    body_hash = hashlib.sha256(body).hexdigest()
    snapshot_ids: list[UUID] = []
    for snapshot in _objects(observations.get("snapshots"), "raw_observations.snapshots"):
        key = _string(snapshot.get("key"), "snapshot.key")
        received_at = _datetime(snapshot.get("received_at"), "snapshot.received_at")
        snapshot_id = source_repository.record_source_snapshot(
            provider_id=aliases["test-provider"],
            resource="synthetic-player",
            request_fingerprint=hashlib.sha256(key.encode()).hexdigest(),
            request_started_at=received_at,
            received_at=received_at,
            stored_at=received_at,
            parsed_at=_datetime(snapshot.get("usable_at"), "snapshot.usable_at"),
            mapped_at=_datetime(snapshot.get("usable_at"), "snapshot.usable_at"),
            usable_at=_datetime(snapshot.get("usable_at"), "snapshot.usable_at"),
            raw_blob_id=raw_id,
            raw_storage_policy="ALLOWED",
            body_sha256=body_hash,
            rights_profile_key="RP-SYNTHETIC-001",
            validation_status="USABLE",
            dataset_mode="RAW_OBSERVED",
            content_type="application/json",
            terms_version="synthetic-v1",
        )
        aliases[key] = snapshot_id
        snapshot_ids.append(snapshot_id)

    external_repository = ExternalIdentifierRepository(session)
    for item in _objects(
        fixture_data.get("external_identifier_versions"), "external_identifier_versions"
    ):
        key = _string(item.get("key"), "external_identifier.key")
        supersedes = item.get("supersedes")
        if supersedes is None:
            version_id = external_repository.add_version(
                canonical_entity_id=aliases[player_key],
                provider_id=aliases[_string(item.get("provider"), "external_identifier.provider")],
                provider_product=_string(item.get("product"), "external_identifier.product"),
                identifier_namespace=_string(
                    item.get("namespace"), "external_identifier.namespace"
                ),
                entity_type=EntityType.PLAYER,
                external_id_text=_string(
                    item.get("external_id"), "external_identifier.external_id"
                ),
                valid_range=_range(item),
                known_at=_datetime(item.get("known_at"), "external_identifier.known_at"),
                mapping_status=MappingStatus(
                    _string(item.get("status"), "external_identifier.status")
                ),
                first_seen_at=_datetime(item.get("known_at"), "external_identifier.known_at"),
                last_seen_at=_datetime(item.get("known_at"), "external_identifier.known_at"),
                raw_example=_string(item.get("raw_example"), "external_identifier.raw_example"),
                evidence_source_snapshot_id=snapshot_ids[0],
            )
        else:
            version_id = external_repository.supersede(
                aliases[_string(supersedes, "external_identifier.supersedes")],
                known_at=_datetime(item.get("known_at"), "external_identifier.known_at"),
                provider_product=_string(item.get("product"), "external_identifier.product"),
                identifier_namespace=_string(
                    item.get("namespace"), "external_identifier.namespace"
                ),
                external_id_text=_string(
                    item.get("external_id"), "external_identifier.external_id"
                ),
                valid_range=_range(item),
                mapping_status=MappingStatus(
                    _string(item.get("status"), "external_identifier.status")
                ),
                raw_example=_string(item.get("raw_example"), "external_identifier.raw_example"),
                evidence_source_snapshot_id=snapshot_ids[1],
                last_seen_at=_datetime(item.get("known_at"), "external_identifier.known_at"),
            )
        aliases[key] = version_id

    membership_repository = PlayerMembershipRepository(session)
    for item in _objects(fixture_data.get("membership_versions"), "membership_versions"):
        key = _string(item.get("key"), "membership.key")
        aliases[key] = membership_repository.add_version(
            player_id=aliases[player_key],
            team_id=aliases[_string(item.get("team"), "membership.team")],
            season_id=aliases[season_alias],
            registration_type=RegistrationType(
                _string(item.get("registration_type"), "membership.registration_type")
            ),
            squad_status=SquadStatus.REGISTERED,
            valid_range=_range(item),
            known_at=_datetime(item.get("known_at"), "membership.known_at"),
            source_snapshot_id=snapshot_ids[0],
        )

    fixture_repository = FixtureRepository(session)
    for item in _objects(fixture_data.get("fixture_revisions"), "fixture_revisions"):
        key = _string(item.get("key"), "fixture_revision.key")
        supersedes = item.get("supersedes")
        revision_number = _integer(item.get("number"), "fixture_revision.number")
        kickoff_at = _datetime(item.get("kickoff"), "fixture_revision.kickoff")
        fixture_status = FixtureStatus(_string(item.get("status"), "fixture_revision.status"))
        valid_range = _range(item)
        known_at = _datetime(item.get("known_at"), "fixture_revision.known_at")
        if supersedes is None:
            revision_id = fixture_repository.add_revision(
                fixture_id=aliases[fixture_key],
                revision_number=revision_number,
                kickoff_at=kickoff_at,
                fixture_status=fixture_status,
                valid_range=valid_range,
                known_at=known_at,
                observed_at=known_at,
                source_snapshot_id=snapshot_ids[0],
            )
        else:
            revision_id = fixture_repository.revise(
                aliases[_string(supersedes, "fixture_revision.supersedes")],
                revision_number=revision_number,
                kickoff_at=kickoff_at,
                fixture_status=fixture_status,
                valid_range=valid_range,
                known_at=known_at,
                observed_at=known_at,
                source_snapshot_id=snapshot_ids[1],
            )
        aliases[key] = revision_id

    for item in _objects(fixture_data.get("gameweek_assignments"), "gameweek_assignments"):
        key = _string(item.get("key"), "gameweek_assignment.key")
        supersedes = item.get("supersedes")
        assignment_id = fixture_repository.assign_gameweek(
            fixture_id=aliases[fixture_key],
            gameweek_id=aliases[
                f"gameweek-{_integer(item.get('gameweek'), 'assignment.gameweek')}"
            ],
            assignment_status=AssignmentStatus(
                _string(item.get("status"), "gameweek_assignment.status")
            ),
            valid_range=_range(item),
            known_at=_datetime(item.get("known_at"), "gameweek_assignment.known_at"),
            source_snapshot_id=snapshot_ids[1] if supersedes is not None else snapshot_ids[0],
            supersedes=(
                aliases[_string(supersedes, "gameweek_assignment.supersedes")]
                if supersedes is not None
                else None
            ),
        )
        aliases[key] = assignment_id

    tombstone_id = session.execute(
        insert(raw_blob_deletion)
        .values(
            raw_blob_id=raw_id,
            deleted_at=_datetime("2026-07-22T00:00:00Z", "tombstone.deleted_at"),
            reason="synthetic retention acceptance",
            tombstone_sha256=hashlib.sha256(f"deleted:{raw_id}".encode()).hexdigest(),
            approved_by="DAT-003 synthetic fixture",
        )
        .returning(raw_blob_deletion.c.deletion_id)
    ).scalar_one()
    if not isinstance(tombstone_id, UUID):
        raise DataModelError("DATABASE_RESULT_INVALID", "database returned an invalid identifier")
    aliases["raw-blob-deletion"] = tombstone_id
    aliases["raw-blob-repeat"] = repeated_raw_id
    return _SeedState(aliases=aliases, fixture=fixture_data)


def _counts(session: Session) -> dict[str, int]:
    return {
        table.fullname: int(session.execute(select(func.count()).select_from(table)).scalar_one())
        for table in sorted(metadata.tables.values(), key=lambda item: item.fullname)
    }


def _scope(valid_at: str, known_at: str) -> AsOfScope:
    return AsOfScope(
        valid_at=_datetime(valid_at, "valid_at"), known_at=_datetime(known_at, "known_at")
    )


def _demo_result(session: Session, state: _SeedState) -> DemoResult:
    aliases = state.aliases
    player = aliases["alex-example"]
    fixture_id = aliases["north-v-south"]
    external = ExternalIdentifierRepository(session)
    membership = PlayerMembershipRepository(session)
    fixtures = FixtureRepository(session)
    before_boundary = membership.get_as_of(
        player,
        RegistrationType.PERMANENT,
        _scope("2026-07-31T23:59:59.999999Z", "2026-07-15T00:00:00Z"),
    )
    at_boundary = membership.get_as_of(
        player,
        RegistrationType.PERMANENT,
        _scope("2026-08-01T00:00:00Z", "2026-07-15T00:00:00Z"),
    )
    before_external = external.get_as_of(
        player, _scope("2026-07-15T00:00:00Z", "2026-07-12T11:59:59.999999Z")
    )
    at_external = external.get_as_of(player, _scope("2026-07-15T00:00:00Z", "2026-07-12T12:00:00Z"))
    before_revision = fixtures.get_revision_as_of(
        fixture_id,
        _scope("2026-08-21T00:00:00Z", "2026-07-20T08:59:59.999999Z"),
    )
    at_revision = fixtures.get_revision_as_of(
        fixture_id, _scope("2026-08-21T00:00:00Z", "2026-07-20T09:00:00Z")
    )
    before_assignment = fixtures.get_gameweek_as_of(
        fixture_id,
        _scope("2026-08-21T00:00:00Z", "2026-07-21T09:59:59.999999Z"),
    )
    at_assignment = fixtures.get_gameweek_as_of(
        fixture_id, _scope("2026-08-21T00:00:00Z", "2026-07-21T10:00:00Z")
    )
    available = int(
        session.execute(text("SELECT count(*) FROM provenance.available_raw_blob")).scalar_one()
    )
    values = {
        "external_history_preserved": (
            before_external["fact_version_id"] == str(aliases["ext-v1"])
            and at_external["fact_version_id"] == str(aliases["ext-v2"])
        ),
        "fixture_revision_correction": (
            before_revision["fact_version_id"] == str(aliases["fixture-rev-1"])
            and at_revision["fact_version_id"] == str(aliases["fixture-rev-2"])
        ),
        "gameweek_reassignment": (
            before_assignment["fact_version_id"] == str(aliases["assign-gw1"])
            and at_assignment["fact_version_id"] == str(aliases["assign-gw2"])
        ),
        "membership_boundary_half_open": (
            before_boundary["team_id"] == str(aliases["north-fc"])
            and at_boundary["team_id"] == str(aliases["south-fc"])
        ),
        "postgres_uuidv7": _uuid_version_is_seven(aliases),
        "raw_blob_deduplicated": aliases["raw-blob"] == aliases["raw-blob-repeat"],
        "raw_tombstone_hides_available": available == 0,
        "source_snapshots_distinct": aliases["snapshot-1"] != aliases["snapshot-2"],
    }
    return DemoResult(
        fixture_id=_string(state.fixture.get("fixture_id"), "fixture_id"),
        aliases={name: name for name in sorted(aliases)},
        counts=_counts(session),
        assertions=_assertions(values),
    )


def run_demo(factory: sessionmaker[Session], fixture_path: Path) -> DemoResult:
    """Execute the bounded synthetic fixture and always roll it back."""

    return _run_rollback(
        factory, lambda session: _demo_result(session, _seed(session, fixture_path))
    )


def _semantic_result(
    result: dict[str, Any],
    *,
    reverse_aliases: Mapping[str, str],
    gameweeks: Mapping[str, int],
) -> dict[str, Any]:
    semantic = dict(result)
    fact_version_id = result["fact_version_id"]
    semantic["version"] = reverse_aliases[fact_version_id]
    for field in ("canonical_id", "fact_version_id", "source_snapshot_id", "team_id"):
        identifier = result.get(field)
        if isinstance(identifier, str) and identifier in reverse_aliases:
            semantic[field] = reverse_aliases[identifier]
    team_id = result.get("team_id")
    if isinstance(team_id, str):
        semantic["team"] = reverse_aliases[team_id]
    gameweek_id = result.get("gameweek_id")
    if isinstance(gameweek_id, str):
        semantic["gameweek"] = gameweeks[gameweek_id]
        semantic["gameweek_id"] = reverse_aliases[gameweek_id]
    return semantic


def _as_of_result(session: Session, state: _SeedState, query_path: Path) -> AsOfResult:
    query_fixture = _load_object(query_path)
    reverse = {str(identifier): alias for alias, identifier in state.aliases.items()}
    gameweek_numbers = {
        str(state.aliases["gameweek-1"]): 1,
        str(state.aliases["gameweek-2"]): 2,
    }
    external = ExternalIdentifierRepository(session)
    memberships = PlayerMembershipRepository(session)
    fixtures = FixtureRepository(session)
    outputs: list[AsOfQueryResult] = []
    assertions: dict[str, bool] = {}
    for query in _objects(query_fixture.get("queries"), "queries"):
        query_id = _string(query.get("query_id"), "query.query_id")
        scope = AsOfScope(
            valid_at=_datetime(query.get("valid_at"), "query.valid_at"),
            known_at=_datetime(query.get("known_at"), "query.known_at"),
        )
        kind = _string(query.get("kind"), "query.kind")
        if kind == "player_membership":
            raw_result = memberships.get_as_of(
                state.aliases[_string(query.get("player"), "query.player")],
                RegistrationType.PERMANENT,
                scope,
            )
        elif kind == "external_identifier":
            raw_result = external.get_as_of(
                state.aliases[_string(query.get("entity"), "query.entity")], scope
            )
        elif kind == "fixture_revision":
            raw_result = fixtures.get_revision_as_of(
                state.aliases[_string(query.get("fixture"), "query.fixture")], scope
            )
        elif kind == "fixture_gameweek":
            raw_result = fixtures.get_gameweek_as_of(
                state.aliases[_string(query.get("fixture"), "query.fixture")], scope
            )
        else:
            raise DataModelError("FIXTURE_INVALID", "as-of query kind is invalid")
        result = _semantic_result(raw_result, reverse_aliases=reverse, gameweeks=gameweek_numbers)
        expected = _object(query.get("expect"), "query.expect")
        assertions[query_id] = all(result.get(key) == value for key, value in expected.items())
        outputs.append(
            AsOfQueryResult(
                query_id=query_id,
                valid_at=scope.valid_at,
                known_at=scope.known_at,
                result=result,
            )
        )
    return AsOfResult(
        fixture_id=_string(query_fixture.get("fixture_id"), "fixture_id"),
        queries=tuple(outputs),
        assertions=_assertions(assertions),
    )


def run_as_of(factory: sessionmaker[Session], query_path: Path) -> AsOfResult:
    """Seed the sibling demo fixture, run declared bitemporal queries, and roll back."""

    demo_path = query_path.with_name("demo.json")
    return _run_rollback(
        factory,
        lambda session: _as_of_result(session, _seed(session, demo_path), query_path),
    )
