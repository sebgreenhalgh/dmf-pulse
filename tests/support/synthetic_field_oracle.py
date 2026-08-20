"""Independent exhaustive oracle for a tiny weighted overall field.

This module intentionally imports neither the production synthetic-field service
nor the production rank-simulator helpers.
"""

from __future__ import annotations

import json
from collections import defaultdict
from math import log
from typing import Any

from dmf_pulse.rank_strategy.models import ManagerMultiplierSet
from dmf_pulse.rank_strategy.synthetic_models import SyntheticOverallPopulation


def _semantic_plan_key(plan) -> str:
    payload = plan.model_dump(mode="json", exclude={"manager_id", "plan_id"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def exhaustive_synthetic_field_oracle(
    population: SyntheticOverallPopulation,
    multiplier_sets: tuple[ManagerMultiplierSet, ...],
    *,
    target_rank: int | None,
) -> dict[str, Any]:
    set_by_manager = {item.manager_id: item for item in multiplier_sets}
    scenario_maps = {
        manager_id: {
            (scenario.scenario_id, scenario.outcome_draw_id): scenario
            for scenario in multiplier_set.scenarios
        }
        for manager_id, multiplier_set in set_by_manager.items()
    }
    target = population.target_plan
    target_set = set_by_manager[target.manager_id]
    pmf: defaultdict[int, float] = defaultdict(float)
    outcomes: list[dict[str, Any]] = []
    for baseline in target_set.scenarios:
        identity = (baseline.scenario_id, baseline.outcome_draw_id)
        target_points = target.cumulative_points + baseline.net_points
        managers_ahead = 0
        managers_tied = 0
        bands: list[dict[str, int | str]] = []
        for band in population.bands:
            band_ahead = 0
            band_tied = 0
            for representative in band.representatives:
                plan = representative.manager_plan
                final_points = (
                    plan.cumulative_points + scenario_maps[plan.manager_id][identity].net_points
                )
                ahead = final_points > target_points or (
                    final_points == target_points
                    and plan.counted_transfers < target.counted_transfers
                )
                tied = (
                    final_points == target_points
                    and plan.counted_transfers == target.counted_transfers
                )
                if ahead:
                    band_ahead += representative.population_count
                elif tied:
                    band_tied += representative.population_count
            managers_ahead += band_ahead
            managers_tied += band_tied
            bands.append(
                {
                    "band_id": band.band_id,
                    "population_count": band.population_count,
                    "managers_strictly_ahead": band_ahead,
                    "managers_exactly_tied": band_tied,
                }
            )
        rank = managers_ahead + 1
        pmf[rank] += baseline.weight
        outcomes.append(
            {
                "scenario_id": identity[0],
                "outcome_draw_id": identity[1],
                "weight": baseline.weight,
                "target_final_points": target_points,
                "target_counted_transfers": target.counted_transfers,
                "managers_strictly_ahead": managers_ahead,
                "managers_exactly_tied": managers_tied,
                "rank": rank,
                "band_counts": bands,
            }
        )

    sorted_pmf = tuple(sorted(pmf.items()))
    represented = population.total_population_count - 1
    semantic_counts: defaultdict[str, int] = defaultdict(int)
    input_count = 0
    for band in population.bands:
        for representative in band.representatives:
            input_count += 1
            semantic_counts[_semantic_plan_key(representative.manager_plan)] += (
                representative.population_count
            )
    effective = represented**2 / sum(count**2 for count in semantic_counts.values())
    maximum_share = max(count / represented for count in semantic_counts.values())
    band_entropy = -sum(
        (band.population_count / represented) * log(band.population_count / represented)
        for band in population.bands
    )
    return {
        "pmf": sorted_pmf,
        "expected_rank": sum(rank * probability for rank, probability in sorted_pmf),
        "probability_target_rank": (
            None
            if target_rank is None
            else sum(probability for rank, probability in sorted_pmf if rank <= target_rank)
        ),
        "rank_one_probability": sum(probability for rank, probability in sorted_pmf if rank == 1),
        "outcomes": outcomes,
        "diagnostics": {
            "represented_manager_count": represented,
            "input_representative_count": input_count,
            "semantic_representative_count": len(semantic_counts),
            "effective_representative_count": effective,
            "maximum_representative_population_share": maximum_share,
            "band_population_entropy": band_entropy,
        },
    }
