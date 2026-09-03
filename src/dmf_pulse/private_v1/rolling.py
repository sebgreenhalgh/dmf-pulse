"""Explicit three-Gameweek private integration over the accepted Stage-11 engine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from time import perf_counter

from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.gameweek import assemble_gameweek
from dmf_pulse.fpl_points.gameweek_summaries import build_gameweek_projection
from dmf_pulse.fpl_points.models import GameweekProjectionResult, GameweekScenarioSet
from dmf_pulse.fpl_points.player_prior import load_packaged_player_prior
from dmf_pulse.optimisation.models import CandidatePlayer
from dmf_pulse.optimisation.multi_gameweek_models import (
    BackendStatus,
    HorizonTransferCountFrontier,
    MultiGameweekOptimisationRequest,
    MultiGameweekOptimisationResult,
    MultiGameweekPlan,
    MultiGameweekResultStatus,
    NodeDecision,
)
from dmf_pulse.optimisation.multi_gameweek_policy import load_terminal_value_policy
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.optimisation.multi_gameweek_solver import resolve_free_transfer_arc
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import PrivateGainMass, PrivateTransferMove
from dmf_pulse.private_v1.progress import NullProgress, ProgressSink
from dmf_pulse.private_v1.rolling_models import (
    PrivateOneGameweekVersusRollingComparison,
    PrivateRollingDecisionLineage,
    PrivateRollingFixtureCoverage,
    PrivateRollingFrontier,
    PrivateRollingFrontierPoint,
    PrivateRollingFutureActionSummary,
    PrivateRollingGameweekDecision,
    PrivateRollingHorizonComparison,
    PrivateV1RollingDecision,
    PrivateV1RollingExecutionInput,
    seal_rolling_decision,
    seal_rolling_frontier,
    seal_rolling_frontier_point,
    seal_rolling_horizon_comparison,
)
from dmf_pulse.private_v1.service import (
    _action_space_disclosure,
    _current_identity_maps,
    _decimal,
    _MemoizedStage10Evaluator,
    _parse_tactical_plan,
    _private_free_transfer_state,
    _private_transfer_moves,
    _project_fixtures,
    _quantile,
    _stage11_request,
    _tactical_decision,
    _verify_captain,
    _verify_current_sources,
    _verify_runtime_artifacts,
)


@dataclass(frozen=True, slots=True)
class PrivateRollingStageTiming:
    stage: str
    elapsed_ms: Decimal


@dataclass(frozen=True)
class PrivateV1RollingRunResult:
    decision: PrivateV1RollingDecision
    report: str
    gameweek_projections: tuple[
        GameweekProjectionResult,
        GameweekProjectionResult,
        GameweekProjectionResult,
    ]
    optimiser_result: MultiGameweekOptimisationResult
    optimiser_request: MultiGameweekOptimisationRequest
    one_gameweek_optimiser_result: MultiGameweekOptimisationResult
    stage_timings: tuple[PrivateRollingStageTiming, ...]


def _coverage(
    value: PrivateV1RollingExecutionInput,
    gameweek: int,
) -> PrivateRollingFixtureCoverage:
    current = value.current_execution
    if gameweek == current.current_state.target_gameweek:
        current_fixtures = current.market_constraints.fixtures
        fixture_count = len(current_fixtures)
        backed = sum(bool(item.constraint_set.constraints) for item in current_fixtures)
        prior_only = fixture_count - backed
        blocked = 0
    else:
        future = next(item for item in value.future_gameweeks if item.gameweek == gameweek)
        backed = sum(item.market_mode == "MARKET_BACKED" for item in future.fixtures)
        prior_only = sum(item.market_mode == "SCORE_PRIOR_ONLY" for item in future.fixtures)
        blocked = sum(item.market_mode == "BLOCKED" for item in future.fixtures)
        fixture_count = len(future.fixtures)
    return PrivateRollingFixtureCoverage(
        fixtures_total=fixture_count,
        market_backed_fixtures=backed,
        score_prior_only_fixtures=prior_only,
        blocked_fixtures=blocked,
    )


def _gameweek_limitations(
    value: PrivateV1RollingExecutionInput,
    gameweek: int,
) -> tuple[str, ...]:
    if gameweek == value.horizon_gameweeks[0]:
        return tuple(
            sorted(set(value.current_execution.market_constraints.source_quality_warnings))
        )
    future = next(item for item in value.future_gameweeks if item.gameweek == gameweek)
    warnings = {warning for fixture in future.fixtures for warning in fixture.warnings}
    if any(item.market_mode == "SCORE_PRIOR_ONLY" for item in future.fixtures):
        warnings.add("FUTURE_FIXTURE_SCORE_PRIOR_ONLY_NO_CURRENT_MARKET")
    warnings.add("CROSS_GAMEWEEK_READINESS_AND_INJURY_TRANSITIONS_NOT_MODELLED")
    return tuple(sorted(warnings))


def _build_gameweek_decision(
    decision: NodeDecision,
    *,
    execution: PrivateV1RollingExecutionInput,
    request: MultiGameweekOptimisationRequest,
    scenarios: GameweekScenarioSet,
    candidates: dict[str, CandidatePlayer],
    tactical: _MemoizedStage10Evaluator,
    element_by_player: dict[str, int],
    actionable: bool,
) -> PrivateRollingGameweekDecision:
    plan = _parse_tactical_plan(decision.tactical_evaluation.tactical_plan)
    captain_hash = _verify_captain(
        plan,
        scenarios=scenarios,
        candidates=candidates,
        tactical=tactical,
    )
    arc = resolve_free_transfer_arc(
        request.rules,
        event=decision.action.transition_event,
        ft_before=decision.free_transfers_before,
        transfer_count=decision.action.transfer_count,
    )
    if (
        arc.ft_after != decision.free_transfers_after
        or arc.hit_points != decision.hit_points
        or arc.paid_transfers != decision.paid_transfers
    ):
        raise PrivateV1Error(
            "ROLLING_FT_TRANSITION_MISMATCH",
            "rolling FT disclosure differs from the accepted Stage-11 transition",
        )
    return PrivateRollingGameweekDecision(
        gameweek=decision.gameweek,
        actionability=("DO_NOW" if actionable else "PROVISIONAL_REOPTIMISE_AT_DEADLINE"),
        transfers=_private_transfer_moves(
            decision.action,
            candidate_pool=request.candidate_pool,
            element_by_player=element_by_player,
        ),
        transfer_count=decision.action.transfer_count,
        hit_points=decision.hit_points,
        free_transfer_state=_private_free_transfer_state(
            arc,
            manager_state_before=decision.free_transfers_before,
        ),
        bank_after_tenths=decision.bank_after_tenths,
        squad_after=decision.squad_after,
        tactics=_tactical_decision(plan, captain_hash),
        expected_manager_points_before_hit=decision.tactical_evaluation.expected_points,
        expected_manager_points_after_hit=(
            decision.tactical_evaluation.expected_points - Decimal(decision.hit_points)
        ),
        fixture_coverage=_coverage(execution, decision.gameweek),
        limitations=_gameweek_limitations(execution, decision.gameweek),
        tactical_plan_sha256=decision.tactical_evaluation.tactical_plan_sha256,
    )


def _node_gain_distribution(
    plan: NodeDecision,
    baseline: NodeDecision,
    scenarios: GameweekScenarioSet,
) -> tuple[dict[int, Fraction], int]:
    plan_tactics = _parse_tactical_plan(plan.tactical_evaluation.tactical_plan)
    baseline_tactics = _parse_tactical_plan(baseline.tactical_evaluation.tactical_plan)
    plan_scores = {
        (item.scenario_id, item.outcome_draw_id): item.manager_points
        for item in plan_tactics.scenario_scores
    }
    baseline_scores = {
        (item.scenario_id, item.outcome_draw_id): item.manager_points
        for item in baseline_tactics.scenario_scores
    }
    weights = {
        (item.scenario_id, item.outcome_draw_id): Fraction(str(item.weight))
        for item in scenarios.scenarios
    }
    if plan_scores.keys() != baseline_scores.keys() or plan_scores.keys() != weights.keys():
        raise PrivateV1Error(
            "ROLLING_COMPARATOR_SCENARIO_MISMATCH",
            "rolling plan and baseline do not share the exact Stage-9 scenarios",
        )
    total = sum(weights.values(), Fraction(0))
    if total <= 0:
        raise PrivateV1Error("ROLLING_COMPARATOR_INVALID", "scenario weights are invalid")
    masses: dict[int, Fraction] = {}
    hit_difference = plan.hit_points - baseline.hit_points
    for key, weight in weights.items():
        gain = plan_scores[key] - baseline_scores[key] - hit_difference
        masses[gain] = masses.get(gain, Fraction(0)) + weight / total
    return masses, len(weights)


def _convolve(left: dict[int, Fraction], right: dict[int, Fraction]) -> dict[int, Fraction]:
    result: dict[int, Fraction] = {}
    for left_points, left_mass in left.items():
        for right_points, right_mass in right.items():
            total = left_points + right_points
            result[total] = result.get(total, Fraction(0)) + left_mass * right_mass
    return result


def _horizon_comparison(
    plan: MultiGameweekPlan,
    baseline: MultiGameweekPlan,
    *,
    scenarios_by_gameweek: dict[int, GameweekScenarioSet],
) -> PrivateRollingHorizonComparison:
    plan_decisions = {item.gameweek: item for item in (plan.current_action, *plan.future_policy)}
    baseline_decisions = {
        item.gameweek: item for item in (baseline.current_action, *baseline.future_policy)
    }
    if set(plan_decisions) != set(baseline_decisions) or set(plan_decisions) != set(
        scenarios_by_gameweek
    ):
        raise PrivateV1Error(
            "ROLLING_COMPARATOR_HORIZON_MISMATCH",
            "rolling plan, baseline and horizon Gameweeks differ",
        )
    masses = {0: Fraction(1)}
    path_count = 1
    for gameweek in sorted(plan_decisions):
        node_masses, scenario_count = _node_gain_distribution(
            plan_decisions[gameweek],
            baseline_decisions[gameweek],
            scenarios_by_gameweek[gameweek],
        )
        masses = _convolve(masses, node_masses)
        path_count *= scenario_count
    expected_gain = sum((Fraction(points) * mass for points, mass in masses.items()), Fraction(0))
    objective_gain = (
        plan.utility.expected_horizon_utility - baseline.utility.expected_horizon_utility
    )
    if _decimal(expected_gain) != objective_gain:
        raise PrivateV1Error(
            "ROLLING_COMPARATOR_OBJECTIVE_MISMATCH",
            "paired rolling distribution differs from the Stage-11 expected objective",
        )
    return seal_rolling_horizon_comparison(
        PrivateRollingHorizonComparison.model_construct(
            cross_gameweek_scenario_mode=(
                "INDEPENDENT_GAMEWEEK_SCENARIO_PRODUCT_NO_INFORMATION_REVELATION_V1"
            ),
            joint_scenario_path_count=path_count,
            plan_expected_horizon_utility=plan.utility.expected_horizon_utility,
            baseline_expected_horizon_utility=baseline.utility.expected_horizon_utility,
            expected_uplift=objective_gain,
            gain_p10=_quantile(masses, Fraction(1, 10)),
            gain_median=_quantile(masses, Fraction(1, 2)),
            gain_p90=_quantile(masses, Fraction(9, 10)),
            probability_plan_beats_baseline=_decimal(
                sum((mass for points, mass in masses.items() if points > 0), Fraction(0))
            ),
            probability_gain_at_least_four=_decimal(
                sum((mass for points, mass in masses.items() if points >= 4), Fraction(0))
            ),
            probability_loss_at_least_four=_decimal(
                sum((mass for points, mass in masses.items() if points <= -4), Fraction(0))
            ),
            gain_pmf=tuple(
                PrivateGainMass(points=points, probability=_decimal(mass))
                for points, mass in sorted(masses.items())
            ),
            semantic_sha256="0" * 64,
        )
    )


def _future_summary(
    plan: MultiGameweekPlan,
    *,
    request: MultiGameweekOptimisationRequest,
    element_by_player: dict[str, int],
) -> tuple[PrivateRollingFutureActionSummary, ...]:
    values = []
    for item in plan.future_policy:
        values.append(
            PrivateRollingFutureActionSummary(
                gameweek=item.gameweek,
                status="PROVISIONAL_REOPTIMISE_AT_DEADLINE",
                transfers=_private_transfer_moves(
                    item.action,
                    candidate_pool=request.candidate_pool,
                    element_by_player=element_by_player,
                ),
                hit_points=item.hit_points,
                free_transfers_entering=item.free_transfers_before,
                free_transfers_at_next_deadline=item.free_transfers_after,
                bank_after_tenths=item.bank_after_tenths,
            )
        )
    return tuple(values)


def _rolling_frontier(
    optimiser: MultiGameweekOptimisationResult,
    *,
    request: MultiGameweekOptimisationRequest,
    baseline: MultiGameweekPlan,
    scenarios_by_gameweek: dict[int, GameweekScenarioSet],
    element_by_player: dict[str, int],
    action_space_disclosure: str,
    candidate_policy_sha256: str,
) -> PrivateRollingFrontier:
    source = optimiser.transfer_count_frontier
    if not isinstance(source, HorizonTransferCountFrontier):
        raise PrivateV1Error(
            "ROLLING_FRONTIER_UNAVAILABLE",
            "Stage 11 omitted the expected horizon-valued transfer-count frontier",
        )
    baseline_immediate = baseline.current_action.tactical_evaluation.expected_points - Decimal(
        baseline.current_action.hit_points
    )
    points = []
    for item in source.points:
        plan = item.plan
        comparison = _horizon_comparison(
            plan,
            baseline,
            scenarios_by_gameweek=scenarios_by_gameweek,
        )
        root = plan.current_action
        points.append(
            seal_rolling_frontier_point(
                PrivateRollingFrontierPoint.model_construct(
                    transfer_count=item.transfer_count,
                    action_signature=root.action.signature,
                    transfers=_private_transfer_moves(
                        root.action,
                        candidate_pool=request.candidate_pool,
                        element_by_player=element_by_player,
                    ),
                    immediate_expected_points_after_hit=item.current_gameweek_objective,
                    expected_horizon_utility=item.expected_horizon_utility,
                    immediate_uplift_vs_hold=(item.current_gameweek_objective - baseline_immediate),
                    horizon_uplift_vs_hold=comparison.expected_uplift,
                    free_transfers_entering_next_gameweek=root.free_transfers_after,
                    bank_after_tenths=root.bank_after_tenths,
                    paired_horizon_comparison=comparison,
                    planned_future_policy=_future_summary(
                        plan,
                        request=request,
                        element_by_player=element_by_player,
                    ),
                    stage11_plan_sha256=plan.plan_sha256,
                    semantic_sha256="0" * 64,
                )
            )
        )
    return seal_rolling_frontier(
        PrivateRollingFrontier.model_construct(
            objective="EXPECTED_THREE_GAMEWEEK_POINTS_WITH_LEGAL_RECOURSE",
            points=tuple(points),
            action_space_disclosure=action_space_disclosure,
            optimiser_request_sha256=request.request_sha256,
            optimiser_result_sha256=optimiser.result_sha256,
            candidate_action_policy_sha256=candidate_policy_sha256,
            semantic_sha256="0" * 64,
        )
    )


def _one_gameweek_comparison(
    one_gameweek: MultiGameweekPlan,
    rolling: MultiGameweekPlan,
    frontier: PrivateRollingFrontier,
    source_frontier: HorizonTransferCountFrontier,
    *,
    request: MultiGameweekOptimisationRequest,
    element_by_player: dict[str, int],
) -> PrivateOneGameweekVersusRollingComparison:
    transfer_count = one_gameweek.current_action.action.transfer_count
    counter_source = next(
        item.plan for item in source_frontier.points if item.transfer_count == transfer_count
    )
    counter_private = next(
        item for item in frontier.points if item.transfer_count == transfer_count
    )
    rolling_utility = rolling.utility
    counter_utility = counter_source.utility
    return PrivateOneGameweekVersusRollingComparison(
        actions_differ=(
            one_gameweek.current_action.action.signature != rolling.current_action.action.signature
        ),
        one_gameweek_action_signature=one_gameweek.current_action.action.signature,
        three_gameweek_action_signature=rolling.current_action.action.signature,
        one_gameweek_transfers=_private_transfer_moves(
            one_gameweek.current_action.action,
            candidate_pool=request.candidate_pool,
            element_by_player=element_by_player,
        ),
        three_gameweek_transfers=_private_transfer_moves(
            rolling.current_action.action,
            candidate_pool=request.candidate_pool,
            element_by_player=element_by_player,
        ),
        counterfactual_basis="THREE_GAMEWEEK_FRONTIER_AT_ONE_GAMEWEEK_TRANSFER_COUNT",
        counterfactual_action_matches_one_gameweek_action=(
            counter_private.action_signature == one_gameweek.current_action.action.signature
        ),
        current_gameweek_points_difference=(
            rolling_utility.current_gameweek_contribution
            - counter_utility.current_gameweek_contribution
        ),
        future_gameweek_points_difference=(
            rolling_utility.future_contribution - counter_utility.future_contribution
        ),
        expected_hit_cost_difference=(
            rolling_utility.expected_hit_cost - counter_utility.expected_hit_cost
        ),
        terminal_contribution_difference=(
            rolling_utility.terminal_flexibility_contribution
            - counter_utility.terminal_flexibility_contribution
        ),
        total_horizon_utility_difference=(
            rolling_utility.expected_horizon_utility - counter_utility.expected_horizon_utility
        ),
        free_transfers_entering_next_difference=(
            rolling.current_action.free_transfers_after
            - counter_source.current_action.free_transfers_after
        ),
    )


def render_rolling_report(
    decision: PrivateV1RollingDecision,
    *,
    label: Callable[[str], str] | None = None,
) -> str:
    """Render only fields already present in the sealed rolling decision."""

    player_label = label or (lambda player_id: player_id)

    def move_list(transfers: tuple[PrivateTransferMove, ...]) -> str:
        if not transfers:
            return "NO TRANSFER"
        return ", ".join(
            f"{player_label(move.player_out_id)} -> {player_label(move.player_in_id)}"
            for move in transfers
        )

    def moves(item: PrivateRollingGameweekDecision) -> str:
        return move_list(item.transfers)

    def bench(item: PrivateRollingGameweekDecision) -> str:
        return ", ".join(
            player_label(player_id)
            for player_id in (
                item.tactics.bench_goalkeeper,
                *item.tactics.bench_outfield_order,
            )
        )

    def future_policy(item: PrivateRollingFrontierPoint) -> str:
        return " | ".join(
            (
                f"GW{future.gameweek} {move_list(future.transfers)}; "
                f"hit=-{future.hit_points}; FT next={future.free_transfers_at_next_deadline}"
            )
            for future in item.planned_future_policy
        )

    def frontier_line(item: PrivateRollingFrontierPoint) -> str:
        paired = item.paired_horizon_comparison
        return (
            f"{item.transfer_count} transfer(s): {move_list(item.transfers)}; "
            f"immediate={item.immediate_expected_points_after_hit:.2f}; "
            f"immediate uplift={item.immediate_uplift_vs_hold:+.2f}; "
            f"3-GW={item.expected_horizon_utility:.2f}; "
            f"3-GW uplift={item.horizon_uplift_vs_hold:+.2f}; "
            f"gain p10/median/p90={paired.gain_p10}/{paired.gain_median}/{paired.gain_p90}; "
            f"P(beat hold)={paired.probability_plan_beats_baseline:.1%}; "
            f"FT next={item.free_transfers_entering_next_gameweek}; "
            f"bank={item.bank_after_tenths}; future=[{future_policy(item)}]"
        )

    lines = [
        "DMF PULSE - PRIVATE 3-GW ROLLING DECISION",
        "",
        "ROLLING HORIZON",
        f"Gameweeks: {', '.join(str(item) for item in decision.horizon_gameweeks)}",
        f"Information cutoff: {decision.information_cutoff.isoformat()}",
        f"Objective: {decision.horizon_objective}",
        f"Terminal value: {decision.terminal_value_mode}",
        f"Price path: {decision.future_price_mode}",
        f"Scenario tree: {decision.scenario_tree_mode}",
        f"Search: {decision.search_scope_mode}",
        f"Transfer-count scope source: {decision.transfer_count_scope_source}",
        f"Derived maximum transfers per deadline: {decision.maximum_transfers_per_deadline}",
        f"Chips: {decision.chip_mode}",
        "",
        "DO NOW",
        f"Transfers: {moves(decision.do_now)}",
        f"Hit: -{decision.do_now.hit_points}",
        f"Bank after: {decision.do_now.bank_after_tenths} tenths",
        f"Squad after: {', '.join(player_label(item) for item in decision.do_now.squad_after)}",
        f"XI: {', '.join(player_label(item) for item in decision.do_now.tactics.starting_xi)}",
        f"Bench: {bench(decision.do_now)}",
        (
            "FT before / next deadline: "
            f"{decision.do_now.free_transfer_state.manager_state_before} / "
            f"{decision.do_now.free_transfer_state.next_decision_deadline}"
        ),
        (
            "Captain / vice: "
            f"{player_label(decision.do_now.tactics.captain)} / "
            f"{player_label(decision.do_now.tactics.vice_captain)}"
        ),
        "",
        "3-GW VALUE",
        f"Expected horizon utility: {decision.horizon_comparison.plan_expected_horizon_utility:.2f}",
        f"Uplift versus no-root-transfer: {decision.horizon_comparison.expected_uplift:+.2f}",
        (
            "Gain p10 / median / p90: "
            f"{decision.horizon_comparison.gain_p10} / "
            f"{decision.horizon_comparison.gain_median} / "
            f"{decision.horizon_comparison.gain_p90}"
        ),
        (
            "P(plan beats baseline): "
            f"{decision.horizon_comparison.probability_plan_beats_baseline:.1%}"
        ),
        "",
        "ROOT TRANSFER-COUNT FRONTIER",
        *(frontier_line(item) for item in decision.transfer_frontier.points),
        "",
        "BY GAMEWEEK",
    ]
    for item in decision.by_gameweek:
        coverage = item.fixture_coverage
        actionability_label = (
            "DO NOW"
            if item.actionability == "DO_NOW"
            else ("PROVISIONAL - REOPTIMISE AT THAT DEADLINE")
        )
        lines.extend(
            (
                f"GW{item.gameweek} - {actionability_label}",
                f"  Transfers: {moves(item)}; hit: -{item.hit_points}",
                (
                    f"  Expected points after hit: {item.expected_manager_points_after_hit:.2f}; "
                    f"FT before/next: {item.free_transfer_state.manager_state_before}/"
                    f"{item.free_transfer_state.next_decision_deadline}; "
                    f"bank: {item.bank_after_tenths}"
                ),
                (
                    f"  Fixture coverage: total={coverage.fixtures_total}, "
                    f"market-backed={coverage.market_backed_fixtures}, "
                    f"prior-only={coverage.score_prior_only_fixtures}, "
                    f"blocked={coverage.blocked_fixtures}"
                ),
                (
                    "  Captain / vice: "
                    f"{player_label(item.tactics.captain)} / "
                    f"{player_label(item.tactics.vice_captain)}"
                ),
                f"  XI: {', '.join(player_label(player) for player in item.tactics.starting_xi)}",
                f"  Limitations: {', '.join(item.limitations) if item.limitations else 'NONE'}",
            )
        )
    comparison = decision.one_gameweek_comparison
    lines.extend(
        (
            "",
            "ONE-GW VERSUS 3-GW",
            f"Actions differ: {'YES' if comparison.actions_differ else 'NO'}",
            f"One-GW action: {comparison.one_gameweek_action_signature}",
            f"One-GW moves: {move_list(comparison.one_gameweek_transfers)}",
            f"Three-GW action: {comparison.three_gameweek_action_signature}",
            f"Three-GW moves: {move_list(comparison.three_gameweek_transfers)}",
            f"Counterfactual basis: {comparison.counterfactual_basis}",
            (
                "Matched-count action equals one-GW action: "
                f"{'YES' if comparison.counterfactual_action_matches_one_gameweek_action else 'NO'}"
            ),
            "WHY CHANGED - STRUCTURED DECOMPOSITION",
            f"Current-GW points difference: {comparison.current_gameweek_points_difference:+.2f}",
            f"Later-GW points difference: {comparison.future_gameweek_points_difference:+.2f}",
            f"Hit-cost difference: {comparison.expected_hit_cost_difference:+.2f}",
            (
                "FT entering next-GW difference: "
                f"{comparison.free_transfers_entering_next_difference:+d}"
            ),
            f"Terminal difference: {comparison.terminal_contribution_difference:+.2f}",
            f"Total horizon difference: {comparison.total_horizon_utility_difference:+.2f}",
            "",
            "WARNINGS",
            *(f"- {item}" for item in decision.warnings),
            "",
        )
    )
    return "\n".join(lines)


class PrivateV1RollingRecommendationService:
    """Build and solve one exact declared private three-GW policy in memory."""

    def run(
        self,
        value: PrivateV1RollingExecutionInput,
        *,
        progress: ProgressSink | None = None,
    ) -> PrivateV1RollingRunResult:
        active_progress = progress or NullProgress()
        timings: list[PrivateRollingStageTiming] = []

        def record(stage: str, started: float) -> None:
            timings.append(
                PrivateRollingStageTiming(
                    stage=stage,
                    elapsed_ms=Decimal(str((perf_counter() - started) * 1000)),
                )
            )

        try:
            execution = PrivateV1RollingExecutionInput.model_validate_json(value.model_dump_json())
        except ValidationError:
            raise PrivateV1Error(
                "PRIVATE_ROLLING_EXECUTION_INPUT_INVALID",
                "private rolling execution input failed validation",
            ) from None
        current = execution.current_execution
        terminal = load_terminal_value_policy()
        if (
            execution.terminal_policy_sha256 != terminal.policy_sha256
            or terminal.enabled
            or terminal.bank_points_per_tenth != Decimal(0)
            or terminal.free_transfer_points != Decimal(0)
            or terminal.liquidation_points_per_tenth != Decimal(0)
        ):
            raise PrivateV1Error(
                "ROLLING_TERMINAL_POLICY_INVALID",
                "three-GW mode requires the accepted disabled zero terminal policy",
            )
        if any(
            fixture.market_mode == "BLOCKED"
            for gameweek in execution.future_gameweeks
            for fixture in gameweek.fixtures
        ):
            raise PrivateV1Error(
                "FUTURE_FIXTURE_INPUT_BLOCKED",
                "at least one future fixture lacks an accepted current-cutoff projection input",
            )
        _verify_current_sources(current)
        prior = load_packaged_player_prior()
        _verify_runtime_artifacts(current, prior)
        projections: list[GameweekProjectionResult] = []
        fixture_results_by_gameweek = {}
        stage7_contexts_by_gameweek = {}
        stage8_hashes_by_gameweek = {}
        binding_hashes_by_gameweek = {}
        fallback_player_ids: set[str] = set()
        for gameweek in execution.horizon_gameweeks:
            future = next(
                (item for item in execution.future_gameweeks if item.gameweek == gameweek),
                None,
            )
            started = perf_counter()
            with active_progress.stage(
                started=f"GW{gameweek} Stage 8/9 projection...",
                completed=f"GW{gameweek} Stage 8/9 projection ready",
                failed=f"GW{gameweek} Stage 8/9 projection",
                heartbeat=f"GW{gameweek} Stage 8/9 projection still running",
            ):
                projected = _project_fixtures(
                    current,
                    prior,
                    active_progress,
                    future_gameweek=future,
                )
            record(f"stage8_9_gameweek_{gameweek}", started)
            fixture_results, stage7_contexts, stage8_hashes, binding_hashes, fallback = projected
            fixture_results_by_gameweek[gameweek] = fixture_results
            stage7_contexts_by_gameweek[gameweek] = stage7_contexts
            stage8_hashes_by_gameweek[gameweek] = stage8_hashes
            binding_hashes_by_gameweek[gameweek] = binding_hashes
            fallback_player_ids.update(fallback)
            started = perf_counter()
            with active_progress.stage(
                started=f"GW{gameweek} joint scenario assembly...",
                completed=f"GW{gameweek} joint scenarios ready",
                failed=f"GW{gameweek} joint scenario assembly",
            ):
                try:
                    scenario_set = assemble_gameweek(fixture_results)
                    projection = build_gameweek_projection(
                        scenario_set,
                        current.stage9_monte_carlo_policy,
                    )
                except (FplPointsError, ValidationError, ValueError) as exc:
                    raise PrivateV1Error(
                        "STAGE9_GAMEWEEK_INVALID",
                        f"GW{gameweek} Stage-9 Gameweek assembly failed",
                    ) from exc
            record(f"joint_scenario_assembly_gameweek_{gameweek}", started)
            if current.require_stage9_mc_pass and projection.monte_carlo.stopping_result != "PASS":
                raise PrivateV1Error(
                    "STAGE9_MC_QUALITY_BLOCKED",
                    f"GW{gameweek} Stage-9 Monte Carlo quality gate did not pass",
                )
            projections.append(projection)
        if len(projections) != 3:
            raise PrivateV1Error("ROLLING_HORIZON_INCOMPLETE", "three projections are required")
        projection_tuple = (projections[0], projections[1], projections[2])
        started = perf_counter()
        request, tactical, candidates, scope = _stage11_request(
            current,
            projection_tuple[0],
            future_gameweeks=projection_tuple[1:],
        )
        record("action_generation", started)
        started = perf_counter()
        with active_progress.stage(
            started="Three-GW root tactical batch...",
            completed="Three-GW root tactical batch ready",
            failed="three-GW root tactical batch",
            heartbeat="Three-GW root tactical batch still running",
        ):
            tactical.precompute()
        record("tactical_batch_evaluation", started)
        started = perf_counter()
        with active_progress.stage(
            started="Stage-11 three-GW policy solving...",
            completed="Stage-11 three-GW policy solving complete",
            failed="Stage-11 three-GW policy solving",
            heartbeat="Stage-11 three-GW policy solving still running",
        ):
            optimiser = optimise_multi_gameweek(request, evaluator=tactical)
        record("stage11_policy_solving", started)
        if (
            optimiser.status is not MultiGameweekResultStatus.SUCCESS
            or optimiser.solver_status.status is not BackendStatus.OPTIMAL
            or optimiser.recommended_plan is None
            or optimiser.no_transfer_baseline is None
            or not isinstance(optimiser.transfer_count_frontier, HorizonTransferCountFrontier)
        ):
            raise PrivateV1Error(
                optimiser.error_code or "ROLLING_OPTIMISER_BLOCKED",
                "Stage 11 did not return a complete exact three-GW recommendation",
            )
        one_request, _unused, _one_candidates, _one_scope = _stage11_request(
            current,
            projection_tuple[0],
        )
        one_gameweek = optimise_multi_gameweek(one_request, evaluator=tactical)
        if one_gameweek.recommended_plan is None or (
            one_gameweek.status is not MultiGameweekResultStatus.SUCCESS
        ):
            raise PrivateV1Error(
                one_gameweek.error_code or "ONE_GAMEWEEK_COMPARATOR_BLOCKED",
                "accepted one-GW comparator could not be reproduced",
            )
        current_players, _teams = _current_identity_maps(current)
        element_by_player = {
            player_id: item.provider_element_id for player_id, item in current_players.items()
        }
        scenarios_by_gameweek = {
            gameweek: projection.scenario_set
            for gameweek, projection in zip(
                execution.horizon_gameweeks,
                projection_tuple,
                strict=True,
            )
        }
        action_space_disclosure = (
            _action_space_disclosure(scope)
            + " Three-Gameweek mode reuses that current-cutoff shortlist at every declared "
            "future node; exactness is only within this bounded action space."
        )
        started = perf_counter()
        baseline = optimiser.no_transfer_baseline
        recommended = optimiser.recommended_plan
        frontier = _rolling_frontier(
            optimiser,
            request=request,
            baseline=baseline,
            scenarios_by_gameweek=scenarios_by_gameweek,
            element_by_player=element_by_player,
            action_space_disclosure=action_space_disclosure,
            candidate_policy_sha256=current.candidate_action_policy.semantic_sha256,
        )
        decisions = tuple(
            _build_gameweek_decision(
                item,
                execution=execution,
                request=request,
                scenarios=scenarios_by_gameweek[item.gameweek],
                candidates=candidates,
                tactical=tactical,
                element_by_player=element_by_player,
                actionable=index == 0,
            )
            for index, item in enumerate((recommended.current_action, *recommended.future_policy))
        )
        if len(decisions) != 3:
            raise PrivateV1Error(
                "ROLLING_POLICY_INCOMPLETE",
                "recommended rolling policy does not contain three decisions",
            )
        horizon_comparison = _horizon_comparison(
            recommended,
            baseline,
            scenarios_by_gameweek=scenarios_by_gameweek,
        )
        one_comparison = _one_gameweek_comparison(
            one_gameweek.recommended_plan,
            recommended,
            frontier,
            optimiser.transfer_count_frontier,
            request=request,
            element_by_player=element_by_player,
        )
        warnings = {
            "NO_CHIP_EXPLICIT",
            "NOT_PRODUCTION_ACTIVE",
            "EXACT_ONLY_WITHIN_DECLARED_CANDIDATE_ACTION_SPACE",
            "THREE_GAMEWEEK_ZERO_TERMINAL_VALUE_AFTER_HORIZON",
            "FUTURE_PRICE_CHANGES_NOT_MODELLED_IN_PRIVATE_3GW_V1",
            "DETERMINISTIC_NO_NEW_INFORMATION_REVELATION_V1",
            "INDEPENDENT_GAMEWEEK_SCENARIO_PRODUCT_NO_INFORMATION_REVELATION_V1",
            "CROSS_GAMEWEEK_READINESS_AND_INJURY_TRANSITIONS_NOT_MODELLED",
            execution.search_scope_mode,
            *optimiser.warnings,
            *(
                warning
                for projection in projection_tuple
                for warning in projection.scenario_set.warnings
            ),
            *(warning for item in decisions for warning in item.limitations),
        }
        provisional = PrivateV1RollingDecision.model_construct(
            status="SUCCESS",
            activation_status="NOT_PRODUCTION_ACTIVE",
            execution_status=(
                "SYNTHETIC_REPLAYABLE_RECOMMENDATION"
                if current.retention_class == "SYNTHETIC_REPLAY_ALLOWED"
                else "REAL_PRIVATE_TRANSIENT_RECOMMENDATION"
            ),
            run_id=current.run_id,
            season=current.current_state.season_code,
            projection_mode=current.projection_mode,
            horizon_gameweeks=execution.horizon_gameweeks,
            information_cutoff=current.current_state.information_cutoff,
            horizon_objective="EXPECTED_THREE_GAMEWEEK_POINTS_WITH_LEGAL_RECOURSE",
            terminal_value_mode=execution.terminal_value_mode,
            future_price_mode=execution.future_price_mode,
            scenario_tree_mode=execution.scenario_tree_mode,
            search_scope_mode=execution.search_scope_mode,
            transfer_count_scope_source=execution.transfer_count_scope_source,
            maximum_transfers_per_deadline=execution.maximum_transfers_per_deadline,
            chip_mode=execution.chip_mode,
            do_now=decisions[0],
            by_gameweek=decisions,
            future_plan=decisions[1:],
            horizon_comparison=horizon_comparison,
            transfer_frontier=frontier,
            one_gameweek_comparison=one_comparison,
            solver_optimality="EXACT_DECLARED_TREE_AND_ACTION_SPACE",
            action_space_disclosure=action_space_disclosure,
            warnings=tuple(sorted(warnings)),
            lineage=PrivateRollingDecisionLineage(
                rolling_execution_input_sha256=execution.semantic_sha256,
                current_execution_input_sha256=current.semantic_sha256,
                current_manager_state_sha256=request.initial_state.state_sha256,
                stage7_input_sha256_by_gameweek={
                    execution.horizon_gameweeks[0]: {
                        item.fixture_id: canonical_sha256(item.model_dump(mode="json"))
                        for item in current.manual_minutes
                    },
                    **{
                        gameweek.gameweek: {
                            str(item.canonical_fixture_id): canonical_sha256(
                                item.stage7.model_dump(mode="json")
                            )
                            for item in gameweek.fixtures
                        }
                        for gameweek in execution.future_gameweeks
                    },
                },
                stage7_context_sha256_by_gameweek=stage7_contexts_by_gameweek,
                stage8_distribution_sha256_by_gameweek=stage8_hashes_by_gameweek,
                player_prior_binding_sha256_by_gameweek=binding_hashes_by_gameweek,
                fixture_projection_sha256_by_gameweek={
                    gameweek: {
                        item.fixture_id: item.result_sha256
                        for item in fixture_results
                        if item.result_sha256 is not None
                    }
                    for gameweek, fixture_results in fixture_results_by_gameweek.items()
                },
                player_prior_fallback_ids=tuple(sorted(fallback_player_ids)),
                gameweek_projection_sha256_by_gameweek={
                    gameweek: projection.result_sha256
                    for gameweek, projection in zip(
                        execution.horizon_gameweeks,
                        projection_tuple,
                        strict=True,
                    )
                    if projection.result_sha256 is not None
                },
                joint_matrix_sha256_by_gameweek={
                    gameweek: semantic_sha256(projection.joint_matrix)
                    for gameweek, projection in zip(
                        execution.horizon_gameweeks,
                        projection_tuple,
                        strict=True,
                    )
                },
                future_gameweek_input_sha256_by_gameweek={
                    item.gameweek: item.semantic_sha256 for item in execution.future_gameweeks
                },
                scenario_tree_sha256=request.scenario_tree.tree_sha256,
                optimiser_request_sha256=request.request_sha256,
                optimiser_result_sha256=optimiser.result_sha256,
                one_gameweek_optimiser_result_sha256=one_gameweek.result_sha256,
                terminal_policy_sha256=terminal.policy_sha256,
                candidate_action_policy_sha256=current.candidate_action_policy.semantic_sha256,
                ruleset_sha256=current.ruleset.ruleset_hash,
                code_sha=current.code_sha,
            ),
            semantic_sha256="0" * 64,
        )
        sealed = seal_rolling_decision(provisional)
        report = render_rolling_report(sealed)
        record("report_and_comparator", started)
        del (
            fixture_results_by_gameweek,
            stage7_contexts_by_gameweek,
            stage8_hashes_by_gameweek,
            binding_hashes_by_gameweek,
            fallback_player_ids,
        )
        return PrivateV1RollingRunResult(
            decision=sealed,
            report=report,
            gameweek_projections=projection_tuple,
            optimiser_result=optimiser,
            optimiser_request=request,
            one_gameweek_optimiser_result=one_gameweek,
            stage_timings=tuple(timings),
        )


__all__ = [
    "PrivateRollingStageTiming",
    "PrivateV1RollingRecommendationService",
    "PrivateV1RollingRunResult",
    "render_rolling_report",
]
