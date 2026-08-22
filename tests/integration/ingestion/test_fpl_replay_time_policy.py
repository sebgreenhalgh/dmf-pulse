"""PostgreSQL regressions for deterministic synthetic replay time.

The test names and docstrings map directly to CI-FPL-REPLAY-001 TIME-01..TIME-18.
Resume-stage cases TIME-08..TIME-12 live beside the existing lifecycle suffix
proofs, while UTC policy boundaries for TIME-17 live in the unit boundary suite.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import source_bundle, source_processing_event
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl import service as service_module
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    DEFAULT_CAPTURED_AT,
    DEFAULT_INFORMATION_CUTOFF,
    FplImportRequest,
    FplIngestionService,
    FplOperationOutcome,
    FplReplayRequest,
    IngestionInterrupted,
)
from dmf_pulse.ingestion.repository import received_context

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

PRE_CUTOFF_HOST = datetime(2026, 8, 21, 17, 5, tzinfo=UTC)
ONE_DAY_LATER_HOST = datetime(2026, 8, 22, 18, tzinfo=UTC)
ONE_YEAR_LATER_HOST = datetime(2027, 8, 22, 18, tzinfo=UTC)
FROZEN_REPLAY_POLICY = "FROZEN_REPLAY_CAPTURED_AT_V1"
PROCESSING_TIME_POLICY = "PROCESSING_TIME_V1"


def _request(repository_root: Path, scenario: str = "happy_path") -> FplReplayRequest:
    return FplReplayRequest(
        fixture_set=repository_root / "fixtures/fpl/FPL-004",
        scenario=scenario,
        information_cutoff=DEFAULT_INFORMATION_CUTOFF,
        database_url_ref=DATABASE_REF,
    )


def _replay(repository_root: Path, scenario: str, host_clock: datetime) -> FplOperationOutcome:
    return FplIngestionService(
        repository_root=repository_root,
        clock=lambda: host_clock,
    ).replay(_request(repository_root, scenario))


def _quality_projection(outcome: FplOperationOutcome) -> list[dict[str, object]]:
    return [issue.model_dump(mode="json") for issue in outcome.result.quality.issues]


def _usable_projection(outcome: FplOperationOutcome) -> tuple[datetime, ...]:
    values = tuple(resource.usable_at for resource in outcome.result.resources)
    assert all(value is not None for value in values)
    return tuple(value for value in values if value is not None)


@pytest.mark.parametrize(
    "future_host",
    (ONE_DAY_LATER_HOST, ONE_YEAR_LATER_HOST),
    ids=("TIME-02-one-day-later", "TIME-03-one-year-later"),
)
def test_time_01_02_03_07_16_18_happy_replay_ignores_host_wall_clock(
    future_host: datetime,
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """TIME-01/02/03/07/16/18: replay output is host-clock invariant."""

    before = _replay(repository_root, "happy_path", PRE_CUTOFF_HOST)
    after = _replay(repository_root, "happy_path", future_host)

    assert before.exit_code == after.exit_code == 0
    assert before.result.status == after.result.status == "USABLE"
    assert before.result.source_bundle is not None
    assert after.result.source_bundle is not None
    assert before.result.source_bundle.bundle_id != after.result.source_bundle.bundle_id
    assert before.result.source_bundle.semantic_sha256 == (
        after.result.source_bundle.semantic_sha256
    )
    assert before.result.source_bundle.information_cutoff == (
        after.result.source_bundle.information_cutoff
    )
    assert tuple(member.role for member in before.result.source_bundle.members) == (
        "BOOTSTRAP",
        "FIXTURES",
    )
    assert tuple(member.role for member in after.result.source_bundle.members) == (
        "BOOTSTRAP",
        "FIXTURES",
    )
    assert tuple(member.usable_at for member in before.result.source_bundle.members) == tuple(
        member.usable_at for member in after.result.source_bundle.members
    )
    assert _usable_projection(before) == _usable_projection(after)
    assert all(value <= DEFAULT_INFORMATION_CUTOFF for value in _usable_projection(after))
    assert _quality_projection(before) == _quality_projection(after)
    assert after.result.canonical_effects["changed"] == {}

    before_snapshot_ids = {resource.source_snapshot_id for resource in before.result.resources}
    after_snapshot_ids = {resource.source_snapshot_id for resource in after.result.resources}
    assert before_snapshot_ids.isdisjoint(after_snapshot_ids)
    with postgres_session_factory() as session:
        assert set(session.scalars(select(source_bundle.c.semantic_sha256))) == {
            before.result.source_bundle.semantic_sha256
        }


def test_time_04_changed_snapshot_remains_pre_cutoff_under_future_host_clock(
    repository_root: Path,
) -> None:
    """TIME-04: changed_snapshot uses its frozen 17:10 replay timestamp."""

    outcome = _replay(repository_root, "changed_snapshot", ONE_YEAR_LATER_HOST)

    assert outcome.exit_code == 0
    assert outcome.result.status == "USABLE"
    assert outcome.result.source_bundle is not None
    assert outcome.result.canonical_effects["outcome"] == "BUNDLE_CREATED"
    assert all(value <= DEFAULT_INFORMATION_CUTOFF for value in _usable_projection(outcome))


@pytest.mark.parametrize(
    "host_clock",
    (PRE_CUTOFF_HOST, ONE_YEAR_LATER_HOST),
    ids=("TIME-05-pre-cutoff-host", "TIME-06-future-host"),
)
def test_time_05_06_15_post_cutoff_replay_retains_exact_blocker(
    host_clock: datetime,
    repository_root: Path,
) -> None:
    """TIME-05/06/15: fixture time, not host time, owns POST_CUTOFF."""

    outcome = _replay(repository_root, "post_cutoff", host_clock)

    assert outcome.exit_code == 2
    assert outcome.result.status == "USABLE"
    assert outcome.result.source_bundle is None
    assert outcome.result.canonical_effects["outcome"] == "OBSERVED_NOT_BUNDLE_ELIGIBLE"
    blockers = [
        issue for issue in outcome.result.quality.issues if issue.decision_impact == "BLOCKING"
    ]
    assert [issue.code for issue in blockers] == ["POST_CUTOFF"]
    assert blockers[0].missingness == "POST_CUTOFF"
    assert all(value > DEFAULT_INFORMATION_CUTOFF for value in _usable_projection(outcome))


def test_time_13_concurrent_future_replays_retain_idempotent_semantics(
    repository_root: Path,
) -> None:
    """TIME-13: concurrent replay workers share the frozen scenario timeline."""

    request = _request(repository_root)
    ready = Barrier(2)

    def replay() -> FplOperationOutcome:
        ready.wait(timeout=10)
        return FplIngestionService(
            repository_root=repository_root,
            clock=lambda: ONE_YEAR_LATER_HOST,
        ).replay(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(replay) for _index in range(2))
        outcomes = tuple(future.result(timeout=30) for future in futures)

    assert {outcome.exit_code for outcome in outcomes} == {0}
    bundles = tuple(outcome.result.source_bundle for outcome in outcomes)
    assert all(bundle is not None for bundle in bundles)
    present_bundles = tuple(bundle for bundle in bundles if bundle is not None)
    assert len({bundle.bundle_id for bundle in present_bundles}) == 2
    assert len({bundle.semantic_sha256 for bundle in present_bundles}) == 1
    assert (
        len({tuple(member.usable_at for member in bundle.members) for bundle in present_bundles})
        == 1
    )
    assert all(
        member.usable_at <= DEFAULT_INFORMATION_CUTOFF
        for bundle in present_bundles
        for member in bundle.members
    )


def test_time_14_ordinary_import_cannot_backdate_from_captured_timestamp(
    repository_root: Path,
) -> None:
    """TIME-14: the ordinary import API retains actual processing-time cutoff safety."""

    fixture_root = repository_root / "fixtures/fpl/FPL-004/happy_path"
    outcome = FplIngestionService(
        repository_root=repository_root,
        clock=lambda: ONE_DAY_LATER_HOST,
    ).import_pair(
        FplImportRequest(
            bootstrap_path=fixture_root / "bootstrap.json",
            fixtures_path=fixture_root / "fixtures.json",
            competition_key="SYNTHETIC_PL",
            season_code="2026/27",
            captured_at=DEFAULT_CAPTURED_AT,
            information_cutoff=DEFAULT_INFORMATION_CUTOFF,
            rights_profile_id="synthetic_test_v1",
            database_url_ref=DATABASE_REF,
        )
    )

    assert outcome.exit_code == 2
    assert outcome.result.source_bundle is None
    assert outcome.result.canonical_effects["outcome"] == "OBSERVED_NOT_BUNDLE_ELIGIBLE"
    blockers = [
        issue.code for issue in outcome.result.quality.issues if issue.decision_impact == "BLOCKING"
    ]
    assert blockers == ["POST_CUTOFF"]
    assert all(value > DEFAULT_INFORMATION_CUTOFF for value in _usable_projection(outcome))


def test_replay_resume_policy_is_persisted_and_context_tamper_is_rejected(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The frozen replay policy is pair-hash-bound and cannot be downgraded on resume."""

    service = FplIngestionService(
        repository_root=repository_root,
        clock=lambda: ONE_YEAR_LATER_HOST,
    )
    request = replace(_request(repository_root), halt_after_stage="PARSED")
    with pytest.raises(IngestionInterrupted) as interrupted:
        service.replay(request)

    with postgres_session_factory() as session:
        for snapshot_id in interrupted.value.snapshot_ids:
            assert received_context(session, snapshot_id)["operation_time_policy"] == (
                FROZEN_REPLAY_POLICY
            )

    original_received_context = service_module.received_context

    def tampered_context(session: Session, snapshot_id: UUID) -> dict[str, object]:
        context = original_received_context(session, snapshot_id)
        context["operation_time_policy"] = PROCESSING_TIME_POLICY
        return context

    monkeypatch.setattr(service_module, "received_context", tampered_context)
    with pytest.raises(IngestionError, match="context hash is invalid") as raised:
        service.resume(interrupted.value.snapshot_ids[0], database_url_ref=DATABASE_REF)
    assert raised.value.code == "LIFECYCLE_INVARIANT"
    with postgres_session_factory() as session:
        for snapshot_id in interrupted.value.snapshot_ids:
            stages = tuple(
                session.scalars(
                    select(source_processing_event.c.stage)
                    .where(source_processing_event.c.source_snapshot_id == snapshot_id)
                    .order_by(source_processing_event.c.sequence_number)
                )
            )
            assert stages == ("RECEIVED", "STORED", "PARSED")
