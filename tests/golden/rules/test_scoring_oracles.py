"""Immutable v1.1 fixture and Gameweek scoring oracles."""

from __future__ import annotations

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
    assert result.model_dump(mode="json") == _expected(
        root / "golden_gameweek_001.expected.json", ruleset.ruleset_hash
    )
    assert result.player_totals["home-fwd"] == 14
    assert len(result.fixture_results) == 2
