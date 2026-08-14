"""Weighted Gameweek marginals, joint matrix, and numerical diagnostics."""

from __future__ import annotations

from math import sqrt

from dmf_pulse.fpl_points.models import (
    POINT_COMPONENT_NAMES,
    ComponentSummary,
    GameweekBpsBonusSummary,
    GameweekPlayerProjectionSummary,
    GameweekProjectionResult,
    GameweekScenarioSet,
    JointScenarioMatrix,
    MonteCarloDiagnostics,
    MonteCarloPolicy,
)
from dmf_pulse.fpl_points.monte_carlo import effective_sample_size
from dmf_pulse.fpl_points.summaries import (
    DEFAULT_QUANTILES,
    normalize_weights,
    threshold_probability,
    weighted_covariance,
    weighted_mean,
    weighted_quantile,
    weighted_variance,
)


def _quantile_key(probability: float) -> str:
    return f"p{round(probability * 100):02d}"


def _pmf(values: tuple[int, ...], weights: tuple[float, ...]) -> dict[int, float]:
    normalized = normalize_weights(weights)
    result: dict[int, float] = {}
    for value, weight in zip(values, normalized, strict=True):
        result[value] = result.get(value, 0.0) + weight
    return dict(sorted(result.items()))


def _component_summary(values: tuple[int, ...], weights: tuple[float, ...]) -> ComponentSummary:
    return ComponentSummary(
        expected_points=weighted_mean(tuple(float(value) for value in values), weights),
        probability_nonzero=sum(
            weight
            for value, weight in zip(values, normalize_weights(weights), strict=True)
            if value != 0
        ),
        minimum=min(values),
        maximum=max(values),
        variance=weighted_variance(tuple(float(value) for value in values), weights),
    )


def _component_covariance(
    vectors: dict[str, tuple[int, ...]], weights: tuple[float, ...]
) -> dict[str, dict[str, float]]:
    return {
        left: {
            right: weighted_covariance(
                tuple(float(value) for value in vectors[left]),
                tuple(float(value) for value in vectors[right]),
                weights,
            )
            for right in POINT_COMPONENT_NAMES
        }
        for left in POINT_COMPONENT_NAMES
    }


def _batch_indices(length: int, batch_count: int) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(range(batch, length, batch_count)) for batch in range(batch_count))


def gameweek_monte_carlo_diagnostics(
    scenario_set: GameweekScenarioSet, policy: MonteCarloPolicy
) -> MonteCarloDiagnostics:
    scenarios = scenario_set.scenarios
    weights = tuple(scenario.weight for scenario in scenarios)
    normalized = normalize_weights(weights)
    ess = effective_sample_size(weights)
    mean_mcse: dict[str, float] = {}
    probability_se: dict[str, dict[str, float]] = {}
    quantile_span: dict[str, dict[str, int]] = {}
    batches = tuple(batch for batch in _batch_indices(len(scenarios), policy.batch_count) if batch)
    for player_id in scenario_set.player_ids:
        values = tuple(scenario.player_points[player_id] for scenario in scenarios)
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
            batch_quantiles = [
                weighted_quantile(
                    tuple(values[index] for index in batch),
                    tuple(normalized[index] for index in batch),
                    probability,
                )
                for batch in batches
            ]
            quantile_span[player_id][_quantile_key(probability)] = max(batch_quantiles) - min(
                batch_quantiles
            )
    reasons: list[str] = []
    deterministic_blank = (
        all(value == 0 for scenario in scenarios for value in scenario.player_points.values())
        and scenario_set.assembly_mode.value == "BLANK"
    )
    if not deterministic_blank:
        if ess < policy.minimum_effective_scenarios:
            reasons.append("ESS_BELOW_THRESHOLD")
        if max(mean_mcse.values(), default=0.0) > policy.maximum_mean_mcse:
            reasons.append("MEAN_MCSE_ABOVE_THRESHOLD")
        if (
            max(
                (value for per_player in probability_se.values() for value in per_player.values()),
                default=0.0,
            )
            > policy.maximum_probability_se
        ):
            reasons.append("THRESHOLD_PROBABILITY_SE_ABOVE_THRESHOLD")
        if (
            max(
                (value for per_player in quantile_span.values() for value in per_player.values()),
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


def build_gameweek_joint_matrix(scenario_set: GameweekScenarioSet) -> JointScenarioMatrix:
    from dmf_pulse.fpl_points.summaries import _pair_dependence

    scenarios = scenario_set.scenarios
    weights = normalize_weights(tuple(scenario.weight for scenario in scenarios))
    player_ids = scenario_set.player_ids
    values = {
        player_id: tuple(scenario.player_points[player_id] for scenario in scenarios)
        for player_id in player_ids
    }
    return JointScenarioMatrix(
        scenario_ids=tuple(scenario.scenario_id for scenario in scenarios),
        outcome_draw_ids=tuple(scenario.outcome_draw_id for scenario in scenarios),
        player_ids=player_ids,
        weights=weights,
        points=tuple(
            tuple(scenario.player_points[player_id] for player_id in player_ids)
            for scenario in scenarios
        ),
        ruleset_hash=scenario_set.ruleset_hash,
        dependence={
            left: {
                right: _pair_dependence(values[left], values[right], weights)
                for right in player_ids
            }
            for left in player_ids
        },
    )


def summarize_gameweek(
    scenario_set: GameweekScenarioSet,
    diagnostics: MonteCarloDiagnostics,
    *,
    quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
) -> dict[str, GameweekPlayerProjectionSummary]:
    scenarios = scenario_set.scenarios
    weights = tuple(scenario.weight for scenario in scenarios)
    normalized = normalize_weights(weights)
    summaries: dict[str, GameweekPlayerProjectionSummary] = {}
    for player_id in scenario_set.player_ids:
        totals = tuple(scenario.player_points[player_id] for scenario in scenarios)
        variance = weighted_variance(tuple(float(value) for value in totals), weights)
        vectors = {
            component: tuple(
                scenario.player_components[player_id][component] for scenario in scenarios
            )
            for component in POINT_COMPONENT_NAMES
        }
        bps = tuple(scenario.player_bps[player_id] for scenario in scenarios)
        bonus = tuple(scenario.player_bonus[player_id] for scenario in scenarios)
        summaries[player_id] = GameweekPlayerProjectionSummary(
            player_id=player_id,
            expected_points=weighted_mean(tuple(float(value) for value in totals), weights),
            median_points=weighted_quantile(totals, weights, 0.50),
            points_variance=variance,
            points_standard_deviation=sqrt(variance),
            probability_negative_points=sum(
                weight for value, weight in zip(totals, normalized, strict=True) if value < 0
            ),
            probability_zero_points=sum(
                weight for value, weight in zip(totals, normalized, strict=True) if value == 0
            ),
            probability_1_plus=threshold_probability(totals, weights, 1),
            probability_2_plus=threshold_probability(totals, weights, 2),
            probability_5_plus=threshold_probability(totals, weights, 5),
            probability_10_plus=threshold_probability(totals, weights, 10),
            probability_15_plus=threshold_probability(totals, weights, 15),
            selected_percentiles={
                _quantile_key(probability): weighted_quantile(totals, weights, probability)
                for probability in quantiles
            },
            pmf=_pmf(totals, weights),
            component_breakdown={
                component: _component_summary(vectors[component], weights)
                for component in POINT_COMPONENT_NAMES
            },
            component_covariance=_component_covariance(vectors, weights),
            bps_bonus=GameweekBpsBonusSummary(
                expected_bps=weighted_mean(tuple(float(value) for value in bps), weights),
                bps_variance=weighted_variance(tuple(float(value) for value in bps), weights),
                expected_bonus=weighted_mean(tuple(float(value) for value in bonus), weights),
                probability_any_bonus=sum(
                    weight for value, weight in zip(bonus, normalized, strict=True) if value > 0
                ),
                completeness_mode=scenario_set.bps_completeness_mode,
            ),
            monte_carlo_mean_se=diagnostics.mean_mcse_by_player[player_id],
            threshold_probability_se=diagnostics.threshold_probability_se_by_player[player_id],
            scenario_effective_sample_size=diagnostics.effective_sample_size,
            confidence_grade=scenario_set.confidence_grade,
            ruleset_hash=scenario_set.ruleset_hash,
            model_version_ids=scenario_set.model_version_ids,
            dataset_version_ids=scenario_set.dataset_version_ids,
            source_bundle_ids=scenario_set.source_bundle_ids,
            upstream_stage8_sha256s=scenario_set.upstream_stage8_sha256s,
        )
    return summaries


def build_gameweek_projection(
    scenario_set: GameweekScenarioSet, policy: MonteCarloPolicy
) -> GameweekProjectionResult:
    diagnostics = gameweek_monte_carlo_diagnostics(scenario_set, policy)
    return GameweekProjectionResult(
        schema_version="fpl-points-gameweek-result-v1",
        scenario_set=scenario_set,
        player_summaries=summarize_gameweek(scenario_set, diagnostics),
        joint_matrix=build_gameweek_joint_matrix(scenario_set),
        monte_carlo=diagnostics,
    )


__all__ = [
    "build_gameweek_joint_matrix",
    "build_gameweek_projection",
    "gameweek_monte_carlo_diagnostics",
    "summarize_gameweek",
]
