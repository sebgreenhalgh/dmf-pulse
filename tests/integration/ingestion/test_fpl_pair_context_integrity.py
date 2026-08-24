"""PostgreSQL adversarial controls for FPL resume pair-context integrity."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.dml import Update

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.tables import (
    ingestion_run,
    source_bundle,
    source_processing_event,
    source_snapshot,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    DEFAULT_INFORMATION_CUTOFF,
    FplIngestionService,
    FplReplayRequest,
    IngestionInterrupted,
)
from dmf_pulse.ingestion.repository import received_context

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

_PROCESSING_EVENT_GUARD = "trg_source_processing_event_guard"
_FUTURE_HOST = datetime(2027, 8, 22, 18, tzinfo=UTC)


def _request(repository_root: Path) -> FplReplayRequest:
    return FplReplayRequest(
        fixture_set=repository_root / "fixtures/fpl/FPL-004",
        scenario="happy_path",
        information_cutoff=DEFAULT_INFORMATION_CUTOFF,
        database_url_ref=DATABASE_REF,
        halt_after_stage="PARSED",
    )


def _interrupted_pair(
    repository_root: Path,
) -> tuple[FplIngestionService, tuple[UUID, UUID]]:
    service = FplIngestionService(
        repository_root=repository_root,
        clock=lambda: _FUTURE_HOST,
    )
    with pytest.raises(IngestionInterrupted) as caught:
        service.replay(_request(repository_root))
    return service, caught.value.snapshot_ids


def _received_update(snapshot_id: UUID, safe_details: object) -> Update:
    return (
        update(source_processing_event)
        .where(
            source_processing_event.c.source_snapshot_id == snapshot_id,
            source_processing_event.c.stage == "RECEIVED",
        )
        .values(safe_details=safe_details)
    )


def _received_stage_update(snapshot_id: UUID, stage: str) -> Update:
    return (
        update(source_processing_event)
        .where(
            source_processing_event.c.source_snapshot_id == snapshot_id,
            source_processing_event.c.stage == "RECEIVED",
        )
        .values(stage=stage)
    )


def _assert_normal_mutation_blocked(
    factory: sessionmaker[Session],
    mutation: Update,
) -> None:
    with pytest.raises(DBAPIError) as caught, factory.begin() as session:
        session.execute(mutation)
    assert "IMMUTABLE_RECORD" in str(caught.value.orig)


def _apply_restored_state_corruption(
    factory: sessionmaker[Session],
    mutations: tuple[Update, ...],
) -> None:
    """Simulate privileged restore corruption and always restore the production guard."""

    disable = text(
        f"ALTER TABLE provenance.source_processing_event DISABLE TRIGGER {_PROCESSING_EVENT_GUARD}"
    )
    enable = text(
        f"ALTER TABLE provenance.source_processing_event ENABLE TRIGGER {_PROCESSING_EVENT_GUARD}"
    )
    try:
        with factory.begin() as session:
            session.execute(disable)
            for mutation in mutations:
                changed = session.execute(mutation)
                assert changed.rowcount == 1
            session.execute(enable)
    finally:
        with factory.begin() as session:
            session.execute(enable)
            trigger_state = session.scalar(
                text(
                    "SELECT trigger.tgenabled "
                    "FROM pg_catalog.pg_trigger AS trigger "
                    "JOIN pg_catalog.pg_class AS relation "
                    "ON relation.oid = trigger.tgrelid "
                    "JOIN pg_catalog.pg_namespace AS namespace "
                    "ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = 'provenance' "
                    "AND relation.relname = 'source_processing_event' "
                    "AND trigger.tgname = :trigger_name"
                ),
                {"trigger_name": _PROCESSING_EVENT_GUARD},
            )
            assert trigger_state == "O"


def _contexts(
    factory: sessionmaker[Session], snapshots: tuple[UUID, UUID]
) -> tuple[dict[str, object], dict[str, object]]:
    with factory() as session:
        return (
            received_context(session, snapshots[0]),
            received_context(session, snapshots[1]),
        )


def _stage_projection(
    factory: sessionmaker[Session], snapshots: tuple[UUID, UUID]
) -> dict[UUID, tuple[str, ...]]:
    with factory() as session:
        return {
            snapshot_id: tuple(
                session.scalars(
                    select(source_processing_event.c.stage)
                    .where(source_processing_event.c.source_snapshot_id == snapshot_id)
                    .order_by(source_processing_event.c.sequence_number)
                )
            )
            for snapshot_id in snapshots
        }


def _corrupt_context(context: dict[str, object], case: str) -> object:
    changed = dict(context)
    if case == "PAIR-01-initiating-policy":
        changed["operation_time_policy"] = "PROCESSING_TIME_V1"
    elif case == "PAIR-02-counterpart-unknown-policy":
        changed["operation_time_policy"] = "UNKNOWN_POLICY"
    elif case == "PAIR-03-counterpart-missing-policy":
        changed.pop("operation_time_policy")
    elif case == "PAIR-05-counterpart-role-mismatch":
        changed["resource_role"] = "BOOTSTRAP"
    elif case == "PAIR-06-counterpart-common-field":
        changed["captured_at"] = "2026-08-21T16:59:00Z"
    elif case == "PAIR-07-counterpart-hash-mismatch":
        changed["retrieval_pair_id"] = "00000000-0000-0000-0000-000000000000"
    else:  # pragma: no cover - the parameter table is closed below
        raise AssertionError(f"unsupported corruption case: {case}")
    return changed


@pytest.mark.parametrize(
    ("case", "target_index", "resume_index"),
    (
        pytest.param("PAIR-01-initiating-policy", 0, 0, id="PAIR-01"),
        pytest.param("PAIR-02-counterpart-unknown-policy", 1, 0, id="PAIR-02"),
        pytest.param("PAIR-03-counterpart-missing-policy", 1, 0, id="PAIR-03"),
        pytest.param("PAIR-04-counterpart-context-unavailable", 1, 0, id="PAIR-04"),
        pytest.param("PAIR-05-counterpart-role-mismatch", 1, 0, id="PAIR-05"),
        pytest.param("PAIR-06-counterpart-common-field", 1, 0, id="PAIR-06"),
        pytest.param("PAIR-07-counterpart-hash-mismatch", 1, 0, id="PAIR-07"),
    ),
)
def test_pair_01_through_07_context_corruption_fails_closed(
    case: str,
    target_index: int,
    resume_index: int,
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """PAIR-01..07: either stored member's corrupt context blocks pair resume."""

    service, snapshots = _interrupted_pair(repository_root)
    contexts = _contexts(postgres_session_factory, snapshots)
    mutation = (
        _received_stage_update(snapshots[target_index], "STORED")
        if case == "PAIR-04-counterpart-context-unavailable"
        else _received_update(
            snapshots[target_index],
            _corrupt_context(contexts[target_index], case),
        )
    )
    _assert_normal_mutation_blocked(postgres_session_factory, mutation)
    _apply_restored_state_corruption(
        postgres_session_factory,
        (mutation,),
    )
    stages_before_resume = _stage_projection(postgres_session_factory, snapshots)

    try:
        outcome = service.resume(snapshots[resume_index], database_url_ref=DATABASE_REF)
    except IngestionError as caught:
        assert caught.code == "LIFECYCLE_INVARIANT"
    else:
        pytest.fail(
            "corrupt pair resumed: "
            f"exit_code={outcome.exit_code}, "
            f"bundle_present={outcome.result.source_bundle is not None}"
        )
    with postgres_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(source_bundle)) == 0
    assert _stage_projection(postgres_session_factory, snapshots) == stages_before_resume


def test_pair_10_self_consistent_context_forgery_conflicts_with_run_anchor(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """PAIR-10: two forged contexts cannot replace the persisted logical run identity."""

    service, snapshots = _interrupted_pair(repository_root)
    contexts = _contexts(postgres_session_factory, snapshots)
    original_pair_key = contexts[0]["pair_key"]
    common = {
        key: value for key, value in contexts[0].items() if key not in {"pair_key", "resource_role"}
    }
    common["retrieval_pair_id"] = "00000000-0000-0000-0000-000000000000"
    forged_pair_key = canonical_sha256(common)
    assert forged_pair_key != original_pair_key
    forged_contexts = tuple(
        {
            **common,
            "pair_key": forged_pair_key,
            "resource_role": role,
        }
        for role in ("BOOTSTRAP", "FIXTURES")
    )
    for snapshot_id, context in zip(snapshots, forged_contexts, strict=True):
        _assert_normal_mutation_blocked(
            postgres_session_factory, _received_update(snapshot_id, context)
        )
    _apply_restored_state_corruption(
        postgres_session_factory,
        tuple(
            _received_update(snapshot_id, context)
            for snapshot_id, context in zip(snapshots, forged_contexts, strict=True)
        ),
    )

    with postgres_session_factory() as session:
        persisted_logical_key = session.scalar(
            select(ingestion_run.c.logical_run_key)
            .join(
                source_snapshot,
                source_snapshot.c.ingestion_run_id == ingestion_run.c.ingestion_run_id,
            )
            .where(source_snapshot.c.source_snapshot_id == snapshots[0])
        )
    assert persisted_logical_key == f"fpl004:{original_pair_key}"

    with pytest.raises(IngestionError) as caught:
        service.resume(snapshots[0], database_url_ref=DATABASE_REF)
    assert caught.value.code == "LIFECYCLE_INVARIANT"
