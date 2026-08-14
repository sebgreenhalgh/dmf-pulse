"""Bounded distribution evaluation and official-score reconciliation interfaces."""

from __future__ import annotations

from math import log

from dmf_pulse.fpl_points.models import (
    DistributionEvaluation,
    PlayerProjectionSummary,
    PlayerScenarioScore,
    ReconciliationDifference,
)


def evaluate_player_distribution(
    summary: PlayerProjectionSummary, observed_points: int
) -> DistributionEvaluation:
    mass = summary.pmf.get(observed_points, 0.0)
    return DistributionEvaluation(
        player_id=summary.player_id,
        observed_points=observed_points,
        probability_mass_observed=mass,
        log_score=-log(mass) if mass > 0.0 else None,
        absolute_error_mean=abs(summary.expected_points - observed_points),
        squared_error_mean=(summary.expected_points - observed_points) ** 2,
        threshold_hits={
            "1_plus": observed_points >= 1,
            "2_plus": observed_points >= 2,
            "5_plus": observed_points >= 5,
            "10_plus": observed_points >= 10,
            "15_plus": observed_points >= 15,
        },
    )


def reconcile_official_score(
    player_id: str,
    modeled: PlayerScenarioScore,
    official_components: dict[str, int],
) -> ReconciliationDifference:
    component_names = (
        "appearance",
        "assists",
        "bonus",
        "clean_sheet",
        "defensive_contributions",
        "goals",
        "goals_conceded",
        "own_goals",
        "penalty_misses",
        "penalty_saves",
        "red_cards",
        "saves",
        "yellow_cards",
    )
    differences = {
        name: getattr(modeled, name) - int(official_components.get(name, 0))
        for name in component_names
    }
    official_total = int(official_components["total"])
    return ReconciliationDifference(
        player_id=player_id,
        modeled_total=modeled.total,
        official_total=official_total,
        total_difference=modeled.total - official_total,
        component_differences=differences,
        exact_match=(
            modeled.total == official_total and all(value == 0 for value in differences.values())
        ),
    )
