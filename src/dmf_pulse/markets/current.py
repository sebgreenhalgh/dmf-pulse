"""Transient current-market bridge from the reviewed Session-1 input to Stage 6."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.current import (
    CurrentOddsBookmaker,
    CurrentOddsEvent,
    current_odds_market_semantic_sha256,
)
from dmf_pulse.ingestion.odds.identity import (
    ResolvedCurrentFixture,
    current_odds_identity_semantic_sha256,
    current_odds_provider_provenance_sha256,
)
from dmf_pulse.ingestion.session1 import Session1DownstreamInput
from dmf_pulse.markets.consensus import evaluate_market_consensus
from dmf_pulse.markets.models import (
    ExcludedBook,
    ExclusiveOutcomeQuote,
    MarketConsensus,
    MarketOutcome,
    MarketState,
)
from dmf_pulse.markets.policy import POLICY_ID, POLICY_SHA256, load_market_normalisation_policy

CURRENT_MARKET_ADAPTER_VERSION = "gw1-current-market-stage6-v1"
_IDENTITY_NAMESPACE = UUID("5b2469af-1f0f-5ba2-9d2c-1c60683c04e6")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


def _uuid(kind: str, *parts: object) -> UUID:
    material = "\x1f".join((CURRENT_MARKET_ADAPTER_VERSION, kind, *(str(part) for part in parts)))
    return uuid5(_IDENTITY_NAMESPACE, material)


class CurrentFixtureMarketConsensus(_FrozenModel):
    """One exact reviewed target fixture normalised by the accepted Stage-6 policy."""

    official_fpl_fixture_id: int = Field(gt=0)
    transient_fixture_id: UUID
    provider_event_id: str = Field(min_length=1, max_length=500)
    source_book_count: int = Field(gt=0)
    source_quote_count: int = Field(gt=0)
    excluded_books: tuple[ExcludedBook, ...]
    warnings: tuple[str, ...]
    consensus: MarketConsensus
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_fixture_result(self) -> CurrentFixtureMarketConsensus:
        if (
            self.consensus.fixture_id != self.transient_fixture_id
            or self.source_quote_count != self.source_book_count * 3
            or self.consensus.eligible_operator_count + len(self.excluded_books)
            != self.source_book_count
            or self.result_sha256 != _fixture_result_sha256(self)
        ):
            raise ValueError("current fixture market-consensus lineage is inconsistent")
        return self


def _fixture_result_sha256(value: CurrentFixtureMarketConsensus) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"result_sha256"}))


class CurrentMarketConsensusSummary(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["COMPLETE"] = "COMPLETE"
    contract: Literal["GW1_CURRENT_MARKET_CONSENSUS"] = "GW1_CURRENT_MARKET_CONSENSUS"
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    fixture_identity_mode: Literal["DETERMINISTIC_TRANSIENT_SURROGATE_NO_DATABASE_RESOLUTION"] = (
        "DETERMINISTIC_TRANSIENT_SURROGATE_NO_DATABASE_RESOLUTION"
    )
    as_of: datetime
    fixture_count: int = Field(gt=0)
    source_book_count: int = Field(gt=0)
    eligible_operator_count: int = Field(gt=0)
    excluded_book_count: int = Field(ge=0)
    confidence_grades: dict[str, int]
    policy_id: Literal["market-normalisation-v1"] = "market-normalisation-v1"
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_session1_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_odds_market_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_coverage: Literal["COMPLETE"] = "COMPLETE"
    next_checkpoint: Literal["2.2_AVAILABILITY_START_MINUTES"] = "2.2_AVAILABILITY_START_MINUTES"


class CurrentMarketConsensusBundle(_FrozenModel):
    """Hash-bound in-memory Stage-6 result plus its complete Session-1 lineage."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_MARKET_CONSENSUS"] = "GW1_CURRENT_MARKET_CONSENSUS"
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    fixture_identity_mode: Literal["DETERMINISTIC_TRANSIENT_SURROGATE_NO_DATABASE_RESOLUTION"] = (
        "DETERMINISTIC_TRANSIENT_SURROGATE_NO_DATABASE_RESOLUTION"
    )
    as_of: datetime
    mapping_cutoff: datetime
    adapter_version: Literal["gw1-current-market-stage6-v1"] = "gw1-current-market-stage6-v1"
    policy_id: Literal["market-normalisation-v1"] = "market-normalisation-v1"
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_session1_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_identity_map_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_odds_provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_odds_market_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_input: Session1DownstreamInput
    fixture_markets: tuple[CurrentFixtureMarketConsensus, ...] = Field(min_length=1)
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_current_consensus(self) -> CurrentMarketConsensusBundle:
        source = _revalidate_session1(self.source_input)
        expected = _build_fixture_markets(source)
        fixture_ids = [row.official_fpl_fixture_id for row in self.fixture_markets]
        if (
            source != self.source_input
            or self.as_of != source.decision_information_at
            or self.mapping_cutoff != source.identity_map.mapping_decided_at
            or self.policy_sha256 != POLICY_SHA256
            or self.source_session1_semantic_sha256 != source.semantic_sha256
            or self.source_identity_map_semantic_sha256 != source.identity_map.semantic_sha256
            or self.source_odds_provenance_sha256
            != current_odds_provider_provenance_sha256(source.odds_input)
            or self.source_odds_identity_semantic_sha256
            != current_odds_identity_semantic_sha256(source.odds_input)
            or self.source_odds_market_semantic_sha256
            != current_odds_market_semantic_sha256(source.odds_input)
            or tuple(self.fixture_markets) != expected
            or len(fixture_ids) != len(set(fixture_ids))
            or len(self.fixture_markets) != source.identity_map.coverage.target_fpl_fixture_count
            or self.semantic_sha256 != _bundle_sha256(self)
        ):
            raise ValueError("current market-consensus bundle lineage is inconsistent")
        return self

    def safe_summary(self) -> CurrentMarketConsensusSummary:
        grades: dict[str, int] = {}
        for row in self.fixture_markets:
            grade = row.consensus.confidence_grade
            grades[grade] = grades.get(grade, 0) + 1
        return CurrentMarketConsensusSummary(
            as_of=self.as_of,
            fixture_count=len(self.fixture_markets),
            source_book_count=sum(row.source_book_count for row in self.fixture_markets),
            eligible_operator_count=sum(
                row.consensus.eligible_operator_count for row in self.fixture_markets
            ),
            excluded_book_count=sum(len(row.excluded_books) for row in self.fixture_markets),
            confidence_grades=dict(sorted(grades.items())),
            policy_sha256=self.policy_sha256,
            source_session1_semantic_sha256=self.source_session1_semantic_sha256,
            source_odds_market_semantic_sha256=self.source_odds_market_semantic_sha256,
            semantic_sha256=self.semantic_sha256,
        )


def _revalidate_session1(value: Session1DownstreamInput) -> Session1DownstreamInput:
    try:
        return Session1DownstreamInput.model_validate(value.model_dump(mode="python"))
    except ValueError as exc:
        raise IngestionError(
            "SOURCE_LINEAGE_INVALID", "Session-1 downstream input failed independent revalidation"
        ) from exc


def _event_and_mapping(
    source: Session1DownstreamInput,
) -> tuple[tuple[CurrentOddsEvent, ResolvedCurrentFixture], ...]:
    events = {event.provider_event_id: event for event in source.odds_input.events}
    mappings = {row.provider_event_id: row for row in source.identity_map.fixture_mappings}
    if set(events) != set(mappings):
        raise IngestionError(
            "MAPPING_CONFLICT", "current market events do not have complete reviewed coverage"
        )
    pairs = tuple((events[event_id], mappings[event_id]) for event_id in sorted(events))
    for event, mapping in pairs:
        if (
            event.provider_home_team != mapping.provider_home_team
            or event.provider_away_team != mapping.provider_away_team
            or event.commence_time != mapping.provider_commence_time
        ):
            raise IngestionError(
                "MAPPING_CONFLICT", "current market event contradicts its reviewed fixture binding"
            )
    return pairs


def _book_quotes(
    source: Session1DownstreamInput,
    event: CurrentOddsEvent,
    mapping: ResolvedCurrentFixture,
    bookmaker: CurrentOddsBookmaker,
) -> tuple[ExclusiveOutcomeQuote, ExclusiveOutcomeQuote, ExclusiveOutcomeQuote]:
    fixture_id = _uuid("fixture", mapping.official_fpl_fixture_identity.canonical_lookup_sha256)
    provider_id = _uuid("provider", source.odds_input.provider)
    operator_id = _uuid("operator", source.odds_input.provider, bookmaker.bookmaker_key)
    market_id = _uuid("market", fixture_id, "FULL_TIME_1X2")
    market = bookmaker.markets[0]
    observed_at = market.provider_last_update or bookmaker.provider_last_update
    book_observation_id = _uuid(
        "book-observation",
        source.odds_input.provenance.source_snapshot_id,
        event.provider_event_id,
        bookmaker.bookmaker_key,
        observed_at.isoformat(),
    )
    by_outcome = {MarketOutcome(row.outcome): row for row in market.outcomes}
    return tuple(
        ExclusiveOutcomeQuote(
            fixture_id=fixture_id,
            market_id=market_id,
            selection_id=_uuid("selection", market_id, outcome.value),
            operator_id=operator_id,
            outcome=outcome,
            decimal_odds=by_outcome[outcome].decimal_price,
            observed_at=observed_at,
            received_at=source.odds_input.temporal.received_at,
            usable_at=source.odds_input.temporal.usable_at,
            source_snapshot_id=source.odds_input.provenance.source_snapshot_id,
            market_state=MarketState.COMPLETE,
            contract_version=source.odds_input.provenance.contract_version,
            book_observation_id=book_observation_id,
            odds_observation_id=_uuid(
                "odds-observation",
                book_observation_id,
                outcome.value,
                by_outcome[outcome].decimal_price,
            ),
            provider_id=provider_id,
            operator_key=bookmaker.bookmaker_key,
        )
        for outcome in MarketOutcome
    )  # type: ignore[return-value]


def _build_fixture_markets(
    source: Session1DownstreamInput,
) -> tuple[CurrentFixtureMarketConsensus, ...]:
    if (
        source.odds_input.rights.transient_processing != "ALLOW"
        or source.odds_input.rights.derived_storage != "ALLOW"
        or source.odds_input.rights.private_internal_use != "ALLOW"
        or source.fpl_input.rights.derived_storage != "DENY"
        or source.fpl_input.rights.database_accessed
    ):
        raise IngestionError("RIGHTS_BLOCKED", "current market transformation rights are invalid")
    policy = load_market_normalisation_policy()
    results: list[CurrentFixtureMarketConsensus] = []
    for event, mapping in _event_and_mapping(source):
        books = tuple(sorted(event.bookmakers, key=lambda item: item.bookmaker_key))
        quotes = tuple(
            quote
            for bookmaker in books
            for quote in _book_quotes(source, event, mapping, bookmaker)
        )
        warnings = tuple(
            sorted(
                {
                    "PROVIDER_MARKET_TIMESTAMP_NOT_PUBLISHED_USED_BOOKMAKER_TIMESTAMP"
                    for bookmaker in books
                    if bookmaker.markets[0].provider_last_update is None
                }
            )
        )
        evaluation = evaluate_market_consensus(
            quotes,
            as_of=source.decision_information_at,
            mapping_cutoff=source.identity_map.mapping_decided_at,
            policy=policy,
            initial_warnings=warnings,
        )
        if evaluation.consensus is None:
            raise IngestionError(
                "NO_ELIGIBLE_MARKET",
                "no fresh complete Stage-6 market remains for a reviewed target fixture",
                details={
                    "official_fpl_fixture_id": mapping.official_fpl_fixture_id,
                    "excluded_books": [
                        row.model_dump(mode="json") for row in evaluation.exclusions
                    ],
                    "warnings": list(evaluation.warnings),
                },
            )
        provisional = CurrentFixtureMarketConsensus.model_construct(
            official_fpl_fixture_id=mapping.official_fpl_fixture_id,
            transient_fixture_id=evaluation.consensus.fixture_id,
            provider_event_id=event.provider_event_id,
            source_book_count=len(books),
            source_quote_count=len(quotes),
            excluded_books=evaluation.exclusions,
            warnings=evaluation.warnings,
            consensus=evaluation.consensus,
            result_sha256="0" * 64,
        )
        results.append(
            CurrentFixtureMarketConsensus(
                official_fpl_fixture_id=mapping.official_fpl_fixture_id,
                transient_fixture_id=evaluation.consensus.fixture_id,
                provider_event_id=event.provider_event_id,
                source_book_count=len(books),
                source_quote_count=len(quotes),
                excluded_books=evaluation.exclusions,
                warnings=evaluation.warnings,
                consensus=evaluation.consensus,
                result_sha256=_fixture_result_sha256(provisional),
            )
        )
    return tuple(sorted(results, key=lambda row: row.official_fpl_fixture_id))


def _bundle_sha256(value: CurrentMarketConsensusBundle) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


def build_current_market_consensus(
    source: Session1DownstreamInput,
) -> CurrentMarketConsensusBundle:
    """Produce complete transient Stage-6 consensus for reviewed target fixtures."""

    validated = _revalidate_session1(source)
    fixture_markets = _build_fixture_markets(validated)
    provisional = CurrentMarketConsensusBundle.model_construct(
        schema_version="1.0.0",
        contract="GW1_CURRENT_MARKET_CONSENSUS",
        run_classification="PRESEASON_DECISION_SUPPORT",
        production_status="NON_PRODUCTION",
        storage_mode="TRANSIENT_IN_MEMORY",
        persistence_performed=False,
        database_accessed=False,
        fixture_identity_mode="DETERMINISTIC_TRANSIENT_SURROGATE_NO_DATABASE_RESOLUTION",
        as_of=validated.decision_information_at,
        mapping_cutoff=validated.identity_map.mapping_decided_at,
        adapter_version=CURRENT_MARKET_ADAPTER_VERSION,
        policy_id=POLICY_ID,
        policy_sha256=POLICY_SHA256,
        source_session1_semantic_sha256=validated.semantic_sha256,
        source_identity_map_semantic_sha256=validated.identity_map.semantic_sha256,
        source_odds_provenance_sha256=current_odds_provider_provenance_sha256(validated.odds_input),
        source_odds_identity_semantic_sha256=current_odds_identity_semantic_sha256(
            validated.odds_input
        ),
        source_odds_market_semantic_sha256=current_odds_market_semantic_sha256(
            validated.odds_input
        ),
        source_input=validated,
        fixture_markets=fixture_markets,
        semantic_sha256="0" * 64,
    )
    return CurrentMarketConsensusBundle(
        as_of=validated.decision_information_at,
        mapping_cutoff=validated.identity_map.mapping_decided_at,
        policy_sha256=POLICY_SHA256,
        source_session1_semantic_sha256=validated.semantic_sha256,
        source_identity_map_semantic_sha256=validated.identity_map.semantic_sha256,
        source_odds_provenance_sha256=current_odds_provider_provenance_sha256(validated.odds_input),
        source_odds_identity_semantic_sha256=current_odds_identity_semantic_sha256(
            validated.odds_input
        ),
        source_odds_market_semantic_sha256=current_odds_market_semantic_sha256(
            validated.odds_input
        ),
        source_input=validated,
        fixture_markets=fixture_markets,
        semantic_sha256=_bundle_sha256(provisional),
    )


__all__ = [
    "CURRENT_MARKET_ADAPTER_VERSION",
    "CurrentFixtureMarketConsensus",
    "CurrentMarketConsensusBundle",
    "CurrentMarketConsensusSummary",
    "build_current_market_consensus",
]
