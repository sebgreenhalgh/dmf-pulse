from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketFamily,
    ScoreEvent,
    constraints_from_market_consensus,
    event_matches,
)

pytestmark = pytest.mark.unit
AS_OF = datetime(2026, 8, 20, 12, tzinfo=UTC)
FIXTURE_ID = "10000000-0000-7000-8000-000000000808"


def _make(event: ScoreEvent, family: MarketFamily, **extra):
    data = {
        "constraint_id": f"{family.value}-{event.value}",
        "family": family,
        "event": event,
        "target_probability": Decimal("0.5"),
        "uncertainty": Decimal("0.02"),
        "weight": Decimal(1),
        "usable_at": AS_OF,
    }
    data.update(extra)
    return MarketConstraint.model_validate(data)


def test_all_supported_event_indicators_have_explicit_semantics() -> None:
    cases = [
        (_make(ScoreEvent.TOTAL_OVER, MarketFamily.TOTALS, line=Decimal("2.5")), 2, 1, True),
        (_make(ScoreEvent.TOTAL_UNDER, MarketFamily.TOTALS, line=Decimal("2.5")), 1, 1, True),
        (
            _make(
                ScoreEvent.HOME_TEAM_TOTAL_OVER,
                MarketFamily.TEAM_TOTAL,
                line=Decimal("1.5"),
            ),
            2,
            0,
            True,
        ),
        (
            _make(
                ScoreEvent.HOME_TEAM_TOTAL_UNDER,
                MarketFamily.TEAM_TOTAL,
                line=Decimal("1.5"),
            ),
            1,
            3,
            True,
        ),
        (
            _make(
                ScoreEvent.AWAY_TEAM_TOTAL_OVER,
                MarketFamily.TEAM_TOTAL,
                line=Decimal("0.5"),
            ),
            0,
            1,
            True,
        ),
        (
            _make(
                ScoreEvent.AWAY_TEAM_TOTAL_UNDER,
                MarketFamily.TEAM_TOTAL,
                line=Decimal("1.5"),
            ),
            4,
            1,
            True,
        ),
        (_make(ScoreEvent.HOME_CLEAN_SHEET, MarketFamily.CLEAN_SHEET), 3, 0, True),
        (_make(ScoreEvent.AWAY_CLEAN_SHEET, MarketFamily.CLEAN_SHEET), 0, 2, True),
        (_make(ScoreEvent.BTTS_YES, MarketFamily.BTTS), 1, 1, True),
        (_make(ScoreEvent.BTTS_NO, MarketFamily.BTTS), 0, 3, True),
        (
            _make(
                ScoreEvent.EXACT_SCORE,
                MarketFamily.CORRECT_SCORE,
                home_goals=2,
                away_goals=1,
            ),
            2,
            1,
            True,
        ),
    ]
    for constraint, home, away, expected in cases:
        assert event_matches(constraint, home, away) is expected
        assert isinstance(constraint.public_dict(), dict)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "event": ScoreEvent.TOTAL_OVER,
            "family": MarketFamily.TOTALS,
        },
        {
            "event": ScoreEvent.TOTAL_OVER,
            "family": MarketFamily.TOTALS,
            "line": Decimal("2.25"),
        },
        {
            "event": ScoreEvent.HOME_WIN,
            "family": MarketFamily.ONE_X_TWO,
            "line": Decimal("0.5"),
        },
        {
            "event": ScoreEvent.EXACT_SCORE,
            "family": MarketFamily.CORRECT_SCORE,
        },
        {
            "event": ScoreEvent.HOME_WIN,
            "family": MarketFamily.TOTALS,
        },
    ],
)
def test_invalid_market_semantics_are_rejected(payload: dict) -> None:
    data = {
        "constraint_id": "invalid",
        "target_probability": Decimal("0.5"),
        "uncertainty": Decimal("0.02"),
        "usable_at": AS_OF,
    }
    data.update(payload)
    with pytest.raises(ValidationError):
        MarketConstraint.model_validate(data)


def _valid_consensus() -> dict:
    return {
        "fixture_id": FIXTURE_ID,
        "as_of": "2026-08-20T11:59:00Z",
        "mapping_cutoff": "2026-08-20T11:58:00Z",
        "market_definition": "FULL_TIME_1X2",
        "provider_count": 1,
        "eligible_operator_count": 2,
        "freshness": {"minimum_age_seconds": 30, "maximum_age_seconds": 120},
        "market_disagreement": "0.010000000000",
        "confidence_grade": "A",
        "result_sha256": "d" * 64,
        "outcomes": [
            {
                "outcome": "HOME",
                "consensus_probability": "0.45",
                "lower_bound": "0.43",
                "upper_bound": "0.47",
            },
            {
                "outcome": "DRAW",
                "consensus_probability": "0.30",
                "lower_bound": "0.28",
                "upper_bound": "0.32",
            },
            {
                "outcome": "AWAY",
                "consensus_probability": "0.25",
                "lower_bound": "0.23",
                "upper_bound": "0.27",
            },
        ],
    }


def test_adapter_accepts_normalisation_result_wrapper() -> None:
    wrapped = {
        "status": "NORMALISED",
        "fixture_id": FIXTURE_ID,
        "as_of": "2026-08-20T12:00:00Z",
        "consensus": _valid_consensus(),
    }
    result = constraints_from_market_consensus(
        wrapped,
        fixture_id=FIXTURE_ID,
        as_of=AS_OF,
        uncertainty_floor=Decimal("0.005"),
    )
    assert len(result.constraints) == 3
    assert sum((item.weight for item in result.constraints), Decimal(0)) == Decimal(1)
    assert max(item.weight for item in result.constraints) - min(
        item.weight for item in result.constraints
    ) <= Decimal("0.000000000001")


def test_adapter_rejects_post_cutoff_outer_normalisation_result() -> None:
    wrapped = {
        "status": "NORMALISED",
        "fixture_id": FIXTURE_ID,
        "as_of": "2026-08-20T12:00:01Z",
        "consensus": _valid_consensus(),
    }
    with pytest.raises(ValueError, match="POST_CUTOFF_MARKET"):
        constraints_from_market_consensus(
            wrapped,
            fixture_id=FIXTURE_ID,
            as_of=AS_OF,
            uncertainty_floor=Decimal("0.005"),
        )


@pytest.mark.parametrize(
    ("outer_as_of", "match"),
    [
        (None, "requires fixture_id and as_of"),
        ("2026-08-20T12:00:00", "RFC3339 UTC"),
        ("2026-08-20T11:58:59Z", "timestamp envelope is inconsistent"),
    ],
)
def test_adapter_rejects_malformed_or_inconsistent_outer_timestamp_envelope(
    outer_as_of: str | None,
    match: str,
) -> None:
    wrapped = {
        "status": "NORMALISED",
        "fixture_id": FIXTURE_ID,
        "as_of": outer_as_of,
        "consensus": _valid_consensus(),
    }
    with pytest.raises(ValueError, match=match):
        constraints_from_market_consensus(
            wrapped,
            fixture_id=FIXTURE_ID,
            as_of=AS_OF,
            uncertainty_floor=Decimal("0.005"),
        )


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (lambda value: value.update(market_definition="ANYTIME_SCORER"), "FULL_TIME_1X2"),
        (lambda value: value.update(result_sha256="bad"), "result_sha256"),
        (lambda value: value.update(confidence_grade="E"), "confidence"),
        (lambda value: value.update(outcomes=[]), "three"),
        (
            lambda value: value["outcomes"][0].update(lower_bound="0.50"),
            "outside its bounds",
        ),
        (
            lambda value: value["outcomes"][1].update(outcome="HOME"),
            "duplicated",
        ),
    ],
)
def test_adapter_fails_closed_on_malformed_consensus(mutator, match: str) -> None:
    value = _valid_consensus()
    mutator(value)
    with pytest.raises(ValueError, match=match):
        constraints_from_market_consensus(
            value,
            fixture_id=FIXTURE_ID,
            as_of=AS_OF,
            uncertainty_floor=Decimal("0.005"),
        )


def test_adapter_rejects_mapping_cutoff_after_consensus_as_of() -> None:
    payload = _valid_consensus()
    payload["mapping_cutoff"] = "2026-08-20T12:00:01Z"
    with pytest.raises(ValueError, match="mapping_cutoff is after"):
        constraints_from_market_consensus(
            payload,
            fixture_id=FIXTURE_ID,
            as_of=AS_OF,
            uncertainty_floor=Decimal("0.005"),
        )


def test_adapter_rejects_nonpositive_operator_count() -> None:
    payload = _valid_consensus()
    payload["eligible_operator_count"] = 0
    with pytest.raises(ValueError, match="eligible_operator_count must be positive"):
        constraints_from_market_consensus(
            payload,
            fixture_id=FIXTURE_ID,
            as_of=AS_OF,
            uncertainty_floor=Decimal("0.005"),
        )


def test_adapter_rejects_result_without_usable_consensus() -> None:
    with pytest.raises(ValueError, match="no usable consensus"):
        constraints_from_market_consensus(
            {"status": "BLOCKED", "fixture_id": FIXTURE_ID, "consensus": None},
            fixture_id=FIXTURE_ID,
            as_of=AS_OF,
            uncertainty_floor=Decimal("0.005"),
        )
