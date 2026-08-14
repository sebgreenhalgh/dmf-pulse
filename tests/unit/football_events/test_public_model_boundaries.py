from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.football_events._decimal import canonical_json_sha256
from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketConstraintSet,
    MarketFamily,
    ScoreEvent,
)
from dmf_pulse.football_events.score_distribution import (
    JointScoreDistribution,
    MarketResidual,
    OneXTwoDistribution,
    TotalGoalsProbability,
    _confidence,
    _decimal_text,
    _probability_text,
    compose_joint_score_distribution,
)
from dmf_pulse.football_events.score_prior import build_score_prior
from dmf_pulse.football_events.score_projection import ProjectionResult
from dmf_pulse.football_events.service import (
    ScoreDistributionService,
    load_score_distribution_request,
)

pytestmark = pytest.mark.unit
FIXTURE = Path("fixtures/events/score/GCS-008/balanced_fixture.json")


def _distribution() -> JointScoreDistribution:
    result = ScoreDistributionService().project(load_score_distribution_request(FIXTURE))
    assert result.distribution is not None
    return result.distribution


def _body() -> dict:
    return _distribution().model_dump(mode="json")


@lru_cache(maxsize=1)
def _all_supported_market_distribution() -> JointScoreDistribution:
    request = load_score_distribution_request(FIXTURE)
    specifications = (
        (MarketFamily.ONE_X_TWO, ScoreEvent.HOME_WIN, "0.400000000000", {}),
        (MarketFamily.ONE_X_TWO, ScoreEvent.DRAW, "0.300000000000", {}),
        (MarketFamily.ONE_X_TWO, ScoreEvent.AWAY_WIN, "0.300000000000", {}),
        (MarketFamily.TOTALS, ScoreEvent.TOTAL_OVER, "0.500000000000", {"line": "2.5"}),
        (MarketFamily.TOTALS, ScoreEvent.TOTAL_UNDER, "0.500000000000", {"line": "2.5"}),
        (
            MarketFamily.TEAM_TOTAL,
            ScoreEvent.HOME_TEAM_TOTAL_OVER,
            "0.500000000000",
            {"line": "1.5"},
        ),
        (
            MarketFamily.TEAM_TOTAL,
            ScoreEvent.HOME_TEAM_TOTAL_UNDER,
            "0.500000000000",
            {"line": "1.5"},
        ),
        (
            MarketFamily.TEAM_TOTAL,
            ScoreEvent.AWAY_TEAM_TOTAL_OVER,
            "0.500000000000",
            {"line": "1.5"},
        ),
        (
            MarketFamily.TEAM_TOTAL,
            ScoreEvent.AWAY_TEAM_TOTAL_UNDER,
            "0.500000000000",
            {"line": "1.5"},
        ),
        (MarketFamily.CLEAN_SHEET, ScoreEvent.HOME_CLEAN_SHEET, "0.350000000000", {}),
        (MarketFamily.CLEAN_SHEET, ScoreEvent.AWAY_CLEAN_SHEET, "0.250000000000", {}),
        (MarketFamily.BTTS, ScoreEvent.BTTS_YES, "0.500000000000", {}),
        (MarketFamily.BTTS, ScoreEvent.BTTS_NO, "0.500000000000", {}),
        (
            MarketFamily.CORRECT_SCORE,
            ScoreEvent.EXACT_SCORE,
            "0.100000000000",
            {"home_goals": 1, "away_goals": 0},
        ),
    )
    constraints = tuple(
        MarketConstraint.model_validate(
            {
                "constraint_id": f"all-events-{event.value.lower()}",
                "event": event,
                "family": family,
                "target_probability": Decimal(target),
                "uncertainty": Decimal("0.200000000000"),
                "usable_at": request.as_of,
                "weight": Decimal("0.010000000000"),
                **extra,
            }
        )
        for family, event, target, extra in specifications
    )
    amended = request.model_copy(update={"constraints": constraints})
    result = ScoreDistributionService().project(amended)
    assert result.distribution is not None
    return result.distribution


def test_public_decimal_parsers_reject_non_string_values() -> None:
    with pytest.raises(ValueError, match="public decimal string"):
        _probability_text(Decimal("0.5"), label="p")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="public decimal string"):
        _decimal_text(Decimal("0.5"), label="x")  # type: ignore[arg-type]


def test_noncanonical_probability_lexeme_cannot_create_a_second_identity() -> None:
    body = _body()
    original = body["probabilities"][0][0]
    body["probabilities"][0][0] = original + "0"
    unhashed = dict(body)
    unhashed.pop("result_sha256")
    body["result_sha256"] = canonical_json_sha256(unhashed)
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        JointScoreDistribution.model_validate(body)


def test_nested_public_simplexes_and_residuals_fail_closed() -> None:
    with pytest.raises(ValidationError, match="1X2 probabilities"):
        OneXTwoDistribution.model_validate(
            {
                "home_win": "0.500000000000",
                "draw": "0.300000000000",
                "away_win": "0.300000000000",
            }
        )
    with pytest.raises(ValidationError, match="under/over"):
        TotalGoalsProbability.model_validate(
            {
                "line": "2.5",
                "under": "0.500000000000",
                "over": "0.600000000000",
            }
        )
    valid = _distribution().market_residuals[0].model_dump(mode="json")
    zero_uncertainty = dict(valid, uncertainty="0.000000000000")
    with pytest.raises(ValidationError, match="uncertainty"):
        MarketResidual.model_validate(zero_uncertainty)
    wrong_residual = dict(valid, residual="0.123456789012")
    with pytest.raises(ValidationError, match="does not equal"):
        MarketResidual.model_validate(wrong_residual)
    wrong_hash = dict(valid, source_result_sha256="bad")
    with pytest.raises(ValidationError, match="SHA-256"):
        MarketResidual.model_validate(wrong_hash)


@pytest.mark.parametrize("event", tuple(ScoreEvent))
def test_matrix_recomputes_every_supported_market_residual(event: ScoreEvent) -> None:
    body = _all_supported_market_distribution().model_dump(mode="json")
    residual = next(item for item in body["market_residuals"] if item["event"] == event.value)
    residual.update(
        {
            "projected_probability": "0.900000000000",
            "residual": "0.100000000000",
            "standardized_residual": "0.500000",
            "target_probability": "0.800000000000",
        }
    )
    unhashed = dict(body)
    unhashed.pop("result_sha256")
    body["result_sha256"] = canonical_json_sha256(unhashed)
    with pytest.raises(ValidationError, match="projected_probability"):
        JointScoreDistribution.model_validate(body)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda body: body["market_residuals"][0].update(standardized_residual="9.000000"),
            "standardized_residual",
        ),
        (
            lambda body: body["diagnostics"].update(market_rmse="0.900000000000"),
            "market_rmse",
        ),
        (
            lambda body: body["diagnostics"].update(
                maximum_absolute_market_residual="0.900000000000"
            ),
            "maximum_absolute_market_residual",
        ),
    ],
)
def test_market_fit_aggregate_diagnostics_are_recomputed(mutate, match: str) -> None:
    body = _body()
    mutate(body)
    unhashed = dict(body)
    unhashed.pop("result_sha256")
    body["result_sha256"] = canonical_json_sha256(unhashed)
    with pytest.raises(ValidationError, match=match):
        JointScoreDistribution.model_validate(body)


def test_frozen_model_copy_revalidates_updates() -> None:
    model = OneXTwoDistribution.model_validate(
        {
            "home_win": "0.400000000000",
            "draw": "0.300000000000",
            "away_win": "0.300000000000",
        }
    )
    assert model.model_copy(deep=True) == model
    with pytest.raises(ValidationError):
        model.model_copy(update={"home_win": "0.500000000000"})


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda body: body.update(fixture_id="not-a-uuid"), "fixture_id"),
        (
            lambda body: body.update(information_cutoff="2026-08-20T11:59:00Z"),
            "identical",
        ),
        (
            lambda body: body.update(source_minutes_context_sha256="0" * 64),
            "source_minutes_context_sha256",
        ),
        (
            lambda body: body["source_minutes_context"]["home"].update(result_sha256="0" * 64),
            "source_minutes_context_sha256",
        ),
        (
            lambda body: body["source_minutes_context"]["away"].update(
                team_id=body["home_team_id"]
            ),
            "distinct teams",
        ),
        (lambda body: body.update(probabilities=body["probabilities"][:-1]), "height"),
        (
            lambda body: body["probabilities"].__setitem__(0, body["probabilities"][0][:-1]),
            "width",
        ),
        (
            lambda body: body["probabilities"][0].__setitem__(0, "0.000000000000"),
            "sum exactly",
        ),
        (lambda body: body.update(home_goal_pmf=body["home_goal_pmf"][:-1]), "home_goal_pmf"),
        (lambda body: body.update(away_goal_pmf=body["away_goal_pmf"][:-1]), "away_goal_pmf"),
        (
            lambda body: body["home_goal_pmf"].__setitem__(0, "0.999999999999"),
            "PMFs",
        ),
        (lambda body: body.update(expected_away_goals="9.000000"), "expected_away"),
        (
            lambda body: body.update(
                one_x_two={
                    "home_win": "0.333333333334",
                    "draw": "0.333333333333",
                    "away_win": "0.333333333333",
                }
            ),
            "1X2",
        ),
        (
            lambda body: body["total_goals"][0].update(
                under=body["total_goals"][0]["over"],
                over=body["total_goals"][0]["under"],
            ),
            "total-goals",
        ),
        (
            lambda body: body.update(top_scorelines=list(reversed(body["top_scorelines"]))),
            "top_scorelines",
        ),
        (
            lambda body: body.update(confidence_reasons=["TAIL_RENORMALISED", "TAIL_RENORMALISED"]),
            "unique",
        ),
        (
            lambda body: body["diagnostics"].update(constraint_count=999),
            "constraint_count",
        ),
    ],
)
def test_joint_distribution_detects_public_identity_mutations(mutate, match: str) -> None:
    body = _body()
    # JSON-loaded rows are mutable lists, matching the public transport boundary.
    mutate(body)
    with pytest.raises(ValidationError, match=match):
        JointScoreDistribution.model_validate(body)


def test_coerce_sequence_non_mapping_path_is_rejected_by_model() -> None:
    with pytest.raises(ValidationError):
        JointScoreDistribution.model_validate("not-an-object")


def test_confidence_policy_covers_degraded_low_confidence_and_residual_states() -> None:
    empty = MarketConstraintSet.model_validate(
        {"as_of": datetime(2026, 8, 20, 12, tzinfo=UTC), "constraints": ()}
    )
    prior = ProjectionResult(
        status="DEGRADED",
        probabilities=((Decimal(1),),),
        iterations=1,
        converged=False,
        dual_objective=Decimal(0),
        prior_to_projected_kl=Decimal(0),
        projected_market_probabilities=(),
        error_code="PROJECTION_DID_NOT_CONVERGE",
    )
    assert _confidence(prior, empty, Decimal(0))[0] == "D"
    request = load_score_distribution_request(FIXTURE)
    constrained = MarketConstraintSet.model_validate(
        {"as_of": request.as_of, "constraints": request.constraints}
    )
    projected = ProjectionResult(
        status="PROJECTED",
        probabilities=((Decimal(1),),),
        iterations=1,
        converged=True,
        dual_objective=Decimal(0),
        prior_to_projected_kl=Decimal(0),
        projected_market_probabilities=(),
        error_code=None,
    )
    low = constrained.model_copy(
        update={
            "constraints": tuple(
                item.model_copy(update={"confidence_grade": "C"})
                for item in constrained.constraints
            )
        }
    )
    grade, reasons = _confidence(projected, low, Decimal("0.04"))
    assert grade == "C"
    assert "LOW_MARKET_CONFIDENCE" in reasons
    assert "MARKET_RESIDUAL_HIGH" in reasons


def test_compose_rejects_invalid_identity_and_output_configuration() -> None:
    request = load_score_distribution_request(FIXTURE)
    prior = build_score_prior(
        request.prior.home_goal_rate,
        request.prior.away_goal_rate,
        minimum_max_goals=6,
        maximum_max_goals=18,
        tail_tolerance=Decimal("1e-10"),
        hard_tail_limit=Decimal("1e-8"),
    )
    projection = ProjectionResult(
        status="PRIOR_ONLY",
        probabilities=prior.grid.probabilities,
        iterations=0,
        converged=True,
        dual_objective=Decimal(0),
        prior_to_projected_kl=Decimal(0),
        projected_market_probabilities=(),
        error_code=None,
    )
    empty = MarketConstraintSet.model_validate({"as_of": request.as_of, "constraints": ()})
    common = {
        "fixture_id": str(request.fixture_id),
        "home_team_id": str(request.home_team_id),
        "away_team_id": str(request.away_team_id),
        "as_of": "2026-08-20T12:00:00Z",
        "minutes_context": request.minutes_context,
        "prior": prior,
        "projection": projection,
        "constraint_set": empty,
        "total_lines": (Decimal("2.5"),),
        "top_scoreline_count": 5,
    }
    with pytest.raises(ValueError, match="input_signature"):
        compose_joint_score_distribution(
            input_signature_sha256="bad",
            policy_sha256="a" * 64,
            **common,
        )
    with pytest.raises(ValueError, match="policy_sha256"):
        compose_joint_score_distribution(
            input_signature_sha256="a" * 64,
            policy_sha256="bad",
            **common,
        )
    with pytest.raises(ValueError, match="top_scoreline_count"):
        compose_joint_score_distribution(
            input_signature_sha256="a" * 64,
            policy_sha256="b" * 64,
            **dict(common, top_scoreline_count=0),
        )
    with pytest.raises(ValueError, match="half-goal"):
        compose_joint_score_distribution(
            input_signature_sha256="a" * 64,
            policy_sha256="b" * 64,
            **dict(common, total_lines=(Decimal("2.25"),)),
        )


def test_joint_output_detects_stage7_lineage_and_btts_mutation() -> None:
    body = _body()
    body["source_minutes_as_of"] = "2026-08-20T12:00:01Z"
    with pytest.raises(ValidationError, match="POST_CUTOFF_MINUTES"):
        JointScoreDistribution.model_validate(body)

    body = _body()
    body["home_goals_conceded_pmf"][0] = "0.999999999999"
    with pytest.raises(ValidationError, match="goals-conceded"):
        JointScoreDistribution.model_validate(body)

    body = _body()
    body["both_teams_to_score"] = {
        "yes": body["both_teams_to_score"]["no"],
        "no": body["both_teams_to_score"]["yes"],
    }
    with pytest.raises(ValidationError, match="BTTS"):
        JointScoreDistribution.model_validate(body)
