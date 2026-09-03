"""Exact bounded sequential transfer state machine and multistage policy enumerator."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations, product

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import PlayerPosition
from dmf_pulse.optimisation.manager_state import (
    ManagerState,
    OwnershipSpell,
    seal_manager_state,
    selling_price_tenths,
    state_fingerprint,
    validate_manager_state,
)
from dmf_pulse.optimisation.models import (
    OneGameweekPlan,
    SearchScope,
)
from dmf_pulse.optimisation.models import (
    OptimalityGuarantee as Stage10OptimalityGuarantee,
)
from dmf_pulse.optimisation.multi_gameweek_errors import (
    InfeasiblePolicyError,
    InputInvalidError,
    ResourceLimitReached,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    BackendStatus,
    FreeTransferArc,
    LeafUtility,
    MoveAttribution,
    MoveMarginalValue,
    MultiGameweekOptimisationRequest,
    MultiGameweekPlan,
    NodeDecision,
    ObjectiveMode,
    OptimalityGuarantee,
    PlanKind,
    PlayerCatalogEntry,
    ScenarioTree,
    ScenarioTreeNode,
    SearchPolicy,
    SolverDiagnostics,
    TacticalValueRecord,
    TerminalValueBreakdown,
    TransferAction,
    TransferMove,
    TransferPrice,
    TransferRules,
    UtilityBreakdown,
    seal_plan,
    verify_plan_hash,
    verify_request_hash,
    verify_scenario_tree_hash,
    verify_search_policy_hash,
    verify_terminal_policy_hash,
)
from dmf_pulse.optimisation.stage10_adapter import StaticTacticalEvaluator, TacticalEvaluator


@dataclass(frozen=True)
class AppliedTransfer:
    state: ManagerState
    selling_prices: tuple[TransferPrice, ...]
    buying_prices: tuple[TransferPrice, ...]
    free_transfer_arc: FreeTransferArc


def node_map(tree: ScenarioTree) -> dict[str, ScenarioTreeNode]:
    return {item.node_id: item for item in tree.nodes}


def children_by_parent(tree: ScenarioTree) -> dict[str, tuple[ScenarioTreeNode, ...]]:
    grouped: dict[str, list[ScenarioTreeNode]] = defaultdict(list)
    for node in tree.nodes:
        if node.parent_id is not None:
            grouped[node.parent_id].append(node)
    return {
        parent: tuple(sorted(children, key=lambda item: item.node_id))
        for parent, children in grouped.items()
    }


def root_node(tree: ScenarioTree) -> ScenarioTreeNode:
    roots = tuple(item for item in tree.nodes if item.parent_id is None)
    if len(roots) != 1:
        raise InputInvalidError("scenario tree must have exactly one root")
    return roots[0]


def leaf_nodes(tree: ScenarioTree) -> tuple[ScenarioTreeNode, ...]:
    parents = set(children_by_parent(tree))
    return tuple(item for item in tree.nodes if item.node_id not in parents)


def path_to_node(tree: ScenarioTree, node_id: str) -> tuple[ScenarioTreeNode, ...]:
    nodes = node_map(tree)
    cursor: ScenarioTreeNode | None = nodes[node_id]
    path: list[ScenarioTreeNode] = []
    while cursor is not None:
        path.append(cursor)
        cursor = nodes.get(cursor.parent_id) if cursor.parent_id is not None else None
    return tuple(reversed(path))


def unconditional_probabilities(tree: ScenarioTree) -> dict[str, Decimal]:
    root = root_node(tree)
    children = children_by_parent(tree)
    probabilities = {root.node_id: Decimal(1)}
    stack = [root]
    while stack:
        parent = stack.pop()
        for child in reversed(children.get(parent.node_id, ())):
            probabilities[child.node_id] = (
                probabilities[parent.node_id] * child.conditional_probability
            )
            stack.append(child)
    return probabilities


def _observable_snapshot(node: ScenarioTreeNode) -> dict[str, object]:
    return {
        "gameweek": node.gameweek,
        "revealed_information": node.revealed_information,
        "availability_state": node.availability_state,
        "fixture_state": node.fixture_state,
        "points_state_id": node.points_state_id,
        "prices": {
            player_id: value.model_dump(mode="json")
            for player_id, value in sorted(node.prices.items())
        },
        "transition_event": node.transition_event,
        "allowed_transfer_in_ids": node.allowed_transfer_in_ids,
    }


def information_set_key(node: ScenarioTreeNode, *, parent_key: str | None) -> str:
    digest = semantic_sha256(
        {
            "parent_information_set_key": parent_key,
            "observable_snapshot": _observable_snapshot(node),
        }
    )
    return f"info-{digest[:40]}"


def resolve_free_transfer_arc(
    rules: TransferRules,
    *,
    event: str,
    ft_before: int,
    transfer_count: int,
) -> FreeTransferArc:
    event_rule = rules.event_rules.get(event)
    if event_rule is None:
        raise ValueError(f"unsupported configured transfer event: {event}")
    effective = event_rule.reset_before if event_rule.reset_before is not None else ft_before
    if event_rule.unlimited_transfers_without_hits:
        free_used = 0
        paid = 0
        hits = 0
    else:
        free_used = min(effective, transfer_count)
        paid = transfer_count - free_used
        hits = paid * rules.hit_cost_per_paid_transfer
    cap = event_rule.cap_after or rules.maximum_free_transfers
    if event_rule.reset_after is not None:
        after = event_rule.reset_after
    else:
        retained = effective - free_used if event_rule.carry_unused else 0
        after = min(cap, retained + event_rule.earn_for_next_deadline)
    if after > cap:
        raise ValueError("configured FT reset exceeds its cap")
    return FreeTransferArc(
        event=event,
        unlimited_transfers_without_hits=event_rule.unlimited_transfers_without_hits,
        effective_ft_before=effective,
        transfer_count=transfer_count,
        free_used=free_used,
        paid_transfers=paid,
        hit_points=hits,
        earned_for_next_deadline=event_rule.earn_for_next_deadline,
        ft_after=after,
        maximum_free_transfers=cap,
    )


def _spell_id(
    state: ManagerState,
    *,
    player_id: str,
    node_id: str,
    gameweek: int,
    purchase_price_tenths: int,
) -> str:
    digest = semantic_sha256(
        {
            "previous_state_sha256": state.state_sha256,
            "player_id": player_id,
            "node_id": node_id,
            "gameweek": gameweek,
            "purchase_price_tenths": purchase_price_tenths,
            "prior_spell_ids": [
                item.spell_id for item in state.ownership_spells if item.player_id == player_id
            ],
        }
    )
    return f"spell-{digest[:32]}"


def observe_node(state: ManagerState, *, node: ScenarioTreeNode) -> ManagerState:
    """Observe new prices/information without taking a transfer decision."""

    if node.gameweek != state.current_gameweek:
        raise ValueError("observed node Gameweek must equal the manager-state Gameweek")
    spells: list[OwnershipSpell] = []
    for spell in state.ownership_spells:
        if not spell.active:
            spells.append(spell)
            continue
        price = node.prices.get(spell.player_id)
        if price is None:
            raise ValueError("observed node lacks an owned player's price")
        spells.append(spell.model_copy(update={"current_price_tenths": price.current_price_tenths}))
    digest = semantic_sha256(
        {
            "parent_state_sha256": state.state_sha256,
            "node_id": node.node_id,
            "observable_snapshot": _observable_snapshot(node),
        }
    )
    value = ManagerState(
        state_id=f"state-{digest[:32]}",
        parent_state_id=state.state_id,
        current_gameweek=node.gameweek,
        observed_node_id=node.node_id,
        bank_tenths=state.bank_tenths,
        free_transfers=state.free_transfers,
        ownership_spells=tuple(
            sorted(spells, key=lambda item: (item.player_id, item.started_gameweek, item.spell_id))
        ),
        ruleset_id=state.ruleset_id,
        ruleset_version=state.ruleset_version,
        ruleset_hash=state.ruleset_hash,
        transition_id=f"observe:{node.node_id}",
        state_sha256="0" * 64,
    )
    return seal_manager_state(value)


def make_transfer_action(
    *, transfers_out: tuple[str, ...], transfers_in: tuple[str, ...], event: str
) -> TransferAction:
    outs = tuple(sorted(transfers_out))
    ins = tuple(sorted(transfers_in))
    digest = semantic_sha256({"event": event, "transfers_out": outs, "transfers_in": ins})
    return TransferAction(
        action_id=f"transfer-{digest[:32]}",
        transfers_out=outs,
        transfers_in=ins,
        transition_event=event,
    )


def apply_transfer_action(
    state: ManagerState,
    action: TransferAction,
    *,
    node: ScenarioTreeNode,
    candidate_pool: tuple[PlayerCatalogEntry, ...],
    rules: TransferRules,
) -> AppliedTransfer:
    """Apply exact squad, bank, ownership-spell and FT transitions."""

    validate_manager_state(state, candidate_pool=candidate_pool, rules=rules)
    if state.current_gameweek != node.gameweek or state.observed_node_id != node.node_id:
        raise ValueError("manager state is not observed at this decision node")
    if action.transition_event != node.transition_event:
        raise ValueError("action transition event differs from the node")
    if action.transfer_count > rules.max_transfers_per_deadline:
        raise ValueError("transfer count exceeds the configured deadline maximum")
    catalog = {item.player_id: item for item in candidate_pool}
    active = state.active_by_player
    for spell in state.active_spells:
        if spell.current_price_tenths != node.prices[spell.player_id].current_price_tenths:
            raise ValueError("owned-player current prices are stale")
    out_ids = set(action.transfers_out)
    in_ids = set(action.transfers_in)
    if not out_ids <= set(active):
        raise ValueError("cannot sell an unowned player")
    if in_ids & set(active):
        raise ValueError("cannot buy a currently owned player")
    if not in_ids <= set(catalog):
        raise ValueError("cannot buy outside the declared candidate pool")
    if node.allowed_transfer_in_ids and not in_ids <= set(node.allowed_transfer_in_ids):
        raise ValueError("transfer is outside the node's declared action scope")
    if Counter(active[item].position for item in action.transfers_out) != Counter(
        catalog[item].position for item in action.transfers_in
    ):
        raise ValueError("transfers must preserve exact position quotas")
    for player_id in action.transfers_in:
        price = node.prices[player_id]
        if not price.purchasable:
            raise ValueError(f"player {player_id} is not purchasable at node {node.node_id}")
    selling_prices = tuple(
        TransferPrice(
            player_id=player_id,
            price_tenths=selling_price_tenths(
                purchase_price_tenths=active[player_id].purchase_price_tenths,
                current_price_tenths=node.prices[player_id].current_price_tenths,
                rule=rules.selling_price_rule,
            ),
        )
        for player_id in action.transfers_out
    )
    buying_prices = tuple(
        TransferPrice(
            player_id=player_id,
            price_tenths=node.prices[player_id].current_price_tenths,
        )
        for player_id in action.transfers_in
    )
    bank_after = (
        state.bank_tenths
        + sum(item.price_tenths for item in selling_prices)
        - sum(item.price_tenths for item in buying_prices)
    )
    if bank_after < 0:
        raise ValueError("transfer action is unaffordable")
    arc = resolve_free_transfer_arc(
        rules,
        event=node.transition_event,
        ft_before=state.free_transfers,
        transfer_count=action.transfer_count,
    )
    spells: list[OwnershipSpell] = []
    selling = {item.player_id: item.price_tenths for item in selling_prices}
    for spell in state.ownership_spells:
        if not spell.active:
            spells.append(spell)
        elif spell.player_id in out_ids:
            spells.append(
                spell.model_copy(
                    update={
                        "current_price_tenths": node.prices[spell.player_id].current_price_tenths,
                        "ended_gameweek": node.gameweek,
                        "ended_at_node_id": node.node_id,
                        "realised_selling_price_tenths": selling[spell.player_id],
                    }
                )
            )
        else:
            spells.append(spell)
    for player_id in action.transfers_in:
        entry = catalog[player_id]
        purchase_price = node.prices[player_id].current_price_tenths
        spells.append(
            OwnershipSpell(
                spell_id=_spell_id(
                    state,
                    player_id=player_id,
                    node_id=node.node_id,
                    gameweek=node.gameweek,
                    purchase_price_tenths=purchase_price,
                ),
                player_id=player_id,
                club_id=entry.club_id,
                position=entry.position,
                purchase_price_tenths=purchase_price,
                current_price_tenths=purchase_price,
                started_gameweek=node.gameweek,
                started_at_node_id=node.node_id,
            )
        )
    spells.sort(key=lambda item: (item.player_id, item.started_gameweek, item.spell_id))
    digest = semantic_sha256(
        {
            "parent_state_sha256": state.state_sha256,
            "node_id": node.node_id,
            "action_id": action.action_id,
            "bank_after": bank_after,
            "ft_after": arc.ft_after,
            "ownership_spells": [item.model_dump(mode="json") for item in spells],
        }
    )
    next_state = ManagerState(
        state_id=f"state-{digest[:32]}",
        parent_state_id=state.state_id,
        current_gameweek=node.gameweek + 1,
        observed_node_id=node.node_id,
        bank_tenths=bank_after,
        free_transfers=arc.ft_after,
        ownership_spells=tuple(spells),
        ruleset_id=state.ruleset_id,
        ruleset_version=state.ruleset_version,
        ruleset_hash=state.ruleset_hash,
        transition_id=action.action_id,
        state_sha256="0" * 64,
    )
    next_state = seal_manager_state(next_state)
    validate_manager_state(next_state, candidate_pool=candidate_pool, rules=rules)
    return AppliedTransfer(
        state=next_state,
        selling_prices=selling_prices,
        buying_prices=buying_prices,
        free_transfer_arc=arc,
    )


def enumerate_legal_actions(
    state: ManagerState,
    *,
    node: ScenarioTreeNode,
    candidate_pool: tuple[PlayerCatalogEntry, ...],
    rules: TransferRules,
    policy: SearchPolicy,
    root_no_transfer_only: bool = False,
) -> tuple[TransferAction, ...]:
    """Enumerate all legal actions; caps fail rather than silently prune."""

    catalog = {item.player_id: item for item in candidate_pool}
    owned = state.squad_ids
    allowed = set(node.allowed_transfer_in_ids) if node.allowed_transfer_in_ids else set(catalog)
    available = tuple(
        item.player_id
        for item in candidate_pool
        if item.player_id not in set(owned)
        and item.player_id in allowed
        and node.prices[item.player_id].purchasable
    )
    available_by_position = {
        position: tuple(
            player_id for player_id in available if catalog[player_id].position is position
        )
        for position in PlayerPosition
    }
    maximum = min(
        policy.max_transfers_per_node,
        rules.max_transfers_per_deadline,
        len(owned),
        len(available),
    )
    actions: list[TransferAction] = []
    combinations_considered = 0
    for count in range(maximum + 1):
        if root_no_transfer_only and count != 0:
            continue
        for outs_raw in combinations(owned, count):
            outs = tuple(sorted(outs_raw))
            out_positions = Counter(catalog[item].position for item in outs)
            position_choices = tuple(
                combinations(available_by_position[position], out_positions[position])
                for position in PlayerPosition
                if out_positions[position]
            )
            for position_parts in product(*position_choices):
                combinations_considered += 1
                if combinations_considered > policy.max_actions_per_state:
                    raise ResourceLimitReached(
                        "candidate action combinations exceed max_actions_per_state; "
                        "no incomplete enumeration was labelled optimal"
                    )
                ins = tuple(sorted(player_id for part in position_parts for player_id in part))
                action = make_transfer_action(
                    transfers_out=outs,
                    transfers_in=ins,
                    event=node.transition_event,
                )
                try:
                    apply_transfer_action(
                        state,
                        action,
                        node=node,
                        candidate_pool=candidate_pool,
                        rules=rules,
                    )
                except ValueError:
                    continue
                actions.append(action)
    actions.sort(key=lambda item: item.signature)
    if not actions:
        raise InfeasiblePolicyError("state has no legal configured transfer action")
    return tuple(actions)


def _validate_tactical_record(
    request: MultiGameweekOptimisationRequest,
    record: TacticalValueRecord,
    *,
    require_exact: bool,
) -> None:
    catalog = {item.player_id: item for item in request.candidate_pool}
    if len(record.squad_ids) != request.rules.squad_size:
        raise InputInvalidError("tactical record has the wrong squad size")
    if not set(record.squad_ids) <= set(catalog):
        raise InputInvalidError("tactical record contains an unknown player")
    if Counter(catalog[item].position for item in record.squad_ids) != Counter(
        request.rules.position_squad_quota
    ):
        raise InputInvalidError("tactical record violates exact position quotas")
    clubs = Counter(catalog[item].club_id for item in record.squad_ids)
    if clubs and max(clubs.values()) > request.rules.max_players_per_club:
        raise InputInvalidError("tactical record violates the club maximum")
    try:
        stage10_plan = OneGameweekPlan.model_validate(record.tactical_plan)
    except ValueError as exc:
        raise InputInvalidError("tactical record does not contain a valid Stage-10 plan") from exc
    payload = stage10_plan.model_dump(mode="json")
    payload["plan_sha256"] = None
    if (
        stage10_plan.plan_sha256 != record.tactical_plan_sha256
        or semantic_sha256(payload) != record.tactical_plan_sha256
        or stage10_plan.squad != record.squad_ids
        or stage10_plan.expected_manager_points != record.expected_points
        or Decimal(stage10_plan.point_distribution.p10) != record.p10_points
        or Decimal(stage10_plan.point_distribution.p90) != record.p90_points
    ):
        raise InputInvalidError("tactical record differs from its canonical Stage-10 plan")
    if not stage10_plan.legality.legal or stage10_plan.legality.issues:
        raise InputInvalidError("tactical record contains an illegal Stage-10 plan")
    if require_exact and not record.exact_stage10_evaluation:
        raise InputInvalidError("current-Gameweek tactical records must be exact Stage-10 plans")
    if record.exact_stage10_evaluation and (
        stage10_plan.solver_status.termination != "OPTIMAL"
        or stage10_plan.solver_status.search_scope is not SearchScope.FIXED_SQUAD
        or stage10_plan.solver_status.guarantee is not Stage10OptimalityGuarantee.EXACT_FIXED_SQUAD
        or stage10_plan.solver_status.objective_value != record.expected_points
        or stage10_plan.solver_status.best_bound != record.expected_points
        or stage10_plan.solver_status.absolute_gap != Decimal(0)
        or stage10_plan.solver_status.relative_gap != Decimal(0)
    ):
        raise InputInvalidError(
            "exact tactical record lacks an exact optimal fixed-squad Stage-10 proof"
        )


def validate_request(request: MultiGameweekOptimisationRequest) -> None:
    """Validate hashes, manager state, tree probabilities and revelation chronology."""

    try:
        verify_request_hash(request)
        verify_search_policy_hash(request.search_policy)
        verify_terminal_policy_hash(request.terminal_policy)
        verify_scenario_tree_hash(request.scenario_tree)
        validate_manager_state(
            request.initial_state,
            candidate_pool=request.candidate_pool,
            rules=request.rules,
        )
    except ValueError as exc:
        raise InputInvalidError(str(exc)) from exc
    tree = request.scenario_tree
    nodes = node_map(tree)
    root = root_node(tree)
    if root.conditional_probability != Decimal(1):
        raise InputInvalidError("root conditional probability must equal one")
    if root.node_id != request.initial_state.observed_node_id:
        raise InputInvalidError("initial manager state must be observed at the root node")
    if root.gameweek != request.initial_state.current_gameweek:
        raise InputInvalidError("root Gameweek must equal the manager-state Gameweek")
    for node in tree.nodes:
        seen: set[str] = set()
        cursor: ScenarioTreeNode | None = node
        while cursor is not None:
            if cursor.node_id in seen:
                raise InputInvalidError("scenario tree contains a parent cycle")
            seen.add(cursor.node_id)
            cursor = nodes.get(cursor.parent_id) if cursor.parent_id is not None else None
    candidate_ids = {item.player_id for item in request.candidate_pool}
    for node in tree.nodes:
        if set(node.prices) != candidate_ids:
            raise InputInvalidError(
                f"node {node.node_id} must carry one price state for every candidate"
            )
        if not set(node.allowed_transfer_in_ids) <= candidate_ids:
            raise InputInvalidError("node action scope contains an unknown player")
        if not set(node.availability_state) <= candidate_ids:
            raise InputInvalidError("node availability state contains an unknown player")
        if node.parent_id is not None:
            parent = nodes.get(node.parent_id)
            if parent is None:
                raise InputInvalidError("scenario node references a missing parent")
            if node.gameweek != parent.gameweek + 1:
                raise InputInvalidError("each tree edge must advance exactly one Gameweek")
            if not set(parent.revealed_information) <= set(node.revealed_information):
                raise InputInvalidError("revealed information cannot disappear")
        for record in node.tactical_values:
            _validate_tactical_record(
                request,
                record,
                require_exact=node.parent_id is None,
            )
    for parent_id, children in children_by_parent(tree).items():
        total = sum((item.conditional_probability for item in children), Decimal(0))
        if total != Decimal(1):
            raise InputInvalidError(
                f"conditional probabilities below {parent_id} must sum exactly to one"
            )
    reachable: set[str] = set()
    stack = [root]
    child_index = children_by_parent(tree)
    while stack:
        current = stack.pop()
        if current.node_id in reachable:
            continue
        reachable.add(current.node_id)
        stack.extend(reversed(child_index.get(current.node_id, ())))
    if reachable != set(nodes):
        raise InputInvalidError("scenario tree contains an unreachable node")
    expected_keys: dict[str, str] = {}
    for node in tree.nodes:
        parent_key = expected_keys.get(node.parent_id) if node.parent_id is not None else None
        expected = information_set_key(node, parent_key=parent_key)
        if node.information_set_key != expected:
            raise InputInvalidError(
                f"node {node.node_id} information key differs from observable history"
            )
        expected_keys[node.node_id] = expected
    if len(set(expected_keys.values())) != len(expected_keys):
        raise InputInvalidError("indistinguishable histories must share one decision node")
    scope_independent_keys: dict[str, str] = {}
    action_scope_by_history: dict[str, tuple[str, ...]] = {}
    for node in tree.nodes:
        snapshot = _observable_snapshot(node)
        snapshot.pop("allowed_transfer_in_ids")
        parent_key = scope_independent_keys[node.parent_id] if node.parent_id is not None else None
        history_key = semantic_sha256(
            {
                "parent_information_set_key": parent_key,
                "observable_snapshot": snapshot,
            }
        )
        prior_scope = action_scope_by_history.setdefault(history_key, node.allowed_transfer_in_ids)
        if prior_scope != node.allowed_transfer_in_ids:
            raise InputInvalidError(
                "observationally identical histories cannot have different action scopes"
            )
        scope_independent_keys[node.node_id] = history_key
    for spell in request.initial_state.active_spells:
        if spell.current_price_tenths != root.prices[spell.player_id].current_price_tenths:
            raise InputInvalidError("initial owned-player price differs from the root price state")


def terminal_value(
    state: ManagerState,
    *,
    request: MultiGameweekOptimisationRequest,
) -> TerminalValueBreakdown:
    policy = request.terminal_policy
    if not policy.enabled:
        return TerminalValueBreakdown(
            policy_id=policy.policy_id,
            bank_value=Decimal(0),
            free_transfer_value=Decimal(0),
            liquidation_value=Decimal(0),
            total=Decimal(0),
        )
    liquidation_tenths = sum(
        selling_price_tenths(
            purchase_price_tenths=item.purchase_price_tenths,
            current_price_tenths=item.current_price_tenths,
            rule=request.rules.selling_price_rule,
        )
        for item in state.active_spells
    )
    bank = policy.bank_points_per_tenth * Decimal(state.bank_tenths)
    free_transfers = policy.free_transfer_points * Decimal(state.free_transfers)
    liquidation = policy.liquidation_points_per_tenth * Decimal(liquidation_tenths)
    return TerminalValueBreakdown(
        policy_id=policy.policy_id,
        bank_value=bank,
        free_transfer_value=free_transfers,
        liquidation_value=liquidation,
        total=bank + free_transfers + liquidation,
    )


@dataclass(frozen=True)
class CandidateLeaf:
    leaf_node_id: str
    expected_utility: Decimal
    conservative_utility: Decimal
    upside_utility: Decimal
    terminal_value: TerminalValueBreakdown


@dataclass(frozen=True)
class PolicyCandidate:
    decisions: tuple[NodeDecision, ...]
    leaf_values: tuple[CandidateLeaf, ...]
    expected_score: Decimal
    conservative_score: Decimal
    upside_score: Decimal
    terminal_bank_value: Decimal
    terminal_free_transfer_value: Decimal
    terminal_liquidation_value: Decimal
    tie_key: str

    @property
    def terminal_total(self) -> Decimal:
        return (
            self.terminal_bank_value
            + self.terminal_free_transfer_value
            + self.terminal_liquidation_value
        )

    @property
    def root_decision(self) -> NodeDecision:
        return min(self.decisions, key=lambda item: (item.gameweek, item.node_id))

    @property
    def root_action(self) -> TransferAction:
        return self.root_decision.action


@dataclass
class SearchCounters:
    state_expansions: int = 0
    action_candidates: int = 0
    policy_candidates: int = 0
    pareto_candidates: int = 0


@dataclass(frozen=True)
class FrontierResult:
    candidates: tuple[PolicyCandidate, ...]
    diagnostics: SolverDiagnostics
    complete: bool


def _configuration_hash(request: MultiGameweekOptimisationRequest) -> str:
    return semantic_sha256(
        {
            "rules": request.rules.model_dump(mode="json"),
            "scenario_tree": request.scenario_tree.model_dump(mode="json"),
            "search_policy": request.search_policy.model_dump(mode="json"),
            "terminal_policy": request.terminal_policy.model_dump(mode="json"),
        }
    )


def _dominates(left: PolicyCandidate, right: PolicyCandidate) -> bool:
    weak = (
        left.expected_score >= right.expected_score
        and left.conservative_score >= right.conservative_score
        and left.upside_score >= right.upside_score
    )
    strict = (
        left.expected_score > right.expected_score
        or left.conservative_score > right.conservative_score
        or left.upside_score > right.upside_score
    )
    return weak and strict


def _pareto_frontier(candidates: list[PolicyCandidate]) -> tuple[PolicyCandidate, ...]:
    unique: dict[tuple[Decimal, Decimal, Decimal], PolicyCandidate] = {}
    for item in sorted(candidates, key=lambda value: value.tie_key):
        key = (item.expected_score, item.conservative_score, item.upside_score)
        unique.setdefault(key, item)
    values = tuple(unique.values())
    return tuple(
        sorted(
            (
                item
                for item in values
                if not any(other is not item and _dominates(other, item) for other in values)
            ),
            key=lambda value: value.tie_key,
        )
    )


def select_candidate(
    candidates: tuple[PolicyCandidate, ...],
    *,
    mode: ObjectiveMode,
    expected_floor: Decimal | None = None,
) -> PolicyCandidate:
    eligible = tuple(
        item
        for item in candidates
        if expected_floor is None or item.expected_score >= expected_floor
    )
    if not eligible:
        raise InfeasiblePolicyError("no policy satisfies the expected-utility floor")
    metric: Callable[[PolicyCandidate], Decimal] = {
        ObjectiveMode.EXPECTED: lambda item: item.expected_score,
        ObjectiveMode.CONSERVATIVE: lambda item: item.conservative_score,
        ObjectiveMode.HIGH_UPSIDE: lambda item: item.upside_score,
    }[mode]
    best = max(metric(item) for item in eligible)
    return min((item for item in eligible if metric(item) == best), key=lambda item: item.tie_key)


def select_transfer_count_frontier(
    candidates: tuple[PolicyCandidate, ...],
) -> tuple[PolicyCandidate, ...]:
    """Select each exact-count current-GW optimum from an evaluated Stage-11 family."""

    if not candidates:
        raise InfeasiblePolicyError("no evaluated root actions are available for the frontier")
    grouped: dict[int, list[PolicyCandidate]] = defaultdict(list)
    for item in candidates:
        grouped[item.root_action.transfer_count].append(item)
    selected: list[PolicyCandidate] = []
    for transfer_count in sorted(grouped):
        values = grouped[transfer_count]
        best = max(
            item.root_decision.tactical_evaluation.expected_points
            - Decimal(item.root_decision.hit_points)
            for item in values
        )
        selected.append(
            min(
                (
                    item
                    for item in values
                    if item.root_decision.tactical_evaluation.expected_points
                    - Decimal(item.root_decision.hit_points)
                    == best
                ),
                key=lambda item: item.tie_key,
            )
        )
    return tuple(selected)


def select_horizon_transfer_count_frontier(
    candidates: tuple[PolicyCandidate, ...],
) -> tuple[PolicyCandidate, ...]:
    """Select the best complete expected-utility policy at each root transfer count."""

    if not candidates:
        raise InfeasiblePolicyError("no evaluated root policies are available for the frontier")
    grouped: dict[int, list[PolicyCandidate]] = defaultdict(list)
    for item in candidates:
        grouped[item.root_action.transfer_count].append(item)
    return tuple(
        select_candidate(tuple(grouped[transfer_count]), mode=ObjectiveMode.EXPECTED)
        for transfer_count in sorted(grouped)
    )


def _root_sufficient_candidates(
    candidates: list[PolicyCandidate],
) -> tuple[PolicyCandidate, ...]:
    """Retain each root action's exact best policy for every supported objective."""

    grouped: dict[str, list[PolicyCandidate]] = defaultdict(list)
    for item in candidates:
        grouped[item.root_action.signature].append(item)
    retained: dict[str, PolicyCandidate] = {}
    for values in grouped.values():
        for mode in ObjectiveMode:
            selected = select_candidate(tuple(values), mode=mode)
            retained[selected.tie_key] = selected
    for item in _pareto_frontier(candidates):
        retained[item.tie_key] = item
    return tuple(sorted(retained.values(), key=lambda item: item.tie_key))


@dataclass
class BoundedExactEnumerator:
    request: MultiGameweekOptimisationRequest
    evaluator: TacticalEvaluator
    root_no_transfer_only: bool = False
    counters: SearchCounters = field(default_factory=SearchCounters)
    memo: dict[tuple[str, str], tuple[PolicyCandidate, ...]] = field(default_factory=dict)

    def enumerate(self) -> FrontierResult:
        root = root_node(self.request.scenario_tree)
        actions = enumerate_legal_actions(
            self.request.initial_state,
            node=root,
            candidate_pool=self.request.candidate_pool,
            rules=self.request.rules,
            policy=self.request.search_policy,
            root_no_transfer_only=self.root_no_transfer_only,
        )
        candidates: list[PolicyCandidate] = []
        try:
            for action in actions:
                candidates.extend(
                    self._generate_for_action(root.node_id, self.request.initial_state, action)
                )
        except ResourceLimitReached as exc:
            if not candidates:
                raise ResourceLimitReached(exc.message, counters=self.counters) from exc
            retained = _root_sufficient_candidates(candidates)
            return FrontierResult(
                candidates=retained,
                diagnostics=self._diagnostics(
                    retained,
                    status=BackendStatus.TIME_RESOURCE_LIMIT_WITH_INCUMBENT,
                    reason=exc.message,
                    complete=False,
                ),
                complete=False,
            )
        if not candidates:
            raise InfeasiblePolicyError("declared tree/action space contains no feasible policy")
        pareto = _pareto_frontier(candidates)
        self.counters.pareto_candidates += len(pareto)
        retained = _root_sufficient_candidates(candidates)
        if len(retained) > self.request.search_policy.max_returned_root_candidates:
            return FrontierResult(
                candidates=retained,
                diagnostics=self._diagnostics(
                    retained,
                    status=BackendStatus.TIME_RESOURCE_LIMIT_WITH_INCUMBENT,
                    reason=(
                        "lossless root summary exceeds max_returned_root_candidates; "
                        "no unsafe truncation was applied"
                    ),
                    complete=False,
                ),
                complete=False,
            )
        return FrontierResult(
            candidates=retained,
            diagnostics=self._diagnostics(
                retained,
                status=BackendStatus.OPTIMAL,
                reason="complete bounded policy frontier exhausted",
                complete=True,
            ),
            complete=True,
        )

    def _diagnostics(
        self,
        candidates: tuple[PolicyCandidate, ...],
        *,
        status: BackendStatus,
        reason: str,
        complete: bool,
    ) -> SolverDiagnostics:
        best = select_candidate(candidates, mode=ObjectiveMode.EXPECTED)
        return SolverDiagnostics(
            status=status,
            termination_reason=reason,
            optimality_guarantee=(
                OptimalityGuarantee.EXACT_DECLARED_TREE_AND_ACTION_SPACE
                if complete
                else OptimalityGuarantee.NONE
            ),
            objective=best.expected_score,
            incumbent=best.expected_score,
            bound=best.expected_score if complete else None,
            absolute_gap=Decimal(0) if complete else None,
            relative_gap=Decimal(0) if complete else None,
            state_expansions=self.counters.state_expansions,
            action_candidates=self.counters.action_candidates,
            policy_candidates=self.counters.policy_candidates,
            pareto_candidates=self.counters.pareto_candidates,
            memo_entries=len(self.memo),
            deterministic_tie_key=best.tie_key,
            runtime_ms=None,
            configuration_sha256=_configuration_hash(self.request),
        )

    def _enumerate_node(self, node_id: str, state: ManagerState) -> tuple[PolicyCandidate, ...]:
        key = (node_id, state_fingerprint(state))
        cached = self.memo.get(key)
        if cached is not None:
            return cached
        if self.counters.state_expansions >= self.request.search_policy.max_state_expansions:
            raise ResourceLimitReached(
                "state-expansion cap reached before complete exhaustion",
                counters=self.counters,
            )
        self.counters.state_expansions += 1
        node = node_map(self.request.scenario_tree)[node_id]
        actions = enumerate_legal_actions(
            state,
            node=node,
            candidate_pool=self.request.candidate_pool,
            rules=self.request.rules,
            policy=self.request.search_policy,
        )
        generated: list[PolicyCandidate] = []
        for action in actions:
            generated.extend(self._generate_for_action(node_id, state, action))
        if not generated:
            raise InfeasiblePolicyError(f"node {node_id} has no complete contingent policy")
        frontier = _pareto_frontier(generated)
        self.counters.pareto_candidates += len(frontier)
        if len(frontier) > self.request.search_policy.max_policy_candidates:
            raise ResourceLimitReached(
                "exact Pareto frontier exceeds max_policy_candidates; no unsafe pruning applied",
                counters=self.counters,
            )
        self.memo[key] = frontier
        return frontier

    def _generate_for_action(
        self,
        node_id: str,
        state: ManagerState,
        action: TransferAction,
    ) -> Iterator[PolicyCandidate]:
        self.counters.action_candidates += 1
        node = node_map(self.request.scenario_tree)[node_id]
        transition = apply_transfer_action(
            state,
            action,
            node=node,
            candidate_pool=self.request.candidate_pool,
            rules=self.request.rules,
        )
        tactical = self.evaluator.evaluate(node=node, state=transition.state)
        arc = transition.free_transfer_arc
        decision = NodeDecision(
            node_id=node.node_id,
            information_set_key=node.information_set_key,
            gameweek=node.gameweek,
            action=action,
            state_before_sha256=state.state_sha256,
            state_after=transition.state,
            bank_before_tenths=state.bank_tenths,
            bank_after_tenths=transition.state.bank_tenths,
            free_transfers_before=state.free_transfers,
            free_transfers_after=transition.state.free_transfers,
            paid_transfers=arc.paid_transfers,
            hit_points=arc.hit_points,
            selling_prices=transition.selling_prices,
            buying_prices=transition.buying_prices,
            squad_after=transition.state.squad_ids,
            tactical_evaluation=tactical,
        )
        hit = Decimal(arc.hit_points)
        immediate_expected = tactical.expected_points - hit
        immediate_conservative = tactical.p10_points - hit
        immediate_upside = tactical.p90_points - hit
        children = children_by_parent(self.request.scenario_tree).get(node_id, ())
        if not children:
            terminal = terminal_value(transition.state, request=self.request)
            leaf = CandidateLeaf(
                leaf_node_id=node.node_id,
                expected_utility=immediate_expected + terminal.total,
                conservative_utility=immediate_conservative + terminal.total,
                upside_utility=immediate_upside + terminal.total,
                terminal_value=terminal,
            )
            yield self._candidate(
                decisions=(decision,),
                leaf_values=(leaf,),
                expected=leaf.expected_utility,
                conservative=leaf.conservative_utility,
                upside=leaf.upside_utility,
                terminal=terminal,
            )
            return
        child_frontiers = tuple(
            self._enumerate_node(
                child.node_id,
                observe_node(transition.state, node=child),
            )
            for child in children
        )
        for child_choices in product(*child_frontiers):
            expected = immediate_expected
            conservative = immediate_conservative
            upside = immediate_upside
            bank_value = Decimal(0)
            ft_value = Decimal(0)
            liquidation_value = Decimal(0)
            decisions: list[NodeDecision] = [decision]
            leaf_values: list[CandidateLeaf] = []
            for child, candidate in zip(children, child_choices, strict=True):
                probability = child.conditional_probability
                expected += probability * candidate.expected_score
                conservative += probability * candidate.conservative_score
                upside += probability * candidate.upside_score
                bank_value += probability * candidate.terminal_bank_value
                ft_value += probability * candidate.terminal_free_transfer_value
                liquidation_value += probability * candidate.terminal_liquidation_value
                decisions.extend(candidate.decisions)
                leaf_values.extend(
                    CandidateLeaf(
                        leaf_node_id=leaf.leaf_node_id,
                        expected_utility=immediate_expected + leaf.expected_utility,
                        conservative_utility=(immediate_conservative + leaf.conservative_utility),
                        upside_utility=immediate_upside + leaf.upside_utility,
                        terminal_value=leaf.terminal_value,
                    )
                    for leaf in candidate.leaf_values
                )
            terminal = TerminalValueBreakdown(
                policy_id=self.request.terminal_policy.policy_id,
                bank_value=bank_value,
                free_transfer_value=ft_value,
                liquidation_value=liquidation_value,
                total=bank_value + ft_value + liquidation_value,
            )
            yield self._candidate(
                decisions=tuple(decisions),
                leaf_values=tuple(leaf_values),
                expected=expected,
                conservative=conservative,
                upside=upside,
                terminal=terminal,
            )

    def _candidate(
        self,
        *,
        decisions: tuple[NodeDecision, ...],
        leaf_values: tuple[CandidateLeaf, ...],
        expected: Decimal,
        conservative: Decimal,
        upside: Decimal,
        terminal: TerminalValueBreakdown,
    ) -> PolicyCandidate:
        self.counters.policy_candidates += 1
        if self.counters.policy_candidates > self.request.search_policy.max_policy_candidates:
            raise ResourceLimitReached(
                "generated policy count exceeds max_policy_candidates before exact exhaustion",
                counters=self.counters,
            )
        ordered_decisions = tuple(sorted(decisions, key=lambda item: (item.gameweek, item.node_id)))
        ordered_leaves = tuple(sorted(leaf_values, key=lambda item: item.leaf_node_id))
        tie_key = "|".join(
            f"{item.node_id}:{item.action.signature}:"
            f"{item.tactical_evaluation.tactical_plan_sha256[:12]}"
            for item in ordered_decisions
        )
        return PolicyCandidate(
            decisions=ordered_decisions,
            leaf_values=ordered_leaves,
            expected_score=expected,
            conservative_score=conservative,
            upside_score=upside,
            terminal_bank_value=terminal.bank_value,
            terminal_free_transfer_value=terminal.free_transfer_value,
            terminal_liquidation_value=terminal.liquidation_value,
            tie_key=tie_key,
        )


def solve_frontier(
    request: MultiGameweekOptimisationRequest,
    evaluator: TacticalEvaluator,
    *,
    root_no_transfer_only: bool = False,
) -> FrontierResult:
    return BoundedExactEnumerator(
        request=request,
        evaluator=evaluator,
        root_no_transfer_only=root_no_transfer_only,
    ).enumerate()


def build_plan(
    request: MultiGameweekOptimisationRequest,
    candidate: PolicyCandidate,
    *,
    plan_kind: PlanKind,
    objective_mode: ObjectiveMode,
    diagnostics: SolverDiagnostics,
    assumptions: tuple[str, ...],
) -> MultiGameweekPlan:
    probabilities = unconditional_probabilities(request.scenario_tree)
    root = root_node(request.scenario_tree)
    by_node = {item.node_id: item for item in candidate.decisions}
    current = by_node[root.node_id]
    future = tuple(
        sorted(
            (item for item in candidate.decisions if item.node_id != root.node_id),
            key=lambda item: (item.gameweek, item.node_id),
        )
    )
    current_points = current.tactical_evaluation.expected_points
    future_points = sum(
        (probabilities[item.node_id] * item.tactical_evaluation.expected_points for item in future),
        Decimal(0),
    )
    hit_cost = sum(
        (probabilities[item.node_id] * Decimal(item.hit_points) for item in (current, *future)),
        Decimal(0),
    )
    terminal = TerminalValueBreakdown(
        policy_id=request.terminal_policy.policy_id,
        bank_value=candidate.terminal_bank_value,
        free_transfer_value=candidate.terminal_free_transfer_value,
        liquidation_value=candidate.terminal_liquidation_value,
        total=candidate.terminal_total,
    )
    total = current_points + future_points - hit_cost + terminal.total
    if total != candidate.expected_score:
        raise ValueError("selected policy expected utility does not reconcile")
    selection_score = {
        ObjectiveMode.EXPECTED: candidate.expected_score,
        ObjectiveMode.CONSERVATIVE: candidate.conservative_score,
        ObjectiveMode.HIGH_UPSIDE: candidate.upside_score,
    }[objective_mode]
    plan_diagnostics = diagnostics.model_copy(
        update={
            "objective": selection_score,
            "incumbent": selection_score,
            "bound": selection_score if diagnostics.status is BackendStatus.OPTIMAL else None,
            "absolute_gap": Decimal(0) if diagnostics.status is BackendStatus.OPTIMAL else None,
            "relative_gap": Decimal(0) if diagnostics.status is BackendStatus.OPTIMAL else None,
            "deterministic_tie_key": candidate.tie_key,
        }
    )
    decisions = (current, *future)
    plan = MultiGameweekPlan(
        plan_kind=plan_kind,
        objective_mode=objective_mode,
        selection_score=selection_score,
        current_action=current,
        future_policy=future,
        leaf_utilities=tuple(
            LeafUtility(
                leaf_node_id=item.leaf_node_id,
                probability=probabilities[item.leaf_node_id],
                expected_utility=item.expected_utility,
                conservative_utility=item.conservative_utility,
                upside_utility=item.upside_utility,
                terminal_value=item.terminal_value,
            )
            for item in candidate.leaf_values
        ),
        bank_path_tenths=tuple((item.node_id, item.bank_after_tenths) for item in decisions),
        free_transfer_path=tuple((item.node_id, item.free_transfers_after) for item in decisions),
        squad_path=tuple((item.node_id, item.squad_after) for item in decisions),
        utility=UtilityBreakdown(
            expected_horizon_utility=total,
            current_gameweek_contribution=current_points,
            future_contribution=future_points,
            expected_hit_cost=hit_cost,
            terminal_flexibility_contribution=terminal.total,
            objective_total=total,
        ),
        terminal_value=terminal,
        solver_status=plan_diagnostics,
        assumptions=tuple(sorted(assumptions)),
        plan_sha256="0" * 64,
    )
    return seal_plan(plan)


def validate_plan(
    request: MultiGameweekOptimisationRequest,
    plan: MultiGameweekPlan,
    *,
    evaluator: TacticalEvaluator | None = None,
) -> None:
    """Replay a complete contingent policy independently of the enumerator."""

    verify_plan_hash(plan)
    evaluator = evaluator or StaticTacticalEvaluator()
    nodes = node_map(request.scenario_tree)
    decisions = (plan.current_action, *plan.future_policy)
    if set(item.node_id for item in decisions) != set(nodes):
        raise ValueError("policy must contain one decision for every tree node")
    by_node = {item.node_id: item for item in decisions}
    replayed: dict[str, AppliedTransfer] = {}
    for node in request.scenario_tree.nodes:
        before = (
            request.initial_state
            if node.parent_id is None
            else observe_node(replayed[node.parent_id].state, node=node)
        )
        emitted = by_node[node.node_id]
        if emitted.information_set_key != node.information_set_key:
            raise ValueError("decision information-set key differs from the node")
        if emitted.state_before_sha256 != before.state_sha256:
            raise ValueError("decision state-before lineage differs")
        transition = apply_transfer_action(
            before,
            emitted.action,
            node=node,
            candidate_pool=request.candidate_pool,
            rules=request.rules,
        )
        if transition.state != emitted.state_after:
            raise ValueError("decision state transition does not replay")
        if transition.selling_prices != emitted.selling_prices:
            raise ValueError("decision selling prices do not replay")
        if transition.buying_prices != emitted.buying_prices:
            raise ValueError("decision buying prices do not replay")
        if transition.free_transfer_arc.paid_transfers != emitted.paid_transfers:
            raise ValueError("decision paid-transfer count does not replay")
        if transition.free_transfer_arc.hit_points != emitted.hit_points:
            raise ValueError("decision hit cost does not replay")
        tactical = evaluator.evaluate(node=node, state=transition.state)
        if tactical != emitted.tactical_evaluation:
            raise ValueError("decision Stage-10 tactical evaluation does not replay")
        replayed[node.node_id] = transition
    probabilities = unconditional_probabilities(request.scenario_tree)
    root = root_node(request.scenario_tree)
    current_points = by_node[root.node_id].tactical_evaluation.expected_points
    future_points = sum(
        (
            probabilities[node_id] * item.tactical_evaluation.expected_points
            for node_id, item in by_node.items()
            if node_id != root.node_id
        ),
        Decimal(0),
    )
    hits = sum(
        (probabilities[node_id] * Decimal(item.hit_points) for node_id, item in by_node.items()),
        Decimal(0),
    )
    terminal_bank = Decimal(0)
    terminal_ft = Decimal(0)
    terminal_liquidation = Decimal(0)
    leaf_by_id = {item.leaf_node_id: item for item in plan.leaf_utilities}
    for leaf in leaf_nodes(request.scenario_tree):
        value = terminal_value(replayed[leaf.node_id].state, request=request)
        probability = probabilities[leaf.node_id]
        terminal_bank += probability * value.bank_value
        terminal_ft += probability * value.free_transfer_value
        terminal_liquidation += probability * value.liquidation_value
        emitted_leaf = leaf_by_id.get(leaf.node_id)
        if emitted_leaf is None or emitted_leaf.probability != probability:
            raise ValueError("leaf utility path/probability is incomplete")
        path = tuple(
            by_node[item.node_id] for item in path_to_node(request.scenario_tree, leaf.node_id)
        )
        expected_leaf = (
            sum(
                (
                    item.tactical_evaluation.expected_points - Decimal(item.hit_points)
                    for item in path
                ),
                Decimal(0),
            )
            + value.total
        )
        conservative_leaf = (
            sum(
                (item.tactical_evaluation.p10_points - Decimal(item.hit_points) for item in path),
                Decimal(0),
            )
            + value.total
        )
        upside_leaf = (
            sum(
                (item.tactical_evaluation.p90_points - Decimal(item.hit_points) for item in path),
                Decimal(0),
            )
            + value.total
        )
        if (
            emitted_leaf.expected_utility != expected_leaf
            or emitted_leaf.conservative_utility != conservative_leaf
            or emitted_leaf.upside_utility != upside_leaf
            or emitted_leaf.terminal_value != value
        ):
            raise ValueError("leaf utility does not reconcile")
    terminal_total = terminal_bank + terminal_ft + terminal_liquidation
    expected = current_points + future_points - hits + terminal_total
    if plan.utility.objective_total != expected:
        raise ValueError("expected utility does not reconcile")
    if (
        plan.terminal_value.bank_value != terminal_bank
        or plan.terminal_value.free_transfer_value != terminal_ft
        or plan.terminal_value.liquidation_value != terminal_liquidation
        or plan.terminal_value.total != terminal_total
    ):
        raise ValueError("terminal attribution does not reconcile")
    metric_field = {
        ObjectiveMode.EXPECTED: "expected_points",
        ObjectiveMode.CONSERVATIVE: "p10_points",
        ObjectiveMode.HIGH_UPSIDE: "p90_points",
    }[plan.objective_mode]
    selection = (
        sum(
            (
                probabilities[node_id] * getattr(item.tactical_evaluation, metric_field)
                for node_id, item in by_node.items()
            ),
            Decimal(0),
        )
        - hits
        + terminal_total
    )
    if selection != plan.selection_score:
        raise ValueError("selection objective does not reconcile")


def select_materially_distinct_candidate(
    candidates: tuple[PolicyCandidate, ...],
    *,
    recommended: PolicyCandidate,
    mode: ObjectiveMode,
    expected_floor: Decimal,
    material_difference: Decimal,
) -> PolicyCandidate | None:
    eligible = tuple(item for item in candidates if item.expected_score >= expected_floor)
    metric: Callable[[PolicyCandidate], Decimal] = {
        ObjectiveMode.CONSERVATIVE: lambda item: item.conservative_score,
        ObjectiveMode.HIGH_UPSIDE: lambda item: item.upside_score,
        ObjectiveMode.EXPECTED: lambda item: item.expected_score,
    }[mode]
    if not eligible:
        return None
    ranked = sorted(eligible, key=lambda item: item.tie_key)
    ranked.sort(key=metric, reverse=True)
    for item in ranked:
        if item.tie_key == recommended.tie_key:
            continue
        root_differs = item.root_action.signature != recommended.root_action.signature
        leaf_differs = any(
            abs(left.expected_utility - right.expected_utility) >= material_difference
            for left, right in zip(item.leaf_values, recommended.leaf_values, strict=True)
        )
        if root_differs or leaf_differs:
            return item
    return None


def action_moves(
    action: TransferAction,
    *,
    candidate_pool: tuple[PlayerCatalogEntry, ...],
) -> tuple[TransferMove, ...]:
    catalog = {item.player_id: item for item in candidate_pool}
    moves: list[TransferMove] = []
    positions = sorted(
        {catalog[item].position for item in action.transfers_out},
        key=lambda item: item.value,
    )
    for position in positions:
        outs = tuple(
            sorted(item for item in action.transfers_out if catalog[item].position is position)
        )
        ins = tuple(
            sorted(item for item in action.transfers_in if catalog[item].position is position)
        )
        moves.extend(
            TransferMove(player_out=player_out, player_in=player_in)
            for player_out, player_in in zip(outs, ins, strict=True)
        )
    return tuple(moves)


def build_move_attribution(
    request: MultiGameweekOptimisationRequest,
    *,
    recommended: PolicyCandidate,
    no_transfer: PolicyCandidate,
    candidates: tuple[PolicyCandidate, ...],
) -> MoveAttribution:
    action = recommended.root_action
    uplift = recommended.expected_score - no_transfer.expected_score
    marginals: list[MoveMarginalValue] = []
    exact_values: list[Decimal] = []
    for move in action_moves(action, candidate_pool=request.candidate_pool):
        # True drop-one re-optimisation: forbid the selected OUT/IN pair, then select the
        # best legal root action and complete future recourse among the retained exact root
        # summaries.  This permits a different funding route rather than freezing every
        # other current move in place.
        alternatives = tuple(
            item
            for item in candidates
            if not (
                move.player_out in item.root_action.transfers_out
                and move.player_in in item.root_action.transfers_in
            )
        )
        if alternatives:
            best = max(item.expected_score for item in alternatives)
            value = recommended.expected_score - best
            exact_values.append(value)
            marginals.append(
                MoveMarginalValue(
                    move=move,
                    exact_leave_one_out_value=value,
                    leave_one_out_feasible=True,
                    additive=action.transfer_count == 1,
                    explanation=(
                        "Exact drop-one value: the selected OUT/IN pair is forbidden while "
                        "the root action and all future recourse are re-optimised."
                    ),
                )
            )
        else:
            marginals.append(
                MoveMarginalValue(
                    move=move,
                    exact_leave_one_out_value=None,
                    leave_one_out_feasible=False,
                    additive=False,
                    explanation=(
                        "No complete policy remains when this selected OUT/IN pair is "
                        "forbidden in the declared root action space; only bundle value is "
                        "reported."
                    ),
                )
            )
    interaction = (
        uplift - sum(exact_values, Decimal(0))
        if len(exact_values) == action.transfer_count
        else None
    )
    return MoveAttribution(
        root_action_signature=action.signature,
        bundle_uplift_vs_no_transfer=uplift,
        marginal_values=tuple(marginals),
        bundle_interaction_value=interaction,
        interaction_explanation=(
            "Bundle interaction is total uplift less exact leave-one-out values; a non-zero "
            "value identifies funding and/or recourse interaction."
            if interaction is not None
            else "At least one exact leave-one-out policy is infeasible; interaction is unstated."
        ),
    )
