from __future__ import annotations

import math
from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.fpl_points.gameweek import assemble_blank_gameweek, assemble_gameweek
from dmf_pulse.fpl_points.gameweek_summaries import build_gameweek_projection
from dmf_pulse.fpl_points.models import ProjectionMode, SimulationStatus
from dmf_pulse.fpl_points.service import FplPointsService, generate_fixture_scenarios
from tests.support.factories import FIXTURE_A, FIXTURE_B, make_request, mc_policy, reference_engine


@given(seed=st.integers(min_value=0, max_value=2**63 - 1))
@settings(max_examples=40, deadline=None)
def test_many_seeds_preserve_goal_on_pitch_and_integer_invariants(seed: int) -> None:
    request = make_request(root_seed=seed, scenario_count=5)
    scenarios = generate_fixture_scenarios(request, reference_engine(), range(5))
    intervals = {
        participant.player_id: participant.interval
        for participant in request.participation_scenarios[0].participants
    }
    for scenario in scenarios:
        event = scenario.event_scenario
        home = [p for p in event.players if p.team_id == event.home_team_id]
        away = [p for p in event.players if p.team_id == event.away_team_id]
        assert (
            sum(p.goals_non_penalty + p.goals_penalty for p in home)
            + sum(p.own_goals for p in away)
            == event.home_goals
        )
        assert (
            sum(p.goals_non_penalty + p.goals_penalty for p in away)
            + sum(p.own_goals for p in home)
            == event.away_goals
        )
        assert len(event.goals) == event.home_goals + event.away_goals
        for goal in event.goals:
            assert goal.scorer_player_id != goal.assister_player_id
            for player_id in (
                goal.scorer_player_id,
                goal.assister_player_id,
                goal.own_goal_player_id,
            ):
                if player_id is not None:
                    assert intervals[player_id] is not None
                    assert intervals[player_id].contains(goal.minute)
        for score in scenario.players.values():
            assert type(score.total) is int
            components = (
                score.appearance,
                score.goals,
                score.assists,
                score.clean_sheet,
                score.saves,
                score.penalty_saves,
                score.defensive_contributions,
                score.goals_conceded,
                score.penalty_misses,
                score.yellow_cards,
                score.red_cards,
                score.own_goals,
                score.bonus,
            )
            assert all(type(value) is int for value in components)
            assert score.total == sum(components)


@given(
    root_seed=st.integers(min_value=0, max_value=2**63 - 1),
    scenario_count=st.integers(min_value=3, max_value=24),
)
@settings(max_examples=20, deadline=None)
def test_same_seed_and_worker_partition_produce_same_semantic_scenarios(
    root_seed: int, scenario_count: int
) -> None:
    request = make_request(root_seed=root_seed, scenario_count=scenario_count)
    full = generate_fixture_scenarios(request, reference_engine(), range(scenario_count))
    partitions = (
        generate_fixture_scenarios(request, reference_engine(), range(0, scenario_count, 3))
        + generate_fixture_scenarios(request, reference_engine(), range(1, scenario_count, 3))
        + generate_fixture_scenarios(request, reference_engine(), range(2, scenario_count, 3))
    )
    assert sorted(full, key=lambda item: item.scenario_index) == sorted(
        partitions, key=lambda item: item.scenario_index
    )


def test_fixture_pmf_threshold_quantile_and_mapping_properties() -> None:
    result = FplPointsService(reference_engine(), mc_policy()).project(
        make_request(scenario_count=80)
    )
    assert result.status is SimulationStatus.SUCCESS
    assert result.joint_matrix is not None
    assert len(set(result.joint_matrix.player_ids)) == len(result.joint_matrix.player_ids)
    for summary in result.player_summaries.values():
        assert math.isclose(sum(summary.pmf.values()), 1.0, abs_tol=1e-10)
        probabilities = (
            summary.probability_1_plus,
            summary.probability_2_plus,
            summary.probability_5_plus,
            summary.probability_10_plus,
            summary.probability_15_plus,
        )
        assert all(left >= right for left, right in pairwise(probabilities))
        ordered = [
            value
            for _, value in sorted(
                (int(key[1:]), value) for key, value in summary.selected_percentiles.items()
            )
        ]
        assert ordered == sorted(ordered)


def test_blank_gameweek_is_point_mass_zero() -> None:
    scenario_set = assemble_blank_gameweek(
        gameweek_id="GW-BLANK", player_ids=("p2", "p1"), ruleset_hash="1" * 64
    )
    result = build_gameweek_projection(scenario_set, mc_policy())
    assert scenario_set.player_ids == ("p1", "p2")
    assert all(summary.pmf == {0: 1.0} for summary in result.player_summaries.values())
    assert all(value == 0 for row in result.joint_matrix.points for value in row)


def test_double_gameweek_total_equals_fixture_scenario_sum() -> None:
    service = FplPointsService(reference_engine(), mc_policy())
    first = service.project(make_request(fixture_id=FIXTURE_A, root_seed=44, scenario_count=12))
    second = service.project(make_request(fixture_id=FIXTURE_B, root_seed=44, scenario_count=12))
    gameweek = assemble_gameweek((first, second))
    first_by_draw = {scenario.outcome_draw_id: scenario for scenario in first.scenarios}
    second_by_draw = {scenario.outcome_draw_id: scenario for scenario in second.scenarios}
    for scenario in gameweek.scenarios:
        for player_id in gameweek.player_ids:
            expected = (
                first_by_draw[scenario.outcome_draw_id].players[player_id].total
                + second_by_draw[scenario.outcome_draw_id].players[player_id].total
            )
            assert scenario.player_points[player_id] == expected


def test_inactive_reference_ruleset_cannot_issue_production_projection() -> None:
    request = make_request(mode=ProjectionMode.PRODUCTION, scenario_count=4)
    result = FplPointsService(reference_engine(), mc_policy()).project(request)
    assert result.status is SimulationStatus.BLOCKED
    assert result.error_code == "RULESET_NOT_ACTIVE"
    assert result.projection_mode is ProjectionMode.PRODUCTION
