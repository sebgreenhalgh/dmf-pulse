"""Explicit synchronous SQLAlchemy engine and session boundaries."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.database.errors import DatabaseError
from dmf_pulse.database.models import DatabaseLocation, DatabaseSettings


def validate_database_url(value: str) -> URL:
    try:
        url = make_url(value)
    except Exception as exc:
        raise DatabaseError(
            "DATABASE_CONFIGURATION_INVALID", "database configuration is invalid"
        ) from exc
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise DatabaseError("DATABASE_CONFIGURATION_INVALID", "PostgreSQL with psycopg is required")
    if not url.host or not url.database:
        raise DatabaseError("DATABASE_CONFIGURATION_INVALID", "database host and name are required")
    return url.set(drivername="postgresql+psycopg")


def database_location(value: str) -> DatabaseLocation:
    url = validate_database_url(value)
    return DatabaseLocation(host=url.host or "", port=url.port or 5432, name=url.database or "")


def resolve_test_database_url(*, environment: str) -> str:
    """Read the test URL only at an explicit TEST runtime boundary."""

    if environment.casefold() != "test":
        raise DatabaseError(
            "DATABASE_CONFIGURATION_INVALID",
            "the test database URL is available only in the TEST environment",
        )
    value = os.environ.get("DMF_TEST_DATABASE_URL")
    if value is None or not value.strip():
        raise DatabaseError(
            "DATABASE_CONFIGURATION_INVALID", "the test database URL is not configured"
        )
    validate_database_url(value)
    return value


def create_database_engine(url: str, settings: DatabaseSettings) -> Engine:
    normalized = validate_database_url(url)
    try:
        return create_engine(
            normalized,
            echo=False,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={
                "connect_timeout": settings.connect_timeout_seconds,
                "application_name": settings.application_name,
                "options": "-c timezone=UTC",
            },
        )
    except (SQLAlchemyError, ValueError, TypeError) as exc:
        raise DatabaseError(
            "DATABASE_CONFIGURATION_INVALID", "database engine setup failed"
        ) from exc


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        with session.begin():
            yield session
    except SQLAlchemyError as exc:
        raise DatabaseError("DATABASE_UNAVAILABLE", "database transaction failed") from exc
    finally:
        session.close()
