"""Create the DAT-003 canonical temporal PostgreSQL foundation.

Revision ID: 20260723_0001
Revises:
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260723_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HASH_CHECK = "VALUE ~ '^[0-9a-f]{64}$'"


def _canonical_range_check(column: str) -> str:
    return (
        f"{column} IS NOT NULL AND NOT isempty({column}) "
        f"AND lower({column}) IS NOT NULL AND NOT lower_inf({column}) "
        f"AND isfinite(lower({column})) AND lower_inc({column}) AND NOT upper_inc({column})"
    )


_DDL_STATEMENTS = (
    "CREATE SCHEMA core",
    "CREATE SCHEMA football",
    "CREATE SCHEMA fpl",
    "CREATE SCHEMA provenance",
    "CREATE EXTENSION btree_gist WITH SCHEMA core",
    "SET search_path TO core, football, fpl, provenance, public, pg_catalog",
    """
    CREATE FUNCTION core.is_canonical_tstzrange(value tstzrange)
    RETURNS boolean
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
      SELECT value IS NOT NULL
         AND NOT isempty(value)
         AND lower(value) IS NOT NULL
         AND NOT lower_inf(value)
         AND isfinite(lower(value))
         AND lower_inc(value)
         AND NOT upper_inc(value)
    $$
    """,
    """
    CREATE FUNCTION provenance.reject_immutable_change()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'IMMUTABLE_RECORD';
    END
    $$
    """,
    """
    CREATE FUNCTION core.guard_canonical_successor()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE successor_type text;
    BEGIN
      IF NEW.superseded_by_entity_id IS NOT NULL THEN
        SELECT entity_type INTO successor_type
        FROM core.canonical_entity
        WHERE entity_id = NEW.superseded_by_entity_id;
        IF successor_type IS NULL OR successor_type <> NEW.entity_type THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ENTITY_TYPE_MISMATCH';
        END IF;
      END IF;
      RETURN NEW;
    END
    $$
    """,
    """
    CREATE FUNCTION core.guard_temporal_version()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
      id_column text := TG_ARGV[0];
      pointer_column text := TG_ARGV[1];
      successor_id uuid;
      successor jsonb;
      lineage_key text;
      argument_index integer;
      close_at timestamptz;
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'IMMUTABLE_RECORD';
      END IF;

      IF TG_OP = 'INSERT' THEN
        IF NOT core.is_canonical_tstzrange(NEW.valid_during)
           OR NOT core.is_canonical_tstzrange(NEW.system_during) THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'TEMPORAL_RANGE_INVALID';
        END IF;
        IF NOT upper_inf(NEW.system_during)
           OR (to_jsonb(NEW) ->> pointer_column) IS NOT NULL THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'TEMPORAL_SUPERSESSION_CONFLICT';
        END IF;
        RETURN NEW;
      END IF;

      IF to_jsonb(NEW) - ARRAY['system_during', pointer_column]
         <> to_jsonb(OLD) - ARRAY['system_during', pointer_column] THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'IMMUTABLE_RECORD';
      END IF;
      IF NOT upper_inf(OLD.system_during)
         OR (to_jsonb(OLD) ->> pointer_column) IS NOT NULL
         OR (to_jsonb(NEW) ->> pointer_column) IS NULL THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'TEMPORAL_SUPERSESSION_CONFLICT';
      END IF;
      IF NOT core.is_canonical_tstzrange(NEW.system_during)
         OR lower(NEW.system_during) <> lower(OLD.system_during)
         OR upper_inf(NEW.system_during) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'TEMPORAL_SUPERSESSION_CONFLICT';
      END IF;

      close_at := upper(NEW.system_during);
      IF close_at <= lower(OLD.system_during) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'TEMPORAL_SUPERSESSION_CONFLICT';
      END IF;
      successor_id := (to_jsonb(NEW) ->> pointer_column)::uuid;
      EXECUTE format(
        'SELECT to_jsonb(candidate) FROM %I.%I AS candidate WHERE %I = $1',
        TG_TABLE_SCHEMA, TG_TABLE_NAME, id_column
      ) INTO successor USING successor_id;
      IF successor IS NULL
         OR NOT upper_inf((successor ->> 'system_during')::tstzrange)
         OR lower((successor ->> 'system_during')::tstzrange) <> close_at
         OR (successor ->> pointer_column) IS NOT NULL THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'TEMPORAL_SUPERSESSION_CONFLICT';
      END IF;
      IF array_length(TG_ARGV, 1) > 2 THEN
        FOR argument_index IN 2..array_upper(TG_ARGV, 1) LOOP
          lineage_key := TG_ARGV[argument_index];
          IF successor -> lineage_key IS DISTINCT FROM to_jsonb(OLD) -> lineage_key THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'TEMPORAL_SUPERSESSION_CONFLICT';
          END IF;
        END LOOP;
      END IF;
      RETURN NEW;
    END
    $$
    """,
    """
    CREATE TABLE core.canonical_entity (
      entity_id uuid CONSTRAINT pk_canonical_entity PRIMARY KEY DEFAULT uuidv7(),
      entity_type varchar(40) NOT NULL,
      lifecycle_status varchar(24) NOT NULL DEFAULT 'ACTIVE',
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      superseded_by_entity_id uuid NULL,
      notes text NULL,
      CONSTRAINT uq_canonical_entity_id_type UNIQUE (entity_id, entity_type),
      CONSTRAINT fk_canonical_entity_successor FOREIGN KEY (superseded_by_entity_id)
        REFERENCES core.canonical_entity(entity_id) ON DELETE RESTRICT,
      CONSTRAINT ck_canonical_entity_type CHECK (entity_type IN
        ('COMPETITION','SEASON','GAMEWEEK','TEAM','PLAYER','FIXTURE','DATA_PROVIDER')),
      CONSTRAINT ck_canonical_entity_lifecycle CHECK (lifecycle_status IN
        ('ACTIVE','INACTIVE','SUPERSEDED','MERGED')),
      CONSTRAINT ck_canonical_entity_no_self CHECK
        (superseded_by_entity_id IS NULL OR superseded_by_entity_id <> entity_id),
      CONSTRAINT ck_canonical_entity_successor_state CHECK (
        (lifecycle_status IN ('SUPERSEDED','MERGED') AND superseded_by_entity_id IS NOT NULL)
        OR (lifecycle_status IN ('ACTIVE','INACTIVE') AND superseded_by_entity_id IS NULL)
      )
    )
    """,
    """
    CREATE TRIGGER trg_canonical_entity_successor
    BEFORE INSERT OR UPDATE ON core.canonical_entity
    FOR EACH ROW EXECUTE FUNCTION core.guard_canonical_successor()
    """,
    """
    CREATE TABLE football.competition (
      competition_id uuid CONSTRAINT pk_competition PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'COMPETITION',
      competition_key varchar(80) NOT NULL,
      canonical_name text NOT NULL,
      country_code char(2) NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT ck_competition_entity_type CHECK (entity_type = 'COMPETITION'),
      CONSTRAINT uq_competition_key UNIQUE (competition_key),
      CONSTRAINT fk_competition_canonical_type FOREIGN KEY (competition_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE football.team (
      team_id uuid CONSTRAINT pk_team PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'TEAM',
      canonical_name text NOT NULL,
      short_name varchar(20) NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT ck_team_entity_type CHECK (entity_type = 'TEAM'),
      CONSTRAINT fk_team_canonical_type FOREIGN KEY (team_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE football.player (
      player_id uuid CONSTRAINT pk_player PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'PLAYER',
      canonical_name text NOT NULL,
      birth_date date NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT ck_player_entity_type CHECK (entity_type = 'PLAYER'),
      CONSTRAINT fk_player_canonical_type FOREIGN KEY (player_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE provenance.data_provider (
      provider_id uuid CONSTRAINT pk_data_provider PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'DATA_PROVIDER',
      provider_key varchar(80) NOT NULL,
      display_name text NOT NULL,
      provider_type varchar(32) NOT NULL,
      rights_profile_key varchar(120) NULL,
      active boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT ck_provider_entity_type CHECK (entity_type = 'DATA_PROVIDER'),
      CONSTRAINT ck_provider_type CHECK (provider_type IN
        ('OFFICIAL','ODDS_API','FOOTBALL_API','MANUAL','OPEN_DATA','INTERNAL')),
      CONSTRAINT uq_provider_key UNIQUE (provider_key),
      CONSTRAINT fk_provider_canonical_type FOREIGN KEY (provider_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE football.season (
      season_id uuid CONSTRAINT pk_season PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'SEASON',
      competition_id uuid NOT NULL,
      season_code varchar(20) NOT NULL,
      starts_on date NOT NULL,
      ends_on date NOT NULL,
      CONSTRAINT ck_season_entity_type CHECK (entity_type = 'SEASON'),
      CONSTRAINT ck_season_dates CHECK (ends_on > starts_on),
      CONSTRAINT uq_season_competition_code UNIQUE (competition_id, season_code),
      CONSTRAINT fk_season_competition FOREIGN KEY (competition_id)
        REFERENCES football.competition(competition_id) ON DELETE RESTRICT,
      CONSTRAINT fk_season_canonical_type FOREIGN KEY (season_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE football.fixture (
      fixture_id uuid CONSTRAINT pk_fixture PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'FIXTURE',
      competition_id uuid NOT NULL,
      season_id uuid NOT NULL,
      home_team_id uuid NOT NULL,
      away_team_id uuid NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT ck_fixture_entity_type CHECK (entity_type = 'FIXTURE'),
      CONSTRAINT ck_fixture_distinct_teams CHECK (home_team_id <> away_team_id),
      CONSTRAINT fk_fixture_competition FOREIGN KEY (competition_id)
        REFERENCES football.competition(competition_id) ON DELETE RESTRICT,
      CONSTRAINT fk_fixture_season FOREIGN KEY (season_id)
        REFERENCES football.season(season_id) ON DELETE RESTRICT,
      CONSTRAINT fk_fixture_home_team FOREIGN KEY (home_team_id)
        REFERENCES football.team(team_id) ON DELETE RESTRICT,
      CONSTRAINT fk_fixture_away_team FOREIGN KEY (away_team_id)
        REFERENCES football.team(team_id) ON DELETE RESTRICT,
      CONSTRAINT fk_fixture_canonical_type FOREIGN KEY (fixture_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE fpl.gameweek (
      gameweek_id uuid CONSTRAINT pk_gameweek PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'GAMEWEEK',
      season_id uuid NOT NULL,
      number smallint NOT NULL,
      display_name text NOT NULL,
      official_deadline_at timestamptz NULL,
      status varchar(20) NOT NULL,
      CONSTRAINT ck_gameweek_entity_type CHECK (entity_type = 'GAMEWEEK'),
      CONSTRAINT ck_gameweek_number CHECK (number BETWEEN 1 AND 60),
      CONSTRAINT ck_gameweek_status CHECK (status IN ('DRAFT','OPEN','CLOSED','FINAL')),
      CONSTRAINT uq_gameweek_season_number UNIQUE (season_id, number),
      CONSTRAINT fk_gameweek_season FOREIGN KEY (season_id)
        REFERENCES football.season(season_id) ON DELETE RESTRICT,
      CONSTRAINT fk_gameweek_canonical_type FOREIGN KEY (gameweek_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE provenance.raw_blob (
      raw_blob_id uuid CONSTRAINT pk_raw_blob PRIMARY KEY DEFAULT uuidv7(),
      body_sha256 char(64) NOT NULL,
      stored_blob_sha256 char(64) NULL,
      byte_size bigint NOT NULL,
      storage_uri text NULL,
      storage_policy varchar(24) NOT NULL,
      content_type text NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT uq_raw_blob_body_sha256 UNIQUE (body_sha256),
      CONSTRAINT ck_raw_blob_body_hash CHECK (body_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_raw_blob_stored_hash CHECK
        (stored_blob_sha256 IS NULL OR stored_blob_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_raw_blob_byte_size CHECK (byte_size >= 0),
      CONSTRAINT ck_raw_blob_policy CHECK
        (storage_policy IN ('ALLOWED','FORBIDDEN','EPHEMERAL','DELETED')),
      CONSTRAINT ck_raw_blob_forbidden_storage CHECK
        (storage_policy <> 'FORBIDDEN' OR
         (storage_uri IS NULL AND stored_blob_sha256 IS NULL))
    )
    """,
    """
    CREATE TABLE provenance.ingestion_run (
      ingestion_run_id uuid CONSTRAINT pk_ingestion_run PRIMARY KEY DEFAULT uuidv7(),
      provider_id uuid NOT NULL,
      resource varchar(120) NOT NULL,
      logical_run_key varchar(200) NOT NULL,
      status varchar(32) NOT NULL,
      scheduled_at timestamptz NULL,
      started_at timestamptz NULL,
      completed_at timestamptz NULL,
      adapter_version text NULL,
      code_commit char(40) NULL,
      counts jsonb NOT NULL DEFAULT '{}'::jsonb,
      error_code text NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT ck_ingestion_run_status CHECK (status IN
        ('PLANNED','RUNNING','SUCCEEDED','SUCCEEDED_WITH_WARNINGS','FAILED_RETRYABLE',
         'FAILED_PERMANENT','CANCELLED')),
      CONSTRAINT ck_ingestion_run_code_commit CHECK
        (code_commit IS NULL OR code_commit ~ '^[0-9a-f]{40}$'),
      CONSTRAINT uq_ingestion_run_logical_key UNIQUE (provider_id, logical_run_key),
      CONSTRAINT fk_ingestion_run_provider FOREIGN KEY (provider_id)
        REFERENCES provenance.data_provider(provider_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE provenance.source_snapshot (
      source_snapshot_id uuid CONSTRAINT pk_source_snapshot PRIMARY KEY DEFAULT uuidv7(),
      ingestion_run_id uuid NULL,
      provider_id uuid NOT NULL,
      resource varchar(120) NOT NULL,
      request_fingerprint char(64) NOT NULL,
      provider_generated_at timestamptz NULL,
      source_updated_at timestamptz NULL,
      request_started_at timestamptz NOT NULL,
      received_at timestamptz NOT NULL,
      stored_at timestamptz NULL,
      parsed_at timestamptz NULL,
      mapped_at timestamptz NULL,
      usable_at timestamptz NULL,
      http_status smallint NULL,
      content_type text NULL,
      raw_blob_id uuid NULL,
      raw_storage_policy varchar(24) NOT NULL,
      body_sha256 char(64) NULL,
      schema_fingerprint char(64) NULL,
      terms_version text NULL,
      rights_profile_key text NOT NULL,
      validation_status varchar(24) NOT NULL,
      dataset_mode varchar(24) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT ck_source_snapshot_request_hash CHECK
        (request_fingerprint ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_source_snapshot_body_hash CHECK
        (body_sha256 IS NULL OR body_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_source_snapshot_schema_hash CHECK
        (schema_fingerprint IS NULL OR schema_fingerprint ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_source_snapshot_policy CHECK
        (raw_storage_policy IN ('ALLOWED','FORBIDDEN','EPHEMERAL','DELETED')),
      CONSTRAINT ck_source_snapshot_validation_status CHECK
        (validation_status IN ('RECEIVED','VALID','QUARANTINED','REJECTED','USABLE')),
      CONSTRAINT ck_source_snapshot_dataset_mode CHECK (dataset_mode IN
        ('LIVE_OBSERVED','RAW_OBSERVED','RECONSTRUCTED','FINAL_OUTCOME','COUNTERFACTUAL')),
      CONSTRAINT ck_source_snapshot_time_order CHECK (
        request_started_at <= received_at
        AND (stored_at IS NULL OR stored_at >= received_at)
        AND (parsed_at IS NULL OR (parsed_at >= received_at AND
             (stored_at IS NULL OR parsed_at >= stored_at)))
        AND (mapped_at IS NULL OR (mapped_at >= received_at AND
             (stored_at IS NULL OR mapped_at >= stored_at) AND
             (parsed_at IS NULL OR mapped_at >= parsed_at)))
        AND (usable_at IS NULL OR (usable_at >= received_at AND
             (stored_at IS NULL OR usable_at >= stored_at) AND
             (parsed_at IS NULL OR usable_at >= parsed_at) AND
             (mapped_at IS NULL OR usable_at >= mapped_at)))
      ),
      CONSTRAINT ck_source_snapshot_usable CHECK
        ((validation_status = 'USABLE') = (usable_at IS NOT NULL)),
      CONSTRAINT ck_source_snapshot_retention CHECK (
        (raw_storage_policy <> 'FORBIDDEN' OR raw_blob_id IS NULL)
        AND (raw_storage_policy <> 'ALLOWED' OR body_sha256 IS NULL OR raw_blob_id IS NOT NULL)
        AND (raw_blob_id IS NULL OR body_sha256 IS NOT NULL)
      ),
      CONSTRAINT fk_source_snapshot_ingestion_run FOREIGN KEY (ingestion_run_id)
        REFERENCES provenance.ingestion_run(ingestion_run_id) ON DELETE RESTRICT,
      CONSTRAINT fk_source_snapshot_provider FOREIGN KEY (provider_id)
        REFERENCES provenance.data_provider(provider_id) ON DELETE RESTRICT,
      CONSTRAINT fk_source_snapshot_raw_blob FOREIGN KEY (raw_blob_id)
        REFERENCES provenance.raw_blob(raw_blob_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE provenance.raw_blob_deletion (
      deletion_id uuid CONSTRAINT pk_raw_blob_deletion PRIMARY KEY DEFAULT uuidv7(),
      raw_blob_id uuid NOT NULL,
      deleted_at timestamptz NOT NULL,
      reason text NOT NULL,
      tombstone_sha256 char(64) NOT NULL,
      approved_by text NOT NULL,
      CONSTRAINT uq_raw_blob_deletion_raw UNIQUE (raw_blob_id),
      CONSTRAINT ck_raw_blob_deletion_hash CHECK
        (tombstone_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT fk_raw_blob_deletion_raw FOREIGN KEY (raw_blob_id)
        REFERENCES provenance.raw_blob(raw_blob_id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE core.external_identifier (
      external_identifier_id uuid CONSTRAINT pk_external_identifier PRIMARY KEY DEFAULT uuidv7(),
      canonical_entity_id uuid NOT NULL,
      provider_id uuid NOT NULL,
      provider_product varchar(120) NOT NULL,
      identifier_namespace varchar(120) NOT NULL,
      entity_type varchar(40) NOT NULL,
      external_id_text text NOT NULL,
      valid_during tstzrange NOT NULL,
      system_during tstzrange NOT NULL DEFAULT tstzrange(transaction_timestamp(), NULL, '[)'),
      mapping_status varchar(24) NOT NULL,
      mapping_method varchar(24) NOT NULL,
      match_probability numeric(7,6) NULL,
      evidence_source_snapshot_id uuid NULL,
      reviewed_by text NULL,
      reviewed_at timestamptz NULL,
      first_seen_at timestamptz NOT NULL,
      last_seen_at timestamptz NOT NULL,
      is_provider_primary boolean NOT NULL DEFAULT false,
      raw_example text NULL,
      superseded_by_mapping_id uuid NULL,
      CONSTRAINT ck_external_identifier_valid_range CHECK
        ({_canonical_range_check("valid_during")}),
      CONSTRAINT ck_external_identifier_system_range CHECK
        ({_canonical_range_check("system_during")}),
      CONSTRAINT ck_external_identifier_status CHECK (mapping_status IN
        ('UNRESOLVED','CANDIDATE','AUTO_MATCHED','HUMAN_VERIFIED','CONFLICTED','REJECTED',
         'SUPERSEDED','EXPIRED')),
      CONSTRAINT ck_external_identifier_method CHECK (mapping_method IN
        ('PROVIDER_MAPPING','DETERMINISTIC','EXACT_EXTERNAL_ID','RULE_BASED','PROBABILISTIC','MANUAL')),
      CONSTRAINT ck_external_identifier_probability CHECK
        (match_probability IS NULL OR match_probability BETWEEN 0 AND 1),
      CONSTRAINT ck_external_identifier_seen_order CHECK (first_seen_at <= last_seen_at),
      CONSTRAINT fk_external_identifier_canonical_type
        FOREIGN KEY (canonical_entity_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT,
      CONSTRAINT fk_external_identifier_provider FOREIGN KEY (provider_id)
        REFERENCES provenance.data_provider(provider_id) ON DELETE RESTRICT,
      CONSTRAINT fk_external_identifier_snapshot FOREIGN KEY (evidence_source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT fk_external_identifier_successor FOREIGN KEY (superseded_by_mapping_id)
        REFERENCES core.external_identifier(external_identifier_id) ON DELETE RESTRICT,
      CONSTRAINT ex_external_identifier_current_accepted EXCLUDE USING gist (
        provider_id WITH =, provider_product WITH =, identifier_namespace WITH =,
        entity_type WITH =, external_id_text WITH =, valid_during WITH &&
      ) WHERE (upper_inf(system_during) AND mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED'))
        DEFERRABLE INITIALLY IMMEDIATE
    )
    """,
    f"""
    CREATE TABLE core.entity_alias (
      alias_id uuid CONSTRAINT pk_entity_alias PRIMARY KEY DEFAULT uuidv7(),
      canonical_entity_id uuid NOT NULL,
      raw_text text NOT NULL,
      normalized_nfc text NOT NULL,
      match_key text NOT NULL,
      language varchar(16) NULL,
      script varchar(16) NULL,
      alias_type varchar(24) NOT NULL,
      provider_id uuid NULL,
      valid_during tstzrange NOT NULL,
      system_during tstzrange NOT NULL DEFAULT tstzrange(transaction_timestamp(), NULL, '[)'),
      source_snapshot_id uuid NULL,
      confidence numeric(7,6) NULL,
      is_preferred boolean NOT NULL DEFAULT false,
      superseded_by_alias_id uuid NULL,
      CONSTRAINT ck_entity_alias_valid_range CHECK ({_canonical_range_check("valid_during")}),
      CONSTRAINT ck_entity_alias_system_range CHECK ({_canonical_range_check("system_during")}),
      CONSTRAINT ck_entity_alias_type CHECK
        (alias_type IN ('OFFICIAL','DISPLAY','SHORT','PROVIDER','HISTORICAL','MANUAL')),
      CONSTRAINT ck_entity_alias_confidence CHECK
        (confidence IS NULL OR confidence BETWEEN 0 AND 1),
      CONSTRAINT ck_entity_alias_language_sentinel CHECK
        (language IS NULL OR language <> '__DMF_NULL__'),
      CONSTRAINT ck_entity_alias_script_sentinel CHECK
        (script IS NULL OR script <> '__DMF_NULL__'),
      CONSTRAINT fk_entity_alias_entity FOREIGN KEY (canonical_entity_id)
        REFERENCES core.canonical_entity(entity_id) ON DELETE RESTRICT,
      CONSTRAINT fk_entity_alias_provider FOREIGN KEY (provider_id)
        REFERENCES provenance.data_provider(provider_id) ON DELETE RESTRICT,
      CONSTRAINT fk_entity_alias_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT fk_entity_alias_successor FOREIGN KEY (superseded_by_alias_id)
        REFERENCES core.entity_alias(alias_id) ON DELETE RESTRICT,
      CONSTRAINT ex_entity_alias_current_preferred EXCLUDE USING gist (
        canonical_entity_id WITH =,
        (coalesce(language, '__DMF_NULL__')) WITH =,
        (coalesce(script, '__DMF_NULL__')) WITH =,
        valid_during WITH &&
      ) WHERE (upper_inf(system_during) AND is_preferred)
        DEFERRABLE INITIALLY IMMEDIATE
    )
    """,
    f"""
    CREATE TABLE football.player_team_membership (
      membership_id uuid CONSTRAINT pk_player_team_membership PRIMARY KEY DEFAULT uuidv7(),
      player_id uuid NOT NULL,
      team_id uuid NOT NULL,
      season_id uuid NOT NULL,
      registration_type varchar(24) NOT NULL,
      squad_status varchar(24) NOT NULL,
      shirt_number smallint NULL,
      valid_during tstzrange NOT NULL,
      system_during tstzrange NOT NULL DEFAULT tstzrange(transaction_timestamp(), NULL, '[)'),
      source_snapshot_id uuid NULL,
      superseded_by_membership_id uuid NULL,
      CONSTRAINT ck_membership_valid_range CHECK ({_canonical_range_check("valid_during")}),
      CONSTRAINT ck_membership_system_range CHECK ({_canonical_range_check("system_during")}),
      CONSTRAINT ck_membership_registration_type CHECK
        (registration_type IN ('PERMANENT','LOAN','YOUTH','TEMPORARY','UNKNOWN')),
      CONSTRAINT ck_membership_squad_status CHECK
        (squad_status IN ('REGISTERED','UNREGISTERED','LEFT','UNKNOWN')),
      CONSTRAINT ck_membership_shirt_number CHECK
        (shirt_number IS NULL OR shirt_number BETWEEN 1 AND 99),
      CONSTRAINT fk_membership_player FOREIGN KEY (player_id)
        REFERENCES football.player(player_id) ON DELETE RESTRICT,
      CONSTRAINT fk_membership_team FOREIGN KEY (team_id)
        REFERENCES football.team(team_id) ON DELETE RESTRICT,
      CONSTRAINT fk_membership_season FOREIGN KEY (season_id)
        REFERENCES football.season(season_id) ON DELETE RESTRICT,
      CONSTRAINT fk_membership_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT fk_membership_successor FOREIGN KEY (superseded_by_membership_id)
        REFERENCES football.player_team_membership(membership_id) ON DELETE RESTRICT,
      CONSTRAINT ex_player_team_membership_current EXCLUDE USING gist (
        player_id WITH =, registration_type WITH =, valid_during WITH &&
      ) WHERE (upper_inf(system_during)) DEFERRABLE INITIALLY IMMEDIATE
    )
    """,
    f"""
    CREATE TABLE football.fixture_revision (
      fixture_revision_id uuid CONSTRAINT pk_fixture_revision PRIMARY KEY DEFAULT uuidv7(),
      fixture_id uuid NOT NULL,
      revision_number integer NOT NULL,
      kickoff_at timestamptz NULL,
      fixture_status varchar(24) NOT NULL,
      venue text NULL,
      valid_during tstzrange NOT NULL,
      system_during tstzrange NOT NULL DEFAULT tstzrange(transaction_timestamp(), NULL, '[)'),
      observed_at timestamptz NOT NULL,
      source_snapshot_id uuid NULL,
      superseded_by_revision_id uuid NULL,
      CONSTRAINT uq_fixture_revision_number UNIQUE (fixture_id, revision_number),
      CONSTRAINT ck_fixture_revision_number CHECK (revision_number > 0),
      CONSTRAINT ck_fixture_revision_status CHECK (fixture_status IN
        ('SCHEDULED','POSTPONED','CANCELLED','STARTED','FINISHED','ABANDONED','UNKNOWN')),
      CONSTRAINT ck_fixture_revision_valid_range CHECK
        ({_canonical_range_check("valid_during")}),
      CONSTRAINT ck_fixture_revision_system_range CHECK
        ({_canonical_range_check("system_during")}),
      CONSTRAINT fk_fixture_revision_fixture FOREIGN KEY (fixture_id)
        REFERENCES football.fixture(fixture_id) ON DELETE RESTRICT,
      CONSTRAINT fk_fixture_revision_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT fk_fixture_revision_successor FOREIGN KEY (superseded_by_revision_id)
        REFERENCES football.fixture_revision(fixture_revision_id) ON DELETE RESTRICT,
      CONSTRAINT ex_fixture_revision_current EXCLUDE USING gist (
        fixture_id WITH =, valid_during WITH &&
      ) WHERE (upper_inf(system_during)) DEFERRABLE INITIALLY IMMEDIATE
    )
    """,
    f"""
    CREATE TABLE football.fixture_gameweek_assignment (
      assignment_id uuid CONSTRAINT pk_fixture_gameweek_assignment PRIMARY KEY DEFAULT uuidv7(),
      fixture_id uuid NOT NULL,
      gameweek_id uuid NULL,
      assignment_status varchar(24) NOT NULL,
      valid_during tstzrange NOT NULL,
      system_during tstzrange NOT NULL DEFAULT tstzrange(transaction_timestamp(), NULL, '[)'),
      source_snapshot_id uuid NULL,
      superseded_by_assignment_id uuid NULL,
      CONSTRAINT ck_assignment_status CHECK
        (assignment_status IN ('ASSIGNED','UNASSIGNED','PROVISIONAL','FINAL')),
      CONSTRAINT ck_assignment_gameweek_coherence CHECK (
        (assignment_status IN ('ASSIGNED','FINAL') AND gameweek_id IS NOT NULL)
        OR (assignment_status = 'UNASSIGNED' AND gameweek_id IS NULL)
        OR assignment_status = 'PROVISIONAL'
      ),
      CONSTRAINT ck_assignment_valid_range CHECK ({_canonical_range_check("valid_during")}),
      CONSTRAINT ck_assignment_system_range CHECK ({_canonical_range_check("system_during")}),
      CONSTRAINT fk_assignment_fixture FOREIGN KEY (fixture_id)
        REFERENCES football.fixture(fixture_id) ON DELETE RESTRICT,
      CONSTRAINT fk_assignment_gameweek FOREIGN KEY (gameweek_id)
        REFERENCES fpl.gameweek(gameweek_id) ON DELETE RESTRICT,
      CONSTRAINT fk_assignment_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT fk_assignment_successor FOREIGN KEY (superseded_by_assignment_id)
        REFERENCES football.fixture_gameweek_assignment(assignment_id) ON DELETE RESTRICT,
      CONSTRAINT ex_fixture_gameweek_assignment_current EXCLUDE USING gist (
        fixture_id WITH =, valid_during WITH &&
      ) WHERE (upper_inf(system_during)) DEFERRABLE INITIALLY IMMEDIATE
    )
    """,
    """
    CREATE TABLE core.data_quality_issue (
      data_quality_issue_id uuid CONSTRAINT pk_data_quality_issue PRIMARY KEY DEFAULT uuidv7(),
      source_snapshot_id uuid NULL,
      canonical_entity_id uuid NULL,
      ingestion_run_id uuid NULL,
      issue_type varchar(80) NOT NULL,
      severity varchar(12) NOT NULL,
      status varchar(20) NOT NULL,
      detected_at timestamptz NOT NULL,
      resolved_at timestamptz NULL,
      owner text NULL,
      decision_impact text NOT NULL,
      details jsonb NOT NULL DEFAULT '{}'::jsonb,
      CONSTRAINT ck_data_quality_severity CHECK (severity IN ('INFO','WARN','ERROR','BLOCKING')),
      CONSTRAINT ck_data_quality_status CHECK
        (status IN ('OPEN','ACKNOWLEDGED','RESOLVED','SUPERSEDED')),
      CONSTRAINT ck_data_quality_resolution CHECK
        (resolved_at IS NULL OR resolved_at >= detected_at),
      CONSTRAINT fk_data_quality_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT fk_data_quality_entity FOREIGN KEY (canonical_entity_id)
        REFERENCES core.canonical_entity(entity_id) ON DELETE RESTRICT,
      CONSTRAINT fk_data_quality_ingestion_run FOREIGN KEY (ingestion_run_id)
        REFERENCES provenance.ingestion_run(ingestion_run_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE provenance.ruleset_artifact (
      ruleset_artifact_id uuid CONSTRAINT pk_ruleset_artifact PRIMARY KEY DEFAULT uuidv7(),
      ruleset_id varchar(100) NOT NULL,
      ruleset_version varchar(80) NOT NULL,
      schema_version varchar(40) NOT NULL,
      source_ruleset_hash char(64) NOT NULL,
      artifact_uri text NOT NULL,
      artifact_sha256 char(64) NOT NULL,
      ruleset_status varchar(24) NOT NULL,
      registered_at timestamptz NOT NULL,
      CONSTRAINT ck_ruleset_artifact_source_hash CHECK
        (source_ruleset_hash ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_ruleset_artifact_hash CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT uq_ruleset_artifact_identity_hash UNIQUE
        (ruleset_id, ruleset_version, source_ruleset_hash)
    )
    """,
    """
    CREATE TABLE provenance.ruleset_activation (
      ruleset_activation_id uuid CONSTRAINT pk_ruleset_activation PRIMARY KEY DEFAULT uuidv7(),
      ruleset_artifact_id uuid NOT NULL,
      active_ruleset_hash char(64) NOT NULL,
      approval_sha256 char(64) NOT NULL,
      activation_manifest_sha256 char(64) NOT NULL,
      approval_uri text NOT NULL,
      activation_manifest_uri text NOT NULL,
      approved_by text NOT NULL,
      approved_at timestamptz NOT NULL,
      activated_at timestamptz NOT NULL,
      CONSTRAINT uq_ruleset_activation_artifact UNIQUE (ruleset_artifact_id),
      CONSTRAINT ck_ruleset_activation_active_hash CHECK
        (active_ruleset_hash ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_ruleset_activation_approval_hash CHECK
        (approval_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_ruleset_activation_manifest_hash CHECK
        (activation_manifest_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT fk_ruleset_activation_artifact FOREIGN KEY (ruleset_artifact_id)
        REFERENCES provenance.ruleset_artifact(ruleset_artifact_id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_season_competition ON football.season (competition_id)",
    "CREATE INDEX ix_fixture_competition ON football.fixture (competition_id)",
    "CREATE INDEX ix_fixture_season ON football.fixture (season_id)",
    "CREATE INDEX ix_fixture_home_team ON football.fixture (home_team_id)",
    "CREATE INDEX ix_fixture_away_team ON football.fixture (away_team_id)",
    "CREATE INDEX ix_gameweek_season ON fpl.gameweek (season_id)",
    "CREATE INDEX ix_ingestion_run_provider ON provenance.ingestion_run (provider_id)",
    "CREATE INDEX ix_source_snapshot_provider ON provenance.source_snapshot (provider_id)",
    "CREATE INDEX ix_source_snapshot_run ON provenance.source_snapshot (ingestion_run_id)",
    "CREATE INDEX ix_source_snapshot_raw ON provenance.source_snapshot (raw_blob_id)",
    "CREATE INDEX ix_external_identifier_entity ON core.external_identifier (canonical_entity_id)",
    "CREATE INDEX ix_external_identifier_provider ON core.external_identifier (provider_id)",
    "CREATE INDEX ix_external_identifier_snapshot ON core.external_identifier (evidence_source_snapshot_id)",
    "CREATE INDEX ix_external_identifier_as_of ON core.external_identifier USING gist (canonical_entity_id, valid_during, system_during)",
    "CREATE INDEX ix_entity_alias_entity ON core.entity_alias (canonical_entity_id)",
    "CREATE INDEX ix_entity_alias_provider ON core.entity_alias (provider_id)",
    "CREATE INDEX ix_entity_alias_snapshot ON core.entity_alias (source_snapshot_id)",
    "CREATE INDEX ix_entity_alias_as_of ON core.entity_alias USING gist (canonical_entity_id, valid_during, system_during)",
    "CREATE INDEX ix_membership_team ON football.player_team_membership (team_id)",
    "CREATE INDEX ix_membership_season ON football.player_team_membership (season_id)",
    "CREATE INDEX ix_membership_snapshot ON football.player_team_membership (source_snapshot_id)",
    "CREATE INDEX ix_membership_as_of ON football.player_team_membership USING gist (player_id, registration_type, valid_during, system_during)",
    "CREATE INDEX ix_fixture_revision_snapshot ON football.fixture_revision (source_snapshot_id)",
    "CREATE INDEX ix_fixture_revision_as_of ON football.fixture_revision USING gist (fixture_id, valid_during, system_during)",
    "CREATE INDEX ix_assignment_gameweek ON football.fixture_gameweek_assignment (gameweek_id)",
    "CREATE INDEX ix_assignment_snapshot ON football.fixture_gameweek_assignment (source_snapshot_id)",
    "CREATE INDEX ix_assignment_as_of ON football.fixture_gameweek_assignment USING gist (fixture_id, valid_during, system_during)",
    "CREATE INDEX ix_data_quality_snapshot ON core.data_quality_issue (source_snapshot_id)",
    "CREATE INDEX ix_data_quality_entity ON core.data_quality_issue (canonical_entity_id)",
    "CREATE INDEX ix_data_quality_run ON core.data_quality_issue (ingestion_run_id)",
    """
    CREATE TRIGGER trg_external_identifier_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON core.external_identifier
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'external_identifier_id', 'superseded_by_mapping_id',
      'canonical_entity_id', 'provider_id'
    )
    """,
    """
    CREATE TRIGGER trg_entity_alias_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON core.entity_alias
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'alias_id', 'superseded_by_alias_id', 'canonical_entity_id'
    )
    """,
    """
    CREATE TRIGGER trg_player_team_membership_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON football.player_team_membership
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'membership_id', 'superseded_by_membership_id', 'player_id', 'registration_type'
    )
    """,
    """
    CREATE TRIGGER trg_fixture_revision_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON football.fixture_revision
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'fixture_revision_id', 'superseded_by_revision_id', 'fixture_id'
    )
    """,
    """
    CREATE TRIGGER trg_fixture_gameweek_assignment_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON football.fixture_gameweek_assignment
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'assignment_id', 'superseded_by_assignment_id', 'fixture_id'
    )
    """,
    """
    CREATE TRIGGER trg_raw_blob_immutable
    BEFORE UPDATE OR DELETE ON provenance.raw_blob
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_raw_blob_deletion_immutable
    BEFORE UPDATE OR DELETE ON provenance.raw_blob_deletion
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_source_snapshot_immutable
    BEFORE UPDATE OR DELETE ON provenance.source_snapshot
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_ruleset_artifact_immutable
    BEFORE UPDATE OR DELETE ON provenance.ruleset_artifact
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_ruleset_activation_immutable
    BEFORE UPDATE OR DELETE ON provenance.ruleset_activation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE VIEW core.current_external_identifier AS
    SELECT * FROM core.external_identifier WHERE upper_inf(system_during)
    """,
    """
    CREATE VIEW core.current_entity_alias AS
    SELECT * FROM core.entity_alias WHERE upper_inf(system_during)
    """,
    """
    CREATE VIEW football.current_player_team_membership AS
    SELECT * FROM football.player_team_membership WHERE upper_inf(system_during)
    """,
    """
    CREATE VIEW football.current_fixture_revision AS
    SELECT * FROM football.fixture_revision WHERE upper_inf(system_during)
    """,
    """
    CREATE VIEW football.current_fixture_gameweek_assignment AS
    SELECT * FROM football.fixture_gameweek_assignment WHERE upper_inf(system_during)
    """,
    """
    CREATE VIEW provenance.available_raw_blob AS
    SELECT raw.*
    FROM provenance.raw_blob AS raw
    WHERE NOT EXISTS (
      SELECT 1 FROM provenance.raw_blob_deletion AS deletion
      WHERE deletion.raw_blob_id = raw.raw_blob_id
    )
    """,
)


def _starts_with(statement: str, prefix: str) -> bool:
    return statement.lstrip().startswith(prefix)


_FUNCTION_STATEMENTS = tuple(
    statement for statement in _DDL_STATEMENTS if _starts_with(statement, "CREATE FUNCTION")
)
_TRIGGER_STATEMENTS = tuple(
    statement for statement in _DDL_STATEMENTS if _starts_with(statement, "CREATE TRIGGER")
)
_VIEW_STATEMENTS = tuple(
    statement for statement in _DDL_STATEMENTS if _starts_with(statement, "CREATE VIEW")
)
_BASE_STATEMENTS = tuple(
    statement
    for statement in _DDL_STATEMENTS
    if not any(
        _starts_with(statement, prefix)
        for prefix in ("CREATE FUNCTION", "CREATE TRIGGER", "CREATE VIEW")
    )
)
UPGRADE_STATEMENTS = (
    *_BASE_STATEMENTS,
    *_FUNCTION_STATEMENTS,
    *_TRIGGER_STATEMENTS,
    *_VIEW_STATEMENTS,
)

DOWNGRADE_STATEMENTS = (
    "DROP VIEW provenance.available_raw_blob",
    "DROP VIEW football.current_fixture_gameweek_assignment",
    "DROP VIEW football.current_fixture_revision",
    "DROP VIEW football.current_player_team_membership",
    "DROP VIEW core.current_entity_alias",
    "DROP VIEW core.current_external_identifier",
    "DROP TABLE core.data_quality_issue",
    "DROP TABLE provenance.ruleset_activation",
    "DROP TABLE provenance.ruleset_artifact",
    "DROP TABLE football.fixture_gameweek_assignment",
    "DROP TABLE football.fixture_revision",
    "DROP TABLE football.player_team_membership",
    "DROP TABLE core.entity_alias",
    "DROP TABLE core.external_identifier",
    "DROP TABLE provenance.raw_blob_deletion",
    "DROP TABLE provenance.source_snapshot",
    "DROP TABLE provenance.ingestion_run",
    "DROP TABLE provenance.raw_blob",
    "DROP TABLE fpl.gameweek",
    "DROP TABLE football.fixture",
    "DROP TABLE football.season",
    "DROP TABLE provenance.data_provider",
    "DROP TABLE football.player",
    "DROP TABLE football.team",
    "DROP TABLE football.competition",
    "DROP TABLE core.canonical_entity",
    "DROP FUNCTION core.guard_temporal_version()",
    "DROP FUNCTION core.guard_canonical_successor()",
    "DROP FUNCTION provenance.reject_immutable_change()",
    "DROP FUNCTION core.is_canonical_tstzrange(tstzrange)",
    "DROP EXTENSION btree_gist",
    "DROP SCHEMA provenance",
    "DROP SCHEMA fpl",
    "DROP SCHEMA football",
    "DROP SCHEMA core",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
