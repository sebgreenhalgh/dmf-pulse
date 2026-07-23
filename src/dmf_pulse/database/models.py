"""Strict public contracts for PostgreSQL settings, health, and schema state."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

REFERENCE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{2,127}$")


class DatabaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DatabaseSettings(DatabaseModel):
    url_secret_ref: Annotated[StrictStr, Field(min_length=3, max_length=128)]
    connect_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=30)] = 5
    application_name: Annotated[
        StrictStr, Field(min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_.-]+$")
    ] = "dmf-pulse"

    @field_validator("url_secret_ref")
    @classmethod
    def reference_is_not_a_url(cls, value: str) -> str:
        candidate = value.strip()
        if (
            REFERENCE_PATTERN.fullmatch(candidate) is None
            or "://" in candidate
            or "@" in candidate
            or "?" in candidate
            or "password" in candidate.casefold()
        ):
            raise ValueError("must be an opaque secret reference, never a database URL")
        return candidate


class SchemaManifest(DatabaseModel):
    postgres_version: StrictStr
    alembic_revision: StrictStr
    extensions: tuple[StrictStr, ...]
    schemas: dict[str, Any]
    schema_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class DatabaseLocation(DatabaseModel):
    host: StrictStr
    port: StrictInt
    name: StrictStr


class PostgresStatus(DatabaseModel):
    version: StrictStr
    major: Literal[18]
    supported: Literal[True]


class DatabaseDoctorResult(DatabaseModel):
    status: Literal["HEALTHY", "DEGRADED", "BLOCKED"]
    database: DatabaseLocation
    postgres: PostgresStatus
    migration: dict[str, Any]
    capabilities: dict[str, Any]
    schema_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
