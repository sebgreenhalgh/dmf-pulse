"""Strict public contracts for Stage-11 multi-Gameweek transfer optimisation."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.optimisation.manager_state import ManagerState
from dmf_pulse.optimisation.models import (
    NonNegativeInt,
    OptimisationModel,
    PositiveInt,
    Sha256,
)


class SellingPriceRule(OptimisationModel):
    schema_version: Literal["selling-price-rule-v1"] = "selling-price-rule-v1"
    rule_id: StrictStr = Field(min_length=1, max_length=100)
    loss_mode: Literal["CURRENT_PRICE"] = "CURRENT_PRICE"
    retained_profit_numerator: NonNegativeInt
    retained_profit_denominator: PositiveInt
    rounding: Literal["FLOOR"] = "FLOOR"

    @model_validator(mode="after")
    def retained_share_is_valid(self) -> SellingPriceRule:
        if self.retained_profit_numerator > self.retained_profit_denominator:
            raise ValueError("retained profit share cannot exceed one")
        return self


class FreeTransferEventRule(OptimisationModel):
    unlimited_transfers_without_hits: StrictBool = False
    reset_before: NonNegativeInt | None = None
    earn_for_next_deadline: NonNegativeInt = 1
    carry_unused: StrictBool = True
    reset_after: NonNegativeInt | None = None
    cap_after: PositiveInt | None = None


class TransferRules(OptimisationModel):
    schema_version: Literal["multi-gameweek-transfer-rules-v1"] = "multi-gameweek-transfer-rules-v1"
    ruleset_id: StrictStr = Field(min_length=1, max_length=100)
    ruleset_version: StrictStr = Field(min_length=1, max_length=100)
    ruleset_hash: Sha256
    projection_mode: ProjectionMode
    capability: StrictStr
    capability_hash: Sha256 | None = None
    squad_size: PositiveInt
    position_squad_quota: dict[PlayerPosition, StrictInt]
    max_players_per_club: PositiveInt
    maximum_free_transfers: PositiveInt
    hit_cost_per_paid_transfer: NonNegativeInt
    max_transfers_per_deadline: PositiveInt
    selling_price_rule: SellingPriceRule
    event_rules: dict[StrictStr, FreeTransferEventRule]

    @model_validator(mode="after")
    def rules_are_complete(self) -> TransferRules:
        if sum(self.position_squad_quota.values()) != self.squad_size:
            raise ValueError("position quotas must sum to squad size")
        if set(self.position_squad_quota) != set(PlayerPosition):
            raise ValueError("position quotas must cover every FPL position")
        if any(value < 0 for value in self.position_squad_quota.values()):
            raise ValueError("position quotas cannot be negative")
        if "NORMAL" not in self.event_rules:
            raise ValueError("transfer rules require a NORMAL event")
        for event in self.event_rules.values():
            cap = event.cap_after or self.maximum_free_transfers
            if cap > self.maximum_free_transfers:
                raise ValueError("event FT cap cannot exceed the configured global maximum")
            if event.reset_before is not None and event.reset_before > cap:
                raise ValueError("event FT reset-before cannot exceed its cap")
            if event.reset_after is not None and event.reset_after > cap:
                raise ValueError("event FT reset-after cannot exceed its cap")
        return self


class PlayerCatalogEntry(OptimisationModel):
    player_id: StrictStr = Field(min_length=1, max_length=100)
    club_id: StrictStr = Field(min_length=1, max_length=100)
    position: PlayerPosition


class PlayerPriceState(OptimisationModel):
    current_price_tenths: NonNegativeInt
    purchasable: StrictBool = True


class TransferPrice(OptimisationModel):
    player_id: StrictStr
    price_tenths: NonNegativeInt


class TransferAction(OptimisationModel):
    action_id: StrictStr = Field(min_length=1, max_length=200)
    transfers_out: tuple[StrictStr, ...] = ()
    transfers_in: tuple[StrictStr, ...] = ()
    transition_event: StrictStr = "NORMAL"

    @model_validator(mode="after")
    def action_is_canonical(self) -> TransferAction:
        if len(self.transfers_out) != len(self.transfers_in):
            raise ValueError("transfer-in and transfer-out counts must match")
        for name, values in (
            ("transfers_out", self.transfers_out),
            ("transfers_in", self.transfers_in),
        ):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"{name} must be sorted and unique")
        if set(self.transfers_out) & set(self.transfers_in):
            raise ValueError("a player cannot be sold and repurchased in one action")
        return self

    @property
    def transfer_count(self) -> int:
        return len(self.transfers_out)

    @property
    def signature(self) -> str:
        return (
            f"{self.transition_event}|{','.join(self.transfers_out)}->{','.join(self.transfers_in)}"
        )


class FreeTransferArc(OptimisationModel):
    event: StrictStr
    unlimited_transfers_without_hits: StrictBool = False
    effective_ft_before: NonNegativeInt
    transfer_count: NonNegativeInt
    free_used: NonNegativeInt
    paid_transfers: NonNegativeInt
    hit_points: NonNegativeInt
    earned_for_next_deadline: NonNegativeInt
    ft_after: NonNegativeInt
    maximum_free_transfers: PositiveInt

    @model_validator(mode="after")
    def arc_reconciles(self) -> FreeTransferArc:
        if self.unlimited_transfers_without_hits:
            if self.free_used != 0 or self.paid_transfers != 0 or self.hit_points != 0:
                raise ValueError("unlimited transfer events cannot consume FT or apply hits")
        else:
            if self.free_used + self.paid_transfers != self.transfer_count:
                raise ValueError("free and paid transfers must reconcile")
            if self.free_used > self.effective_ft_before:
                raise ValueError("free transfers used exceed effective availability")
        if self.ft_after > self.maximum_free_transfers:
            raise ValueError("free-transfer state exceeds configured maximum")
        return self


class TacticalValueRecord(OptimisationModel):
    """Frozen Stage-10 tactical evaluation for one squad at one decision node."""

    squad_ids: tuple[StrictStr, ...]
    expected_points: Decimal
    p10_points: Decimal
    p90_points: Decimal
    tactical_plan_sha256: Sha256
    tactical_plan: dict[StrictStr, object]
    exact_stage10_evaluation: StrictBool = True

    @model_validator(mode="after")
    def tactical_record_is_canonical(self) -> TacticalValueRecord:
        if self.squad_ids != tuple(sorted(self.squad_ids)):
            raise ValueError("tactical-value squad IDs must be sorted")
        if len(self.squad_ids) != len(set(self.squad_ids)):
            raise ValueError("tactical-value squad IDs must be unique")
        if not self.p10_points <= self.expected_points <= self.p90_points:
            raise ValueError("tactical p10, mean and p90 must be monotone")
        return self


class ScenarioTreeNode(OptimisationModel):
    node_id: StrictStr = Field(min_length=1, max_length=100)
    parent_id: StrictStr | None = None
    gameweek: PositiveInt
    conditional_probability: Decimal = Field(gt=Decimal("0"), le=Decimal("1"))
    information_set_key: StrictStr = Field(min_length=1, max_length=200)
    revealed_information: tuple[StrictStr, ...] = ()
    availability_state: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    fixture_state: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    points_state_id: StrictStr = Field(min_length=1, max_length=200)
    prices: dict[StrictStr, PlayerPriceState]
    transition_event: StrictStr = "NORMAL"
    allowed_transfer_in_ids: tuple[StrictStr, ...] = ()
    tactical_values: tuple[TacticalValueRecord, ...]

    @model_validator(mode="after")
    def node_is_canonical(self) -> ScenarioTreeNode:
        if self.revealed_information != tuple(sorted(self.revealed_information)):
            raise ValueError("revealed information must be sorted")
        if len(self.revealed_information) != len(set(self.revealed_information)):
            raise ValueError("revealed information must be unique")
        if self.allowed_transfer_in_ids != tuple(sorted(self.allowed_transfer_in_ids)):
            raise ValueError("allowed transfer-in IDs must be sorted")
        if len(self.allowed_transfer_in_ids) != len(set(self.allowed_transfer_in_ids)):
            raise ValueError("allowed transfer-in IDs must be unique")
        signatures = tuple(item.squad_ids for item in self.tactical_values)
        if signatures != tuple(sorted(signatures)):
            raise ValueError("tactical values must be sorted by squad signature")
        if len(signatures) != len(set(signatures)):
            raise ValueError("tactical values must contain unique squad signatures")
        return self


class ScenarioTree(OptimisationModel):
    schema_version: Literal["multi-gameweek-scenario-tree-v1"] = "multi-gameweek-scenario-tree-v1"
    tree_id: StrictStr = Field(min_length=1, max_length=200)
    nodes: tuple[ScenarioTreeNode, ...] = Field(min_length=1)
    tree_sha256: Sha256

    @model_validator(mode="after")
    def tree_is_canonical(self) -> ScenarioTree:
        ordered = tuple(sorted(self.nodes, key=lambda item: (item.gameweek, item.node_id)))
        if self.nodes != ordered:
            raise ValueError("scenario-tree nodes must be sorted by Gameweek and node ID")
        ids = tuple(item.node_id for item in self.nodes)
        if len(ids) != len(set(ids)):
            raise ValueError("scenario-tree node IDs must be unique")
        return self

    @property
    def root(self) -> ScenarioTreeNode:
        roots = tuple(item for item in self.nodes if item.parent_id is None)
        if len(roots) != 1:
            raise ValueError("scenario tree must have exactly one root")
        return roots[0]


class SearchPolicy(OptimisationModel):
    schema_version: Literal["multi-gameweek-search-policy-v1"] = "multi-gameweek-search-policy-v1"
    backend: Literal["BOUNDED_EXACT_MULTISTAGE_ENUMERATOR"] = "BOUNDED_EXACT_MULTISTAGE_ENUMERATOR"
    max_transfers_per_node: NonNegativeInt
    max_actions_per_state: PositiveInt
    max_state_expansions: PositiveInt
    max_policy_candidates: PositiveInt
    max_returned_root_candidates: PositiveInt
    alternative_expected_sacrifice_points: Decimal = Field(ge=Decimal("0"))
    material_difference_points: Decimal = Field(ge=Decimal("0"))
    deterministic_seed: NonNegativeInt = 0
    policy_sha256: Sha256


class TerminalValuePolicy(OptimisationModel):
    schema_version: Literal["multi-gameweek-terminal-policy-v1"] = (
        "multi-gameweek-terminal-policy-v1"
    )
    policy_id: StrictStr = Field(min_length=1, max_length=100)
    policy_version: StrictStr = Field(min_length=1, max_length=50)
    enabled: StrictBool
    bank_points_per_tenth: Decimal = Field(ge=Decimal("0"))
    free_transfer_points: Decimal = Field(ge=Decimal("0"))
    liquidation_points_per_tenth: Decimal = Field(ge=Decimal("0"))
    policy_sha256: Sha256

    @model_validator(mode="after")
    def disabled_policy_has_no_latent_weights(self) -> TerminalValuePolicy:
        if not self.enabled and any(
            value != Decimal(0)
            for value in (
                self.bank_points_per_tenth,
                self.free_transfer_points,
                self.liquidation_points_per_tenth,
            )
        ):
            raise ValueError("disabled terminal policy must have zero coefficients")
        return self


class TerminalValueBreakdown(OptimisationModel):
    policy_id: StrictStr
    bank_value: Decimal
    free_transfer_value: Decimal
    liquidation_value: Decimal
    total: Decimal

    @model_validator(mode="after")
    def components_reconcile(self) -> TerminalValueBreakdown:
        if self.bank_value + self.free_transfer_value + self.liquidation_value != self.total:
            raise ValueError("terminal-value components do not reconcile")
        return self


class MultiGameweekOptimisationRequest(OptimisationModel):
    schema_version: Literal["multi-gameweek-optimisation-request-v1"] = (
        "multi-gameweek-optimisation-request-v1"
    )
    request_id: StrictStr = Field(min_length=1, max_length=100)
    projection_mode: ProjectionMode
    initial_state: ManagerState
    candidate_pool: tuple[PlayerCatalogEntry, ...]
    rules: TransferRules
    scenario_tree: ScenarioTree
    search_policy: SearchPolicy
    terminal_policy: TerminalValuePolicy
    assumptions: tuple[StrictStr, ...] = ()
    request_sha256: Sha256

    @model_validator(mode="after")
    def request_is_canonical(self) -> MultiGameweekOptimisationRequest:
        player_ids = tuple(item.player_id for item in self.candidate_pool)
        if player_ids != tuple(sorted(player_ids)):
            raise ValueError("candidate players must be sorted by player ID")
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("candidate player IDs must be unique")
        if self.assumptions != tuple(sorted(self.assumptions)):
            raise ValueError("request assumptions must be sorted")
        if len(self.assumptions) != len(set(self.assumptions)):
            raise ValueError("request assumptions must be unique")
        if self.projection_mode is not self.rules.projection_mode:
            raise ValueError("request and transfer-rules projection modes differ")
        return self


class TacticalNodeEvaluation(OptimisationModel):
    expected_points: Decimal
    p10_points: Decimal
    p90_points: Decimal
    tactical_plan_sha256: Sha256
    tactical_plan: dict[StrictStr, object]
    exact_stage10_evaluation: StrictBool
    source: Literal["STAGE10_ADAPTER", "FROZEN_STAGE10_RECORD"]

    @model_validator(mode="after")
    def values_are_monotone(self) -> TacticalNodeEvaluation:
        if not self.p10_points <= self.expected_points <= self.p90_points:
            raise ValueError("tactical p10, mean and p90 must be monotone")
        return self


class NodeDecision(OptimisationModel):
    node_id: StrictStr
    information_set_key: StrictStr
    gameweek: PositiveInt
    action: TransferAction
    state_before_sha256: Sha256
    state_after: ManagerState
    bank_before_tenths: NonNegativeInt
    bank_after_tenths: NonNegativeInt
    free_transfers_before: NonNegativeInt
    free_transfers_after: NonNegativeInt
    paid_transfers: NonNegativeInt
    hit_points: NonNegativeInt
    selling_prices: tuple[TransferPrice, ...]
    buying_prices: tuple[TransferPrice, ...]
    squad_after: tuple[StrictStr, ...]
    tactical_evaluation: TacticalNodeEvaluation

    @model_validator(mode="after")
    def decision_reconciles(self) -> NodeDecision:
        if self.state_after.bank_tenths != self.bank_after_tenths:
            raise ValueError("decision bank path differs from resulting state")
        if self.state_after.free_transfers != self.free_transfers_after:
            raise ValueError("decision FT path differs from resulting state")
        if self.state_after.squad_ids != self.squad_after:
            raise ValueError("decision squad path differs from resulting state")
        if self.state_after.current_gameweek != self.gameweek + 1:
            raise ValueError("decision state must advance exactly one Gameweek")
        if self.state_after.observed_node_id != self.node_id:
            raise ValueError("decision state must retain its decision-node lineage")
        if tuple(item.player_id for item in self.selling_prices) != self.action.transfers_out:
            raise ValueError("decision selling-price rows must match transferred-out players")
        if tuple(item.player_id for item in self.buying_prices) != self.action.transfers_in:
            raise ValueError("decision buying-price rows must match transferred-in players")
        expected_bank = (
            self.bank_before_tenths
            + sum(item.price_tenths for item in self.selling_prices)
            - sum(item.price_tenths for item in self.buying_prices)
        )
        if expected_bank != self.bank_after_tenths:
            raise ValueError("decision bank values do not conserve transfer cash")
        if self.paid_transfers > self.action.transfer_count:
            raise ValueError("paid transfers cannot exceed the transfer count")
        if self.paid_transfers == 0 and self.hit_points != 0:
            raise ValueError("a decision without paid transfers cannot carry a hit")
        return self


class BackendStatus(StrEnum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE_NOT_PROVEN_OPTIMAL = "FEASIBLE_NOT_PROVEN_OPTIMAL"
    TIME_RESOURCE_LIMIT_WITH_INCUMBENT = "TIME_RESOURCE_LIMIT_WITH_INCUMBENT"
    TIME_RESOURCE_LIMIT_NO_INCUMBENT = "TIME_RESOURCE_LIMIT_NO_INCUMBENT"
    INFEASIBLE = "INFEASIBLE"
    UNBOUNDED = "UNBOUNDED"
    SOLVER_BACKEND_ERROR = "SOLVER_BACKEND_ERROR"
    INPUT_CAPABILITY_BLOCKED = "INPUT_CAPABILITY_BLOCKED"


class OptimalityGuarantee(StrEnum):
    EXACT_DECLARED_TREE_AND_ACTION_SPACE = "EXACT_DECLARED_TREE_AND_ACTION_SPACE"
    NONE = "NONE"


class SolverDiagnostics(OptimisationModel):
    backend: Literal["BOUNDED_EXACT_MULTISTAGE_ENUMERATOR"] = "BOUNDED_EXACT_MULTISTAGE_ENUMERATOR"
    status: BackendStatus
    termination_reason: StrictStr
    optimality_guarantee: OptimalityGuarantee
    objective: Decimal | None = None
    incumbent: Decimal | None = None
    bound: Decimal | None = None
    absolute_gap: Decimal | None = None
    relative_gap: Decimal | None = None
    state_expansions: NonNegativeInt = 0
    action_candidates: NonNegativeInt = 0
    policy_candidates: NonNegativeInt = 0
    pareto_candidates: NonNegativeInt = 0
    memo_entries: NonNegativeInt = 0
    deterministic_tie_key: StrictStr | None = None
    runtime_ms: NonNegativeInt | None = None
    configuration_sha256: Sha256

    @model_validator(mode="after")
    def termination_shape_is_coherent(self) -> SolverDiagnostics:
        if self.status is BackendStatus.OPTIMAL:
            if (
                self.optimality_guarantee
                is not OptimalityGuarantee.EXACT_DECLARED_TREE_AND_ACTION_SPACE
            ):
                raise ValueError("optimal status requires the exact declared-space guarantee")
            if (
                self.objective is None
                or self.incumbent is None
                or self.bound is None
                or self.absolute_gap != Decimal(0)
                or self.relative_gap != Decimal(0)
            ):
                raise ValueError(
                    "optimal status requires objective, bound, incumbent and zero gaps"
                )
            if not self.objective == self.incumbent == self.bound:
                raise ValueError("optimal objective, incumbent and bound must be identical")
        elif self.status is BackendStatus.TIME_RESOURCE_LIMIT_WITH_INCUMBENT:
            if self.incumbent is None or self.optimality_guarantee is not OptimalityGuarantee.NONE:
                raise ValueError("resource-limit incumbent status requires an unproven incumbent")
            if (
                self.objective != self.incumbent
                or self.bound is not None
                or self.absolute_gap is not None
                or self.relative_gap is not None
            ):
                raise ValueError("resource-limit incumbent cannot report an unproved bound or gap")
        elif self.status is BackendStatus.FEASIBLE_NOT_PROVEN_OPTIMAL:
            if self.incumbent is None or self.optimality_guarantee is not OptimalityGuarantee.NONE:
                raise ValueError("feasible status requires an unproven incumbent")
            if self.objective != self.incumbent:
                raise ValueError("feasible objective must equal its incumbent")
        elif self.status is BackendStatus.TIME_RESOURCE_LIMIT_NO_INCUMBENT:
            if any(
                value is not None
                for value in (
                    self.objective,
                    self.incumbent,
                    self.bound,
                    self.absolute_gap,
                    self.relative_gap,
                )
            ):
                raise ValueError("resource-limit no-incumbent status cannot contain an incumbent")
        elif self.status in {
            BackendStatus.INFEASIBLE,
            BackendStatus.UNBOUNDED,
            BackendStatus.SOLVER_BACKEND_ERROR,
            BackendStatus.INPUT_CAPABILITY_BLOCKED,
        }:
            if self.optimality_guarantee is not OptimalityGuarantee.NONE:
                raise ValueError("non-optimal terminal statuses cannot claim an exact guarantee")
            if any(
                value is not None
                for value in (
                    self.objective,
                    self.incumbent,
                    self.bound,
                    self.absolute_gap,
                    self.relative_gap,
                )
            ):
                raise ValueError("terminal failure statuses cannot carry objective claims")
        return self


class ObjectiveMode(StrEnum):
    EXPECTED = "EXPECTED"
    CONSERVATIVE = "CONSERVATIVE"
    HIGH_UPSIDE = "HIGH_UPSIDE"


class PlanKind(StrEnum):
    RECOMMENDED = "RECOMMENDED"
    CONSERVATIVE = "CONSERVATIVE"
    HIGH_UPSIDE = "HIGH_UPSIDE"
    NO_TRANSFER_BASELINE = "NO_TRANSFER_BASELINE"
    TRANSFER_COUNT_FRONTIER = "TRANSFER_COUNT_FRONTIER"


class UtilityBreakdown(OptimisationModel):
    expected_horizon_utility: Decimal
    current_gameweek_contribution: Decimal
    future_contribution: Decimal
    expected_hit_cost: Decimal = Field(ge=Decimal("0"))
    terminal_flexibility_contribution: Decimal
    objective_total: Decimal

    @model_validator(mode="after")
    def utility_reconciles(self) -> UtilityBreakdown:
        total = (
            self.current_gameweek_contribution
            + self.future_contribution
            - self.expected_hit_cost
            + self.terminal_flexibility_contribution
        )
        if total != self.expected_horizon_utility or total != self.objective_total:
            raise ValueError("utility components do not reconcile exactly")
        return self


class LeafUtility(OptimisationModel):
    leaf_node_id: StrictStr
    probability: Decimal = Field(gt=Decimal("0"), le=Decimal("1"))
    expected_utility: Decimal
    conservative_utility: Decimal
    upside_utility: Decimal
    terminal_value: TerminalValueBreakdown


class MultiGameweekPlan(OptimisationModel):
    schema_version: Literal["multi-gameweek-plan-v1"] = "multi-gameweek-plan-v1"
    plan_kind: PlanKind
    objective_mode: ObjectiveMode
    selection_score: Decimal
    current_action: NodeDecision
    future_policy: tuple[NodeDecision, ...]
    leaf_utilities: tuple[LeafUtility, ...]
    bank_path_tenths: tuple[tuple[StrictStr, NonNegativeInt], ...]
    free_transfer_path: tuple[tuple[StrictStr, NonNegativeInt], ...]
    squad_path: tuple[tuple[StrictStr, tuple[StrictStr, ...]], ...]
    utility: UtilityBreakdown
    terminal_value: TerminalValueBreakdown
    solver_status: SolverDiagnostics
    assumptions: tuple[StrictStr, ...]
    plan_sha256: Sha256

    @model_validator(mode="after")
    def plan_is_canonical(self) -> MultiGameweekPlan:
        decisions = (self.current_action, *self.future_policy)
        if decisions != tuple(sorted(decisions, key=lambda item: (item.gameweek, item.node_id))):
            raise ValueError("policy decisions must be sorted by Gameweek and node ID")
        ids = tuple(item.node_id for item in decisions)
        if len(ids) != len(set(ids)):
            raise ValueError("policy contains duplicate decision nodes")
        if self.leaf_utilities != tuple(
            sorted(self.leaf_utilities, key=lambda item: item.leaf_node_id)
        ):
            raise ValueError("leaf utilities must be sorted")
        if sum((item.probability for item in self.leaf_utilities), Decimal(0)) != Decimal(1):
            raise ValueError("leaf probabilities must sum exactly to one")
        if self.assumptions != tuple(sorted(self.assumptions)):
            raise ValueError("plan assumptions must be sorted")
        if len(self.assumptions) != len(set(self.assumptions)):
            raise ValueError("plan assumptions must be unique")
        expected_bank_path = tuple((item.node_id, item.bank_after_tenths) for item in decisions)
        expected_ft_path = tuple((item.node_id, item.free_transfers_after) for item in decisions)
        expected_squad_path = tuple((item.node_id, item.squad_after) for item in decisions)
        if self.bank_path_tenths != expected_bank_path:
            raise ValueError("plan bank path differs from its decisions")
        if self.free_transfer_path != expected_ft_path:
            raise ValueError("plan free-transfer path differs from its decisions")
        if self.squad_path != expected_squad_path:
            raise ValueError("plan squad path differs from its decisions")
        weighted_expected = sum(
            (item.probability * item.expected_utility for item in self.leaf_utilities),
            Decimal(0),
        )
        if weighted_expected != self.utility.expected_horizon_utility:
            raise ValueError("plan leaf expected utilities do not reconcile")
        selection_field = {
            ObjectiveMode.EXPECTED: "expected_utility",
            ObjectiveMode.CONSERVATIVE: "conservative_utility",
            ObjectiveMode.HIGH_UPSIDE: "upside_utility",
        }[self.objective_mode]
        weighted_selection = sum(
            (item.probability * getattr(item, selection_field) for item in self.leaf_utilities),
            Decimal(0),
        )
        if weighted_selection != self.selection_score:
            raise ValueError("plan leaf selection utilities do not reconcile")
        terminal_bank = sum(
            (item.probability * item.terminal_value.bank_value for item in self.leaf_utilities),
            Decimal(0),
        )
        terminal_ft = sum(
            (
                item.probability * item.terminal_value.free_transfer_value
                for item in self.leaf_utilities
            ),
            Decimal(0),
        )
        terminal_liquidation = sum(
            (
                item.probability * item.terminal_value.liquidation_value
                for item in self.leaf_utilities
            ),
            Decimal(0),
        )
        if (
            self.terminal_value.bank_value != terminal_bank
            or self.terminal_value.free_transfer_value != terminal_ft
            or self.terminal_value.liquidation_value != terminal_liquidation
            or self.utility.terminal_flexibility_contribution != self.terminal_value.total
        ):
            raise ValueError("plan terminal values do not reconcile with its leaves")
        if (
            self.solver_status.objective != self.selection_score
            or self.solver_status.incumbent != self.selection_score
        ):
            raise ValueError("plan solver objective differs from its selection score")
        return self


class TransferCountFrontierPoint(OptimisationModel):
    """Best already-evaluated root policy at one exact transfer count."""

    transfer_count: NonNegativeInt
    plan: MultiGameweekPlan
    immediate_expected_points_before_hit: Decimal
    transfer_hit_points: NonNegativeInt
    current_gameweek_objective: Decimal

    @model_validator(mode="after")
    def point_reconciles(self) -> TransferCountFrontierPoint:
        current = self.plan.current_action
        if self.plan.plan_kind is not PlanKind.TRANSFER_COUNT_FRONTIER:
            raise ValueError("frontier point plan has the wrong plan kind")
        if self.plan.objective_mode is not ObjectiveMode.EXPECTED:
            raise ValueError("frontier point must retain the expected-objective policy")
        if current.action.transfer_count != self.transfer_count:
            raise ValueError("frontier point transfer count differs from its root action")
        if current.tactical_evaluation.expected_points != self.immediate_expected_points_before_hit:
            raise ValueError("frontier point expected points differ from Stage 10")
        if current.hit_points != self.transfer_hit_points:
            raise ValueError("frontier point hit differs from its compiled transition")
        if (
            self.immediate_expected_points_before_hit - Decimal(self.transfer_hit_points)
            != self.current_gameweek_objective
        ):
            raise ValueError("frontier point current objective does not reconcile")
        return self


class TransferCountFrontier(OptimisationModel):
    """Canonical exact-count frontier selected from one Stage-11 evaluated family."""

    schema_version: Literal["transfer-count-frontier-v1"] = "transfer-count-frontier-v1"
    objective_scope: Literal["CURRENT_GAMEWEEK_POINTS_AFTER_HIT"] = (
        "CURRENT_GAMEWEEK_POINTS_AFTER_HIT"
    )
    points: tuple[TransferCountFrontierPoint, ...]
    frontier_sha256: Sha256

    @model_validator(mode="after")
    def frontier_is_canonical_and_sealed(self) -> TransferCountFrontier:
        if not self.points or self.points[0].transfer_count != 0:
            raise ValueError("transfer-count frontier requires at least the hold plan")
        counts = tuple(item.transfer_count for item in self.points)
        if counts != tuple(sorted(set(counts))):
            raise ValueError("transfer-count frontier points must be canonically ordered")
        if self.frontier_sha256 != _hash_without(self, "frontier_sha256"):
            raise ValueError("transfer-count frontier semantic hash does not match")
        return self


class AlternativeAvailability(StrEnum):
    DISTINCT = "DISTINCT"
    NO_MATERIALLY_DISTINCT_PLAN = "NO_MATERIALLY_DISTINCT_PLAN"
    UNAVAILABLE = "UNAVAILABLE"


class PlanAlternative(OptimisationModel):
    availability: AlternativeAvailability
    plan: MultiGameweekPlan | None = None
    reason: StrictStr

    @model_validator(mode="after")
    def availability_reconciles(self) -> PlanAlternative:
        if (self.availability is AlternativeAvailability.DISTINCT) != (self.plan is not None):
            raise ValueError("alternative availability and plan presence disagree")
        return self


class TransferMove(OptimisationModel):
    player_out: StrictStr
    player_in: StrictStr


class MoveMarginalValue(OptimisationModel):
    move: TransferMove
    exact_leave_one_out_value: Decimal | None
    leave_one_out_feasible: StrictBool
    additive: StrictBool
    explanation: StrictStr


class MoveAttribution(OptimisationModel):
    root_action_signature: StrictStr
    bundle_uplift_vs_no_transfer: Decimal
    marginal_values: tuple[MoveMarginalValue, ...]
    bundle_interaction_value: Decimal | None
    interaction_explanation: StrictStr


class ResultConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    BLOCKED = "BLOCKED"


class MultiGameweekResultStatus(StrEnum):
    SUCCESS = "SUCCESS"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    INFEASIBLE = "INFEASIBLE"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class MultiGameweekLineage(OptimisationModel):
    stage10_parent_sha: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")
    request_sha256: Sha256
    manager_state_sha256: Sha256
    scenario_tree_sha256: Sha256
    search_policy_sha256: Sha256
    terminal_policy_sha256: Sha256
    ruleset_hash: Sha256
    input_sha256: Sha256


class MultiGameweekOptimisationResult(OptimisationModel):
    schema_version: Literal["multi-gameweek-optimisation-result-v1"] = (
        "multi-gameweek-optimisation-result-v1"
    )
    status: MultiGameweekResultStatus
    request_id: StrictStr
    recommended_plan: MultiGameweekPlan | None = None
    conservative_plan: PlanAlternative
    high_upside_plan: PlanAlternative
    no_transfer_baseline: MultiGameweekPlan | None = None
    transfer_count_frontier: TransferCountFrontier | None = None
    marginal_value_of_each_move: MoveAttribution | None = None
    current_action: TransferAction | None = None
    future_policy: tuple[NodeDecision, ...] = ()
    solver_status: SolverDiagnostics
    confidence: ResultConfidence
    assumptions: tuple[StrictStr, ...]
    warnings: tuple[StrictStr, ...] = ()
    lineage: MultiGameweekLineage
    error_code: StrictStr | None = None
    error_message: StrictStr | None = None
    result_sha256: Sha256

    @model_validator(mode="after")
    def result_reconciles(self) -> MultiGameweekOptimisationResult:
        if self.assumptions != tuple(sorted(self.assumptions)) or len(self.assumptions) != len(
            set(self.assumptions)
        ):
            raise ValueError("result assumptions must be sorted and unique")
        if self.warnings != tuple(sorted(self.warnings)) or len(self.warnings) != len(
            set(self.warnings)
        ):
            raise ValueError("result warnings must be sorted and unique")
        if self.recommended_plan is not None:
            if self.current_action != self.recommended_plan.current_action.action:
                raise ValueError("result current action differs from recommended plan")
            if self.future_policy != self.recommended_plan.future_policy:
                raise ValueError("result future policy differs from recommended plan")
            if self.recommended_plan.plan_kind is not PlanKind.RECOMMENDED:
                raise ValueError("result recommendation has the wrong plan kind")
            if self.solver_status != self.recommended_plan.solver_status:
                raise ValueError("result solver status differs from its recommended plan")
        if self.no_transfer_baseline is not None and (
            self.no_transfer_baseline.plan_kind is not PlanKind.NO_TRANSFER_BASELINE
            or self.no_transfer_baseline.current_action.action.transfer_count != 0
        ):
            raise ValueError("no-transfer baseline must retain the root squad")
        for alternative, kind in (
            (self.conservative_plan, PlanKind.CONSERVATIVE),
            (self.high_upside_plan, PlanKind.HIGH_UPSIDE),
        ):
            if alternative.plan is not None and alternative.plan.plan_kind is not kind:
                raise ValueError("alternative plan has the wrong plan kind")
        if self.status is MultiGameweekResultStatus.SUCCESS and self.recommended_plan is None:
            raise ValueError("successful result requires a recommended plan")
        if self.status is MultiGameweekResultStatus.SUCCESS and (
            self.no_transfer_baseline is None
            or self.marginal_value_of_each_move is None
            or self.confidence is ResultConfidence.BLOCKED
        ):
            raise ValueError("successful result requires baseline, attribution and confidence")
        if (
            self.status is MultiGameweekResultStatus.SUCCESS
            and self.solver_status.status is not BackendStatus.OPTIMAL
        ):
            raise ValueError("successful result requires an optimal backend status")
        if self.status is MultiGameweekResultStatus.RESOURCE_LIMIT:
            with_incumbent = (
                self.solver_status.status is BackendStatus.TIME_RESOURCE_LIMIT_WITH_INCUMBENT
            )
            without_incumbent = (
                self.solver_status.status is BackendStatus.TIME_RESOURCE_LIMIT_NO_INCUMBENT
            )
            if not (with_incumbent or without_incumbent):
                raise ValueError("resource-limit result requires a resource-limit backend status")
            if with_incumbent != (self.recommended_plan is not None):
                raise ValueError("resource-limit incumbent status and plan presence disagree")
            if with_incumbent and (
                self.conservative_plan.availability is not AlternativeAvailability.UNAVAILABLE
                or self.high_upside_plan.availability is not AlternativeAvailability.UNAVAILABLE
                or self.marginal_value_of_each_move is not None
            ):
                raise ValueError(
                    "incomplete frontiers cannot claim exact alternatives or attribution"
                )
        if self.status in {
            MultiGameweekResultStatus.BLOCKED,
            MultiGameweekResultStatus.INFEASIBLE,
            MultiGameweekResultStatus.ERROR,
        } and (self.error_code is None or self.error_message is None):
            raise ValueError("failed result requires an error code and message")
        if self.status in {
            MultiGameweekResultStatus.BLOCKED,
            MultiGameweekResultStatus.INFEASIBLE,
            MultiGameweekResultStatus.ERROR,
        } and (
            self.recommended_plan is not None
            or self.conservative_plan.plan is not None
            or self.high_upside_plan.plan is not None
            or self.no_transfer_baseline is not None
            or self.transfer_count_frontier is not None
            or self.marginal_value_of_each_move is not None
            or self.current_action is not None
            or self.future_policy
        ):
            raise ValueError("terminal failure results cannot contain executable plans")
        expected_backend = {
            MultiGameweekResultStatus.BLOCKED: BackendStatus.INPUT_CAPABILITY_BLOCKED,
            MultiGameweekResultStatus.INFEASIBLE: BackendStatus.INFEASIBLE,
            MultiGameweekResultStatus.ERROR: BackendStatus.SOLVER_BACKEND_ERROR,
        }.get(self.status)
        if expected_backend is not None and self.solver_status.status is not expected_backend:
            raise ValueError("failed result status and backend status disagree")
        if self.status is MultiGameweekResultStatus.SUCCESS and (
            self.error_code is not None or self.error_message is not None
        ):
            raise ValueError("successful result cannot carry a terminal error")
        if self.status is MultiGameweekResultStatus.RESOURCE_LIMIT:
            has_error = self.error_code is not None and self.error_message is not None
            if (self.recommended_plan is None) != has_error:
                raise ValueError(
                    "resource-limit result requires an error only when no incumbent exists"
                )
        return self


class StateAdvanceResult(OptimisationModel):
    schema_version: Literal["multi-gameweek-state-advance-v1"] = "multi-gameweek-state-advance-v1"
    request_id: StrictStr
    executed_action: TransferAction
    observed_node_id: StrictStr | None
    manager_state: ManagerState
    advance_sha256: Sha256

    @model_validator(mode="after")
    def observation_reconciles(self) -> StateAdvanceResult:
        if (
            self.observed_node_id is not None
            and self.manager_state.observed_node_id != self.observed_node_id
        ):
            raise ValueError("advanced manager state differs from its observed node")
        return self


def _hash_without(value: OptimisationModel, field: str) -> str:
    payload = value.model_dump(mode="json")
    payload[field] = None
    return semantic_sha256(payload)


def seal_scenario_tree(value: ScenarioTree) -> ScenarioTree:
    return value.model_copy(update={"tree_sha256": _hash_without(value, "tree_sha256")})


def verify_scenario_tree_hash(value: ScenarioTree) -> None:
    if value.tree_sha256 != _hash_without(value, "tree_sha256"):
        raise ValueError("scenario-tree semantic hash does not match")


def seal_search_policy(value: SearchPolicy) -> SearchPolicy:
    return value.model_copy(update={"policy_sha256": _hash_without(value, "policy_sha256")})


def verify_search_policy_hash(value: SearchPolicy) -> None:
    if value.policy_sha256 != _hash_without(value, "policy_sha256"):
        raise ValueError("search-policy semantic hash does not match")


def seal_terminal_policy(value: TerminalValuePolicy) -> TerminalValuePolicy:
    return value.model_copy(update={"policy_sha256": _hash_without(value, "policy_sha256")})


def verify_terminal_policy_hash(value: TerminalValuePolicy) -> None:
    if value.policy_sha256 != _hash_without(value, "policy_sha256"):
        raise ValueError("terminal-policy semantic hash does not match")


def seal_request(value: MultiGameweekOptimisationRequest) -> MultiGameweekOptimisationRequest:
    return value.model_copy(update={"request_sha256": _hash_without(value, "request_sha256")})


def verify_request_hash(value: MultiGameweekOptimisationRequest) -> None:
    if value.request_sha256 != _hash_without(value, "request_sha256"):
        raise ValueError("multi-Gameweek request semantic hash does not match")


def seal_plan(value: MultiGameweekPlan) -> MultiGameweekPlan:
    return value.model_copy(update={"plan_sha256": _hash_without(value, "plan_sha256")})


def verify_plan_hash(value: MultiGameweekPlan) -> None:
    if value.plan_sha256 != _hash_without(value, "plan_sha256"):
        raise ValueError("multi-Gameweek plan semantic hash does not match")


def seal_transfer_count_frontier(value: TransferCountFrontier) -> TransferCountFrontier:
    return value.model_copy(update={"frontier_sha256": _hash_without(value, "frontier_sha256")})


def verify_transfer_count_frontier_hash(value: TransferCountFrontier) -> None:
    if value.frontier_sha256 != _hash_without(value, "frontier_sha256"):
        raise ValueError("transfer-count frontier semantic hash does not match")


def _result_hash(value: MultiGameweekOptimisationResult) -> str:
    payload = value.model_dump(mode="json")
    payload["result_sha256"] = None
    if value.transfer_count_frontier is None:
        payload.pop("transfer_count_frontier")
    return semantic_sha256(payload)


def seal_result(value: MultiGameweekOptimisationResult) -> MultiGameweekOptimisationResult:
    return value.model_copy(update={"result_sha256": _result_hash(value)})


def verify_result_hash(value: MultiGameweekOptimisationResult) -> None:
    if value.result_sha256 != _result_hash(value):
        raise ValueError("multi-Gameweek result semantic hash does not match")


def seal_advance(value: StateAdvanceResult) -> StateAdvanceResult:
    return value.model_copy(update={"advance_sha256": _hash_without(value, "advance_sha256")})


def verify_advance_hash(value: StateAdvanceResult) -> None:
    if value.advance_sha256 != _hash_without(value, "advance_sha256"):
        raise ValueError("state-advance semantic hash does not match")
