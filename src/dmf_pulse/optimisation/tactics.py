"""Deterministic legal tactical configuration enumeration and scenario evaluation."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from itertools import combinations, permutations, product
from math import factorial

from dmf_pulse.fpl_points.models import GameweekPointScenario, PlayerPosition
from dmf_pulse.optimisation.autosub_evaluator import evaluate_scenario
from dmf_pulse.optimisation.errors import ResourceLimitError
from dmf_pulse.optimisation.legality import validate_tactical_configuration
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidateSquad,
    OneGameweekOptimiserPolicy,
    OneGameweekPlan,
    OneGameweekRulesView,
    PointDistributionSummary,
    PointMass,
    ScenarioManagerScore,
    TacticalConfiguration,
)

CANONICAL_DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


def _quantile(masses: dict[int, Fraction], probability: Fraction) -> int:
    accumulated = Fraction(0)
    for points, mass in sorted(masses.items()):
        accumulated += mass
        if accumulated >= probability:
            return points
    raise ValueError("point-mass probabilities must be positive")


def _players_by_position(
    squad: CandidateSquad, players: dict[str, CandidatePlayer]
) -> dict[PlayerPosition, tuple[str, ...]]:
    return {
        position: tuple(
            sorted(player for player in squad.player_ids if players[player].position is position)
        )
        for position in PlayerPosition
    }


def tactical_configuration_upper_bound(
    squad: CandidateSquad, players: dict[str, CandidatePlayer], rules: OneGameweekRulesView
) -> int:
    grouped = _players_by_position(squad, players)
    outfield_bench = rules.bench_size - 1
    bench_orders = factorial(outfield_bench)
    captain_pairs = rules.starting_size * (rules.starting_size - 1)
    formations = 0
    for gk_choice in combinations(grouped[PlayerPosition.GK], rules.lineup_max[PlayerPosition.GK]):
        del gk_choice
        for d in range(
            rules.lineup_min[PlayerPosition.DEF],
            min(rules.lineup_max[PlayerPosition.DEF], len(grouped[PlayerPosition.DEF])) + 1,
        ):
            for m in range(
                rules.lineup_min[PlayerPosition.MID],
                min(rules.lineup_max[PlayerPosition.MID], len(grouped[PlayerPosition.MID])) + 1,
            ):
                for f in range(
                    rules.lineup_min[PlayerPosition.FWD],
                    min(rules.lineup_max[PlayerPosition.FWD], len(grouped[PlayerPosition.FWD])) + 1,
                ):
                    if d + m + f + 1 == rules.starting_size:
                        formations += (
                            factorial(len(grouped[PlayerPosition.DEF]))
                            // (factorial(d) * factorial(len(grouped[PlayerPosition.DEF]) - d))
                            * factorial(len(grouped[PlayerPosition.MID]))
                            // (factorial(m) * factorial(len(grouped[PlayerPosition.MID]) - m))
                            * factorial(len(grouped[PlayerPosition.FWD]))
                            // (factorial(f) * factorial(len(grouped[PlayerPosition.FWD]) - f))
                        )
    return formations * bench_orders * captain_pairs


def enumerate_tactical_configurations(
    squad: CandidateSquad,
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
    policy: OneGameweekOptimiserPolicy,
) -> tuple[Iterator[TacticalConfiguration], int]:
    upper = tactical_configuration_upper_bound(squad, players, rules)
    if upper > policy.max_tactical_configurations:
        raise ResourceLimitError(f"conservative tactical upper bound {upper} exceeds cap")
    grouped = _players_by_position(squad, players)
    gk = grouped[PlayerPosition.GK]
    outfield = {
        position: grouped[position]
        for position in (PlayerPosition.DEF, PlayerPosition.MID, PlayerPosition.FWD)
    }

    def generator() -> Iterator[TacticalConfiguration]:
        for bench_gk in gk:
            starting_gk = next(player for player in gk if player != bench_gk)
            for d_count in range(
                rules.lineup_min[PlayerPosition.DEF], rules.lineup_max[PlayerPosition.DEF] + 1
            ):
                for m_count in range(
                    rules.lineup_min[PlayerPosition.MID], rules.lineup_max[PlayerPosition.MID] + 1
                ):
                    f_count = rules.starting_size - 1 - d_count - m_count
                    if (
                        f_count < rules.lineup_min[PlayerPosition.FWD]
                        or f_count > rules.lineup_max[PlayerPosition.FWD]
                    ):
                        continue
                    for defenders, mids, fwds in product(
                        combinations(outfield[PlayerPosition.DEF], d_count),
                        combinations(outfield[PlayerPosition.MID], m_count),
                        combinations(outfield[PlayerPosition.FWD], f_count),
                    ):
                        selected = (starting_gk, *defenders, *mids, *fwds)
                        bench_outfield = tuple(
                            sorted(set(squad.player_ids) - set(selected) - {bench_gk})
                        )
                        for bench_order in permutations(bench_outfield):
                            for captain, vice in permutations(selected, 2):
                                tactic = TacticalConfiguration(
                                    starting_xi=selected,
                                    bench_goalkeeper=bench_gk,
                                    outfield_bench_order=bench_order,
                                    captain=captain,
                                    vice_captain=vice,
                                )
                                if validate_tactical_configuration(
                                    squad, tactic, players, rules
                                ).legal:
                                    yield tactic

    return generator(), upper


def evaluate_tactical_configuration(
    squad: CandidateSquad,
    tactic: TacticalConfiguration,
    scenarios: tuple[GameweekPointScenario, ...],
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
) -> tuple[OneGameweekPlan, Fraction]:
    report = validate_tactical_configuration(squad, tactic, players, rules)
    if not report.legal:
        raise ValueError("cannot evaluate an illegal tactical configuration")
    scores: list[ScenarioManagerScore] = []
    total = Fraction(0)
    for scenario in scenarios:
        score, weighted = evaluate_scenario(scenario, tactic, players, rules)
        scores.append(score)
        total += weighted
    masses_by_points: dict[int, Fraction] = {}
    for score in scores:
        masses_by_points[score.manager_points] = masses_by_points.get(
            score.manager_points, Fraction(0)
        ) + Fraction(Decimal(score.weight_token))
    total_weight = sum(masses_by_points.values(), Fraction(0))
    if total_weight <= 0:
        raise ValueError("scenario weights must sum to a positive value")
    normalized_masses = {
        points: probability / total_weight for points, probability in masses_by_points.items()
    }
    fallback = (
        sum(
            Fraction(Decimal(score.weight_token))
            for score in scores
            if score.captain_resolution.multiplier_player == tactic.vice_captain
        )
        / total_weight
    )
    captain_and_vice_failure = (
        sum(
            Fraction(Decimal(score.weight_token))
            for score in scores
            if score.captain_resolution.multiplier_player is None
        )
        / total_weight
    )
    field_11 = (
        sum(
            Fraction(Decimal(score.weight_token))
            for score in scores
            if len(score.player_points) == rules.starting_size
        )
        / total_weight
    )
    expected_bench = (
        sum(
            Fraction(Decimal(score.weight_token))
            * sum(
                scenario.player_points[event.player_in]
                for event in score.autosub_events
                for scenario in scenarios
                if scenario.scenario_id == score.scenario_id
            )
            for score in scores
        )
        / total_weight
    )
    expectation = total / total_weight
    manager_values = tuple(score.manager_points for score in scores)
    manager_weights = tuple(
        Fraction(Decimal(score.weight_token)) / total_weight for score in scores
    )
    variance = sum(
        weight * (value - expectation) ** 2
        for value, weight in zip(manager_values, manager_weights, strict=True)
    )
    with localcontext(CANONICAL_DECIMAL_CONTEXT):
        masses = tuple(
            PointMass(
                points=points,
                probability=Decimal(prob.numerator) / Decimal(prob.denominator),
            )
            for points, prob in sorted(normalized_masses.items())
        )
        expected = Decimal(expectation.numerator) / Decimal(expectation.denominator)
        distribution = PointDistributionSummary(
            expected_points=expected,
            minimum_points=min(normalized_masses),
            maximum_points=max(normalized_masses),
            masses=masses,
            p10=_quantile(normalized_masses, Fraction(1, 10)),
            median=_quantile(normalized_masses, Fraction(1, 2)),
            p90=_quantile(normalized_masses, Fraction(9, 10)),
            probability_field_11=Decimal(field_11.numerator) / Decimal(field_11.denominator),
            probability_field_10_or_fewer=Decimal(1)
            - Decimal(field_11.numerator) / Decimal(field_11.denominator),
            captain_fallback_probability=Decimal(fallback.numerator)
            / Decimal(fallback.denominator),
            captain_and_vice_failure_probability=(
                Decimal(captain_and_vice_failure.numerator)
                / Decimal(captain_and_vice_failure.denominator)
            ),
            expected_bench_contribution=(
                Decimal(expected_bench.numerator) / Decimal(expected_bench.denominator)
            ),
            component_means={"manager_points": expected},
            component_covariance={
                "manager_points": {
                    "manager_points": Decimal(variance.numerator) / Decimal(variance.denominator)
                }
            },
        )
    signature = "|".join(
        (
            ",".join(sorted(squad.player_ids)),
            ",".join(sorted(tactic.starting_xi)),
            tactic.bench_goalkeeper,
            ",".join(tactic.outfield_bench_order),
            tactic.captain,
            tactic.vice_captain,
        )
    )
    plan = OneGameweekPlan(
        candidate_squad=squad,
        tactical_configuration=tactic,
        scenario_scores=tuple(scores),
        distribution=distribution,
        expected_manager_points=expected,
        initial_selection_cost_tenths=squad.initial_selection_cost_tenths,
        budget_tenths=rules.initial_budget_tenths
        if squad.initial_selection_cost_tenths is not None
        else None,
        signature=signature,
        legality_report=report,
    )
    return plan, total
