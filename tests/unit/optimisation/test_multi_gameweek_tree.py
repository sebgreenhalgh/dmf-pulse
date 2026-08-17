"""Scenario-tree, nonanticipativity and terminal-policy tests for OPT-011."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.multi_gameweek_errors import InputInvalidError
from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekResultStatus,
    ScenarioTree,
    TerminalValuePolicy,
    seal_request,
    seal_scenario_tree,
)
from dmf_pulse.optimisation.multi_gameweek_policy import (
    load_multi_gameweek_search_policy,
    load_terminal_value_policy,
)
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.optimisation.multi_gameweek_solver import validate_request
from tests.support.multi_gameweek_factories import (
    NodeSpec,
    base_squad,
    build_request,
    constrain_mid_transfer_prices,
    replace,
)

pytestmark = pytest.mark.unit


def _branch_request():
    prices = constrain_mid_transfer_prices()
    base = base_squad()
    swapped = replace(base, "p07", "p15")
    return build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p07": 5, "p15": 5},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swapped),
            ),
            NodeSpec(
                node_id="injured",
                parent_id="root",
                gameweek=2,
                conditional_probability=Decimal("0.5"),
                revealed_information=("P07_INJURED",),
                availability_state={"p07": "OUT"},
                points={"p07": 0, "p15": 8},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swapped),
            ),
            NodeSpec(
                node_id="fit",
                parent_id="root",
                gameweek=2,
                conditional_probability=Decimal("0.5"),
                revealed_information=("P07_FIT",),
                availability_state={"p07": "AVAILABLE"},
                points={"p07": 8, "p15": 0},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swapped),
            ),
        ),
        root_prices=prices,
        max_transfers_per_node=1,
    )


def test_future_actions_recourse_only_after_revelation() -> None:
    request = _branch_request()
    result = optimise_multi_gameweek(request)
    assert result.status is MultiGameweekResultStatus.SUCCESS
    assert result.recommended_plan is not None
    assert result.current_action is not None
    assert result.current_action.transfer_count == 0
    decisions = {item.node_id: item.action.signature for item in result.future_policy}
    assert decisions["injured"] == "NORMAL|p07->p15"
    assert decisions["fit"] == "NORMAL|->"


def test_clairvoyant_root_policy_is_not_representable() -> None:
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
                points={"p15": 1, "p19": 1},
                allowed_transfer_in_ids=("p15", "p19"),
                squads=(base, p15_squad, p19_squad),
            ),
            NodeSpec(
                node_id="left",
                parent_id="root",
                gameweek=2,
                conditional_probability=Decimal("0.5"),
                revealed_information=("LEFT",),
                points={"p15": 10, "p19": 0},
                allowed_transfer_in_ids=("p17",),
                purchasable={"p17": False},
                squads=(base, p15_squad, p19_squad),
            ),
            NodeSpec(
                node_id="right",
                parent_id="root",
                gameweek=2,
                conditional_probability=Decimal("0.5"),
                revealed_information=("RIGHT",),
                points={"p15": 0, "p19": 10},
                allowed_transfer_in_ids=("p17",),
                purchasable={"p17": False},
                squads=(base, p15_squad, p19_squad),
            ),
        ),
        root_prices=prices,
        include_second_mid=True,
        max_transfers_per_node=1,
    )
    result = optimise_multi_gameweek(request)
    assert result.recommended_plan is not None
    production_value = result.recommended_plan.utility.expected_horizon_utility
    # A cheating leaf-specific root action would buy p15 on LEFT and p19 on RIGHT.
    clairvoyant_value = Decimal(22)
    assert production_value == Decimal(12)
    assert production_value < clairvoyant_value
    assert result.recommended_plan.current_action.action.transfers_in in {("p15",), ("p19",)}


def test_malformed_sibling_probability_sum_fails_closed() -> None:
    request = _branch_request()
    nodes = tuple(
        item.model_copy(update={"conditional_probability": Decimal("0.6")})
        if item.parent_id is not None
        else item
        for item in request.scenario_tree.nodes
    )
    tree = seal_scenario_tree(
        request.scenario_tree.model_copy(update={"nodes": nodes, "tree_sha256": "0" * 64})
    )
    malformed = seal_request(
        request.model_copy(update={"scenario_tree": tree, "request_sha256": "0" * 64})
    )
    with pytest.raises(InputInvalidError, match="probabilities"):
        validate_request(malformed)


def test_root_probability_must_equal_one() -> None:
    request = _branch_request()
    nodes = tuple(
        item.model_copy(update={"conditional_probability": Decimal("0.9")})
        if item.parent_id is None
        else item
        for item in request.scenario_tree.nodes
    )
    malformed = seal_request(
        request.model_copy(
            update={
                "scenario_tree": seal_scenario_tree(
                    request.scenario_tree.model_copy(
                        update={"nodes": nodes, "tree_sha256": "0" * 64}
                    )
                ),
                "request_sha256": "0" * 64,
            }
        )
    )
    with pytest.raises(InputInvalidError, match="root conditional probability"):
        validate_request(malformed)


def test_missing_parent_is_rejected() -> None:
    request = _branch_request()
    nodes = tuple(
        item.model_copy(update={"parent_id": "missing-parent"}) if item.node_id == "fit" else item
        for item in request.scenario_tree.nodes
    )
    malformed = seal_request(
        request.model_copy(
            update={
                "scenario_tree": seal_scenario_tree(
                    request.scenario_tree.model_copy(
                        update={"nodes": nodes, "tree_sha256": "0" * 64}
                    )
                ),
                "request_sha256": "0" * 64,
            }
        )
    )
    with pytest.raises(InputInvalidError, match="missing parent"):
        validate_request(malformed)


def test_parent_cycle_is_rejected_before_chronology_checks() -> None:
    request = _branch_request()
    root = request.scenario_tree.root
    injured = next(item for item in request.scenario_tree.nodes if item.node_id == "injured")
    fit = next(item for item in request.scenario_tree.nodes if item.node_id == "fit")
    cycle_a = injured.model_copy(
        update={"node_id": "cycle-a", "parent_id": "cycle-b", "gameweek": 2}
    )
    cycle_b = fit.model_copy(update={"node_id": "cycle-b", "parent_id": "cycle-a", "gameweek": 3})
    tree = seal_scenario_tree(
        request.scenario_tree.model_copy(
            update={"nodes": (root, cycle_a, cycle_b), "tree_sha256": "0" * 64}
        )
    )
    malformed = seal_request(
        request.model_copy(update={"scenario_tree": tree, "request_sha256": "0" * 64})
    )
    with pytest.raises(InputInvalidError, match="parent cycle"):
        validate_request(malformed)


def test_tree_edge_must_advance_exactly_one_gameweek() -> None:
    request = _branch_request()
    nodes = tuple(
        item.model_copy(update={"gameweek": 3}) if item.node_id == "fit" else item
        for item in request.scenario_tree.nodes
    )
    tree = seal_scenario_tree(
        request.scenario_tree.model_copy(
            update={
                "nodes": tuple(sorted(nodes, key=lambda item: (item.gameweek, item.node_id))),
                "tree_sha256": "0" * 64,
            }
        )
    )
    malformed = seal_request(
        request.model_copy(update={"scenario_tree": tree, "request_sha256": "0" * 64})
    )
    with pytest.raises(InputInvalidError, match="advance exactly one Gameweek"):
        validate_request(malformed)


def test_duplicate_node_ids_are_rejected_by_contract() -> None:
    request = _branch_request()
    with pytest.raises(ValidationError, match="unique"):
        ScenarioTree(
            tree_id="duplicate",
            nodes=(request.scenario_tree.nodes[0], request.scenario_tree.nodes[0]),
            tree_sha256="0" * 64,
        )


def test_revelation_cannot_disappear() -> None:
    request = _branch_request()
    injured = next(item for item in request.scenario_tree.nodes if item.node_id == "injured")
    child = injured.model_copy(
        update={
            "node_id": "grandchild",
            "parent_id": "injured",
            "gameweek": 3,
            "conditional_probability": Decimal(1),
            "revealed_information": (),
        }
    )
    tree = seal_scenario_tree(
        request.scenario_tree.model_copy(
            update={
                "nodes": tuple(
                    sorted(
                        (*request.scenario_tree.nodes, child),
                        key=lambda item: (item.gameweek, item.node_id),
                    )
                ),
                "tree_sha256": "0" * 64,
            }
        )
    )
    malformed = seal_request(
        request.model_copy(update={"scenario_tree": tree, "request_sha256": "0" * 64})
    )
    with pytest.raises(InputInvalidError, match="cannot disappear"):
        validate_request(malformed)


def test_terminal_value_is_separate_and_can_reverse_a_tie() -> None:
    prices = constrain_mid_transfer_prices()
    prices["p15"] = 49
    base = base_squad()
    swapped = replace(base, "p07", "p15")
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                prices=prices,
                points={"p07": 5, "p15": 5},
                allowed_transfer_in_ids=("p15",),
                squads=(base, swapped),
            ),
        ),
        root_prices=prices,
        terminal_enabled=True,
        bank_points_per_tenth=Decimal(2),
        max_transfers_per_node=1,
    )
    result = optimise_multi_gameweek(request)
    assert result.current_action is not None
    assert result.current_action.transfers_in == ("p15",)
    assert result.recommended_plan is not None
    assert result.recommended_plan.terminal_value.bank_value == Decimal(2)
    assert result.recommended_plan.utility.terminal_flexibility_contribution == Decimal(2)


def test_identical_inputs_reproduce_exact_result_hash() -> None:
    request = _branch_request()
    left = optimise_multi_gameweek(request)
    right = optimise_multi_gameweek(request)
    assert left == right
    assert left.result_sha256 == right.result_sha256


def test_production_mode_fails_closed_without_unrestricted_backend() -> None:
    request = _branch_request()
    production = request.model_copy(
        update={
            "projection_mode": ProjectionMode.PRODUCTION,
            "rules": request.rules.model_copy(
                update={"projection_mode": ProjectionMode.PRODUCTION}
            ),
            "request_sha256": "0" * 64,
        }
    )
    production = seal_request(production)
    result = optimise_multi_gameweek(production)
    assert result.status is MultiGameweekResultStatus.BLOCKED
    assert result.error_code == "MULTI_GAMEWEEK_PRODUCTION_BACKEND_UNAVAILABLE"


def test_packaged_search_and_terminal_policies_match_reviewable_configs() -> None:
    packaged_search = load_multi_gameweek_search_policy()
    configured_search = load_multi_gameweek_search_policy(
        Path("config/optimisation/multi_gameweek.yaml")
    )
    packaged_terminal = load_terminal_value_policy()
    configured_terminal = load_terminal_value_policy(
        Path("config/optimisation/multi_gameweek_terminal.yaml")
    )
    assert packaged_search == configured_search
    assert packaged_terminal == configured_terminal
    assert not packaged_terminal.enabled
    assert packaged_terminal.bank_points_per_tenth == Decimal(0)
    assert packaged_terminal.free_transfer_points == Decimal(0)
    assert packaged_terminal.liquidation_points_per_tenth == Decimal(0)


def test_disabled_terminal_policy_rejects_hidden_nonzero_weight() -> None:
    with pytest.raises(ValidationError, match="zero coefficients"):
        TerminalValuePolicy(
            policy_id="disabled-with-hidden-weight",
            policy_version="1.0.0",
            enabled=False,
            bank_points_per_tenth=Decimal(1),
            free_transfer_points=Decimal(0),
            liquidation_points_per_tenth=Decimal(0),
            policy_sha256="0" * 64,
        )
