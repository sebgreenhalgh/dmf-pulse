"""Immutable v1.1 fixture and Gameweek scoring oracles."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from dmf_pulse.rules.aggregation import score_gameweek
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.models import FixtureScenario, GameweekScenario
from dmf_pulse.rules.scoring import score_fixture


def _expected(path: Path, ruleset_hash: str) -> dict[str, object]:
    value: dict[str, object] = json.loads(path.read_text("utf-8"))
    value["ruleset_hash"] = ruleset_hash
    return value


@pytest.mark.golden
def test_corrected_v11_fixture_oracle_matches_exactly(repository_root: Path) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    ruleset = compile_ruleset(root / "synthetic_complete")
    scenario = FixtureScenario.model_validate_json((root / "golden_fixture_001.json").read_bytes())
    result = score_fixture(ruleset, scenario)
    assert result.model_dump(mode="json") == _expected(
        root / "golden_fixture_001.expected.json", ruleset.ruleset_hash
    )
    assert result.players["home-def"].bps == 27
    assert result.players["home-gk"].bonus == 1
    assert result.sum_player_totals == 38


@pytest.mark.golden
def test_corrected_v11_gameweek_oracle_matches_exactly(repository_root: Path) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    ruleset = compile_ruleset(root / "synthetic_complete")
    scenario = GameweekScenario.model_validate_json(
        (root / "golden_gameweek_001.json").read_bytes()
    )
    result = score_gameweek(ruleset, scenario)
    legacy = {
        key: value
        for key, value in result.model_dump(mode="json").items()
        if key in {"fixture_ids", "gameweek_id", "player_totals", "ruleset_hash", "ruleset_id"}
    }
    assert legacy == _expected(root / "golden_gameweek_001.expected.json", ruleset.ruleset_hash)
    assert result.player_totals["home-fwd"] == 14
    assert result.players["home-fwd"].bonus == 6
    assert result.players["home-fwd"].bps == 38
    assert result.ruleset_version == ruleset.ruleset_version
    assert len(result.fixture_results) == 2
    assert result.fixture_results[0].fixture_id == "synthetic-fixture-001"


@pytest.mark.golden
def test_gameweek_public_result_blank_one_and_two_fixture_boundaries(
    repository_root: Path,
) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    ruleset = compile_ruleset(root / "synthetic_complete")
    value = json.loads((root / "golden_gameweek_001.json").read_text("utf-8"))

    blank = score_gameweek(
        ruleset,
        GameweekScenario(gameweek_id="blank-gw", fixtures=()),
    )
    assert blank.fixture_results == ()
    assert blank.players == {}
    assert blank.player_totals == {}

    one_scenario = GameweekScenario.model_validate(
        {"gameweek_id": value["gameweek_id"], "fixtures": value["fixtures"][:1]}
    )
    one = score_gameweek(ruleset, one_scenario)
    assert one.fixture_ids == ("synthetic-fixture-001",)
    assert one.fixture_results[0].players == one.players

    two_value = copy.deepcopy(value)
    second_only = next(
        player
        for player in two_value["fixtures"][1]["players"]
        if player["player_id"] == "away-fwd"
    )
    second_only["player_id"] = "second-only-player"
    two_value["fixtures"].reverse()
    two = score_gameweek(ruleset, GameweekScenario.model_validate(two_value))
    assert two.fixture_ids == ("synthetic-fixture-001", "synthetic-fixture-002")
    assert two.players["away-fwd"].total == 2
    assert two.players["second-only-player"].total == 0
    assert two.players["home-fwd"].model_dump(mode="json") == {
        "appearance": 4,
        "assists": 0,
        "bonus": 6,
        "bps": 38,
        "clean_sheet": 0,
        "defensive_contributions": 0,
        "goals": 4,
        "goals_conceded": 0,
        "own_goals": 0,
        "penalty_misses": 0,
        "penalty_saves": 0,
        "red_cards": 0,
        "saves": 0,
        "total": 14,
        "yellow_cards": 0,
    }
