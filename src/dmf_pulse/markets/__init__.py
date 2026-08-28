"""Canonical market observations, exact normalisation and consensus."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dmf_pulse.markets.consensus import build_market_consensus
from dmf_pulse.markets.models import (
    ExclusionReason,
    ExclusiveOutcomeQuote,
    MarketBook,
    MarketConsensus,
    MarketNormalisationResult,
    MarketObservation,
    MarketOutcome,
    MarketQueryResult,
    MarketState,
    NormalisationMethod,
    NormalisationStatus,
    NormalisedOperatorMarket,
    Probability,
)
from dmf_pulse.markets.normalisation import (
    normalise_complete_market,
    raw_implied_probability,
)
from dmf_pulse.markets.policy import (
    ConsensusPolicy,
    MarketNormalisationPolicy,
    load_market_normalisation_policy,
)

if TYPE_CHECKING:
    from dmf_pulse.markets.current import (
        CurrentMarketCanonicalIdentityRepository,
        CurrentMarketCanonicalIdentityView,
        CurrentMarketConstraintBundle,
        CurrentMarketConstraintError,
        CurrentMarketConstraintRequest,
        CurrentMarketConstraintService,
        CurrentMarketReadiness,
    )

_CURRENT_EXPORTS = frozenset(
    {
        "CurrentMarketCanonicalIdentityRepository",
        "CurrentMarketCanonicalIdentityView",
        "CurrentMarketConstraintBundle",
        "CurrentMarketConstraintError",
        "CurrentMarketConstraintRequest",
        "CurrentMarketConstraintService",
        "CurrentMarketReadiness",
        "bind_current_market_constraint_request",
    }
)


def __getattr__(name: str) -> Any:
    """Load current-market orchestration only when explicitly requested."""

    if name not in _CURRENT_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from dmf_pulse.markets import current

    value = getattr(current, name)
    globals()[name] = value
    return value


__all__ = [
    "ConsensusPolicy",
    "CurrentMarketCanonicalIdentityRepository",
    "CurrentMarketCanonicalIdentityView",
    "CurrentMarketConstraintBundle",
    "CurrentMarketConstraintError",
    "CurrentMarketConstraintRequest",
    "CurrentMarketConstraintService",
    "CurrentMarketReadiness",
    "ExclusionReason",
    "ExclusiveOutcomeQuote",
    "MarketBook",
    "MarketConsensus",
    "MarketNormalisationPolicy",
    "MarketNormalisationResult",
    "MarketObservation",
    "MarketOutcome",
    "MarketQueryResult",
    "MarketState",
    "NormalisationMethod",
    "NormalisationStatus",
    "NormalisedOperatorMarket",
    "Probability",
    "bind_current_market_constraint_request",
    "build_market_consensus",
    "load_market_normalisation_policy",
    "normalise_complete_market",
    "raw_implied_probability",
]
