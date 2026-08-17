"""Compatibility projection of the independent Stage-11 test oracle."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from dmf_pulse.optimisation.multi_gameweek_models import MultiGameweekOptimisationRequest
from tests.support.stage11_oracle import exhaustive_expected_oracle as _solve


@dataclass(frozen=True)
class OracleValue:
    expected_utility: Decimal
    root_action_signature: str


def exhaustive_expected_oracle(request: MultiGameweekOptimisationRequest) -> OracleValue:
    """Return the historical compact view of the test-owned oracle result."""

    outcome = _solve(request)
    return OracleValue(
        expected_utility=outcome.expected_score,
        root_action_signature=outcome.root_action_signature,
    )
