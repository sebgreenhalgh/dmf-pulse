"""Canonical append-only private-refresh control metadata.

Revision ID: 20261029_0008. Revises: 20261029_0007.
No provider response, manager fact, credential, forecast or approval is seeded.
"""

from __future__ import annotations

from alembic import op

from dmf_pulse.data_model.tables import refresh_control_event, refresh_control_ledger

revision = "20261029_0008"
down_revision = "20261029_0007"
branch_labels = None
depends_on = None

GUARD = """
CREATE FUNCTION core.guard_refresh_control() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE binding core.refresh_control_ledger%ROWTYPE;
  previous core.refresh_control_event%ROWTYPE;
  expected_sequence integer := 0;
  expected_previous text := repeat('0',64);
  common_keys text[] := ARRAY['kind','at','reservation_id','ledger_id','sequence','previous_sha256','sha256'];
  extra_keys text[]; actual_keys text[]; expected_keys text[]; field text;
BEGIN
  IF TG_TABLE_NAME='refresh_control_ledger' THEN
    IF NEW.binding_sha256 IS DISTINCT FROM football.canonical_json_sha256(jsonb_build_object(
      'ledger_id',NEW.ledger_id,'account_sha256',NEW.account_sha256,'schema_version',NEW.schema_version
    )) THEN RAISE EXCEPTION 'REFRESH_CONTROL_BINDING_INVALID'; END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO binding FROM core.refresh_control_ledger
    WHERE ledger_id=NEW.ledger_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'REFRESH_CONTROL_BINDING_REQUIRED'; END IF;
  IF NEW.kind='RESERVATION' THEN
    extra_keys := ARRAY['grant_sha256','approval_sha256','account_sha256','authorization_sha256','day','period'];
  ELSIF NEW.kind='CLAIM' THEN extra_keys := ARRAY['worker_sha256'];
  ELSIF NEW.kind='CHECK' THEN extra_keys := ARRAY[]::text[];
  ELSIF NEW.kind='ATTEMPT' THEN extra_keys := ARRAY['route_sha256'];
  ELSE RAISE EXCEPTION 'REFRESH_CONTROL_KIND_INVALID'; END IF;
  SELECT array_agg(key ORDER BY key) INTO actual_keys FROM jsonb_object_keys(NEW.payload) key;
  SELECT array_agg(key ORDER BY key) INTO expected_keys FROM unnest(common_keys || extra_keys) key;
  IF (actual_keys=expected_keys
      AND jsonb_typeof(NEW.payload->'sequence')='number'
      AND NEW.payload->>'sequence' ~ '^(0|[1-9][0-9]*)$'
      AND (NEW.payload->>'sequence')::integer=NEW.sequence
      AND NEW.payload->>'ledger_id'=NEW.ledger_id
      AND NEW.payload->>'kind'=NEW.kind
      AND NEW.payload->>'sha256'=NEW.sha256
      AND NEW.payload->>'previous_sha256'=NEW.previous_sha256
      AND jsonb_typeof(NEW.payload->'at')='string'
      AND length(NEW.payload->>'at')<=40
      AND NEW.payload->>'at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
      AND (NEW.payload->>'at')::timestamptz=NEW.at
      AND NEW.sha256=football.canonical_json_sha256(NEW.payload-'sha256')) IS NOT TRUE THEN
    RAISE EXCEPTION 'REFRESH_CONTROL_EVENT_INVALID';
  END IF;
  FOREACH field IN ARRAY actual_keys LOOP
    IF field NOT IN ('kind','at','sequence','day','period') AND (
      jsonb_typeof(NEW.payload->field)='string' AND NEW.payload->>field ~ '^[0-9a-f]{64}$'
    ) IS NOT TRUE THEN RAISE EXCEPTION 'REFRESH_CONTROL_FIELD_INVALID'; END IF;
  END LOOP;
  SELECT * INTO previous FROM core.refresh_control_event WHERE ledger_id=NEW.ledger_id
    ORDER BY sequence DESC LIMIT 1;
  IF FOUND THEN
    expected_sequence := previous.sequence+1; expected_previous := previous.sha256;
    IF NEW.at<previous.at THEN RAISE EXCEPTION 'REFRESH_CONTROL_CLOCK_REGRESSED'; END IF;
  END IF;
  IF NEW.sequence<>expected_sequence OR NEW.previous_sha256<>expected_previous THEN
    RAISE EXCEPTION 'REFRESH_CONTROL_CHAIN_INVALID'; END IF;
  IF NEW.kind='RESERVATION' THEN
    IF (NEW.payload->>'account_sha256'=binding.account_sha256
        AND NEW.payload->>'day'=(NEW.at AT TIME ZONE 'UTC')::date::text
        AND jsonb_typeof(NEW.payload->'period')='string'
        AND length(NEW.payload->>'period')<=40
        AND NEW.payload->>'period' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
        AND (NEW.payload->>'period')::timestamptz<=NEW.at) IS NOT TRUE
      OR EXISTS (SELECT 1 FROM core.refresh_control_event WHERE ledger_id=NEW.ledger_id
        AND payload->>'reservation_id'=NEW.payload->>'reservation_id') THEN
      RAISE EXCEPTION 'REFRESH_CONTROL_RESERVATION_INVALID'; END IF;
  ELSE
    IF NOT EXISTS (SELECT 1 FROM core.refresh_control_event WHERE ledger_id=NEW.ledger_id
      AND kind='RESERVATION' AND payload->>'reservation_id'=NEW.payload->>'reservation_id') THEN
      RAISE EXCEPTION 'REFRESH_CONTROL_RESERVATION_REQUIRED'; END IF;
    IF NEW.kind='CLAIM' THEN
      IF EXISTS (SELECT 1 FROM core.refresh_control_event WHERE ledger_id=NEW.ledger_id
        AND kind='CLAIM' AND payload->>'reservation_id'=NEW.payload->>'reservation_id') THEN
        RAISE EXCEPTION 'REFRESH_CONTROL_ALREADY_CLAIMED'; END IF;
    ELSIF NOT EXISTS (SELECT 1 FROM core.refresh_control_event WHERE ledger_id=NEW.ledger_id
      AND kind='CLAIM' AND payload->>'reservation_id'=NEW.payload->>'reservation_id') THEN
      RAISE EXCEPTION 'REFRESH_CONTROL_CLAIM_REQUIRED'; END IF;
  END IF;
  RETURN NEW;
END $$
"""

IMMUTABLE = """
CREATE FUNCTION core.reject_refresh_control_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'REFRESH_CONTROL_APPEND_ONLY'; END $$
"""


def upgrade() -> None:
    bind = op.get_bind()
    refresh_control_ledger.create(bind)
    refresh_control_event.create(bind)
    op.execute(GUARD)
    op.execute(IMMUTABLE)
    for name in ("ledger", "event"):
        table = f"core.refresh_control_{name}"
        op.execute(
            f"CREATE TRIGGER trg_refresh_control_{name}_insert BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION core.guard_refresh_control()"
        )
        op.execute(
            f"CREATE TRIGGER trg_refresh_control_{name}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION core.reject_refresh_control_change()"
        )
        op.execute(
            f"CREATE TRIGGER trg_refresh_control_{name}_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION core.reject_refresh_control_change()"
        )


def downgrade() -> None:
    bind = op.get_bind()
    refresh_control_event.drop(bind)
    refresh_control_ledger.drop(bind)
    op.execute("DROP FUNCTION core.guard_refresh_control()")
    op.execute("DROP FUNCTION core.reject_refresh_control_change()")
