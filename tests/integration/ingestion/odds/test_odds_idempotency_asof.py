"""PostgreSQL idempotency, concurrency, and exact as-of odds proofs."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg.types.range import Range
from sqlalchemy import Engine, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    betting_operator,
    canonical_entity,
    data_provider,
    external_identifier,
    market_definition,
    market_selection,
    odds_observation,
    odds_publication_batch,
    operator_fixture_market,
    operator_market_observation,
    provider_market_representation,
    rights_decision,
    rights_profile,
    source_snapshot,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.ingestion.odds.mapping import load_mapping_plan
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.ingestion.odds.persistence import OddsPersistence
from dmf_pulse.ingestion.odds.service import (
    DEFAULT_CUTOFF,
    OddsImportRequest,
    OddsIngestionService,
    OddsReplayRequest,
)
from dmf_pulse.markets.models import MarketOutcome, MarketQueryResult, MarketState
from dmf_pulse.markets.service import MarketService

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

CAPTURED = datetime(2026, 8, 20, 12, tzinfo=UTC)


def _count(session: Session, table: object) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)  # type: ignore[arg-type]


def _replay(root: Path, scenario: str):
    return OddsIngestionService(repository_root=root).replay(
        OddsReplayRequest(
            fixture_set=root / "fixtures/odds/ODD-005",
            scenario=scenario,
            information_cutoff=DEFAULT_CUTOFF,
            database_url_ref=DATABASE_REF,
        )
    )


def _import(root: Path, name: str, captured_at: datetime):
    return OddsIngestionService(
        repository_root=root,
        clock=lambda: captured_at + timedelta(seconds=10),
    ).import_payload(
        OddsImportRequest(
            input_path=root / "fixtures/odds/ODD-005" / name,
            mapping_plan_path=root / "fixtures/odds/ODD-005/mapping_plan.json",
            captured_at=captured_at,
            processing_at=captured_at + timedelta(seconds=5),
            information_cutoff=DEFAULT_CUTOFF,
            rights_profile_id="synthetic_the_odds_api_v1",
            database_url_ref=DATABASE_REF,
            quota=QuotaState(
                remaining=498,
                used=2,
                last_cost=1,
                observed_at=captured_at,
                source=QuotaSource.SYNTHETIC_FIXTURE,
            ),
        )
    )


def _query(as_of: datetime):
    return MarketService().observations(
        fixture_external_provider="synthetic_fpl",
        fixture_external_id="101",
        season_code="2026/27",
        as_of=as_of,
        database_url_ref=DATABASE_REF,
    )


def _price(result: MarketQueryResult, operator: str, outcome: MarketOutcome) -> Decimal:
    books = result.books
    return next(
        quote.decimal_odds
        for book in books
        if book.operator_key == operator
        for quote in book.observations
        if quote.outcome is outcome
    )


def test_repeated_identical_retrieval_retains_new_observations_without_identity_duplication(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    first = _replay(repository_root, "happy_path")
    second = _replay(repository_root, "happy_path")

    assert first.exit_code == second.exit_code == 0
    assert first.result.source_snapshot_id != second.result.source_snapshot_id
    assert first.result.observations_created == second.result.observations_created == 6
    with postgres_session_factory() as session:
        odds_provider_id = session.scalar(
            select(data_provider.c.provider_id).where(
                data_provider.c.provider_key == "synthetic_the_odds_api"
            )
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(source_snapshot)
                .where(source_snapshot.c.provider_id == odds_provider_id)
            )
            == 2
        )
        assert _count(session, betting_operator) == 2
        assert _count(session, market_definition) == 1
        assert _count(session, operator_fixture_market) == 2
        assert _count(session, market_selection) == 6
        assert _count(session, provider_market_representation) == 2
        assert _count(session, operator_market_observation) == 4
        assert _count(session, odds_observation) == 12
        assert (
            session.scalar(
                select(func.count(func.distinct(external_identifier.c.canonical_entity_id))).where(
                    external_identifier.c.identifier_namespace == "the_odds_api.bookmaker.key"
                )
            )
            == 2
        )


def test_reprocessing_one_source_snapshot_cannot_duplicate_quote_effects(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    outcome = _replay(repository_root, "happy_path")
    assert outcome.result.source_snapshot_id is not None
    parsed = parse_odds_payload(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes()
    )
    mapping = load_mapping_plan(repository_root / "fixtures/odds/ODD-005/mapping_plan.json")

    with postgres_session_factory.begin() as session:
        profile_id = session.scalar(
            select(source_snapshot.c.rights_profile_record_id).where(
                source_snapshot.c.source_snapshot_id == outcome.result.source_snapshot_id
            )
        )
        assert profile_id is not None
        publication_batch_id = session.scalar(
            select(odds_publication_batch.c.publication_batch_id).where(
                odds_publication_batch.c.source_snapshot_id == outcome.result.source_snapshot_id
            )
        )
        assert publication_batch_id is not None
        persistence = OddsPersistence(
            session,
            snapshot_id=outcome.result.source_snapshot_id,
            rights_profile_record_id=profile_id,
            captured_at=CAPTURED,
            mapping_cutoff=DEFAULT_CUTOFF,
            mapping_plan=mapping,
        )
        prepared = persistence.prepare(parsed)
        counts = persistence.publish(prepared, publication_batch_id=publication_batch_id)
        assert counts.observations_created == 0
        assert counts.observations_reused == 6

    with postgres_session_factory() as session:
        assert _count(session, operator_market_observation) == 2
        assert _count(session, odds_observation) == 6


def test_later_change_appends_and_cannot_rewrite_earlier_asof(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    first = _replay(repository_root, "happy_path")
    earlier_before = _query(datetime(2026, 8, 20, 12, 5, tzinfo=UTC))
    changed = _replay(repository_root, "changed_quote")
    earlier_after = _query(datetime(2026, 8, 20, 12, 5, tzinfo=UTC))
    later = _query(datetime(2026, 8, 20, 13, 5, tzinfo=UTC))

    assert first.exit_code == changed.exit_code == 0
    assert earlier_after.model_dump(mode="json") == earlier_before.model_dump(mode="json")
    assert _price(earlier_after, "book_alpha", MarketOutcome.HOME) == Decimal("1.80")
    assert _price(later, "book_alpha", MarketOutcome.HOME) == Decimal("1.75")
    assert earlier_after.observation_count == later.observation_count == 6
    with postgres_session_factory() as session:
        assert _count(session, odds_observation) == 12
        assert _count(session, operator_market_observation) == 4


def test_latest_incomplete_book_does_not_stale_fill_missing_selection(
    repository_root: Path,
) -> None:
    _replay(repository_root, "happy_path")
    incomplete = _import(
        repository_root,
        "incomplete_book.json",
        datetime(2026, 8, 20, 13, tzinfo=UTC),
    )
    assert incomplete.exit_code == 0

    result = _query(datetime(2026, 8, 20, 13, 5, tzinfo=UTC))
    alpha = next(book for book in result.books if book.operator_key == "book_alpha")
    beta = next(book for book in result.books if book.operator_key == "book_beta")
    assert alpha.market_state is MarketState.INCOMPLETE
    assert {quote.outcome for quote in alpha.observations} == {
        MarketOutcome.HOME,
        MarketOutcome.AWAY,
    }
    assert beta.market_state is MarketState.COMPLETE
    assert len(beta.observations) == 3
    assert result.observation_count == 5


def test_concurrent_retrievals_share_canonical_mapping_and_market_identity(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    service = OddsIngestionService(repository_root=repository_root)
    service._seed_fpl_fixture(DATABASE_REF, DEFAULT_CUTOFF)

    def worker(index: int):
        return _import(
            repository_root,
            "happy_path.json",
            CAPTURED + timedelta(microseconds=index),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(worker, (0, 1)))

    assert all(outcome.exit_code == 0 for outcome in outcomes)
    assert len({outcome.result.source_snapshot_id for outcome in outcomes}) == 2
    with postgres_session_factory() as session:
        assert _count(session, betting_operator) == 2
        assert _count(session, operator_fixture_market) == 2
        assert _count(session, market_selection) == 6
        assert _count(session, provider_market_representation) == 2
        assert _count(session, operator_market_observation) == 4
        assert _count(session, odds_observation) == 12
        assert (
            session.scalar(
                select(func.count())
                .select_from(rights_profile)
                .where(rights_profile.c.rights_profile_id == "synthetic_the_odds_api_v1")
            )
            == 1
        )


def test_database_rejects_conflicting_global_bookmaker_mapping(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay(repository_root, "happy_path")
    with postgres_session_factory.begin() as session:
        existing = (
            session.execute(
                select(external_identifier).where(
                    external_identifier.c.identifier_namespace == "the_odds_api.bookmaker.key",
                    external_identifier.c.external_id_text == "book_alpha",
                )
            )
            .mappings()
            .one()
        )
        conflicting_operator_id = uuid4()
        session.execute(
            insert(canonical_entity).values(
                entity_id=conflicting_operator_id,
                entity_type="BETTING_OPERATOR",
            )
        )
        session.execute(
            insert(betting_operator).values(
                operator_id=conflicting_operator_id,
                operator_key="CONFLICTING_BOOK_ALPHA",
                display_name="Conflicting Book Alpha",
            )
        )
        values = {
            "canonical_entity_id": conflicting_operator_id,
            "provider_id": existing["provider_id"],
            "provider_product": "soccer_epl/odds",
            "identifier_namespace": "the_odds_api.bookmaker.key",
            "entity_type": "BETTING_OPERATOR",
            "external_id_text": "book_alpha",
            "valid_during": existing["valid_during"],
            "system_during": Range(CAPTURED + timedelta(hours=1), None, bounds="[)"),
            "mapping_status": "HUMAN_VERIFIED",
            "mapping_method": "PROVIDER_MAPPING",
            "match_probability": Decimal("1"),
            "evidence_source_snapshot_id": existing["evidence_source_snapshot_id"],
            "reviewed_by": "ODD-005 negative control",
            "reviewed_at": CAPTURED + timedelta(hours=1),
            "first_seen_at": CAPTURED + timedelta(hours=1),
            "last_seen_at": CAPTURED + timedelta(hours=1),
            "is_provider_primary": True,
            "season_id": None,
        }
        with (
            pytest.raises(DBAPIError, match="ex_external_identifier_current_accepted"),
            session.begin_nested(),
        ):
            session.execute(insert(external_identifier).values(**values))

        event_season_id = session.scalar(
            select(external_identifier.c.season_id).where(
                external_identifier.c.identifier_namespace == "the_odds_api.event.id"
            )
        )
        assert event_season_id is not None
        with (
            pytest.raises(DBAPIError, match="ck_external_identifier_odds_operator_scope"),
            session.begin_nested(),
        ):
            session.execute(
                insert(external_identifier).values(
                    **{
                        **values,
                        "provider_product": "alternate/product",
                        "season_id": event_season_id,
                    }
                )
            )


def test_database_rejects_conflicting_rights_authority(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    outcome = _replay(repository_root, "happy_path")
    assert outcome.result.source_snapshot_id is not None
    with postgres_session_factory.begin() as session:
        existing = (
            session.execute(
                select(rights_decision).where(
                    rights_decision.c.source_snapshot_id == outcome.result.source_snapshot_id,
                    rights_decision.c.capability == "derived_storage",
                )
            )
            .mappings()
            .one()
        )
        with (
            pytest.raises(DBAPIError, match="uq_rights_decision_authority"),
            session.begin_nested(),
        ):
            session.execute(
                insert(rights_decision).values(
                    rights_profile_record_id=existing["rights_profile_record_id"],
                    source_snapshot_id=existing["source_snapshot_id"],
                    capability=existing["capability"],
                    decision="DENY",
                    reason_code="ODD005_CONFLICT_NEGATIVE_CONTROL",
                    checked_at=CAPTURED + timedelta(hours=1),
                    context_sha256="f" * 64,
                )
            )


def test_advisory_lock_timeout_is_bounded_and_typed_retryable(
    repository_root: Path,
    postgres_engine: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    OddsIngestionService(repository_root=repository_root)._seed_fpl_fixture(
        DATABASE_REF, DEFAULT_CUTOFF
    )
    with postgres_engine.connect() as lock_connection:
        transaction = lock_connection.begin()
        lock_connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": "operator:SYNTHETIC_BOOK_ALPHA"},
        )
        started = time.monotonic()
        try:
            with pytest.raises(IngestionError) as raised:
                _import(repository_root, "happy_path.json", CAPTURED)
        finally:
            elapsed = time.monotonic() - started
            transaction.rollback()

    assert raised.value.code == "DATABASE_RETRYABLE"
    assert raised.value.retryable is True
    assert 4 <= elapsed < 9
    with postgres_session_factory() as session:
        states = tuple(
            session.scalars(
                text(
                    "SELECT lifecycle.current_state "
                    "FROM provenance.source_snapshot_lifecycle AS lifecycle "
                    "JOIN provenance.source_snapshot AS snapshot "
                    "ON snapshot.source_snapshot_id = lifecycle.source_snapshot_id "
                    "JOIN provenance.data_provider AS provider "
                    "ON provider.provider_id = snapshot.provider_id "
                    "WHERE provider.provider_key = 'synthetic_the_odds_api'"
                )
            )
        )
    assert states == ("FAILED_RETRYABLE",)
