from __future__ import annotations

import pytest

from dmf_pulse.rank_strategy.manager_multipliers import calculate_manager_multipliers
from dmf_pulse.rank_strategy.mini_league import simulate_mini_league_rank
from dmf_pulse.rank_strategy.rank_utility import evaluate_rank_strategy
from dmf_pulse.rank_strategy.utility_models import RankObjectiveMode, RankTargetDefinition
from tests.support.rank_strategy_fixtures import (
    cohort,
    manager_plan,
    multiplier_policy,
    rank_players,
    rank_rules,
    rank_tie_policy,
    scenario_set,
)
from tests.support.rank_utility_fixtures import candidate, context, policy

pytestmark = pytest.mark.integration


def _distribution_for_sebastian(captain: str):
    shared = scenario_set(
        {f"p{index:02d}": index % 5 for index in range(15)},
        {f"p{index:02d}": (14 - index) % 5 for index in range(15)},
        weights=(0.5, 0.5),
    )
    sebastian = manager_plan(
        "sebastian",
        captain=captain,
        vice="p13" if captain != "p13" else "p12",
    )
    rival = manager_plan("rival", captain="p12", vice="p13")
    sets = tuple(
        calculate_manager_multipliers(
            plan,
            shared,
            rank_players(),
            rank_rules(),
            multiplier_policy(),
        )
        for plan in (sebastian, rival)
    )
    sample = cohort(sebastian, rival)
    return simulate_mini_league_rank(
        sample,
        sets,
        rank_tie_policy(),
        target_manager_id="sebastian",
        target_rank=1,
    )


def test_exact_mini_league_rank_distributions_feed_lexicographic_utility_without_projection_mutation() -> (
    None
):
    points_distribution = _distribution_for_sebastian("p12")
    alternative_distribution = _distribution_for_sebastian("p13")
    points = candidate(
        "points",
        60.0,
        None,
        raw_hash=points_distribution.raw_projection_hash,
        scenario_hash=points_distribution.scenario_set_hash,
    ).model_copy(update={"rank_distribution": points_distribution})
    alternative = candidate(
        "alternative",
        59.8,
        None,
        raw_hash=alternative_distribution.raw_projection_hash,
        scenario_hash=alternative_distribution.scenario_set_hash,
    ).model_copy(update={"rank_distribution": alternative_distribution})

    result = evaluate_rank_strategy(
        request_id="exact-mini-league-utility",
        objective=RankObjectiveMode.MINI_LEAGUE_WIN,
        candidates=(points, alternative),
        context=context(),
        policy=policy(material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )
    assert result.points_optimal_plan_id == "points"
    assert result.projection_invariance.identical is True
    assert result.rank_optimal_metrics.mini_league_win_probability is not None
