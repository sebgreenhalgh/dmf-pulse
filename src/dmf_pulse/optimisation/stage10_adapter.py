"""Explicit adapter from Stage 11 candidate squads to canonical Stage-10 tactics."""

from __future__ import annotations

from collections.abc import Callable, Mapping
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
    OneGameweekPlan,
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
    ExactTacticalNodeKernel,
    enumerate_tactical_configurations,
    evaluate_tactical_configuration,
    optimise_fixed_squad_tactics_exact,
    tactical_configuration_upper_bound,
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

    def _players(self, node: ScenarioTreeNode) -> dict[str, CandidatePlayer]:
        return {
            item.player_id: CandidatePlayer(
                player_id=item.player_id,
                club_id=item.club_id,
                position=item.position,
                initial_selection_cost_tenths=node.prices[item.player_id].current_price_tenths,
            )
            for item in self.candidate_pool
        }

    @staticmethod
    def _sealed_evaluation(
        *,
        best_plan: OneGameweekPlan,
        tactical_upper: int,
        tactics_evaluated: int,
        tied_optima: int,
        scenario_count: int,
    ) -> TacticalNodeEvaluation:
        solver_status = SolverStatus(
            termination="OPTIMAL",
            search_scope=SearchScope.FIXED_SQUAD,
            guarantee=OptimalityGuarantee.EXACT_FIXED_SQUAD,
            squad_upper_bound=1,
            tactical_upper_bound=tactical_upper,
            scenario_operation_upper_bound=tactical_upper * scenario_count,
            squad_candidates_evaluated=1,
            legal_squads_evaluated=1,
            tactical_configurations_evaluated=tactics_evaluated,
            scenario_operations_evaluated=tactics_evaluated * scenario_count,
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

    def evaluate(self, *, node: ScenarioTreeNode, state: ManagerState) -> TacticalNodeEvaluation:
        scenarios = self.scenarios_by_node.get(node.node_id)
        if scenarios is None:
            raise InfeasiblePolicyError(
                f"node {node.node_id} has no Stage-9 joint scenarios for Stage 10"
            )
        players = self._players(node)
        squad = CandidateSquad(player_ids=state.squad_ids)
        supplied_tactics, tactical_upper = enumerate_tactical_configurations(
            squad, players, self.rules, self.policy
        )
        canonical_upper = tactical_configuration_upper_bound(squad, players, self.rules)
        if tactical_upper == canonical_upper:
            try:
                best_plan, _best_objective, tactics_evaluated, tied_optima = (
                    optimise_fixed_squad_tactics_exact(
                        squad,
                        scenarios,
                        players,
                        self.rules,
                        self.policy,
                    )
                )
            except ValueError as exc:
                raise InfeasiblePolicyError(
                    f"Stage-10 tactical layer found no legal plan at node {node.node_id}"
                ) from exc
        else:
            # Preserve the explicit injected-enumerator seam used by contract tests and
            # downstream adapters. Normal canonical enumeration always takes the exact
            # factored path above.
            best_plan = None
            best_objective = None
            tactics_evaluated = 0
            tied_optima = 0
            for tactic in supplied_tactics:
                tactics_evaluated += 1
                plan, objective = evaluate_tactical_configuration(
                    squad, tactic, scenarios, players, self.rules
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
        if best_plan is None:  # pragma: no cover - guarded by both exact paths above
            raise InfeasiblePolicyError(
                f"Stage-10 tactical layer found no legal plan at node {node.node_id}"
            )
        return self._sealed_evaluation(
            best_plan=best_plan,
            tactical_upper=tactical_upper,
            tactics_evaluated=tactics_evaluated,
            tied_optima=tied_optima,
            scenario_count=len(scenarios),
        )

    def evaluate_many(
        self,
        *,
        node: ScenarioTreeNode,
        squads: tuple[CandidateSquad, ...],
        progress: Callable[[tuple[int, int]], None] | None = None,
    ) -> dict[tuple[str, ...], TacticalNodeEvaluation]:
        """Evaluate unique squads canonically through one exact node kernel."""

        scenarios = self.scenarios_by_node.get(node.node_id)
        if scenarios is None:
            raise InfeasiblePolicyError(
                f"node {node.node_id} has no Stage-9 joint scenarios for Stage 10"
            )
        players = self._players(node)
        kernel = ExactTacticalNodeKernel(scenarios=scenarios, players=players, rules=self.rules)
        unique = tuple(
            CandidateSquad(player_ids=player_ids)
            for player_ids in sorted({squad.player_ids for squad in squads})
        )
        results: dict[tuple[str, ...], TacticalNodeEvaluation] = {}
        total = len(unique)
        for completed, squad in enumerate(unique, start=1):
            tactical_upper = tactical_configuration_upper_bound(squad, players, self.rules)
            try:
                best_plan, _best_objective, tactics_evaluated, tied_optima = kernel.optimise(
                    squad, self.policy
                )
            except ValueError as exc:
                raise InfeasiblePolicyError(
                    f"Stage-10 tactical layer found no legal plan at node {node.node_id}"
                ) from exc
            results[squad.player_ids] = self._sealed_evaluation(
                best_plan=best_plan,
                tactical_upper=tactical_upper,
                tactics_evaluated=tactics_evaluated,
                tied_optima=tied_optima,
                scenario_count=len(scenarios),
            )
            if progress is not None:
                progress((completed, total))
        return results
