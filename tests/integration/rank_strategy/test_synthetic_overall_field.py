from __future__ import annotations

import pytest

from dmf_pulse.rank_strategy.rank_utility import evaluate_rank_strategy
from dmf_pulse.rank_strategy.synthetic_field import simulate_synthetic_overall_rank
from dmf_pulse.rank_strategy.synthetic_models import SyntheticApproximationStatus
from dmf_pulse.rank_strategy.utility_models import (
    RankActivationStatus,
    RankDistributionScope,
    RankObjectiveMode,
    RankPlanCandidate,
    RankTargetDefinition,
)
from tests.support.rank_strategy_fixtures import manager_plan, rank_tie_policy, scenario_set
from tests.support.rank_utility_fixtures import candidate, context, policy
from tests.support.synthetic_field_fixtures import (
    multiplier_sets_for_population,
    tiny_known_truth_population,
)
from tests.support.synthetic_field_oracle import exhaustive_synthetic_field_oracle

pytestmark = pytest.mark.integration


def _point_map(**overrides: int) -> dict[str, int]:
    values = {f"p{index:02d}": 2 for index in range(15)}
    values.update(overrides)
    return values


def _candidate_with_distribution(
    plan_id: str,
    expected_points: float,
    distribution,
) -> RankPlanCandidate:
    payload = candidate(
        plan_id,
        expected_points,
        None,
        raw_hash=distribution.raw_projection_hash,
        scenario_hash=distribution.scenario_set_hash,
    ).model_dump(mode="python")
    payload["rank_distribution"] = distribution
    return RankPlanCandidate.model_validate(payload)


def test_tiny_synthetic_field_matches_independent_exhaustive_oracle() -> None:
    population = tiny_known_truth_population()
    scenarios = scenario_set(
        _point_map(p12=12, p13=2, p14=5),
        _point_map(p12=2, p13=12, p14=5),
        _point_map(p12=3, p13=4, p14=13),
        weights=(0.25, 0.35, 0.40),
    )
    multiplier_sets = multiplier_sets_for_population(population, scenarios)
    result = simulate_synthetic_overall_rank(
        population,
        multiplier_sets,
        rank_tie_policy(),
        target_rank=3,
    )
    oracle = exhaustive_synthetic_field_oracle(
        population,
        multiplier_sets,
        target_rank=3,
    )

    assert (
        tuple((item.rank, item.probability) for item in result.distribution.rank_pmf)
        == oracle["pmf"]
    )
    assert result.distribution.expected_rank == pytest.approx(oracle["expected_rank"])
    assert result.distribution.probability_target_rank == pytest.approx(
        oracle["probability_target_rank"]
    )
    assert result.distribution.overall_rank_one_probability == pytest.approx(
        oracle["rank_one_probability"]
    )
    assert [item.model_dump(mode="json") for item in result.distribution.outcomes] == (
        oracle["outcomes"]
    )
    diagnostics = oracle["diagnostics"]
    assert result.diagnostics.represented_manager_count == diagnostics["represented_manager_count"]
    assert (
        result.diagnostics.input_representative_count == diagnostics["input_representative_count"]
    )
    assert (
        result.diagnostics.semantic_representative_count
        == diagnostics["semantic_representative_count"]
    )
    assert result.diagnostics.effective_representative_count == pytest.approx(
        diagnostics["effective_representative_count"]
    )
    assert result.diagnostics.maximum_representative_population_share == pytest.approx(
        diagnostics["maximum_representative_population_share"]
    )
    assert result.diagnostics.band_population_entropy == pytest.approx(
        diagnostics["band_population_entropy"]
    )
    assert (
        result.diagnostics.approximation_status
        is SyntheticApproximationStatus.KNOWN_TRUTH_EXHAUSTIVE
    )


def test_target_probability_exactly_reconciles_with_overall_rank_pmf() -> None:
    population = tiny_known_truth_population()
    scenarios = scenario_set(
        _point_map(p12=9, p13=1, p14=2),
        _point_map(p12=1, p13=9, p14=2),
        weights=(0.4, 0.6),
    )
    result = simulate_synthetic_overall_rank(
        population,
        multiplier_sets_for_population(population, scenarios),
        rank_tie_policy(),
        target_rank=2,
    )
    expected = sum(item.probability for item in result.distribution.rank_pmf if item.rank <= 2)
    assert result.distribution.probability_target_rank == expected
    assert sum(item.probability for item in result.distribution.rank_pmf) == pytest.approx(1.0)
    assert sum(item.weight for item in result.distribution.outcomes) == pytest.approx(1.0)


def test_synthetic_overall_distribution_feeds_target_rank_utility_without_win_mislabel() -> None:
    scenarios = scenario_set(
        _point_map(p12=12, p13=1, p14=3),
        _point_map(p12=1, p13=12, p14=3),
        weights=(0.5, 0.5),
    )
    points_population = tiny_known_truth_population(
        target_plan=manager_plan(
            "sebastian",
            captain="p13",
            vice="p14",
            cumulative_points=100,
            counted_transfers=5,
        )
    )
    rank_population = tiny_known_truth_population(
        target_plan=manager_plan(
            "sebastian",
            captain="p12",
            vice="p14",
            cumulative_points=100,
            counted_transfers=5,
        )
    )
    points_distribution = simulate_synthetic_overall_rank(
        points_population,
        multiplier_sets_for_population(points_population, scenarios),
        rank_tie_policy(),
        target_rank=1,
    ).distribution
    rank_distribution = simulate_synthetic_overall_rank(
        rank_population,
        multiplier_sets_for_population(rank_population, scenarios),
        rank_tie_policy(),
        target_rank=1,
    ).distribution

    result = evaluate_rank_strategy(
        request_id="synthetic-target-rank-utility",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=(
            _candidate_with_distribution("points", 60.0, points_distribution),
            _candidate_with_distribution("rank", 59.8, rank_distribution),
        ),
        context=context(),
        policy=policy(material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )

    assert result.activation_status is RankActivationStatus.ACTIVE
    assert result.selected_plan_id == "rank"
    assert result.rank_optimal_metrics.distribution_scope is (
        RankDistributionScope.SYNTHETIC_OVERALL_APPROXIMATION
    )
    assert result.rank_optimal_metrics.overall_rank_one_probability == pytest.approx(0.5)
    assert result.rank_optimal_metrics.mini_league_win_probability is None
    assert result.rank_optimal_metrics.approximation_only is True


def test_synthetic_overall_distribution_cannot_activate_mini_league_win_objective() -> None:
    population = tiny_known_truth_population()
    scenarios = scenario_set()
    distribution = simulate_synthetic_overall_rank(
        population,
        multiplier_sets_for_population(population, scenarios),
        rank_tie_policy(),
        target_rank=1,
    ).distribution
    result = evaluate_rank_strategy(
        request_id="synthetic-not-mini-league",
        objective=RankObjectiveMode.MINI_LEAGUE_WIN,
        candidates=(_candidate_with_distribution("points", 60.0, distribution),),
        context=context(),
        policy=policy(),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.activation_status is RankActivationStatus.DIAGNOSTIC_ONLY
    assert result.effective_objective is RankObjectiveMode.PURE_POINTS
    assert "EXACT_MINI_LEAGUE_DISTRIBUTION_REQUIRED" in result.fallback_reasons
    assert result.points_optimal_metrics.mini_league_win_probability is None
    assert result.points_optimal_metrics.overall_rank_one_probability is not None
