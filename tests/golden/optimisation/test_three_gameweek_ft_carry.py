from __future__ import annotations

from collections import Counter
from itertools import combinations

from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.optimisation.multi_gameweek_solver import resolve_free_transfer_arc
from tests.support.multi_gameweek_factories import (
    NodeSpec,
    base_squad,
    build_request,
    player_catalog,
)
from tests.support.multi_gameweek_oracle import exhaustive_expected_oracle


def _expanded_squads(
    starting: tuple[tuple[str, ...], ...],
    *,
    incoming: tuple[str, ...],
    maximum_transfers: int,
) -> tuple[tuple[str, ...], ...]:
    positions = {item.player_id: item.position for item in player_catalog(include_second_mid=True)}
    results = set(starting)
    for squad in starting:
        for count in range(1, maximum_transfers + 1):
            for transfer_in in combinations(incoming, count):
                required = Counter(positions[item] for item in transfer_in)
                for transfer_out in combinations(squad, count):
                    if Counter(positions[item] for item in transfer_out) != required:
                        continue
                    results.add(tuple(sorted((set(squad) - set(transfer_out)) | set(transfer_in))))
    return tuple(sorted(results))


def _requests(*, first_root_gain: int = 2, second_root_gain: int = 1, free_transfers: int = 2):
    base = base_squad()
    root_squads = _expanded_squads((base,), incoming=("p15", "p16"), maximum_transfers=2)
    future_squads = _expanded_squads(root_squads, incoming=("p17", "p18"), maximum_transfers=2)
    root = NodeSpec(
        node_id="gw1",
        gameweek=1,
        points={"p15": first_root_gain, "p16": second_root_gain},
        allowed_transfer_in_ids=("p15", "p16"),
        squads=root_squads,
    )
    one_gameweek = build_request(
        (root,),
        free_transfers=free_transfers,
        max_transfers_per_node=2,
        include_second_mid=True,
        request_id="three-gw-ft-carry-one",
    )
    rolling = build_request(
        (
            root,
            NodeSpec(
                node_id="gw2",
                parent_id="gw1",
                gameweek=2,
                points={"p17": 5, "p18": 5},
                allowed_transfer_in_ids=("p17", "p18"),
                squads=future_squads,
            ),
            NodeSpec(
                node_id="gw3",
                parent_id="gw2",
                gameweek=3,
                points={},
                purchasable={"p19": False},
                allowed_transfer_in_ids=("p19",),
                squads=future_squads,
            ),
        ),
        free_transfers=free_transfers,
        max_transfers_per_node=2,
        include_second_mid=True,
        request_id="three-gw-ft-carry-rolling",
    )
    return one_gameweek, rolling


def test_saved_free_transfer_changes_root_through_real_future_hit_avoidance() -> None:
    one_request, rolling_request = _requests()

    one = optimise_multi_gameweek(one_request)
    rolling = optimise_multi_gameweek(rolling_request)
    oracle = exhaustive_expected_oracle(rolling_request)

    assert one.current_action is not None
    assert rolling.current_action is not None
    assert rolling.recommended_plan is not None
    assert one.current_action.transfer_count == 2
    assert rolling.current_action.transfer_count == 1
    assert rolling.current_action.signature == oracle.root_action_signature
    assert rolling.recommended_plan.utility.expected_horizon_utility == oracle.expected_utility
    assert rolling.recommended_plan.current_action.free_transfers_before == 2
    assert rolling.recommended_plan.current_action.free_transfers_after == 2
    assert rolling.recommended_plan.future_policy[0].action.transfer_count == 2
    assert rolling.recommended_plan.future_policy[0].hit_points == 0
    assert rolling.recommended_plan.terminal_value.free_transfer_value == 0


def test_spending_both_free_transfers_now_remains_correct_when_immediate_gain_clears_recourse() -> (
    None
):
    _one_request, rolling_request = _requests(first_root_gain=20, second_root_gain=20)

    result = optimise_multi_gameweek(rolling_request)
    oracle = exhaustive_expected_oracle(rolling_request)

    assert result.current_action is not None
    assert result.recommended_plan is not None
    assert result.current_action.transfer_count == 2
    assert result.current_action.signature == oracle.root_action_signature
    assert result.recommended_plan.utility.expected_horizon_utility == oracle.expected_utility


def test_root_hit_is_selected_only_when_three_gameweek_value_clears_compiled_cost() -> None:
    _one_request, rolling_request = _requests(
        first_root_gain=20, second_root_gain=20, free_transfers=1
    )

    result = optimise_multi_gameweek(rolling_request)

    assert result.current_action is not None
    assert result.current_action.transfer_count == 2
    assert result.recommended_plan is not None
    assert result.recommended_plan.current_action.paid_transfers == 1
    assert result.recommended_plan.current_action.hit_points == 4


def test_compiled_two_free_transfer_arcs_preserve_before_action_and_next_deadline_states() -> None:
    _one_request, rolling_request = _requests()
    rules = rolling_request.rules

    hold = resolve_free_transfer_arc(rules, event="NORMAL", ft_before=2, transfer_count=0)
    one = resolve_free_transfer_arc(rules, event="NORMAL", ft_before=2, transfer_count=1)
    two = resolve_free_transfer_arc(rules, event="NORMAL", ft_before=2, transfer_count=2)

    assert (hold.effective_ft_before, hold.free_used, hold.paid_transfers, hold.ft_after) == (
        2,
        0,
        0,
        3,
    )
    assert (one.effective_ft_before, one.free_used, one.paid_transfers, one.ft_after) == (
        2,
        1,
        0,
        2,
    )
    assert (two.effective_ft_before, two.free_used, two.paid_transfers, two.ft_after) == (
        2,
        2,
        0,
        1,
    )
