"""Exact manager multipliers over accepted shared Stage-9 scenarios."""

from __future__ import annotations

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import GameweekPointScenario, GameweekScenarioSet
from dmf_pulse.optimisation.autosub_evaluator import evaluate_scenario
from dmf_pulse.optimisation.models import CandidatePlayer, OneGameweekRulesView
from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.models import (
    ManagerChip,
    ManagerMultiplierPolicy,
    ManagerMultiplierSet,
    ManagerTeamPlan,
    ScenarioManagerMultiplier,
)


def raw_projection_hash(scenario_set: GameweekScenarioSet) -> str:
    """Bind the complete unchanged Stage-9 projection and upstream event lineage."""

    return semantic_sha256(scenario_set.model_dump(mode="json"))


def shared_scenario_set_hash(scenario_set: GameweekScenarioSet) -> str:
    """Hash the exact common scenario denominator used for every manager."""

    return semantic_sha256(
        {
            "gameweek_id": scenario_set.gameweek_id,
            "scenarios": [
                {
                    "scenario_id": item.scenario_id,
                    "outcome_draw_id": item.outcome_draw_id,
                    "weight": item.weight,
                }
                for item in scenario_set.scenarios
            ],
        }
    )


def _validate_inputs(
    plan: ManagerTeamPlan,
    scenario_set: GameweekScenarioSet,
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
) -> None:
    active = set(plan.active_squad)
    if not active <= set(players):
        raise RankStrategyError(
            "RANK_PLAYER_UNIVERSE_INVALID",
            "manager active squad contains a player absent from the accepted candidate universe",
            manager_id=plan.manager_id,
        )
    scenario_players = set(scenario_set.player_ids)
    if not active <= scenario_players:
        raise RankStrategyError(
            "RANK_SCENARIO_UNIVERSE_INVALID",
            "manager active squad contains a player absent from shared Stage-9 scenarios",
            manager_id=plan.manager_id,
        )
    if scenario_set.ruleset_hash != rules.ruleset_hash:
        raise RankStrategyError(
            "RANK_RULESET_MISMATCH",
            "Stage-9 scenarios and Stage-10 tactical rules use different ruleset hashes",
        )
    if len(plan.active_squad) != rules.squad_size:
        raise RankStrategyError(
            "RANK_SQUAD_SIZE_INVALID",
            "manager active squad size differs from accepted tactical rules",
            manager_id=plan.manager_id,
            expected=rules.squad_size,
            actual=len(plan.active_squad),
        )


def _scenario_multiplier(
    plan: ManagerTeamPlan,
    scenario: GameweekPointScenario,
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
    policy: ManagerMultiplierPolicy,
) -> ScenarioManagerMultiplier:
    accepted, _ = evaluate_scenario(
        scenario,
        plan.tactical_configuration,
        players,
        rules,
    )
    appeared = {player_id for player_id, value in scenario.player_appeared.items() if value}
    if plan.active_chip is ManagerChip.BENCH_BOOST:
        counted = set(plan.active_squad) & appeared
    else:
        counted = set(accepted.counted_player_ids)

    multipliers = {player_id: 0 for player_id in sorted(scenario.player_points)}
    for player_id in counted:
        multipliers[player_id] = 1

    if accepted.effective_captain_id is not None:
        captain_multiplier = (
            policy.triple_captain_multiplier
            if plan.active_chip is ManagerChip.TRIPLE_CAPTAIN
            else rules.captain_multiplier
        )
        multipliers[accepted.effective_captain_id] += captain_multiplier - 1

    gross_points = sum(
        scenario.player_points[player_id] * multiplier
        for player_id, multiplier in multipliers.items()
    )
    value = ScenarioManagerMultiplier(
        manager_id=plan.manager_id,
        plan_id=plan.plan_id,
        scenario_id=scenario.scenario_id,
        outcome_draw_id=scenario.outcome_draw_id,
        weight=scenario.weight,
        active_chip=plan.active_chip,
        player_multipliers=multipliers,
        counted_player_ids=tuple(
            player_id for player_id, multiplier in multipliers.items() if multiplier > 0
        ),
        autosubs=() if plan.active_chip is ManagerChip.BENCH_BOOST else accepted.autosubs,
        captain_resolution=accepted.captain_resolution,
        effective_captain_id=accepted.effective_captain_id,
        gross_points=gross_points,
        transfer_hit_points=plan.transfer_hit_points,
        net_points=gross_points - plan.transfer_hit_points,
        multiplier_hash="0" * 64,
    )
    payload = value.model_dump(mode="json", exclude={"multiplier_hash"})
    return ScenarioManagerMultiplier.model_validate(
        value.model_copy(update={"multiplier_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def calculate_manager_multipliers(
    plan: ManagerTeamPlan,
    scenario_set: GameweekScenarioSet,
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
    policy: ManagerMultiplierPolicy,
) -> ManagerMultiplierSet:
    """Resolve autosubs, captain fallback and chip effects for every shared scenario."""

    _validate_inputs(plan, scenario_set, players, rules)
    scenarios = tuple(
        sorted(
            (
                _scenario_multiplier(plan, scenario, players, rules, policy)
                for scenario in scenario_set.scenarios
            ),
            key=lambda item: (item.scenario_id, item.outcome_draw_id),
        )
    )
    expected_gross = sum(item.weight * item.gross_points for item in scenarios)
    expected_net = sum(item.weight * item.net_points for item in scenarios)
    value = ManagerMultiplierSet(
        manager_id=plan.manager_id,
        plan_id=plan.plan_id,
        scenario_set_hash=shared_scenario_set_hash(scenario_set),
        raw_projection_hash=raw_projection_hash(scenario_set),
        scenarios=scenarios,
        expected_gross_points=expected_gross,
        expected_net_points=expected_net,
        multiplier_set_hash="0" * 64,
    )
    payload = value.model_dump(mode="json", exclude={"multiplier_set_hash"})
    return ManagerMultiplierSet.model_validate(
        value.model_copy(update={"multiplier_set_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )
