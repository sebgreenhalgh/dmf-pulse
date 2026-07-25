"""PostgreSQL proofs for append-only lifecycle and deterministic resume."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    competition,
    fixture,
    fixture_gameweek_assignment,
    fixture_revision,
    gameweek,
    ingestion_run,
    player,
    player_season,
    raw_storage_object,
    season,
    source_bundle,
    source_bundle_member,
    source_processing_event,
    source_snapshot,
    team,
    team_season,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl import service as service_module
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    DEFAULT_CAPTURED_AT,
    DEFAULT_INFORMATION_CUTOFF,
    FplIngestionService,
    FplReplayRequest,
    IngestionInterrupted,
)
from dmf_pulse.ingestion.repository import received_context

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SUCCESSFUL_STAGES = (
    "RECEIVED",
    "STORED",
    "PARSED",
    "VALIDATED",
    "MAPPED",
    "PROMOTED",
    "QUALITY_PASSED",
    "USABLE",
)


def _row_count(session: Session, table: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def _semantic_counts(factory: sessionmaker[Session]) -> dict[str, int]:
    with factory() as session:
        return {
            "competition": _row_count(session, competition),
            "fixture": _row_count(session, fixture),
            "fixture_assignment": _row_count(session, fixture_gameweek_assignment),
            "fixture_revision": _row_count(session, fixture_revision),
            "gameweek": _row_count(session, gameweek),
            "player": _row_count(session, player),
            "player_season": _row_count(session, player_season),
            "season": _row_count(session, season),
            "source_bundle": _row_count(session, source_bundle),
            "source_bundle_member": _row_count(session, source_bundle_member),
            "source_snapshot": _row_count(session, source_snapshot),
            "team": _row_count(session, team),
            "team_season": _row_count(session, team_season),
        }


def _stages(session: Session, snapshot_id: UUID) -> tuple[str, ...]:
    return tuple(
        session.scalars(
            select(source_processing_event.c.stage)
            .where(source_processing_event.c.source_snapshot_id == snapshot_id)
            .order_by(source_processing_event.c.sequence_number)
        )
    )


@pytest.fixture
def replay_request(repository_root: Path) -> FplReplayRequest:
    return FplReplayRequest(
        fixture_set=repository_root / "fixtures" / "fpl" / "FPL-004",
        scenario="happy_path",
        database_url_ref=DATABASE_REF,
    )


def _interruption_cases(repository_root: Path) -> Iterator[str]:
    contract = json.loads(
        (
            repository_root / "fixtures" / "fpl" / "FPL-004" / "lifecycle_resume_cases.json"
        ).read_text(encoding="utf-8")
    )
    yield from contract["stages"]


@pytest.mark.parametrize(
    "interruption_stage",
    (
        "STORED_OR_RAW_DISCARDED",
        "PARSED",
        "VALIDATED",
        "MAPPED",
        "PROMOTED",
    ),
)
def test_resume_executes_only_incomplete_suffix_without_duplicate_effects(
    interruption_stage: str,
    replay_request: FplReplayRequest,
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert interruption_stage in set(_interruption_cases(repository_root))
    service = FplIngestionService(repository_root=repository_root)
    interrupted_request = FplReplayRequest(
        fixture_set=replay_request.fixture_set,
        scenario=replay_request.scenario,
        information_cutoff=replay_request.information_cutoff,
        rights_profile_id=replay_request.rights_profile_id,
        database_url_ref=replay_request.database_url_ref,
        competition_key=replay_request.competition_key,
        season_code=replay_request.season_code,
        halt_after_stage=interruption_stage,
    )

    with pytest.raises(IngestionInterrupted) as caught:
        service.replay(interrupted_request)

    completed_stage = (
        "STORED" if interruption_stage == "STORED_OR_RAW_DISCARDED" else interruption_stage
    )
    assert caught.value.stage == completed_stage
    assert len(set(caught.value.snapshot_ids)) == 2
    prefix_length = SUCCESSFUL_STAGES.index(completed_stage) + 1
    with postgres_session_factory() as session:
        for snapshot_id in caught.value.snapshot_ids:
            assert _stages(session, snapshot_id) == SUCCESSFUL_STAGES[:prefix_length]
        if completed_stage == "STORED":
            stored = session.execute(
                select(
                    source_snapshot.c.body_sha256,
                    raw_storage_object.c.storage_uri,
                )
                .join(
                    raw_storage_object,
                    raw_storage_object.c.raw_storage_object_id
                    == source_snapshot.c.raw_storage_object_id,
                )
                .where(source_snapshot.c.source_snapshot_id.in_(caught.value.snapshot_ids))
            ).all()
            assert len(stored) == 2
            for body_sha256, storage_uri in stored:
                assert isinstance(storage_uri, str)
                location, separator, fragment = storage_uri.partition("#sha256=")
                assert separator and fragment == body_sha256
                assert location.startswith("repository://fixtures/")
                durable_path = repository_root / location.removeprefix("repository://")
                assert hashlib.sha256(durable_path.read_bytes()).hexdigest() == body_sha256
    if completed_stage == "PROMOTED":
        assert _semantic_counts(postgres_session_factory) == {
            "competition": 1,
            "fixture": 1,
            "fixture_assignment": 1,
            "fixture_revision": 1,
            "gameweek": 2,
            "player": 4,
            "player_season": 4,
            "season": 1,
            "source_bundle": 0,
            "source_bundle_member": 0,
            "source_snapshot": 2,
            "team": 2,
            "team_season": 2,
        }

    parse_calls = 0
    validation_calls = 0
    original_parse = service_module.parse_fpl_payload
    original_cross_validate = service_module._cross_validate

    def counted_parse(*args: object, **kwargs: object) -> Any:
        nonlocal parse_calls
        parse_calls += 1
        return original_parse(*args, **kwargs)

    def counted_cross_validate(*args: object, **kwargs: object) -> None:
        nonlocal validation_calls
        validation_calls += 1
        original_cross_validate(*args, **kwargs)

    monkeypatch.setattr(service_module, "parse_fpl_payload", counted_parse)
    monkeypatch.setattr(service_module, "_cross_validate", counted_cross_validate)
    if prefix_length > SUCCESSFUL_STAGES.index("PARSED"):
        monkeypatch.setattr(
            service_module,
            "approve_synthetic_fixture",
            lambda *_args, **_kwargs: pytest.fail("resume must reuse the parsed artifact"),
        )
        monkeypatch.setattr(
            service_module,
            "_read_bounded",
            lambda *_args, **_kwargs: pytest.fail("resume must not reread a parsed source"),
        )

    resumed = service.resume(caught.value.snapshot_ids[0], database_url_ref=DATABASE_REF)

    assert parse_calls == (2 if completed_stage == "STORED" else 0)
    assert validation_calls == (1 if completed_stage in {"STORED", "PARSED"} else 0)
    assert resumed.exit_code == 0
    assert resumed.result.status == "USABLE"
    assert resumed.result.source_bundle is not None
    assert tuple(member.role for member in resumed.result.source_bundle.members) == (
        "BOOTSTRAP",
        "FIXTURES",
    )
    assert {resource.lifecycle_state for resource in resumed.result.resources} == {"USABLE"}
    assert _semantic_counts(postgres_session_factory) == {
        "competition": 1,
        "fixture": 1,
        "fixture_assignment": 1,
        "fixture_revision": 1,
        "gameweek": 2,
        "player": 4,
        "player_season": 4,
        "season": 1,
        "source_bundle": 1,
        "source_bundle_member": 2,
        "source_snapshot": 2,
        "team": 2,
        "team_season": 2,
    }
    with postgres_session_factory() as session:
        for snapshot_id in caught.value.snapshot_ids:
            stages = _stages(session, snapshot_id)
            assert stages == SUCCESSFUL_STAGES
            assert len(stages) == len(set(stages))

    before_replay = _semantic_counts(postgres_session_factory)
    replayed = service.resume(caught.value.snapshot_ids[1], database_url_ref=DATABASE_REF)
    assert replayed.result.source_bundle is not None
    assert replayed.result.source_bundle.bundle_id == resumed.result.source_bundle.bundle_id
    assert replayed.result.source_bundle.semantic_sha256 == (
        resumed.result.source_bundle.semantic_sha256
    )
    assert _semantic_counts(postgres_session_factory) == before_replay


def test_lifecycle_events_are_append_only_and_have_one_monotonic_sequence(
    replay_request: FplReplayRequest,
    repository_root: Path,
    postgres_engine: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    outcome = FplIngestionService(repository_root=repository_root).replay(replay_request)
    assert outcome.result.source_bundle is not None

    with postgres_session_factory() as session:
        snapshot_ids = tuple(resource.source_snapshot_id for resource in outcome.result.resources)
        for snapshot_id in snapshot_ids:
            events = session.execute(
                select(
                    source_processing_event.c.sequence_number,
                    source_processing_event.c.stage,
                    source_processing_event.c.event_at,
                    source_processing_event.c.previous_event_id,
                )
                .where(source_processing_event.c.source_snapshot_id == snapshot_id)
                .order_by(source_processing_event.c.sequence_number)
            ).all()
            assert tuple(row.stage for row in events) == SUCCESSFUL_STAGES
            assert tuple(row.sequence_number for row in events) == tuple(range(1, 9))
            assert tuple(row.event_at for row in events) == tuple(
                sorted(row.event_at for row in events)
            )
            assert events[0].previous_event_id is None
            assert all(
                events[index].previous_event_id is not None for index in range(1, len(events))
            )
        envelopes = session.execute(
            select(
                source_snapshot.c.ingestion_run_id,
                source_snapshot.c.attempt_number,
            ).order_by(source_snapshot.c.source_snapshot_id)
        ).all()
        assert len(envelopes) == 2
        assert len({row.ingestion_run_id for row in envelopes}) == 1
        assert all(row.attempt_number == 1 for row in envelopes)
        assert _row_count(session, ingestion_run) == 1

    snapshot_id = outcome.result.resources[0].source_snapshot_id
    with pytest.raises(DBAPIError), postgres_engine.begin() as connection:
        connection.execute(
            source_processing_event.update()
            .where(source_processing_event.c.source_snapshot_id == snapshot_id)
            .values(stage="CANCELLED")
        )


def test_identical_interrupted_retrievals_resume_only_the_requested_pair(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    request = FplReplayRequest(
        fixture_set=repository_root / "fixtures/fpl/FPL-004",
        scenario="happy_path",
        database_url_ref=DATABASE_REF,
        halt_after_stage="PARSED",
    )
    service = FplIngestionService(repository_root=repository_root)
    interrupted: list[IngestionInterrupted] = []
    for _index in range(2):
        with pytest.raises(IngestionInterrupted) as caught:
            service.replay(request)
        interrupted.append(caught.value)

    first_ids = set(interrupted[0].snapshot_ids)
    second_ids = set(interrupted[1].snapshot_ids)
    assert first_ids.isdisjoint(second_ids)
    with postgres_session_factory() as session:
        pair_keys = {
            str(received_context(session, next(iter(snapshot_ids)))["pair_key"])
            for snapshot_ids in (first_ids, second_ids)
        }
    assert len(pair_keys) == 2

    resumed = service.resume(interrupted[1].snapshot_ids[0], database_url_ref=DATABASE_REF)
    assert {resource.source_snapshot_id for resource in resumed.result.resources} == second_ids
    with postgres_session_factory() as session:
        assert all(
            _stages(session, snapshot_id) == SUCCESSFUL_STAGES[:3] for snapshot_id in first_ids
        )
        assert all(_stages(session, snapshot_id) == SUCCESSFUL_STAGES for snapshot_id in second_ids)


def test_repeated_retryable_failures_resume_with_actual_usable_timestamps(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    request = FplReplayRequest(
        fixture_set=repository_root / "fixtures/fpl/FPL-004",
        scenario="happy_path",
        database_url_ref=DATABASE_REF,
        halt_after_stage="PARSED",
    )
    service = FplIngestionService(repository_root=repository_root)
    with pytest.raises(IngestionInterrupted) as caught:
        service.replay(request)
    with postgres_session_factory() as session:
        pair_key = received_context(session, caught.value.snapshot_ids[0])["pair_key"]
    assert isinstance(pair_key, str)
    failure = IngestionError(
        "DATABASE_RETRYABLE",
        "synthetic retryable transaction failure",
        retryable=True,
    )
    service._record_retryable_failure(
        postgres_session_factory,
        DEFAULT_CAPTURED_AT,
        caught.value.snapshot_ids,
        pair_key,
        failure,
    )
    service._record_retryable_failure(
        postgres_session_factory,
        DEFAULT_CAPTURED_AT,
        caught.value.snapshot_ids,
        pair_key,
        failure,
    )

    resumed = service.resume(caught.value.snapshot_ids[0], database_url_ref=DATABASE_REF)
    assert resumed.exit_code == 0
    assert resumed.result.source_bundle is not None
    with postgres_session_factory() as session:
        for snapshot_id in caught.value.snapshot_ids:
            events = session.execute(
                select(
                    source_processing_event.c.stage,
                    source_processing_event.c.event_at,
                )
                .where(source_processing_event.c.source_snapshot_id == snapshot_id)
                .order_by(source_processing_event.c.sequence_number)
            ).all()
            assert tuple(row.stage for row in events) == (
                "RECEIVED",
                "STORED",
                "PARSED",
                "FAILED_RETRYABLE",
                "FAILED_RETRYABLE",
                "VALIDATED",
                "MAPPED",
                "PROMOTED",
                "QUALITY_PASSED",
                "USABLE",
            )
            assert tuple(row.event_at for row in events) == tuple(
                sorted(row.event_at for row in events)
            )
            resource = next(
                item for item in resumed.result.resources if item.source_snapshot_id == snapshot_id
            )
            assert resource.usable_at == events[-1].event_at


def test_resume_after_cutoff_uses_resume_clock_and_cannot_backdate_bundle_eligibility(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    current = [DEFAULT_CAPTURED_AT]
    service = FplIngestionService(
        repository_root=repository_root,
        clock=lambda: current[0],
    )
    request = FplReplayRequest(
        fixture_set=repository_root / "fixtures/fpl/FPL-004",
        scenario="happy_path",
        information_cutoff=DEFAULT_INFORMATION_CUTOFF,
        database_url_ref=DATABASE_REF,
        halt_after_stage="PARSED",
    )
    with pytest.raises(IngestionInterrupted) as caught:
        service.replay(request)

    current[0] = DEFAULT_INFORMATION_CUTOFF + timedelta(minutes=1)
    resumed = service.resume(caught.value.snapshot_ids[0], database_url_ref=DATABASE_REF)

    assert resumed.exit_code == 2
    assert resumed.result.source_bundle is None
    assert resumed.result.canonical_effects["outcome"] == "OBSERVED_NOT_BUNDLE_ELIGIBLE"
    assert all(
        resource.usable_at is not None and resource.usable_at > DEFAULT_INFORMATION_CUTOFF
        for resource in resumed.result.resources
    )
    with postgres_session_factory() as session:
        assert _row_count(session, source_bundle) == 0


@pytest.mark.parametrize("tamper", ["rights-config", "provider-config", "profile-version"])
def test_resume_rejects_authority_drift_before_adding_an_event(
    tamper: str,
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FplReplayRequest(
        fixture_set=repository_root / "fixtures/fpl/FPL-004",
        scenario="happy_path",
        database_url_ref=DATABASE_REF,
        halt_after_stage="PARSED",
    )
    service = FplIngestionService(repository_root=repository_root)
    with pytest.raises(IngestionInterrupted) as caught:
        service.replay(request)
    if tamper == "rights-config":
        monkeypatch.setattr(service_module, "rights_config_sha256", lambda: "f" * 64)
    elif tamper == "provider-config":
        monkeypatch.setattr(service_module, "provider_config_sha256", lambda: "f" * 64)
    else:
        profile = service_module._profile("synthetic_test_v1")
        monkeypatch.setattr(
            service_module,
            "_profile",
            lambda _profile_id: profile.model_copy(update={"profile_version": "1.0.1"}),
        )

    with pytest.raises(IngestionError) as raised:
        service.resume(caught.value.snapshot_ids[0], database_url_ref=DATABASE_REF)
    assert raised.value.code == "RIGHTS_BLOCKED"
    with postgres_session_factory() as session:
        assert all(
            _stages(session, snapshot_id) == SUCCESSFUL_STAGES[:3]
            for snapshot_id in caught.value.snapshot_ids
        )
