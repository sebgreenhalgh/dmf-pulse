from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketConstraintSet,
    MarketFamily,
    ScoreEvent,
    build_design_matrix,
    cap_market_family_weights,
    constraints_from_market_consensus,
    event_matches,
)
from dmf_pulse.football_events.service import load_score_distribution_request
from dmf_pulse.markets.models import (
    MarketConsensus,
    MarketNormalisationResult,
    NormalisationStatus,
)

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 8, 20, 12, tzinfo=UTC)
FIXTURE_ID = "10000000-0000-7000-8000-000000000808"
STAGE6_FIXTURE = Path("fixtures/events/score/GCS-008/stage6_consensus_fixture.json")


def _constraint(event: ScoreEvent, target: str) -> MarketConstraint:
    return MarketConstraint.model_validate(
        {
            "confidence_grade": "B",
            "constraint_id": event.value.lower(),
            "event": event,
            "family": MarketFamily.ONE_X_TWO,
            "target_probability": Decimal(target),
            "uncertainty": Decimal("0.02"),
            "usable_at": AS_OF,
            "weight": Decimal(1),
        }
    )


def test_market_design_rows_partition_score_space() -> None:
    constraints = (
        _constraint(ScoreEvent.HOME_WIN, "0.45"),
        _constraint(ScoreEvent.DRAW, "0.28"),
        _constraint(ScoreEvent.AWAY_WIN, "0.27"),
    )
    design = build_design_matrix(constraints, home_max=3, away_max=3)
    assert all(sum(design[row][cell] for row in range(3)) == 1 for cell in range(16))
    assert event_matches(constraints[0], 2, 1)
    assert event_matches(constraints[1], 2, 2)
    assert event_matches(constraints[2], 0, 3)


def test_impossible_one_x_two_state_is_rejected() -> None:
    with pytest.raises(ValidationError, match="sum exactly to one"):
        MarketConstraintSet.model_validate(
            {
                "as_of": AS_OF,
                "constraints": (
                    _constraint(ScoreEvent.HOME_WIN, "0.50"),
                    _constraint(ScoreEvent.DRAW, "0.30"),
                    _constraint(ScoreEvent.AWAY_WIN, "0.30"),
                ),
            }
        )


def test_post_cutoff_constraint_is_rejected() -> None:
    future = _constraint(ScoreEvent.HOME_WIN, "0.45").model_copy(
        update={"usable_at": datetime(2026, 8, 20, 13, tzinfo=UTC)}
    )
    with pytest.raises(ValidationError, match="POST_CUTOFF_MARKET"):
        MarketConstraintSet.model_validate(
            {
                "as_of": AS_OF,
                "constraints": (
                    future,
                    _constraint(ScoreEvent.DRAW, "0.28"),
                    _constraint(ScoreEvent.AWAY_WIN, "0.27"),
                ),
            }
        )


def test_stage6_consensus_adapter_preserves_hash_cutoff_and_bounds() -> None:
    source_hash = "1" * 64
    consensus = {
        "fixture_id": FIXTURE_ID,
        "as_of": "2026-08-20T11:59:00Z",
        "mapping_cutoff": "2026-08-20T11:58:00Z",
        "market_definition": "FULL_TIME_1X2",
        "provider_count": 1,
        "eligible_operator_count": 4,
        "freshness": {"minimum_age_seconds": 30, "maximum_age_seconds": 120},
        "market_disagreement": "0.010000000000",
        "confidence_grade": "B",
        "result_sha256": source_hash,
        "outcomes": [
            {
                "outcome": "HOME",
                "consensus_probability": "0.460000000000",
                "lower_bound": "0.440000000000",
                "upper_bound": "0.480000000000",
            },
            {
                "outcome": "DRAW",
                "consensus_probability": "0.280000000000",
                "lower_bound": "0.260000000000",
                "upper_bound": "0.300000000000",
            },
            {
                "outcome": "AWAY",
                "consensus_probability": "0.260000000000",
                "lower_bound": "0.240000000000",
                "upper_bound": "0.280000000000",
            },
        ],
    }
    result = constraints_from_market_consensus(
        consensus,
        fixture_id=FIXTURE_ID,
        as_of=AS_OF,
        uncertainty_floor=Decimal("0.005"),
    )
    assert result.source_result_sha256 == source_hash
    assert tuple(item.target_probability for item in result.constraints) == (
        Decimal("0.46"),
        Decimal("0.28"),
        Decimal("0.26"),
    )
    assert all(item.uncertainty == Decimal("0.02") for item in result.constraints)
    assert sum((item.weight for item in result.constraints), Decimal(0)) == Decimal("0.75")


def test_real_stage6_result_enforces_outer_and_nested_cutoffs() -> None:
    request = load_score_distribution_request(STAGE6_FIXTURE)
    assert isinstance(request.market_consensus, MarketConsensus)
    accepted = MarketNormalisationResult(
        status=NormalisationStatus.NORMALISED,
        fixture_id=request.fixture_id,
        as_of=AS_OF,
        consensus=request.market_consensus,
        excluded_books=(),
        warnings=(),
        error_code=None,
    )
    constraints = constraints_from_market_consensus(
        accepted,
        fixture_id=request.fixture_id,
        as_of=AS_OF,
        uncertainty_floor=Decimal("0.005"),
    )
    assert len(constraints.constraints) == 3

    post_cutoff = MarketNormalisationResult(
        status=NormalisationStatus.NORMALISED,
        fixture_id=request.fixture_id,
        as_of=datetime(2026, 8, 20, 12, 0, 1, tzinfo=UTC),
        consensus=request.market_consensus,
        excluded_books=(),
        warnings=(),
        error_code=None,
    )
    with pytest.raises(ValueError, match="POST_CUTOFF_MARKET"):
        constraints_from_market_consensus(
            post_cutoff,
            fixture_id=request.fixture_id,
            as_of=AS_OF,
            uncertainty_floor=Decimal("0.005"),
        )


def test_stage6_future_consensus_is_rejected() -> None:
    consensus = {
        "fixture_id": FIXTURE_ID,
        "as_of": "2026-08-20T12:01:00Z",
        "mapping_cutoff": "2026-08-20T12:01:00Z",
        "market_definition": "FULL_TIME_1X2",
        "provider_count": 1,
        "eligible_operator_count": 1,
        "freshness": {"minimum_age_seconds": 30, "maximum_age_seconds": 120},
        "market_disagreement": "0.010000000000",
        "confidence_grade": "D",
        "result_sha256": "2" * 64,
        "outcomes": [],
    }
    with pytest.raises(ValueError, match="POST_CUTOFF_MARKET"):
        constraints_from_market_consensus(
            consensus,
            fixture_id=FIXTURE_ID,
            as_of=AS_OF,
            uncertainty_floor=Decimal("0.005"),
        )


def test_stage6_consensus_for_another_fixture_is_rejected() -> None:
    consensus = {
        "fixture_id": "10000000-0000-7000-8000-000000000809",
        "as_of": "2026-08-20T11:59:00Z",
        "mapping_cutoff": "2026-08-20T11:58:00Z",
        "market_definition": "FULL_TIME_1X2",
        "provider_count": 1,
        "eligible_operator_count": 4,
        "freshness": {"minimum_age_seconds": 30, "maximum_age_seconds": 120},
        "market_disagreement": "0.010000000000",
        "confidence_grade": "B",
        "result_sha256": "3" * 64,
        "outcomes": [
            {
                "outcome": "HOME",
                "consensus_probability": "0.460000000000",
                "lower_bound": "0.440000000000",
                "upper_bound": "0.480000000000",
            },
            {
                "outcome": "DRAW",
                "consensus_probability": "0.280000000000",
                "lower_bound": "0.260000000000",
                "upper_bound": "0.300000000000",
            },
            {
                "outcome": "AWAY",
                "consensus_probability": "0.260000000000",
                "lower_bound": "0.240000000000",
                "upper_bound": "0.280000000000",
            },
        ],
    }
    with pytest.raises(ValueError, match="MARKET_FIXTURE_MISMATCH"):
        constraints_from_market_consensus(
            consensus,
            fixture_id=FIXTURE_ID,
            as_of=AS_OF,
            uncertainty_floor=Decimal("0.005"),
        )


def test_family_weight_caps_prevent_correlated_market_double_counting() -> None:
    raw = MarketConstraintSet.model_validate(
        {
            "as_of": AS_OF,
            "constraints": (
                _constraint(ScoreEvent.HOME_WIN, "0.45"),
                _constraint(ScoreEvent.DRAW, "0.28"),
                _constraint(ScoreEvent.AWAY_WIN, "0.27"),
            ),
        }
    )
    caps = {family: Decimal(1) for family in MarketFamily}
    capped = cap_market_family_weights(raw, caps)
    assert sum((item.weight for item in capped.constraints), Decimal(0)) == Decimal(1)
    assert max(item.weight for item in capped.constraints) - min(
        item.weight for item in capped.constraints
    ) <= Decimal("0.000000000001")


def test_family_weight_caps_require_a_complete_policy() -> None:
    raw = MarketConstraintSet.model_validate({"as_of": AS_OF, "constraints": ()})
    with pytest.raises(ValueError, match="every market family"):
        cap_market_family_weights(raw, {MarketFamily.ONE_X_TWO: Decimal(1)})


def test_stage6_disagreement_and_freshness_are_preserved_in_uncertainty() -> None:
    consensus = {
        "fixture_id": FIXTURE_ID,
        "as_of": "2026-08-20T11:59:00Z",
        "mapping_cutoff": "2026-08-20T11:58:00Z",
        "market_definition": "FULL_TIME_1X2",
        "provider_count": 2,
        "eligible_operator_count": 4,
        "freshness": {"minimum_age_seconds": 15, "maximum_age_seconds": 90},
        "market_disagreement": "0.040000000000",
        "confidence_grade": "B",
        "result_sha256": "4" * 64,
        "outcomes": [
            {
                "outcome": "HOME",
                "consensus_probability": "0.46",
                "lower_bound": "0.45",
                "upper_bound": "0.47",
            },
            {
                "outcome": "DRAW",
                "consensus_probability": "0.28",
                "lower_bound": "0.27",
                "upper_bound": "0.29",
            },
            {
                "outcome": "AWAY",
                "consensus_probability": "0.26",
                "lower_bound": "0.25",
                "upper_bound": "0.27",
            },
        ],
    }
    result = constraints_from_market_consensus(
        consensus,
        fixture_id=FIXTURE_ID,
        as_of=AS_OF,
        uncertainty_floor=Decimal("0.005"),
    )
    assert all(item.uncertainty == Decimal("0.04") for item in result.constraints)
    assert all(item.market_disagreement == Decimal("0.04") for item in result.constraints)
    assert all(item.maximum_age_seconds == 90 for item in result.constraints)
    assert all(item.provider_count == 2 for item in result.constraints)
