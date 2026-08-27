"""Official-FPL-shaped reference adapter implemented against synthetic fixtures."""

from dmf_pulse.ingestion.fpl.adapter import FplReferenceAdapter
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplInputBundle,
    CurrentFplInputRequest,
    CurrentFplInputService,
    CurrentFplInputSummary,
)
from dmf_pulse.ingestion.fpl.manager_current import (
    CurrentManagerDeclaration,
    CurrentManagerStateBundle,
    CurrentManagerStateRequest,
    CurrentManagerStateService,
    CurrentManagerStateSummary,
    bind_current_manager_state_request,
)
from dmf_pulse.ingestion.fpl.parser import FplResource, ParsedFplResource, parse_fpl_payload

__all__ = [
    "CurrentFplInputBundle",
    "CurrentFplInputRequest",
    "CurrentFplInputService",
    "CurrentFplInputSummary",
    "CurrentManagerDeclaration",
    "CurrentManagerStateBundle",
    "CurrentManagerStateRequest",
    "CurrentManagerStateService",
    "CurrentManagerStateSummary",
    "FplReferenceAdapter",
    "FplResource",
    "ParsedFplResource",
    "bind_current_manager_state_request",
    "parse_fpl_payload",
]
