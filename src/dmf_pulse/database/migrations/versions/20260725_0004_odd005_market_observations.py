"""Add canonical operators, markets, exact odds, and quota evidence.

Revision ID: 20260725_0004
Revises: 20260725_0003
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260725_0004"
down_revision: str | None = "20260725_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPGRADE_STATEMENTS = (
    "CREATE SCHEMA betting",
    """
    ALTER TABLE provenance.rights_decision
      ADD CONSTRAINT uq_rights_decision_authority
      UNIQUE NULLS NOT DISTINCT
        (rights_profile_record_id, source_snapshot_id, capability)
    """,
    """
    ALTER TABLE core.external_identifier
      ADD CONSTRAINT ck_external_identifier_odds_operator_scope CHECK (
        identifier_namespace <> 'the_odds_api.bookmaker.key'
        OR (entity_type = 'BETTING_OPERATOR'
            AND season_id IS NULL
            AND provider_product = 'soccer_epl/odds')
      )
    """,
    "ALTER TABLE core.canonical_entity DROP CONSTRAINT ck_canonical_entity_type",
    """
    ALTER TABLE core.canonical_entity ADD CONSTRAINT ck_canonical_entity_type CHECK (
      entity_type IN ('COMPETITION','SEASON','GAMEWEEK','TEAM','PLAYER','FIXTURE',
                      'DATA_PROVIDER','BETTING_OPERATOR','MARKET','SELECTION')
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    "CREATE INDEX ix_operator_market_fixture ON betting.operator_fixture_market (fixture_id)",
    "CREATE INDEX ix_operator_market_operator ON betting.operator_fixture_market (operator_id)",
    "CREATE INDEX ix_market_selection_market ON betting.market_selection (market_id)",
    "CREATE INDEX ix_provider_market_market ON betting.provider_market_representation (market_id)",
    "CREATE INDEX ix_book_observation_market_usable ON betting.operator_market_observation (market_id, usable_at)",
    "CREATE INDEX ix_book_observation_snapshot ON betting.operator_market_observation (source_snapshot_id)",
    "CREATE INDEX ix_odds_observation_fixture_usable ON betting.odds_observation (fixture_id, usable_at)",
    "CREATE INDEX ix_odds_observation_book ON betting.odds_observation (book_observation_id)",
    "CREATE INDEX ix_quota_observation_provider ON betting.provider_quota_observation (provider_id, observed_at)",
    """
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
    $$
    """,
    """
    CREATE TRIGGER trg_provider_market_representation_guard
    BEFORE INSERT ON betting.provider_market_representation
    FOR EACH ROW EXECUTE FUNCTION betting.guard_provider_market_representation()
    """,
    """
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
    $$
    """,
    """
    CREATE TRIGGER trg_data_quality_odds_guard
    BEFORE INSERT OR UPDATE ON core.data_quality_issue
    FOR EACH ROW EXECUTE FUNCTION betting.guard_odds_quality_subject()
    """,
    """
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
    $$
    """,
    """
    CREATE TRIGGER trg_operator_book_observation_guard
    BEFORE INSERT ON betting.operator_market_observation
    FOR EACH ROW EXECUTE FUNCTION betting.guard_operator_book_observation()
    """,
    """
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
    $$
    """,
    """
    CREATE TRIGGER trg_odds_observation_coherence
    BEFORE INSERT ON betting.odds_observation
    FOR EACH ROW EXECUTE FUNCTION betting.guard_odds_observation_coherence()
    """,
    """
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
    $$
    """,
    """
    CREATE TRIGGER trg_provider_quota_observation_guard
    BEFORE INSERT ON betting.provider_quota_observation
    FOR EACH ROW EXECUTE FUNCTION betting.guard_quota_provider()
    """,
    """
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
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_operator_book_completeness
    AFTER INSERT ON betting.operator_market_observation
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION betting.guard_book_completeness()
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_odds_observation_completeness
    AFTER INSERT ON betting.odds_observation
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION betting.guard_book_completeness()
    """,
    """
    CREATE TRIGGER trg_provider_market_representation_immutable
    BEFORE UPDATE OR DELETE ON betting.provider_market_representation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_betting_operator_immutable
    BEFORE UPDATE OR DELETE ON betting.betting_operator
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_market_definition_immutable
    BEFORE UPDATE OR DELETE ON betting.market_definition
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_settlement_profile_immutable
    BEFORE UPDATE OR DELETE ON betting.settlement_profile
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_operator_fixture_market_immutable
    BEFORE UPDATE OR DELETE ON betting.operator_fixture_market
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_market_selection_immutable
    BEFORE UPDATE OR DELETE ON betting.market_selection
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_operator_market_observation_immutable
    BEFORE UPDATE OR DELETE ON betting.operator_market_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_odds_observation_immutable
    BEFORE UPDATE OR DELETE ON betting.odds_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
    """
    CREATE TRIGGER trg_provider_quota_observation_immutable
    BEFORE UPDATE OR DELETE ON betting.provider_quota_observation
    FOR EACH ROW EXECUTE FUNCTION provenance.reject_immutable_change()
    """,
)


DOWNGRADE_STATEMENTS = (
    "ALTER TABLE core.external_identifier DROP CONSTRAINT IF EXISTS ck_external_identifier_odds_operator_scope",
    "ALTER TABLE provenance.rights_decision DROP CONSTRAINT IF EXISTS uq_rights_decision_authority",
    "DROP TRIGGER trg_provider_quota_observation_immutable ON betting.provider_quota_observation",
    "DROP TRIGGER trg_odds_observation_immutable ON betting.odds_observation",
    "DROP TRIGGER trg_operator_market_observation_immutable ON betting.operator_market_observation",
    "DROP TRIGGER IF EXISTS trg_market_selection_immutable ON betting.market_selection",
    "DROP TRIGGER IF EXISTS trg_operator_fixture_market_immutable ON betting.operator_fixture_market",
    "DROP TRIGGER IF EXISTS trg_settlement_profile_immutable ON betting.settlement_profile",
    "DROP TRIGGER IF EXISTS trg_market_definition_immutable ON betting.market_definition",
    "DROP TRIGGER IF EXISTS trg_betting_operator_immutable ON betting.betting_operator",
    "DROP TRIGGER trg_provider_market_representation_immutable ON betting.provider_market_representation",
    "DROP TRIGGER IF EXISTS trg_provider_quota_observation_guard ON betting.provider_quota_observation",
    "DROP FUNCTION IF EXISTS betting.guard_quota_provider()",
    "DROP TRIGGER trg_odds_observation_completeness ON betting.odds_observation",
    "DROP TRIGGER trg_operator_book_completeness ON betting.operator_market_observation",
    "DROP FUNCTION betting.guard_book_completeness()",
    "DROP TRIGGER IF EXISTS trg_odds_observation_coherence ON betting.odds_observation",
    "DROP FUNCTION IF EXISTS betting.guard_odds_observation_coherence()",
    "DROP TRIGGER trg_operator_book_observation_guard ON betting.operator_market_observation",
    "DROP FUNCTION betting.guard_operator_book_observation()",
    "DROP TRIGGER IF EXISTS trg_data_quality_odds_guard ON core.data_quality_issue",
    "DROP FUNCTION IF EXISTS betting.guard_odds_quality_subject()",
    "DROP TRIGGER IF EXISTS trg_provider_market_representation_guard ON betting.provider_market_representation",
    "DROP FUNCTION IF EXISTS betting.guard_provider_market_representation()",
    "DROP TABLE betting.provider_quota_observation",
    "DROP TABLE betting.odds_observation",
    "DROP TABLE betting.operator_market_observation",
    "DROP TABLE betting.provider_market_representation",
    "DROP TABLE betting.market_selection",
    "DROP TABLE betting.operator_fixture_market",
    "DROP TABLE betting.settlement_profile",
    "DROP TABLE betting.market_definition",
    "DROP TABLE betting.betting_operator",
    "DROP TRIGGER trg_external_identifier_temporal ON core.external_identifier",
    """
    DELETE FROM core.external_identifier AS identifier
    USING provenance.data_provider AS provider
    WHERE identifier.provider_id = provider.provider_id
      AND provider.provider_key IN ('the_odds_api','synthetic_the_odds_api')
      AND identifier.identifier_namespace LIKE 'the_odds_api.%'
    """,
    """
    CREATE TRIGGER trg_external_identifier_temporal
    BEFORE INSERT OR UPDATE OR DELETE ON core.external_identifier
    FOR EACH ROW EXECUTE FUNCTION core.guard_temporal_version(
      'external_identifier_id', 'superseded_by_mapping_id',
      'canonical_entity_id', 'provider_id'
    )
    """,
    "DELETE FROM core.canonical_entity WHERE entity_type IN ('BETTING_OPERATOR','MARKET','SELECTION')",
    "ALTER TABLE core.canonical_entity DROP CONSTRAINT ck_canonical_entity_type",
    """
    ALTER TABLE core.canonical_entity ADD CONSTRAINT ck_canonical_entity_type CHECK (
      entity_type IN ('COMPETITION','SEASON','GAMEWEEK','TEAM','PLAYER','FIXTURE','DATA_PROVIDER')
    )
    """,
    "DROP SCHEMA betting",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
