"""Dependency-free exact exhaustive search engine."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from dmf_pulse.fpl_points.models import GameweekPointScenario
from dmf_pulse.optimisation.candidate_pool import enumerate_squads
from dmf_pulse.optimisation.errors import InfeasibleError, ResourceLimitError
from dmf_pulse.optimisation.models import (
    OneGameweekOptimisationRequest,
    OneGameweekOptimiserPolicy,
    OneGameweekPlan,
    OneGameweekRulesView,
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
        for squad in candidates:
            tactical_upper = max(
                tactical_upper, tactical_configuration_upper_bound(squad, players, rules)
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
        tactical_upper = tactical_configuration_upper_bound(representative, players, rules)
    operation_upper = squad_upper * tactical_upper * len(scenarios)
    if operation_upper > policy.max_scenario_score_operations:
        raise ResourceLimitError(
            f"conservative scenario operation upper bound {operation_upper} exceeds cap"
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
                squad, tactic, scenarios, players, rules
            )
            if best is None or objective > best:
                best = objective
                ties = [plan]
                total_ties = 1
            elif objective == best:
                total_ties += 1
                if len(ties) < policy.max_returned_ties:
                    ties.append(plan)
    if best is None:
        raise InfeasibleError("declared search scope contains no legal plan")
    ties.sort(key=lambda plan: plan.signature)
    return SearchOutput(
        plans=tuple(ties[: policy.max_returned_ties]),
        objective=best,
        status=SolverStatus(
            squads_examined=squads_examined,
            tactical_configurations_examined=tactics_examined,
            scenario_score_operations=operations,
            conservative_squad_upper_bound=squad_upper,
            conservative_tactical_upper_bound=tactical_upper,
            conservative_operation_upper_bound=operation_upper,
            total_optimal_ties=total_ties,
        ),
    )
