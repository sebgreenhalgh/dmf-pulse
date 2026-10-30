"""Extend the existing research ledger with qualified real server-clock custody.

The public release seeds no real source, protocol acceptance, forecast or label.
Synthetic v1 guards and rows remain unchanged. Later qualifications require a
new independently reviewed registry/migration release.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from alembic import op

revision = "20261030_0009"
down_revision = "20261029_0008"
branch_labels = None
depends_on = None

SOURCE_GUARD = """
CREATE FUNCTION evaluation.guard_real_source() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.dataset_mode <> 'INDEPENDENTLY_QUALIFIED_REAL' OR NOT EXISTS (
    SELECT 1 FROM jsonb_array_elements(evaluation.real_authority()->'sources') q
    WHERE q->'source'=NEW.source_ref AND q=NEW.qualification
      AND q->'source'->>'source_id'=NEW.source_id
  )) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_SOURCE_QUALIFICATION_REQUIRED'; END IF;
  RETURN NEW;
END $$
"""

ARTIFACT_GUARD = """
CREATE FUNCTION evaluation.guard_real_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ref jsonb; q evaluation.qualified_source%ROWTYPE; parent evaluation.research_artifact%ROWTYPE;
  population evaluation.research_artifact%ROWTYPE; previous evaluation.research_artifact%ROWTYPE;
  body jsonb; prediction jsonb; protocol jsonb; target text; schema_name text; frozen timestamptz;
  intent text; proof jsonb; model_binding jsonb;
BEGIN
  NEW.stored_at := clock_timestamp();
  IF (NEW.dataset_mode <> 'PROSPECTIVE_REAL'
     OR NEW.payload->>'semantic_sha256' IS DISTINCT FROM NEW.artifact_sha256
     OR football.canonical_json_sha256(NEW.payload-'semantic_sha256') <> NEW.artifact_sha256
     OR jsonb_typeof(NEW.source_refs) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.source_refs)=0) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_HASH_MODE_OR_SOURCE_INVALID'; END IF;
  FOR ref IN SELECT value FROM jsonb_array_elements(NEW.source_refs) LOOP
    SELECT * INTO q FROM evaluation.qualified_source WHERE source_id=ref->>'source_id';
    IF (NOT FOUND OR q.dataset_mode <> 'INDEPENDENTLY_QUALIFIED_REAL' OR q.source_ref <> ref
       OR NOT ((q.qualification->>'qualified_at')::timestamptz <= NEW.stored_at
         AND NEW.stored_at < (q.qualification->>'valid_until')::timestamptz)
       OR q.qualification->'profile'->>'approved_purpose' <> 'PLAYER_FORECAST_RETENTION_AND_EVALUATION'
       OR q.qualification->'profile'->'retention_seconds' IS DISTINCT FROM 'null'::jsonb
       OR q.qualification->'profile'->'termination_deletion_required' IS DISTINCT FROM 'false'::jsonb
       OR q.qualification->'profile'->'capabilities'->>'derived_storage' <> 'ALLOW'
       OR q.qualification->'profile'->'capabilities'->>'private_internal_use' <> 'ALLOW') IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_SOURCE_RIGHTS_BLOCKED'; END IF;
  END LOOP;
  schema_name := NEW.payload->>'schema_version';
  IF NEW.kind='EXPERIMENT' AND schema_name='qualified-real-player-protocol-v1' THEN
    intent := football.canonical_json_sha256(NEW.payload-'semantic_sha256'-'registered_at');
    IF (NOT EXISTS (SELECT 1 FROM jsonb_array_elements(evaluation.real_authority()->'accepted_protocol_intents') a
      WHERE a->>'intent_sha256'=intent AND (a->>'accepted_at')::timestamptz <= NEW.stored_at
        AND NEW.stored_at < (a->>'expires_at')::timestamptz)
      OR NEW.source_refs <> NEW.payload->'sources'
      OR NEW.payload->>'registered_at' IS NULL
      OR NOT (NEW.payload->>'registered_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$')
      OR (NEW.payload->>'registered_at')::timestamptz > NEW.stored_at
      OR NEW.stored_at-(NEW.payload->>'registered_at')::timestamptz > interval '10 seconds'
      OR (NEW.payload->>'evaluation_classification'='PREREGISTERED_PROSPECTIVE'
        AND NEW.stored_at >= (NEW.payload->>'first_deadline_at')::timestamptz)) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_PROTOCOL_ACCEPTANCE_OR_CLOCK_INVALID'; END IF;
    RETURN NEW;
  ELSIF NEW.kind='EXPERIMENT' AND schema_name='qualified-real-player-deadline-registration-v1' THEN
    SELECT * INTO parent FROM evaluation.research_artifact WHERE artifact_sha256=NEW.payload->>'protocol_sha256';
    IF (NOT FOUND OR parent.dataset_mode <> 'PROSPECTIVE_REAL' OR parent.payload->>'schema_version' <> 'qualified-real-player-protocol-v1'
      OR NEW.source_refs <> jsonb_build_array(NEW.payload->'population'->'catalogue_source')
      OR NEW.payload->>'registered_at' IS NULL OR NEW.payload->>'original_population_frozen_at' IS NULL
      OR NEW.payload->>'custody' IS NULL OR NEW.payload->>'custody' NOT IN ('DATABASE_PREDEADLINE','QUALIFIED_EXTERNAL_HISTORICAL_IMPORT')
      OR NOT (NEW.payload->>'registered_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$')
      OR NOT (NEW.payload->>'original_population_frozen_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$')
      OR (NEW.payload->>'registered_at')::timestamptz > NEW.stored_at
      OR NEW.stored_at-(NEW.payload->>'registered_at')::timestamptz > interval '10 seconds') IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_POPULATION_PARENT_OR_CLOCK_INVALID'; END IF;
    body := NEW.payload->'population'; protocol := parent.payload;
    IF (NOT (protocol->'gameweeks' @> jsonb_build_array((body->>'gameweek')::integer))
      OR NOT EXISTS (SELECT 1 FROM evaluation.qualified_source s WHERE s.source_ref=body->'catalogue_source'
        AND s.qualification->'qualified_population_sha256s' ? football.canonical_json_sha256(body))
      OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(protocol->'sources') s
        WHERE s->'profile_id'=body->'catalogue_source'->'profile_id' AND s->'profile_sha256'=body->'catalogue_source'->'profile_sha256')
      OR ((body->>'gameweek')::integer=(protocol->'gameweeks'->>0)::integer AND
        ((body->>'deadline_at')::timestamptz <> (protocol->>'first_deadline_at')::timestamptz
          OR body->>'official_deadline_evidence_sha256' <> protocol->>'first_deadline_evidence_sha256'))) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_EXACT_CATALOGUE_OR_DEADLINE_REQUIRED'; END IF;
    frozen := (NEW.payload->>'original_population_frozen_at')::timestamptz;
    IF (NOT ((body->'catalogue_source'->>'usable_at')::timestamptz <= frozen AND frozen < (body->>'deadline_at')::timestamptz)) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_POPULATION_ORIGIN_INVALID'; END IF;
    IF NEW.payload->>'custody'='DATABASE_PREDEADLINE' THEN
      IF (protocol->>'evaluation_classification' <> 'PREREGISTERED_PROSPECTIVE'
        OR NEW.stored_at >= (body->>'deadline_at')::timestamptz
        OR frozen <> (NEW.payload->>'registered_at')::timestamptz
        OR NEW.payload->'external_custody_sha256' <> 'null'::jsonb) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_NATIVE_POPULATION_BACKDATE'; END IF;
    ELSE
      SELECT a INTO proof FROM jsonb_array_elements(evaluation.real_authority()->'historical_freezes') a
        WHERE football.canonical_json_sha256(a)=NEW.payload->>'external_custody_sha256'
          AND a->>'artifact_kind'='DEADLINE_POPULATION' AND a->>'artifact_semantic_sha256'=football.canonical_json_sha256(body)
          AND (a->>'original_frozen_at')::timestamptz=frozen AND (a->>'accepted_at')::timestamptz <= NEW.stored_at;
      IF (proof IS NULL OR protocol->>'evaluation_classification' <> 'POST_ORIGIN_DESCRIPTIVE') IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_EXTERNAL_POPULATION_PROOF_REQUIRED'; END IF;
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.kind IN ('FORECAST','SCORECARD') THEN
    SELECT * INTO parent FROM evaluation.research_artifact WHERE artifact_sha256=NEW.experiment_sha256;
    IF (NOT FOUND OR parent.dataset_mode <> 'PROSPECTIVE_REAL' OR parent.payload->>'schema_version' <> 'qualified-real-player-protocol-v1') IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_PROTOCOL_REQUIRED'; END IF;
    protocol := parent.payload;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.source_refs) r WHERE NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements(protocol->'sources') s WHERE s->'profile_id'=r->'profile_id' AND s->'profile_sha256'=r->'profile_sha256'
    )) THEN RAISE EXCEPTION 'REAL_PLAYER_PREDECLARED_SOURCE_SCOPE_REQUIRED'; END IF;
  END IF;
  IF NEW.kind='FORECAST' THEN
    prediction := NEW.payload->'forecast';
    target := football.canonical_json_sha256(prediction->'key');
    SELECT * INTO population FROM evaluation.research_artifact WHERE artifact_sha256=NEW.payload->>'population_registration_sha256';
    SELECT a INTO model_binding FROM jsonb_array_elements(protocol->'model_bindings') a WHERE a->>'model_id'=NEW.model_id;
    IF (population.artifact_sha256 IS NULL OR model_binding IS NULL OR population.dataset_mode <> 'PROSPECTIVE_REAL'
      OR population.payload->>'protocol_sha256' <> NEW.experiment_sha256
      OR NEW.target_id IS DISTINCT FROM target OR NEW.model_id IS DISTINCT FROM prediction->>'model_id'
      OR NEW.source_refs <> prediction->'sources' OR prediction->>'dataset_mode' <> 'PROSPECTIVE_REAL'
      OR prediction->>'schema_version' IS DISTINCT FROM 'qualified-real-player-point-forecast-v1'
      OR NEW.payload->>'recorded_at' IS NULL OR NEW.payload->>'original_frozen_at' IS NULL
      OR NEW.payload->>'custody' IS NULL OR NEW.payload->>'custody' NOT IN ('DATABASE_PREDEADLINE','QUALIFIED_EXTERNAL_HISTORICAL_IMPORT')
      OR NOT (NEW.payload->>'recorded_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$')
      OR NOT (NEW.payload->>'original_frozen_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$')
      OR prediction->'stage12'->>'point_forecast' IS NULL
      OR prediction->'stage12'->>'horizon' IS DISTINCT FROM '1'
      OR prediction->'stage12'->>'dataset_mode' IS DISTINCT FROM protocol->>'information_grade'
      OR prediction->>'generated_at' IS DISTINCT FROM prediction->'stage12'->>'issued_at'
      OR prediction->>'semantic_sha256' <> football.canonical_json_sha256(prediction-'semantic_sha256')
      OR NOT (population.payload->'population'->'targets' @> jsonb_build_array(prediction->'key'))
      OR (prediction->>'deadline_at')::timestamptz <> (population.payload->'population'->>'deadline_at')::timestamptz
      OR model_binding->>'code_sha' IS DISTINCT FROM prediction->'stage12'->'lineage'->>'code_commit'
      OR model_binding->'model_version_ids' IS DISTINCT FROM prediction->'stage12'->'lineage'->'model_version_ids'
      OR model_binding->>'ruleset_sha256' IS DISTINCT FROM prediction->'stage12'->'lineage'->>'ruleset_hash'
      OR prediction->'stage12'->>'forecast_sha256' <> encode(pg_catalog.sha256(convert_to(football.canonical_json_text(jsonb_set(prediction->'stage12','{forecast_sha256}','null'::jsonb)) || chr(10),'UTF8')),'hex')) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_FORECAST_BINDING_INVALID'; END IF;

    IF ((SELECT array_agg(k ORDER BY k COLLATE "C") FROM jsonb_object_keys(NEW.payload) k) IS DISTINCT FROM ARRAY['custody','external_custody_sha256','forecast','original_frozen_at','population_registration_sha256','recorded_at','semantic_sha256']::text[]
      OR (SELECT array_agg(k ORDER BY k COLLATE "C") FROM jsonb_object_keys(prediction) k) IS DISTINCT FROM ARRAY['dataset_mode','deadline_at','expected_minutes','generated_at','information_cutoff','key','label_finality_cutoff','model_id','original_full_forecast','schema_version','semantic_sha256','sources','stage12']::text[]
      OR (SELECT array_agg(k ORDER BY k COLLATE "C") FROM jsonb_object_keys(prediction->'stage12') k) IS DISTINCT FROM ARRAY['benchmark_id','dataset_mode','forecast_id','forecast_sha256','horizon','issued_at','lineage','pmf','point_forecast','probability_forecast','scenario_dimension_ids','scenario_samples','scenario_weights','schema_version','target_id']::text[]
      OR (SELECT array_agg(k ORDER BY k COLLATE "C") FROM jsonb_object_keys(prediction->'stage12'->'lineage') k) IS DISTINCT FROM ARRAY['benchmark_config_sha256','code_commit','dataset_manifest_sha256','fold_sha256','forecast_origin','information_cutoff','input_manifest_sha256','label_finality_cutoff','metric_config_sha256','model_version_ids','random_seed','ruleset_hash','ruleset_id','training_cutoff','usable_at_cutoff']::text[]
      OR prediction->'stage12'->>'schema_version' IS DISTINCT FROM 'frozen-forecast-v1'
      OR EXISTS (SELECT 1 FROM jsonb_each_text(prediction) d WHERE d.key IN ('generated_at','information_cutoff','deadline_at','label_finality_cutoff')
        AND (d.value ~ '(Z|[+-][0-9]{2}:[0-9]{2})$') IS NOT TRUE)
      OR prediction->'stage12'->>'target_id' IS DISTINCT FROM target
      OR prediction->'stage12'->>'benchmark_id' IS DISTINCT FROM prediction->>'model_id'
      OR jsonb_typeof(prediction->'stage12'->'point_forecast') IS DISTINCT FROM 'string'
      OR (prediction->'stage12'->>'point_forecast')::numeric IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)
      OR prediction->>'information_cutoff' IS DISTINCT FROM prediction->'stage12'->'lineage'->>'information_cutoff'
      OR prediction->>'information_cutoff' IS DISTINCT FROM prediction->'stage12'->'lineage'->>'usable_at_cutoff'
      OR prediction->'stage12'->'lineage'->>'label_finality_cutoff' IS DISTINCT FROM prediction->>'label_finality_cutoff'
      OR prediction->'stage12'->'lineage'->>'dataset_manifest_sha256' IS DISTINCT FROM football.canonical_json_sha256(prediction->'sources')
      OR NOT ((prediction->>'information_cutoff')::timestamptz <= (prediction->>'generated_at')::timestamptz
        AND (prediction->>'generated_at')::timestamptz <= (prediction->'stage12'->'lineage'->>'forecast_origin')::timestamptz
        AND (prediction->'stage12'->'lineage'->>'forecast_origin')::timestamptz < (prediction->>'deadline_at')::timestamptz
        AND (prediction->>'deadline_at')::timestamptz < (prediction->>'label_finality_cutoff')::timestamptz)
      OR EXISTS (SELECT 1 FROM jsonb_array_elements(prediction->'sources') s
        WHERE ((s->>'usable_at')::timestamptz <= (prediction->>'information_cutoff')::timestamptz) IS NOT TRUE)
      OR NOT (prediction->'sources' @> jsonb_build_array(population.payload->'population'->'catalogue_source'))
      OR NOT ((population.payload->>'original_population_frozen_at')::timestamptz <= (prediction->>'generated_at')::timestamptz)
      OR prediction->'stage12'->'scenario_samples' IS DISTINCT FROM '[]'::jsonb
      OR prediction->'stage12'->'scenario_weights' IS DISTINCT FROM '[]'::jsonb
      OR prediction->'stage12'->'scenario_dimension_ids' IS DISTINCT FROM '[]'::jsonb
      OR prediction->'stage12'->'probability_forecast' IS DISTINCT FROM 'null'::jsonb
    ) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_FORECAST_SHAPE_OR_LINEAGE_INVALID'; END IF;

    IF (jsonb_typeof(prediction->'stage12'->'pmf') IS DISTINCT FROM 'object'
      OR EXISTS (SELECT 1 FROM jsonb_each_text(prediction->'stage12'->'pmf') p
        WHERE p.key !~ '^-?[0-9]+$' OR p.key IS DISTINCT FROM (p.key::numeric)::text
          OR (p.value::numeric >= 0 AND p.value::numeric <= 1) IS NOT TRUE)
      OR (prediction->'stage12'->'pmf' <> '{}'::jsonb AND
        (SELECT sum(p.value::numeric) FROM jsonb_each_text(prediction->'stage12'->'pmf') p) IS DISTINCT FROM 1::numeric)
      OR (prediction->'stage12'->'pmf' <> '{}'::jsonb AND
        abs((SELECT sum(p.key::numeric*p.value::numeric) FROM jsonb_each_text(prediction->'stage12'->'pmf') p)
          -(prediction->'stage12'->>'point_forecast')::numeric) > 1e-10::numeric)
      OR (prediction->'expected_minutes' <> 'null'::jsonb AND
        ((prediction->>'expected_minutes')::numeric >= 0 AND (prediction->>'expected_minutes')::numeric <= 90*jsonb_array_length(prediction->'key'->'fixture_ids')) IS NOT TRUE)
      OR EXISTS (SELECT 1 FROM jsonb_each(prediction->'stage12'->'lineage') l
        WHERE l.key IN ('ruleset_hash','dataset_manifest_sha256','input_manifest_sha256') AND
          (jsonb_typeof(l.value)='string' AND l.value #>> '{}' ~ '^[0-9a-f]{64}$') IS NOT TRUE)
      OR jsonb_typeof(prediction->'stage12'->'lineage'->'ruleset_id') IS DISTINCT FROM 'string'
      OR jsonb_typeof(prediction->'stage12'->'forecast_id') IS DISTINCT FROM 'string'
      OR EXISTS (SELECT 1 FROM jsonb_each(prediction->'stage12'->'lineage') l
        WHERE l.key IN ('fold_sha256','benchmark_config_sha256','metric_config_sha256') AND l.value <> 'null'::jsonb
          AND (jsonb_typeof(l.value)='string' AND l.value #>> '{}' ~ '^[0-9a-f]{64}$') IS NOT TRUE)
      OR (prediction->'stage12'->'lineage'->'random_seed' <> 'null'::jsonb AND
        (jsonb_typeof(prediction->'stage12'->'lineage'->'random_seed')='number'
          AND prediction->'stage12'->'lineage'->>'random_seed' ~ '^(0|[1-9][0-9]*)$') IS NOT TRUE)
      OR NOT (prediction->'stage12'->'lineage'->>'forecast_origin' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$')
      OR (prediction->'stage12'->'lineage'->'training_cutoff' <> 'null'::jsonb AND
        (jsonb_typeof(prediction->'stage12'->'lineage'->'training_cutoff')='string'
          AND prediction->'stage12'->'lineage'->>'training_cutoff' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
          AND (prediction->'stage12'->'lineage'->>'training_cutoff')::timestamptz <= (prediction->>'information_cutoff')::timestamptz) IS NOT TRUE)
    ) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_FORECAST_VALUES_INVALID'; END IF;
    IF prediction->'original_full_forecast' <> 'null'::jsonb THEN
      body := prediction->'original_full_forecast';
      IF ((SELECT array_agg(k ORDER BY k COLLATE "C") FROM jsonb_object_keys(body) k) IS DISTINCT FROM ARRAY['code_sha','components','dataset_mode','deadline_at','expected_minutes','generated_at','horizon_gameweeks','information_cutoff','input_sha256','key','label_finality_cutoff','mean','model_id','model_version_ids','pmf','pmf_conversion_policy','position','retention','ruleset_sha256','schema_version','semantic_sha256','source_summary_sha256','sources','training_cutoff']::text[]
        OR (SELECT array_agg(k ORDER BY k COLLATE "C") FROM jsonb_object_keys(body->'components') k) IS DISTINCT FROM ARRAY['appearance','assists','bonus','clean_sheet','defensive_contributions','goals','goals_conceded','own_goals','penalty_misses','penalty_saves','red_cards','saves','yellow_cards']::text[]
        OR body->>'semantic_sha256' IS DISTINCT FROM football.canonical_json_sha256(body-'semantic_sha256')
        OR body->>'schema_version' IS DISTINCT FROM 'player-forecast-v1'
        OR body->>'dataset_mode' IS DISTINCT FROM 'PROSPECTIVE_REAL'
        OR body->'horizon_gameweeks' IS DISTINCT FROM '1'::jsonb
        OR body->>'retention' IS DISTINCT FROM 'QUALIFIED_RESEARCH_ONLY'
        OR body->>'pmf_conversion_policy' IS DISTINCT FROM 'EXACT_DECIMAL_OR_STAGE9_18DP_HALF_EVEN_V1'
        OR (body->>'position' IN ('GK','DEF','MID','FWD')) IS NOT TRUE
        OR (jsonb_typeof(body->'source_summary_sha256')='string' AND body->>'source_summary_sha256' ~ '^[0-9a-f]{64}$') IS NOT TRUE
        OR EXISTS (SELECT 1 FROM jsonb_each(body->'components') c
          WHERE jsonb_typeof(c.value) IS DISTINCT FROM 'string'
            OR (c.value #>> '{}')::numeric IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric))
        OR abs((SELECT sum(c.value::numeric) FROM jsonb_each_text(body->'components') c)-(body->>'mean')::numeric) > 1e-10::numeric
        OR body->'key' IS DISTINCT FROM prediction->'key'
        OR body->'sources' IS DISTINCT FROM prediction->'sources'
        OR body->'model_id' IS DISTINCT FROM prediction->'model_id'
        OR body->'mean' IS DISTINCT FROM prediction->'stage12'->'point_forecast'
        OR body->'pmf' IS DISTINCT FROM prediction->'stage12'->'pmf'
        OR body->'expected_minutes' IS DISTINCT FROM prediction->'expected_minutes'
        OR body->'generated_at' IS DISTINCT FROM prediction->'generated_at'
        OR body->'information_cutoff' IS DISTINCT FROM prediction->'information_cutoff'
        OR body->'deadline_at' IS DISTINCT FROM prediction->'deadline_at'
        OR body->'label_finality_cutoff' IS DISTINCT FROM prediction->'label_finality_cutoff'
        OR body->'training_cutoff' IS DISTINCT FROM prediction->'stage12'->'lineage'->'training_cutoff'
        OR body->'code_sha' IS DISTINCT FROM prediction->'stage12'->'lineage'->'code_commit'
        OR body->'model_version_ids' IS DISTINCT FROM prediction->'stage12'->'lineage'->'model_version_ids'
        OR body->'ruleset_sha256' IS DISTINCT FROM prediction->'stage12'->'lineage'->'ruleset_hash'
        OR body->'input_sha256' IS DISTINCT FROM prediction->'stage12'->'lineage'->'input_manifest_sha256'
      ) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_FULL_FORECAST_ADAPTER_INVALID'; END IF;
    END IF;
    frozen := (NEW.payload->>'original_frozen_at')::timestamptz;
    IF (NOT ((prediction->>'generated_at')::timestamptz <= frozen AND frozen < (prediction->>'deadline_at')::timestamptz)
      OR (NEW.payload->>'recorded_at')::timestamptz > NEW.stored_at
      OR NEW.stored_at-(NEW.payload->>'recorded_at')::timestamptz > interval '10 seconds') IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_FORECAST_CLOCK_INVALID'; END IF;
    IF NEW.payload->>'custody'='DATABASE_PREDEADLINE' THEN
      IF (protocol->>'evaluation_classification' <> 'PREREGISTERED_PROSPECTIVE'
        OR NEW.stored_at >= (prediction->>'deadline_at')::timestamptz
        OR frozen <> (NEW.payload->>'recorded_at')::timestamptz
        OR NEW.payload->'external_custody_sha256' <> 'null'::jsonb) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_NATIVE_FORECAST_BACKDATE'; END IF;
    ELSE
      SELECT a INTO proof FROM jsonb_array_elements(evaluation.real_authority()->'historical_freezes') a
        WHERE football.canonical_json_sha256(a)=NEW.payload->>'external_custody_sha256'
          AND a->>'artifact_kind'='POINT_FORECAST' AND a->>'artifact_semantic_sha256'=prediction->>'semantic_sha256'
          AND (a->>'original_frozen_at')::timestamptz=frozen AND (a->>'accepted_at')::timestamptz <= NEW.stored_at;
      IF (proof IS NULL OR protocol->>'evaluation_classification' <> 'POST_ORIGIN_DESCRIPTIVE') IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_EXTERNAL_FORECAST_PROOF_REQUIRED'; END IF;
    END IF;
  ELSIF NEW.kind='LABEL' THEN
    target := football.canonical_json_sha256(NEW.payload->'key');
    IF (NEW.target_id IS DISTINCT FROM target OR NEW.source_refs <> jsonb_build_array(NEW.payload->'source')
      OR NEW.payload->>'dataset_mode' <> 'PROSPECTIVE_REAL' OR NEW.payload->>'finalization_status' <> 'FINAL'
      OR (NEW.payload->>'revision')::integer IS DISTINCT FROM NEW.revision
      OR NEW.payload->>'supersedes_sha256' IS DISTINCT FROM NEW.supersedes_sha256
      OR (NEW.payload->>'usable_at')::timestamptz > NEW.stored_at
      OR NOT EXISTS (SELECT 1 FROM evaluation.qualified_source s WHERE s.source_ref=NEW.payload->'source'
        AND s.qualification->'qualified_label_sha256s' ? NEW.artifact_sha256)) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_FINAL_LABEL_NOT_QUALIFIED'; END IF;
    IF NEW.revision>0 THEN
      SELECT * INTO previous FROM evaluation.research_artifact WHERE artifact_sha256=NEW.supersedes_sha256;
      IF (NOT FOUND OR previous.kind <> 'LABEL' OR previous.target_id <> target OR previous.revision+1 <> NEW.revision
        OR NEW.payload->>'supersedes_sha256' <> NEW.supersedes_sha256
        OR (previous.payload->>'usable_at')::timestamptz >= (NEW.payload->>'usable_at')::timestamptz) IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_LABEL_PREDECESSOR_INVALID'; END IF;
    ELSIF NEW.supersedes_sha256 IS NOT NULL THEN RAISE EXCEPTION 'REAL_PLAYER_LABEL_PREDECESSOR_INVALID'; END IF;
  ELSIF NEW.kind='SCORECARD' THEN
    IF (schema_name <> 'qualified-real-player-point-scorecard-v1' OR NEW.payload->>'model_id' <> NEW.model_id
      OR NEW.payload->>'evaluation_classification' <> protocol->>'evaluation_classification') IS NOT FALSE THEN RAISE EXCEPTION 'REAL_PLAYER_SCORE_BINDING_INVALID'; END IF;
  ELSE RAISE EXCEPTION 'REAL_PLAYER_ARTIFACT_KIND_INVALID'; END IF;
  RETURN NEW;
END $$
"""


def upgrade() -> None:
    from dmf_pulse.player_lab.real_rights import real_source_registry, require_real_sources

    registry = real_source_registry()
    for row in registry.sources:
        require_real_sources((row.source,), now=datetime.now(UTC))
    body = json.dumps(registry.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    tag = "$dmf_" + hashlib.sha256(body.encode()).hexdigest()[:16] + "$"
    if tag in body:
        raise ValueError("source registry dollar delimiter collision")
    # SQLAlchemy text interprets colon-prefixed JSON values as bind parameters.
    # Encode the entire bounded metadata value, including arbitrary notes, as
    # UTF-8 hex. Neither SQL quoting nor driver bind parsing can reinterpret it.
    literal = "convert_from(decode('" + body.encode().hex() + "','hex'),'UTF8')::jsonb"
    op.execute(
        f"CREATE FUNCTION evaluation.real_authority() RETURNS jsonb LANGUAGE sql IMMUTABLE AS {tag} SELECT {literal} {tag}"
    )
    op.execute("DROP TRIGGER trg_research_source ON evaluation.qualified_source")
    op.execute(
        "CREATE TRIGGER trg_research_source BEFORE INSERT ON evaluation.qualified_source FOR EACH ROW WHEN (NEW.dataset_mode='SYNTHETIC') EXECUTE FUNCTION evaluation.guard_source()"
    )
    op.execute(SOURCE_GUARD)
    op.execute(
        "CREATE TRIGGER trg_research_real_source BEFORE INSERT ON evaluation.qualified_source FOR EACH ROW WHEN (NEW.dataset_mode='INDEPENDENTLY_QUALIFIED_REAL') EXECUTE FUNCTION evaluation.guard_real_source()"
    )
    for row in registry.sources:
        source_id = (
            "convert_from(decode('" + row.source.source_id.encode().hex() + "','hex'),'UTF8')"
        )
        source = (
            "convert_from(decode('"
            + json.dumps(row.source.model_dump(mode="json")).encode().hex()
            + "','hex'),'UTF8')::jsonb"
        )
        qualification = (
            "convert_from(decode('"
            + json.dumps(row.model_dump(mode="json")).encode().hex()
            + "','hex'),'UTF8')::jsonb"
        )
        op.execute(
            f"INSERT INTO evaluation.qualified_source(source_id,source_ref,qualification,dataset_mode) VALUES ({source_id},{source},{qualification},'INDEPENDENTLY_QUALIFIED_REAL')"
        )
    op.execute("DROP TRIGGER trg_research_artifact ON evaluation.research_artifact")
    op.execute(
        "CREATE TRIGGER trg_research_artifact BEFORE INSERT ON evaluation.research_artifact FOR EACH ROW WHEN (NEW.dataset_mode='SYNTHETIC') EXECUTE FUNCTION evaluation.guard_artifact()"
    )
    op.execute(ARTIFACT_GUARD)
    op.execute(
        "CREATE TRIGGER trg_research_real_artifact BEFORE INSERT ON evaluation.research_artifact FOR EACH ROW WHEN (NEW.dataset_mode='PROSPECTIVE_REAL') EXECUTE FUNCTION evaluation.guard_real_artifact()"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_real_player_deadline_population ON evaluation.research_artifact ((payload->>'protocol_sha256'),((payload->'population'->>'gameweek')::integer)) WHERE dataset_mode='PROSPECTIVE_REAL' AND payload->>'schema_version'='qualified-real-player-deadline-registration-v1'"
    )


def downgrade() -> None:
    # The immutable research record is never silently discarded on downgrade.
    connection = op.get_bind()
    from sqlalchemy import text

    if connection.execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM evaluation.research_artifact WHERE dataset_mode='PROSPECTIVE_REAL') OR EXISTS(SELECT 1 FROM evaluation.qualified_source WHERE dataset_mode='INDEPENDENTLY_QUALIFIED_REAL')"
        )
    ).scalar_one():
        raise ValueError("real research custody prevents destructive downgrade")
    op.execute("DROP INDEX evaluation.uq_real_player_deadline_population")
    for table, trigger in (
        ("research_artifact", "trg_research_real_artifact"),
        ("qualified_source", "trg_research_real_source"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON evaluation.{table}")
    for table, trigger, function in (
        ("research_artifact", "trg_research_artifact", "guard_artifact"),
        ("qualified_source", "trg_research_source", "guard_source"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON evaluation.{table}")
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE INSERT ON evaluation.{table} FOR EACH ROW EXECUTE FUNCTION evaluation.{function}()"
        )
    for function in ("guard_real_artifact", "guard_real_source", "real_authority"):
        op.execute(f"DROP FUNCTION evaluation.{function}()")
