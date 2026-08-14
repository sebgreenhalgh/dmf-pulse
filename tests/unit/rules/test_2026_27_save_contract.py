"""Exact 2026/27 save and BPS contract regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmf_pulse.fpl_points.models import (
    BpsEvents as Stage9BpsEvents,
)
from dmf_pulse.fpl_points.models import (
    DefensiveActions as Stage9DefensiveActions,
)
from dmf_pulse.fpl_points.models import (
    FixtureEventScenario,
    PlayerEventVector,
    PlayerPosition,
)
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter
from dmf_pulse.rules.bps import calculate_bps
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.models import (
    BpsEvents,
    DefensiveActions,
    FixtureScenario,
    FPLPosition,
    PlayerScenario,
    validate_v11_save_contract,
)
from dmf_pulse.rules.scoring import score_fixture


def _compiled(repository_root: Path):
    return compile_ruleset(repository_root / "fixtures/rules/RUL-002/target_2026_27_partial")


def _player(
    *,
    position: FPLPosition = FPLPosition.GK,
    saves: int = 0,
    penalty_saves: int = 0,
    **bps_updates: int,
) -> PlayerScenario:
    bps = BpsEvents.model_validate(
        {name: bps_updates.get(name, 0) for name in BpsEvents.model_fields}
    )
    return PlayerScenario(
        player_id="player",
        team_id="HOME",
        position=position,
        minutes=90,
        goals_non_penalty=0,
        goals_penalty=0,
        eligible_assists=0,
        goals_conceded_while_eligible=0,
        saves=saves,
        penalty_saves=penalty_saves,
        penalty_misses=0,
        yellow_cards=0,
        red_cards=0,
        own_goals=0,
        defensive_actions=DefensiveActions(
            ball_recoveries=0, blocks=0, clearances=0, interceptions=0, tackles=0
        ),
        bps=bps,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("saves", "penalties", "bps_updates", "expected"),
    (
        (1, 0, {"saves_outside_box": 1}, 8),
        (1, 0, {"saves_inside_box": 1}, 9),
        (1, 0, {"big_chance_saves": 1}, 9),
        (1, 0, {"saves_inside_box": 1, "big_chance_saves": 1}, 10),
        (1, 0, {}, 8),
        (1, 1, {"saves_inside_box": 1, "big_chance_saves": 1}, 17),
    ),
    ids=("outside", "inside", "big-chance", "inside-big-chance", "neutral", "penalty"),
)
def test_2026_27_save_bps_composes_from_total_and_declared_subsets(
    repository_root: Path, saves: int, penalties: int, bps_updates: dict[str, int], expected: int
) -> None:
    assert (
        calculate_bps(
            _compiled(repository_root),
            _player(saves=saves, penalty_saves=penalties, **bps_updates),
            clean_sheet_eligible=False,
            goals_conceded=0,
        )
        == expected
    )


@pytest.mark.unit
def test_three_total_saves_award_one_fpl_save_point(repository_root: Path) -> None:
    compiled = _compiled(repository_root)
    player = _player(saves=3, saves_inside_box=1, saves_outside_box=1)
    fixture = FixtureScenario(
        fixture_id="save-fixture",
        gameweek_id="GW1",
        home_team_id="HOME",
        away_team_id="AWAY",
        home_goals=0,
        away_goals=0,
        participant_universe_complete=True,
        players=(player,),
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
    )
    assert score_fixture(compiled, fixture).players["player"].saves == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs",
    (
        {"saves": 1, "saves_inside_box": 1, "saves_outside_box": 1},
        {"saves": 1, "big_chance_saves": 2},
        {"saves": 1, "penalty_saves": 2, "saves_inside_box": 1, "big_chance_saves": 1},
        {"saves": 1, "penalty_saves": 1, "big_chance_saves": 1},
        {"saves": 1, "penalty_saves": 1, "saves_inside_box": 1},
    ),
)
def test_save_subset_contradictions_are_rejected(kwargs: dict[str, int]) -> None:
    penalty_saves = kwargs.pop("penalty_saves", 0)
    player = _player(penalty_saves=penalty_saves, **kwargs)
    with pytest.raises(ValueError):
        validate_v11_save_contract(player)


@pytest.mark.unit
def test_non_gk_save_events_and_big_chance_save_survive_stage9_adapter(
    repository_root: Path,
) -> None:
    compiled = _compiled(repository_root)
    bps = Stage9BpsEvents.model_validate(
        {name: int(name == "big_chance_saves") for name in Stage9BpsEvents.model_fields}
    )
    event_player = PlayerEventVector(
        player_id="mid-keeper",
        team_id="HOME",
        position=PlayerPosition.MID,
        minutes=90,
        goals_non_penalty=0,
        goals_penalty=0,
        eligible_assists=0,
        goals_conceded_while_eligible=0,
        saves=1,
        penalty_saves=0,
        penalty_misses=0,
        yellow_cards=0,
        red_cards=0,
        own_goals=0,
        defensive_actions=Stage9DefensiveActions(
            ball_recoveries=0, blocks=0, clearances=0, interceptions=0, tackles=0
        ),
        bps=bps,
        dismissed=False,
        team_goals_after_dismissal=0,
        auxiliary_source_tag="TEST_SYNTHETIC",
    )
    scenario = FixtureEventScenario(
        fixture_id="adapter-save",
        gameweek_id="GW1",
        home_team_id="HOME",
        away_team_id="AWAY",
        home_goals=0,
        away_goals=0,
        participant_universe_complete=True,
        players=(event_player,),
        goals=(),
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
    )
    score = AcceptedRulesAdapter(compiled).score_fixture(scenario)["mid-keeper"]
    assert score.bps == 9
