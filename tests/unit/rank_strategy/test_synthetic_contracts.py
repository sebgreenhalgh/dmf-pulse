from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.rank_strategy.models import SampleRightsStatus
from dmf_pulse.rank_strategy.synthetic_models import (
    SyntheticBandSelectionBasis,
    SyntheticOverallDistribution,
    SyntheticOverallPopulation,
    SyntheticOverallRankResult,
    SyntheticRankBand,
)
from tests.support.rank_strategy_fixtures import manager_plan
from tests.support.synthetic_field_fixtures import (
    rank_band,
    representative,
    seal_population,
    tiny_known_truth_population,
)

pytestmark = pytest.mark.unit


def test_known_truth_population_is_sealed_and_carries_rights_lineage() -> None:
    population = tiny_known_truth_population()
    assert population.rights_status is SampleRightsStatus.SYNTHETIC_APPROVED
    assert population.known_truth is True
    assert population.mass_scrape_used is False
    assert population.final_rank_hindsight_used is False
    assert population.definitive_overall_win_model is False
    assert population.provenance_ids == ("fixture:tiny-known-truth-field",)
    assert population.source_bundle_ids == ("source:synthetic-rank-stage15",)
    assert population.upstream_hashes == ("4" * 64,)
    assert population.total_population_count == 5


def test_population_rejects_unsealed_or_mutated_payload() -> None:
    population = tiny_known_truth_population()
    payload = population.model_dump(mode="python")
    payload["population_hash"] = "9" * 64
    with pytest.raises(ValidationError, match="population hash"):
        SyntheticOverallPopulation.model_validate(payload)


def test_population_rejects_empty_lineage_identifiers() -> None:
    population = tiny_known_truth_population()
    payload = {
        field_name: getattr(population, field_name)
        for field_name in type(population).model_fields
        if field_name != "population_hash"
    }
    payload["provenance_ids"] = ("",)
    with pytest.raises(ValidationError, match="at least 1 character"):
        seal_population(**payload)


def test_named_rival_rights_cannot_authorise_overall_population() -> None:
    with pytest.raises(ValidationError, match="synthetic or repository-approved rights"):
        tiny_known_truth_population(
            rights_status=SampleRightsStatus.NAMED_RIVAL_AUTHORISED,
        )


def test_repository_population_requires_repository_selection_basis() -> None:
    bands = (
        rank_band(
            "band-a",
            1,
            2,
            representative(
                "rep-a",
                manager_plan("rival-a", cumulative_points=100),
                2,
            ),
            selection_basis=SyntheticBandSelectionBasis.REPOSITORY_APPROVED_SAMPLE,
        ),
    )
    population = tiny_known_truth_population(
        bands=bands,
        rights_status=SampleRightsStatus.REPOSITORY_APPROVED,
        known_truth=False,
    )
    assert population.rights_status is SampleRightsStatus.REPOSITORY_APPROVED
    assert population.known_truth is False


def test_repository_population_cannot_relabel_synthetic_generator() -> None:
    with pytest.raises(ValidationError, match="cannot relabel"):
        tiny_known_truth_population(
            rights_status=SampleRightsStatus.REPOSITORY_APPROVED,
            known_truth=False,
        )


def test_band_counts_rank_ranges_and_target_identity_are_strict() -> None:
    band_payload = rank_band(
        "band-a",
        1,
        2,
        representative("rep-a", manager_plan("rival-a"), 2),
    ).model_dump(mode="python")
    band_payload["population_count"] = 3
    with pytest.raises(ValidationError, match="counts must reconcile"):
        SyntheticRankBand.model_validate(band_payload)

    target = manager_plan("sebastian")
    duplicate_target_band = rank_band(
        "band-a",
        1,
        2,
        representative("rep-a", target, 1),
    )
    with pytest.raises(ValidationError, match="target manager cannot be duplicated"):
        tiny_known_truth_population(target_plan=target, bands=(duplicate_target_band,))


def test_result_and_distribution_hashes_are_mandatory() -> None:
    from dmf_pulse.rank_strategy.synthetic_field import simulate_synthetic_overall_rank
    from tests.support.rank_strategy_fixtures import rank_tie_policy, scenario_set
    from tests.support.synthetic_field_fixtures import multiplier_sets_for_population

    population = tiny_known_truth_population()
    scenarios = scenario_set()
    result = simulate_synthetic_overall_rank(
        population,
        multiplier_sets_for_population(population, scenarios),
        rank_tie_policy(),
        target_rank=3,
    )
    assert result.distribution.population_hash == population.population_hash
    assert result.distribution.target_manager_id in (
        result.distribution.manager_multiplier_set_hashes
    )
    assert tuple(result.distribution.manager_multiplier_set_hashes) == tuple(
        sorted(result.distribution.manager_multiplier_set_hashes)
    )
    assert result.distribution.tie_policy_hash != "0" * 64

    distribution_payload = result.distribution.model_dump(mode="python")
    distribution_payload["distribution_hash"] = "8" * 64
    with pytest.raises(ValidationError, match="distribution hash"):
        SyntheticOverallDistribution.model_validate(distribution_payload)

    result_payload = result.model_dump(mode="json")
    result_payload["result_hash"] = "7" * 64
    with pytest.raises(ValidationError, match="result hash"):
        SyntheticOverallRankResult.model_validate(result_payload)


def test_distribution_and_result_lineage_bindings_fail_closed() -> None:
    from dmf_pulse.rank_strategy.synthetic_field import simulate_synthetic_overall_rank
    from tests.support.rank_strategy_fixtures import rank_tie_policy, scenario_set
    from tests.support.synthetic_field_fixtures import multiplier_sets_for_population

    population = tiny_known_truth_population()
    result = simulate_synthetic_overall_rank(
        population,
        multiplier_sets_for_population(population, scenario_set()),
        rank_tie_policy(),
    )

    distribution_payload = result.distribution.model_dump(mode="python")
    distribution_payload["manager_multiplier_set_hashes"] = {
        manager_id: value
        for manager_id, value in distribution_payload["manager_multiplier_set_hashes"].items()
        if manager_id != result.distribution.target_manager_id
    }
    distribution_payload["distribution_hash"] = semantic_sha256(
        {key: value for key, value in distribution_payload.items() if key != "distribution_hash"}
    )
    with pytest.raises(ValidationError, match="target manager is missing"):
        SyntheticOverallDistribution.model_validate(distribution_payload)

    result_payload = result.model_dump(mode="json")
    result_payload["population_hash"] = "9" * 64
    result_payload["result_hash"] = semantic_sha256(
        {key: value for key, value in result_payload.items() if key != "result_hash"}
    )
    with pytest.raises(ValidationError, match="population hash does not match"):
        SyntheticOverallRankResult.model_validate(result_payload)
