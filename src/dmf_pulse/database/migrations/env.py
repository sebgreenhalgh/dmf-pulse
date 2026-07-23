"""Alembic environment using only an explicitly supplied test database URL."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from alembic.config import Config
from sqlalchemy import engine_from_config, pool

from dmf_pulse.data_model.tables import metadata

try:
    config: Config | None = context.config
except (AttributeError, NameError):  # Ordinary import, outside an Alembic EnvironmentContext.
    config = None
if config is not None and config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def _include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    """Exclude Alembic's own version table from application metadata drift."""

    del compare_to
    schema = getattr(object_, "schema", None)
    return not (
        reflected and type_ == "table" and name == "alembic_version" and schema in {None, "public"}
    )


def _database_url() -> str:
    configured = config.get_main_option("sqlalchemy.url") if config is not None else None
    value = configured or os.environ.get("DMF_TEST_DATABASE_URL")
    if value is None or not value.strip():
        raise RuntimeError("DMF_TEST_DATABASE_URL is required for DAT-003 migrations")
    return value


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=_include_object,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if config is None:
        raise RuntimeError("Alembic context is unavailable")
    values = config.get_section(config.config_ini_section, {})
    values["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        values,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"options": "-c timezone=UTC"},
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=_include_object,
            version_table_schema="public",
        )
        with context.begin_transaction():
            context.run_migrations()


if config is not None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
