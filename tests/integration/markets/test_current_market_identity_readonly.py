"""PostgreSQL proof that current canonical resolution is exact and read-only."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from psycopg.types.range import Range
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, registry, sessionmaker

from dmf_pulse.data_model.tables import (
    betting_operator,
    canonical_entity,
    competition,
    data_provider,
    external_identifier,
    market_consensus_outcome,
    market_consensus_result,
    market_normalisation_run,
    operator_fixture_market,
    season,
)
from dmf_pulse.markets.current import (
    CurrentMarketCanonicalIdentityRepository,
    CurrentMarketConstraintError,
    CurrentMarketConstraintService,
    bind_current_market_constraint_request,
)
from tests.unit.markets.current_market_test_support import (
    build_source_context,
    recompose,
    rehash_odds,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


class _PendingCanonicalEntity:
    entity_id: UUID
    entity_type: str


class _DirtyDataProvider:
    display_name: str


_orm_registry = registry()
_orm_registry.map_imperatively(_PendingCanonicalEntity, canonical_entity)
_orm_registry.map_imperatively(_DirtyDataProvider, data_provider)


def _count(session: Session, table: object) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)  # type: ignore[arg-type]


def _uuid(number: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{number:012d}")


def _seed_current_identities(
    session: Session,
    context,
    *,
    mapping_status: str = "HUMAN_VERIFIED",
    mapping_method: str = "MANUAL",
    match_probability: Decimal | None = Decimal(1),
    official_product: str = "fantasy_premierleague",
    official_active: bool = True,
    competition_key: str = "PL",
    season_code: str = "2026/27",
    official_namespace: str = "fpl.fixture.id",
    official_entity_type: str = "FIXTURE",
    official_valid_range: Range | None = None,
    official_system_range: Range | None = None,
    add_parallel_pl_season: bool = False,
    operator_valid_ranges: Mapping[str, Range] | None = None,
    duplicate_operator_key: str | None = None,
) -> None:
    competition_id = _uuid(3901)
    season_id = _uuid(3902)
    official_provider_id = _uuid(3903)
    odds_provider_id = _uuid(3904)
    session.execute(
        insert(canonical_entity),
        [
            {"entity_id": competition_id, "entity_type": "COMPETITION"},
            {"entity_id": season_id, "entity_type": "SEASON"},
            {"entity_id": official_provider_id, "entity_type": "DATA_PROVIDER"},
            {"entity_id": odds_provider_id, "entity_type": "DATA_PROVIDER"},
        ],
    )
    session.execute(
        insert(competition).values(
            competition_id=competition_id,
            competition_key=competition_key,
            canonical_name="Synthetic Premier League",
            country_code="GB",
        )
    )
    session.execute(
        insert(season).values(
            season_id=season_id,
            competition_id=competition_id,
            season_code=season_code,
            starts_on=date(2026, 8, 1),
            ends_on=date(2027, 5, 31),
        )
    )
    session.execute(
        insert(data_provider),
        [
            {
                "provider_id": official_provider_id,
                "provider_key": "official_fpl",
                "display_name": "Synthetic official FPL",
                "provider_type": "OFFICIAL",
                "rights_profile_key": "fpl_official_private_manual_v1",
                "active": official_active,
            },
            {
                "provider_id": odds_provider_id,
                "provider_key": "the_odds_api",
                "display_name": "Synthetic The Odds API",
                "provider_type": "ODDS_API",
                "rights_profile_key": "the_odds_api_private_analytics_v1",
                "active": True,
            },
        ],
    )
    system_range = Range(datetime(2026, 8, 1, tzinfo=UTC), None, bounds="[)")
    valid_range = Range(
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2027, 6, 1, tzinfo=UTC),
        bounds="[)",
    )
    observed_at = datetime(2026, 8, 24, 10, tzinfo=UTC)
    if add_parallel_pl_season:
        replacement_competition_id = _uuid(3981)
        replacement_season_id = _uuid(3982)
        session.execute(
            insert(canonical_entity),
            [
                {
                    "entity_id": replacement_competition_id,
                    "entity_type": "COMPETITION",
                },
                {"entity_id": replacement_season_id, "entity_type": "SEASON"},
            ],
        )
        session.execute(
            insert(competition).values(
                competition_id=replacement_competition_id,
                competition_key="PL",
                canonical_name="Replacement synthetic PL",
                country_code="GB",
            )
        )
        session.execute(
            insert(season).values(
                season_id=replacement_season_id,
                competition_id=replacement_competition_id,
                season_code="2026/27",
                starts_on=date(2026, 8, 1),
                ends_on=date(2027, 5, 31),
            )
        )
    event_by_id = {event.provider_event_id: event for event in context.odds_input.events}
    identifier_rows: list[dict[str, object]] = []
    for index, mapping in enumerate(context.identity_map.fixture_mappings, start=1):
        fixture_id = _uuid(3910 + index)
        session.execute(
            insert(canonical_entity).values(entity_id=fixture_id, entity_type="FIXTURE")
        )
        official_canonical_id = fixture_id
        if official_entity_type != "FIXTURE":
            official_canonical_id = _uuid(3970 + index)
            session.execute(
                insert(canonical_entity).values(
                    entity_id=official_canonical_id,
                    entity_type=official_entity_type,
                )
            )
        identifier_rows.extend(
            (
                {
                    "external_identifier_id": _uuid(3920 + index),
                    "canonical_entity_id": official_canonical_id,
                    "provider_id": official_provider_id,
                    "provider_product": official_product,
                    "identifier_namespace": official_namespace,
                    "entity_type": official_entity_type,
                    "external_id_text": str(mapping.official_fpl_fixture_id),
                    "valid_during": (
                        official_valid_range if official_valid_range is not None else valid_range
                    ),
                    "system_during": (
                        official_system_range if official_system_range is not None else system_range
                    ),
                    "mapping_status": mapping_status,
                    "mapping_method": mapping_method,
                    "match_probability": match_probability,
                    "reviewed_by": "CURRENT-MARKETS-001A synthetic integration",
                    "reviewed_at": observed_at,
                    "first_seen_at": observed_at,
                    "last_seen_at": observed_at,
                    "is_provider_primary": True,
                    "season_id": season_id,
                },
                {
                    "external_identifier_id": _uuid(3930 + index),
                    "canonical_entity_id": fixture_id,
                    "provider_id": odds_provider_id,
                    "provider_product": "soccer_epl/odds",
                    "identifier_namespace": "the_odds_api.event.id",
                    "entity_type": "FIXTURE",
                    "external_id_text": mapping.provider_event_id,
                    "valid_during": valid_range,
                    "system_during": system_range,
                    "mapping_status": mapping_status,
                    "mapping_method": mapping_method,
                    "match_probability": match_probability,
                    "reviewed_by": "CURRENT-MARKETS-001A synthetic integration",
                    "reviewed_at": observed_at,
                    "first_seen_at": observed_at,
                    "last_seen_at": observed_at,
                    "is_provider_primary": True,
                    "season_id": season_id,
                },
            )
        )
        assert event_by_id[mapping.provider_event_id].commence_time in valid_range
    target_event_ids = {item.provider_event_id for item in context.identity_map.fixture_mappings}
    bookmaker_by_key = {
        bookmaker.bookmaker_key: bookmaker
        for event in context.odds_input.events
        if event.provider_event_id in target_event_ids
        for bookmaker in event.bookmakers
    }
    for index, (key, bookmaker) in enumerate(sorted(bookmaker_by_key.items()), start=1):
        operator_id = _uuid(3940 + index)
        session.execute(
            insert(canonical_entity).values(
                entity_id=operator_id,
                entity_type="BETTING_OPERATOR",
            )
        )
        session.execute(
            insert(betting_operator).values(
                operator_id=operator_id,
                operator_key=f"SYNTHETIC_{key.upper()}",
                display_name=bookmaker.bookmaker_title,
            )
        )
        operator_identifier = {
            "external_identifier_id": _uuid(3950 + index),
            "canonical_entity_id": operator_id,
            "provider_id": odds_provider_id,
            "provider_product": "soccer_epl/odds",
            "identifier_namespace": "the_odds_api.bookmaker.key",
            "entity_type": "BETTING_OPERATOR",
            "external_id_text": key,
            "valid_during": (
                operator_valid_ranges.get(key, valid_range)
                if operator_valid_ranges is not None
                else valid_range
            ),
            "system_during": system_range,
            "mapping_status": mapping_status,
            "mapping_method": mapping_method,
            "match_probability": match_probability,
            "reviewed_by": "CURRENT-MARKETS-001A synthetic integration",
            "reviewed_at": observed_at,
            "first_seen_at": observed_at,
            "last_seen_at": observed_at,
            "is_provider_primary": True,
            "season_id": None,
        }
        identifier_rows.append(operator_identifier)
        if duplicate_operator_key == key:
            identifier_rows.append(
                {
                    **operator_identifier,
                    "external_identifier_id": _uuid(3990 + index),
                    "system_during": Range(
                        datetime(2026, 8, 1, tzinfo=UTC),
                        datetime(2026, 9, 1, tzinfo=UTC),
                        bounds="[)",
                    ),
                }
            )
    session.execute(insert(external_identifier), identifier_rows)


def _resolver_row_counts(session: Session) -> dict[str, int]:
    return {
        "canonical": _count(session, canonical_entity),
        "identifiers": _count(session, external_identifier),
        "operators": _count(session, betting_operator),
        "providers": _count(session, data_provider),
        "operator_fixture_markets": _count(session, operator_fixture_market),
        "normalisation_runs": _count(session, market_normalisation_run),
        "consensus_results": _count(session, market_consensus_result),
        "consensus_outcomes": _count(session, market_consensus_outcome),
    }


def _assert_resolver_does_not_autoflush(
    session: Session,
    context,
    *,
    before: dict[str, int],
) -> None:
    flushes: list[bool] = []
    dml: list[str] = []

    def record_flush(*_args: object) -> None:
        flushes.append(True)

    def record_sql(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        verb = statement.lstrip().partition(" ")[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE"}:
            dml.append(statement)

    connection = session.connection()
    sqlalchemy_event.listen(session, "before_flush", record_flush)
    sqlalchemy_event.listen(connection, "before_cursor_execute", record_sql)
    try:
        view = CurrentMarketCanonicalIdentityRepository(session).resolve(
            context.bundle,
            resolved_at=context.bundle.decision_information_at,
        )
        request = bind_current_market_constraint_request(context.bundle, view)
        result = CurrentMarketConstraintService().build(
            request,
            source=context.bundle,
            identity_view=view,
        )
        after = {
            name: int(connection.scalar(select(func.count()).select_from(table)) or 0)
            for name, table in (
                ("canonical", canonical_entity),
                ("identifiers", external_identifier),
                ("operators", betting_operator),
                ("providers", data_provider),
                ("operator_fixture_markets", operator_fixture_market),
                ("normalisation_runs", market_normalisation_run),
                ("consensus_results", market_consensus_result),
                ("consensus_outcomes", market_consensus_outcome),
            )
        }
    finally:
        sqlalchemy_event.remove(connection, "before_cursor_execute", record_sql)
        sqlalchemy_event.remove(session, "before_flush", record_flush)

    assert before == after
    assert not flushes
    assert not dml
    assert result.runtime.database_write_performed is False
    assert result.runtime.persistence_performed is False


def test_real_postgres_resolution_and_market_build_make_no_database_writes(
    repository_root,
    tmp_path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    context = build_source_context(repository_root, tmp_path)
    with postgres_session_factory.begin() as session:
        _seed_current_identities(session, context)
    with postgres_session_factory() as session:
        before = {
            "canonical": _count(session, canonical_entity),
            "identifiers": _count(session, external_identifier),
            "operators": _count(session, betting_operator),
            "providers": _count(session, data_provider),
        }
        view = CurrentMarketCanonicalIdentityRepository(session).resolve(
            context.bundle,
            resolved_at=context.bundle.decision_information_at,
        )
        request = bind_current_market_constraint_request(context.bundle, view)
        result = CurrentMarketConstraintService().build(
            request,
            source=context.bundle,
            identity_view=view,
        )
        after = {
            "canonical": _count(session, canonical_entity),
            "identifiers": _count(session, external_identifier),
            "operators": _count(session, betting_operator),
            "providers": _count(session, data_provider),
        }

    assert before == after
    assert result.runtime.database_read_performed is True
    assert result.runtime.database_write_performed is False
    assert result.runtime.persistence_performed is False
    assert result.runtime.network_called is False
    assert all(item.readiness == "MARKET_READY" for item in result.fixtures)


def test_cmr_ir_007_pending_orm_state_is_not_autoflushed_by_resolver_selects(
    repository_root,
    tmp_path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    context = build_source_context(repository_root, tmp_path)
    with postgres_session_factory.begin() as seed_session:
        _seed_current_identities(seed_session, context)
    with postgres_session_factory() as bound_session:
        bind = bound_session.get_bind()
    with Session(bind=bind, autoflush=True) as session:
        before = _resolver_row_counts(session)
        pending = _PendingCanonicalEntity()
        pending.entity_id = _uuid(3999)
        pending.entity_type = "TEAM"
        session.add(pending)

        _assert_resolver_does_not_autoflush(session, context, before=before)

        assert pending in session.new
        session.rollback()
    with Session(bind=bind) as verification_session:
        assert _resolver_row_counts(verification_session) == before


def test_cmr_ir_007_dirty_orm_state_is_not_autoflushed_by_resolver_selects(
    repository_root,
    tmp_path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    context = build_source_context(repository_root, tmp_path)
    with postgres_session_factory.begin() as seed_session:
        _seed_current_identities(seed_session, context)
    with postgres_session_factory() as bound_session:
        bind = bound_session.get_bind()
    with Session(bind=bind, autoflush=True) as session:
        provider = session.get(_DirtyDataProvider, _uuid(3904))
        assert provider is not None
        original_display_name = provider.display_name
        before = _resolver_row_counts(session)
        provider.display_name = "Uncommitted dirty provider name"

        _assert_resolver_does_not_autoflush(session, context, before=before)

        assert provider in session.dirty
        session.rollback()
    with Session(bind=bind) as verification_session:
        provider = verification_session.get(_DirtyDataProvider, _uuid(3904))
        assert provider is not None
        assert provider.display_name == original_display_name
        assert _resolver_row_counts(verification_session) == before


@pytest.mark.parametrize(
    ("valid_range", "expected_pass"),
    (
        (
            Range(
                datetime(2026, 8, 29, 13, tzinfo=UTC),
                datetime(2026, 8, 29, 17, tzinfo=UTC),
                bounds="[)",
            ),
            True,
        ),
        (
            Range(
                datetime(2026, 8, 29, 13, tzinfo=UTC),
                datetime(2026, 8, 29, 15, tzinfo=UTC),
                bounds="[)",
            ),
            False,
        ),
        (
            Range(
                datetime(2026, 8, 29, 15, tzinfo=UTC),
                datetime(2026, 8, 29, 17, tzinfo=UTC),
                bounds="[)",
            ),
            False,
        ),
        (
            Range(
                datetime(2026, 8, 29, 14, tzinfo=UTC),
                datetime(2026, 8, 29, 17, tzinfo=UTC),
                bounds="[)",
            ),
            True,
        ),
        (
            Range(
                datetime(2026, 8, 29, 13, tzinfo=UTC),
                datetime(2026, 8, 29, 16, tzinfo=UTC),
                bounds="[)",
            ),
            False,
        ),
    ),
    ids=(
        "covers-both",
        "expires-before-second",
        "starts-after-first",
        "inclusive-lower",
        "excluded-upper",
    ),
)
def test_cmr_ir_009_one_operator_mapping_must_cover_every_target_occurrence(
    repository_root,
    tmp_path,
    postgres_session_factory: sessionmaker[Session],
    valid_range: Range,
    expected_pass: bool,
) -> None:
    context = build_source_context(repository_root, tmp_path)
    ranges = {"book_alpha": valid_range, "book_beta": valid_range}
    with postgres_session_factory.begin() as session:
        _seed_current_identities(session, context, operator_valid_ranges=ranges)

    with postgres_session_factory() as session:
        if expected_pass:
            view = CurrentMarketCanonicalIdentityRepository(session).resolve(
                context.bundle,
                resolved_at=context.bundle.decision_information_at,
            )
            assert len(view.operators) == 2
        else:
            with pytest.raises(CurrentMarketConstraintError) as caught:
                CurrentMarketCanonicalIdentityRepository(session).resolve(
                    context.bundle,
                    resolved_at=context.bundle.decision_information_at,
                )
            assert caught.value.code == "CANONICAL_IDENTITY_UNAVAILABLE"


def test_cmr_ir_009_mapping_need_not_cover_fixture_where_bookmaker_is_absent(
    repository_root,
    tmp_path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    context = build_source_context(repository_root, tmp_path)
    events = list(context.odds_input.events)
    second_target = events[1]
    events[1] = second_target.model_copy(
        update={
            "bookmakers": tuple(
                item for item in second_target.bookmakers if item.bookmaker_key != "book_alpha"
            )
        }
    )
    context = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    ranges = {
        "book_alpha": Range(
            datetime(2026, 8, 29, 13, tzinfo=UTC),
            datetime(2026, 8, 29, 15, tzinfo=UTC),
            bounds="[)",
        ),
        "book_beta": Range(
            datetime(2026, 8, 29, 13, tzinfo=UTC),
            datetime(2026, 8, 29, 17, tzinfo=UTC),
            bounds="[)",
        ),
    }
    with postgres_session_factory.begin() as session:
        _seed_current_identities(session, context, operator_valid_ranges=ranges)
    with postgres_session_factory() as session:
        view = CurrentMarketCanonicalIdentityRepository(session).resolve(
            context.bundle,
            resolved_at=context.bundle.decision_information_at,
        )
    assert len(view.operators) == 2


def test_cmr_ir_009_unrelated_provider_event_occurrence_is_ignored(
    repository_root,
    tmp_path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    context = build_source_context(repository_root, tmp_path)
    target_event_ids = {item.provider_event_id for item in context.identity_map.fixture_mappings}
    unrelated = next(
        event
        for event in context.odds_input.events
        if event.provider_event_id not in target_event_ids
    )
    ranges = {
        key: Range(
            datetime(2026, 8, 29, 13, tzinfo=UTC),
            datetime(2026, 8, 29, 17, tzinfo=UTC),
            bounds="[)",
        )
        for key in {book.bookmaker_key for book in unrelated.bookmakers}
    }
    assert all(unrelated.commence_time not in valid_range for valid_range in ranges.values())
    with postgres_session_factory.begin() as session:
        _seed_current_identities(session, context, operator_valid_ranges=ranges)
    with postgres_session_factory() as session:
        view = CurrentMarketCanonicalIdentityRepository(session).resolve(
            context.bundle,
            resolved_at=context.bundle.decision_information_at,
        )
    assert len(view.operators) == 2


def test_cmr_ir_009_duplicate_covering_operator_mappings_are_blocked_by_dat003(
    repository_root,
    tmp_path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    context = build_source_context(repository_root, tmp_path)
    with (
        pytest.raises(DBAPIError),
        postgres_session_factory.begin() as session,
    ):
        _seed_current_identities(session, context, duplicate_operator_key="book_alpha")

    with postgres_session_factory() as session:
        assert _count(session, external_identifier) == 0
        assert _count(session, betting_operator) == 0


@pytest.mark.parametrize(
    ("status", "method", "probability"),
    (
        ("AUTO_MATCHED", "PROBABILISTIC", Decimal("0.999999")),
        ("AUTO_MATCHED", "PROBABILISTIC", Decimal("0.010000")),
        ("AUTO_MATCHED", "PROBABILISTIC", Decimal(0)),
        ("AUTO_MATCHED", "PROBABILISTIC", None),
        ("CANDIDATE", "MANUAL", None),
        ("UNRESOLVED", "MANUAL", None),
        ("CONFLICTED", "MANUAL", None),
        ("REJECTED", "MANUAL", None),
        ("EXPIRED", "MANUAL", None),
    ),
)
def test_cmr_ir_004_only_human_verified_blocking_mappings_are_accepted(
    repository_root,
    tmp_path,
    postgres_session_factory: sessionmaker[Session],
    status: str,
    method: str,
    probability: Decimal | None,
) -> None:
    context = build_source_context(repository_root, tmp_path)
    with postgres_session_factory.begin() as session:
        _seed_current_identities(
            session,
            context,
            mapping_status=status,
            mapping_method=method,
            match_probability=probability,
        )

    with (
        postgres_session_factory() as session,
        pytest.raises(CurrentMarketConstraintError) as caught,
    ):
        CurrentMarketCanonicalIdentityRepository(session).resolve(
            context.bundle,
            resolved_at=context.bundle.decision_information_at,
        )

    assert caught.value.code == "CANONICAL_IDENTITY_UNAVAILABLE"


@pytest.mark.parametrize(
    "scope_defect",
    (
        "WRONG_PRODUCT",
        "INACTIVE_PROVIDER",
        "WRONG_COMPETITION",
        "CROSS_COMPETITION",
        "WRONG_SEASON",
        "WRONG_NAMESPACE",
        "WRONG_ENTITY_TYPE",
        "EXPIRED_VALID_RANGE",
        "FUTURE_SYSTEM_RANGE",
    ),
)
def test_cmr_ir_005_official_fpl_scope_defects_fail_closed(
    repository_root,
    tmp_path,
    postgres_session_factory: sessionmaker[Session],
    scope_defect: str,
) -> None:
    context = build_source_context(repository_root, tmp_path)
    seed_options: dict[str, object] = {}
    if scope_defect == "WRONG_PRODUCT":
        seed_options["official_product"] = "synthetic_wrong_product"
    elif scope_defect == "INACTIVE_PROVIDER":
        seed_options["official_active"] = False
    elif scope_defect == "WRONG_COMPETITION":
        seed_options["competition_key"] = "SYNTHETIC_OTHER"
    elif scope_defect == "CROSS_COMPETITION":
        seed_options.update(
            competition_key="SYNTHETIC_OTHER",
            add_parallel_pl_season=True,
        )
    elif scope_defect == "WRONG_SEASON":
        seed_options["season_code"] = "2025/26"
    elif scope_defect == "WRONG_NAMESPACE":
        seed_options["official_namespace"] = "synthetic.fixture.id"
    elif scope_defect == "WRONG_ENTITY_TYPE":
        seed_options["official_entity_type"] = "TEAM"
    elif scope_defect == "EXPIRED_VALID_RANGE":
        seed_options["official_valid_range"] = Range(
            datetime(2025, 8, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            bounds="[)",
        )
    else:
        seed_options["official_system_range"] = Range(
            context.identity_map.mapping_decided_at + timedelta(seconds=1),
            None,
            bounds="[)",
        )
    with postgres_session_factory.begin() as session:
        _seed_current_identities(session, context, **seed_options)

    with (
        postgres_session_factory() as session,
        pytest.raises(CurrentMarketConstraintError) as caught,
    ):
        CurrentMarketCanonicalIdentityRepository(session).resolve(
            context.bundle,
            resolved_at=context.bundle.decision_information_at,
        )

    assert caught.value.code == "CANONICAL_IDENTITY_UNAVAILABLE"
