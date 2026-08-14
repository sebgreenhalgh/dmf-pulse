"""Independent-Poisson score-prior construction for GCS-008."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from dmf_pulse.football_events._decimal import (
    canonical_decimal_text,
    canonical_json_sha256,
    nonnegative_decimal,
)
from dmf_pulse.football_events.score_grid import ScoreGrid, build_adaptive_score_grid


@dataclass(frozen=True, slots=True)
class ScorePrior:
    model_family: str
    home_rate: Decimal
    away_rate: Decimal
    grid: ScoreGrid
    semantic_sha256: str


def build_score_prior(
    home_rate: Decimal,
    away_rate: Decimal,
    *,
    minimum_max_goals: int,
    maximum_max_goals: int,
    tail_tolerance: Decimal,
    hard_tail_limit: Decimal,
) -> ScorePrior:
    """Build the selected Stage-8 baseline prior without market information."""

    home = nonnegative_decimal(home_rate, label="home_rate")
    away = nonnegative_decimal(away_rate, label="away_rate")
    grid = build_adaptive_score_grid(
        home,
        away,
        minimum_max_goals=minimum_max_goals,
        maximum_max_goals=maximum_max_goals,
        tail_tolerance=tail_tolerance,
        hard_tail_limit=hard_tail_limit,
    )
    semantic = {
        "away_max": grid.away_max,
        "away_rate": canonical_decimal_text(away),
        "home_max": grid.home_max,
        "home_rate": canonical_decimal_text(home),
        "model_family": "INDEPENDENT_POISSON_V1",
        "omitted_tail_mass": canonical_decimal_text(grid.omitted_tail_mass),
        "probabilities": [
            [canonical_decimal_text(value) for value in row] for row in grid.probabilities
        ],
    }
    return ScorePrior(
        model_family="INDEPENDENT_POISSON_V1",
        home_rate=home,
        away_rate=away,
        grid=grid,
        semantic_sha256=canonical_json_sha256(semantic),
    )


__all__ = ["ScorePrior", "build_score_prior"]
