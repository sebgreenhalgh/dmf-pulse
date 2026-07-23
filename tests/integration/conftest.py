"""PostgreSQL 18 integration fixtures with deterministic table cleanup."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import metadata
from dmf_pulse.database.engine import create_database_engine, session_factory
from dmf_pulse.database.models import DatabaseSettings


@pytest.fixture(scope="session")
def postgres_url() -> str:
    value = os.environ.get("DMF_TEST_DATABASE_URL")
    if value is None:
        pytest.fail("DMF_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest.fixture(scope="session")
def postgres_engine(postgres_url: str) -> Iterator[Engine]:
    engine = create_database_engine(
        postgres_url,
        DatabaseSettings(
            url_secret_ref="env:DMF_TEST_DATABASE_URL",
            application_name="dmf-pulse-tests",
        ),
    )
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def postgres_session_factory(postgres_engine: Engine) -> sessionmaker[Session]:
    return session_factory(postgres_engine)


def _truncate(engine: Engine) -> None:
    tables = ", ".join(table.fullname for table in metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def clean_postgres_test(request: pytest.FixtureRequest) -> Iterator[None]:
    if not (
        request.node.get_closest_marker("postgres") or request.node.get_closest_marker("migration")
    ):
        yield
        return
    postgres_engine = request.getfixturevalue("postgres_engine")
    _truncate(postgres_engine)
    yield
    _truncate(postgres_engine)
