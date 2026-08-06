"""Stable NRM-006 semantic projections for golden and audit comparison."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dmf_pulse.markets.models import MarketNormalisationResult, source_decimal_text
from dmf_pulse.markets.policy import MarketNormalisationPolicy, canonical_json_sha256


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def market_normalisation_semantic_projection(
    result: MarketNormalisationResult,
    *,
    policy: MarketNormalisationPolicy,
) -> dict[str, Any]:
    """Remove generated IDs while retaining every frozen semantic output."""

    exclusions = [
        {"operator_key": item.operator_key, "reason": item.reason.value}
        for item in result.excluded_books
    ]
    if result.consensus is None:
        projected: dict[str, Any] = {
            "status": result.status.value,
            "reason": result.error_code,
            "eligible_operator_count": 0,
            "excluded_books": exclusions,
            "contains_probabilities": False,
            "policy_id": policy.policy_id,
            "policy_sha256": policy.sha256,
        }
    else:
        consensus = result.consensus
        projected = {
            "status": result.status.value,
            "as_of": _timestamp(result.as_of),
            "mapping_cutoff": _timestamp(consensus.mapping_cutoff),
            "market_definition": consensus.market_definition,
            "policy_id": consensus.policy_id,
            "policy_sha256": consensus.policy_sha256,
            "provider_count": consensus.provider_count,
            "operator_count": consensus.operator_count,
            "eligible_operator_count": consensus.eligible_operator_count,
            "operator_markets": [
                {
                    "operator_key": market.operator_key,
                    "raw_booksum": format(market.raw_booksum, ".12f"),
                    "overround": format(market.overround, ".12f"),
                    "power_exponent": (
                        format(market.power_exponent, ".12f")
                        if market.power_exponent is not None
                        else None
                    ),
                    "outcomes": [
                        {
                            "outcome": outcome.outcome.value,
                            "decimal_odds": source_decimal_text(outcome.decimal_odds),
                            "raw_implied_probability": format(
                                outcome.raw_implied_probability, ".12f"
                            ),
                            "proportional_probability": format(
                                outcome.proportional_probability, ".12f"
                            ),
                            "market_probability": format(outcome.market_probability, ".12f"),
                        }
                        for outcome in market.outcomes
                    ],
                }
                for market in consensus.operator_markets
            ],
            "outcomes": [
                {
                    "outcome": outcome.outcome.value,
                    "consensus_probability": format(outcome.consensus_probability, ".12f"),
                    "lower_bound": format(outcome.lower_bound, ".12f"),
                    "upper_bound": format(outcome.upper_bound, ".12f"),
                }
                for outcome in consensus.outcomes
            ],
            "operator_disagreement": format(consensus.operator_disagreement, ".12f"),
            "method_disagreement": format(consensus.method_disagreement, ".12f"),
            "market_disagreement": format(consensus.market_disagreement, ".12f"),
            "freshness": {
                "minimum_age_seconds": consensus.freshness.minimum_age_seconds,
                "maximum_age_seconds": consensus.freshness.maximum_age_seconds,
            },
            "confidence_grade": consensus.confidence_grade,
            "excluded_books": exclusions,
            "warnings": list(result.warnings),
        }
    projected["semantic_result_sha256"] = canonical_json_sha256(projected)
    return projected


__all__ = ["market_normalisation_semantic_projection"]
