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
    "provenance.dataset_version",
    "provenance.dataset_training_example",
    "provenance.model_version",
    "provenance.model_evaluation",
    "football.prediction_run",
    "football.prediction_dependency",
    "football.prediction_hard_eligibility",
    "football.role_marginal",
    "football.conditional_minute_pmf",
    "football.lineup_scenario",
    "football.lineup_scenario_member",
    "football.player_minutes_projection",
)


PMF_FUNCTION = """
CREATE OR REPLACE FUNCTION football.validate_minute_pmf(p_values numeric[], requested_role text)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  value numeric;
  total numeric := 0;
BEGIN
  IF p_values IS NULL OR array_ndims(p_values) <> 1 OR cardinality(p_values) <> 91
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
  IF start_probability < 0 OR start_probability > 1
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
  RETURN sixty_plus_probability = tail_value AND round(expected, 6) = round(mean_value, 6);
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
  RETURN NULL;
END
$$
"""


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(PMF_FUNCTION)
    op.execute(PROJECTION_FUNCTION)
    for table in TABLES:
        table.create(bind=bind, checkfirst=False)
    op.execute(SCENARIO_FUNCTION)
    op.execute(IMMUTABLE_FUNCTION)
    for index, table_name in enumerate(IMMUTABLE_TABLES):
        op.execute(
            f"CREATE TRIGGER trg_min007f_immutable_{index} "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION football.reject_immutable_availability_change()"
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


def downgrade() -> None:
    for table_name in IMMUTABLE_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_min007f_immutable_{IMMUTABLE_TABLES.index(table_name)} ON {table_name}"
        )
    op.execute("DROP TRIGGER IF EXISTS trg_min007f_scenario_parent ON football.lineup_scenario")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_min007f_scenario_member ON football.lineup_scenario_member"
    )
    # Table CHECK constraints depend on the PMF/projection validator
    # functions, so remove the tables before dropping those functions.
    for table in reversed(TABLES):
        table.drop(bind=op.get_bind(), checkfirst=False)
    op.execute("DROP FUNCTION IF EXISTS football.validate_lineup_scenario()")
    op.execute("DROP FUNCTION IF EXISTS football.reject_immutable_availability_change()")
    op.execute(
        "DROP FUNCTION IF EXISTS football.validate_player_minutes_projection(numeric,numeric,numeric,numeric[],numeric,numeric,numeric)"
    )
    op.execute("DROP FUNCTION IF EXISTS football.validate_minute_pmf(numeric[],text)")
