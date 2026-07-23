"""PostgreSQL-backed canonical, temporal, provenance, and CLI contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from psycopg.types.range import Range
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.data_model.errors import DataModelError, translate_database_error
from dmf_pulse.data_model.models import (
    AliasType,
    AsOfScope,
    AssignmentStatus,
    EntityType,
    FixtureStatus,
    MappingMethod,
    MappingStatus,
    RegistrationType,
    SquadStatus,
    TemporalRange,
)
from dmf_pulse.data_model.repositories import (
    AliasRepository,
    CanonicalRepository,
    ExternalIdentifierRepository,
    FixtureRepository,
    PlayerMembershipRepository,
    SourceObservationRepository,
    commit_session,
)
from dmf_pulse.data_model.services import run_as_of, run_demo
from dmf_pulse.data_model.tables import (
    canonical_entity,
    entity_alias,
    fixture_revision,
    player_team_membership,
    raw_blob,
    raw_blob_deletion,
    ruleset_activation,
    ruleset_artifact,
    source_snapshot,
    team,
)

pytestmark = pytest.mark.postgres

SEED_KNOWN = datetime(2026, 7, 10, 10, tzinfo=UTC)
VALID_START = datetime(2026, 7, 1, tzinfo=UTC)


@dataclass(frozen=True)
class _Graph:
    competition: UUID
    fixture: UUID
    gameweek_one: UUID
    gameweek_two: UUID
    north: UUID
    player: UUID
    provider: UUID
    season: UUID
    snapshot_one: UUID
    snapshot_two: UUID
    south: UUID


def _graph(factory: sessionmaker[Session]) -> _Graph:
    with factory() as session:
        canonical = CanonicalRepository(session)
        competition = canonical.create_entity(
            EntityType.COMPETITION,
            competition_key="test-league",
            canonical_name="Test League",
            country_code="GB",
        )
        north = canonical.create_entity(EntityType.TEAM, canonical_name="North", short_name="NTH")
        south = canonical.create_entity(EntityType.TEAM, canonical_name="South", short_name="STH")
        player = canonical.create_entity(
            EntityType.PLAYER, canonical_name="Alex", birth_date=date(2000, 1, 1)
        )
        provider = canonical.create_entity(
            EntityType.DATA_PROVIDER,
            provider_key="test-provider",
            display_name="Test Provider",
            provider_type="INTERNAL",
            rights_profile_key="RP-SYNTHETIC",
        )
        season = canonical.create_entity(
            EntityType.SEASON,
            competition_id=competition,
            season_code="2026/27",
            starts_on=date(2026, 8, 1),
            ends_on=date(2027, 5, 31),
        )
        fixture = canonical.create_entity(
            EntityType.FIXTURE,
            competition_id=competition,
            season_id=season,
            home_team_id=north,
            away_team_id=south,
        )
        gameweek_one = canonical.create_entity(
            EntityType.GAMEWEEK,
            season_id=season,
            number=1,
            display_name="GW1",
            official_deadline_at=datetime(2026, 8, 21, 17, 30, tzinfo=UTC),
            status="DRAFT",
        )
        gameweek_two = canonical.create_entity(
            EntityType.GAMEWEEK,
            season_id=season,
            number=2,
            display_name="GW2",
            official_deadline_at=datetime(2026, 8, 28, 17, 30, tzinfo=UTC),
            status="DRAFT",
        )
        sources = SourceObservationRepository(session)
        snapshot_one = sources.record_source_snapshot(
            provider_id=provider,
            resource="synthetic-correction",
            request_fingerprint="a" * 64,
            request_started_at=SEED_KNOWN,
            received_at=SEED_KNOWN,
            usable_at=SEED_KNOWN,
            raw_blob_id=None,
            raw_storage_policy="FORBIDDEN",
            body_sha256=None,
            rights_profile_key="RP-SYNTHETIC",
            validation_status="USABLE",
            dataset_mode="RAW_OBSERVED",
        )
        second_known = SEED_KNOWN + timedelta(hours=1)
        snapshot_two = sources.record_source_snapshot(
            provider_id=provider,
            resource="synthetic-correction",
            request_fingerprint="b" * 64,
            request_started_at=second_known,
            received_at=second_known,
            usable_at=second_known,
            raw_blob_id=None,
            raw_storage_policy="FORBIDDEN",
            body_sha256=None,
            rights_profile_key="RP-SYNTHETIC",
            validation_status="USABLE",
            dataset_mode="RAW_OBSERVED",
        )
        commit_session(session)
    return _Graph(
        competition=competition,
        fixture=fixture,
        gameweek_one=gameweek_one,
        gameweek_two=gameweek_two,
        north=north,
        player=player,
        provider=provider,
        season=season,
        snapshot_one=snapshot_one,
        snapshot_two=snapshot_two,
        south=south,
    )


def test_demo_and_as_of_goldens_are_transactionally_idempotent(
    postgres_session_factory: sessionmaker[Session], repository_root: Path
) -> None:
    fixture_root = repository_root / "fixtures/data_model/DAT-003"
    first = run_demo(postgres_session_factory, fixture_root / "demo.json")
    second = run_demo(postgres_session_factory, fixture_root / "demo.json")
    assert first.fixture_id == second.fixture_id == "DAT-003-DEMO-001"
    assert first.counts == second.counts
    assert all(assertion["passed"] for assertion in first.assertions)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    serialized_demo = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    assert re.search(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", serialized_demo) is None

    as_of = run_as_of(postgres_session_factory, fixture_root / "as_of_queries.json")
    repeated_as_of = run_as_of(postgres_session_factory, fixture_root / "as_of_queries.json")
    assert as_of.model_dump(mode="json") == repeated_as_of.model_dump(mode="json")
    assert as_of.fixture_id == "DAT-003-ASOF-001"
    assert len(as_of.queries) == 8
    assert all(assertion["passed"] for assertion in as_of.assertions)
    assert as_of.queries[0].result is not None
    assert as_of.queries[0].result["team"] == "north-fc"
    assert as_of.queries[1].result is not None
    assert as_of.queries[1].result["team"] == "south-fc"
    assert as_of.queries[3].result is not None
    assert as_of.queries[3].result["source_snapshot_id"] == "snapshot-2"
    assert as_of.queries[5].result is not None
    assert as_of.queries[5].result["source_snapshot_id"] == "snapshot-2"
    assert as_of.queries[7].result is not None
    assert as_of.queries[7].result["source_snapshot_id"] == "snapshot-2"
    serialized_as_of = json.dumps(as_of.model_dump(mode="json"), sort_keys=True)
    assert re.search(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", serialized_as_of) is None

    with postgres_session_factory() as session:
        assert session.execute(select(func.count()).select_from(canonical_entity)).scalar_one() == 0


def test_demo_rejects_fixture_without_explicit_synthetic_rights(
    postgres_session_factory: sessionmaker[Session], repository_root: Path, tmp_path: Path
) -> None:
    fixture = json.loads(
        (repository_root / "fixtures/data_model/DAT-003/demo.json").read_text(encoding="utf-8")
    )
    fixture["rights"] = "UNKNOWN"
    path = tmp_path / "unsafe-demo.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    with pytest.raises(DataModelError) as denied:
        run_demo(postgres_session_factory, path)
    assert denied.value.code == "FIXTURE_RIGHTS_FORBIDDEN"


def test_cli_json_is_public_contract_shaped_and_secret_redacted(
    monkeypatch: pytest.MonkeyPatch, postgres_url: str, repository_root: Path
) -> None:
    monkeypatch.setenv("DMF_ENVIRONMENT", "TEST")
    monkeypatch.setenv("DMF_TEST_DATABASE_URL", postgres_url)
    runner = CliRunner()
    doctor = runner.invoke(app, ["data-model", "doctor", "--json"])
    assert doctor.exit_code == 0, doctor.output
    doctor_json = json.loads(doctor.stdout)
    assert doctor_json["status"] == "HEALTHY"
    assert doctor_json["postgres"]["major"] == 18
    assert all(value not in doctor.stdout for value in ("changeme", "dmf_test_password"))
    assert "postgresql" not in doctor.stdout

    manifest = runner.invoke(app, ["data-model", "schema-manifest", "--json"])
    assert manifest.exit_code == 0, manifest.output
    assert len(json.loads(manifest.stdout)["schema_sha256"]) == 64

    demo_path = repository_root / "fixtures/data_model/DAT-003/demo.json"
    demo = runner.invoke(app, ["data-model", "demo", "--fixture", str(demo_path), "--json"])
    assert demo.exit_code == 0, demo.output
    assert all(item["passed"] for item in json.loads(demo.stdout)["assertions"])

    monkeypatch.setenv("DMF_ENVIRONMENT", "PRODUCTION")
    rejected = runner.invoke(app, ["data-model", "doctor", "--json"])
    assert rejected.exit_code == 50
    assert all(value not in rejected.output for value in ("changeme", "dmf_test_password"))
    assert json.loads(rejected.stderr)["error"]["code"] == "DATABASE_CONFIGURATION_INVALID"


def test_external_identifier_supersession_preserves_history(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _graph(postgres_session_factory)
    with postgres_session_factory() as session:
        repository = ExternalIdentifierRepository(session)
        late_snapshot = SourceObservationRepository(session).record_source_snapshot(
            provider_id=graph.provider,
            resource="late-synthetic",
            request_fingerprint="c" * 64,
            request_started_at=SEED_KNOWN,
            received_at=SEED_KNOWN,
            usable_at=SEED_KNOWN + timedelta(days=1),
            raw_blob_id=None,
            raw_storage_policy="FORBIDDEN",
            body_sha256=None,
            rights_profile_key="RP-SYNTHETIC",
            validation_status="USABLE",
            dataset_mode="RAW_OBSERVED",
        )
        with pytest.raises(DataModelError) as premature:
            repository.add_version(
                canonical_entity_id=graph.player,
                provider_id=graph.provider,
                provider_product="players",
                identifier_namespace="test.player",
                entity_type=EntityType.PLAYER,
                external_id_text="premature",
                valid_range=TemporalRange(start=VALID_START),
                known_at=SEED_KNOWN,
                mapping_status=MappingStatus.AUTO_MATCHED,
                first_seen_at=SEED_KNOWN,
                last_seen_at=SEED_KNOWN,
                evidence_source_snapshot_id=late_snapshot,
            )
        assert premature.value.code == "PROVENANCE_INTEGRITY"
        original = repository.add_version(
            canonical_entity_id=graph.player,
            provider_id=graph.provider,
            provider_product="players",
            identifier_namespace="test.player",
            entity_type=EntityType.PLAYER,
            external_id_text="player-1",
            valid_range=TemporalRange(start=VALID_START),
            known_at=SEED_KNOWN,
            mapping_status=MappingStatus.AUTO_MATCHED,
            first_seen_at=SEED_KNOWN,
            last_seen_at=SEED_KNOWN,
            evidence_source_snapshot_id=graph.snapshot_one,
        )
        corrected_at = datetime(2026, 7, 12, 12, tzinfo=UTC)
        with pytest.raises(DataModelError) as reused_source:
            repository.supersede(
                original,
                known_at=corrected_at,
                provider_product="players-v2",
                identifier_namespace="test.player.v2",
                external_id_text="player-1",
                valid_range=TemporalRange(start=VALID_START),
                mapping_status=MappingStatus.HUMAN_VERIFIED,
                evidence_source_snapshot_id=graph.snapshot_one,
                last_seen_at=corrected_at,
            )
        assert reused_source.value.code == "PROVENANCE_INTEGRITY"
        corrected = repository.supersede(
            original,
            known_at=corrected_at,
            provider_product="players-v2",
            identifier_namespace="test.player.v2",
            external_id_text="player-1",
            valid_range=TemporalRange(start=VALID_START),
            mapping_status=MappingStatus.HUMAN_VERIFIED,
            evidence_source_snapshot_id=graph.snapshot_two,
            last_seen_at=corrected_at + timedelta(hours=2),
        )
        commit_session(session)

    with postgres_session_factory() as session:
        repository = ExternalIdentifierRepository(session)
        before = repository.get_as_of(
            graph.player,
            AsOfScope(
                valid_at=datetime(2026, 7, 15, tzinfo=UTC),
                known_at=corrected_at - timedelta(microseconds=1),
            ),
        )
        after = repository.get_as_of(
            graph.player,
            AsOfScope(valid_at=datetime(2026, 7, 15, tzinfo=UTC), known_at=corrected_at),
        )
        assert before["fact_version_id"] == str(original)
        assert before["namespace"] == "test.player"
        assert after["fact_version_id"] == str(corrected)
        assert after["namespace"] == "test.player.v2"

    with postgres_session_factory() as session:
        second_provider = CanonicalRepository(session).create_entity(
            EntityType.DATA_PROVIDER,
            provider_key="second-provider",
            display_name="Second Provider",
            provider_type="INTERNAL",
            rights_profile_key="RP-SYNTHETIC-2",
        )
        ExternalIdentifierRepository(session).add_version(
            canonical_entity_id=graph.player,
            provider_id=second_provider,
            provider_product="players",
            identifier_namespace="second.player",
            entity_type=EntityType.PLAYER,
            external_id_text="other-player-1",
            valid_range=TemporalRange(start=VALID_START),
            known_at=SEED_KNOWN,
            mapping_status=MappingStatus.AUTO_MATCHED,
            first_seen_at=SEED_KNOWN,
            last_seen_at=SEED_KNOWN,
        )
        commit_session(session)

    with postgres_session_factory() as session:
        repository = ExternalIdentifierRepository(session)
        scope = AsOfScope(valid_at=datetime(2026, 7, 15, tzinfo=UTC), known_at=corrected_at)
        with pytest.raises(DataModelError) as ambiguous:
            repository.get_as_of(graph.player, scope)
        assert ambiguous.value.code == "AS_OF_AMBIGUOUS"
        selected = repository.get_as_of(graph.player, scope, provider_id=graph.provider)
        assert selected["fact_version_id"] == str(corrected)
        current = (
            session.execute(
                text(
                    "SELECT external_identifier_id FROM core.current_external_identifier "
                    "WHERE canonical_entity_id = :entity AND provider_id = :provider"
                ),
                {"entity": graph.player, "provider": graph.provider},
            )
            .scalars()
            .all()
        )
        assert current == [corrected]


def test_alias_insertion_preserves_identity_and_enforces_preferred_scope(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _graph(postgres_session_factory)
    with postgres_session_factory() as session:
        repository = AliasRepository(session)
        preferred = repository.add_version(
            canonical_entity_id=graph.player,
            raw_text="A\N{COMBINING ACUTE ACCENT}lex",
            normalized_nfc="\N{LATIN CAPITAL LETTER A WITH ACUTE}lex",
            match_key="alex",
            alias_type=AliasType.OFFICIAL,
            valid_range=TemporalRange(start=VALID_START),
            known_at=SEED_KNOWN,
            provider_id=graph.provider,
            source_snapshot_id=graph.snapshot_one,
            confidence=Decimal("1.000000"),
            is_preferred=True,
        )
        secondary = repository.add_version(
            canonical_entity_id=graph.player,
            raw_text="Alex",
            normalized_nfc="Alex",
            match_key="alex",
            alias_type=AliasType.SHORT,
            valid_range=TemporalRange(start=VALID_START),
            known_at=SEED_KNOWN,
        )
        commit_session(session)

    with postgres_session_factory() as session:
        aliases = (
            session.execute(
                select(entity_alias).where(entity_alias.c.canonical_entity_id == graph.player)
            )
            .mappings()
            .all()
        )
        assert {row["alias_id"] for row in aliases} == {preferred, secondary}
        assert all(row["canonical_entity_id"] == graph.player for row in aliases)
        assert {row["normalized_nfc"] for row in aliases} == {
            "\N{LATIN CAPITAL LETTER A WITH ACUTE}lex",
            "Alex",
        }

    with postgres_session_factory() as session:
        with pytest.raises(DataModelError) as overlap:
            AliasRepository(session).add_version(
                canonical_entity_id=graph.player,
                raw_text="Alex Preferred",
                normalized_nfc="Alex Preferred",
                match_key="alex preferred",
                alias_type=AliasType.DISPLAY,
                valid_range=TemporalRange(start=VALID_START),
                known_at=SEED_KNOWN,
                is_preferred=True,
            )
        assert overlap.value.code == "TEMPORAL_OVERLAP"


def test_uuidv7_and_core_business_constraints_are_database_enforced(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _graph(postgres_session_factory)
    identifiers = tuple(value for value in graph.__dict__.values() if isinstance(value, UUID))
    assert len(set(identifiers)) == len(identifiers)
    assert all(identifier.version == 7 for identifier in identifiers)

    with postgres_session_factory() as session:
        with pytest.raises(DataModelError) as same_team:
            CanonicalRepository(session).create_entity(
                EntityType.FIXTURE,
                competition_id=graph.competition,
                season_id=graph.season,
                home_team_id=graph.north,
                away_team_id=graph.north,
            )
        assert same_team.value.code == "DATABASE_CONSTRAINT_VIOLATION"
        session.rollback()

    with postgres_session_factory() as session:
        with pytest.raises(DataModelError) as invalid_dates:
            CanonicalRepository(session).create_entity(
                EntityType.SEASON,
                competition_id=graph.competition,
                season_code="invalid",
                starts_on=date(2027, 1, 1),
                ends_on=date(2026, 1, 1),
            )
        assert invalid_dates.value.code == "DATABASE_CONSTRAINT_VIOLATION"
        session.rollback()

    for attributes in (
        {"number": 0, "status": "DRAFT"},
        {"number": 3, "status": "INVALID"},
    ):
        with postgres_session_factory() as session:
            with pytest.raises(DataModelError) as invalid_gameweek:
                CanonicalRepository(session).create_entity(
                    EntityType.GAMEWEEK,
                    season_id=graph.season,
                    display_name="Invalid",
                    official_deadline_at=None,
                    **attributes,
                )
            assert invalid_gameweek.value.code == "DATABASE_CONSTRAINT_VIOLATION"
            session.rollback()


def test_adjacent_memberships_and_exact_boundary_queries(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _graph(postgres_session_factory)
    boundary = datetime(2026, 8, 1, tzinfo=UTC)
    with postgres_session_factory() as session:
        repository = PlayerMembershipRepository(session)
        north_version = repository.add_version(
            player_id=graph.player,
            team_id=graph.north,
            season_id=graph.season,
            registration_type=RegistrationType.PERMANENT,
            squad_status=SquadStatus.REGISTERED,
            valid_range=TemporalRange(start=VALID_START, end=boundary),
            known_at=SEED_KNOWN,
        )
        south_version = repository.add_version(
            player_id=graph.player,
            team_id=graph.south,
            season_id=graph.season,
            registration_type=RegistrationType.PERMANENT,
            squad_status=SquadStatus.REGISTERED,
            valid_range=TemporalRange(start=boundary),
            known_at=SEED_KNOWN,
        )
        commit_session(session)

    with postgres_session_factory() as session:
        repository = PlayerMembershipRepository(session)
        before = repository.get_as_of(
            graph.player,
            RegistrationType.PERMANENT,
            AsOfScope(
                valid_at=boundary - timedelta(microseconds=1),
                known_at=datetime(2026, 7, 15, tzinfo=UTC),
            ),
        )
        at = repository.get_as_of(
            graph.player,
            RegistrationType.PERMANENT,
            AsOfScope(valid_at=boundary, known_at=datetime(2026, 7, 15, tzinfo=UTC)),
        )
        assert before["fact_version_id"] == str(north_version)
        assert at["fact_version_id"] == str(south_version)


def test_overlap_wrong_type_invalid_range_and_double_supersession_are_typed(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _graph(postgres_session_factory)
    with postgres_session_factory() as session:
        memberships = PlayerMembershipRepository(session)
        memberships.add_version(
            player_id=graph.player,
            team_id=graph.north,
            season_id=graph.season,
            registration_type=RegistrationType.PERMANENT,
            squad_status=SquadStatus.REGISTERED,
            valid_range=TemporalRange(start=VALID_START),
            known_at=SEED_KNOWN,
        )
        with pytest.raises(DataModelError) as overlap:
            memberships.add_version(
                player_id=graph.player,
                team_id=graph.south,
                season_id=graph.season,
                registration_type=RegistrationType.PERMANENT,
                squad_status=SquadStatus.REGISTERED,
                valid_range=TemporalRange(start=datetime(2026, 7, 2, tzinfo=UTC)),
                known_at=SEED_KNOWN,
            )
        assert overlap.value.code == "TEMPORAL_OVERLAP"
        session.rollback()

    with postgres_session_factory() as session:
        wrong_type_id = session.execute(
            insert(canonical_entity)
            .values(entity_type=EntityType.PLAYER.value)
            .returning(canonical_entity.c.entity_id)
        ).scalar_one()
        with pytest.raises(DBAPIError) as wrong_type:
            session.execute(
                insert(team).values(
                    team_id=wrong_type_id,
                    entity_type=EntityType.TEAM.value,
                    canonical_name="Wrong",
                )
            )
        assert translate_database_error(wrong_type.value).code == "ENTITY_TYPE_MISMATCH"
        session.rollback()

    with postgres_session_factory() as session:
        with pytest.raises(DBAPIError) as invalid_range:
            session.execute(
                insert(player_team_membership).values(
                    player_id=graph.player,
                    team_id=graph.north,
                    season_id=graph.season,
                    registration_type=RegistrationType.PERMANENT.value,
                    squad_status=SquadStatus.REGISTERED.value,
                    valid_during=Range(VALID_START, None, bounds="(]"),
                    system_during=Range(SEED_KNOWN, None, bounds="[)"),
                )
            )
        assert translate_database_error(invalid_range.value).code == "TEMPORAL_RANGE_INVALID"
        session.rollback()

    with postgres_session_factory() as session:
        with pytest.raises(DBAPIError) as infinite_start:
            session.execute(
                text(
                    "INSERT INTO football.player_team_membership "
                    "(player_id,team_id,season_id,registration_type,squad_status,"
                    "valid_during,system_during) VALUES "
                    "(:player,:team,:season,'PERMANENT','REGISTERED',"
                    "tstzrange('-infinity'::timestamptz,NULL,'[)'),"
                    "tstzrange(:known,NULL,'[)'))"
                ),
                {
                    "known": SEED_KNOWN,
                    "player": graph.player,
                    "season": graph.season,
                    "team": graph.north,
                },
            )
        assert translate_database_error(infinite_start.value).code == "TEMPORAL_RANGE_INVALID"
        session.rollback()

    with postgres_session_factory() as session:
        with pytest.raises(DBAPIError) as empty_range:
            session.execute(
                text(
                    "INSERT INTO football.player_team_membership "
                    "(player_id,team_id,season_id,registration_type,squad_status,"
                    "valid_during,system_during) VALUES "
                    "(:player,:team,:season,'PERMANENT','REGISTERED','empty'::tstzrange,"
                    "tstzrange(:known,NULL,'[)'))"
                ),
                {
                    "known": SEED_KNOWN,
                    "player": graph.player,
                    "season": graph.season,
                    "team": graph.north,
                },
            )
        assert translate_database_error(empty_range.value).code == "TEMPORAL_RANGE_INVALID"
        session.rollback()

    with postgres_session_factory() as session:
        fixtures = FixtureRepository(session)
        first = fixtures.add_revision(
            fixture_id=graph.fixture,
            revision_number=1,
            kickoff_at=datetime(2026, 8, 21, 19, tzinfo=UTC),
            fixture_status=FixtureStatus.SCHEDULED,
            valid_range=TemporalRange(start=VALID_START),
            known_at=SEED_KNOWN,
            observed_at=SEED_KNOWN,
            source_snapshot_id=graph.snapshot_one,
        )
        fixtures.revise(
            first,
            revision_number=2,
            kickoff_at=datetime(2026, 8, 22, 14, tzinfo=UTC),
            fixture_status=FixtureStatus.SCHEDULED,
            valid_range=TemporalRange(start=VALID_START),
            known_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
            observed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
            source_snapshot_id=graph.snapshot_two,
        )
        with pytest.raises(DataModelError) as double:
            fixtures.revise(
                first,
                revision_number=3,
                kickoff_at=None,
                fixture_status=FixtureStatus.POSTPONED,
                valid_range=TemporalRange(start=VALID_START),
                known_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
                observed_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
                source_snapshot_id=graph.snapshot_one,
            )
        assert double.value.code == "TEMPORAL_SUPERSESSION_CONFLICT"


def test_assignment_overlap_and_temporal_trigger_reject_unauthorized_changes(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _graph(postgres_session_factory)
    with postgres_session_factory() as session:
        fixtures = FixtureRepository(session)
        fixtures.assign_gameweek(
            fixture_id=graph.fixture,
            gameweek_id=graph.gameweek_one,
            assignment_status=AssignmentStatus.ASSIGNED,
            valid_range=TemporalRange(start=VALID_START),
            known_at=SEED_KNOWN,
            source_snapshot_id=graph.snapshot_one,
        )
        with pytest.raises(DataModelError) as overlap:
            fixtures.assign_gameweek(
                fixture_id=graph.fixture,
                gameweek_id=graph.gameweek_two,
                assignment_status=AssignmentStatus.ASSIGNED,
                valid_range=TemporalRange(start=VALID_START),
                known_at=SEED_KNOWN,
                source_snapshot_id=graph.snapshot_one,
            )
        assert overlap.value.code == "TEMPORAL_OVERLAP"
        session.rollback()

    with postgres_session_factory() as session:
        revision = FixtureRepository(session).add_revision(
            fixture_id=graph.fixture,
            revision_number=1,
            kickoff_at=datetime(2026, 8, 21, 19, tzinfo=UTC),
            fixture_status=FixtureStatus.SCHEDULED,
            valid_range=TemporalRange(start=VALID_START),
            known_at=SEED_KNOWN,
            observed_at=SEED_KNOWN,
            source_snapshot_id=graph.snapshot_one,
        )
        commit_session(session)

    statements = (
        update(fixture_revision)
        .where(fixture_revision.c.fixture_revision_id == revision)
        .values(venue="unauthorized"),
        update(fixture_revision)
        .where(fixture_revision.c.fixture_revision_id == revision)
        .values(system_during=Range(SEED_KNOWN, SEED_KNOWN + timedelta(days=1), bounds="[)")),
        delete(fixture_revision).where(fixture_revision.c.fixture_revision_id == revision),
    )
    expected_codes = ("IMMUTABLE_RECORD", "TEMPORAL_SUPERSESSION_CONFLICT", "IMMUTABLE_RECORD")
    for statement, expected_code in zip(statements, expected_codes, strict=True):
        with postgres_session_factory() as session:
            with pytest.raises(DBAPIError) as rejected:
                session.execute(statement)
            assert translate_database_error(rejected.value).code == expected_code
            session.rollback()


def test_assignment_supersession_rejects_fixture_lineage_mismatch(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _graph(postgres_session_factory)
    with postgres_session_factory() as session:
        other_fixture = CanonicalRepository(session).create_entity(
            EntityType.FIXTURE,
            competition_id=graph.competition,
            season_id=graph.season,
            home_team_id=graph.south,
            away_team_id=graph.north,
        )
        original = FixtureRepository(session).assign_gameweek(
            fixture_id=graph.fixture,
            gameweek_id=graph.gameweek_one,
            assignment_status=AssignmentStatus.ASSIGNED,
            valid_range=TemporalRange(start=VALID_START),
            known_at=SEED_KNOWN,
            source_snapshot_id=graph.snapshot_one,
        )
        commit_session(session)

    with postgres_session_factory() as session:
        with pytest.raises(DataModelError) as mismatch:
            FixtureRepository(session).assign_gameweek(
                fixture_id=other_fixture,
                gameweek_id=graph.gameweek_two,
                assignment_status=AssignmentStatus.ASSIGNED,
                valid_range=TemporalRange(start=VALID_START),
                known_at=SEED_KNOWN + timedelta(hours=2),
                source_snapshot_id=graph.snapshot_two,
                supersedes=original,
            )
        assert mismatch.value.code == "TEMPORAL_SUPERSESSION_CONFLICT"
        session.rollback()


def test_rules_registry_rows_are_immutable_and_foreign_keys_restrict_deletion(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _graph(postgres_session_factory)
    with postgres_session_factory() as session:
        artifact_id = session.execute(
            insert(ruleset_artifact)
            .values(
                ruleset_id="synthetic-rules",
                ruleset_version="1.0",
                schema_version="1.0",
                source_ruleset_hash="a" * 64,
                artifact_uri="artifact://synthetic",
                artifact_sha256="b" * 64,
                ruleset_status="ACTIVE",
                registered_at=SEED_KNOWN,
            )
            .returning(ruleset_artifact.c.ruleset_artifact_id)
        ).scalar_one()
        activation_id = session.execute(
            insert(ruleset_activation)
            .values(
                ruleset_artifact_id=artifact_id,
                active_ruleset_hash="c" * 64,
                approval_sha256="d" * 64,
                activation_manifest_sha256="e" * 64,
                approval_uri="artifact://approval",
                activation_manifest_uri="artifact://manifest",
                approved_by="test-suite",
                approved_at=SEED_KNOWN,
                activated_at=SEED_KNOWN,
            )
            .returning(ruleset_activation.c.ruleset_activation_id)
        ).scalar_one()
        commit_session(session)

    for statement in (
        update(ruleset_artifact)
        .where(ruleset_artifact.c.ruleset_artifact_id == artifact_id)
        .values(ruleset_status="VERIFIED"),
        delete(ruleset_artifact).where(ruleset_artifact.c.ruleset_artifact_id == artifact_id),
        update(ruleset_activation)
        .where(ruleset_activation.c.ruleset_activation_id == activation_id)
        .values(approved_by="changed"),
        delete(ruleset_activation).where(
            ruleset_activation.c.ruleset_activation_id == activation_id
        ),
    ):
        with postgres_session_factory() as session:
            with pytest.raises(DBAPIError) as immutable:
                session.execute(statement)
            assert translate_database_error(immutable.value).code == "IMMUTABLE_RECORD"
            session.rollback()

    with postgres_session_factory() as session:
        with pytest.raises(DBAPIError) as restricted:
            session.execute(
                delete(canonical_entity).where(canonical_entity.c.entity_id == graph.north)
            )
        assert translate_database_error(restricted.value).code == "DATABASE_CONSTRAINT_VIOLATION"
        session.rollback()


def test_raw_dedup_snapshots_immutability_and_tombstone_view(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _graph(postgres_session_factory)
    body = b'{"synthetic":true}'
    body_hash = hashlib.sha256(body).hexdigest()
    with postgres_session_factory() as session:
        sources = SourceObservationRepository(session)
        with pytest.raises(DataModelError) as forbidden:
            sources.get_or_create_raw_blob(
                body,
                storage_policy="FORBIDDEN",
                content_type="application/json",
                storage_uri="file:///forbidden",
            )
        assert forbidden.value.code == "RAW_STORAGE_FORBIDDEN"
        with pytest.raises(DataModelError) as deleted_policy:
            sources.get_or_create_raw_blob(
                body, storage_policy="DELETED", content_type="application/json"
            )
        assert deleted_policy.value.code == "RAW_BLOB_DELETED"
        raw_id = sources.get_or_create_raw_blob(
            body, storage_policy="ALLOWED", content_type="application/json"
        )
        assert raw_id == sources.get_or_create_raw_blob(
            body, storage_policy="ALLOWED", content_type="application/json"
        )
        with pytest.raises(DataModelError) as metadata_mismatch:
            sources.get_or_create_raw_blob(
                body, storage_policy="ALLOWED", content_type="text/plain"
            )
        assert metadata_mismatch.value.code == "IMMUTABLE_RECORD"
        first = sources.record_source_snapshot(
            provider_id=graph.provider,
            resource="synthetic",
            request_fingerprint="1" * 64,
            request_started_at=SEED_KNOWN,
            received_at=SEED_KNOWN,
            usable_at=SEED_KNOWN,
            raw_blob_id=raw_id,
            raw_storage_policy="ALLOWED",
            body_sha256=body_hash,
            rights_profile_key="RP-SYNTHETIC",
            validation_status="USABLE",
            dataset_mode="RAW_OBSERVED",
        )
        second = sources.record_source_snapshot(
            provider_id=graph.provider,
            resource="synthetic",
            request_fingerprint="2" * 64,
            request_started_at=SEED_KNOWN,
            received_at=SEED_KNOWN,
            usable_at=SEED_KNOWN,
            raw_blob_id=raw_id,
            raw_storage_policy="ALLOWED",
            body_sha256=body_hash,
            rights_profile_key="RP-SYNTHETIC",
            validation_status="USABLE",
            dataset_mode="RAW_OBSERVED",
        )
        assert first != second
        commit_session(session)

    with postgres_session_factory() as session:
        with pytest.raises(DataModelError) as mismatched:
            SourceObservationRepository(session).record_source_snapshot(
                provider_id=graph.provider,
                resource="synthetic",
                request_fingerprint="3" * 64,
                request_started_at=SEED_KNOWN,
                received_at=SEED_KNOWN,
                usable_at=SEED_KNOWN,
                raw_blob_id=raw_id,
                raw_storage_policy="ALLOWED",
                body_sha256="f" * 64,
                rights_profile_key="RP-SYNTHETIC",
                validation_status="USABLE",
                dataset_mode="RAW_OBSERVED",
            )
        assert mismatched.value.code == "PROVENANCE_INTEGRITY"
        session.rollback()

    with postgres_session_factory() as session:
        with pytest.raises(DBAPIError):
            session.execute(
                insert(raw_blob).values(
                    body_sha256="a" * 64,
                    byte_size=1,
                    storage_policy="FORBIDDEN",
                    storage_uri="file:///forbidden",
                )
            )
        session.rollback()

    for statement in (
        update(raw_blob).where(raw_blob.c.raw_blob_id == raw_id).values(content_type="text/plain"),
        delete(raw_blob).where(raw_blob.c.raw_blob_id == raw_id),
        update(source_snapshot)
        .where(source_snapshot.c.source_snapshot_id == first)
        .values(resource="changed"),
        delete(source_snapshot).where(source_snapshot.c.source_snapshot_id == second),
    ):
        with postgres_session_factory() as session:
            with pytest.raises(DBAPIError) as immutable:
                session.execute(statement)
            assert translate_database_error(immutable.value).code == "IMMUTABLE_RECORD"
            session.rollback()

    with postgres_session_factory() as session:
        deletion_id = session.execute(
            insert(raw_blob_deletion)
            .values(
                raw_blob_id=raw_id,
                deleted_at=SEED_KNOWN + timedelta(days=1),
                reason="synthetic retention test",
                tombstone_sha256="d" * 64,
                approved_by="test-suite",
            )
            .returning(raw_blob_deletion.c.deletion_id)
        ).scalar_one()
        commit_session(session)

    with postgres_session_factory() as session:
        assert (
            session.execute(text("SELECT count(*) FROM provenance.available_raw_blob")).scalar_one()
            == 0
        )
        sources = SourceObservationRepository(session)
        with pytest.raises(DataModelError) as tombstoned_dedup:
            sources.get_or_create_raw_blob(
                body, storage_policy="ALLOWED", content_type="application/json"
            )
        assert tombstoned_dedup.value.code == "RAW_BLOB_DELETED"
        with pytest.raises(DataModelError) as tombstoned_snapshot:
            sources.record_source_snapshot(
                provider_id=graph.provider,
                resource="synthetic",
                request_fingerprint="4" * 64,
                request_started_at=SEED_KNOWN,
                received_at=SEED_KNOWN,
                usable_at=SEED_KNOWN,
                raw_blob_id=raw_id,
                raw_storage_policy="ALLOWED",
                body_sha256=body_hash,
                rights_profile_key="RP-SYNTHETIC",
                validation_status="USABLE",
                dataset_mode="RAW_OBSERVED",
            )
        assert tombstoned_snapshot.value.code == "RAW_BLOB_DELETED"
        session.rollback()

    for statement in (
        update(raw_blob_deletion)
        .where(raw_blob_deletion.c.deletion_id == deletion_id)
        .values(reason="changed"),
        delete(raw_blob_deletion).where(raw_blob_deletion.c.deletion_id == deletion_id),
    ):
        with postgres_session_factory() as session:
            with pytest.raises(DBAPIError) as immutable:
                session.execute(statement)
            assert translate_database_error(immutable.value).code == "IMMUTABLE_RECORD"
            session.rollback()


@pytest.mark.parametrize(
    ("validation_status", "usable_at"),
    [("QUARANTINED", SEED_KNOWN), ("USABLE", None)],
)
def test_source_snapshot_usable_time_exactly_tracks_eligibility(
    postgres_session_factory: sessionmaker[Session],
    validation_status: str,
    usable_at: datetime | None,
) -> None:
    graph = _graph(postgres_session_factory)
    values = {
        "provider_id": graph.provider,
        "resource": "eligibility-invariant",
        "request_fingerprint": hashlib.sha256(validation_status.encode()).hexdigest(),
        "request_started_at": SEED_KNOWN,
        "received_at": SEED_KNOWN,
        "usable_at": usable_at,
        "raw_blob_id": None,
        "raw_storage_policy": "FORBIDDEN",
        "body_sha256": None,
        "rights_profile_key": "RP-SYNTHETIC",
        "validation_status": validation_status,
        "dataset_mode": "RAW_OBSERVED",
    }
    with postgres_session_factory() as session:
        with pytest.raises(DataModelError) as repository_error:
            SourceObservationRepository(session).record_source_snapshot(**values)
        assert repository_error.value.code == "PROVENANCE_INTEGRITY"
        session.rollback()

    with postgres_session_factory() as session:
        with pytest.raises(DBAPIError) as database_error:
            session.execute(insert(source_snapshot).values(**values))
        assert (
            translate_database_error(database_error.value).code == "DATABASE_CONSTRAINT_VIOLATION"
        )
        session.rollback()


def test_repository_optional_provenance_filters_and_failure_paths(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _graph(postgres_session_factory)
    established = SEED_KNOWN + timedelta(hours=2)
    valid = TemporalRange(start=VALID_START)
    with postgres_session_factory() as session:
        external = ExternalIdentifierRepository(session)
        external_id = external.add_version(
            canonical_entity_id=graph.player,
            provider_id=graph.provider,
            provider_product="contract-oracle",
            identifier_namespace="test.player.contract",
            entity_type=EntityType.PLAYER,
            external_id_text="player-contract",
            valid_range=valid,
            known_at=established,
            mapping_status=MappingStatus.HUMAN_VERIFIED,
            mapping_method=MappingMethod.MANUAL,
            first_seen_at=established,
            last_seen_at=established,
            evidence_source_snapshot_id=graph.snapshot_two,
        )
        membership_id = PlayerMembershipRepository(session).add_version(
            player_id=graph.player,
            team_id=graph.north,
            season_id=graph.season,
            registration_type=RegistrationType.PERMANENT,
            squad_status=SquadStatus.REGISTERED,
            valid_range=valid,
            known_at=established,
            source_snapshot_id=graph.snapshot_two,
        )
        fixtures = FixtureRepository(session)
        revision_id = fixtures.add_revision(
            fixture_id=graph.fixture,
            revision_number=1,
            kickoff_at=None,
            fixture_status=FixtureStatus.SCHEDULED,
            valid_range=valid,
            known_at=established,
            observed_at=established,
            source_snapshot_id=None,
        )
        assignment_id = fixtures.assign_gameweek(
            fixture_id=graph.fixture,
            gameweek_id=graph.gameweek_one,
            assignment_status=AssignmentStatus.ASSIGNED,
            valid_range=valid,
            known_at=established,
            source_snapshot_id=None,
        )
        commit_session(session)

    scope = AsOfScope(valid_at=VALID_START, known_at=established)
    before_valid = AsOfScope(valid_at=VALID_START - timedelta(microseconds=1), known_at=established)
    with postgres_session_factory() as session:
        external = ExternalIdentifierRepository(session)
        result = external.get_as_of(
            graph.player,
            scope,
            provider_id=graph.provider,
            provider_product="contract-oracle",
            identifier_namespace="test.player.contract",
        )
        assert result["fact_version_id"] == str(external_id)
        with pytest.raises(DataModelError) as filtered:
            external.get_as_of(
                graph.player,
                scope,
                provider_product="contract-oracle",
                identifier_namespace="wrong.namespace",
            )
        assert filtered.value.code == "AS_OF_NOT_FOUND"

        with pytest.raises(DataModelError) as membership_absent:
            PlayerMembershipRepository(session).get_as_of(
                graph.player, RegistrationType.PERMANENT, before_valid
            )
        assert membership_absent.value.code == "AS_OF_NOT_FOUND"
        fixtures = FixtureRepository(session)
        with pytest.raises(DataModelError) as revision_absent:
            fixtures.get_revision_as_of(graph.fixture, before_valid)
        assert revision_absent.value.code == "AS_OF_NOT_FOUND"
        with pytest.raises(DataModelError) as assignment_absent:
            fixtures.get_gameweek_as_of(graph.fixture, before_valid)
        assert assignment_absent.value.code == "AS_OF_NOT_FOUND"

        with pytest.raises(DataModelError) as missing_correction_source:
            fixtures.assign_gameweek(
                fixture_id=graph.fixture,
                gameweek_id=graph.gameweek_two,
                assignment_status=AssignmentStatus.ASSIGNED,
                valid_range=valid,
                known_at=established + timedelta(hours=1),
                supersedes=assignment_id,
            )
        assert missing_correction_source.value.code == "PROVENANCE_INTEGRITY"

        with pytest.raises(DataModelError) as repeated_membership_source:
            PlayerMembershipRepository(session).supersede(
                membership_id,
                team_id=graph.south,
                season_id=graph.season,
                valid_range=valid,
                known_at=established + timedelta(hours=1),
                squad_status=SquadStatus.REGISTERED,
                source_snapshot_id=graph.snapshot_two,
            )
        assert repeated_membership_source.value.code == "PROVENANCE_INTEGRITY"

        with pytest.raises(DataModelError) as backdated_external:
            external.supersede(
                external_id,
                known_at=established,
                provider_product="contract-oracle",
                identifier_namespace="test.player.contract.v2",
                external_id_text="player-contract",
                valid_range=valid,
                mapping_status=MappingStatus.HUMAN_VERIFIED,
                evidence_source_snapshot_id=graph.snapshot_one,
                last_seen_at=established,
            )
        assert backdated_external.value.code == "TEMPORAL_SUPERSESSION_CONFLICT"

        with pytest.raises(DataModelError) as missing_revision_source:
            fixtures.revise(
                revision_id,
                revision_number=2,
                kickoff_at=None,
                fixture_status=FixtureStatus.SCHEDULED,
                valid_range=valid,
                known_at=established + timedelta(hours=1),
                observed_at=established + timedelta(hours=1),
                source_snapshot_id=None,
            )
        assert missing_revision_source.value.code == "PROVENANCE_INTEGRITY"

        corrected_assignment = fixtures.assign_gameweek(
            fixture_id=graph.fixture,
            gameweek_id=graph.gameweek_two,
            assignment_status=AssignmentStatus.ASSIGNED,
            valid_range=valid,
            known_at=established + timedelta(hours=1),
            source_snapshot_id=graph.snapshot_two,
            supersedes=assignment_id,
        )
        assert corrected_assignment.version == 7
        session.rollback()
