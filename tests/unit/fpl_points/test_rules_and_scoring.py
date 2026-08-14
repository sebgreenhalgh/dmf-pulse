from __future__ import annotations

import pytest

from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.fpl_points.rules_adapter import competition_ranks, rank_expected_bps
from tests.support.factories import (
    empty_bps,
    empty_defensive,
    event_fixture,
    event_player,
    reference_engine,
)


def test_reference_ruleset_blocks_production() -> None:
    with pytest.raises(FplPointsError, match="requires an ACTIVE ruleset"):
        reference_engine().assert_mode_allowed(ProjectionMode.PRODUCTION)


def test_appearance_clean_sheet_goal_and_assist_components_are_exact() -> None:
    players = (
        event_player("h-def", "HOME", PlayerPosition.DEF, goals_non_penalty=1, assists=1),
        event_player("h-mid", "HOME", PlayerPosition.MID, minutes=59, goals_non_penalty=1),
        event_player("a-fwd", "AWAY", PlayerPosition.FWD, conceded=2),
    )
    scores = reference_engine().score_fixture(
        event_fixture(home_goals=2, away_goals=0, players=players)
    )
    assert scores["h-def"].appearance == 2
    assert scores["h-def"].goals == 6
    assert scores["h-def"].assists == 3
    assert scores["h-def"].clean_sheet == 4
    assert scores["h-mid"].appearance == 1
    assert scores["h-mid"].clean_sheet == 0
    assert scores["h-def"].total == sum(
        getattr(scores["h-def"], name)
        for name in (
            "appearance",
            "goals",
            "assists",
            "clean_sheet",
            "saves",
            "penalty_saves",
            "defensive_contributions",
            "goals_conceded",
            "penalty_misses",
            "yellow_cards",
            "red_cards",
            "own_goals",
            "bonus",
        )
    )


def test_save_groups_penalty_save_and_negative_events() -> None:
    players = (
        event_player("h-gk", "HOME", PlayerPosition.GK, saves=7, penalty_saves=1),
        event_player("a-fwd", "AWAY", PlayerPosition.FWD, penalty_misses=1, yellow=1),
    )
    scores = reference_engine().score_fixture(
        event_fixture(home_goals=0, away_goals=0, players=players)
    )
    assert scores["h-gk"].saves == 2
    assert scores["h-gk"].penalty_saves == 5
    assert scores["a-fwd"].penalty_misses == -2
    assert scores["a-fwd"].yellow_cards == -1


def test_defensive_contribution_threshold_boundary() -> None:
    below = event_player(
        "h-def",
        "HOME",
        PlayerPosition.DEF,
        defensive=empty_defensive(clearances=9),
    )
    at = event_player(
        "a-def",
        "AWAY",
        PlayerPosition.DEF,
        defensive=empty_defensive(clearances=10),
    )
    scores = reference_engine().score_fixture(
        event_fixture(home_goals=0, away_goals=0, players=(below, at))
    )
    assert scores["h-def"].defensive_contributions == 0
    assert scores["a-def"].defensive_contributions == 2


def test_goals_conceded_red_card_own_goal_and_negative_support() -> None:
    players = (
        event_player(
            "h-def",
            "HOME",
            PlayerPosition.DEF,
            conceded=2,
            own_goals=1,
            penalty_misses=1,
            red=1,
            team_goals_after_dismissal=0,
        ),
        event_player("a-fwd", "AWAY", PlayerPosition.FWD, goals_non_penalty=1),
    )
    score = reference_engine().score_fixture(
        event_fixture(home_goals=0, away_goals=2, players=players)
    )["h-def"]
    assert score.goals_conceded == -1
    assert score.own_goals == -2
    assert score.red_cards == -3
    assert score.penalty_misses == -2
    assert score.total < 0


def test_competition_ranking_and_more_than_three_bonus_recipients() -> None:
    assert competition_ranks({"a": 10, "b": 10, "c": 8, "d": 7}) == {"a": 1, "b": 1, "c": 3, "d": 4}
    players = tuple(
        event_player(player_id, team, PlayerPosition.FWD)
        for player_id, team in (("h1", "HOME"), ("h2", "HOME"), ("a1", "AWAY"), ("a2", "AWAY"))
    )
    scores = reference_engine().score_fixture(
        event_fixture(home_goals=0, away_goals=0, players=players)
    )
    assert sum(score.bonus == 3 for score in scores.values()) == 4
    assert all(score.bps_tied_at_rank for score in scores.values())


def test_zero_minute_players_do_not_enter_bps_competition() -> None:
    zero_minutes = event_player(
        "h-zero",
        "HOME",
        PlayerPosition.FWD,
        minutes=0,
    )
    eligible = event_player("a-eligible", "AWAY", PlayerPosition.FWD)
    scores = reference_engine().score_fixture(
        event_fixture(home_goals=0, away_goals=0, players=(zero_minutes, eligible))
    )
    assert scores["h-zero"].bps_competition_rank is None
    assert scores["h-zero"].bps_tied_at_rank is False
    assert scores["a-eligible"].bps_competition_rank == 1
    assert scores["a-eligible"].bonus == 3


def test_bps_event_values_are_scenario_level_integers() -> None:
    player = event_player(
        "h-mid",
        "HOME",
        PlayerPosition.MID,
        assists=1,
        bps=empty_bps(key_passes=2, pass_attempts=40, passes_completed=36),
    )
    scorer = event_player("h-fwd", "HOME", PlayerPosition.FWD, goals_non_penalty=1)
    opponent = event_player("a-fwd", "AWAY", PlayerPosition.FWD, conceded=1)
    score = reference_engine().score_fixture(
        event_fixture(home_goals=1, away_goals=0, players=(player, scorer, opponent))
    )["h-mid"]
    assert isinstance(score.bps, int)
    assert score.bps >= 9 + 2 + 6


def test_expected_bps_ranking_is_explicitly_prohibited() -> None:
    with pytest.raises(FplPointsError, match="never from expected BPS"):
        rank_expected_bps({"p": 12.5})
