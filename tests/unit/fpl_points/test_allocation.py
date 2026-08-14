from __future__ import annotations

import pytest

from dmf_pulse.fpl_points.allocation import (
    allocate_fixture_events,
    sample_participation,
    sample_scoreline,
    validate_assist_share_constraints,
    validate_goal_share_simplex,
)
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import ProjectionMode, ScorelineCell
from tests.support.factories import (
    A_FWD,
    AWAY_TEAM_ID,
    H_MID,
    HOME_TEAM_ID,
    allocation_config,
    base_profiles,
    make_request,
    reference_engine,
)


def _allocate(
    seed: int = 7,
    *,
    cell: ScorelineCell | None = None,
    profiles=None,
    **config_updates,
):
    request = make_request(
        root_seed=seed,
        scenario_count=1,
        config=allocation_config(**config_updates),
    )
    return allocate_fixture_events(
        cell=cell or ScorelineCell(home_goals=3, away_goals=2, probability="1.000000000000"),
        participation=request.participation_scenarios[0],
        profiles=profiles or request.allocation_profiles,
        config=request.allocation_config,
        ruleset=reference_engine().identity,
        projection_mode=ProjectionMode.TEST,
        root_seed=seed,
        scenario_index=0,
    )


def test_goal_share_simplex_rejects_empty_team() -> None:
    profiles = tuple(
        profile.model_copy(update={"goal_share": 0.0})
        for profile in base_profiles()
        if profile.team_id == HOME_TEAM_ID
    )
    with pytest.raises(FplPointsError, match="positive scorer share"):
        validate_goal_share_simplex(profiles, HOME_TEAM_ID)


def test_sampling_rejects_empty_or_non_normalized_inputs() -> None:
    with pytest.raises(FplPointsError, match="score matrix is empty"):
        sample_scoreline((), root_seed=1, scenario_index=0)
    with pytest.raises(FplPointsError, match="exact simplex"):
        sample_scoreline(
            (ScorelineCell(home_goals=0, away_goals=0, probability="0.500000000000"),),
            root_seed=1,
            scenario_index=0,
        )
    with pytest.raises(FplPointsError, match="do not align"):
        sample_participation((), root_seed=1, scenario_index=0)


def test_assist_share_validator_rejects_negative_even_if_model_was_tampered() -> None:
    profile = base_profiles()[0].model_copy(update={"assist_share": -1.0})
    with pytest.raises(FplPointsError, match="non-negative"):
        validate_assist_share_constraints((profile,), HOME_TEAM_ID)


def test_goal_and_assist_allocation_is_conserved_and_on_pitch() -> None:
    scenario, _ = _allocate(seed=13)
    players = {player.player_id: player for player in scenario.players}
    home = [player for player in scenario.players if player.team_id == HOME_TEAM_ID]
    away = [player for player in scenario.players if player.team_id == AWAY_TEAM_ID]
    assert (
        sum(p.goals_non_penalty + p.goals_penalty for p in home) + sum(p.own_goals for p in away)
        == 3
    )
    assert (
        sum(p.goals_non_penalty + p.goals_penalty for p in away) + sum(p.own_goals for p in home)
        == 2
    )
    participation = {
        player.player_id: player
        for player in make_request().participation_scenarios[0].participants
    }
    for goal in scenario.goals:
        assert goal.scorer_player_id != goal.assister_player_id
        for player_id in (goal.scorer_player_id, goal.assister_player_id, goal.own_goal_player_id):
            if player_id is None:
                continue
            interval = participation[player_id].interval
            assert interval is not None and interval.contains(goal.minute)
            assert players[player_id].minutes > 0
    assert players[A_FWD].minutes == 0
    assert players[A_FWD].goals_non_penalty == 0
    assert players[A_FWD].eligible_assists == 0


def test_same_seed_produces_identical_semantic_event_scenario() -> None:
    left, left_reasons = _allocate(seed=99)
    right, right_reasons = _allocate(seed=99)
    assert left == right
    assert left_reasons == right_reasons


def test_ambiguous_assist_classification_is_explicit() -> None:
    scenario, _ = _allocate(
        seed=2,
        cell=ScorelineCell(home_goals=1, away_goals=0, probability="1.000000000000"),
        ambiguous_assist_probability=1.0,
        ambiguous_assist_eligible_probability=0.0,
    )
    goal = scenario.goals[0]
    assert goal.assist_classification.value == "AMBIGUOUS_ASSIST"
    assert goal.assister_player_id is None
    assert goal.assist_awarded is False


def test_penalty_goal_uses_an_on_pitch_taker() -> None:
    scenario, _ = _allocate(
        seed=3,
        cell=ScorelineCell(home_goals=1, away_goals=0, probability="1.000000000000"),
        penalty_goal_probability=1.0,
        assistable_probability=1.0,
    )
    goal = scenario.goals[0]
    assert goal.mechanism.value == "PENALTY"
    assert goal.scorer_player_id == H_MID
    assert next(p for p in scenario.players if p.player_id == H_MID).goals_penalty == 1


def test_own_goal_reconciles_to_team_score() -> None:
    scenario, _ = _allocate(
        seed=5,
        cell=ScorelineCell(home_goals=1, away_goals=0, probability="1.000000000000"),
        own_goal_probability=1.0,
    )
    goal = scenario.goals[0]
    assert goal.mechanism.value == "OPPONENT_OWN_GOAL"
    assert goal.own_goal_player_id is not None
    assert goal.scorer_player_id is None


def test_own_goal_and_penalty_share_fallbacks_are_explicit() -> None:
    no_own_goals = tuple(
        profile.model_copy(update={"own_goal_share": 0.0}) for profile in base_profiles()
    )
    scenario, reasons = _allocate(
        seed=5,
        cell=ScorelineCell(home_goals=1, away_goals=0, probability="1.000000000000"),
        profiles=no_own_goals,
        own_goal_probability=1.0,
    )
    assert scenario.goals[0].scorer_player_id is not None
    assert "OWN_GOAL_SHARE_FALLBACK_TO_CREDITED_SCORER" in reasons

    no_penalty_taker = tuple(
        profile.model_copy(update={"penalty_taker_share": 0.0}) for profile in base_profiles()
    )
    scenario, reasons = _allocate(
        seed=3,
        cell=ScorelineCell(home_goals=1, away_goals=0, probability="1.000000000000"),
        profiles=no_penalty_taker,
        penalty_goal_probability=1.0,
    )
    assert scenario.goals[0].scorer_player_id is not None
    assert "PENALTY_SHARE_FALLBACK_TO_GOAL_SHARE" in reasons


def test_extra_penalty_path_generates_a_miss_and_save() -> None:
    scenario, _ = _allocate(
        seed=14,
        cell=ScorelineCell(home_goals=0, away_goals=0, probability="1.000000000000"),
        extra_penalty_attempt_probability=1.0,
        extra_penalty_save_probability=1.0,
    )
    assert sum(player.penalty_misses for player in scenario.players) == 1
    assert sum(player.penalty_saves for player in scenario.players) == 1
