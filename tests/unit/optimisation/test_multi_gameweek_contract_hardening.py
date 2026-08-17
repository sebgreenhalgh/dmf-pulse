"""Adversarial validation coverage for the public OPT-011 contracts."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.fpl_points.models import PlayerPosition
from dmf_pulse.optimisation.manager_state import (
    ManagerState,
    OwnershipSpell,
    seal_manager_state,
    selling_price_tenths,
    validate_manager_state,
    verify_manager_state_hash,
)
from dmf_pulse.optimisation.multi_gameweek_artifacts import load_canonical_json
from dmf_pulse.optimisation.multi_gameweek_models import (
    AlternativeAvailability,
    BackendStatus,
    FreeTransferArc,
    MultiGameweekOptimisationRequest,
    MultiGameweekOptimisationResult,
    MultiGameweekPlan,
    NodeDecision,
    OptimalityGuarantee,
    PlanAlternative,
    ScenarioTree,
    ScenarioTreeNode,
    SellingPriceRule,
    SolverDiagnostics,
    StateAdvanceResult,
    TacticalNodeEvaluation,
    TacticalValueRecord,
    TerminalValuePolicy,
    TransferAction,
    TransferRules,
    UtilityBreakdown,
    verify_advance_hash,
    verify_plan_hash,
    verify_request_hash,
    verify_result_hash,
    verify_scenario_tree_hash,
    verify_search_policy_hash,
    verify_terminal_policy_hash,
)
from dmf_pulse.optimisation.multi_gameweek_service import (
    advance_current_action,
    optimise_multi_gameweek,
)

pytestmark = pytest.mark.unit
ROOT = Path("fixtures/optimisation/multi_gameweek/adversarial")


def _request(name: str = "simple_one_ft") -> MultiGameweekOptimisationRequest:
    return load_canonical_json(ROOT / f"{name}.json", MultiGameweekOptimisationRequest)


def _success(name: str = "simple_one_ft"):
    request = _request(name)
    result = optimise_multi_gameweek(request)
    assert result.recommended_plan is not None
    return request, result


def test_selling_price_contract_rejects_profit_share_above_one() -> None:
    with pytest.raises(ValidationError, match="cannot exceed one"):
        SellingPriceRule(
            rule_id="invalid",
            retained_profit_numerator=2,
            retained_profit_denominator=1,
        )


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("negative_quota", "cannot be negative"),
        ("event_cap", "global maximum"),
        ("reset_before", "reset-before"),
        ("reset_after", "reset-after"),
    ),
)
def test_transfer_rules_reject_incoherent_event_and_quota_limits(case: str, message: str) -> None:
    payload = _request().rules.model_dump(mode="json")
    if case == "negative_quota":
        payload["position_squad_quota"] = {"GK": -1, "DEF": 8, "MID": 5, "FWD": 3}
    elif case == "event_cap":
        payload["event_rules"]["NORMAL"]["cap_after"] = 6
    elif case == "reset_before":
        payload["event_rules"]["NORMAL"].update({"cap_after": 5, "reset_before": 6})
    else:
        payload["event_rules"]["NORMAL"].update({"cap_after": 5, "reset_after": 6})
    with pytest.raises(ValidationError, match=message):
        TransferRules.model_validate(payload)


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        (
            {
                "action_id": "bad",
                "transfers_out": ["a"],
                "transfers_in": [],
            },
            "counts must match",
        ),
        (
            {
                "action_id": "bad",
                "transfers_out": ["b", "a"],
                "transfers_in": ["c", "d"],
            },
            "sorted and unique",
        ),
        (
            {
                "action_id": "bad",
                "transfers_out": ["a", "a"],
                "transfers_in": ["c", "d"],
            },
            "sorted and unique",
        ),
        (
            {
                "action_id": "bad",
                "transfers_out": ["a"],
                "transfers_in": ["a"],
            },
            "sold and repurchased",
        ),
    ),
)
def test_transfer_actions_reject_noncanonical_batches(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        TransferAction.model_validate(payload)


@pytest.mark.parametrize(
    ("update", "message"),
    (
        (
            {"unlimited_transfers_without_hits": True, "free_used": 1},
            "unlimited transfer events",
        ),
        ({"paid_transfers": 1}, "must reconcile"),
        ({"effective_ft_before": 0}, "exceed effective"),
        ({"ft_after": 6}, "exceeds configured maximum"),
    ),
)
def test_free_transfer_arc_rejects_incoherent_accounting(
    update: dict[str, object], message: str
) -> None:
    payload: dict[str, object] = {
        "event": "NORMAL",
        "effective_ft_before": 1,
        "transfer_count": 1,
        "free_used": 1,
        "paid_transfers": 0,
        "hit_points": 0,
        "earned_for_next_deadline": 1,
        "ft_after": 1,
        "maximum_free_transfers": 5,
    }
    payload.update(update)
    with pytest.raises(ValidationError, match=message):
        FreeTransferArc.model_validate(payload)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("squad_order", "sorted"),
        ("squad_duplicate", "unique"),
        ("quantile", "monotone"),
    ),
)
def test_tactical_record_rejects_noncanonical_or_nonmonotone_values(
    case: str, message: str
) -> None:
    record = _request().scenario_tree.root.tactical_values[0]
    payload = record.model_dump(mode="json")
    if case == "squad_order":
        payload["squad_ids"] = list(reversed(payload["squad_ids"]))
    elif case == "squad_duplicate":
        payload["squad_ids"][1] = payload["squad_ids"][0]
        payload["squad_ids"].sort()
    else:
        payload["p10_points"] = str(Decimal(payload["expected_points"]) + 1)
    with pytest.raises(ValidationError, match=message):
        TacticalValueRecord.model_validate(payload)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("revelation_order", "revealed information must be sorted"),
        ("revelation_duplicate", "revealed information must be unique"),
        ("scope_order", "transfer-in IDs must be sorted"),
        ("scope_duplicate", "transfer-in IDs must be unique"),
        ("records_order", "sorted by squad signature"),
        ("records_duplicate", "unique squad signatures"),
    ),
)
def test_scenario_node_rejects_noncanonical_collections(case: str, message: str) -> None:
    request = _request("injury_revealed_after_current_decision")
    node = request.scenario_tree.nodes[1]
    payload = node.model_dump(mode="json")
    if case == "revelation_order":
        payload["revealed_information"] = ["z", "a"]
    elif case == "revelation_duplicate":
        payload["revealed_information"] = ["same", "same"]
    elif case == "scope_order":
        payload["allowed_transfer_in_ids"] = ["mid_7", "mid_6"]
    elif case == "scope_duplicate":
        payload["allowed_transfer_in_ids"] = ["mid_6", "mid_6"]
    elif case == "records_order":
        payload["tactical_values"] = list(reversed(payload["tactical_values"]))
    else:
        payload["tactical_values"] = [
            payload["tactical_values"][0],
            payload["tactical_values"][0],
        ]
    with pytest.raises(ValidationError, match=message):
        ScenarioTreeNode.model_validate(payload)


def test_scenario_tree_rejects_order_duplicates_and_ambiguous_root() -> None:
    tree = _request("injury_revealed_after_current_decision").scenario_tree
    payload = tree.model_dump(mode="json")
    payload["nodes"] = list(reversed(payload["nodes"]))
    with pytest.raises(ValidationError, match="must be sorted"):
        ScenarioTree.model_validate(payload)
    payload = tree.model_dump(mode="json")
    payload["nodes"][1]["node_id"] = payload["nodes"][0]["node_id"]
    payload["nodes"] = sorted(
        payload["nodes"], key=lambda item: (item["gameweek"], item["node_id"])
    )
    with pytest.raises(ValidationError, match="must be unique"):
        ScenarioTree.model_validate(payload)
    ambiguous = tree.model_copy(
        update={"nodes": tuple(item.model_copy(update={"parent_id": None}) for item in tree.nodes)}
    )
    with pytest.raises(ValueError, match="exactly one root"):
        _ = ambiguous.root


def test_terminal_policy_rejects_disabled_latent_weights() -> None:
    payload = _request().terminal_policy.model_dump(mode="json")
    payload["bank_points_per_tenth"] = "1"
    with pytest.raises(ValidationError, match="must have zero coefficients"):
        TerminalValuePolicy.model_validate(payload)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("candidate_order", "players must be sorted"),
        ("candidate_duplicate", "IDs must be unique"),
        ("assumption_order", "assumptions must be sorted"),
        ("assumption_duplicate", "assumptions must be unique"),
        ("mode", "projection modes differ"),
    ),
)
def test_request_rejects_noncanonical_identity_and_mode(case: str, message: str) -> None:
    payload = _request().model_dump(mode="json")
    if case == "candidate_order":
        payload["candidate_pool"] = list(reversed(payload["candidate_pool"]))
    elif case == "candidate_duplicate":
        payload["candidate_pool"][1] = payload["candidate_pool"][0]
    elif case == "assumption_order":
        payload["assumptions"] = ["z", "a"]
    elif case == "assumption_duplicate":
        payload["assumptions"] = ["same", "same"]
    else:
        payload["projection_mode"] = "PRODUCTION"
    with pytest.raises(ValidationError, match=message):
        MultiGameweekOptimisationRequest.model_validate(payload)


def test_tactical_evaluation_requires_monotone_quantiles() -> None:
    _, result = _success()
    assert result.recommended_plan is not None
    payload = result.recommended_plan.current_action.tactical_evaluation.model_dump(mode="json")
    payload["p10_points"] = str(Decimal(payload["expected_points"]) + 1)
    with pytest.raises(ValidationError, match="must be monotone"):
        TacticalNodeEvaluation.model_validate(payload)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("state_bank", "bank path"),
        ("state_ft", "FT path"),
        ("state_squad", "squad path"),
        ("gameweek", "advance exactly one"),
        ("node", "decision-node lineage"),
        ("selling", "selling-price rows"),
        ("buying", "buying-price rows"),
        ("cash", "conserve transfer cash"),
        ("paid", "cannot exceed"),
        ("hit", "cannot carry a hit"),
    ),
)
def test_node_decision_rejects_nonreconciling_paths(case: str, message: str) -> None:
    _, result = _success()
    assert result.recommended_plan is not None
    payload = result.recommended_plan.current_action.model_dump(mode="json")
    if case == "state_bank":
        payload["state_after"]["bank_tenths"] += 1
    elif case == "state_ft":
        payload["state_after"]["free_transfers"] += 1
    elif case == "state_squad":
        payload["state_after"]["ownership_spells"] = payload["state_after"]["ownership_spells"][:-1]
    elif case == "gameweek":
        payload["state_after"]["current_gameweek"] += 1
    elif case == "node":
        payload["state_after"]["observed_node_id"] = "wrong-node"
    elif case == "selling":
        payload["selling_prices"][0]["player_id"] = "wrong"
    elif case == "buying":
        payload["buying_prices"][0]["player_id"] = "wrong"
    elif case == "cash":
        payload["bank_before_tenths"] += 1
    elif case == "paid":
        payload["paid_transfers"] = payload["action"]["transfers_out"].__len__() + 1
    else:
        payload["hit_points"] = 1
    with pytest.raises(ValidationError, match=message):
        NodeDecision.model_validate(payload)


@pytest.mark.parametrize(
    ("status", "update", "message"),
    (
        (
            BackendStatus.TIME_RESOURCE_LIMIT_WITH_INCUMBENT,
            {"objective": "1", "incumbent": "1", "bound": "1"},
            "unproved bound",
        ),
        (
            BackendStatus.FEASIBLE_NOT_PROVEN_OPTIMAL,
            {"objective": "2", "incumbent": "1"},
            "must equal",
        ),
        (
            BackendStatus.TIME_RESOURCE_LIMIT_NO_INCUMBENT,
            {"objective": "1"},
            "cannot contain an incumbent",
        ),
        (
            BackendStatus.INFEASIBLE,
            {"objective": "1"},
            "cannot carry objective claims",
        ),
    ),
)
def test_solver_diagnostics_reject_false_terminal_claims(
    status: BackendStatus, update: dict[str, object], message: str
) -> None:
    payload: dict[str, object] = {
        "status": status.value,
        "termination_reason": "synthetic",
        "optimality_guarantee": OptimalityGuarantee.NONE.value,
        "configuration_sha256": "0" * 64,
    }
    payload.update(update)
    with pytest.raises(ValidationError, match=message):
        SolverDiagnostics.model_validate(payload)


def test_utility_breakdown_requires_exact_component_reconciliation() -> None:
    with pytest.raises(ValidationError, match="do not reconcile"):
        UtilityBreakdown(
            expected_horizon_utility=Decimal(1),
            current_gameweek_contribution=Decimal(2),
            future_contribution=Decimal(0),
            expected_hit_cost=Decimal(0),
            terminal_flexibility_contribution=Decimal(0),
            objective_total=Decimal(1),
        )


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("decision_order", "decisions must be sorted"),
        ("decision_duplicate", "duplicate decision nodes"),
        ("leaf_order", "leaf utilities must be sorted"),
        ("leaf_probability", "sum exactly to one"),
        ("assumption_order", "assumptions must be sorted"),
        ("assumption_duplicate", "assumptions must be unique"),
        ("ft_path", "free-transfer path"),
        ("squad_path", "squad path"),
        ("selection", "selection utilities"),
    ),
)
def test_plan_rejects_noncanonical_policy_and_summary_paths(case: str, message: str) -> None:
    _, result = _success("injury_revealed_after_current_decision")
    assert result.recommended_plan is not None
    payload = result.recommended_plan.model_dump(mode="json")
    if case == "decision_order":
        payload["current_action"], payload["future_policy"][0] = (
            payload["future_policy"][0],
            payload["current_action"],
        )
    elif case == "decision_duplicate":
        payload["future_policy"] = [payload["current_action"]]
    elif case == "leaf_order":
        payload["leaf_utilities"] = list(reversed(payload["leaf_utilities"]))
    elif case == "leaf_probability":
        payload["leaf_utilities"][0]["probability"] = "0.4"
    elif case == "assumption_order":
        payload["assumptions"] = ["z", "a"]
    elif case == "assumption_duplicate":
        payload["assumptions"] = ["same", "same"]
    elif case == "ft_path":
        payload["free_transfer_path"][0][1] += 1
    elif case == "squad_path":
        payload["squad_path"][0][1] = []
    else:
        payload["selection_score"] = str(Decimal(payload["selection_score"]) + 1)
    with pytest.raises(ValidationError, match=message):
        MultiGameweekPlan.model_validate(payload)


def test_alternative_contract_requires_plan_only_for_distinct_status() -> None:
    _, result = _success()
    assert result.recommended_plan is not None
    with pytest.raises(ValidationError, match="plan presence disagree"):
        PlanAlternative(
            availability=AlternativeAvailability.UNAVAILABLE,
            plan=result.recommended_plan,
            reason="invalid",
        )


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("assumptions", "assumptions must be sorted and unique"),
        ("warnings", "warnings must be sorted and unique"),
        ("current", "current action differs"),
        ("future", "future policy differs"),
        ("kind", "wrong plan kind"),
        ("solver", "solver status differs"),
        ("baseline", "must retain the root squad"),
        ("alternative", "wrong plan kind"),
        ("success_plan", "requires a recommended plan"),
        ("success_baseline", "requires baseline"),
        ("success_error", "cannot carry a terminal error"),
    ),
)
def test_result_rejects_incoherent_public_output(case: str, message: str) -> None:
    _, result = _success("price_change_blocks_later_route")
    payload = result.model_dump(mode="json")
    if case == "assumptions":
        payload["assumptions"] = ["z", "a"]
    elif case == "warnings":
        payload["warnings"] = ["same", "same"]
    elif case == "current":
        payload["current_action"] = payload["no_transfer_baseline"]["current_action"]["action"]
    elif case == "future":
        payload["future_policy"] = []
    elif case == "kind":
        payload["recommended_plan"]["plan_kind"] = "CONSERVATIVE"
    elif case == "solver":
        payload["solver_status"] = payload["no_transfer_baseline"]["solver_status"]
    elif case == "baseline":
        baseline = deepcopy(payload["recommended_plan"])
        baseline["plan_kind"] = "NO_TRANSFER_BASELINE"
        payload["no_transfer_baseline"] = baseline
    elif case == "alternative":
        payload["conservative_plan"]["plan"]["plan_kind"] = "HIGH_UPSIDE"
    elif case == "success_plan":
        payload["recommended_plan"] = None
    elif case == "success_baseline":
        payload["no_transfer_baseline"] = None
    else:
        payload["error_code"] = "INVALID"
        payload["error_message"] = "invalid"
    with pytest.raises(ValidationError, match=message):
        MultiGameweekOptimisationResult.model_validate(payload)


def test_state_advance_observation_must_match_manager_state() -> None:
    request, result = _success("injury_revealed_after_current_decision")
    advance = advance_current_action(request, result, observed_node_id="n2_a")
    payload = advance.model_dump(mode="json")
    payload["observed_node_id"] = "n2_b"
    with pytest.raises(ValidationError, match="differs from its observed node"):
        StateAdvanceResult.model_validate(payload)


def test_every_stage11_embedded_hash_verifier_rejects_tampering() -> None:
    request, result = _success("injury_revealed_after_current_decision")
    assert result.recommended_plan is not None
    advance = advance_current_action(request, result, observed_node_id="n2_a")
    cases = (
        (
            verify_scenario_tree_hash,
            request.scenario_tree.model_copy(update={"tree_sha256": "0" * 64}),
        ),
        (
            verify_search_policy_hash,
            request.search_policy.model_copy(update={"policy_sha256": "0" * 64}),
        ),
        (
            verify_terminal_policy_hash,
            request.terminal_policy.model_copy(update={"policy_sha256": "0" * 64}),
        ),
        (verify_request_hash, request.model_copy(update={"request_sha256": "0" * 64})),
        (verify_plan_hash, result.recommended_plan.model_copy(update={"plan_sha256": "0" * 64})),
        (verify_result_hash, result.model_copy(update={"result_sha256": "0" * 64})),
        (verify_advance_hash, advance.model_copy(update={"advance_sha256": "0" * 64})),
    )
    for verifier, value in cases:
        with pytest.raises(ValueError, match="semantic hash"):
            verifier(value)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("end_node", "end node and Gameweek"),
        ("sale", "requires its realised selling price"),
        ("chronology", "cannot end before"),
    ),
)
def test_ownership_spell_rejects_partial_or_impossible_closure(case: str, message: str) -> None:
    payload = _request().initial_state.active_spells[0].model_dump(mode="json")
    if case == "end_node":
        payload["ended_at_node_id"] = "node"
    elif case == "sale":
        payload.update({"ended_gameweek": 1, "ended_at_node_id": "node"})
    else:
        payload.update(
            {
                "started_gameweek": 2,
                "ended_gameweek": 1,
                "ended_at_node_id": "node",
                "realised_selling_price_tenths": payload["current_price_tenths"],
            }
        )
    with pytest.raises(ValidationError, match=message):
        OwnershipSpell.model_validate(payload)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("order", "canonically sorted"),
        ("spell_id", "spell IDs must be unique"),
        ("active_duplicate", "non-empty unique squad"),
        ("active_not_latest", "must be the player's latest"),
    ),
)
def test_manager_state_rejects_noncanonical_ownership_history(case: str, message: str) -> None:
    if case == "active_not_latest":
        _, result = _success("repurchase_resets_cohort")
        assert result.recommended_plan is not None
        payload = result.recommended_plan.future_policy[-1].state_after.model_dump(mode="json")
        spells = [item for item in payload["ownership_spells"] if item["player_id"] == "mid_1"]
        spells[0].update(
            {
                "ended_gameweek": None,
                "ended_at_node_id": None,
                "realised_selling_price_tenths": None,
            }
        )
        spells[1].update(
            {
                "ended_gameweek": spells[1]["started_gameweek"],
                "ended_at_node_id": "closed",
                "realised_selling_price_tenths": spells[1]["current_price_tenths"],
            }
        )
    else:
        payload = _request().initial_state.model_dump(mode="json")
        if case == "order":
            payload["ownership_spells"] = list(reversed(payload["ownership_spells"]))
        elif case == "spell_id":
            payload["ownership_spells"][1]["spell_id"] = payload["ownership_spells"][0]["spell_id"]
        else:
            payload["ownership_spells"][1]["player_id"] = payload["ownership_spells"][0][
                "player_id"
            ]
            payload["ownership_spells"] = sorted(
                payload["ownership_spells"],
                key=lambda item: (
                    item["player_id"],
                    item["started_gameweek"],
                    item["spell_id"],
                ),
            )
    with pytest.raises(ValidationError, match=message):
        ManagerState.model_validate(payload)


def test_manager_state_hash_and_negative_price_inputs_fail_closed() -> None:
    state = _request().initial_state
    with pytest.raises(ValueError, match="semantic hash"):
        verify_manager_state_hash(state.model_copy(update={"state_sha256": "0" * 64}))
    with pytest.raises(ValueError, match="non-negative"):
        selling_price_tenths(
            purchase_price_tenths=-1,
            current_price_tenths=1,
            rule=_request().rules.selling_price_rule,
        )


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("lineage", "lineage differ"),
        ("free_transfers", "exceeds configured maximum"),
        ("candidate_duplicate", "duplicate player IDs"),
        ("squad_size", "wrong size"),
        ("unknown_active", "unknown player"),
        ("unknown_history", "history contains an unknown"),
        ("metadata", "metadata differs"),
        ("position", "position quotas"),
        ("club", "club maximum"),
    ),
)
def test_manager_state_validation_rejects_every_illegal_boundary(case: str, message: str) -> None:
    request = _request("repurchase_resets_cohort" if case == "unknown_history" else "simple_one_ft")
    if case == "unknown_history":
        result = optimise_multi_gameweek(request)
        assert result.recommended_plan is not None
        state = result.recommended_plan.future_policy[-1].state_after
    else:
        state = request.initial_state
    pool = request.candidate_pool
    rules = request.rules
    if case == "lineage":
        state = seal_manager_state(state.model_copy(update={"ruleset_id": "wrong"}))
    elif case == "free_transfers":
        state = seal_manager_state(
            state.model_copy(update={"free_transfers": rules.maximum_free_transfers + 1})
        )
    elif case == "candidate_duplicate":
        pool = (pool[0], pool[0], *pool[2:])
    elif case == "squad_size":
        state = seal_manager_state(
            state.model_copy(update={"ownership_spells": state.ownership_spells[:-1]})
        )
    elif case == "unknown_active":
        first = state.ownership_spells[0].model_copy(update={"player_id": "unknown"})
        state = seal_manager_state(
            state.model_copy(update={"ownership_spells": (first, *state.ownership_spells[1:])})
        )
    elif case == "unknown_history":
        closed = next(item for item in state.ownership_spells if not item.active)
        spells = tuple(
            item.model_copy(update={"player_id": "unknown-history"})
            if item.spell_id == closed.spell_id
            else item
            for item in state.ownership_spells
        )
        state = seal_manager_state(state.model_copy(update={"ownership_spells": spells}))
    elif case == "metadata":
        first = state.ownership_spells[0].model_copy(update={"club_id": "wrong"})
        state = seal_manager_state(
            state.model_copy(update={"ownership_spells": (first, *state.ownership_spells[1:])})
        )
    elif case == "position":
        target = next(item for item in state.ownership_spells if item.position is PlayerPosition.GK)
        player_id = target.player_id
        spells = tuple(
            item.model_copy(update={"position": PlayerPosition.DEF})
            if item.player_id == player_id
            else item
            for item in state.ownership_spells
        )
        state = seal_manager_state(state.model_copy(update={"ownership_spells": spells}))
        pool = tuple(
            item.model_copy(update={"position": PlayerPosition.DEF})
            if item.player_id == player_id
            else item
            for item in pool
        )
    else:
        ids = {item.player_id for item in state.active_spells[:4]}
        state = seal_manager_state(
            state.model_copy(
                update={
                    "ownership_spells": tuple(
                        item.model_copy(update={"club_id": "same-club"})
                        if item.player_id in ids
                        else item
                        for item in state.ownership_spells
                    )
                }
            )
        )
        pool = tuple(
            item.model_copy(update={"club_id": "same-club"}) if item.player_id in ids else item
            for item in pool
        )
    with pytest.raises(ValueError, match=message):
        validate_manager_state(state, candidate_pool=pool, rules=rules)
