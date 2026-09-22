"""Real public Stage 8; synthetic current-market contracts; no network."""

from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from dmf_pulse.football_events.market_constraints import MarketFamily
from dmf_pulse.football_events.score_prior_request import ScorePriorRequest
from dmf_pulse.football_events.service import (
    ScoreDistributionService,
    load_score_distribution_request,
)
from dmf_pulse.private_v1.horizon_markets import build_future_market_evidence
from tests.unit.markets.current_market_test_support import (
    build_market_context,
    rehash_odds,
    rehash_unified_source,
)

RANGES = (
    ("strong_home", "2.600000", "0.650000"),
    ("weak_home", "0.700000", "2.350000"),
    ("balanced", "1.500000", "1.300000"),
    ("entrant", "0.900000", "1.850000"),
    ("low_total", "0.800000", "0.650000"),
    ("high_total", "2.600000", "2.100000"),
)
FIXTURE = Path("fixtures/events/score/GCS-008/balanced_fixture.json")


@pytest.mark.parametrize("case,home,away", RANGES)
@pytest.mark.parametrize("coverage", ["FULL", "H2H", "PRIOR"])
def test_real_stage8_realistic_two_world_market_matrix(case, home, away, coverage):
    request = load_score_distribution_request(FIXTURE)
    constraints = (
        request.constraints
        if coverage == "FULL"
        else tuple(row for row in request.constraints if row.family == MarketFamily.ONE_X_TWO)
        if coverage == "H2H"
        else ()
    )
    for world, rates in (
        ("LEAGUE_BASELINE", ("1.613158", "1.374561")),
        ("TEAM_STRENGTH_SHADOW", (home, away)),
    ):
        assert all(Decimal(0) < Decimal(rate) <= Decimal(8) for rate in rates)
        prior = ScorePriorRequest(
            model_family="INDEPENDENT_POISSON_V1",
            home_goal_rate=Decimal(rates[0]),
            away_goal_rate=Decimal(rates[1]),
        )
        with localcontext() as context:
            context.prec = 28
            result = ScoreDistributionService().project(
                request.model_copy(update={"prior": prior, "constraints": constraints})
            )
        assert result.status == "PROJECTED", (case, world, coverage)
        assert result.error_code is None and result.distribution is not None
        diagnostics = result.distribution.diagnostics
        assert diagnostics.constraint_count == len(constraints)
        if diagnostics.projection_status == "DEGRADED":
            assert diagnostics.solver_error_code == "PROJECTION_DID_NOT_CONVERGE"
            assert "NUMERICAL_FALLBACK_TO_PRIOR" in result.distribution.confidence_reasons
        else:
            assert diagnostics.solver_error_code is None


@pytest.mark.parametrize("status", ["POSTPONED", "CANCELLED", "ABANDONED"])
def test_legitimate_h2h_block_is_not_numeric_fallback(status):
    request = load_score_distribution_request(FIXTURE)
    constraints = tuple(row for row in request.constraints if row.family == MarketFamily.ONE_X_TWO)
    result = ScoreDistributionService().project(
        request.model_copy(update={"constraints": constraints, "fixture_status": status})
    )
    assert result.status == "BLOCKED" and result.distribution is None
    assert result.error_code == f"FIXTURE_{status}"


def test_totals_only_future_market_remains_governed_prior_only(repository_root, tmp_path):
    context, view, _request, _wrapped = build_market_context(repository_root, tmp_path)
    target = context.odds_input.events[0]
    books = tuple(book.model_copy(update={"markets": ()}) for book in target.bookmakers)
    assert any(book.totals_markets for book in books)
    event = target.model_copy(update={"bookmakers": books})
    odds = rehash_odds(context.odds_input, events=(event, context.odds_input.events[1]))
    source = rehash_unified_source(context, odds_input=odds)
    fixture = next(
        row
        for row in context.fpl_input.fixtures
        if row.provider_fixture_id == view.fixtures[0].official_fpl_fixture_id
    )
    evidence = build_future_market_evidence(
        source, fixture=fixture, canonical_fixture_id=view.fixtures[0].canonical_fixture_id
    )
    assert evidence.classification == "H2H_UNAVAILABLE"
    assert evidence.constraints == ()
    assert "FUTURE_MARKET_H2H_UNAVAILABLE" in evidence.warnings
