from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.optimisation.autosub_evaluator import canonical_weight_token, weight_fraction


@settings(max_examples=100, deadline=None, derandomize=True)
@given(st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False))
def test_weight_token_round_trips_exactly(weight: float) -> None:
    assert float(weight_fraction(weight)) == float(canonical_weight_token(weight))
