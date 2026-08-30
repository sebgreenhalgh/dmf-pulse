"""Approved commit-pinned OpenFootball historical score-prior adapter."""

from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorResult,
    CurrentScorePriorService,
    CurrentScorePriorSummary,
)

__all__ = [
    "CurrentScorePriorBuildRequest",
    "CurrentScorePriorResult",
    "CurrentScorePriorService",
    "CurrentScorePriorSummary",
]
