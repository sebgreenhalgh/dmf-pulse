"""Immutable normalisation persistence boundary oracles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.markets.consensus import evaluate_market_consensus
from dmf_pulse.markets.models import (
    ExcludedBook,
    ExclusionReason,
    MarketNormalisationResult,
    NormalisationStatus,
)
from dmf_pulse.markets.policy import (
    MarketNormalisationPolicy,
    load_market_normalisation_policy,
)
from dmf_pulse.markets.repository import MarketObservationRepository

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 8, 20, 12, tzinfo=UTC)
FIXTURE_ID = UUID("00000000-0000-0000-0000-000000000601")
RUN_ID = UUID("00000000-0000-0000-0000-000000000602")
INPUT_SHA256 = "a" * 64
RESULT_SHA256 = "b" * 64


class _Result:
    def __init__(self, value: object) -> None:
        self.value = value

    def mappings(self) -> _Result:
        return self

    def one(self) -> object:
        return self.value

    def scalar_one_or_none(self) -> object:
        return self.value

    def scalar_one(self) -> object:
        return self.value


class _SequenceSession:
    def __init__(self, values: list[object]) -> None:
        self.values = values
        self.statements: list[object] = []

    def execute(self, statement: object, *_args: object, **_kwargs: object) -> _Result:
        self.statements.append(statement)
        value = self.values.pop(0) if self.values else None
        return _Result(value)


class _Rows:
    def __init__(self, value: object) -> None:
        self.value = value

    def mappings(self) -> _Rows:
        return self

    def __iter__(self):
        return iter(self.value if isinstance(self.value, list) else ())


class _SequencedRowsSession:
    def __init__(self, values: list[list[dict[str, object]]]) -> None:
        self.values = values
        self.statements: list[object] = []
        self.parameters: list[object] = []
        self.lock_error: DBAPIError | None = None

    def execute(self, statement: object, *_args: object, **_kwargs: object) -> _Rows:
        self.statements.append(statement)
        self.parameters.append(_args[0] if _args else _kwargs)
        if str(statement).startswith("SET LOCAL lock_timeout"):
            return _Rows([])
        if "pg_advisory_xact_lock" in str(statement):
            if self.lock_error is not None:
                raise self.lock_error
            return _Rows([])
        return _Rows(self.values.pop(0))


class _SqlStateError(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate


def _db_error(sqlstate: str) -> DBAPIError:
    return DBAPIError("synthetic", {}, _SqlStateError(sqlstate))


def _blocked_without_fixture() -> MarketNormalisationResult:
    return MarketNormalisationResult(
        status=NormalisationStatus.BLOCKED,
        fixture_id=None,
        as_of=AS_OF,
        consensus=None,
        excluded_books=(),
        warnings=(),
        error_code="MAPPING_CONFLICT",
    )


def _insufficient() -> MarketNormalisationResult:
    return MarketNormalisationResult(
        status=NormalisationStatus.INSUFFICIENT,
        fixture_id=FIXTURE_ID,
        as_of=AS_OF,
        consensus=None,
        excluded_books=(
            ExcludedBook(
                operator_key="synthetic_incomplete",
                reason=ExclusionReason.INCOMPLETE,
            ),
        ),
        warnings=("BOOK_EXCLUDED_INCOMPLETE",),
        error_code="NO_ELIGIBLE_COMPLETE_BOOK",
    )


def _stored_policy(policy: MarketNormalisationPolicy) -> dict[str, object]:
    return {
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
        "policy_document": policy.model_dump(mode="json", exclude={"sha256"}),
    }


def _observation_rows(
    *,
    book_number: int = 101,
    source_number: int = 103,
    usable_at: datetime | None = None,
    observed_at: datetime | None = None,
    market_state: str = "COMPLETE",
) -> list[dict[str, object]]:
    outcomes = ("HOME", "DRAW", "AWAY")
    return [
        {
            "book_observation_id": UUID(int=book_number),
            "market_id": UUID(int=102),
            "source_snapshot_id": UUID(int=source_number),
            "market_state": market_state,
            "operator_id": UUID(int=104),
            "operator_key": "book_alpha",
            "provider_id": UUID(int=105),
            "provider_observed_at": observed_at or AS_OF - timedelta(seconds=10),
            "attested_usable_at": usable_at or AS_OF - timedelta(seconds=1),
            "selection_id": UUID(int=book_number + 10 + index),
            "outcome": outcome,
            "decimal_odds": (Decimal("1.80"), Decimal("3.60"), Decimal("4.20"))[index],
            "observed_at": observed_at or AS_OF - timedelta(seconds=10),
            "received_at": AS_OF - timedelta(seconds=5),
            "contract_version": "the-odds-api-v4-reference-v1",
            "odds_observation_id": UUID(int=book_number + 20 + index),
        }
        for index, outcome in enumerate(outcomes)
    ]


def _eligibility_row(**updates: object) -> dict[str, object]:
    expected_commence_time = AS_OF + timedelta(days=2)
    dependency_fields = {
        "provider_market_representation_id": UUID(int=201),
        "mapping_plan_sha256": "d" * 64,
        "fixture_lookup_mapping_id": UUID(int=202),
        "home_team_mapping_id": UUID(int=203),
        "away_team_mapping_id": UUID(int=204),
        "fixture_observation_id": UUID(int=205),
        "expected_commence_time": expected_commence_time,
    }
    dependency_material = {
        key: str(value)
        if isinstance(value, UUID)
        else value.isoformat()
        if isinstance(value, datetime)
        else value
        for key, value in dependency_fields.items()
    }
    row: dict[str, object] = {
        "book_observation_id": UUID(int=101),
        "market_state": "COMPLETE",
        "operator_key": "book_alpha",
        "mapping_plan_approved_at": AS_OF - timedelta(days=1),
        **dependency_fields,
        "dependency_sha256": canonical_sha256(dependency_material),
        "representation_matches_plan": True,
        "event_mapping_valid": True,
        "operator_mapping_valid": True,
        "schedule_matches": True,
        "fixture_mapping_valid": True,
        "home_team_mapping_valid": True,
        "away_team_mapping_valid": True,
        "rights_valid": True,
        "blocking_issue_count": 0,
        "warning_codes": [],
    }
    row.update(updates)
    return row


def _persist(
    session: _SequenceSession,
    result: MarketNormalisationResult,
    policy: MarketNormalisationPolicy,
) -> UUID:
    return MarketObservationRepository(session).persist_normalisation(  # type: ignore[arg-type]
        result=result,
        policy=policy,
        observations=(),
        book_sources=(),
        input_signature_sha256=INPUT_SHA256,
        semantic_result_sha256=RESULT_SHA256,
    )


def test_normalisation_without_fixture_is_never_persisted() -> None:
    policy = load_market_normalisation_policy()
    session = _SequenceSession([])

    with pytest.raises(IngestionError) as caught:
        _persist(session, _blocked_without_fixture(), policy)

    assert caught.value.code == "MAPPING_CONFLICT"
    assert session.statements == []


def test_stored_policy_identity_conflict_is_rejected() -> None:
    policy = load_market_normalisation_policy()
    stored = _stored_policy(policy)
    stored["policy_version"] = "0.0.0"
    session = _SequenceSession([None, stored])

    with pytest.raises(IngestionError) as caught:
        _persist(session, _insufficient(), policy)

    assert caught.value.code == "POLICY_INVALID"
    assert len(session.statements) == 2


def test_policy_self_hash_conflict_is_rejected_before_persistence() -> None:
    policy = load_market_normalisation_policy().model_copy(update={"sha256": "0" * 64})
    session = _SequenceSession([])

    with pytest.raises(IngestionError) as caught:
        _persist(session, _insufficient(), policy)

    assert caught.value.code == "POLICY_INVALID"
    assert session.statements == []


def test_existing_normalisation_run_is_reused_only_for_an_exact_identity() -> None:
    policy = load_market_normalisation_policy()
    existing = {
        "normalisation_run_id": RUN_ID,
        "fixture_id": FIXTURE_ID,
        "as_of": AS_OF,
        "mapping_cutoff": AS_OF,
        "policy_sha256": policy.sha256,
        "semantic_result_sha256": RESULT_SHA256,
        "status": NormalisationStatus.INSUFFICIENT.value,
    }
    session = _SequenceSession([None, _stored_policy(policy), None, existing])

    assert _persist(session, _insufficient(), policy) == RUN_ID
    assert len(session.statements) == 4


def test_existing_normalisation_run_identity_conflict_is_rejected() -> None:
    policy = load_market_normalisation_policy()
    existing = {
        "normalisation_run_id": RUN_ID,
        "fixture_id": FIXTURE_ID,
        "as_of": AS_OF,
        "mapping_cutoff": AS_OF,
        "policy_sha256": policy.sha256,
        "semantic_result_sha256": "c" * 64,
        "status": NormalisationStatus.INSUFFICIENT.value,
    }
    session = _SequenceSession([None, _stored_policy(policy), None, existing])

    with pytest.raises(IngestionError) as caught:
        _persist(session, _insufficient(), policy)

    assert caught.value.code == "CANONICAL_INVARIANT"
    assert len(session.statements) == 4


def test_created_consensus_free_run_persists_exclusions_and_warnings() -> None:
    policy = load_market_normalisation_policy()
    session = _SequenceSession([None, _stored_policy(policy), RUN_ID, None, None])

    assert _persist(session, _insufficient(), policy) == RUN_ID

    inserted_tables = [
        getattr(getattr(statement, "table", None), "name", None) for statement in session.statements
    ]
    assert "market_consensus_result" not in inserted_tables
    assert "market_normalisation_exclusion" in inserted_tables
    assert "market_normalisation_warning" in inserted_tables


def test_operator_source_absent_from_run_lineage_is_rejected() -> None:
    policy = load_market_normalisation_policy()
    books = MarketObservationRepository._books_from_rows(
        fixture_id=FIXTURE_ID,
        rows=_observation_rows(),
    )
    evaluation = evaluate_market_consensus(
        books[0].observations,
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=policy,
    )
    assert evaluation.consensus is not None
    result = MarketNormalisationResult(
        status=NormalisationStatus.NORMALISED,
        fixture_id=FIXTURE_ID,
        as_of=AS_OF,
        consensus=evaluation.consensus,
        excluded_books=evaluation.exclusions,
        warnings=evaluation.warnings,
        error_code=None,
    )
    session = _SequenceSession([None, _stored_policy(policy), RUN_ID, UUID(int=999)])

    with pytest.raises(IngestionError) as caught:
        _persist(session, result, policy)

    assert caught.value.code == "CANONICAL_INVARIANT"
    assert "normalised operator source is absent from run lineage" in str(caught.value)
    assert len(session.statements) == 4


def test_historical_eligibility_rejects_plan_approved_after_requested_cutoff() -> None:
    repository = MarketObservationRepository(
        _SequencedRowsSession(
            [
                _observation_rows(),
                [_eligibility_row(mapping_plan_approved_at=AS_OF + timedelta(microseconds=1))],
            ]
        )  # type: ignore[arg-type]
    )

    result = repository.normalisation_input(
        fixture_id=FIXTURE_ID,
        fixture_external_provider="synthetic_fpl",
        fixture_external_id="101",
        as_of=AS_OF,
        stale_after_seconds=1800,
    )

    assert result.eligible_observations == ()
    assert len(result.source_observations) == 3
    assert result.exclusions == (
        ExcludedBook(
            operator_key="book_alpha",
            reason=ExclusionReason.MAPPING_UNAVAILABLE,
        ),
    )
    assert "BOOK_EXCLUDED_MAPPING_UNAVAILABLE" in result.warnings


def test_quality_locks_cover_every_candidate_snapshot_in_deterministic_order() -> None:
    session = _SequencedRowsSession([])
    repository = MarketObservationRepository(session)  # type: ignore[arg-type]

    repository._lock_quality_subjects({UUID(int=3), UUID(int=1), UUID(int=2)})

    assert str(session.statements[0]).startswith("SET LOCAL lock_timeout")
    assert all("pg_advisory_xact_lock" in str(statement) for statement in session.statements[1:])
    assert session.parameters[1:] == [
        {"lock_key": f"bundle-quality:{UUID(int=1)}"},
        {"lock_key": f"bundle-quality:{UUID(int=2)}"},
        {"lock_key": f"bundle-quality:{UUID(int=3)}"},
    ]


@pytest.mark.parametrize(
    ("sqlstate", "code", "retryable"),
    [
        pytest.param("55P03", "DATABASE_RETRYABLE", True, id="timeout"),
        pytest.param("08006", "DATABASE_UNAVAILABLE", False, id="connection"),
    ],
)
def test_quality_lock_database_failures_are_typed(
    sqlstate: str,
    code: str,
    retryable: bool,
) -> None:
    session = _SequencedRowsSession([])
    session.lock_error = _db_error(sqlstate)
    repository = MarketObservationRepository(session)  # type: ignore[arg-type]

    with pytest.raises(IngestionError) as caught:
        repository._lock_quality_subjects({UUID(int=1)})

    assert caught.value.code == code
    assert caught.value.retryable is retryable


def test_test_only_schedule_attested_after_cutoff_is_mapping_unavailable() -> None:
    session = _SequencedRowsSession(
        [
            _observation_rows(),
            [_eligibility_row(schedule_matches=False)],
        ]
    )
    repository = MarketObservationRepository(session)  # type: ignore[arg-type]

    result = repository.normalisation_input(
        fixture_id=FIXTURE_ID,
        fixture_external_provider="synthetic_fpl",
        fixture_external_id="101",
        as_of=AS_OF,
        stale_after_seconds=1800,
    )

    assert result.eligible_observations == ()
    assert result.exclusions == (
        ExcludedBook(operator_key="book_alpha", reason=ExclusionReason.MAPPING_UNAVAILABLE),
    )
    eligibility_sql = str(session.statements[-1])
    assert "schedule.usable_at <= :cutoff" in eligibility_sql
    assert "batch.mapping_evidence_class = 'TEST_ONLY'" not in eligibility_sql
    lock_index = next(
        index
        for index, statement in enumerate(session.statements)
        if "pg_advisory_xact_lock" in str(statement)
    )
    assert lock_index < len(session.statements) - 1
    assert session.parameters[lock_index] == {"lock_key": f"bundle-quality:{UUID(int=103)}"}


def test_p1_mislabeled_nonblocking_still_blocks_the_whole_book() -> None:
    repository = MarketObservationRepository(
        _SequencedRowsSession(
            [
                _observation_rows(),
                [
                    _eligibility_row(
                        blocking_issue_count=1,
                        warning_codes=["MISLABELED_P1_NONBLOCKING"],
                    )
                ],
            ]
        )  # type: ignore[arg-type]
    )

    result = repository.normalisation_input(
        fixture_id=FIXTURE_ID,
        fixture_external_provider="synthetic_fpl",
        fixture_external_id="101",
        as_of=AS_OF,
        stale_after_seconds=1800,
    )

    assert result.eligible_observations == ()
    assert result.exclusions == (
        ExcludedBook(operator_key="book_alpha", reason=ExclusionReason.QUALITY_BLOCKED),
    )
    assert result.warnings == ("BOOK_EXCLUDED_QUALITY_BLOCKED",)


@pytest.mark.parametrize(
    ("eligibility_updates", "older_state"),
    [
        pytest.param({"event_mapping_valid": False}, "COMPLETE", id="mapping"),
        pytest.param({"rights_valid": False}, "COMPLETE", id="rights"),
        pytest.param({"blocking_issue_count": 1}, "COMPLETE", id="quality"),
        pytest.param({"market_state": "INCOMPLETE"}, "INCOMPLETE", id="state"),
    ],
)
def test_superseded_older_failures_do_not_degrade_a_newer_eligible_book(
    eligibility_updates: dict[str, object],
    older_state: str,
) -> None:
    newer_rows = _observation_rows(
        book_number=301,
        source_number=303,
        usable_at=AS_OF - timedelta(seconds=1),
        observed_at=AS_OF - timedelta(seconds=10),
    )
    older_rows = _observation_rows(
        book_number=201,
        source_number=203,
        usable_at=AS_OF - timedelta(seconds=2),
        observed_at=AS_OF - timedelta(seconds=20),
        market_state=older_state,
    )
    if older_state == "INCOMPLETE":
        older_rows = older_rows[:2]
    older_eligibility = _eligibility_row(
        book_observation_id=UUID(int=201),
        **eligibility_updates,
    )
    repository = MarketObservationRepository(
        _SequencedRowsSession(
            [
                [*newer_rows, *older_rows],
                [
                    _eligibility_row(book_observation_id=UUID(int=301)),
                    older_eligibility,
                ],
            ]
        )  # type: ignore[arg-type]
    )

    result = repository.normalisation_input(
        fixture_id=FIXTURE_ID,
        fixture_external_provider="synthetic_fpl",
        fixture_external_id="101",
        as_of=AS_OF,
        stale_after_seconds=1800,
    )

    assert {item.book_observation_id for item in result.eligible_observations} == {UUID(int=301)}
    assert len(result.source_observations) == 3 + len(older_rows)
    assert result.exclusions == ()
    assert result.warnings == ()


def test_nonblocking_duplicate_warning_is_retained_without_disqualifying_book() -> None:
    session = _SequencedRowsSession(
        [
            _observation_rows(),
            [_eligibility_row(warning_codes=["DUPLICATE_OUTCOME_SAME_PAYLOAD"])],
        ]
    )
    repository = MarketObservationRepository(
        session  # type: ignore[arg-type]
    )

    result = repository.normalisation_input(
        fixture_id=FIXTURE_ID,
        fixture_external_provider="synthetic_fpl",
        fixture_external_id="101",
        as_of=AS_OF,
        stale_after_seconds=1800,
    )

    assert len(result.eligible_observations) == 3
    assert result.exclusions == ()
    assert result.warnings == ("DUPLICATE_OUTCOME_SAME_PAYLOAD",)
    eligibility_sql = str(session.statements[-1])
    assert "profile.unresolved_rights = '[]'::jsonb" in eligibility_sql
    assert "batch.mapping_evidence_class = 'TEST_ONLY'" not in eligibility_sql
    assert "schedule.usable_at <= :cutoff" in eligibility_sql
    assert "blocker.decision_impact = 'BLOCKING'" not in eligibility_sql
    assert "blocker.detected_at <= :cutoff" in eligibility_sql
    assert "blocker.resolved_at > :cutoff" in eligibility_sql
    assert "blocker.source_snapshot_id = snapshot.source_snapshot_id" in eligibility_sql
    assert "blocker.ingestion_run_id = snapshot.ingestion_run_id" in eligibility_sql
    assert "blocker.canonical_entity_id = mapped_fixture.fixture_id" in eligibility_sql
    assert "warning.detected_at <= :cutoff" in eligibility_sql
    assert "warning.resolved_at > :cutoff" in eligibility_sql


def test_zero_quote_suspended_book_retains_typed_exclusion_and_book_lineage() -> None:
    observation = _observation_rows()[0]
    observation.update(
        {
            "market_state": "SUSPENDED",
            "selection_id": None,
            "odds_observation_id": None,
        }
    )
    repository = MarketObservationRepository(
        _SequencedRowsSession(
            [
                [observation],
                [_eligibility_row(market_state="SUSPENDED")],
            ]
        )  # type: ignore[arg-type]
    )

    result = repository.normalisation_input(
        fixture_id=FIXTURE_ID,
        fixture_external_provider="synthetic_fpl",
        fixture_external_id="101",
        as_of=AS_OF,
        stale_after_seconds=1800,
    )

    assert result.eligible_observations == ()
    assert result.source_observations == ()
    assert len(result.source_books) == 1
    assert result.source_books[0].book_observation_id == UUID(int=101)
    assert result.exclusions == (
        ExcludedBook(
            operator_key="book_alpha",
            reason=ExclusionReason.SUSPENDED,
        ),
    )
    assert result.warnings == ("BOOK_EXCLUDED_SUSPENDED",)


def test_unresolved_or_denied_rights_disqualify_the_whole_book() -> None:
    repository = MarketObservationRepository(
        _SequencedRowsSession(
            [
                _observation_rows(),
                [_eligibility_row(rights_valid=False)],
            ]
        )  # type: ignore[arg-type]
    )

    result = repository.normalisation_input(
        fixture_id=FIXTURE_ID,
        fixture_external_provider="synthetic_fpl",
        fixture_external_id="101",
        as_of=AS_OF,
        stale_after_seconds=1800,
    )

    assert result.eligible_observations == ()
    assert len(result.source_observations) == 3
    assert len(result.source_books) == 1
    assert result.exclusions == (
        ExcludedBook(
            operator_key="book_alpha",
            reason=ExclusionReason.RIGHTS_BLOCKED,
        ),
    )
    assert result.warnings == ("BOOK_EXCLUDED_RIGHTS_BLOCKED",)
