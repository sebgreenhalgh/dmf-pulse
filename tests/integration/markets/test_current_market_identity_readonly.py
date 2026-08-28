"""PostgreSQL proof that current canonical resolution is exact and read-only."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from psycopg.types.range import Range
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    betting_operator,
    canonical_entity,
    competition,
    data_provider,
    external_identifier,
    season,
)
from dmf_pulse.markets.current import (
    CurrentMarketCanonicalIdentityRepository,
    CurrentMarketConstraintService,
    bind_current_market_constraint_request,
)
from tests.unit.markets.current_market_test_support import build_source_context

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _count(session: Session, table: object) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)  # type: ignore[arg-type]


def _uuid(number: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{number:012d}")


def _seed_current_identities(session: Session, context) -> None:
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
            competition_key="PL",
            canonical_name="Synthetic Premier League",
            country_code="GB",
        )
    )
    session.execute(
        insert(season).values(
            season_id=season_id,
            competition_id=competition_id,
            season_code="2026/27",
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
            },
            {
                "provider_id": odds_provider_id,
                "provider_key": "the_odds_api",
                "display_name": "Synthetic The Odds API",
                "provider_type": "ODDS_API",
                "rights_profile_key": "the_odds_api_private_analytics_v1",
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
    event_by_id = {event.provider_event_id: event for event in context.odds_input.events}
    identifier_rows: list[dict[str, object]] = []
    for index, mapping in enumerate(context.identity_map.fixture_mappings, start=1):
        fixture_id = _uuid(3910 + index)
        session.execute(
            insert(canonical_entity).values(entity_id=fixture_id, entity_type="FIXTURE")
        )
        identifier_rows.extend(
            (
                {
                    "external_identifier_id": _uuid(3920 + index),
                    "canonical_entity_id": fixture_id,
                    "provider_id": official_provider_id,
                    "provider_product": "fantasy_premierleague",
                    "identifier_namespace": "fpl.fixture.id",
                    "entity_type": "FIXTURE",
                    "external_id_text": str(mapping.official_fpl_fixture_id),
                    "valid_during": valid_range,
                    "system_during": system_range,
                    "mapping_status": "HUMAN_VERIFIED",
                    "mapping_method": "MANUAL",
                    "match_probability": Decimal(1),
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
                    "mapping_status": "HUMAN_VERIFIED",
                    "mapping_method": "MANUAL",
                    "match_probability": Decimal(1),
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
        identifier_rows.append(
            {
                "external_identifier_id": _uuid(3950 + index),
                "canonical_entity_id": operator_id,
                "provider_id": odds_provider_id,
                "provider_product": "soccer_epl/odds",
                "identifier_namespace": "the_odds_api.bookmaker.key",
                "entity_type": "BETTING_OPERATOR",
                "external_id_text": key,
                "valid_during": valid_range,
                "system_during": system_range,
                "mapping_status": "HUMAN_VERIFIED",
                "mapping_method": "MANUAL",
                "match_probability": Decimal(1),
                "reviewed_by": "CURRENT-MARKETS-001A synthetic integration",
                "reviewed_at": observed_at,
                "first_seen_at": observed_at,
                "last_seen_at": observed_at,
                "is_provider_primary": True,
                "season_id": None,
            }
        )
    session.execute(insert(external_identifier), identifier_rows)


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
