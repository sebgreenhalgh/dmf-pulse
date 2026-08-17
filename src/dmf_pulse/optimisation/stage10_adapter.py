"""Explicit adapter from Stage 11 candidate squads to canonical Stage-10 tactics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import GameweekPointScenario
from dmf_pulse.optimisation.manager_state import ManagerState
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidateSquad,
    OneGameweekOptimiserPolicy,
    OneGameweekRulesView,
    OptimalityGuarantee,
    SearchScope,
    SolverStatus,
)
from dmf_pulse.optimisation.multi_gameweek_errors import InfeasiblePolicyError
from dmf_pulse.optimisation.multi_gameweek_models import (
    PlayerCatalogEntry,
    ScenarioTreeNode,
    TacticalNodeEvaluation,
)
from dmf_pulse.optimisation.tactics import (
    enumerate_tactical_configurations,
    evaluate_tactical_configuration,
)


class TacticalEvaluator(Protocol):
    def evaluate(
        self, *, node: ScenarioTreeNode, state: ManagerState
    ) -> TacticalNodeEvaluation: ...


@dataclass(frozen=True)
class StaticTacticalEvaluator:
    """Consume immutable Stage-10 records embedded in TEST/REPLAY fixtures."""

    def evaluate(self, *, node: ScenarioTreeNode, state: ManagerState) -> TacticalNodeEvaluation:
        record = next(
            (item for item in node.tactical_values if item.squad_ids == state.squad_ids),
            None,
        )
        if record is None:
            raise InfeasiblePolicyError(
                f"node {node.node_id} has no Stage-10 tactical value for squad {state.squad_ids}"
            )
        return TacticalNodeEvaluation(
            expected_points=record.expected_points,
            p10_points=record.p10_points,
            p90_points=record.p90_points,
            tactical_plan_sha256=record.tactical_plan_sha256,
            tactical_plan=record.tactical_plan,
            exact_stage10_evaluation=record.exact_stage10_evaluation,
            source="FROZEN_STAGE10_RECORD",
        )


@dataclass(frozen=True)
class Stage10TacticalAdapter:
    """Run Stage 10 exactly; Stage 11 never reimplements lineup or autosub logic."""

    candidate_pool: tuple[PlayerCatalogEntry, ...]
    rules: OneGameweekRulesView
    policy: OneGameweekOptimiserPolicy
    scenarios_by_node: Mapping[str, tuple[GameweekPointScenario, ...]]

    def evaluate(self, *, node: ScenarioTreeNode, state: ManagerState) -> TacticalNodeEvaluation:
        scenarios = self.scenarios_by_node.get(node.node_id)
        if scenarios is None:
            raise InfeasiblePolicyError(
                f"node {node.node_id} has no Stage-9 joint scenarios for Stage 10"
            )
        players = {
            item.player_id: CandidatePlayer(
                player_id=item.player_id,
                club_id=item.club_id,
                position=item.position,
                initial_selection_cost_tenths=node.prices[item.player_id].current_price_tenths,
            )
            for item in self.candidate_pool
        }
        squad = CandidateSquad(player_ids=state.squad_ids)
        tactics, tactical_upper = enumerate_tactical_configurations(
            squad,
            players,
            self.rules,
            self.policy,
        )
        best_plan = None
        best_objective = None
        tactics_evaluated = 0
        tied_optima = 0
        for tactic in tactics:
            tactics_evaluated += 1
            plan, objective = evaluate_tactical_configuration(
                squad,
                tactic,
                scenarios,
                players,
                self.rules,
            )
            if best_objective is None or objective > best_objective:
                best_plan = plan
                best_objective = objective
                tied_optima = 1
            elif objective == best_objective and best_plan is not None:
                tied_optima += 1
                if plan.signature < best_plan.signature:
                    best_plan = plan
        if best_plan is None:
            raise InfeasiblePolicyError(
                f"Stage-10 tactical layer found no legal plan at node {node.node_id}"
            )
        solver_status = SolverStatus(
            termination="OPTIMAL",
            search_scope=SearchScope.FIXED_SQUAD,
            guarantee=OptimalityGuarantee.EXACT_FIXED_SQUAD,
            squad_upper_bound=1,
            tactical_upper_bound=tactical_upper,
            scenario_operation_upper_bound=tactical_upper * len(scenarios),
            squad_candidates_evaluated=1,
            legal_squads_evaluated=1,
            tactical_configurations_evaluated=tactics_evaluated,
            scenario_operations_evaluated=tactics_evaluated * len(scenarios),
            objective_value=best_plan.expected_manager_points,
            best_bound=best_plan.expected_manager_points,
            absolute_gap=Decimal(0),
            relative_gap=Decimal(0),
            tied_optima_total=tied_optima,
            returned_ties=1,
            ties_truncated=tied_optima > 1,
        )
        best_plan = best_plan.model_copy(
            update={"solver_status": solver_status, "plan_sha256": "0" * 64}
        )
        plan_payload = best_plan.model_dump(mode="json")
        plan_payload["plan_sha256"] = None
        best_plan = best_plan.model_copy(update={"plan_sha256": semantic_sha256(plan_payload)})
        distribution = best_plan.point_distribution
        return TacticalNodeEvaluation(
            expected_points=best_plan.expected_manager_points,
            p10_points=Decimal(distribution.p10),
            p90_points=Decimal(distribution.p90),
            tactical_plan_sha256=best_plan.plan_sha256,
            tactical_plan=best_plan.model_dump(mode="json"),
            exact_stage10_evaluation=True,
            source="STAGE10_ADAPTER",
        )
