"""Free Hit temporary-policy comparison with exact permanent-state restoration."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import isfinite
from typing import Literal

from dmf_pulse.chips.definitions import (
    ActivationStatus,
    CompiledChipBundle,
    CompiledChipDefinition,
    semantic_sha256,
)
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import ChipInventory, TokenStatus, activate_token
from dmf_pulse.chips.policy_models import (
    ChipPolicyCandidate,
    FreeHitEvaluation,
    FreeHitScenarioValue,
    PolicyCostProfile,
    PolicyRole,
    PolicyScenarioScore,
)
from dmf_pulse.optimisation.manager_state import (
    ManagerState,
    seal_manager_state,
    validate_manager_state,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    NodeDecision,
    PlayerCatalogEntry,
    ScenarioTreeNode,
    TransferRules,
)
from dmf_pulse.optimisation.multi_gameweek_solver import resolve_free_transfer_arc

_REQUIRED_FREE_HIT_EFFECTS = frozenset(
    {
        ("TRANSFERS", "UNLIMITED_FREE"),
        ("TRANSFERS", "PRESERVE_SAVED_FREE_TRANSFERS"),
        ("SQUAD", "RESTORE_NEXT_DEADLINE"),
        ("BANK", "RESTORE_NEXT_DEADLINE"),
        ("PURCHASE_PRICES", "RESTORE_NEXT_DEADLINE"),
    }
)


def make_policy_candidate(
    *,
    policy_id: str,
    policy_role: PolicyRole,
    state_before_sha256: str,
    state_after_sha256: str,
    transition_event: str,
    squad_ids: Iterable[str],
    bank_tenths: int,
    active_purchase_spell_ids: Iterable[str],
    free_transfers_after: int,
    transfer_count: int,
    transfer_hit_points: float,
    tactical_plan_sha256: str,
    scenario_scores: Iterable[PolicyScenarioScore],
    costs: PolicyCostProfile | None = None,
    continuation_value: float = 0.0,
) -> ChipPolicyCandidate:
    """Seal one policy candidate from a previously legal tactical/transfer evaluation."""

    scores = tuple(
        sorted(scenario_scores, key=lambda item: (item.scenario_id, item.outcome_draw_id))
    )
    ordered_squad_ids = tuple(sorted(str(item) for item in squad_ids))
    ordered_spell_ids = tuple(sorted(str(item) for item in active_purchase_spell_ids))
    expected = sum(item.weight * item.manager_points for item in scores)
    payload: dict[str, object] = {
        "policy_id": policy_id,
        "policy_role": policy_role,
        "state_before_sha256": state_before_sha256,
        "state_after_sha256": state_after_sha256,
        "transition_event": transition_event,
        "squad_ids": ordered_squad_ids,
        "bank_tenths": bank_tenths,
        "active_purchase_spell_ids": ordered_spell_ids,
        "free_transfers_after": free_transfers_after,
        "transfer_count": transfer_count,
        "transfer_hit_points": transfer_hit_points,
        "tactical_plan_sha256": tactical_plan_sha256,
        "scenario_scores": [item.model_dump(mode="json") for item in scores],
        "expected_current_points": float(expected),
        "costs": (costs or PolicyCostProfile()).model_dump(mode="json"),
        "continuation_value": continuation_value,
    }
    return ChipPolicyCandidate(
        policy_id=policy_id,
        policy_role=policy_role,
        state_before_sha256=state_before_sha256,
        state_after_sha256=state_after_sha256,
        transition_event=transition_event,
        squad_ids=ordered_squad_ids,
        bank_tenths=bank_tenths,
        active_purchase_spell_ids=ordered_spell_ids,
        free_transfers_after=free_transfers_after,
        transfer_count=transfer_count,
        transfer_hit_points=transfer_hit_points,
        tactical_plan_sha256=tactical_plan_sha256,
        scenario_scores=scores,
        expected_current_points=float(expected),
        costs=costs or PolicyCostProfile(),
        continuation_value=continuation_value,
        candidate_hash=semantic_sha256(payload),
    )


def policy_candidate_from_stage11(
    decision: NodeDecision,
    *,
    policy_id: str,
    policy_role: PolicyRole,
    scenario_scores: Iterable[PolicyScenarioScore],
    costs: PolicyCostProfile | None = None,
    continuation_value: float = 0.0,
) -> ChipPolicyCandidate:
    """Adapt the accepted Stage-11 root decision without reimplementing its transitions."""

    scores = tuple(scenario_scores)
    expected = sum(item.weight * item.manager_points for item in scores)
    if abs(float(decision.tactical_evaluation.expected_points) - expected) > 1e-9:
        raise ChipError(
            "CHIP_POLICY_STAGE10_MISMATCH",
            "common-scenario scores differ from the accepted Stage-10 tactical evaluation",
            policy_id=policy_id,
        )
    return make_policy_candidate(
        policy_id=policy_id,
        policy_role=policy_role,
        state_before_sha256=decision.state_before_sha256,
        state_after_sha256=decision.state_after.state_sha256,
        transition_event=decision.action.transition_event,
        squad_ids=decision.squad_after,
        bank_tenths=decision.bank_after_tenths,
        active_purchase_spell_ids=(item.spell_id for item in decision.state_after.active_spells),
        free_transfers_after=decision.free_transfers_after,
        transfer_count=decision.action.transfer_count,
        transfer_hit_points=float(decision.hit_points),
        tactical_plan_sha256=decision.tactical_evaluation.tactical_plan_sha256,
        scenario_scores=scores,
        costs=costs,
        continuation_value=continuation_value,
    )


def _free_hit_definition(bundle: CompiledChipBundle) -> CompiledChipDefinition:
    try:
        compiled = bundle.definition_for("FREE_HIT")
    except KeyError as exc:
        raise ChipError(
            "CHIP_FH_DEFINITION_MISSING",
            "compiled chip bundle does not contain Free Hit",
        ) from exc
    if compiled.activation_status is not ActivationStatus.READY:
        raise ChipError(
            "CHIP_EFFECT_BLOCKED",
            "Free Hit definition is blocked",
            blockers=compiled.blockers,
        )
    effects = frozenset(
        (effect.surface, effect.operation) for effect in compiled.definition.effects
    )
    missing = tuple(sorted(_REQUIRED_FREE_HIT_EFFECTS - effects))
    if missing:
        raise ChipError(
            "CHIP_FH_EFFECT_MISSING",
            "compiled Free Hit lacks a required restoration/transfer capability",
            missing=missing,
        )
    return compiled


def _validate_candidate_set(
    candidates: Sequence[ChipPolicyCandidate],
    *,
    role: Literal["NORMAL_TRANSFER", "FREE_HIT_TEMPORARY"],
    state: ManagerState,
) -> tuple[ChipPolicyCandidate, ...]:
    if not candidates:
        raise ChipError("CHIP_FH_CANDIDATES_EMPTY", f"{role} candidate set is empty")
    values = tuple(candidates)
    if len({item.candidate_hash for item in values}) != len(values):
        raise ChipError("CHIP_FH_CANDIDATES_DUPLICATE", "policy candidates must be unique")
    if any(item.policy_role != role for item in values):
        raise ChipError("CHIP_FH_CANDIDATE_ROLE", "policy candidate has the wrong role")
    if any(item.state_before_sha256 != state.state_sha256 for item in values):
        raise ChipError(
            "CHIP_FH_STATE_LINEAGE",
            "every policy candidate must start from the permanent manager state",
        )
    identities = tuple(
        (item.scenario_id, item.outcome_draw_id) for item in values[0].scenario_scores
    )
    weights = tuple(item.weight for item in values[0].scenario_scores)
    for candidate in values[1:]:
        if (
            tuple((item.scenario_id, item.outcome_draw_id) for item in candidate.scenario_scores)
            != identities
            or tuple(item.weight for item in candidate.scenario_scores) != weights
        ):
            raise ChipError(
                "CHIP_FH_SCENARIO_MISMATCH",
                "all normal and Free Hit policies must use one common scenario set",
            )
    return values


def _best(candidates: Sequence[ChipPolicyCandidate]) -> ChipPolicyCandidate:
    return min(candidates, key=lambda item: (-item.policy_value, item.candidate_hash))


def _restore_permanent_state(
    state: ManagerState,
    *,
    temporary_policy: ChipPolicyCandidate,
    node: ScenarioTreeNode,
    candidate_pool: tuple[PlayerCatalogEntry, ...],
    rules: TransferRules,
) -> ManagerState:
    arc = resolve_free_transfer_arc(
        rules,
        event=temporary_policy.transition_event,
        ft_before=state.free_transfers,
        transfer_count=temporary_policy.transfer_count,
    )
    if float(arc.hit_points) != temporary_policy.transfer_hit_points:
        raise ChipError(
            "CHIP_FH_TRANSFER_TRANSITION_MISMATCH",
            "Free Hit candidate transfer hits differ from configured Stage-11 transition",
        )
    if arc.ft_after != temporary_policy.free_transfers_after:
        raise ChipError(
            "CHIP_FH_TRANSFER_TRANSITION_MISMATCH",
            "Free Hit candidate free-transfer result differs from configured transition",
        )
    digest = semantic_sha256(
        {
            "parent_state_sha256": state.state_sha256,
            "temporary_policy_hash": temporary_policy.candidate_hash,
            "node_id": node.node_id,
            "restored_bank_tenths": state.bank_tenths,
            "restored_free_transfers": arc.ft_after,
            "restored_ownership_spells": [
                item.model_dump(mode="json") for item in state.ownership_spells
            ],
        }
    )
    restored = seal_manager_state(
        ManagerState(
            state_id=f"state-{digest[:32]}",
            parent_state_id=state.state_id,
            current_gameweek=state.current_gameweek + 1,
            observed_node_id=node.node_id,
            bank_tenths=state.bank_tenths,
            free_transfers=arc.ft_after,
            ownership_spells=state.ownership_spells,
            ruleset_id=state.ruleset_id,
            ruleset_version=state.ruleset_version,
            ruleset_hash=state.ruleset_hash,
            transition_id=f"free-hit-restore:{temporary_policy.candidate_hash[:20]}",
            state_sha256="0" * 64,
        )
    )
    validate_manager_state(restored, candidate_pool=candidate_pool, rules=rules)
    return restored


def evaluate_free_hit(
    *,
    normal_candidates: Sequence[ChipPolicyCandidate],
    free_hit_candidates: Sequence[ChipPolicyCandidate],
    permanent_state: ManagerState,
    node: ScenarioTreeNode,
    candidate_pool: tuple[PlayerCatalogEntry, ...],
    transfer_rules: TransferRules,
    chip_bundle: CompiledChipBundle,
    inventory: ChipInventory,
    token_id: str,
) -> FreeHitEvaluation:
    """Compare the best legal temporary Free Hit with the best legal normal policy."""

    try:
        validate_manager_state(
            permanent_state,
            candidate_pool=candidate_pool,
            rules=transfer_rules,
        )
    except ValueError as exc:
        raise ChipError("CHIP_FH_MANAGER_STATE_INVALID", str(exc)) from exc
    if permanent_state.observed_node_id != node.node_id:
        raise ChipError("CHIP_FH_NODE_MISMATCH", "manager state is not observed at the node")
    if permanent_state.current_gameweek != node.gameweek:
        raise ChipError("CHIP_FH_NODE_MISMATCH", "manager state and node Gameweeks differ")
    if (
        permanent_state.ruleset_id,
        permanent_state.ruleset_version,
        permanent_state.ruleset_hash,
    ) != (
        chip_bundle.ruleset_id,
        chip_bundle.ruleset_version,
        chip_bundle.ruleset_hash,
    ):
        raise ChipError("CHIP_RULESET_LINEAGE_MISMATCH", "Free Hit inputs have different rules")
    if (
        transfer_rules.ruleset_id,
        transfer_rules.ruleset_version,
        transfer_rules.ruleset_hash,
    ) != (
        chip_bundle.ruleset_id,
        chip_bundle.ruleset_version,
        chip_bundle.ruleset_hash,
    ):
        raise ChipError("CHIP_RULESET_LINEAGE_MISMATCH", "Free Hit transfer rules differ")

    definition = _free_hit_definition(chip_bundle)
    token = inventory.token(token_id)
    if token.chip_key != "FREE_HIT":
        raise ChipError(
            "CHIP_FH_TOKEN_MISMATCH",
            "Free Hit evaluation requires a Free Hit token",
            chip_key=token.chip_key,
        )
    if token.status not in {TokenStatus.AVAILABLE, TokenStatus.PENDING_CANCELLABLE}:
        raise ChipError(
            "CHIP_FH_TOKEN_UNAVAILABLE",
            "Free Hit token is not available for projected activation",
            status=token.status,
        )

    normal = _validate_candidate_set(
        normal_candidates, role="NORMAL_TRANSFER", state=permanent_state
    )
    free_hit = _validate_candidate_set(
        free_hit_candidates, role="FREE_HIT_TEMPORARY", state=permanent_state
    )
    reference_ids = tuple(
        (item.scenario_id, item.outcome_draw_id) for item in normal[0].scenario_scores
    )
    reference_weights = tuple(item.weight for item in normal[0].scenario_scores)
    for candidate in free_hit:
        if (
            tuple((item.scenario_id, item.outcome_draw_id) for item in candidate.scenario_scores)
            != reference_ids
            or tuple(item.weight for item in candidate.scenario_scores) != reference_weights
        ):
            raise ChipError(
                "CHIP_FH_SCENARIO_MISMATCH",
                "normal and Free Hit policies must use one common scenario set",
            )
        if candidate.transition_event not in transfer_rules.event_rules:
            raise ChipError(
                "CHIP_FH_TRANSFER_EVENT_MISSING",
                "Free Hit candidate uses an unconfigured transfer event",
            )
        arc = resolve_free_transfer_arc(
            transfer_rules,
            event=candidate.transition_event,
            ft_before=permanent_state.free_transfers,
            transfer_count=candidate.transfer_count,
        )
        if not arc.unlimited_transfers_without_hits or arc.hit_points != 0:
            raise ChipError(
                "CHIP_FH_TRANSFER_EVENT_INVALID",
                "configured Free Hit event must waive transfer hits",
            )
        if candidate.transfer_hit_points != 0.0:
            raise ChipError(
                "CHIP_FH_TEMPORARY_HIT",
                "Free Hit temporary policy cannot contain transfer-hit points",
            )

    selected_normal = _best(normal)
    selected_free_hit = _best(free_hit)
    restored = _restore_permanent_state(
        permanent_state,
        temporary_policy=selected_free_hit,
        node=node,
        candidate_pool=candidate_pool,
        rules=transfer_rules,
    )
    comparisons = tuple(
        FreeHitScenarioValue(
            scenario_id=normal_score.scenario_id,
            outcome_draw_id=normal_score.outcome_draw_id,
            weight=normal_score.weight,
            normal_points=normal_score.manager_points,
            free_hit_points=free_hit_score.manager_points,
            gross_current_increment=(free_hit_score.manager_points - normal_score.manager_points),
        )
        for normal_score, free_hit_score in zip(
            selected_normal.scenario_scores,
            selected_free_hit.scenario_scores,
            strict=True,
        )
    )
    gross = selected_free_hit.expected_current_points - selected_normal.expected_current_points
    hits_avoided = selected_normal.transfer_hit_points - selected_free_hit.transfer_hit_points
    permanent_damage_avoided = (
        selected_normal.costs.permanent_squad_damage_points
        - selected_free_hit.costs.permanent_squad_damage_points
    )
    route_preserved = (
        selected_normal.costs.route_flexibility_cost_points
        - selected_free_hit.costs.route_flexibility_cost_points
    )
    purchase_preserved = (
        selected_normal.costs.purchase_price_spell_damage_points
        - selected_free_hit.costs.purchase_price_spell_damage_points
    )
    net_pre = gross + hits_avoided + permanent_damage_avoided + route_preserved + purchase_preserved
    continuation = selected_free_hit.continuation_value - selected_normal.continuation_value
    net_policy = net_pre + continuation
    if not all(
        isfinite(value)
        for value in (
            gross,
            hits_avoided,
            permanent_damage_avoided,
            route_preserved,
            purchase_preserved,
            net_pre,
            continuation,
            net_policy,
        )
    ):
        raise ChipError("CHIP_FH_VALUE_INVALID", "Free Hit value decomposition is not finite")

    original_active_ids = tuple(sorted(item.spell_id for item in permanent_state.active_spells))
    restored_active_ids = tuple(sorted(item.spell_id for item in restored.active_spells))
    if (
        restored.squad_ids != permanent_state.squad_ids
        or restored_active_ids != original_active_ids
    ):
        raise ChipError("CHIP_FH_RESTORATION_FAILED", "permanent squad/cohorts were not restored")
    if restored.bank_tenths != permanent_state.bank_tenths:
        raise ChipError("CHIP_FH_RESTORATION_FAILED", "permanent bank was not restored")
    before_purchase = {
        item.spell_id: item.purchase_price_tenths for item in permanent_state.ownership_spells
    }
    after_purchase = {
        item.spell_id: item.purchase_price_tenths for item in restored.ownership_spells
    }
    if before_purchase != after_purchase:
        raise ChipError("CHIP_FH_RESTORATION_FAILED", "purchase prices were not restored")
    temporary_only = set(selected_free_hit.active_purchase_spell_ids) - set(original_active_ids)
    if temporary_only & {item.spell_id for item in restored.ownership_spells}:
        raise ChipError(
            "CHIP_FH_TEMPORARY_COHORT_CONTAMINATION",
            "temporary Free Hit purchases contaminated permanent ownership history",
        )

    projected_inventory = activate_token(inventory, chip_bundle, token_id=token_id)
    scenario_set_hash = semantic_sha256(
        [item.model_dump(mode="json") for item in selected_normal.scenario_scores]
    )
    payload = {
        "chip_key": "FREE_HIT",
        "normal_policy": selected_normal.model_dump(mode="json"),
        "free_hit_policy": selected_free_hit.model_dump(mode="json"),
        "scenario_values": [item.model_dump(mode="json") for item in comparisons],
        "gross_current_gain": gross,
        "transfer_hits_avoided": hits_avoided,
        "permanent_squad_damage_avoided": permanent_damage_avoided,
        "route_flexibility_preserved": route_preserved,
        "purchase_price_spell_value_preserved": purchase_preserved,
        "net_pre_continuation_value": net_pre,
        "continuation_value_difference": continuation,
        "net_policy_value": net_policy,
        "exercise_advantage": net_policy,
        "use_now": net_policy > 0.0,
        "permanent_squad_restored": True,
        "permanent_bank_restored": True,
        "purchase_prices_restored": True,
        "temporary_purchases_excluded_from_permanent_cohorts": True,
        "restored_state": restored.model_dump(mode="json"),
        "token_id": token_id,
        "inventory_before_hash": inventory.inventory_hash,
        "inventory_after_activation_hash": projected_inventory.inventory_hash,
        "scenario_set_hash": scenario_set_hash,
        "ruleset_id": chip_bundle.ruleset_id,
        "ruleset_version": chip_bundle.ruleset_version,
        "ruleset_hash": chip_bundle.ruleset_hash,
        "chip_definition_hash": definition.definition_hash,
    }
    return FreeHitEvaluation(
        chip_key="FREE_HIT",
        normal_policy=selected_normal,
        free_hit_policy=selected_free_hit,
        scenario_values=comparisons,
        gross_current_gain=gross,
        transfer_hits_avoided=hits_avoided,
        permanent_squad_damage_avoided=permanent_damage_avoided,
        route_flexibility_preserved=route_preserved,
        purchase_price_spell_value_preserved=purchase_preserved,
        net_pre_continuation_value=net_pre,
        continuation_value_difference=continuation,
        net_policy_value=net_policy,
        exercise_advantage=net_policy,
        use_now=net_policy > 0.0,
        permanent_squad_restored=True,
        permanent_bank_restored=True,
        purchase_prices_restored=True,
        temporary_purchases_excluded_from_permanent_cohorts=True,
        restored_state=restored,
        token_id=token_id,
        inventory_before_hash=inventory.inventory_hash,
        inventory_after_activation_hash=projected_inventory.inventory_hash,
        scenario_set_hash=scenario_set_hash,
        ruleset_id=chip_bundle.ruleset_id,
        ruleset_version=chip_bundle.ruleset_version,
        ruleset_hash=chip_bundle.ruleset_hash,
        chip_definition_hash=definition.definition_hash,
        evaluation_hash=semantic_sha256(payload),
    )
