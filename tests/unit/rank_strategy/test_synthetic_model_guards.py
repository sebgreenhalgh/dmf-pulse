from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import inf

import pytest

from dmf_pulse.rank_strategy.models import RankMass, SampleRightsStatus
from dmf_pulse.rank_strategy.synthetic_field import simulate_synthetic_overall_rank
from dmf_pulse.rank_strategy.synthetic_models import (
    SyntheticApproximationStatus,
    SyntheticBandScenarioCount,
    SyntheticBandSelectionBasis,
    SyntheticOverallRankResult,
)
from tests.support.rank_strategy_fixtures import manager_plan, rank_tie_policy, scenario_set
from tests.support.synthetic_field_fixtures import (
    multiplier_sets_for_population,
    rank_band,
    representative,
    tiny_known_truth_population,
)

pytestmark = pytest.mark.unit


def _result() -> SyntheticOverallRankResult:
    population = tiny_known_truth_population()
    scenarios = scenario_set()
    return simulate_synthetic_overall_rank(
        population,
        multiplier_sets_for_population(population, scenarios),
        rank_tie_policy(),
        target_rank=3,
    )


def test_rank_band_rejects_inverted_range_and_noncanonical_representatives() -> None:
    population = tiny_known_truth_population()
    band = population.bands[1]

    inverted = band.model_copy(update={"best_rank": band.worst_rank + 1})
    with pytest.raises(ValueError, match="best rank cannot exceed"):
        inverted.band_is_canonical()

    reversed_representatives = band.model_copy(
        update={"representatives": tuple(reversed(band.representatives))}
    )
    with pytest.raises(ValueError, match="sorted and unique"):
        reversed_representatives.band_is_canonical()

    duplicate_manager = band.model_copy(
        update={
            "representatives": (
                band.representatives[0],
                band.representatives[1].model_copy(
                    update={"manager_plan": band.representatives[0].manager_plan}
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="manager IDs must be unique"):
        duplicate_manager.band_is_canonical()


def test_population_rejects_invalid_time_and_lineage_ordering() -> None:
    population = tiny_known_truth_population()

    naive = population.model_copy(update={"generated_at": datetime(2026, 8, 20, 10)})
    with pytest.raises(ValueError, match="generated_at must be timezone-aware UTC"):
        naive.population_is_canonical()

    non_utc = population.model_copy(
        update={
            "information_cutoff": datetime(2026, 8, 20, 12, tzinfo=timezone(timedelta(hours=1)))
        }
    )
    with pytest.raises(ValueError, match="information_cutoff must be timezone-aware UTC"):
        non_utc.population_is_canonical()

    generated_late = population.model_copy(
        update={"generated_at": population.information_cutoff + timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="cannot be generated after"):
        generated_late.population_is_canonical()

    unsorted_lineage = population.model_copy(update={"provenance_ids": ("z", "a")})
    with pytest.raises(ValueError, match="provenance IDs must be sorted and unique"):
        unsorted_lineage.population_is_canonical()


def test_population_rejects_band_overlap_bounds_and_cross_band_duplicates() -> None:
    population = tiny_known_truth_population()
    first, second = population.bands

    unsorted = population.model_copy(update={"bands": (second, first)})
    with pytest.raises(ValueError, match="rank bands must be sorted and unique"):
        unsorted.population_is_canonical()

    overlap = population.model_copy(
        update={"bands": (first, second.model_copy(update={"best_rank": first.worst_rank}))}
    )
    with pytest.raises(ValueError, match="cannot overlap"):
        overlap.population_is_canonical()

    outside = population.model_copy(
        update={"bands": (first, second.model_copy(update={"worst_rank": 6}))}
    )
    with pytest.raises(ValueError, match="outside the represented population"):
        outside.population_is_canonical()

    duplicate_rep_id = second.model_copy(
        update={
            "representatives": (
                second.representatives[0].model_copy(
                    update={"representative_id": first.representatives[0].representative_id}
                ),
                second.representatives[1],
            )
        }
    )
    duplicate_representative_population = population.model_copy(
        update={"bands": (first, duplicate_rep_id)}
    )
    with pytest.raises(ValueError, match="IDs must be unique across bands"):
        duplicate_representative_population.population_is_canonical()

    duplicate_manager = second.model_copy(
        update={
            "representatives": (
                second.representatives[0].model_copy(
                    update={"manager_plan": first.representatives[0].manager_plan}
                ),
                second.representatives[1],
            )
        }
    )
    duplicate_manager_population = population.model_copy(
        update={"bands": (first, duplicate_manager)}
    )
    with pytest.raises(ValueError, match="manager IDs must be unique across bands"):
        duplicate_manager_population.population_is_canonical()


def test_population_rejects_count_rights_basis_and_truth_mismatch() -> None:
    population = tiny_known_truth_population()

    wrong_total = population.model_copy(update={"total_population_count": 6})
    with pytest.raises(ValueError, match="total population must include target once"):
        wrong_total.population_is_canonical()

    repository_band = rank_band(
        "band-a",
        1,
        2,
        representative("rep-a", manager_plan("rival-a"), 2),
        selection_basis=SyntheticBandSelectionBasis.REPOSITORY_APPROVED_SAMPLE,
    )
    wrong_synthetic_basis = population.model_copy(
        update={"bands": (repository_band,), "total_population_count": 3}
    )
    with pytest.raises(ValueError, match="must use synthetic generators only"):
        wrong_synthetic_basis.population_is_canonical()

    repository_known_truth = population.model_copy(
        update={
            "rights_status": SampleRightsStatus.REPOSITORY_APPROVED,
            "known_truth": True,
            "bands": tuple(
                band.model_copy(
                    update={
                        "selection_basis": SyntheticBandSelectionBasis.REPOSITORY_APPROVED_SAMPLE
                    }
                )
                for band in population.bands
            ),
        }
    )
    with pytest.raises(ValueError, match="known-truth overall populations"):
        repository_known_truth.population_is_canonical()


def test_population_diagnostics_reject_nonfinite_counts_and_truth_mismatch() -> None:
    diagnostics = _result().diagnostics

    nonfinite = diagnostics.model_copy(update={"effective_representative_count": inf})
    with pytest.raises(ValueError, match="must be finite"):
        nonfinite.diagnostics_are_finite()

    semantic_exceeds_input = diagnostics.model_copy(
        update={"semantic_representative_count": diagnostics.input_representative_count + 1}
    )
    with pytest.raises(ValueError, match="cannot exceed input count"):
        semantic_exceeds_input.diagnostics_are_finite()

    wrong_status = diagnostics.model_copy(
        update={
            "approximation_status": (
                SyntheticApproximationStatus.WEIGHTED_REPRESENTATIVE_APPROXIMATION
            )
        }
    )
    with pytest.raises(ValueError, match="does not match truth label"):
        wrong_status.diagnostics_are_finite()


def test_band_scenario_count_rejects_population_overrun() -> None:
    count = SyntheticBandScenarioCount(
        band_id="band-a",
        population_count=2,
        managers_strictly_ahead=1,
        managers_exactly_tied=1,
    )
    invalid = count.model_copy(update={"managers_exactly_tied": 2})
    with pytest.raises(ValueError, match="exceed represented population"):
        invalid.counts_fit_band()


def test_scenario_outcome_rejects_rank_band_and_count_mismatch() -> None:
    outcome = _result().distribution.outcomes[0]

    wrong_rank = outcome.model_copy(update={"rank": outcome.rank + 1})
    with pytest.raises(ValueError, match="one plus managers strictly ahead"):
        wrong_rank.rank_reconciles()

    reversed_bands = outcome.model_copy(
        update={"band_counts": tuple(reversed(outcome.band_counts))}
    )
    with pytest.raises(ValueError, match="band counts must be sorted and unique"):
        reversed_bands.rank_reconciles()

    wrong_ahead = outcome.model_copy(
        update={
            "managers_strictly_ahead": outcome.managers_strictly_ahead + 1,
            "rank": outcome.rank + 1,
        }
    )
    with pytest.raises(ValueError, match="ahead count must reconcile"):
        wrong_ahead.rank_reconciles()

    wrong_tied = outcome.model_copy(update={"managers_exactly_tied": 1})
    with pytest.raises(ValueError, match="tied count must reconcile"):
        wrong_tied.rank_reconciles()


def test_distribution_rejects_lineage_pmf_and_population_mismatch() -> None:
    distribution = _result().distribution

    empty_lineage = distribution.model_copy(update={"manager_multiplier_set_hashes": {}})
    with pytest.raises(ValueError, match="sorted non-empty manager IDs"):
        empty_lineage.distribution_is_canonical()

    reversed_lineage = distribution.model_copy(
        update={
            "manager_multiplier_set_hashes": dict(
                reversed(tuple(distribution.manager_multiplier_set_hashes.items()))
            )
        }
    )
    with pytest.raises(ValueError, match="sorted non-empty manager IDs"):
        reversed_lineage.distribution_is_canonical()

    duplicate_rank = distribution.model_copy(
        update={"rank_pmf": (distribution.rank_pmf[0], distribution.rank_pmf[0])}
    )
    with pytest.raises(ValueError, match="sorted by unique rank"):
        duplicate_rank.distribution_is_canonical()

    outside_rank = distribution.model_copy(
        update={"rank_pmf": (RankMass(rank=6, probability=1.0),)}
    )
    with pytest.raises(ValueError, match="rank outside the population"):
        outside_rank.distribution_is_canonical()

    bad_mass = distribution.model_copy(update={"rank_pmf": (RankMass(rank=3, probability=0.5),)})
    with pytest.raises(ValueError, match="probabilities must sum to one"):
        bad_mass.distribution_is_canonical()

    bad_expected = distribution.model_copy(
        update={"expected_rank": distribution.expected_rank + 1.0}
    )
    with pytest.raises(ValueError, match="expected rank does not reconcile"):
        bad_expected.distribution_is_canonical()


def test_distribution_rejects_percentile_target_and_rank_one_mismatch() -> None:
    distribution = _result().distribution

    bad_percentiles = distribution.model_copy(
        update={"rank_percentiles": {"p25": 3, "p10": 3, "p50": 3, "p75": 3, "p90": 3}}
    )
    with pytest.raises(ValueError, match="canonical keys"):
        bad_percentiles.distribution_is_canonical()

    target_outside = distribution.model_copy(
        update={"target_rank": distribution.population_size + 1}
    )
    with pytest.raises(ValueError, match="target rank lies outside"):
        target_outside.distribution_is_canonical()

    bad_target_probability = distribution.model_copy(update={"probability_target_rank": 0.0})
    with pytest.raises(ValueError, match="target probability must be derived"):
        bad_target_probability.distribution_is_canonical()

    bad_rank_one = distribution.model_copy(update={"overall_rank_one_probability": 1.0})
    with pytest.raises(ValueError, match="rank-one probability must equal PMF mass"):
        bad_rank_one.distribution_is_canonical()


def test_distribution_rejects_outcome_order_weight_rank_and_pmf_mismatch() -> None:
    distribution = _result().distribution
    outcome = distribution.outcomes[0]

    duplicate_outcomes = distribution.model_copy(update={"outcomes": (outcome, outcome)})
    with pytest.raises(ValueError, match="outcomes must be sorted and unique"):
        duplicate_outcomes.distribution_is_canonical()

    bad_weight_outcome = outcome.model_copy(update={"weight": 0.5})
    bad_weight = distribution.model_copy(update={"outcomes": (bad_weight_outcome,)})
    with pytest.raises(ValueError, match="outcome weights must sum to one"):
        bad_weight.distribution_is_canonical()

    outside_outcome = outcome.model_copy(
        update={
            "rank": distribution.population_size + 1,
            "managers_strictly_ahead": distribution.population_size,
        }
    )
    bad_outcome_rank = distribution.model_copy(update={"outcomes": (outside_outcome,)})
    with pytest.raises(ValueError, match="scenario rank lies outside"):
        bad_outcome_rank.distribution_is_canonical()

    changed_outcome = outcome.model_copy(update={"rank": 2, "managers_strictly_ahead": 1})
    pmf_mismatch = distribution.model_copy(update={"outcomes": (changed_outcome,)})
    with pytest.raises(ValueError, match="PMF must be derived"):
        pmf_mismatch.distribution_is_canonical()


def test_result_rejects_cutoff_rights_lineage_population_and_truth_mismatch() -> None:
    result = _result()

    naive = result.model_copy(update={"information_cutoff": datetime(2026, 8, 20, 12)})
    with pytest.raises(ValueError, match="cutoff must be timezone-aware UTC"):
        naive.result_is_canonical()

    rights_invalid = result.model_copy(update={"rights_status": SampleRightsStatus.UNKNOWN})
    with pytest.raises(ValueError, match="rights are not permitted"):
        rights_invalid.result_is_canonical()

    unsorted_lineage = result.model_copy(update={"source_bundle_ids": ("z", "a")})
    with pytest.raises(ValueError, match="source bundle IDs must be sorted and unique"):
        unsorted_lineage.result_is_canonical()

    wrong_population = result.model_copy(
        update={
            "diagnostics": result.diagnostics.model_copy(
                update={
                    "represented_manager_count": result.diagnostics.represented_manager_count + 1
                }
            )
        }
    )
    with pytest.raises(ValueError, match="population does not reconcile"):
        wrong_population.result_is_canonical()

    truth_mismatch = result.model_copy(
        update={
            "diagnostics": result.diagnostics.model_copy(
                update={
                    "approximation_status": (
                        SyntheticApproximationStatus.WEIGHTED_REPRESENTATIVE_APPROXIMATION
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError, match="truth diagnostics do not reconcile"):
        truth_mismatch.result_is_canonical()
