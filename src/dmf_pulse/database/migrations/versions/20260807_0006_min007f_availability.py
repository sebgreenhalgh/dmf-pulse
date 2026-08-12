"""MIN-007F immutable availability registry and prediction persistence.

Revision ID: 20260807_0006
Revises: 20260803_0005
"""

from __future__ import annotations

from alembic import op

from dmf_pulse.data_model.tables import (
    conditional_minute_pmf,
    dataset_training_example,
    dataset_version,
    lineup_scenario,
    lineup_scenario_member,
    model_evaluation,
    model_version,
    player_minutes_projection,
    prediction_dependency,
    prediction_hard_eligibility,
    prediction_run,
    role_marginal,
)

revision = "20260807_0006"
down_revision = "20260803_0005"
branch_labels = None
depends_on = None

TABLES = (
    dataset_version,
    dataset_training_example,
    model_version,
    model_evaluation,
    prediction_run,
    prediction_dependency,
    prediction_hard_eligibility,
    role_marginal,
    conditional_minute_pmf,
    lineup_scenario,
    lineup_scenario_member,
    player_minutes_projection,
)

IMMUTABLE_TABLES = (
    "provenance.dataset_training_example",
    "provenance.model_version",
    "provenance.model_evaluation",
    "football.prediction_dependency",
    "football.prediction_hard_eligibility",
    "football.role_marginal",
    "football.conditional_minute_pmf",
    "football.lineup_scenario",
    "football.lineup_scenario_member",
    "football.player_minutes_projection",
)

DATASET_LIFECYCLE_FUNCTION = """
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
$$
"""

DATASET_LINEAGE_MUTATION_FUNCTION = """
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
$$
"""

PREDICTION_LIFECYCLE_FUNCTION = """
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
$$
"""

CORE_MUTATION_FUNCTION = """
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
$$
"""

FINAL_OUTPUT_MUTATION_FUNCTION = """
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
$$
"""


PMF_FUNCTION = """
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
$$
"""

PROJECTION_FUNCTION = """
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
$$
"""


CONFIDENCE_REASONS_FUNCTION = """
CREATE OR REPLACE FUNCTION football.validate_minutes_confidence_reasons(reasons varchar[])
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
  SELECT reasons IS NOT NULL
     AND COALESCE(array_ndims(reasons), 1) = 1
     AND NOT EXISTS (
       SELECT 1
         FROM unnest(reasons) AS reason
        WHERE reason IS NULL
           OR reason NOT IN (
             'HARD_INELIGIBLE_OVERRIDE',
             'NO_TARGET_TEAM_COMPETITIVE_HISTORY',
             'THIN_PLAYER_HISTORY',
             'NEW_SIGNING',
             'NEW_MANAGER_REGIME',
             'PROMOTED_TEAM_EARLY_REGIME',
             'BASELINE_MODEL_CAP_B'
           )
     )
     AND cardinality(reasons) = (
       SELECT count(DISTINCT reason) FROM unnest(reasons) AS reason
     )
$$
"""


CANONICAL_JSON_FUNCTION = """
CREATE OR REPLACE FUNCTION football.canonical_json_text(value jsonb)
RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
  kind text;
  rendered text;
BEGIN
  kind := jsonb_typeof(value);
  IF kind = 'object' THEN
    SELECT '{' || COALESCE(
      string_agg(to_jsonb(key)::text || ':' || football.canonical_json_text(entry), ','
                 ORDER BY key COLLATE "C"),
      ''
    ) || '}'
      INTO rendered
      FROM jsonb_each(value) AS item(key, entry);
    RETURN rendered;
  END IF;
  IF kind = 'array' THEN
    SELECT '[' || COALESCE(
      string_agg(football.canonical_json_text(entry), ',' ORDER BY ordinal),
      ''
    ) || ']'
      INTO rendered
      FROM jsonb_array_elements(value) WITH ORDINALITY AS item(entry, ordinal);
    RETURN rendered;
  END IF;
  RETURN value::text;
END
$$;

CREATE OR REPLACE FUNCTION football.canonical_json_sha256(value jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT encode(pg_catalog.sha256(convert_to(football.canonical_json_text(value), 'UTF8')), 'hex')
$$;

CREATE OR REPLACE FUNCTION football.render_final_probability(value numeric)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT to_char(value, 'FM999999999990.000000000000')
$$;

CREATE OR REPLACE FUNCTION football.render_final_minutes(value numeric)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT to_char(value, 'FM999999990.000000')
$$;

CREATE OR REPLACE FUNCTION football.render_final_as_of(value timestamptz)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT CASE
    WHEN date_trunc('second', value) = value
      THEN to_char(value AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    ELSE to_char(value AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  END
$$
"""

HALF_EVEN_FUNCTION = """
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
$$
"""

IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION football.reject_immutable_availability_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'IMMUTABLE_RECORD';
END
$$
"""

SCENARIO_FUNCTION = """
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
$$
"""

DATASET_COMPLETENESS_FUNCTION = """
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
$$
"""

MODEL_DATASET_FUNCTION = """
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
$$
"""

PREDICTION_COMPLETENESS_FUNCTION = """
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
$$
"""

FINAL_OUTPUT_COMPLETENESS_FUNCTION = """
CREATE OR REPLACE FUNCTION football.validate_final_output_complete()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  final_total integer;
  marginal_total integer;
  mismatch integer;
  model_family text;
  artifact_sha text;
  dataset_sha text;
  scenario_set_sha text;
  actual_players jsonb;
  result_body jsonb;
  actual_result jsonb;
  expected_final_sha text;
  expected_output_sha text;
  top_level_mismatch text;
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
  IF EXISTS (
    SELECT 1
      FROM football.player_minutes_projection AS projection
      LEFT JOIN football.role_marginal AS marginal
        ON marginal.prediction_run_id = projection.prediction_run_id
       AND marginal.player_id = projection.player_id
     WHERE projection.prediction_run_id = NEW.prediction_run_id
       AND (
         marginal.player_id IS NULL
         OR projection.position <> marginal.position
         OR projection.p_start <> marginal.p_start
         OR projection.p_bench <> marginal.p_bench
         OR projection.p_out <> marginal.p_out
       )
  ) THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'FINAL_OUTPUT_ROW_MISMATCH';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM football.player_minutes_projection AS projection
     WHERE projection.prediction_run_id = NEW.prediction_run_id
       AND (
         projection.p_start <> trunc(projection.p_start * 1000000000000) / 1000000000000
         OR projection.p_bench <> trunc(projection.p_bench * 1000000000000) / 1000000000000
         OR projection.p_out <> trunc(projection.p_out * 1000000000000) / 1000000000000
         OR projection.p_zero <> trunc(projection.p_zero * 1000000000000) / 1000000000000
         OR projection.p_60_plus <> trunc(projection.p_60_plus * 1000000000000) / 1000000000000
         OR projection.expected_minutes <> trunc(projection.expected_minutes * 1000000) / 1000000
         OR EXISTS (
           SELECT 1
             FROM unnest(projection.minute_pmf) AS minute_value
            WHERE minute_value <> trunc(minute_value * 1000000000000) / 1000000000000
         )
       )
  ) THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'FINAL_OUTPUT_SCALE_INVALID';
  END IF;
  SELECT model.model_family,
         model.artifact ->> 'artifact_sha256',
         COALESCE(dataset.source_dataset_sha256, dataset.dataset_semantic_sha256)
    INTO model_family, artifact_sha, dataset_sha
    FROM provenance.model_version AS model
    JOIN provenance.dataset_version AS dataset
      ON dataset.dataset_semantic_sha256 = NEW.dataset_version_sha256
   WHERE model.model_semantic_sha256 = NEW.model_version_sha256;
  IF model_family IS NULL OR artifact_sha IS NULL OR dataset_sha IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'FINAL_OUTPUT_PROVENANCE_INVALID';
  END IF;
  SELECT encode(
           pg_catalog.sha256(
             convert_to(
               COALESCE(string_agg(scenario.scenario_sha256, '' ORDER BY scenario.scenario_index), ''),
               'UTF8'
             )
           ),
           'hex'
         )
    INTO scenario_set_sha
    FROM football.lineup_scenario AS scenario
   WHERE scenario.prediction_run_id = NEW.prediction_run_id;
  SELECT jsonb_agg(player_payload ORDER BY player_id)
    INTO actual_players
    FROM (
      SELECT projection.player_id,
             player_body || jsonb_build_object(
               'projection_sha256', football.canonical_json_sha256(player_body)
             ) AS player_payload
        FROM football.player_minutes_projection AS projection
        CROSS JOIN LATERAL jsonb_build_object(
          'player_id', projection.player_id,
          'position', projection.position,
          'p_start', football.render_final_probability(projection.p_start),
          'p_bench', football.render_final_probability(projection.p_bench),
          'p_out_of_squad', football.render_final_probability(projection.p_out),
          'p_appearance', football.render_final_probability(1 - projection.p_zero),
          'p_zero_minutes', football.render_final_probability(projection.p_zero),
          'p_60_plus', football.render_final_probability(projection.p_60_plus),
          'expected_minutes', football.render_final_minutes(projection.expected_minutes),
          'minute_pmf', (
            SELECT jsonb_agg(football.render_final_probability(minute_value) ORDER BY ordinal)
              FROM unnest(projection.minute_pmf) WITH ORDINALITY AS pmf(minute_value, ordinal)
          ),
          'confidence_grade', projection.confidence_grade,
          'confidence_reasons', to_jsonb(projection.confidence_reasons)
        ) AS player_body
       WHERE projection.prediction_run_id = NEW.prediction_run_id
    ) AS persisted_player;
  result_body := jsonb_build_object(
    'schema_version', 'team-minutes-projection-v1',
    'fixture_id', NEW.fixture_id::text,
    'team_id', NEW.team_id::text,
    'as_of', football.render_final_as_of(NEW.as_of),
    'model_family', model_family,
    'dataset_sha256', dataset_sha,
    'model_artifact_sha256', artifact_sha,
    'sample_count', NEW.sample_count,
    'bench_size', NEW.bench_size,
    'bench_goalkeeper_slots', NEW.bench_goalkeeper_slots,
    'players', actual_players,
    'scenario_set_sha256', scenario_set_sha,
    'sum_p_start', football.render_final_probability((
      SELECT sum(projection.p_start)
        FROM football.player_minutes_projection AS projection
       WHERE projection.prediction_run_id = NEW.prediction_run_id
    )),
    'sum_p_bench', football.render_final_probability((
      SELECT sum(projection.p_bench)
        FROM football.player_minutes_projection AS projection
       WHERE projection.prediction_run_id = NEW.prediction_run_id
    )),
    'sum_p_out', football.render_final_probability((
      SELECT sum(projection.p_out)
        FROM football.player_minutes_projection AS projection
       WHERE projection.prediction_run_id = NEW.prediction_run_id
    ))
  );
  actual_result := result_body || jsonb_build_object(
    'result_sha256', football.canonical_json_sha256(result_body)
  );
  IF NEW.final_output_payload -> 'players' IS DISTINCT FROM actual_players THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'FINAL_OUTPUT_PLAYER_PAYLOAD_MISMATCH';
  END IF;
  IF (NEW.final_output_payload - ARRAY['players', 'result_sha256'])
       IS DISTINCT FROM (result_body - 'players') THEN
    SELECT string_agg(
             key || ': expected=' || entry::text || ', supplied=' || COALESCE(NEW.final_output_payload -> key, 'null'::jsonb)::text,
             ';' ORDER BY key
           )
      INTO top_level_mismatch
      FROM jsonb_each(result_body) AS item(key, entry)
     WHERE key <> 'players'
       AND entry IS DISTINCT FROM NEW.final_output_payload -> key;
    RAISE EXCEPTION USING
      ERRCODE = '23514',
      MESSAGE = 'FINAL_OUTPUT_TEAM_PAYLOAD_MISMATCH',
      DETAIL = COALESCE(top_level_mismatch, 'unknown top-level field');
  END IF;
  IF NEW.final_output_payload ->> 'result_sha256' <> actual_result ->> 'result_sha256' THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'FINAL_OUTPUT_RESULT_HASH_MISMATCH';
  END IF;
  IF NEW.final_output_payload IS DISTINCT FROM actual_result THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'FINAL_OUTPUT_PAYLOAD_MISMATCH';
  END IF;
  expected_final_sha := football.canonical_json_sha256(actual_result);
  IF NEW.final_output_semantic_sha256 <> expected_final_sha THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'FINAL_OUTPUT_SEMANTIC_HASH_MISMATCH';
  END IF;
  IF NEW.core_output_payload IS NULL
     OR jsonb_typeof(NEW.core_output_payload) <> 'object'
     OR NEW.core_output_payload -> 'role_marginals' IS NULL
     OR NEW.core_output_payload -> 'minute_pmfs' IS NULL
     OR NEW.core_output_payload -> 'scenarios' IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'FINAL_OUTPUT_CORE_INCOMPLETE';
  END IF;
  expected_output_sha := football.canonical_json_sha256(jsonb_build_object(
    'role_marginals', NEW.core_output_payload -> 'role_marginals',
    'minute_pmfs', NEW.core_output_payload -> 'minute_pmfs',
    'scenarios', NEW.core_output_payload -> 'scenarios',
    'final_projection', actual_result
  ));
  IF NEW.output_semantic_sha256 <> expected_output_sha THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'FINAL_OUTPUT_OUTPUT_HASH_MISMATCH';
  END IF;
  RETURN NULL;
END
$$
"""


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(PMF_FUNCTION)
    op.execute(HALF_EVEN_FUNCTION)
    op.execute(PROJECTION_FUNCTION)
    op.execute(CONFIDENCE_REASONS_FUNCTION)
    op.execute(CANONICAL_JSON_FUNCTION)
    for table in TABLES:
        table.create(bind=bind, checkfirst=False)
    op.execute(SCENARIO_FUNCTION)
    op.execute(DATASET_LIFECYCLE_FUNCTION)
    op.execute(DATASET_LINEAGE_MUTATION_FUNCTION)
    op.execute(PREDICTION_LIFECYCLE_FUNCTION)
    op.execute(CORE_MUTATION_FUNCTION)
    op.execute(FINAL_OUTPUT_MUTATION_FUNCTION)
    op.execute(DATASET_COMPLETENESS_FUNCTION)
    op.execute(MODEL_DATASET_FUNCTION)
    op.execute(PREDICTION_COMPLETENESS_FUNCTION)
    op.execute(FINAL_OUTPUT_COMPLETENESS_FUNCTION)
    op.execute(IMMUTABLE_FUNCTION)
    for index, table_name in enumerate(IMMUTABLE_TABLES):
        op.execute(
            f"CREATE TRIGGER trg_min007f_immutable_{index} "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change()"
        )
    op.execute(
        "CREATE TRIGGER trg_min007f_dataset_lifecycle "
        "BEFORE UPDATE ON provenance.dataset_version FOR EACH ROW "
        "EXECUTE FUNCTION provenance.validate_dataset_lifecycle()"
    )
    op.execute(
        "CREATE TRIGGER trg_min007f_dataset_lineage_freeze "
        "BEFORE INSERT OR UPDATE OR DELETE ON provenance.dataset_training_example "
        "FOR EACH ROW EXECUTE FUNCTION provenance.reject_complete_dataset_lineage_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_min007f_prediction_lifecycle "
        "BEFORE UPDATE ON football.prediction_run FOR EACH ROW "
        "EXECUTE FUNCTION football.validate_prediction_lifecycle()"
    )
    for index, table_name in enumerate(
        (
            "football.prediction_dependency",
            "football.prediction_hard_eligibility",
            "football.role_marginal",
            "football.conditional_minute_pmf",
            "football.lineup_scenario",
            "football.lineup_scenario_member",
        )
    ):
        op.execute(
            f"CREATE TRIGGER trg_min007f_core_freeze_{index} "
            f"BEFORE INSERT OR UPDATE OR DELETE ON {table_name} FOR EACH ROW "
            "EXECUTE FUNCTION football.reject_complete_core_mutation()"
        )
    op.execute(
        "CREATE TRIGGER trg_min007f_final_output_freeze "
        "BEFORE INSERT OR UPDATE OR DELETE ON football.player_minutes_projection "
        "FOR EACH ROW EXECUTE FUNCTION football.reject_frozen_final_output_mutation()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_min007f_scenario_parent "
        "AFTER INSERT OR UPDATE ON football.lineup_scenario "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION football.validate_lineup_scenario()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_min007f_scenario_member "
        "AFTER INSERT OR UPDATE OR DELETE ON football.lineup_scenario_member "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION football.validate_lineup_scenario()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_min007f_dataset_complete "
        "AFTER INSERT OR UPDATE ON provenance.dataset_version "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION provenance.validate_dataset_complete()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_min007f_model_dataset_complete "
        "AFTER INSERT OR UPDATE ON provenance.model_version "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION provenance.validate_model_dataset_complete()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_min007f_prediction_complete "
        "AFTER INSERT OR UPDATE ON football.prediction_run "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION football.validate_prediction_complete()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_min007f_final_output_complete "
        "AFTER UPDATE ON football.prediction_run "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION football.validate_final_output_complete()"
    )


def downgrade() -> None:
    for table_name in IMMUTABLE_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_min007f_immutable_{IMMUTABLE_TABLES.index(table_name)} ON {table_name}"
        )
    op.execute("DROP TRIGGER IF EXISTS trg_min007f_scenario_parent ON football.lineup_scenario")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_min007f_scenario_member ON football.lineup_scenario_member"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_min007f_dataset_complete ON provenance.dataset_version")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_min007f_model_dataset_complete ON provenance.model_version"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_min007f_prediction_complete ON football.prediction_run")
    op.execute("DROP TRIGGER IF EXISTS trg_min007f_dataset_lifecycle ON provenance.dataset_version")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_min007f_dataset_lineage_freeze ON provenance.dataset_training_example"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_min007f_prediction_lifecycle ON football.prediction_run")
    for index, table_name in enumerate(
        (
            "football.prediction_dependency",
            "football.prediction_hard_eligibility",
            "football.role_marginal",
            "football.conditional_minute_pmf",
            "football.lineup_scenario",
            "football.lineup_scenario_member",
        )
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_min007f_core_freeze_{index} ON {table_name}")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_min007f_final_output_freeze ON football.player_minutes_projection"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_min007f_final_output_complete ON football.prediction_run"
    )
    # Table CHECK constraints depend on the PMF/projection validator
    # functions, so remove the tables before dropping those functions.
    for table in reversed(TABLES):
        table.drop(bind=op.get_bind(), checkfirst=False)
    op.execute("DROP FUNCTION IF EXISTS football.validate_lineup_scenario()")
    op.execute("DROP FUNCTION IF EXISTS provenance.validate_dataset_complete()")
    op.execute("DROP FUNCTION IF EXISTS provenance.validate_model_dataset_complete()")
    op.execute("DROP FUNCTION IF EXISTS football.validate_prediction_complete()")
    op.execute("DROP FUNCTION IF EXISTS provenance.validate_dataset_lifecycle()")
    op.execute("DROP FUNCTION IF EXISTS provenance.reject_complete_dataset_lineage_mutation()")
    op.execute("DROP FUNCTION IF EXISTS football.validate_prediction_lifecycle()")
    op.execute("DROP FUNCTION IF EXISTS football.reject_complete_core_mutation()")
    op.execute("DROP FUNCTION IF EXISTS football.reject_frozen_final_output_mutation()")
    op.execute("DROP FUNCTION IF EXISTS football.validate_final_output_complete()")
    op.execute("DROP FUNCTION IF EXISTS football.render_final_as_of(timestamptz)")
    op.execute("DROP FUNCTION IF EXISTS football.render_final_minutes(numeric)")
    op.execute("DROP FUNCTION IF EXISTS football.render_final_probability(numeric)")
    op.execute("DROP FUNCTION IF EXISTS football.canonical_json_sha256(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS football.canonical_json_text(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS football.validate_minutes_confidence_reasons(varchar[])")
    op.execute("DROP FUNCTION IF EXISTS football.reject_immutable_availability_change()")
    op.execute(
        "DROP FUNCTION IF EXISTS football.validate_player_minutes_projection(numeric,numeric,numeric,numeric[],numeric,numeric,numeric)"
    )
    op.execute("DROP FUNCTION IF EXISTS football.validate_minute_pmf(numeric[],text)")
    op.execute("DROP FUNCTION IF EXISTS football.round_half_even_6(numeric)")
