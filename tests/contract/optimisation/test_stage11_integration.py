"""Cross-boundary Stage-9/10/11, artifact, CLI and rolling-horizon tests."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.optimise import optimise_app
from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.errors import OptimisationError
from dmf_pulse.optimisation.models import (
    OneGameweekOptimiserPolicy,
    OneGameweekPlan,
    SearchScope,
)
from dmf_pulse.optimisation.models import (
    OptimalityGuarantee as Stage10OptimalityGuarantee,
)
from dmf_pulse.optimisation.multi_gameweek_artifacts import (
    load_canonical_json,
    load_verified_artifact,
    persist_advance,
    persist_result,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekOptimisationRequest,
    MultiGameweekOptimisationResult,
    ScenarioTree,
    StateAdvanceResult,
    seal_request,
    seal_scenario_tree,
)
from dmf_pulse.optimisation.multi_gameweek_service import (
    advance_current_action,
    optimise_multi_gameweek,
)
from dmf_pulse.optimisation.multi_gameweek_solver import information_set_key
from dmf_pulse.optimisation.stage10_adapter import Stage10TacticalAdapter
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.multi_gameweek_factories import (
    NodeSpec,
    _scenario,
    base_squad,
    build_request,
    compiled_ruleset,
)

pytestmark = pytest.mark.integration
RUNNER = CliRunner()
FIXTURE_ROOT = Path("fixtures/optimisation/multi_gameweek")
ADVERSARIAL_ROOT = FIXTURE_ROOT / "adversarial"


def test_reference_rules_compile_to_exact_request_transfer_view() -> None:
    request = load_canonical_json(FIXTURE_ROOT / "request.json", MultiGameweekOptimisationRequest)
    compiled = compiled_ruleset()
    resolved = build_multi_gameweek_transfer_rules(compiled, projection_mode=ProjectionMode.TEST)
    assert resolved == request.rules
    assert resolved.capability == "REFERENCE_ONLY"
    assert resolved.hit_cost_per_paid_transfer == 4
    assert resolved.maximum_free_transfers == 5


def test_frozen_stage10_record_is_a_canonical_stage9_driven_plan() -> None:
    request = load_canonical_json(FIXTURE_ROOT / "request.json", MultiGameweekOptimisationRequest)
    record = request.scenario_tree.root.tactical_values[0]
    plan = OneGameweekPlan.model_validate(record.tactical_plan)
    assert plan.plan_sha256 == record.tactical_plan_sha256
    assert plan.squad == record.squad_ids
    assert plan.scenario_scores
    assert plan.expected_manager_points == record.expected_points


def test_explicit_stage10_adapter_uses_joint_scenario_and_stage10_evaluator(monkeypatch) -> None:
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                points={"p07": 4, "p08": 2},
                squads=(base_squad(),),
            ),
        ),
        max_transfers_per_node=0,
    )
    node = request.scenario_tree.root
    embedded = OneGameweekPlan.model_validate(node.tactical_values[0].tactical_plan)
    monkeypatch.setattr(
        "dmf_pulse.optimisation.stage10_adapter.enumerate_tactical_configurations",
        lambda *_args, **_kwargs: (iter((embedded.tactical_configuration,)), 1),
    )
    adapter = Stage10TacticalAdapter(
        candidate_pool=request.candidate_pool,
        rules=build_one_gameweek_rules_view(
            compiled_ruleset(), projection_mode=ProjectionMode.TEST
        ),
        policy=OneGameweekOptimiserPolicy(
            max_squad_candidates=1,
            max_tactical_configurations=1,
            max_scenario_score_operations=100,
            max_returned_ties=1,
        ),
        scenarios_by_node={
            "root": _scenario(
                node_id="root",
                gameweek=1,
                catalog=request.candidate_pool,
                points={"p07": 4, "p08": 2},
            )
        },
    )
    evaluated = adapter.evaluate(node=node, state=request.initial_state)
    assert evaluated.source == "STAGE10_ADAPTER"
    assert evaluated.expected_points == embedded.expected_manager_points
    evaluated_plan = OneGameweekPlan.model_validate(evaluated.tactical_plan)
    assert evaluated_plan.plan_sha256 == evaluated.tactical_plan_sha256
    assert evaluated_plan.solver_status.termination == "OPTIMAL"
    assert evaluated_plan.solver_status.search_scope is SearchScope.FIXED_SQUAD
    assert evaluated_plan.solver_status.guarantee is Stage10OptimalityGuarantee.EXACT_FIXED_SQUAD


def test_immutable_result_and_advance_artifacts_round_trip_and_detect_tampering(
    tmp_path: Path,
) -> None:
    request = load_canonical_json(
        ADVERSARIAL_ROOT / "injury_revealed_after_current_decision.json",
        MultiGameweekOptimisationRequest,
    )
    result = optimise_multi_gameweek(request)
    result_path = persist_result(result, artifact_root=tmp_path)
    assert load_verified_artifact(result_path, MultiGameweekOptimisationResult) == result
    advanced = advance_current_action(request, result, observed_node_id="n2_a")
    advance_path = persist_advance(advanced, artifact_root=tmp_path)
    assert load_verified_artifact(advance_path, StateAdvanceResult) == advanced
    result_path.write_bytes(result_path.read_bytes() + b" ")
    with pytest.raises(OptimisationError, match="detached hash"):
        load_verified_artifact(result_path, MultiGameweekOptimisationResult)


def test_rolling_horizon_executes_observes_then_reoptimises() -> None:
    request = load_canonical_json(
        ADVERSARIAL_ROOT / "injury_revealed_after_current_decision.json",
        MultiGameweekOptimisationRequest,
    )
    first = optimise_multi_gameweek(request)
    advanced = advance_current_action(request, first, observed_node_id="n2_a")
    child = next(node for node in request.scenario_tree.nodes if node.node_id == "n2_a")
    root_child = child.model_copy(
        update={
            "parent_id": None,
            "conditional_probability": Decimal(1),
            "information_set_key": "temporary",
        }
    )
    root_child = root_child.model_copy(
        update={"information_set_key": information_set_key(root_child, parent_key=None)}
    )
    tree = seal_scenario_tree(
        ScenarioTree(
            tree_id=request.scenario_tree.tree_id + "-rerooted",
            nodes=(root_child,),
            tree_sha256="0" * 64,
        )
    )
    rerooted = seal_request(
        request.model_copy(
            update={
                "request_id": request.request_id + "-rerooted",
                "initial_state": advanced.manager_state,
                "scenario_tree": tree,
                "request_sha256": "0" * 64,
            }
        )
    )
    second = optimise_multi_gameweek(rerooted)
    assert first.current_action is not None and first.current_action.transfer_count == 0
    assert second.current_action is not None
    assert second.current_action.signature == "NORMAL|mid_1->mid_6"


def test_supported_cli_vertical_slice_optimise_then_advance(tmp_path: Path) -> None:
    request_path = FIXTURE_ROOT / "request.json"
    rules_path = FIXTURE_ROOT / "reference_ruleset_test_only.json"
    first = RUNNER.invoke(
        optimise_app,
        [
            "multi-gameweek",
            "--request",
            str(request_path),
            "--ruleset",
            str(rules_path),
            "--artifact-root",
            str(tmp_path),
            "--output",
            "json",
        ],
    )
    assert first.exit_code == 0, first.stdout
    payload = json.loads(first.stdout)
    assert payload["status"] == "SUCCESS"
    assert payload["current_action"]["transfers_in"] == ["p15"]
    result_path = next((tmp_path / "optimisation/multi_gameweek/results").rglob("*.json"))
    second = RUNNER.invoke(
        optimise_app,
        [
            "advance-multi-gameweek",
            "--request",
            str(request_path),
            "--result",
            str(result_path),
            "--artifact-root",
            str(tmp_path),
            "--observed-node",
            "gw2-price-rise",
            "--output",
            "json",
        ],
    )
    assert second.exit_code == 0, second.stdout
    advanced = json.loads(second.stdout)
    assert advanced["executed_action"]["transfers_in"] == ["p15"]
    assert advanced["manager_state"]["current_gameweek"] == 2
    assert advanced["manager_state"]["observed_node_id"] == "gw2-price-rise"
