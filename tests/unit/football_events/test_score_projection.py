from datetime import UTC, datetime
from decimal import Decimal

import pytest

from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketConstraintSet,
    MarketFamily,
    ScoreEvent,
)
from dmf_pulse.football_events.score_prior import build_score_prior
from dmf_pulse.football_events.score_projection import (
    constraint_probabilities,
    project_to_markets,
)

pytestmark = pytest.mark.unit
AS_OF = datetime(2026, 8, 20, 12, tzinfo=UTC)


def _prior():
    return build_score_prior(
        Decimal("1.4"),
        Decimal("1.1"),
        minimum_max_goals=6,
        maximum_max_goals=18,
        tail_tolerance=Decimal("0.0000000001"),
        hard_tail_limit=Decimal("0.00000001"),
    )


def _set(sigma: str = "0.02") -> MarketConstraintSet:
    targets = (
        (ScoreEvent.HOME_WIN, "0.46"),
        (ScoreEvent.DRAW, "0.28"),
        (ScoreEvent.AWAY_WIN, "0.26"),
    )
    constraints = tuple(
        MarketConstraint.model_validate(
            {
                "confidence_grade": "B",
                "constraint_id": event.value.lower(),
                "event": event,
                "family": MarketFamily.ONE_X_TWO,
                "target_probability": Decimal(target),
                "uncertainty": Decimal(sigma),
                "usable_at": AS_OF,
                "weight": Decimal(1),
            }
        )
        for event, target in targets
    )
    return MarketConstraintSet.model_validate({"as_of": AS_OF, "constraints": constraints})


def test_soft_kl_projection_is_deterministic_and_normalized() -> None:
    kwargs = {
        "max_iterations": 80,
        "gradient_tolerance": Decimal("1e-18"),
        "line_search_min_step": Decimal("1e-12"),
        "allow_prior_fallback": True,
    }
    first = project_to_markets(_prior(), _set(), **kwargs)
    second = project_to_markets(_prior(), _set(), **kwargs)
    assert first == second
    assert first.status == "PROJECTED"
    assert first.converged
    assert sum((sum(row, Decimal(0)) for row in first.probabilities), Decimal(0)) == Decimal(1)
    assert first.prior_to_projected_kl > 0


def test_high_trust_synthetic_constraints_are_reproduced() -> None:
    result = project_to_markets(
        _prior(),
        _set("0.000001"),
        max_iterations=80,
        gradient_tolerance=Decimal("1e-20"),
        line_search_min_step=Decimal("1e-14"),
        allow_prior_fallback=False,
    )
    projected = constraint_probabilities(result.probabilities, _set("0.000001").constraints)
    targets = tuple(item.target_probability for item in _set("0.000001").constraints)
    maximum_error = max(
        abs(value - target) for value, target in zip(projected, targets, strict=True)
    )
    assert maximum_error < Decimal("1e-9")


def test_inconsistent_total_and_outcome_constraints_remain_soft() -> None:
    base = list(_set().constraints)
    base.append(
        MarketConstraint.model_validate(
            {
                "confidence_grade": "B",
                "constraint_id": "over-0.5-impossible-with-low-outcomes",
                "event": ScoreEvent.TOTAL_OVER,
                "family": MarketFamily.TOTALS,
                "line": Decimal("0.5"),
                "target_probability": Decimal("0.01"),
                "uncertainty": Decimal("0.01"),
                "usable_at": AS_OF,
                "weight": Decimal(1),
            }
        )
    )
    constraints = MarketConstraintSet.model_validate({"as_of": AS_OF, "constraints": tuple(base)})
    result = project_to_markets(
        _prior(),
        constraints,
        max_iterations=80,
        gradient_tolerance=Decimal("1e-18"),
        line_search_min_step=Decimal("1e-12"),
        allow_prior_fallback=True,
    )
    projected = constraint_probabilities(result.probabilities, constraints.constraints)
    assert result.status == "PROJECTED"
    assert projected[-1] > Decimal("0.01")
    maximum_error = max(
        abs(projected[index] - constraints.constraints[index].target_probability)
        for index in range(3)
    )
    assert maximum_error > 0


def test_nonconvergence_can_fail_closed_without_fallback() -> None:
    with pytest.raises(ArithmeticError, match="did not converge"):
        project_to_markets(
            _prior(),
            _set(),
            max_iterations=1,
            gradient_tolerance=Decimal("1e-40"),
            line_search_min_step=Decimal("1e-12"),
            allow_prior_fallback=False,
        )


def test_nonconvergence_uses_visible_prior_fallback_when_configured() -> None:
    result = project_to_markets(
        _prior(),
        _set(),
        max_iterations=1,
        gradient_tolerance=Decimal("1e-40"),
        line_search_min_step=Decimal("1e-12"),
        allow_prior_fallback=True,
    )
    assert result.status == "DEGRADED"
    assert result.error_code == "PROJECTION_DID_NOT_CONVERGE"
    assert result.probabilities == _prior().grid.probabilities
