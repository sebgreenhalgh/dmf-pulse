"""Threshold, negative-event, dismissal, and false-success scoring tests."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.rules.bps import calculate_bps
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import (
    BpsEvents,
    FixtureScenario,
    FixtureScoreResult,
    FPLPosition,
    GameweekScenario,
    PlayerScenario,
    PlayerScore,
)
from dmf_pulse.rules.scoring import score_fixture


@pytest.fixture
def scoring_inputs(repository_root: Path):
    root = repository_root / "fixtures/rules/RUL-002"
    ruleset = compile_ruleset(root / "synthetic_complete")
    value = json.loads((root / "golden_fixture_001.json").read_text("utf-8"))
    return ruleset, value


@pytest.mark.unit
def test_appearance_pass_and_group_boundaries(scoring_inputs) -> None:
    ruleset, value = scoring_inputs
    player = PlayerScenario.model_validate(value["players"][0])
    assert (
        calculate_bps(
            ruleset,
            player.model_copy(update={"minutes": 60}),
            clean_sheet_eligible=False,
            goals_conceded=0,
        )
        == 32
    )
    assert (
        calculate_bps(
            ruleset,
            player.model_copy(update={"minutes": 61}),
            clean_sheet_eligible=False,
            goals_conceded=0,
        )
        == 35
    )
    base_bps = player.bps.model_dump()
    expected = {70: 2, 80: 4, 90: 6}
    for percentage, award in expected.items():
        bps = BpsEvents.model_validate(
            {**base_bps, "pass_attempts": 100, "passes_completed": percentage}
        )
        plain = player.model_copy(
            update={
                "goals_non_penalty": 0,
                "bps": bps.model_copy(update={"match_winning_goals": 0, "shots_on_target": 0}),
            }
        )
        assert (
            calculate_bps(ruleset, plain, clean_sheet_eligible=False, goals_conceded=0) == 6 + award
        )
    under_attempts = player.model_copy(
        update={
            "goals_non_penalty": 0,
            "bps": player.bps.model_copy(
                update={
                    "pass_attempts": 29,
                    "passes_completed": 29,
                    "match_winning_goals": 0,
                    "shots_on_target": 0,
                }
            ),
        }
    )
    assert calculate_bps(ruleset, under_attempts, clean_sheet_eligible=False, goals_conceded=0) == 6


@pytest.mark.unit
def test_all_configured_positive_and_negative_bps_categories_are_additive(scoring_inputs) -> None:
    ruleset, value = scoring_inputs
    raw = value["players"][3]
    raw.update(
        minutes=90,
        goals_non_penalty=0,
        goals_penalty=1,
        eligible_assists=1,
        goals_conceded_while_eligible=2,
        penalty_saves=1,
        penalty_misses=1,
        yellow_cards=1,
        red_cards=1,
        dismissed=True,
        own_goals=1,
    )
    raw["defensive_actions"] = {
        "ball_recoveries": 0,
        "blocks": 2,
        "clearances": 2,
        "interceptions": 1,
        "tackles": 0,
    }
    raw["bps"] = {
        "big_chances_created": 1,
        "big_chances_missed": 1,
        "errors_leading_attempt": 1,
        "errors_leading_goal": 1,
        "fouls_conceded": 1,
        "fouls_won": 1,
        "goal_line_clearances": 1,
        "key_passes": 1,
        "match_winning_goals": 1,
        "offsides": 1,
        "pass_attempts": 30,
        "passes_completed": 21,
        "penalties_conceded": 1,
        "recoveries": 3,
        "saves_inside_box": 1,
        "saves_outside_box": 1,
        "shots_off_target": 1,
        "shots_on_target": 1,
        "successful_dribbles": 1,
        "successful_open_play_crosses": 1,
        "successful_tackles": 1,
        "times_tackled": 1,
    }
    player = PlayerScenario.model_validate(raw)
    result = calculate_bps(ruleset, player, clean_sheet_eligible=False, goals_conceded=2)
    assert result == 22
    # Mutation probes: grouped CBI and recoveries use floor division.
    assert (
        calculate_bps(
            ruleset,
            player.model_copy(
                update={
                    "defensive_actions": player.defensive_actions.model_copy(
                        update={"interceptions": 0}
                    )
                }
            ),
            clean_sheet_eligible=False,
            goals_conceded=2,
        )
        == result
    )
    assert (
        calculate_bps(
            ruleset,
            player.model_copy(update={"bps": player.bps.model_copy(update={"recoveries": 2})}),
            clean_sheet_eligible=False,
            goals_conceded=2,
        )
        == result - 1
    )


@pytest.mark.unit
def test_dismissal_continuation_and_component_deductions(scoring_inputs) -> None:
    ruleset, value = scoring_inputs
    raw = value["players"][3]
    raw.update(
        dismissed=True,
        team_goals_after_dismissal=2,
        goals_conceded_while_eligible=0,
        saves=7,
        penalty_saves=1,
        penalty_misses=1,
        yellow_cards=1,
        red_cards=1,
        own_goals=0,
    )
    value["players"][0]["bps"]["match_winning_goals"] = 0
    value["players"][5]["goals_non_penalty"] = 2
    value["players"][5]["bps"]["match_winning_goals"] = 1
    scenario = FixtureScenario.model_validate({**value, "away_goals": 2})
    result = score_fixture(ruleset, scenario).players["home-gk"]
    assert result.clean_sheet == 0
    assert result.goals_conceded == -1
    assert result.penalty_saves == 5
    assert result.penalty_misses == -2
    assert result.yellow_cards == -1 and result.red_cards == -3 and result.own_goals == 0


@pytest.mark.unit
def test_defensive_threshold_and_disabled_gk_paths(scoring_inputs) -> None:
    ruleset, value = scoring_inputs
    defender = value["players"][2]
    defender["defensive_actions"] = {
        "ball_recoveries": 0,
        "blocks": 0,
        "clearances": 8,
        "interceptions": 1,
        "tackles": 0,
    }
    goalkeeper = value["players"][3]
    goalkeeper["defensive_actions"] = {
        "ball_recoveries": 100,
        "blocks": 100,
        "clearances": 100,
        "interceptions": 100,
        "tackles": 100,
    }
    scenario = FixtureScenario.model_validate(value)
    scores = score_fixture(ruleset, scenario).players
    assert scores["home-def"].defensive_contributions == 0
    assert scores["home-gk"].defensive_contributions == 0


@pytest.mark.unit
def test_unknown_ruleset_scoring_and_invalid_scenarios_fail_closed(
    repository_root: Path, scoring_inputs
) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    target = compile_ruleset(root / "target_2026_27_partial")
    scenario = FixtureScenario.model_validate_json((root / "golden_fixture_001.json").read_bytes())
    assert score_fixture(target, scenario).players

    _, value = scoring_inputs
    player = value["players"][0]
    with pytest.raises(ValidationError):
        FixtureScenario.model_validate({**value, "away_team_id": value["home_team_id"]})
    with pytest.raises(ValidationError):
        FixtureScenario.model_validate({**value, "players": [player, player]})
    unrelated = {**player, "team_id": "THIRD"}
    with pytest.raises(ValidationError):
        FixtureScenario.model_validate({**value, "players": [unrelated]})
    excess = {**player, "goals_conceded_while_eligible": 2}
    with pytest.raises(ValidationError):
        FixtureScenario.model_validate({**value, "players": [excess]})
    with pytest.raises(ValidationError):
        PlayerScenario.model_validate({**player, "minutes": 0})
    with pytest.raises(ValidationError):
        PlayerScenario.model_validate(
            {**player, "dismissed": False, "team_goals_after_dismissal": 1}
        )
    with pytest.raises(ValidationError, match="red cards require dismissed"):
        PlayerScenario.model_validate({**player, "red_cards": 1, "dismissed": False})
    with pytest.raises(ValidationError, match="requires a red card"):
        PlayerScenario.model_validate({**player, "red_cards": 0, "dismissed": True})
    assert PlayerScenario.model_validate({**player, "red_cards": 1, "dismissed": True}).dismissed
    with pytest.raises(ValidationError):
        PlayerScenario.model_validate({**player, "eligible_assists": -1})
    with pytest.raises(ValidationError):
        FixtureScenario.model_validate({**value, "participant_universe_complete": False})


@pytest.mark.unit
def test_result_and_gameweek_model_invariants(scoring_inputs) -> None:
    _, value = scoring_inputs
    fixture = FixtureScenario.model_validate(value)
    other = fixture.model_copy(update={"fixture_id": "other"})
    with pytest.raises(ValidationError):
        GameweekScenario(gameweek_id=fixture.gameweek_id, fixtures=(fixture, fixture))
    with pytest.raises(ValidationError):
        GameweekScenario(gameweek_id="wrong", fixtures=(other,))
    with pytest.raises(ValidationError):
        PlayerScore(
            appearance=1,
            assists=0,
            bonus=0,
            bps=0,
            clean_sheet=0,
            defensive_contributions=0,
            goals=0,
            goals_conceded=0,
            own_goals=0,
            penalty_misses=0,
            penalty_saves=0,
            red_cards=0,
            saves=0,
            total=2,
            yellow_cards=0,
        )

    with pytest.raises(ValidationError, match="bonus must"):
        PlayerScore(
            appearance=1,
            assists=0,
            bonus=-1,
            bps=0,
            clean_sheet=0,
            defensive_contributions=0,
            goals=0,
            goals_conceded=0,
            own_goals=0,
            penalty_misses=0,
            penalty_saves=0,
            red_cards=0,
            saves=0,
            total=0,
            yellow_cards=0,
        )
    assert (
        PlayerScore(
            appearance=1,
            assists=0,
            bonus=5,
            bps=0,
            clean_sheet=0,
            defensive_contributions=0,
            goals=0,
            goals_conceded=0,
            own_goals=0,
            penalty_misses=0,
            penalty_saves=0,
            red_cards=0,
            saves=0,
            total=6,
            yellow_cards=0,
        ).bonus
        == 5
    )


@pytest.mark.unit
def test_appearance_and_position_goal_matrix(scoring_inputs) -> None:
    ruleset, value = scoring_inputs
    appearances = {0: (0, 0), 1: (1, 3), 59: (1, 3), 60: (2, 3), 90: (2, 6)}
    for minutes, (appearance, bps) in appearances.items():
        scenario_value = copy.deepcopy(value)
        player = next(item for item in scenario_value["players"] if item["player_id"] == "away-fwd")
        player.update(
            minutes=minutes,
            goals_non_penalty=0,
            goals_penalty=0,
            eligible_assists=0,
            goals_conceded_while_eligible=0,
            saves=0,
            penalty_saves=0,
            penalty_misses=0,
            yellow_cards=0,
            red_cards=0,
            own_goals=0,
            dismissed=False,
            team_goals_after_dismissal=0,
        )
        player["defensive_actions"] = {key: 0 for key in player["defensive_actions"]}
        player["bps"] = {key: 0 for key in player["bps"]}
        score = score_fixture(ruleset, FixtureScenario.model_validate(scenario_value)).players[
            "away-fwd"
        ]
        assert (score.appearance, score.bps) == (appearance, bps)

    goal_points = {
        FPLPosition.GK: (10, 23),
        FPLPosition.DEF: (6, 23),
        FPLPosition.MID: (5, 29),
        FPLPosition.FWD: (4, 35),
    }
    for position, (fpl_points, expected_bps) in goal_points.items():
        scenario_value = copy.deepcopy(value)
        raw = next(item for item in scenario_value["players"] if item["player_id"] == "home-fwd")
        raw["position"] = position.value
        scenario = FixtureScenario.model_validate(scenario_value)
        player = next(item for item in scenario.players if item.player_id == "home-fwd")
        score = score_fixture(ruleset, scenario).players["home-fwd"]
        assert score.goals == fpl_points
        assert (
            calculate_bps(
                ruleset,
                player,
                clean_sheet_eligible=False,
                goals_conceded=0,
            )
            == expected_bps
        )


@pytest.mark.unit
def test_every_fixture_coherence_false_success_is_rejected(scoring_inputs) -> None:
    ruleset, value = scoring_inputs

    post_dismissal = copy.deepcopy(value)
    post_dismissal["away_goals"] = 1
    goalkeeper = next(item for item in post_dismissal["players"] if item["player_id"] == "home-gk")
    goalkeeper.update(
        dismissed=True,
        red_cards=1,
        goals_conceded_while_eligible=1,
        team_goals_after_dismissal=1,
    )
    with pytest.raises(ValidationError, match="post-dismissal"):
        FixtureScenario.model_validate(post_dismissal)

    winner_without_goal = copy.deepcopy(value)
    next(item for item in winner_without_goal["players"] if item["player_id"] == "home-mid")["bps"][
        "match_winning_goals"
    ] = 1
    with pytest.raises(ValidationError, match="requires a scored goal"):
        FixtureScenario.model_validate(winner_without_goal)

    non_goalkeeper_save = copy.deepcopy(value)
    next(item for item in non_goalkeeper_save["players"] if item["player_id"] == "home-mid")[
        "saves"
    ] = 1
    assert FixtureScenario.model_validate(non_goalkeeper_save)

    with pytest.raises(ValidationError, match="reconcile"):
        FixtureScenario.model_validate({**value, "home_goals": 2})

    excess_assist = copy.deepcopy(value)
    next(item for item in excess_assist["players"] if item["player_id"] == "home-fwd")[
        "eligible_assists"
    ] = 2
    with pytest.raises(ValidationError, match="assists exceed"):
        FixtureScenario.model_validate(excess_assist)

    no_winner = copy.deepcopy(value)
    next(item for item in no_winner["players"] if item["player_id"] == "home-fwd")["bps"][
        "match_winning_goals"
    ] = 0
    with pytest.raises(ValidationError, match="winning goal events"):
        FixtureScenario.model_validate(no_winner)

    own_goal_winner = copy.deepcopy(value)
    forward = next(item for item in own_goal_winner["players"] if item["player_id"] == "home-fwd")
    forward["goals_non_penalty"] = 0
    forward["bps"]["match_winning_goals"] = 0
    midfielder = next(
        item for item in own_goal_winner["players"] if item["player_id"] == "home-mid"
    )
    midfielder["eligible_assists"] = 0
    away_defender = next(
        item for item in own_goal_winner["players"] if item["player_id"] == "away-def"
    )
    away_defender["own_goals"] = 1
    own_goal_fixture = FixtureScenario.model_validate(own_goal_winner)
    own_goal_result = score_fixture(ruleset, own_goal_fixture)
    assert own_goal_result.sum_player_totals == 29
    assert own_goal_result.players["home-fwd"].bps == 8

    mixed_own_goal_winner = copy.deepcopy(value)
    mixed_own_goal_winner["home_goals"] = 2
    mixed_own_goal_winner["away_goals"] = 1
    next(item for item in mixed_own_goal_winner["players"] if item["player_id"] == "home-fwd")[
        "bps"
    ]["match_winning_goals"] = 0
    mixed_away_defender = next(
        item for item in mixed_own_goal_winner["players"] if item["player_id"] == "away-def"
    )
    mixed_away_defender["goals_non_penalty"] = 1
    mixed_away_defender["own_goals"] = 1
    mixed_fixture = FixtureScenario.model_validate(mixed_own_goal_winner)
    assert mixed_fixture.home_goals > mixed_fixture.away_goals

    result = score_fixture(ruleset, FixtureScenario.model_validate(value)).model_dump(mode="json")
    result["sum_player_totals"] += 1
    with pytest.raises(ValidationError, match="fixture total"):
        FixtureScoreResult.model_validate(result)


@pytest.mark.unit
def test_ruleset_identity_status_and_save_cap_are_enforced(
    repository_root: Path, scoring_inputs, tmp_path: Path
) -> None:
    ruleset, value = scoring_inputs
    scenario = FixtureScenario.model_validate(value)
    matching = scenario.model_copy(
        update={
            "ruleset_id": ruleset.ruleset_id,
            "ruleset_version": ruleset.ruleset_version,
            "ruleset_hash": ruleset.ruleset_hash,
        }
    )
    assert score_fixture(ruleset, matching).ruleset_hash == ruleset.ruleset_hash
    mismatch = scenario.model_copy(update={"ruleset_id": "another-ruleset"})
    with pytest.raises(RulesValidationError) as identity:
        score_fixture(ruleset, mismatch)
    assert identity.value.code == "RULESET_SCENARIO_MISMATCH"

    source = tmp_path / "draft"
    shutil.copytree(
        repository_root / "fixtures/rules/RUL-002/synthetic_complete",
        source,
    )
    manifest = source / "season_manifest.yaml"
    manifest.write_text(
        manifest.read_text("utf-8").replace(
            'status: "REFERENCE_ONLY"', 'status: "DRAFT_PRELAUNCH"'
        ),
        encoding="utf-8",
    )
    draft = compile_ruleset(source)
    with pytest.raises(RulesValidationError) as status:
        score_fixture(draft, scenario)
    assert status.value.code == "RULESET_SCORING_BLOCKED"

    capped_source = tmp_path / "capped"
    shutil.copytree(
        repository_root / "fixtures/rules/RUL-002/synthetic_complete",
        capped_source,
    )
    scoring = capped_source / "scoring.yaml"
    scoring.write_text(
        scoring.read_text("utf-8").replace("cap_per_fixture: null", "cap_per_fixture: 1"),
        encoding="utf-8",
    )
    capped = compile_ruleset(capped_source)
    assert score_fixture(capped, scenario).players["home-gk"].saves == 1
