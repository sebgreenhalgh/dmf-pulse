"""Bind FPL bundles to authoritative rights and persisted quality.

Revision ID: 20260725_0003
Revises: 20260724_0002
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260725_0003"
down_revision: str | None = "20260724_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPGRADE_STATEMENTS = (
    "DROP TRIGGER trg_source_bundle_immutable ON provenance.source_bundle",
    "DROP TRIGGER trg_source_bundle_member_immutable ON provenance.source_bundle_member",
    "ALTER TABLE provenance.source_bundle ADD COLUMN rights_profile_record_id uuid",
    "ALTER TABLE provenance.source_bundle_member ADD COLUMN rights_profile_record_id uuid",
    """
    UPDATE provenance.source_bundle_member AS member
    SET rights_profile_record_id = snapshot.rights_profile_record_id
    FROM provenance.source_snapshot AS snapshot
    WHERE snapshot.source_snapshot_id = member.source_snapshot_id
    """,
    """
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
    WHERE candidate.source_bundle_id = bundle.source_bundle_id
    """,
    """
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
    $$
    """,
    "ALTER TABLE provenance.source_bundle ALTER COLUMN rights_profile_record_id SET NOT NULL",
    "ALTER TABLE provenance.source_bundle_member ALTER COLUMN rights_profile_record_id SET NOT NULL",
    """
    ALTER TABLE provenance.source_bundle
      ADD CONSTRAINT fk_source_bundle_rights_profile
      FOREIGN KEY (rights_profile_record_id)
      REFERENCES provenance.rights_profile(rights_profile_record_id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE provenance.source_bundle
      ADD CONSTRAINT uq_source_bundle_rights_profile
      UNIQUE (source_bundle_id, rights_profile_record_id)
    """,
    """
    ALTER TABLE provenance.source_bundle_member
      ADD CONSTRAINT fk_source_bundle_member_bundle_rights
      FOREIGN KEY (source_bundle_id, rights_profile_record_id)
      REFERENCES provenance.source_bundle(source_bundle_id, rights_profile_record_id)
      ON DELETE RESTRICT
    """,
    """
    ALTER TABLE provenance.source_bundle_member
      ADD CONSTRAINT fk_source_bundle_member_snapshot_rights
      FOREIGN KEY (source_snapshot_id, rights_profile_record_id)
      REFERENCES provenance.source_snapshot(source_snapshot_id, rights_profile_record_id)
      ON DELETE RESTRICT
    """,
    """
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
    $$
    """,
    """
    CREATE TRIGGER trg_data_quality_bundle_lock
    BEFORE INSERT OR UPDATE ON core.data_quality_issue
    FOR EACH ROW EXECUTE FUNCTION provenance.lock_bundle_quality_subject()
    """,
    """
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
    $$
    """,
    """
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
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_source_bundle_publication_guard
    AFTER INSERT ON provenance.source_bundle
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_source_bundle_publication()
    """,
    """
    CREATE CONSTRAINT TRIGGER trg_source_bundle_member_publication_guard
    AFTER INSERT ON provenance.source_bundle_member
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION provenance.guard_source_bundle_publication()
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
)


DOWNGRADE_STATEMENTS = (
    "DROP TRIGGER trg_source_bundle_member_publication_guard ON provenance.source_bundle_member",
    "DROP TRIGGER trg_source_bundle_publication_guard ON provenance.source_bundle",
    "DROP FUNCTION provenance.guard_source_bundle_publication()",
    "DROP TRIGGER trg_data_quality_bundle_lock ON core.data_quality_issue",
    "DROP FUNCTION provenance.lock_bundle_quality_subject()",
    "DROP TRIGGER trg_source_bundle_member_immutable ON provenance.source_bundle_member",
    "DROP TRIGGER trg_source_bundle_immutable ON provenance.source_bundle",
    "ALTER TABLE provenance.source_bundle_member DROP CONSTRAINT fk_source_bundle_member_snapshot_rights",
    "ALTER TABLE provenance.source_bundle_member DROP CONSTRAINT fk_source_bundle_member_bundle_rights",
    "ALTER TABLE provenance.source_bundle DROP CONSTRAINT uq_source_bundle_rights_profile",
    "ALTER TABLE provenance.source_bundle DROP CONSTRAINT fk_source_bundle_rights_profile",
    "ALTER TABLE provenance.source_bundle_member DROP COLUMN rights_profile_record_id",
    "ALTER TABLE provenance.source_bundle DROP COLUMN rights_profile_record_id",
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
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
