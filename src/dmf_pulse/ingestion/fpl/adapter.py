"""Reference FPL adapter implementing the common provider boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.client import FplClient, Transport, UrllibTransport
from dmf_pulse.ingestion.fpl.parser import (
    CONTRACT_VERSION,
    FplResource,
    ParsedFplResource,
    parse_fpl_payload,
)
from dmf_pulse.ingestion.models import RightsProfile


@dataclass(frozen=True, slots=True)
class FplReferenceAdapter:
    """Parse reference payloads and delegate authorized retrieval to the FPL client."""

    profile: RightsProfile | None = None
    transport_factory: Callable[[], Transport] = UrllibTransport
    provider_key: str = "official_fpl"
    adapter_version: str = CONTRACT_VERSION
    contract_version: str = CONTRACT_VERSION

    def validate(self, resource: FplResource, body: bytes) -> ParsedFplResource:
        return parse_fpl_payload(resource, body, contract_version=self.contract_version)

    def fetch(self, resource: FplResource) -> bytes:
        if self.profile is None:
            raise IngestionError("CONFIGURATION_INVALID", "FPL fetch requires a rights profile")
        return FplClient(self.profile, self.transport_factory).fetch(resource)


__all__ = ["FplReferenceAdapter"]
