"""PostgreSQL proof that current canonical resolution is exact and read-only."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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
    CurrentMarketConstraintError,
    CurrentMarketConstraintService,
    bind_current_market_constraint_request,
)
from tests.unit.markets.current_market_test_support import build_source_context

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


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
