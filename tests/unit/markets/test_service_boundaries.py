"""Offline application-service boundaries for NRM-006 market normalisation."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

import dmf_pulse.markets.service as service_module
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.markets.models import (
    ExcludedBook,
    ExclusionReason,
    ExclusiveOutcomeQuote,
    MarketBook,
    MarketObservation,
    MarketOutcome,
    MarketQueryResult,
    MarketState,
    NormalisationStatus,
)
from dmf_pulse.markets.repository import (
    MarketObservationRepository,
    NormalisationInput,
    SourceBookLineage,
)
from dmf_pulse.markets.service import MarketService

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 8, 20, 12, 5, tzinfo=UTC)
FIXTURE_ID = UUID("00000000-0000-7000-8000-000000000101")


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _Factory:
    def begin(self) -> nullcontext[object]:
        return nullcontext(object())


class _Repository:
    def __init__(
        self,
        query: MarketQueryResult | None = None,
        error: IngestionError | None = None,
        prepared_input: NormalisationInput | None = None,
    ) -> None:
        self.query = query
        self.error = error
        self.input_error: IngestionError | None = None
        self.prepared_input = prepared_input
        self.persisted: list[dict[str, object]] = []

    def resolve_fixture(self, **_kwargs: object) -> UUID:
        if self.error is not None:
            raise self.error
        return FIXTURE_ID

    def observations(self, **_kwargs: object) -> MarketQueryResult:
        assert self.query is not None
        return self.query

    def normalisation_input(self, **_kwargs: object) -> NormalisationInput:
        if self.input_error is not None:
            raise self.input_error
        if self.prepared_input is not None:
            return self.prepared_input
        assert self.query is not None
        candidate_observations = tuple(
            observation for book in self.query.books for observation in book.observations
        )
        source_observations = tuple(
            observation
            for book in self.query.books
            for observation in book.observations
            if isinstance(observation, ExclusiveOutcomeQuote)
        )
        source_books = tuple(
            SourceBookLineage(
                book_observation_id=book.observations[0].book_observation_id,
                source_snapshot_id=book.observations[0].source_snapshot_id,
                fixture_id=FIXTURE_ID,
            )
            for book in self.query.books
            if book.observations and isinstance(book.observations[0], ExclusiveOutcomeQuote)
        )
        return NormalisationInput(
            eligible_observations=candidate_observations,  # type: ignore[arg-type]
            source_observations=source_observations,
            source_books=source_books,
            exclusions=(),
            warnings=(),
        )

    def persist_normalisation(self, **kwargs: object) -> UUID:
        self.persisted.append(kwargs)
        return UUID(int=999)


class _Rows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> _Rows:
        return self

    def __iter__(self):
        return iter(self.rows)


class _RowSession:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def execute(self, *_args: object, **_kwargs: object) -> _Rows:
        return _Rows(self.rows)


def _quote(
    *,
    operator: int,
    outcome: MarketOutcome,
    index: int,
    state: MarketState = MarketState.COMPLETE,
) -> ExclusiveOutcomeQuote:
    observed = AS_OF - timedelta(seconds=operator * 10)
    return ExclusiveOutcomeQuote(
        fixture_id=FIXTURE_ID,
        market_id=UUID(f"00000000-0000-7000-8100-{operator:012d}"),
        selection_id=UUID(f"00000000-0000-7000-8200-{operator * 10 + index:012d}"),
        operator_id=UUID(f"00000000-0000-7000-8300-{operator:012d}"),
        outcome=outcome,
        decimal_odds=(Decimal("1.80"), Decimal("3.60"), Decimal("4.20"))[index],
        observed_at=observed,
        received_at=observed,
        usable_at=observed,
        source_snapshot_id=UUID(f"00000000-0000-7000-8400-{operator:012d}"),
        market_state=state,
        contract_version="the-odds-api-v4-reference-v1",
        book_observation_id=UUID(f"00000000-0000-7000-8500-{operator:012d}"),
        odds_observation_id=UUID(f"00000000-0000-7000-8600-{operator * 10 + index:012d}"),
        provider_id=UUID(int=901),
        operator_key=f"book_{operator}",
    )


def _book(operator: int, *, state: MarketState = MarketState.COMPLETE) -> MarketBook:
    outcomes = tuple(MarketOutcome) if state is MarketState.COMPLETE else tuple(MarketOutcome)[:2]
    quotes = tuple(
        _quote(operator=operator, outcome=outcome, index=index, state=state)
        for index, outcome in enumerate(outcomes)
    )
    return MarketBook(
        operator_id=quotes[0].operator_id,
        operator_key=quotes[0].operator_key,
        market_state=state,
        observations=quotes,
    )


def _query(*books: MarketBook) -> MarketQueryResult:
    return MarketQueryResult(
        fixture_id=FIXTURE_ID,
        as_of=AS_OF,
        books=books,
        observation_count=sum(len(book.observations) for book in books),
    )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    repository: _Repository,
) -> _Engine:
    engine = _Engine()
    monkeypatch.setattr(service_module, "_validate_database_reference", lambda _value: None)
    monkeypatch.setattr(service_module, "_fpl_database_engine", lambda _value: engine)
    monkeypatch.setattr(service_module, "session_factory", lambda _engine: _Factory())
    monkeypatch.setattr(
        service_module,
        "MarketObservationRepository",
        lambda _session: repository,
    )
    return engine


def _normalise(as_of: datetime = AS_OF) -> object:
    return MarketService().normalise(
        fixture_external_provider="synthetic_fpl",
        fixture_external_id="101",
        season_code="2026/27",
        as_of=as_of,
    )


def test_mapping_conflict_becomes_blocked_and_other_errors_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _Repository(error=IngestionError("MAPPING_CONFLICT", "synthetic"))
    engine = _install(monkeypatch, repository)
    result = _normalise()
    assert result.status is NormalisationStatus.BLOCKED  # type: ignore[attr-defined]
    assert result.error_code == "MAPPING_UNAVAILABLE"  # type: ignore[attr-defined]
    assert engine.disposed is True

    repository.error = IngestionError("DATABASE_UNAVAILABLE", "synthetic")
    engine.disposed = False
    with pytest.raises(IngestionError) as caught:
        _normalise()
    assert caught.value.code == "DATABASE_UNAVAILABLE"
    assert engine.disposed is True


def test_unenriched_observation_fails_the_canonical_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quote = _quote(operator=1, outcome=MarketOutcome.HOME, index=0)
    plain = MarketObservation.model_validate(
        {name: getattr(quote, name) for name in MarketObservation.model_fields}
    ).model_copy(update={"market_state": MarketState.INCOMPLETE})
    repository = _Repository(
        _query(
            MarketBook(
                operator_id=plain.operator_id,
                operator_key="plain",
                market_state=MarketState.INCOMPLETE,
                observations=(plain,),
            )
        )
    )
    engine = _install(monkeypatch, repository)
    with pytest.raises(IngestionError) as caught:
        _normalise()
    assert caught.value.code == "CANONICAL_INVARIANT"
    assert engine.disposed is True


def test_quality_lock_retryable_error_propagates_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _Repository(_query())
    repository.input_error = IngestionError(
        "DATABASE_RETRYABLE",
        "synthetic quality lock timeout",
        retryable=True,
    )
    engine = _install(monkeypatch, repository)

    with pytest.raises(IngestionError) as caught:
        _normalise()

    assert caught.value.code == "DATABASE_RETRYABLE"
    assert caught.value.retryable is True
    assert repository.persisted == []
    assert engine.disposed is True


def test_equivalent_offset_instants_produce_identical_results_and_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _Repository(_query(_book(1), _book(2)))
    _install(monkeypatch, repository)
    equivalent_offset = datetime.fromisoformat("2026-08-20T13:05:00+01:00")

    utc_result = _normalise(AS_OF)
    offset_result = _normalise(equivalent_offset)

    assert utc_result.model_dump_json() == offset_result.model_dump_json()  # type: ignore[attr-defined]
    assert utc_result.as_of == AS_OF  # type: ignore[attr-defined]
    assert len(repository.persisted) == 2
    assert (
        repository.persisted[0]["input_signature_sha256"]
        == repository.persisted[1]["input_signature_sha256"]
    )


def test_empty_query_is_persisted_as_typed_insufficient_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _Repository(_query())
    engine = _install(monkeypatch, repository)
    result = _normalise()
    assert result.status is NormalisationStatus.INSUFFICIENT  # type: ignore[attr-defined]
    assert result.error_code == "NO_ELIGIBLE_COMPLETE_BOOK"  # type: ignore[attr-defined]
    assert len(repository.persisted) == 1
    assert repository.persisted[0]["observations"] == ()
    assert engine.disposed is True


@pytest.mark.parametrize(
    ("reason", "error_code"),
    (
        (ExclusionReason.RIGHTS_BLOCKED, "RIGHTS_BLOCKED"),
        (ExclusionReason.QUALITY_BLOCKED, "QUALITY_BLOCKED"),
    ),
)
def test_all_books_blocked_by_governance_returns_typed_blocked_status(
    monkeypatch: pytest.MonkeyPatch,
    reason: ExclusionReason,
    error_code: str,
) -> None:
    repository = _Repository(
        prepared_input=NormalisationInput(
            eligible_observations=(),
            source_observations=(),
            source_books=(
                SourceBookLineage(
                    book_observation_id=UUID(int=1),
                    source_snapshot_id=UUID(int=2),
                    fixture_id=FIXTURE_ID,
                ),
            ),
            exclusions=(ExcludedBook(operator_key="book_1", reason=reason),),
            warnings=(f"BOOK_EXCLUDED_{reason.value}",),
        )
    )
    engine = _install(monkeypatch, repository)

    result = _normalise()

    assert result.status is NormalisationStatus.BLOCKED  # type: ignore[attr-defined]
    assert result.error_code == error_code  # type: ignore[attr-defined]
    assert len(repository.persisted) == 1
    assert repository.persisted[0]["book_sources"] == repository.prepared_input.source_books
    assert engine.disposed is True


@pytest.mark.parametrize(
    ("books", "expected"),
    (
        ((_book(1),), NormalisationStatus.NORMALISED),
        (
            (_book(1), _book(2, state=MarketState.INCOMPLETE)),
            NormalisationStatus.DEGRADED,
        ),
    ),
)
def test_consensus_status_tracks_typed_degradation(
    monkeypatch: pytest.MonkeyPatch,
    books: tuple[MarketBook, ...],
    expected: NormalisationStatus,
) -> None:
    repository = _Repository(_query(*books))
    engine = _install(monkeypatch, repository)
    result = _normalise()
    assert result.status is expected  # type: ignore[attr-defined]
    assert result.consensus is not None  # type: ignore[attr-defined]
    assert len(repository.persisted) == 1
    assert len(repository.persisted[0]["book_sources"]) == len(books)  # type: ignore[arg-type]
    assert engine.disposed is True


def _stored_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "book_observation_id": UUID(int=1),
        "market_id": UUID(int=2),
        "source_snapshot_id": UUID(int=3),
        "market_state": "COMPLETE",
        "operator_id": UUID(int=4),
        "operator_key": "book",
        "provider_id": UUID(int=5),
        "attested_usable_at": AS_OF,
        "selection_id": UUID(int=6),
        "outcome": "HOME",
        "decimal_odds": Decimal("1.80"),
        "observed_at": AS_OF,
        "received_at": AS_OF,
        "contract_version": "the-odds-api-v4-reference-v1",
        "odds_observation_id": UUID(int=7),
    }
    row.update(updates)
    return row


def test_observation_query_handles_empty_nonoffered_book() -> None:
    repository = MarketObservationRepository(
        _RowSession(
            [
                _stored_row(
                    market_state="SUSPENDED",
                    selection_id=None,
                )
            ]
        )  # type: ignore[arg-type]
    )
    result = repository.observations(fixture_id=FIXTURE_ID, as_of=AS_OF)
    assert result.observation_count == 0
    assert result.books[0].market_state is MarketState.SUSPENDED


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"decimal_odds": "1.80"}, "exact Decimal"),
        ({"contract_version": "wrong"}, "contract is unsupported"),
    ),
)
def test_observation_query_rejects_storage_type_or_contract_drift(
    updates: dict[str, object],
    message: str,
) -> None:
    repository = MarketObservationRepository(
        _RowSession([_stored_row(**updates)])  # type: ignore[arg-type]
    )
    with pytest.raises(IngestionError, match=message):
        repository.observations(fixture_id=FIXTURE_ID, as_of=AS_OF)
