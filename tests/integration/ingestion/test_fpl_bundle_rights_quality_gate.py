"""Database-enforced FPL bundle rights and quality remediation proofs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    competition,
    season,
    source_bundle,
    source_bundle_member,
    source_snapshot,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.parser import FplResource, parse_fpl_payload
from dmf_pulse.ingestion.fpl.persistence import FplPersistence
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    FplIngestionService,
    FplReplayRequest,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _replay(root: Path, scenario: str):
    return FplIngestionService(repository_root=root).replay(
        FplReplayRequest(
            fixture_set=root / "fixtures/fpl/FPL-004",
            scenario=scenario,
            rights_profile_id="synthetic_test_v1",
            database_url_ref=DATABASE_REF,
        )
    )


def _copy_bundle(
    session: Session,
    *,
    snapshot_ids: tuple[UUID, UUID],
    manifest_character: str,
    rights_profiles: list[dict[str, str]],
    quality_status: str,
    cutoff: datetime,
) -> None:
    competition_id = session.scalar(select(competition.c.competition_id))
    season_id = session.scalar(select(season.c.season_id))
    snapshots = {
        row.resource: row
        for row in session.execute(
            select(
                source_snapshot.c.source_snapshot_id,
                source_snapshot.c.resource,
                source_snapshot.c.rights_profile_record_id,
                source_snapshot.c.envelope_sha256,
            ).where(source_snapshot.c.source_snapshot_id.in_(snapshot_ids))
        )
    }
    profile_ids = {row.rights_profile_record_id for row in snapshots.values()}
    assert len(profile_ids) == 1
    profile_id = profile_ids.pop()
    assert isinstance(competition_id, UUID)
    assert isinstance(season_id, UUID)
    assert isinstance(profile_id, UUID)
    bundle_id = session.execute(
        insert(source_bundle)
        .values(
            bundle_type="FPL_BOOTSTRAP_FIXTURES",
            competition_id=competition_id,
            season_id=season_id,
            information_cutoff=cutoff,
            created_at=cutoff,
            rights_profiles=rights_profiles,
            rights_profile_record_id=profile_id,
            adapter_version="fpl-reference-v1",
            contract_version="fpl-reference-v1",
            quality_status=quality_status,
            semantic_sha256="a" * 64,
            manifest_sha256=manifest_character * 64,
            config_sha256="b" * 64,
        )
        .returning(source_bundle.c.source_bundle_id)
    ).scalar_one()
    for role, resource in (("BOOTSTRAP", "bootstrap"), ("FIXTURES", "fixtures")):
        snapshot = snapshots[resource]
        usable_at = session.scalar(
            text(
                "SELECT usable_at FROM provenance.source_snapshot_lifecycle "
                "WHERE source_snapshot_id = :snapshot_id"
            ),
            {"snapshot_id": snapshot.source_snapshot_id},
        )
        session.execute(
            insert(source_bundle_member).values(
                source_bundle_id=bundle_id,
                source_snapshot_id=snapshot.source_snapshot_id,
                rights_profile_record_id=profile_id,
                role=role,
                usable_at=usable_at,
                payload_semantic_sha256="c" * 64,
                envelope_sha256=snapshot.envelope_sha256,
                lifecycle_sha256="d" * 64,
                schema_drift={},
            )
        )


def _freeze_post_cutoff_pair(
    session: Session,
    root: Path,
    *,
    bootstrap_snapshot_id: UUID,
    fixtures_snapshot_id: UUID,
) -> None:
    fixture_root = root / "fixtures/fpl/FPL-004/post_cutoff"
    bootstrap = parse_fpl_payload(
        FplResource.BOOTSTRAP,
        (fixture_root / "bootstrap.json").read_bytes(),
    )
    fixtures = parse_fpl_payload(
        FplResource.FIXTURES,
        (fixture_root / "fixtures.json").read_bytes(),
    )
    competition_id = session.scalar(select(competition.c.competition_id))
    season_id = session.scalar(select(season.c.season_id))
    assert isinstance(competition_id, UUID)
    assert isinstance(season_id, UUID)
    FplPersistence(
        session,
        captured_at=datetime(2026, 8, 21, 17, 31, tzinfo=UTC),
        competition_key="SYNTHETIC_PL",
        season_code="2026/27",
        bootstrap_snapshot_id=bootstrap_snapshot_id,
        fixtures_snapshot_id=fixtures_snapshot_id,
    ).freeze_bundle(
        competition_id=competition_id,
        season_id=season_id,
        information_cutoff=datetime(2026, 8, 21, 18, tzinfo=UTC),
        bootstrap=bootstrap,
        fixtures=fixtures,
        config_sha256="a" * 64,
        mapping_plan_sha256="b" * 64,
    )


def test_bundle_rights_are_relational_immutable_and_cannot_be_caller_claimed(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    outcome = _replay(repository_root, "happy_path")
    assert outcome.result.source_bundle is not None
    bundle = outcome.result.source_bundle
    snapshot_ids = tuple(member.source_snapshot_id for member in bundle.members)
    assert len(snapshot_ids) == 2

    with (
        pytest.raises(DBAPIError, match="immutable"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            update(source_bundle)
            .where(source_bundle.c.source_bundle_id == bundle.bundle_id)
            .values(quality_status="PASS")
        )

    with (
        pytest.raises(DBAPIError, match="BUNDLE_RIGHTS_BLOCKED"),
        postgres_session_factory.begin() as session,
    ):
        _copy_bundle(
            session,
            snapshot_ids=snapshot_ids,  # type: ignore[arg-type]
            manifest_character="1",
            rights_profiles=[{"id": "caller_claim", "version": "9.9.9"}],
            quality_status="PASS_WITH_WARNINGS",
            cutoff=datetime(2026, 8, 21, 17, 30, tzinfo=UTC),
        )


def test_open_p1_member_issue_blocks_deferred_bundle_publication(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    outcome = _replay(repository_root, "post_cutoff")
    assert outcome.result.source_bundle is None
    snapshot_ids = {
        resource.resource: resource.source_snapshot_id for resource in outcome.result.resources
    }
    assert set(snapshot_ids) == {"bootstrap", "fixtures"}

    with postgres_session_factory.begin() as session:
        with pytest.raises(IngestionError) as raised:
            _freeze_post_cutoff_pair(
                session,
                repository_root,
                bootstrap_snapshot_id=snapshot_ids["bootstrap"],
                fixtures_snapshot_id=snapshot_ids["fixtures"],
            )
        assert raised.value.code == "QUALITY_BLOCKED"
        assert (
            raised.value.message == "bundle publication is blocked by authoritative quality issues"
        )

    with (
        pytest.raises(DBAPIError, match="BUNDLE_QUALITY_BLOCKED"),
        postgres_session_factory.begin() as session,
    ):
        _copy_bundle(
            session,
            snapshot_ids=(snapshot_ids["bootstrap"], snapshot_ids["fixtures"]),
            manifest_character="2",
            rights_profiles=[{"id": "synthetic_test_v1", "version": "1.0.0"}],
            quality_status="PASS",
            cutoff=datetime(2026, 8, 21, 18, tzinfo=UTC),
        )


def test_missing_persisted_derived_storage_decision_blocks_refreeze(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    outcome = _replay(repository_root, "post_cutoff")
    snapshot_ids = {item.resource: item.source_snapshot_id for item in outcome.result.resources}
    assert set(snapshot_ids) == {"bootstrap", "fixtures"}

    with postgres_session_factory.begin() as session:
        existing_bundle_ids = set(session.scalars(select(source_bundle.c.source_bundle_id)))
        session.execute(text("TRUNCATE TABLE provenance.rights_decision"))
        with pytest.raises(IngestionError) as raised:
            _freeze_post_cutoff_pair(
                session,
                repository_root,
                bootstrap_snapshot_id=snapshot_ids["bootstrap"],
                fixtures_snapshot_id=snapshot_ids["fixtures"],
            )
        assert raised.value.code == "RIGHTS_BLOCKED"
        assert raised.value.message == "bundle publication lacks authoritative rights approval"
        assert set(session.scalars(select(source_bundle.c.source_bundle_id))) == existing_bundle_ids
