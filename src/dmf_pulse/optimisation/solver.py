"""Dependency-free exact exhaustive search engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import GameweekPointScenario
from dmf_pulse.optimisation.candidate_pool import enumerate_squads
from dmf_pulse.optimisation.errors import InfeasibleError, ResourceLimitError
from dmf_pulse.optimisation.models import (
    OneGameweekOptimisationRequest,
    OneGameweekOptimiserPolicy,
    OneGameweekPlan,
    OneGameweekRulesView,
    OptimalityGuarantee,
    SearchScope,
    SolverStatus,
)
from dmf_pulse.optimisation.tactics import (
    enumerate_tactical_configurations,
    evaluate_tactical_configuration,
    tactical_configuration_upper_bound,
)


@dataclass(frozen=True)
class SearchOutput:
    plans: tuple[OneGameweekPlan, ...]
    objective: Fraction | None
    status: SolverStatus


def _guarantee(scope: SearchScope) -> OptimalityGuarantee:
    return {
        SearchScope.FIXED_SQUAD: OptimalityGuarantee.EXACT_FIXED_SQUAD,
        SearchScope.PROVIDED_SQUADS: OptimalityGuarantee.EXACT_PROVIDED_SET,
        SearchScope.BOUNDED_PLAYER_POOL: OptimalityGuarantee.EXACT_DECLARED_PLAYER_POOL,
    }[scope]


def solve(
    request: OneGameweekOptimisationRequest,
    scenarios: tuple[GameweekPointScenario, ...],
    rules: OneGameweekRulesView,
    policy: OneGameweekOptimiserPolicy,
) -> SearchOutput:
    players = {candidate.player_id: candidate for candidate in request.candidate_pool.candidates}
    squads, squad_upper = enumerate_squads(request, rules, policy)
    tactical_upper = 0
    if request.search_scope.value != "BOUNDED_PLAYER_POOL":
        candidates = list(squads)
        squads = iter(candidates)
        tactical_upper = sum(
            tactical_configuration_upper_bound(squad, players, rules) for squad in candidates
        )
    else:
        # Shape-only preflight uses one complete legal squad shape, independent of player IDs.
        grouped = {
            position: [p for p in request.candidate_pool.candidates if p.position is position]
            for position in rules.position_squad_quota
        }
        if any(
            len(grouped[position]) < rules.position_squad_quota[position]
            for position in rules.position_squad_quota
        ):
            raise InfeasibleError("declared player pool cannot satisfy compiled position quotas")
        representative_ids = tuple(
            sorted(
                p.player_id
                for position, quota in rules.position_squad_quota.items()
                for p in grouped[position][:quota]
            )
        )
        from dmf_pulse.optimisation.models import CandidateSquad

        representative = CandidateSquad(player_ids=representative_ids)
        tactical_upper = squad_upper * tactical_configuration_upper_bound(
            representative, players, rules
        )
    operation_upper = tactical_upper * len(scenarios)
    preflight = SolverStatus(
        search_scope=request.search_scope,
        guarantee=OptimalityGuarantee.NONE,
        squad_upper_bound=squad_upper,
        tactical_upper_bound=tactical_upper,
        scenario_operation_upper_bound=operation_upper,
    )
    if tactical_upper > policy.max_tactical_configurations:
        raise ResourceLimitError(
            f"conservative tactical upper bound {tactical_upper} exceeds cap",
            solver_status=preflight,
        )
    if operation_upper > policy.max_scenario_score_operations:
        raise ResourceLimitError(
            f"conservative scenario operation upper bound {operation_upper} exceeds cap",
            solver_status=preflight,
        )
    best: Fraction | None = None
    ties: list[OneGameweekPlan] = []
    total_ties = 0
    squads_examined = 0
    tactics_examined = 0
    operations = 0
    for squad in squads:
        squads_examined += 1
        tactics, _ = enumerate_tactical_configurations(squad, players, rules, policy)
        for tactic in tactics:
            tactics_examined += 1
            operations += len(scenarios)
            plan, objective = evaluate_tactical_configuration(
                squad,
                tactic,
                scenarios,
                players,
                rules,
                search_scope=request.search_scope,
                report_budget=request.search_scope is SearchScope.BOUNDED_PLAYER_POOL,
            )
            if best is None or objective > best:
                best = objective
                ties = [plan]
                total_ties = 1
            elif objective == best:
                total_ties += 1
                if len(ties) < policy.max_returned_ties:
                    ties.append(plan)
                else:
                    largest = max(range(len(ties)), key=lambda index: ties[index].signature)
                    if plan.signature < ties[largest].signature:
                        ties[largest] = plan
    if best is None:
        raise InfeasibleError("declared search scope contains no legal plan")
    ties.sort(key=lambda plan: plan.signature)
    status = SolverStatus(
        termination="OPTIMAL",
        search_scope=request.search_scope,
        guarantee=_guarantee(request.search_scope),
        squad_upper_bound=squad_upper,
        tactical_upper_bound=tactical_upper,
        scenario_operation_upper_bound=operation_upper,
        squad_candidates_evaluated=squads_examined,
        legal_squads_evaluated=squads_examined,
        tactical_configurations_evaluated=tactics_examined,
        scenario_operations_evaluated=operations,
        tied_optima_total=total_ties,
        returned_ties=len(ties[: policy.max_returned_ties]),
        ties_truncated=total_ties > policy.max_returned_ties,
        objective_value=ties[0].expected_manager_points,
        best_bound=ties[0].expected_manager_points,
        absolute_gap=Decimal(0),
        relative_gap=Decimal(0),
    )
    final_plans: list[OneGameweekPlan] = []
    for plan in ties[: policy.max_returned_ties]:
        updated = plan.model_copy(update={"solver_status": status, "plan_sha256": "0" * 64})
        payload = updated.model_dump(mode="json")
        payload["plan_sha256"] = None
        final_plans.append(updated.model_copy(update={"plan_sha256": semantic_sha256(payload)}))
    return SearchOutput(plans=tuple(final_plans), objective=best, status=status)
