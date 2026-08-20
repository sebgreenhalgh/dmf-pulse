"""Market-constrained team score and clean-sheet distributions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dmf_pulse.football_events.coherence import (
    ScoreCoherenceError,
    assert_score_coherence,
)
from dmf_pulse.football_events.evaluation import evaluate_realized_score
from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketConstraintSet,
    MarketFamily,
    ScoreEvent,
    cap_market_family_weights,
    combine_market_constraint_sets,
    constraints_from_market_consensus,
    constraints_from_totals_consensus,
)
from dmf_pulse.football_events.minutes_context import (
    Stage7MinutesContext,
    TeamMinutesProjectionIdentity,
)
from dmf_pulse.football_events.poisson import (
    adaptive_poisson_support,
    poisson_pmf,
    poisson_tail_mass,
)
from dmf_pulse.football_events.score_distribution import JointScoreDistribution
from dmf_pulse.football_events.score_prior import ScorePrior, build_score_prior
from dmf_pulse.football_events.score_projection import project_to_markets

if TYPE_CHECKING:
    from dmf_pulse.football_events.service import (
        ScoreBaselinePolicy,
        ScoreDistributionError,
        ScoreDistributionRequest,
        ScoreDistributionResult,
        ScoreDistributionService,
    )

_SERVICE_EXPORTS = frozenset(
    {
        "ScoreBaselinePolicy",
        "ScoreDistributionError",
        "ScoreDistributionRequest",
        "ScoreDistributionResult",
        "ScoreDistributionService",
        "load_score_baseline_policy",
    }
)


def __getattr__(name: str) -> Any:
    """Load orchestration exports only when requested.

    Pure score mathematics remains importable without eagerly importing the
    Stage-6 market orchestration boundary.
    """

    if name not in _SERVICE_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from dmf_pulse.football_events import service

    value = getattr(service, name)
    globals()[name] = value
    return value


__all__ = [
    "JointScoreDistribution",
    "MarketConstraint",
    "MarketConstraintSet",
    "MarketFamily",
    "ScoreBaselinePolicy",
    "ScoreCoherenceError",
    "ScoreDistributionError",
    "ScoreDistributionRequest",
    "ScoreDistributionResult",
    "ScoreDistributionService",
    "ScoreEvent",
    "ScorePrior",
    "Stage7MinutesContext",
    "TeamMinutesProjectionIdentity",
    "adaptive_poisson_support",
    "assert_score_coherence",
    "build_score_prior",
    "cap_market_family_weights",
    "combine_market_constraint_sets",
    "constraints_from_market_consensus",
    "constraints_from_totals_consensus",
    "evaluate_realized_score",
    "load_score_baseline_policy",
    "poisson_pmf",
    "poisson_tail_mass",
    "project_to_markets",
]
