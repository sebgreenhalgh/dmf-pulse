"""Rights-gated, deterministic source-ingestion boundaries."""

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.provider import ProviderAdapter

__all__ = ["IngestionError", "ProviderAdapter"]
