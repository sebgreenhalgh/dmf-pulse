"""Proper-score evaluation for frozen Stage-8 joint score distributions."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

from dmf_pulse.football_events._decimal import DECIMAL_PRECISION, public_measure_text
from dmf_pulse.football_events.score_distribution import JointScoreDistribution


def _brier(probabilities: tuple[Decimal, ...], observed_index: int) -> Decimal:
    return sum(
        (
            (probability - (Decimal(1) if index == observed_index else Decimal(0))) ** 2
            for index, probability in enumerate(probabilities)
        ),
        Decimal(0),
    )


def _binary_brier(probability: Decimal, observed: bool) -> Decimal:
    return (probability - (Decimal(1) if observed else Decimal(0))) ** 2


def _log_loss(probability: Decimal) -> Decimal:
    if probability <= 0 or probability > 1:
        raise ValueError("observed event has invalid forecast probability")
    return -probability.ln()


def _binary_log_loss(probability: Decimal, observed: bool) -> Decimal:
    selected = probability if observed else Decimal(1) - probability
    return _log_loss(selected)


def _rps(probabilities: tuple[Decimal, ...], observed: int) -> Decimal:
    cumulative = Decimal(0)
    score = Decimal(0)
    for index, probability in enumerate(probabilities[:-1]):
        cumulative += probability
        observed_cumulative = Decimal(1) if observed <= index else Decimal(0)
        score += (cumulative - observed_cumulative) ** 2
    return score


def evaluate_realized_score(
    distribution: JointScoreDistribution,
    *,
    home_goals: int,
    away_goals: int,
) -> dict[str, Any]:
    """Score one final result without modifying the frozen forecast artifact."""

    if home_goals < 0 or away_goals < 0:
        raise ValueError("realized goals must be nonnegative")
    if home_goals > distribution.home_max or away_goals > distribution.away_max:
        raise ValueError("OUTCOME_OUTSIDE_ADAPTIVE_SUPPORT")
    matrix = tuple(tuple(Decimal(value) for value in row) for row in distribution.probabilities)
    observed_probability = matrix[home_goals][away_goals]
    one_x_two = (
        Decimal(distribution.one_x_two.home_win),
        Decimal(distribution.one_x_two.draw),
        Decimal(distribution.one_x_two.away_win),
    )
    observed_outcome = 0 if home_goals > away_goals else 1 if home_goals == away_goals else 2
    home_clean_sheet_probability = Decimal(distribution.clean_sheets.home_clean_sheet)
    away_clean_sheet_probability = Decimal(distribution.clean_sheets.away_clean_sheet)
    home_clean_sheet_observed = away_goals == 0
    away_clean_sheet_observed = home_goals == 0
    btts_probability = Decimal(distribution.both_teams_to_score.yes)
    btts_observed = home_goals > 0 and away_goals > 0
    home_pmf = tuple(Decimal(value) for value in distribution.home_goal_pmf)
    away_pmf = tuple(Decimal(value) for value in distribution.away_goal_pmf)
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        result = {
            "away_clean_sheet_brier": public_measure_text(
                _binary_brier(away_clean_sheet_probability, away_clean_sheet_observed)
            ),
            "away_clean_sheet_log_loss": public_measure_text(
                _binary_log_loss(away_clean_sheet_probability, away_clean_sheet_observed)
            ),
            "away_goal_log_loss": public_measure_text(_log_loss(away_pmf[away_goals])),
            "away_goal_rps": public_measure_text(_rps(away_pmf, away_goals)),
            "away_goals": away_goals,
            "btts_brier": public_measure_text(_binary_brier(btts_probability, btts_observed)),
            "btts_log_loss": public_measure_text(_binary_log_loss(btts_probability, btts_observed)),
            "exact_score_log_loss": public_measure_text(_log_loss(observed_probability)),
            "fixture_id": distribution.fixture_id,
            "forecast_result_sha256": distribution.result_sha256,
            "home_clean_sheet_brier": public_measure_text(
                _binary_brier(home_clean_sheet_probability, home_clean_sheet_observed)
            ),
            "home_clean_sheet_log_loss": public_measure_text(
                _binary_log_loss(home_clean_sheet_probability, home_clean_sheet_observed)
            ),
            "home_goal_log_loss": public_measure_text(_log_loss(home_pmf[home_goals])),
            "home_goal_rps": public_measure_text(_rps(home_pmf, home_goals)),
            "home_goals": home_goals,
            "observed_score_probability": format(observed_probability, ".12f"),
            "one_x_two_brier": public_measure_text(_brier(one_x_two, observed_outcome)),
            "one_x_two_log_loss": public_measure_text(_log_loss(one_x_two[observed_outcome])),
            "schema_version": "score-distribution-evaluation-v1",
        }
    return result


__all__ = ["evaluate_realized_score"]
