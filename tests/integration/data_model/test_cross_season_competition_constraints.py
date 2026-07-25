"""PostgreSQL enforcement of FPL season and competition coherence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from psycopg.types.range import Range
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    canonical_entity,
    competition,
    fixture,
    fixture_gameweek_assignment,
    gameweek,
    player,
    player_team_membership,
    season,
    team,
    team_season,
)

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

VALID_DURING = Range(
    datetime(2026, 8, 1, tzinfo=UTC),
    datetime(2027, 6, 1, tzinfo=UTC),
    bounds="[)",
)


@dataclass(frozen=True)
class SeasonGraph:
    competition_a: UUID
    competition_b: UUID
    season_a: UUID
    season_b: UUID
    home_a: UUID
    away_a: UUID
    home_b: UUID
    away_b: UUID
    player_id: UUID
    fixture_a: UUID
    gameweek_a: UUID
    gameweek_b: UUID


def _entity(session: Session, entity_type: str) -> UUID:
    value = session.execute(
        insert(canonical_entity)
        .values(entity_type=entity_type)
        .returning(canonical_entity.c.entity_id)
    ).scalar_one()
    assert isinstance(value, UUID)
    return value


def _seed(factory: sessionmaker[Session]) -> SeasonGraph:
    with factory.begin() as session:
        competition_a = _entity(session, "COMPETITION")
        competition_b = _entity(session, "COMPETITION")
        session.execute(
            insert(competition),
            [
                {
                    "competition_id": competition_a,
                    "entity_type": "COMPETITION",
                    "competition_key": "SYNTHETIC-A",
                    "canonical_name": "Synthetic Competition A",
                },
                {
                    "competition_id": competition_b,
                    "entity_type": "COMPETITION",
                    "competition_key": "SYNTHETIC-B",
                    "canonical_name": "Synthetic Competition B",
                },
            ],
        )

        season_a = _entity(session, "SEASON")
        season_b = _entity(session, "SEASON")
        session.execute(
            insert(season),
            [
                {
                    "season_id": season_a,
                    "entity_type": "SEASON",
                    "competition_id": competition_a,
                    "season_code": "2026/27",
                    "starts_on": date(2026, 8, 1),
                    "ends_on": date(2027, 5, 31),
                },
                {
                    "season_id": season_b,
                    "entity_type": "SEASON",
                    "competition_id": competition_b,
                    "season_code": "2026/27",
                    "starts_on": date(2026, 8, 1),
                    "ends_on": date(2027, 5, 31),
                },
            ],
        )

        home_a = _entity(session, "TEAM")
        away_a = _entity(session, "TEAM")
        home_b = _entity(session, "TEAM")
        away_b = _entity(session, "TEAM")
        session.execute(
            insert(team),
            [
                {
                    "team_id": identifier,
                    "entity_type": "TEAM",
                    "canonical_name": name,
                }
                for identifier, name in (
                    (home_a, "Synthetic A Home"),
                    (away_a, "Synthetic A Away"),
                    (home_b, "Synthetic B Home"),
                    (away_b, "Synthetic B Away"),
                )
            ],
        )
        session.execute(
            insert(team_season),
            [
                {"team_id": home_a, "season_id": season_a},
                {"team_id": away_a, "season_id": season_a},
                {"team_id": home_b, "season_id": season_b},
                {"team_id": away_b, "season_id": season_b},
            ],
        )

        player_id = _entity(session, "PLAYER")
        session.execute(
            insert(player).values(
                player_id=player_id,
                entity_type="PLAYER",
                canonical_name="Synthetic Player",
            )
        )

        fixture_a = _entity(session, "FIXTURE")
        session.execute(
            insert(fixture).values(
                fixture_id=fixture_a,
                entity_type="FIXTURE",
                competition_id=competition_a,
                season_id=season_a,
                home_team_id=home_a,
                away_team_id=away_a,
            )
        )

        gameweek_a = _entity(session, "GAMEWEEK")
        gameweek_b = _entity(session, "GAMEWEEK")
        session.execute(
            insert(gameweek),
            [
                {
                    "gameweek_id": gameweek_a,
                    "entity_type": "GAMEWEEK",
                    "season_id": season_a,
                    "number": 1,
                    "display_name": "Gameweek 1",
                    "status": "OPEN",
                },
                {
                    "gameweek_id": gameweek_b,
                    "entity_type": "GAMEWEEK",
                    "season_id": season_b,
                    "number": 1,
                    "display_name": "Gameweek 1",
                    "status": "OPEN",
                },
            ],
        )

    return SeasonGraph(
        competition_a=competition_a,
        competition_b=competition_b,
        season_a=season_a,
        season_b=season_b,
        home_a=home_a,
        away_a=away_a,
        home_b=home_b,
        away_b=away_b,
        player_id=player_id,
        fixture_a=fixture_a,
        gameweek_a=gameweek_a,
        gameweek_b=gameweek_b,
    )


def _assert_constraint(error: IntegrityError, expected_name: str) -> None:
    assert expected_name in str(error.orig)


def test_fixture_rejects_season_from_another_competition(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _seed(postgres_session_factory)

    with (
        postgres_session_factory() as session,
        pytest.raises(IntegrityError) as caught,
        session.begin(),
    ):
        fixture_id = _entity(session, "FIXTURE")
        session.execute(
            insert(fixture).values(
                fixture_id=fixture_id,
                entity_type="FIXTURE",
                competition_id=graph.competition_a,
                season_id=graph.season_b,
                home_team_id=graph.home_b,
                away_team_id=graph.away_b,
            )
        )

    _assert_constraint(caught.value, "fk_fixture_season_competition")


def test_fixture_rejects_team_not_registered_for_its_season(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _seed(postgres_session_factory)

    with (
        postgres_session_factory() as session,
        pytest.raises(IntegrityError) as caught,
        session.begin(),
    ):
        fixture_id = _entity(session, "FIXTURE")
        session.execute(
            insert(fixture).values(
                fixture_id=fixture_id,
                entity_type="FIXTURE",
                competition_id=graph.competition_a,
                season_id=graph.season_a,
                home_team_id=graph.home_b,
                away_team_id=graph.away_a,
            )
        )

    _assert_constraint(caught.value, "fk_fixture_home_team_season")


def test_fixture_assignment_rejects_gameweek_from_another_season(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _seed(postgres_session_factory)

    with (
        postgres_session_factory() as session,
        pytest.raises(IntegrityError) as caught,
        session.begin(),
    ):
        session.execute(
            insert(fixture_gameweek_assignment).values(
                fixture_id=graph.fixture_a,
                gameweek_id=graph.gameweek_b,
                season_id=graph.season_a,
                assignment_status="ASSIGNED",
                valid_during=VALID_DURING,
            )
        )

    _assert_constraint(caught.value, "fk_assignment_gameweek_season")


def test_membership_rejects_team_from_another_season(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _seed(postgres_session_factory)

    with (
        postgres_session_factory() as session,
        pytest.raises(IntegrityError) as caught,
        session.begin(),
    ):
        session.execute(
            insert(player_team_membership).values(
                player_id=graph.player_id,
                team_id=graph.home_b,
                season_id=graph.season_a,
                registration_type="PERMANENT",
                squad_status="REGISTERED",
                valid_during=VALID_DURING,
            )
        )

    _assert_constraint(caught.value, "fk_membership_team_season")


def test_same_season_fixture_assignment_is_accepted(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    graph = _seed(postgres_session_factory)

    with postgres_session_factory.begin() as session:
        assignment_id = session.execute(
            insert(fixture_gameweek_assignment)
            .values(
                fixture_id=graph.fixture_a,
                gameweek_id=graph.gameweek_a,
                season_id=graph.season_a,
                assignment_status="ASSIGNED",
                valid_during=VALID_DURING,
            )
            .returning(fixture_gameweek_assignment.c.assignment_id)
        ).scalar_one()

    with postgres_session_factory() as session:
        persisted = session.execute(
            select(fixture_gameweek_assignment.c.assignment_id).where(
                fixture_gameweek_assignment.c.assignment_id == assignment_id
            )
        ).scalar_one()
    assert persisted == assignment_id
