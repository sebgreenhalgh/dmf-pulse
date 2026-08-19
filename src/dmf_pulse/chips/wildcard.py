"""Wildcard permanent-reset comparison with explicit delay and information routes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from math import isfinite
from typing import cast

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
    WildcardEvaluation,
    WildcardFutureOutcome,
    WildcardRouteCandidate,
    WildcardRouteCostProfile,
    WildcardRouteRole,
    WildcardScenarioValue,
)
from dmf_pulse.optimisation.manager_state import ManagerState, validate_manager_state
from dmf_pulse.optimisation.multi_gameweek_models import (
    PlayerCatalogEntry,
    ScenarioTreeNode,
    TransferRules,
)
from dmf_pulse.optimisation.multi_gameweek_solver import (
    apply_transfer_action,
    make_transfer_action,
    resolve_free_transfer_arc,
)

_REQUIRED_WILDCARD_EFFECTS = frozenset(
    {
        ("TRANSFERS", "UNLIMITED_FREE"),
        ("TRANSFERS", "REMOVE_CURRENT_GAMEWEEK_HITS"),
        ("TRANSFERS", "PRESERVE_SAVED_FREE_TRANSFERS"),
        ("SQUAD", "PERMANENT"),
    }
)
_RETAINED_ROLES = frozenset({"WILDCARD_DELAYED", "FREE_HIT_BRIDGE", "HOLD"})
_ALLOWED_ROUTE_ROLES = frozenset({"WILDCARD_IMMEDIATE", *_RETAINED_ROLES})


def make_wildcard_route_candidate(
    *,
    route_id: str,
    current_policy: ChipPolicyCandidate,
    permanent_state_after_current_action: ManagerState,
    information_outcomes: Iterable[WildcardFutureOutcome],
    activation_gameweek: int | None = None,
    information_event_id: str | None = None,
    token_consumed_now: bool = False,
    expires_without_use: bool = False,
    information_value: float = 0.0,
    route_costs: WildcardRouteCostProfile | None = None,
) -> WildcardRouteCandidate:
    """Seal one current action plus information-contingent Wildcard continuation route."""

    if current_policy.policy_role not in _ALLOWED_ROUTE_ROLES:
        raise ChipError(
            "CHIP_WC_ROUTE_ROLE_INVALID",
            "Wildcard route requires an immediate, delayed, bridge or hold policy role",
            policy_role=current_policy.policy_role,
        )
    route_role = cast(WildcardRouteRole, current_policy.policy_role)
    outcomes = tuple(sorted(information_outcomes, key=lambda item: item.outcome_id))
    costs = route_costs or WildcardRouteCostProfile()
    current_net = current_policy.net_pre_continuation_value
    expected_future = sum(item.probability * item.total_value for item in outcomes)
    route_value = current_net + expected_future + information_value - costs.total_cost
    payload: dict[str, object] = {
        "route_id": route_id,
        "route_role": route_role,
        "current_policy": current_policy.model_dump(mode="json"),
        "permanent_state_after_current_action": permanent_state_after_current_action.model_dump(
            mode="json"
        ),
        "activation_gameweek": activation_gameweek,
        "information_event_id": information_event_id,
        "information_outcomes": [item.model_dump(mode="json") for item in outcomes],
        "token_consumed_now": token_consumed_now,
        "expires_without_use": expires_without_use,
        "information_value": information_value,
        "route_costs": costs.model_dump(mode="json"),
        "current_net_value": current_net,
        "expected_future_value": expected_future,
        "route_value": route_value,
    }
    return WildcardRouteCandidate(
        route_id=route_id,
        route_role=route_role,
        current_policy=current_policy,
        permanent_state_after_current_action=permanent_state_after_current_action,
        activation_gameweek=activation_gameweek,
        information_event_id=information_event_id,
        information_outcomes=outcomes,
        token_consumed_now=token_consumed_now,
        expires_without_use=expires_without_use,
        information_value=information_value,
        route_costs=costs,
        current_net_value=current_net,
        expected_future_value=expected_future,
        route_value=route_value,
        route_hash=semantic_sha256(payload),
    )


def _wildcard_definition(bundle: CompiledChipBundle) -> CompiledChipDefinition:
    try:
        compiled = bundle.definition_for("WILDCARD")
    except KeyError as exc:
        raise ChipError(
            "CHIP_WC_DEFINITION_MISSING",
            "compiled chip bundle does not contain Wildcard",
        ) from exc
    if compiled.activation_status is not ActivationStatus.READY:
        raise ChipError(
            "CHIP_EFFECT_BLOCKED",
            "Wildcard definition is blocked",
            blockers=compiled.blockers,
        )
    effects = frozenset(
        (effect.surface, effect.operation) for effect in compiled.definition.effects
    )
    missing = tuple(sorted(_REQUIRED_WILDCARD_EFFECTS - effects))
    if missing:
        raise ChipError(
            "CHIP_WC_EFFECT_MISSING",
            "compiled Wildcard lacks a required permanent-reset/transfer capability",
            missing=missing,
        )
    return compiled


def apply_wildcard_reset(
    permanent_state: ManagerState,
    *,
    desired_squad_ids: Iterable[str],
    node: ScenarioTreeNode,
    candidate_pool: tuple[PlayerCatalogEntry, ...],
    transfer_rules: TransferRules,
) -> ManagerState:
    """Apply the exact permanent Stage-11 squad, bank, FT and cohort transition."""

    try:
        validate_manager_state(
            permanent_state,
            candidate_pool=candidate_pool,
            rules=transfer_rules,
        )
    except ValueError as exc:
        raise ChipError("CHIP_WC_MANAGER_STATE_INVALID", str(exc)) from exc
    if (
        permanent_state.current_gameweek != node.gameweek
        or permanent_state.observed_node_id != node.node_id
    ):
        raise ChipError("CHIP_WC_NODE_MISMATCH", "manager state is not observed at the node")

    desired = tuple(sorted(str(item) for item in desired_squad_ids))
    if len(desired) != transfer_rules.squad_size or len(desired) != len(set(desired)):
        raise ChipError(
            "CHIP_WC_SQUAD_INVALID",
            "Wildcard desired squad must be one complete unique permanent squad",
        )
    catalog = {item.player_id: item for item in candidate_pool}
    if not set(desired) <= set(catalog):
        raise ChipError(
            "CHIP_WC_SQUAD_INVALID",
            "Wildcard desired squad contains an unknown player",
        )
    if Counter(catalog[item].position for item in desired) != Counter(
        transfer_rules.position_squad_quota
    ):
        raise ChipError(
            "CHIP_WC_SQUAD_INVALID",
            "Wildcard desired squad violates position quotas",
        )
    clubs = Counter(catalog[item].club_id for item in desired)
    if clubs and max(clubs.values()) > transfer_rules.max_players_per_club:
        raise ChipError(
            "CHIP_WC_SQUAD_INVALID",
            "Wildcard desired squad violates club limits",
        )

    current = set(permanent_state.squad_ids)
    target = set(desired)
    transfers_out = tuple(sorted(current - target))
    transfers_in = tuple(sorted(target - current))
    wildcard_node = node.model_copy(update={"transition_event": "WILDCARD"})
    action = make_transfer_action(
        transfers_out=transfers_out,
        transfers_in=transfers_in,
        event="WILDCARD",
    )
    try:
        applied = apply_transfer_action(
            permanent_state,
            action,
            node=wildcard_node,
            candidate_pool=candidate_pool,
            rules=transfer_rules,
        )
    except ValueError as exc:
        raise ChipError("CHIP_WC_TRANSITION_INVALID", str(exc)) from exc
    arc = applied.free_transfer_arc
    if not arc.unlimited_transfers_without_hits or arc.hit_points != 0:
        raise ChipError(
            "CHIP_WC_TRANSFER_EVENT_INVALID",
            "configured Wildcard event must provide unlimited hit-free transfers",
        )
    if arc.ft_after != permanent_state.free_transfers:
        raise ChipError(
            "CHIP_WC_FT_NOT_PRESERVED",
            "configured Wildcard event must preserve saved free transfers",
        )
    return applied.state


def _scenario_signature(
    route: WildcardRouteCandidate,
) -> tuple[tuple[str, str, float], ...]:
    return tuple(
        (item.scenario_id, item.outcome_draw_id, item.weight)
        for item in route.current_policy.scenario_scores
    )


def _validate_routes(
    routes: Sequence[WildcardRouteCandidate],
    *,
    permanent_state: ManagerState,
    node: ScenarioTreeNode,
    candidate_pool: tuple[PlayerCatalogEntry, ...],
    transfer_rules: TransferRules,
    token_expiry: int,
) -> tuple[WildcardRouteCandidate, ...]:
    if not routes:
        raise ChipError("CHIP_WC_ROUTES_EMPTY", "Wildcard route set is empty")
    values = tuple(routes)
    if len({item.route_hash for item in values}) != len(values):
        raise ChipError("CHIP_WC_ROUTES_DUPLICATE", "Wildcard routes must be unique")
    if not any(item.route_role == "WILDCARD_IMMEDIATE" for item in values):
        raise ChipError(
            "CHIP_WC_IMMEDIATE_MISSING",
            "Wildcard evaluation requires an immediate route",
        )
    if not any(item.route_role in _RETAINED_ROLES for item in values):
        raise ChipError(
            "CHIP_WC_HOLD_MISSING",
            "Wildcard evaluation requires a route retaining it now",
        )

    reference = _scenario_signature(values[0])
    for route in values:
        policy = route.current_policy
        state = route.permanent_state_after_current_action
        if policy.state_before_sha256 != permanent_state.state_sha256:
            raise ChipError(
                "CHIP_WC_STATE_LINEAGE",
                "every Wildcard route must start from the permanent manager state",
            )
        if _scenario_signature(route) != reference:
            raise ChipError(
                "CHIP_WC_SCENARIO_MISMATCH",
                "all Wildcard routes must use one common current scenario set",
            )
        try:
            validate_manager_state(state, candidate_pool=candidate_pool, rules=transfer_rules)
        except ValueError as exc:
            raise ChipError("CHIP_WC_RESULTING_STATE_INVALID", str(exc)) from exc
        if state.current_gameweek != node.gameweek + 1 or state.observed_node_id != node.node_id:
            raise ChipError(
                "CHIP_WC_RESULTING_STATE_INVALID",
                "Wildcard route state must be the post-decision permanent state",
            )
        if policy.transition_event not in transfer_rules.event_rules:
            raise ChipError(
                "CHIP_WC_TRANSFER_EVENT_MISSING",
                "Wildcard route uses an unconfigured transfer event",
            )
        arc = resolve_free_transfer_arc(
            transfer_rules,
            event=policy.transition_event,
            ft_before=permanent_state.free_transfers,
            transfer_count=policy.transfer_count,
        )
        if float(arc.hit_points) != policy.transfer_hit_points:
            raise ChipError(
                "CHIP_WC_TRANSFER_TRANSITION_MISMATCH",
                "Wildcard route transfer hits differ from configured Stage-11 transition",
            )
        if arc.ft_after != policy.free_transfers_after:
            raise ChipError(
                "CHIP_WC_TRANSFER_TRANSITION_MISMATCH",
                "Wildcard route free-transfer result differs from configured transition",
            )

        if route.route_role == "WILDCARD_IMMEDIATE":
            if policy.transition_event != "WILDCARD":
                raise ChipError(
                    "CHIP_WC_ROUTE_EVENT",
                    "immediate Wildcard route must use WILDCARD",
                )
            if route.activation_gameweek != node.gameweek:
                raise ChipError(
                    "CHIP_WC_ACTIVATION_TIME",
                    "immediate Wildcard route must activate at the current node",
                )
            expected = apply_wildcard_reset(
                permanent_state,
                desired_squad_ids=policy.squad_ids,
                node=node,
                candidate_pool=candidate_pool,
                transfer_rules=transfer_rules,
            )
            if expected != state:
                raise ChipError(
                    "CHIP_WC_PERMANENT_RESET_MISMATCH",
                    "immediate Wildcard state differs from the exact permanent reset",
                )
        elif route.route_role in {"WILDCARD_DELAYED", "HOLD"}:
            if policy.transition_event != "NORMAL":
                raise ChipError(
                    "CHIP_WC_ROUTE_EVENT",
                    "hold and delayed Wildcard routes must use a normal current transfer event",
                )
        elif policy.transition_event != "FREE_HIT":
            raise ChipError(
                "CHIP_WC_ROUTE_EVENT",
                "Free Hit bridge route must use the configured FREE_HIT event",
            )

        if route.activation_gameweek is None:
            continue
        if route.activation_gameweek < node.gameweek:
            raise ChipError(
                "CHIP_WC_ACTIVATION_TIME",
                "Wildcard activation cannot be in the past",
            )
        if route.activation_gameweek > token_expiry:
            raise ChipError(
                "CHIP_WC_ACTIVATION_AFTER_EXPIRY",
                "Wildcard delayed activation exceeds token expiry",
            )
        if route.route_role == "WILDCARD_IMMEDIATE":
            continue
        if route.activation_gameweek <= node.gameweek:
            raise ChipError(
                "CHIP_WC_ACTIVATION_TIME",
                "delayed/bridge Wildcard route must activate after the current node",
            )
    return values


def _best(routes: Sequence[WildcardRouteCandidate]) -> WildcardRouteCandidate:
    return min(routes, key=lambda item: (-item.route_value, item.route_hash))


def _expected(route: WildcardRouteCandidate, field: str) -> float:
    return float(
        sum(item.probability * float(getattr(item, field)) for item in route.information_outcomes)
    )


def evaluate_wildcard(
    *,
    routes: Sequence[WildcardRouteCandidate],
    permanent_state: ManagerState,
    node: ScenarioTreeNode,
    candidate_pool: tuple[PlayerCatalogEntry, ...],
    transfer_rules: TransferRules,
    chip_bundle: CompiledChipBundle,
    inventory: ChipInventory,
    token_id: str,
) -> WildcardEvaluation:
    """Compare the best legal immediate reset with the best route retaining Wildcard."""

    try:
        validate_manager_state(
            permanent_state,
            candidate_pool=candidate_pool,
            rules=transfer_rules,
        )
    except ValueError as exc:
        raise ChipError("CHIP_WC_MANAGER_STATE_INVALID", str(exc)) from exc
    if (
        permanent_state.current_gameweek != node.gameweek
        or permanent_state.observed_node_id != node.node_id
    ):
        raise ChipError("CHIP_WC_NODE_MISMATCH", "manager state is not observed at the node")

    lineage = (
        permanent_state.ruleset_id,
        permanent_state.ruleset_version,
        permanent_state.ruleset_hash,
    )
    if lineage != (
        chip_bundle.ruleset_id,
        chip_bundle.ruleset_version,
        chip_bundle.ruleset_hash,
    ) or lineage != (
        transfer_rules.ruleset_id,
        transfer_rules.ruleset_version,
        transfer_rules.ruleset_hash,
    ):
        raise ChipError(
            "CHIP_RULESET_LINEAGE_MISMATCH",
            "Wildcard inputs have different rules",
        )
    if (
        inventory.ruleset_id,
        inventory.ruleset_version,
        inventory.ruleset_hash,
        inventory.bundle_hash,
    ) != (
        chip_bundle.ruleset_id,
        chip_bundle.ruleset_version,
        chip_bundle.ruleset_hash,
        chip_bundle.bundle_hash,
    ):
        raise ChipError(
            "CHIP_INVENTORY_LINEAGE_MISMATCH",
            "Wildcard inventory differs from rules",
        )

    definition = _wildcard_definition(chip_bundle)
    token = inventory.token(token_id)
    if token.chip_key != "WILDCARD":
        raise ChipError(
            "CHIP_WC_TOKEN_MISMATCH",
            "Wildcard evaluation requires a Wildcard token",
            chip_key=token.chip_key,
        )
    if token.status not in {TokenStatus.AVAILABLE, TokenStatus.PENDING_CANCELLABLE}:
        raise ChipError(
            "CHIP_WC_TOKEN_UNAVAILABLE",
            "Wildcard token is not available for projected activation",
            status=token.status,
        )
    if inventory.current_gameweek != node.gameweek:
        raise ChipError(
            "CHIP_WC_INVENTORY_TIME_MISMATCH",
            "Wildcard inventory and decision node Gameweeks differ",
        )

    checked = _validate_routes(
        routes,
        permanent_state=permanent_state,
        node=node,
        candidate_pool=candidate_pool,
        transfer_rules=transfer_rules,
        token_expiry=token.expires_after_gameweek,
    )
    immediate = _best(tuple(item for item in checked if item.route_role == "WILDCARD_IMMEDIATE"))
    retained = _best(tuple(item for item in checked if item.route_role in _RETAINED_ROLES))
    exercise_advantage = immediate.route_value - retained.route_value
    use_now = exercise_advantage > 0.0
    selected = immediate if use_now else retained

    comparisons = tuple(
        WildcardScenarioValue(
            scenario_id=hold_score.scenario_id,
            outcome_draw_id=hold_score.outcome_draw_id,
            weight=hold_score.weight,
            hold_points=hold_score.manager_points,
            immediate_wildcard_points=immediate_score.manager_points,
            gross_current_increment=(immediate_score.manager_points - hold_score.manager_points),
        )
        for immediate_score, hold_score in zip(
            immediate.current_policy.scenario_scores,
            retained.current_policy.scenario_scores,
            strict=True,
        )
    )
    gross_current = (
        immediate.current_policy.expected_current_points
        - retained.current_policy.expected_current_points
    )
    current_hits_saved = (
        retained.current_policy.transfer_hit_points - immediate.current_policy.transfer_hit_points
    )
    current_costs_avoided = (
        retained.current_policy.costs.total_cost_points
        - immediate.current_policy.costs.total_cost_points
    )
    components = {
        "future_squad_value_difference": _expected(immediate, "future_squad_points")
        - _expected(retained, "future_squad_points"),
        "future_transfer_hit_value_difference": _expected(immediate, "transfer_hits_saved")
        - _expected(retained, "transfer_hits_saved"),
        "price_route_value_difference": _expected(immediate, "price_route_value")
        - _expected(retained, "price_route_value"),
        "flexibility_value_difference": _expected(immediate, "flexibility_value")
        - _expected(retained, "flexibility_value"),
        "forced_transfer_value_difference": _expected(immediate, "forced_transfer_value")
        - _expected(retained, "forced_transfer_value"),
        "bench_boost_synergy_difference": _expected(immediate, "bench_boost_synergy")
        - _expected(retained, "bench_boost_synergy"),
        "free_hit_synergy_difference": _expected(immediate, "free_hit_synergy")
        - _expected(retained, "free_hit_synergy"),
        "triple_captain_synergy_difference": _expected(immediate, "triple_captain_synergy")
        - _expected(retained, "triple_captain_synergy"),
        "terminal_value_difference": _expected(immediate, "terminal_value")
        - _expected(retained, "terminal_value"),
    }
    information_difference = immediate.information_value - retained.information_value
    route_costs_avoided = retained.route_costs.total_cost - immediate.route_costs.total_cost
    decomposition = (
        gross_current
        + current_hits_saved
        + current_costs_avoided
        + sum(components.values())
        + information_difference
        + route_costs_avoided
    )
    values = (
        gross_current,
        current_hits_saved,
        current_costs_avoided,
        *components.values(),
        information_difference,
        route_costs_avoided,
        decomposition,
        exercise_advantage,
    )
    if not all(isfinite(value) for value in values):
        raise ChipError(
            "CHIP_WC_VALUE_INVALID",
            "Wildcard value decomposition is not finite",
        )
    if abs(decomposition - exercise_advantage) > 1e-9:
        raise ChipError(
            "CHIP_WC_VALUE_MISMATCH",
            "Wildcard decomposition differs from immediate-versus-hold policy value",
        )

    previous_active_ids = {item.spell_id for item in permanent_state.active_spells}
    incoming_ids = tuple(
        sorted(
            item.spell_id
            for item in immediate.permanent_state_after_current_action.active_spells
            if item.spell_id not in previous_active_ids
        )
    )
    incoming_players = set(immediate.current_policy.squad_ids) - set(permanent_state.squad_ids)
    incoming_spells = tuple(
        item
        for item in immediate.permanent_state_after_current_action.active_spells
        if item.spell_id in set(incoming_ids)
    )
    if {item.player_id for item in incoming_spells} != incoming_players:
        raise ChipError(
            "CHIP_WC_COHORT_REPLACEMENT_FAILED",
            "Wildcard incoming players do not have exact new purchase cohorts",
        )
    if any(
        item.started_gameweek != node.gameweek
        or item.started_at_node_id != node.node_id
        or item.purchase_price_tenths != node.prices[item.player_id].current_price_tenths
        for item in incoming_spells
    ):
        raise ChipError(
            "CHIP_WC_COHORT_REPLACEMENT_FAILED",
            "Wildcard incoming purchase cohorts have invalid start or price metadata",
        )

    projected_inventory = activate_token(inventory, chip_bundle, token_id=token_id)
    scenario_set_hash = semantic_sha256(
        [item.model_dump(mode="json") for item in immediate.current_policy.scenario_scores]
    )
    ordered_routes = tuple(sorted(checked, key=lambda item: item.route_hash))
    payload: dict[str, object] = {
        "chip_key": "WILDCARD",
        "routes": [item.model_dump(mode="json") for item in ordered_routes],
        "best_immediate_route": immediate.model_dump(mode="json"),
        "best_hold_route": retained.model_dump(mode="json"),
        "selected_route": selected.model_dump(mode="json"),
        "scenario_values": [item.model_dump(mode="json") for item in comparisons],
        "gross_current_gain": gross_current,
        "current_transfer_hits_saved": current_hits_saved,
        "current_policy_costs_avoided": current_costs_avoided,
        **components,
        "information_value_difference": information_difference,
        "route_costs_avoided": route_costs_avoided,
        "net_policy_value": decomposition,
        "exercise_advantage": exercise_advantage,
        "use_now": use_now,
        "immediate_wildcard_state": immediate.permanent_state_after_current_action.model_dump(
            mode="json"
        ),
        "incoming_purchase_spell_ids": incoming_ids,
        "token_id": token_id,
        "inventory_before_hash": inventory.inventory_hash,
        "inventory_after_activation_hash": projected_inventory.inventory_hash,
        "scenario_set_hash": scenario_set_hash,
        "ruleset_id": chip_bundle.ruleset_id,
        "ruleset_version": chip_bundle.ruleset_version,
        "ruleset_hash": chip_bundle.ruleset_hash,
        "chip_definition_hash": definition.definition_hash,
    }
    return WildcardEvaluation(
        chip_key="WILDCARD",
        routes=ordered_routes,
        best_immediate_route=immediate,
        best_hold_route=retained,
        selected_route=selected,
        scenario_values=comparisons,
        gross_current_gain=gross_current,
        current_transfer_hits_saved=current_hits_saved,
        current_policy_costs_avoided=current_costs_avoided,
        future_squad_value_difference=components["future_squad_value_difference"],
        future_transfer_hit_value_difference=components["future_transfer_hit_value_difference"],
        price_route_value_difference=components["price_route_value_difference"],
        flexibility_value_difference=components["flexibility_value_difference"],
        forced_transfer_value_difference=components["forced_transfer_value_difference"],
        bench_boost_synergy_difference=components["bench_boost_synergy_difference"],
        free_hit_synergy_difference=components["free_hit_synergy_difference"],
        triple_captain_synergy_difference=components["triple_captain_synergy_difference"],
        terminal_value_difference=components["terminal_value_difference"],
        information_value_difference=information_difference,
        route_costs_avoided=route_costs_avoided,
        net_policy_value=decomposition,
        exercise_advantage=exercise_advantage,
        use_now=use_now,
        immediate_wildcard_state=immediate.permanent_state_after_current_action,
        incoming_purchase_spell_ids=incoming_ids,
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
