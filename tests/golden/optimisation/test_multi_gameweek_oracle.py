"""Finite exact-oracle and golden policy tests for OPT-011."""

from __future__ import annotations

from decimal import Decimal

import pytest

from dmf_pulse.optimisation.multi_gameweek_models import MultiGameweekResultStatus
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from tests.support.multi_gameweek_factories import (
    NodeSpec,
    base_squad,
    build_request,
    constrain_mid_transfer_prices,
    replace,
)
from tests.support.multi_gameweek_oracle import exhaustive_expected_oracle

pytestmark = [pytest.mark.golden, pytest.mark.integration]


def _assert_matches_oracle(request):
    oracle = exhaustive_expected_oracle(request)
    result = optimise_multi_gameweek(request)
    assert result.status is MultiGameweekResultStatus.SUCCESS
    assert result.recommended_plan is not None
    assert result.current_action is not None
    assert result.recommended_plan.utility.expected_horizon_utility == oracle.expected_utility
    assert result.current_action.signature == oracle.root_action_signature
    assert result.solver_status.status.value == "OPTIMAL"
    assert result.solver_status.optimality_guarantee.value == (
        "EXACT_DECLARED_TREE_AND_ACTION_SPACE"
    )
    return result


def test_one_transfer_optimum_matches_exhaustive_oracle() -> None:
    prices = constrain_mid_transfer_prices()
    base = base_squad()
    swap = replace(base, "p07", "p15")
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p07": 1, "p15": 8},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swap),
            ),
        ),
        root_prices=prices,
        max_transfers_per_node=1,
    )
    result = _assert_matches_oracle(request)
    assert result.current_action is not None
    assert result.current_action.transfers_out == ("p07",)
    assert result.current_action.transfers_in == ("p15",)


def test_roll_transfer_optimum_matches_oracle_and_banks_ft() -> None:
    prices = constrain_mid_transfer_prices()
    base = base_squad()
    swap = replace(base, "p07", "p15")
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p07": 5, "p15": 5},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swap),
            ),
        ),
        root_prices=prices,
        max_transfers_per_node=1,
    )
    result = _assert_matches_oracle(request)
    assert result.current_action is not None
    assert result.current_action.transfer_count == 0
    assert result.recommended_plan is not None
    assert result.recommended_plan.current_action.free_transfers_after == 2


def test_rational_hit_matches_oracle() -> None:
    prices = constrain_mid_transfer_prices()
    base = base_squad()
    swap = replace(base, "p07", "p15")
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p07": 1, "p15": 8},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swap),
            ),
        ),
        root_prices=prices,
        free_transfers=0,
        max_transfers_per_node=1,
    )
    result = _assert_matches_oracle(request)
    assert result.recommended_plan is not None
    assert result.recommended_plan.current_action.hit_points == 4


def test_retained_profit_route_matches_oracle() -> None:
    prices = constrain_mid_transfer_prices(target_price=55)
    prices["p15"] = 52
    base = base_squad()
    swap = replace(base, "p07", "p15")
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p07": 1, "p15": 8},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swap),
            ),
        ),
        root_prices=prices,
        purchase_prices={"p07": 50},
        max_transfers_per_node=1,
    )
    result = _assert_matches_oracle(request)
    assert result.recommended_plan is not None
    decision = result.recommended_plan.current_action
    assert decision.selling_prices[0].price_tenths == 52
    assert decision.bank_after_tenths == 0


def test_two_gameweek_price_route_matches_oracle() -> None:
    prices = constrain_mid_transfer_prices()
    base = base_squad()
    swap = replace(base, "p07", "p15")
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p07": 5, "p15": 4},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swap),
            ),
            NodeSpec(
                node_id="later",
                parent_id="root",
                gameweek=2,
                prices={"p15": 51},
                points={"p07": 1, "p15": 10},
                allowed_transfer_in_ids=("p15",),
                revealed_information=("PRICE_RISE",),
                squads=(base, swap),
            ),
        ),
        root_prices=prices,
        max_transfers_per_node=1,
    )
    result = _assert_matches_oracle(request)
    assert result.current_action is not None
    assert result.current_action.transfers_in == ("p15",)
    assert result.recommended_plan is not None
    assert result.recommended_plan.utility.current_gameweek_contribution == Decimal(8)
    assert result.recommended_plan.utility.future_contribution == Decimal(20)


def test_three_gameweek_policy_matches_oracle() -> None:
    prices = constrain_mid_transfer_prices()
    base = base_squad()
    swap = replace(base, "p07", "p15")
    request = build_request(
        (
            NodeSpec(
                node_id="gw1",
                gameweek=1,
                prices=prices,
                points={"p07": 5, "p15": 4},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swap),
            ),
            NodeSpec(
                node_id="gw2",
                parent_id="gw1",
                gameweek=2,
                prices={"p15": 51},
                points={"p07": 1, "p15": 8},
                allowed_transfer_in_ids=("p15",),
                revealed_information=("PRICE_RISE",),
                squads=(base, swap),
            ),
            NodeSpec(
                node_id="gw3",
                parent_id="gw2",
                gameweek=3,
                points={"p07": 1, "p15": 9},
                allowed_transfer_in_ids=("p15",),
                revealed_information=("PRICE_RISE", "GW3_KNOWN"),
                squads=(base, swap),
            ),
        ),
        root_prices=prices,
        max_transfers_per_node=1,
    )
    result = _assert_matches_oracle(request)
    assert result.recommended_plan is not None
    assert len(result.recommended_plan.future_policy) == 2
    assert result.current_action is not None
    assert result.current_action.transfers_in == ("p15",)


def test_funding_bundle_is_optimised_as_interacting_bundle() -> None:
    prices = constrain_mid_transfer_prices(target_price=50)
    prices.update({"p15": 60, "p12": 50, "p13": 30, "p14": 30, "p16": 40})
    base = base_squad()
    down = replace(base, "p12", "p16")
    bundle = replace(replace(base, "p07", "p15"), "p12", "p16")
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p12": 2, "p15": 10},
                allowed_transfer_in_ids=("p15", "p16"),
                squads=(base, down, bundle),
            ),
        ),
        root_prices=prices,
        free_transfers=2,
        max_transfers_per_node=2,
    )
    result = _assert_matches_oracle(request)
    assert result.current_action is not None
    assert result.current_action.transfer_count == 2
    assert set(result.current_action.transfers_in) == {"p15", "p16"}
    assert result.marginal_value_of_each_move is not None
    attribution = result.marginal_value_of_each_move
    assert all(item.leave_one_out_feasible for item in attribution.marginal_values)
    assert all(not item.additive for item in attribution.marginal_values)
    exact_drop_values = sum(
        (
            item.exact_leave_one_out_value
            for item in attribution.marginal_values
            if item.exact_leave_one_out_value is not None
        ),
        Decimal(0),
    )
    assert attribution.bundle_interaction_value == (
        attribution.bundle_uplift_vs_no_transfer - exact_drop_values
    )
    assert attribution.bundle_interaction_value != Decimal(0)


def test_horizon_reversal_changes_current_action() -> None:
    prices = constrain_mid_transfer_prices()
    base = base_squad()
    swap = replace(base, "p07", "p15")
    one = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p07": 5, "p15": 8},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swap),
            ),
        ),
        root_prices=prices,
        max_transfers_per_node=1,
        request_id="one-week",
    )
    two = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p07": 5, "p15": 8},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swap),
            ),
            NodeSpec(
                node_id="future",
                parent_id="root",
                gameweek=2,
                points={"p07": 10, "p15": 0},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swap),
            ),
        ),
        root_prices=prices,
        max_transfers_per_node=1,
        request_id="two-week",
    )
    one_result = _assert_matches_oracle(one)
    two_result = _assert_matches_oracle(two)
    assert one_result.current_action is not None
    assert two_result.current_action is not None
    assert one_result.current_action.transfers_in == ("p15",)
    assert two_result.current_action.transfer_count == 0


def test_terminal_value_reversal_matches_oracle() -> None:
    prices = constrain_mid_transfer_prices()
    prices["p15"] = 49
    base = base_squad()
    swap = replace(base, "p07", "p15")
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p07": 5, "p15": 5},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swap),
            ),
        ),
        root_prices=prices,
        terminal_enabled=True,
        bank_points_per_tenth=Decimal(2),
        max_transfers_per_node=1,
    )
    result = _assert_matches_oracle(request)
    assert result.current_action is not None
    assert result.current_action.transfers_in == ("p15",)


def test_deterministic_tie_uses_canonical_action_signature() -> None:
    prices = constrain_mid_transfer_prices()
    prices["p19"] = 50
    base = base_squad()
    p15_squad = replace(base, "p07", "p15")
    p19_squad = replace(base, "p07", "p19")
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p15": 5, "p19": 5},
                allowed_transfer_in_ids=("p15", "p19"),
                squads=(base, p15_squad, p19_squad),
            ),
        ),
        root_prices=prices,
        include_second_mid=True,
        max_transfers_per_node=1,
    )
    result = _assert_matches_oracle(request)
    assert result.current_action is not None
    assert result.current_action.transfers_in == ("p15",)
