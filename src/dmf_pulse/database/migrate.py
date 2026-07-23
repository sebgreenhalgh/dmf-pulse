"""Programmatic access to the packaged Alembic revision environment."""

from __future__ import annotations

from importlib.resources import files

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    migration_root = files("dmf_pulse.database.migrations")
    config.set_main_option("script_location", str(migration_root))
    config.set_main_option("version_locations", str(migration_root.joinpath("versions")))
    config.set_main_option("path_separator", "os")
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("packaged Alembic history has no head revision")
    return head


def upgrade_database(database_url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade_database(database_url: str, revision: str = "base") -> None:
    command.downgrade(alembic_config(database_url), revision)
