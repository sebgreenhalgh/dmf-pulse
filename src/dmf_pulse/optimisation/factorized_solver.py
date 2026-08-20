"""Exact preseason Stage-10 search with captain/scenario algebraic factorisation."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from itertools import permutations

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import GameweekPointScenario
from dmf_pulse.optimisation.autosub_evaluator import evaluate_base_scenario, weight_fraction
from dmf_pulse.optimisation.candidate_pool import enumerate_squads
from dmf_pulse.optimisation.errors import InfeasibleError, ResourceLimitError
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidateSquad,
    OneGameweekOptimisationRequest,
    OneGameweekOptimiserPolicy,
    OneGameweekPlan,
    OneGameweekRulesView,
    OptimalityGuarantee,
    SearchScope,
    SolverStatus,
    TacticalConfiguration,
)
from dmf_pulse.optimisation.tactics import (
    TacticalShape,
    enumerate_tactical_shapes,
    evaluate_tactical_configuration,
    tactical_configuration_upper_bound,
    tactical_shape_upper_bound,
)


def _guarantee(scope: SearchScope) -> OptimalityGuarantee:
    return {
        SearchScope.FIXED_SQUAD: OptimalityGuarantee.EXACT_FIXED_SQUAD,
        SearchScope.PROVIDED_SQUADS: OptimalityGuarantee.EXACT_PROVIDED_SET,
        SearchScope.BOUNDED_PLAYER_POOL: OptimalityGuarantee.EXACT_DECLARED_PLAYER_POOL,
    }[scope]


def _representative_squad(
    request: OneGameweekOptimisationRequest, rules: OneGameweekRulesView
) -> CandidateSquad:
    grouped = {
        position: [
            player for player in request.candidate_pool.players if player.position is position
        ]
        for position in rules.position_squad_quota
    }
    if any(
        len(grouped[position]) < rules.position_squad_quota[position]
        for position in rules.position_squad_quota
    ):
        raise InfeasibleError("declared player pool cannot satisfy compiled position quotas")
    return CandidateSquad(
        player_ids=tuple(
            sorted(
                player.player_id
                for position, quota in rules.position_squad_quota.items()
                for player in grouped[position][:quota]
            )
        )
    )


def _signature(squad: CandidateSquad, shape: TacticalShape, captain: str, vice_captain: str) -> str:
    return "|".join(
        (
            ",".join(sorted(squad.player_ids)),
            ",".join(sorted(shape.starting_xi)),
            shape.bench_goalkeeper,
            ",".join(shape.bench_order),
            captain,
            vice_captain,
        )
    )


def _captain_bonus_expectations(
    squad: CandidateSquad,
    scenarios: tuple[GameweekPointScenario, ...],
    weights: tuple[Fraction, ...],
    rules: OneGameweekRulesView,
) -> dict[tuple[str, str], Fraction]:
    multiplier = rules.captain_multiplier - 1
    output: dict[tuple[str, str], Fraction] = {}
    for captain, vice in permutations(squad.player_ids, 2):
        total = Fraction(0)
        for scenario, weight in zip(scenarios, weights, strict=True):
            if scenario.player_appeared[captain]:
                points = scenario.player_points[captain]
            elif rules.vice_captain_fallback and scenario.player_appeared[vice]:
                points = scenario.player_points[vice]
            else:
                points = 0
            total += weight * multiplier * points
        output[(captain, vice)] = total
    return output


def _base_expectation(
    shape: TacticalShape,
    scenarios: tuple[GameweekPointScenario, ...],
    weights: tuple[Fraction, ...],
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
) -> Fraction:
    player_order = tuple(sorted(players))
    counted_by_appearance: dict[tuple[bool, ...], tuple[str, ...]] = {}
    total = Fraction(0)
    for scenario, weight in zip(scenarios, weights, strict=True):
        appearance = tuple(scenario.player_appeared[player] for player in player_order)
        counted = counted_by_appearance.get(appearance)
        if counted is None:
            counted = evaluate_base_scenario(
                scenario,
                starting_xi=shape.starting_xi,
                bench_goalkeeper=shape.bench_goalkeeper,
                bench_order=shape.bench_order,
                players=players,
                rules=rules,
            ).counted_player_ids
            counted_by_appearance[appearance] = counted
        total += weight * sum(scenario.player_points[player] for player in counted)
    return total


def _preflight(
    request: OneGameweekOptimisationRequest,
    scenarios: tuple[GameweekPointScenario, ...],
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
    policy: OneGameweekOptimiserPolicy,
    squad_upper: int,
) -> SolverStatus:
    representative = _representative_squad(request, rules)
    tactic_per_squad = tactical_configuration_upper_bound(representative, players, rules)
    shape_per_squad = tactical_shape_upper_bound(representative, players, rules)
    captain_pairs_per_squad = rules.squad_size * (rules.squad_size - 1)
    tactical_upper = squad_upper * tactic_per_squad
    operation_upper = (
        squad_upper * (shape_per_squad + captain_pairs_per_squad) + policy.max_returned_ties
    ) * len(scenarios)
    status = SolverStatus(
        search_scope=request.search_scope,
        guarantee=OptimalityGuarantee.NONE,
        squad_upper_bound=squad_upper,
        tactical_upper_bound=tactical_upper,
        scenario_operation_upper_bound=operation_upper,
    )
    if tactical_upper > policy.max_tactical_configurations:
        raise ResourceLimitError(
            f"conservative tactical upper bound {tactical_upper} exceeds cap",
            solver_status=status,
        )
    if operation_upper > policy.max_scenario_score_operations:
        raise ResourceLimitError(
            f"factorized scenario operation upper bound {operation_upper} exceeds cap",
            solver_status=status,
        )
    return status


def solve_factorized_preseason(
    request: OneGameweekOptimisationRequest,
    scenarios: tuple[GameweekPointScenario, ...],
    rules: OneGameweekRulesView,
    policy: OneGameweekOptimiserPolicy,
) -> tuple[tuple[OneGameweekPlan, ...], Fraction, SolverStatus]:
    """Search every squad/tactic exactly while reusing captain expectations."""

    players = {candidate.player_id: candidate for candidate in request.candidate_pool.players}
    squads, squad_upper = enumerate_squads(request, rules, policy)
    preflight = _preflight(request, scenarios, players, rules, policy, squad_upper)
    weights = tuple(weight_fraction(scenario.weight) for scenario in scenarios)
    best: Fraction | None = None
    retained: dict[str, tuple[CandidateSquad, TacticalConfiguration]] = {}
    total_ties = 0
    squads_examined = 0
    tactics_examined = 0
    operations = 0
    for squad in squads:
        squads_examined += 1
        captain_bonus = _captain_bonus_expectations(squad, scenarios, weights, rules)
        operations += len(captain_bonus) * len(scenarios)
        for shape in enumerate_tactical_shapes(squad, players, rules):
            base = _base_expectation(shape, scenarios, weights, players, rules)
            operations += len(scenarios)
            for captain, vice in permutations(shape.starting_xi, 2):
                tactics_examined += 1
                objective = base + captain_bonus[(captain, vice)]
                signature = _signature(squad, shape, captain, vice)
                if best is None or objective > best:
                    best = objective
                    total_ties = 1
                    retained = {
                        signature: (
                            squad,
                            TacticalConfiguration(
                                starting_xi=shape.starting_xi,
                                bench_goalkeeper=shape.bench_goalkeeper,
                                bench_order=shape.bench_order,
                                captain=captain,
                                vice_captain=vice,
                            ),
                        )
                    }
                elif objective == best:
                    total_ties += 1
                    if len(retained) < policy.max_returned_ties or signature < max(retained):
                        retained[signature] = (
                            squad,
                            TacticalConfiguration(
                                starting_xi=shape.starting_xi,
                                bench_goalkeeper=shape.bench_goalkeeper,
                                bench_order=shape.bench_order,
                                captain=captain,
                                vice_captain=vice,
                            ),
                        )
                        if len(retained) > policy.max_returned_ties:
                            del retained[max(retained)]
    if best is None:
        raise InfeasibleError("declared search scope contains no legal plan")

    evaluated: list[OneGameweekPlan] = []
    for signature in sorted(retained):
        squad, tactic = retained[signature]
        plan, objective = evaluate_tactical_configuration(
            squad,
            tactic,
            scenarios,
            players,
            rules,
            search_scope=request.search_scope,
            report_budget=request.search_scope is SearchScope.BOUNDED_PLAYER_POOL,
        )
        operations += len(scenarios)
        if objective != best:
            raise InfeasibleError("factorized tactical objective failed exact reconciliation")
        evaluated.append(plan)
    first = evaluated[0]
    status = preflight.model_copy(
        update={
            "termination": "OPTIMAL",
            "guarantee": _guarantee(request.search_scope),
            "squad_candidates_evaluated": squads_examined,
            "legal_squads_evaluated": squads_examined,
            "tactical_configurations_evaluated": tactics_examined,
            "scenario_operations_evaluated": operations,
            "objective_value": first.expected_manager_points,
            "best_bound": first.expected_manager_points,
            "absolute_gap": Decimal(0),
            "relative_gap": Decimal(0),
            "tied_optima_total": total_ties,
            "returned_ties": len(evaluated),
            "ties_truncated": total_ties > len(evaluated),
        }
    )
    plans: list[OneGameweekPlan] = []
    for plan in evaluated:
        updated = plan.model_copy(update={"solver_status": status, "plan_sha256": "0" * 64})
        payload = updated.model_dump(mode="json")
        payload["plan_sha256"] = None
        plans.append(updated.model_copy(update={"plan_sha256": semantic_sha256(payload)}))
    return tuple(plans), best, status


__all__ = ["solve_factorized_preseason"]
