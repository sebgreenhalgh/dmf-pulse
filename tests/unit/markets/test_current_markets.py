"""Positive current H2H, totals and constraint acceptance."""

from __future__ import annotations

import json
from decimal import Decimal

from dmf_pulse.football_events.market_constraints import MarketFamily, ScoreEvent
from dmf_pulse.markets.current import (
    CurrentMarketConstraintBundle,
    CurrentMarketConstraintService,
    CurrentMarketReadiness,
    current_market_constraint_bundle_sha256,
)

from .current_market_test_support import build_market_context


def test_two_target_fixtures_produce_ready_transient_constraints(repository_root, tmp_path) -> None:
    context, view, request, result = build_market_context(repository_root, tmp_path)

    assert result.target_gameweek == 2
    assert len(result.fixtures) == 2
    assert all(item.readiness is CurrentMarketReadiness.MARKET_READY for item in result.fixtures)
    assert all(item.h2h_consensus is not None for item in result.fixtures)
    assert all(len(item.totals_consensuses) == 2 for item in result.fixtures)
    assert all(
        sum((row.consensus_probability for row in item.h2h_consensus.outcomes), Decimal(0))
        == Decimal(1)
        for item in result.fixtures
        if item.h2h_consensus is not None
    )
    assert all(
        sum((row.consensus_probability for row in totals.outcomes), Decimal(0)) == Decimal(1)
        for item in result.fixtures
        for totals in item.totals_consensuses
    )
    assert all(
        {
            row.event
            for row in item.constraint_set.constraints
            if row.family is MarketFamily.ONE_X_TWO
        }
        == {ScoreEvent.HOME_WIN, ScoreEvent.DRAW, ScoreEvent.AWAY_WIN}
        for item in result.fixtures
    )
    assert all(
        sum(
            (
                row.weight
                for row in item.constraint_set.constraints
                if row.family is MarketFamily.TOTALS
            ),
            Decimal(0),
        )
        <= Decimal(1)
        for item in result.fixtures
    )
    assert result.runtime.persistence_performed is False
    assert result.runtime.database_write_performed is False
    assert result.runtime.network_called is False
    assert result.runtime.database_read_performed is False
    assert result.semantic_sha256 == current_market_constraint_bundle_sha256(result)
    assert CurrentMarketConstraintBundle.model_validate_json(result.model_dump_json()) == result
    assert (
        CurrentMarketConstraintService().verify(
            result,
            request,
            source=context.bundle,
            identity_view=view,
        )
        == result
    )


def test_extra_provider_event_is_ignored_and_summary_is_safe(repository_root, tmp_path) -> None:
    context, _view, _request, result = build_market_context(repository_root, tmp_path)
    summary = result.safe_summary()
    serialized = json.dumps(summary.model_dump(mode="json"), sort_keys=True)

    assert len(context.odds_input.events) == 3
    assert summary.fixture_count == 2
    assert summary.market_ready_count == 2
    assert summary.totals_line_count == 4
    assert context.identity_map.coverage.outside_target_provider_event_ids[0] not in serialized
    assert context.odds_input.events[0].provider_home_team not in serialized
    assert context.odds_input.events[0].provider_away_team not in serialized
    assert all(
        bookmaker.bookmaker_key not in serialized
        for bookmaker in context.odds_input.events[0].bookmakers
    )
    assert "decimal_price" not in serialized
    assert "manager" not in serialized.casefold()


def test_h2h_reuses_accepted_stage6_power_consensus(repository_root, tmp_path) -> None:
    _context, _view, _request, result = build_market_context(repository_root, tmp_path)
    for fixture in result.fixtures:
        consensus = fixture.h2h_consensus
        assert consensus is not None
        assert consensus.market_definition == "FULL_TIME_1X2"
        assert consensus.policy_id == "market-normalisation-v1"
        assert consensus.eligible_operator_count == 2
        assert all(
            operator.primary_method.value == "POWER" for operator in consensus.operator_markets
        )
        assert all(operator.raw_booksum > Decimal(1) for operator in consensus.operator_markets)


def test_totals_are_binary_power_normalised_with_exact_complements(
    repository_root, tmp_path
) -> None:
    _context, _view, _request, result = build_market_context(repository_root, tmp_path)
    for fixture in result.fixtures:
        assert tuple(item.line for item in fixture.totals_consensuses) == (
            Decimal("1.5"),
            Decimal("2.5"),
        )
        for totals in fixture.totals_consensuses:
            assert totals.market_definition == "FULL_TIME_TOTALS_HALF_GOAL"
            assert totals.eligible_operator_count == 2
            assert all(item.primary_method == "POWER" for item in totals.operator_markets)
            assert all(item.raw_booksum > Decimal(1) for item in totals.operator_markets)
            line_constraints = [
                row
                for row in fixture.constraint_set.constraints
                if row.family is MarketFamily.TOTALS and row.line == totals.line
            ]
            assert {row.event for row in line_constraints} == {
                ScoreEvent.TOTAL_OVER,
                ScoreEvent.TOTAL_UNDER,
            }
            assert sum((row.target_probability for row in line_constraints), Decimal(0)) == Decimal(
                1
            )
