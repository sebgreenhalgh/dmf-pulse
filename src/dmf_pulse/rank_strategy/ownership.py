"""Saved-team ownership and multiplier diagnostics."""

from __future__ import annotations

from dmf_pulse.rank_strategy.models import ManagerChip, ManagerMultiplierPolicy, ManagerTeamPlan


def saved_multiplier(
    plan: ManagerTeamPlan,
    player_id: str,
    *,
    ordinary_captain_multiplier: int,
    policy: ManagerMultiplierPolicy,
) -> int:
    """Return the saved counted multiplier before appearance/autosub uncertainty."""

    tactic = plan.tactical_configuration
    if plan.active_chip is ManagerChip.BENCH_BOOST:
        multiplier = int(player_id in plan.active_squad)
    else:
        multiplier = int(player_id in tactic.starting_xi)
    if player_id == tactic.captain:
        target = (
            policy.triple_captain_multiplier
            if plan.active_chip is ManagerChip.TRIPLE_CAPTAIN
            else ordinary_captain_multiplier
        )
        multiplier += target - 1
    return multiplier


def is_bench_player(plan: ManagerTeamPlan, player_id: str) -> bool:
    tactic = plan.tactical_configuration
    return player_id in {tactic.bench_goalkeeper, *tactic.bench_order}
