"""Official-FPL-shaped reference adapter implemented against synthetic fixtures."""

from dmf_pulse.ingestion.fpl.adapter import FplReferenceAdapter
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplInputBundle,
    CurrentFplInputRequest,
    CurrentFplInputService,
    CurrentFplInputSummary,
)
from dmf_pulse.ingestion.fpl.parser import FplResource, ParsedFplResource, parse_fpl_payload

__all__ = [
    "CurrentFplInputBundle",
    "CurrentFplInputRequest",
    "CurrentFplInputService",
    "CurrentFplInputSummary",
    "FplReferenceAdapter",
    "FplResource",
    "ParsedFplResource",
    "parse_fpl_payload",
]
