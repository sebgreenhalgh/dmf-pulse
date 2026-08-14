from pathlib import Path

import pytest

from dmf_pulse.football_events.coherence import (
    ScoreCoherenceError,
    assert_score_coherence,
    score_distribution_semantic_projection,
)
from dmf_pulse.football_events.score_distribution import JointScoreDistribution

pytestmark = pytest.mark.unit
FIXTURE = Path("fixtures/events/score/GCS-008/balanced_fixture.expected.json")


def _distribution() -> JointScoreDistribution:
    return JointScoreDistribution.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def test_semantic_projection_recomputes_hash() -> None:
    distribution = _distribution()
    assert score_distribution_semantic_projection(distribution)["result_sha256"] == (
        distribution.result_sha256
    )


def test_coherence_detects_matrix_mass_mutation() -> None:
    distribution = _distribution()
    rows = [list(row) for row in distribution.probabilities]
    rows[0][0] = "0.000000000000"
    object.__setattr__(distribution, "probabilities", tuple(tuple(row) for row in rows))
    with pytest.raises(ScoreCoherenceError, match="sum exactly"):
        assert_score_coherence(distribution)


def test_coherence_detects_clean_sheet_mutation() -> None:
    distribution = _distribution()
    object.__setattr__(
        distribution.clean_sheets,
        "home_clean_sheet",
        "0.999999999999",
    )
    with pytest.raises(ScoreCoherenceError, match="home clean sheet"):
        assert_score_coherence(distribution)


def test_coherence_detects_expectation_mutation() -> None:
    distribution = _distribution()
    object.__setattr__(distribution, "expected_home_goals", "9.000000")
    with pytest.raises(ScoreCoherenceError, match="home expected goals"):
        assert_score_coherence(distribution)


def test_semantic_projection_detects_hash_mutation() -> None:
    distribution = _distribution()
    object.__setattr__(distribution, "result_sha256", "0" * 64)
    with pytest.raises(ScoreCoherenceError, match="hash mutation"):
        score_distribution_semantic_projection(distribution)


def test_coherence_detects_away_clean_sheet_mutation() -> None:
    distribution = _distribution()
    object.__setattr__(
        distribution.clean_sheets,
        "away_clean_sheet",
        "0.999999999999",
    )
    with pytest.raises(ScoreCoherenceError, match="away clean sheet"):
        assert_score_coherence(distribution)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("home_goals_conceded_pmf", ("1.000000000000",), "home conceded PMF"),
        ("away_goals_conceded_pmf", ("1.000000000000",), "away conceded PMF"),
    ],
)
def test_coherence_detects_goals_conceded_marginal_mutation(
    field: str,
    replacement: tuple[str, ...],
    message: str,
) -> None:
    distribution = _distribution()
    object.__setattr__(distribution, field, replacement)
    with pytest.raises(ScoreCoherenceError, match=message):
        assert_score_coherence(distribution)


def test_coherence_detects_btts_yes_and_no_mutations() -> None:
    distribution = _distribution()
    object.__setattr__(distribution.both_teams_to_score, "yes", "0.999999999999")
    with pytest.raises(ScoreCoherenceError, match="BTTS yes"):
        assert_score_coherence(distribution)

    distribution = _distribution()
    object.__setattr__(distribution.both_teams_to_score, "no", "0.999999999999")
    with pytest.raises(ScoreCoherenceError, match="BTTS no"):
        assert_score_coherence(distribution)


def test_coherence_detects_away_expectation_mutation() -> None:
    distribution = _distribution()
    object.__setattr__(distribution, "expected_away_goals", "9.000000")
    with pytest.raises(ScoreCoherenceError, match="away expected goals"):
        assert_score_coherence(distribution)
