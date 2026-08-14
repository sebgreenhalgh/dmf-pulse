"""Weighted discrete player summaries and full joint scenario matrices."""

from __future__ import annotations

from collections import defaultdict
from math import isfinite, sqrt

from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import (
    POINT_COMPONENT_NAMES,
    BpsBonusSummary,
    ComponentSummary,
    FixturePointScenario,
    JointScenarioMatrix,
    MonteCarloDiagnostics,
    PairDependence,
    PlayerProjectionSummary,
)

COMPONENTS = POINT_COMPONENT_NAMES

DEFAULT_QUANTILES = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)


def normalize_weights(weights: tuple[float, ...]) -> tuple[float, ...]:
    if not weights or any(not isfinite(weight) or weight <= 0.0 for weight in weights):
        raise FplPointsError("WEIGHTS_INVALID", "scenario weights must be positive")
    total = float(sum(weights))
    if not isfinite(total) or total <= 0.0:
        raise FplPointsError("WEIGHTS_INVALID", "scenario weights have no positive mass")
    return tuple(weight / total for weight in weights)


def weighted_mean(values: tuple[float, ...], weights: tuple[float, ...]) -> float:
    normalized = normalize_weights(weights)
    if len(values) != len(normalized):
        raise FplPointsError("WEIGHT_DIMENSION_MISMATCH", "values and weights do not align")
    return sum(value * weight for value, weight in zip(values, normalized, strict=True))


def weighted_variance(values: tuple[float, ...], weights: tuple[float, ...]) -> float:
    mean = weighted_mean(values, weights)
    normalized = normalize_weights(weights)
    return max(
        0.0,
        sum(weight * (value - mean) ** 2 for value, weight in zip(values, normalized, strict=True)),
    )


def weighted_covariance(
    left: tuple[float, ...], right: tuple[float, ...], weights: tuple[float, ...]
) -> float:
    if len(left) != len(right):
        raise FplPointsError("VALUE_DIMENSION_MISMATCH", "covariance vectors do not align")
    normalized = normalize_weights(weights)
    if len(left) != len(normalized):
        raise FplPointsError("WEIGHT_DIMENSION_MISMATCH", "values and weights do not align")
    left_mean = sum(value * weight for value, weight in zip(left, normalized, strict=True))
    right_mean = sum(value * weight for value, weight in zip(right, normalized, strict=True))
    return sum(
        weight * (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value, weight in zip(left, right, normalized, strict=True)
    )


def _pair_dependence(
    left: tuple[int, ...], right: tuple[int, ...], weights: tuple[float, ...]
) -> PairDependence:
    left_float = tuple(float(value) for value in left)
    right_float = tuple(float(value) for value in right)
    covariance = weighted_covariance(left_float, right_float, weights)
    left_variance = weighted_variance(left_float, weights)
    right_variance = weighted_variance(right_float, weights)
    if left_variance <= 1e-15 or right_variance <= 1e-15:
        reason = (
            "BOTH_PLAYERS_ZERO_VARIANCE"
            if left_variance <= 1e-15 and right_variance <= 1e-15
            else "LEFT_PLAYER_ZERO_VARIANCE"
            if left_variance <= 1e-15
            else "RIGHT_PLAYER_ZERO_VARIANCE"
        )
        return PairDependence(
            covariance=covariance,
            correlation=None,
            correlation_undefined_reason=reason,
        )
    correlation = covariance / sqrt(left_variance * right_variance)
    correlation = max(-1.0, min(1.0, correlation))
    return PairDependence(
        covariance=covariance,
        correlation=correlation,
        correlation_undefined_reason=None,
    )


def weighted_quantile(
    values: tuple[int, ...], weights: tuple[float, ...], probability: float
) -> int:
    """Weighted discrete inverse CDF: minimum x with F(x) >= probability."""

    if not 0.0 <= probability <= 1.0:
        raise FplPointsError("QUANTILE_INVALID", "quantile probability must be in [0,1]")
    normalized = normalize_weights(weights)
    if len(values) != len(normalized):
        raise FplPointsError("WEIGHT_DIMENSION_MISMATCH", "values and weights do not align")
    ordered = sorted(zip(values, normalized, strict=True), key=lambda item: item[0])
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative + 1e-15 >= probability:
            return value
    return ordered[-1][0]


def threshold_probability(
    values: tuple[int, ...], weights: tuple[float, ...], threshold: int
) -> float:
    normalized = normalize_weights(weights)
    return sum(
        weight for value, weight in zip(values, normalized, strict=True) if value >= threshold
    )


def _pmf(values: tuple[int, ...], weights: tuple[float, ...]) -> dict[int, float]:
    normalized = normalize_weights(weights)
    pmf: dict[int, float] = defaultdict(float)
    for value, weight in zip(values, normalized, strict=True):
        pmf[value] += weight
    return dict(sorted(pmf.items()))


def _quantile_key(probability: float) -> str:
    return f"p{round(probability * 100):02d}"


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
    player_scores: tuple[object, ...], weights: tuple[float, ...]
) -> dict[str, dict[str, float]]:
    vectors = {
        component: tuple(float(getattr(score, component)) for score in player_scores)
        for component in COMPONENTS
    }
    return {
        left: {
            right: weighted_covariance(vectors[left], vectors[right], weights)
            for right in COMPONENTS
        }
        for left in COMPONENTS
    }


def _bps_summary(
    scenarios: tuple[FixturePointScenario, ...], player_id: str, weights: tuple[float, ...]
) -> BpsBonusSummary:
    scores = tuple(scenario.players[player_id] for scenario in scenarios)
    bps = tuple(score.bps for score in scores)
    bonus = tuple(score.bonus for score in scores)
    ranks = tuple(score.bps_competition_rank for score in scores)
    normalized = normalize_weights(weights)
    valid_ranks = tuple(rank for rank in ranks if rank is not None)
    expected_rank = None
    if valid_ranks:
        expected_rank = sum(
            weight * float(rank)
            for rank, weight in zip(ranks, normalized, strict=True)
            if rank is not None
        ) / sum(weight for rank, weight in zip(ranks, normalized, strict=True) if rank is not None)
    modes = {scenario.bps_completeness_mode for scenario in scenarios}
    if len(modes) != 1:
        raise FplPointsError(
            "BPS_COMPLETENESS_MIXED", "one projection cannot mix BPS completeness modes"
        )
    mode = next(iter(modes))
    return BpsBonusSummary(
        expected_bps=weighted_mean(tuple(float(value) for value in bps), weights),
        bps_variance=weighted_variance(tuple(float(value) for value in bps), weights),
        bps_quantiles={
            _quantile_key(probability): weighted_quantile(bps, weights, probability)
            for probability in (0.10, 0.25, 0.50, 0.75, 0.90)
        },
        probability_bonus_0=sum(
            weight for value, weight in zip(bonus, normalized, strict=True) if value == 0
        ),
        probability_bonus_1=sum(
            weight for value, weight in zip(bonus, normalized, strict=True) if value == 1
        ),
        probability_bonus_2=sum(
            weight for value, weight in zip(bonus, normalized, strict=True) if value == 2
        ),
        probability_bonus_3=sum(
            weight for value, weight in zip(bonus, normalized, strict=True) if value == 3
        ),
        expected_bonus=weighted_mean(tuple(float(value) for value in bonus), weights),
        probability_any_bonus=sum(
            weight for value, weight in zip(bonus, normalized, strict=True) if value > 0
        ),
        expected_competition_rank=expected_rank,
        probability_rank_1=sum(
            weight for rank, weight in zip(ranks, normalized, strict=True) if rank == 1
        ),
        probability_rank_2=sum(
            weight for rank, weight in zip(ranks, normalized, strict=True) if rank == 2
        ),
        probability_rank_3=sum(
            weight for rank, weight in zip(ranks, normalized, strict=True) if rank == 3
        ),
        tie_probability=sum(
            weight
            for score, weight in zip(scores, normalized, strict=True)
            if score.bps_tied_at_rank
        ),
        completeness_mode=mode,
    )


def summarize_fixture_scenarios(
    scenarios: tuple[FixturePointScenario, ...],
    *,
    diagnostics: MonteCarloDiagnostics,
    quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
) -> dict[str, PlayerProjectionSummary]:
    if not scenarios:
        raise FplPointsError("SCENARIOS_EMPTY", "cannot summarize an empty scenario set")
    player_ids = tuple(sorted(scenarios[0].players))
    if any(tuple(sorted(scenario.players)) != player_ids for scenario in scenarios):
        raise FplPointsError(
            "PARTICIPANT_UNIVERSE_MISMATCH", "every scenario must retain the same player universe"
        )
    weights = tuple(scenario.weight for scenario in scenarios)
    normalized = normalize_weights(weights)
    ruleset_hashes = {scenario.ruleset.ruleset_hash for scenario in scenarios}
    upstream_hashes = {scenario.upstream_stage8_sha256 for scenario in scenarios}
    confidence_grades = {scenario.confidence_grade for scenario in scenarios}
    if len(ruleset_hashes) != 1 or len(upstream_hashes) != 1 or len(confidence_grades) != 1:
        raise FplPointsError(
            "SUMMARY_LINEAGE_MIXED",
            "one fixture summary cannot mix rulesets, upstreams, or confidence",
        )
    ruleset_hash = next(iter(ruleset_hashes))
    upstream_hash = next(iter(upstream_hashes))
    confidence_grade = next(iter(confidence_grades))
    model_version_ids = tuple(
        sorted({item for scenario in scenarios for item in scenario.model_version_ids})
    )
    dataset_version_ids = tuple(
        sorted({item for scenario in scenarios for item in scenario.dataset_version_ids})
    )
    source_bundle_ids = tuple(
        sorted({item for scenario in scenarios for item in scenario.source_bundle_ids})
    )
    summaries: dict[str, PlayerProjectionSummary] = {}
    for player_id in player_ids:
        player_scores = tuple(scenario.players[player_id] for scenario in scenarios)
        totals = tuple(score.total for score in player_scores)
        variance = weighted_variance(tuple(float(value) for value in totals), weights)
        components = {
            component: _component_summary(
                tuple(getattr(score, component) for score in player_scores), weights
            )
            for component in COMPONENTS
        }
        summaries[player_id] = PlayerProjectionSummary(
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
            component_breakdown=components,
            component_covariance=_component_covariance(player_scores, weights),
            bps_bonus=_bps_summary(scenarios, player_id, weights),
            monte_carlo_mean_se=diagnostics.mean_mcse_by_player[player_id],
            threshold_probability_se=diagnostics.threshold_probability_se_by_player[player_id],
            scenario_effective_sample_size=diagnostics.effective_sample_size,
            confidence_grade=confidence_grade,
            ruleset_hash=ruleset_hash,
            model_version_ids=model_version_ids,
            dataset_version_ids=dataset_version_ids,
            source_bundle_ids=source_bundle_ids,
            upstream_stage8_sha256=upstream_hash,
        )
    return summaries


def build_joint_matrix(scenarios: tuple[FixturePointScenario, ...]) -> JointScenarioMatrix:
    if not scenarios:
        raise FplPointsError("SCENARIOS_EMPTY", "cannot build a matrix from no scenarios")
    player_ids = tuple(sorted(scenarios[0].players))
    if any(tuple(sorted(scenario.players)) != player_ids for scenario in scenarios):
        raise FplPointsError(
            "PARTICIPANT_UNIVERSE_MISMATCH", "scenario player mappings are not one-to-one"
        )
    ruleset_hashes = {scenario.ruleset.ruleset_hash for scenario in scenarios}
    if len(ruleset_hashes) != 1:
        raise FplPointsError("RULESET_MIXED", "joint matrix cannot mix rulesets")
    weights = normalize_weights(tuple(scenario.weight for scenario in scenarios))
    return JointScenarioMatrix(
        scenario_ids=tuple(scenario.scenario_id for scenario in scenarios),
        outcome_draw_ids=tuple(scenario.outcome_draw_id for scenario in scenarios),
        player_ids=player_ids,
        weights=weights,
        points=tuple(
            tuple(scenario.players[player_id].total for player_id in player_ids)
            for scenario in scenarios
        ),
        ruleset_hash=next(iter(ruleset_hashes)),
        dependence={
            left: {
                right: _pair_dependence(
                    tuple(scenario.players[left].total for scenario in scenarios),
                    tuple(scenario.players[right].total for scenario in scenarios),
                    tuple(scenario.weight for scenario in scenarios),
                )
                for right in player_ids
            }
            for left in player_ids
        },
    )
