"""Post-commit publication-time and repair boundary oracles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

import dmf_pulse.ingestion.odds.service as odds_service
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.mapping import load_mapping_plan
from dmf_pulse.ingestion.odds.parser import ParsedOddsPayload, parse_odds_payload
from dmf_pulse.ingestion.odds.persistence import PublishCounts
from dmf_pulse.ingestion.odds.service import (
    OddsImportRequest,
    OddsIngestionService,
    _Envelope,
    _PromotionOutcome,
)

pytestmark = pytest.mark.unit

CAPTURED_AT = datetime(2026, 8, 20, 12, tzinfo=UTC)
PROCESSING_AT = CAPTURED_AT + timedelta(seconds=1)
PUBLICATION_BATCH_ID = UUID("00000000-0000-0000-0000-000000000201")
COUNTS = PublishCounts(
    operator_books_seen=3,
    complete_books_created=2,
    incomplete_books_created=1,
    observations_created=6,
    observations_reused=0,
)


class _Result:
    def __init__(self, value: object) -> None:
        self.value = value

    def mappings(self) -> _Result:
        return self

    def one_or_none(self) -> object:
        return self.value


class _Session:
    def __init__(self, row: object = None) -> None:
        self.row = row

    def execute(self, *_args: object, **_kwargs: object) -> _Result:
        return _Result(self.row)


class _Context:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def __enter__(self) -> _Session:
        return self.session

    def __exit__(self, *_args: object) -> None:
        return None


class _Factory:
    def __init__(self, row: object = None) -> None:
        self.session = _Session(row)
        self.begin_calls = 0
        self.query_calls = 0

    def __call__(self) -> _Context:
        self.query_calls += 1
        return _Context(self.session)

    def begin(self) -> _Context:
        self.begin_calls += 1
        return _Context(self.session)


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _Persistence:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def prepare(self, parsed: ParsedOddsPayload) -> object:
        return parsed

    @staticmethod
    def publish_prepared(*_args: object, **_kwargs: object) -> PublishCounts:
        return COUNTS


def _parsed(repository_root: Path) -> ParsedOddsPayload:
    return parse_odds_payload(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes()
    )


@pytest.mark.parametrize(
    (
        "sampled",
        "attestation_fails",
        "expected_error",
        "expected_begin_calls",
        "expected_blocker",
    ),
    [
        (
            datetime(2026, 8, 20, 12, 0, 2),
            False,
            "PUBLICATION_CLOCK_INVALID",
            2,
            True,
        ),
        (
            RuntimeError("synthetic clock failure"),
            False,
            "PUBLICATION_CLOCK_INVALID",
            2,
            True,
        ),
        (
            CAPTURED_AT - timedelta(microseconds=1),
            False,
            "PUBLICATION_CLOCK_REGRESSION",
            2,
            True,
        ),
        (
            PROCESSING_AT + timedelta(microseconds=1),
            True,
            "PUBLICATION_ATTESTATION_PENDING",
            3,
            False,
        ),
    ],
)
def test_post_commit_promotion_preserves_activation_on_attestation_failure(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    sampled: datetime | Exception,
    attestation_fails: bool,
    expected_error: str,
    expected_begin_calls: int,
    expected_blocker: bool,
) -> None:
    """A post-commit time failure never rolls back the activation transaction."""

    factory = _Factory()
    attestation_calls: list[datetime] = []

    def attest(*_args: object, **kwargs: object) -> datetime:
        usable_at = kwargs["usable_at"]
        assert isinstance(usable_at, datetime)
        attestation_calls.append(usable_at)
        if attestation_fails:
            raise IngestionError("DATABASE_RETRYABLE", "synthetic attestation failure")
        return usable_at

    monkeypatch.setattr(odds_service, "OddsPersistence", _Persistence)
    monkeypatch.setattr(
        odds_service,
        "append_processing_event_idempotent",
        lambda *_args, **_kwargs: UUID(int=101),
    )
    monkeypatch.setattr(
        odds_service,
        "create_publication_batch",
        lambda *_args, **_kwargs: PUBLICATION_BATCH_ID,
    )
    monkeypatch.setattr(odds_service, "attest_publication_batch", attest)
    service = OddsIngestionService(repository_root=repository_root)
    clock_calls = 0

    def post_commit_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        assert factory.begin_calls >= 2
        if isinstance(sampled, Exception):
            raise sampled
        return sampled

    outcome = service._promote(
        factory,  # type: ignore[arg-type]
        envelope=_Envelope(UUID(int=1), UUID(int=2)),
        parsed=_parsed(repository_root),
        mapping_plan=load_mapping_plan(repository_root / "fixtures/odds/ODD-005/mapping_plan.json"),
        captured_at=CAPTURED_AT,
        processing_at=PROCESSING_AT,
        mapping_cutoff=CAPTURED_AT,
        post_commit_clock=post_commit_clock,
    )

    assert outcome.counts == COUNTS
    assert outcome.publication_batch_id == PUBLICATION_BATCH_ID
    assert outcome.usable_at is None
    assert outcome.attestation_error == expected_error
    assert outcome.temporal_integrity_blocker is expected_blocker
    assert factory.begin_calls == expected_begin_calls
    assert len(attestation_calls) == int(attestation_fails)
    assert clock_calls == 1


def test_import_request_cannot_preselect_post_commit_usable_at() -> None:
    assert "post_commit_usable_at" not in OddsImportRequest.model_fields


@pytest.mark.parametrize(
    ("attestation_error", "temporal_blocker", "expected_exit", "expected_quality"),
    [
        ("PUBLICATION_CLOCK_INVALID", True, 4, "BLOCKING"),
        ("PUBLICATION_CLOCK_REGRESSION", True, 4, "BLOCKING"),
        ("PUBLICATION_ATTESTATION_PENDING", False, 2, "WARNING"),
    ],
)
def test_committed_unattested_batch_reports_temporal_clock_failures_as_blocking(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    attestation_error: str,
    temporal_blocker: bool,
    expected_exit: int,
    expected_quality: str,
) -> None:
    factory = _Factory()
    engine = _Engine()
    service = OddsIngestionService(repository_root=repository_root)
    monkeypatch.setattr(service, "_engine", lambda _reference: engine)
    monkeypatch.setattr(odds_service, "session_factory", lambda _engine: factory)
    monkeypatch.setattr(
        service,
        "_create_envelope",
        lambda *_args, **_kwargs: _Envelope(UUID(int=1), UUID(int=2)),
    )
    monkeypatch.setattr(
        service,
        "_promote",
        lambda *_args, **_kwargs: _PromotionOutcome(
            COUNTS,
            PUBLICATION_BATCH_ID,
            None,
            attestation_error,
            temporal_blocker,
        ),
    )

    outcome = service._ingest(
        body=(repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes(),
        approved_fixture=None,
        mapping_plan=load_mapping_plan(repository_root / "fixtures/odds/ODD-005/mapping_plan.json"),
        profile=load_rights_profiles()["synthetic_the_odds_api_v1"],
        captured_at=CAPTURED_AT,
        information_cutoff=CAPTURED_AT,
        database_url_ref="DMF_PULSE_DATABASE_URL",
        quota=None,
        operation="synthetic_import",
        processing_at=PROCESSING_AT,
        post_commit_clock=lambda: PROCESSING_AT,
    )

    assert outcome.exit_code == expected_exit
    assert outcome.result.status == "OBSERVED_NOT_USABLE"
    assert outcome.result.quality.status == expected_quality
    assert (attestation_error in outcome.result.quality.blockers) is temporal_blocker
    assert (attestation_error in outcome.result.quality.warnings) is not temporal_blocker
    assert outcome.result.observations_created == COUNTS.observations_created
    assert engine.disposed is True


def _repair_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    row: object,
    sampled: datetime,
) -> tuple[OddsIngestionService, _Factory, _Engine]:
    service = OddsIngestionService(clock=lambda: sampled)
    factory = _Factory(row)
    engine = _Engine()
    monkeypatch.setattr(service, "_engine", lambda _reference: engine)
    monkeypatch.setattr(odds_service, "session_factory", lambda _engine: factory)
    return service, factory, engine


def test_publication_repair_rejects_a_missing_batch_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, factory, engine = _repair_service(
        monkeypatch,
        row=None,
        sampled=PROCESSING_AT,
    )

    with pytest.raises(IngestionError) as caught:
        service.repair_publication_attestation(source_snapshot_id=UUID(int=1))

    assert caught.value.code == "ATTESTATION_UNAVAILABLE"
    assert factory.query_calls == 1
    assert factory.begin_calls == 0
    assert engine.disposed is True


def test_publication_repair_reuses_an_existing_attestation_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = PROCESSING_AT + timedelta(seconds=1)
    service, factory, engine = _repair_service(
        monkeypatch,
        row={
            "publication_batch_id": PUBLICATION_BATCH_ID,
            "activation_event_at": CAPTURED_AT,
            "received_at": CAPTURED_AT,
            "usable_at": existing,
        },
        sampled=PROCESSING_AT,
    )

    assert service.repair_publication_attestation(source_snapshot_id=UUID(int=1)) == existing
    assert factory.query_calls == 1
    assert factory.begin_calls == 0
    assert engine.disposed is True


def test_publication_repair_rejects_clock_regression_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, factory, engine = _repair_service(
        monkeypatch,
        row={
            "publication_batch_id": PUBLICATION_BATCH_ID,
            "activation_event_at": PROCESSING_AT + timedelta(seconds=2),
            "received_at": CAPTURED_AT,
            "usable_at": None,
        },
        sampled=PROCESSING_AT + timedelta(seconds=1),
    )

    with pytest.raises(IngestionError) as caught:
        service.repair_publication_attestation(source_snapshot_id=UUID(int=1))

    assert caught.value.code == "CLOCK_REGRESSION"
    assert factory.query_calls == 1
    assert factory.begin_calls == 0
    assert engine.disposed is True


def test_publication_repair_rejects_a_naive_clock_with_typed_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, factory, engine = _repair_service(
        monkeypatch,
        row={
            "publication_batch_id": PUBLICATION_BATCH_ID,
            "activation_event_at": PROCESSING_AT,
            "activated_at": PROCESSING_AT + timedelta(days=365),
            "received_at": CAPTURED_AT,
            "usable_at": None,
        },
        sampled=PROCESSING_AT.replace(tzinfo=None),
    )

    with pytest.raises(IngestionError) as caught:
        service.repair_publication_attestation(source_snapshot_id=UUID(int=1))

    assert caught.value.code == "CLOCK_INVALID"
    assert factory.query_calls == 1
    assert factory.begin_calls == 0
    assert engine.disposed is True


def test_publication_repair_uses_logical_event_time_not_audit_wall_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampled = PROCESSING_AT + timedelta(seconds=1)
    service, factory, engine = _repair_service(
        monkeypatch,
        row={
            "publication_batch_id": PUBLICATION_BATCH_ID,
            "activation_event_at": PROCESSING_AT,
            "activated_at": PROCESSING_AT + timedelta(days=365),
            "received_at": CAPTURED_AT,
            "usable_at": None,
        },
        sampled=sampled,
    )
    calls: list[tuple[UUID, datetime]] = []

    def attest(*_args: object, **kwargs: object) -> datetime:
        publication_batch_id = kwargs["publication_batch_id"]
        usable_at = kwargs["usable_at"]
        assert isinstance(publication_batch_id, UUID)
        assert isinstance(usable_at, datetime)
        calls.append((publication_batch_id, usable_at))
        return usable_at

    monkeypatch.setattr(odds_service, "attest_publication_batch", attest)

    assert service.repair_publication_attestation(source_snapshot_id=UUID(int=1)) == sampled
    assert calls == [(PUBLICATION_BATCH_ID, sampled)]
    assert factory.query_calls == 1
    assert factory.begin_calls == 1
    assert engine.disposed is True
