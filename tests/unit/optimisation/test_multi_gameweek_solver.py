"""Solver status, alternatives, attribution and rolling-state unit tests for OPT-011."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.optimisation.multi_gameweek_artifacts import load_canonical_json
from dmf_pulse.optimisation.multi_gameweek_models import (
    AlternativeAvailability,
    BackendStatus,
    MultiGameweekOptimisationRequest,
    MultiGameweekResultStatus,
    OptimalityGuarantee,
    SolverDiagnostics,
    seal_request,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_service import (
    advance_current_action,
    optimise_multi_gameweek,
)

pytestmark = pytest.mark.unit
ROOT = Path("fixtures/optimisation/multi_gameweek/adversarial")


def _result(name: str):
    request = load_canonical_json(ROOT / f"{name}.json", MultiGameweekOptimisationRequest)
    return request, optimise_multi_gameweek(request)


def test_rational_hit_and_ft_path_are_exact() -> None:
    _, result = _result("rational_hit")
    assert result.recommended_plan is not None
    current = result.recommended_plan.current_action
    assert current.action.transfer_count == 2
    assert current.paid_transfers == 1
    assert current.hit_points == 4
    assert current.free_transfers_before == 1
    assert current.free_transfers_after == 1
    assert result.recommended_plan.utility.expected_hit_cost == Decimal(4)


def test_roll_transfer_preserves_current_squad_and_banks_ft() -> None:
    _, result = _result("roll_ft")
    assert result.recommended_plan is not None
    current = result.recommended_plan.current_action
    assert current.action.transfer_count == 0
    assert current.free_transfers_before == 1
    assert current.free_transfers_after == 2


def test_repurchase_closes_old_spell_and_creates_new_purchase_cohort() -> None:
    _, result = _result("repurchase_resets_cohort")
    assert result.recommended_plan is not None
    decisions = (
        result.recommended_plan.current_action,
        *result.recommended_plan.future_policy,
    )
    assert [item.action.signature for item in decisions] == [
        "NORMAL|mid_1->mid_6",
        "NORMAL|->",
        "NORMAL|mid_6->mid_1",
    ]
    spells = tuple(
        item for item in decisions[-1].state_after.ownership_spells if item.player_id == "mid_1"
    )
    assert len(spells) == 2
    assert spells[0].purchase_price_tenths == 50
    assert spells[0].ended_gameweek == 1
    assert spells[1].purchase_price_tenths == 52
    assert spells[1].active


def test_funding_move_reports_bundle_not_false_additivity() -> None:
    _, result = _result("funding_transfer_bundle")
    attribution = result.marginal_value_of_each_move
    assert attribution is not None
    assert len(attribution.marginal_values) == 2
    assert all(item.leave_one_out_feasible for item in attribution.marginal_values)
    assert all(item.exact_leave_one_out_value == Decimal(0) for item in attribution.marginal_values)
    assert all(not item.additive for item in attribution.marginal_values)
    assert attribution.bundle_interaction_value == attribution.bundle_uplift_vs_no_transfer


def test_interacting_tied_bundle_reports_nonzero_interaction() -> None:
    _, result = _result("tied_plans")
    attribution = result.marginal_value_of_each_move
    assert attribution is not None
    assert attribution.bundle_interaction_value == Decimal(4)
    assert all(not item.additive for item in attribution.marginal_values)


def test_no_artificial_conservative_or_upside_plan_is_manufactured() -> None:
    _, result = _result("no_materially_distinct_alternative")
    assert (
        result.conservative_plan.availability is AlternativeAvailability.NO_MATERIALLY_DISTINCT_PLAN
    )
    assert (
        result.high_upside_plan.availability is AlternativeAvailability.NO_MATERIALLY_DISTINCT_PLAN
    )
    assert result.conservative_plan.plan is None
    assert result.high_upside_plan.plan is None


def test_resource_limit_with_complete_incumbent_is_not_reported_optimal() -> None:
    _, result = _result("resource_limit_incumbent")
    assert result.status is MultiGameweekResultStatus.RESOURCE_LIMIT
    assert result.solver_status.status is BackendStatus.TIME_RESOURCE_LIMIT_WITH_INCUMBENT
    assert result.solver_status.optimality_guarantee is OptimalityGuarantee.NONE
    assert result.solver_status.incumbent is not None
    assert result.solver_status.bound is None
    assert result.recommended_plan is not None
    assert result.conservative_plan.availability is AlternativeAvailability.UNAVAILABLE
    assert result.high_upside_plan.availability is AlternativeAvailability.UNAVAILABLE
    assert result.marginal_value_of_each_move is None
    assert "prevented complete frontier exhaustion" in result.conservative_plan.reason
    assert "exact declared frontier" not in result.conservative_plan.reason


def test_resource_limit_without_incumbent_has_no_recommendation() -> None:
    request, _ = _result("simple_one_ft")
    search = seal_search_policy(
        request.search_policy.model_copy(
            update={"max_actions_per_state": 1, "policy_sha256": "0" * 64}
        )
    )
    limited = seal_request(
        request.model_copy(update={"search_policy": search, "request_sha256": "0" * 64})
    )
    result = optimise_multi_gameweek(limited)
    assert result.status is MultiGameweekResultStatus.RESOURCE_LIMIT
    assert result.solver_status.status is BackendStatus.TIME_RESOURCE_LIMIT_NO_INCUMBENT
    assert result.recommended_plan is None
    assert result.current_action is None
    assert result.error_code == "MULTI_GAMEWEEK_RESOURCE_LIMIT"


def test_invalid_and_infeasible_statuses_remain_distinct() -> None:
    _, malformed = _result("malformed_scenario_probabilities_tree")
    _, infeasible = _result("infeasible_future_state")
    assert malformed.status is MultiGameweekResultStatus.BLOCKED
    assert malformed.solver_status.status is BackendStatus.INPUT_CAPABILITY_BLOCKED
    assert infeasible.status is MultiGameweekResultStatus.INFEASIBLE
    assert infeasible.solver_status.status is BackendStatus.INFEASIBLE


def test_terminal_policy_is_versioned_and_separately_attributed() -> None:
    _, result = _result("terminal_value_reversal")
    assert result.recommended_plan is not None
    plan = result.recommended_plan
    assert plan.current_action.action.signature == "NORMAL|mid_1->mid_6"
    assert plan.terminal_value.policy_id == "synthetic-terminal-v1"
    assert plan.terminal_value.bank_value == Decimal("1.5")
    assert plan.utility.terminal_flexibility_contribution == Decimal("1.5")


def test_advance_executes_only_current_action() -> None:
    request, result = _result("injury_revealed_after_current_decision")
    advanced = advance_current_action(request, result, observed_node_id="n2_a")
    assert advanced.executed_action.transfer_count == 0
    assert advanced.observed_node_id == "n2_a"
    assert advanced.manager_state.current_gameweek == 2
    assert advanced.manager_state.observed_node_id == "n2_a"
    assert "mid_6" not in advanced.manager_state.squad_ids


def test_advance_rejects_same_id_request_with_different_lineage() -> None:
    request, result = _result("simple_one_ft")
    altered = seal_request(
        request.model_copy(
            update={
                "assumptions": (*request.assumptions, "different-input-lineage"),
                "request_sha256": "0" * 64,
            }
        )
    )
    with pytest.raises(ValueError, match="lineage"):
        advance_current_action(altered, result)


def test_optimal_diagnostics_require_matching_objective_incumbent_and_bound() -> None:
    with pytest.raises(ValidationError, match="must be identical"):
        SolverDiagnostics(
            status=BackendStatus.OPTIMAL,
            termination_reason="invalid",
            optimality_guarantee=OptimalityGuarantee.EXACT_DECLARED_TREE_AND_ACTION_SPACE,
            objective=Decimal(10),
            incumbent=Decimal(10),
            bound=Decimal(11),
            absolute_gap=Decimal(0),
            relative_gap=Decimal(0),
            configuration_sha256="0" * 64,
        )
