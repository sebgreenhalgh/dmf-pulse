"""Independent tiny exhaustive oracle for exact mini-league tests.

This deliberately does not import production mini-league or rank-simulator code.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from dmf_pulse.rank_strategy.models import CohortSample, ManagerMultiplierSet


def exhaustive_mini_league_oracle(
    sample: CohortSample,
    multiplier_sets: tuple[ManagerMultiplierSet, ...],
    *,
    target_manager_id: str,
    target_rank: int | None = None,
) -> dict[str, Any]:
    plans = {member.manager_plan.manager_id: member.manager_plan for member in sample.members}
    scenario_maps = {
        item.manager_id: {
            (scenario.scenario_id, scenario.outcome_draw_id): scenario
            for scenario in item.scenarios
        }
        for item in multiplier_sets
    }
    baseline = multiplier_sets[0]
    pmf: defaultdict[int, float] = defaultdict(float)
    outcomes: list[dict[str, Any]] = []
    for baseline_scenario in baseline.scenarios:
        identity = (baseline_scenario.scenario_id, baseline_scenario.outcome_draw_id)
        final_points = {
            manager_id: plan.cumulative_points + scenario_maps[manager_id][identity].net_points
            for manager_id, plan in plans.items()
        }
        transfers = {manager_id: plan.counted_transfers for manager_id, plan in plans.items()}
        ranks: dict[str, int] = {}
        for manager_id in plans:
            outrankers = 0
            for rival_id in plans:
                if rival_id == manager_id:
                    continue
                if final_points[rival_id] > final_points[manager_id] or (
                    final_points[rival_id] == final_points[manager_id]
                    and transfers[rival_id] < transfers[manager_id]
                ):
                    outrankers += 1
            ranks[manager_id] = outrankers + 1
        pmf[ranks[target_manager_id]] += baseline_scenario.weight
        outcomes.append(
            {
                "identity": identity,
                "weight": baseline_scenario.weight,
                "ranks": dict(sorted(ranks.items())),
                "final_points": dict(sorted(final_points.items())),
                "transfers": dict(sorted(transfers.items())),
            }
        )
    ordered_pmf = tuple(sorted(pmf.items()))
    expected_rank = sum(rank * probability for rank, probability in ordered_pmf)
    target_probability = (
        None
        if target_rank is None
        else sum(probability for rank, probability in ordered_pmf if rank <= target_rank)
    )
    return {
        "rank_pmf": ordered_pmf,
        "expected_rank": expected_rank,
        "probability_target_rank": target_probability,
        "win_probability": pmf.get(1, 0.0),
        "outcomes": tuple(outcomes),
    }
