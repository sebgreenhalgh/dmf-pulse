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
from dmf_pulse.fpl_points.models import OnPitchInterval, ProjectionMode, ScorelineCell
from tests.support.factories import (
    A_FWD,
    A_GK,
    AWAY_TEAM_ID,
    H_DEF,
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
    participants=None,
    **config_updates,
):
    request = make_request(
        root_seed=seed,
        scenario_count=1,
        participants=participants,
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


def _allocate_60_minute_defender_counterexample(*, red_card: bool):
    participants = tuple(
        participant.model_copy(
            update={
                "official_minutes": 60,
                "interval": OnPitchInterval(start_minute=0.0, end_minute=60.0),
            }
        )
        if participant.player_id == H_DEF
        else participant
        for participant in make_request().participation_scenarios[0].participants
    )
    profiles = tuple(
        profile.model_copy(update={"red_cards_per90": 1000.0 if red_card else 0.0})
        if profile.player_id == H_DEF
        else profile
        for profile in base_profiles()
    )
    request = make_request(
        participants=participants,
        profiles=profiles,
        config=allocation_config(goal_time_lower=70.0, goal_time_upper=80.0),
    )
    return allocate_fixture_events(
        cell=ScorelineCell(home_goals=0, away_goals=2, probability="1.000000000000"),
        participation=request.participation_scenarios[0],
        profiles=request.allocation_profiles,
        config=request.allocation_config,
        ruleset=reference_engine().identity,
        projection_mode=ProjectionMode.TEST,
        root_seed=request.root_seed,
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


def test_red_card_uses_stage7_endpoint_for_post_dismissal_conceded_goals() -> None:
    scenario, _ = _allocate_60_minute_defender_counterexample(red_card=True)
    defender = next(player for player in scenario.players if player.player_id == H_DEF)

    assert all(goal.minute > 60.0 for goal in scenario.goals)
    assert defender.minutes == 60
    assert defender.red_cards == 1
    assert defender.dismissed is True
    assert defender.goals_conceded_while_eligible == 0
    assert defender.team_goals_after_dismissal == 2

    score = reference_engine().score_fixture(scenario)[H_DEF]
    assert score.clean_sheet == 0
    assert score.goals_conceded == -1
    assert score.red_cards == -3


def test_normal_substitution_does_not_create_post_dismissal_conceded_goals() -> None:
    scenario, _ = _allocate_60_minute_defender_counterexample(red_card=False)
    defender = next(player for player in scenario.players if player.player_id == H_DEF)

    assert defender.minutes == 60
    assert defender.dismissed is False
    assert defender.goals_conceded_while_eligible == 0
    assert defender.team_goals_after_dismissal == 0

    score = reference_engine().score_fixture(scenario)[H_DEF]
    assert score.clean_sheet == 4
    assert score.goals_conceded == 0


def test_forced_red_card_counterexample_is_deterministic() -> None:
    left = _allocate_60_minute_defender_counterexample(red_card=True)
    right = _allocate_60_minute_defender_counterexample(red_card=True)
    assert left == right


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
    assert len(scenario.penalties) == 1
    assert scenario.penalties[0].outcome.value == "GOAL"
    assert scenario.penalties[0].goal_id == goal.goal_id
    assert scenario.penalties[0].taker_player_id == goal.scorer_player_id


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


def test_missing_own_goal_and_penalty_shares_fail_closed() -> None:
    no_own_goals = tuple(
        profile.model_copy(update={"own_goal_share": 0.0}) for profile in base_profiles()
    )
    with pytest.raises(FplPointsError) as own_goal_error:
        _allocate(
            seed=5,
            cell=ScorelineCell(home_goals=1, away_goals=0, probability="1.000000000000"),
            profiles=no_own_goals,
            own_goal_probability=1.0,
        )
    assert own_goal_error.value.code == "NO_ELIGIBLE_OWN_GOAL_PLAYER"

    no_penalty_taker = tuple(
        profile.model_copy(update={"penalty_taker_share": 0.0}) for profile in base_profiles()
    )
    with pytest.raises(FplPointsError) as penalty_error:
        _allocate(
            seed=3,
            cell=ScorelineCell(home_goals=1, away_goals=0, probability="1.000000000000"),
            profiles=no_penalty_taker,
            penalty_goal_probability=1.0,
        )
    assert penalty_error.value.code == "NO_ELIGIBLE_PENALTY_TAKER"


def test_extra_penalty_path_generates_a_miss_and_save() -> None:
    scenario, _ = _allocate(
        seed=14,
        cell=ScorelineCell(home_goals=0, away_goals=0, probability="1.000000000000"),
        extra_penalty_attempt_probability=1.0,
        extra_penalty_save_probability=1.0,
    )
    assert sum(player.penalty_misses for player in scenario.players) == 1
    assert sum(player.penalty_saves for player in scenario.players) == 1
    assert len(scenario.penalties) == 1
    assert scenario.penalties[0].outcome.value == "SAVED"
    assert len(scenario.goalkeeper_saves) >= 1
    penalty_save = next(
        save
        for save in scenario.goalkeeper_saves
        if save.penalty_id == scenario.penalties[0].penalty_id
    )
    assert penalty_save.goalkeeper_player_id == scenario.penalties[0].goalkeeper_player_id


def test_goalkeeper_saves_are_timed_linked_and_never_assigned_to_outfield_players() -> None:
    participants = tuple(
        participant.model_copy(
            update={
                "official_minutes": 45,
                "interval": OnPitchInterval(start_minute=0.0, end_minute=45.0),
            }
        )
        if participant.player_id == A_GK
        else participant
        for participant in make_request().participation_scenarios[0].participants
    )
    profiles = tuple(
        profile.model_copy(update={"goalkeeper_saves_per90": 20.0})
        if profile.player_id in {A_GK, H_DEF}
        else profile
        for profile in base_profiles()
    )
    scenario, reasons = _allocate(
        seed=72,
        cell=ScorelineCell(home_goals=0, away_goals=0, probability="1.000000000000"),
        participants=participants,
        profiles=profiles,
    )
    players = {player.player_id: player for player in scenario.players}

    assert scenario.goalkeeper_saves
    assert players[H_DEF].saves == 0
    assert players[A_GK].saves == len(scenario.goalkeeper_saves)
    assert "TEST_SAVE_SHOOTER_GOAL_SHARE_PROXY" in reasons
    for save in scenario.goalkeeper_saves:
        goalkeeper = players[save.goalkeeper_player_id]
        shooter = players[save.shooter_player_id]
        assert goalkeeper.position.value == "GK"
        assert goalkeeper.on_pitch_interval is not None
        assert goalkeeper.on_pitch_interval.contains(save.minute)
        assert shooter.on_pitch_interval is not None
        assert shooter.on_pitch_interval.contains(save.minute)
        assert save.minute < 45.0
    saved_shots = {
        player_id: sum(save.shooter_player_id == player_id for save in scenario.goalkeeper_saves)
        for player_id in players
    }
    assert all(
        saved_shots[player_id] <= player.bps.shots_on_target
        for player_id, player in players.items()
    )


def test_zero_minute_goalkeeper_cannot_receive_save() -> None:
    participants = tuple(
        participant.model_copy(update={"official_minutes": 0, "interval": None, "starter": False})
        if participant.player_id == A_GK
        else participant
        for participant in make_request().participation_scenarios[0].participants
    )
    profiles = tuple(
        profile.model_copy(update={"goalkeeper_saves_per90": 1000.0})
        if profile.player_id == A_GK
        else profile
        for profile in base_profiles()
    )
    scenario, _ = _allocate(
        seed=81,
        cell=ScorelineCell(home_goals=0, away_goals=0, probability="1.000000000000"),
        participants=participants,
        profiles=profiles,
    )
    goalkeeper = next(player for player in scenario.players if player.player_id == A_GK)
    assert goalkeeper.minutes == 0
    assert goalkeeper.saves == 0
    assert all(save.goalkeeper_player_id != A_GK for save in scenario.goalkeeper_saves)


def test_semantic_allocation_is_invariant_to_participant_and_profile_order() -> None:
    request = make_request(root_seed=91, scenario_count=1)
    cell = ScorelineCell(home_goals=2, away_goals=1, probability="1.000000000000")
    left, left_reasons = allocate_fixture_events(
        cell=cell,
        participation=request.participation_scenarios[0],
        profiles=request.allocation_profiles,
        config=request.allocation_config,
        ruleset=reference_engine().identity,
        projection_mode=ProjectionMode.TEST,
        root_seed=91,
        scenario_index=0,
    )
    reordered_participation = request.participation_scenarios[0].model_copy(
        update={"participants": tuple(reversed(request.participation_scenarios[0].participants))}
    )
    right, right_reasons = allocate_fixture_events(
        cell=cell,
        participation=reordered_participation,
        profiles=tuple(reversed(request.allocation_profiles)),
        config=request.allocation_config,
        ruleset=reference_engine().identity,
        projection_mode=ProjectionMode.TEST,
        root_seed=91,
        scenario_index=0,
    )
    assert right == left
    assert right_reasons == left_reasons
