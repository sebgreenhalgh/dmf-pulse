"""SQLAlchemy Core metadata for the exact DAT-003 PostgreSQL surface."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSTZRANGE, UUID, ExcludeConstraint
from sqlalchemy.types import DateTime

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def _canonical_range_check(column: str) -> str:
    return (
        f"{column} IS NOT NULL AND NOT isempty({column}) "
        f"AND lower({column}) IS NOT NULL AND NOT lower_inf({column}) "
        f"AND isfinite(lower({column})) AND lower_inc({column}) AND NOT upper_inc({column})"
    )


canonical_entity = Table(
    "canonical_entity",
    metadata,
    Column("entity_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("entity_type", String(40), nullable=False),
    Column("lifecycle_status", String(24), nullable=False, server_default="ACTIVE"),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    Column(
        "superseded_by_entity_id",
        UUID(as_uuid=True),
        ForeignKey(
            "core.canonical_entity.entity_id",
            name="fk_canonical_entity_successor",
            ondelete="RESTRICT",
        ),
    ),
    Column("notes", Text),
    UniqueConstraint("entity_id", "entity_type", name="uq_canonical_entity_id_type"),
    CheckConstraint(
        "entity_type IN ('COMPETITION','SEASON','GAMEWEEK','TEAM','PLAYER','FIXTURE',"
        "'DATA_PROVIDER','BETTING_OPERATOR','MARKET','SELECTION')",
        name="ck_canonical_entity_type",
    ),
    CheckConstraint(
        "lifecycle_status IN ('ACTIVE','INACTIVE','SUPERSEDED','MERGED')",
        name="ck_canonical_entity_lifecycle",
    ),
    CheckConstraint(
        "superseded_by_entity_id IS NULL OR superseded_by_entity_id <> entity_id",
        name="ck_canonical_entity_no_self",
    ),
    CheckConstraint(
        "(lifecycle_status IN ('SUPERSEDED','MERGED') AND "
        "superseded_by_entity_id IS NOT NULL) OR "
        "(lifecycle_status IN ('ACTIVE','INACTIVE') AND superseded_by_entity_id IS NULL)",
        name="ck_canonical_entity_successor_state",
    ),
    schema="core",
)


def _typed_entity_columns(id_name: str, entity_type: str) -> list[Column[Any]]:
    return [
        Column(id_name, UUID(as_uuid=True), primary_key=True),
        Column("entity_type", String(40), nullable=False, server_default=entity_type),
    ]


competition = Table(
    "competition",
    metadata,
    *_typed_entity_columns("competition_id", "COMPETITION"),
    Column("competition_key", String(80), nullable=False),
    Column("canonical_name", Text, nullable=False),
    Column("country_code", CHAR(2)),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["competition_id", "entity_type"],
        ["core.canonical_entity.entity_id", "core.canonical_entity.entity_type"],
        name="fk_competition_canonical_type",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("competition_key", name="uq_competition_key"),
    CheckConstraint("entity_type = 'COMPETITION'", name="ck_competition_entity_type"),
    schema="football",
)

season = Table(
    "season",
    metadata,
    *_typed_entity_columns("season_id", "SEASON"),
    Column(
        "competition_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.competition.competition_id",
            name="fk_season_competition",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("season_code", String(20), nullable=False),
    Column("starts_on", Date, nullable=False),
    Column("ends_on", Date, nullable=False),
    ForeignKeyConstraint(
        ["season_id", "entity_type"],
        ["core.canonical_entity.entity_id", "core.canonical_entity.entity_type"],
        name="fk_season_canonical_type",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("season_id", "competition_id", name="uq_season_id_competition"),
    UniqueConstraint("competition_id", "season_code", name="uq_season_competition_code"),
    CheckConstraint("entity_type = 'SEASON'", name="ck_season_entity_type"),
    CheckConstraint("ends_on > starts_on", name="ck_season_dates"),
    schema="football",
)

team = Table(
    "team",
    metadata,
    *_typed_entity_columns("team_id", "TEAM"),
    Column("canonical_name", Text, nullable=False),
    Column("short_name", String(20)),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["team_id", "entity_type"],
        ["core.canonical_entity.entity_id", "core.canonical_entity.entity_type"],
        name="fk_team_canonical_type",
        ondelete="RESTRICT",
    ),
    CheckConstraint("entity_type = 'TEAM'", name="ck_team_entity_type"),
    schema="football",
)

player = Table(
    "player",
    metadata,
    *_typed_entity_columns("player_id", "PLAYER"),
    Column("canonical_name", Text, nullable=False),
    Column("birth_date", Date),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["player_id", "entity_type"],
        ["core.canonical_entity.entity_id", "core.canonical_entity.entity_type"],
        name="fk_player_canonical_type",
        ondelete="RESTRICT",
    ),
    CheckConstraint("entity_type = 'PLAYER'", name="ck_player_entity_type"),
    schema="football",
)

team_season = Table(
    "team_season",
    metadata,
    Column("team_season_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column(
        "team_id",
        UUID(as_uuid=True),
        ForeignKey("football.team.team_id", name="fk_team_season_team", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "season_id",
        UUID(as_uuid=True),
        ForeignKey("football.season.season_id", name="fk_team_season_season", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_team_season_snapshot",
            ondelete="RESTRICT",
        ),
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("team_id", "season_id", name="uq_team_season_identity"),
    UniqueConstraint("team_season_id", "season_id", name="uq_team_season_id_season"),
    schema="football",
)

fixture = Table(
    "fixture",
    metadata,
    *_typed_entity_columns("fixture_id", "FIXTURE"),
    Column(
        "competition_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.competition.competition_id",
            name="fk_fixture_competition",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "season_id",
        UUID(as_uuid=True),
        ForeignKey("football.season.season_id", name="fk_fixture_season", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "home_team_id",
        UUID(as_uuid=True),
        ForeignKey("football.team.team_id", name="fk_fixture_home_team", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "away_team_id",
        UUID(as_uuid=True),
        ForeignKey("football.team.team_id", name="fk_fixture_away_team", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["fixture_id", "entity_type"],
        ["core.canonical_entity.entity_id", "core.canonical_entity.entity_type"],
        name="fk_fixture_canonical_type",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["season_id", "competition_id"],
        ["football.season.season_id", "football.season.competition_id"],
        name="fk_fixture_season_competition",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["home_team_id", "season_id"],
        ["football.team_season.team_id", "football.team_season.season_id"],
        name="fk_fixture_home_team_season",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["away_team_id", "season_id"],
        ["football.team_season.team_id", "football.team_season.season_id"],
        name="fk_fixture_away_team_season",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("fixture_id", "season_id", name="uq_fixture_id_season"),
    CheckConstraint("entity_type = 'FIXTURE'", name="ck_fixture_entity_type"),
    CheckConstraint("home_team_id <> away_team_id", name="ck_fixture_distinct_teams"),
    schema="football",
)

gameweek = Table(
    "gameweek",
    metadata,
    *_typed_entity_columns("gameweek_id", "GAMEWEEK"),
    Column(
        "season_id",
        UUID(as_uuid=True),
        ForeignKey("football.season.season_id", name="fk_gameweek_season", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("number", SmallInteger, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("official_deadline_at", DateTime(timezone=True)),
    Column("status", String(20), nullable=False),
    ForeignKeyConstraint(
        ["gameweek_id", "entity_type"],
        ["core.canonical_entity.entity_id", "core.canonical_entity.entity_type"],
        name="fk_gameweek_canonical_type",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("season_id", "number", name="uq_gameweek_season_number"),
    UniqueConstraint("gameweek_id", "season_id", name="uq_gameweek_id_season"),
    CheckConstraint("entity_type = 'GAMEWEEK'", name="ck_gameweek_entity_type"),
    CheckConstraint("number BETWEEN 1 AND 60", name="ck_gameweek_number"),
    CheckConstraint("status IN ('DRAFT','OPEN','CLOSED','FINAL')", name="ck_gameweek_status"),
    schema="fpl",
)

data_provider = Table(
    "data_provider",
    metadata,
    *_typed_entity_columns("provider_id", "DATA_PROVIDER"),
    Column("provider_key", String(80), nullable=False),
    Column("display_name", Text, nullable=False),
    Column("provider_type", String(32), nullable=False),
    Column("rights_profile_key", String(120)),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["provider_id", "entity_type"],
        ["core.canonical_entity.entity_id", "core.canonical_entity.entity_type"],
        name="fk_provider_canonical_type",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("provider_key", name="uq_provider_key"),
    CheckConstraint("entity_type = 'DATA_PROVIDER'", name="ck_provider_entity_type"),
    CheckConstraint(
        "provider_type IN ('OFFICIAL','ODDS_API','FOOTBALL_API','MANUAL','OPEN_DATA','INTERNAL')",
        name="ck_provider_type",
    ),
    schema="provenance",
)

raw_blob = Table(
    "raw_blob",
    metadata,
    Column("raw_blob_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("body_sha256", CHAR(64), nullable=False),
    # DAT-003 compatibility metadata. New FPL-004 writes use raw_storage_object.
    Column("stored_blob_sha256", CHAR(64)),
    Column("byte_size", BigInteger, nullable=False),
    Column("storage_uri", Text),
    Column("storage_policy", String(24)),
    Column("content_type", Text),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("body_sha256", name="uq_raw_blob_body_sha256"),
    UniqueConstraint(
        "raw_blob_id", "body_sha256", "byte_size", name="uq_raw_blob_content_coherence"
    ),
    CheckConstraint("body_sha256 ~ '^[0-9a-f]{64}$'", name="ck_raw_blob_body_hash"),
    CheckConstraint(
        "stored_blob_sha256 IS NULL OR stored_blob_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_raw_blob_stored_hash",
    ),
    CheckConstraint("byte_size >= 0", name="ck_raw_blob_byte_size"),
    CheckConstraint(
        "storage_policy IS NULL OR storage_policy IN ('ALLOWED','FORBIDDEN','EPHEMERAL','DELETED')",
        name="ck_raw_blob_policy",
    ),
    CheckConstraint(
        "storage_policy <> 'FORBIDDEN' OR (storage_uri IS NULL AND stored_blob_sha256 IS NULL)",
        name="ck_raw_blob_forbidden_storage",
    ),
    schema="provenance",
)

rights_profile = Table(
    "rights_profile",
    metadata,
    Column(
        "rights_profile_record_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column("rights_profile_id", String(120), nullable=False),
    Column("provider_key", String(80), nullable=False),
    Column("profile_version", String(40), nullable=False),
    Column("status", String(24), nullable=False),
    Column("capabilities", JSONB, nullable=False),
    Column("retention_seconds", BigInteger),
    Column("retention_reason", Text),
    Column("termination_deletion_required", Boolean, nullable=False),
    Column("attribution_required", Boolean, nullable=False),
    Column("attribution_text", Text),
    Column("geography_scope", Text, nullable=False),
    Column("account_scope", Text, nullable=False),
    Column("approved_purpose", Text, nullable=False),
    Column("terms_source", Text, nullable=False),
    Column("terms_version", Text, nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("human_approval_id", Text, nullable=False),
    Column("approved_by", Text, nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    Column("notes", Text, nullable=False, server_default=""),
    Column("unresolved_rights", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint(
        "rights_profile_id", "profile_version", name="uq_rights_profile_identity_version"
    ),
    UniqueConstraint(
        "rights_profile_record_id",
        "rights_profile_id",
        "profile_version",
        name="uq_rights_profile_record_identity_version",
    ),
    ForeignKeyConstraint(
        ["provider_key"],
        ["provenance.data_provider.provider_key"],
        name="fk_rights_profile_provider_key",
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "status IN ('DRAFT','HUMAN_APPROVED','BLOCKED','SUPERSEDED','WITHDRAWN')",
        name="ck_rights_profile_status",
    ),
    CheckConstraint(
        "retention_seconds IS NULL OR retention_seconds >= 0",
        name="ck_rights_profile_retention",
    ),
    CheckConstraint(
        "jsonb_typeof(capabilities) = 'object'",
        name="ck_rights_profile_capabilities_object",
    ),
    schema="provenance",
)

raw_storage_object = Table(
    "raw_storage_object",
    metadata,
    Column(
        "raw_storage_object_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "raw_blob_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.raw_blob.raw_blob_id", name="fk_raw_storage_content", ondelete="RESTRICT"
        ),
        nullable=False,
    ),
    Column(
        "rights_profile_record_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.rights_profile.rights_profile_record_id",
            name="fk_raw_storage_rights_profile",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("stored_blob_sha256", CHAR(64), nullable=False),
    Column("storage_uri", Text, nullable=False),
    Column("storage_policy", String(24), nullable=False),
    Column("content_type", Text, nullable=False),
    Column("retention_seconds", BigInteger),
    Column("access_allowed", Boolean, nullable=False),
    Column("export_allowed", Boolean, nullable=False),
    Column("backup_allowed", Boolean, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint(
        "raw_blob_id",
        "storage_uri",
        name="uq_raw_storage_context_uri",
    ),
    UniqueConstraint(
        "raw_storage_object_id",
        "raw_blob_id",
        "rights_profile_record_id",
        name="uq_raw_storage_coherence",
    ),
    CheckConstraint("stored_blob_sha256 ~ '^[0-9a-f]{64}$'", name="ck_raw_storage_stored_hash"),
    CheckConstraint("storage_policy IN ('ALLOWED','EPHEMERAL')", name="ck_raw_storage_policy"),
    CheckConstraint(
        "retention_seconds IS NULL OR retention_seconds >= 0",
        name="ck_raw_storage_retention",
    ),
    schema="provenance",
)

ingestion_run = Table(
    "ingestion_run",
    metadata,
    Column(
        "ingestion_run_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column(
        "provider_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.data_provider.provider_id",
            name="fk_ingestion_run_provider",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("resource", String(120), nullable=False),
    Column("logical_run_key", String(200), nullable=False),
    Column("status", String(32), nullable=False),
    Column("scheduled_at", DateTime(timezone=True)),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("adapter_version", Text),
    Column("code_commit", CHAR(40)),
    Column("counts", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("error_code", Text),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("provider_id", "logical_run_key", name="uq_ingestion_run_logical_key"),
    CheckConstraint(
        "status IN ('PLANNED','RUNNING','SUCCEEDED','SUCCEEDED_WITH_WARNINGS',"
        "'FAILED_RETRYABLE','FAILED_PERMANENT','CANCELLED')",
        name="ck_ingestion_run_status",
    ),
    CheckConstraint(
        "code_commit IS NULL OR code_commit ~ '^[0-9a-f]{40}$'",
        name="ck_ingestion_run_code_commit",
    ),
    schema="provenance",
)

source_snapshot = Table(
    "source_snapshot",
    metadata,
    Column(
        "source_snapshot_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column(
        "ingestion_run_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.ingestion_run.ingestion_run_id",
            name="fk_source_snapshot_ingestion_run",
            ondelete="RESTRICT",
        ),
    ),
    Column("attempt_number", Integer),
    Column(
        "provider_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.data_provider.provider_id",
            name="fk_source_snapshot_provider",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("resource", String(120), nullable=False),
    Column("request_fingerprint", CHAR(64), nullable=False),
    Column("provider_generated_at", DateTime(timezone=True)),
    Column("source_updated_at", DateTime(timezone=True)),
    Column("request_started_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("stored_at", DateTime(timezone=True)),
    Column("parsed_at", DateTime(timezone=True)),
    Column("mapped_at", DateTime(timezone=True)),
    Column("usable_at", DateTime(timezone=True)),
    Column("http_status", SmallInteger),
    Column("content_type", Text),
    Column(
        "raw_blob_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.raw_blob.raw_blob_id",
            name="fk_source_snapshot_raw_blob",
            ondelete="RESTRICT",
        ),
    ),
    Column("raw_storage_policy", String(24), nullable=False),
    Column("body_sha256", CHAR(64)),
    Column("schema_fingerprint", CHAR(64)),
    Column("terms_version", Text),
    Column("rights_profile_key", Text, nullable=False),
    Column("validation_status", String(24), nullable=False),
    Column("dataset_mode", String(24), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    Column("body_size", BigInteger),
    Column("sanitized_target", Text),
    Column(
        "raw_storage_object_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.raw_storage_object.raw_storage_object_id",
            name="fk_source_snapshot_raw_storage",
            ondelete="RESTRICT",
        ),
    ),
    Column("rights_profile_version", String(40)),
    Column(
        "rights_profile_record_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.rights_profile.rights_profile_record_id",
            name="fk_source_snapshot_rights_profile",
            ondelete="RESTRICT",
        ),
    ),
    Column("adapter_version", String(40)),
    Column("contract_version", String(40)),
    Column("envelope_sha256", CHAR(64)),
    ForeignKeyConstraint(
        ["raw_storage_object_id", "raw_blob_id", "rights_profile_record_id"],
        [
            "provenance.raw_storage_object.raw_storage_object_id",
            "provenance.raw_storage_object.raw_blob_id",
            "provenance.raw_storage_object.rights_profile_record_id",
        ],
        name="fk_source_snapshot_raw_storage_coherence",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["raw_blob_id", "body_sha256", "body_size"],
        [
            "provenance.raw_blob.raw_blob_id",
            "provenance.raw_blob.body_sha256",
            "provenance.raw_blob.byte_size",
        ],
        name="fk_source_snapshot_raw_content_coherence",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["rights_profile_record_id", "rights_profile_key", "rights_profile_version"],
        [
            "provenance.rights_profile.rights_profile_record_id",
            "provenance.rights_profile.rights_profile_id",
            "provenance.rights_profile.profile_version",
        ],
        name="fk_source_snapshot_rights_profile_version",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "source_snapshot_id",
        "rights_profile_record_id",
        name="uq_source_snapshot_rights_profile",
    ),
    CheckConstraint(
        "request_fingerprint ~ '^[0-9a-f]{64}$'",
        name="ck_source_snapshot_request_hash",
    ),
    CheckConstraint(
        "body_sha256 IS NULL OR body_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_source_snapshot_body_hash",
    ),
    CheckConstraint(
        "envelope_sha256 IS NULL OR envelope_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_source_snapshot_envelope_hash",
    ),
    CheckConstraint("body_size IS NULL OR body_size >= 0", name="ck_source_snapshot_body_size"),
    CheckConstraint(
        "(ingestion_run_id IS NULL) = (attempt_number IS NULL) "
        "AND (attempt_number IS NULL OR attempt_number > 0)",
        name="ck_source_snapshot_attempt",
    ),
    CheckConstraint(
        "schema_fingerprint IS NULL OR schema_fingerprint ~ '^[0-9a-f]{64}$'",
        name="ck_source_snapshot_schema_hash",
    ),
    CheckConstraint(
        "raw_storage_policy IN ('ALLOWED','FORBIDDEN','EPHEMERAL','DELETED')",
        name="ck_source_snapshot_policy",
    ),
    CheckConstraint(
        "validation_status IN ('RECEIVED','VALID','QUARANTINED','REJECTED','USABLE')",
        name="ck_source_snapshot_validation_status",
    ),
    CheckConstraint(
        "dataset_mode IN ('LIVE_OBSERVED','RAW_OBSERVED','RECONSTRUCTED',"
        "'FINAL_OUTCOME','COUNTERFACTUAL')",
        name="ck_source_snapshot_dataset_mode",
    ),
    CheckConstraint(
        "request_started_at <= received_at "
        "AND (stored_at IS NULL OR stored_at >= received_at) "
        "AND (parsed_at IS NULL OR (parsed_at >= received_at AND "
        "(stored_at IS NULL OR parsed_at >= stored_at))) "
        "AND (mapped_at IS NULL OR (mapped_at >= received_at AND "
        "(stored_at IS NULL OR mapped_at >= stored_at) AND "
        "(parsed_at IS NULL OR mapped_at >= parsed_at))) "
        "AND (usable_at IS NULL OR (usable_at >= received_at AND "
        "(stored_at IS NULL OR usable_at >= stored_at) AND "
        "(parsed_at IS NULL OR usable_at >= parsed_at) AND "
        "(mapped_at IS NULL OR usable_at >= mapped_at)))",
        name="ck_source_snapshot_time_order",
    ),
    CheckConstraint(
        "(validation_status = 'USABLE') = (usable_at IS NOT NULL)",
        name="ck_source_snapshot_usable",
    ),
    CheckConstraint(
        "(raw_storage_policy <> 'FORBIDDEN' OR raw_storage_object_id IS NULL) "
        "AND (raw_storage_policy <> 'ALLOWED' OR body_sha256 IS NULL "
        "OR raw_blob_id IS NOT NULL) "
        "AND (rights_profile_record_id IS NULL OR raw_storage_policy <> 'ALLOWED' "
        "OR body_sha256 IS NULL OR raw_storage_object_id IS NOT NULL) "
        "AND (raw_storage_object_id IS NULL OR raw_blob_id IS NOT NULL) "
        "AND (raw_storage_object_id IS NULL OR rights_profile_record_id IS NOT NULL) "
        "AND (rights_profile_record_id IS NULL OR rights_profile_version IS NOT NULL) "
        "AND (rights_profile_record_id IS NULL OR body_sha256 IS NULL "
        "OR body_size IS NOT NULL) "
        "AND (raw_blob_id IS NULL OR body_sha256 IS NOT NULL)",
        name="ck_source_snapshot_retention",
    ),
    schema="provenance",
)

rights_decision = Table(
    "rights_decision",
    metadata,
    Column(
        "rights_decision_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column(
        "rights_profile_record_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.rights_profile.rights_profile_record_id",
            name="fk_rights_decision_profile",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("source_snapshot_id", UUID(as_uuid=True)),
    Column("capability", String(48), nullable=False),
    Column("decision", String(8), nullable=False),
    Column("reason_code", String(80), nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("context_sha256", CHAR(64), nullable=False),
    ForeignKeyConstraint(
        ["source_snapshot_id", "rights_profile_record_id"],
        [
            "provenance.source_snapshot.source_snapshot_id",
            "provenance.source_snapshot.rights_profile_record_id",
        ],
        name="fk_rights_decision_snapshot_profile",
        ondelete="RESTRICT",
    ),
    CheckConstraint("decision IN ('ALLOW','DENY')", name="ck_rights_decision_value"),
    CheckConstraint("context_sha256 ~ '^[0-9a-f]{64}$'", name="ck_rights_decision_context_hash"),
    UniqueConstraint(
        "rights_profile_record_id",
        "source_snapshot_id",
        "capability",
        name="uq_rights_decision_authority",
        postgresql_nulls_not_distinct=True,
    ),
    schema="provenance",
)

source_processing_event = Table(
    "source_processing_event",
    metadata,
    Column(
        "processing_event_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_processing_event_snapshot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("operation_id", UUID(as_uuid=True), nullable=False),
    Column(
        "previous_event_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_processing_event.processing_event_id",
            name="fk_processing_event_previous",
            ondelete="RESTRICT",
        ),
    ),
    Column("sequence_number", Integer, nullable=False),
    Column("stage", String(32), nullable=False),
    Column("outcome", String(24), nullable=False, server_default="SUCCEEDED"),
    Column("event_at", DateTime(timezone=True), nullable=False),
    Column("stage_version", String(40), nullable=False),
    Column("input_sha256", CHAR(64)),
    Column("output_sha256", CHAR(64)),
    Column("event_sha256", CHAR(64), nullable=False),
    Column("safe_details", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("error_code", String(80)),
    Column("actor", String(80), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint(
        "source_snapshot_id", "sequence_number", name="uq_processing_event_snapshot_sequence"
    ),
    UniqueConstraint(
        "processing_event_id",
        "source_snapshot_id",
        name="uq_processing_event_snapshot_scope",
    ),
    UniqueConstraint("event_sha256", name="uq_processing_event_hash"),
    CheckConstraint("sequence_number > 0", name="ck_processing_event_sequence"),
    CheckConstraint(
        "stage IN ('RECEIVED','STORED','RAW_DISCARDED','PARSED','VALIDATED','MAPPED',"
        "'PROMOTED','QUALITY_PASSED','USABLE','QUARANTINED','REJECTED','CANCELLED',"
        "'FAILED_RETRYABLE','FAILED_PERMANENT')",
        name="ck_processing_event_stage",
    ),
    CheckConstraint(
        "outcome IN ('SUCCEEDED','FAILED_RETRYABLE','FAILED_PERMANENT')",
        name="ck_processing_event_outcome",
    ),
    CheckConstraint(
        "input_sha256 IS NULL OR input_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_processing_event_input_hash",
    ),
    CheckConstraint(
        "output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_processing_event_output_hash",
    ),
    CheckConstraint("event_sha256 ~ '^[0-9a-f]{64}$'", name="ck_processing_event_event_hash"),
    CheckConstraint(
        "jsonb_typeof(safe_details) = 'object'", name="ck_processing_event_details_object"
    ),
    schema="provenance",
)

source_mapping_candidate = Table(
    "source_mapping_candidate",
    metadata,
    Column(
        "mapping_candidate_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "provider_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.data_provider.provider_id",
            name="fk_mapping_candidate_provider",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("competition_key", String(80), nullable=False),
    Column("season_code", String(32), nullable=False),
    Column("provider_product", String(64), nullable=False),
    Column("identifier_namespace", String(96), nullable=False),
    Column("entity_type", String(32), nullable=False),
    Column("external_id_text", Text, nullable=False),
    Column("planned_entity_id", UUID(as_uuid=True), nullable=False),
    Column(
        "evidence_source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_mapping_candidate_snapshot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint(
        "provider_id",
        "competition_key",
        "season_code",
        "provider_product",
        "identifier_namespace",
        "entity_type",
        "external_id_text",
        name="uq_mapping_candidate_scope",
    ),
    CheckConstraint(
        "entity_type IN ('COMPETITION','SEASON','TEAM','PLAYER','GAMEWEEK','FIXTURE')",
        name="ck_mapping_candidate_entity_type",
    ),
    schema="provenance",
)

raw_blob_deletion = Table(
    "raw_blob_deletion",
    metadata,
    Column("deletion_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column(
        "raw_blob_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.raw_blob.raw_blob_id",
            name="fk_raw_blob_deletion_raw",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("deleted_at", DateTime(timezone=True), nullable=False),
    Column("reason", Text, nullable=False),
    Column("tombstone_sha256", CHAR(64), nullable=False),
    Column("approved_by", Text, nullable=False),
    UniqueConstraint("raw_blob_id", name="uq_raw_blob_deletion_raw"),
    CheckConstraint("tombstone_sha256 ~ '^[0-9a-f]{64}$'", name="ck_raw_blob_deletion_hash"),
    schema="provenance",
)

raw_storage_deletion = Table(
    "raw_storage_deletion",
    metadata,
    Column(
        "raw_storage_deletion_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "raw_storage_object_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.raw_storage_object.raw_storage_object_id",
            name="fk_raw_storage_deletion_object",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("deleted_at", DateTime(timezone=True), nullable=False),
    Column("reason", Text, nullable=False),
    Column("tombstone_sha256", CHAR(64), nullable=False),
    Column("approved_by", Text, nullable=False),
    UniqueConstraint("raw_storage_object_id", name="uq_raw_storage_deletion_object"),
    CheckConstraint("tombstone_sha256 ~ '^[0-9a-f]{64}$'", name="ck_raw_storage_deletion_hash"),
    schema="provenance",
)


def _range_columns() -> list[Column[Any]]:
    return [
        Column("valid_during", TSTZRANGE(), nullable=False),
        Column(
            "system_during",
            TSTZRANGE(),
            nullable=False,
            server_default=text("tstzrange(transaction_timestamp(), NULL, '[)')"),
        ),
    ]


def _successor_column(pointer_name: str, target: str, fk_name: str) -> Column[Any]:
    return Column(
        pointer_name,
        UUID(as_uuid=True),
        ForeignKey(target, name=fk_name, ondelete="RESTRICT"),
    )


external_identifier = Table(
    "external_identifier",
    metadata,
    Column(
        "external_identifier_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column("canonical_entity_id", UUID(as_uuid=True), nullable=False),
    Column(
        "provider_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.data_provider.provider_id",
            name="fk_external_identifier_provider",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("provider_product", String(120), nullable=False),
    Column("identifier_namespace", String(120), nullable=False),
    Column("entity_type", String(40), nullable=False),
    Column("external_id_text", Text, nullable=False),
    *_range_columns(),
    Column("mapping_status", String(24), nullable=False),
    Column("mapping_method", String(24), nullable=False),
    Column("match_probability", Numeric(7, 6)),
    Column(
        "evidence_source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_external_identifier_snapshot",
            ondelete="RESTRICT",
        ),
    ),
    Column("reviewed_by", Text),
    Column("reviewed_at", DateTime(timezone=True)),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("is_provider_primary", Boolean, nullable=False, server_default=text("false")),
    Column("raw_example", Text),
    _successor_column(
        "superseded_by_mapping_id",
        "core.external_identifier.external_identifier_id",
        "fk_external_identifier_successor",
    ),
    Column(
        "season_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.season.season_id",
            name="fk_external_identifier_season",
            ondelete="RESTRICT",
        ),
    ),
    ForeignKeyConstraint(
        ["canonical_entity_id", "entity_type"],
        ["core.canonical_entity.entity_id", "core.canonical_entity.entity_type"],
        name="fk_external_identifier_canonical_type",
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        _canonical_range_check("valid_during"),
        name="ck_external_identifier_valid_range",
    ),
    CheckConstraint(
        _canonical_range_check("system_during"),
        name="ck_external_identifier_system_range",
    ),
    CheckConstraint(
        "mapping_status IN ('UNRESOLVED','CANDIDATE','AUTO_MATCHED','HUMAN_VERIFIED',"
        "'CONFLICTED','REJECTED','SUPERSEDED','EXPIRED')",
        name="ck_external_identifier_status",
    ),
    CheckConstraint(
        "mapping_method IN ('PROVIDER_MAPPING','DETERMINISTIC','EXACT_EXTERNAL_ID',"
        "'RULE_BASED','PROBABILISTIC','MANUAL')",
        name="ck_external_identifier_method",
    ),
    CheckConstraint(
        "match_probability IS NULL OR match_probability BETWEEN 0 AND 1",
        name="ck_external_identifier_probability",
    ),
    CheckConstraint(
        "identifier_namespace <> 'the_odds_api.bookmaker.key' OR "
        "(entity_type = 'BETTING_OPERATOR' AND season_id IS NULL "
        "AND provider_product = 'soccer_epl/odds')",
        name="ck_external_identifier_odds_operator_scope",
    ),
    CheckConstraint("first_seen_at <= last_seen_at", name="ck_external_identifier_seen_order"),
    schema="core",
)

entity_alias = Table(
    "entity_alias",
    metadata,
    Column("alias_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column(
        "canonical_entity_id",
        UUID(as_uuid=True),
        ForeignKey(
            "core.canonical_entity.entity_id",
            name="fk_entity_alias_entity",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("raw_text", Text, nullable=False),
    Column("normalized_nfc", Text, nullable=False),
    Column("match_key", Text, nullable=False),
    Column("language", String(16)),
    Column("script", String(16)),
    Column("alias_type", String(24), nullable=False),
    Column(
        "provider_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.data_provider.provider_id",
            name="fk_entity_alias_provider",
            ondelete="RESTRICT",
        ),
    ),
    *_range_columns(),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_entity_alias_snapshot",
            ondelete="RESTRICT",
        ),
    ),
    Column("confidence", Numeric(7, 6)),
    Column("is_preferred", Boolean, nullable=False, server_default=text("false")),
    _successor_column(
        "superseded_by_alias_id", "core.entity_alias.alias_id", "fk_entity_alias_successor"
    ),
    CheckConstraint(_canonical_range_check("valid_during"), name="ck_entity_alias_valid_range"),
    CheckConstraint(_canonical_range_check("system_during"), name="ck_entity_alias_system_range"),
    CheckConstraint(
        "alias_type IN ('OFFICIAL','DISPLAY','SHORT','PROVIDER','HISTORICAL','MANUAL')",
        name="ck_entity_alias_type",
    ),
    CheckConstraint(
        "confidence IS NULL OR confidence BETWEEN 0 AND 1",
        name="ck_entity_alias_confidence",
    ),
    CheckConstraint(
        "language IS NULL OR language <> '__DMF_NULL__'",
        name="ck_entity_alias_language_sentinel",
    ),
    CheckConstraint(
        "script IS NULL OR script <> '__DMF_NULL__'",
        name="ck_entity_alias_script_sentinel",
    ),
    schema="core",
)

player_team_membership = Table(
    "player_team_membership",
    metadata,
    Column("membership_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column(
        "player_id",
        UUID(as_uuid=True),
        ForeignKey("football.player.player_id", name="fk_membership_player", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "team_id",
        UUID(as_uuid=True),
        ForeignKey("football.team.team_id", name="fk_membership_team", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "season_id",
        UUID(as_uuid=True),
        ForeignKey("football.season.season_id", name="fk_membership_season", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("registration_type", String(24), nullable=False),
    Column("squad_status", String(24), nullable=False),
    Column("shirt_number", SmallInteger),
    *_range_columns(),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_membership_snapshot",
            ondelete="RESTRICT",
        ),
    ),
    _successor_column(
        "superseded_by_membership_id",
        "football.player_team_membership.membership_id",
        "fk_membership_successor",
    ),
    ForeignKeyConstraint(
        ["team_id", "season_id"],
        ["football.team_season.team_id", "football.team_season.season_id"],
        name="fk_membership_team_season",
        ondelete="RESTRICT",
    ),
    CheckConstraint(_canonical_range_check("valid_during"), name="ck_membership_valid_range"),
    CheckConstraint(_canonical_range_check("system_during"), name="ck_membership_system_range"),
    CheckConstraint(
        "registration_type IN ('PERMANENT','LOAN','YOUTH','TEMPORARY','UNKNOWN')",
        name="ck_membership_registration_type",
    ),
    CheckConstraint(
        "squad_status IN ('REGISTERED','UNREGISTERED','LEFT','UNKNOWN')",
        name="ck_membership_squad_status",
    ),
    CheckConstraint(
        "shirt_number IS NULL OR shirt_number BETWEEN 1 AND 99",
        name="ck_membership_shirt_number",
    ),
    schema="football",
)

fixture_revision = Table(
    "fixture_revision",
    metadata,
    Column(
        "fixture_revision_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column(
        "fixture_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.fixture.fixture_id",
            name="fk_fixture_revision_fixture",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("revision_number", Integer, nullable=False),
    Column("kickoff_at", DateTime(timezone=True)),
    Column("fixture_status", String(24), nullable=False),
    Column("venue", Text),
    *_range_columns(),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_fixture_revision_snapshot",
            ondelete="RESTRICT",
        ),
    ),
    _successor_column(
        "superseded_by_revision_id",
        "football.fixture_revision.fixture_revision_id",
        "fk_fixture_revision_successor",
    ),
    UniqueConstraint("fixture_id", "revision_number", name="uq_fixture_revision_number"),
    CheckConstraint("revision_number > 0", name="ck_fixture_revision_number"),
    CheckConstraint(
        "fixture_status IN ('SCHEDULED','POSTPONED','CANCELLED','STARTED','FINISHED',"
        "'ABANDONED','UNKNOWN')",
        name="ck_fixture_revision_status",
    ),
    CheckConstraint(
        _canonical_range_check("valid_during"),
        name="ck_fixture_revision_valid_range",
    ),
    CheckConstraint(
        _canonical_range_check("system_during"),
        name="ck_fixture_revision_system_range",
    ),
    schema="football",
)

fixture_gameweek_assignment = Table(
    "fixture_gameweek_assignment",
    metadata,
    Column("assignment_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column(
        "fixture_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.fixture.fixture_id", name="fk_assignment_fixture", ondelete="RESTRICT"
        ),
        nullable=False,
    ),
    Column(
        "gameweek_id",
        UUID(as_uuid=True),
        ForeignKey("fpl.gameweek.gameweek_id", name="fk_assignment_gameweek", ondelete="RESTRICT"),
    ),
    Column("assignment_status", String(24), nullable=False),
    *_range_columns(),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_assignment_snapshot",
            ondelete="RESTRICT",
        ),
    ),
    _successor_column(
        "superseded_by_assignment_id",
        "football.fixture_gameweek_assignment.assignment_id",
        "fk_assignment_successor",
    ),
    Column("season_id", UUID(as_uuid=True), nullable=False),
    ForeignKeyConstraint(
        ["fixture_id", "season_id"],
        ["football.fixture.fixture_id", "football.fixture.season_id"],
        name="fk_assignment_fixture_season",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["gameweek_id", "season_id"],
        ["fpl.gameweek.gameweek_id", "fpl.gameweek.season_id"],
        name="fk_assignment_gameweek_season",
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "assignment_status IN ('ASSIGNED','UNASSIGNED','PROVISIONAL','FINAL')",
        name="ck_assignment_status",
    ),
    CheckConstraint(
        "(assignment_status IN ('ASSIGNED','FINAL') AND gameweek_id IS NOT NULL) OR "
        "(assignment_status = 'UNASSIGNED' AND gameweek_id IS NULL) OR "
        "assignment_status = 'PROVISIONAL'",
        name="ck_assignment_gameweek_coherence",
    ),
    CheckConstraint(_canonical_range_check("valid_during"), name="ck_assignment_valid_range"),
    CheckConstraint(_canonical_range_check("system_during"), name="ck_assignment_system_range"),
    schema="football",
)

player_season = Table(
    "player_season",
    metadata,
    Column(
        "player_fpl_season_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "player_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.player.player_id", name="fk_player_season_player", ondelete="RESTRICT"
        ),
        nullable=False,
    ),
    Column(
        "season_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.season.season_id", name="fk_player_season_season", ondelete="RESTRICT"
        ),
        nullable=False,
    ),
    Column("position_code", String(24), nullable=False),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_player_season_snapshot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("player_id", "season_id", name="uq_player_season_identity"),
    UniqueConstraint("player_fpl_season_id", "season_id", name="uq_player_season_id_season"),
    schema="fpl",
)

team_observation = Table(
    "team_observation",
    metadata,
    Column(
        "team_observation_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column(
        "team_season_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.team_season.team_season_id",
            name="fk_team_observation_team_season",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("display_name", Text, nullable=False),
    Column("short_name", String(40), nullable=False),
    Column("strength", Integer),
    Column("strength_overall_home", Integer),
    Column("strength_overall_away", Integer),
    Column("strength_attack_home", Integer),
    Column("strength_attack_away", Integer),
    Column("strength_defence_home", Integer),
    Column("strength_defence_away", Integer),
    Column("position", Integer),
    Column("played", Integer),
    Column("win", Integer),
    Column("draw", Integer),
    Column("loss", Integer),
    Column("points", Integer),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("usable_at", DateTime(timezone=True), nullable=False),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_team_observation_snapshot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("contract_version", String(40), nullable=False),
    Column("missingness", JSONB, nullable=False),
    Column("semantic_sha256", CHAR(64), nullable=False),
    UniqueConstraint(
        "semantic_sha256",
        "source_snapshot_id",
        name="uq_team_observation_semantic_source",
    ),
    CheckConstraint("semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_team_observation_semantic_hash"),
    CheckConstraint("jsonb_typeof(missingness) = 'object'", name="ck_team_observation_missingness"),
    CheckConstraint("received_at <= usable_at", name="ck_team_observation_time_order"),
    schema="fpl",
)

player_observation = Table(
    "player_observation",
    metadata,
    Column(
        "player_observation_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "player_fpl_season_id",
        UUID(as_uuid=True),
        ForeignKey(
            "fpl.player_season.player_fpl_season_id",
            name="fk_player_observation_player_season",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "team_season_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.team_season.team_season_id",
            name="fk_player_observation_team_season",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("position_code", String(24), nullable=False),
    Column("price_tenths", Integer, nullable=False),
    Column("status", String(24), nullable=False),
    Column("chance_next_round", SmallInteger),
    Column("chance_this_round", SmallInteger),
    Column("news", Text),
    Column("news_added_at", DateTime(timezone=True)),
    Column("selected_by_percent", Numeric(7, 3)),
    Column("transfers_in", BigInteger),
    Column("transfers_out", BigInteger),
    Column("transfers_in_event", BigInteger),
    Column("transfers_out_event", BigInteger),
    Column("cost_change_start", Integer),
    Column("cost_change_event", Integer),
    Column("cost_change_start_fall", Integer),
    Column("cost_change_event_fall", Integer),
    Column("minutes", Integer),
    Column("total_points", Integer),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("usable_at", DateTime(timezone=True), nullable=False),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_player_observation_snapshot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("contract_version", String(40), nullable=False),
    Column("missingness", JSONB, nullable=False),
    Column("semantic_sha256", CHAR(64), nullable=False),
    UniqueConstraint(
        "semantic_sha256",
        "source_snapshot_id",
        name="uq_player_observation_semantic_source",
    ),
    CheckConstraint("price_tenths >= 0", name="ck_player_observation_price"),
    CheckConstraint(
        "chance_next_round IS NULL OR chance_next_round BETWEEN 0 AND 100",
        name="ck_player_observation_chance_next",
    ),
    CheckConstraint(
        "chance_this_round IS NULL OR chance_this_round BETWEEN 0 AND 100",
        name="ck_player_observation_chance_this",
    ),
    CheckConstraint(
        "selected_by_percent IS NULL OR selected_by_percent BETWEEN 0 AND 100",
        name="ck_player_observation_ownership",
    ),
    CheckConstraint(
        "semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_player_observation_semantic_hash"
    ),
    CheckConstraint(
        "jsonb_typeof(missingness) = 'object'", name="ck_player_observation_missingness"
    ),
    CheckConstraint("received_at <= usable_at", name="ck_player_observation_time_order"),
    schema="fpl",
)

gameweek_observation = Table(
    "gameweek_observation",
    metadata,
    Column(
        "gameweek_observation_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "gameweek_id",
        UUID(as_uuid=True),
        ForeignKey(
            "fpl.gameweek.gameweek_id", name="fk_gameweek_observation_gameweek", ondelete="RESTRICT"
        ),
        nullable=False,
    ),
    Column("source_event_id", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("deadline_at", DateTime(timezone=True), nullable=False),
    Column("finished", Boolean),
    Column("data_checked", Boolean),
    Column("is_previous", Boolean),
    Column("is_current", Boolean),
    Column("is_next", Boolean),
    Column("average_entry_score", Integer),
    Column("highest_score", Integer),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("usable_at", DateTime(timezone=True), nullable=False),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_gameweek_observation_snapshot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("contract_version", String(40), nullable=False),
    Column("missingness", JSONB, nullable=False),
    Column("semantic_sha256", CHAR(64), nullable=False),
    UniqueConstraint(
        "semantic_sha256",
        "source_snapshot_id",
        name="uq_gameweek_observation_semantic_source",
    ),
    CheckConstraint(
        "semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_gameweek_observation_semantic_hash"
    ),
    CheckConstraint(
        "jsonb_typeof(missingness) = 'object'", name="ck_gameweek_observation_missingness"
    ),
    CheckConstraint("received_at <= usable_at", name="ck_gameweek_observation_time_order"),
    schema="fpl",
)

fixture_observation = Table(
    "fixture_observation",
    metadata,
    Column(
        "fixture_observation_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "fixture_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.fixture.fixture_id",
            name="fk_fixture_observation_fixture",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("source_fixture_id", Text, nullable=False),
    Column("source_fixture_code", Text, nullable=False),
    Column("kickoff_at", DateTime(timezone=True)),
    Column("finished", Boolean, nullable=False),
    Column("started", Boolean),
    Column("finished_provisional", Boolean),
    Column("minutes", Integer),
    Column("team_h_score", Integer),
    Column("team_a_score", Integer),
    Column("team_h_difficulty", Integer),
    Column("team_a_difficulty", Integer),
    Column("provisional_start_time", Boolean),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("usable_at", DateTime(timezone=True), nullable=False),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_fixture_observation_snapshot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("contract_version", String(40), nullable=False),
    Column("missingness", JSONB, nullable=False),
    Column("semantic_sha256", CHAR(64), nullable=False),
    UniqueConstraint(
        "semantic_sha256",
        "source_snapshot_id",
        name="uq_fixture_observation_semantic_source",
    ),
    CheckConstraint(
        "semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_fixture_observation_semantic_hash"
    ),
    CheckConstraint(
        "jsonb_typeof(missingness) = 'object'", name="ck_fixture_observation_missingness"
    ),
    CheckConstraint("received_at <= usable_at", name="ck_fixture_observation_time_order"),
    schema="fpl",
)

semantic_effect_source = Table(
    "semantic_effect_source",
    metadata,
    Column(
        "semantic_effect_source_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column("effect_type", String(40), nullable=False),
    Column("semantic_sha256", CHAR(64), nullable=False),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_semantic_effect_source_snapshot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "effect_type",
        "semantic_sha256",
        "source_snapshot_id",
        name="uq_semantic_effect_source_lineage",
    ),
    CheckConstraint("semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_semantic_effect_source_hash"),
    schema="provenance",
)

semantic_observation_claim = Table(
    "semantic_observation_claim",
    metadata,
    Column(
        "semantic_observation_claim_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column("effect_type", String(40), nullable=False),
    Column("subject_key", UUID(as_uuid=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("semantic_sha256", CHAR(64), nullable=False),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_semantic_observation_claim_snapshot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    UniqueConstraint(
        "effect_type",
        "subject_key",
        "observed_at",
        name="uq_semantic_observation_claim_subject_time",
    ),
    CheckConstraint(
        "effect_type IN ('TEAM_OBSERVATION','PLAYER_OBSERVATION',"
        "'GAMEWEEK_OBSERVATION','FIXTURE_OBSERVATION')",
        name="ck_semantic_observation_claim_type",
    ),
    CheckConstraint(
        "semantic_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_semantic_observation_claim_hash",
    ),
    schema="provenance",
)

source_bundle = Table(
    "source_bundle",
    metadata,
    Column(
        "source_bundle_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column("bundle_type", String(48), nullable=False),
    Column(
        "competition_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.competition.competition_id",
            name="fk_source_bundle_competition",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "season_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.season.season_id", name="fk_source_bundle_season", ondelete="RESTRICT"
        ),
        nullable=False,
    ),
    Column("information_cutoff", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("rights_profiles", JSONB, nullable=False),
    Column(
        "rights_profile_record_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.rights_profile.rights_profile_record_id",
            name="fk_source_bundle_rights_profile",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("adapter_version", String(40), nullable=False),
    Column("contract_version", String(40), nullable=False),
    Column("quality_status", String(32), nullable=False),
    Column("semantic_sha256", CHAR(64), nullable=False),
    Column("manifest_sha256", CHAR(64), nullable=False),
    Column("code_commit", CHAR(40)),
    Column("config_sha256", CHAR(64), nullable=False),
    UniqueConstraint("manifest_sha256", name="uq_source_bundle_manifest_hash"),
    UniqueConstraint(
        "source_bundle_id",
        "rights_profile_record_id",
        name="uq_source_bundle_rights_profile",
    ),
    ForeignKeyConstraint(
        ["season_id", "competition_id"],
        ["football.season.season_id", "football.season.competition_id"],
        name="fk_source_bundle_season_competition",
        ondelete="RESTRICT",
    ),
    CheckConstraint("bundle_type = 'FPL_BOOTSTRAP_FIXTURES'", name="ck_source_bundle_type"),
    CheckConstraint(
        "quality_status IN ('PASS','PASS_WITH_WARNINGS')",
        name="ck_source_bundle_quality_status",
    ),
    CheckConstraint("semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_bundle_semantic_hash"),
    CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_bundle_manifest_hash"),
    CheckConstraint("config_sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_bundle_config_hash"),
    CheckConstraint(
        "code_commit IS NULL OR code_commit ~ '^[0-9a-f]{40}$'",
        name="ck_source_bundle_code_commit",
    ),
    schema="provenance",
)

source_bundle_member = Table(
    "source_bundle_member",
    metadata,
    Column(
        "source_bundle_member_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "source_bundle_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_bundle.source_bundle_id",
            name="fk_source_bundle_member_bundle",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_source_bundle_member_snapshot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("rights_profile_record_id", UUID(as_uuid=True), nullable=False),
    Column("role", String(16), nullable=False),
    Column("usable_at", DateTime(timezone=True), nullable=False),
    Column("payload_semantic_sha256", CHAR(64), nullable=False),
    Column("envelope_sha256", CHAR(64), nullable=False),
    Column("lifecycle_sha256", CHAR(64), nullable=False),
    Column("schema_drift", JSONB, nullable=False),
    UniqueConstraint("source_bundle_id", "role", name="uq_source_bundle_member_role"),
    UniqueConstraint(
        "source_bundle_id", "source_snapshot_id", name="uq_source_bundle_member_snapshot"
    ),
    ForeignKeyConstraint(
        ["source_bundle_id", "rights_profile_record_id"],
        [
            "provenance.source_bundle.source_bundle_id",
            "provenance.source_bundle.rights_profile_record_id",
        ],
        name="fk_source_bundle_member_bundle_rights",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["source_snapshot_id", "rights_profile_record_id"],
        [
            "provenance.source_snapshot.source_snapshot_id",
            "provenance.source_snapshot.rights_profile_record_id",
        ],
        name="fk_source_bundle_member_snapshot_rights",
        ondelete="RESTRICT",
    ),
    CheckConstraint("role IN ('BOOTSTRAP','FIXTURES')", name="ck_source_bundle_member_role"),
    CheckConstraint(
        "payload_semantic_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_source_bundle_member_payload_hash",
    ),
    CheckConstraint(
        "envelope_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_source_bundle_member_envelope_hash",
    ),
    CheckConstraint(
        "lifecycle_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_source_bundle_member_lifecycle_hash",
    ),
    schema="provenance",
)

betting_operator = Table(
    "betting_operator",
    metadata,
    *_typed_entity_columns("operator_id", "BETTING_OPERATOR"),
    Column("operator_key", String(120), nullable=False),
    Column("display_name", Text, nullable=False),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["operator_id", "entity_type"],
        ["core.canonical_entity.entity_id", "core.canonical_entity.entity_type"],
        name="fk_betting_operator_canonical_type",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("operator_key", name="uq_betting_operator_key"),
    CheckConstraint("entity_type = 'BETTING_OPERATOR'", name="ck_betting_operator_entity_type"),
    schema="betting",
)

market_definition = Table(
    "market_definition",
    metadata,
    Column(
        "market_definition_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column("definition_key", String(120), nullable=False),
    Column("definition_version", String(40), nullable=False),
    Column("scope", String(24), nullable=False),
    Column("period", String(24), nullable=False),
    Column("outcomes", JSONB, nullable=False),
    Column("description", Text, nullable=False),
    UniqueConstraint("definition_key", "definition_version", name="uq_market_definition_identity"),
    CheckConstraint(
        "definition_key = 'MATCH_RESULT_1X2' AND definition_version = '1.0.0'",
        name="ck_market_definition_reference",
    ),
    CheckConstraint("scope = 'FIXTURE'", name="ck_market_definition_scope"),
    CheckConstraint("period = 'FULL_TIME'", name="ck_market_definition_period"),
    CheckConstraint(
        'outcomes = \'["HOME","DRAW","AWAY"]\'::jsonb',
        name="ck_market_definition_outcomes",
    ),
    schema="betting",
)

settlement_profile = Table(
    "settlement_profile",
    metadata,
    Column(
        "settlement_profile_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column("profile_key", String(160), nullable=False),
    Column("profile_version", String(40), nullable=False),
    Column("period", String(24), nullable=False),
    Column("includes_extra_time", Boolean, nullable=False),
    Column("description", Text, nullable=False),
    UniqueConstraint("profile_key", "profile_version", name="uq_settlement_profile_identity"),
    CheckConstraint(
        "profile_key = 'SOCCER_FULL_TIME_90_MINUTES_REFERENCE_V1' AND profile_version = '1.0.0'",
        name="ck_settlement_profile_reference",
    ),
    CheckConstraint("period = 'FULL_TIME'", name="ck_settlement_profile_period"),
    CheckConstraint("includes_extra_time = false", name="ck_settlement_profile_no_extra_time"),
    schema="betting",
)

operator_fixture_market = Table(
    "operator_fixture_market",
    metadata,
    *_typed_entity_columns("market_id", "MARKET"),
    Column(
        "fixture_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.fixture.fixture_id", name="fk_operator_market_fixture", ondelete="RESTRICT"
        ),
        nullable=False,
    ),
    Column(
        "operator_id",
        UUID(as_uuid=True),
        ForeignKey(
            "betting.betting_operator.operator_id",
            name="fk_operator_market_operator",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "market_definition_id",
        UUID(as_uuid=True),
        ForeignKey(
            "betting.market_definition.market_definition_id",
            name="fk_operator_market_definition",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("period", String(24), nullable=False),
    Column("line", Numeric),
    Column(
        "settlement_profile_id",
        UUID(as_uuid=True),
        ForeignKey(
            "betting.settlement_profile.settlement_profile_id",
            name="fk_operator_market_settlement",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["market_id", "entity_type"],
        ["core.canonical_entity.entity_id", "core.canonical_entity.entity_type"],
        name="fk_operator_market_canonical_type",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("market_id", "fixture_id", "operator_id", name="uq_operator_market_scope"),
    UniqueConstraint("market_id", "operator_id", name="uq_operator_market_operator"),
    UniqueConstraint(
        "fixture_id",
        "operator_id",
        "market_definition_id",
        "period",
        "line",
        "settlement_profile_id",
        name="uq_operator_market_identity",
        postgresql_nulls_not_distinct=True,
    ),
    CheckConstraint("entity_type = 'MARKET'", name="ck_operator_market_entity_type"),
    CheckConstraint("period = 'FULL_TIME'", name="ck_operator_market_period"),
    CheckConstraint("line IS NULL", name="ck_operator_market_no_line"),
    schema="betting",
)

market_selection = Table(
    "market_selection",
    metadata,
    *_typed_entity_columns("selection_id", "SELECTION"),
    Column(
        "market_id",
        UUID(as_uuid=True),
        ForeignKey(
            "betting.operator_fixture_market.market_id",
            name="fk_market_selection_market",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("outcome", String(16), nullable=False),
    ForeignKeyConstraint(
        ["selection_id", "entity_type"],
        ["core.canonical_entity.entity_id", "core.canonical_entity.entity_type"],
        name="fk_market_selection_canonical_type",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("market_id", "outcome", name="uq_market_selection_outcome"),
    UniqueConstraint("selection_id", "market_id", name="uq_market_selection_scope"),
    UniqueConstraint(
        "selection_id", "market_id", "outcome", name="uq_market_selection_outcome_scope"
    ),
    CheckConstraint("entity_type = 'SELECTION'", name="ck_market_selection_entity_type"),
    CheckConstraint("outcome IN ('HOME','DRAW','AWAY')", name="ck_market_selection_outcome"),
    schema="betting",
)

provider_market_representation = Table(
    "provider_market_representation",
    metadata,
    Column(
        "provider_market_representation_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "provider_id",
        UUID(as_uuid=True),
        ForeignKey("provenance.data_provider.provider_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "event_mapping_id",
        UUID(as_uuid=True),
        ForeignKey("core.external_identifier.external_identifier_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "operator_mapping_id",
        UUID(as_uuid=True),
        ForeignKey("core.external_identifier.external_identifier_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "market_id",
        UUID(as_uuid=True),
        ForeignKey("betting.operator_fixture_market.market_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("provider_market_key", String(120), nullable=False),
    Column("representation_version", String(40), nullable=False),
    Column("mapping_plan_sha256", CHAR(64), nullable=False),
    UniqueConstraint(
        "provider_id",
        "event_mapping_id",
        "operator_mapping_id",
        "provider_market_key",
        "representation_version",
        name="uq_provider_market_representation",
    ),
    UniqueConstraint(
        "provider_market_representation_id",
        "mapping_plan_sha256",
        name="uq_provider_market_representation_plan",
    ),
    CheckConstraint("provider_market_key = 'h2h'", name="ck_provider_market_key"),
    CheckConstraint(
        "mapping_plan_sha256 ~ '^[0-9a-f]{64}$'", name="ck_provider_market_mapping_hash"
    ),
    schema="betting",
)

odds_publication_batch = Table(
    "odds_publication_batch",
    metadata,
    Column(
        "publication_batch_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey("provenance.source_snapshot.source_snapshot_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("activation_event_id", UUID(as_uuid=True), nullable=False),
    Column("mapping_cutoff", DateTime(timezone=True), nullable=False),
    Column("mapping_plan_id", String(160), nullable=False),
    Column("mapping_plan_sha256", CHAR(64), nullable=False),
    Column("mapping_plan_approved_at", DateTime(timezone=True), nullable=False),
    Column("mapping_evidence_class", String(24), nullable=False),
    Column("mapping_reviewer", String(160), nullable=False),
    Column("mapping_status", String(40), nullable=False),
    Column(
        "activation_xid",
        BigInteger,
        nullable=False,
        server_default=text("(pg_current_xact_id()::text)::bigint"),
    ),
    Column(
        "activated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["activation_event_id", "source_snapshot_id"],
        [
            "provenance.source_processing_event.processing_event_id",
            "provenance.source_processing_event.source_snapshot_id",
        ],
        name="fk_odds_publication_batch_activation",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("source_snapshot_id", name="uq_odds_publication_batch_snapshot"),
    UniqueConstraint("activation_event_id", name="uq_odds_publication_batch_event"),
    UniqueConstraint(
        "publication_batch_id",
        "source_snapshot_id",
        name="uq_odds_publication_batch_scope",
    ),
    UniqueConstraint(
        "publication_batch_id",
        "mapping_plan_sha256",
        name="uq_odds_publication_batch_plan",
    ),
    CheckConstraint(
        "mapping_plan_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_odds_publication_batch_mapping_hash",
    ),
    CheckConstraint(
        "mapping_evidence_class IN ('TEST_ONLY','OFFICIAL','APPROVED_MANUAL')",
        name="ck_odds_publication_batch_evidence_class",
    ),
    CheckConstraint(
        "mapping_status IN ('APPROVED_FOR_TEST','APPROVED')",
        name="ck_odds_publication_batch_mapping_status",
    ),
    CheckConstraint(
        "mapping_plan_approved_at <= mapping_cutoff",
        name="ck_odds_publication_batch_approval_cutoff",
    ),
    schema="betting",
)

odds_publication_attestation = Table(
    "odds_publication_attestation",
    metadata,
    Column(
        "publication_batch_id",
        UUID(as_uuid=True),
        ForeignKey("betting.odds_publication_batch.publication_batch_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("usable_at", DateTime(timezone=True), nullable=False),
    Column(
        "attestation_xid",
        BigInteger,
        nullable=False,
        server_default=text("(pg_current_xact_id()::text)::bigint"),
    ),
    Column(
        "recorded_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    schema="betting",
)

operator_market_observation = Table(
    "operator_market_observation",
    metadata,
    Column(
        "book_observation_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "market_id",
        UUID(as_uuid=True),
        ForeignKey("betting.operator_fixture_market.market_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey("provenance.source_snapshot.source_snapshot_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("publication_batch_id", UUID(as_uuid=True)),
    Column(
        "provider_market_representation_id",
        UUID(as_uuid=True),
        ForeignKey(
            "betting.provider_market_representation.provider_market_representation_id",
            name="fk_book_observation_provider_rep",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("market_state", String(24), nullable=False),
    Column("provider_observed_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("usable_at", DateTime(timezone=True)),
    Column("missing_outcomes", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("semantic_sha256", CHAR(64), nullable=False),
    Column("source_semantic_sha256", CHAR(64), nullable=False),
    Column("contract_version", String(48), nullable=False),
    Column(
        "rights_profile_record_id",
        UUID(as_uuid=True),
        ForeignKey("provenance.rights_profile.rights_profile_record_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("source_snapshot_id", "market_id", name="uq_book_observation_source_market"),
    UniqueConstraint(
        "book_observation_id",
        "source_snapshot_id",
        "market_id",
        name="uq_book_observation_scope",
    ),
    UniqueConstraint(
        "provider_market_representation_id",
        "publication_batch_id",
        name="uq_book_observation_representation_batch",
    ),
    UniqueConstraint(
        "book_observation_id",
        "source_snapshot_id",
        name="uq_book_observation_snapshot_scope",
    ),
    ForeignKeyConstraint(
        ["publication_batch_id", "source_snapshot_id"],
        [
            "betting.odds_publication_batch.publication_batch_id",
            "betting.odds_publication_batch.source_snapshot_id",
        ],
        name="fk_book_observation_publication_batch",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["source_snapshot_id", "rights_profile_record_id"],
        [
            "provenance.source_snapshot.source_snapshot_id",
            "provenance.source_snapshot.rights_profile_record_id",
        ],
        name="fk_book_observation_snapshot_rights",
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "market_state IN ('COMPLETE','INCOMPLETE','SUSPENDED','UNSUPPORTED','UNAVAILABLE')",
        name="ck_book_observation_state",
    ),
    CheckConstraint(
        "provider_observed_at <= received_at AND "
        "((publication_batch_id IS NULL AND usable_at IS NOT NULL AND received_at <= usable_at) "
        "OR (publication_batch_id IS NOT NULL AND usable_at IS NULL))",
        name="ck_book_observation_time_order",
    ),
    CheckConstraint("jsonb_typeof(missing_outcomes) = 'array'", name="ck_book_missing_outcomes"),
    CheckConstraint("semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_book_semantic_hash"),
    CheckConstraint(
        "source_semantic_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_book_source_semantic_hash",
    ),
    CheckConstraint(
        "contract_version = 'the-odds-api-v4-reference-v1'",
        name="ck_book_contract_version",
    ),
    schema="betting",
)

odds_mapping_dependency = Table(
    "odds_mapping_dependency",
    metadata,
    Column("provider_market_representation_id", UUID(as_uuid=True), primary_key=True),
    Column("publication_batch_id", UUID(as_uuid=True), primary_key=True),
    Column("mapping_plan_sha256", CHAR(64), nullable=False),
    Column(
        "fixture_lookup_mapping_id",
        UUID(as_uuid=True),
        ForeignKey(
            "core.external_identifier.external_identifier_id",
            name="fk_odds_mapping_dependency_fixture_mapping",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "home_team_mapping_id",
        UUID(as_uuid=True),
        ForeignKey(
            "core.external_identifier.external_identifier_id",
            name="fk_odds_mapping_dependency_home_mapping",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "away_team_mapping_id",
        UUID(as_uuid=True),
        ForeignKey(
            "core.external_identifier.external_identifier_id",
            name="fk_odds_mapping_dependency_away_mapping",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "fixture_observation_id",
        UUID(as_uuid=True),
        ForeignKey(
            "fpl.fixture_observation.fixture_observation_id",
            name="fk_odds_mapping_dependency_fixture_observation",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("expected_commence_time", DateTime(timezone=True), nullable=False),
    Column("dependency_sha256", CHAR(64), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["provider_market_representation_id", "mapping_plan_sha256"],
        [
            "betting.provider_market_representation.provider_market_representation_id",
            "betting.provider_market_representation.mapping_plan_sha256",
        ],
        name="fk_odds_mapping_dependency_representation_plan",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["publication_batch_id", "mapping_plan_sha256"],
        [
            "betting.odds_publication_batch.publication_batch_id",
            "betting.odds_publication_batch.mapping_plan_sha256",
        ],
        name="fk_odds_mapping_dependency_batch_plan",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["provider_market_representation_id", "publication_batch_id"],
        [
            "betting.operator_market_observation.provider_market_representation_id",
            "betting.operator_market_observation.publication_batch_id",
        ],
        name="fk_odds_mapping_dependency_book",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    ),
    CheckConstraint(
        "mapping_plan_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_odds_mapping_dependency_plan_hash",
    ),
    CheckConstraint(
        "dependency_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_odds_mapping_dependency_hash",
    ),
    CheckConstraint(
        "home_team_mapping_id <> away_team_mapping_id",
        name="ck_odds_mapping_dependency_distinct_teams",
    ),
    schema="betting",
)

odds_observation = Table(
    "odds_observation",
    metadata,
    Column(
        "odds_observation_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column("book_observation_id", UUID(as_uuid=True), nullable=False),
    Column("source_snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("publication_batch_id", UUID(as_uuid=True)),
    Column(
        "fixture_id",
        UUID(as_uuid=True),
        ForeignKey("football.fixture.fixture_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("market_id", UUID(as_uuid=True), nullable=False),
    Column("selection_id", UUID(as_uuid=True), nullable=False),
    Column(
        "operator_id",
        UUID(as_uuid=True),
        ForeignKey("betting.betting_operator.operator_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("outcome", String(16), nullable=False),
    Column("decimal_odds", Numeric, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("usable_at", DateTime(timezone=True)),
    Column("source_semantic_sha256", CHAR(64), nullable=False),
    Column("contract_version", String(48), nullable=False),
    Column(
        "rights_profile_record_id",
        UUID(as_uuid=True),
        ForeignKey("provenance.rights_profile.rights_profile_record_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["publication_batch_id", "source_snapshot_id"],
        [
            "betting.odds_publication_batch.publication_batch_id",
            "betting.odds_publication_batch.source_snapshot_id",
        ],
        name="fk_odds_observation_publication_batch",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["book_observation_id", "source_snapshot_id", "market_id"],
        [
            "betting.operator_market_observation.book_observation_id",
            "betting.operator_market_observation.source_snapshot_id",
            "betting.operator_market_observation.market_id",
        ],
        name="fk_odds_observation_book_scope",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["selection_id", "market_id"],
        ["betting.market_selection.selection_id", "betting.market_selection.market_id"],
        name="fk_odds_observation_selection_scope",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["selection_id", "market_id", "outcome"],
        [
            "betting.market_selection.selection_id",
            "betting.market_selection.market_id",
            "betting.market_selection.outcome",
        ],
        name="fk_odds_observation_selection_outcome",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["market_id", "fixture_id", "operator_id"],
        [
            "betting.operator_fixture_market.market_id",
            "betting.operator_fixture_market.fixture_id",
            "betting.operator_fixture_market.operator_id",
        ],
        name="fk_odds_observation_market_scope",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["source_snapshot_id", "rights_profile_record_id"],
        [
            "provenance.source_snapshot.source_snapshot_id",
            "provenance.source_snapshot.rights_profile_record_id",
        ],
        name="fk_odds_observation_snapshot_rights",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "source_snapshot_id",
        "market_id",
        "selection_id",
        name="uq_odds_observation_source_effect",
    ),
    UniqueConstraint(
        "odds_observation_id",
        "source_snapshot_id",
        name="uq_odds_observation_snapshot_scope",
    ),
    UniqueConstraint(
        "odds_observation_id",
        "source_snapshot_id",
        "fixture_id",
        name="uq_odds_observation_snapshot_fixture_scope",
    ),
    CheckConstraint("outcome IN ('HOME','DRAW','AWAY')", name="ck_odds_observation_outcome"),
    CheckConstraint(
        "decimal_odds > 1 AND decimal_odds <> 'NaN'::numeric "
        "AND decimal_odds <> 'Infinity'::numeric AND decimal_odds <> '-Infinity'::numeric",
        name="ck_odds_observation_price",
    ),
    CheckConstraint(
        "observed_at <= received_at AND "
        "((publication_batch_id IS NULL AND usable_at IS NOT NULL AND received_at <= usable_at) "
        "OR (publication_batch_id IS NOT NULL AND usable_at IS NULL))",
        name="ck_odds_observation_time_order",
    ),
    CheckConstraint(
        "source_semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_odds_observation_source_hash"
    ),
    CheckConstraint(
        "contract_version = 'the-odds-api-v4-reference-v1'",
        name="ck_odds_observation_contract_version",
    ),
    schema="betting",
)

market_normalisation_policy = Table(
    "market_normalisation_policy",
    metadata,
    Column("policy_sha256", CHAR(64), primary_key=True),
    Column("policy_id", String(120), nullable=False),
    Column("policy_version", String(40), nullable=False),
    Column("policy_document", JSONB, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("policy_id", "policy_version", name="uq_market_normalisation_policy_identity"),
    CheckConstraint("policy_sha256 ~ '^[0-9a-f]{64}$'", name="ck_market_normalisation_policy_hash"),
    CheckConstraint(
        "jsonb_typeof(policy_document) = 'object'",
        name="ck_market_normalisation_policy_document",
    ),
    schema="betting",
)

market_normalisation_run = Table(
    "market_normalisation_run",
    metadata,
    Column(
        "normalisation_run_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "fixture_id",
        UUID(as_uuid=True),
        ForeignKey("football.fixture.fixture_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("market_definition", String(40), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("mapping_cutoff", DateTime(timezone=True), nullable=False),
    Column(
        "policy_sha256",
        CHAR(64),
        ForeignKey("betting.market_normalisation_policy.policy_sha256", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("code_identity", String(160), nullable=False),
    Column("input_signature_sha256", CHAR(64), nullable=False, unique=True),
    Column("semantic_result_sha256", CHAR(64), nullable=False),
    Column("status", String(24), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    Column(
        "published_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint(
        "normalisation_run_id",
        "fixture_id",
        name="uq_market_normalisation_run_scope",
    ),
    CheckConstraint(
        "market_definition = 'FULL_TIME_1X2'",
        name="ck_market_normalisation_run_definition",
    ),
    CheckConstraint(
        "input_signature_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_market_normalisation_run_input_hash",
    ),
    CheckConstraint(
        "semantic_result_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_market_normalisation_run_result_hash",
    ),
    CheckConstraint(
        "status IN ('NORMALISED','DEGRADED','INSUFFICIENT','BLOCKED')",
        name="ck_market_normalisation_run_status",
    ),
    schema="betting",
)

market_normalisation_source = Table(
    "market_normalisation_source",
    metadata,
    Column(
        "normalisation_run_id",
        UUID(as_uuid=True),
        ForeignKey("betting.market_normalisation_run.normalisation_run_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("odds_observation_id", UUID(as_uuid=True), primary_key=True),
    Column("source_snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("fixture_id", UUID(as_uuid=True), nullable=False),
    UniqueConstraint(
        "normalisation_run_id",
        "odds_observation_id",
        "source_snapshot_id",
        "fixture_id",
        name="uq_market_normalisation_source_scope",
    ),
    ForeignKeyConstraint(
        ["odds_observation_id", "source_snapshot_id"],
        [
            "betting.odds_observation.odds_observation_id",
            "betting.odds_observation.source_snapshot_id",
        ],
        name="fk_market_normalisation_source_observation",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["normalisation_run_id", "fixture_id"],
        [
            "betting.market_normalisation_run.normalisation_run_id",
            "betting.market_normalisation_run.fixture_id",
        ],
        name="fk_market_normalisation_source_run_fixture",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["odds_observation_id", "source_snapshot_id", "fixture_id"],
        [
            "betting.odds_observation.odds_observation_id",
            "betting.odds_observation.source_snapshot_id",
            "betting.odds_observation.fixture_id",
        ],
        name="fk_market_normalisation_source_observation_fixture",
        ondelete="RESTRICT",
    ),
    schema="betting",
)

market_normalisation_book_source = Table(
    "market_normalisation_book_source",
    metadata,
    Column("normalisation_run_id", UUID(as_uuid=True), primary_key=True),
    Column("book_observation_id", UUID(as_uuid=True), primary_key=True),
    Column("source_snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("fixture_id", UUID(as_uuid=True), nullable=False),
    ForeignKeyConstraint(
        ["book_observation_id", "source_snapshot_id"],
        [
            "betting.operator_market_observation.book_observation_id",
            "betting.operator_market_observation.source_snapshot_id",
        ],
        name="fk_market_normalisation_book_source_book",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["normalisation_run_id", "fixture_id"],
        [
            "betting.market_normalisation_run.normalisation_run_id",
            "betting.market_normalisation_run.fixture_id",
        ],
        name="fk_market_normalisation_book_source_run_fixture",
        ondelete="RESTRICT",
    ),
    schema="betting",
)

normalised_operator_market = Table(
    "normalised_operator_market",
    metadata,
    Column(
        "normalised_operator_market_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "normalisation_run_id",
        UUID(as_uuid=True),
        ForeignKey("betting.market_normalisation_run.normalisation_run_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("fixture_id", UUID(as_uuid=True), nullable=False),
    Column("market_id", UUID(as_uuid=True), nullable=False),
    Column("provider_id", UUID(as_uuid=True), nullable=False),
    Column("operator_id", UUID(as_uuid=True), nullable=False),
    Column("operator_key", String(120), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("usable_at", DateTime(timezone=True), nullable=False),
    Column("primary_method", String(24), nullable=False),
    Column("fallback_used", Boolean, nullable=False),
    Column("raw_booksum", Numeric(60, 50), nullable=False),
    Column("overround", Numeric(60, 50), nullable=False),
    Column("power_exponent", Numeric(60, 50)),
    Column("input_signature_sha256", CHAR(64), nullable=False),
    Column("result_sha256", CHAR(64), nullable=False),
    ForeignKeyConstraint(
        ["normalisation_run_id", "fixture_id"],
        [
            "betting.market_normalisation_run.normalisation_run_id",
            "betting.market_normalisation_run.fixture_id",
        ],
        name="fk_normalised_operator_run_fixture",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["market_id", "fixture_id", "operator_id"],
        [
            "betting.operator_fixture_market.market_id",
            "betting.operator_fixture_market.fixture_id",
            "betting.operator_fixture_market.operator_id",
        ],
        name="fk_normalised_operator_market_scope",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["provider_id"],
        ["provenance.data_provider.provider_id"],
        name="fk_normalised_operator_provider",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "normalisation_run_id", "operator_id", name="uq_normalised_operator_run_operator"
    ),
    UniqueConstraint(
        "normalised_operator_market_id",
        "normalisation_run_id",
        name="uq_normalised_operator_scope",
    ),
    CheckConstraint(
        "primary_method IN ('POWER','PROPORTIONAL')",
        name="ck_normalised_operator_primary_method",
    ),
    CheckConstraint(
        "input_signature_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_normalised_operator_input_hash",
    ),
    CheckConstraint(
        "result_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_normalised_operator_result_hash",
    ),
    CheckConstraint(
        "raw_booksum >= 0 AND raw_booksum <> 'NaN'::numeric "
        "AND raw_booksum <> 'Infinity'::numeric "
        "AND raw_booksum <> '-Infinity'::numeric",
        name="ck_normalised_operator_raw_booksum_finite",
    ),
    CheckConstraint(
        "overround <> 'NaN'::numeric AND overround <> 'Infinity'::numeric "
        "AND overround <> '-Infinity'::numeric AND overround = raw_booksum - 1",
        name="ck_normalised_operator_overround_coherence",
    ),
    CheckConstraint(
        "(fallback_used AND primary_method = 'PROPORTIONAL' AND power_exponent IS NULL) "
        "OR (NOT fallback_used AND primary_method = 'POWER' "
        "AND power_exponent IS NOT NULL AND power_exponent > 0 "
        "AND power_exponent <> 'NaN'::numeric "
        "AND power_exponent <> 'Infinity'::numeric "
        "AND power_exponent <> '-Infinity'::numeric)",
        name="ck_normalised_operator_power_state",
    ),
    schema="betting",
)

normalised_operator_outcome = Table(
    "normalised_operator_outcome",
    metadata,
    Column("normalised_operator_market_id", UUID(as_uuid=True), primary_key=True),
    Column("normalisation_run_id", UUID(as_uuid=True), nullable=False),
    Column("outcome", String(16), primary_key=True),
    Column("decimal_odds", Numeric, nullable=False),
    Column("raw_implied_probability", Numeric(60, 50), nullable=False),
    Column("proportional_probability", Numeric(13, 12), nullable=False),
    Column("market_probability", Numeric(13, 12), nullable=False),
    ForeignKeyConstraint(
        ["normalised_operator_market_id", "normalisation_run_id"],
        [
            "betting.normalised_operator_market.normalised_operator_market_id",
            "betting.normalised_operator_market.normalisation_run_id",
        ],
        name="fk_normalised_operator_outcome_scope",
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "outcome IN ('HOME','DRAW','AWAY')",
        name="ck_normalised_operator_outcome_name",
    ),
    CheckConstraint(
        "decimal_odds > 1 AND decimal_odds <> 'NaN'::numeric "
        "AND decimal_odds <> 'Infinity'::numeric "
        "AND decimal_odds <> '-Infinity'::numeric",
        name="ck_normalised_operator_outcome_decimal_odds_finite",
    ),
    CheckConstraint(
        "raw_implied_probability BETWEEN 0 AND 1",
        name="ck_normalised_operator_outcome_raw_probability",
    ),
    CheckConstraint(
        "proportional_probability BETWEEN 0 AND 1",
        name="ck_normalised_operator_outcome_proportional_probability",
    ),
    CheckConstraint(
        "market_probability BETWEEN 0 AND 1",
        name="ck_normalised_operator_outcome_market_probability",
    ),
    schema="betting",
)

normalised_operator_market_source = Table(
    "normalised_operator_market_source",
    metadata,
    Column("normalised_operator_market_id", UUID(as_uuid=True), primary_key=True),
    Column("normalisation_run_id", UUID(as_uuid=True), nullable=False),
    Column("odds_observation_id", UUID(as_uuid=True), primary_key=True),
    Column("source_snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("fixture_id", UUID(as_uuid=True), nullable=False),
    ForeignKeyConstraint(
        ["normalised_operator_market_id", "normalisation_run_id"],
        [
            "betting.normalised_operator_market.normalised_operator_market_id",
            "betting.normalised_operator_market.normalisation_run_id",
        ],
        name="fk_normalised_operator_source_parent",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        [
            "normalisation_run_id",
            "odds_observation_id",
            "source_snapshot_id",
            "fixture_id",
        ],
        [
            "betting.market_normalisation_source.normalisation_run_id",
            "betting.market_normalisation_source.odds_observation_id",
            "betting.market_normalisation_source.source_snapshot_id",
            "betting.market_normalisation_source.fixture_id",
        ],
        name="fk_normalised_operator_source_run_source",
        ondelete="RESTRICT",
    ),
    schema="betting",
)

market_consensus_result = Table(
    "market_consensus_result",
    metadata,
    Column(
        "normalisation_run_id",
        UUID(as_uuid=True),
        ForeignKey("betting.market_normalisation_run.normalisation_run_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("provider_count", Integer, nullable=False),
    Column("operator_count", Integer, nullable=False),
    Column("eligible_operator_count", Integer, nullable=False),
    Column("operator_disagreement", Numeric(13, 12), nullable=False),
    Column("method_disagreement", Numeric(13, 12), nullable=False),
    Column("market_disagreement", Numeric(13, 12), nullable=False),
    Column("minimum_age_seconds", Integer, nullable=False),
    Column("maximum_age_seconds", Integer, nullable=False),
    Column("confidence_grade", CHAR(1), nullable=False),
    Column("input_signature_sha256", CHAR(64), nullable=False),
    Column("result_sha256", CHAR(64), nullable=False),
    CheckConstraint("provider_count >= 1", name="ck_market_consensus_provider_count"),
    CheckConstraint("operator_count >= 1", name="ck_market_consensus_operator_count"),
    CheckConstraint("eligible_operator_count >= 1", name="ck_market_consensus_eligible_count"),
    CheckConstraint(
        "operator_disagreement BETWEEN 0 AND 1",
        name="ck_market_consensus_operator_disagreement",
    ),
    CheckConstraint(
        "method_disagreement BETWEEN 0 AND 1",
        name="ck_market_consensus_method_disagreement",
    ),
    CheckConstraint(
        "market_disagreement BETWEEN 0 AND 1",
        name="ck_market_consensus_market_disagreement",
    ),
    CheckConstraint(
        "market_disagreement = GREATEST(operator_disagreement, method_disagreement)",
        name="ck_market_consensus_disagreement_coherence",
    ),
    CheckConstraint("minimum_age_seconds >= 0", name="ck_market_consensus_minimum_age"),
    CheckConstraint(
        "maximum_age_seconds >= minimum_age_seconds",
        name="ck_market_consensus_maximum_age",
    ),
    CheckConstraint(
        "confidence_grade IN ('A','B','C','D')",
        name="ck_market_consensus_confidence_grade",
    ),
    CheckConstraint(
        "input_signature_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_market_consensus_input_hash",
    ),
    CheckConstraint(
        "result_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_market_consensus_result_hash",
    ),
    schema="betting",
)

market_consensus_outcome = Table(
    "market_consensus_outcome",
    metadata,
    Column(
        "normalisation_run_id",
        UUID(as_uuid=True),
        ForeignKey("betting.market_consensus_result.normalisation_run_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("outcome", String(16), primary_key=True),
    Column("consensus_probability", Numeric(13, 12), nullable=False),
    Column("lower_bound", Numeric(13, 12), nullable=False),
    Column("upper_bound", Numeric(13, 12), nullable=False),
    CheckConstraint(
        "outcome IN ('HOME','DRAW','AWAY')",
        name="ck_market_consensus_outcome_name",
    ),
    CheckConstraint(
        "consensus_probability BETWEEN 0 AND 1",
        name="ck_market_consensus_outcome_probability",
    ),
    CheckConstraint(
        "lower_bound BETWEEN 0 AND 1",
        name="ck_market_consensus_outcome_lower_bound",
    ),
    CheckConstraint(
        "upper_bound BETWEEN 0 AND 1",
        name="ck_market_consensus_outcome_upper_bound",
    ),
    CheckConstraint(
        "lower_bound <= consensus_probability AND consensus_probability <= upper_bound",
        name="ck_market_consensus_outcome_bounds",
    ),
    schema="betting",
)

market_normalisation_exclusion = Table(
    "market_normalisation_exclusion",
    metadata,
    Column(
        "normalisation_run_id",
        UUID(as_uuid=True),
        ForeignKey("betting.market_normalisation_run.normalisation_run_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("sequence_number", Integer, primary_key=True),
    Column("operator_key", String(120), nullable=False),
    Column("reason", String(40), nullable=False),
    CheckConstraint("sequence_number > 0", name="ck_market_normalisation_exclusion_sequence"),
    CheckConstraint(
        "reason IN ('INCOMPLETE','STALE','UNSUPPORTED','SUSPENDED','UNAVAILABLE',"
        "'RIGHTS_BLOCKED','QUALITY_BLOCKED','MAPPING_UNAVAILABLE',"
        "'FUTURE_OBSERVATION','DUPLICATE_OPERATOR')",
        name="ck_market_normalisation_exclusion_reason",
    ),
    schema="betting",
)

market_normalisation_warning = Table(
    "market_normalisation_warning",
    metadata,
    Column(
        "normalisation_run_id",
        UUID(as_uuid=True),
        ForeignKey("betting.market_normalisation_run.normalisation_run_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("sequence_number", Integer, primary_key=True),
    Column("warning_code", String(120), nullable=False),
    CheckConstraint("sequence_number > 0", name="ck_market_normalisation_warning_sequence"),
    schema="betting",
)

provider_quota_observation = Table(
    "provider_quota_observation",
    metadata,
    Column(
        "quota_observation_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey("provenance.source_snapshot.source_snapshot_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "provider_id",
        UUID(as_uuid=True),
        ForeignKey("provenance.data_provider.provider_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("remaining", Integer, nullable=False),
    Column("used", Integer, nullable=False),
    Column("last_cost", Integer, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("source", String(32), nullable=False),
    Column("request_fingerprint", CHAR(64), nullable=False),
    UniqueConstraint("source_snapshot_id", name="uq_quota_observation_snapshot"),
    CheckConstraint(
        "remaining >= 0 AND used >= 0 AND last_cost >= 0 AND last_cost <= used",
        name="ck_quota_observation_values",
    ),
    CheckConstraint(
        "source IN ('RESPONSE_HEADERS','SYNTHETIC_FIXTURE')",
        name="ck_quota_observation_source",
    ),
    CheckConstraint(
        "request_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_quota_observation_request_hash"
    ),
    schema="betting",
)

data_quality_issue = Table(
    "data_quality_issue",
    metadata,
    Column(
        "data_quality_issue_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "source_snapshot_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_snapshot.source_snapshot_id",
            name="fk_data_quality_snapshot",
            ondelete="RESTRICT",
        ),
    ),
    Column(
        "canonical_entity_id",
        UUID(as_uuid=True),
        ForeignKey(
            "core.canonical_entity.entity_id",
            name="fk_data_quality_entity",
            ondelete="RESTRICT",
        ),
    ),
    Column(
        "ingestion_run_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.ingestion_run.ingestion_run_id",
            name="fk_data_quality_ingestion_run",
            ondelete="RESTRICT",
        ),
    ),
    Column("issue_type", String(80), nullable=False),
    Column("severity", String(12), nullable=False),
    Column("status", String(20), nullable=False),
    Column("detected_at", DateTime(timezone=True), nullable=False),
    Column("resolved_at", DateTime(timezone=True)),
    Column("owner", Text),
    Column("decision_impact", Text, nullable=False),
    Column("details", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "source_bundle_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.source_bundle.source_bundle_id",
            name="fk_data_quality_source_bundle",
            ondelete="RESTRICT",
        ),
    ),
    Column("subject_scope", String(32), nullable=False),
    Column("stage", String(40), nullable=False),
    Column("message", Text, nullable=False),
    Column("review_at", DateTime(timezone=True)),
    CheckConstraint(
        "severity IN ('P0','P1','P2','P3')",
        name="ck_data_quality_severity",
    ),
    CheckConstraint(
        "status IN ('OPEN','ACKNOWLEDGED','RESOLVED','SUPERSEDED')",
        name="ck_data_quality_status",
    ),
    CheckConstraint(
        "resolved_at IS NULL OR resolved_at >= detected_at",
        name="ck_data_quality_resolution",
    ),
    CheckConstraint(
        "(subject_scope = 'SOURCE_SNAPSHOT' AND source_snapshot_id IS NOT NULL) OR "
        "(subject_scope = 'INGESTION_RUN' AND ingestion_run_id IS NOT NULL) OR "
        "(subject_scope = 'CANONICAL_ENTITY' AND canonical_entity_id IS NOT NULL) OR "
        "(subject_scope = 'SOURCE_BUNDLE' AND source_bundle_id IS NOT NULL) OR "
        "(subject_scope = 'GLOBAL_SYSTEM' AND source_snapshot_id IS NULL "
        "AND ingestion_run_id IS NULL AND canonical_entity_id IS NULL "
        "AND source_bundle_id IS NULL)",
        name="ck_data_quality_subject",
    ),
    schema="core",
)

ruleset_artifact = Table(
    "ruleset_artifact",
    metadata,
    Column(
        "ruleset_artifact_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column("ruleset_id", String(100), nullable=False),
    Column("ruleset_version", String(80), nullable=False),
    Column("schema_version", String(40), nullable=False),
    Column("source_ruleset_hash", CHAR(64), nullable=False),
    Column("artifact_uri", Text, nullable=False),
    Column("artifact_sha256", CHAR(64), nullable=False),
    Column("ruleset_status", String(24), nullable=False),
    Column("registered_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "ruleset_id",
        "ruleset_version",
        name="uq_ruleset_artifact_identity",
    ),
    CheckConstraint(
        "source_ruleset_hash ~ '^[0-9a-f]{64}$'",
        name="ck_ruleset_artifact_source_hash",
    ),
    CheckConstraint("artifact_sha256 ~ '^[0-9a-f]{64}$'", name="ck_ruleset_artifact_hash"),
    schema="provenance",
)

ruleset_activation = Table(
    "ruleset_activation",
    metadata,
    Column(
        "ruleset_activation_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "ruleset_artifact_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.ruleset_artifact.ruleset_artifact_id",
            name="fk_ruleset_activation_artifact",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("active_ruleset_hash", CHAR(64), nullable=False),
    Column("approval_sha256", CHAR(64), nullable=False),
    Column("activation_manifest_sha256", CHAR(64), nullable=False),
    Column("approval_uri", Text, nullable=False),
    Column("activation_manifest_uri", Text, nullable=False),
    Column("approved_by", Text, nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    Column("activated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("ruleset_artifact_id", name="uq_ruleset_activation_artifact"),
    CheckConstraint(
        "active_ruleset_hash ~ '^[0-9a-f]{64}$'",
        name="ck_ruleset_activation_active_hash",
    ),
    CheckConstraint(
        "approval_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ruleset_activation_approval_hash",
    ),
    CheckConstraint(
        "activation_manifest_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ruleset_activation_manifest_hash",
    ),
    schema="provenance",
)

# MIN-007F availability registry and immutable prediction bundle.
dataset_version = Table(
    "dataset_version",
    metadata,
    Column(
        "dataset_version_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column("dataset_semantic_sha256", CHAR(64), nullable=False),
    Column("dataset_key", String(160), nullable=False),
    Column("schema_version", String(80), nullable=False),
    Column("competition_code", String(80), nullable=False),
    Column("season_code", String(40), nullable=False),
    Column("training_cutoff", DateTime(timezone=True), nullable=False),
    Column("source_dataset_sha256", CHAR(64)),
    Column("policy_sha256", CHAR(64), nullable=False),
    Column("declared_training_example_count", Integer, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("dataset_semantic_sha256", name="uq_dataset_version_semantic_hash"),
    CheckConstraint(
        "dataset_semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dataset_version_semantic_hash"
    ),
    CheckConstraint(
        "source_dataset_sha256 IS NULL OR source_dataset_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_dataset_version_source_hash",
    ),
    CheckConstraint("policy_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dataset_version_policy_hash"),
    CheckConstraint(
        "declared_training_example_count >= 0", name="ck_dataset_version_example_count"
    ),
    schema="provenance",
)

dataset_training_example = Table(
    "dataset_training_example",
    metadata,
    Column(
        "training_example_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column(
        "dataset_version_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.dataset_version.dataset_version_id",
            name="fk_dataset_example_version",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("example_id", String(160), nullable=False),
    Column("fixture_id", String(160), nullable=False),
    Column("fixture_key", String(160), nullable=False),
    Column("feature_cutoff", DateTime(timezone=True), nullable=False),
    Column("label_usable_at", DateTime(timezone=True), nullable=False),
    Column("manager_regime_id", String(160), nullable=False),
    Column("minutes_label", SmallInteger, nullable=False),
    Column("player_id", String(160), nullable=False),
    Column("player_key", String(160), nullable=False),
    Column("position", String(8), nullable=False),
    Column("role_label", String(8), nullable=False),
    Column("sequence_index", Integer, nullable=False),
    Column("split", String(16), nullable=False, server_default=text("'TRAIN'")),
    Column("team_id", String(160), nullable=False),
    Column("team_key", String(160), nullable=False),
    Column("evidence_type", String(40), nullable=False),
    Column("lineage_sha256", CHAR(64), nullable=False),
    Column("source_lineage", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("dataset_version_id", "example_id", name="uq_dataset_example_identity"),
    CheckConstraint("lineage_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dataset_example_lineage_hash"),
    CheckConstraint("minutes_label BETWEEN 0 AND 90", name="ck_dataset_example_minutes"),
    CheckConstraint("role_label IN ('START','BENCH','OUT')", name="ck_dataset_example_role"),
    CheckConstraint("position IN ('GK','DEF','MID','FWD')", name="ck_dataset_example_position"),
    CheckConstraint("split = 'TRAIN'", name="ck_dataset_example_split"),
    CheckConstraint("sequence_index > 0", name="ck_dataset_example_sequence"),
    CheckConstraint("label_usable_at >= feature_cutoff", name="ck_dataset_example_time_order"),
    schema="provenance",
)

model_version = Table(
    "model_version",
    metadata,
    Column(
        "model_version_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column("model_semantic_sha256", CHAR(64), nullable=False),
    Column("model_key", String(160), nullable=False),
    Column("schema_version", String(80), nullable=False),
    Column("dataset_version_sha256", CHAR(64), nullable=False),
    Column("role_artifact_sha256", CHAR(64), nullable=False),
    Column("minute_artifact_sha256", CHAR(64), nullable=False),
    Column("policy_sha256", CHAR(64), nullable=False),
    Column("model_family", String(160), nullable=False),
    Column("code_identity", String(160), nullable=False),
    Column("artifact", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["dataset_version_sha256"],
        ["provenance.dataset_version.dataset_semantic_sha256"],
        name="fk_model_dataset_version",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("model_semantic_sha256", name="uq_model_version_semantic_hash"),
    CheckConstraint(
        "model_semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_model_version_semantic_hash"
    ),
    CheckConstraint(
        "dataset_version_sha256 ~ '^[0-9a-f]{64}$'", name="ck_model_version_dataset_hash"
    ),
    CheckConstraint("role_artifact_sha256 ~ '^[0-9a-f]{64}$'", name="ck_model_version_role_hash"),
    CheckConstraint(
        "minute_artifact_sha256 ~ '^[0-9a-f]{64}$'", name="ck_model_version_minute_hash"
    ),
    CheckConstraint("policy_sha256 ~ '^[0-9a-f]{64}$'", name="ck_model_version_policy_hash"),
    schema="provenance",
)

model_evaluation = Table(
    "model_evaluation",
    metadata,
    Column(
        "model_evaluation_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column(
        "model_version_id",
        UUID(as_uuid=True),
        ForeignKey(
            "provenance.model_version.model_version_id",
            name="fk_model_evaluation_model",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("evaluation_semantic_sha256", CHAR(64), nullable=False),
    Column("status", String(24), nullable=False),
    Column("evaluation", JSONB, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("evaluation_semantic_sha256", name="uq_model_evaluation_semantic_hash"),
    CheckConstraint(
        "evaluation_semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_model_evaluation_semantic_hash"
    ),
    CheckConstraint(
        "status IN ('PENDING','COMPLETE','BLOCKED')", name="ck_model_evaluation_status"
    ),
    schema="provenance",
)

prediction_run = Table(
    "prediction_run",
    metadata,
    Column(
        "prediction_run_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column("prediction_input_signature_sha256", CHAR(64), nullable=False),
    Column("output_semantic_sha256", CHAR(64), nullable=False),
    Column("fixture_id", UUID(as_uuid=True), nullable=False),
    Column("team_id", UUID(as_uuid=True), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("feature_cutoff", DateTime(timezone=True)),
    Column("model_version_sha256", CHAR(64), nullable=False),
    Column("dataset_version_sha256", CHAR(64), nullable=False),
    Column("policy_sha256", CHAR(64), nullable=False),
    Column("manager_regime_id", String(160), nullable=False),
    Column("manager_context", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("seed", String(160), nullable=False),
    Column("sample_count", Integer, nullable=False),
    Column("bench_size", SmallInteger, nullable=False),
    Column("bench_goalkeeper_slots", SmallInteger, nullable=False),
    Column("code_identity", String(160), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    ForeignKeyConstraint(
        ["model_version_sha256"],
        ["provenance.model_version.model_semantic_sha256"],
        name="fk_prediction_model_version",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["dataset_version_sha256"],
        ["provenance.dataset_version.dataset_semantic_sha256"],
        name="fk_prediction_dataset_version",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("prediction_input_signature_sha256", name="uq_prediction_input_signature"),
    CheckConstraint(
        "prediction_input_signature_sha256 ~ '^[0-9a-f]{64}$'", name="ck_prediction_input_signature"
    ),
    CheckConstraint("output_semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_prediction_output_hash"),
    CheckConstraint(
        "sample_count > 0 AND bench_size >= 0 AND bench_goalkeeper_slots >= 0 AND bench_goalkeeper_slots <= bench_size",
        name="ck_prediction_configuration",
    ),
    schema="football",
)

prediction_dependency = Table(
    "prediction_dependency",
    metadata,
    Column(
        "prediction_dependency_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "prediction_run_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.prediction_run.prediction_run_id",
            name="fk_prediction_dependency_run",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("dependency_type", String(64), nullable=False),
    Column("dependency_key", String(200), nullable=False),
    Column("semantic_sha256", CHAR(64), nullable=False),
    Column("ordinal", Integer, nullable=False),
    UniqueConstraint(
        "prediction_run_id",
        "dependency_type",
        "dependency_key",
        name="uq_prediction_dependency_key",
    ),
    CheckConstraint("semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_prediction_dependency_hash"),
    CheckConstraint("ordinal >= 0", name="ck_prediction_dependency_ordinal"),
    schema="football",
)

prediction_hard_eligibility = Table(
    "prediction_hard_eligibility",
    metadata,
    Column(
        "prediction_hard_eligibility_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "prediction_run_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.prediction_run.prediction_run_id",
            name="fk_prediction_hard_eligibility_run",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("player_id", String(160), nullable=False),
    Column("reason", String(240), nullable=False),
    Column("hard_ineligible", Boolean, nullable=False, server_default=text("true")),
    UniqueConstraint(
        "prediction_run_id", "player_id", name="uq_prediction_hard_eligibility_player"
    ),
    schema="football",
)

role_marginal = Table(
    "role_marginal",
    metadata,
    Column(
        "role_marginal_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column(
        "prediction_run_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.prediction_run.prediction_run_id",
            name="fk_role_marginal_run",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("player_id", String(160), nullable=False),
    Column("player_key", String(160), nullable=False),
    Column("position", String(8), nullable=False),
    Column("p_start", Numeric, nullable=False),
    Column("p_bench", Numeric, nullable=False),
    Column("p_out", Numeric, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("prediction_run_id", "player_id", name="uq_role_marginal_player"),
    CheckConstraint("position IN ('GK','DEF','MID','FWD')", name="ck_role_marginal_position"),
    CheckConstraint(
        "p_start >= 0 AND p_start <= 1 AND p_bench >= 0 AND p_bench <= 1 AND p_out >= 0 AND p_out <= 1",
        name="ck_role_marginal_bounds",
    ),
    CheckConstraint("p_start + p_bench + p_out = 1", name="ck_role_marginal_exact_sum"),
    schema="football",
)

conditional_minute_pmf = Table(
    "conditional_minute_pmf",
    metadata,
    Column(
        "conditional_minute_pmf_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "prediction_run_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.prediction_run.prediction_run_id",
            name="fk_minute_pmf_run",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("player_id", String(160), nullable=False),
    Column("role", String(8), nullable=False),
    Column("minute_pmf", ARRAY(Numeric), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("prediction_run_id", "player_id", "role", name="uq_minute_pmf_player_role"),
    CheckConstraint("role IN ('START','BENCH')", name="ck_minute_pmf_role"),
    CheckConstraint(
        "football.validate_minute_pmf(minute_pmf, role)", name="ck_minute_pmf_exact_simplex"
    ),
    schema="football",
)

lineup_scenario = Table(
    "lineup_scenario",
    metadata,
    Column(
        "lineup_scenario_id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    ),
    Column(
        "prediction_run_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.prediction_run.prediction_run_id",
            name="fk_lineup_scenario_run",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("scenario_index", Integer, nullable=False),
    Column("scenario_sha256", CHAR(64), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("prediction_run_id", "scenario_index", name="uq_lineup_scenario_index"),
    UniqueConstraint("prediction_run_id", "scenario_sha256", name="uq_lineup_scenario_hash"),
    UniqueConstraint("lineup_scenario_id", "prediction_run_id", name="uq_lineup_scenario_id_run"),
    CheckConstraint("scenario_index >= 0", name="ck_lineup_scenario_index"),
    CheckConstraint("scenario_sha256 ~ '^[0-9a-f]{64}$'", name="ck_lineup_scenario_hash"),
    schema="football",
)

lineup_scenario_member = Table(
    "lineup_scenario_member",
    metadata,
    Column(
        "lineup_scenario_member_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column("lineup_scenario_id", UUID(as_uuid=True), nullable=False),
    Column("prediction_run_id", UUID(as_uuid=True), nullable=False),
    Column("player_id", String(160), nullable=False),
    Column("role", String(8), nullable=False),
    Column("position", String(8), nullable=False),
    ForeignKeyConstraint(
        ["lineup_scenario_id", "prediction_run_id"],
        [
            "football.lineup_scenario.lineup_scenario_id",
            "football.lineup_scenario.prediction_run_id",
        ],
        name="fk_lineup_member_scenario_run",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("lineup_scenario_id", "player_id", name="uq_lineup_member_player"),
    CheckConstraint("role IN ('START','BENCH','OUT')", name="ck_lineup_member_role"),
    CheckConstraint("position IN ('GK','DEF','MID','FWD')", name="ck_lineup_member_position"),
    schema="football",
)

player_minutes_projection = Table(
    "player_minutes_projection",
    metadata,
    Column(
        "player_minutes_projection_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    ),
    Column(
        "prediction_run_id",
        UUID(as_uuid=True),
        ForeignKey(
            "football.prediction_run.prediction_run_id",
            name="fk_player_minutes_projection_run",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("player_id", String(160), nullable=False),
    Column("p_start", Numeric, nullable=False),
    Column("p_bench", Numeric, nullable=False),
    Column("p_out", Numeric, nullable=False),
    Column("minute_pmf", ARRAY(Numeric), nullable=False),
    Column("p_zero", Numeric, nullable=False),
    Column("p_60_plus", Numeric, nullable=False),
    Column("expected_minutes", Numeric, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("prediction_run_id", "player_id", name="uq_player_minutes_projection_player"),
    CheckConstraint(
        "football.validate_player_minutes_projection(p_start, p_bench, p_out, minute_pmf, p_zero, p_60_plus, expected_minutes)",
        name="ck_player_minutes_projection_consistent",
    ),
    schema="football",
)

external_identifier.append_constraint(
    ExcludeConstraint(
        (external_identifier.c.provider_id, "="),
        (
            func.coalesce(
                external_identifier.c.season_id,
                text("'00000000-0000-0000-0000-000000000000'::uuid"),
            ),
            "=",
        ),
        (external_identifier.c.provider_product, "="),
        (external_identifier.c.identifier_namespace, "="),
        (external_identifier.c.entity_type, "="),
        (external_identifier.c.external_id_text, "="),
        (external_identifier.c.valid_during, "&&"),
        name="ex_external_identifier_current_accepted",
        using="gist",
        where=text(
            "upper_inf(system_during) AND mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED')"
        ),
        deferrable=True,
        initially="IMMEDIATE",
    )
)
entity_alias.append_constraint(
    ExcludeConstraint(
        (entity_alias.c.canonical_entity_id, "="),
        (func.coalesce(entity_alias.c.language, "__DMF_NULL__"), "="),
        (func.coalesce(entity_alias.c.script, "__DMF_NULL__"), "="),
        (entity_alias.c.valid_during, "&&"),
        name="ex_entity_alias_current_preferred",
        using="gist",
        where=text("upper_inf(system_during) AND is_preferred"),
        deferrable=True,
        initially="IMMEDIATE",
    )
)
player_team_membership.append_constraint(
    ExcludeConstraint(
        (player_team_membership.c.player_id, "="),
        (player_team_membership.c.registration_type, "="),
        (player_team_membership.c.valid_during, "&&"),
        name="ex_player_team_membership_current",
        using="gist",
        where=text("upper_inf(system_during)"),
        deferrable=True,
        initially="IMMEDIATE",
    )
)
fixture_revision.append_constraint(
    ExcludeConstraint(
        (fixture_revision.c.fixture_id, "="),
        (fixture_revision.c.valid_during, "&&"),
        name="ex_fixture_revision_current",
        using="gist",
        where=text("upper_inf(system_during)"),
        deferrable=True,
        initially="IMMEDIATE",
    )
)
fixture_gameweek_assignment.append_constraint(
    ExcludeConstraint(
        (fixture_gameweek_assignment.c.fixture_id, "="),
        (fixture_gameweek_assignment.c.valid_during, "&&"),
        name="ex_fixture_gameweek_assignment_current",
        using="gist",
        where=text("upper_inf(system_during)"),
        deferrable=True,
        initially="IMMEDIATE",
    )
)

Index("ix_season_competition", season.c.competition_id)
Index("ix_team_season_season", team_season.c.season_id)
Index("ix_team_season_snapshot", team_season.c.source_snapshot_id)
Index("ix_fixture_competition", fixture.c.competition_id)
Index("ix_fixture_season", fixture.c.season_id)
Index("ix_fixture_home_team", fixture.c.home_team_id)
Index("ix_fixture_away_team", fixture.c.away_team_id)
Index("ix_gameweek_season", gameweek.c.season_id)
Index("ix_ingestion_run_provider", ingestion_run.c.provider_id)
Index("ix_source_snapshot_provider", source_snapshot.c.provider_id)
Index("ix_source_snapshot_run", source_snapshot.c.ingestion_run_id)
Index("ix_source_snapshot_raw", source_snapshot.c.raw_blob_id)
Index("ix_source_snapshot_raw_storage", source_snapshot.c.raw_storage_object_id)
Index("ix_source_snapshot_rights_profile", source_snapshot.c.rights_profile_record_id)
Index("ix_rights_profile_provider", rights_profile.c.provider_key)
Index("ix_raw_storage_content", raw_storage_object.c.raw_blob_id)
Index("ix_raw_storage_rights", raw_storage_object.c.rights_profile_record_id)
Index("ix_rights_decision_profile", rights_decision.c.rights_profile_record_id)
Index("ix_rights_decision_snapshot", rights_decision.c.source_snapshot_id)
Index(
    "ix_processing_event_snapshot_sequence",
    source_processing_event.c.source_snapshot_id,
    source_processing_event.c.sequence_number,
)
Index("ix_external_identifier_entity", external_identifier.c.canonical_entity_id)
Index("ix_external_identifier_provider", external_identifier.c.provider_id)
Index("ix_external_identifier_season", external_identifier.c.season_id)
Index(
    "ix_external_identifier_snapshot",
    external_identifier.c.evidence_source_snapshot_id,
)
Index(
    "ix_external_identifier_as_of",
    external_identifier.c.canonical_entity_id,
    external_identifier.c.valid_during,
    external_identifier.c.system_during,
    postgresql_using="gist",
)
Index("ix_entity_alias_entity", entity_alias.c.canonical_entity_id)
Index("ix_entity_alias_provider", entity_alias.c.provider_id)
Index("ix_entity_alias_snapshot", entity_alias.c.source_snapshot_id)
Index(
    "ix_entity_alias_as_of",
    entity_alias.c.canonical_entity_id,
    entity_alias.c.valid_during,
    entity_alias.c.system_during,
    postgresql_using="gist",
)
Index("ix_membership_team", player_team_membership.c.team_id)
Index("ix_membership_season", player_team_membership.c.season_id)
Index("ix_membership_snapshot", player_team_membership.c.source_snapshot_id)
Index(
    "ix_membership_as_of",
    player_team_membership.c.player_id,
    player_team_membership.c.registration_type,
    player_team_membership.c.valid_during,
    player_team_membership.c.system_during,
    postgresql_using="gist",
)
Index("ix_fixture_revision_snapshot", fixture_revision.c.source_snapshot_id)
Index(
    "ix_fixture_revision_as_of",
    fixture_revision.c.fixture_id,
    fixture_revision.c.valid_during,
    fixture_revision.c.system_during,
    postgresql_using="gist",
)
Index("ix_assignment_gameweek", fixture_gameweek_assignment.c.gameweek_id)
Index("ix_assignment_season", fixture_gameweek_assignment.c.season_id)
Index("ix_assignment_snapshot", fixture_gameweek_assignment.c.source_snapshot_id)
Index(
    "ix_assignment_as_of",
    fixture_gameweek_assignment.c.fixture_id,
    fixture_gameweek_assignment.c.valid_during,
    fixture_gameweek_assignment.c.system_during,
    postgresql_using="gist",
)
Index("ix_data_quality_snapshot", data_quality_issue.c.source_snapshot_id)
Index("ix_data_quality_entity", data_quality_issue.c.canonical_entity_id)
Index("ix_data_quality_run", data_quality_issue.c.ingestion_run_id)
Index("ix_data_quality_bundle", data_quality_issue.c.source_bundle_id)
Index("ix_player_season_season", player_season.c.season_id)
Index("ix_player_season_snapshot", player_season.c.source_snapshot_id)
Index("ix_team_observation_subject", team_observation.c.team_season_id)
Index("ix_team_observation_snapshot", team_observation.c.source_snapshot_id)
Index("ix_player_observation_subject", player_observation.c.player_fpl_season_id)
Index("ix_player_observation_team", player_observation.c.team_season_id)
Index("ix_player_observation_snapshot", player_observation.c.source_snapshot_id)
Index("ix_gameweek_observation_subject", gameweek_observation.c.gameweek_id)
Index("ix_gameweek_observation_snapshot", gameweek_observation.c.source_snapshot_id)
Index("ix_fixture_observation_subject", fixture_observation.c.fixture_id)
Index("ix_fixture_observation_snapshot", fixture_observation.c.source_snapshot_id)
Index("ix_semantic_effect_source_snapshot", semantic_effect_source.c.source_snapshot_id)
Index(
    "ix_semantic_observation_claim_snapshot",
    semantic_observation_claim.c.source_snapshot_id,
)
Index(
    "ix_source_bundle_season_cutoff",
    source_bundle.c.season_id,
    source_bundle.c.information_cutoff,
)
Index("ix_source_bundle_member_snapshot", source_bundle_member.c.source_snapshot_id)
Index("ix_operator_market_fixture", operator_fixture_market.c.fixture_id)
Index("ix_operator_market_operator", operator_fixture_market.c.operator_id)
Index("ix_market_selection_market", market_selection.c.market_id)
Index("ix_provider_market_market", provider_market_representation.c.market_id)
Index(
    "ix_odds_publication_attestation_usable",
    odds_publication_attestation.c.usable_at,
    odds_publication_attestation.c.publication_batch_id,
)
Index("ix_book_observation_batch", operator_market_observation.c.publication_batch_id)
Index(
    "ix_book_observation_market_usable",
    operator_market_observation.c.market_id,
    operator_market_observation.c.usable_at,
)
Index("ix_book_observation_snapshot", operator_market_observation.c.source_snapshot_id)
Index(
    "ix_odds_observation_fixture_usable",
    odds_observation.c.fixture_id,
    odds_observation.c.usable_at,
)
Index("ix_odds_observation_book", odds_observation.c.book_observation_id)
Index(
    "ix_quota_observation_provider",
    provider_quota_observation.c.provider_id,
    provider_quota_observation.c.observed_at,
)
Index("ix_dataset_training_example_version", dataset_training_example.c.dataset_version_id)
Index("ix_model_version_dataset", model_version.c.dataset_version_sha256)
Index(
    "ix_prediction_run_fixture_team_asof",
    prediction_run.c.fixture_id,
    prediction_run.c.team_id,
    prediction_run.c.as_of,
)
Index("ix_prediction_dependency_run", prediction_dependency.c.prediction_run_id)
Index("ix_prediction_hard_eligibility_run", prediction_hard_eligibility.c.prediction_run_id)
Index("ix_role_marginal_run", role_marginal.c.prediction_run_id)
Index("ix_minute_pmf_run", conditional_minute_pmf.c.prediction_run_id)
Index("ix_lineup_scenario_run", lineup_scenario.c.prediction_run_id)
Index("ix_lineup_member_scenario", lineup_scenario_member.c.lineup_scenario_id)
Index("ix_player_minutes_projection_run", player_minutes_projection.c.prediction_run_id)
