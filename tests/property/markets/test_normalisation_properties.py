"""Property invariants for frozen exact Decimal normalisation and consensus."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, getcontext, localcontext
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.markets import (
    MarketOutcome,
    MarketState,
    NormalisationMethod,
    build_market_consensus,
    load_market_normalisation_policy,
    normalise_complete_market,
    raw_implied_probability,
)
from dmf_pulse.markets.consensus import evaluate_market_consensus
from dmf_pulse.markets.models import ExclusiveOutcomeQuote

pytestmark = pytest.mark.property

AS_OF = datetime(2026, 8, 20, 12, 5, tzinfo=UTC)
SCALE = Decimal("0.000000000001")
ODDS = st.decimals(
    min_value=Decimal("1.01"),
    max_value=Decimal("50.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


def _uuid(group: int, value: int) -> UUID:
    return UUID(f"00000000-0000-7000-{group:04x}-{value:012d}")


def _quotes(
    odds: tuple[Decimal, Decimal, Decimal],
    *,
    operator: int,
    age_seconds: int = 60,
) -> tuple[ExclusiveOutcomeQuote, ExclusiveOutcomeQuote, ExclusiveOutcomeQuote]:
    observed_at = AS_OF - timedelta(seconds=age_seconds)
    book_observation_id = _uuid(0x8500, operator)
    rows = tuple(
        ExclusiveOutcomeQuote(
            fixture_id=_uuid(0x8000, 1),
            market_id=_uuid(0x8100, operator),
            selection_id=_uuid(0x8200, operator * 10 + index),
            operator_id=_uuid(0x8300, operator),
            outcome=outcome,
            decimal_odds=format(odds[index], "f"),
            observed_at=observed_at,
            received_at=observed_at,
            usable_at=observed_at,
            source_snapshot_id=_uuid(0x8400, operator * 10 + index),
            market_state=MarketState.COMPLETE,
            contract_version="the-odds-api-v4-reference-v1",
            book_observation_id=book_observation_id,
            odds_observation_id=_uuid(0x8600, operator * 10 + index),
            provider_id=_uuid(0x8700, 1),
            operator_key=f"book_{operator}",
        )
        for index, outcome in enumerate(MarketOutcome)
    )
    return rows[0], rows[1], rows[2]


@settings(max_examples=40, deadline=None)
@given(
    odds=st.tuples(ODDS, ODDS, ODDS),
    permutation=st.permutations((0, 1, 2)),
)
def test_power_output_is_an_exact_deterministic_public_simplex(
    odds: tuple[Decimal, Decimal, Decimal], permutation: list[int]
) -> None:
    policy = load_market_normalisation_policy()
    quotes = _quotes(odds, operator=1)
    original_context = getcontext().copy()
    first = normalise_complete_market(quotes, NormalisationMethod.POWER, policy)
    after_call = getcontext().copy()
    reordered = normalise_complete_market(
        tuple(quotes[index] for index in permutation),
        NormalisationMethod.POWER,
        policy,
    )

    assert (
        after_call.prec,
        after_call.rounding,
        after_call.flags,
        after_call.traps,
    ) == (
        original_context.prec,
        original_context.rounding,
        original_context.flags,
        original_context.traps,
    )
    assert first == reordered
    assert sum(row.market_probability for row in first.outcomes) == Decimal(1)
    assert sum(row.proportional_probability for row in first.outcomes) == Decimal(1)
    assert all(
        value == value.quantize(SCALE)
        for row in first.outcomes
        for value in (
            row.raw_implied_probability,
            row.proportional_probability,
            row.market_probability,
        )
    )
    assert all(row.market_probability >= 0 for row in first.outcomes)
    assert all(row.proportional_probability > 0 for row in first.outcomes)
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_EVEN
        expected_raw = [raw_implied_probability(value).quantize(SCALE) for value in odds]
    assert [row.raw_implied_probability for row in first.outcomes] == expected_raw
    assert [format(row.decimal_odds, ".2f") for row in first.outcomes] == [
        format(value, ".2f") for value in odds
    ]


@settings(max_examples=30, deadline=None)
@given(odds=st.tuples(ODDS, ODDS, ODDS))
def test_proportional_primary_equals_the_retained_baseline(
    odds: tuple[Decimal, Decimal, Decimal],
) -> None:
    result = normalise_complete_market(
        _quotes(odds, operator=1),
        NormalisationMethod.PROPORTIONAL,
        load_market_normalisation_policy(),
    )
    assert result.primary_method is NormalisationMethod.PROPORTIONAL
    assert result.fallback_used is False
    assert result.power_exponent is None
    assert [row.market_probability for row in result.outcomes] == [
        row.proportional_probability for row in result.outcomes
    ]
    assert sum(row.market_probability for row in result.outcomes) == Decimal(1)


@settings(max_examples=25, deadline=None)
@given(
    first_odds=st.tuples(ODDS, ODDS, ODDS),
    second_odds=st.tuples(ODDS, ODDS, ODDS),
)
def test_consensus_is_equal_operator_weighted_and_order_independent(
    first_odds: tuple[Decimal, Decimal, Decimal],
    second_odds: tuple[Decimal, Decimal, Decimal],
) -> None:
    observations = (
        *_quotes(first_odds, operator=1, age_seconds=60),
        *_quotes(second_odds, operator=2, age_seconds=120),
    )
    policy = load_market_normalisation_policy()
    first = build_market_consensus(
        observations,
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=policy,
    )
    second = build_market_consensus(
        tuple(reversed(observations)),
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=policy,
    )

    assert first == second
    assert first.operator_count == 2
    assert first.provider_count == 1
    assert sum(row.consensus_probability for row in first.outcomes) == Decimal(1)
    for index, outcome in enumerate(first.outcomes):
        public_mean = sum(
            market.outcomes[index].market_probability for market in first.operator_markets
        ) / Decimal(2)
        assert abs(outcome.consensus_probability - public_mean) <= SCALE
        assert outcome.lower_bound <= outcome.consensus_probability <= outcome.upper_bound


def test_extreme_power_bracket_failure_is_typed_fallback_and_caps_confidence() -> None:
    odds = (Decimal("1.0001"), Decimal("1.0001"), Decimal("1.0001"))
    observations = tuple(
        quote
        for operator in range(1, 4)
        for quote in _quotes(odds, operator=operator, age_seconds=1)
    )
    evaluation = evaluate_market_consensus(
        observations,
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=load_market_normalisation_policy(),
    )
    assert evaluation.consensus is not None
    assert evaluation.warnings == (
        "POWER_FALLBACK_DIAGNOSTIC:POWER_BRACKET_EXCEEDED",
        "POWER_FALLBACK_PROPORTIONAL",
    )
    assert evaluation.consensus.confidence_grade == "C"
    assert all(market.fallback_used for market in evaluation.consensus.operator_markets)
    assert all(
        outcome.market_probability == outcome.proportional_probability
        for market in evaluation.consensus.operator_markets
        for outcome in market.outcomes
    )


def test_underround_uses_the_lower_power_bracket_and_preserves_symmetry() -> None:
    result = normalise_complete_market(
        _quotes((Decimal("4.00"), Decimal("4.00"), Decimal("4.00")), operator=1),
        NormalisationMethod.POWER,
        load_market_normalisation_policy(),
    )
    assert result.power_exponent is not None
    assert Decimal(0) < result.power_exponent < Decimal(1)
    assert [row.market_probability for row in result.outcomes] == [
        Decimal("0.333333333334"),
        Decimal("0.333333333333"),
        Decimal("0.333333333333"),
    ]
