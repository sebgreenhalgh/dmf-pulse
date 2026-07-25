"""Remediate DAT-003 and add the FPL-004 ingestion foundation.

Revision ID: 20260724_0002
Revises: 20260723_0001
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260724_0002"
down_revision: str | None = "20260723_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPGRADE_STATEMENTS = (
    "ALTER TABLE football.season ADD CONSTRAINT uq_season_id_competition UNIQUE (season_id, competition_id)",
    """
    CREATE TABLE football.team_season (
      team_season_id uuid CONSTRAINT pk_team_season PRIMARY KEY DEFAULT uuidv7(),
      team_id uuid NOT NULL,
      season_id uuid NOT NULL,
      source_snapshot_id uuid NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT uq_team_season_identity UNIQUE (team_id, season_id),
      CONSTRAINT uq_team_season_id_season UNIQUE (team_season_id, season_id),
      CONSTRAINT fk_team_season_team FOREIGN KEY (team_id)
        REFERENCES football.team(team_id) ON DELETE RESTRICT,
      CONSTRAINT fk_team_season_season FOREIGN KEY (season_id)
        REFERENCES football.season(season_id) ON DELETE RESTRICT,
      CONSTRAINT fk_team_season_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT
    )
    """,
    """
    INSERT INTO football.team_season (team_id, season_id)
    SELECT candidate.team_id, candidate.season_id
    FROM (
      SELECT home_team_id AS team_id, season_id FROM football.fixture
      UNION
      SELECT away_team_id AS team_id, season_id FROM football.fixture
      UNION
      SELECT team_id, season_id FROM football.player_team_membership
    ) AS candidate
    ON CONFLICT (team_id, season_id) DO NOTHING
    """,
    "ALTER TABLE football.fixture ADD CONSTRAINT uq_fixture_id_season UNIQUE (fixture_id, season_id)",
    """
    ALTER TABLE football.fixture ADD CONSTRAINT fk_fixture_season_competition
      FOREIGN KEY (season_id, competition_id)
      REFERENCES football.season(season_id, competition_id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE football.fixture ADD CONSTRAINT fk_fixture_home_team_season
      FOREIGN KEY (home_team_id, season_id)
      REFERENCES football.team_season(team_id, season_id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE football.fixture ADD CONSTRAINT fk_fixture_away_team_season
      FOREIGN KEY (away_team_id, season_id)
      REFERENCES football.team_season(team_id, season_id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE football.player_team_membership ADD CONSTRAINT fk_membership_team_season
      FOREIGN KEY (team_id, season_id)
      REFERENCES football.team_season(team_id, season_id) ON DELETE RESTRICT
    """,
    "ALTER TABLE fpl.gameweek ADD CONSTRAINT uq_gameweek_id_season UNIQUE (gameweek_id, season_id)",
    "ALTER TABLE football.fixture_gameweek_assignment ADD COLUMN season_id uuid",
    "DROP TRIGGER trg_fixture_gameweek_assignment_temporal ON football.fixture_gameweek_assignment",
    """
    UPDATE football.fixture_gameweek_assignment AS assignment
    SET season_id = fixture_record.season_id
    FROM football.fixture AS fixture_record
    WHERE fixture_record.fixture_id = assignment.fixture_id
    """,
    "ALTER TABLE football.fixture_gameweek_assignment ALTER COLUMN season_id SET NOT NULL",
    """
    ALTER TABLE football.fixture_gameweek_assignment ADD CONSTRAINT fk_assignment_fixture_season
      FOREIGN KEY (fixture_id, season_id)
      REFERENCES football.fixture(fixture_id, season_id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE football.fixture_gameweek_assignment ADD CONSTRAINT fk_assignment_gameweek_season
      FOREIGN KEY (gameweek_id, season_id)
      REFERENCES fpl.gameweek(gameweek_id, season_id) ON DELETE RESTRICT
    """,
    """
    CREATE TRIGGER trg_fixture_gameweek_assignment_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON football.fixture_gameweek_assignment
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'assignment_id', 'superseded_by_assignment_id', 'fixture_id'
    )
    """,
    "ALTER TABLE provenance.ruleset_artifact DROP CONSTRAINT uq_ruleset_artifact_identity_hash",
    "ALTER TABLE provenance.ruleset_artifact ADD CONSTRAINT uq_ruleset_artifact_identity UNIQUE (ruleset_id, ruleset_version)",
    "ALTER TABLE provenance.raw_blob ALTER COLUMN storage_policy DROP NOT NULL",
    "ALTER TABLE provenance.raw_blob ADD CONSTRAINT uq_raw_blob_content_coherence UNIQUE (raw_blob_id, body_sha256, byte_size)",
    """
    CREATE TABLE provenance.rights_profile (
      rights_profile_record_id uuid CONSTRAINT pk_rights_profile PRIMARY KEY DEFAULT uuidv7(),
      rights_profile_id varchar(120) NOT NULL,
      provider_key varchar(80) NOT NULL,
      profile_version varchar(40) NOT NULL,
      status varchar(24) NOT NULL,
      capabilities jsonb NOT NULL,
      retention_seconds bigint NULL,
      retention_reason text NULL,
      termination_deletion_required boolean NOT NULL,
      attribution_required boolean NOT NULL,
      attribution_text text NULL,
      geography_scope text NOT NULL,
      account_scope text NOT NULL,
      approved_purpose text NOT NULL,
      terms_source text NOT NULL,
      terms_version text NOT NULL,
      checked_at timestamptz NOT NULL,
      human_approval_id text NOT NULL,
      approved_by text NOT NULL,
      approved_at timestamptz NOT NULL,
      notes text NOT NULL DEFAULT '',
      unresolved_rights jsonb NOT NULL DEFAULT '[]'::jsonb,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT uq_rights_profile_identity_version UNIQUE (rights_profile_id, profile_version),
      CONSTRAINT uq_rights_profile_record_identity_version UNIQUE
        (rights_profile_record_id, rights_profile_id, profile_version),
      CONSTRAINT fk_rights_profile_provider_key FOREIGN KEY (provider_key)
        REFERENCES provenance.data_provider(provider_key) ON DELETE RESTRICT,
      CONSTRAINT ck_rights_profile_status CHECK
        (status IN ('DRAFT','HUMAN_APPROVED','BLOCKED','SUPERSEDED','WITHDRAWN')),
      CONSTRAINT ck_rights_profile_retention CHECK
        (retention_seconds IS NULL OR retention_seconds >= 0),
      CONSTRAINT ck_rights_profile_capabilities_object CHECK
        (jsonb_typeof(capabilities) = 'object')
    )
    """,
    """
    CREATE TABLE provenance.raw_storage_object (
      raw_storage_object_id uuid CONSTRAINT pk_raw_storage_object PRIMARY KEY DEFAULT uuidv7(),
      raw_blob_id uuid NOT NULL,
      rights_profile_record_id uuid NOT NULL,
      stored_blob_sha256 char(64) NOT NULL,
      storage_uri text NOT NULL,
      storage_policy varchar(24) NOT NULL,
      content_type text NOT NULL,
      retention_seconds bigint NULL,
      access_allowed boolean NOT NULL,
      export_allowed boolean NOT NULL,
      backup_allowed boolean NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT uq_raw_storage_context_uri UNIQUE
        (raw_blob_id, storage_uri),
      CONSTRAINT uq_raw_storage_coherence UNIQUE
        (raw_storage_object_id, raw_blob_id, rights_profile_record_id),
      CONSTRAINT fk_raw_storage_content FOREIGN KEY (raw_blob_id)
        REFERENCES provenance.raw_blob(raw_blob_id) ON DELETE RESTRICT,
      CONSTRAINT fk_raw_storage_rights_profile FOREIGN KEY (rights_profile_record_id)
        REFERENCES provenance.rights_profile(rights_profile_record_id) ON DELETE RESTRICT,
      CONSTRAINT ck_raw_storage_stored_hash CHECK
        (stored_blob_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_raw_storage_policy CHECK (storage_policy IN ('ALLOWED','EPHEMERAL')),
      CONSTRAINT ck_raw_storage_retention CHECK
        (retention_seconds IS NULL OR retention_seconds >= 0)
    )
    """,
    """
    CREATE FUNCTION provenance.guard_raw_storage_rights()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
      profile_status text;
      profile_capabilities jsonb;
      profile_retention bigint;
      content_sha256 text;
    BEGIN
      SELECT status, capabilities, retention_seconds
      INTO profile_status, profile_capabilities, profile_retention
      FROM provenance.rights_profile
      WHERE rights_profile_record_id = NEW.rights_profile_record_id;
      SELECT body_sha256 INTO content_sha256
      FROM provenance.raw_blob WHERE raw_blob_id = NEW.raw_blob_id;
      IF profile_status IS DISTINCT FROM 'HUMAN_APPROVED'
         OR profile_capabilities ->> 'raw_storage' IS DISTINCT FROM 'ALLOW'
         OR content_sha256 IS DISTINCT FROM NEW.stored_blob_sha256 THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'RAW_STORAGE_RIGHTS_BLOCKED';
      END IF;
      IF (NEW.access_allowed
          AND profile_capabilities ->> 'private_internal_use' IS DISTINCT FROM 'ALLOW')
         OR (NEW.export_allowed
             AND profile_capabilities ->> 'redistribution' IS DISTINCT FROM 'ALLOW')
         OR (NEW.backup_allowed
             AND profile_capabilities ->> 'backup' IS DISTINCT FROM 'ALLOW') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'RAW_STORAGE_CAPABILITY_BLOCKED';
      END IF;
      IF profile_retention IS NOT NULL
         AND (NEW.retention_seconds IS NULL OR NEW.retention_seconds > profile_retention) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'RAW_STORAGE_RETENTION_EXCEEDED';
      END IF;
      RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER trg_raw_storage_rights
    BEFORE INSERT ON provenance.raw_storage_object
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_raw_storage_rights()
    """,
    """
    CREATE TABLE provenance.raw_storage_deletion (
      raw_storage_deletion_id uuid CONSTRAINT pk_raw_storage_deletion PRIMARY KEY DEFAULT uuidv7(),
      raw_storage_object_id uuid NOT NULL,
      deleted_at timestamptz NOT NULL,
      reason text NOT NULL,
      tombstone_sha256 char(64) NOT NULL,
      approved_by text NOT NULL,
      CONSTRAINT uq_raw_storage_deletion_object UNIQUE (raw_storage_object_id),
      CONSTRAINT fk_raw_storage_deletion_object FOREIGN KEY (raw_storage_object_id)
        REFERENCES provenance.raw_storage_object(raw_storage_object_id) ON DELETE RESTRICT,
      CONSTRAINT ck_raw_storage_deletion_hash CHECK
        (tombstone_sha256 ~ '^[0-9a-f]{64}$')
    )
    """,
    "ALTER TABLE provenance.source_snapshot ADD COLUMN body_size bigint",
    "ALTER TABLE provenance.source_snapshot ADD COLUMN attempt_number integer",
    "ALTER TABLE provenance.source_snapshot ADD COLUMN sanitized_target text",
    "ALTER TABLE provenance.source_snapshot ADD COLUMN raw_storage_object_id uuid",
    "ALTER TABLE provenance.source_snapshot ADD COLUMN rights_profile_version varchar(40)",
    "ALTER TABLE provenance.source_snapshot ADD COLUMN rights_profile_record_id uuid",
    "ALTER TABLE provenance.source_snapshot ADD COLUMN adapter_version varchar(40)",
    "ALTER TABLE provenance.source_snapshot ADD COLUMN contract_version varchar(40)",
    "ALTER TABLE provenance.source_snapshot ADD COLUMN envelope_sha256 char(64)",
    """
    ALTER TABLE provenance.source_snapshot ADD CONSTRAINT fk_source_snapshot_raw_storage
      FOREIGN KEY (raw_storage_object_id)
      REFERENCES provenance.raw_storage_object(raw_storage_object_id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE provenance.source_snapshot ADD CONSTRAINT fk_source_snapshot_rights_profile
      FOREIGN KEY (rights_profile_record_id)
      REFERENCES provenance.rights_profile(rights_profile_record_id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE provenance.source_snapshot
      ADD CONSTRAINT fk_source_snapshot_raw_storage_coherence
      FOREIGN KEY (raw_storage_object_id, raw_blob_id, rights_profile_record_id)
      REFERENCES provenance.raw_storage_object
        (raw_storage_object_id, raw_blob_id, rights_profile_record_id)
      ON DELETE RESTRICT
    """,
    """
    ALTER TABLE provenance.source_snapshot
      ADD CONSTRAINT fk_source_snapshot_raw_content_coherence
      FOREIGN KEY (raw_blob_id, body_sha256, body_size)
      REFERENCES provenance.raw_blob (raw_blob_id, body_sha256, byte_size)
      ON DELETE RESTRICT
    """,
    """
    ALTER TABLE provenance.source_snapshot
      ADD CONSTRAINT fk_source_snapshot_rights_profile_version
      FOREIGN KEY (rights_profile_record_id, rights_profile_key, rights_profile_version)
      REFERENCES provenance.rights_profile
        (rights_profile_record_id, rights_profile_id, profile_version)
      ON DELETE RESTRICT
    """,
    "ALTER TABLE provenance.source_snapshot ADD CONSTRAINT uq_source_snapshot_rights_profile UNIQUE (source_snapshot_id, rights_profile_record_id)",
    "ALTER TABLE provenance.source_snapshot ADD CONSTRAINT ck_source_snapshot_body_size CHECK (body_size IS NULL OR body_size >= 0)",
    """
    ALTER TABLE provenance.source_snapshot ADD CONSTRAINT ck_source_snapshot_attempt CHECK (
      (ingestion_run_id IS NULL) = (attempt_number IS NULL)
      AND (attempt_number IS NULL OR attempt_number > 0)
    )
    """,
    "ALTER TABLE provenance.source_snapshot ADD CONSTRAINT ck_source_snapshot_envelope_hash CHECK (envelope_sha256 IS NULL OR envelope_sha256 ~ '^[0-9a-f]{64}$')",
    "ALTER TABLE provenance.source_snapshot DROP CONSTRAINT ck_source_snapshot_retention",
    """
    ALTER TABLE provenance.source_snapshot ADD CONSTRAINT ck_source_snapshot_retention CHECK (
      (raw_storage_policy <> 'FORBIDDEN' OR raw_storage_object_id IS NULL)
      AND (raw_storage_policy <> 'ALLOWED' OR body_sha256 IS NULL OR raw_blob_id IS NOT NULL)
      AND (rights_profile_record_id IS NULL OR raw_storage_policy <> 'ALLOWED'
           OR body_sha256 IS NULL OR raw_storage_object_id IS NOT NULL)
      AND (raw_storage_object_id IS NULL OR raw_blob_id IS NOT NULL)
      AND (raw_storage_object_id IS NULL OR rights_profile_record_id IS NOT NULL)
      AND (rights_profile_record_id IS NULL OR rights_profile_version IS NOT NULL)
      AND (rights_profile_record_id IS NULL OR body_sha256 IS NULL OR body_size IS NOT NULL)
      AND (raw_blob_id IS NULL OR body_sha256 IS NOT NULL)
    )
    """,
    """
    CREATE TABLE provenance.rights_decision (
      rights_decision_id uuid CONSTRAINT pk_rights_decision PRIMARY KEY DEFAULT uuidv7(),
      rights_profile_record_id uuid NOT NULL,
      source_snapshot_id uuid NULL,
      capability varchar(48) NOT NULL,
      decision varchar(8) NOT NULL,
      reason_code varchar(80) NOT NULL,
      checked_at timestamptz NOT NULL,
      context_sha256 char(64) NOT NULL,
      CONSTRAINT fk_rights_decision_profile FOREIGN KEY (rights_profile_record_id)
        REFERENCES provenance.rights_profile(rights_profile_record_id) ON DELETE RESTRICT,
      CONSTRAINT fk_rights_decision_snapshot_profile
        FOREIGN KEY (source_snapshot_id, rights_profile_record_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id, rights_profile_record_id)
        ON DELETE RESTRICT,
      CONSTRAINT ck_rights_decision_value CHECK (decision IN ('ALLOW','DENY')),
      CONSTRAINT ck_rights_decision_context_hash CHECK
        (context_sha256 ~ '^[0-9a-f]{64}$')
    )
    """,
    """
    CREATE TABLE provenance.source_processing_event (
      processing_event_id uuid CONSTRAINT pk_source_processing_event PRIMARY KEY DEFAULT uuidv7(),
      source_snapshot_id uuid NOT NULL,
      operation_id uuid NOT NULL,
      previous_event_id uuid NULL,
      sequence_number integer NOT NULL,
      stage varchar(32) NOT NULL,
      outcome varchar(24) NOT NULL DEFAULT 'SUCCEEDED',
      event_at timestamptz NOT NULL,
      stage_version varchar(40) NOT NULL,
      input_sha256 char(64) NULL,
      output_sha256 char(64) NULL,
      event_sha256 char(64) NOT NULL,
      safe_details jsonb NOT NULL DEFAULT '{}'::jsonb,
      error_code varchar(80) NULL,
      actor varchar(80) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT fk_processing_event_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT fk_processing_event_previous FOREIGN KEY (previous_event_id)
        REFERENCES provenance.source_processing_event(processing_event_id) ON DELETE RESTRICT,
      CONSTRAINT uq_processing_event_snapshot_sequence UNIQUE
        (source_snapshot_id, sequence_number),
      CONSTRAINT uq_processing_event_hash UNIQUE (event_sha256),
      CONSTRAINT ck_processing_event_sequence CHECK (sequence_number > 0),
      CONSTRAINT ck_processing_event_stage CHECK (stage IN (
        'RECEIVED','STORED','RAW_DISCARDED','PARSED','VALIDATED','MAPPED','PROMOTED',
        'QUALITY_PASSED','USABLE','QUARANTINED','REJECTED','CANCELLED',
        'FAILED_RETRYABLE','FAILED_PERMANENT')),
      CONSTRAINT ck_processing_event_outcome CHECK
        (outcome IN ('SUCCEEDED','FAILED_RETRYABLE','FAILED_PERMANENT')),
      CONSTRAINT ck_processing_event_input_hash CHECK
        (input_sha256 IS NULL OR input_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_processing_event_output_hash CHECK
        (output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_processing_event_event_hash CHECK
        (event_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_processing_event_details_object CHECK
        (jsonb_typeof(safe_details) = 'object')
    )
    """,
    """
    CREATE TABLE provenance.source_mapping_candidate (
      mapping_candidate_id uuid CONSTRAINT pk_source_mapping_candidate PRIMARY KEY
        DEFAULT uuidv7(),
      provider_id uuid NOT NULL,
      competition_key varchar(80) NOT NULL,
      season_code varchar(32) NOT NULL,
      provider_product varchar(64) NOT NULL,
      identifier_namespace varchar(96) NOT NULL,
      entity_type varchar(32) NOT NULL,
      external_id_text text NOT NULL,
      planned_entity_id uuid NOT NULL,
      evidence_source_snapshot_id uuid NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT fk_mapping_candidate_provider FOREIGN KEY (provider_id)
        REFERENCES provenance.data_provider(provider_id) ON DELETE RESTRICT,
      CONSTRAINT fk_mapping_candidate_snapshot FOREIGN KEY (evidence_source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT uq_mapping_candidate_scope UNIQUE (
        provider_id, competition_key, season_code, provider_product,
        identifier_namespace, entity_type, external_id_text
      ),
      CONSTRAINT ck_mapping_candidate_entity_type CHECK (
        entity_type IN ('COMPETITION','SEASON','TEAM','PLAYER','GAMEWEEK','FIXTURE')
      )
    )
    """,
    """
    CREATE TRIGGER trg_source_mapping_candidate_immutable
    BEFORE UPDATE OR DELETE ON provenance.source_mapping_candidate
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    INSERT INTO provenance.source_processing_event (
      source_snapshot_id, operation_id, sequence_number, stage, event_at, stage_version,
      event_sha256, actor
    )
    SELECT source_snapshot_id, source_snapshot_id, 1, 'RECEIVED', received_at, 'legacy-dat003',
           encode(sha256(convert_to(source_snapshot_id::text || chr(58) || '1', 'UTF8')), 'hex'),
           'dat003-migration'
    FROM provenance.source_snapshot
    """,
    """
    INSERT INTO provenance.source_processing_event (
      source_snapshot_id, operation_id, sequence_number, stage, event_at, stage_version,
      event_sha256, actor
    )
    SELECT source_snapshot_id, source_snapshot_id, 2,
           CASE WHEN raw_storage_policy = 'FORBIDDEN' THEN 'RAW_DISCARDED' ELSE 'STORED' END,
           COALESCE(stored_at, received_at), 'legacy-dat003',
           encode(sha256(convert_to(source_snapshot_id::text || chr(58) || '2', 'UTF8')), 'hex'),
           'dat003-migration'
    FROM provenance.source_snapshot
    WHERE stored_at IS NOT NULL OR validation_status <> 'RECEIVED'
    """,
    """
    INSERT INTO provenance.source_processing_event (
      source_snapshot_id, operation_id, sequence_number, stage, event_at, stage_version,
      event_sha256, actor
    )
    SELECT source_snapshot_id, source_snapshot_id, stage_record.sequence_number,
           stage_record.stage,
           CASE stage_record.stage
             WHEN 'PARSED' THEN COALESCE(parsed_at, stored_at, received_at)
             WHEN 'VALIDATED' THEN COALESCE(parsed_at, stored_at, received_at)
             WHEN 'MAPPED' THEN COALESCE(mapped_at, parsed_at, stored_at, received_at)
             WHEN 'PROMOTED' THEN COALESCE(mapped_at, parsed_at, stored_at, received_at)
             WHEN 'QUALITY_PASSED' THEN COALESCE(usable_at, mapped_at, parsed_at, received_at)
             WHEN 'USABLE' THEN COALESCE(usable_at, mapped_at, parsed_at, received_at)
           END,
           'legacy-dat003',
           encode(sha256(convert_to(source_snapshot_id::text || chr(58)
                    || stage_record.sequence_number::text, 'UTF8')), 'hex'),
           'dat003-migration'
    FROM provenance.source_snapshot
    CROSS JOIN (VALUES (3, 'PARSED'), (4, 'VALIDATED'), (5, 'MAPPED'), (6, 'PROMOTED'),
                       (7, 'QUALITY_PASSED'), (8, 'USABLE'))
      AS stage_record(sequence_number, stage)
    WHERE validation_status = 'USABLE'
    """,
    """
    INSERT INTO provenance.source_processing_event (
      source_snapshot_id, operation_id, sequence_number, stage, event_at, stage_version,
      event_sha256, actor
    )
    SELECT source_snapshot_id, source_snapshot_id, stage_record.sequence_number,
           stage_record.stage,
           GREATEST(COALESCE(parsed_at, received_at), COALESCE(stored_at, received_at)),
           'legacy-dat003',
           encode(sha256(convert_to(source_snapshot_id::text || chr(58)
                    || stage_record.sequence_number::text, 'UTF8')), 'hex'),
           'dat003-migration'
    FROM provenance.source_snapshot
    CROSS JOIN (VALUES (3, 'PARSED'), (4, 'VALIDATED'))
      AS stage_record(sequence_number, stage)
    WHERE validation_status = 'VALID'
    """,
    """
    INSERT INTO provenance.source_processing_event (
      source_snapshot_id, operation_id, sequence_number, stage, event_at, stage_version,
      event_sha256, actor
    )
    SELECT source_snapshot_id, source_snapshot_id, 3, validation_status,
           GREATEST(COALESCE(parsed_at, received_at), COALESCE(stored_at, received_at)),
           'legacy-dat003',
           encode(sha256(convert_to(source_snapshot_id::text || chr(58)
                    || 'terminal', 'UTF8')), 'hex'),
           'dat003-migration'
    FROM provenance.source_snapshot
    WHERE validation_status IN ('QUARANTINED','REJECTED')
    """,
    """
    UPDATE provenance.source_processing_event AS event
    SET previous_event_id = predecessor.processing_event_id
    FROM provenance.source_processing_event AS predecessor
    WHERE predecessor.source_snapshot_id = event.source_snapshot_id
      AND predecessor.sequence_number = event.sequence_number - 1
      AND event.sequence_number > 1
    """,
    """
    CREATE FUNCTION provenance.guard_source_snapshot_envelope()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
      snapshot_provider_key text;
      profile_provider_key text;
    BEGIN
      IF NEW.validation_status <> 'RECEIVED'
         OR NEW.stored_at IS NOT NULL OR NEW.parsed_at IS NOT NULL
         OR NEW.mapped_at IS NOT NULL OR NEW.usable_at IS NOT NULL THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'SOURCE_ENVELOPE_NOT_INITIAL';
      END IF;
      IF NEW.rights_profile_record_id IS NOT NULL THEN
        SELECT provider_key INTO snapshot_provider_key
        FROM provenance.data_provider WHERE provider_id = NEW.provider_id;
        SELECT provider_key INTO profile_provider_key
        FROM provenance.rights_profile
        WHERE rights_profile_record_id = NEW.rights_profile_record_id;
        IF profile_provider_key IS NULL
           OR snapshot_provider_key IS DISTINCT FROM profile_provider_key THEN
          RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'SOURCE_PROFILE_PROVIDER_MISMATCH';
        END IF;
      END IF;
      RETURN NEW;
    END
    $$
    """,
    """
    CREATE FUNCTION provenance.guard_processing_event()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
      snapshot_received timestamptz;
      prior_stage text;
      prior_sequence integer;
      prior_event_at timestamptz;
      prior_event_id uuid;
      transition_from text;
      terminal_exists boolean;
      expected_stage text;
    BEGIN
      IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'IMMUTABLE_RECORD';
      END IF;
      SELECT received_at INTO snapshot_received
      FROM provenance.source_snapshot
      WHERE source_snapshot_id = NEW.source_snapshot_id
      FOR UPDATE;
      IF snapshot_received IS NULL OR NEW.event_at < snapshot_received THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'PROCESSING_EVENT_TIME_INVALID';
      END IF;
      SELECT EXISTS (
        SELECT 1 FROM provenance.source_processing_event
        WHERE source_snapshot_id = NEW.source_snapshot_id
          AND stage IN ('USABLE','QUARANTINED','REJECTED','CANCELLED','FAILED_PERMANENT')
      ) INTO terminal_exists;
      IF terminal_exists THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'PROCESSING_TERMINAL';
      END IF;
      SELECT stage, sequence_number, event_at, processing_event_id
      INTO prior_stage, prior_sequence, prior_event_at, prior_event_id
      FROM provenance.source_processing_event
      WHERE source_snapshot_id = NEW.source_snapshot_id
      ORDER BY sequence_number DESC LIMIT 1 FOR UPDATE;
      IF (NEW.stage = 'FAILED_RETRYABLE') <> (NEW.outcome = 'FAILED_RETRYABLE')
         OR (NEW.stage = 'FAILED_PERMANENT') <> (NEW.outcome = 'FAILED_PERMANENT')
         OR (NEW.stage NOT IN ('FAILED_RETRYABLE','FAILED_PERMANENT')
             AND NEW.outcome <> 'SUCCEEDED') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'PROCESSING_OUTCOME_INVALID';
      END IF;
      IF prior_sequence IS NULL THEN
        IF NEW.sequence_number <> 1 OR NEW.stage <> 'RECEIVED'
           OR NEW.previous_event_id IS NOT NULL THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'PROCESSING_STAGE_ORDER';
        END IF;
      ELSE
        IF NEW.sequence_number <> prior_sequence + 1
           OR NEW.previous_event_id IS DISTINCT FROM prior_event_id
           OR NEW.event_at < prior_event_at THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'PROCESSING_STAGE_ORDER';
        END IF;
        transition_from := prior_stage;
        IF prior_stage = 'FAILED_RETRYABLE' THEN
          SELECT stage INTO transition_from
          FROM provenance.source_processing_event
          WHERE source_snapshot_id = NEW.source_snapshot_id
            AND stage <> 'FAILED_RETRYABLE'
          ORDER BY sequence_number DESC LIMIT 1;
        END IF;
        expected_stage := CASE transition_from
          WHEN 'RECEIVED' THEN 'STORAGE'
          WHEN 'STORED' THEN 'PARSED'
          WHEN 'RAW_DISCARDED' THEN 'PARSED'
          WHEN 'PARSED' THEN 'VALIDATED'
          WHEN 'VALIDATED' THEN 'MAPPED'
          WHEN 'MAPPED' THEN 'PROMOTED'
          WHEN 'PROMOTED' THEN 'QUALITY_PASSED'
          WHEN 'QUALITY_PASSED' THEN 'USABLE'
          ELSE NULL
        END;
        IF NEW.stage IN ('QUARANTINED','REJECTED','CANCELLED','FAILED_PERMANENT','FAILED_RETRYABLE') THEN
          RETURN NEW;
        END IF;
        IF expected_stage IS NULL
           OR (expected_stage = 'STORAGE' AND NEW.stage NOT IN ('STORED','RAW_DISCARDED'))
           OR (expected_stage <> 'STORAGE' AND NEW.stage <> expected_stage) THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'PROCESSING_STAGE_ORDER';
        END IF;
      END IF;
      RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER trg_source_snapshot_envelope
    BEFORE INSERT ON provenance.source_snapshot
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_source_snapshot_envelope()
    """,
    """
    CREATE TRIGGER trg_source_processing_event_guard
    BEFORE INSERT OR UPDATE OR DELETE ON provenance.source_processing_event
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_processing_event()
    """,
    """
    CREATE VIEW provenance.source_snapshot_lifecycle AS
    SELECT snapshot.source_snapshot_id,
           COALESCE(latest.stage, 'ENVELOPE_ONLY') AS current_state,
           usable.usable_at,
           COALESCE(latest.sequence_number, 0) AS event_count,
           COALESCE(latest.stage IN
             ('USABLE','QUARANTINED','REJECTED','CANCELLED','FAILED_PERMANENT'), false)
             AS terminal
    FROM provenance.source_snapshot AS snapshot
    LEFT JOIN LATERAL (
      SELECT event.stage, event.sequence_number
      FROM provenance.source_processing_event AS event
      WHERE event.source_snapshot_id = snapshot.source_snapshot_id
      ORDER BY event.sequence_number DESC LIMIT 1
    ) AS latest ON true
    LEFT JOIN LATERAL (
      SELECT min(event.event_at) AS usable_at
      FROM provenance.source_processing_event AS event
      WHERE event.source_snapshot_id = snapshot.source_snapshot_id AND event.stage = 'USABLE'
    ) AS usable ON true
    """,
    "ALTER TABLE core.external_identifier DROP CONSTRAINT ex_external_identifier_current_accepted",
    "ALTER TABLE core.external_identifier ADD COLUMN season_id uuid",
    """
    ALTER TABLE core.external_identifier ADD CONSTRAINT fk_external_identifier_season
      FOREIGN KEY (season_id) REFERENCES football.season(season_id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE core.external_identifier ADD CONSTRAINT ex_external_identifier_current_accepted
    EXCLUDE USING gist (
      provider_id WITH =,
      COALESCE(season_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =,
      provider_product WITH =,
      identifier_namespace WITH =,
      entity_type WITH =,
      external_id_text WITH =,
      valid_during WITH &&
    ) WHERE (upper_inf(system_during) AND mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED'))
      DEFERRABLE INITIALLY IMMEDIATE
    """,
    """
    CREATE TABLE fpl.player_season (
      player_fpl_season_id uuid CONSTRAINT pk_player_season PRIMARY KEY DEFAULT uuidv7(),
      player_id uuid NOT NULL,
      season_id uuid NOT NULL,
      position_code varchar(24) NOT NULL,
      source_snapshot_id uuid NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT uq_player_season_identity UNIQUE (player_id, season_id),
      CONSTRAINT uq_player_season_id_season UNIQUE (player_fpl_season_id, season_id),
      CONSTRAINT fk_player_season_player FOREIGN KEY (player_id)
        REFERENCES football.player(player_id) ON DELETE RESTRICT,
      CONSTRAINT fk_player_season_season FOREIGN KEY (season_id)
        REFERENCES football.season(season_id) ON DELETE RESTRICT,
      CONSTRAINT fk_player_season_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE fpl.team_observation (
      team_observation_id uuid CONSTRAINT pk_team_observation PRIMARY KEY DEFAULT uuidv7(),
      team_season_id uuid NOT NULL,
      display_name text NOT NULL,
      short_name varchar(40) NOT NULL,
      strength integer NULL,
      strength_overall_home integer NULL, strength_overall_away integer NULL,
      strength_attack_home integer NULL, strength_attack_away integer NULL,
      strength_defence_home integer NULL, strength_defence_away integer NULL,
      position integer NULL, played integer NULL, win integer NULL, draw integer NULL,
      loss integer NULL, points integer NULL,
      observed_at timestamptz NOT NULL, received_at timestamptz NOT NULL,
      usable_at timestamptz NOT NULL, source_snapshot_id uuid NOT NULL,
      contract_version varchar(40) NOT NULL, missingness jsonb NOT NULL,
      semantic_sha256 char(64) NOT NULL,
      CONSTRAINT uq_team_observation_semantic_source
        UNIQUE (semantic_sha256, source_snapshot_id),
      CONSTRAINT fk_team_observation_team_season FOREIGN KEY (team_season_id)
        REFERENCES football.team_season(team_season_id) ON DELETE RESTRICT,
      CONSTRAINT fk_team_observation_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT ck_team_observation_semantic_hash CHECK (semantic_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_team_observation_missingness CHECK (jsonb_typeof(missingness) = 'object'),
      CONSTRAINT ck_team_observation_time_order CHECK (received_at <= usable_at)
    )
    """,
    """
    CREATE TABLE fpl.player_observation (
      player_observation_id uuid CONSTRAINT pk_player_observation PRIMARY KEY DEFAULT uuidv7(),
      player_fpl_season_id uuid NOT NULL, team_season_id uuid NOT NULL,
      position_code varchar(24) NOT NULL, price_tenths integer NOT NULL,
      status varchar(24) NOT NULL, chance_next_round smallint NULL,
      chance_this_round smallint NULL, news text NULL, news_added_at timestamptz NULL,
      selected_by_percent numeric(7,3) NULL,
      transfers_in bigint NULL, transfers_out bigint NULL,
      transfers_in_event bigint NULL, transfers_out_event bigint NULL,
      cost_change_start integer NULL, cost_change_event integer NULL,
      cost_change_start_fall integer NULL, cost_change_event_fall integer NULL,
      minutes integer NULL, total_points integer NULL,
      observed_at timestamptz NOT NULL, received_at timestamptz NOT NULL,
      usable_at timestamptz NOT NULL, source_snapshot_id uuid NOT NULL,
      contract_version varchar(40) NOT NULL, missingness jsonb NOT NULL,
      semantic_sha256 char(64) NOT NULL,
      CONSTRAINT uq_player_observation_semantic_source
        UNIQUE (semantic_sha256, source_snapshot_id),
      CONSTRAINT fk_player_observation_player_season FOREIGN KEY (player_fpl_season_id)
        REFERENCES fpl.player_season(player_fpl_season_id) ON DELETE RESTRICT,
      CONSTRAINT fk_player_observation_team_season FOREIGN KEY (team_season_id)
        REFERENCES football.team_season(team_season_id) ON DELETE RESTRICT,
      CONSTRAINT fk_player_observation_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT ck_player_observation_price CHECK (price_tenths >= 0),
      CONSTRAINT ck_player_observation_chance_next CHECK
        (chance_next_round IS NULL OR chance_next_round BETWEEN 0 AND 100),
      CONSTRAINT ck_player_observation_chance_this CHECK
        (chance_this_round IS NULL OR chance_this_round BETWEEN 0 AND 100),
      CONSTRAINT ck_player_observation_ownership CHECK
        (selected_by_percent IS NULL OR selected_by_percent BETWEEN 0 AND 100),
      CONSTRAINT ck_player_observation_semantic_hash CHECK
        (semantic_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_player_observation_missingness CHECK
        (jsonb_typeof(missingness) = 'object'),
      CONSTRAINT ck_player_observation_time_order CHECK (received_at <= usable_at)
    )
    """,
    """
    CREATE TABLE fpl.gameweek_observation (
      gameweek_observation_id uuid CONSTRAINT pk_gameweek_observation PRIMARY KEY DEFAULT uuidv7(),
      gameweek_id uuid NOT NULL, source_event_id text NOT NULL, display_name text NOT NULL,
      deadline_at timestamptz NOT NULL, finished boolean NULL, data_checked boolean NULL,
      is_previous boolean NULL, is_current boolean NULL, is_next boolean NULL,
      average_entry_score integer NULL, highest_score integer NULL,
      observed_at timestamptz NOT NULL, received_at timestamptz NOT NULL,
      usable_at timestamptz NOT NULL, source_snapshot_id uuid NOT NULL,
      contract_version varchar(40) NOT NULL, missingness jsonb NOT NULL,
      semantic_sha256 char(64) NOT NULL,
      CONSTRAINT uq_gameweek_observation_semantic_source
        UNIQUE (semantic_sha256, source_snapshot_id),
      CONSTRAINT fk_gameweek_observation_gameweek FOREIGN KEY (gameweek_id)
        REFERENCES fpl.gameweek(gameweek_id) ON DELETE RESTRICT,
      CONSTRAINT fk_gameweek_observation_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT ck_gameweek_observation_semantic_hash CHECK
        (semantic_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_gameweek_observation_missingness CHECK
        (jsonb_typeof(missingness) = 'object'),
      CONSTRAINT ck_gameweek_observation_time_order CHECK (received_at <= usable_at)
    )
    """,
    """
    CREATE TABLE fpl.fixture_observation (
      fixture_observation_id uuid CONSTRAINT pk_fixture_observation PRIMARY KEY DEFAULT uuidv7(),
      fixture_id uuid NOT NULL, source_fixture_id text NOT NULL, source_fixture_code text NOT NULL,
      kickoff_at timestamptz NULL, finished boolean NOT NULL, started boolean NULL,
      finished_provisional boolean NULL, minutes integer NULL,
      team_h_score integer NULL, team_a_score integer NULL,
      team_h_difficulty integer NULL, team_a_difficulty integer NULL,
      provisional_start_time boolean NULL,
      observed_at timestamptz NOT NULL, received_at timestamptz NOT NULL,
      usable_at timestamptz NOT NULL, source_snapshot_id uuid NOT NULL,
      contract_version varchar(40) NOT NULL, missingness jsonb NOT NULL,
      semantic_sha256 char(64) NOT NULL,
      CONSTRAINT uq_fixture_observation_semantic_source
        UNIQUE (semantic_sha256, source_snapshot_id),
      CONSTRAINT fk_fixture_observation_fixture FOREIGN KEY (fixture_id)
        REFERENCES football.fixture(fixture_id) ON DELETE RESTRICT,
      CONSTRAINT fk_fixture_observation_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT ck_fixture_observation_semantic_hash CHECK
        (semantic_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_fixture_observation_missingness CHECK
        (jsonb_typeof(missingness) = 'object'),
      CONSTRAINT ck_fixture_observation_time_order CHECK (received_at <= usable_at)
    )
    """,
    """
    CREATE FUNCTION provenance.guard_fpl_observation_source_usable()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
      first_usable_at timestamptz;
      snapshot_resource text;
    BEGIN
      SELECT min(event.event_at), snapshot.resource
      INTO first_usable_at, snapshot_resource
      FROM provenance.source_snapshot AS snapshot
      LEFT JOIN provenance.source_processing_event AS event
        ON event.source_snapshot_id = snapshot.source_snapshot_id
       AND event.stage = 'USABLE'
      WHERE snapshot.source_snapshot_id = NEW.source_snapshot_id
      GROUP BY snapshot.resource;
      IF first_usable_at IS NULL OR NEW.usable_at IS DISTINCT FROM first_usable_at THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
          MESSAGE = 'FPL_OBSERVATION_SOURCE_NOT_USABLE';
      END IF;
      IF (TG_TABLE_NAME = 'fixture_observation' AND snapshot_resource <> 'fixtures')
         OR (TG_TABLE_NAME <> 'fixture_observation' AND snapshot_resource <> 'bootstrap') THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
          MESSAGE = 'FPL_OBSERVATION_SOURCE_ROLE_INVALID';
      END IF;
      RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER trg_team_observation_source_usable
    BEFORE INSERT ON fpl.team_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_fpl_observation_source_usable()
    """,
    """
    CREATE TRIGGER trg_player_observation_source_usable
    BEFORE INSERT ON fpl.player_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_fpl_observation_source_usable()
    """,
    """
    CREATE TRIGGER trg_gameweek_observation_source_usable
    BEFORE INSERT ON fpl.gameweek_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_fpl_observation_source_usable()
    """,
    """
    CREATE TRIGGER trg_fixture_observation_source_usable
    BEFORE INSERT ON fpl.fixture_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_fpl_observation_source_usable()
    """,
    """
    CREATE TABLE provenance.semantic_effect_source (
      semantic_effect_source_id uuid CONSTRAINT pk_semantic_effect_source PRIMARY KEY DEFAULT uuidv7(),
      effect_type varchar(40) NOT NULL, semantic_sha256 char(64) NOT NULL,
      source_snapshot_id uuid NOT NULL, observed_at timestamptz NOT NULL,
      CONSTRAINT uq_semantic_effect_source_lineage UNIQUE
        (effect_type, semantic_sha256, source_snapshot_id),
      CONSTRAINT fk_semantic_effect_source_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT ck_semantic_effect_source_hash CHECK (semantic_sha256 ~ '^[0-9a-f]{64}$')
    )
    """,
    """
    CREATE TABLE provenance.semantic_observation_claim (
      semantic_observation_claim_id uuid
        CONSTRAINT pk_semantic_observation_claim PRIMARY KEY DEFAULT uuidv7(),
      effect_type varchar(40) NOT NULL, subject_key uuid NOT NULL,
      observed_at timestamptz NOT NULL, semantic_sha256 char(64) NOT NULL,
      source_snapshot_id uuid NOT NULL,
      CONSTRAINT uq_semantic_observation_claim_subject_time UNIQUE
        (effect_type, subject_key, observed_at),
      CONSTRAINT fk_semantic_observation_claim_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT ck_semantic_observation_claim_type CHECK
        (effect_type IN ('TEAM_OBSERVATION','PLAYER_OBSERVATION',
                         'GAMEWEEK_OBSERVATION','FIXTURE_OBSERVATION')),
      CONSTRAINT ck_semantic_observation_claim_hash CHECK
        (semantic_sha256 ~ '^[0-9a-f]{64}$')
    )
    """,
    """
    CREATE TABLE provenance.source_bundle (
      source_bundle_id uuid CONSTRAINT pk_source_bundle PRIMARY KEY DEFAULT uuidv7(),
      bundle_type varchar(48) NOT NULL, competition_id uuid NOT NULL, season_id uuid NOT NULL,
      information_cutoff timestamptz NOT NULL, created_at timestamptz NOT NULL,
      rights_profiles jsonb NOT NULL, adapter_version varchar(40) NOT NULL,
      contract_version varchar(40) NOT NULL, quality_status varchar(32) NOT NULL,
      semantic_sha256 char(64) NOT NULL, manifest_sha256 char(64) NOT NULL,
      code_commit char(40) NULL, config_sha256 char(64) NOT NULL,
      CONSTRAINT uq_source_bundle_manifest_hash UNIQUE (manifest_sha256),
      CONSTRAINT fk_source_bundle_competition FOREIGN KEY (competition_id)
        REFERENCES football.competition(competition_id) ON DELETE RESTRICT,
      CONSTRAINT fk_source_bundle_season FOREIGN KEY (season_id)
        REFERENCES football.season(season_id) ON DELETE RESTRICT,
      CONSTRAINT fk_source_bundle_season_competition FOREIGN KEY (season_id, competition_id)
        REFERENCES football.season(season_id, competition_id) ON DELETE RESTRICT,
      CONSTRAINT ck_source_bundle_type CHECK (bundle_type = 'FPL_BOOTSTRAP_FIXTURES'),
      CONSTRAINT ck_source_bundle_quality_status CHECK
        (quality_status IN ('PASS','PASS_WITH_WARNINGS')),
      CONSTRAINT ck_source_bundle_semantic_hash CHECK (semantic_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_source_bundle_manifest_hash CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_source_bundle_config_hash CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_source_bundle_code_commit CHECK
        (code_commit IS NULL OR code_commit ~ '^[0-9a-f]{40}$')
    )
    """,
    """
    CREATE TABLE provenance.source_bundle_member (
      source_bundle_member_id uuid CONSTRAINT pk_source_bundle_member PRIMARY KEY DEFAULT uuidv7(),
      source_bundle_id uuid NOT NULL, source_snapshot_id uuid NOT NULL,
      role varchar(16) NOT NULL, usable_at timestamptz NOT NULL,
      payload_semantic_sha256 char(64) NOT NULL, envelope_sha256 char(64) NOT NULL,
      lifecycle_sha256 char(64) NOT NULL, schema_drift jsonb NOT NULL,
      CONSTRAINT uq_source_bundle_member_role UNIQUE (source_bundle_id, role),
      CONSTRAINT uq_source_bundle_member_snapshot UNIQUE (source_bundle_id, source_snapshot_id),
      CONSTRAINT fk_source_bundle_member_bundle FOREIGN KEY (source_bundle_id)
        REFERENCES provenance.source_bundle(source_bundle_id) ON DELETE RESTRICT,
      CONSTRAINT fk_source_bundle_member_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT ck_source_bundle_member_role CHECK (role IN ('BOOTSTRAP','FIXTURES')),
      CONSTRAINT ck_source_bundle_member_payload_hash CHECK
        (payload_semantic_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_source_bundle_member_envelope_hash CHECK
        (envelope_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_source_bundle_member_lifecycle_hash CHECK
        (lifecycle_sha256 ~ '^[0-9a-f]{64}$')
    )
    """,
    "ALTER TABLE core.data_quality_issue ADD COLUMN source_bundle_id uuid",
    "ALTER TABLE core.data_quality_issue ADD COLUMN subject_scope varchar(32)",
    "ALTER TABLE core.data_quality_issue ADD COLUMN stage varchar(40)",
    "ALTER TABLE core.data_quality_issue ADD COLUMN message text",
    "ALTER TABLE core.data_quality_issue ADD COLUMN review_at timestamptz",
    """
    UPDATE core.data_quality_issue
    SET subject_scope = CASE
          WHEN source_snapshot_id IS NOT NULL THEN 'SOURCE_SNAPSHOT'
          WHEN ingestion_run_id IS NOT NULL THEN 'INGESTION_RUN'
          WHEN canonical_entity_id IS NOT NULL THEN 'CANONICAL_ENTITY'
          ELSE 'GLOBAL_SYSTEM' END,
        stage = 'DAT003_LEGACY',
        message = issue_type
    """,
    "ALTER TABLE core.data_quality_issue ALTER COLUMN subject_scope SET NOT NULL",
    "ALTER TABLE core.data_quality_issue ALTER COLUMN stage SET NOT NULL",
    "ALTER TABLE core.data_quality_issue ALTER COLUMN message SET NOT NULL",
    "ALTER TABLE core.data_quality_issue DROP CONSTRAINT ck_data_quality_severity",
    """
    UPDATE core.data_quality_issue
    SET severity = CASE severity
      WHEN 'INFO' THEN 'P3'
      WHEN 'WARN' THEN 'P2'
      WHEN 'ERROR' THEN 'P1'
      WHEN 'BLOCKING' THEN 'P0'
      ELSE severity
    END
    WHERE severity IN ('INFO','WARN','ERROR','BLOCKING')
    """,
    """
    ALTER TABLE core.data_quality_issue ADD CONSTRAINT ck_data_quality_severity CHECK
      (severity IN ('P0','P1','P2','P3'))
    """,
    """
    ALTER TABLE core.data_quality_issue ADD CONSTRAINT fk_data_quality_source_bundle
      FOREIGN KEY (source_bundle_id)
      REFERENCES provenance.source_bundle(source_bundle_id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE core.data_quality_issue ADD CONSTRAINT ck_data_quality_subject CHECK (
      (subject_scope = 'SOURCE_SNAPSHOT' AND source_snapshot_id IS NOT NULL)
      OR (subject_scope = 'INGESTION_RUN' AND ingestion_run_id IS NOT NULL)
      OR (subject_scope = 'CANONICAL_ENTITY' AND canonical_entity_id IS NOT NULL)
      OR (subject_scope = 'SOURCE_BUNDLE' AND source_bundle_id IS NOT NULL)
      OR (subject_scope = 'GLOBAL_SYSTEM' AND source_snapshot_id IS NULL
          AND ingestion_run_id IS NULL AND canonical_entity_id IS NULL
          AND source_bundle_id IS NULL)
    )
    """,
    "CREATE INDEX ix_team_season_season ON football.team_season (season_id)",
    "CREATE INDEX ix_team_season_snapshot ON football.team_season (source_snapshot_id)",
    "CREATE INDEX ix_assignment_season ON football.fixture_gameweek_assignment (season_id)",
    "CREATE INDEX ix_rights_profile_provider ON provenance.rights_profile (provider_key)",
    "CREATE INDEX ix_raw_storage_content ON provenance.raw_storage_object (raw_blob_id)",
    "CREATE INDEX ix_raw_storage_rights ON provenance.raw_storage_object (rights_profile_record_id)",
    "CREATE INDEX ix_source_snapshot_raw_storage ON provenance.source_snapshot (raw_storage_object_id)",
    "CREATE INDEX ix_source_snapshot_rights_profile ON provenance.source_snapshot (rights_profile_record_id)",
    "CREATE INDEX ix_rights_decision_profile ON provenance.rights_decision (rights_profile_record_id)",
    "CREATE INDEX ix_rights_decision_snapshot ON provenance.rights_decision (source_snapshot_id)",
    "CREATE INDEX ix_processing_event_snapshot_sequence ON provenance.source_processing_event (source_snapshot_id, sequence_number)",
    "CREATE INDEX ix_external_identifier_season ON core.external_identifier (season_id)",
    "CREATE INDEX ix_player_season_season ON fpl.player_season (season_id)",
    "CREATE INDEX ix_player_season_snapshot ON fpl.player_season (source_snapshot_id)",
    "CREATE INDEX ix_team_observation_subject ON fpl.team_observation (team_season_id)",
    "CREATE INDEX ix_team_observation_snapshot ON fpl.team_observation (source_snapshot_id)",
    "CREATE INDEX ix_player_observation_subject ON fpl.player_observation (player_fpl_season_id)",
    "CREATE INDEX ix_player_observation_team ON fpl.player_observation (team_season_id)",
    "CREATE INDEX ix_player_observation_snapshot ON fpl.player_observation (source_snapshot_id)",
    "CREATE INDEX ix_gameweek_observation_subject ON fpl.gameweek_observation (gameweek_id)",
    "CREATE INDEX ix_gameweek_observation_snapshot ON fpl.gameweek_observation (source_snapshot_id)",
    "CREATE INDEX ix_fixture_observation_subject ON fpl.fixture_observation (fixture_id)",
    "CREATE INDEX ix_fixture_observation_snapshot ON fpl.fixture_observation (source_snapshot_id)",
    "CREATE INDEX ix_semantic_effect_source_snapshot ON provenance.semantic_effect_source (source_snapshot_id)",
    "CREATE INDEX ix_semantic_observation_claim_snapshot ON provenance.semantic_observation_claim (source_snapshot_id)",
    "CREATE INDEX ix_source_bundle_season_cutoff ON provenance.source_bundle (season_id, information_cutoff)",
    "CREATE INDEX ix_source_bundle_member_snapshot ON provenance.source_bundle_member (source_snapshot_id)",
    "CREATE INDEX ix_data_quality_bundle ON core.data_quality_issue (source_bundle_id)",
    """
    CREATE TRIGGER trg_rights_profile_immutable
    BEFORE UPDATE OR DELETE ON provenance.rights_profile
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_raw_storage_object_immutable
    BEFORE UPDATE OR DELETE ON provenance.raw_storage_object
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_raw_storage_deletion_immutable
    BEFORE UPDATE OR DELETE ON provenance.raw_storage_deletion
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_rights_decision_immutable
    BEFORE UPDATE OR DELETE ON provenance.rights_decision
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_player_season_immutable
    BEFORE UPDATE OR DELETE ON fpl.player_season
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_team_observation_immutable
    BEFORE UPDATE OR DELETE ON fpl.team_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_player_observation_immutable
    BEFORE UPDATE OR DELETE ON fpl.player_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_gameweek_observation_immutable
    BEFORE UPDATE OR DELETE ON fpl.gameweek_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_fixture_observation_immutable
    BEFORE UPDATE OR DELETE ON fpl.fixture_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_semantic_effect_source_immutable
    BEFORE UPDATE OR DELETE ON provenance.semantic_effect_source
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_semantic_observation_claim_immutable
    BEFORE UPDATE OR DELETE ON provenance.semantic_observation_claim
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_source_bundle_immutable
    BEFORE UPDATE OR DELETE ON provenance.source_bundle
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_source_bundle_member_immutable
    BEFORE UPDATE OR DELETE ON provenance.source_bundle_member
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE VIEW provenance.available_raw_storage_object AS
    SELECT storage.*
    FROM provenance.raw_storage_object AS storage
    WHERE NOT EXISTS (
      SELECT 1 FROM provenance.raw_storage_deletion AS deletion
      WHERE deletion.raw_storage_object_id = storage.raw_storage_object_id
    )
    """,
    "DROP VIEW core.current_external_identifier",
    "CREATE VIEW core.current_external_identifier AS SELECT * FROM core.external_identifier WHERE upper_inf(system_during)",
    "DROP VIEW football.current_fixture_gameweek_assignment",
    "CREATE VIEW football.current_fixture_gameweek_assignment AS SELECT * FROM football.fixture_gameweek_assignment WHERE upper_inf(system_during)",
    "CREATE VIEW fpl.current_team_observation AS SELECT DISTINCT ON (observation.team_season_id) observation.* FROM fpl.team_observation AS observation JOIN provenance.source_snapshot_lifecycle AS lifecycle ON lifecycle.source_snapshot_id = observation.source_snapshot_id WHERE lifecycle.current_state = 'USABLE' ORDER BY observation.team_season_id, observation.observed_at DESC, observation.usable_at DESC, observation.team_observation_id DESC",
    "CREATE VIEW fpl.current_player_observation AS SELECT DISTINCT ON (observation.player_fpl_season_id) observation.* FROM fpl.player_observation AS observation JOIN provenance.source_snapshot_lifecycle AS lifecycle ON lifecycle.source_snapshot_id = observation.source_snapshot_id WHERE lifecycle.current_state = 'USABLE' ORDER BY observation.player_fpl_season_id, observation.observed_at DESC, observation.usable_at DESC, observation.player_observation_id DESC",
    "CREATE VIEW fpl.current_gameweek_observation AS SELECT DISTINCT ON (observation.gameweek_id) observation.* FROM fpl.gameweek_observation AS observation JOIN provenance.source_snapshot_lifecycle AS lifecycle ON lifecycle.source_snapshot_id = observation.source_snapshot_id WHERE lifecycle.current_state = 'USABLE' ORDER BY observation.gameweek_id, observation.observed_at DESC, observation.usable_at DESC, observation.gameweek_observation_id DESC",
    "CREATE VIEW fpl.current_fixture_observation AS SELECT DISTINCT ON (observation.fixture_id) observation.* FROM fpl.fixture_observation AS observation JOIN provenance.source_snapshot_lifecycle AS lifecycle ON lifecycle.source_snapshot_id = observation.source_snapshot_id WHERE lifecycle.current_state = 'USABLE' ORDER BY observation.fixture_id, observation.observed_at DESC, observation.usable_at DESC, observation.fixture_observation_id DESC",
)


DOWNGRADE_STATEMENTS = (
    "DROP VIEW fpl.current_fixture_observation",
    "DROP VIEW fpl.current_gameweek_observation",
    "DROP VIEW fpl.current_player_observation",
    "DROP VIEW fpl.current_team_observation",
    "DROP VIEW provenance.available_raw_storage_object",
    "DROP TRIGGER trg_fixture_observation_source_usable ON fpl.fixture_observation",
    "DROP TRIGGER trg_gameweek_observation_source_usable ON fpl.gameweek_observation",
    "DROP TRIGGER trg_player_observation_source_usable ON fpl.player_observation",
    "DROP TRIGGER trg_team_observation_source_usable ON fpl.team_observation",
    "DROP FUNCTION provenance.guard_fpl_observation_source_usable()",
    "ALTER TABLE core.data_quality_issue DROP CONSTRAINT ck_data_quality_subject",
    "ALTER TABLE core.data_quality_issue DROP CONSTRAINT fk_data_quality_source_bundle",
    "ALTER TABLE core.data_quality_issue DROP CONSTRAINT ck_data_quality_severity",
    """
    UPDATE core.data_quality_issue
    SET severity = CASE severity
      WHEN 'P0' THEN 'BLOCKING'
      WHEN 'P1' THEN 'ERROR'
      WHEN 'P2' THEN 'WARN'
      WHEN 'P3' THEN 'INFO'
      ELSE severity
    END
    WHERE severity IN ('P0','P1','P2','P3')
    """,
    "ALTER TABLE core.data_quality_issue ADD CONSTRAINT ck_data_quality_severity CHECK (severity IN ('INFO','WARN','ERROR','BLOCKING'))",
    "ALTER TABLE core.data_quality_issue DROP COLUMN review_at",
    "ALTER TABLE core.data_quality_issue DROP COLUMN message",
    "ALTER TABLE core.data_quality_issue DROP COLUMN stage",
    "ALTER TABLE core.data_quality_issue DROP COLUMN subject_scope",
    "ALTER TABLE core.data_quality_issue DROP COLUMN source_bundle_id",
    "DROP TABLE provenance.source_bundle_member",
    "DROP TABLE provenance.source_bundle",
    "DROP TABLE provenance.semantic_observation_claim",
    "DROP TABLE provenance.semantic_effect_source",
    "DROP TABLE fpl.fixture_observation",
    "DROP TABLE fpl.gameweek_observation",
    "DROP TABLE fpl.player_observation",
    "DROP TABLE fpl.team_observation",
    "DROP TABLE fpl.player_season",
    "DROP VIEW core.current_external_identifier",
    "ALTER TABLE core.external_identifier DROP CONSTRAINT ex_external_identifier_current_accepted",
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM core.external_identifier AS left_mapping
        JOIN core.external_identifier AS right_mapping
          ON left_mapping.external_identifier_id < right_mapping.external_identifier_id
         AND left_mapping.provider_id = right_mapping.provider_id
         AND left_mapping.provider_product = right_mapping.provider_product
         AND left_mapping.identifier_namespace = right_mapping.identifier_namespace
         AND left_mapping.entity_type = right_mapping.entity_type
         AND left_mapping.external_id_text = right_mapping.external_id_text
         AND left_mapping.valid_during && right_mapping.valid_during
        WHERE upper_inf(left_mapping.system_during)
          AND upper_inf(right_mapping.system_during)
          AND left_mapping.mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED')
          AND right_mapping.mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED')
      ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
          MESSAGE = 'DOWNGRADE_SEASON_MAPPING_CONFLICT';
      END IF;
    END
    $$
    """,
    "ALTER TABLE core.external_identifier DROP CONSTRAINT fk_external_identifier_season",
    "ALTER TABLE core.external_identifier DROP COLUMN season_id",
    """
    ALTER TABLE core.external_identifier ADD CONSTRAINT ex_external_identifier_current_accepted
    EXCLUDE USING gist (
      provider_id WITH =, provider_product WITH =, identifier_namespace WITH =,
      entity_type WITH =, external_id_text WITH =, valid_during WITH &&
    ) WHERE (upper_inf(system_during) AND mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED'))
      DEFERRABLE INITIALLY IMMEDIATE
    """,
    "CREATE VIEW core.current_external_identifier AS SELECT * FROM core.external_identifier WHERE upper_inf(system_during)",
    "DROP VIEW provenance.source_snapshot_lifecycle",
    "DROP TRIGGER trg_source_processing_event_guard ON provenance.source_processing_event",
    "DROP TRIGGER trg_source_snapshot_envelope ON provenance.source_snapshot",
    "DROP FUNCTION provenance.guard_processing_event()",
    "DROP FUNCTION provenance.guard_source_snapshot_envelope()",
    "DROP TRIGGER trg_source_snapshot_immutable ON provenance.source_snapshot",
    """
    UPDATE provenance.source_snapshot
    SET validation_status = CASE
          WHEN EXISTS (
            SELECT 1 FROM provenance.source_processing_event AS event
            WHERE event.source_snapshot_id = source_snapshot.source_snapshot_id
              AND event.stage = 'USABLE'
          ) THEN 'USABLE'
          WHEN EXISTS (
            SELECT 1 FROM provenance.source_processing_event AS event
            WHERE event.source_snapshot_id = source_snapshot.source_snapshot_id
              AND event.stage = 'QUARANTINED'
          ) THEN 'QUARANTINED'
          WHEN EXISTS (
            SELECT 1 FROM provenance.source_processing_event AS event
            WHERE event.source_snapshot_id = source_snapshot.source_snapshot_id
              AND event.stage IN ('REJECTED','CANCELLED','FAILED_PERMANENT')
          ) THEN 'REJECTED'
          WHEN EXISTS (
            SELECT 1 FROM provenance.source_processing_event AS event
            WHERE event.source_snapshot_id = source_snapshot.source_snapshot_id
              AND event.stage IN ('VALIDATED','MAPPED','PROMOTED','QUALITY_PASSED')
          ) THEN 'VALID'
          ELSE 'RECEIVED'
        END,
        stored_at = (
          SELECT min(event.event_at) FROM provenance.source_processing_event AS event
          WHERE event.source_snapshot_id = source_snapshot.source_snapshot_id
            AND event.stage IN ('STORED','RAW_DISCARDED')
        ),
        parsed_at = (
          SELECT min(event.event_at) FROM provenance.source_processing_event AS event
          WHERE event.source_snapshot_id = source_snapshot.source_snapshot_id
            AND event.stage = 'PARSED'
        ),
        mapped_at = (
          SELECT min(event.event_at) FROM provenance.source_processing_event AS event
          WHERE event.source_snapshot_id = source_snapshot.source_snapshot_id
            AND event.stage = 'MAPPED'
        ),
        usable_at = (
          SELECT min(event.event_at) FROM provenance.source_processing_event AS event
          WHERE event.source_snapshot_id = source_snapshot.source_snapshot_id
            AND event.stage = 'USABLE'
        ),
        raw_blob_id = CASE WHEN raw_storage_policy = 'FORBIDDEN' THEN NULL ELSE raw_blob_id END
    """,
    "DROP TABLE provenance.source_mapping_candidate",
    "DROP TABLE provenance.source_processing_event",
    "DROP TABLE provenance.rights_decision",
    "ALTER TABLE provenance.source_snapshot DROP CONSTRAINT IF EXISTS uq_source_snapshot_rights_profile",
    "ALTER TABLE provenance.source_snapshot DROP CONSTRAINT ck_source_snapshot_retention",
    "ALTER TABLE provenance.source_snapshot DROP CONSTRAINT IF EXISTS fk_source_snapshot_raw_storage_coherence",
    "ALTER TABLE provenance.source_snapshot DROP CONSTRAINT IF EXISTS fk_source_snapshot_raw_content_coherence",
    "ALTER TABLE provenance.source_snapshot DROP CONSTRAINT IF EXISTS fk_source_snapshot_rights_profile_version",
    "ALTER TABLE provenance.source_snapshot DROP CONSTRAINT fk_source_snapshot_rights_profile",
    "ALTER TABLE provenance.source_snapshot DROP CONSTRAINT fk_source_snapshot_raw_storage",
    "ALTER TABLE provenance.source_snapshot DROP CONSTRAINT ck_source_snapshot_envelope_hash",
    "ALTER TABLE provenance.source_snapshot DROP CONSTRAINT ck_source_snapshot_body_size",
    "ALTER TABLE provenance.source_snapshot DROP CONSTRAINT ck_source_snapshot_attempt",
    "ALTER TABLE provenance.source_snapshot DROP COLUMN envelope_sha256",
    "ALTER TABLE provenance.source_snapshot DROP COLUMN contract_version",
    "ALTER TABLE provenance.source_snapshot DROP COLUMN adapter_version",
    "ALTER TABLE provenance.source_snapshot DROP COLUMN rights_profile_record_id",
    "ALTER TABLE provenance.source_snapshot DROP COLUMN rights_profile_version",
    "ALTER TABLE provenance.source_snapshot DROP COLUMN raw_storage_object_id",
    "ALTER TABLE provenance.source_snapshot DROP COLUMN sanitized_target",
    "ALTER TABLE provenance.source_snapshot DROP COLUMN body_size",
    "ALTER TABLE provenance.source_snapshot DROP COLUMN attempt_number",
    """
    ALTER TABLE provenance.source_snapshot ADD CONSTRAINT ck_source_snapshot_retention CHECK (
      (raw_storage_policy <> 'FORBIDDEN' OR raw_blob_id IS NULL)
      AND (raw_storage_policy <> 'ALLOWED' OR body_sha256 IS NULL OR raw_blob_id IS NOT NULL)
      AND (raw_blob_id IS NULL OR body_sha256 IS NOT NULL)
    )
    """,
    """
    CREATE TRIGGER trg_source_snapshot_immutable
    BEFORE UPDATE OR DELETE ON provenance.source_snapshot
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    "DROP TABLE provenance.raw_storage_deletion",
    "DROP TRIGGER IF EXISTS trg_raw_storage_rights ON provenance.raw_storage_object",
    "DROP FUNCTION IF EXISTS provenance.guard_raw_storage_rights()",
    "DROP TABLE provenance.raw_storage_object",
    "DROP TABLE provenance.rights_profile",
    "DROP TRIGGER trg_raw_blob_immutable ON provenance.raw_blob",
    """
    UPDATE provenance.raw_blob
    SET storage_policy = CASE
      WHEN storage_uri IS NULL AND stored_blob_sha256 IS NULL THEN 'FORBIDDEN'
      ELSE 'ALLOWED'
    END
    WHERE storage_policy IS NULL
    """,
    "ALTER TABLE provenance.raw_blob ALTER COLUMN storage_policy SET NOT NULL",
    "ALTER TABLE provenance.raw_blob DROP CONSTRAINT uq_raw_blob_content_coherence",
    """
    CREATE TRIGGER trg_raw_blob_immutable
    BEFORE UPDATE OR DELETE ON provenance.raw_blob
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    "ALTER TABLE provenance.ruleset_artifact DROP CONSTRAINT uq_ruleset_artifact_identity",
    "ALTER TABLE provenance.ruleset_artifact ADD CONSTRAINT uq_ruleset_artifact_identity_hash UNIQUE (ruleset_id, ruleset_version, source_ruleset_hash)",
    "DROP VIEW football.current_fixture_gameweek_assignment",
    "ALTER TABLE football.fixture_gameweek_assignment DROP CONSTRAINT fk_assignment_gameweek_season",
    "ALTER TABLE football.fixture_gameweek_assignment DROP CONSTRAINT fk_assignment_fixture_season",
    "ALTER TABLE football.fixture_gameweek_assignment DROP COLUMN season_id",
    "CREATE VIEW football.current_fixture_gameweek_assignment AS SELECT * FROM football.fixture_gameweek_assignment WHERE upper_inf(system_during)",
    "ALTER TABLE fpl.gameweek DROP CONSTRAINT uq_gameweek_id_season",
    "ALTER TABLE football.player_team_membership DROP CONSTRAINT fk_membership_team_season",
    "ALTER TABLE football.fixture DROP CONSTRAINT fk_fixture_away_team_season",
    "ALTER TABLE football.fixture DROP CONSTRAINT fk_fixture_home_team_season",
    "ALTER TABLE football.fixture DROP CONSTRAINT fk_fixture_season_competition",
    "ALTER TABLE football.fixture DROP CONSTRAINT uq_fixture_id_season",
    "DROP TABLE football.team_season",
    "ALTER TABLE football.season DROP CONSTRAINT uq_season_id_competition",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
