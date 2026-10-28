"""Deterministic, display-only disclosure of existing one-Gameweek evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from dmf_pulse.private_v1.models import PrivateV1Decision


@dataclass(frozen=True, slots=True)
class DecisionQualitySummary:
    information_cutoff: datetime
    confidence: str
    minutes_family: str
    prior_status: str
    prior_evidence_cutoff: datetime
    fallback_player_ids: tuple[str, ...]
    monte_carlo_status: str
    monte_carlo_reasons: tuple[str, ...]
    scenario_count: int
    decision_sha256: str

    @classmethod
    def from_decision(cls, value: PrivateV1Decision) -> DecisionQualitySummary:
        decision = PrivateV1Decision.model_validate(value)
        return cls(
            information_cutoff=decision.information_cutoff,
            confidence=decision.confidence,
            minutes_family=decision.stage7_family,
            prior_status=decision.player_prior_status,
            prior_evidence_cutoff=decision.player_prior_evidence_cutoff,
            fallback_player_ids=decision.player_prior_fallback_player_ids,
            monte_carlo_status=decision.stage9_monte_carlo_status,
            monte_carlo_reasons=decision.stage9_monte_carlo_reasons,
            scenario_count=decision.scenario_count,
            decision_sha256=decision.semantic_sha256,
        )


def render_decision_quality(summary: DecisionQualitySummary, *, label: Callable[[str], str]) -> str:
    fallback = ", ".join(label(player) for player in summary.fallback_player_ids) or "NONE"
    reasons = ", ".join(summary.monte_carlo_reasons) or "NONE"
    acceptance = (
        "Historical private GW1 acceptance applies only to that GW1 scope."
        if summary.prior_status == "HISTORICAL_GW1_ACCEPTED_SCOPE"
        else "Current-GW carry-forward is outside historical private GW1 acceptance."
    )
    return (
        "DECISION EVIDENCE\n"
        f"Information cutoff: {summary.information_cutoff.isoformat()}\n"
        f"Minutes confidence (Stage 7): {summary.confidence}\n"
        f"Minutes family: {summary.minutes_family}\n"
        f"Player-prior current use: {summary.prior_status}\n"
        f"Player-prior evidence cutoff: {summary.prior_evidence_cutoff.isoformat()}\n"
        "Player allocation remains the historical Grade-E prior; this display does not establish forecast accuracy.\n"
        f"{acceptance}\n"
        f"Explicit position-fallback players: {fallback}\n"
        f"Stage-9 Monte Carlo gate: {summary.monte_carlo_status}; reasons: {reasons}\n"
        f"Scenario count: {summary.scenario_count}\n"
        f"Decision SHA: {summary.decision_sha256}\n"
    )
