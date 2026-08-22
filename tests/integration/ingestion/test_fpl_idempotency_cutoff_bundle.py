"""PostgreSQL proofs for canonical idempotency, history, and source cutoffs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    competition,
    data_quality_issue,
    external_identifier,
    fixture,
    fixture_gameweek_assignment,
    fixture_observation,
    fixture_revision,
    gameweek,
    gameweek_observation,
    player,
    player_observation,
    player_season,
    raw_blob,
    season,
    source_bundle,
    source_bundle_member,
    source_snapshot,
    team,
    team_observation,
    team_season,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.config import effective_config_sha256
from dmf_pulse.ingestion.fpl.persistence import FplPersistence
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    DEFAULT_INFORMATION_CUTOFF,
    FplImportRequest,
    FplIngestionService,
    FplOperationOutcome,
    FplReplayRequest,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _count(session: Session, table: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def _replay(
    service: FplIngestionService,
    fixture_root: Path,
    scenario: str,
) -> FplOperationOutcome:
    return service.replay(
        FplReplayRequest(
            fixture_set=fixture_root,
            scenario=scenario,
            database_url_ref=DATABASE_REF,
        )
    )


def test_same_payload_creates_new_envelopes_but_no_duplicate_semantic_fact(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    fixture_root = repository_root / "fixtures" / "fpl" / "FPL-004"
    service = FplIngestionService(repository_root=repository_root)

    first = _replay(service, fixture_root, "happy_path")
    second = _replay(service, fixture_root, "happy_path")

    assert first.exit_code == second.exit_code == 0
    assert first.result.source_bundle is not None
    assert second.result.source_bundle is not None
    assert second.result.source_bundle.bundle_id != first.result.source_bundle.bundle_id
    assert second.result.source_bundle.semantic_sha256 == first.result.source_bundle.semantic_sha256
    assert second.result.canonical_effects["created"] == {"source_bundle": 1}
    assert second.result.canonical_effects["changed"] == {}

    with postgres_session_factory() as session:
        assert set(session.scalars(select(source_bundle.c.config_sha256))) == {
            effective_config_sha256()
        }
        assert {
            "competition": _count(session, competition),
            "fixture": _count(session, fixture),
            "fixture_assignment": _count(session, fixture_gameweek_assignment),
            "fixture_observation": _count(session, fixture_observation),
            "fixture_revision": _count(session, fixture_revision),
            "gameweek": _count(session, gameweek),
            "gameweek_observation": _count(session, gameweek_observation),
            "player": _count(session, player),
            "player_observation": _count(session, player_observation),
            "player_season": _count(session, player_season),
            "raw_content": _count(session, raw_blob),
            "season": _count(session, season),
            "source_bundle": _count(session, source_bundle),
            "source_bundle_member": _count(session, source_bundle_member),
            "source_snapshot": _count(session, source_snapshot),
            "team": _count(session, team),
            "team_observation": _count(session, team_observation),
            "team_season": _count(session, team_season),
        } == {
            "competition": 1,
            "fixture": 1,
            "fixture_assignment": 1,
            "fixture_observation": 1,
            "fixture_revision": 1,
            "gameweek": 2,
            "gameweek_observation": 2,
            "player": 4,
            "player_observation": 4,
            "player_season": 4,
            "raw_content": 2,
            "season": 1,
            "source_bundle": 2,
            "source_bundle_member": 4,
            "source_snapshot": 4,
            "team": 2,
            "team_observation": 2,
            "team_season": 2,
        }
        snapshot_ids = set(session.scalars(select(source_snapshot.c.source_snapshot_id)))
        assert len(snapshot_ids) == 4
        assert {
            first.result.source_bundle.members[0].source_snapshot_id,
            first.result.source_bundle.members[1].source_snapshot_id,
        }.issubset(snapshot_ids)
        assert {
            second.result.source_bundle.members[0].source_snapshot_id,
            second.result.source_bundle.members[1].source_snapshot_id,
        }.isdisjoint(
            {
                first.result.source_bundle.members[0].source_snapshot_id,
                first.result.source_bundle.members[1].source_snapshot_id,
            }
        )


def test_reverted_values_append_history_and_become_current_with_new_exact_bundle_lineage(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    fixture_root = repository_root / "fixtures/fpl/FPL-004"
    service = FplIngestionService(repository_root=repository_root)
    original = _replay(service, fixture_root, "happy_path")
    changed = _replay(service, fixture_root, "changed_snapshot")
    reverted_at = datetime(2026, 8, 21, 17, 20, tzinfo=UTC)
    reverted = FplIngestionService(
        repository_root=repository_root,
        clock=lambda: reverted_at,
    ).import_pair(
        FplImportRequest(
            bootstrap_path=fixture_root / "happy_path/bootstrap.json",
            fixtures_path=fixture_root / "happy_path/fixtures.json",
            competition_key="SYNTHETIC_PL",
            season_code="2026/27",
            captured_at=reverted_at,
            information_cutoff=DEFAULT_INFORMATION_CUTOFF,
            rights_profile_id="synthetic_test_v1",
            database_url_ref=DATABASE_REF,
        )
    )

    assert original.result.source_bundle is not None
    assert changed.result.source_bundle is not None
    assert reverted.result.source_bundle is not None
    assert reverted.result.source_bundle.semantic_sha256 == (
        original.result.source_bundle.semantic_sha256
    )
    assert reverted.result.source_bundle.bundle_id not in {
        original.result.source_bundle.bundle_id,
        changed.result.source_bundle.bundle_id,
    }
    assert {member.source_snapshot_id for member in reverted.result.source_bundle.members} == {
        resource.source_snapshot_id for resource in reverted.result.resources
    }

    with postgres_session_factory() as session:
        current_prices = tuple(
            session.scalars(text("SELECT price_tenths FROM fpl.current_player_observation"))
        )
        assert sorted(current_prices) == [50, 55, 75, 80]
        assert _count(session, player_observation) == 6
        assert _count(session, gameweek_observation) == 4
        assert _count(session, fixture_observation) == 3
        assert _count(session, source_bundle) == 3
        assert _count(session, source_bundle_member) == 6


def test_changed_snapshot_appends_history_and_preserves_canonical_identity(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    fixture_root = repository_root / "fixtures" / "fpl" / "FPL-004"
    service = FplIngestionService(repository_root=repository_root)
    original = _replay(service, fixture_root, "happy_path")
    changed = _replay(service, fixture_root, "changed_snapshot")

    assert original.result.source_bundle is not None
    assert changed.exit_code == 0
    assert changed.result.source_bundle is not None
    assert changed.result.source_bundle.semantic_sha256 != (
        original.result.source_bundle.semantic_sha256
    )
    assert changed.result.canonical_effects["changed"] == {
        "fixture_gameweek_assignment": 1,
        "fixture_revision": 1,
        "gameweek_observation": 1,
        "player_observation": 1,
        "fixture_observation": 1,
    }

    with postgres_session_factory() as session:
        assert _count(session, competition) == 1
        assert _count(session, season) == 1
        assert _count(session, team) == 2
        assert _count(session, player) == 4
        assert _count(session, gameweek) == 2
        assert _count(session, fixture) == 1
        assert _count(session, team_observation) == 2
        assert _count(session, player_observation) == 5
        assert _count(session, gameweek_observation) == 3
        assert _count(session, fixture_observation) == 2
        assert _count(session, fixture_revision) == 2
        assert _count(session, fixture_gameweek_assignment) == 2
        assert _count(session, source_bundle) == 2
        assert _count(session, source_bundle_member) == 4
        assert (
            session.scalar(
                select(func.count())
                .select_from(fixture_revision)
                .where(func.upper_inf(fixture_revision.c.system_during))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(fixture_gameweek_assignment)
                .where(func.upper_inf(fixture_gameweek_assignment.c.system_during))
            )
            == 1
        )
        previous_revision, current_revision = session.execute(
            select(
                fixture_revision.c.fixture_revision_id,
                fixture_revision.c.superseded_by_revision_id,
            ).order_by(fixture_revision.c.revision_number)
        ).all()
        assert previous_revision.superseded_by_revision_id == (current_revision.fixture_revision_id)
        assert current_revision.superseded_by_revision_id is None


def test_post_cutoff_snapshots_remain_observed_but_cannot_enter_bundle(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    fixture_root = repository_root / "fixtures" / "fpl" / "FPL-004"
    outcome = _replay(
        FplIngestionService(repository_root=repository_root),
        fixture_root,
        "post_cutoff",
    )

    assert outcome.exit_code == 2
    assert outcome.result.status == "USABLE"
    assert outcome.result.source_bundle is None
    assert outcome.result.canonical_effects["outcome"] == "OBSERVED_NOT_BUNDLE_ELIGIBLE"
    assert outcome.result.quality.status == "BLOCKED"
    assert outcome.result.quality.blocker_count == 1
    post_cutoff_issue = next(
        issue for issue in outcome.result.quality.issues if issue.code == "POST_CUTOFF"
    )
    assert post_cutoff_issue.missingness == "POST_CUTOFF"
    assert {resource.lifecycle_state for resource in outcome.result.resources} == {"USABLE"}
    assert all(
        resource.usable_at is not None and resource.usable_at > DEFAULT_INFORMATION_CUTOFF
        for resource in outcome.result.resources
    )

    with postgres_session_factory() as session:
        assert _count(session, source_snapshot) == 2
        assert _count(session, fixture_observation) == 1
        assert _count(session, source_bundle) == 0
        assert _count(session, source_bundle_member) == 0
        persisted_issues = session.execute(
            select(
                data_quality_issue.c.issue_type,
                data_quality_issue.c.decision_impact,
                data_quality_issue.c.details,
            ).where(data_quality_issue.c.issue_type == "POST_CUTOFF")
        ).all()
        assert len(persisted_issues) == 2
        assert all(issue.decision_impact == "BLOCKING" for issue in persisted_issues)
        assert all(issue.details["missingness"] == "POST_CUTOFF" for issue in persisted_issues)
        lifecycle_rows = session.execute(
            text(
                "SELECT current_state, usable_at FROM provenance.source_snapshot_lifecycle "
                "ORDER BY source_snapshot_id"
            )
        ).all()
        assert len(lifecycle_rows) == 2
        assert all(row.current_state == "USABLE" for row in lifecycle_rows)


def test_non_cutoff_bundle_failure_is_not_downgraded_to_observed_success(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_bundle(*_args: object, **_kwargs: object) -> None:
        raise IngestionError("LIFECYCLE_INVARIANT", "synthetic non-cutoff failure")

    monkeypatch.setattr(FplPersistence, "freeze_bundle", fail_bundle)
    fixture_root = repository_root / "fixtures" / "fpl" / "FPL-004"
    with pytest.raises(IngestionError, match="non-cutoff failure") as caught:
        _replay(FplIngestionService(repository_root=repository_root), fixture_root, "happy_path")
    assert caught.value.code == "LIFECYCLE_INVARIANT"

    with postgres_session_factory() as session:
        assert _count(session, source_bundle) == 0


@pytest.mark.parametrize(
    ("scenario", "expected_error"),
    (
        ("malformed", "MALFORMED_JSON"),
        ("missing_required", "VALIDATION_FAILED"),
        ("wrong_type", "VALIDATION_FAILED"),
    ),
)
def test_blocking_payload_is_terminally_quarantined_without_bundle_or_promotion(
    scenario: str,
    expected_error: str,
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    fixture_root = repository_root / "fixtures" / "fpl" / "FPL-004"
    outcome = _replay(FplIngestionService(repository_root=repository_root), fixture_root, scenario)

    assert outcome.exit_code == 2
    assert outcome.result.status == "QUARANTINED"
    assert outcome.result.source_bundle is None
    assert outcome.result.canonical_effects["error_code"] == expected_error
    assert {resource.lifecycle_state for resource in outcome.result.resources} == {"QUARANTINED"}
    with postgres_session_factory() as session:
        assert _count(session, source_snapshot) == 2
        assert _count(session, competition) == 0
        assert _count(session, player) == 0
        assert _count(session, fixture) == 0
        assert _count(session, source_bundle) == 0


def test_late_mapping_conflict_rolls_back_promotion_and_records_blockers(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_after_partial_mapping(self: FplPersistence, *_args: object) -> object:
        raise IngestionError("MAPPING_CONFLICT", "synthetic late mapping conflict")

    monkeypatch.setattr(FplPersistence, "_player_season", fail_after_partial_mapping)
    outcome = _replay(
        FplIngestionService(repository_root=repository_root),
        repository_root / "fixtures/fpl/FPL-004",
        "happy_path",
    )

    assert outcome.exit_code == 2
    assert outcome.result.status == "QUARANTINED"
    assert outcome.result.canonical_effects["error_code"] == "MAPPING_CONFLICT"
    assert outcome.result.quality.blocker_count == 1
    with postgres_session_factory() as session:
        assert _count(session, source_snapshot) == 2
        assert _count(session, competition) == 0
        assert _count(session, season) == 0
        assert _count(session, team) == 0
        assert _count(session, player) == 0
        assert _count(session, external_identifier) == 0
        assert _count(session, fixture_observation) == 0
        assert _count(session, source_bundle) == 0
        issues = session.execute(
            select(
                data_quality_issue.c.issue_type,
                data_quality_issue.c.severity,
                data_quality_issue.c.decision_impact,
                data_quality_issue.c.details,
            ).order_by(data_quality_issue.c.source_snapshot_id)
        ).all()
        assert len(issues) == 2
        assert all(issue.issue_type == "MAPPING_CONFLICT" for issue in issues)
        assert all(issue.severity == "P1" for issue in issues)
        assert all(issue.decision_impact == "BLOCKING" for issue in issues)
        assert all(issue.details["missingness"] == "MAPPING_FAILED" for issue in issues)
