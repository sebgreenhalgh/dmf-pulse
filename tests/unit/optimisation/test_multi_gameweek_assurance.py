"""Independent-review regressions for OPT-011 trust-boundary hardening."""

from __future__ import annotations

import os
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.errors import OptimisationError
from dmf_pulse.optimisation.manager_state import (
    ManagerState,
    seal_manager_state,
    validate_manager_state,
)
from dmf_pulse.optimisation.models import (
    OneGameweekPlan,
    SearchScope,
)
from dmf_pulse.optimisation.models import (
    OptimalityGuarantee as Stage10OptimalityGuarantee,
)
from dmf_pulse.optimisation.models import (
    SolverStatus as Stage10SolverStatus,
)
from dmf_pulse.optimisation.multi_gameweek_artifacts import (
    _write_once,
    load_canonical_json,
    persist_model,
    persist_result,
)
from dmf_pulse.optimisation.multi_gameweek_errors import (
    InputInvalidError,
    ResourceLimitReached,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    BackendStatus,
    MultiGameweekOptimisationRequest,
    MultiGameweekOptimisationResult,
    MultiGameweekPlan,
    MultiGameweekResultStatus,
    OptimalityGuarantee,
    TransferRules,
    seal_request,
    seal_result,
    seal_scenario_tree,
)
from dmf_pulse.optimisation.multi_gameweek_policy import (
    load_multi_gameweek_search_policy,
    load_terminal_value_policy,
)
from dmf_pulse.optimisation.multi_gameweek_service import (
    advance_current_action,
    optimise_multi_gameweek,
    reroot_request_after_observation,
)
from dmf_pulse.optimisation.multi_gameweek_solver import (
    enumerate_legal_actions,
    information_set_key,
    solve_frontier,
    validate_request,
)
from dmf_pulse.optimisation.stage10_adapter import StaticTacticalEvaluator
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import RulesetStatus
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules
from tests.support.multi_gameweek_factories import (
    NodeSpec,
    base_squad,
    build_request,
    compiled_ruleset,
    replace,
)

pytestmark = pytest.mark.unit
FIXTURE_ROOT = Path("fixtures/optimisation/multi_gameweek/adversarial")


def _request(name: str) -> MultiGameweekOptimisationRequest:
    return load_canonical_json(FIXTURE_ROOT / f"{name}.json", MultiGameweekOptimisationRequest)


def _success(
    name: str = "simple_one_ft",
) -> tuple[MultiGameweekOptimisationRequest, MultiGameweekOptimisationResult]:
    request = _request(name)
    result = optimise_multi_gameweek(request)
    assert result.status is MultiGameweekResultStatus.SUCCESS
    return request, result


def _terminal_failure_diagnostics(payload: dict[str, object]) -> dict[str, object]:
    diagnostics = deepcopy(payload)
    diagnostics.update(
        {
            "status": BackendStatus.SOLVER_BACKEND_ERROR.value,
            "termination_reason": "synthetic terminal failure",
            "optimality_guarantee": OptimalityGuarantee.NONE.value,
            "objective": None,
            "incumbent": None,
            "bound": None,
            "absolute_gap": None,
            "relative_gap": None,
            "deterministic_tie_key": None,
        }
    )
    return diagnostics


def test_frozen_exact_record_requires_internal_stage10_optimality_proof() -> None:
    request = _request("simple_one_ft")
    root = request.scenario_tree.root
    record = root.tactical_values[0]
    plan = OneGameweekPlan.model_validate(record.tactical_plan)
    plan = plan.model_copy(
        update={
            "solver_status": Stage10SolverStatus(
                search_scope=SearchScope.FIXED_SQUAD,
                guarantee=Stage10OptimalityGuarantee.NONE,
            ),
            "plan_sha256": "0" * 64,
        }
    )
    plan_payload = plan.model_dump(mode="json")
    plan_payload["plan_sha256"] = None
    plan = plan.model_copy(update={"plan_sha256": semantic_sha256(plan_payload)})
    bad_record = record.model_copy(
        update={
            "tactical_plan": plan.model_dump(mode="json"),
            "tactical_plan_sha256": plan.plan_sha256,
        }
    )
    bad_root = root.model_copy(update={"tactical_values": (bad_record, *root.tactical_values[1:])})
    tree = seal_scenario_tree(
        request.scenario_tree.model_copy(
            update={
                "nodes": (bad_root, *request.scenario_tree.nodes[1:]),
                "tree_sha256": "0" * 64,
            }
        )
    )
    malformed = seal_request(
        request.model_copy(update={"scenario_tree": tree, "request_sha256": "0" * 64})
    )
    with pytest.raises(InputInvalidError, match="exact optimal fixed-squad"):
        validate_request(malformed)


def test_observationally_identical_histories_cannot_change_action_scope() -> None:
    base = base_squad()
    request = build_request(
        (
            NodeSpec(node_id="root", gameweek=1, squads=(base,)),
            NodeSpec(
                node_id="left",
                parent_id="root",
                gameweek=2,
                conditional_probability=Decimal("0.5"),
                revealed_information=("SAME",),
                allowed_transfer_in_ids=("p15",),
                squads=(base,),
            ),
            NodeSpec(
                node_id="right",
                parent_id="root",
                gameweek=2,
                conditional_probability=Decimal("0.5"),
                revealed_information=("SAME",),
                allowed_transfer_in_ids=("p17",),
                squads=(base,),
            ),
        ),
        max_transfers_per_node=1,
    )
    root = request.scenario_tree.root
    nodes = [root]
    for node in request.scenario_tree.nodes[1:]:
        node = node.model_copy(update={"points_state_id": "same-points"})
        nodes.append(
            node.model_copy(
                update={
                    "information_set_key": information_set_key(
                        node, parent_key=root.information_set_key
                    )
                }
            )
        )
    tree = seal_scenario_tree(
        request.scenario_tree.model_copy(update={"nodes": tuple(nodes), "tree_sha256": "0" * 64})
    )
    malformed = seal_request(
        request.model_copy(update={"scenario_tree": tree, "request_sha256": "0" * 64})
    )
    with pytest.raises(InputInvalidError, match="different action scopes"):
        validate_request(malformed)


def test_action_cap_counts_invalid_raw_combinations_before_legality_filtering() -> None:
    base = base_squad()
    request = build_request(
        (
            NodeSpec(
                node_id="root",
                gameweek=1,
                allowed_transfer_in_ids=("p17",),
                squads=(base, replace(base, "p02", "p17")),
            ),
        ),
        max_transfers_per_node=1,
        max_actions_per_state=1,
    )
    with pytest.raises(ResourceLimitReached, match="candidate action combinations"):
        enumerate_legal_actions(
            request.initial_state,
            node=request.scenario_tree.root,
            candidate_pool=request.candidate_pool,
            rules=request.rules,
            policy=request.search_policy,
        )


def test_second_best_materially_distinct_policy_is_returned() -> None:
    _, result = _success()
    assert result.recommended_plan is not None
    assert result.conservative_plan.plan is not None
    assert result.high_upside_plan.plan is not None
    assert (
        result.conservative_plan.plan.current_action.action.signature
        != result.recommended_plan.current_action.action.signature
    )
    assert (
        result.high_upside_plan.plan.current_action.action.signature
        != result.recommended_plan.current_action.action.signature
    )
    assert result.conservative_plan.plan.selection_score < result.recommended_plan.selection_score


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("bank_path", "bank path"),
        ("leaf_expected", "leaf expected utilities"),
        ("terminal", "terminal values"),
        ("solver", "solver objective"),
    ),
)
def test_resealed_plan_cannot_hide_internal_reconciliation_errors(
    mutation: str, message: str
) -> None:
    _, result = _success()
    assert result.recommended_plan is not None
    payload = result.recommended_plan.model_dump(mode="json")
    if mutation == "bank_path":
        payload["bank_path_tenths"][0][1] += 1
    elif mutation == "leaf_expected":
        payload["leaf_utilities"][0]["expected_utility"] = str(
            Decimal(payload["leaf_utilities"][0]["expected_utility"]) + 1
        )
    elif mutation == "terminal":
        payload["terminal_value"]["bank_value"] = "1"
        payload["terminal_value"]["total"] = "1"
    else:
        score = Decimal(payload["selection_score"]) + 1
        for field in ("objective", "incumbent", "bound"):
            payload["solver_status"][field] = str(score)
    with pytest.raises(ValidationError, match=message):
        MultiGameweekPlan.model_validate(payload)


def test_terminal_failure_result_cannot_retain_alternative_plan() -> None:
    _, result = _success()
    assert result.conservative_plan.plan is not None
    payload = result.model_dump(mode="json")
    payload.update(
        {
            "status": MultiGameweekResultStatus.ERROR.value,
            "recommended_plan": None,
            "no_transfer_baseline": None,
            "marginal_value_of_each_move": None,
            "current_action": None,
            "future_policy": [],
            "solver_status": _terminal_failure_diagnostics(payload["solver_status"]),
            "confidence": "BLOCKED",
            "error_code": "SYNTHETIC_ERROR",
            "error_message": "synthetic terminal failure",
        }
    )
    with pytest.raises(ValidationError, match="cannot contain executable plans"):
        MultiGameweekOptimisationResult.model_validate(payload)


def test_advance_rejects_a_hash_valid_terminal_failure_even_if_plan_is_attached() -> None:
    request, result = _success()
    malformed = seal_result(result.model_copy(update={"status": MultiGameweekResultStatus.ERROR}))
    with pytest.raises(ValueError, match="only a successful"):
        advance_current_action(request, malformed)


def test_ownership_spells_cannot_overlap() -> None:
    _, result = _success("repurchase_resets_cohort")
    assert result.recommended_plan is not None
    state = result.recommended_plan.future_policy[-1].state_after
    payload = state.model_dump(mode="json")
    spells = [item for item in payload["ownership_spells"] if item["player_id"] == "mid_1"]
    assert len(spells) == 2
    spells[0]["ended_gameweek"] = spells[1]["started_gameweek"] + 1
    with pytest.raises(ValidationError, match="cannot overlap"):
        ManagerState.model_validate(payload)


def test_closed_ownership_spell_rechecks_realised_selling_price() -> None:
    request, result = _success("repurchase_resets_cohort")
    assert result.recommended_plan is not None
    state = result.recommended_plan.future_policy[-1].state_after
    closed = next(item for item in state.ownership_spells if not item.active)
    bad_spells = tuple(
        item.model_copy(
            update={"realised_selling_price_tenths": item.realised_selling_price_tenths + 1}
        )
        if item.spell_id == closed.spell_id
        else item
        for item in state.ownership_spells
    )
    malformed = seal_manager_state(state.model_copy(update={"ownership_spells": bad_spells}))
    with pytest.raises(ValueError, match="invalid realised selling price"):
        validate_manager_state(
            malformed,
            candidate_pool=request.candidate_pool,
            rules=request.rules,
        )


@pytest.mark.parametrize(
    ("update", "message"),
    (({"position_squad_quota": {"GK": 2, "DEF": 5, "MID": 6, "FWD": 3}}, "sum"),),
)
def test_transfer_rules_reject_impossible_global_limits(
    update: dict[str, object], message: str
) -> None:
    request = _request("simple_one_ft")
    payload = request.rules.model_dump(mode="json")
    payload.update(update)
    with pytest.raises(ValidationError, match=message):
        TransferRules.model_validate(payload)


def test_transfer_rules_allow_official_deadline_cap_above_final_squad_size() -> None:
    request = _request("simple_one_ft")
    payload = request.rules.model_dump(mode="json")
    payload["max_transfers_per_deadline"] = 20
    assert TransferRules.model_validate(payload).max_transfers_per_deadline == 20


def test_artifact_persistence_rejects_embedded_semantic_hash_mismatch(
    tmp_path: Path,
) -> None:
    _, result = _success()
    malformed = result.model_copy(update={"result_sha256": "0" * 64})
    with pytest.raises(OptimisationError, match="embedded semantic hash"):
        persist_result(malformed, artifact_root=tmp_path)


def test_generic_artifact_persistence_verifies_known_request_models(tmp_path: Path) -> None:
    request = _request("simple_one_ft")
    malformed = request.model_copy(update={"request_sha256": "0" * 64})
    with pytest.raises(OptimisationError, match="embedded semantic hash"):
        persist_model(
            malformed,
            artifact_root=tmp_path,
            category="requests",
            request_id=request.request_id,
        )


def test_artifact_write_once_rechecks_symlink_after_file_exists_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "artifact.json"
    raced = False
    original_is_symlink = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        return (raced and path == target) or original_is_symlink(path)

    def fake_link(_source: Path, _destination: Path) -> None:
        nonlocal raced
        raced = True
        raise FileExistsError

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    monkeypatch.setattr(os, "link", fake_link)
    with pytest.raises(OptimisationError, match="symbolic link"):
        _write_once(target, b"content", root=tmp_path)


def test_artifact_paths_reject_collisions_unsafe_segments_and_root_escape(
    tmp_path: Path,
) -> None:
    target = tmp_path / "root" / "artifact.json"
    target.parent.mkdir()
    target.write_bytes(b"existing")
    with pytest.raises(OptimisationError, match="different bytes"):
        _write_once(target, b"different", root=target.parent)
    _, result = _success()
    with pytest.raises(OptimisationError, match="safe artifact path segment"):
        persist_model(
            result,
            artifact_root=tmp_path,
            category="../results",
            request_id=result.request_id,
        )
    with pytest.raises(OptimisationError, match="escapes"):
        _write_once(tmp_path / "outside" / "artifact.json", b"x", root=tmp_path / "root")


@pytest.mark.parametrize("invalid", ("duplicate", "float"))
def test_search_policy_loader_uses_strict_rules_yaml_subset(tmp_path: Path, invalid: str) -> None:
    raw = Path("config/optimisation/multi_gameweek.yaml").read_text(encoding="utf-8")
    if invalid == "duplicate":
        raw += "max_transfers_per_node: 3\n"
    else:
        raw = raw.replace("max_transfers_per_node: 2", "max_transfers_per_node: 2.0")
    path = tmp_path / "invalid.yaml"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(InputInvalidError, match="invalid multi-Gameweek search policy"):
        load_multi_gameweek_search_policy(path)


def test_policy_loaders_wrap_missing_files_as_input_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(InputInvalidError, match="invalid multi-Gameweek search policy"):
        load_multi_gameweek_search_policy(missing)
    with pytest.raises(InputInvalidError, match="invalid terminal-value policy"):
        load_terminal_value_policy(missing)


def test_independent_oracles_do_not_import_stage11_solver_or_adapter() -> None:
    for path in (
        Path("tests/support/stage11_oracle.py"),
        Path("tests/support/multi_gameweek_oracle.py"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "multi_gameweek_solver" not in source
        assert "stage10_adapter" not in source


@pytest.mark.parametrize(
    "case",
    (
        "schema",
        "status",
        "unresolved",
        "missing_mapping",
        "invalid_mapping",
        "selling_branch",
        "literal",
        "accounting_order",
        "free_transfer_cap",
        "hit_sign",
        "preseason_type",
    ),
)
def test_rules_projection_fails_closed_on_invalid_transfer_semantics(case: str) -> None:
    compiled = compiled_ruleset()
    rules = deepcopy(compiled.rules)
    updates: dict[str, object] = {}
    if case == "schema":
        updates["schema_version"] = "1.0"
    elif case == "status":
        updates["status"] = RulesetStatus.CAPTURED_UNVERIFIED
    elif case == "unresolved":
        rules["transfers"]["transition"] = {
            "value": None,
            "verification_status": "UNKNOWN",
        }
    elif case == "missing_mapping":
        del rules["transfers"]["transition"]
    elif case == "invalid_mapping":
        rules["transfers"]["transition"] = 1
    elif case == "selling_branch":
        rules["prices"]["selling_price"]["above_purchase"] = "invalid"
    elif case == "literal":
        rules["prices"]["price_unit"] = "BINARY_FLOAT_MILLIONS"
    elif case == "accounting_order":
        rules["transfers"]["transition"]["transfer_accounting_order"] = []
    elif case == "free_transfer_cap":
        rules["transfers"]["transition"]["free_transfer_cap"] = True
    elif case == "hit_sign":
        rules["transfers"]["transition"]["hit_points"] = 4
    else:
        rules["transfers"]["transition"]["preseason_unlimited"] = "yes"
    malformed = compiled.model_copy(update={"rules": rules, **updates})
    with pytest.raises(RulesValidationError):
        build_multi_gameweek_transfer_rules(
            malformed,
            projection_mode=ProjectionMode.TEST,
        )


def test_rules_projection_supports_resolved_wrappers_and_disabled_preseason() -> None:
    compiled = compiled_ruleset()
    rules = deepcopy(compiled.rules)
    transition = rules["transfers"]["transition"]
    transition["preseason_unlimited"] = False
    rules["transfers"]["transition"] = {
        "value": transition,
        "verification_status": "VERIFIED",
    }
    resolved = build_multi_gameweek_transfer_rules(
        compiled.model_copy(update={"rules": rules}),
        projection_mode=ProjectionMode.TEST,
    )
    assert set(resolved.event_rules) == {"NORMAL"}


def test_rules_projection_requires_production_capability() -> None:
    with pytest.raises(RulesValidationError, match="FULL_SEASON"):
        build_multi_gameweek_transfer_rules(
            compiled_ruleset(),
            projection_mode=ProjectionMode.PRODUCTION,
        )


def test_service_converts_unexpected_input_value_error_to_blocked_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request("simple_one_ft")

    def reject(_request: MultiGameweekOptimisationRequest) -> None:
        raise ValueError("synthetic validation failure")

    monkeypatch.setattr("dmf_pulse.optimisation.multi_gameweek_service.validate_request", reject)
    result = optimise_multi_gameweek(request)
    assert result.status is MultiGameweekResultStatus.BLOCKED
    assert result.error_code == "MULTI_GAMEWEEK_INPUT_INVALID"


def test_service_fails_closed_when_recommended_plan_construction_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request("simple_one_ft")

    def reject(*_args: object, **_kwargs: object) -> None:
        raise ValueError("synthetic plan failure")

    monkeypatch.setattr("dmf_pulse.optimisation.multi_gameweek_service.build_plan", reject)
    result = optimise_multi_gameweek(request)
    assert result.status is MultiGameweekResultStatus.ERROR
    assert result.error_code == "OPTIMISER_EMITTED_INVALID_POLICY"


def test_service_fails_closed_when_exact_no_transfer_baseline_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request("simple_one_ft")
    frontier = solve_frontier(request, StaticTacticalEvaluator())

    def solve(
        _request: MultiGameweekOptimisationRequest,
        _evaluator: object,
        *,
        root_no_transfer_only: bool = False,
    ):
        if root_no_transfer_only:
            raise ValueError("synthetic baseline failure")
        return frontier

    monkeypatch.setattr("dmf_pulse.optimisation.multi_gameweek_service.solve_frontier", solve)
    result = optimise_multi_gameweek(request)
    assert result.status is MultiGameweekResultStatus.ERROR
    assert result.error_code == "NO_TRANSFER_BASELINE_UNAVAILABLE"


def test_service_fails_closed_when_alternative_validation_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request("simple_one_ft")

    def reject(*_args: object, **_kwargs: object) -> None:
        raise ValueError("synthetic alternative failure")

    monkeypatch.setattr("dmf_pulse.optimisation.multi_gameweek_service._build_alternative", reject)
    result = optimise_multi_gameweek(request)
    assert result.status is MultiGameweekResultStatus.ERROR
    assert result.error_code == "OPTIMISER_EMITTED_INVALID_POLICY"


def test_service_fails_closed_when_move_attribution_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request("simple_one_ft")

    def reject(*_args: object, **_kwargs: object) -> None:
        raise ValueError("synthetic attribution failure")

    monkeypatch.setattr(
        "dmf_pulse.optimisation.multi_gameweek_service.build_move_attribution", reject
    )
    result = optimise_multi_gameweek(request)
    assert result.status is MultiGameweekResultStatus.ERROR
    assert result.error_code == "MOVE_ATTRIBUTION_INVALID"


def test_rolling_horizon_rejects_missing_or_nonchild_observation() -> None:
    request, result = _success("injury_revealed_after_current_decision")
    unobserved = advance_current_action(request, result)
    with pytest.raises(ValueError, match="requires an observed child"):
        reroot_request_after_observation(request, unobserved)
    with pytest.raises(ValueError, match="immediate child"):
        advance_current_action(request, result, observed_node_id="not-a-child")
