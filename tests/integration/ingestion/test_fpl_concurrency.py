"""Concurrent PostgreSQL proofs for ingestion mapping and resume."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from time import monotonic
from typing import Any
from uuid import uuid4

import pytest
from psycopg.types.range import Range
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    canonical_entity,
    competition,
    fixture,
    fixture_gameweek_assignment,
    fixture_observation,
    fixture_revision,
    gameweek,
    gameweek_observation,
    player,
    player_observation,
    season,
    source_bundle,
    source_bundle_member,
    source_processing_event,
    source_snapshot,
    team,
    team_observation,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl import service as service_module
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    FplIngestionService,
    FplOperationOutcome,
    FplReplayRequest,
    IngestionInterrupted,
)
from dmf_pulse.ingestion.repository import (
    append_processing_event_idempotent,
    received_context,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _count(session: Session, table: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def _happy_request(repository_root: Path) -> FplReplayRequest:
    return FplReplayRequest(
        fixture_set=repository_root / "fixtures" / "fpl" / "FPL-004",
        scenario="happy_path",
        database_url_ref=DATABASE_REF,
    )


def test_concurrent_imports_reuse_canonical_identity_and_bundle(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    request = _happy_request(repository_root)
    ready = Barrier(2)

    def ingest() -> FplOperationOutcome:
        ready.wait(timeout=10)
        return FplIngestionService(repository_root=repository_root).replay(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ingest) for _index in range(2)]
        outcomes = tuple(future.result(timeout=30) for future in futures)

    assert {outcome.exit_code for outcome in outcomes} == {0}
    bundles = tuple(outcome.result.source_bundle for outcome in outcomes)
    assert all(bundle is not None for bundle in bundles)
    assert len({bundle.bundle_id for bundle in bundles if bundle is not None}) == 2
    assert len({bundle.semantic_sha256 for bundle in bundles if bundle is not None}) == 1
    with postgres_session_factory() as session:
        assert _count(session, source_snapshot) == 4
        assert _count(session, competition) == 1
        assert _count(session, team) == 2
        assert _count(session, player) == 4
        assert _count(session, gameweek) == 2
        assert _count(session, fixture) == 1
        assert _count(session, source_bundle) == 2
        assert _count(session, source_bundle_member) == 4
        assert (
            session.scalar(
                select(func.count())
                .select_from(source_processing_event)
                .where(source_processing_event.c.stage == "USABLE")
            )
            == 4
        )


def test_concurrent_resume_records_each_stage_once_and_promotes_once(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    interrupted_request = FplReplayRequest(
        fixture_set=repository_root / "fixtures" / "fpl" / "FPL-004",
        scenario="happy_path",
        database_url_ref=DATABASE_REF,
        halt_after_stage="MAPPED",
    )
    service = FplIngestionService(repository_root=repository_root)
    with pytest.raises(IngestionInterrupted) as caught:
        service.replay(interrupted_request)
    snapshot_id = caught.value.snapshot_ids[0]
    ready = Barrier(2)

    def resume() -> FplOperationOutcome:
        ready.wait(timeout=10)
        return FplIngestionService(repository_root=repository_root).resume(
            snapshot_id, database_url_ref=DATABASE_REF
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(resume) for _index in range(2)]
        outcomes = tuple(future.result(timeout=30) for future in futures)

    bundles = tuple(outcome.result.source_bundle for outcome in outcomes)
    assert {outcome.exit_code for outcome in outcomes} == {0}
    assert len({bundle.bundle_id for bundle in bundles if bundle is not None}) == 1
    with postgres_session_factory() as session:
        for paired_snapshot_id in caught.value.snapshot_ids:
            rows = session.execute(
                select(
                    source_processing_event.c.sequence_number,
                    source_processing_event.c.stage,
                )
                .where(source_processing_event.c.source_snapshot_id == paired_snapshot_id)
                .order_by(source_processing_event.c.sequence_number)
            ).all()
            assert tuple(row.sequence_number for row in rows) == tuple(range(1, 9))
            assert tuple(row.stage for row in rows) == (
                "RECEIVED",
                "STORED",
                "PARSED",
                "VALIDATED",
                "MAPPED",
                "PROMOTED",
                "QUALITY_PASSED",
                "USABLE",
            )
        assert _count(session, source_snapshot) == 2
        assert _count(session, player) == 4
        assert _count(session, fixture) == 1
        assert _count(session, source_bundle) == 1
        assert _count(session, source_bundle_member) == 2


def test_changed_observation_races_unchanged_replay_without_stale_supersession(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    fixture_set = repository_root / "fixtures/fpl/FPL-004"

    def late_clock() -> datetime:
        return datetime(2027, 1, 1, tzinfo=UTC)

    service = FplIngestionService(repository_root=repository_root, clock=late_clock)
    information_cutoff = datetime(2027, 1, 2, tzinfo=UTC)
    initial = service.replay(
        FplReplayRequest(
            fixture_set=fixture_set,
            scenario="happy_path",
            information_cutoff=information_cutoff,
            database_url_ref=DATABASE_REF,
        )
    )
    assert initial.result.source_bundle is not None
    ready = Barrier(2)

    def replay(scenario: str) -> FplOperationOutcome:
        ready.wait(timeout=10)
        return FplIngestionService(repository_root=repository_root, clock=late_clock).replay(
            FplReplayRequest(
                fixture_set=fixture_set,
                scenario=scenario,
                information_cutoff=information_cutoff,
                database_url_ref=DATABASE_REF,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(replay, scenario) for scenario in ("changed", "happy")]
        changed, unchanged = (future.result(timeout=30) for future in futures)

    assert changed.exit_code == unchanged.exit_code == 0
    assert changed.result.source_bundle is not None
    assert unchanged.result.source_bundle is not None
    assert unchanged.result.source_bundle.bundle_id != initial.result.source_bundle.bundle_id
    assert (
        unchanged.result.source_bundle.semantic_sha256
        == initial.result.source_bundle.semantic_sha256
    )
    assert (
        changed.result.source_bundle.semantic_sha256 != initial.result.source_bundle.semantic_sha256
    )
    with postgres_session_factory() as session:
        assert _count(session, team_observation) == 2
        assert _count(session, player_observation) == 5
        assert _count(session, gameweek_observation) == 3
        assert _count(session, fixture_observation) == 2
        assert _count(session, fixture_revision) == 2
        assert _count(session, fixture_gameweek_assignment) == 2
        current_prices = sorted(
            session.scalars(text("SELECT price_tenths FROM fpl.current_player_observation"))
        )
        assert current_prices == [50, 56, 75, 80]
        current_revision = session.execute(
            select(fixture_revision.c.revision_number, fixture_revision.c.kickoff_at).where(
                func.upper_inf(fixture_revision.c.system_during)
            )
        ).one()
        assert current_revision.revision_number == 2
        assert current_revision.kickoff_at is not None
        assert current_revision.kickoff_at.minute == 30


def test_bundle_freeze_race_excludes_post_cutoff_snapshots(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    fixture_set = repository_root / "fixtures/fpl/FPL-004"
    ready = Barrier(2)

    def replay(scenario: str) -> FplOperationOutcome:
        ready.wait(timeout=10)
        return FplIngestionService(repository_root=repository_root).replay(
            FplReplayRequest(
                fixture_set=fixture_set,
                scenario=scenario,
                database_url_ref=DATABASE_REF,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(replay, scenario) for scenario in ("happy_path", "post_cutoff")]
        outcomes = tuple(future.result(timeout=30) for future in futures)

    eligible = next(outcome for outcome in outcomes if outcome.exit_code == 0)
    post_cutoff = next(outcome for outcome in outcomes if outcome.exit_code == 2)
    assert eligible.result.source_bundle is not None
    assert post_cutoff.result.source_bundle is None
    post_cutoff_ids = {resource.source_snapshot_id for resource in post_cutoff.result.resources}
    with postgres_session_factory() as session:
        assert _count(session, source_bundle) == 1
        members = set(session.scalars(select(source_bundle_member.c.source_snapshot_id)))
        assert len(members) == 2
        assert members.isdisjoint(post_cutoff_ids)


def test_conflicting_fixture_gameweek_season_insert_is_typed_under_concurrency(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    outcome = FplIngestionService(repository_root=repository_root).replay(
        _happy_request(repository_root)
    )
    assert outcome.result.source_bundle is not None
    new_fixture_id = uuid4()
    other_season_id = uuid4()
    other_gameweek_id = uuid4()
    with postgres_session_factory.begin() as session:
        source_fixture = session.execute(
            select(
                fixture.c.competition_id,
                fixture.c.season_id,
                fixture.c.home_team_id,
                fixture.c.away_team_id,
            ).limit(1)
        ).one()
        valid_gameweek_id = session.scalar(
            select(gameweek.c.gameweek_id)
            .where(gameweek.c.season_id == source_fixture.season_id)
            .limit(1)
        )
        assert valid_gameweek_id is not None
        session.execute(
            insert(canonical_entity),
            [
                {"entity_id": new_fixture_id, "entity_type": "FIXTURE"},
                {"entity_id": other_season_id, "entity_type": "SEASON"},
                {"entity_id": other_gameweek_id, "entity_type": "GAMEWEEK"},
            ],
        )
        session.execute(
            insert(season).values(
                season_id=other_season_id,
                competition_id=source_fixture.competition_id,
                season_code="2027/28",
                starts_on=date(2027, 8, 1),
                ends_on=date(2028, 5, 31),
            )
        )
        session.execute(
            insert(gameweek).values(
                gameweek_id=other_gameweek_id,
                season_id=other_season_id,
                number=1,
                display_name="Other season Gameweek 1",
                status="OPEN",
            )
        )
        session.execute(
            insert(fixture).values(
                fixture_id=new_fixture_id,
                competition_id=source_fixture.competition_id,
                season_id=source_fixture.season_id,
                home_team_id=source_fixture.home_team_id,
                away_team_id=source_fixture.away_team_id,
            )
        )
        original_season_id = source_fixture.season_id

    ready = Barrier(2)

    def assign(gameweek_id: object) -> str | IngestionError:
        try:
            with postgres_session_factory.begin() as session:
                ready.wait(timeout=10)
                session.execute(
                    insert(fixture_gameweek_assignment).values(
                        fixture_id=new_fixture_id,
                        gameweek_id=gameweek_id,
                        assignment_status="ASSIGNED",
                        valid_during=Range(
                            datetime(2026, 8, 29, 16, 30, tzinfo=UTC),
                            datetime(2026, 8, 29, 18, 30, tzinfo=UTC),
                            bounds="[)",
                        ),
                        system_during=Range(
                            datetime(2026, 8, 21, 17, 0, tzinfo=UTC),
                            None,
                            bounds="[)",
                        ),
                        season_id=original_season_id,
                    )
                )
            return "PASS"
        except SQLAlchemyError as exc:
            return service_module._database_error(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(assign, gameweek_id)
            for gameweek_id in (valid_gameweek_id, other_gameweek_id)
        ]
        results = tuple(future.result(timeout=30) for future in futures)

    assert results.count("PASS") == 1
    failure = next(result for result in results if isinstance(result, IngestionError))
    assert failure.code == "DATABASE_CONSTRAINT"
    assert failure.retryable is False
    with postgres_session_factory() as session:
        assignments = session.execute(
            select(
                fixture_gameweek_assignment.c.gameweek_id,
                fixture_gameweek_assignment.c.season_id,
            ).where(fixture_gameweek_assignment.c.fixture_id == new_fixture_id)
        ).all()
        assert assignments == [(valid_gameweek_id, original_season_id)]


def test_stale_worker_cannot_append_out_of_order_lifecycle_event(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    request = FplReplayRequest(
        fixture_set=repository_root / "fixtures/fpl/FPL-004",
        scenario="happy_path",
        database_url_ref=DATABASE_REF,
        halt_after_stage="PARSED",
    )
    with pytest.raises(IngestionInterrupted) as caught:
        FplIngestionService(repository_root=repository_root).replay(request)
    snapshot_id = caught.value.snapshot_ids[0]
    with postgres_session_factory() as session:
        predecessor = session.execute(
            select(
                source_processing_event.c.processing_event_id,
                source_processing_event.c.event_at,
            ).where(
                source_processing_event.c.source_snapshot_id == snapshot_id,
                source_processing_event.c.stage == "PARSED",
            )
        ).one()
    ready = Barrier(2)

    def append_valid() -> str:
        with postgres_session_factory.begin() as session:
            ready.wait(timeout=10)
            append_processing_event_idempotent(
                session,
                snapshot_id=snapshot_id,
                stage="VALIDATED",
                event_at=predecessor.event_at + timedelta(microseconds=1),
                input_sha256="a" * 64,
                output_sha256="b" * 64,
                safe_details={"contract": "fpl-reference-v1"},
            )
        return "PASS"

    def append_stale() -> IngestionError:
        try:
            with postgres_session_factory.begin() as session:
                ready.wait(timeout=10)
                session.execute(
                    insert(source_processing_event).values(
                        source_snapshot_id=snapshot_id,
                        operation_id=uuid4(),
                        previous_event_id=predecessor.processing_event_id,
                        sequence_number=4,
                        stage="MAPPED",
                        outcome="SUCCEEDED",
                        event_at=predecessor.event_at + timedelta(microseconds=1),
                        stage_version="fpl-reference-v1",
                        event_sha256="c" * 64,
                        safe_details={},
                        actor="stale-worker-test",
                    )
                )
        except SQLAlchemyError as exc:
            return service_module._database_error(exc)
        raise AssertionError("stale lifecycle event was accepted")

    with ThreadPoolExecutor(max_workers=2) as executor:
        valid_future = executor.submit(append_valid)
        stale_future = executor.submit(append_stale)
        assert valid_future.result(timeout=15) == "PASS"
        failure = stale_future.result(timeout=15)
    assert failure.code == "DATABASE_CONSTRAINT"
    with postgres_session_factory() as session:
        assert tuple(
            session.scalars(
                select(source_processing_event.c.stage)
                .where(source_processing_event.c.source_snapshot_id == snapshot_id)
                .order_by(source_processing_event.c.sequence_number)
            )
        ) == ("RECEIVED", "STORED", "PARSED", "VALIDATED")


def test_held_pair_lock_fails_retryably_with_bounded_timeout(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    request = FplReplayRequest(
        fixture_set=repository_root / "fixtures/fpl/FPL-004",
        scenario="happy_path",
        database_url_ref=DATABASE_REF,
        halt_after_stage="MAPPED",
    )
    service = FplIngestionService(repository_root=repository_root)
    with pytest.raises(IngestionInterrupted) as caught:
        service.replay(request)
    with postgres_session_factory() as session:
        pair_key = received_context(session, caught.value.snapshot_ids[0])["pair_key"]
    assert isinstance(pair_key, str)
    acquired = Event()
    release = Event()

    def hold_pair_lock() -> None:
        with postgres_session_factory.begin() as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": f"fpl-pair:{pair_key}"},
            )
            acquired.set()
            assert release.wait(timeout=20)

    with ThreadPoolExecutor(max_workers=1) as executor:
        holder = executor.submit(hold_pair_lock)
        assert acquired.wait(timeout=5)
        started = monotonic()
        try:
            with pytest.raises(IngestionError) as raised:
                service.resume(caught.value.snapshot_ids[0], database_url_ref=DATABASE_REF)
        finally:
            release.set()
        holder.result(timeout=5)
    elapsed = monotonic() - started
    assert raised.value.code == "DATABASE_RETRYABLE"
    assert raised.value.retryable is True
    assert raised.value.exit_code == 5
    assert 4.0 <= elapsed < 13.0
    with postgres_session_factory() as session:
        assert all(
            tuple(
                session.scalars(
                    select(source_processing_event.c.stage)
                    .where(source_processing_event.c.source_snapshot_id == snapshot_id)
                    .order_by(source_processing_event.c.sequence_number)
                )
            )
            == ("RECEIVED", "STORED", "PARSED", "VALIDATED", "MAPPED")
            for snapshot_id in caught.value.snapshot_ids
        )
