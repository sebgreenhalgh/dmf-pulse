"""Cutoff-safe PostgreSQL retrieval of latest eligible operator books."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from dmf_pulse.data_model.models import require_utc
from dmf_pulse.data_model.tables import (
    data_provider,
    external_identifier,
    season,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.markets.models import (
    MarketBook,
    MarketObservation,
    MarketOutcome,
    MarketQueryResult,
    MarketState,
)


def _uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise IngestionError("CANONICAL_INVARIANT", "database returned an invalid identifier")
    return value


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

    def observations(self, *, fixture_id: UUID, as_of: datetime) -> MarketQueryResult:
        cutoff = require_utc(as_of)
        rows = list(
            self.session.execute(
                text(
                    """
                    WITH latest_book AS (
                      SELECT DISTINCT ON (book.market_id)
                             book.book_observation_id, book.market_id,
                             book.source_snapshot_id, book.market_state,
                             book.provider_observed_at, book.received_at, book.usable_at,
                             market.operator_id, operator_record.operator_key
                      FROM betting.operator_market_observation AS book
                      JOIN betting.operator_fixture_market AS market
                        ON market.market_id = book.market_id
                      JOIN betting.betting_operator AS operator_record
                        ON operator_record.operator_id = market.operator_id
                      JOIN betting.market_definition AS definition
                        ON definition.market_definition_id = market.market_definition_id
                      JOIN betting.settlement_profile AS settlement
                        ON settlement.settlement_profile_id = market.settlement_profile_id
                      JOIN provenance.source_snapshot_lifecycle AS lifecycle
                        ON lifecycle.source_snapshot_id = book.source_snapshot_id
                      WHERE market.fixture_id = :fixture_id
                        AND definition.definition_key = 'MATCH_RESULT_1X2'
                        AND definition.definition_version = '1.0.0'
                        AND market.period = 'FULL_TIME'
                        AND market.line IS NULL
                        AND settlement.profile_key = 'SOCCER_FULL_TIME_90_MINUTES_REFERENCE_V1'
                        AND settlement.includes_extra_time = false
                        AND lifecycle.current_state = 'USABLE'
                        AND lifecycle.usable_at = book.usable_at
                        AND book.usable_at <= :cutoff
                        AND book.market_state IN
                          ('COMPLETE','INCOMPLETE','SUSPENDED','UNAVAILABLE')
                      ORDER BY book.market_id, book.usable_at DESC,
                               book.provider_observed_at DESC,
                               book.source_snapshot_id DESC,
                               book.book_observation_id DESC
                    )
                    SELECT latest.book_observation_id, latest.market_id,
                           latest.source_snapshot_id, latest.market_state,
                           latest.operator_id, latest.operator_key,
                           quote.selection_id, quote.outcome, quote.decimal_odds,
                           quote.observed_at, quote.received_at, quote.usable_at,
                           quote.contract_version, quote.odds_observation_id
                    FROM latest_book AS latest
                    LEFT JOIN betting.odds_observation AS quote
                      ON quote.book_observation_id = latest.book_observation_id
                     AND quote.usable_at <= :cutoff
                    ORDER BY latest.operator_key, latest.market_id,
                             CASE quote.outcome
                               WHEN 'HOME' THEN 1 WHEN 'DRAW' THEN 2 WHEN 'AWAY' THEN 3 ELSE 4
                             END,
                             quote.odds_observation_id
                    """
                ),
                {"fixture_id": fixture_id, "cutoff": cutoff},
            ).mappings()
        )
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
                MarketObservation(
                    fixture_id=fixture_id,
                    market_id=_uuid(row["market_id"]),
                    selection_id=_uuid(row["selection_id"]),
                    operator_id=_uuid(row["operator_id"]),
                    outcome=MarketOutcome(str(row["outcome"])),
                    decimal_odds=price,
                    observed_at=row["observed_at"],
                    received_at=row["received_at"],
                    usable_at=row["usable_at"],
                    source_snapshot_id=_uuid(row["source_snapshot_id"]),
                    market_state=MarketState(str(row["market_state"])),
                    contract_version="the-odds-api-v4-reference-v1",
                )
            )
        books = tuple(
            MarketBook(
                operator_id=group[0],
                operator_key=group[1],
                market_state=group[2],
                observations=tuple(group[3]),
            )
            for group in grouped.values()
        )
        return MarketQueryResult(
            fixture_id=fixture_id,
            as_of=cutoff,
            books=books,
            observation_count=sum(len(book.observations) for book in books),
        )
