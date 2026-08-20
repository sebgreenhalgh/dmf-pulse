"""Stage-15 rank, effective-ownership and competition-utility package."""

from dmf_pulse.rank_strategy.effective_ownership import calculate_effective_ownership
from dmf_pulse.rank_strategy.manager_multipliers import (
    calculate_manager_multipliers,
    raw_projection_hash,
    shared_scenario_set_hash,
)
from dmf_pulse.rank_strategy.mini_league import simulate_mini_league_rank
from dmf_pulse.rank_strategy.models import (
    CohortKind,
    CohortMember,
    CohortSample,
    EffectiveOwnershipReport,
    ManagerChip,
    ManagerMultiplierPolicy,
    ManagerMultiplierSet,
    ManagerScenarioStanding,
    ManagerTeamPlan,
    MiniLeagueScenarioOutcome,
    PlayerOwnership,
    RankDistribution,
    RankMass,
    RankTiePolicy,
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
    "ManagerScenarioStanding",
    "ManagerTeamPlan",
    "MiniLeagueScenarioOutcome",
    "PlayerOwnership",
    "RankDistribution",
    "RankMass",
    "RankTiePolicy",
    "SampleRightsStatus",
    "ScenarioManagerMultiplier",
    "calculate_effective_ownership",
    "calculate_manager_multipliers",
    "raw_projection_hash",
    "shared_scenario_set_hash",
    "simulate_mini_league_rank",
]
