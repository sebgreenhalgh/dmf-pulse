"""Pure human rendering for the private transfer-count frontier."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from dmf_pulse.private_v1.models import (
    PrivateTransferFrontier,
    PrivateTransferFrontierDelta,
    PrivateTransferFrontierPoint,
    PrivateTransferMove,
)


def _move(value: PrivateTransferMove, *, label: Callable[[str], str]) -> str:
    return f"{label(value.player_out_id)} -> {label(value.player_in_id)}"


def _delta(
    value: PrivateTransferFrontierDelta,
    *,
    label: Callable[[str], str],
) -> str:
    heading = (
        f"FRONTIER DELTA VS BEST {value.lower_transfer_count}-TRANSFER PLAN: "
        f"{value.immediate_expected_points_delta:+.2f}"
    )
    if value.plan_relationship == "NON_NESTED":
        return (
            f"{heading}\n"
            "PLANS ARE NON-NESTED. THIS FRONTIER DELTA IS NOT ATTRIBUTABLE TO "
            "A SPECIFIC TRANSFER."
        )
    moves = ", ".join(_move(item, label=label) for item in value.nested_incremental_transfers)
    return f"{heading}\nStrict-extension incremental move(s): {moves}"


def _point(
    value: PrivateTransferFrontierPoint,
    *,
    delta: PrivateTransferFrontierDelta | None,
    label: Callable[[str], str],
) -> str:
    heading = (
        "0 TRANSFERS - HOLD"
        if value.transfer_count == 0
        else f"{value.transfer_count} TRANSFER{'S' if value.transfer_count != 1 else ''}"
    )
    transfers = (
        "HOLD"
        if not value.transfers
        else "\n".join(f"- {_move(item, label=label)}" for item in value.transfers)
    )
    tactics = value.tactics
    free_transfers = value.free_transfer_state
    bank = Decimal(value.bank_after_tenths) / Decimal(10)
    delta_text = "" if delta is None else f"\n{_delta(delta, label=label)}"
    squad = ", ".join(label(item) for item in value.resulting_squad)
    xi = ", ".join(label(item) for item in tactics.starting_xi)
    bench = ", ".join(
        (
            label(tactics.bench_goalkeeper),
            *(label(item) for item in tactics.bench_outfield_order),
        )
    )
    return (
        f"{heading}\n"
        f"Transfers:\n{transfers}\n"
        f"Expected points after hit: {value.comparison_vs_hold.plan_expected_points_after_hit:.2f}\n"
        f"Uplift vs hold: {value.comparison_vs_hold.expected_uplift:+.2f}\n"
        f"Paired gain p10 / median / p90: {value.comparison_vs_hold.gain_p10} / "
        f"{value.comparison_vs_hold.gain_median} / {value.comparison_vs_hold.gain_p90}\n"
        f"P(plan beats hold): {value.comparison_vs_hold.probability_plan_beats_hold:.1%}\n"
        f"Transfer hit: -{value.comparison_vs_hold.transfer_hit_points}\n"
        f"Bank after action: {bank:.1f}\n"
        f"FT before action (manager / effective): {free_transfers.manager_state_before} / "
        f"{free_transfers.effective_before_action}\n"
        f"FT used / paid: {free_transfers.used_by_action} / {free_transfers.paid_transfers}\n"
        "FT remaining immediately after action: "
        f"{free_transfers.remaining_immediately_after_action}\n"
        f"FT grant for next deadline: {free_transfers.granted_for_next_deadline}\n"
        f"FT at next decision deadline: {free_transfers.next_decision_deadline}\n"
        f"Resulting squad: {squad}\n"
        f"Formation: {'-'.join(str(item) for item in value.formation)}\n"
        f"XI: {xi}\n"
        f"Bench (GK, 1, 2, 3): {bench}\n"
        f"Captain: {label(tactics.captain)}\n"
        f"Vice-captain: {label(tactics.vice_captain)}\n"
        f"Action hash: {value.action_sha256}\n"
        f"Tactical plan hash: {value.tactical_plan_sha256}\n"
        f"Stage-11 plan hash: {value.stage11_plan_sha256}"
        f"{delta_text}"
    )


def render_transfer_frontier(
    frontier: PrivateTransferFrontier | None,
    *,
    label: Callable[[str], str],
) -> str:
    """Render only structured frontier values; perform no optimisation or FT arithmetic."""

    if frontier is None:
        return ""
    delta_by_higher_count = {item.higher_transfer_count: item for item in frontier.deltas}
    points = "\n\n".join(
        _point(
            item,
            delta=delta_by_higher_count.get(item.transfer_count),
            label=label,
        )
        for item in frontier.points
    )
    return (
        "TRANSFER FRONTIER\n"
        f"{points}\n\n"
        "FRONTIER GOVERNANCE\n"
        f"Search scope: {frontier.action_space_disclosure}\n"
        f"Stage-9 projection hash: {frontier.stage9_projection_sha256}\n"
        f"Stage-9 joint-scenario hash: {frontier.stage9_joint_scenario_sha256}\n"
        f"Stage-11 request hash: {frontier.optimiser_request_sha256}\n"
        f"Stage-11 result hash: {frontier.optimiser_result_sha256}\n"
        f"Candidate-action policy hash: {frontier.candidate_action_policy_sha256}\n"
        "FUTURE FREE-TRANSFER VALUE IS NOT INCLUDED.\n"
        "CURRENT OBJECTIVE REMAINS ONE_GAMEWEEK_ZERO_TERMINAL_VALUE_OBJECTIVE."
    )


__all__ = ["render_transfer_frontier"]
