"""Stage-15 rank, effective-ownership and competition-utility package."""

from dmf_pulse.rank_strategy.effective_ownership import calculate_effective_ownership
from dmf_pulse.rank_strategy.manager_multipliers import (
    calculate_manager_multipliers,
    raw_projection_hash,
    shared_scenario_set_hash,
)
from dmf_pulse.rank_strategy.models import (
    CohortKind,
    CohortMember,
    CohortSample,
    EffectiveOwnershipReport,
    ManagerChip,
    ManagerMultiplierPolicy,
    ManagerMultiplierSet,
    ManagerTeamPlan,
    PlayerOwnership,
    SampleRightsStatus,
    ScenarioManagerMultiplier,
)

__all__ = [
    "CohortKind",
    "CohortMember",
    "CohortSample",
    "EffectiveOwnershipReport",
    "ManagerChip",
    "ManagerMultiplierPolicy",
    "ManagerMultiplierSet",
    "ManagerTeamPlan",
    "PlayerOwnership",
    "SampleRightsStatus",
    "ScenarioManagerMultiplier",
    "calculate_effective_ownership",
    "calculate_manager_multipliers",
    "raw_projection_hash",
    "shared_scenario_set_hash",
]
