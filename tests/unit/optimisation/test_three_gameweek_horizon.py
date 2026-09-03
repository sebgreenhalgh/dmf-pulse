from __future__ import annotations

from decimal import Decimal

import pytest

from dmf_pulse.optimisation.multi_gameweek_models import (
    HorizonTransferCountFrontier,
    MultiGameweekResultStatus,
    seal_request,
)
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.optimisation.multi_gameweek_solver import (
    InfeasiblePolicyError,
    select_horizon_transfer_count_frontier,
)
from tests.support.multi_gameweek_factories import (
    NodeSpec,
    base_squad,
    build_request,
    constrain_mid_transfer_prices,
    replace,
)
from tests.support.multi_gameweek_oracle import exhaustive_expected_oracle


def _with_horizon_frontier(request):
    return seal_request(
        request.model_copy(
            update={
                "assumptions": tuple(
                    sorted((*request.assumptions, "HORIZON_TRANSFER_COUNT_FRONTIER_V1"))
                ),
                "request_sha256": "0" * 64,
            }
        )
    )


def test_horizon_frontier_rejects_an_empty_evaluated_policy_set() -> None:
    with pytest.raises(InfeasiblePolicyError, match="no evaluated root policies"):
        select_horizon_transfer_count_frontier(())


def test_three_gameweek_frontier_selects_each_count_by_horizon_utility() -> None:
    prices = constrain_mid_transfer_prices()
    base = base_squad()
    bought = replace(base, "p07", "p15")
    request = _with_horizon_frontier(
        build_request(
            (
                NodeSpec(
                    node_id="gw1",
                    gameweek=1,
                    prices=prices,
                    points={"p07": 4, "p15": 5},
                    allowed_transfer_in_ids=("p15",),
                    squads=(base, bought),
                ),
                NodeSpec(
                    node_id="gw2",
                    parent_id="gw1",
                    gameweek=2,
                    points={"p07": 0, "p15": 8},
                    allowed_transfer_in_ids=("p15",),
                    squads=(base, bought),
                ),
                NodeSpec(
                    node_id="gw3",
                    parent_id="gw2",
                    gameweek=3,
                    points={"p07": 0, "p15": 8},
                    allowed_transfer_in_ids=("p15",),
                    squads=(base, bought),
                ),
            ),
            root_prices=prices,
            max_transfers_per_node=1,
        )
    )

    result = optimise_multi_gameweek(request)

    assert result.status is MultiGameweekResultStatus.SUCCESS
    assert isinstance(result.transfer_count_frontier, HorizonTransferCountFrontier)
    assert result.transfer_count_frontier.objective_scope == "EXPECTED_HORIZON_UTILITY"
    assert result.transfer_count_frontier.horizon_gameweeks == (1, 2, 3)
    point = result.transfer_count_frontier.points[1]
    assert point.transfer_count == 1
    assert point.expected_horizon_utility == point.plan.utility.expected_horizon_utility
    assert point.expected_horizon_utility > point.current_gameweek_objective


def test_three_gameweek_policy_matches_independent_exact_oracle() -> None:
    prices = constrain_mid_transfer_prices()
    base = base_squad()
    bought = replace(base, "p07", "p15")
    request = _with_horizon_frontier(
        build_request(
            (
                NodeSpec(
                    node_id="gw1",
                    gameweek=1,
                    prices=prices,
                    points={"p07": 6, "p15": 8},
                    allowed_transfer_in_ids=("p15",),
                    squads=(base, bought),
                ),
                NodeSpec(
                    node_id="gw2",
                    parent_id="gw1",
                    gameweek=2,
                    points={"p07": 1, "p15": 7},
                    allowed_transfer_in_ids=("p15",),
                    squads=(base, bought),
                ),
                NodeSpec(
                    node_id="gw3",
                    parent_id="gw2",
                    gameweek=3,
                    points={"p07": 1, "p15": 7},
                    allowed_transfer_in_ids=("p15",),
                    squads=(base, bought),
                ),
            ),
            root_prices=prices,
            max_transfers_per_node=1,
        )
    )
    oracle = exhaustive_expected_oracle(request)

    result = optimise_multi_gameweek(request)

    assert result.recommended_plan is not None
    assert result.current_action is not None
    assert result.recommended_plan.utility.expected_horizon_utility == oracle.expected_utility
    assert result.current_action.signature == oracle.root_action_signature
    assert result.recommended_plan.terminal_value.total == Decimal(0)


def test_three_gameweek_order_invariance_and_deterministic_tie_break() -> None:
    prices = constrain_mid_transfer_prices()
    base = base_squad()
    bought = replace(base, "p07", "p15")
    specs = (
        NodeSpec(
            node_id="gw1",
            gameweek=1,
            prices=prices,
            points={"p07": 5, "p15": 5},
            allowed_transfer_in_ids=("p15",),
            squads=(bought, base),
        ),
        NodeSpec(
            node_id="gw2",
            parent_id="gw1",
            gameweek=2,
            points={"p07": 5, "p15": 5},
            allowed_transfer_in_ids=("p15",),
            squads=(bought, base),
        ),
        NodeSpec(
            node_id="gw3",
            parent_id="gw2",
            gameweek=3,
            points={"p07": 5, "p15": 5},
            allowed_transfer_in_ids=("p15",),
            squads=(bought, base),
        ),
    )
    ordered = _with_horizon_frontier(
        build_request(specs, root_prices=prices, max_transfers_per_node=1)
    )
    reversed_input = _with_horizon_frontier(
        build_request(tuple(reversed(specs)), root_prices=prices, max_transfers_per_node=1)
    )

    first = optimise_multi_gameweek(ordered)
    second = optimise_multi_gameweek(reversed_input)

    assert first == second
    assert first.current_action is not None
    assert first.current_action.transfer_count == 0
