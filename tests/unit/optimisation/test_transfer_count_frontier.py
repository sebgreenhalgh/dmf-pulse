"""Exact Stage-11 transfer-count frontier selection contracts for 001M."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.optimisation.manager_state import ManagerState
from dmf_pulse.optimisation.multi_gameweek_errors import InfeasiblePolicyError
from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekOptimisationResult,
    ObjectiveMode,
    ScenarioTreeNode,
    TacticalNodeEvaluation,
    TransferCountFrontier,
    verify_result_hash,
    verify_transfer_count_frontier_hash,
)
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.optimisation.multi_gameweek_solver import (
    select_candidate,
    select_transfer_count_frontier,
    solve_frontier,
)
from dmf_pulse.optimisation.stage10_adapter import StaticTacticalEvaluator
from tests.support.multi_gameweek_factories import (
    NodeSpec,
    base_squad,
    build_request,
    constrain_mid_transfer_prices,
    replace,
)

pytestmark = pytest.mark.unit


def _zero_one_two_request(
    *,
    free_transfers: int = 2,
    incoming_points: tuple[int, int] = (8, 6),
):
    base = base_squad()
    squads = {base}
    for midfielder in ("p07", "p08", "p09", "p10", "p11"):
        squads.add(replace(base, midfielder, "p15"))
    for defender in ("p02", "p03", "p04", "p05", "p06"):
        squads.add(replace(base, defender, "p17"))
    for midfielder in ("p07", "p08", "p09", "p10", "p11"):
        for defender in ("p02", "p03", "p04", "p05", "p06"):
            squads.add(tuple(sorted((set(base) - {midfielder, defender}) | {"p15", "p17"})))
    return build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                points={"p15": incoming_points[0], "p17": incoming_points[1]},
                allowed_transfer_in_ids=("p15", "p17"),
                squads=tuple(sorted(squads)),
            ),
        ),
        root_prices=constrain_mid_transfer_prices(),
        free_transfers=free_transfers,
        max_transfers_per_node=2,
        request_id=f"transfer-frontier-ft-{free_transfers}",
    )


def _tied_one_transfer_request():
    base = base_squad()
    squads = {base}
    for outgoing in ("p07", "p08", "p09", "p10", "p11"):
        for incoming in ("p15", "p19"):
            squads.add(replace(base, outgoing, incoming))
    prices = constrain_mid_transfer_prices()
    prices["p19"] = 50
    return build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                points={"p15": 8, "p19": 8},
                allowed_transfer_in_ids=("p15", "p19"),
                squads=tuple(sorted(squads)),
            ),
        ),
        root_prices=prices,
        include_second_mid=True,
        max_transfers_per_node=1,
        request_id="transfer-frontier-tie",
    )


def test_exact_best_already_evaluated_action_is_exposed_for_zero_one_and_two() -> None:
    result = optimise_multi_gameweek(_zero_one_two_request())

    assert result.transfer_count_frontier is not None
    points = result.transfer_count_frontier.points
    assert tuple(item.transfer_count for item in points) == (0, 1, 2)
    assert points[0].plan.current_action.action.signature == "NORMAL|->"
    assert points[1].plan.current_action.action.signature == "NORMAL|p07->p15"
    assert points[2].plan.current_action.action.signature == "NORMAL|p02,p07->p15,p17"
    assert all(item.plan.current_action.hit_points == 0 for item in points)
    assert tuple(item.current_gameweek_objective for item in points) == tuple(
        item.plan.current_action.tactical_evaluation.expected_points for item in points
    )


def test_frontier_uses_the_existing_canonical_tie_break_and_keeps_recommendation() -> None:
    request = _tied_one_transfer_request()
    evaluated = solve_frontier(request, StaticTacticalEvaluator())
    before = select_candidate(evaluated.candidates, mode=ObjectiveMode.EXPECTED)

    selected = select_transfer_count_frontier(evaluated.candidates)
    result = optimise_multi_gameweek(request)

    assert selected[1].root_action.signature == "NORMAL|p07->p15"
    assert result.recommended_plan is not None
    assert result.recommended_plan.current_action.action == before.root_action
    assert result.recommended_plan.solver_status.deterministic_tie_key == before.tie_key


def test_frontier_selection_is_order_invariant_lossless_and_performs_no_evaluation() -> None:
    request = _zero_one_two_request()

    class CountingEvaluator(StaticTacticalEvaluator):
        calls = 0

        def evaluate(
            self,
            *,
            node: ScenarioTreeNode,
            state: ManagerState,
        ) -> TacticalNodeEvaluation:
            self.calls += 1
            return super().evaluate(node=node, state=state)

    evaluator = CountingEvaluator()
    evaluated = solve_frontier(request, evaluator)
    calls_after_evaluation = evaluator.calls

    forward = select_transfer_count_frontier(evaluated.candidates)
    reverse = select_transfer_count_frontier(tuple(reversed(evaluated.candidates)))
    with_gap = select_transfer_count_frontier(
        tuple(item for item in evaluated.candidates if item.root_action.transfer_count != 1)
    )

    assert forward == reverse
    assert tuple(item.root_action.transfer_count for item in with_gap) == (0, 2)
    assert all(any(item is candidate for candidate in evaluated.candidates) for item in forward)
    assert evaluator.calls == calls_after_evaluation
    with pytest.raises(InfeasiblePolicyError, match="no evaluated root actions"):
        select_transfer_count_frontier(())


def test_frontier_preserves_hit_bank_and_negative_exact_count_uplift() -> None:
    result = optimise_multi_gameweek(
        _zero_one_two_request(free_transfers=0, incoming_points=(0, 0))
    )
    assert result.transfer_count_frontier is not None
    hold, one, two = result.transfer_count_frontier.points

    assert hold.plan.current_action.free_transfers_before == 0
    assert one.transfer_hit_points == 4
    assert two.transfer_hit_points == 8
    assert one.current_gameweek_objective < hold.current_gameweek_objective
    assert two.current_gameweek_objective < hold.current_gameweek_objective
    assert one.current_gameweek_objective == (one.immediate_expected_points_before_hit - Decimal(4))
    assert two.plan.current_action.bank_after_tenths == 0


def test_only_hold_frontier_and_hash_roundtrip_are_supported() -> None:
    base = base_squad()
    request = build_request(
        (NodeSpec(node_id="root", gameweek=1, squads=(base,)),),
        max_transfers_per_node=0,
        request_id="hold-only-frontier",
    )
    result = optimise_multi_gameweek(request)

    assert result.transfer_count_frontier is not None
    assert tuple(item.transfer_count for item in result.transfer_count_frontier.points) == (0,)
    verify_transfer_count_frontier_hash(result.transfer_count_frontier)
    assert MultiGameweekOptimisationResult.model_validate_json(result.model_dump_json()) == result

    payload = result.transfer_count_frontier.model_dump(mode="python")
    payload["frontier_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="frontier semantic hash"):
        type(result.transfer_count_frontier).model_validate(payload)

    legacy_payload = result.model_dump(mode="json")
    legacy_payload.pop("transfer_count_frontier")
    legacy_payload["result_sha256"] = None
    legacy_payload["result_sha256"] = semantic_sha256(legacy_payload)
    legacy = MultiGameweekOptimisationResult.model_validate(legacy_payload)
    assert legacy.transfer_count_frontier is None
    verify_result_hash(legacy)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("transfer_count", 1, "transfer count differs"),
        ("immediate_expected_points_before_hit", Decimal(1), "expected points differ"),
        ("transfer_hit_points", 1, "hit differs"),
        ("current_gameweek_objective", Decimal(1), "objective does not reconcile"),
    ),
)
def test_frontier_point_rejects_malformed_reconciliation_fields(
    field: str,
    replacement: int | Decimal,
    message: str,
) -> None:
    result = optimise_multi_gameweek(_zero_one_two_request())
    assert result.transfer_count_frontier is not None
    payload = result.transfer_count_frontier.points[0].model_dump(mode="python")
    payload[field] = replacement

    with pytest.raises(ValidationError, match=message):
        type(result.transfer_count_frontier.points[0]).model_validate(payload)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("plan_kind", "RECOMMENDED", "wrong plan kind"),
        ("objective_mode", "CONSERVATIVE", "expected-objective policy"),
    ),
)
def test_frontier_point_rejects_a_plan_with_changed_selection_semantics(
    field: str,
    replacement: str,
    message: str,
) -> None:
    result = optimise_multi_gameweek(_zero_one_two_request())
    assert result.transfer_count_frontier is not None
    point = result.transfer_count_frontier.points[0]
    payload = point.model_dump(mode="python")
    plan = point.plan.model_dump(mode="python")
    plan[field] = replacement
    payload["plan"] = plan

    with pytest.raises(ValidationError, match=message):
        type(point).model_validate(payload)


def test_frontier_container_rejects_empty_duplicate_and_unsealed_content() -> None:
    result = optimise_multi_gameweek(_zero_one_two_request())
    assert result.transfer_count_frontier is not None
    frontier = result.transfer_count_frontier

    empty = frontier.model_dump(mode="python")
    empty["points"] = ()
    empty["frontier_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="requires at least the hold plan"):
        type(frontier).model_validate(empty)

    duplicate = frontier.model_dump(mode="python")
    duplicate["points"] = (frontier.points[0], frontier.points[0])
    duplicate["frontier_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="canonically ordered"):
        type(frontier).model_validate(duplicate)

    unsealed = TransferCountFrontier.model_construct(
        points=frontier.points,
        frontier_sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="frontier semantic hash"):
        verify_transfer_count_frontier_hash(unsealed)
