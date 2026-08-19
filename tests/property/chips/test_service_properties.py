from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.chips.service import evaluate_chip_opportunities
from dmf_pulse.chips.service_models import ChipDecisionAction, ChipServiceRequest
from tests.support.stage14_chip_fixtures import service_request


@settings(max_examples=50, deadline=None)
@given(
    current_left=st.integers(min_value=-10, max_value=20),
    current_right=st.integers(min_value=-10, max_value=20),
    future_left=st.integers(min_value=-10, max_value=20),
    future_right=st.integers(min_value=-10, max_value=20),
)
def test_service_roundtrip_is_semantically_deterministic(
    current_left: int,
    current_right: int,
    future_left: int,
    future_right: int,
) -> None:
    request = service_request(
        current_values={"TRIPLE_CAPTAIN": (float(current_left), float(current_right))},
        future_values={"TRIPLE_CAPTAIN": (float(future_left), float(future_right))},
    )

    first = evaluate_chip_opportunities(request)
    second = evaluate_chip_opportunities(
        ChipServiceRequest.model_validate_json(request.model_dump_json())
    )

    assert first == second
    assert first.decision_set_hash == second.decision_set_hash
    assert first.decision.recommended_action in {
        ChipDecisionAction.USE,
        ChipDecisionAction.WAIT,
        ChipDecisionAction.HOLD,
    }
    assert first.decision.probability_diagnostic.denominator_weight == 1.0
    assert 0.0 <= first.decision.probability_now_optimal <= 1.0


@settings(max_examples=40, deadline=None)
@given(
    base=st.integers(min_value=-5, max_value=10),
    increase=st.integers(min_value=0, max_value=15),
    future=st.integers(min_value=-5, max_value=15),
)
def test_raising_current_value_cannot_reduce_single_token_exercise_advantage(
    base: int,
    increase: int,
    future: int,
) -> None:
    before = evaluate_chip_opportunities(
        service_request(
            current_values={"TRIPLE_CAPTAIN": (float(base), float(base))},
            future_values={"TRIPLE_CAPTAIN": (float(future), float(future))},
        )
    )
    after = evaluate_chip_opportunities(
        service_request(
            current_values={"TRIPLE_CAPTAIN": (float(base + increase), float(base + increase))},
            future_values={"TRIPLE_CAPTAIN": (float(future), float(future))},
        )
    )

    assert after.decision.exercise_advantage >= before.decision.exercise_advantage


@settings(max_examples=30, deadline=None)
@given(value=st.integers(min_value=-20, max_value=-1))
def test_strictly_negative_current_and_future_values_produce_valid_hold(value: int) -> None:
    result = evaluate_chip_opportunities(
        service_request(
            current_values={"TRIPLE_CAPTAIN": (float(value), float(value))},
            future_values={"TRIPLE_CAPTAIN": (float(value), float(value))},
        )
    )

    assert result.decision.recommended_action is ChipDecisionAction.HOLD
    assert result.decision.selected_chip is None
