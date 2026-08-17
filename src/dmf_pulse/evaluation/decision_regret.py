"""Decision regret and transfer-value accounting, separate from forecast error."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from dmf_pulse.evaluation.artifacts import seal
from dmf_pulse.evaluation.models import (
    ComparatorInformationSet,
    DecisionRegret,
)


def calculate_decision_regret(
    *,
    decision_id: str,
    comparator_id: str,
    realised_decision_utility: Decimal,
    realised_comparator_utility: Decimal,
    transfer_hit_points: Decimal = Decimal(0),
    no_transfer_utility: Decimal | None = None,
    horizon_gameweeks: int = 1,
    outcome_convention: Literal["REALISED_PATH", "COUNTERFACTUAL_PATH"] = "REALISED_PATH",
    comparator_information_set: ComparatorInformationSet = (
        ComparatorInformationSet.SAME_HISTORICAL_INFORMATION
    ),
) -> DecisionRegret:
    """Calculate regret from utilities that already include any declared hit charge."""

    if transfer_hit_points < 0:
        raise ValueError("transfer hit points must be non-negative")
    hit_adjusted = (
        realised_decision_utility - no_transfer_utility if no_transfer_utility is not None else None
    )
    value = DecisionRegret(
        decision_id=decision_id,
        comparator_id=comparator_id,
        comparator_information_set=comparator_information_set,
        comparator_is_oracle=(
            comparator_information_set is ComparatorInformationSet.COUNTERFACTUAL_HINDSIGHT
        ),
        horizon_gameweeks=horizon_gameweeks,
        outcome_convention=outcome_convention,
        utilities_include_hit_costs=True,
        realised_decision_utility=realised_decision_utility,
        realised_comparator_utility=realised_comparator_utility,
        regret=realised_comparator_utility - realised_decision_utility,
        transfer_hit_points=transfer_hit_points,
        hit_adjusted_transfer_value=hit_adjusted,
        no_transfer_utility=no_transfer_utility,
        regret_sha256="0" * 64,
    )
    return seal(value, "regret_sha256")
