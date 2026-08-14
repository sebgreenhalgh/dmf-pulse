from __future__ import annotations

import math

import pytest

import dmf_pulse.fpl_points.summaries as summaries_module
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.monte_carlo import effective_sample_size, monte_carlo_diagnostics
from dmf_pulse.fpl_points.service import FplPointsService, generate_fixture_scenarios
from dmf_pulse.fpl_points.summaries import (
    build_joint_matrix,
    normalize_weights,
    summarize_fixture_scenarios,
    threshold_probability,
    weighted_covariance,
    weighted_mean,
    weighted_quantile,
    weighted_variance,
)
from tests.support.factories import (
    A_FWD,
    RULESET_HASH,
    make_request,
    mc_policy,
    reference_engine,
)


def test_weighted_moments_quantile_threshold_and_ess() -> None:
    values = (0.0, 2.0, 10.0)
    weights = (1.0, 2.0, 1.0)
    assert normalize_weights(weights) == (0.25, 0.5, 0.25)
    assert weighted_mean(values, weights) == 3.5
    assert weighted_variance(values, weights) == 14.75
    assert weighted_quantile((0, 2, 10), weights, 0.5) == 2
    assert threshold_probability((0, 2, 10), weights, 5) == 0.25
    assert effective_sample_size(weights) == pytest_approx(8 / 3)
    assert weighted_covariance(values, values, weights) == 14.75


def test_weighted_helpers_reject_nonfinite_and_misaligned_inputs() -> None:
    for weights in ((), (0.0,), (math.nan,), (math.inf,), (1e308, 1e308)):
        with pytest.raises(FplPointsError, match="weights"):
            normalize_weights(weights)
    with pytest.raises(FplPointsError, match="values and weights"):
        weighted_mean((1.0,), (1.0, 1.0))
    with pytest.raises(FplPointsError, match="covariance vectors"):
        weighted_covariance((1.0,), (1.0, 2.0), (1.0,))
    with pytest.raises(FplPointsError, match="values and weights"):
        weighted_covariance((1.0,), (2.0,), (1.0, 1.0))
    with pytest.raises(FplPointsError, match="quantile probability"):
        weighted_quantile((1,), (1.0,), 1.1)
    with pytest.raises(FplPointsError, match="values and weights"):
        weighted_quantile((1,), (1.0, 1.0), 0.5)


def test_dependence_reasons_cover_one_sided_zero_variance() -> None:
    left = summaries_module._pair_dependence((1, 1), (1, 2), (0.5, 0.5))
    right = summaries_module._pair_dependence((1, 2), (1, 1), (0.5, 0.5))
    varying = summaries_module._pair_dependence((1, 2), (2, 4), (0.5, 0.5))
    assert left.correlation_undefined_reason == "LEFT_PLAYER_ZERO_VARIANCE"
    assert right.correlation_undefined_reason == "RIGHT_PLAYER_ZERO_VARIANCE"
    assert varying.correlation == pytest.approx(1.0)


def test_summary_and_matrix_reject_empty_scenario_sets() -> None:
    with pytest.raises(FplPointsError, match="empty scenario"):
        summarize_fixture_scenarios((), diagnostics=None)  # type: ignore[arg-type]
    with pytest.raises(FplPointsError, match="no scenarios"):
        build_joint_matrix(())


def pytest_approx(value: float, tolerance: float = 1e-12):
    class Approx:
        def __eq__(self, other: object) -> bool:
            return isinstance(other, (int, float)) and math.isclose(
                float(other), value, abs_tol=tolerance
            )

    return Approx()


def test_fixture_summary_retains_pmf_thresholds_covariance_and_lineage() -> None:
    result = FplPointsService(reference_engine(), mc_policy()).project(
        make_request(scenario_count=64)
    )
    assert result.status.value == "SUCCESS"
    for summary in result.player_summaries.values():
        assert math.isclose(sum(summary.pmf.values()), 1.0, abs_tol=1e-10)
        assert (
            summary.probability_15_plus <= summary.probability_10_plus <= summary.probability_5_plus
        )
        quantiles = [
            summary.selected_percentiles[key]
            for key in ("p01", "p05", "p10", "p25", "p50", "p75", "p90", "p95", "p99")
        ]
        assert quantiles == sorted(quantiles)
        assert set(summary.component_covariance) == set(summary.component_breakdown)
        assert summary.ruleset_hash == RULESET_HASH
        assert summary.upstream_stage8_sha256 == result.upstream_stage8_sha256
        assert summary.scenario_effective_sample_size == 64


def test_joint_matrix_has_deterministic_mapping_and_null_correlation_reason() -> None:
    scenarios = generate_fixture_scenarios(
        make_request(scenario_count=8), reference_engine(), range(8)
    )
    matrix = build_joint_matrix(scenarios)
    assert matrix.player_ids == tuple(sorted(matrix.player_ids))
    assert len(matrix.points) == 8
    assert all(len(row) == len(matrix.player_ids) for row in matrix.points)
    zero_player = A_FWD
    pair = matrix.dependence[zero_player][zero_player]
    assert pair.covariance == 0.0
    assert pair.correlation is None
    assert pair.correlation_undefined_reason == "BOTH_PLAYERS_ZERO_VARIANCE"


def test_mc_diagnostics_are_separate_and_fail_precision_gate_when_under_sampled() -> None:
    scenarios = generate_fixture_scenarios(
        make_request(scenario_count=8), reference_engine(), range(8)
    )
    diagnostics = monte_carlo_diagnostics(
        scenarios,
        mc_policy(minimum_effective_scenarios=1000, maximum_mean_mcse=0.0001),
    )
    assert diagnostics.scenario_count == 8
    assert diagnostics.effective_sample_size == 8
    assert diagnostics.stopping_result == "CONTINUE"
    assert "ESS_BELOW_THRESHOLD" in diagnostics.stopping_reasons
    assert diagnostics.max_scenario_weight == 0.125
