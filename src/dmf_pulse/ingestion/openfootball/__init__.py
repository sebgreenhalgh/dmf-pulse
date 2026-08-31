"""Approved commit-pinned OpenFootball historical score-prior adapter."""

from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorBundle,
    CurrentScorePriorResult,
    CurrentScorePriorService,
    CurrentScorePriorSummary,
    build_current_score_prior_bundle,
    score_prior_request_from_bundle,
)

__all__ = [
    "CurrentScorePriorBuildRequest",
    "CurrentScorePriorBundle",
    "CurrentScorePriorResult",
    "CurrentScorePriorService",
    "CurrentScorePriorSummary",
    "build_current_score_prior_bundle",
    "score_prior_request_from_bundle",
]
