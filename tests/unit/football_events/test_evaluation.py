from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.football_events.evaluation import evaluate_realized_score
from dmf_pulse.football_events.service import (
    ScoreDistributionService,
    load_score_distribution_request,
)

pytestmark = pytest.mark.unit
FIXTURE = Path("fixtures/events/score/GCS-008/balanced_fixture.json")


def _distribution():
    result = ScoreDistributionService().project(load_score_distribution_request(FIXTURE))
    assert result.distribution is not None
    return result.distribution


def test_exact_score_scoring_harness_uses_frozen_probability() -> None:
    distribution = _distribution()
    evaluation = evaluate_realized_score(distribution, home_goals=2, away_goals=1)
    assert evaluation["forecast_result_sha256"] == distribution.result_sha256
    assert Decimal(evaluation["observed_score_probability"]) == Decimal(
        distribution.probabilities[2][1]
    )
    assert Decimal(evaluation["exact_score_log_loss"]) > 0
    assert Decimal(evaluation["one_x_two_brier"]) >= 0


def test_outcome_beyond_adaptive_support_fails_explicitly() -> None:
    distribution = _distribution()
    with pytest.raises(ValueError, match="OUTCOME_OUTSIDE_ADAPTIVE_SUPPORT"):
        evaluate_realized_score(
            distribution,
            home_goals=distribution.home_max + 1,
            away_goals=0,
        )
