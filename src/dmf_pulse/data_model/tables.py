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
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, UUID, ExcludeConstraint
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
        "entity_type IN ('COMPETITION','SEASON','GAMEWEEK','TEAM','PLAYER','FIXTURE','DATA_PROVIDER')",
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
    Column("stored_blob_sha256", CHAR(64)),
    Column("byte_size", BigInteger, nullable=False),
    Column("storage_uri", Text),
    Column("storage_policy", String(24), nullable=False),
    Column("content_type", Text),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("transaction_timestamp()"),
    ),
    UniqueConstraint("body_sha256", name="uq_raw_blob_body_sha256"),
    CheckConstraint("body_sha256 ~ '^[0-9a-f]{64}$'", name="ck_raw_blob_body_hash"),
    CheckConstraint(
        "stored_blob_sha256 IS NULL OR stored_blob_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_raw_blob_stored_hash",
    ),
    CheckConstraint("byte_size >= 0", name="ck_raw_blob_byte_size"),
    CheckConstraint(
        "storage_policy IN ('ALLOWED','FORBIDDEN','EPHEMERAL','DELETED')",
        name="ck_raw_blob_policy",
    ),
    CheckConstraint(
        "storage_policy <> 'FORBIDDEN' OR (storage_uri IS NULL AND stored_blob_sha256 IS NULL)",
        name="ck_raw_blob_forbidden_storage",
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
    CheckConstraint(
        "request_fingerprint ~ '^[0-9a-f]{64}$'",
        name="ck_source_snapshot_request_hash",
    ),
    CheckConstraint(
        "body_sha256 IS NULL OR body_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_source_snapshot_body_hash",
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
        "(raw_storage_policy <> 'FORBIDDEN' OR raw_blob_id IS NULL) "
        "AND (raw_storage_policy <> 'ALLOWED' OR body_sha256 IS NULL OR raw_blob_id IS NOT NULL) "
        "AND (raw_blob_id IS NULL OR body_sha256 IS NOT NULL)",
        name="ck_source_snapshot_retention",
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
    CheckConstraint(
        "severity IN ('INFO','WARN','ERROR','BLOCKING')", name="ck_data_quality_severity"
    ),
    CheckConstraint(
        "status IN ('OPEN','ACKNOWLEDGED','RESOLVED','SUPERSEDED')",
        name="ck_data_quality_status",
    ),
    CheckConstraint(
        "resolved_at IS NULL OR resolved_at >= detected_at",
        name="ck_data_quality_resolution",
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
        "source_ruleset_hash",
        name="uq_ruleset_artifact_identity_hash",
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

external_identifier.append_constraint(
    ExcludeConstraint(
        (external_identifier.c.provider_id, "="),
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
Index("ix_fixture_competition", fixture.c.competition_id)
Index("ix_fixture_season", fixture.c.season_id)
Index("ix_fixture_home_team", fixture.c.home_team_id)
Index("ix_fixture_away_team", fixture.c.away_team_id)
Index("ix_gameweek_season", gameweek.c.season_id)
Index("ix_ingestion_run_provider", ingestion_run.c.provider_id)
Index("ix_source_snapshot_provider", source_snapshot.c.provider_id)
Index("ix_source_snapshot_run", source_snapshot.c.ingestion_run_id)
Index("ix_source_snapshot_raw", source_snapshot.c.raw_blob_id)
Index("ix_external_identifier_entity", external_identifier.c.canonical_entity_id)
Index("ix_external_identifier_provider", external_identifier.c.provider_id)
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
