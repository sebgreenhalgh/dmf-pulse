"""Zero-retention current Odds acquisition for the one-command path."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import NAMESPACE_URL, uuid5

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.client import OddsClient
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.credentials import EnvironmentOddsCredentialProvider
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput, build_current_odds_input
from dmf_pulse.ingestion.odds.parser import parse_odds_payload

ODDS_PRIVATE_PROFILE_ID = "the_odds_api_private_analytics_v1"


class CurrentOddsTransientService:
    """Perform one existing Odds fetch and compile its body only in memory."""

    def __init__(
        self,
        *,
        credential_provider: EnvironmentOddsCredentialProvider | None = None,
        client_factory: Callable[..., OddsClient] = OddsClient,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._credential_provider = credential_provider or EnvironmentOddsCredentialProvider()
        self._client_factory = client_factory
        self._clock = clock

    def acquire(
        self,
        *,
        information_cutoff: datetime,
        commence_to: datetime,
    ) -> OddsProviderCurrentInput:
        if information_cutoff.tzinfo is None or information_cutoff.utcoffset() is None:
            raise IngestionError("VALIDATION_FAILED", "Odds cutoff must be timezone-aware")
        if commence_to.tzinfo is None or commence_to.utcoffset() is None:
            raise IngestionError("VALIDATION_FAILED", "Odds range must be timezone-aware")
        cutoff = information_cutoff.astimezone(UTC)
        range_end = commence_to.astimezone(UTC)
        if range_end <= cutoff:
            raise IngestionError("VALIDATION_FAILED", "Odds fixture range is empty")
        if not self._credential_provider._configured():
            raise IngestionError("CREDENTIAL_UNAVAILABLE", "THE_ODDS_API_KEY is missing.")
        profile = load_rights_profiles()[ODDS_PRIVATE_PROFILE_ID]
        client = self._client_factory(
            profile,
            credential_provider=self._credential_provider,
            clock=self._clock,
        )
        fetched = client.fetch(commence_from=cutoff, commence_to=range_end)
        parsed = parse_odds_payload(fetched.body)
        if not fetched.attempts:
            raise IngestionError("INTERNAL_INVARIANT", "Odds retrieval evidence is absent")
        first = fetched.attempts[0]
        last = fetched.attempts[-1]
        usable_at = self._clock()
        if usable_at.tzinfo is None or usable_at.utcoffset() is None:
            raise IngestionError("INTERNAL_INVARIANT", "Odds clock must be timezone-aware")
        transport_id = cast(
            Literal["stdlib_http_client", "stdlib_urllib", "injected"], fetched.transport_id
        )
        return build_current_odds_input(
            parsed,
            profile=profile,
            source_snapshot_id=uuid5(
                NAMESPACE_URL,
                f"dmf-pulse:odds-transient:{parsed.body_sha256}:{last.received_at.isoformat()}",
            ),
            request_started_at=first.request_started_at,
            received_at=last.received_at,
            information_cutoff=cutoff,
            usable_at=usable_at.astimezone(UTC),
            quota=fetched.quota,
            request_fingerprint=fetched.request_fingerprint,
            sanitized_target=fetched.sanitized_target,
            attempt_count=len(fetched.attempts),
            transport_call_count=fetched.transport_call_count,
            transport_id=transport_id,
            provider_request_id_sha256=fetched.provider_request_id_sha256,
        )


__all__ = ["ODDS_PRIVATE_PROFILE_ID", "CurrentOddsTransientService"]
