"""Add standing-operation custody; preserve all original control identities."""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from dmf_pulse.data_model.tables import operator_journal

revision = "20261101_0010"
down_revision = "20261030_0009"
branch_labels = None
depends_on = None

GUARD = """
CREATE FUNCTION core.guard_operator_journal() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous core.operator_journal%ROWTYPE; expected_sequence integer := 0;
  expected_previous text := repeat('0',64); body jsonb;
BEGIN
  PERFORM 1 FROM core.refresh_control_ledger WHERE ledger_id=NEW.ledger_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'OPERATOR_ORIGINAL_LEDGER_REQUIRED'; END IF;
  SELECT * INTO previous FROM core.operator_journal WHERE ledger_id=NEW.ledger_id
    ORDER BY sequence DESC LIMIT 1;
  IF FOUND THEN
    expected_sequence := previous.sequence+1; expected_previous := previous.sha256;
    IF NEW.at<previous.at THEN RAISE EXCEPTION 'OPERATOR_CLOCK_REGRESSED'; END IF;
  END IF;
  body := jsonb_build_object('ledger_id',NEW.ledger_id,'sequence',NEW.sequence,
    'previous_sha256',NEW.previous_sha256,'at',NEW.payload->>'recorded_at',
    'kind',NEW.kind,'execution_key',NEW.execution_key,'payload',NEW.payload);
  IF (NEW.sequence=expected_sequence AND NEW.previous_sha256=expected_previous
      AND (NEW.payload->>'recorded_at')::timestamptz=NEW.at
      AND NEW.payload->>'recorded_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
      AND NEW.sha256=football.canonical_json_sha256(body)) IS NOT TRUE THEN
    RAISE EXCEPTION 'OPERATOR_JOURNAL_INVALID';
  END IF;
  IF NEW.kind IN ('SETTLEMENT','PUBLICATION') AND NOT EXISTS (
    SELECT 1 FROM core.operator_journal WHERE ledger_id=NEW.ledger_id
      AND execution_key=NEW.execution_key AND kind='ENROLL'
  ) THEN RAISE EXCEPTION 'OPERATOR_EVENT_ENROLLMENT_REQUIRED'; END IF;
  RETURN NEW;
END $$
"""


def upgrade() -> None:
    operator_journal.create(op.get_bind())
    op.execute(GUARD)
    op.execute(
        "CREATE TRIGGER trg_operator_journal_insert BEFORE INSERT ON core.operator_journal FOR EACH ROW EXECUTE FUNCTION core.guard_operator_journal()"
    )
    for operation in ("UPDATE OR DELETE", "TRUNCATE"):
        level = "STATEMENT" if operation == "TRUNCATE" else "ROW"
        name = "truncate" if operation == "TRUNCATE" else "immutable"
        op.execute(
            f"CREATE TRIGGER trg_operator_journal_{name} BEFORE {operation} ON core.operator_journal FOR EACH {level} EXECUTE FUNCTION core.reject_refresh_control_change()"
        )


def downgrade() -> None:
    # Empty test/install staging can roll back. Never remove a durable launch,
    # event marker, paid observation or publication from an operational database.
    bind = op.get_bind()
    if bind.execute(text("SELECT EXISTS (SELECT 1 FROM core.operator_journal)")).scalar_one():
        raise RuntimeError("OPERATOR_JOURNAL_DOWNGRADE_REQUIRES_SEPARATE_DATA_REVIEW")
    operator_journal.drop(bind)
    op.execute("DROP FUNCTION core.guard_operator_journal()")
