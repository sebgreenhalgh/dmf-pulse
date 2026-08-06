"""PostgreSQL proofs for the NRM-006 application-service vertical slice."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.cli.app import app
from dmf_pulse.data_model.tables import (
    data_quality_issue,
    fixture_observation,
    market_consensus_outcome,
    market_consensus_result,
    market_normalisation_book_source,
    market_normalisation_policy,
    market_normalisation_run,
    market_normalisation_source,
    market_normalisation_warning,
    normalised_operator_market,
    normalised_operator_market_source,
    normalised_operator_outcome,
    odds_mapping_dependency,
    odds_observation,
)
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    FplImportRequest,
    FplIngestionService,
)
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.service import (
    DEFAULT_CUTOFF,
    OddsImportRequest,
    OddsIngestionService,
    OddsReplayRequest,
)
from dmf_pulse.ingestion.repository import lifecycle_state
from dmf_pulse.markets.models import ExclusionReason, NormalisationStatus
from dmf_pulse.markets.policy import load_market_normalisation_policy
from dmf_pulse.markets.projection import market_normalisation_semantic_projection
from dmf_pulse.markets.service import MarketService

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

AS_OF = datetime(2026, 8, 20, 12, 5, tzinfo=UTC)
LATER_AS_OF = datetime(2026, 8, 20, 13, 5, tzinfo=UTC)


def _replay(repository_root: Path, scenario: str = "happy_path"):
    outcome = OddsIngestionService(repository_root=repository_root).replay(
        OddsReplayRequest(
            fixture_set=repository_root / "fixtures/odds/ODD-005",
            scenario=scenario,
            information_cutoff=DEFAULT_CUTOFF,
            database_url_ref=DATABASE_REF,
        )
    )
    assert outcome.exit_code == 0
    return outcome


def _import(repository_root: Path, payload: str, captured_at: datetime):
    return OddsIngestionService(
        repository_root=repository_root,
        clock=lambda: captured_at + timedelta(seconds=10),
    ).import_payload(
        OddsImportRequest(
            input_path=repository_root / "fixtures/odds/ODD-005" / payload,
            mapping_plan_path=repository_root / "fixtures/odds/ODD-005/mapping_plan.json",
            captured_at=captured_at,
            processing_at=captured_at + timedelta(seconds=5),
            information_cutoff=DEFAULT_CUTOFF,
            rights_profile_id="synthetic_the_odds_api_v1",
            database_url_ref=DATABASE_REF,
            quota=QuotaState(
                remaining=498,
                used=2,
                last_cost=1,
                observed_at=captured_at,
                source=QuotaSource.SYNTHETIC_FIXTURE,
            ),
        )
    )


def _normalise(as_of: datetime = AS_OF):
    return MarketService().normalise(
        fixture_external_provider="synthetic_fpl",
        fixture_external_id="101",
        season_code="2026/27",
        as_of=as_of,
        database_url_ref=DATABASE_REF,
    )


def _later_fixture_snapshot(repository_root: Path, usable_at: datetime):
    outcome = FplIngestionService(
        repository_root=repository_root,
        clock=lambda: usable_at,
    ).import_pair(
        FplImportRequest(
            bootstrap_path=(repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"),
            fixtures_path=(repository_root / "fixtures/fpl/FPL-004/happy_path/fixtures.json"),
            competition_key="SYNTHETIC_PL",
            season_code="2026/27",
            captured_at=usable_at,
            information_cutoff=usable_at + timedelta(seconds=1),
            rights_profile_id="synthetic_test_v1",
            database_url_ref=DATABASE_REF,
        )
    )
    assert outcome.exit_code == 0
    return next(
        resource.source_snapshot_id
        for resource in outcome.result.resources
        if resource.resource == "fixtures"
    )


def _count(session: Session, table: object) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)  # type: ignore[arg-type]


def _add_quality_issue(
    session: Session,
    *,
    source_snapshot_id: object,
    issue_type: str,
    severity: str,
    decision_impact: str,
    detected_at: datetime | None = None,
) -> UUID:
    created = session.scalar(
        insert(data_quality_issue)
        .values(
            source_snapshot_id=source_snapshot_id,
            issue_type=issue_type,
            severity=severity,
            status="OPEN",
            detected_at=detected_at or AS_OF - timedelta(minutes=1),
            decision_impact=decision_impact,
            subject_scope="SOURCE_SNAPSHOT",
            stage="MARKET_NORMALISATION",
            message=f"synthetic {issue_type} canary",
        )
        .returning(data_quality_issue.c.data_quality_issue_id)
    )
    assert isinstance(created, UUID)
    return created


def test_happy_path_matches_frozen_semantic_projection(repository_root: Path) -> None:
    _replay(repository_root)
    result = _normalise()

    assert result.status is NormalisationStatus.NORMALISED
    actual = market_normalisation_semantic_projection(
        result, policy=load_market_normalisation_policy()
    )
    expected = json.loads(
        (
            repository_root / "fixtures/odds/NRM-006/expected_outputs/happy_path_consensus.json"
        ).read_text(encoding="utf-8")
    )
    assert actual == expected


def test_persists_complete_immutable_lineage(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay(repository_root)
    result = _normalise()
    assert result.consensus is not None

    with postgres_session_factory() as session:
        assert _count(session, market_normalisation_policy) == 1
        assert _count(session, market_normalisation_run) == 1
        assert _count(session, market_normalisation_source) == 6
        assert _count(session, market_normalisation_book_source) == 2
        assert _count(session, normalised_operator_market) == 2
        assert _count(session, normalised_operator_market_source) == 6
        assert _count(session, normalised_operator_outcome) == 6
        assert _count(session, market_consensus_result) == 1
        assert _count(session, market_consensus_outcome) == 3
        run = session.execute(select(market_normalisation_run)).mappings().one()
        assert run["status"] == "NORMALISED"
        assert run["as_of"] == AS_OF
        assert run["mapping_cutoff"] == AS_OF
        assert (
            run["semantic_result_sha256"]
            == market_normalisation_semantic_projection(
                result, policy=load_market_normalisation_policy()
            )["semantic_result_sha256"]
        )
        operator_vectors = session.execute(
            select(
                normalised_operator_outcome.c.normalised_operator_market_id,
                func.sum(normalised_operator_outcome.c.proportional_probability),
                func.sum(normalised_operator_outcome.c.market_probability),
            ).group_by(normalised_operator_outcome.c.normalised_operator_market_id)
        ).all()
        assert len(operator_vectors) == 2
        assert all(proportional == market == 1 for _, proportional, market in operator_vectors)
        assert (
            session.scalar(select(func.sum(market_consensus_outcome.c.consensus_probability))) == 1
        )


def test_cli_and_library_share_schema_shaped_result(repository_root: Path) -> None:
    _replay(repository_root)
    library = _normalise().model_dump(mode="json")

    cli = CliRunner().invoke(
        app,
        [
            "market",
            "normalise",
            "--fixture-external-provider",
            "synthetic_fpl",
            "--fixture-external-id",
            "101",
            "--season-code",
            "2026/27",
            "--as-of",
            "2026-08-20T12:05:00Z",
            "--output",
            "json",
        ],
    )

    assert cli.exit_code == 0
    assert json.loads(cli.stdout) == library


def test_pinned_mapping_schedule_ignores_later_fixture_correction(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay(repository_root)
    policy = load_market_normalisation_policy()
    before = market_normalisation_semantic_projection(_normalise(), policy=policy)
    correction_usable_at = AS_OF + timedelta(minutes=2)
    correction_snapshot_id = _later_fixture_snapshot(repository_root, correction_usable_at)

    with postgres_session_factory.begin() as session:
        correction_source_usable_at = lifecycle_state(session, correction_snapshot_id)["usable_at"]
        assert isinstance(correction_source_usable_at, datetime)
        pinned_id = session.scalar(
            select(odds_mapping_dependency.c.fixture_observation_id).limit(1)
        )
        assert pinned_id is not None
        pinned = (
            session.execute(
                select(fixture_observation).where(
                    fixture_observation.c.fixture_observation_id == pinned_id
                )
            )
            .mappings()
            .one()
        )
        correction = dict(pinned)
        correction.pop("fixture_observation_id")
        correction["kickoff_at"] = pinned["kickoff_at"] + timedelta(hours=1)
        correction["observed_at"] = correction_source_usable_at
        correction["received_at"] = correction_source_usable_at
        correction["usable_at"] = correction_source_usable_at
        correction["source_snapshot_id"] = correction_snapshot_id
        correction["semantic_sha256"] = canonical_sha256(
            {
                "pinned_fixture_observation_id": str(pinned_id),
                "synthetic_correction": "future-kickoff",
            }
        )
        session.execute(insert(fixture_observation).values(**correction))

    after = market_normalisation_semantic_projection(_normalise(), policy=policy)

    assert after == before


def test_test_only_pinned_schedule_attested_after_asof_is_ineligible(
    repository_root: Path,
) -> None:
    _later_fixture_snapshot(repository_root, AS_OF + timedelta(minutes=1))
    imported = _import(repository_root, "happy_path.json", AS_OF - timedelta(minutes=5))
    assert imported.exit_code == 0

    result = _normalise()

    assert result.status is NormalisationStatus.BLOCKED
    assert result.consensus is None
    assert result.error_code == "MAPPING_UNAVAILABLE"
    assert {item.reason for item in result.excluded_books} == {ExclusionReason.MAPPING_UNAVAILABLE}


def test_post_publication_p1_blocker_blocks_all_affected_books(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    replay = _replay(repository_root)
    snapshot_id = replay.result.source_snapshot_id
    assert snapshot_id is not None
    with postgres_session_factory.begin() as session:
        _add_quality_issue(
            session,
            source_snapshot_id=snapshot_id,
            issue_type="POST_PUBLICATION_P1_CANARY",
            severity="P1",
            decision_impact="BLOCKING",
        )

    result = _normalise()

    assert result.status is NormalisationStatus.BLOCKED
    assert result.consensus is None
    assert result.error_code == "QUALITY_BLOCKED"
    assert {item.reason for item in result.excluded_books} == {ExclusionReason.QUALITY_BLOCKED}
    assert "BOOK_EXCLUDED_QUALITY_BLOCKED" in result.warnings


def test_p1_mislabeled_nonblocking_still_blocks_all_affected_books(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    replay = _replay(repository_root)
    snapshot_id = replay.result.source_snapshot_id
    assert snapshot_id is not None
    with postgres_session_factory.begin() as session:
        _add_quality_issue(
            session,
            source_snapshot_id=snapshot_id,
            issue_type="MISLABELED_P1_NONBLOCKING_CANARY",
            severity="P1",
            decision_impact="NONBLOCKING",
        )

    result = _normalise()

    assert result.status is NormalisationStatus.BLOCKED
    assert result.consensus is None
    assert result.error_code == "QUALITY_BLOCKED"
    assert {item.reason for item in result.excluded_books} == {ExclusionReason.QUALITY_BLOCKED}


def test_nonblocking_duplicate_warning_remains_eligible_and_is_persisted(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    replay = _replay(repository_root)
    snapshot_id = replay.result.source_snapshot_id
    assert snapshot_id is not None
    with postgres_session_factory.begin() as session:
        _add_quality_issue(
            session,
            source_snapshot_id=snapshot_id,
            issue_type="DUPLICATE_OUTCOME_SAME_PAYLOAD",
            severity="P2",
            decision_impact="NONBLOCKING",
        )

    result = _normalise()

    assert result.status is NormalisationStatus.DEGRADED
    assert result.consensus is not None
    assert result.consensus.eligible_operator_count == 2
    assert "DUPLICATE_OUTCOME_SAME_PAYLOAD" in result.warnings
    with postgres_session_factory() as session:
        stored = set(session.scalars(select(market_normalisation_warning.c.warning_code)))
    assert "DUPLICATE_OUTCOME_SAME_PAYLOAD" in stored


def test_newer_incomplete_book_does_not_merge_or_suppress_older_complete_book(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    replay = _replay(repository_root)
    original_snapshot_id = replay.result.source_snapshot_id
    assert original_snapshot_id is not None
    imported = _import(
        repository_root,
        "incomplete_book.json",
        AS_OF - timedelta(minutes=3),
    )
    assert imported.exit_code == 0

    result = _normalise()

    assert result.status is NormalisationStatus.DEGRADED
    assert result.consensus is not None
    assert result.consensus.eligible_operator_count == 2
    assert any(
        item.operator_key == "book_alpha" and item.reason is ExclusionReason.INCOMPLETE
        for item in result.excluded_books
    )
    alpha = next(
        item for item in result.consensus.operator_markets if item.operator_key == "book_alpha"
    )
    with postgres_session_factory() as session:
        selected_lineage = session.execute(
            select(
                odds_observation.c.book_observation_id,
                odds_observation.c.source_snapshot_id,
            ).where(odds_observation.c.odds_observation_id.in_(alpha.source_observation_ids))
        ).all()
    assert len({row.book_observation_id for row in selected_lineage}) == 1
    assert {row.source_snapshot_id for row in selected_lineage} == {original_snapshot_id}


def test_newer_quality_blocked_book_falls_back_to_older_complete_eligible_book(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    replay = _replay(repository_root)
    original_snapshot_id = replay.result.source_snapshot_id
    assert original_snapshot_id is not None
    imported = _import(
        repository_root,
        "happy_path.json",
        AS_OF - timedelta(minutes=3),
    )
    blocked_snapshot_id = imported.result.source_snapshot_id
    assert imported.exit_code == 0 and blocked_snapshot_id is not None
    with postgres_session_factory.begin() as session:
        _add_quality_issue(
            session,
            source_snapshot_id=blocked_snapshot_id,
            issue_type="NEWER_BOOK_P1_CANARY",
            severity="P1",
            decision_impact="BLOCKING",
        )

    result = _normalise()

    assert result.status is NormalisationStatus.DEGRADED
    assert result.consensus is not None
    assert result.consensus.eligible_operator_count == 2
    assert {item.reason for item in result.excluded_books} == {ExclusionReason.QUALITY_BLOCKED}
    selected_ids = {
        observation_id
        for item in result.consensus.operator_markets
        for observation_id in item.source_observation_ids
    }
    with postgres_session_factory() as session:
        selected_snapshots = set(
            session.scalars(
                select(odds_observation.c.source_snapshot_id).where(
                    odds_observation.c.odds_observation_id.in_(selected_ids)
                )
            )
        )
    assert selected_snapshots == {original_snapshot_id}


def test_quality_findings_and_resolutions_are_historical_as_of(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    replay = _replay(repository_root)
    snapshot_id = replay.result.source_snapshot_id
    assert snapshot_id is not None
    clean_before = _normalise(AS_OF)
    detected_at = AS_OF + timedelta(minutes=1)
    with postgres_session_factory.begin() as session:
        issue_id = _add_quality_issue(
            session,
            source_snapshot_id=snapshot_id,
            issue_type="FUTURE_P1_CANARY",
            severity="P1",
            decision_impact="BLOCKING",
            detected_at=detected_at,
        )

    clean_after = _normalise(AS_OF)
    blocked_as_of = AS_OF + timedelta(minutes=2)
    blocked_before_resolution = _normalise(blocked_as_of)
    assert clean_after.model_dump(mode="json") == clean_before.model_dump(mode="json")
    assert blocked_before_resolution.status is NormalisationStatus.BLOCKED

    resolved_at = AS_OF + timedelta(minutes=3)
    with postgres_session_factory.begin() as session:
        session.execute(
            update(data_quality_issue)
            .where(data_quality_issue.c.data_quality_issue_id == issue_id)
            .values(status="RESOLVED", resolved_at=resolved_at)
        )

    blocked_after_resolution = _normalise(blocked_as_of)
    available_after_resolution = _normalise(AS_OF + timedelta(minutes=4))
    assert blocked_after_resolution.model_dump(mode="json") == blocked_before_resolution.model_dump(
        mode="json"
    )
    assert available_after_resolution.status is NormalisationStatus.NORMALISED
    assert available_after_resolution.consensus is not None


def test_obsolete_stale_version_does_not_degrade_fresh_same_operator_version(
    repository_root: Path,
) -> None:
    _replay(repository_root, "happy_path")
    _replay(repository_root, "changed_quote")

    result = _normalise(LATER_AS_OF)

    assert result.status is NormalisationStatus.NORMALISED
    assert result.consensus is not None
    assert result.consensus.eligible_operator_count == 2
    assert all(item.reason is not ExclusionReason.STALE for item in result.excluded_books)
    assert "BOOK_EXCLUDED_STALE" not in result.warnings


def test_obsolete_quality_blocked_version_does_not_degrade_fresh_version(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    replay = _replay(repository_root, "happy_path")
    old_snapshot_id = replay.result.source_snapshot_id
    assert old_snapshot_id is not None
    with postgres_session_factory.begin() as session:
        _add_quality_issue(
            session,
            source_snapshot_id=old_snapshot_id,
            issue_type="SUPERSEDED_P1_CANARY",
            severity="P1",
            decision_impact="BLOCKING",
        )
    _replay(repository_root, "changed_quote")

    result = _normalise(LATER_AS_OF)

    assert result.status is NormalisationStatus.NORMALISED
    assert result.consensus is not None
    assert result.consensus.eligible_operator_count == 2
    assert all(item.reason is not ExclusionReason.QUALITY_BLOCKED for item in result.excluded_books)
    assert "BOOK_EXCLUDED_QUALITY_BLOCKED" not in result.warnings
