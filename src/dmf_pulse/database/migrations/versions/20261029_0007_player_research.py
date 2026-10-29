"""ACCEL-002 qualified immutable player research ledger.

Revision ID: 20261029_0007. Revises: 20260807_0006.
The v1 packaged source registry is a frozen migration dependency; new rights
qualifications require a later migration/registry version, never editing v1.
"""

from __future__ import annotations

import json
from importlib.resources import files

from alembic import op

from dmf_pulse.data_model.tables import (
    player_research_artifact,
    player_research_pair,
    player_research_source,
)
from dmf_pulse.ingestion.models import RightsCapability
from dmf_pulse.ingestion.rights import load_rights_profiles
from dmf_pulse.player_lab.actuals import FinalityContext
from dmf_pulse.player_lab.contracts import FinalPlayerOutcome, SourceRef
from dmf_pulse.player_lab.demo import synthetic_evaluation
from dmf_pulse.player_lab.evaluation import evaluate_players
from dmf_pulse.player_lab.rights import ingest_offline_actuals, profile_identity, require_sources

revision = "20261029_0007"
down_revision = "20260807_0006"
branch_labels = None
depends_on = None
TABLES = (player_research_source, player_research_artifact, player_research_pair)

IMMUTABLE = """
CREATE FUNCTION evaluation.reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='55000', MESSAGE='PLAYER_RESEARCH_IMMUTABLE'; END $$
"""

ARTIFACT_GUARD = """
CREATE FUNCTION evaluation.guard_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ref jsonb; qualified evaluation.qualified_source%ROWTYPE;
  parent evaluation.research_artifact%ROWTYPE; previous evaluation.research_artifact%ROWTYPE;
  forecast jsonb; key_body jsonb; target text; expected_refs jsonb;
BEGIN
  NEW.stored_at := clock_timestamp();
  IF NEW.payload->>'semantic_sha256' IS DISTINCT FROM NEW.artifact_sha256
     OR football.canonical_json_sha256(NEW.payload - 'semantic_sha256') <> NEW.artifact_sha256
     OR NEW.dataset_mode <> 'SYNTHETIC' THEN
    RAISE EXCEPTION 'PLAYER_RESEARCH_HASH_OR_MODE_INVALID';
  END IF;
  IF NEW.kind='EXPERIMENT' THEN
    IF NEW.source_refs <> '[]'::jsonb OR NOT EXISTS (
      SELECT 1 FROM evaluation.qualified_source s
      WHERE s.qualification->'qualified_experiment_sha256s' ? NEW.artifact_sha256
    ) THEN RAISE EXCEPTION 'EXPERIMENT_INVALID'; END IF;
    RETURN NEW;
  END IF;
  IF jsonb_typeof(NEW.source_refs) <> 'array' OR jsonb_array_length(NEW.source_refs)=0 THEN
    RAISE EXCEPTION 'PLAYER_SOURCE_REQUIRED'; END IF;
  FOR ref IN SELECT value FROM jsonb_array_elements(NEW.source_refs) LOOP
    SELECT * INTO qualified FROM evaluation.qualified_source WHERE source_id=ref->>'source_id';
    IF NOT FOUND OR qualified.dataset_mode <> 'SYNTHETIC' OR qualified.source_ref <> ref THEN
      RAISE EXCEPTION 'PLAYER_SOURCE_RIGHTS_BLOCKED'; END IF;
  END LOOP;
  IF NEW.kind IN ('FORECAST','SCORECARD') THEN
    SELECT * INTO parent FROM evaluation.research_artifact WHERE artifact_sha256=NEW.experiment_sha256;
    IF NOT FOUND OR parent.kind <> 'EXPERIMENT' THEN RAISE EXCEPTION 'EXPERIMENT_REQUIRED'; END IF;
  END IF;
  IF NEW.kind='FORECAST' THEN
    IF jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
       OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(NEW.payload) k)
          IS DISTINCT FROM ARRAY['forecast','recorded_at','semantic_sha256']::text[]
       OR jsonb_typeof(NEW.payload->'recorded_at') IS DISTINCT FROM 'string'
       OR NOT (NEW.payload->>'recorded_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$') THEN
      RAISE EXCEPTION 'PLAYER_FORECAST_CUSTODY_INVALID'; END IF;
    forecast := NEW.payload->'forecast'; key_body := forecast->'key';
    target := football.canonical_json_sha256(key_body);
    IF (forecast->>'semantic_sha256' <> football.canonical_json_sha256(forecast - 'semantic_sha256')
       OR NEW.target_id IS DISTINCT FROM target OR NEW.model_id IS DISTINCT FROM forecast->>'model_id'
       OR NEW.source_refs <> forecast->'sources'
       OR forecast->>'dataset_mode' <> NEW.dataset_mode
       OR NOT (parent.payload->'target_ids' ? target)
       OR NEW.model_id NOT IN (parent.payload->>'champion_id',parent.payload->>'challenger_id')
       OR (parent.payload->>'registered_at')::timestamptz > (forecast->>'generated_at')::timestamptz
       OR (forecast->>'generated_at')::timestamptz > (NEW.payload->>'recorded_at')::timestamptz
       OR (NEW.payload->>'recorded_at')::timestamptz >= (forecast->>'deadline_at')::timestamptz
       OR (forecast->>'information_cutoff')::timestamptz > (forecast->>'generated_at')::timestamptz) IS NOT FALSE THEN
      RAISE EXCEPTION 'PLAYER_FORECAST_CUSTODY_INVALID'; END IF;
    IF NOT EXISTS (
      SELECT 1 FROM evaluation.qualified_source s, jsonb_array_elements(NEW.source_refs) r
      WHERE s.source_id=r->>'source_id'
        AND s.qualification->'qualified_forecast_sha256s' ? (forecast->>'semantic_sha256')
    ) THEN RAISE EXCEPTION 'PLAYER_FORECAST_NOT_QUALIFIED'; END IF;
  ELSIF NEW.kind='LABEL' THEN
    target := football.canonical_json_sha256(NEW.payload->'key');
    IF NEW.target_id IS DISTINCT FROM target OR NEW.source_refs <> jsonb_build_array(NEW.payload->'source')
       OR NEW.payload->>'dataset_mode' <> NEW.dataset_mode
       OR NEW.payload->>'finalization_status' <> 'FINAL'
       OR (NEW.payload->>'revision')::integer <> NEW.revision
       OR (NEW.payload->>'finalized_at')::timestamptz > (NEW.payload->>'retrieved_at')::timestamptz
       OR (NEW.payload->>'retrieved_at')::timestamptz > (NEW.payload->>'usable_at')::timestamptz
       OR NOT EXISTS (SELECT 1 FROM evaluation.qualified_source s
         WHERE s.source_id=NEW.payload->'source'->>'source_id'
           AND s.qualification->'qualified_label_sha256s' ? NEW.artifact_sha256)
    THEN RAISE EXCEPTION 'PLAYER_LABEL_NOT_QUALIFIED'; END IF;
    IF NEW.revision=0 THEN
      IF NEW.supersedes_sha256 IS NOT NULL OR NEW.payload->>'supersedes_sha256' IS NOT NULL THEN
        RAISE EXCEPTION 'PLAYER_LABEL_PREDECESSOR_INVALID'; END IF;
    ELSE
      SELECT * INTO previous FROM evaluation.research_artifact WHERE artifact_sha256=NEW.supersedes_sha256;
      IF NOT FOUND OR previous.kind <> 'LABEL' OR previous.target_id <> target
         OR previous.revision+1 <> NEW.revision
         OR NEW.payload->>'supersedes_sha256' <> NEW.supersedes_sha256
         OR (previous.payload->>'usable_at')::timestamptz >= (NEW.payload->>'usable_at')::timestamptz THEN
        RAISE EXCEPTION 'PLAYER_LABEL_PREDECESSOR_INVALID'; END IF;
    END IF;
  ELSIF NEW.kind='SCORECARD' THEN
    IF NEW.payload->>'model_id' IS DISTINCT FROM NEW.model_id OR NOT EXISTS (
      SELECT 1 FROM evaluation.qualified_source s
      WHERE s.qualification->'qualified_scorecard_sha256s' ? NEW.artifact_sha256
    ) THEN RAISE EXCEPTION 'PLAYER_SCORE_INVALID'; END IF;
  END IF;
  RETURN NEW;
END $$
"""

PAIR_GUARD = """
CREATE FUNCTION evaluation.guard_score_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE score evaluation.research_artifact%ROWTYPE; pair record; expected_count integer;
  forecast evaluation.research_artifact%ROWTYPE; label evaluation.research_artifact%ROWTYPE;
  score_id text; pair_count integer;
BEGIN
  IF TG_TABLE_NAME='score_pair' THEN score_id := NEW.score_sha256;
  ELSE score_id := NEW.artifact_sha256; END IF;
  SELECT * INTO score FROM evaluation.research_artifact WHERE artifact_sha256=score_id;
  IF TG_TABLE_NAME='score_pair' AND score.kind IS DISTINCT FROM 'SCORECARD' THEN RAISE EXCEPTION 'PLAYER_SCORE_PARENT_INVALID'; END IF;
  IF score.kind <> 'SCORECARD' THEN RETURN NULL; END IF;
  expected_count := (score.payload->>'count')::integer;
  SELECT count(*) INTO pair_count FROM evaluation.score_pair WHERE score_sha256=score_id;
  IF (pair_count <> expected_count OR expected_count < 1
     OR jsonb_array_length(score.payload->'forecast_hashes') <> expected_count
     OR jsonb_array_length(score.payload->'label_hashes') <> expected_count) IS NOT FALSE THEN
    RAISE EXCEPTION 'PLAYER_SCORE_COHORT_INCOMPLETE'; END IF;
  FOR pair IN SELECT * FROM evaluation.score_pair WHERE score_sha256=score_id LOOP
    SELECT * INTO forecast FROM evaluation.research_artifact WHERE artifact_sha256=pair.forecast_sha256;
    SELECT * INTO label FROM evaluation.research_artifact WHERE artifact_sha256=pair.label_sha256;
    IF (forecast.kind <> 'FORECAST' OR label.kind <> 'LABEL' OR forecast.target_id <> pair.target_id
       OR label.target_id <> pair.target_id OR forecast.model_id <> score.model_id
       OR forecast.experiment_sha256 <> score.experiment_sha256
       OR NOT (score.payload->'forecast_hashes' ? pair.forecast_sha256)
       OR NOT (score.payload->'label_hashes' ? pair.label_sha256)
       OR NOT (score.source_refs @> forecast.source_refs AND score.source_refs @> label.source_refs)
       OR (label.payload->>'finalized_at')::timestamptz <= (forecast.payload->'forecast'->>'deadline_at')::timestamptz
       OR (label.payload->>'finalized_at')::timestamptz > (forecast.payload->'forecast'->>'label_finality_cutoff')::timestamptz) IS NOT FALSE THEN
      RAISE EXCEPTION 'PLAYER_SCORE_PAIR_INVALID'; END IF;
  END LOOP;
  RETURN NULL;
END $$
"""


def _qualifications() -> list[dict[str, object]]:
    root = files("dmf_pulse.player_lab.resources")
    registry = json.loads(root.joinpath("source-registry.json").read_text(encoding="utf-8"))
    profiles = load_rights_profiles()
    # No arbitrary caller-resealed experiment/report can become a synthetic
    # persistence envelope. Admit the exact owned original and corrected fixture
    # reports, computed by the accepted kernels, including every nested field.
    demonstration = synthetic_evaluation()
    correction_context = FinalityContext.model_validate_json(
        root.joinpath("context-gw2-revision1.json").read_bytes()
    )
    corrections = ingest_offline_actuals(
        root.joinpath("actuals-gw2-revision1.json").read_bytes(), correction_context
    ).labels
    for label in corrections:
        demonstration.custody.record_outcome(label)
    corrected_labels = (
        *corrections,
        *(label for label in demonstration.labels if label.key.gameweek != 2),
    )
    champion = tuple(
        item
        for item in demonstration.forecasts
        if item.forecast.model_id == demonstration.experiment.champion_id
    )
    corrected_report = evaluate_players(champion, corrected_labels, custody=demonstration.custody)
    records = []
    for source_id, item in registry["sources"].items():
        source = SourceRef.model_validate_json(
            json.dumps(
                {
                    "source_id": source_id,
                    "payload_sha256": item["payload_sha256"],
                    "profile_id": item["profile_id"],
                    "profile_sha256": profile_identity(profiles[item["profile_id"]]),
                    "observed_at": item["observed_at"],
                    "usable_at": item["usable_at"],
                }
            )
        )
        labels: tuple[FinalPlayerOutcome, ...] = ()
        require_sources((source,), RightsCapability.DERIVED_STORAGE)
        if "context_resource" in item:
            context = FinalityContext.model_validate_json(
                root.joinpath(item["context_resource"]).read_bytes()
            )
            labels = ingest_offline_actuals(
                root.joinpath(item["resource"]).read_bytes(), context
            ).labels
        records.append(
            {
                "source_id": source_id,
                "source_ref": source.model_dump(mode="json"),
                "dataset_mode": "SYNTHETIC",
                "qualification": {
                    "qualified_experiment_sha256s": [demonstration.experiment.semantic_sha256],
                    "qualified_scorecard_sha256s": [
                        demonstration.scorecard.semantic_sha256,
                        corrected_report.semantic_sha256,
                    ],
                    "qualified_forecast_sha256s": item.get("qualified_forecast_sha256s", []),
                    "qualified_label_sha256s": [label.semantic_sha256 for label in labels],
                },
            }
        )
    return records


def upgrade() -> None:
    op.execute("CREATE SCHEMA evaluation")
    for table in TABLES:
        table.create(op.get_bind())
    records = _qualifications()
    for record in records:
        source_id = str(record["source_id"]).replace("'", "''")
        source_ref = json.dumps(record["source_ref"]).replace("'", "''")
        qualification = json.dumps(record["qualification"]).replace("'", "''")
        op.execute(
            f"INSERT INTO evaluation.qualified_source(source_id,source_ref,qualification,dataset_mode) VALUES ('{source_id}','{source_ref}'::jsonb,'{qualification}'::jsonb,'SYNTHETIC')"
        )
    # Freeze the accepted registry into SQL; direct SQL cannot invent an ALLOW row.
    allowed = json.dumps(records, sort_keys=True, separators=(",", ":")).replace("'", "''")
    op.execute(f"""CREATE FUNCTION evaluation.guard_source() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN IF NOT ('{allowed}'::jsonb @> jsonb_build_array(to_jsonb(NEW))) THEN
      RAISE EXCEPTION 'PLAYER_SOURCE_QUALIFICATION_REQUIRED'; END IF; RETURN NEW; END $$""")
    op.execute(IMMUTABLE)
    op.execute(ARTIFACT_GUARD)
    op.execute(PAIR_GUARD)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER trg_research_immutable_{table.name} BEFORE UPDATE OR DELETE ON evaluation.{table.name} FOR EACH ROW EXECUTE FUNCTION evaluation.reject_change()"
        )
    op.execute(
        "CREATE TRIGGER trg_research_source BEFORE INSERT ON evaluation.qualified_source FOR EACH ROW EXECUTE FUNCTION evaluation.guard_source()"
    )
    op.execute(
        "CREATE TRIGGER trg_research_artifact BEFORE INSERT ON evaluation.research_artifact FOR EACH ROW EXECUTE FUNCTION evaluation.guard_artifact()"
    )
    for table, name in ((player_research_artifact, "artifact"), (player_research_pair, "pair")):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_research_complete_{name} AFTER INSERT ON evaluation.{table.name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION evaluation.guard_score_complete()"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        table.drop(op.get_bind())
    for name in ("guard_score_complete", "guard_artifact", "guard_source", "reject_change"):
        op.execute(f"DROP FUNCTION evaluation.{name}()")
    op.execute("DROP SCHEMA evaluation")
