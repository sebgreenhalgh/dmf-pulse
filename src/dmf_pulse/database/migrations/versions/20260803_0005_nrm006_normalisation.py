"""NRM-006 post-commit odds publication and normalisation persistence.

Revision ID: 20260803_0005
Revises: 20260725_0004
"""

from __future__ import annotations

from alembic import op

revision = "20260803_0005"
down_revision = "20260725_0004"
branch_labels = None
depends_on = None


UPGRADE_STATEMENTS = (
    """
    ALTER TABLE provenance.source_processing_event
      ADD CONSTRAINT uq_processing_event_snapshot_scope
      UNIQUE (processing_event_id, source_snapshot_id)
    """,
    """
    ALTER TABLE betting.provider_market_representation
      ADD CONSTRAINT uq_provider_market_representation_plan
      UNIQUE (provider_market_representation_id, mapping_plan_sha256)
    """,
    """
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
    )
    """,
    """
    CREATE TABLE betting.odds_publication_attestation (
      publication_batch_id uuid PRIMARY KEY
        REFERENCES betting.odds_publication_batch(publication_batch_id) ON DELETE RESTRICT,
      usable_at timestamptz NOT NULL,
      attestation_xid bigint NOT NULL DEFAULT ((pg_current_xact_id()::text)::bigint),
      recorded_at timestamptz NOT NULL DEFAULT transaction_timestamp()
    )
    """,
    """
    CREATE INDEX ix_odds_publication_attestation_usable
      ON betting.odds_publication_attestation(usable_at, publication_batch_id)
    """,
    """
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
      )
    """,
    """
    CREATE INDEX ix_book_observation_batch
      ON betting.operator_market_observation(publication_batch_id)
    """,
    """
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
        UNIQUE (odds_observation_id, source_snapshot_id, fixture_id)
    """,
    """
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
    END $$
    """,
    """
    CREATE TRIGGER trg_odds_publication_batch_guard
      BEFORE INSERT ON betting.odds_publication_batch
      FOR EACH ROW EXECUTE FUNCTION betting.guard_odds_publication_batch()
    """,
    """
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
    END $$
    """,
    """
    CREATE TRIGGER trg_odds_publication_attestation_guard
      BEFORE INSERT ON betting.odds_publication_attestation
      FOR EACH ROW EXECUTE FUNCTION betting.guard_odds_publication_attestation()
    """,
    """
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
    END $$
    """,
    """
    CREATE FUNCTION betting.reject_immutable_change()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'IMMUTABLE_MARKET_RECORD';
    END $$
    """,
    """
    CREATE TRIGGER trg_odds_publication_batch_immutable
      BEFORE UPDATE OR DELETE ON betting.odds_publication_batch
      FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_odds_publication_attestation_immutable
      BEFORE UPDATE OR DELETE ON betting.odds_publication_attestation
      FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change()
    """,
    """
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
    END $$
    """,
    """
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
    END $$
    """,
    """
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
    )
    """,
    """
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
    END $$
    """,
    """
    CREATE TRIGGER trg_odds_mapping_dependency_guard
      BEFORE INSERT ON betting.odds_mapping_dependency
      FOR EACH ROW EXECUTE FUNCTION betting.guard_odds_mapping_dependency()
    """,
    """
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
    END $$
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_operator_book_mapping_dependency
      AFTER INSERT ON betting.operator_market_observation
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.require_odds_mapping_dependency()
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    END $$
    """,
    """
    CREATE TRIGGER trg_market_normalisation_source_fixture
      BEFORE INSERT ON betting.market_normalisation_source
      FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_source_fixture()
    """,
    """
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
    )
    """,
    """
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
    END $$
    """,
    """
    CREATE TRIGGER trg_market_normalisation_book_source_fixture
      BEFORE INSERT ON betting.market_normalisation_book_source
      FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_book_source_fixture()
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
    CREATE TABLE betting.market_normalisation_warning (
      normalisation_run_id uuid NOT NULL
        REFERENCES betting.market_normalisation_run(normalisation_run_id) ON DELETE RESTRICT,
      sequence_number integer NOT NULL,
      warning_code varchar(120) NOT NULL,
      PRIMARY KEY (normalisation_run_id, sequence_number),
      CONSTRAINT ck_market_normalisation_warning_sequence
        CHECK (sequence_number > 0)
    )
    """,
    """
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
    END $$
    """,
    *(
        f"""
        CREATE TRIGGER trg_{table}_run_open
          BEFORE INSERT ON betting.{table}
          FOR EACH ROW EXECUTE FUNCTION betting.guard_normalisation_run_open()
        """
        for table in (
            "market_normalisation_book_source",
            "market_normalisation_source",
            "normalised_operator_market",
            "normalised_operator_market_source",
            "normalised_operator_outcome",
            "market_consensus_result",
            "market_consensus_outcome",
            "market_normalisation_exclusion",
            "market_normalisation_warning",
        )
    ),
    """
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
    END $$
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_normalised_operator_vector
      AFTER INSERT OR UPDATE OR DELETE ON betting.normalised_operator_outcome
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_vectors()
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_normalised_operator_parent_vector
      AFTER INSERT OR UPDATE ON betting.normalised_operator_market
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_vectors()
    """,
    """
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
    END $$
    """,
    """
    CREATE TRIGGER trg_normalised_operator_source_guard
      BEFORE INSERT ON betting.normalised_operator_market_source
      FOR EACH ROW EXECUTE FUNCTION betting.guard_normalised_operator_source()
    """,
    """
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
    END $$
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_normalised_operator_source_count
      AFTER INSERT OR UPDATE OR DELETE ON betting.normalised_operator_market_source
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalised_operator_source_count()
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_normalised_operator_parent_source_count
      AFTER INSERT OR UPDATE ON betting.normalised_operator_market
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalised_operator_source_count()
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_normalised_operator_outcome_source_count
      AFTER INSERT OR UPDATE OR DELETE ON betting.normalised_operator_outcome
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalised_operator_source_count()
    """,
    """
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
    END $$
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_market_consensus_vector
      AFTER INSERT OR UPDATE OR DELETE ON betting.market_consensus_outcome
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_consensus_vector()
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_market_consensus_parent_vector
      AFTER INSERT ON betting.market_consensus_result
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_consensus_vector()
    """,
    """
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
    END $$
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_market_normalisation_run_graph
      AFTER INSERT OR UPDATE ON betting.market_normalisation_run
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_run_graph()
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_normalised_operator_run_graph
      AFTER INSERT OR UPDATE OR DELETE ON betting.normalised_operator_market
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_run_graph()
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_market_consensus_run_graph
      AFTER INSERT OR UPDATE OR DELETE ON betting.market_consensus_result
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_run_graph()
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_market_normalisation_exclusion_run_graph
      AFTER INSERT OR UPDATE OR DELETE ON betting.market_normalisation_exclusion
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_run_graph()
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_market_normalisation_warning_run_graph
      AFTER INSERT OR UPDATE OR DELETE ON betting.market_normalisation_warning
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION betting.guard_normalisation_run_graph()
    """,
    *(
        f"""
        CREATE TRIGGER trg_{table}_immutable
          BEFORE UPDATE OR DELETE ON betting.{table}
          FOR EACH ROW EXECUTE FUNCTION betting.reject_immutable_change()
        """
        for table in (
            "odds_mapping_dependency",
            "market_normalisation_policy",
            "market_normalisation_run",
            "market_normalisation_book_source",
            "market_normalisation_source",
            "normalised_operator_market",
            "normalised_operator_market_source",
            "normalised_operator_outcome",
            "market_consensus_result",
            "market_consensus_outcome",
            "market_normalisation_exclusion",
            "market_normalisation_warning",
        )
    ),
)


DOWNGRADE_STATEMENTS = (
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM betting.odds_publication_batch AS batch
        LEFT JOIN betting.odds_publication_attestation AS attestation
          ON attestation.publication_batch_id = batch.publication_batch_id
        WHERE attestation.publication_batch_id IS NULL
      ) THEN
        RAISE EXCEPTION USING
          ERRCODE = '23514',
          MESSAGE = 'NRM006_DOWNGRADE_UNATTESTED_PUBLICATION';
      END IF;
    END $$
    """,
    "DROP TRIGGER IF EXISTS trg_operator_book_mapping_dependency ON betting.operator_market_observation",
    "DROP TABLE IF EXISTS betting.odds_mapping_dependency",
    "DROP FUNCTION IF EXISTS betting.require_odds_mapping_dependency()",
    "DROP FUNCTION IF EXISTS betting.guard_odds_mapping_dependency()",
    "DROP TABLE betting.market_normalisation_warning",
    "DROP TABLE betting.market_normalisation_exclusion",
    "DROP TABLE betting.market_consensus_outcome",
    "DROP TABLE betting.market_consensus_result",
    "DROP TABLE IF EXISTS betting.normalised_operator_market_source",
    "DROP TABLE betting.normalised_operator_outcome",
    "DROP TABLE betting.normalised_operator_market",
    "DROP TABLE IF EXISTS betting.market_normalisation_book_source",
    "DROP FUNCTION IF EXISTS betting.guard_normalisation_book_source_fixture()",
    "DROP TABLE betting.market_normalisation_source",
    "DROP FUNCTION IF EXISTS betting.guard_normalisation_source_fixture()",
    "DROP TABLE betting.market_normalisation_run",
    "DROP TABLE betting.market_normalisation_policy",
    "DROP FUNCTION IF EXISTS betting.guard_normalisation_run_open()",
    "DROP FUNCTION IF EXISTS betting.guard_normalisation_run_graph()",
    "DROP FUNCTION IF EXISTS betting.guard_normalised_operator_source_count()",
    "DROP FUNCTION IF EXISTS betting.guard_normalised_operator_source()",
    "DROP FUNCTION betting.guard_consensus_vector()",
    "DROP FUNCTION betting.guard_normalisation_vectors()",
    "DROP TRIGGER trg_odds_publication_attestation_immutable ON betting.odds_publication_attestation",
    "DROP TRIGGER trg_odds_publication_batch_immutable ON betting.odds_publication_batch",
    "DROP FUNCTION betting.reject_immutable_change()",
    "DROP TRIGGER trg_odds_publication_attestation_guard ON betting.odds_publication_attestation",
    "DROP FUNCTION betting.guard_odds_publication_attestation()",
    "DROP TRIGGER trg_odds_publication_batch_guard ON betting.odds_publication_batch",
    "DROP FUNCTION betting.guard_odds_publication_batch()",
    "DROP INDEX betting.ix_book_observation_batch",
    "ALTER TABLE betting.operator_market_observation DROP CONSTRAINT ck_book_observation_time_order",
    "ALTER TABLE betting.odds_observation DROP CONSTRAINT ck_odds_observation_time_order",
    "ALTER TABLE betting.operator_market_observation DISABLE TRIGGER trg_operator_market_observation_immutable",
    "ALTER TABLE betting.operator_market_observation DISABLE TRIGGER trg_operator_book_observation_guard",
    "ALTER TABLE betting.odds_observation DISABLE TRIGGER trg_odds_observation_immutable",
    "ALTER TABLE betting.odds_observation DISABLE TRIGGER trg_odds_observation_coherence",
    """
    UPDATE betting.operator_market_observation AS book
    SET usable_at = attestation.usable_at
    FROM betting.odds_publication_batch AS batch
    JOIN betting.odds_publication_attestation AS attestation
      ON attestation.publication_batch_id = batch.publication_batch_id
    WHERE book.publication_batch_id = batch.publication_batch_id
      AND book.usable_at IS NULL
    """,
    """
    UPDATE betting.odds_observation AS observation
    SET usable_at = attestation.usable_at
    FROM betting.odds_publication_batch AS batch
    JOIN betting.odds_publication_attestation AS attestation
      ON attestation.publication_batch_id = batch.publication_batch_id
    WHERE observation.publication_batch_id = batch.publication_batch_id
      AND observation.usable_at IS NULL
    """,
    "ALTER TABLE betting.operator_market_observation ENABLE TRIGGER trg_operator_book_observation_guard",
    "ALTER TABLE betting.operator_market_observation ENABLE TRIGGER trg_operator_market_observation_immutable",
    "ALTER TABLE betting.odds_observation ENABLE TRIGGER trg_odds_observation_coherence",
    "ALTER TABLE betting.odds_observation ENABLE TRIGGER trg_odds_observation_immutable",
    """
    ALTER TABLE betting.odds_observation
      DROP CONSTRAINT IF EXISTS uq_odds_observation_snapshot_fixture_scope,
      DROP CONSTRAINT uq_odds_observation_snapshot_scope,
      DROP CONSTRAINT fk_odds_observation_publication_batch,
      DROP COLUMN publication_batch_id,
      ALTER COLUMN usable_at SET NOT NULL,
      ADD CONSTRAINT ck_odds_observation_time_order
        CHECK (observed_at <= received_at AND received_at <= usable_at)
    """,
    """
    ALTER TABLE betting.operator_market_observation
      DROP CONSTRAINT IF EXISTS uq_book_observation_representation_batch,
      DROP CONSTRAINT IF EXISTS uq_book_observation_snapshot_scope,
      DROP CONSTRAINT fk_book_observation_publication_batch,
      DROP COLUMN publication_batch_id,
      ALTER COLUMN usable_at SET NOT NULL,
      ADD CONSTRAINT ck_book_observation_time_order
        CHECK (provider_observed_at <= received_at AND received_at <= usable_at)
    """,
    "DROP TABLE betting.odds_publication_attestation",
    "DROP TABLE betting.odds_publication_batch",
    """
    ALTER TABLE betting.provider_market_representation
      DROP CONSTRAINT IF EXISTS uq_provider_market_representation_plan
    """,
    "ALTER TABLE provenance.source_processing_event DROP CONSTRAINT uq_processing_event_snapshot_scope",
    # Restore the exact ODD-005 publication guards after the A6 columns disappear.
    """
    CREATE OR REPLACE FUNCTION betting.guard_odds_quality_subject()
    RETURNS trigger LANGUAGE plpgsql AS $$
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
          RAISE EXCEPTION USING
            ERRCODE = '23514', MESSAGE = 'ODDS_QUALITY_ALREADY_PUBLISHED';
        END IF;
      END IF;
      RETURN NEW;
    END $$
    """,
    """
    CREATE OR REPLACE FUNCTION betting.guard_operator_book_observation()
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
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION betting.guard_odds_observation_coherence()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE book_record record; market_record record;
    BEGIN
      SELECT * INTO book_record FROM betting.operator_market_observation WHERE book_observation_id = NEW.book_observation_id;
      SELECT * INTO market_record FROM betting.operator_fixture_market WHERE market_id = NEW.market_id;
      IF book_record IS NULL OR market_record IS NULL
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
    END $$
    """,
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
