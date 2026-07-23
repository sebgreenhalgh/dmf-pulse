"""Independent-session overlap races enforced by PostgreSQL, not application timing."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier, Event
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.errors import DataModelError
from dmf_pulse.data_model.models import (
    EntityType,
    FixtureStatus,
    MappingStatus,
    RegistrationType,
    SquadStatus,
    TemporalRange,
)
from dmf_pulse.data_model.repositories import (
    CanonicalRepository,
    ExternalIdentifierRepository,
    FixtureRepository,
    PlayerMembershipRepository,
    SourceObservationRepository,
    commit_session,
)
from dmf_pulse.data_model.tables import (
    external_identifier,
    fixture_revision,
    player_team_membership,
)

pytestmark = pytest.mark.postgres


def _seed(factory: sessionmaker[Session]) -> dict[str, UUID]:
    with factory() as session:
        canonical = CanonicalRepository(session)
        competition = canonical.create_entity(
            EntityType.COMPETITION,
            competition_key="race-league",
            canonical_name="Race League",
            country_code="GB",
        )
        north = canonical.create_entity(EntityType.TEAM, canonical_name="North")
        south = canonical.create_entity(EntityType.TEAM, canonical_name="South")
        player = canonical.create_entity(EntityType.PLAYER, canonical_name="Alex")
        provider = canonical.create_entity(
            EntityType.DATA_PROVIDER,
            provider_key="race-provider",
            display_name="Race Provider",
            provider_type="MANUAL",
            rights_profile_key="synthetic-only",
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
        sources = SourceObservationRepository(session)
        snapshot_one = sources.record_source_snapshot(
            provider_id=provider,
            resource="race",
            request_fingerprint="a" * 64,
            request_started_at=datetime(2026, 7, 10, tzinfo=UTC),
            received_at=datetime(2026, 7, 10, tzinfo=UTC),
            usable_at=datetime(2026, 7, 10, tzinfo=UTC),
            raw_blob_id=None,
            raw_storage_policy="FORBIDDEN",
            body_sha256=None,
            rights_profile_key="synthetic-only",
            validation_status="USABLE",
            dataset_mode="RAW_OBSERVED",
        )
        snapshot_two = sources.record_source_snapshot(
            provider_id=provider,
            resource="race",
            request_fingerprint="b" * 64,
            request_started_at=datetime(2026, 7, 11, tzinfo=UTC),
            received_at=datetime(2026, 7, 11, tzinfo=UTC),
            usable_at=datetime(2026, 7, 11, tzinfo=UTC),
            raw_blob_id=None,
            raw_storage_policy="FORBIDDEN",
            body_sha256=None,
            rights_profile_key="synthetic-only",
            validation_status="USABLE",
            dataset_mode="RAW_OBSERVED",
        )
        commit_session(session)
    return {
        "fixture": fixture,
        "north": north,
        "player": player,
        "provider": provider,
        "season": season,
        "south": south,
        "snapshot_one": snapshot_one,
        "snapshot_two": snapshot_two,
    }


def _insert_external(session: Session, ids: dict[str, UUID], external_id: str) -> UUID:
    known = datetime(2026, 7, 10, tzinfo=UTC)
    return ExternalIdentifierRepository(session).add_version(
        canonical_entity_id=ids["player"],
        provider_id=ids["provider"],
        provider_product="fantasy",
        identifier_namespace="player",
        entity_type=EntityType.PLAYER,
        external_id_text=external_id,
        valid_range=TemporalRange(start=datetime(2026, 7, 1, tzinfo=UTC)),
        known_at=known,
        mapping_status=MappingStatus.HUMAN_VERIFIED,
        first_seen_at=known,
        last_seen_at=known,
        evidence_source_snapshot_id=ids["snapshot_one"],
    )


def test_two_overlap_races_commit_exactly_one_row(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    ids = _seed(postgres_session_factory)
    valid = TemporalRange(start=datetime(2026, 7, 1, tzinfo=UTC))
    known = datetime(2026, 7, 10, tzinfo=UTC)
    membership_barrier = Barrier(2)

    def membership_worker(team: UUID) -> str:
        with postgres_session_factory() as session:
            membership_barrier.wait(timeout=10)
            try:
                PlayerMembershipRepository(session).add_version(
                    player_id=ids["player"],
                    team_id=team,
                    season_id=ids["season"],
                    registration_type=RegistrationType.PERMANENT,
                    squad_status=SquadStatus.REGISTERED,
                    valid_range=valid,
                    known_at=known,
                )
                commit_session(session)
                return "COMMITTED"
            except DataModelError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        membership_results = list(executor.map(membership_worker, (ids["north"], ids["south"])))
    assert sorted(membership_results) == ["COMMITTED", "TEMPORAL_OVERLAP"]

    revision_barrier = Barrier(2)

    def revision_worker(number: int) -> str:
        with postgres_session_factory() as session:
            revision_barrier.wait(timeout=10)
            try:
                FixtureRepository(session).add_revision(
                    fixture_id=ids["fixture"],
                    revision_number=number,
                    kickoff_at=datetime(2026, 8, 21, 19 + number, tzinfo=UTC),
                    fixture_status=FixtureStatus.SCHEDULED,
                    valid_range=valid,
                    known_at=known,
                    observed_at=known,
                    source_snapshot_id=ids["snapshot_one"],
                )
                commit_session(session)
                return "COMMITTED"
            except DataModelError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        revision_results = list(executor.map(revision_worker, (1, 2)))
    assert sorted(revision_results) == ["COMMITTED", "TEMPORAL_OVERLAP"]

    with postgres_session_factory() as session:
        assert (
            session.execute(select(func.count()).select_from(player_team_membership)).scalar_one()
            == 1
        )
        assert session.execute(select(func.count()).select_from(fixture_revision)).scalar_one() == 1


def test_overlapping_current_accepted_external_mapping_writers_are_serialized(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    ids = _seed(postgres_session_factory)
    barrier = Barrier(2)

    def worker() -> str:
        with postgres_session_factory() as session:
            barrier.wait(timeout=10)
            try:
                _insert_external(session, ids, "player-001")
                commit_session(session)
                return "COMMITTED"
            except DataModelError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: worker(), range(2)))
    assert sorted(results) == ["COMMITTED", "TEMPORAL_OVERLAP"]
    with postgres_session_factory() as session:
        assert (
            session.execute(select(func.count()).select_from(external_identifier)).scalar_one() == 1
        )


def test_two_writers_cannot_supersede_the_same_version(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    ids = _seed(postgres_session_factory)
    with postgres_session_factory() as session:
        original = _insert_external(session, ids, "player-001")
        commit_session(session)
    barrier = Barrier(2)

    def worker(replacement: str) -> str:
        with postgres_session_factory() as session:
            barrier.wait(timeout=10)
            try:
                ExternalIdentifierRepository(session).supersede(
                    original,
                    known_at=datetime(2026, 7, 12, tzinfo=UTC),
                    provider_product="fantasy",
                    identifier_namespace="player",
                    external_id_text=replacement,
                    valid_range=TemporalRange(start=datetime(2026, 7, 1, tzinfo=UTC)),
                    mapping_status=MappingStatus.HUMAN_VERIFIED,
                    evidence_source_snapshot_id=ids["snapshot_two"],
                    last_seen_at=datetime(2026, 7, 12, tzinfo=UTC),
                )
                commit_session(session)
                return "COMMITTED"
            except DataModelError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, ("player-002", "player-003")))
    assert sorted(results) == ["COMMITTED", "TEMPORAL_SUPERSESSION_CONFLICT"]
    with postgres_session_factory() as session:
        assert (
            session.execute(select(func.count()).select_from(external_identifier)).scalar_one() == 2
        )


def test_nonconflicting_external_mapping_writers_both_commit(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    ids = _seed(postgres_session_factory)
    barrier = Barrier(2)

    def worker(external_id: str) -> str:
        with postgres_session_factory() as session:
            barrier.wait(timeout=10)
            try:
                _insert_external(session, ids, external_id)
                commit_session(session)
                return "COMMITTED"
            except DataModelError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, ("player-001", "player-002")))
    assert results == ["COMMITTED", "COMMITTED"]
    with postgres_session_factory() as session:
        assert (
            session.execute(select(func.count()).select_from(external_identifier)).scalar_one() == 2
        )


def test_rolled_back_supersession_leaves_no_partial_mutation(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    ids = _seed(postgres_session_factory)
    with postgres_session_factory() as session:
        original = _insert_external(session, ids, "player-001")
        commit_session(session)

    first_ready = Event()
    release_rollback = Event()
    second_started = Event()
    known_at = datetime(2026, 7, 12, tzinfo=UTC)

    def rollback_worker() -> UUID:
        with postgres_session_factory() as session:
            successor = ExternalIdentifierRepository(session).supersede(
                original,
                known_at=known_at,
                provider_product="fantasy",
                identifier_namespace="player",
                external_id_text="rolled-back",
                valid_range=TemporalRange(start=datetime(2026, 7, 1, tzinfo=UTC)),
                mapping_status=MappingStatus.HUMAN_VERIFIED,
                evidence_source_snapshot_id=ids["snapshot_two"],
                last_seen_at=known_at,
            )
            first_ready.set()
            assert release_rollback.wait(timeout=10)
            session.rollback()
            return successor

    def succeeding_worker() -> UUID:
        assert first_ready.wait(timeout=10)
        with postgres_session_factory() as session:
            second_started.set()
            successor = ExternalIdentifierRepository(session).supersede(
                original,
                known_at=known_at,
                provider_product="fantasy",
                identifier_namespace="player",
                external_id_text="committed",
                valid_range=TemporalRange(start=datetime(2026, 7, 1, tzinfo=UTC)),
                mapping_status=MappingStatus.HUMAN_VERIFIED,
                evidence_source_snapshot_id=ids["snapshot_two"],
                last_seen_at=known_at,
            )
            commit_session(session)
            return successor

    with ThreadPoolExecutor(max_workers=2) as executor:
        rolled_back_future = executor.submit(rollback_worker)
        assert first_ready.wait(timeout=10)
        committed_future = executor.submit(succeeding_worker)
        assert second_started.wait(timeout=10)
        release_rollback.set()
        rolled_back = rolled_back_future.result(timeout=10)
        committed = committed_future.result(timeout=10)

    assert rolled_back != committed
    with postgres_session_factory() as session:
        rows = session.execute(select(external_identifier)).mappings().all()
    assert len(rows) == 2
    assert all(row["external_identifier_id"] != rolled_back for row in rows)
    old = next(row for row in rows if row["external_identifier_id"] == original)
    assert old["superseded_by_mapping_id"] == committed
    assert old["system_during"].upper == known_at
