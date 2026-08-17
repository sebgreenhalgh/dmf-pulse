"""Independent expected-utility oracle for bounded OPT-011 synthetic cases.

This test oracle deliberately shares only the public request schema with Stage 11. It
does not call the production action enumerator, state transition, tactical adapter,
dynamic program, or terminal-value implementation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations

from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekOptimisationRequest,
    ScenarioTreeNode,
)


@dataclass(frozen=True)
class _OwnedPlayer:
    player_id: str
    purchase_price_tenths: int
    current_price_tenths: int


@dataclass(frozen=True)
class _OracleState:
    bank_tenths: int
    free_transfers: int
    owned: tuple[_OwnedPlayer, ...]

    @property
    def squad_ids(self) -> tuple[str, ...]:
        return tuple(item.player_id for item in self.owned)


@dataclass(frozen=True)
class _OracleAction:
    transfers_out: tuple[str, ...]
    transfers_in: tuple[str, ...]
    transition_event: str

    @property
    def signature(self) -> str:
        return (
            f"{self.transition_event}|{','.join(self.transfers_out)}->{','.join(self.transfers_in)}"
        )


@dataclass(frozen=True)
class OracleOutcome:
    expected_score: Decimal
    tie_key: str
    action_by_node: tuple[tuple[str, str], ...]

    @property
    def root_action_signature(self) -> str:
        return self.action_by_node[0][1]


def _selling_price(
    purchase_price_tenths: int,
    current_price_tenths: int,
    *,
    numerator: int,
    denominator: int,
) -> int:
    if current_price_tenths <= purchase_price_tenths:
        return current_price_tenths
    profit = current_price_tenths - purchase_price_tenths
    return purchase_price_tenths + profit * numerator // denominator


def _observe(state: _OracleState, node: ScenarioTreeNode) -> _OracleState:
    return _OracleState(
        bank_tenths=state.bank_tenths,
        free_transfers=state.free_transfers,
        owned=tuple(
            _OwnedPlayer(
                player_id=item.player_id,
                purchase_price_tenths=item.purchase_price_tenths,
                current_price_tenths=node.prices[item.player_id].current_price_tenths,
            )
            for item in state.owned
        ),
    )


def _free_transfer_result(
    request: MultiGameweekOptimisationRequest,
    state: _OracleState,
    action: _OracleAction,
) -> tuple[int, int]:
    rule = request.rules.event_rules[action.transition_event]
    effective = rule.reset_before if rule.reset_before is not None else state.free_transfers
    if rule.unlimited_transfers_without_hits:
        free_used = 0
        hit_points = 0
    else:
        free_used = min(effective, len(action.transfers_out))
        hit_points = (
            len(action.transfers_out) - free_used
        ) * request.rules.hit_cost_per_paid_transfer
    if rule.reset_after is not None:
        after = rule.reset_after
    else:
        retained = effective - free_used if rule.carry_unused else 0
        cap = rule.cap_after or request.rules.maximum_free_transfers
        after = min(cap, retained + rule.earn_for_next_deadline)
    return after, hit_points


def _apply(
    request: MultiGameweekOptimisationRequest,
    state: _OracleState,
    node: ScenarioTreeNode,
    action: _OracleAction,
) -> tuple[_OracleState, int]:
    catalog = {item.player_id: item for item in request.candidate_pool}
    by_player = {item.player_id: item for item in state.owned}
    rule = request.rules.selling_price_rule
    sale_proceeds = sum(
        _selling_price(
            by_player[player_id].purchase_price_tenths,
            node.prices[player_id].current_price_tenths,
            numerator=rule.retained_profit_numerator,
            denominator=rule.retained_profit_denominator,
        )
        for player_id in action.transfers_out
    )
    purchase_cost = sum(
        node.prices[player_id].current_price_tenths for player_id in action.transfers_in
    )
    bank_after = state.bank_tenths + sale_proceeds - purchase_cost
    if bank_after < 0:
        raise ValueError("unaffordable oracle action")
    retained = {
        item.player_id: item
        for item in state.owned
        if item.player_id not in set(action.transfers_out)
    }
    retained.update(
        {
            player_id: _OwnedPlayer(
                player_id=player_id,
                purchase_price_tenths=node.prices[player_id].current_price_tenths,
                current_price_tenths=node.prices[player_id].current_price_tenths,
            )
            for player_id in action.transfers_in
        }
    )
    clubs = Counter(catalog[player_id].club_id for player_id in retained)
    if clubs and max(clubs.values()) > request.rules.max_players_per_club:
        raise ValueError("oracle action violates the club quota")
    ft_after, hit_points = _free_transfer_result(request, state, action)
    return (
        _OracleState(
            bank_tenths=bank_after,
            free_transfers=ft_after,
            owned=tuple(retained[player_id] for player_id in sorted(retained)),
        ),
        hit_points,
    )


def _actions(
    request: MultiGameweekOptimisationRequest,
    state: _OracleState,
    node: ScenarioTreeNode,
) -> tuple[_OracleAction, ...]:
    catalog = {item.player_id: item for item in request.candidate_pool}
    owned = state.squad_ids
    allowed = set(node.allowed_transfer_in_ids) or set(catalog)
    available = tuple(
        item.player_id
        for item in request.candidate_pool
        if item.player_id not in set(owned)
        and item.player_id in allowed
        and node.prices[item.player_id].purchasable
    )
    maximum = min(
        request.search_policy.max_transfers_per_node,
        request.rules.max_transfers_per_deadline,
        len(owned),
        len(available),
    )
    actions: list[_OracleAction] = []
    for count in range(maximum + 1):
        for transfers_out in combinations(owned, count):
            outgoing_positions = Counter(catalog[player_id].position for player_id in transfers_out)
            for transfers_in in combinations(available, count):
                if (
                    Counter(catalog[player_id].position for player_id in transfers_in)
                    != outgoing_positions
                ):
                    continue
                action = _OracleAction(
                    transfers_out=transfers_out,
                    transfers_in=transfers_in,
                    transition_event=node.transition_event,
                )
                try:
                    _apply(request, state, node, action)
                except ValueError:
                    continue
                actions.append(action)
    return tuple(sorted(actions, key=lambda item: item.signature))


def _tactical_value(state: _OracleState, node: ScenarioTreeNode) -> tuple[Decimal, str]:
    record = next(
        (item for item in node.tactical_values if item.squad_ids == state.squad_ids),
        None,
    )
    if record is None:
        raise ValueError("oracle state has no frozen tactical record")
    return record.expected_points, record.tactical_plan_sha256


def _terminal_value(request: MultiGameweekOptimisationRequest, state: _OracleState) -> Decimal:
    policy = request.terminal_policy
    if not policy.enabled:
        return Decimal(0)
    rule = request.rules.selling_price_rule
    liquidation_tenths = sum(
        _selling_price(
            item.purchase_price_tenths,
            item.current_price_tenths,
            numerator=rule.retained_profit_numerator,
            denominator=rule.retained_profit_denominator,
        )
        for item in state.owned
    )
    return (
        policy.bank_points_per_tenth * Decimal(state.bank_tenths)
        + policy.free_transfer_points * Decimal(state.free_transfers)
        + policy.liquidation_points_per_tenth * Decimal(liquidation_tenths)
    )


def _best_node(
    request: MultiGameweekOptimisationRequest,
    *,
    node: ScenarioTreeNode,
    state: _OracleState,
    children: dict[str, tuple[ScenarioTreeNode, ...]],
) -> OracleOutcome:
    outcomes: list[OracleOutcome] = []
    for action in _actions(request, state, node):
        next_state, hit_points = _apply(request, state, node, action)
        tactical_points, tactical_hash = _tactical_value(next_state, node)
        immediate = tactical_points - Decimal(hit_points)
        child_outcomes = tuple(
            (
                child,
                _best_node(
                    request,
                    node=child,
                    state=_observe(next_state, child),
                    children=children,
                ),
            )
            for child in children.get(node.node_id, ())
        )
        decision_key = f"{node.node_id}:{action.signature}:{tactical_hash[:12]}"
        if child_outcomes:
            score = immediate + sum(
                child.conditional_probability * outcome.expected_score
                for child, outcome in child_outcomes
            )
            action_by_node = (
                (node.node_id, action.signature),
                *(item for _, outcome in child_outcomes for item in outcome.action_by_node),
            )
            tie_key = "|".join((decision_key, *(outcome.tie_key for _, outcome in child_outcomes)))
        else:
            score = immediate + _terminal_value(request, next_state)
            action_by_node = ((node.node_id, action.signature),)
            tie_key = decision_key
        outcomes.append(
            OracleOutcome(
                expected_score=score,
                tie_key=tie_key,
                action_by_node=action_by_node,
            )
        )
    if not outcomes:
        raise ValueError("oracle found no complete feasible policy")
    best_score = max(item.expected_score for item in outcomes)
    return min(
        (item for item in outcomes if item.expected_score == best_score),
        key=lambda item: item.tie_key,
    )


def exhaustive_expected_oracle(
    request: MultiGameweekOptimisationRequest,
) -> OracleOutcome:
    """Exhaust the declared tiny action tree using test-owned transition logic."""

    grouped: dict[str, list[ScenarioTreeNode]] = defaultdict(list)
    for node in request.scenario_tree.nodes:
        if node.parent_id is not None:
            grouped[node.parent_id].append(node)
    children = {
        parent_id: tuple(sorted(nodes, key=lambda item: item.node_id))
        for parent_id, nodes in grouped.items()
    }
    initial_state = _OracleState(
        bank_tenths=request.initial_state.bank_tenths,
        free_transfers=request.initial_state.free_transfers,
        owned=tuple(
            _OwnedPlayer(
                player_id=spell.player_id,
                purchase_price_tenths=spell.purchase_price_tenths,
                current_price_tenths=spell.current_price_tenths,
            )
            for spell in request.initial_state.active_spells
        ),
    )
    return _best_node(
        request,
        node=request.scenario_tree.root,
        state=initial_state,
        children=children,
    )
