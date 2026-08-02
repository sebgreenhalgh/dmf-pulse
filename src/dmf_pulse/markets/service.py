"""Database boundary for public market observation queries."""

from __future__ import annotations

from datetime import datetime

from dmf_pulse.database.engine import session_factory
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    _validate_database_reference,
)
from dmf_pulse.ingestion.fpl.service import (
    _engine as _fpl_database_engine,
)
from dmf_pulse.markets.models import MarketQueryResult
from dmf_pulse.markets.repository import MarketObservationRepository


class MarketService:
    def observations(
        self,
        *,
        fixture_external_provider: str,
        fixture_external_id: str,
        season_code: str,
        as_of: datetime,
        database_url_ref: str = DATABASE_REF,
    ) -> MarketQueryResult:
        _validate_database_reference(database_url_ref)
        engine = _fpl_database_engine(database_url_ref)
        try:
            factory = session_factory(engine)
            with factory() as session:
                repository = MarketObservationRepository(session)
                fixture_id = repository.resolve_fixture(
                    external_provider=fixture_external_provider,
                    external_id=fixture_external_id,
                    season_code=season_code,
                    as_of=as_of,
                )
                return repository.observations(fixture_id=fixture_id, as_of=as_of)
        finally:
            engine.dispose()
