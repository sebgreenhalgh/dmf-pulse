import hashlib
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketFamily,
    ScoreEvent,
)
from dmf_pulse.football_events.score_grid import build_adaptive_score_grid
from dmf_pulse.football_events.service import (
    ScoreDistributionRequest,
    ScoreDistributionService,
    ScorePriorRequest,
)


def _stage7_request_fields(fixture_id: UUID, as_of: datetime) -> dict[str, object]:
    source_as_of = as_of.replace(minute=max(0, as_of.minute - 10))
    home_team_id = UUID("20000000-0000-7000-8000-000000000001")
    away_team_id = UUID("20000000-0000-7000-8000-000000000002")

    def identity(side: str, team_id: UUID) -> dict[str, object]:
        fixture_text = str(fixture_id)
        return {
            "schema_version": "team-minutes-projection-v1",
            "fixture_id": fixture_text,
            "team_id": str(team_id),
            "as_of": source_as_of.isoformat().replace("+00:00", "Z"),
            "model_family": "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
            "dataset_sha256": hashlib.sha256(b"GCS-008 Stage-7 dataset").hexdigest(),
            "model_artifact_sha256": hashlib.sha256(b"GCS-008 Stage-7 model").hexdigest(),
            "sample_count": 256,
            "scenario_set_sha256": hashlib.sha256(
                f"{fixture_text}:{side}:scenarios".encode()
            ).hexdigest(),
            "result_sha256": hashlib.sha256(
                f"{fixture_text}:{side}:team-minutes-projection-v1".encode()
            ).hexdigest(),
        }

    return {
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "minutes_context": {
            "schema_version": "stage7-minutes-context-v1",
            "home": identity("home", home_team_id),
            "away": identity("away", away_team_id),
        },
    }


pytestmark = pytest.mark.property

RATE_TENTHS = st.integers(min_value=0, max_value=45)


def _rate(value: int) -> Decimal:
    return Decimal(value) / Decimal(10)


@given(home=RATE_TENTHS, away=RATE_TENTHS)
@settings(max_examples=60, deadline=None)
def test_adaptive_matrix_is_a_nonnegative_simplex(home: int, away: int) -> None:
    grid = build_adaptive_score_grid(
        _rate(home),
        _rate(away),
        minimum_max_goals=6,
        maximum_max_goals=36,
        tail_tolerance=Decimal("0.0000000001"),
        hard_tail_limit=Decimal("0.00000001"),
    )
    values = [value for row in grid.probabilities for value in row]
    assert all(value >= 0 for value in values)
    # Internal score arithmetic declares precision 60.  Use double that precision
    # so summing the finite stored coefficients itself introduces no rounding.
    with localcontext() as context:
        context.prec = 120
        assert sum(values, Decimal(0)) == Decimal(1)


@given(home=RATE_TENTHS, away=RATE_TENTHS)
@settings(max_examples=40, deadline=None)
def test_public_clean_sheet_and_expectation_identities(home: int, away: int) -> None:
    request = ScoreDistributionRequest.model_validate(
        {
            "schema_version": "score-distribution-request-v1",
            "fixture_id": UUID("10000000-0000-7000-8000-000000000899"),
            "as_of": datetime(2026, 8, 20, 12, tzinfo=UTC),
            **_stage7_request_fields(
                UUID("10000000-0000-7000-8000-000000000899"),
                datetime(2026, 8, 20, 12, tzinfo=UTC),
            ),
            "fixture_status": "SCHEDULED",
            "prior": ScorePriorRequest.model_validate(
                {
                    "home_goal_rate": _rate(home),
                    "away_goal_rate": _rate(away),
                }
            ),
            "constraints": (),
        }
    )
    first = ScoreDistributionService().project(request)
    second = ScoreDistributionService().project(request)
    assert first == second
    assert first.distribution is not None
    distribution = first.distribution
    matrix = tuple(tuple(Decimal(value) for value in row) for row in distribution.probabilities)
    assert Decimal(distribution.clean_sheets.home_clean_sheet) == sum(
        (matrix[index][0] for index in range(distribution.home_max + 1)),
        Decimal(0),
    )
    assert Decimal(distribution.clean_sheets.away_clean_sheet) == sum(matrix[0], Decimal(0))
    assert distribution.home_goals_conceded_pmf == distribution.away_goal_pmf
    assert distribution.away_goals_conceded_pmf == distribution.home_goal_pmf
    btts_yes = sum(
        (
            matrix[home_goals][away_goals]
            for home_goals in range(1, distribution.home_max + 1)
            for away_goals in range(1, distribution.away_max + 1)
        ),
        Decimal(0),
    )
    assert Decimal(distribution.both_teams_to_score.yes) == btts_yes
    assert Decimal(distribution.both_teams_to_score.no) == Decimal(1) - btts_yes
    assert Decimal(distribution.expected_home_goals) == sum(
        (Decimal(index) * Decimal(value) for index, value in enumerate(distribution.home_goal_pmf)),
        Decimal(0),
    ).quantize(Decimal("0.000001"))


@given(value=st.one_of(st.integers(max_value=-1), st.integers(min_value=2, max_value=100)))
def test_invalid_constraint_probabilities_never_enter_model(value: int) -> None:
    with pytest.raises(ValidationError):
        MarketConstraint.model_validate(
            {
                "constraint_id": "invalid",
                "family": MarketFamily.ONE_X_TWO,
                "event": ScoreEvent.HOME_WIN,
                "target_probability": Decimal(value),
                "uncertainty": Decimal("0.02"),
                "usable_at": datetime(2026, 8, 20, 12, tzinfo=UTC),
            }
        )


@given(home=RATE_TENTHS, away=RATE_TENTHS)
@settings(max_examples=40, deadline=None)
def test_larger_grid_preserves_overlapping_probability_with_declared_tail(
    home: int,
    away: int,
) -> None:
    small = build_adaptive_score_grid(
        _rate(home),
        _rate(away),
        minimum_max_goals=4,
        maximum_max_goals=36,
        tail_tolerance=Decimal("0.0001"),
        hard_tail_limit=Decimal("0.001"),
    )
    large = build_adaptive_score_grid(
        _rate(home),
        _rate(away),
        minimum_max_goals=max(10, small.home_max, small.away_max),
        maximum_max_goals=36,
        tail_tolerance=Decimal("0.0000000001"),
        hard_tail_limit=Decimal("0.00000001"),
    )
    bound = Decimal("2") * (small.omitted_tail_mass + large.omitted_tail_mass)
    for home_goals in range(small.home_max + 1):
        for away_goals in range(small.away_max + 1):
            assert (
                abs(
                    small.probabilities[home_goals][away_goals]
                    - large.probabilities[home_goals][away_goals]
                )
                <= bound
            )


@given(home=RATE_TENTHS, away=RATE_TENTHS)
@settings(max_examples=30, deadline=None)
def test_all_published_binary_totals_are_exact_complements(home: int, away: int) -> None:
    request = ScoreDistributionRequest.model_validate(
        {
            "schema_version": "score-distribution-request-v1",
            "fixture_id": UUID("10000000-0000-7000-8000-000000000898"),
            "as_of": datetime(2026, 8, 20, 12, tzinfo=UTC),
            **_stage7_request_fields(
                UUID("10000000-0000-7000-8000-000000000898"),
                datetime(2026, 8, 20, 12, tzinfo=UTC),
            ),
            "prior": {
                "home_goal_rate": _rate(home),
                "away_goal_rate": _rate(away),
            },
        }
    )
    result = ScoreDistributionService().project(request)
    assert result.distribution is not None
    for total in result.distribution.total_goals:
        assert Decimal(total.under) + Decimal(total.over) == Decimal(1)
