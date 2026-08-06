"""As-of stability, exact cache identity and concurrency proofs for NRM-006."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from uuid import UUID

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    data_quality_issue,
    market_consensus_result,
    market_normalisation_run,
    market_normalisation_source,
    normalised_operator_market,
    normalised_operator_market_source,
    normalised_operator_outcome,
    odds_observation,
)
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.ingestion.odds import service as odds_service_module
from dmf_pulse.ingestion.odds.persistence import attest_publication_batch
from dmf_pulse.ingestion.odds.service import DEFAULT_CUTOFF, OddsIngestionService, OddsReplayRequest
from dmf_pulse.markets.models import MarketNormalisationResult, NormalisationStatus
from dmf_pulse.markets.policy import load_market_normalisation_policy
from dmf_pulse.markets.projection import market_normalisation_semantic_projection
from dmf_pulse.markets.repository import MarketObservationRepository
from dmf_pulse.markets.service import MarketService

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

EARLY = datetime(2026, 8, 20, 12, 5, tzinfo=UTC)
LATE = datetime(2026, 8, 20, 13, 5, tzinfo=UTC)


def _replay(repository_root: Path, scenario: str) -> UUID:
    outcome = OddsIngestionService(repository_root=repository_root).replay(
        OddsReplayRequest(
            fixture_set=repository_root / "fixtures/odds/ODD-005",
            scenario=scenario,
            information_cutoff=DEFAULT_CUTOFF,
            database_url_ref=DATABASE_REF,
        )
    )
    assert outcome.exit_code == 0
    snapshot_id = outcome.result.source_snapshot_id
    assert isinstance(snapshot_id, UUID)
    return snapshot_id


def _normalise(as_of: datetime) -> MarketNormalisationResult:
    return MarketService().normalise(
        fixture_external_provider="synthetic_fpl",
        fixture_external_id="101",
        season_code="2026/27",
        as_of=as_of,
        database_url_ref=DATABASE_REF,
    )


def _run_count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return int(session.scalar(select(func.count()).select_from(market_normalisation_run)) or 0)


def test_concurrent_exact_signature_reuses_one_run(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay(repository_root, "happy_path")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: _normalise(EARLY), range(2)))

    assert results[0].model_dump(mode="json") == results[1].model_dump(mode="json")
    assert _run_count(postgres_session_factory) == 1
    with postgres_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(market_normalisation_source)) == 6
        assert (
            session.scalar(select(func.count()).select_from(normalised_operator_market_source)) == 6
        )


def test_equivalent_offset_instants_reuse_one_byte_identical_run(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay(repository_root, "happy_path")
    equivalent_offset = datetime.fromisoformat("2026-08-20T13:05:00+01:00")

    utc_result = _normalise(EARLY)
    offset_result = _normalise(equivalent_offset)

    assert utc_result.model_dump_json() == offset_result.model_dump_json()
    assert utc_result.as_of == EARLY
    assert _run_count(postgres_session_factory) == 1


def test_simultaneous_same_source_correction_accepts_one_consistent_run(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay(repository_root, "happy_path")
    original = _normalise(EARLY)
    assert original.consensus is not None
    original_source_ids = {
        observation_id
        for market in original.consensus.operator_markets
        for observation_id in market.source_observation_ids
    }

    _replay(repository_root, "changed_quote")
    start = Barrier(2)

    def normalise_correction() -> MarketNormalisationResult:
        start.wait(timeout=10)
        return _normalise(LATE)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(normalise_correction) for _ in range(2))
        results = tuple(future.result(timeout=30) for future in futures)

    assert results[0].model_dump(mode="json") == results[1].model_dump(mode="json")
    corrected = results[0]
    assert corrected.consensus is not None
    corrected_source_ids = {
        observation_id
        for market in corrected.consensus.operator_markets
        for observation_id in market.source_observation_ids
    }
    assert len(corrected_source_ids) == 6
    assert corrected_source_ids.isdisjoint(original_source_ids)
    assert _run_count(postgres_session_factory) == 2

    with postgres_session_factory() as session:
        correction_run_ids = tuple(
            session.scalars(
                select(market_consensus_result.c.normalisation_run_id).where(
                    market_consensus_result.c.input_signature_sha256
                    == corrected.consensus.input_signature_sha256
                )
            )
        )
        assert len(correction_run_ids) == 1
        lineage = tuple(
            session.execute(
                select(
                    market_normalisation_source.c.odds_observation_id,
                    market_normalisation_source.c.source_snapshot_id,
                    market_normalisation_source.c.fixture_id,
                ).where(market_normalisation_source.c.normalisation_run_id == correction_run_ids[0])
            ).all()
        )
        selected_lineage = tuple(
            session.execute(
                select(
                    normalised_operator_market_source.c.odds_observation_id,
                    normalised_operator_market_source.c.source_snapshot_id,
                    normalised_operator_market_source.c.fixture_id,
                ).where(
                    normalised_operator_market_source.c.normalisation_run_id
                    == correction_run_ids[0]
                )
            ).all()
        )
    assert {row.odds_observation_id for row in lineage} > corrected_source_ids
    assert len(lineage) == 12
    assert len({row.source_snapshot_id for row in lineage}) == 2
    assert {row.fixture_id for row in lineage} == {corrected.fixture_id}
    assert {row.odds_observation_id for row in selected_lineage} == corrected_source_ids
    assert len(selected_lineage) == 6
    assert len({row.source_snapshot_id for row in selected_lineage}) == 1
    assert {row.fixture_id for row in selected_lineage} == {corrected.fixture_id}


def test_correction_publication_race_never_persists_a_torn_market_version(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _replay(repository_root, "happy_path")
    publication_committed = Barrier(2)
    normalisation_finished = Barrier(2)
    original_attest = attest_publication_batch

    def pause_before_attestation(
        session: Session,
        *,
        publication_batch_id: UUID,
        usable_at: datetime,
    ) -> datetime:
        publication_committed.wait(timeout=30)
        normalisation_finished.wait(timeout=30)
        return original_attest(
            session,
            publication_batch_id=publication_batch_id,
            usable_at=usable_at,
        )

    monkeypatch.setattr(odds_service_module, "attest_publication_batch", pause_before_attestation)

    def normalise_during_publication() -> MarketNormalisationResult:
        publication_committed.wait(timeout=30)
        result = _normalise(LATE)
        normalisation_finished.wait(timeout=30)
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        publication = executor.submit(_replay, repository_root, "changed_quote")
        raced_normalisation = executor.submit(normalise_during_publication)
        during = raced_normalisation.result(timeout=60)
        publication.result(timeout=60)

    assert during.consensus is None
    corrected = _normalise(LATE)
    assert corrected.consensus is not None

    with postgres_session_factory() as session:
        rows = tuple(
            session.execute(
                select(
                    market_normalisation_run.c.normalisation_run_id,
                    normalised_operator_market.c.normalised_operator_market_id,
                    normalised_operator_market_source.c.odds_observation_id,
                    normalised_operator_market_source.c.source_snapshot_id,
                    odds_observation.c.book_observation_id,
                    odds_observation.c.outcome,
                    odds_observation.c.decimal_odds.label("source_decimal_odds"),
                    normalised_operator_outcome.c.decimal_odds.label("result_decimal_odds"),
                )
                .join(
                    normalised_operator_market,
                    normalised_operator_market.c.normalisation_run_id
                    == market_normalisation_run.c.normalisation_run_id,
                )
                .join(
                    normalised_operator_market_source,
                    normalised_operator_market_source.c.normalised_operator_market_id
                    == normalised_operator_market.c.normalised_operator_market_id,
                )
                .join(
                    odds_observation,
                    odds_observation.c.odds_observation_id
                    == normalised_operator_market_source.c.odds_observation_id,
                )
                .join(
                    normalised_operator_outcome,
                    (
                        normalised_operator_outcome.c.normalised_operator_market_id
                        == normalised_operator_market.c.normalised_operator_market_id
                    )
                    & (normalised_operator_outcome.c.outcome == odds_observation.c.outcome),
                )
                .where(market_normalisation_run.c.status.in_(("NORMALISED", "DEGRADED")))
            ).all()
        )

    accepted_run_ids = {row.normalisation_run_id for row in rows}
    assert len(accepted_run_ids) == 1
    market_ids = {row.normalised_operator_market_id for row in rows}
    assert len(market_ids) == 2
    for market_id in market_ids:
        market_rows = tuple(row for row in rows if row.normalised_operator_market_id == market_id)
        assert len(market_rows) == 3
        assert {row.outcome for row in market_rows} == {"HOME", "DRAW", "AWAY"}
        assert len({row.book_observation_id for row in market_rows}) == 1
        assert len({row.source_snapshot_id for row in market_rows}) == 1
        assert all(row.source_decimal_odds == row.result_decimal_odds for row in market_rows)
    assert len({row.source_snapshot_id for row in rows}) == 1
    assert {row.odds_observation_id for row in rows} == {
        observation_id
        for market in corrected.consensus.operator_markets
        for observation_id in market.source_observation_ids
    }


def test_concurrent_p1_commit_serializes_before_run_eligibility_recheck(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_id = _replay(repository_root, "happy_path")
    lock_attempted = Event()
    lock_acquired = Event()
    original_lock = MarketObservationRepository._lock_quality_subjects

    def observed_quality_lock(
        repository: MarketObservationRepository,
        source_snapshot_ids: set[UUID],
    ) -> None:
        lock_attempted.set()
        original_lock(repository, source_snapshot_ids)
        lock_acquired.set()

    monkeypatch.setattr(
        MarketObservationRepository,
        "_lock_quality_subjects",
        observed_quality_lock,
    )

    quality_session = postgres_session_factory()
    quality_transaction = quality_session.begin()
    try:
        quality_session.execute(
            insert(data_quality_issue).values(
                source_snapshot_id=snapshot_id,
                issue_type="CONCURRENT_P1_CANARY",
                severity="P1",
                status="OPEN",
                detected_at=EARLY - timedelta(seconds=1),
                decision_impact="BLOCKING",
                subject_scope="SOURCE_SNAPSHOT",
                stage="MARKET_NORMALISATION",
                message="synthetic concurrent P1 eligibility canary",
            )
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_normalise, EARLY)
            assert lock_attempted.wait(timeout=30)
            assert not lock_acquired.wait(timeout=1)
            quality_transaction.commit()
            result = future.result(timeout=30)
    finally:
        if quality_transaction.is_active:
            quality_transaction.rollback()
        quality_session.close()

    assert lock_acquired.is_set()
    assert result.status is NormalisationStatus.BLOCKED
    assert result.consensus is None
    assert result.error_code == "QUALITY_BLOCKED"
    with postgres_session_factory() as session:
        accepted_count = session.scalar(
            select(func.count())
            .select_from(market_normalisation_run)
            .where(market_normalisation_run.c.status.in_(("NORMALISED", "DEGRADED")))
        )
    assert accepted_count == 0


def test_same_value_reobservation_creates_new_lineage_with_same_semantics(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    policy = load_market_normalisation_policy()
    _replay(repository_root, "happy_path")
    first = _normalise(EARLY)
    first_projection = market_normalisation_semantic_projection(first, policy=policy)
    _replay(repository_root, "happy_path")
    second = _normalise(EARLY)
    second_projection = market_normalisation_semantic_projection(second, policy=policy)

    assert first_projection == second_projection
    assert _run_count(postgres_session_factory) == 2
    with postgres_session_factory() as session:
        signatures = set(session.scalars(select(market_normalisation_run.c.input_signature_sha256)))
        semantic_hashes = set(
            session.scalars(select(market_normalisation_run.c.semantic_result_sha256))
        )
        assert len(signatures) == 2
        assert semantic_hashes == {first_projection["semantic_result_sha256"]}
        run_source_counts = sorted(
            session.scalars(
                select(func.count())
                .select_from(market_normalisation_source)
                .group_by(market_normalisation_source.c.normalisation_run_id)
            )
        )
        selected_source_counts = sorted(
            session.scalars(
                select(func.count())
                .select_from(normalised_operator_market_source)
                .group_by(normalised_operator_market_source.c.normalisation_run_id)
            )
        )
        assert run_source_counts == [6, 12]
        assert selected_source_counts == [6, 6]


def test_later_correction_cannot_change_earlier_asof_result(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    policy = load_market_normalisation_policy()
    _replay(repository_root, "happy_path")
    earlier_before = market_normalisation_semantic_projection(_normalise(EARLY), policy=policy)
    _replay(repository_root, "changed_quote")
    earlier_after = market_normalisation_semantic_projection(_normalise(EARLY), policy=policy)
    later = market_normalisation_semantic_projection(_normalise(LATE), policy=policy)

    assert earlier_after == earlier_before
    assert later != earlier_before
    assert _run_count(postgres_session_factory) == 2


def test_published_run_rejects_mutation(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay(repository_root, "happy_path")
    _normalise(EARLY)

    with postgres_session_factory.begin() as session:
        run_id = session.scalar(select(market_normalisation_run.c.normalisation_run_id))
        assert run_id is not None
        with pytest.raises(DBAPIError, match="IMMUTABLE_MARKET_RECORD"), session.begin_nested():
            session.execute(
                update(market_normalisation_run)
                .where(market_normalisation_run.c.normalisation_run_id == run_id)
                .values(status="DEGRADED")
            )
