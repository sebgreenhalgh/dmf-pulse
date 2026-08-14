"""Independent semantic coherence checks for Stage-8 public artifacts."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from dmf_pulse.football_events._decimal import (
    canonical_json_sha256,
    public_measure_text,
)
from dmf_pulse.football_events.score_distribution import JointScoreDistribution


class ScoreCoherenceError(ValueError):
    """A public score distribution violates an independent invariant."""


def assert_score_coherence(distribution: JointScoreDistribution) -> None:
    """Recheck the conservation identities without relying on solver internals."""

    matrix = tuple(tuple(Decimal(value) for value in row) for row in distribution.probabilities)
    total = sum((sum(row, Decimal(0)) for row in matrix), Decimal(0))
    if total != Decimal(1):
        raise ScoreCoherenceError("score matrix does not sum exactly to one")
    home_clean_sheet = sum(
        (matrix[home][0] for home in range(distribution.home_max + 1)),
        Decimal(0),
    )
    away_clean_sheet = sum(matrix[0], Decimal(0))
    if home_clean_sheet != Decimal(distribution.clean_sheets.home_clean_sheet):
        raise ScoreCoherenceError("home clean sheet is not P(away goals = 0)")
    if away_clean_sheet != Decimal(distribution.clean_sheets.away_clean_sheet):
        raise ScoreCoherenceError("away clean sheet is not P(home goals = 0)")
    if tuple(distribution.home_goals_conceded_pmf) != tuple(distribution.away_goal_pmf):
        raise ScoreCoherenceError("home conceded PMF is not the away goal PMF")
    if tuple(distribution.away_goals_conceded_pmf) != tuple(distribution.home_goal_pmf):
        raise ScoreCoherenceError("away conceded PMF is not the home goal PMF")
    btts_yes = sum(
        (
            matrix[home][away]
            for home in range(1, distribution.home_max + 1)
            for away in range(1, distribution.away_max + 1)
        ),
        Decimal(0),
    )
    if btts_yes != Decimal(distribution.both_teams_to_score.yes):
        raise ScoreCoherenceError("BTTS yes is not P(home > 0 and away > 0)")
    if Decimal(1) - btts_yes != Decimal(distribution.both_teams_to_score.no):
        raise ScoreCoherenceError("BTTS no is not the complement of BTTS yes")
    home_expectation = sum(
        (Decimal(index) * Decimal(value) for index, value in enumerate(distribution.home_goal_pmf)),
        Decimal(0),
    )
    away_expectation = sum(
        (Decimal(index) * Decimal(value) for index, value in enumerate(distribution.away_goal_pmf)),
        Decimal(0),
    )
    if public_measure_text(home_expectation) != distribution.expected_home_goals:
        raise ScoreCoherenceError("home expected goals do not match the home PMF")
    if public_measure_text(away_expectation) != distribution.expected_away_goals:
        raise ScoreCoherenceError("away expected goals do not match the away PMF")


def score_distribution_semantic_projection(
    distribution: JointScoreDistribution,
) -> dict[str, Any]:
    """Return the frozen public body and an independently recomputed identity."""

    body = distribution.model_dump(mode="json")
    supplied = body.pop("result_sha256")
    recomputed = canonical_json_sha256(body)
    if supplied != recomputed:
        raise ScoreCoherenceError("result hash mutation detected")
    body["result_sha256"] = supplied
    return body


__all__ = [
    "ScoreCoherenceError",
    "assert_score_coherence",
    "score_distribution_semantic_projection",
]
