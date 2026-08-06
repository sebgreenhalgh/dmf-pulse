"""Cutoff-safe PostgreSQL retrieval of latest eligible operator books."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import bindparam, insert, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.models import require_utc
from dmf_pulse.data_model.tables import (
    data_provider,
    external_identifier,
    market_consensus_outcome,
    market_consensus_result,
    market_normalisation_book_source,
    market_normalisation_exclusion,
    market_normalisation_policy,
    market_normalisation_run,
    market_normalisation_source,
    market_normalisation_warning,
    normalised_operator_market,
    normalised_operator_market_source,
    normalised_operator_outcome,
    season,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.markets.models import (
    ExcludedBook,
    ExclusionReason,
    ExclusiveOutcomeQuote,
    MarketBook,
    MarketNormalisationResult,
    MarketObservation,
    MarketOutcome,
    MarketQueryResult,
    MarketState,
)
from dmf_pulse.markets.normalisation import code_identity
from dmf_pulse.markets.policy import (
    MarketNormalisationPolicy,
    canonical_json_sha256,
)


@dataclass(frozen=True, slots=True)
class SourceBookLineage:
    """Exact immutable stored-book lineage, including books with no offered quotes."""

    book_observation_id: UUID
    source_snapshot_id: UUID
    fixture_id: UUID


@dataclass(frozen=True, slots=True)
class NormalisationInput:
    """Whole eligible candidates plus immutable reasons that disqualified stored books."""

    eligible_observations: tuple[ExclusiveOutcomeQuote, ...]
    source_observations: tuple[ExclusiveOutcomeQuote, ...]
    source_books: tuple[SourceBookLineage, ...]
    exclusions: tuple[ExcludedBook, ...]
    warnings: tuple[str, ...]


def _uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise IngestionError("CANONICAL_INVARIANT", "database returned an invalid identifier")
    return value


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise IngestionError("CANONICAL_INVARIANT", "database returned an invalid timestamp")
    return require_utc(value)


def _integer(value: object) -> int:
    if not isinstance(value, int):
        raise IngestionError("CANONICAL_INVARIANT", "database returned an invalid count")
    return value


def _mapping_dependency_hash_matches(row: dict[str, object]) -> bool:
    uuid_fields = (
        "provider_market_representation_id",
        "fixture_lookup_mapping_id",
        "home_team_mapping_id",
        "away_team_mapping_id",
        "fixture_observation_id",
    )
    if any(not isinstance(row.get(name), UUID) for name in uuid_fields):
        return False
    expected_commence_time = row.get("expected_commence_time")
    mapping_plan_sha256 = row.get("mapping_plan_sha256")
    dependency_sha256 = row.get("dependency_sha256")
    if (
        not isinstance(expected_commence_time, datetime)
        or not isinstance(mapping_plan_sha256, str)
        or not isinstance(dependency_sha256, str)
    ):
        return False
    material = {name: str(row[name]) for name in uuid_fields}
    material["mapping_plan_sha256"] = mapping_plan_sha256
    material["expected_commence_time"] = require_utc(expected_commence_time).isoformat()
    return canonical_sha256(material) == dependency_sha256


class MarketObservationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve_fixture(
        self,
        *,
        external_provider: str,
        external_id: str,
        season_code: str,
        as_of: datetime,
    ) -> UUID:
        cutoff = require_utc(as_of)
        rows = list(
            self.session.execute(
                select(external_identifier.c.canonical_entity_id)
                .join(
                    data_provider,
                    data_provider.c.provider_id == external_identifier.c.provider_id,
                )
                .join(season, season.c.season_id == external_identifier.c.season_id)
                .where(
                    data_provider.c.provider_key == external_provider,
                    season.c.season_code == season_code,
                    external_identifier.c.identifier_namespace == "fpl.fixture.id",
                    external_identifier.c.entity_type == "FIXTURE",
                    external_identifier.c.external_id_text == external_id,
                    external_identifier.c.mapping_status.in_(("AUTO_MATCHED", "HUMAN_VERIFIED")),
                    external_identifier.c.valid_during.op("@>")(cutoff),
                    external_identifier.c.system_during.op("@>")(cutoff),
                )
            ).scalars()
        )
        fixture_ids = {_uuid(value) for value in rows}
        if len(fixture_ids) != 1:
            raise IngestionError("MAPPING_CONFLICT", "fixture external mapping is unresolved")
        return fixture_ids.pop()

    def _observation_rows(
        self,
        *,
        fixture_id: UUID,
        cutoff: datetime,
        latest_only: bool = True,
    ) -> list[dict[str, object]]:
        return [
            dict(row)
            for row in self.session.execute(
                text(
                    """
                    WITH ranked_book AS (
                      SELECT book.book_observation_id, book.market_id,
                             book.source_snapshot_id, book.market_state,
                             book.provider_observed_at, book.received_at,
                             attestation.usable_at,
                             market.operator_id,
                             operator_mapping.external_id_text AS operator_key,
                             representation.provider_id,
                             row_number() OVER (
                               PARTITION BY book.market_id
                               ORDER BY attestation.usable_at DESC,
                                        book.provider_observed_at DESC,
                                        book.source_snapshot_id DESC,
                                        book.book_observation_id DESC
                             ) AS recency_rank
                      FROM betting.operator_market_observation AS book
                      JOIN betting.odds_publication_batch AS batch
                        ON batch.publication_batch_id = book.publication_batch_id
                       AND batch.source_snapshot_id = book.source_snapshot_id
                      JOIN betting.odds_publication_attestation AS attestation
                        ON attestation.publication_batch_id = batch.publication_batch_id
                      JOIN betting.operator_fixture_market AS market
                        ON market.market_id = book.market_id
                      JOIN betting.provider_market_representation AS representation
                        ON representation.provider_market_representation_id =
                           book.provider_market_representation_id
                      JOIN core.external_identifier AS operator_mapping
                        ON operator_mapping.external_identifier_id =
                           representation.operator_mapping_id
                      JOIN betting.market_definition AS definition
                        ON definition.market_definition_id = market.market_definition_id
                      JOIN betting.settlement_profile AS settlement
                        ON settlement.settlement_profile_id = market.settlement_profile_id
                      WHERE market.fixture_id = :fixture_id
                        AND definition.definition_key = 'MATCH_RESULT_1X2'
                        AND definition.definition_version = '1.0.0'
                        AND market.period = 'FULL_TIME'
                        AND market.line IS NULL
                        AND settlement.profile_key = 'SOCCER_FULL_TIME_90_MINUTES_REFERENCE_V1'
                        AND settlement.includes_extra_time = false
                        AND attestation.usable_at <= :cutoff
                        AND book.market_state IN
                          ('COMPLETE','INCOMPLETE','SUSPENDED','UNSUPPORTED','UNAVAILABLE')
                    )
                    SELECT candidate.book_observation_id, candidate.market_id,
                           candidate.source_snapshot_id, candidate.market_state,
                           candidate.operator_id, candidate.operator_key,
                           candidate.provider_id, candidate.provider_observed_at,
                           candidate.usable_at AS attested_usable_at,
                           quote.selection_id, quote.outcome, quote.decimal_odds,
                           quote.observed_at, quote.received_at,
                           quote.contract_version, quote.odds_observation_id
                    FROM ranked_book AS candidate
                    LEFT JOIN betting.odds_observation AS quote
                      ON quote.book_observation_id = candidate.book_observation_id
                    WHERE (:latest_only = false OR candidate.recency_rank = 1)
                    ORDER BY candidate.operator_id,
                             candidate.usable_at DESC,
                             candidate.provider_observed_at DESC,
                             candidate.source_snapshot_id DESC,
                             candidate.book_observation_id DESC,
                             CASE quote.outcome
                               WHEN 'HOME' THEN 1 WHEN 'DRAW' THEN 2 WHEN 'AWAY' THEN 3 ELSE 4
                             END,
                             quote.odds_observation_id
                    """
                ),
                {
                    "fixture_id": fixture_id,
                    "cutoff": cutoff,
                    "latest_only": latest_only,
                },
            ).mappings()
        ]

    @staticmethod
    def _books_from_rows(
        *, fixture_id: UUID, rows: list[dict[str, object]]
    ) -> tuple[MarketBook, ...]:
        grouped: dict[UUID, tuple[UUID, str, MarketState, list[MarketObservation]]] = {}
        for row in rows:
            book_id = _uuid(row["book_observation_id"])
            group = grouped.setdefault(
                book_id,
                (
                    _uuid(row["operator_id"]),
                    str(row["operator_key"]),
                    MarketState(str(row["market_state"])),
                    [],
                ),
            )
            if row["selection_id"] is None:
                continue
            price = row["decimal_odds"]
            if not isinstance(price, Decimal):
                raise IngestionError("CANONICAL_INVARIANT", "stored odds are not exact Decimal")
            if row["contract_version"] != "the-odds-api-v4-reference-v1":
                raise IngestionError("CANONICAL_INVARIANT", "stored odds contract is unsupported")
            group[3].append(
                ExclusiveOutcomeQuote(
                    fixture_id=fixture_id,
                    market_id=_uuid(row["market_id"]),
                    selection_id=_uuid(row["selection_id"]),
                    operator_id=_uuid(row["operator_id"]),
                    outcome=MarketOutcome(str(row["outcome"])),
                    decimal_odds=price,
                    observed_at=_datetime(row["observed_at"]),
                    received_at=_datetime(row["received_at"]),
                    usable_at=_datetime(row["attested_usable_at"]),
                    source_snapshot_id=_uuid(row["source_snapshot_id"]),
                    market_state=MarketState(str(row["market_state"])),
                    contract_version="the-odds-api-v4-reference-v1",
                    book_observation_id=book_id,
                    odds_observation_id=_uuid(row["odds_observation_id"]),
                    provider_id=_uuid(row["provider_id"]),
                    operator_key=str(row["operator_key"]),
                )
            )
        return tuple(
            MarketBook(
                operator_id=group[0],
                operator_key=group[1],
                market_state=group[2],
                observations=tuple(group[3]),
            )
            for group in grouped.values()
        )

    @classmethod
    def _query_from_rows(
        cls, *, fixture_id: UUID, cutoff: datetime, rows: list[dict[str, object]]
    ) -> MarketQueryResult:
        books = cls._books_from_rows(fixture_id=fixture_id, rows=rows)
        return MarketQueryResult(
            fixture_id=fixture_id,
            as_of=cutoff,
            books=books,
            observation_count=sum(len(book.observations) for book in books),
        )

    def observations(self, *, fixture_id: UUID, as_of: datetime) -> MarketQueryResult:
        cutoff = require_utc(as_of)
        return self._query_from_rows(
            fixture_id=fixture_id,
            cutoff=cutoff,
            rows=self._observation_rows(fixture_id=fixture_id, cutoff=cutoff),
        )

    def _lock_quality_subjects(self, source_snapshot_ids: set[UUID]) -> None:
        """Serialize eligibility and run publication against blocking quality writes."""

        try:
            self.session.execute(text("SET LOCAL lock_timeout = '5s'"))
            for snapshot_id in sorted(source_snapshot_ids, key=str):
                self.session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": f"bundle-quality:{snapshot_id}"},
                )
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if sqlstate in {"40001", "40P01", "55P03"}:
                raise IngestionError(
                    "DATABASE_RETRYABLE",
                    "market quality lock was not acquired in time",
                    retryable=True,
                ) from None
            raise IngestionError("DATABASE_UNAVAILABLE", "market quality lock failed") from None

    def normalisation_input(
        self,
        *,
        fixture_id: UUID,
        fixture_external_provider: str,
        fixture_external_id: str,
        as_of: datetime,
        stale_after_seconds: int,
    ) -> NormalisationInput:
        """Revalidate the exact persisted publication dependencies at ``as_of``."""

        cutoff = require_utc(as_of)
        rows = self._observation_rows(
            fixture_id=fixture_id,
            cutoff=cutoff,
            latest_only=False,
        )
        if not rows:
            return NormalisationInput(
                eligible_observations=(),
                source_observations=(),
                source_books=(),
                exclusions=(),
                warnings=(),
            )
        self._lock_quality_subjects({_uuid(row["source_snapshot_id"]) for row in rows})
        book_ids = tuple(sorted({_uuid(row["book_observation_id"]) for row in rows}, key=str))
        eligibility_statement = text(
            """
            SELECT book.book_observation_id,
                   book.market_state,
                   market.operator_id,
                   operator_mapping.external_id_text AS operator_key,
                   batch.mapping_plan_approved_at,
                   dependency.provider_market_representation_id,
                   dependency.mapping_plan_sha256,
                   dependency.fixture_lookup_mapping_id,
                   dependency.home_team_mapping_id,
                   dependency.away_team_mapping_id,
                   dependency.fixture_observation_id,
                   dependency.expected_commence_time,
                   dependency.dependency_sha256,
                   (batch.mapping_status IN ('APPROVED_FOR_TEST','APPROVED')
                    AND representation.mapping_plan_sha256 = batch.mapping_plan_sha256
                    AND dependency.mapping_plan_sha256 = batch.mapping_plan_sha256
                   ) AS representation_matches_plan,
                   (event_mapping.canonical_entity_id = market.fixture_id
                    AND event_mapping.provider_id = representation.provider_id
                    AND event_mapping.entity_type = 'FIXTURE'
                    AND event_mapping.identifier_namespace = 'the_odds_api.event.id'
                    AND event_mapping.mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED')
                    AND event_mapping.valid_during @> dependency.expected_commence_time
                    AND event_mapping.system_during @> :cutoff
                   ) AS event_mapping_valid,
                   (operator_mapping.canonical_entity_id = market.operator_id
                    AND operator_mapping.provider_id = representation.provider_id
                    AND operator_mapping.entity_type = 'BETTING_OPERATOR'
                    AND operator_mapping.identifier_namespace = 'the_odds_api.bookmaker.key'
                    AND operator_mapping.mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED')
                    AND operator_mapping.valid_during @> dependency.expected_commence_time
                    AND operator_mapping.system_during @> :cutoff
                   ) AS operator_mapping_valid,
                   (schedule.fixture_id = mapped_fixture.fixture_id
                    AND schedule.kickoff_at = dependency.expected_commence_time
                    AND schedule.usable_at <= :cutoff
                   ) AS schedule_matches,
                   (fixture_provider.provider_key = :fixture_external_provider
                    AND fixture_mapping.season_id = mapped_fixture.season_id
                    AND fixture_mapping.canonical_entity_id = mapped_fixture.fixture_id
                    AND fixture_mapping.entity_type = 'FIXTURE'
                    AND fixture_mapping.identifier_namespace = 'fpl.fixture.id'
                    AND fixture_mapping.external_id_text = :fixture_external_id
                    AND fixture_mapping.mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED')
                    AND fixture_mapping.valid_during @> dependency.expected_commence_time
                    AND fixture_mapping.system_during @> :cutoff
                   ) AS fixture_mapping_valid,
                   (home_mapping.provider_id = fixture_mapping.provider_id
                    AND home_mapping.season_id = mapped_fixture.season_id
                    AND home_mapping.canonical_entity_id = mapped_fixture.home_team_id
                    AND home_mapping.entity_type = 'TEAM'
                    AND home_mapping.identifier_namespace = 'fpl.team.id'
                    AND home_mapping.mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED')
                    AND home_mapping.valid_during @> dependency.expected_commence_time
                    AND home_mapping.system_during @> :cutoff
                   ) AS home_team_mapping_valid,
                   (away_mapping.provider_id = fixture_mapping.provider_id
                    AND away_mapping.season_id = mapped_fixture.season_id
                    AND away_mapping.canonical_entity_id = mapped_fixture.away_team_id
                    AND away_mapping.entity_type = 'TEAM'
                    AND away_mapping.identifier_namespace = 'fpl.team.id'
                    AND away_mapping.mapping_status IN ('AUTO_MATCHED','HUMAN_VERIFIED')
                    AND away_mapping.valid_during @> dependency.expected_commence_time
                    AND away_mapping.system_during @> :cutoff
                   ) AS away_team_mapping_valid,
                   (profile.status = 'HUMAN_APPROVED'
                    AND profile.approved_at <= :cutoff
                    AND profile.unresolved_rights = '[]'::jsonb
                    AND profile.capabilities ->> 'derived_storage' = 'ALLOW'
                    AND profile.capabilities ->> 'private_internal_use' = 'ALLOW'
                    AND EXISTS (
                      SELECT 1 FROM provenance.rights_decision AS derived_decision
                      WHERE derived_decision.source_snapshot_id = snapshot.source_snapshot_id
                        AND derived_decision.rights_profile_record_id =
                            snapshot.rights_profile_record_id
                        AND derived_decision.capability = 'derived_storage'
                        AND derived_decision.decision = 'ALLOW'
                        AND derived_decision.checked_at <= :cutoff
                    )
                    AND EXISTS (
                      SELECT 1 FROM provenance.rights_decision AS private_decision
                      WHERE private_decision.source_snapshot_id = snapshot.source_snapshot_id
                        AND private_decision.rights_profile_record_id =
                            snapshot.rights_profile_record_id
                        AND private_decision.capability = 'private_internal_use'
                        AND private_decision.decision = 'ALLOW'
                        AND private_decision.checked_at <= :cutoff
                    )
                   ) AS rights_valid,
                   (
                     SELECT count(*)
                     FROM core.data_quality_issue AS blocker
                     WHERE blocker.severity IN ('P0','P1')
                       AND blocker.detected_at <= :cutoff
                       AND (blocker.status IN ('OPEN','ACKNOWLEDGED')
                            OR blocker.resolved_at IS NULL
                            OR blocker.resolved_at > :cutoff)
                       AND (blocker.source_snapshot_id = snapshot.source_snapshot_id
                            OR blocker.ingestion_run_id = snapshot.ingestion_run_id
                            OR blocker.canonical_entity_id = mapped_fixture.fixture_id)
                   ) AS blocking_issue_count,
                   ARRAY(
                     SELECT warning.issue_type
                     FROM core.data_quality_issue AS warning
                     WHERE warning.decision_impact = 'NONBLOCKING'
                       AND warning.detected_at <= :cutoff
                       AND (warning.status IN ('OPEN','ACKNOWLEDGED')
                            OR warning.resolved_at IS NULL
                            OR warning.resolved_at > :cutoff)
                       AND (warning.source_snapshot_id = snapshot.source_snapshot_id
                            OR warning.ingestion_run_id = snapshot.ingestion_run_id
                            OR warning.canonical_entity_id = mapped_fixture.fixture_id)
                     ORDER BY warning.detected_at, warning.data_quality_issue_id
                   ) AS warning_codes
            FROM betting.operator_market_observation AS book
            JOIN betting.odds_publication_batch AS batch
              ON batch.publication_batch_id = book.publication_batch_id
             AND batch.source_snapshot_id = book.source_snapshot_id
            JOIN betting.provider_market_representation AS representation
              ON representation.provider_market_representation_id =
                 book.provider_market_representation_id
            LEFT JOIN betting.odds_mapping_dependency AS dependency
              ON dependency.provider_market_representation_id =
                 book.provider_market_representation_id
             AND dependency.publication_batch_id = book.publication_batch_id
            JOIN core.external_identifier AS event_mapping
              ON event_mapping.external_identifier_id = representation.event_mapping_id
            JOIN core.external_identifier AS operator_mapping
              ON operator_mapping.external_identifier_id = representation.operator_mapping_id
            LEFT JOIN core.external_identifier AS fixture_mapping
              ON fixture_mapping.external_identifier_id =
                 dependency.fixture_lookup_mapping_id
            LEFT JOIN provenance.data_provider AS fixture_provider
              ON fixture_provider.provider_id = fixture_mapping.provider_id
            LEFT JOIN core.external_identifier AS home_mapping
              ON home_mapping.external_identifier_id = dependency.home_team_mapping_id
            LEFT JOIN core.external_identifier AS away_mapping
              ON away_mapping.external_identifier_id = dependency.away_team_mapping_id
            LEFT JOIN fpl.fixture_observation AS schedule
              ON schedule.fixture_observation_id = dependency.fixture_observation_id
            JOIN betting.operator_fixture_market AS market
              ON market.market_id = book.market_id
            JOIN football.fixture AS mapped_fixture
              ON mapped_fixture.fixture_id = market.fixture_id
            JOIN provenance.source_snapshot AS snapshot
              ON snapshot.source_snapshot_id = book.source_snapshot_id
            JOIN provenance.rights_profile AS profile
              ON profile.rights_profile_record_id = snapshot.rights_profile_record_id
            WHERE book.book_observation_id IN :book_ids
            ORDER BY operator_mapping.external_id_text, book.book_observation_id
            """
        ).bindparams(bindparam("book_ids", expanding=True))
        eligibility_rows = [
            dict(row)
            for row in self.session.execute(
                eligibility_statement,
                {
                    "book_ids": book_ids,
                    "cutoff": cutoff,
                    "fixture_external_id": fixture_external_id,
                    "fixture_external_provider": fixture_external_provider,
                },
            ).mappings()
        ]
        if {_uuid(row["book_observation_id"]) for row in eligibility_rows} != set(book_ids):
            raise IngestionError(
                "CANONICAL_INVARIANT", "stored book eligibility lineage is incomplete"
            )
        source_observations = tuple(
            observation
            for book in self._books_from_rows(fixture_id=fixture_id, rows=rows)
            for observation in book.observations
            if isinstance(observation, ExclusiveOutcomeQuote)
        )
        quotes_by_book: dict[UUID, list[ExclusiveOutcomeQuote]] = {}
        for observation in source_observations:
            quotes_by_book.setdefault(observation.book_observation_id, []).append(observation)
        book_rows: dict[UUID, list[dict[str, object]]] = {}
        for row in rows:
            book_rows.setdefault(_uuid(row["book_observation_id"]), []).append(row)
        eligibility_by_book = {_uuid(row["book_observation_id"]): row for row in eligibility_rows}
        candidates_by_operator: dict[UUID, list[UUID]] = {}
        for book_id in book_ids:
            operator_id = _uuid(book_rows[book_id][0]["operator_id"])
            candidates_by_operator.setdefault(operator_id, []).append(book_id)
        for candidates in candidates_by_operator.values():
            candidates.sort(
                key=lambda book_id: (
                    _datetime(book_rows[book_id][0]["attested_usable_at"]),
                    _datetime(book_rows[book_id][0]["provider_observed_at"]),
                    str(book_rows[book_id][0]["source_snapshot_id"]),
                    str(book_id),
                ),
                reverse=True,
            )

        eligible_ids: set[UUID] = set()
        exclusions: list[ExcludedBook] = []
        warnings: set[str] = set()
        mapping_fields = (
            "representation_matches_plan",
            "event_mapping_valid",
            "operator_mapping_valid",
            "schedule_matches",
            "fixture_mapping_valid",
            "home_team_mapping_valid",
            "away_team_mapping_valid",
        )
        state_reasons = {
            MarketState.INCOMPLETE: ExclusionReason.INCOMPLETE,
            MarketState.SUSPENDED: ExclusionReason.SUSPENDED,
            MarketState.UNSUPPORTED: ExclusionReason.UNSUPPORTED,
            MarketState.UNAVAILABLE: ExclusionReason.UNAVAILABLE,
        }
        for operator_id in sorted(candidates_by_operator, key=str):
            for book_id in candidates_by_operator[operator_id]:
                eligibility = eligibility_by_book[book_id]
                operator_key = str(eligibility["operator_key"])
                approved_at = _datetime(eligibility["mapping_plan_approved_at"])
                reason: ExclusionReason | None = None
                if (
                    approved_at > cutoff
                    or not _mapping_dependency_hash_matches(eligibility)
                    or not all(bool(eligibility[name]) for name in mapping_fields)
                ):
                    reason = ExclusionReason.MAPPING_UNAVAILABLE
                elif not bool(eligibility["rights_valid"]):
                    reason = ExclusionReason.RIGHTS_BLOCKED
                elif _integer(eligibility["blocking_issue_count"]) > 0:
                    reason = ExclusionReason.QUALITY_BLOCKED
                else:
                    market_state = MarketState(str(eligibility["market_state"]))
                    reason = state_reasons.get(market_state)
                    quotes = quotes_by_book.get(book_id, [])
                    if reason is None and (
                        len(quotes) != 3
                        or {quote.outcome for quote in quotes} != set(MarketOutcome)
                    ):
                        reason = ExclusionReason.INCOMPLETE
                    if reason is None and any(
                        quote.observed_at > cutoff or quote.usable_at > cutoff for quote in quotes
                    ):
                        reason = ExclusionReason.FUTURE_OBSERVATION
                    if reason is None:
                        latest_observed = max(quote.observed_at for quote in quotes)
                        if cutoff - latest_observed > timedelta(seconds=stale_after_seconds):
                            reason = ExclusionReason.STALE
                if reason is not None:
                    exclusions.append(ExcludedBook(operator_key=operator_key, reason=reason))
                    warnings.add(f"BOOK_EXCLUDED_{reason.value}")
                    continue
                eligible_ids.add(book_id)
                warning_codes = eligibility["warning_codes"]
                if not isinstance(warning_codes, (list, tuple)):
                    raise IngestionError(
                        "CANONICAL_INVARIANT", "stored quality warning evidence is invalid"
                    )
                warnings.update(str(code) for code in warning_codes)
                break
        source_books = tuple(
            SourceBookLineage(
                book_observation_id=book_id,
                source_snapshot_id=source_snapshot_id,
                fixture_id=fixture_id,
            )
            for book_id, source_snapshot_id in sorted(
                {
                    _uuid(row["book_observation_id"]): _uuid(row["source_snapshot_id"])
                    for row in rows
                }.items(),
                key=lambda item: str(item[0]),
            )
        )
        eligible_observations = tuple(
            observation
            for observation in source_observations
            if observation.book_observation_id in eligible_ids
        )
        return NormalisationInput(
            eligible_observations=eligible_observations,
            source_observations=source_observations,
            source_books=source_books,
            exclusions=tuple(
                sorted(set(exclusions), key=lambda item: (item.operator_key, item.reason.value))
            ),
            warnings=tuple(sorted(warnings)),
        )

    def persist_normalisation(
        self,
        *,
        result: MarketNormalisationResult,
        policy: MarketNormalisationPolicy,
        observations: tuple[ExclusiveOutcomeQuote, ...],
        book_sources: tuple[SourceBookLineage, ...],
        input_signature_sha256: str,
        semantic_result_sha256: str,
    ) -> UUID:
        """Persist or concurrency-reuse one exact immutable normalisation run."""

        if result.fixture_id is None:
            raise IngestionError(
                "MAPPING_CONFLICT", "normalisation without a fixture cannot be persisted"
            )
        policy_document = policy.model_dump(mode="json", exclude={"sha256"})
        if canonical_json_sha256(policy_document) != policy.sha256:
            raise IngestionError("POLICY_INVALID", "normalisation policy hash is inconsistent")
        self.session.execute(
            postgresql_insert(market_normalisation_policy)
            .values(
                policy_sha256=policy.sha256,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                policy_document=policy_document,
            )
            .on_conflict_do_nothing(index_elements=[market_normalisation_policy.c.policy_sha256])
        )
        stored_policy = (
            self.session.execute(
                select(market_normalisation_policy).where(
                    market_normalisation_policy.c.policy_sha256 == policy.sha256
                )
            )
            .mappings()
            .one()
        )
        if (
            stored_policy["policy_id"] != policy.policy_id
            or stored_policy["policy_version"] != policy.version
            or dict(stored_policy["policy_document"]) != policy_document
            or canonical_json_sha256(dict(stored_policy["policy_document"])) != policy.sha256
        ):
            raise IngestionError("POLICY_INVALID", "stored normalisation policy conflicts")
        mapping_cutoff = (
            result.consensus.mapping_cutoff if result.consensus is not None else result.as_of
        )
        created = self.session.execute(
            postgresql_insert(market_normalisation_run)
            .values(
                fixture_id=result.fixture_id,
                market_definition="FULL_TIME_1X2",
                as_of=result.as_of,
                mapping_cutoff=mapping_cutoff,
                policy_sha256=policy.sha256,
                code_identity=code_identity(),
                input_signature_sha256=input_signature_sha256,
                semantic_result_sha256=semantic_result_sha256,
                status=result.status.value,
            )
            .on_conflict_do_nothing(
                index_elements=[market_normalisation_run.c.input_signature_sha256]
            )
            .returning(market_normalisation_run.c.normalisation_run_id)
        ).scalar_one_or_none()
        if created is None:
            existing = (
                self.session.execute(
                    select(market_normalisation_run).where(
                        market_normalisation_run.c.input_signature_sha256 == input_signature_sha256
                    )
                )
                .mappings()
                .one()
            )
            if (
                existing["fixture_id"] != result.fixture_id
                or existing["as_of"] != result.as_of
                or existing["mapping_cutoff"] != mapping_cutoff
                or existing["policy_sha256"] != policy.sha256
                or existing["semantic_result_sha256"] != semantic_result_sha256
                or existing["status"] != result.status.value
            ):
                raise IngestionError(
                    "CANONICAL_INVARIANT", "normalisation input signature conflicts"
                )
            return _uuid(existing["normalisation_run_id"])
        run_id = _uuid(created)
        unique_books = {item.book_observation_id: item for item in book_sources}
        for book_id in sorted(unique_books, key=str):
            book = unique_books[book_id]
            self.session.execute(
                insert(market_normalisation_book_source).values(
                    normalisation_run_id=run_id,
                    book_observation_id=book_id,
                    source_snapshot_id=book.source_snapshot_id,
                    fixture_id=book.fixture_id,
                )
            )
        unique_observations = {
            observation.odds_observation_id: observation for observation in observations
        }
        for observation_id in sorted(unique_observations, key=str):
            observation = unique_observations[observation_id]
            self.session.execute(
                insert(market_normalisation_source).values(
                    normalisation_run_id=run_id,
                    odds_observation_id=observation_id,
                    source_snapshot_id=observation.source_snapshot_id,
                )
            )
        if result.consensus is not None:
            consensus = result.consensus
            for operator in consensus.operator_markets:
                operator_result_id = _uuid(
                    self.session.execute(
                        insert(normalised_operator_market)
                        .values(
                            normalisation_run_id=run_id,
                            fixture_id=operator.fixture_id,
                            market_id=operator.market_id,
                            provider_id=operator.provider_id,
                            operator_id=operator.operator_id,
                            operator_key=operator.operator_key,
                            observed_at=operator.observed_at,
                            usable_at=operator.usable_at,
                            primary_method=operator.primary_method.value,
                            fallback_used=operator.fallback_used,
                            raw_booksum=operator.raw_booksum,
                            overround=operator.overround,
                            power_exponent=operator.power_exponent,
                            input_signature_sha256=operator.input_signature_sha256,
                            result_sha256=operator.result_sha256,
                        )
                        .returning(normalised_operator_market.c.normalised_operator_market_id)
                    ).scalar_one()
                )
                for observation_id in operator.source_observation_ids:
                    source = unique_observations.get(observation_id)
                    if source is None:
                        raise IngestionError(
                            "CANONICAL_INVARIANT",
                            "normalised operator source is absent from run lineage",
                        )
                    self.session.execute(
                        insert(normalised_operator_market_source).values(
                            normalised_operator_market_id=operator_result_id,
                            normalisation_run_id=run_id,
                            odds_observation_id=observation_id,
                            source_snapshot_id=source.source_snapshot_id,
                            fixture_id=source.fixture_id,
                        )
                    )
                for outcome in operator.outcomes:
                    self.session.execute(
                        insert(normalised_operator_outcome).values(
                            normalised_operator_market_id=operator_result_id,
                            normalisation_run_id=run_id,
                            outcome=outcome.outcome.value,
                            decimal_odds=outcome.decimal_odds,
                            raw_implied_probability=outcome.raw_implied_probability,
                            proportional_probability=outcome.proportional_probability,
                            market_probability=outcome.market_probability,
                        )
                    )
            self.session.execute(
                insert(market_consensus_result).values(
                    normalisation_run_id=run_id,
                    provider_count=consensus.provider_count,
                    operator_count=consensus.operator_count,
                    eligible_operator_count=consensus.eligible_operator_count,
                    operator_disagreement=consensus.operator_disagreement,
                    method_disagreement=consensus.method_disagreement,
                    market_disagreement=consensus.market_disagreement,
                    minimum_age_seconds=consensus.freshness.minimum_age_seconds,
                    maximum_age_seconds=consensus.freshness.maximum_age_seconds,
                    confidence_grade=consensus.confidence_grade,
                    input_signature_sha256=consensus.input_signature_sha256,
                    result_sha256=consensus.result_sha256,
                )
            )
            for consensus_outcome in consensus.outcomes:
                self.session.execute(
                    insert(market_consensus_outcome).values(
                        normalisation_run_id=run_id,
                        outcome=consensus_outcome.outcome.value,
                        consensus_probability=consensus_outcome.consensus_probability,
                        lower_bound=consensus_outcome.lower_bound,
                        upper_bound=consensus_outcome.upper_bound,
                    )
                )
        for sequence, exclusion in enumerate(result.excluded_books, start=1):
            self.session.execute(
                insert(market_normalisation_exclusion).values(
                    normalisation_run_id=run_id,
                    sequence_number=sequence,
                    operator_key=exclusion.operator_key,
                    reason=exclusion.reason.value,
                )
            )
        for sequence, warning in enumerate(result.warnings, start=1):
            self.session.execute(
                insert(market_normalisation_warning).values(
                    normalisation_run_id=run_id,
                    sequence_number=sequence,
                    warning_code=warning,
                )
            )
        return run_id
