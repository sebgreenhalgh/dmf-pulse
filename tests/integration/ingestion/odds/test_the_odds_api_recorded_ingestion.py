"""Recorded The Odds API ingestion proofs using only manifest-approved fixtures."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    data_provider,
    external_identifier,
    market_definition,
    odds_observation,
    operator_market_observation,
    provider_market_representation,
    provider_quota_observation,
    rights_decision,
    source_snapshot,
)
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.service import (
    DEFAULT_CUTOFF,
    OddsImportRequest,
    OddsIngestionService,
    OddsReplayRequest,
)
from dmf_pulse.markets.models import MarketOutcome, MarketState
from dmf_pulse.markets.service import MarketService

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

FIXTURE_ROOT = Path("fixtures/odds/ODD-005")
EARLY_QUERY = datetime(2026, 8, 20, 12, 5, tzinfo=UTC)


def _count(session: Session, table: object) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)  # type: ignore[arg-type]


def _replay(root: Path, scenario: str = "happy_path"):
    return OddsIngestionService(repository_root=root).replay(
        OddsReplayRequest(
            fixture_set=root / FIXTURE_ROOT,
            scenario=scenario,
            information_cutoff=DEFAULT_CUTOFF,
            database_url_ref=DATABASE_REF,
        )
    )


def _import(root: Path, name: str, captured_at: datetime):
    service = OddsIngestionService(repository_root=root)
    service._seed_fpl_fixture(DATABASE_REF, DEFAULT_CUTOFF)
    return service.import_payload(
        OddsImportRequest(
            input_path=root / FIXTURE_ROOT / name,
            mapping_plan_path=root / FIXTURE_ROOT / "mapping_plan.json",
            captured_at=captured_at,
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
        fixture_external_provider="official_fpl",
        fixture_external_id="101",
        season_code="2026/27",
        as_of=as_of,
        database_url_ref=DATABASE_REF,
    )


def test_happy_recorded_replay_persists_exact_relational_evidence(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    outcome = _replay(repository_root)

    assert outcome.exit_code == 0
    assert outcome.result.status == "COMPLETE"
    assert outcome.result.events_seen == 1
    assert outcome.result.operator_books_seen == 2
    assert outcome.result.complete_books_created == 2
    assert outcome.result.incomplete_books_created == 0
    assert outcome.result.observations_created == 6
    assert outcome.result.observations_reused == 0
    assert outcome.result.quota is not None
    assert outcome.result.quota.model_dump(mode="json") == {
        "remaining": 499,
        "used": 1,
        "last_cost": 1,
        "observed_at": "2026-08-20T12:00:00Z",
        "source": "SYNTHETIC_FIXTURE",
    }

    result = _query(EARLY_QUERY)
    assert result.observation_count == 6
    assert len(result.books) == 2
    assert {book.market_state for book in result.books} == {MarketState.COMPLETE}
    observed = {
        book.operator_key: {quote.outcome: quote.decimal_odds for quote in book.observations}
        for book in result.books
    }
    assert observed == {
        "SYNTHETIC_BOOK_ALPHA": {
            MarketOutcome.HOME: Decimal("1.80"),
            MarketOutcome.DRAW: Decimal("3.60"),
            MarketOutcome.AWAY: Decimal("4.20"),
        },
        "SYNTHETIC_BOOK_BETA": {
            MarketOutcome.HOME: Decimal("1.85"),
            MarketOutcome.DRAW: Decimal("3.50"),
            MarketOutcome.AWAY: Decimal("4.10"),
        },
    }
    serialized = result.model_dump(mode="json")
    serialized_books = {
        str(book["operator_key"]).removeprefix("SYNTHETIC_").casefold(): {
            quote["outcome"]: quote["decimal_odds"] for quote in book["observations"]
        }
        for book in serialized["books"]
    }
    happy_golden = json.loads(
        (repository_root / "fixtures/odds/ODD-005/expected_outputs/happy_path.json").read_text(
            encoding="utf-8"
        )
    )
    asof_golden = json.loads(
        (
            repository_root
            / "fixtures/odds/ODD-005/expected_outputs/as_of_2026-08-20T12-05-00Z.json"
        ).read_text(encoding="utf-8")
    )
    assert serialized_books == happy_golden["books"]
    assert serialized_books == {
        key: value for key, value in asof_golden.items() if key.startswith("book_")
    }

    with postgres_session_factory() as session:
        snapshot_id = outcome.result.source_snapshot_id
        snapshot = (
            session.execute(
                select(source_snapshot).where(source_snapshot.c.source_snapshot_id == snapshot_id)
            )
            .mappings()
            .one()
        )
        assert snapshot["raw_storage_policy"] == "ALLOWED"
        assert snapshot["raw_blob_id"] is not None
        assert snapshot["raw_storage_object_id"] is not None
        assert snapshot["body_sha256"] is not None
        assert snapshot["rights_profile_record_id"] is not None
        assert _count(session, provider_quota_observation) == 1
        assert _count(session, operator_market_observation) == 2
        assert _count(session, odds_observation) == 6
        assert _count(session, provider_market_representation) == 2
        assert _count(session, market_definition) == 1
        assert _count(session, rights_decision) >= 5
        assert {
            row.identifier_namespace
            for row in session.execute(
                select(external_identifier.c.identifier_namespace).where(
                    external_identifier.c.identifier_namespace.in_(
                        (
                            "the_odds_api.event.id",
                            "the_odds_api.bookmaker.key",
                        )
                    )
                )
            )
        } == {"the_odds_api.event.id", "the_odds_api.bookmaker.key"}
        lifecycle = session.execute(
            text(
                "SELECT current_state, usable_at FROM provenance.source_snapshot_lifecycle "
                "WHERE source_snapshot_id = :snapshot_id"
            ),
            {"snapshot_id": snapshot_id},
        ).one()
        assert lifecycle.current_state == "USABLE"
        assert lifecycle.usable_at <= EARLY_QUERY
        odds_provider = session.execute(
            select(data_provider.c.provider_key).where(
                data_provider.c.provider_id == snapshot["provider_id"]
            )
        ).scalar_one()
        assert odds_provider == "synthetic_the_odds_api"


def test_incomplete_book_retains_present_quotes_without_zero_fill(
    repository_root: Path,
) -> None:
    outcome = _import(
        repository_root,
        "incomplete_book.json",
        datetime(2026, 8, 20, 13, tzinfo=UTC),
    )

    assert outcome.exit_code == 0
    assert outcome.result.status == "COMPLETE"
    assert outcome.result.complete_books_created == 0
    assert outcome.result.incomplete_books_created == 1
    assert outcome.result.observations_created == 2
    assert "INCOMPLETE_BOOK" in outcome.result.quality.warnings
    result = _query(datetime(2026, 8, 20, 13, 5, tzinfo=UTC))
    assert result.observation_count == 2
    assert len(result.books) == 1
    assert result.books[0].market_state is MarketState.INCOMPLETE
    assert {quote.outcome for quote in result.books[0].observations} == {
        MarketOutcome.HOME,
        MarketOutcome.AWAY,
    }


def test_unknown_market_is_warning_only_and_cannot_pollute_1x2(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    outcome = _import(
        repository_root,
        "unknown_market.json",
        datetime(2026, 8, 20, 13, tzinfo=UTC),
    )

    assert outcome.exit_code == 0
    assert outcome.result.status == "COMPLETE"
    assert any(
        warning.startswith("UNSUPPORTED_MARKET") for warning in outcome.result.quality.warnings
    )
    with postgres_session_factory() as session:
        assert set(session.scalars(select(market_definition.c.definition_key))) == {
            "MATCH_RESULT_1X2"
        }
        assert set(session.scalars(select(odds_observation.c.outcome))) == {
            "HOME",
            "DRAW",
            "AWAY",
        }


@pytest.mark.parametrize(
    ("fixture_name", "expected_blocker"),
    (
        ("duplicate_conflict.json", "VALIDATION_FAILED"),
        ("unmapped_fixture.json", "MAPPING_CONFLICT"),
    ),
)
def test_blocking_payload_or_mapping_is_quarantined_without_market_effects(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    fixture_name: str,
    expected_blocker: str,
) -> None:
    outcome = _import(
        repository_root,
        fixture_name,
        datetime(2026, 8, 20, 13, tzinfo=UTC),
    )

    assert outcome.exit_code == 3
    assert outcome.result.status == "QUARANTINED"
    assert expected_blocker in outcome.result.quality.blockers
    with postgres_session_factory() as session:
        assert _count(session, operator_market_observation) == 0
        assert _count(session, odds_observation) == 0
        state = session.execute(
            text(
                "SELECT current_state FROM provenance.source_snapshot_lifecycle "
                "WHERE source_snapshot_id = :snapshot_id"
            ),
            {"snapshot_id": outcome.result.source_snapshot_id},
        ).scalar_one()
        assert state == "QUARANTINED"


def test_post_cutoff_observation_is_retained_but_excluded_from_earlier_query(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    earlier = _replay(repository_root, "happy_path")
    outcome = _replay(repository_root, "post_cutoff")

    assert outcome.exit_code == 2
    assert outcome.result.status == "OBSERVED_NOT_USABLE"
    assert outcome.result.observations_created == 3
    before_cutoff = _query(DEFAULT_CUTOFF)
    after_cutoff = _query(datetime(2026, 8, 21, 17, 32, tzinfo=UTC))
    assert before_cutoff.observation_count == 6
    assert all(
        quote.source_snapshot_id != outcome.result.source_snapshot_id
        for book in before_cutoff.books
        for quote in book.observations
    )
    assert any(
        quote.source_snapshot_id == outcome.result.source_snapshot_id
        for book in after_cutoff.books
        for quote in book.observations
    )
    assert earlier.result.source_snapshot_id != outcome.result.source_snapshot_id
    with postgres_session_factory() as session:
        assert _count(session, odds_observation) == 9
