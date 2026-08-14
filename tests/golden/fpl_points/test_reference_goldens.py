from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dmf_pulse.fpl_points.models import PlayerPosition
from tests.support.factories import (
    REFERENCE_RULESET,
    empty_bps,
    empty_defensive,
    event_fixture,
    event_player,
    reference_engine,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "fixtures/points/PTS-009"


def _player(raw: dict[str, object]):
    return event_player(
        str(raw["player_id"]),
        str(raw["team_id"]),
        PlayerPosition(str(raw["position"])),
        minutes=int(raw.get("minutes", 90)),
        goals_non_penalty=int(raw.get("goals_non_penalty", 0)),
        goals_penalty=int(raw.get("goals_penalty", 0)),
        assists=int(raw.get("assists", 0)),
        conceded=int(raw.get("conceded", 0)),
        saves=int(raw.get("saves", 0)),
        penalty_saves=int(raw.get("penalty_saves", 0)),
        penalty_misses=int(raw.get("penalty_misses", 0)),
        yellow=int(raw.get("yellow", 0)),
        red=int(raw.get("red", 0)),
        own_goals=int(raw.get("own_goals", 0)),
        defensive=empty_defensive(**dict(raw.get("defensive", {}))),
        bps=empty_bps(),
    )


def test_reference_golden_files_are_checksum_addressed() -> None:
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    for relative, metadata in manifest["files"].items():
        data = (FIXTURE_DIR / relative).read_bytes()
        assert len(data) == metadata["bytes"]
        assert hashlib.sha256(data).hexdigest() == metadata["sha256"]


def test_reference_rule_goldens_match_ruleset_driven_oracle() -> None:
    payload = json.loads((FIXTURE_DIR / "golden_cases.json").read_text(encoding="utf-8"))
    engine = reference_engine()
    assert payload["mode"] == "REFERENCE/TEST_ONLY"
    assert payload["ruleset_hash"] == engine.identity.ruleset_hash
    assert REFERENCE_RULESET.name == "reference_ruleset_test_only.json"
    expected_case_ids = {
        "zero_zero_appearance_clean_sheet",
        "two_one_scorer_assist",
        "goalkeeper_saves_penalty_save",
        "defensive_threshold",
        "card_and_own_goal",
        "bonus_tie_more_than_three",
        "substitute_minute_boundary",
        "negative_score",
    }
    assert {case["case_id"] for case in payload["cases"]} == expected_case_ids
    for case in payload["cases"]:
        fixture = event_fixture(
            home_goals=int(case["home_goals"]),
            away_goals=int(case["away_goals"]),
            players=tuple(_player(player) for player in case["players"]),
            fixture_id=f"GOLD-{case['case_id']}",
        )
        actual = {
            player_id: score.model_dump(mode="json")
            for player_id, score in sorted(engine.score_fixture(fixture).items())
        }
        assert actual == case["expected"]


def test_golden_negative_case_retains_negative_support() -> None:
    payload = json.loads((FIXTURE_DIR / "golden_cases.json").read_text(encoding="utf-8"))
    case = next(item for item in payload["cases"] if item["case_id"] == "negative_score")
    assert case["expected"]["h-def"]["total"] < 0


def test_golden_bonus_tie_awards_more_than_three_players() -> None:
    payload = json.loads((FIXTURE_DIR / "golden_cases.json").read_text(encoding="utf-8"))
    case = next(item for item in payload["cases"] if item["case_id"] == "bonus_tie_more_than_three")
    assert sum(score["bonus"] == 3 for score in case["expected"].values()) == 4
