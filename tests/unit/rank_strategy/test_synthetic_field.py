from __future__ import annotations

from collections.abc import Iterable

import pytest

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.models import ManagerMultiplierSet, SampleRightsStatus
from dmf_pulse.rank_strategy.synthetic_field import simulate_synthetic_overall_rank
from dmf_pulse.rank_strategy.synthetic_models import (
    SyntheticApproximationStatus,
    SyntheticOverallPopulation,
)
from tests.support.rank_strategy_fixtures import (
    manager_plan,
    rank_tie_policy,
    scenario_set,
)
from tests.support.synthetic_field_fixtures import (
    multiplier_sets_for_population,
    rank_band,
    representative,
    tiny_known_truth_population,
)

pytestmark = pytest.mark.unit


def _point_map(**overrides: int) -> dict[str, int]:
    values = {f"p{index:02d}": 2 for index in range(15)}
    values.update(overrides)
    return values


def _reseal_multiplier_set(value: ManagerMultiplierSet) -> ManagerMultiplierSet:
    payload = value.model_dump(mode="python", exclude={"multiplier_set_hash"})
    semantic_payload = value.model_dump(mode="json", exclude={"multiplier_set_hash"})
    return ManagerMultiplierSet(
        **payload,
        multiplier_set_hash=semantic_sha256(semantic_payload),
    )


def _invalid_constructed_population(
    population,
    **updates,
) -> SyntheticOverallPopulation:
    payload = {
        field_name: getattr(population, field_name)
        for field_name in type(population).model_fields
        if field_name != "population_hash"
    }
    payload.update(updates)
    unsealed = SyntheticOverallPopulation.model_construct(
        **payload,
        population_hash="0" * 64,
    )
    semantic_payload = unsealed.model_dump(mode="json", exclude={"population_hash"})
    return SyntheticOverallPopulation.model_construct(
        **payload,
        population_hash=semantic_sha256(semantic_payload),
    )


def _sets_by_id(values: Iterable[ManagerMultiplierSet]) -> dict[str, ManagerMultiplierSet]:
    return {item.manager_id: item for item in values}


def test_weighted_field_uses_cumulative_points_and_counted_transfer_tie_state() -> None:
    target = manager_plan(
        "sebastian",
        captain="p12",
        cumulative_points=100,
        counted_transfers=5,
    )
    bands = (
        rank_band(
            "band-a",
            1,
            4,
            representative(
                "rep-ahead-on-transfer",
                manager_plan(
                    "ahead-on-transfer",
                    captain="p12",
                    cumulative_points=100,
                    counted_transfers=4,
                ),
                2,
            ),
            representative(
                "rep-exact-tie",
                manager_plan(
                    "exact-tie",
                    captain="p12",
                    cumulative_points=100,
                    counted_transfers=5,
                ),
                1,
            ),
            representative(
                "rep-behind-on-transfer",
                manager_plan(
                    "behind-on-transfer",
                    captain="p12",
                    cumulative_points=100,
                    counted_transfers=6,
                ),
                1,
            ),
        ),
    )
    population = tiny_known_truth_population(target_plan=target, bands=bands)
    scenarios = scenario_set(_point_map())
    result = simulate_synthetic_overall_rank(
        population,
        multiplier_sets_for_population(population, scenarios),
        rank_tie_policy(),
        target_rank=3,
    )
    outcome = result.distribution.outcomes[0]
    assert outcome.managers_strictly_ahead == 2
    assert outcome.managers_exactly_tied == 1
    assert outcome.rank == 3
    assert result.distribution.probability_target_rank == 1.0


def test_common_football_scenarios_are_required_for_every_representative() -> None:
    population = tiny_known_truth_population()
    scenarios = scenario_set(
        _point_map(p12=8, p13=1),
        _point_map(p12=1, p13=8),
        weights=(0.4, 0.6),
    )
    values = list(multiplier_sets_for_population(population, scenarios))
    target_id = population.target_plan.manager_id
    tamper_index = next(index for index, item in enumerate(values) if item.manager_id != target_id)
    tampered = values[tamper_index]
    first = tampered.scenarios[0]
    changed_first = first.model_copy(
        update={
            "scenario_id": "independent-scenario",
            "multiplier_hash": "0" * 64,
        }
    )
    changed_first_payload = changed_first.model_dump(mode="json", exclude={"multiplier_hash"})
    changed_first = changed_first.model_copy(
        update={"multiplier_hash": semantic_sha256(changed_first_payload)}
    )
    values[tamper_index] = _reseal_multiplier_set(
        tampered.model_copy(update={"scenarios": (changed_first, *tampered.scenarios[1:])})
    )

    with pytest.raises(RankStrategyError) as exc_info:
        simulate_synthetic_overall_rank(
            population,
            tuple(values),
            rank_tie_policy(),
        )
    assert exc_info.value.code == "RANK_SHARED_SCENARIO_IDENTITY_MISMATCH"


def test_raw_projection_and_scenario_set_hash_mismatches_fail_closed() -> None:
    population = tiny_known_truth_population()
    scenarios = scenario_set()
    values = list(multiplier_sets_for_population(population, scenarios))
    target_id = population.target_plan.manager_id
    tamper_index = next(index for index, item in enumerate(values) if item.manager_id != target_id)

    raw_tampered = values[tamper_index].model_copy(
        update={"raw_projection_hash": "9" * 64, "multiplier_set_hash": "0" * 64}
    )
    values[tamper_index] = _reseal_multiplier_set(raw_tampered)
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_synthetic_overall_rank(population, tuple(values), rank_tie_policy())
    assert exc_info.value.code == "RANK_RAW_PROJECTION_MISMATCH"

    values = list(multiplier_sets_for_population(population, scenarios))
    hash_tampered = values[tamper_index].model_copy(
        update={"scenario_set_hash": "8" * 64, "multiplier_set_hash": "0" * 64}
    )
    values[tamper_index] = _reseal_multiplier_set(hash_tampered)
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_synthetic_overall_rank(population, tuple(values), rank_tie_policy())
    assert exc_info.value.code == "RANK_SHARED_SCENARIO_HASH_MISMATCH"


def test_mutated_multiplier_hash_fails_before_rank_arithmetic() -> None:
    population = tiny_known_truth_population()
    values = list(multiplier_sets_for_population(population, scenario_set()))
    values[0] = values[0].model_copy(update={"expected_net_points": 999.0})
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_synthetic_overall_rank(population, tuple(values), rank_tie_policy())
    assert exc_info.value.code == "RANK_SYNTHETIC_MULTIPLIER_SET_HASH_INVALID"


def test_population_membership_plan_target_and_tie_policy_gates() -> None:
    population = tiny_known_truth_population()
    values = multiplier_sets_for_population(population, scenario_set())
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_synthetic_overall_rank(population, values[:-1], rank_tie_policy())
    assert exc_info.value.code == "RANK_SYNTHETIC_MANAGER_SET_MISMATCH"

    changed = list(values)
    changed[0] = _reseal_multiplier_set(
        changed[0].model_copy(update={"plan_id": "wrong", "multiplier_set_hash": "0" * 64})
    )
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_synthetic_overall_rank(population, tuple(changed), rank_tie_policy())
    assert exc_info.value.code == "RANK_SYNTHETIC_MANAGER_PLAN_MISMATCH"

    with pytest.raises(RankStrategyError) as exc_info:
        simulate_synthetic_overall_rank(
            population,
            values,
            rank_tie_policy(verified=False),
        )
    assert exc_info.value.code == "RANK_TIE_RULES_INACTIVE"

    with pytest.raises(RankStrategyError) as exc_info:
        simulate_synthetic_overall_rank(
            population,
            values,
            rank_tie_policy(),
            target_rank=population.total_population_count + 1,
        )
    assert exc_info.value.code == "RANK_TARGET_INVALID"


def test_rights_scrape_hindsight_and_definitive_win_inputs_fail_closed() -> None:
    population = tiny_known_truth_population()
    scenarios = scenario_set()
    values = multiplier_sets_for_population(population, scenarios)

    invalid_rights = _invalid_constructed_population(
        population,
        rights_status=SampleRightsStatus.UNKNOWN,
    )
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_synthetic_overall_rank(invalid_rights, values, rank_tie_policy())
    assert exc_info.value.code == "RANK_SYNTHETIC_RIGHTS_INVALID"

    for field in (
        "mass_scrape_used",
        "final_rank_hindsight_used",
        "definitive_overall_win_model",
    ):
        invalid = _invalid_constructed_population(population, **{field: True})
        with pytest.raises(RankStrategyError) as exc_info:
            simulate_synthetic_overall_rank(invalid, values, rank_tie_policy())
        assert exc_info.value.code == "RANK_SYNTHETIC_FORBIDDEN_INPUT"


def test_semantically_duplicated_representatives_do_not_change_weighting() -> None:
    target = manager_plan("sebastian", captain="p12", cumulative_points=100)
    single_plan = manager_plan("single", captain="p13", cumulative_points=101)
    single_population = tiny_known_truth_population(
        target_plan=target,
        bands=(
            rank_band(
                "band-a",
                1,
                4,
                representative("rep-single", single_plan, 4),
            ),
        ),
    )

    duplicate_a = manager_plan("duplicate-a", captain="p13", cumulative_points=101)
    duplicate_b = manager_plan("duplicate-b", captain="p13", cumulative_points=101)
    duplicated_population = tiny_known_truth_population(
        target_plan=target,
        bands=(
            rank_band(
                "band-a",
                1,
                4,
                representative("rep-a", duplicate_a, 2),
                representative("rep-b", duplicate_b, 2),
            ),
        ),
    )
    scenarios = scenario_set(
        _point_map(p12=10, p13=2),
        _point_map(p12=2, p13=10),
        weights=(0.3, 0.7),
    )
    single = simulate_synthetic_overall_rank(
        single_population,
        multiplier_sets_for_population(single_population, scenarios),
        rank_tie_policy(),
        target_rank=1,
    )
    duplicated = simulate_synthetic_overall_rank(
        duplicated_population,
        multiplier_sets_for_population(duplicated_population, scenarios),
        rank_tie_policy(),
        target_rank=1,
    )

    assert duplicated.distribution.rank_pmf == single.distribution.rank_pmf
    assert (
        duplicated.distribution.probability_target_rank
        == single.distribution.probability_target_rank
    )
    assert duplicated.diagnostics.semantic_representative_count == 1
    assert duplicated.diagnostics.effective_representative_count == pytest.approx(1.0)
    assert (
        duplicated.diagnostics.maximum_representative_population_share
        == single.diagnostics.maximum_representative_population_share
        == 1.0
    )
    assert duplicated.diagnostics.input_representative_count == 2
    assert single.diagnostics.input_representative_count == 1


def test_diagnostics_and_approximation_labels_are_explicit() -> None:
    population = tiny_known_truth_population()
    result = simulate_synthetic_overall_rank(
        population,
        multiplier_sets_for_population(population, scenario_set()),
        rank_tie_policy(),
    )
    assert result.approximation_only is True
    assert result.definitive_overall_win_model is False
    assert result.distribution.approximation_only is True
    assert result.distribution.definitive_overall_win_model is False
    assert result.diagnostics.known_truth is True
    assert (
        result.diagnostics.approximation_status
        is SyntheticApproximationStatus.KNOWN_TRUTH_EXHAUSTIVE
    )
    assert result.diagnostics.represented_manager_count == 4
    assert result.diagnostics.input_representative_count == 3
    assert result.diagnostics.semantic_representative_count == 3
    assert result.diagnostics.effective_representative_count > 0.0
    assert 0.0 < result.diagnostics.maximum_representative_population_share <= 1.0
    assert result.diagnostics.band_population_entropy > 0.0
    assert result.population_hash == population.population_hash
    assert result.provenance_ids == population.provenance_ids
    assert result.source_bundle_ids == population.source_bundle_ids
    assert result.upstream_hashes == population.upstream_hashes


def test_malformed_population_contract_fails_closed_at_service_boundary() -> None:
    population = tiny_known_truth_population()
    malformed = _invalid_constructed_population(population, provenance_ids=())
    with pytest.raises(RankStrategyError) as exc_info:
        simulate_synthetic_overall_rank(
            malformed,
            multiplier_sets_for_population(population, scenario_set()),
            rank_tie_policy(),
        )
    assert exc_info.value.code == "RANK_SYNTHETIC_INPUT_INVALID"
