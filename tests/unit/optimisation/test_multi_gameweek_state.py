"""Exact integer manager-state and transfer-transition tests for OPT-011."""

from __future__ import annotations

from decimal import Decimal

import pytest

from dmf_pulse.optimisation.manager_state import verify_manager_state_hash
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.optimisation.multi_gameweek_solver import (
    apply_transfer_action,
    make_transfer_action,
    observe_node,
    resolve_free_transfer_arc,
    selling_price_tenths,
)
from tests.support.multi_gameweek_factories import (
    NodeSpec,
    base_squad,
    build_request,
    constrain_mid_transfer_prices,
    replace,
    transfer_rules,
)

pytestmark = pytest.mark.unit


def _one_node_request(
    *,
    root_prices: dict[str, int],
    purchase_prices: dict[str, int] | None = None,
    bank_tenths: int = 0,
    free_transfers: int = 1,
    points: dict[str, int] | None = None,
):
    base = base_squad()
    swapped = replace(base, "p07", "p15")
    return build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=root_prices,
                points=points or {"p07": 1, "p15": 8},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swapped),
            ),
        ),
        root_prices=root_prices,
        purchase_prices=purchase_prices,
        bank_tenths=bank_tenths,
        free_transfers=free_transfers,
        max_transfers_per_node=1,
    )


def test_selling_price_retains_floor_half_profit_and_full_loss() -> None:
    rule = transfer_rules().selling_price_rule
    assert selling_price_tenths(purchase_price_tenths=50, current_price_tenths=55, rule=rule) == 52
    assert selling_price_tenths(purchase_price_tenths=50, current_price_tenths=54, rule=rule) == 52
    assert selling_price_tenths(purchase_price_tenths=50, current_price_tenths=49, rule=rule) == 49
    assert selling_price_tenths(purchase_price_tenths=50, current_price_tenths=50, rule=rule) == 50


def test_free_transfer_banking_consumption_hits_and_boundaries() -> None:
    rules = transfer_rules()
    arc = resolve_free_transfer_arc(rules, event="NORMAL", ft_before=1, transfer_count=0)
    assert arc.ft_after == 2
    one = resolve_free_transfer_arc(rules, event="NORMAL", ft_before=1, transfer_count=1)
    assert (one.free_used, one.paid_transfers, one.hit_points, one.ft_after) == (1, 0, 0, 1)
    hit = resolve_free_transfer_arc(rules, event="NORMAL", ft_before=1, transfer_count=2)
    assert (hit.free_used, hit.paid_transfers, hit.hit_points, hit.ft_after) == (1, 1, 4, 1)
    capped = resolve_free_transfer_arc(rules, event="NORMAL", ft_before=5, transfer_count=0)
    assert capped.ft_after == 5
    preseason = resolve_free_transfer_arc(rules, event="PRESEASON", ft_before=0, transfer_count=15)
    assert (preseason.paid_transfers, preseason.hit_points, preseason.ft_after) == (0, 0, 1)


def test_profit_sale_bank_conservation_and_new_purchase_cohort() -> None:
    prices = constrain_mid_transfer_prices(target_price=55)
    prices["p15"] = 50
    request = _one_node_request(
        root_prices=prices,
        purchase_prices={"p07": 50},
    )
    action = make_transfer_action(transfers_out=("p07",), transfers_in=("p15",), event="NORMAL")
    transition = apply_transfer_action(
        request.initial_state,
        action,
        node=request.scenario_tree.root,
        candidate_pool=request.candidate_pool,
        rules=request.rules,
    )
    assert transition.selling_prices[0].price_tenths == 52
    assert transition.buying_prices[0].price_tenths == 50
    assert transition.state.bank_tenths == 2
    closed = next(spell for spell in transition.state.ownership_spells if spell.player_id == "p07")
    bought = next(
        spell
        for spell in transition.state.ownership_spells
        if spell.player_id == "p15" and spell.active
    )
    assert closed.realised_selling_price_tenths == 52
    assert bought.purchase_price_tenths == 50
    verify_manager_state_hash(transition.state)


def test_price_loss_uses_current_price_without_binary_float() -> None:
    prices = constrain_mid_transfer_prices(target_price=48)
    prices["p15"] = 48
    request = _one_node_request(
        root_prices=prices,
        purchase_prices={"p07": 50},
    )
    transition = apply_transfer_action(
        request.initial_state,
        make_transfer_action(transfers_out=("p07",), transfers_in=("p15",), event="NORMAL"),
        node=request.scenario_tree.root,
        candidate_pool=request.candidate_pool,
        rules=request.rules,
    )
    assert transition.selling_prices[0].price_tenths == 48
    assert transition.state.bank_tenths == 0
    assert isinstance(transition.state.bank_tenths, int)


def test_sell_then_repurchase_creates_second_append_only_spell() -> None:
    prices = constrain_mid_transfer_prices(target_price=50)
    base = base_squad()
    swapped = replace(base, "p07", "p15")
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p07": 1, "p15": 8},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swapped),
            ),
            NodeSpec(
                node_id="child",
                parent_id="root",
                gameweek=2,
                prices={"p07": 53, "p15": 53},
                points={"p07": 9, "p15": 1},
                allowed_transfer_in_ids=("p07",),
                squads=(base, swapped),
            ),
        ),
        root_prices=prices,
        bank_tenths=3,
        free_transfers=2,
        max_transfers_per_node=1,
    )
    sold = apply_transfer_action(
        request.initial_state,
        make_transfer_action(transfers_out=("p07",), transfers_in=("p15",), event="NORMAL"),
        node=request.scenario_tree.root,
        candidate_pool=request.candidate_pool,
        rules=request.rules,
    )
    child = next(item for item in request.scenario_tree.nodes if item.node_id == "child")
    observed = observe_node(sold.state, node=child)
    repurchased = apply_transfer_action(
        observed,
        make_transfer_action(transfers_out=("p15",), transfers_in=("p07",), event="NORMAL"),
        node=child,
        candidate_pool=request.candidate_pool,
        rules=request.rules,
    )
    p07_spells = tuple(
        spell for spell in repurchased.state.ownership_spells if spell.player_id == "p07"
    )
    assert len(p07_spells) == 2
    assert sum(spell.active for spell in p07_spells) == 1
    assert p07_spells[0].purchase_price_tenths == 50
    assert p07_spells[1].purchase_price_tenths == 53
    assert p07_spells[0].spell_id != p07_spells[1].spell_id


def test_rational_hit_is_reported_and_reconciles_objective() -> None:
    prices = constrain_mid_transfer_prices()
    request = _one_node_request(
        root_prices=prices,
        free_transfers=0,
        points={"p07": 1, "p15": 8},
    )
    result = optimise_multi_gameweek(request)
    assert result.status.value == "SUCCESS"
    assert result.recommended_plan is not None
    assert result.current_action is not None
    assert result.current_action.transfers_in == ("p15",)
    assert result.recommended_plan.current_action.hit_points == 4
    assert result.recommended_plan.utility.expected_hit_cost == Decimal(4)
    assert result.recommended_plan.utility.expected_horizon_utility == Decimal(12)


def test_unaffordable_transfer_cannot_make_bank_negative() -> None:
    prices = constrain_mid_transfer_prices(target_price=50)
    prices["p15"] = 51
    request = _one_node_request(root_prices=prices)
    with pytest.raises(ValueError, match="unaffordable"):
        apply_transfer_action(
            request.initial_state,
            make_transfer_action(transfers_out=("p07",), transfers_in=("p15",), event="NORMAL"),
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            rules=request.rules,
        )
