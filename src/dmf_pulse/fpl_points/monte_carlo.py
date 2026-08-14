"""Monte Carlo numerical diagnostics kept separate from football uncertainty."""

from __future__ import annotations

from math import sqrt

from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import (
    FixturePointScenario,
    MonteCarloDiagnostics,
    MonteCarloPolicy,
)
from dmf_pulse.fpl_points.summaries import (
    normalize_weights,
    threshold_probability,
    weighted_quantile,
    weighted_variance,
)


def effective_sample_size(weights: tuple[float, ...]) -> float:
    normalized = normalize_weights(weights)
    return 1.0 / sum(weight * weight for weight in normalized)


def _batch_indices(length: int, batch_count: int) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(range(batch, length, batch_count)) for batch in range(batch_count))


def monte_carlo_diagnostics(
    scenarios: tuple[FixturePointScenario, ...], policy: MonteCarloPolicy
) -> MonteCarloDiagnostics:
    if not scenarios:
        raise FplPointsError("SCENARIOS_EMPTY", "Monte Carlo diagnostics require scenarios")
    player_ids = tuple(sorted(scenarios[0].players))
    weights = tuple(scenario.weight for scenario in scenarios)
    normalized = normalize_weights(weights)
    ess = effective_sample_size(weights)
    mean_mcse: dict[str, float] = {}
    probability_se: dict[str, dict[str, float]] = {}
    quantile_span: dict[str, dict[str, int]] = {}
    batches = tuple(batch for batch in _batch_indices(len(scenarios), policy.batch_count) if batch)
    for player_id in player_ids:
        values = tuple(scenario.players[player_id].total for scenario in scenarios)
        variance = weighted_variance(tuple(float(value) for value in values), weights)
        mean_mcse[player_id] = sqrt(variance / ess)
        probability_se[player_id] = {}
        for threshold in policy.thresholds:
            probability = threshold_probability(values, weights, threshold)
            probability_se[player_id][str(threshold)] = sqrt(
                max(0.0, probability * (1.0 - probability) / ess)
            )
        quantile_span[player_id] = {}
        for probability in policy.quantiles:
            batch_quantiles: list[int] = []
            for batch in batches:
                batch_values = tuple(values[index] for index in batch)
                batch_weights = tuple(normalized[index] for index in batch)
                batch_quantiles.append(weighted_quantile(batch_values, batch_weights, probability))
            quantile_span[player_id][f"p{round(probability * 100):02d}"] = max(
                batch_quantiles
            ) - min(batch_quantiles)
    reasons: list[str] = []
    if ess < policy.minimum_effective_scenarios:
        reasons.append("ESS_BELOW_THRESHOLD")
    if max(mean_mcse.values(), default=0.0) > policy.maximum_mean_mcse:
        reasons.append("MEAN_MCSE_ABOVE_THRESHOLD")
    if (
        max(
            (value for player in probability_se.values() for value in player.values()),
            default=0.0,
        )
        > policy.maximum_probability_se
    ):
        reasons.append("THRESHOLD_PROBABILITY_SE_ABOVE_THRESHOLD")
    if (
        max(
            (value for player in quantile_span.values() for value in player.values()),
            default=0,
        )
        > policy.maximum_quantile_span
    ):
        reasons.append("QUANTILE_STABILITY_ABOVE_THRESHOLD")
    return MonteCarloDiagnostics(
        scenario_count=len(scenarios),
        normalized_weight_sum=sum(normalized),
        effective_sample_size=ess,
        max_scenario_weight=max(normalized),
        mean_mcse_by_player=mean_mcse,
        threshold_probability_se_by_player=probability_se,
        quantile_stability_max_span_by_player=quantile_span,
        stopping_result="PASS" if not reasons else "CONTINUE",
        stopping_reasons=tuple(reasons),
    )
