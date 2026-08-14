import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.football_events.coherence import assert_score_coherence
from dmf_pulse.football_events.score_distribution import JointScoreDistribution
from dmf_pulse.football_events.service import (
    ScoreDistributionService,
    load_score_distribution_request,
)

pytestmark = pytest.mark.unit
FIXTURE = Path("fixtures/events/score/GCS-008/balanced_fixture.json")


def test_service_derives_every_team_output_from_one_matrix() -> None:
    result = ScoreDistributionService().project(load_score_distribution_request(FIXTURE))
    assert result.status == "PROJECTED"
    distribution = result.distribution
    assert distribution is not None
    assert_score_coherence(distribution)
    matrix = tuple(tuple(Decimal(value) for value in row) for row in distribution.probabilities)
    assert sum((sum(row, Decimal(0)) for row in matrix), Decimal(0)) == Decimal(1)
    assert Decimal(distribution.clean_sheets.home_clean_sheet) == sum(
        (row[0] for row in matrix), Decimal(0)
    )
    assert Decimal(distribution.clean_sheets.away_clean_sheet) == sum(matrix[0], Decimal(0))
    assert distribution.confidence_grade == "B"
    assert distribution.diagnostics.constraint_count == 4


def test_serialized_distribution_has_no_binary_float_or_nonfinite_value() -> None:
    distribution = (
        ScoreDistributionService().project(load_score_distribution_request(FIXTURE)).distribution
    )
    assert distribution is not None
    serialized = json.dumps(distribution.model_dump(mode="json"), allow_nan=False)
    assert "NaN" not in serialized
    assert "Infinity" not in serialized
    assert not any(isinstance(value, float) for row in distribution.probabilities for value in row)


def test_public_hash_mutation_is_rejected() -> None:
    distribution = (
        ScoreDistributionService().project(load_score_distribution_request(FIXTURE)).distribution
    )
    assert distribution is not None
    body = distribution.model_dump(mode="json")
    body["expected_home_goals"] = "9.000000"
    with pytest.raises(ValidationError):
        JointScoreDistribution.model_validate(body)


def test_probability_identity_mutation_is_rejected_even_with_old_hash() -> None:
    distribution = (
        ScoreDistributionService().project(load_score_distribution_request(FIXTURE)).distribution
    )
    assert distribution is not None
    body = distribution.model_dump(mode="json")
    body["clean_sheets"]["home_clean_sheet"] = "0.999999999999"
    with pytest.raises(ValidationError, match="clean-sheet"):
        JointScoreDistribution.model_validate(body)
