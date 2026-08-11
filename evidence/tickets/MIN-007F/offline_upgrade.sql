BEGIN;

CREATE TABLE public.alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 20260723_0001

CREATE SCHEMA core;

CREATE SCHEMA football;

CREATE SCHEMA fpl;

CREATE SCHEMA provenance;

CREATE EXTENSION btree_gist WITH SCHEMA core;

SET search_path TO core, football, fpl, provenance, public, pg_catalog;

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
    );

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
    );

CREATE TABLE football.team (
      team_id uuid CONSTRAINT pk_team PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'TEAM',
      canonical_name text NOT NULL,
      short_name varchar(20) NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT ck_team_entity_type CHECK (entity_type = 'TEAM'),
      CONSTRAINT fk_team_canonical_type FOREIGN KEY (team_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT
    );

CREATE TABLE football.player (
      player_id uuid CONSTRAINT pk_player PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'PLAYER',
      canonical_name text NOT NULL,
      birth_date date NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT ck_player_entity_type CHECK (entity_type = 'PLAYER'),
      CONSTRAINT fk_player_canonical_type FOREIGN KEY (player_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT
    );

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
    );

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
    );

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
    );

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
    );

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
    );

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
    );

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
    );

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
    );

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
        (valid_during IS NOT NULL AND NOT isempty(valid_during) AND lower(valid_during) IS NOT NULL AND NOT lower_inf(valid_during) AND isfinite(lower(valid_during)) AND lower_inc(valid_during) AND NOT upper_inc(valid_during)),
      CONSTRAINT ck_external_identifier_system_range CHECK
        (system_during IS NOT NULL AND NOT isempty(system_during) AND lower(system_during) IS NOT NULL AND NOT lower_inf(system_during) AND isfinite(lower(system_during)) AND lower_inc(system_during) AND NOT upper_inc(system_during)),
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
    );

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
      CONSTRAINT ck_entity_alias_valid_range CHECK (valid_during IS NOT NULL AND NOT isempty(valid_during) AND lower(valid_during) IS NOT NULL AND NOT lower_inf(valid_during) AND isfinite(lower(valid_during)) AND lower_inc(valid_during) AND NOT upper_inc(valid_during)),
      CONSTRAINT ck_entity_alias_system_range CHECK (system_during IS NOT NULL AND NOT isempty(system_during) AND lower(system_during) IS NOT NULL AND NOT lower_inf(system_during) AND isfinite(lower(system_during)) AND lower_inc(system_during) AND NOT upper_inc(system_during)),
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
    );

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
      CONSTRAINT ck_membership_valid_range CHECK (valid_during IS NOT NULL AND NOT isempty(valid_during) AND lower(valid_during) IS NOT NULL AND NOT lower_inf(valid_during) AND isfinite(lower(valid_during)) AND lower_inc(valid_during) AND NOT upper_inc(valid_during)),
      CONSTRAINT ck_membership_system_range CHECK (system_during IS NOT NULL AND NOT isempty(system_during) AND lower(system_during) IS NOT NULL AND NOT lower_inf(system_during) AND isfinite(lower(system_during)) AND lower_inc(system_during) AND NOT upper_inc(system_during)),
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
    );

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
        (valid_during IS NOT NULL AND NOT isempty(valid_during) AND lower(valid_during) IS NOT NULL AND NOT lower_inf(valid_during) AND isfinite(lower(valid_during)) AND lower_inc(valid_during) AND NOT upper_inc(valid_during)),
      CONSTRAINT ck_fixture_revision_system_range CHECK
        (system_during IS NOT NULL AND NOT isempty(system_during) AND lower(system_during) IS NOT NULL AND NOT lower_inf(system_during) AND isfinite(lower(system_during)) AND lower_inc(system_during) AND NOT upper_inc(system_during)),
      CONSTRAINT fk_fixture_revision_fixture FOREIGN KEY (fixture_id)
        REFERENCES football.fixture(fixture_id) ON DELETE RESTRICT,
      CONSTRAINT fk_fixture_revision_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT fk_fixture_revision_successor FOREIGN KEY (superseded_by_revision_id)
        REFERENCES football.fixture_revision(fixture_revision_id) ON DELETE RESTRICT,
      CONSTRAINT ex_fixture_revision_current EXCLUDE USING gist (
        fixture_id WITH =, valid_during WITH &&
      ) WHERE (upper_inf(system_during)) DEFERRABLE INITIALLY IMMEDIATE
    );

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
      CONSTRAINT ck_assignment_valid_range CHECK (valid_during IS NOT NULL AND NOT isempty(valid_during) AND lower(valid_during) IS NOT NULL AND NOT lower_inf(valid_during) AND isfinite(lower(valid_during)) AND lower_inc(valid_during) AND NOT upper_inc(valid_during)),
      CONSTRAINT ck_assignment_system_range CHECK (system_during IS NOT NULL AND NOT isempty(system_during) AND lower(system_during) IS NOT NULL AND NOT lower_inf(system_during) AND isfinite(lower(system_during)) AND lower_inc(system_during) AND NOT upper_inc(system_during)),
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
    );

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
    );

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
    );

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
    );

CREATE INDEX ix_season_competition ON football.season (competition_id);

CREATE INDEX ix_fixture_competition ON football.fixture (competition_id);

CREATE INDEX ix_fixture_season ON football.fixture (season_id);

CREATE INDEX ix_fixture_home_team ON football.fixture (home_team_id);

CREATE INDEX ix_fixture_away_team ON football.fixture (away_team_id);

CREATE INDEX ix_gameweek_season ON fpl.gameweek (season_id);

CREATE INDEX ix_ingestion_run_provider ON provenance.ingestion_run (provider_id);

CREATE INDEX ix_source_snapshot_provider ON provenance.source_snapshot (provider_id);

CREATE INDEX ix_source_snapshot_run ON provenance.source_snapshot (ingestion_run_id);

CREATE INDEX ix_source_snapshot_raw ON provenance.source_snapshot (raw_blob_id);

CREATE INDEX ix_external_identifier_entity ON core.external_identifier (canonical_entity_id);

CREATE INDEX ix_external_identifier_provider ON core.external_identifier (provider_id);

CREATE INDEX ix_external_identifier_snapshot ON core.external_identifier (evidence_source_snapshot_id);

CREATE INDEX ix_external_identifier_as_of ON core.external_identifier USING gist (canonical_entity_id, valid_during, system_during);

CREATE INDEX ix_entity_alias_entity ON core.entity_alias (canonical_entity_id);

CREATE INDEX ix_entity_alias_provider ON core.entity_alias (provider_id);

CREATE INDEX ix_entity_alias_snapshot ON core.entity_alias (source_snapshot_id);

CREATE INDEX ix_entity_alias_as_of ON core.entity_alias USING gist (canonical_entity_id, valid_during, system_during);

CREATE INDEX ix_membership_team ON football.player_team_membership (team_id);

CREATE INDEX ix_membership_season ON football.player_team_membership (season_id);

CREATE INDEX ix_membership_snapshot ON football.player_team_membership (source_snapshot_id);

CREATE INDEX ix_membership_as_of ON football.player_team_membership USING gist (player_id, registration_type, valid_during, system_during);

CREATE INDEX ix_fixture_revision_snapshot ON football.fixture_revision (source_snapshot_id);

CREATE INDEX ix_fixture_revision_as_of ON football.fixture_revision USING gist (fixture_id, valid_during, system_during);

CREATE INDEX ix_assignment_gameweek ON football.fixture_gameweek_assignment (gameweek_id);

CREATE INDEX ix_assignment_snapshot ON football.fixture_gameweek_assignment (source_snapshot_id);

CREATE INDEX ix_assignment_as_of ON football.fixture_gameweek_assignment USING gist (fixture_id, valid_during, system_during);

CREATE INDEX ix_data_quality_snapshot ON core.data_quality_issue (source_snapshot_id);

CREATE INDEX ix_data_quality_entity ON core.data_quality_issue (canonical_entity_id);

CREATE INDEX ix_data_quality_run ON core.data_quality_issue (ingestion_run_id);

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
    $$;

CREATE FUNCTION provenance.reject_immutable_change()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'IMMUTABLE_RECORD';
    END
    $$;

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
    $$;

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
    $$;

CREATE TRIGGER trg_canonical_entity_successor
    BEFORE INSERT OR UPDATE ON core.canonical_entity
    FOR EACH ROW EXECUTE FUNCTION core.guard_canonical_successor();

CREATE TRIGGER trg_external_identifier_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON core.external_identifier
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'external_identifier_id', 'superseded_by_mapping_id',
      'canonical_entity_id', 'provider_id'
    );

CREATE TRIGGER trg_entity_alias_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON core.entity_alias
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'alias_id', 'superseded_by_alias_id', 'canonical_entity_id'
    );

CREATE TRIGGER trg_player_team_membership_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON football.player_team_membership
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'membership_id', 'superseded_by_membership_id', 'player_id', 'registration_type'
    );

CREATE TRIGGER trg_fixture_revision_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON football.fixture_revision
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'fixture_revision_id', 'superseded_by_revision_id', 'fixture_id'
    );

CREATE TRIGGER trg_fixture_gameweek_assignment_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON football.fixture_gameweek_assignment
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'assignment_id', 'superseded_by_assignment_id', 'fixture_id'
    );

CREATE TRIGGER trg_raw_blob_immutable
    BEFORE UPDATE OR DELETE ON provenance.raw_blob
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_raw_blob_deletion_immutable
    BEFORE UPDATE OR DELETE ON provenance.raw_blob_deletion
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_source_snapshot_immutable
    BEFORE UPDATE OR DELETE ON provenance.source_snapshot
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_ruleset_artifact_immutable
    BEFORE UPDATE OR DELETE ON provenance.ruleset_artifact
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_ruleset_activation_immutable
    BEFORE UPDATE OR DELETE ON provenance.ruleset_activation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE VIEW core.current_external_identifier AS
    SELECT * FROM core.external_identifier WHERE upper_inf(system_during);

CREATE VIEW core.current_entity_alias AS
    SELECT * FROM core.entity_alias WHERE upper_inf(system_during);

CREATE VIEW football.current_player_team_membership AS
    SELECT * FROM football.player_team_membership WHERE upper_inf(system_during);

CREATE VIEW football.current_fixture_revision AS
    SELECT * FROM football.fixture_revision WHERE upper_inf(system_during);

CREATE VIEW football.current_fixture_gameweek_assignment AS
    SELECT * FROM football.fixture_gameweek_assignment WHERE upper_inf(system_during);

CREATE VIEW provenance.available_raw_blob AS
    SELECT raw.*
    FROM provenance.raw_blob AS raw
    WHERE NOT EXISTS (
      SELECT 1 FROM provenance.raw_blob_deletion AS deletion
      WHERE deletion.raw_blob_id = raw.raw_blob_id
    );

INSERT INTO public.alembic_version (version_num) VALUES ('20260723_0001') RETURNING public.alembic_version.version_num;

-- Running upgrade 20260723_0001 -> 20260724_0002

ALTER TABLE football.season ADD CONSTRAINT uq_season_id_competition UNIQUE (season_id, competition_id);

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
    );

INSERT INTO football.team_season (team_id, season_id)
    SELECT candidate.team_id, candidate.season_id
    FROM (
      SELECT home_team_id AS team_id, season_id FROM football.fixture
      UNION
      SELECT away_team_id AS team_id, season_id FROM football.fixture
      UNION
      SELECT team_id, season_id FROM football.player_team_membership
    ) AS candidate
    ON CONFLICT (team_id, season_id) DO NOTHING;

ALTER TABLE football.fixture ADD CONSTRAINT uq_fixture_id_season UNIQUE (fixture_id, season_id);

ALTER TABLE football.fixture ADD CONSTRAINT fk_fixture_season_competition
      FOREIGN KEY (season_id, competition_id)
      REFERENCES football.season(season_id, competition_id) ON DELETE RESTRICT;

ALTER TABLE football.fixture ADD CONSTRAINT fk_fixture_home_team_season
      FOREIGN KEY (home_team_id, season_id)
      REFERENCES football.team_season(team_id, season_id) ON DELETE RESTRICT;

ALTER TABLE football.fixture ADD CONSTRAINT fk_fixture_away_team_season
      FOREIGN KEY (away_team_id, season_id)
      REFERENCES football.team_season(team_id, season_id) ON DELETE RESTRICT;

ALTER TABLE football.player_team_membership ADD CONSTRAINT fk_membership_team_season
      FOREIGN KEY (team_id, season_id)
      REFERENCES football.team_season(team_id, season_id) ON DELETE RESTRICT;

ALTER TABLE fpl.gameweek ADD CONSTRAINT uq_gameweek_id_season UNIQUE (gameweek_id, season_id);

ALTER TABLE football.fixture_gameweek_assignment ADD COLUMN season_id uuid;

DROP TRIGGER trg_fixture_gameweek_assignment_temporal ON football.fixture_gameweek_assignment;

UPDATE football.fixture_gameweek_assignment AS assignment
    SET season_id = fixture_record.season_id
    FROM football.fixture AS fixture_record
    WHERE fixture_record.fixture_id = assignment.fixture_id;

ALTER TABLE football.fixture_gameweek_assignment ALTER COLUMN season_id SET NOT NULL;

ALTER TABLE football.fixture_gameweek_assignment ADD CONSTRAINT fk_assignment_fixture_season
      FOREIGN KEY (fixture_id, season_id)
      REFERENCES football.fixture(fixture_id, season_id) ON DELETE RESTRICT;

ALTER TABLE football.fixture_gameweek_assignment ADD CONSTRAINT fk_assignment_gameweek_season
      FOREIGN KEY (gameweek_id, season_id)
      REFERENCES fpl.gameweek(gameweek_id, season_id) ON DELETE RESTRICT;

CREATE TRIGGER trg_fixture_gameweek_assignment_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON football.fixture_gameweek_assignment
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'assignment_id', 'superseded_by_assignment_id', 'fixture_id'
    );

ALTER TABLE provenance.ruleset_artifact DROP CONSTRAINT uq_ruleset_artifact_identity_hash;

ALTER TABLE provenance.ruleset_artifact ADD CONSTRAINT uq_ruleset_artifact_identity UNIQUE (ruleset_id, ruleset_version);

ALTER TABLE provenance.raw_blob ALTER COLUMN storage_policy DROP NOT NULL;

ALTER TABLE provenance.raw_blob ADD CONSTRAINT uq_raw_blob_content_coherence UNIQUE (raw_blob_id, body_sha256, byte_size);

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
    );

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
    );

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
    $$;

CREATE TRIGGER trg_raw_storage_rights
    BEFORE INSERT ON provenance.raw_storage_object
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_raw_storage_rights();

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
    );

ALTER TABLE provenance.source_snapshot ADD COLUMN body_size bigint;

ALTER TABLE provenance.source_snapshot ADD COLUMN attempt_number integer;

ALTER TABLE provenance.source_snapshot ADD COLUMN sanitized_target text;

ALTER TABLE provenance.source_snapshot ADD COLUMN raw_storage_object_id uuid;

ALTER TABLE provenance.source_snapshot ADD COLUMN rights_profile_version varchar(40);

ALTER TABLE provenance.source_snapshot ADD COLUMN rights_profile_record_id uuid;

ALTER TABLE provenance.source_snapshot ADD COLUMN adapter_version varchar(40);

ALTER TABLE provenance.source_snapshot ADD COLUMN contract_version varchar(40);

ALTER TABLE provenance.source_snapshot ADD COLUMN envelope_sha256 char(64);

ALTER TABLE provenance.source_snapshot ADD CONSTRAINT fk_source_snapshot_raw_storage
      FOREIGN KEY (raw_storage_object_id)
      REFERENCES provenance.raw_storage_object(raw_storage_object_id) ON DELETE RESTRICT;

ALTER TABLE provenance.source_snapshot ADD CONSTRAINT fk_source_snapshot_rights_profile
      FOREIGN KEY (rights_profile_record_id)
      REFERENCES provenance.rights_profile(rights_profile_record_id) ON DELETE RESTRICT;

ALTER TABLE provenance.source_snapshot
      ADD CONSTRAINT fk_source_snapshot_raw_storage_coherence
      FOREIGN KEY (raw_storage_object_id, raw_blob_id, rights_profile_record_id)
      REFERENCES provenance.raw_storage_object
        (raw_storage_object_id, raw_blob_id, rights_profile_record_id)
      ON DELETE RESTRICT;

ALTER TABLE provenance.source_snapshot
      ADD CONSTRAINT fk_source_snapshot_raw_content_coherence
      FOREIGN KEY (raw_blob_id, body_sha256, body_size)
      REFERENCES provenance.raw_blob (raw_blob_id, body_sha256, byte_size)
      ON DELETE RESTRICT;

ALTER TABLE provenance.source_snapshot
      ADD CONSTRAINT fk_source_snapshot_rights_profile_version
      FOREIGN KEY (rights_profile_record_id, rights_profile_key, rights_profile_version)
      REFERENCES provenance.rights_profile
        (rights_profile_record_id, rights_profile_id, profile_version)
      ON DELETE RESTRICT;

ALTER TABLE provenance.source_snapshot ADD CONSTRAINT uq_source_snapshot_rights_profile UNIQUE (source_snapshot_id, rights_profile_record_id);

ALTER TABLE provenance.source_snapshot ADD CONSTRAINT ck_source_snapshot_body_size CHECK (body_size IS NULL OR body_size >= 0);

ALTER TABLE provenance.source_snapshot ADD CONSTRAINT ck_source_snapshot_attempt CHECK (
      (ingestion_run_id IS NULL) = (attempt_number IS NULL)
      AND (attempt_number IS NULL OR attempt_number > 0)
    );

ALTER TABLE provenance.source_snapshot ADD CONSTRAINT ck_source_snapshot_envelope_hash CHECK (envelope_sha256 IS NULL OR envelope_sha256 ~ '^[0-9a-f]{64}$');

ALTER TABLE provenance.source_snapshot DROP CONSTRAINT ck_source_snapshot_retention;

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
    );

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
    );

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
    );

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
    );

CREATE TRIGGER trg_source_mapping_candidate_immutable
    BEFORE UPDATE OR DELETE ON provenance.source_mapping_candidate
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

INSERT INTO provenance.source_processing_event (
      source_snapshot_id, operation_id, sequence_number, stage, event_at, stage_version,
      event_sha256, actor
    )
    SELECT source_snapshot_id, source_snapshot_id, 1, 'RECEIVED', received_at, 'legacy-dat003',
           encode(sha256(convert_to(source_snapshot_id::text || chr(58) || '1', 'UTF8')), 'hex'),
           'dat003-migration'
    FROM provenance.source_snapshot;

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
    WHERE stored_at IS NOT NULL OR validation_status <> 'RECEIVED';

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
    WHERE validation_status = 'USABLE';

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
    WHERE validation_status = 'VALID';

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
    WHERE validation_status IN ('QUARANTINED','REJECTED');

UPDATE provenance.source_processing_event AS event
    SET previous_event_id = predecessor.processing_event_id
    FROM provenance.source_processing_event AS predecessor
    WHERE predecessor.source_snapshot_id = event.source_snapshot_id
      AND predecessor.sequence_number = event.sequence_number - 1
      AND event.sequence_number > 1;

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
    $$;

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
    $$;

CREATE TRIGGER trg_source_snapshot_envelope
    BEFORE INSERT ON provenance.source_snapshot
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_source_snapshot_envelope();

CREATE TRIGGER trg_source_processing_event_guard
    BEFORE INSERT OR UPDATE OR DELETE ON provenance.source_processing_event
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_processing_event();

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
    ) AS usable ON true;

ALTER TABLE core.external_identifier DROP CONSTRAINT ex_external_identifier_current_accepted;

ALTER TABLE core.external_identifier ADD COLUMN season_id uuid;

ALTER TABLE core.external_identifier ADD CONSTRAINT fk_external_identifier_season
      FOREIGN KEY (season_id) REFERENCES football.season(season_id) ON DELETE RESTRICT;

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
      DEFERRABLE INITIALLY IMMEDIATE;

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
    );

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
    );

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
    );

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
    );

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
    );

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
    $$;

CREATE TRIGGER trg_team_observation_source_usable
    BEFORE INSERT ON fpl.team_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_fpl_observation_source_usable();

CREATE TRIGGER trg_player_observation_source_usable
    BEFORE INSERT ON fpl.player_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_fpl_observation_source_usable();

CREATE TRIGGER trg_gameweek_observation_source_usable
    BEFORE INSERT ON fpl.gameweek_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_fpl_observation_source_usable();

CREATE TRIGGER trg_fixture_observation_source_usable
    BEFORE INSERT ON fpl.fixture_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_fpl_observation_source_usable();

CREATE TABLE provenance.semantic_effect_source (
      semantic_effect_source_id uuid CONSTRAINT pk_semantic_effect_source PRIMARY KEY DEFAULT uuidv7(),
      effect_type varchar(40) NOT NULL, semantic_sha256 char(64) NOT NULL,
      source_snapshot_id uuid NOT NULL, observed_at timestamptz NOT NULL,
      CONSTRAINT uq_semantic_effect_source_lineage UNIQUE
        (effect_type, semantic_sha256, source_snapshot_id),
      CONSTRAINT fk_semantic_effect_source_snapshot FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT ck_semantic_effect_source_hash CHECK (semantic_sha256 ~ '^[0-9a-f]{64}$')
    );

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
    );

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
    );

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
    );

ALTER TABLE core.data_quality_issue ADD COLUMN source_bundle_id uuid;

ALTER TABLE core.data_quality_issue ADD COLUMN subject_scope varchar(32);

ALTER TABLE core.data_quality_issue ADD COLUMN stage varchar(40);

ALTER TABLE core.data_quality_issue ADD COLUMN message text;

ALTER TABLE core.data_quality_issue ADD COLUMN review_at timestamptz;

UPDATE core.data_quality_issue
    SET subject_scope = CASE
          WHEN source_snapshot_id IS NOT NULL THEN 'SOURCE_SNAPSHOT'
          WHEN ingestion_run_id IS NOT NULL THEN 'INGESTION_RUN'
          WHEN canonical_entity_id IS NOT NULL THEN 'CANONICAL_ENTITY'
          ELSE 'GLOBAL_SYSTEM' END,
        stage = 'DAT003_LEGACY',
        message = issue_type;

ALTER TABLE core.data_quality_issue ALTER COLUMN subject_scope SET NOT NULL;

ALTER TABLE core.data_quality_issue ALTER COLUMN stage SET NOT NULL;

ALTER TABLE core.data_quality_issue ALTER COLUMN message SET NOT NULL;

ALTER TABLE core.data_quality_issue DROP CONSTRAINT ck_data_quality_severity;

UPDATE core.data_quality_issue
    SET severity = CASE severity
      WHEN 'INFO' THEN 'P3'
      WHEN 'WARN' THEN 'P2'
      WHEN 'ERROR' THEN 'P1'
      WHEN 'BLOCKING' THEN 'P0'
      ELSE severity
    END
    WHERE severity IN ('INFO','WARN','ERROR','BLOCKING');

ALTER TABLE core.data_quality_issue ADD CONSTRAINT ck_data_quality_severity CHECK
      (severity IN ('P0','P1','P2','P3'));

ALTER TABLE core.data_quality_issue ADD CONSTRAINT fk_data_quality_source_bundle
      FOREIGN KEY (source_bundle_id)
      REFERENCES provenance.source_bundle(source_bundle_id) ON DELETE RESTRICT;

ALTER TABLE core.data_quality_issue ADD CONSTRAINT ck_data_quality_subject CHECK (
      (subject_scope = 'SOURCE_SNAPSHOT' AND source_snapshot_id IS NOT NULL)
      OR (subject_scope = 'INGESTION_RUN' AND ingestion_run_id IS NOT NULL)
      OR (subject_scope = 'CANONICAL_ENTITY' AND canonical_entity_id IS NOT NULL)
      OR (subject_scope = 'SOURCE_BUNDLE' AND source_bundle_id IS NOT NULL)
      OR (subject_scope = 'GLOBAL_SYSTEM' AND source_snapshot_id IS NULL
          AND ingestion_run_id IS NULL AND canonical_entity_id IS NULL
          AND source_bundle_id IS NULL)
    );

CREATE INDEX ix_team_season_season ON football.team_season (season_id);

CREATE INDEX ix_team_season_snapshot ON football.team_season (source_snapshot_id);

CREATE INDEX ix_assignment_season ON football.fixture_gameweek_assignment (season_id);

CREATE INDEX ix_rights_profile_provider ON provenance.rights_profile (provider_key);

CREATE INDEX ix_raw_storage_content ON provenance.raw_storage_object (raw_blob_id);

CREATE INDEX ix_raw_storage_rights ON provenance.raw_storage_object (rights_profile_record_id);

CREATE INDEX ix_source_snapshot_raw_storage ON provenance.source_snapshot (raw_storage_object_id);

CREATE INDEX ix_source_snapshot_rights_profile ON provenance.source_snapshot (rights_profile_record_id);

CREATE INDEX ix_rights_decision_profile ON provenance.rights_decision (rights_profile_record_id);

CREATE INDEX ix_rights_decision_snapshot ON provenance.rights_decision (source_snapshot_id);

CREATE INDEX ix_processing_event_snapshot_sequence ON provenance.source_processing_event (source_snapshot_id, sequence_number);

CREATE INDEX ix_external_identifier_season ON core.external_identifier (season_id);

CREATE INDEX ix_player_season_season ON fpl.player_season (season_id);

CREATE INDEX ix_player_season_snapshot ON fpl.player_season (source_snapshot_id);

CREATE INDEX ix_team_observation_subject ON fpl.team_observation (team_season_id);

CREATE INDEX ix_team_observation_snapshot ON fpl.team_observation (source_snapshot_id);

CREATE INDEX ix_player_observation_subject ON fpl.player_observation (player_fpl_season_id);

CREATE INDEX ix_player_observation_team ON fpl.player_observation (team_season_id);

CREATE INDEX ix_player_observation_snapshot ON fpl.player_observation (source_snapshot_id);

CREATE INDEX ix_gameweek_observation_subject ON fpl.gameweek_observation (gameweek_id);

CREATE INDEX ix_gameweek_observation_snapshot ON fpl.gameweek_observation (source_snapshot_id);

CREATE INDEX ix_fixture_observation_subject ON fpl.fixture_observation (fixture_id);

CREATE INDEX ix_fixture_observation_snapshot ON fpl.fixture_observation (source_snapshot_id);

CREATE INDEX ix_semantic_effect_source_snapshot ON provenance.semantic_effect_source (source_snapshot_id);

CREATE INDEX ix_semantic_observation_claim_snapshot ON provenance.semantic_observation_claim (source_snapshot_id);

CREATE INDEX ix_source_bundle_season_cutoff ON provenance.source_bundle (season_id, information_cutoff);

CREATE INDEX ix_source_bundle_member_snapshot ON provenance.source_bundle_member (source_snapshot_id);

CREATE INDEX ix_data_quality_bundle ON core.data_quality_issue (source_bundle_id);

CREATE TRIGGER trg_rights_profile_immutable
    BEFORE UPDATE OR DELETE ON provenance.rights_profile
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_raw_storage_object_immutable
    BEFORE UPDATE OR DELETE ON provenance.raw_storage_object
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_raw_storage_deletion_immutable
    BEFORE UPDATE OR DELETE ON provenance.raw_storage_deletion
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_rights_decision_immutable
    BEFORE UPDATE OR DELETE ON provenance.rights_decision
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_player_season_immutable
    BEFORE UPDATE OR DELETE ON fpl.player_season
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_team_observation_immutable
    BEFORE UPDATE OR DELETE ON fpl.team_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_player_observation_immutable
    BEFORE UPDATE OR DELETE ON fpl.player_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_gameweek_observation_immutable
    BEFORE UPDATE OR DELETE ON fpl.gameweek_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_fixture_observation_immutable
    BEFORE UPDATE OR DELETE ON fpl.fixture_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_semantic_effect_source_immutable
    BEFORE UPDATE OR DELETE ON provenance.semantic_effect_source
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_semantic_observation_claim_immutable
    BEFORE UPDATE OR DELETE ON provenance.semantic_observation_claim
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_source_bundle_immutable
    BEFORE UPDATE OR DELETE ON provenance.source_bundle
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_source_bundle_member_immutable
    BEFORE UPDATE OR DELETE ON provenance.source_bundle_member
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE VIEW provenance.available_raw_storage_object AS
    SELECT storage.*
    FROM provenance.raw_storage_object AS storage
    WHERE NOT EXISTS (
      SELECT 1 FROM provenance.raw_storage_deletion AS deletion
      WHERE deletion.raw_storage_object_id = storage.raw_storage_object_id
    );

DROP VIEW core.current_external_identifier;

CREATE VIEW core.current_external_identifier AS SELECT * FROM core.external_identifier WHERE upper_inf(system_during);

DROP VIEW football.current_fixture_gameweek_assignment;

CREATE VIEW football.current_fixture_gameweek_assignment AS SELECT * FROM football.fixture_gameweek_assignment WHERE upper_inf(system_during);

CREATE VIEW fpl.current_team_observation AS SELECT DISTINCT ON (observation.team_season_id) observation.* FROM fpl.team_observation AS observation JOIN provenance.source_snapshot_lifecycle AS lifecycle ON lifecycle.source_snapshot_id = observation.source_snapshot_id WHERE lifecycle.current_state = 'USABLE' ORDER BY observation.team_season_id, observation.observed_at DESC, observation.usable_at DESC, observation.team_observation_id DESC;

CREATE VIEW fpl.current_player_observation AS SELECT DISTINCT ON (observation.player_fpl_season_id) observation.* FROM fpl.player_observation AS observation JOIN provenance.source_snapshot_lifecycle AS lifecycle ON lifecycle.source_snapshot_id = observation.source_snapshot_id WHERE lifecycle.current_state = 'USABLE' ORDER BY observation.player_fpl_season_id, observation.observed_at DESC, observation.usable_at DESC, observation.player_observation_id DESC;

CREATE VIEW fpl.current_gameweek_observation AS SELECT DISTINCT ON (observation.gameweek_id) observation.* FROM fpl.gameweek_observation AS observation JOIN provenance.source_snapshot_lifecycle AS lifecycle ON lifecycle.source_snapshot_id = observation.source_snapshot_id WHERE lifecycle.current_state = 'USABLE' ORDER BY observation.gameweek_id, observation.observed_at DESC, observation.usable_at DESC, observation.gameweek_observation_id DESC;

CREATE VIEW fpl.current_fixture_observation AS SELECT DISTINCT ON (observation.fixture_id) observation.* FROM fpl.fixture_observation AS observation JOIN provenance.source_snapshot_lifecycle AS lifecycle ON lifecycle.source_snapshot_id = observation.source_snapshot_id WHERE lifecycle.current_state = 'USABLE' ORDER BY observation.fixture_id, observation.observed_at DESC, observation.usable_at DESC, observation.fixture_observation_id DESC;

UPDATE public.alembic_version SET version_num='20260724_0002' WHERE public.alembic_version.version_num = '20260723_0001';

-- Running upgrade 20260724_0002 -> 20260725_0003

DROP TRIGGER trg_source_bundle_immutable ON provenance.source_bundle;

DROP TRIGGER trg_source_bundle_member_immutable ON provenance.source_bundle_member;

ALTER TABLE provenance.source_bundle ADD COLUMN rights_profile_record_id uuid;

ALTER TABLE provenance.source_bundle_member ADD COLUMN rights_profile_record_id uuid;

UPDATE provenance.source_bundle_member AS member
    SET rights_profile_record_id = snapshot.rights_profile_record_id
    FROM provenance.source_snapshot AS snapshot
    WHERE snapshot.source_snapshot_id = member.source_snapshot_id;

UPDATE provenance.source_bundle AS bundle
    SET rights_profile_record_id = candidate.rights_profile_record_id
    FROM (
      SELECT member.source_bundle_id, min(member.rights_profile_record_id::text)::uuid
               AS rights_profile_record_id
      FROM provenance.source_bundle_member AS member
      GROUP BY member.source_bundle_id
      HAVING count(DISTINCT member.rights_profile_record_id) = 1
         AND bool_and(member.rights_profile_record_id IS NOT NULL)
    ) AS candidate
    WHERE candidate.source_bundle_id = bundle.source_bundle_id;

DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM provenance.source_bundle AS bundle
        LEFT JOIN provenance.source_bundle_member AS member
          ON member.source_bundle_id = bundle.source_bundle_id
        WHERE bundle.rights_profile_record_id IS NULL
           OR member.rights_profile_record_id IS NULL
           OR member.rights_profile_record_id IS DISTINCT FROM bundle.rights_profile_record_id
      ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'BUNDLE_RIGHTS_BACKFILL_INVALID';
      END IF;
    END
    $$;

ALTER TABLE provenance.source_bundle ALTER COLUMN rights_profile_record_id SET NOT NULL;

ALTER TABLE provenance.source_bundle_member ALTER COLUMN rights_profile_record_id SET NOT NULL;

ALTER TABLE provenance.source_bundle
      ADD CONSTRAINT fk_source_bundle_rights_profile
      FOREIGN KEY (rights_profile_record_id)
      REFERENCES provenance.rights_profile(rights_profile_record_id) ON DELETE RESTRICT;

ALTER TABLE provenance.source_bundle
      ADD CONSTRAINT uq_source_bundle_rights_profile
      UNIQUE (source_bundle_id, rights_profile_record_id);

ALTER TABLE provenance.source_bundle_member
      ADD CONSTRAINT fk_source_bundle_member_bundle_rights
      FOREIGN KEY (source_bundle_id, rights_profile_record_id)
      REFERENCES provenance.source_bundle(source_bundle_id, rights_profile_record_id)
      ON DELETE RESTRICT;

ALTER TABLE provenance.source_bundle_member
      ADD CONSTRAINT fk_source_bundle_member_snapshot_rights
      FOREIGN KEY (source_snapshot_id, rights_profile_record_id)
      REFERENCES provenance.source_snapshot(source_snapshot_id, rights_profile_record_id)
      ON DELETE RESTRICT;

CREATE FUNCTION provenance.lock_bundle_quality_subject()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      IF NEW.source_snapshot_id IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(
          hashtextextended('bundle-quality:' || NEW.source_snapshot_id::text, 0)
        );
        IF NEW.status IN ('OPEN','ACKNOWLEDGED')
           AND NEW.severity IN ('P0','P1')
           AND EXISTS (
             SELECT 1 FROM provenance.source_bundle_member AS member
             WHERE member.source_snapshot_id = NEW.source_snapshot_id
           ) THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'BUNDLE_QUALITY_ALREADY_PUBLISHED';
        END IF;
      END IF;
      RETURN NEW;
    END
    $$;

CREATE TRIGGER trg_data_quality_bundle_lock
    BEFORE INSERT OR UPDATE ON core.data_quality_issue
    FOR EACH ROW EXECUTE FUNCTION provenance.lock_bundle_quality_subject();

CREATE FUNCTION provenance.guard_source_bundle_publication()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
      target_bundle_id uuid;
      bundle_record record;
      member_count integer;
      expected_quality text;
      member_record record;
    BEGIN
      target_bundle_id := CASE
        WHEN TG_TABLE_NAME = 'source_bundle' THEN NEW.source_bundle_id
        ELSE NEW.source_bundle_id
      END;

      SELECT bundle.*, profile.rights_profile_id, profile.profile_version,
             profile.provider_key,
             profile.status AS profile_status, profile.capabilities
      INTO bundle_record
      FROM provenance.source_bundle AS bundle
      JOIN provenance.rights_profile AS profile
        ON profile.rights_profile_record_id = bundle.rights_profile_record_id
      WHERE bundle.source_bundle_id = target_bundle_id;

      IF bundle_record IS NULL
         OR bundle_record.profile_status IS DISTINCT FROM 'HUMAN_APPROVED'
         OR bundle_record.capabilities ->> 'derived_storage' IS DISTINCT FROM 'ALLOW'
         OR bundle_record.capabilities ->> 'private_internal_use' IS DISTINCT FROM 'ALLOW'
         OR bundle_record.rights_profiles IS DISTINCT FROM jsonb_build_array(
              jsonb_build_object(
                'id', bundle_record.rights_profile_id,
                'version', bundle_record.profile_version
              )
            ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'BUNDLE_RIGHTS_BLOCKED';
      END IF;

      SELECT count(*) INTO member_count
      FROM provenance.source_bundle_member
      WHERE source_bundle_id = target_bundle_id;
      IF member_count <> 2
         OR NOT EXISTS (
              SELECT 1 FROM provenance.source_bundle_member
              WHERE source_bundle_id = target_bundle_id AND role = 'BOOTSTRAP'
            )
         OR NOT EXISTS (
              SELECT 1 FROM provenance.source_bundle_member
              WHERE source_bundle_id = target_bundle_id AND role = 'FIXTURES'
            ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'BUNDLE_MEMBERS_INVALID';
      END IF;

      FOR member_record IN
        SELECT member.*, snapshot.resource, snapshot.rights_profile_key,
               snapshot.rights_profile_version, lifecycle.current_state,
               lifecycle.usable_at AS authoritative_usable_at,
               provider.provider_key AS source_provider_key
        FROM provenance.source_bundle_member AS member
        JOIN provenance.source_snapshot AS snapshot
          ON snapshot.source_snapshot_id = member.source_snapshot_id
        JOIN provenance.data_provider AS provider
          ON provider.provider_id = snapshot.provider_id
        JOIN provenance.source_snapshot_lifecycle AS lifecycle
          ON lifecycle.source_snapshot_id = member.source_snapshot_id
        WHERE member.source_bundle_id = target_bundle_id
        ORDER BY member.source_snapshot_id
      LOOP
        PERFORM pg_advisory_xact_lock(
          hashtextextended('bundle-quality:' || member_record.source_snapshot_id::text, 0)
        );
        IF member_record.rights_profile_record_id
             IS DISTINCT FROM bundle_record.rights_profile_record_id
           OR member_record.rights_profile_key IS DISTINCT FROM bundle_record.rights_profile_id
           OR member_record.rights_profile_version
             IS DISTINCT FROM bundle_record.profile_version
           OR member_record.source_provider_key
             IS DISTINCT FROM bundle_record.provider_key
           OR member_record.current_state IS DISTINCT FROM 'USABLE'
           OR member_record.authoritative_usable_at IS DISTINCT FROM member_record.usable_at
           OR member_record.usable_at > bundle_record.information_cutoff
           OR (member_record.role = 'BOOTSTRAP' AND member_record.resource <> 'bootstrap')
           OR (member_record.role = 'FIXTURES' AND member_record.resource <> 'fixtures')
           OR NOT EXISTS (
                SELECT 1 FROM provenance.rights_decision AS decision
                WHERE decision.source_snapshot_id = member_record.source_snapshot_id
                  AND decision.rights_profile_record_id = bundle_record.rights_profile_record_id
                  AND decision.capability = 'derived_storage'
                  AND decision.decision = 'ALLOW'
              )
           OR EXISTS (
                SELECT 1 FROM provenance.rights_decision AS decision
                WHERE decision.source_snapshot_id = member_record.source_snapshot_id
                  AND decision.rights_profile_record_id = bundle_record.rights_profile_record_id
                  AND decision.capability = 'derived_storage'
                  AND decision.decision <> 'ALLOW'
              ) THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'BUNDLE_MEMBER_RIGHTS_BLOCKED';
        END IF;
      END LOOP;

      IF EXISTS (
        SELECT 1
        FROM core.data_quality_issue AS issue
        JOIN provenance.source_bundle_member AS member
          ON member.source_snapshot_id = issue.source_snapshot_id
        WHERE member.source_bundle_id = target_bundle_id
          AND issue.status IN ('OPEN','ACKNOWLEDGED')
          AND issue.severity IN ('P0','P1')
      ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'BUNDLE_QUALITY_BLOCKED';
      END IF;

      expected_quality := CASE WHEN EXISTS (
        SELECT 1
        FROM core.data_quality_issue AS issue
        JOIN provenance.source_bundle_member AS member
          ON member.source_snapshot_id = issue.source_snapshot_id
        WHERE member.source_bundle_id = target_bundle_id
          AND issue.status IN ('OPEN','ACKNOWLEDGED')
          AND issue.severity IN ('P2','P3')
      ) THEN 'PASS_WITH_WARNINGS' ELSE 'PASS' END;
      IF bundle_record.quality_status IS DISTINCT FROM expected_quality THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'BUNDLE_QUALITY_MISMATCH';
      END IF;
      RETURN NEW;
    END
    $$;

DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM provenance.source_bundle AS bundle
        JOIN provenance.rights_profile AS profile
          ON profile.rights_profile_record_id = bundle.rights_profile_record_id
        WHERE profile.status <> 'HUMAN_APPROVED'
           OR profile.capabilities ->> 'derived_storage' <> 'ALLOW'
           OR profile.capabilities ->> 'private_internal_use' <> 'ALLOW'
           OR bundle.rights_profiles IS DISTINCT FROM jsonb_build_array(
                jsonb_build_object(
                  'id', profile.rights_profile_id,
                  'version', profile.profile_version
                )
              )
      ) OR EXISTS (
        SELECT 1 FROM provenance.source_bundle AS bundle
        WHERE (SELECT count(*) FROM provenance.source_bundle_member AS member
               WHERE member.source_bundle_id = bundle.source_bundle_id) <> 2
           OR NOT EXISTS (
                SELECT 1 FROM provenance.source_bundle_member AS member
                WHERE member.source_bundle_id = bundle.source_bundle_id
                  AND member.role = 'BOOTSTRAP'
              )
           OR NOT EXISTS (
                SELECT 1 FROM provenance.source_bundle_member AS member
                WHERE member.source_bundle_id = bundle.source_bundle_id
                  AND member.role = 'FIXTURES'
              )
      ) OR EXISTS (
        SELECT 1
        FROM provenance.source_bundle_member AS member
        JOIN provenance.source_bundle AS bundle
          ON bundle.source_bundle_id = member.source_bundle_id
        JOIN provenance.source_snapshot AS snapshot
          ON snapshot.source_snapshot_id = member.source_snapshot_id
        JOIN provenance.source_snapshot_lifecycle AS lifecycle
          ON lifecycle.source_snapshot_id = member.source_snapshot_id
        JOIN provenance.data_provider AS provider
          ON provider.provider_id = snapshot.provider_id
        JOIN provenance.rights_profile AS profile
          ON profile.rights_profile_record_id = bundle.rights_profile_record_id
        WHERE member.rights_profile_record_id IS DISTINCT FROM bundle.rights_profile_record_id
           OR snapshot.rights_profile_record_id IS DISTINCT FROM bundle.rights_profile_record_id
           OR snapshot.rights_profile_key IS DISTINCT FROM profile.rights_profile_id
           OR snapshot.rights_profile_version IS DISTINCT FROM profile.profile_version
           OR provider.provider_key IS DISTINCT FROM profile.provider_key
           OR lifecycle.current_state IS DISTINCT FROM 'USABLE'
           OR lifecycle.usable_at IS DISTINCT FROM member.usable_at
           OR member.usable_at > bundle.information_cutoff
           OR (member.role = 'BOOTSTRAP' AND snapshot.resource <> 'bootstrap')
           OR (member.role = 'FIXTURES' AND snapshot.resource <> 'fixtures')
           OR NOT EXISTS (
                SELECT 1 FROM provenance.rights_decision AS decision
                WHERE decision.source_snapshot_id = member.source_snapshot_id
                  AND decision.rights_profile_record_id = bundle.rights_profile_record_id
                  AND decision.capability = 'derived_storage'
                  AND decision.decision = 'ALLOW'
              )
           OR EXISTS (
                SELECT 1 FROM provenance.rights_decision AS decision
                WHERE decision.source_snapshot_id = member.source_snapshot_id
                  AND decision.rights_profile_record_id = bundle.rights_profile_record_id
                  AND decision.capability = 'derived_storage'
                  AND decision.decision <> 'ALLOW'
              )
      ) OR EXISTS (
        SELECT 1
        FROM provenance.source_bundle AS bundle
        WHERE EXISTS (
          SELECT 1
          FROM provenance.source_bundle_member AS member
          JOIN core.data_quality_issue AS issue
            ON issue.source_snapshot_id = member.source_snapshot_id
          WHERE member.source_bundle_id = bundle.source_bundle_id
            AND issue.status IN ('OPEN','ACKNOWLEDGED')
            AND issue.severity IN ('P0','P1')
        ) OR bundle.quality_status IS DISTINCT FROM CASE WHEN EXISTS (
          SELECT 1
          FROM provenance.source_bundle_member AS member
          JOIN core.data_quality_issue AS issue
            ON issue.source_snapshot_id = member.source_snapshot_id
          WHERE member.source_bundle_id = bundle.source_bundle_id
            AND issue.status IN ('OPEN','ACKNOWLEDGED')
            AND issue.severity IN ('P2','P3')
        ) THEN 'PASS_WITH_WARNINGS' ELSE 'PASS' END
      ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'EXISTING_BUNDLE_AUTHORITY_INVALID';
      END IF;
    END
    $$;

CREATE CONSTRAINT TRIGGER trg_source_bundle_publication_guard
    AFTER INSERT ON provenance.source_bundle
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_source_bundle_publication();

CREATE CONSTRAINT TRIGGER trg_source_bundle_member_publication_guard
    AFTER INSERT ON provenance.source_bundle_member
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_source_bundle_publication();

CREATE TRIGGER trg_source_bundle_immutable
    BEFORE UPDATE OR DELETE ON provenance.source_bundle
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_source_bundle_member_immutable
    BEFORE UPDATE OR DELETE ON provenance.source_bundle_member
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

UPDATE public.alembic_version SET version_num='20260725_0003' WHERE public.alembic_version.version_num = '20260724_0002';

-- Running upgrade 20260725_0003 -> 20260725_0004

CREATE SCHEMA betting;

ALTER TABLE provenance.rights_decision
      ADD CONSTRAINT uq_rights_decision_authority
      UNIQUE NULLS NOT DISTINCT
        (rights_profile_record_id, source_snapshot_id, capability);

ALTER TABLE core.external_identifier
      ADD CONSTRAINT ck_external_identifier_odds_operator_scope CHECK (
        identifier_namespace <> 'the_odds_api.bookmaker.key'
        OR (entity_type = 'BETTING_OPERATOR'
            AND season_id IS NULL
            AND provider_product = 'soccer_epl/odds')
      );

ALTER TABLE core.canonical_entity DROP CONSTRAINT ck_canonical_entity_type;

ALTER TABLE core.canonical_entity ADD CONSTRAINT ck_canonical_entity_type CHECK (
      entity_type IN ('COMPETITION','SEASON','GAMEWEEK','TEAM','PLAYER','FIXTURE',
                      'DATA_PROVIDER','BETTING_OPERATOR','MARKET','SELECTION')
    );

CREATE TABLE betting.betting_operator (
      operator_id uuid CONSTRAINT pk_betting_operator PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'BETTING_OPERATOR',
      operator_key varchar(120) NOT NULL,
      display_name text NOT NULL,
      active boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT fk_betting_operator_canonical_type
        FOREIGN KEY (operator_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT,
      CONSTRAINT uq_betting_operator_key UNIQUE (operator_key),
      CONSTRAINT ck_betting_operator_entity_type CHECK (entity_type = 'BETTING_OPERATOR')
    );

CREATE TABLE betting.market_definition (
      market_definition_id uuid CONSTRAINT pk_market_definition PRIMARY KEY DEFAULT uuidv7(),
      definition_key varchar(120) NOT NULL,
      definition_version varchar(40) NOT NULL,
      scope varchar(24) NOT NULL,
      period varchar(24) NOT NULL,
      outcomes jsonb NOT NULL,
      description text NOT NULL,
      CONSTRAINT uq_market_definition_identity UNIQUE (definition_key, definition_version),
      CONSTRAINT ck_market_definition_reference CHECK
        (definition_key = 'MATCH_RESULT_1X2' AND definition_version = '1.0.0'),
      CONSTRAINT ck_market_definition_scope CHECK (scope = 'FIXTURE'),
      CONSTRAINT ck_market_definition_period CHECK (period = 'FULL_TIME'),
      CONSTRAINT ck_market_definition_outcomes CHECK
        (outcomes = '["HOME","DRAW","AWAY"]'::jsonb)
    );

CREATE TABLE betting.settlement_profile (
      settlement_profile_id uuid CONSTRAINT pk_settlement_profile PRIMARY KEY DEFAULT uuidv7(),
      profile_key varchar(160) NOT NULL,
      profile_version varchar(40) NOT NULL,
      period varchar(24) NOT NULL,
      includes_extra_time boolean NOT NULL,
      description text NOT NULL,
      CONSTRAINT uq_settlement_profile_identity UNIQUE (profile_key, profile_version),
      CONSTRAINT ck_settlement_profile_reference CHECK
        (profile_key = 'SOCCER_FULL_TIME_90_MINUTES_REFERENCE_V1'
         AND profile_version = '1.0.0'),
      CONSTRAINT ck_settlement_profile_period CHECK (period = 'FULL_TIME'),
      CONSTRAINT ck_settlement_profile_no_extra_time CHECK (includes_extra_time = false)
    );

CREATE TABLE betting.operator_fixture_market (
      market_id uuid CONSTRAINT pk_operator_fixture_market PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'MARKET',
      fixture_id uuid NOT NULL,
      operator_id uuid NOT NULL,
      market_definition_id uuid NOT NULL,
      period varchar(24) NOT NULL,
      line numeric NULL,
      settlement_profile_id uuid NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT fk_operator_market_canonical_type
        FOREIGN KEY (market_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT,
      CONSTRAINT fk_operator_market_fixture FOREIGN KEY (fixture_id)
        REFERENCES football.fixture(fixture_id) ON DELETE RESTRICT,
      CONSTRAINT fk_operator_market_operator FOREIGN KEY (operator_id)
        REFERENCES betting.betting_operator(operator_id) ON DELETE RESTRICT,
      CONSTRAINT fk_operator_market_definition FOREIGN KEY (market_definition_id)
        REFERENCES betting.market_definition(market_definition_id) ON DELETE RESTRICT,
      CONSTRAINT fk_operator_market_settlement FOREIGN KEY (settlement_profile_id)
        REFERENCES betting.settlement_profile(settlement_profile_id) ON DELETE RESTRICT,
      CONSTRAINT uq_operator_market_scope UNIQUE (market_id, fixture_id, operator_id),
      CONSTRAINT uq_operator_market_operator UNIQUE (market_id, operator_id),
      CONSTRAINT uq_operator_market_identity UNIQUE NULLS NOT DISTINCT
        (fixture_id, operator_id, market_definition_id, period, line, settlement_profile_id),
      CONSTRAINT ck_operator_market_entity_type CHECK (entity_type = 'MARKET'),
      CONSTRAINT ck_operator_market_period CHECK (period = 'FULL_TIME'),
      CONSTRAINT ck_operator_market_no_line CHECK (line IS NULL)
    );

CREATE TABLE betting.market_selection (
      selection_id uuid CONSTRAINT pk_market_selection PRIMARY KEY,
      entity_type varchar(40) NOT NULL DEFAULT 'SELECTION',
      market_id uuid NOT NULL,
      outcome varchar(16) NOT NULL,
      CONSTRAINT fk_market_selection_canonical_type
        FOREIGN KEY (selection_id, entity_type)
        REFERENCES core.canonical_entity(entity_id, entity_type) ON DELETE RESTRICT,
      CONSTRAINT fk_market_selection_market FOREIGN KEY (market_id)
        REFERENCES betting.operator_fixture_market(market_id) ON DELETE RESTRICT,
      CONSTRAINT uq_market_selection_outcome UNIQUE (market_id, outcome),
      CONSTRAINT uq_market_selection_scope UNIQUE (selection_id, market_id),
      CONSTRAINT uq_market_selection_outcome_scope UNIQUE (selection_id, market_id, outcome),
      CONSTRAINT ck_market_selection_entity_type CHECK (entity_type = 'SELECTION'),
      CONSTRAINT ck_market_selection_outcome CHECK (outcome IN ('HOME','DRAW','AWAY'))
    );

CREATE TABLE betting.provider_market_representation (
      provider_market_representation_id uuid
        CONSTRAINT pk_provider_market_representation PRIMARY KEY DEFAULT uuidv7(),
      provider_id uuid NOT NULL,
      event_mapping_id uuid NOT NULL,
      operator_mapping_id uuid NOT NULL,
      market_id uuid NOT NULL,
      provider_market_key varchar(120) NOT NULL,
      representation_version varchar(40) NOT NULL,
      mapping_plan_sha256 char(64) NOT NULL,
      CONSTRAINT fk_provider_market_representation_provider_id
        FOREIGN KEY (provider_id) REFERENCES provenance.data_provider(provider_id)
        ON DELETE RESTRICT,
      CONSTRAINT fk_provider_market_representation_event_mapping_id
        FOREIGN KEY (event_mapping_id) REFERENCES core.external_identifier(external_identifier_id)
        ON DELETE RESTRICT,
      CONSTRAINT fk_provider_market_representation_operator_mapping_id
        FOREIGN KEY (operator_mapping_id) REFERENCES core.external_identifier(external_identifier_id)
        ON DELETE RESTRICT,
      CONSTRAINT fk_provider_market_representation_market_id
        FOREIGN KEY (market_id) REFERENCES betting.operator_fixture_market(market_id)
        ON DELETE RESTRICT,
      CONSTRAINT uq_provider_market_representation UNIQUE
        (provider_id, event_mapping_id, operator_mapping_id, provider_market_key,
         representation_version),
      CONSTRAINT ck_provider_market_key CHECK (provider_market_key = 'h2h'),
      CONSTRAINT ck_provider_market_mapping_hash CHECK
        (mapping_plan_sha256 ~ '^[0-9a-f]{64}$')
    );

CREATE TABLE betting.operator_market_observation (
      book_observation_id uuid CONSTRAINT pk_operator_market_observation
        PRIMARY KEY DEFAULT uuidv7(),
      market_id uuid NOT NULL,
      source_snapshot_id uuid NOT NULL,
      provider_market_representation_id uuid NOT NULL,
      market_state varchar(24) NOT NULL,
      provider_observed_at timestamptz NOT NULL,
      received_at timestamptz NOT NULL,
      usable_at timestamptz NOT NULL,
      missing_outcomes jsonb NOT NULL DEFAULT '[]'::jsonb,
      semantic_sha256 char(64) NOT NULL,
      source_semantic_sha256 char(64) NOT NULL,
      contract_version varchar(48) NOT NULL,
      rights_profile_record_id uuid NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT fk_operator_market_observation_market_id FOREIGN KEY (market_id)
        REFERENCES betting.operator_fixture_market(market_id) ON DELETE RESTRICT,
      CONSTRAINT fk_operator_market_observation_source_snapshot_id
        FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT fk_book_observation_provider_rep
        FOREIGN KEY (provider_market_representation_id)
        REFERENCES betting.provider_market_representation(provider_market_representation_id)
        ON DELETE RESTRICT,
      CONSTRAINT fk_operator_market_observation_rights_profile_record_id
        FOREIGN KEY (rights_profile_record_id)
        REFERENCES provenance.rights_profile(rights_profile_record_id) ON DELETE RESTRICT,
      CONSTRAINT fk_book_observation_snapshot_rights
        FOREIGN KEY (source_snapshot_id, rights_profile_record_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id, rights_profile_record_id)
        ON DELETE RESTRICT,
      CONSTRAINT uq_book_observation_source_market UNIQUE (source_snapshot_id, market_id),
      CONSTRAINT uq_book_observation_scope UNIQUE
        (book_observation_id, source_snapshot_id, market_id),
      CONSTRAINT ck_book_observation_state CHECK
        (market_state IN ('COMPLETE','INCOMPLETE','SUSPENDED','UNSUPPORTED','UNAVAILABLE')),
      CONSTRAINT ck_book_observation_time_order CHECK
        (provider_observed_at <= received_at AND received_at <= usable_at),
      CONSTRAINT ck_book_missing_outcomes CHECK (jsonb_typeof(missing_outcomes) = 'array'),
      CONSTRAINT ck_book_semantic_hash CHECK (semantic_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_book_source_semantic_hash CHECK
        (source_semantic_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_book_contract_version CHECK
        (contract_version = 'the-odds-api-v4-reference-v1')
    );

CREATE TABLE betting.odds_observation (
      odds_observation_id uuid CONSTRAINT pk_odds_observation PRIMARY KEY DEFAULT uuidv7(),
      book_observation_id uuid NOT NULL,
      source_snapshot_id uuid NOT NULL,
      fixture_id uuid NOT NULL,
      market_id uuid NOT NULL,
      selection_id uuid NOT NULL,
      operator_id uuid NOT NULL,
      outcome varchar(16) NOT NULL,
      decimal_odds numeric NOT NULL,
      observed_at timestamptz NOT NULL,
      received_at timestamptz NOT NULL,
      usable_at timestamptz NOT NULL,
      source_semantic_sha256 char(64) NOT NULL,
      contract_version varchar(48) NOT NULL,
      rights_profile_record_id uuid NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT fk_odds_observation_fixture_id FOREIGN KEY (fixture_id)
        REFERENCES football.fixture(fixture_id) ON DELETE RESTRICT,
      CONSTRAINT fk_odds_observation_operator_id FOREIGN KEY (operator_id)
        REFERENCES betting.betting_operator(operator_id) ON DELETE RESTRICT,
      CONSTRAINT fk_odds_observation_rights_profile_record_id
        FOREIGN KEY (rights_profile_record_id)
        REFERENCES provenance.rights_profile(rights_profile_record_id) ON DELETE RESTRICT,
      CONSTRAINT fk_odds_observation_book_scope
        FOREIGN KEY (book_observation_id, source_snapshot_id, market_id)
        REFERENCES betting.operator_market_observation
          (book_observation_id, source_snapshot_id, market_id) ON DELETE RESTRICT,
      CONSTRAINT fk_odds_observation_selection_scope
        FOREIGN KEY (selection_id, market_id)
        REFERENCES betting.market_selection(selection_id, market_id) ON DELETE RESTRICT,
      CONSTRAINT fk_odds_observation_selection_outcome
        FOREIGN KEY (selection_id, market_id, outcome)
        REFERENCES betting.market_selection(selection_id, market_id, outcome) ON DELETE RESTRICT,
      CONSTRAINT fk_odds_observation_market_scope
        FOREIGN KEY (market_id, fixture_id, operator_id)
        REFERENCES betting.operator_fixture_market(market_id, fixture_id, operator_id)
        ON DELETE RESTRICT,
      CONSTRAINT fk_odds_observation_snapshot_rights
        FOREIGN KEY (source_snapshot_id, rights_profile_record_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id, rights_profile_record_id)
        ON DELETE RESTRICT,
      CONSTRAINT uq_odds_observation_source_effect
        UNIQUE (source_snapshot_id, market_id, selection_id),
      CONSTRAINT ck_odds_observation_outcome CHECK (outcome IN ('HOME','DRAW','AWAY')),
      CONSTRAINT ck_odds_observation_price CHECK
        (decimal_odds > 1 AND decimal_odds <> 'NaN'::numeric
         AND decimal_odds <> 'Infinity'::numeric AND decimal_odds <> '-Infinity'::numeric),
      CONSTRAINT ck_odds_observation_time_order CHECK
        (observed_at <= received_at AND received_at <= usable_at),
      CONSTRAINT ck_odds_observation_source_hash CHECK
        (source_semantic_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_odds_observation_contract_version CHECK
        (contract_version = 'the-odds-api-v4-reference-v1')
    );

CREATE TABLE betting.provider_quota_observation (
      quota_observation_id uuid CONSTRAINT pk_provider_quota_observation
        PRIMARY KEY DEFAULT uuidv7(),
      source_snapshot_id uuid NOT NULL,
      provider_id uuid NOT NULL,
      remaining integer NOT NULL,
      used integer NOT NULL,
      last_cost integer NOT NULL,
      observed_at timestamptz NOT NULL,
      source varchar(32) NOT NULL,
      request_fingerprint char(64) NOT NULL,
      CONSTRAINT fk_provider_quota_observation_source_snapshot_id
        FOREIGN KEY (source_snapshot_id)
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT fk_provider_quota_observation_provider_id FOREIGN KEY (provider_id)
        REFERENCES provenance.data_provider(provider_id) ON DELETE RESTRICT,
      CONSTRAINT uq_quota_observation_snapshot UNIQUE (source_snapshot_id),
      CONSTRAINT ck_quota_observation_values CHECK
        (remaining >= 0 AND used >= 0 AND last_cost >= 0 AND last_cost <= used),
      CONSTRAINT ck_quota_observation_source CHECK
        (source IN ('RESPONSE_HEADERS','SYNTHETIC_FIXTURE')),
      CONSTRAINT ck_quota_observation_request_hash CHECK
        (request_fingerprint ~ '^[0-9a-f]{64}$')
    );

CREATE INDEX ix_operator_market_fixture ON betting.operator_fixture_market (fixture_id);

CREATE INDEX ix_operator_market_operator ON betting.operator_fixture_market (operator_id);

CREATE INDEX ix_market_selection_market ON betting.market_selection (market_id);

CREATE INDEX ix_provider_market_market ON betting.provider_market_representation (market_id);

CREATE INDEX ix_book_observation_market_usable ON betting.operator_market_observation (market_id, usable_at);

CREATE INDEX ix_book_observation_snapshot ON betting.operator_market_observation (source_snapshot_id);

CREATE INDEX ix_odds_observation_fixture_usable ON betting.odds_observation (fixture_id, usable_at);

CREATE INDEX ix_odds_observation_book ON betting.odds_observation (book_observation_id);

CREATE INDEX ix_quota_observation_provider ON betting.provider_quota_observation (provider_id, observed_at);

CREATE FUNCTION betting.guard_provider_market_representation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
      coherent_count integer;
    BEGIN
      SELECT count(*) INTO coherent_count
      FROM core.external_identifier AS event_mapping
      JOIN core.external_identifier AS operator_mapping ON true
      JOIN betting.operator_fixture_market AS market
        ON market.market_id = NEW.market_id
      WHERE event_mapping.external_identifier_id = NEW.event_mapping_id
        AND operator_mapping.external_identifier_id = NEW.operator_mapping_id
        AND event_mapping.provider_id = NEW.provider_id
        AND operator_mapping.provider_id = NEW.provider_id
        AND event_mapping.identifier_namespace = 'the_odds_api.event.id'
        AND operator_mapping.identifier_namespace = 'the_odds_api.bookmaker.key'
        AND event_mapping.entity_type = 'FIXTURE'
        AND operator_mapping.entity_type = 'BETTING_OPERATOR'
        AND event_mapping.canonical_entity_id = market.fixture_id
        AND operator_mapping.canonical_entity_id = market.operator_id
        AND event_mapping.mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED')
        AND operator_mapping.mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED')
        AND upper_inf(event_mapping.system_during)
        AND upper_inf(operator_mapping.system_during);
      IF coherent_count <> 1 THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_REPRESENTATION_MAPPING_INVALID';
      END IF;
      RETURN NEW;
    END
    $$;

CREATE TRIGGER trg_provider_market_representation_guard
    BEFORE INSERT ON betting.provider_market_representation
    FOR EACH ROW EXECUTE FUNCTION betting.guard_provider_market_representation();

CREATE FUNCTION betting.guard_odds_quality_subject()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      IF NEW.source_snapshot_id IS NOT NULL
         AND NEW.status IN ('OPEN','ACKNOWLEDGED')
         AND NEW.severity IN ('P0','P1') THEN
        PERFORM pg_advisory_xact_lock(
          hashtextextended('bundle-quality:' || NEW.source_snapshot_id::text, 0)
        );
        IF EXISTS (
          SELECT 1 FROM betting.operator_market_observation AS book
          WHERE book.source_snapshot_id = NEW.source_snapshot_id
        ) THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_QUALITY_ALREADY_PUBLISHED';
        END IF;
      END IF;
      RETURN NEW;
    END
    $$;

CREATE TRIGGER trg_data_quality_odds_guard
    BEFORE INSERT OR UPDATE ON core.data_quality_issue
    FOR EACH ROW EXECUTE FUNCTION betting.guard_odds_quality_subject();

CREATE FUNCTION betting.guard_operator_book_observation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
      snapshot_record record;
      representation_record record;
    BEGIN
      PERFORM pg_advisory_xact_lock(
        hashtextextended('bundle-quality:' || NEW.source_snapshot_id::text, 0)
      );
      SELECT snapshot.rights_profile_record_id, lifecycle.current_state,
             lifecycle.usable_at, profile.status, profile.capabilities,
             profile.provider_key AS profile_provider_key,
             provider.provider_key AS snapshot_provider_key
      INTO snapshot_record
      FROM provenance.source_snapshot AS snapshot
      JOIN provenance.source_snapshot_lifecycle AS lifecycle
        ON lifecycle.source_snapshot_id = snapshot.source_snapshot_id
      JOIN provenance.rights_profile AS profile
        ON profile.rights_profile_record_id = snapshot.rights_profile_record_id
      JOIN provenance.data_provider AS provider
        ON provider.provider_id = snapshot.provider_id
      WHERE snapshot.source_snapshot_id = NEW.source_snapshot_id;
      SELECT representation.market_id,
             representation_provider.provider_key AS representation_provider_key,
             snapshot_provider.provider_key AS snapshot_provider_key
      INTO representation_record
      FROM betting.provider_market_representation AS representation
      JOIN provenance.data_provider AS representation_provider
        ON representation_provider.provider_id = representation.provider_id
      JOIN provenance.source_snapshot AS snapshot
        ON snapshot.source_snapshot_id = NEW.source_snapshot_id
      JOIN provenance.data_provider AS snapshot_provider
        ON snapshot_provider.provider_id = snapshot.provider_id
      WHERE representation.provider_market_representation_id =
            NEW.provider_market_representation_id;
      IF snapshot_record IS NULL
         OR snapshot_record.rights_profile_record_id
              IS DISTINCT FROM NEW.rights_profile_record_id
         OR snapshot_record.current_state IS DISTINCT FROM 'USABLE'
         OR snapshot_record.usable_at IS DISTINCT FROM NEW.usable_at
         OR snapshot_record.status IS DISTINCT FROM 'HUMAN_APPROVED'
         OR snapshot_record.capabilities ->> 'derived_storage' IS DISTINCT FROM 'ALLOW'
         OR snapshot_record.capabilities ->> 'private_internal_use' IS DISTINCT FROM 'ALLOW'
         OR snapshot_record.profile_provider_key
              IS DISTINCT FROM snapshot_record.snapshot_provider_key
         OR representation_record.market_id IS DISTINCT FROM NEW.market_id
         OR NOT (
              representation_record.representation_provider_key = 'the_odds_api'
              AND representation_record.snapshot_provider_key IN
                    ('the_odds_api','synthetic_the_odds_api')
            )
         OR EXISTS (
              SELECT 1 FROM core.data_quality_issue AS issue
              WHERE issue.source_snapshot_id = NEW.source_snapshot_id
                AND issue.status IN ('OPEN','ACKNOWLEDGED')
                AND issue.severity IN ('P0','P1')
            )
         OR EXISTS (
              SELECT 1
              FROM (VALUES ('derived_storage'), ('private_internal_use'))
                   AS required(capability)
              WHERE NOT EXISTS (
                      SELECT 1 FROM provenance.rights_decision AS decision
                      WHERE decision.source_snapshot_id = NEW.source_snapshot_id
                        AND decision.rights_profile_record_id = NEW.rights_profile_record_id
                        AND decision.capability = required.capability
                        AND decision.decision = 'ALLOW'
                    )
                 OR EXISTS (
                      SELECT 1 FROM provenance.rights_decision AS decision
                      WHERE decision.source_snapshot_id = NEW.source_snapshot_id
                        AND decision.rights_profile_record_id = NEW.rights_profile_record_id
                        AND decision.capability = required.capability
                        AND decision.decision <> 'ALLOW'
                    )
            ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_PUBLICATION_BLOCKED';
      END IF;
      RETURN NEW;
    END
    $$;

CREATE TRIGGER trg_operator_book_observation_guard
    BEFORE INSERT ON betting.operator_market_observation
    FOR EACH ROW EXECUTE FUNCTION betting.guard_operator_book_observation();

CREATE FUNCTION betting.guard_odds_observation_coherence()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
      book_record record;
      market_record record;
    BEGIN
      SELECT * INTO book_record
      FROM betting.operator_market_observation
      WHERE book_observation_id = NEW.book_observation_id;
      SELECT * INTO market_record
      FROM betting.operator_fixture_market
      WHERE market_id = NEW.market_id;
      IF book_record IS NULL OR market_record IS NULL
         OR book_record.source_snapshot_id IS DISTINCT FROM NEW.source_snapshot_id
         OR book_record.market_id IS DISTINCT FROM NEW.market_id
         OR book_record.provider_observed_at IS DISTINCT FROM NEW.observed_at
         OR book_record.received_at IS DISTINCT FROM NEW.received_at
         OR book_record.usable_at IS DISTINCT FROM NEW.usable_at
         OR book_record.source_semantic_sha256 IS DISTINCT FROM NEW.source_semantic_sha256
         OR book_record.contract_version IS DISTINCT FROM NEW.contract_version
         OR book_record.rights_profile_record_id
              IS DISTINCT FROM NEW.rights_profile_record_id
         OR market_record.fixture_id IS DISTINCT FROM NEW.fixture_id
         OR market_record.operator_id IS DISTINCT FROM NEW.operator_id THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_QUOTE_BOOK_MISMATCH';
      END IF;
      RETURN NEW;
    END
    $$;

CREATE TRIGGER trg_odds_observation_coherence
    BEFORE INSERT ON betting.odds_observation
    FOR EACH ROW EXECUTE FUNCTION betting.guard_odds_observation_coherence();

CREATE FUNCTION betting.guard_quota_provider()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM provenance.source_snapshot AS snapshot
        WHERE snapshot.source_snapshot_id = NEW.source_snapshot_id
          AND snapshot.provider_id = NEW.provider_id
      ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_QUOTA_PROVIDER_MISMATCH';
      END IF;
      RETURN NEW;
    END
    $$;

CREATE TRIGGER trg_provider_quota_observation_guard
    BEFORE INSERT ON betting.provider_quota_observation
    FOR EACH ROW EXECUTE FUNCTION betting.guard_quota_provider();

CREATE FUNCTION betting.guard_book_completeness()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
      target_book_id uuid;
      book_record record;
      quote_count integer;
      distinct_count integer;
      missing_count integer;
    BEGIN
      target_book_id := CASE WHEN TG_TABLE_NAME = 'odds_observation'
        THEN NEW.book_observation_id ELSE NEW.book_observation_id END;
      SELECT * INTO book_record FROM betting.operator_market_observation
      WHERE book_observation_id = target_book_id;
      SELECT count(*), count(DISTINCT outcome) INTO quote_count, distinct_count
      FROM betting.odds_observation WHERE book_observation_id = target_book_id;
      missing_count := jsonb_array_length(book_record.missing_outcomes);
      IF book_record.market_state = 'COMPLETE' THEN
        IF quote_count <> 3 OR distinct_count <> 3 OR missing_count <> 0
           OR NOT EXISTS (SELECT 1 FROM betting.odds_observation
                          WHERE book_observation_id = target_book_id AND outcome = 'HOME')
           OR NOT EXISTS (SELECT 1 FROM betting.odds_observation
                          WHERE book_observation_id = target_book_id AND outcome = 'DRAW')
           OR NOT EXISTS (SELECT 1 FROM betting.odds_observation
                          WHERE book_observation_id = target_book_id AND outcome = 'AWAY') THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_BOOK_INCOMPLETE';
        END IF;
      ELSIF book_record.market_state = 'INCOMPLETE' THEN
        IF quote_count NOT BETWEEN 1 AND 2 OR distinct_count <> quote_count
           OR missing_count <> 3 - quote_count
           OR EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(book_record.missing_outcomes) AS missing(value)
                WHERE missing.value NOT IN ('HOME','DRAW','AWAY')
                   OR EXISTS (SELECT 1 FROM betting.odds_observation
                              WHERE book_observation_id = target_book_id
                                AND outcome = missing.value)
              )
           OR (SELECT count(DISTINCT value)
               FROM jsonb_array_elements_text(book_record.missing_outcomes)) <> missing_count THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_BOOK_STATE_INVALID';
        END IF;
      ELSIF book_record.market_state = 'UNAVAILABLE' THEN
        IF quote_count <> 0 OR missing_count <> 3
           OR (SELECT count(DISTINCT value)
               FROM jsonb_array_elements_text(book_record.missing_outcomes)) <> 3
           OR EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(book_record.missing_outcomes) AS missing(value)
                WHERE missing.value NOT IN ('HOME','DRAW','AWAY')
              ) THEN
          RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_BOOK_STATE_INVALID';
        END IF;
      ELSIF quote_count <> 0 OR missing_count <> 0 THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_BOOK_STATE_INVALID';
      END IF;
      RETURN NEW;
    END
    $$;

CREATE CONSTRAINT TRIGGER trg_operator_book_completeness
    AFTER INSERT ON betting.operator_market_observation
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION betting.guard_book_completeness();

CREATE CONSTRAINT TRIGGER trg_odds_observation_completeness
    AFTER INSERT ON betting.odds_observation
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION betting.guard_book_completeness();

CREATE TRIGGER trg_provider_market_representation_immutable
    BEFORE UPDATE OR DELETE ON betting.provider_market_representation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_betting_operator_immutable
    BEFORE UPDATE OR DELETE ON betting.betting_operator
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_market_definition_immutable
    BEFORE UPDATE OR DELETE ON betting.market_definition
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_settlement_profile_immutable
    BEFORE UPDATE OR DELETE ON betting.settlement_profile
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_operator_fixture_market_immutable
    BEFORE UPDATE OR DELETE ON betting.operator_fixture_market
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_market_selection_immutable
    BEFORE UPDATE OR DELETE ON betting.market_selection
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_operator_market_observation_immutable
    BEFORE UPDATE OR DELETE ON betting.operator_market_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_odds_observation_immutable
    BEFORE UPDATE OR DELETE ON betting.odds_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

CREATE TRIGGER trg_provider_quota_observation_immutable
    BEFORE UPDATE OR DELETE ON betting.provider_quota_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change();

UPDATE public.alembic_version SET version_num='20260725_0004' WHERE public.alembic_version.version_num = '20260725_0003';

-- Running upgrade 20260725_0004 -> 20260803_0005

ALTER TABLE provenance.source_processing_event
      ADD CONSTRAINT uq_processing_event_snapshot_scope
      UNIQUE (processing_event_id, source_snapshot_id);

ALTER TABLE betting.provider_market_representation
      ADD CONSTRAINT uq_provider_market_representation_plan
      UNIQUE (provider_market_representation_id, mapping_plan_sha256);

CREATE TABLE betting.odds_publication_batch (
      publication_batch_id uuid PRIMARY KEY DEFAULT uuidv7(),
      source_snapshot_id uuid NOT NULL
        REFERENCES provenance.source_snapshot(source_snapshot_id) ON DELETE RESTRICT,
      activation_event_id uuid NOT NULL,
      mapping_cutoff timestamptz NOT NULL,
      mapping_plan_id varchar(160) NOT NULL,
      mapping_plan_sha256 char(64) NOT NULL,
      mapping_plan_approved_at timestamptz NOT NULL,
      mapping_evidence_class varchar(24) NOT NULL,
      mapping_reviewer varchar(160) NOT NULL,
      mapping_status varchar(40) NOT NULL,
      activation_xid bigint NOT NULL DEFAULT ((pg_current_xact_id()::text)::bigint),
      activated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT fk_odds_publication_batch_activation
        FOREIGN KEY (activation_event_id, source_snapshot_id)
        REFERENCES provenance.source_processing_event(processing_event_id, source_snapshot_id)
        ON DELETE RESTRICT,
      CONSTRAINT uq_odds_publication_batch_snapshot UNIQUE (source_snapshot_id),
      CONSTRAINT uq_odds_publication_batch_event UNIQUE (activation_event_id),
      CONSTRAINT uq_odds_publication_batch_scope
        UNIQUE (publication_batch_id, source_snapshot_id),
      CONSTRAINT uq_odds_publication_batch_plan
        UNIQUE (publication_batch_id, mapping_plan_sha256),
      CONSTRAINT ck_odds_publication_batch_mapping_hash
        CHECK (mapping_plan_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_odds_publication_batch_evidence_class
        CHECK (mapping_evidence_class IN ('TEST_ONLY','OFFICIAL','APPROVED_MANUAL')),
      CONSTRAINT ck_odds_publication_batch_mapping_status
        CHECK (mapping_status IN ('APPROVED_FOR_TEST','APPROVED')),
      CONSTRAINT ck_odds_publication_batch_approval_cutoff
        CHECK (mapping_plan_approved_at <= mapping_cutoff)
    );

CREATE TABLE betting.odds_publication_attestation (
      publication_batch_id uuid PRIMARY KEY
        REFERENCES betting.odds_publication_batch(publication_batch_id) ON DELETE RESTRICT,
      usable_at timestamptz NOT NULL,
      attestation_xid bigint NOT NULL DEFAULT ((pg_current_xact_id()::text)::bigint),
      recorded_at timestamptz NOT NULL DEFAULT transaction_timestamp()
    );

CREATE INDEX ix_odds_publication_attestation_usable
      ON betting.odds_publication_attestation(usable_at, publication_batch_id);

ALTER TABLE betting.operator_market_observation
      ADD COLUMN publication_batch_id uuid,
      ALTER COLUMN usable_at DROP NOT NULL,
      DROP CONSTRAINT ck_book_observation_time_order,
      ADD CONSTRAINT fk_book_observation_publication_batch
        FOREIGN KEY (publication_batch_id, source_snapshot_id)
        REFERENCES betting.odds_publication_batch(publication_batch_id, source_snapshot_id)
        ON DELETE RESTRICT,
      ADD CONSTRAINT uq_book_observation_representation_batch
        UNIQUE (provider_market_representation_id, publication_batch_id),
      ADD CONSTRAINT uq_book_observation_snapshot_scope
        UNIQUE (book_observation_id, source_snapshot_id),
      ADD CONSTRAINT ck_book_observation_time_order CHECK (
        provider_observed_at <= received_at AND
        ((publication_batch_id IS NULL AND usable_at IS NOT NULL AND received_at <= usable_at)
         OR (publication_batch_id IS NOT NULL AND usable_at IS NULL))
      );

CREATE INDEX ix_book_observation_batch
      ON betting.operator_market_observation(publication_batch_id);

ALTER TABLE betting.odds_observation
      ADD COLUMN publication_batch_id uuid,
      ALTER COLUMN usable_at DROP NOT NULL,
      DROP CONSTRAINT ck_odds_observation_time_order,
      ADD CONSTRAINT fk_odds_observation_publication_batch
        FOREIGN KEY (publication_batch_id, source_snapshot_id)
        REFERENCES betting.odds_publication_batch(publication_batch_id, source_snapshot_id)
        ON DELETE RESTRICT,
      ADD CONSTRAINT ck_odds_observation_time_order CHECK (
        observed_at <= received_at AND
        ((publication_batch_id IS NULL AND usable_at IS NOT NULL AND received_at <= usable_at)
         OR (publication_batch_id IS NOT NULL AND usable_at IS NULL))
      ),
      ADD CONSTRAINT uq_odds_observation_snapshot_scope
        UNIQUE (odds_observation_id, source_snapshot_id),
      ADD CONSTRAINT uq_odds_observation_snapshot_fixture_scope
        UNIQUE (odds_observation_id, source_snapshot_id, fixture_id);

CREATE FUNCTION betting.guard_odds_publication_batch()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE event_record record; snapshot_provider text;
    BEGIN
      SELECT stage, source_snapshot_id, event_at INTO event_record
      FROM provenance.source_processing_event
      WHERE processing_event_id = NEW.activation_event_id;
      SELECT provider.provider_key INTO snapshot_provider
      FROM provenance.source_snapshot AS snapshot
      JOIN provenance.data_provider AS provider ON provider.provider_id = snapshot.provider_id
      WHERE snapshot.source_snapshot_id = NEW.source_snapshot_id;
      IF event_record IS NULL OR event_record.stage IS DISTINCT FROM 'USABLE'
         OR event_record.source_snapshot_id IS DISTINCT FROM NEW.source_snapshot_id
         OR NEW.activation_xid IS DISTINCT FROM
              ((pg_current_xact_id()::text)::bigint)
         OR NEW.activated_at IS DISTINCT FROM transaction_timestamp()
         OR (snapshot_provider = 'synthetic_the_odds_api'
             AND (NEW.mapping_evidence_class <> 'TEST_ONLY'
                  OR NEW.mapping_status <> 'APPROVED_FOR_TEST'))
         OR (snapshot_provider <> 'synthetic_the_odds_api'
             AND NEW.mapping_evidence_class = 'TEST_ONLY') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_PUBLICATION_BATCH_INVALID';
      END IF;
      RETURN NEW;
    END $$;

CREATE TRIGGER trg_odds_publication_batch_guard
      BEFORE INSERT ON betting.odds_publication_batch
      FOR EACH ROW EXECUTE FUNCTION betting.guard_odds_publication_batch();

CREATE FUNCTION betting.guard_odds_publication_attestation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE batch_record record; received_time timestamptz; activation_event_time timestamptz;
    BEGIN
      SELECT activation_xid, source_snapshot_id, activation_event_id INTO batch_record
      FROM betting.odds_publication_batch
      WHERE publication_batch_id = NEW.publication_batch_id;
      SELECT received_at INTO received_time
      FROM provenance.source_snapshot
      WHERE source_snapshot_id = batch_record.source_snapshot_id;
      SELECT event_at INTO activation_event_time
      FROM provenance.source_processing_event
      WHERE processing_event_id = batch_record.activation_event_id;
      IF batch_record IS NULL OR NEW.attestation_xid = batch_record.activation_xid
         OR NEW.attestation_xid IS DISTINCT FROM
              ((pg_current_xact_id()::text)::bigint)
         OR NEW.recorded_at IS DISTINCT FROM transaction_timestamp()
         OR received_time IS NULL OR NEW.usable_at < received_time
         OR activation_event_time IS NULL OR NEW.usable_at < activation_event_time THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_ATTESTATION_INVALID';
      END IF;
      RETURN NEW;
    END $$;

CREATE TRIGGER trg_odds_publication_attestation_guard
      BEFORE INSERT ON betting.odds_publication_attestation
      FOR EACH ROW EXECUTE FUNCTION betting.guard_odds_publication_attestation();

CREATE OR REPLACE FUNCTION betting.guard_odds_quality_subject()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE affected_snapshot_id uuid;
    BEGIN
      IF NEW.status IN ('OPEN','ACKNOWLEDGED')
         AND NEW.severity IN ('P0','P1') THEN
        FOR affected_snapshot_id IN
          SELECT affected.source_snapshot_id
          FROM (
            SELECT DISTINCT candidate.source_snapshot_id
            FROM (
              SELECT NEW.source_snapshot_id
              WHERE NEW.source_snapshot_id IS NOT NULL
              UNION ALL
              SELECT snapshot.source_snapshot_id
              FROM provenance.source_snapshot AS snapshot
              WHERE NEW.ingestion_run_id IS NOT NULL
                AND snapshot.ingestion_run_id = NEW.ingestion_run_id
              UNION ALL
              SELECT book.source_snapshot_id
              FROM betting.operator_market_observation AS book
              JOIN betting.operator_fixture_market AS market
                ON market.market_id = book.market_id
              WHERE NEW.canonical_entity_id IS NOT NULL
                AND market.fixture_id = NEW.canonical_entity_id
            ) AS candidate
            WHERE candidate.source_snapshot_id IS NOT NULL
          ) AS affected
          ORDER BY affected.source_snapshot_id::text
        LOOP
          PERFORM pg_advisory_xact_lock(
            hashtextextended('bundle-quality:' || affected_snapshot_id::text, 0)
          );
        END LOOP;
      END IF;
      RETURN NEW;
    END $$;

CREATE FUNCTION betting.reject_immutable_change()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'IMMUTABLE_MARKET_RECORD';
    END $$;

CREATE TRIGGER trg_odds_publication_batch_immutable
      BEFORE UPDATE OR DELETE ON betting.odds_publication_batch
      FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_odds_publication_attestation_immutable
      BEFORE UPDATE OR DELETE ON betting.odds_publication_attestation
      FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE OR REPLACE FUNCTION betting.guard_operator_book_observation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE snapshot_record record; representation_record record; batch_record record;
    BEGIN
      PERFORM pg_advisory_xact_lock(
        hashtextextended('bundle-quality:' || NEW.source_snapshot_id::text, 0)
      );
      SELECT snapshot.rights_profile_record_id, lifecycle.current_state,
             profile.status, profile.capabilities,
             profile.provider_key AS profile_provider_key,
             provider.provider_key AS snapshot_provider_key
      INTO snapshot_record
      FROM provenance.source_snapshot AS snapshot
      JOIN provenance.source_snapshot_lifecycle AS lifecycle
        ON lifecycle.source_snapshot_id = snapshot.source_snapshot_id
      JOIN provenance.rights_profile AS profile
        ON profile.rights_profile_record_id = snapshot.rights_profile_record_id
      JOIN provenance.data_provider AS provider ON provider.provider_id = snapshot.provider_id
      WHERE snapshot.source_snapshot_id = NEW.source_snapshot_id;
      SELECT representation.market_id,
             representation_provider.provider_key AS representation_provider_key,
             snapshot_provider.provider_key AS snapshot_provider_key
      INTO representation_record
      FROM betting.provider_market_representation AS representation
      JOIN provenance.data_provider AS representation_provider
        ON representation_provider.provider_id = representation.provider_id
      JOIN provenance.source_snapshot AS snapshot
        ON snapshot.source_snapshot_id = NEW.source_snapshot_id
      JOIN provenance.data_provider AS snapshot_provider
        ON snapshot_provider.provider_id = snapshot.provider_id
      WHERE representation.provider_market_representation_id =
            NEW.provider_market_representation_id;
      SELECT source_snapshot_id INTO batch_record
      FROM betting.odds_publication_batch
      WHERE publication_batch_id = NEW.publication_batch_id;
      IF NEW.publication_batch_id IS NULL OR NEW.usable_at IS NOT NULL
         OR batch_record.source_snapshot_id IS DISTINCT FROM NEW.source_snapshot_id
         OR snapshot_record IS NULL
         OR snapshot_record.rights_profile_record_id IS DISTINCT FROM NEW.rights_profile_record_id
         OR snapshot_record.current_state IS DISTINCT FROM 'USABLE'
         OR snapshot_record.status IS DISTINCT FROM 'HUMAN_APPROVED'
         OR snapshot_record.capabilities ->> 'derived_storage' IS DISTINCT FROM 'ALLOW'
         OR snapshot_record.capabilities ->> 'private_internal_use' IS DISTINCT FROM 'ALLOW'
         OR snapshot_record.profile_provider_key IS DISTINCT FROM snapshot_record.snapshot_provider_key
         OR representation_record.market_id IS DISTINCT FROM NEW.market_id
         OR NOT (representation_record.representation_provider_key = 'the_odds_api'
                 AND representation_record.snapshot_provider_key IN
                     ('the_odds_api','synthetic_the_odds_api'))
         OR EXISTS (
              SELECT 1 FROM core.data_quality_issue AS issue
              WHERE issue.source_snapshot_id = NEW.source_snapshot_id
                AND issue.status IN ('OPEN','ACKNOWLEDGED')
                AND issue.severity IN ('P0','P1')
            )
         OR EXISTS (
              SELECT 1 FROM (VALUES ('derived_storage'), ('private_internal_use')) AS required(capability)
              WHERE NOT EXISTS (
                    SELECT 1 FROM provenance.rights_decision AS decision
                    WHERE decision.source_snapshot_id = NEW.source_snapshot_id
                      AND decision.rights_profile_record_id = NEW.rights_profile_record_id
                      AND decision.capability = required.capability AND decision.decision = 'ALLOW'
                  )
            ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_PUBLICATION_BLOCKED';
      END IF;
      RETURN NEW;
    END $$;

CREATE OR REPLACE FUNCTION betting.guard_odds_observation_coherence()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE book_record record; market_record record;
    BEGIN
      SELECT * INTO book_record FROM betting.operator_market_observation
      WHERE book_observation_id = NEW.book_observation_id;
      SELECT * INTO market_record FROM betting.operator_fixture_market
      WHERE market_id = NEW.market_id;
      IF book_record IS NULL OR market_record IS NULL
         OR NEW.publication_batch_id IS NULL OR NEW.usable_at IS NOT NULL
         OR book_record.publication_batch_id IS DISTINCT FROM NEW.publication_batch_id
         OR book_record.source_snapshot_id IS DISTINCT FROM NEW.source_snapshot_id
         OR book_record.market_id IS DISTINCT FROM NEW.market_id
         OR book_record.provider_observed_at IS DISTINCT FROM NEW.observed_at
         OR book_record.received_at IS DISTINCT FROM NEW.received_at
         OR book_record.usable_at IS DISTINCT FROM NEW.usable_at
         OR book_record.source_semantic_sha256 IS DISTINCT FROM NEW.source_semantic_sha256
         OR book_record.contract_version IS DISTINCT FROM NEW.contract_version
         OR book_record.rights_profile_record_id IS DISTINCT FROM NEW.rights_profile_record_id
         OR market_record.fixture_id IS DISTINCT FROM NEW.fixture_id
         OR market_record.operator_id IS DISTINCT FROM NEW.operator_id THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ODDS_QUOTE_BOOK_MISMATCH';
      END IF;
      RETURN NEW;
    END $$;

CREATE TABLE betting.odds_mapping_dependency (
      provider_market_representation_id uuid NOT NULL,
      publication_batch_id uuid NOT NULL,
      mapping_plan_sha256 char(64) NOT NULL,
      fixture_lookup_mapping_id uuid NOT NULL
        REFERENCES core.external_identifier(external_identifier_id) ON DELETE RESTRICT,
      home_team_mapping_id uuid NOT NULL
        REFERENCES core.external_identifier(external_identifier_id) ON DELETE RESTRICT,
      away_team_mapping_id uuid NOT NULL
        REFERENCES core.external_identifier(external_identifier_id) ON DELETE RESTRICT,
      fixture_observation_id uuid NOT NULL
        REFERENCES fpl.fixture_observation(fixture_observation_id) ON DELETE RESTRICT,
      expected_commence_time timestamptz NOT NULL,
      dependency_sha256 char(64) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      PRIMARY KEY (provider_market_representation_id, publication_batch_id),
      CONSTRAINT fk_odds_mapping_dependency_representation_plan
        FOREIGN KEY (provider_market_representation_id, mapping_plan_sha256)
        REFERENCES betting.provider_market_representation
          (provider_market_representation_id, mapping_plan_sha256)
        ON DELETE RESTRICT,
      CONSTRAINT fk_odds_mapping_dependency_batch_plan
        FOREIGN KEY (publication_batch_id, mapping_plan_sha256)
        REFERENCES betting.odds_publication_batch(publication_batch_id, mapping_plan_sha256)
        ON DELETE RESTRICT,
      CONSTRAINT fk_odds_mapping_dependency_book
        FOREIGN KEY (provider_market_representation_id, publication_batch_id)
        REFERENCES betting.operator_market_observation
          (provider_market_representation_id, publication_batch_id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
      CONSTRAINT ck_odds_mapping_dependency_plan_hash
        CHECK (mapping_plan_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_odds_mapping_dependency_hash
        CHECK (dependency_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_odds_mapping_dependency_distinct_teams
        CHECK (home_team_mapping_id <> away_team_mapping_id)
    );

CREATE FUNCTION betting.guard_odds_mapping_dependency()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE dependency_record record;
    BEGIN
      SELECT representation.mapping_plan_sha256 AS representation_plan_sha256,
             batch.mapping_plan_sha256 AS batch_plan_sha256,
             batch.mapping_cutoff,
             market.fixture_id,
             canonical_fixture.season_id,
             canonical_fixture.home_team_id,
             canonical_fixture.away_team_id,
             event_mapping.canonical_entity_id AS event_fixture_id,
             event_mapping.entity_type AS event_entity_type,
             event_mapping.season_id AS event_season_id,
             event_mapping.mapping_status AS event_mapping_status,
             event_mapping.valid_during AS event_valid_during,
             event_mapping.system_during AS event_system_during,
             fixture_mapping.canonical_entity_id AS lookup_fixture_id,
             fixture_mapping.provider_id AS lookup_provider_id,
             fixture_mapping.entity_type AS fixture_entity_type,
             fixture_mapping.season_id AS fixture_season_id,
             fixture_mapping.mapping_status AS fixture_mapping_status,
             fixture_mapping.valid_during AS fixture_valid_during,
             fixture_mapping.system_during AS fixture_system_during,
             home_mapping.canonical_entity_id AS mapped_home_team_id,
             home_mapping.provider_id AS home_provider_id,
             home_mapping.entity_type AS home_entity_type,
             home_mapping.season_id AS home_season_id,
             home_mapping.mapping_status AS home_mapping_status,
             home_mapping.valid_during AS home_valid_during,
             home_mapping.system_during AS home_system_during,
             away_mapping.canonical_entity_id AS mapped_away_team_id,
             away_mapping.provider_id AS away_provider_id,
             away_mapping.entity_type AS away_entity_type,
             away_mapping.season_id AS away_season_id,
             away_mapping.mapping_status AS away_mapping_status,
             away_mapping.valid_during AS away_valid_during,
             away_mapping.system_during AS away_system_during,
             schedule.fixture_id AS schedule_fixture_id,
             schedule.kickoff_at,
             schedule.usable_at AS schedule_usable_at
      INTO dependency_record
      FROM betting.provider_market_representation AS representation
      JOIN betting.operator_fixture_market AS market
        ON market.market_id = representation.market_id
      JOIN football.fixture AS canonical_fixture
        ON canonical_fixture.fixture_id = market.fixture_id
      JOIN core.external_identifier AS event_mapping
        ON event_mapping.external_identifier_id = representation.event_mapping_id
      JOIN betting.odds_publication_batch AS batch
        ON batch.publication_batch_id = NEW.publication_batch_id
      JOIN core.external_identifier AS fixture_mapping
        ON fixture_mapping.external_identifier_id = NEW.fixture_lookup_mapping_id
      JOIN core.external_identifier AS home_mapping
        ON home_mapping.external_identifier_id = NEW.home_team_mapping_id
      JOIN core.external_identifier AS away_mapping
        ON away_mapping.external_identifier_id = NEW.away_team_mapping_id
      JOIN fpl.fixture_observation AS schedule
        ON schedule.fixture_observation_id = NEW.fixture_observation_id
      WHERE representation.provider_market_representation_id =
            NEW.provider_market_representation_id;
      IF dependency_record IS NULL
         OR dependency_record.representation_plan_sha256 IS DISTINCT FROM
            NEW.mapping_plan_sha256
         OR dependency_record.batch_plan_sha256 IS DISTINCT FROM NEW.mapping_plan_sha256
         OR dependency_record.event_fixture_id IS DISTINCT FROM dependency_record.fixture_id
         OR dependency_record.lookup_fixture_id IS DISTINCT FROM dependency_record.fixture_id
         OR dependency_record.mapped_home_team_id IS DISTINCT FROM
            dependency_record.home_team_id
         OR dependency_record.mapped_away_team_id IS DISTINCT FROM
            dependency_record.away_team_id
         OR dependency_record.event_entity_type IS DISTINCT FROM 'FIXTURE'
         OR dependency_record.fixture_entity_type IS DISTINCT FROM 'FIXTURE'
         OR dependency_record.home_entity_type IS DISTINCT FROM 'TEAM'
         OR dependency_record.away_entity_type IS DISTINCT FROM 'TEAM'
         OR dependency_record.event_season_id IS DISTINCT FROM dependency_record.season_id
         OR dependency_record.fixture_season_id IS DISTINCT FROM dependency_record.season_id
         OR dependency_record.home_season_id IS DISTINCT FROM dependency_record.season_id
         OR dependency_record.away_season_id IS DISTINCT FROM dependency_record.season_id
         OR dependency_record.lookup_provider_id IS DISTINCT FROM
            dependency_record.home_provider_id
         OR dependency_record.lookup_provider_id IS DISTINCT FROM
            dependency_record.away_provider_id
         OR dependency_record.event_mapping_status NOT IN ('AUTO_MATCHED','HUMAN_VERIFIED')
         OR dependency_record.fixture_mapping_status NOT IN ('AUTO_MATCHED','HUMAN_VERIFIED')
         OR dependency_record.home_mapping_status NOT IN ('AUTO_MATCHED','HUMAN_VERIFIED')
         OR dependency_record.away_mapping_status NOT IN ('AUTO_MATCHED','HUMAN_VERIFIED')
         OR NOT (dependency_record.event_valid_during @> NEW.expected_commence_time)
         OR NOT (dependency_record.fixture_valid_during @> NEW.expected_commence_time)
         OR NOT (dependency_record.home_valid_during @> NEW.expected_commence_time)
         OR NOT (dependency_record.away_valid_during @> NEW.expected_commence_time)
         OR NOT (dependency_record.event_system_during @> dependency_record.mapping_cutoff)
         OR NOT (dependency_record.fixture_system_during @> dependency_record.mapping_cutoff)
         OR NOT (dependency_record.home_system_during @> dependency_record.mapping_cutoff)
         OR NOT (dependency_record.away_system_during @> dependency_record.mapping_cutoff)
         OR dependency_record.schedule_fixture_id IS DISTINCT FROM dependency_record.fixture_id
         OR dependency_record.kickoff_at IS DISTINCT FROM NEW.expected_commence_time
         OR dependency_record.schedule_usable_at > dependency_record.mapping_cutoff THEN
        RAISE EXCEPTION USING
          ERRCODE = '23514', MESSAGE = 'ODDS_MAPPING_DEPENDENCY_INVALID';
      END IF;
      RETURN NEW;
    END $$;

CREATE TRIGGER trg_odds_mapping_dependency_guard
      BEFORE INSERT ON betting.odds_mapping_dependency
      FOR EACH ROW EXECUTE FUNCTION betting.guard_odds_mapping_dependency();

CREATE FUNCTION betting.require_odds_mapping_dependency()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.publication_batch_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM betting.odds_mapping_dependency AS dependency
           WHERE dependency.provider_market_representation_id =
                 NEW.provider_market_representation_id
             AND dependency.publication_batch_id = NEW.publication_batch_id
         ) THEN
        RAISE EXCEPTION USING
          ERRCODE = '23514', MESSAGE = 'ODDS_MAPPING_DEPENDENCY_MISSING';
      END IF;
      RETURN NULL;
    END $$;

CREATE CONSTRAINT TRIGGER trg_operator_book_mapping_dependency
      AFTER INSERT ON betting.operator_market_observation
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.require_odds_mapping_dependency();

CREATE TABLE betting.market_normalisation_policy (
      policy_sha256 char(64) PRIMARY KEY,
      policy_id varchar(120) NOT NULL,
      policy_version varchar(40) NOT NULL,
      policy_document jsonb NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT uq_market_normalisation_policy_identity UNIQUE (policy_id, policy_version),
      CONSTRAINT ck_market_normalisation_policy_hash
        CHECK (policy_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_market_normalisation_policy_document
        CHECK (jsonb_typeof(policy_document) = 'object')
    );

CREATE TABLE betting.market_normalisation_run (
      normalisation_run_id uuid PRIMARY KEY DEFAULT uuidv7(),
      fixture_id uuid NOT NULL REFERENCES football.fixture(fixture_id) ON DELETE RESTRICT,
      market_definition varchar(40) NOT NULL,
      as_of timestamptz NOT NULL,
      mapping_cutoff timestamptz NOT NULL,
      policy_sha256 char(64) NOT NULL
        REFERENCES betting.market_normalisation_policy(policy_sha256) ON DELETE RESTRICT,
      code_identity varchar(160) NOT NULL,
      input_signature_sha256 char(64) NOT NULL,
      semantic_result_sha256 char(64) NOT NULL,
      status varchar(24) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      published_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
      CONSTRAINT uq_market_normalisation_run_input_signature_sha256
        UNIQUE (input_signature_sha256),
      CONSTRAINT uq_market_normalisation_run_scope UNIQUE (normalisation_run_id, fixture_id),
      CONSTRAINT ck_market_normalisation_run_definition
        CHECK (market_definition = 'FULL_TIME_1X2'),
      CONSTRAINT ck_market_normalisation_run_input_hash
        CHECK (input_signature_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_market_normalisation_run_result_hash
        CHECK (semantic_result_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_market_normalisation_run_status
        CHECK (status IN ('NORMALISED','DEGRADED','INSUFFICIENT','BLOCKED'))
    );

CREATE TABLE betting.market_normalisation_source (
      normalisation_run_id uuid NOT NULL
        REFERENCES betting.market_normalisation_run(normalisation_run_id) ON DELETE RESTRICT,
      odds_observation_id uuid NOT NULL,
      source_snapshot_id uuid NOT NULL,
      fixture_id uuid NOT NULL,
      PRIMARY KEY (normalisation_run_id, odds_observation_id),
      CONSTRAINT uq_market_normalisation_source_scope
        UNIQUE (normalisation_run_id, odds_observation_id, source_snapshot_id, fixture_id),
      CONSTRAINT fk_market_normalisation_source_observation
        FOREIGN KEY (odds_observation_id, source_snapshot_id)
        REFERENCES betting.odds_observation(odds_observation_id, source_snapshot_id)
        ON DELETE RESTRICT,
      CONSTRAINT fk_market_normalisation_source_run_fixture
        FOREIGN KEY (normalisation_run_id, fixture_id)
        REFERENCES betting.market_normalisation_run(normalisation_run_id, fixture_id)
        ON DELETE RESTRICT,
      CONSTRAINT fk_market_normalisation_source_observation_fixture
        FOREIGN KEY (odds_observation_id, source_snapshot_id, fixture_id)
        REFERENCES betting.odds_observation(odds_observation_id, source_snapshot_id, fixture_id)
        ON DELETE RESTRICT
    );

CREATE FUNCTION betting.guard_normalisation_source_fixture()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE run_fixture_id uuid; observation_fixture_id uuid;
    BEGIN
      SELECT fixture_id INTO run_fixture_id
      FROM betting.market_normalisation_run
      WHERE normalisation_run_id = NEW.normalisation_run_id;
      SELECT fixture_id INTO observation_fixture_id
      FROM betting.odds_observation
      WHERE odds_observation_id = NEW.odds_observation_id
        AND source_snapshot_id = NEW.source_snapshot_id;
      IF run_fixture_id IS NULL OR observation_fixture_id IS NULL
         OR run_fixture_id IS DISTINCT FROM observation_fixture_id THEN
        RAISE EXCEPTION USING
          ERRCODE = '23514', MESSAGE = 'NORMALISATION_SOURCE_FIXTURE_MISMATCH';
      END IF;
      NEW.fixture_id := run_fixture_id;
      RETURN NEW;
    END $$;

CREATE TRIGGER trg_market_normalisation_source_fixture
      BEFORE INSERT ON betting.market_normalisation_source
      FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_source_fixture();

CREATE TABLE betting.market_normalisation_book_source (
      normalisation_run_id uuid NOT NULL,
      book_observation_id uuid NOT NULL,
      source_snapshot_id uuid NOT NULL,
      fixture_id uuid NOT NULL,
      PRIMARY KEY (normalisation_run_id, book_observation_id),
      CONSTRAINT fk_market_normalisation_book_source_book
        FOREIGN KEY (book_observation_id, source_snapshot_id)
        REFERENCES betting.operator_market_observation
          (book_observation_id, source_snapshot_id)
        ON DELETE RESTRICT,
      CONSTRAINT fk_market_normalisation_book_source_run_fixture
        FOREIGN KEY (normalisation_run_id, fixture_id)
        REFERENCES betting.market_normalisation_run(normalisation_run_id, fixture_id)
        ON DELETE RESTRICT
    );

CREATE FUNCTION betting.guard_normalisation_book_source_fixture()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE run_fixture_id uuid; book_fixture_id uuid;
    BEGIN
      SELECT fixture_id INTO run_fixture_id
      FROM betting.market_normalisation_run
      WHERE normalisation_run_id = NEW.normalisation_run_id;
      SELECT market.fixture_id INTO book_fixture_id
      FROM betting.operator_market_observation AS book
      JOIN betting.operator_fixture_market AS market
        ON market.market_id = book.market_id
      WHERE book.book_observation_id = NEW.book_observation_id
        AND book.source_snapshot_id = NEW.source_snapshot_id;
      IF run_fixture_id IS NULL OR book_fixture_id IS NULL
         OR run_fixture_id IS DISTINCT FROM book_fixture_id THEN
        RAISE EXCEPTION USING
          ERRCODE = '23514', MESSAGE = 'NORMALISATION_BOOK_SOURCE_FIXTURE_MISMATCH';
      END IF;
      NEW.fixture_id := run_fixture_id;
      RETURN NEW;
    END $$;

CREATE TRIGGER trg_market_normalisation_book_source_fixture
      BEFORE INSERT ON betting.market_normalisation_book_source
      FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_book_source_fixture();

CREATE TABLE betting.normalised_operator_market (
      normalised_operator_market_id uuid PRIMARY KEY DEFAULT uuidv7(),
      normalisation_run_id uuid NOT NULL
        REFERENCES betting.market_normalisation_run(normalisation_run_id) ON DELETE RESTRICT,
      fixture_id uuid NOT NULL,
      market_id uuid NOT NULL,
      provider_id uuid NOT NULL REFERENCES provenance.data_provider(provider_id) ON DELETE RESTRICT,
      operator_id uuid NOT NULL,
      operator_key varchar(120) NOT NULL,
      observed_at timestamptz NOT NULL,
      usable_at timestamptz NOT NULL,
      primary_method varchar(24) NOT NULL,
      fallback_used boolean NOT NULL,
      raw_booksum numeric(60,50) NOT NULL,
      overround numeric(60,50) NOT NULL,
      power_exponent numeric(60,50),
      input_signature_sha256 char(64) NOT NULL,
      result_sha256 char(64) NOT NULL,
      CONSTRAINT ck_normalised_operator_primary_method
        CHECK (primary_method IN ('POWER','PROPORTIONAL')),
      CONSTRAINT ck_normalised_operator_input_hash
        CHECK (input_signature_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_normalised_operator_result_hash
        CHECK (result_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_normalised_operator_raw_booksum_finite CHECK (
        raw_booksum >= 0 AND raw_booksum <> 'NaN'::numeric
        AND raw_booksum <> 'Infinity'::numeric
        AND raw_booksum <> '-Infinity'::numeric
      ),
      CONSTRAINT ck_normalised_operator_overround_coherence CHECK (
        overround <> 'NaN'::numeric
        AND overround <> 'Infinity'::numeric
        AND overround <> '-Infinity'::numeric
        AND overround = raw_booksum - 1
      ),
      CONSTRAINT ck_normalised_operator_power_state CHECK (
        (fallback_used AND primary_method = 'PROPORTIONAL' AND power_exponent IS NULL)
        OR
        (NOT fallback_used AND primary_method = 'POWER'
         AND power_exponent IS NOT NULL
         AND power_exponent > 0
         AND power_exponent <> 'NaN'::numeric
         AND power_exponent <> 'Infinity'::numeric
         AND power_exponent <> '-Infinity'::numeric)
      ),
      CONSTRAINT fk_normalised_operator_run_fixture
        FOREIGN KEY (normalisation_run_id, fixture_id)
        REFERENCES betting.market_normalisation_run(normalisation_run_id, fixture_id)
        ON DELETE RESTRICT,
      CONSTRAINT fk_normalised_operator_market_scope
        FOREIGN KEY (market_id, fixture_id, operator_id)
        REFERENCES betting.operator_fixture_market(market_id, fixture_id, operator_id)
        ON DELETE RESTRICT,
      CONSTRAINT uq_normalised_operator_run_operator UNIQUE (normalisation_run_id, operator_id),
      CONSTRAINT uq_normalised_operator_scope
        UNIQUE (normalised_operator_market_id, normalisation_run_id)
    );

CREATE TABLE betting.normalised_operator_outcome (
      normalised_operator_market_id uuid NOT NULL,
      normalisation_run_id uuid NOT NULL,
      outcome varchar(16) NOT NULL,
      decimal_odds numeric NOT NULL,
      raw_implied_probability numeric(60,50) NOT NULL,
      proportional_probability numeric(13,12) NOT NULL,
      market_probability numeric(13,12) NOT NULL,
      CONSTRAINT ck_normalised_operator_outcome_name
        CHECK (outcome IN ('HOME','DRAW','AWAY')),
      CONSTRAINT ck_normalised_operator_outcome_decimal_odds_finite CHECK (
        decimal_odds > 1 AND decimal_odds <> 'NaN'::numeric
        AND decimal_odds <> 'Infinity'::numeric
        AND decimal_odds <> '-Infinity'::numeric
      ),
      CONSTRAINT ck_normalised_operator_outcome_raw_probability
        CHECK (raw_implied_probability BETWEEN 0 AND 1),
      CONSTRAINT ck_normalised_operator_outcome_proportional_probability
        CHECK (proportional_probability BETWEEN 0 AND 1),
      CONSTRAINT ck_normalised_operator_outcome_market_probability
        CHECK (market_probability BETWEEN 0 AND 1),
      PRIMARY KEY (normalised_operator_market_id, outcome),
      CONSTRAINT fk_normalised_operator_outcome_scope
        FOREIGN KEY (normalised_operator_market_id, normalisation_run_id)
        REFERENCES betting.normalised_operator_market(normalised_operator_market_id, normalisation_run_id)
        ON DELETE RESTRICT
    );

CREATE TABLE betting.normalised_operator_market_source (
      normalised_operator_market_id uuid NOT NULL,
      normalisation_run_id uuid NOT NULL,
      odds_observation_id uuid NOT NULL,
      source_snapshot_id uuid NOT NULL,
      fixture_id uuid NOT NULL,
      PRIMARY KEY (normalised_operator_market_id, odds_observation_id),
      CONSTRAINT fk_normalised_operator_source_parent
        FOREIGN KEY (normalised_operator_market_id, normalisation_run_id)
        REFERENCES betting.normalised_operator_market
          (normalised_operator_market_id, normalisation_run_id)
        ON DELETE RESTRICT,
      CONSTRAINT fk_normalised_operator_source_run_source
        FOREIGN KEY (
          normalisation_run_id, odds_observation_id, source_snapshot_id, fixture_id
        )
        REFERENCES betting.market_normalisation_source (
          normalisation_run_id, odds_observation_id, source_snapshot_id, fixture_id
        )
        ON DELETE RESTRICT
    );

CREATE TABLE betting.market_consensus_result (
      normalisation_run_id uuid PRIMARY KEY
        REFERENCES betting.market_normalisation_run(normalisation_run_id) ON DELETE RESTRICT,
      provider_count integer NOT NULL,
      operator_count integer NOT NULL,
      eligible_operator_count integer NOT NULL,
      operator_disagreement numeric(13,12) NOT NULL,
      method_disagreement numeric(13,12) NOT NULL,
      market_disagreement numeric(13,12) NOT NULL,
      minimum_age_seconds integer NOT NULL,
      maximum_age_seconds integer NOT NULL,
      confidence_grade char(1) NOT NULL,
      input_signature_sha256 char(64) NOT NULL,
      result_sha256 char(64) NOT NULL,
      CONSTRAINT ck_market_consensus_provider_count CHECK (provider_count >= 1),
      CONSTRAINT ck_market_consensus_operator_count CHECK (operator_count >= 1),
      CONSTRAINT ck_market_consensus_eligible_count CHECK (eligible_operator_count >= 1),
      CONSTRAINT ck_market_consensus_operator_disagreement
        CHECK (operator_disagreement BETWEEN 0 AND 1),
      CONSTRAINT ck_market_consensus_method_disagreement
        CHECK (method_disagreement BETWEEN 0 AND 1),
      CONSTRAINT ck_market_consensus_market_disagreement
        CHECK (market_disagreement BETWEEN 0 AND 1),
      CONSTRAINT ck_market_consensus_disagreement_coherence
        CHECK (market_disagreement = GREATEST(operator_disagreement, method_disagreement)),
      CONSTRAINT ck_market_consensus_minimum_age CHECK (minimum_age_seconds >= 0),
      CONSTRAINT ck_market_consensus_maximum_age
        CHECK (maximum_age_seconds >= minimum_age_seconds),
      CONSTRAINT ck_market_consensus_confidence_grade
        CHECK (confidence_grade IN ('A','B','C','D')),
      CONSTRAINT ck_market_consensus_input_hash
        CHECK (input_signature_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_market_consensus_result_hash
        CHECK (result_sha256 ~ '^[0-9a-f]{64}$')
    );

CREATE TABLE betting.market_consensus_outcome (
      normalisation_run_id uuid NOT NULL
        REFERENCES betting.market_consensus_result(normalisation_run_id) ON DELETE RESTRICT,
      outcome varchar(16) NOT NULL,
      consensus_probability numeric(13,12) NOT NULL,
      lower_bound numeric(13,12) NOT NULL,
      upper_bound numeric(13,12) NOT NULL,
      PRIMARY KEY (normalisation_run_id, outcome),
      CONSTRAINT ck_market_consensus_outcome_name
        CHECK (outcome IN ('HOME','DRAW','AWAY')),
      CONSTRAINT ck_market_consensus_outcome_probability
        CHECK (consensus_probability BETWEEN 0 AND 1),
      CONSTRAINT ck_market_consensus_outcome_lower_bound
        CHECK (lower_bound BETWEEN 0 AND 1),
      CONSTRAINT ck_market_consensus_outcome_upper_bound
        CHECK (upper_bound BETWEEN 0 AND 1),
      CONSTRAINT ck_market_consensus_outcome_bounds
        CHECK (lower_bound <= consensus_probability AND consensus_probability <= upper_bound)
    );

CREATE TABLE betting.market_normalisation_exclusion (
      normalisation_run_id uuid NOT NULL
        REFERENCES betting.market_normalisation_run(normalisation_run_id) ON DELETE RESTRICT,
      sequence_number integer NOT NULL,
      operator_key varchar(120) NOT NULL,
      reason varchar(40) NOT NULL,
      PRIMARY KEY (normalisation_run_id, sequence_number),
      CONSTRAINT ck_market_normalisation_exclusion_sequence
        CHECK (sequence_number > 0),
      CONSTRAINT ck_market_normalisation_exclusion_reason CHECK (reason IN
        ('INCOMPLETE','STALE','UNSUPPORTED','SUSPENDED','UNAVAILABLE','RIGHTS_BLOCKED',
         'QUALITY_BLOCKED','MAPPING_UNAVAILABLE','FUTURE_OBSERVATION','DUPLICATE_OPERATOR'))
    );

CREATE TABLE betting.market_normalisation_warning (
      normalisation_run_id uuid NOT NULL
        REFERENCES betting.market_normalisation_run(normalisation_run_id) ON DELETE RESTRICT,
      sequence_number integer NOT NULL,
      warning_code varchar(120) NOT NULL,
      PRIMARY KEY (normalisation_run_id, sequence_number),
      CONSTRAINT ck_market_normalisation_warning_sequence
        CHECK (sequence_number > 0)
    );

CREATE FUNCTION betting.guard_normalisation_run_open()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE parent_xid bigint;
    BEGIN
      SELECT (run.xmin::text)::bigint INTO parent_xid
      FROM betting.market_normalisation_run AS run
      WHERE run.normalisation_run_id = NEW.normalisation_run_id;
      IF parent_xid IS NULL OR parent_xid IS DISTINCT FROM
           ((pg_current_xact_id()::text)::bigint) THEN
        RAISE EXCEPTION USING
          ERRCODE = '23514', MESSAGE = 'NORMALISATION_RUN_CLOSED';
      END IF;
      RETURN NEW;
    END $$;

CREATE TRIGGER trg_market_normalisation_book_source_run_open
          BEFORE INSERT ON betting.market_normalisation_book_source
          FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_run_open();

CREATE TRIGGER trg_market_normalisation_source_run_open
          BEFORE INSERT ON betting.market_normalisation_source
          FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_run_open();

CREATE TRIGGER trg_normalised_operator_market_run_open
          BEFORE INSERT ON betting.normalised_operator_market
          FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_run_open();

CREATE TRIGGER trg_normalised_operator_market_source_run_open
          BEFORE INSERT ON betting.normalised_operator_market_source
          FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_run_open();

CREATE TRIGGER trg_normalised_operator_outcome_run_open
          BEFORE INSERT ON betting.normalised_operator_outcome
          FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_run_open();

CREATE TRIGGER trg_market_consensus_result_run_open
          BEFORE INSERT ON betting.market_consensus_result
          FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_run_open();

CREATE TRIGGER trg_market_consensus_outcome_run_open
          BEFORE INSERT ON betting.market_consensus_outcome
          FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_run_open();

CREATE TRIGGER trg_market_normalisation_exclusion_run_open
          BEFORE INSERT ON betting.market_normalisation_exclusion
          FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_run_open();

CREATE TRIGGER trg_market_normalisation_warning_run_open
          BEFORE INSERT ON betting.market_normalisation_warning
          FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_run_open();

CREATE FUNCTION betting.guard_normalisation_vectors()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE target_id uuid; row_count integer; outcome_count integer; raw_sum numeric;
            prop_sum numeric; market_sum numeric; parent_booksum numeric;
            parent_fallback boolean;
    BEGIN
      target_id := COALESCE(NEW.normalised_operator_market_id, OLD.normalised_operator_market_id);
      SELECT count(*), count(DISTINCT outcome), sum(raw_implied_probability),
             sum(proportional_probability), sum(market_probability)
      INTO row_count, outcome_count, raw_sum, prop_sum, market_sum
      FROM betting.normalised_operator_outcome
      WHERE normalised_operator_market_id = target_id;
      SELECT raw_booksum, fallback_used INTO parent_booksum, parent_fallback
      FROM betting.normalised_operator_market
      WHERE normalised_operator_market_id = target_id;
      IF row_count <> 3 OR outcome_count <> 3 OR prop_sum <> 1 OR market_sum <> 1
         OR parent_booksum IS NULL
         OR abs(raw_sum - parent_booksum) > 0.000000000002
         OR (parent_fallback AND EXISTS (
              SELECT 1 FROM betting.normalised_operator_outcome AS outcome
              WHERE outcome.normalised_operator_market_id = target_id
                AND outcome.market_probability IS DISTINCT FROM
                    outcome.proportional_probability
            )) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'NORMALISED_VECTOR_INVALID';
      END IF;
      RETURN NULL;
    END $$;

CREATE CONSTRAINT TRIGGER trg_normalised_operator_vector
      AFTER INSERT OR UPDATE OR DELETE ON betting.normalised_operator_outcome
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_vectors();

CREATE CONSTRAINT TRIGGER trg_normalised_operator_parent_vector
      AFTER INSERT OR UPDATE ON betting.normalised_operator_market
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_vectors();

CREATE FUNCTION betting.guard_normalised_operator_source()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE parent_record record; observation_record record;
    BEGIN
      SELECT normalisation_run_id, fixture_id, market_id, provider_id,
             operator_id, operator_key
      INTO parent_record
      FROM betting.normalised_operator_market
      WHERE normalised_operator_market_id = NEW.normalised_operator_market_id;
      SELECT observation.source_snapshot_id, observation.fixture_id,
             observation.market_id, representation.provider_id,
             observation.operator_id,
             operator_mapping.external_id_text AS operator_key
      INTO observation_record
      FROM betting.odds_observation AS observation
      JOIN betting.operator_market_observation AS book
        ON book.book_observation_id = observation.book_observation_id
      JOIN betting.provider_market_representation AS representation
        ON representation.provider_market_representation_id =
           book.provider_market_representation_id
      JOIN core.external_identifier AS operator_mapping
        ON operator_mapping.external_identifier_id = representation.operator_mapping_id
      WHERE observation.odds_observation_id = NEW.odds_observation_id;
      IF parent_record.normalisation_run_id IS NULL
         OR observation_record.source_snapshot_id IS NULL
         OR (NEW.normalisation_run_id IS NOT NULL
             AND NEW.normalisation_run_id IS DISTINCT FROM
                 parent_record.normalisation_run_id)
         OR (NEW.source_snapshot_id IS NOT NULL
             AND NEW.source_snapshot_id IS DISTINCT FROM
                 observation_record.source_snapshot_id)
         OR (NEW.fixture_id IS NOT NULL
             AND NEW.fixture_id IS DISTINCT FROM parent_record.fixture_id)
         OR observation_record.fixture_id IS DISTINCT FROM parent_record.fixture_id
         OR observation_record.market_id IS DISTINCT FROM parent_record.market_id
         OR observation_record.provider_id IS DISTINCT FROM parent_record.provider_id
         OR observation_record.operator_id IS DISTINCT FROM parent_record.operator_id
         OR observation_record.operator_key IS DISTINCT FROM parent_record.operator_key THEN
        RAISE EXCEPTION USING
          ERRCODE = '23514', MESSAGE = 'NORMALISED_OPERATOR_SOURCE_MISMATCH';
      END IF;
      NEW.normalisation_run_id := parent_record.normalisation_run_id;
      NEW.source_snapshot_id := observation_record.source_snapshot_id;
      NEW.fixture_id := parent_record.fixture_id;
      RETURN NEW;
    END $$;

CREATE TRIGGER trg_normalised_operator_source_guard
      BEFORE INSERT ON betting.normalised_operator_market_source
      FOR EACH ROW EXECUTE FUNCTION betting.guard_normalised_operator_source();

CREATE FUNCTION betting.guard_normalised_operator_source_count()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE target_id uuid; row_count integer; outcome_count integer;
            published_outcome_count integer;
            book_count integer; mismatch_count integer; price_mismatch_count integer;
            maximum_observed_at timestamptz; maximum_usable_at timestamptz;
            parent_observed_at timestamptz; parent_usable_at timestamptz;
    BEGIN
      target_id := COALESCE(NEW.normalised_operator_market_id,
                            OLD.normalised_operator_market_id);
      SELECT count(*) INTO published_outcome_count
      FROM betting.normalised_operator_outcome
      WHERE normalised_operator_market_id = target_id;
      IF published_outcome_count <> 3 THEN
        RETURN NULL;
      END IF;
      SELECT count(*), count(DISTINCT observation.outcome),
             count(DISTINCT observation.book_observation_id),
             count(*) FILTER (WHERE
               representation.provider_id IS DISTINCT FROM parent.provider_id
               OR operator_mapping.external_id_text IS DISTINCT FROM parent.operator_key),
             count(*) FILTER (WHERE
               outcome.decimal_odds IS DISTINCT FROM observation.decimal_odds),
             max(observation.observed_at), max(attestation.usable_at),
             max(parent.observed_at), max(parent.usable_at)
      INTO row_count, outcome_count, book_count, mismatch_count,
           price_mismatch_count, maximum_observed_at, maximum_usable_at,
           parent_observed_at, parent_usable_at
      FROM betting.normalised_operator_market_source AS source
      JOIN betting.normalised_operator_market AS parent
        ON parent.normalised_operator_market_id = source.normalised_operator_market_id
      JOIN betting.odds_observation AS observation
        ON observation.odds_observation_id = source.odds_observation_id
      JOIN betting.normalised_operator_outcome AS outcome
        ON outcome.normalised_operator_market_id = source.normalised_operator_market_id
       AND outcome.outcome = observation.outcome
      JOIN betting.operator_market_observation AS book
        ON book.book_observation_id = observation.book_observation_id
      JOIN betting.provider_market_representation AS representation
        ON representation.provider_market_representation_id =
           book.provider_market_representation_id
      JOIN core.external_identifier AS operator_mapping
        ON operator_mapping.external_identifier_id = representation.operator_mapping_id
      JOIN betting.odds_publication_attestation AS attestation
        ON attestation.publication_batch_id = book.publication_batch_id
      WHERE source.normalised_operator_market_id = target_id;
      IF row_count <> 3 OR outcome_count <> 3 OR book_count <> 1
         OR mismatch_count <> 0 OR price_mismatch_count <> 0
         OR maximum_observed_at IS DISTINCT FROM parent_observed_at
         OR maximum_usable_at IS DISTINCT FROM parent_usable_at THEN
        RAISE EXCEPTION USING
          ERRCODE = '23514', MESSAGE = 'NORMALISED_OPERATOR_SOURCE_INVALID';
      END IF;
      RETURN NULL;
    END $$;

CREATE CONSTRAINT TRIGGER trg_normalised_operator_source_count
      AFTER INSERT OR UPDATE OR DELETE ON betting.normalised_operator_market_source
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalised_operator_source_count();

CREATE CONSTRAINT TRIGGER trg_normalised_operator_parent_source_count
      AFTER INSERT OR UPDATE ON betting.normalised_operator_market
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalised_operator_source_count();

CREATE CONSTRAINT TRIGGER trg_normalised_operator_outcome_source_count
      AFTER INSERT OR UPDATE OR DELETE ON betting.normalised_operator_outcome
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalised_operator_source_count();

CREATE FUNCTION betting.guard_consensus_vector()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE target_id uuid; row_count integer; outcome_count integer; probability_sum numeric;
    BEGIN
      target_id := COALESCE(NEW.normalisation_run_id, OLD.normalisation_run_id);
      SELECT count(*), count(DISTINCT outcome), sum(consensus_probability)
      INTO row_count, outcome_count, probability_sum
      FROM betting.market_consensus_outcome WHERE normalisation_run_id = target_id;
      IF row_count <> 3 OR outcome_count <> 3 OR probability_sum <> 1 THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'CONSENSUS_VECTOR_INVALID';
      END IF;
      RETURN NULL;
    END $$;

CREATE CONSTRAINT TRIGGER trg_market_consensus_vector
      AFTER INSERT OR UPDATE OR DELETE ON betting.market_consensus_outcome
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_consensus_vector();

CREATE CONSTRAINT TRIGGER trg_market_consensus_parent_vector
      AFTER INSERT ON betting.market_consensus_result
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_consensus_vector();

CREATE FUNCTION betting.guard_normalisation_run_graph()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE target_id uuid; run_status text; operator_rows integer;
            distinct_providers integer; distinct_operators integer;
            consensus_rows integer; reported_providers integer;
            reported_operators integer; reported_eligible integer;
            exclusion_rows integer; warning_rows integer;
    BEGIN
      target_id := COALESCE(NEW.normalisation_run_id, OLD.normalisation_run_id);
      SELECT status INTO run_status
      FROM betting.market_normalisation_run
      WHERE normalisation_run_id = target_id;
      IF run_status IS NULL THEN
        RETURN NULL;
      END IF;

      -- Let the more specific deferred vector/source guards report partial graphs.
      IF EXISTS (
           SELECT 1
           FROM betting.normalised_operator_market AS market
           WHERE market.normalisation_run_id = target_id
             AND (
               (SELECT count(*) FROM betting.normalised_operator_outcome AS outcome
                WHERE outcome.normalised_operator_market_id =
                      market.normalised_operator_market_id) <> 3
               OR
               (SELECT count(*) FROM betting.normalised_operator_market_source AS source
                WHERE source.normalised_operator_market_id =
                      market.normalised_operator_market_id) <> 3
             )
         )
         OR EXISTS (
           SELECT 1
           FROM betting.market_consensus_result AS consensus
           WHERE consensus.normalisation_run_id = target_id
             AND (SELECT count(*) FROM betting.market_consensus_outcome AS outcome
                  WHERE outcome.normalisation_run_id = target_id) <> 3
         ) THEN
        RETURN NULL;
      END IF;

      SELECT count(*), count(DISTINCT provider_id), count(DISTINCT operator_id)
      INTO operator_rows, distinct_providers, distinct_operators
      FROM betting.normalised_operator_market
      WHERE normalisation_run_id = target_id;
      SELECT count(*), max(provider_count), max(operator_count),
             max(eligible_operator_count)
      INTO consensus_rows, reported_providers, reported_operators, reported_eligible
      FROM betting.market_consensus_result
      WHERE normalisation_run_id = target_id;
      SELECT count(*) INTO exclusion_rows
      FROM betting.market_normalisation_exclusion
      WHERE normalisation_run_id = target_id;
      SELECT count(*) INTO warning_rows
      FROM betting.market_normalisation_warning
      WHERE normalisation_run_id = target_id;

      IF run_status IN ('NORMALISED','DEGRADED') THEN
        IF operator_rows < 1 OR consensus_rows <> 1
           OR reported_providers IS DISTINCT FROM distinct_providers
           OR reported_operators IS DISTINCT FROM distinct_operators
           OR reported_eligible IS DISTINCT FROM operator_rows
           OR (run_status = 'NORMALISED' AND exclusion_rows + warning_rows <> 0)
           OR (run_status = 'DEGRADED' AND exclusion_rows + warning_rows < 1) THEN
          RAISE EXCEPTION USING
            ERRCODE = '23514', MESSAGE = 'NORMALISATION_RUN_GRAPH_INVALID';
        END IF;
      ELSIF operator_rows <> 0 OR consensus_rows <> 0
            OR (run_status = 'BLOCKED' AND exclusion_rows < 1) THEN
        RAISE EXCEPTION USING
          ERRCODE = '23514', MESSAGE = 'NORMALISATION_RUN_GRAPH_INVALID';
      END IF;
      RETURN NULL;
    END $$;

CREATE CONSTRAINT TRIGGER trg_market_normalisation_run_graph
      AFTER INSERT OR UPDATE ON betting.market_normalisation_run
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_run_graph();

CREATE CONSTRAINT TRIGGER trg_normalised_operator_run_graph
      AFTER INSERT OR UPDATE OR DELETE ON betting.normalised_operator_market
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_run_graph();

CREATE CONSTRAINT TRIGGER trg_market_consensus_run_graph
      AFTER INSERT OR UPDATE OR DELETE ON betting.market_consensus_result
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_run_graph();

CREATE CONSTRAINT TRIGGER trg_market_normalisation_exclusion_run_graph
      AFTER INSERT OR UPDATE OR DELETE ON betting.market_normalisation_exclusion
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_run_graph();

CREATE CONSTRAINT TRIGGER trg_market_normalisation_warning_run_graph
      AFTER INSERT OR UPDATE OR DELETE ON betting.market_normalisation_warning
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_run_graph();

CREATE TRIGGER trg_odds_mapping_dependency_immutable
          BEFORE UPDATE OR DELETE ON betting.odds_mapping_dependency
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_market_normalisation_policy_immutable
          BEFORE UPDATE OR DELETE ON betting.market_normalisation_policy
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_market_normalisation_run_immutable
          BEFORE UPDATE OR DELETE ON betting.market_normalisation_run
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_market_normalisation_book_source_immutable
          BEFORE UPDATE OR DELETE ON betting.market_normalisation_book_source
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_market_normalisation_source_immutable
          BEFORE UPDATE OR DELETE ON betting.market_normalisation_source
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_normalised_operator_market_immutable
          BEFORE UPDATE OR DELETE ON betting.normalised_operator_market
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_normalised_operator_market_source_immutable
          BEFORE UPDATE OR DELETE ON betting.normalised_operator_market_source
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_normalised_operator_outcome_immutable
          BEFORE UPDATE OR DELETE ON betting.normalised_operator_outcome
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_market_consensus_result_immutable
          BEFORE UPDATE OR DELETE ON betting.market_consensus_result
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_market_consensus_outcome_immutable
          BEFORE UPDATE OR DELETE ON betting.market_consensus_outcome
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_market_normalisation_exclusion_immutable
          BEFORE UPDATE OR DELETE ON betting.market_normalisation_exclusion
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

CREATE TRIGGER trg_market_normalisation_warning_immutable
          BEFORE UPDATE OR DELETE ON betting.market_normalisation_warning
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change();

UPDATE public.alembic_version SET version_num='20260803_0005' WHERE public.alembic_version.version_num = '20260725_0004';

-- Running upgrade 20260803_0005 -> 20260807_0006

CREATE OR REPLACE FUNCTION football.validate_minute_pmf(p_values numeric[], requested_role text)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  value numeric;
  total numeric := 0;
BEGIN
  IF p_values IS NULL
     OR COALESCE(array_ndims(p_values), 0) <> 1
     OR COALESCE(array_lower(p_values, 1), 0) <> 1
     OR COALESCE(array_upper(p_values, 1), 0) <> 91
     OR COALESCE(cardinality(p_values), 0) <> 91
     OR requested_role IS NULL
     OR requested_role NOT IN ('START','BENCH') THEN
    RETURN false;
  END IF;
  FOREACH value IN ARRAY p_values LOOP
    IF value IS NULL OR value < 0 OR value > 1 THEN
      RETURN false;
    END IF;
    total := total + value;
  END LOOP;
  IF total <> 1 THEN
    RETURN false;
  END IF;
  RETURN requested_role <> 'START' OR p_values[1] = 0;
END
$$;

CREATE OR REPLACE FUNCTION football.round_half_even_6(value numeric)
RETURNS numeric LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  scaled numeric;
  base numeric;
  fraction numeric;
BEGIN
  IF value IS NULL THEN
    RETURN NULL;
  END IF;
  scaled := value * 1000000;
  base := trunc(scaled);
  fraction := scaled - base;
  IF fraction > 0.5 OR (fraction = 0.5 AND mod(base, 2) <> 0) THEN
    base := base + 1;
  END IF;
  RETURN base / 1000000;
END
$$;

CREATE OR REPLACE FUNCTION football.validate_player_minutes_projection(
  start_probability numeric,
  bench_probability numeric,
  out_probability numeric,
  p_values numeric[], zero_probability numeric,
  sixty_plus_probability numeric, expected numeric
)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  index_value integer;
  total numeric := 0;
  mean_value numeric := 0;
  tail_value numeric := 0;
BEGIN
  IF start_probability IS NULL OR bench_probability IS NULL OR out_probability IS NULL
     OR zero_probability IS NULL OR sixty_plus_probability IS NULL OR expected IS NULL
     OR start_probability < 0 OR start_probability > 1
     OR bench_probability < 0 OR bench_probability > 1
     OR out_probability < 0 OR out_probability > 1
     OR start_probability + bench_probability + out_probability <> 1
     OR NOT football.validate_minute_pmf(p_values, 'BENCH')
     OR zero_probability <> p_values[1] THEN
    RETURN false;
  END IF;
  FOR index_value IN 1..cardinality(p_values) LOOP
    total := total + p_values[index_value];
    mean_value := mean_value + (index_value - 1) * p_values[index_value];
    IF index_value >= 61 THEN
      tail_value := tail_value + p_values[index_value];
    END IF;
  END LOOP;
  RETURN sixty_plus_probability = tail_value
     AND expected = football.round_half_even_6(mean_value);
END
$$;

CREATE TABLE provenance.dataset_version (
    dataset_version_id UUID DEFAULT uuidv7() NOT NULL,
    dataset_semantic_sha256 CHAR(64) NOT NULL,
    dataset_key VARCHAR(160) NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    competition_code VARCHAR(80) NOT NULL,
    season_code VARCHAR(40) NOT NULL,
    training_cutoff TIMESTAMP WITH TIME ZONE NOT NULL,
    source_dataset_sha256 CHAR(64),
    policy_sha256 CHAR(64) NOT NULL,
    declared_training_example_count INTEGER NOT NULL,
    publication_state VARCHAR(16) DEFAULT 'DRAFT' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT pk_dataset_version PRIMARY KEY (dataset_version_id),
    CONSTRAINT uq_dataset_version_semantic_hash UNIQUE (dataset_semantic_sha256),
    CONSTRAINT ck_dataset_version_semantic_hash CHECK (dataset_semantic_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_dataset_version_source_hash CHECK (source_dataset_sha256 IS NULL OR source_dataset_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_dataset_version_policy_hash CHECK (policy_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_dataset_version_example_count CHECK (declared_training_example_count >= 0),
    CONSTRAINT ck_dataset_version_publication_state CHECK (publication_state IN ('DRAFT','COMPLETE'))
);

CREATE TABLE provenance.dataset_training_example (
    training_example_id UUID DEFAULT uuidv7() NOT NULL,
    dataset_version_id UUID NOT NULL,
    example_id VARCHAR(160) NOT NULL,
    fixture_id VARCHAR(160) NOT NULL,
    fixture_key VARCHAR(160) NOT NULL,
    feature_cutoff TIMESTAMP WITH TIME ZONE NOT NULL,
    label_usable_at TIMESTAMP WITH TIME ZONE NOT NULL,
    manager_regime_id VARCHAR(160) NOT NULL,
    minutes_label SMALLINT NOT NULL,
    player_id VARCHAR(160) NOT NULL,
    player_key VARCHAR(160) NOT NULL,
    position VARCHAR(8) NOT NULL,
    role_label VARCHAR(8) NOT NULL,
    sequence_index INTEGER NOT NULL,
    split VARCHAR(16) DEFAULT 'TRAIN' NOT NULL,
    team_id VARCHAR(160) NOT NULL,
    team_key VARCHAR(160) NOT NULL,
    evidence_type VARCHAR(40) NOT NULL,
    lineage_sha256 CHAR(64) NOT NULL,
    source_lineage JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT pk_dataset_training_example PRIMARY KEY (training_example_id),
    CONSTRAINT uq_dataset_example_identity UNIQUE (dataset_version_id, example_id),
    CONSTRAINT ck_dataset_example_lineage_hash CHECK (lineage_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_dataset_example_minutes CHECK (minutes_label BETWEEN 0 AND 90),
    CONSTRAINT ck_dataset_example_role CHECK (role_label IN ('START','BENCH','OUT')),
    CONSTRAINT ck_dataset_example_position CHECK (position IN ('GK','DEF','MID','FWD')),
    CONSTRAINT ck_dataset_example_split CHECK (split = 'TRAIN'),
    CONSTRAINT ck_dataset_example_sequence CHECK (sequence_index > 0),
    CONSTRAINT ck_dataset_example_time_order CHECK (label_usable_at >= feature_cutoff),
    CONSTRAINT fk_dataset_example_version FOREIGN KEY(dataset_version_id) REFERENCES provenance.dataset_version (dataset_version_id) ON DELETE RESTRICT
);

CREATE INDEX ix_dataset_training_example_version ON provenance.dataset_training_example (dataset_version_id);

CREATE TABLE provenance.model_version (
    model_version_id UUID DEFAULT uuidv7() NOT NULL,
    model_semantic_sha256 CHAR(64) NOT NULL,
    model_key VARCHAR(160) NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    dataset_version_sha256 CHAR(64) NOT NULL,
    role_artifact_sha256 CHAR(64) NOT NULL,
    minute_artifact_sha256 CHAR(64) NOT NULL,
    policy_sha256 CHAR(64) NOT NULL,
    model_family VARCHAR(160) NOT NULL,
    code_identity VARCHAR(160) NOT NULL,
    artifact JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT pk_model_version PRIMARY KEY (model_version_id),
    CONSTRAINT fk_model_dataset_version FOREIGN KEY(dataset_version_sha256) REFERENCES provenance.dataset_version (dataset_semantic_sha256) ON DELETE RESTRICT,
    CONSTRAINT uq_model_version_semantic_hash UNIQUE (model_semantic_sha256),
    CONSTRAINT ck_model_version_semantic_hash CHECK (model_semantic_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_model_version_dataset_hash CHECK (dataset_version_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_model_version_role_hash CHECK (role_artifact_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_model_version_minute_hash CHECK (minute_artifact_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_model_version_policy_hash CHECK (policy_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX ix_model_version_dataset ON provenance.model_version (dataset_version_sha256);

CREATE TABLE provenance.model_evaluation (
    model_evaluation_id UUID DEFAULT uuidv7() NOT NULL,
    model_version_id UUID NOT NULL,
    evaluation_semantic_sha256 CHAR(64) NOT NULL,
    evaluated_model_semantic_sha256 CHAR(64) NOT NULL,
    evaluated_model_artifact_sha256 CHAR(64) NOT NULL,
    evaluated_model_family VARCHAR(160) NOT NULL,
    status VARCHAR(24) NOT NULL,
    evaluation JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT pk_model_evaluation PRIMARY KEY (model_evaluation_id),
    CONSTRAINT uq_model_evaluation_semantic_hash UNIQUE (evaluation_semantic_sha256),
    CONSTRAINT ck_model_evaluation_semantic_hash CHECK (evaluation_semantic_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_model_evaluation_model_hash CHECK (evaluated_model_semantic_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_model_evaluation_artifact_hash CHECK (evaluated_model_artifact_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_model_evaluation_status CHECK (status IN ('PENDING','COMPLETE','BLOCKED')),
    CONSTRAINT ck_model_evaluation_not_production_calibration CHECK (evaluation->>'production_calibration_claim' = 'false'),
    CONSTRAINT fk_model_evaluation_model FOREIGN KEY(model_version_id) REFERENCES provenance.model_version (model_version_id) ON DELETE RESTRICT
);

CREATE TABLE football.prediction_run (
    prediction_run_id UUID DEFAULT uuidv7() NOT NULL,
    prediction_input_signature_sha256 CHAR(64) NOT NULL,
    output_semantic_sha256 CHAR(64) NOT NULL,
    core_output_payload JSONB,
    fixture_id UUID NOT NULL,
    team_id UUID NOT NULL,
    as_of TIMESTAMP WITH TIME ZONE NOT NULL,
    feature_cutoff TIMESTAMP WITH TIME ZONE,
    model_version_sha256 CHAR(64) NOT NULL,
    dataset_version_sha256 CHAR(64) NOT NULL,
    policy_sha256 CHAR(64) NOT NULL,
    manager_regime_id VARCHAR(160) NOT NULL,
    manager_context JSONB DEFAULT '{}'::jsonb NOT NULL,
    seed VARCHAR(160) NOT NULL,
    sample_count INTEGER NOT NULL,
    dependency_count INTEGER DEFAULT 0 NOT NULL,
    hard_eligibility_count INTEGER DEFAULT 0 NOT NULL,
    role_marginal_count INTEGER DEFAULT 0 NOT NULL,
    minute_pmf_count INTEGER DEFAULT 0 NOT NULL,
    scenario_count INTEGER DEFAULT 0 NOT NULL,
    core_state VARCHAR(16) DEFAULT 'DRAFT' NOT NULL,
    final_output_state VARCHAR(16) DEFAULT 'NONE' NOT NULL,
    final_output_count INTEGER DEFAULT 0 NOT NULL,
    final_output_semantic_sha256 CHAR(64),
    final_output_payload JSONB,
    bench_size SMALLINT NOT NULL,
    bench_goalkeeper_slots SMALLINT NOT NULL,
    code_identity VARCHAR(160) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT pk_prediction_run PRIMARY KEY (prediction_run_id),
    CONSTRAINT fk_prediction_model_version FOREIGN KEY(model_version_sha256) REFERENCES provenance.model_version (model_semantic_sha256) ON DELETE RESTRICT,
    CONSTRAINT fk_prediction_dataset_version FOREIGN KEY(dataset_version_sha256) REFERENCES provenance.dataset_version (dataset_semantic_sha256) ON DELETE RESTRICT,
    CONSTRAINT uq_prediction_input_signature UNIQUE (prediction_input_signature_sha256),
    CONSTRAINT ck_prediction_input_signature CHECK (prediction_input_signature_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_prediction_output_hash CHECK (output_semantic_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_prediction_configuration CHECK (sample_count > 0 AND bench_size >= 0 AND bench_goalkeeper_slots >= 0 AND bench_goalkeeper_slots <= bench_size),
    CONSTRAINT ck_prediction_publication_counts CHECK (dependency_count >= 0 AND hard_eligibility_count >= 0 AND role_marginal_count > 0 AND minute_pmf_count > 0 AND scenario_count = sample_count),
    CONSTRAINT ck_prediction_core_state CHECK (core_state IN ('DRAFT','COMPLETE')),
    CONSTRAINT ck_prediction_final_output_state CHECK (final_output_state IN ('NONE','DRAFT','COMPLETE')),
    CONSTRAINT ck_prediction_final_output_count CHECK (final_output_count >= 0),
    CONSTRAINT ck_prediction_final_output_hash CHECK (final_output_semantic_sha256 IS NULL OR final_output_semantic_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_prediction_final_output_payload_state CHECK ((final_output_state = 'NONE' AND final_output_count = 0 AND final_output_semantic_sha256 IS NULL AND final_output_payload IS NULL) OR (final_output_state IN ('DRAFT','COMPLETE')))
);

CREATE INDEX ix_prediction_run_fixture_team_asof ON football.prediction_run (fixture_id, team_id, as_of);

CREATE TABLE football.prediction_dependency (
    prediction_dependency_id UUID DEFAULT uuidv7() NOT NULL,
    prediction_run_id UUID NOT NULL,
    dependency_type VARCHAR(64) NOT NULL,
    dependency_key VARCHAR(200) NOT NULL,
    semantic_sha256 CHAR(64) NOT NULL,
    ordinal INTEGER NOT NULL,
    CONSTRAINT pk_prediction_dependency PRIMARY KEY (prediction_dependency_id),
    CONSTRAINT uq_prediction_dependency_key UNIQUE (prediction_run_id, dependency_type, dependency_key),
    CONSTRAINT ck_prediction_dependency_hash CHECK (semantic_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_prediction_dependency_ordinal CHECK (ordinal >= 0),
    CONSTRAINT fk_prediction_dependency_run FOREIGN KEY(prediction_run_id) REFERENCES football.prediction_run (prediction_run_id) ON DELETE RESTRICT
);

CREATE INDEX ix_prediction_dependency_run ON football.prediction_dependency (prediction_run_id);

CREATE TABLE football.prediction_hard_eligibility (
    prediction_hard_eligibility_id UUID DEFAULT uuidv7() NOT NULL,
    prediction_run_id UUID NOT NULL,
    player_id VARCHAR(160) NOT NULL,
    reason VARCHAR(240) NOT NULL,
    hard_ineligible BOOLEAN DEFAULT true NOT NULL,
    CONSTRAINT pk_prediction_hard_eligibility PRIMARY KEY (prediction_hard_eligibility_id),
    CONSTRAINT uq_prediction_hard_eligibility_player UNIQUE (prediction_run_id, player_id),
    CONSTRAINT fk_prediction_hard_eligibility_run FOREIGN KEY(prediction_run_id) REFERENCES football.prediction_run (prediction_run_id) ON DELETE RESTRICT
);

CREATE INDEX ix_prediction_hard_eligibility_run ON football.prediction_hard_eligibility (prediction_run_id);

CREATE TABLE football.role_marginal (
    role_marginal_id UUID DEFAULT uuidv7() NOT NULL,
    prediction_run_id UUID NOT NULL,
    player_id VARCHAR(160) NOT NULL,
    player_key VARCHAR(160) NOT NULL,
    position VARCHAR(8) NOT NULL,
    p_start NUMERIC NOT NULL,
    p_bench NUMERIC NOT NULL,
    p_out NUMERIC NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT pk_role_marginal PRIMARY KEY (role_marginal_id),
    CONSTRAINT uq_role_marginal_player UNIQUE (prediction_run_id, player_id),
    CONSTRAINT ck_role_marginal_position CHECK (position IN ('GK','DEF','MID','FWD')),
    CONSTRAINT ck_role_marginal_bounds CHECK (p_start >= 0 AND p_start <= 1 AND p_bench >= 0 AND p_bench <= 1 AND p_out >= 0 AND p_out <= 1),
    CONSTRAINT ck_role_marginal_exact_sum CHECK (p_start + p_bench + p_out = 1),
    CONSTRAINT fk_role_marginal_run FOREIGN KEY(prediction_run_id) REFERENCES football.prediction_run (prediction_run_id) ON DELETE RESTRICT
);

CREATE INDEX ix_role_marginal_run ON football.role_marginal (prediction_run_id);

CREATE TABLE football.conditional_minute_pmf (
    conditional_minute_pmf_id UUID DEFAULT uuidv7() NOT NULL,
    prediction_run_id UUID NOT NULL,
    player_id VARCHAR(160) NOT NULL,
    role VARCHAR(8) NOT NULL,
    minute_pmf NUMERIC[] NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT pk_conditional_minute_pmf PRIMARY KEY (conditional_minute_pmf_id),
    CONSTRAINT uq_minute_pmf_player_role UNIQUE (prediction_run_id, player_id, role),
    CONSTRAINT ck_minute_pmf_role CHECK (role IN ('START','BENCH')),
    CONSTRAINT ck_minute_pmf_exact_simplex CHECK (football.validate_minute_pmf(minute_pmf, role)),
    CONSTRAINT fk_minute_pmf_run FOREIGN KEY(prediction_run_id) REFERENCES football.prediction_run (prediction_run_id) ON DELETE RESTRICT
);

CREATE INDEX ix_minute_pmf_run ON football.conditional_minute_pmf (prediction_run_id);

CREATE TABLE football.lineup_scenario (
    lineup_scenario_id UUID DEFAULT uuidv7() NOT NULL,
    prediction_run_id UUID NOT NULL,
    scenario_index INTEGER NOT NULL,
    scenario_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT pk_lineup_scenario PRIMARY KEY (lineup_scenario_id),
    CONSTRAINT uq_lineup_scenario_index UNIQUE (prediction_run_id, scenario_index),
    CONSTRAINT uq_lineup_scenario_hash UNIQUE (prediction_run_id, scenario_sha256),
    CONSTRAINT uq_lineup_scenario_id_run UNIQUE (lineup_scenario_id, prediction_run_id),
    CONSTRAINT ck_lineup_scenario_index CHECK (scenario_index >= 0),
    CONSTRAINT ck_lineup_scenario_hash CHECK (scenario_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT fk_lineup_scenario_run FOREIGN KEY(prediction_run_id) REFERENCES football.prediction_run (prediction_run_id) ON DELETE RESTRICT
);

CREATE INDEX ix_lineup_scenario_run ON football.lineup_scenario (prediction_run_id);

CREATE TABLE football.lineup_scenario_member (
    lineup_scenario_member_id UUID DEFAULT uuidv7() NOT NULL,
    lineup_scenario_id UUID NOT NULL,
    prediction_run_id UUID NOT NULL,
    player_id VARCHAR(160) NOT NULL,
    role VARCHAR(8) NOT NULL,
    position VARCHAR(8) NOT NULL,
    CONSTRAINT pk_lineup_scenario_member PRIMARY KEY (lineup_scenario_member_id),
    CONSTRAINT fk_lineup_member_scenario_run FOREIGN KEY(lineup_scenario_id, prediction_run_id) REFERENCES football.lineup_scenario (lineup_scenario_id, prediction_run_id) ON DELETE RESTRICT,
    CONSTRAINT uq_lineup_member_player UNIQUE (lineup_scenario_id, player_id),
    CONSTRAINT ck_lineup_member_role CHECK (role IN ('START','BENCH','OUT')),
    CONSTRAINT ck_lineup_member_position CHECK (position IN ('GK','DEF','MID','FWD'))
);

CREATE INDEX ix_lineup_member_scenario ON football.lineup_scenario_member (lineup_scenario_id);

CREATE TABLE football.player_minutes_projection (
    player_minutes_projection_id UUID DEFAULT uuidv7() NOT NULL,
    prediction_run_id UUID NOT NULL,
    player_id VARCHAR(160) NOT NULL,
    p_start NUMERIC NOT NULL,
    p_bench NUMERIC NOT NULL,
    p_out NUMERIC NOT NULL,
    minute_pmf NUMERIC[] NOT NULL,
    p_zero NUMERIC NOT NULL,
    p_60_plus NUMERIC NOT NULL,
    expected_minutes NUMERIC NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT pk_player_minutes_projection PRIMARY KEY (player_minutes_projection_id),
    CONSTRAINT uq_player_minutes_projection_player UNIQUE (prediction_run_id, player_id),
    CONSTRAINT ck_player_minutes_projection_consistent CHECK (football.validate_player_minutes_projection(p_start, p_bench, p_out, minute_pmf, p_zero, p_60_plus, expected_minutes)),
    CONSTRAINT fk_player_minutes_projection_run FOREIGN KEY(prediction_run_id) REFERENCES football.prediction_run (prediction_run_id) ON DELETE RESTRICT
);

CREATE INDEX ix_player_minutes_projection_run ON football.player_minutes_projection (prediction_run_id);

CREATE OR REPLACE FUNCTION football.validate_lineup_scenario()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  target_scenario uuid;
  target_run uuid;
  expected_bench integer;
  expected_bench_gk integer;
  start_count integer;
  bench_count integer;
  start_gk_count integer;
  bench_gk_count integer;
BEGIN
  target_scenario := COALESCE(NEW.lineup_scenario_id, OLD.lineup_scenario_id);
  target_run := COALESCE(NEW.prediction_run_id, OLD.prediction_run_id);
  SELECT run.bench_size, run.bench_goalkeeper_slots
    INTO expected_bench, expected_bench_gk
    FROM football.prediction_run AS run
   WHERE run.prediction_run_id = target_run;
  IF expected_bench IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'LINEUP_RUN_NOT_FOUND';
  END IF;
  SELECT count(*) FILTER (WHERE member.role = 'START'),
         count(*) FILTER (WHERE member.role = 'BENCH'),
         count(*) FILTER (WHERE member.role = 'START' AND member.position = 'GK'),
         count(*) FILTER (WHERE member.role = 'BENCH' AND member.position = 'GK')
    INTO start_count, bench_count, start_gk_count, bench_gk_count
    FROM football.lineup_scenario_member AS member
   WHERE member.lineup_scenario_id = target_scenario
     AND member.prediction_run_id = target_run;
  IF start_count <> 11 OR bench_count <> expected_bench
     OR start_gk_count <> 1 OR bench_gk_count <> expected_bench_gk THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'LINEUP_SCENARIO_COUNTS_INVALID';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM football.lineup_scenario_member AS member
      JOIN football.prediction_hard_eligibility AS blocked
        ON blocked.prediction_run_id = member.prediction_run_id
       AND blocked.player_id = member.player_id
     WHERE member.lineup_scenario_id = target_scenario
       AND member.role IN ('START','BENCH')
       AND blocked.hard_ineligible
  ) THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'LINEUP_HARD_INELIGIBLE_MEMBER';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM football.lineup_scenario_member AS member
      LEFT JOIN football.role_marginal AS marginal
        ON marginal.prediction_run_id = target_run
       AND marginal.player_id = member.player_id
     WHERE member.lineup_scenario_id = target_scenario
       AND (marginal.player_id IS NULL OR marginal.position <> member.position)
  ) OR EXISTS (
    SELECT 1
      FROM football.role_marginal AS marginal
      LEFT JOIN football.lineup_scenario_member AS member
        ON member.prediction_run_id = target_run
       AND member.lineup_scenario_id = target_scenario
       AND member.player_id = marginal.player_id
     WHERE marginal.prediction_run_id = target_run
       AND member.player_id IS NULL
  ) THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'LINEUP_MARGINAL_COHERENCE_INVALID';
  END IF;
  RETURN NULL;
END
$$;

CREATE OR REPLACE FUNCTION provenance.validate_dataset_lifecycle()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE'
     AND OLD.publication_state = 'DRAFT'
     AND NEW.publication_state = 'COMPLETE'
     AND (to_jsonb(OLD) - 'publication_state') IS NOT DISTINCT FROM (to_jsonb(NEW) - 'publication_state') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'DATASET_IMMUTABLE';
END
$$;

CREATE OR REPLACE FUNCTION provenance.reject_complete_dataset_lineage_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  target_dataset uuid;
  target_state text;
BEGIN
  target_dataset := COALESCE(NEW.dataset_version_id, OLD.dataset_version_id);
  SELECT publication_state INTO target_state
    FROM provenance.dataset_version
   WHERE dataset_version_id = target_dataset;
  IF target_state IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'DATASET_NOT_FOUND';
  END IF;
  IF target_state = 'COMPLETE' THEN
    RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'DATASET_LINEAGE_FROZEN';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION football.validate_prediction_lifecycle()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE'
     AND OLD.core_state = 'DRAFT'
     AND NEW.core_state = 'COMPLETE'
     AND OLD.final_output_state = NEW.final_output_state
     AND (to_jsonb(OLD) - ARRAY['core_state','core_output_payload']) IS NOT DISTINCT FROM
         (to_jsonb(NEW) - ARRAY['core_state','core_output_payload']) THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE'
     AND OLD.core_state = 'COMPLETE'
     AND OLD.final_output_state = 'NONE'
     AND NEW.final_output_state = 'DRAFT'
     AND (to_jsonb(OLD) - 'final_output_state') IS NOT DISTINCT FROM (to_jsonb(NEW) - 'final_output_state') THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE'
     AND OLD.core_state = 'COMPLETE'
     AND OLD.final_output_state = 'DRAFT'
     AND NEW.final_output_state = 'COMPLETE'
     AND (to_jsonb(OLD) - ARRAY['final_output_state','final_output_count','final_output_semantic_sha256','final_output_payload','output_semantic_sha256']) IS NOT DISTINCT FROM
         (to_jsonb(NEW) - ARRAY['final_output_state','final_output_count','final_output_semantic_sha256','final_output_payload','output_semantic_sha256']) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'PREDICTION_RUN_IMMUTABLE';
END
$$;

CREATE OR REPLACE FUNCTION football.reject_complete_core_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  target_run uuid;
  target_state text;
BEGIN
  target_run := COALESCE(NEW.prediction_run_id, OLD.prediction_run_id);
  SELECT core_state INTO target_state
    FROM football.prediction_run
   WHERE prediction_run_id = target_run;
  IF target_state IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'PREDICTION_RUN_NOT_FOUND';
  END IF;
  IF target_state = 'COMPLETE' THEN
    RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'PREDICTION_CORE_FROZEN';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION football.reject_frozen_final_output_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  target_run uuid;
  target_state text;
BEGIN
  target_run := COALESCE(NEW.prediction_run_id, OLD.prediction_run_id);
  SELECT final_output_state INTO target_state
    FROM football.prediction_run
   WHERE prediction_run_id = target_run;
  IF target_state IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'PREDICTION_RUN_NOT_FOUND';
  END IF;
  IF target_state <> 'DRAFT' THEN
    RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'FINAL_OUTPUT_FROZEN';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION provenance.validate_dataset_complete()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  expected integer;
  actual integer;
BEGIN
  SELECT declared_training_example_count INTO expected
    FROM provenance.dataset_version
   WHERE dataset_version_id = COALESCE(NEW.dataset_version_id, OLD.dataset_version_id);
  IF expected IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'DATASET_NOT_FOUND';
  END IF;
  IF (SELECT publication_state FROM provenance.dataset_version
       WHERE dataset_version_id = COALESCE(NEW.dataset_version_id, OLD.dataset_version_id)) <> 'COMPLETE' THEN
    RETURN NULL;
  END IF;
  SELECT count(*) INTO actual
    FROM provenance.dataset_training_example
   WHERE dataset_version_id = COALESCE(NEW.dataset_version_id, OLD.dataset_version_id);
  IF actual <> expected THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'DATASET_LINEAGE_INCOMPLETE';
  END IF;
  RETURN NULL;
END
$$;

CREATE OR REPLACE FUNCTION provenance.validate_model_dataset_complete()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  expected integer;
  actual integer;
BEGIN
  SELECT dataset.declared_training_example_count INTO expected
    FROM provenance.dataset_version AS dataset
   WHERE dataset.dataset_semantic_sha256 = NEW.dataset_version_sha256;
  IF expected IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'MODEL_DATASET_NOT_FOUND';
  END IF;
  IF (SELECT dataset.publication_state
        FROM provenance.dataset_version AS dataset
       WHERE dataset.dataset_semantic_sha256 = NEW.dataset_version_sha256) <> 'COMPLETE' THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'MODEL_DATASET_INCOMPLETE';
  END IF;
  SELECT count(*) INTO actual
    FROM provenance.dataset_training_example AS example
    JOIN provenance.dataset_version AS dataset
      ON dataset.dataset_version_id = example.dataset_version_id
   WHERE dataset.dataset_semantic_sha256 = NEW.dataset_version_sha256;
  IF actual <> expected THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'MODEL_DATASET_INCOMPLETE';
  END IF;
  RETURN NULL;
END
$$;

CREATE OR REPLACE FUNCTION football.validate_prediction_complete()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  dependency_total integer;
  hard_total integer;
  marginal_total integer;
  pmf_total integer;
  scenario_total integer;
  role_total integer;
BEGIN
  IF NEW.core_state <> 'COMPLETE' THEN
    RETURN NULL;
  END IF;
  SELECT count(*) INTO dependency_total
    FROM football.prediction_dependency
   WHERE prediction_run_id = NEW.prediction_run_id;
  SELECT count(*) INTO hard_total
    FROM football.prediction_hard_eligibility
   WHERE prediction_run_id = NEW.prediction_run_id;
  SELECT count(*) INTO marginal_total
    FROM football.role_marginal
   WHERE prediction_run_id = NEW.prediction_run_id;
  SELECT count(*) INTO pmf_total
    FROM football.conditional_minute_pmf
   WHERE prediction_run_id = NEW.prediction_run_id;
  SELECT count(*) INTO scenario_total
    FROM football.lineup_scenario
   WHERE prediction_run_id = NEW.prediction_run_id;
  SELECT count(*) INTO role_total
    FROM football.conditional_minute_pmf
   WHERE prediction_run_id = NEW.prediction_run_id
     AND role IN ('START', 'BENCH');
  IF dependency_total <> NEW.dependency_count
     OR hard_total <> NEW.hard_eligibility_count
     OR marginal_total <> NEW.role_marginal_count
     OR pmf_total <> NEW.minute_pmf_count
     OR scenario_total <> NEW.scenario_count
     OR marginal_total = 0
     OR pmf_total = 0
     OR role_total <> pmf_total THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'PREDICTION_GRAPH_INCOMPLETE';
  END IF;
  RETURN NULL;
END
$$;

CREATE OR REPLACE FUNCTION football.validate_final_output_complete()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  final_total integer;
  marginal_total integer;
  mismatch integer;
BEGIN
  IF NEW.final_output_state <> 'COMPLETE' THEN
    RETURN NULL;
  END IF;
  IF NEW.core_state <> 'COMPLETE' OR NEW.final_output_payload IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'FINAL_OUTPUT_CORE_INCOMPLETE';
  END IF;
  SELECT count(*) INTO final_total
    FROM football.player_minutes_projection
   WHERE prediction_run_id = NEW.prediction_run_id;
  SELECT count(*) INTO marginal_total
    FROM football.role_marginal
   WHERE prediction_run_id = NEW.prediction_run_id;
  SELECT count(*) INTO mismatch
    FROM (
      (SELECT player_id FROM football.player_minutes_projection WHERE prediction_run_id = NEW.prediction_run_id
       EXCEPT SELECT player_id FROM football.role_marginal WHERE prediction_run_id = NEW.prediction_run_id)
      UNION ALL
      (SELECT player_id FROM football.role_marginal WHERE prediction_run_id = NEW.prediction_run_id
       EXCEPT SELECT player_id FROM football.player_minutes_projection WHERE prediction_run_id = NEW.prediction_run_id)
    ) AS differences;
  IF final_total <> NEW.final_output_count OR final_total = 0 OR final_total <> marginal_total OR mismatch <> 0 THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'FINAL_OUTPUT_GRAPH_INCOMPLETE';
  END IF;
  RETURN NULL;
END
$$;

CREATE OR REPLACE FUNCTION football.reject_immutable_availability_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'IMMUTABLE_RECORD';
END
$$;

CREATE TRIGGER trg_min007f_immutable_0 BEFORE UPDATE OR DELETE ON provenance.dataset_training_example FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change();

CREATE TRIGGER trg_min007f_immutable_1 BEFORE UPDATE OR DELETE ON provenance.model_version FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change();

CREATE TRIGGER trg_min007f_immutable_2 BEFORE UPDATE OR DELETE ON provenance.model_evaluation FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change();

CREATE TRIGGER trg_min007f_immutable_3 BEFORE UPDATE OR DELETE ON football.prediction_dependency FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change();

CREATE TRIGGER trg_min007f_immutable_4 BEFORE UPDATE OR DELETE ON football.prediction_hard_eligibility FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change();

CREATE TRIGGER trg_min007f_immutable_5 BEFORE UPDATE OR DELETE ON football.role_marginal FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change();

CREATE TRIGGER trg_min007f_immutable_6 BEFORE UPDATE OR DELETE ON football.conditional_minute_pmf FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change();

CREATE TRIGGER trg_min007f_immutable_7 BEFORE UPDATE OR DELETE ON football.lineup_scenario FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change();

CREATE TRIGGER trg_min007f_immutable_8 BEFORE UPDATE OR DELETE ON football.lineup_scenario_member FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change();

CREATE TRIGGER trg_min007f_immutable_9 BEFORE UPDATE OR DELETE ON football.player_minutes_projection FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change();

CREATE TRIGGER trg_min007f_dataset_lifecycle BEFORE UPDATE ON provenance.dataset_version FOR EACH ROW EXECUTE FUNCTION provenance.validate_dataset_lifecycle();

CREATE TRIGGER trg_min007f_dataset_lineage_freeze BEFORE INSERT OR UPDATE OR DELETE ON provenance.dataset_training_example FOR EACH ROW EXECUTE FUNCTION provenance.reject_complete_dataset_lineage_mutation();

CREATE TRIGGER trg_min007f_prediction_lifecycle BEFORE UPDATE ON football.prediction_run FOR EACH ROW EXECUTE FUNCTION football.validate_prediction_lifecycle();

CREATE TRIGGER trg_min007f_core_freeze_0 BEFORE INSERT OR UPDATE OR DELETE ON football.prediction_dependency FOR EACH ROW EXECUTE FUNCTION football.reject_complete_core_mutation();

CREATE TRIGGER trg_min007f_core_freeze_1 BEFORE INSERT OR UPDATE OR DELETE ON football.prediction_hard_eligibility FOR EACH ROW EXECUTE FUNCTION football.reject_complete_core_mutation();

CREATE TRIGGER trg_min007f_core_freeze_2 BEFORE INSERT OR UPDATE OR DELETE ON football.role_marginal FOR EACH ROW EXECUTE FUNCTION football.reject_complete_core_mutation();

CREATE TRIGGER trg_min007f_core_freeze_3 BEFORE INSERT OR UPDATE OR DELETE ON football.conditional_minute_pmf FOR EACH ROW EXECUTE FUNCTION football.reject_complete_core_mutation();

CREATE TRIGGER trg_min007f_core_freeze_4 BEFORE INSERT OR UPDATE OR DELETE ON football.lineup_scenario FOR EACH ROW EXECUTE FUNCTION football.reject_complete_core_mutation();

CREATE TRIGGER trg_min007f_core_freeze_5 BEFORE INSERT OR UPDATE OR DELETE ON football.lineup_scenario_member FOR EACH ROW EXECUTE FUNCTION football.reject_complete_core_mutation();

CREATE TRIGGER trg_min007f_final_output_freeze BEFORE INSERT OR UPDATE OR DELETE ON football.player_minutes_projection FOR EACH ROW EXECUTE FUNCTION football.reject_frozen_final_output_mutation();

CREATE CONSTRAINT TRIGGER trg_min007f_scenario_parent AFTER INSERT OR UPDATE ON football.lineup_scenario DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION football.validate_lineup_scenario();

CREATE CONSTRAINT TRIGGER trg_min007f_scenario_member AFTER INSERT OR UPDATE OR DELETE ON football.lineup_scenario_member DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION football.validate_lineup_scenario();

CREATE CONSTRAINT TRIGGER trg_min007f_dataset_complete AFTER INSERT OR UPDATE ON provenance.dataset_version DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION provenance.validate_dataset_complete();

CREATE CONSTRAINT TRIGGER trg_min007f_model_dataset_complete AFTER INSERT OR UPDATE ON provenance.model_version DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION provenance.validate_model_dataset_complete();

CREATE CONSTRAINT TRIGGER trg_min007f_prediction_complete AFTER INSERT OR UPDATE ON football.prediction_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION football.validate_prediction_complete();

CREATE CONSTRAINT TRIGGER trg_min007f_final_output_complete AFTER UPDATE ON football.prediction_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION football.validate_final_output_complete();

UPDATE public.alembic_version SET version_num='20260807_0006' WHERE public.alembic_version.version_num = '20260803_0005';

COMMIT;
