"""Deterministic property tests for ranking and Gameweek aggregation."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.rules.aggregation import score_gameweek
from dmf_pulse.rules.bonus import allocate_bonus
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import GameweekScenario


@pytest.mark.property
@given(
    st.dictionaries(
        st.text(min_size=1, max_size=8), st.integers(-100, 100), min_size=1, max_size=20
    )
)
def test_bonus_is_bounded_and_equal_bps_always_ties(scores: dict[str, int]) -> None:
    awards = allocate_bonus(scores, {1: 3, 2: 2, 3: 1})
    assert set(awards) == set(scores)
    assert set(awards.values()) <= {0, 1, 2, 3}
    for left, left_score in scores.items():
        for right, right_score in scores.items():
            if left_score == right_score:
                assert awards[left] == awards[right]


@pytest.mark.property
@given(
    st.dictionaries(
        st.text(min_size=1, max_size=8).filter(lambda value: value != "new-low-player"),
        st.integers(-100, 100),
        min_size=1,
        max_size=20,
    )
)
def test_adding_a_player_below_every_rank_never_changes_existing_awards(
    scores: dict[str, int],
) -> None:
    policy = {1: 3, 2: 2, 3: 1}
    before = allocate_bonus(scores, policy)
    after = allocate_bonus({**scores, "new-low-player": min(scores.values()) - 1}, policy)
    assert {player: after[player] for player in scores} == before


@pytest.mark.property
def test_fixture_order_does_not_change_gameweek_sums(repository_root: Path) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    ruleset = compile_ruleset(root / "synthetic_complete")
    scenario = GameweekScenario.model_validate_json(
        (root / "golden_gameweek_001.json").read_bytes()
    )
    reversed_scenario = scenario.model_copy(update={"fixtures": tuple(reversed(scenario.fixtures))})
    assert (
        score_gameweek(ruleset, scenario).player_totals
        == score_gameweek(ruleset, reversed_scenario).player_totals
    )
    bound = scenario.model_copy(
        update={
            "ruleset_id": ruleset.ruleset_id,
            "ruleset_version": ruleset.ruleset_version,
            "ruleset_hash": ruleset.ruleset_hash,
        }
    )
    assert (
        score_gameweek(ruleset, bound).player_totals
        == score_gameweek(ruleset, scenario).player_totals
    )
    with pytest.raises(RulesValidationError) as mismatch:
        score_gameweek(ruleset, scenario.model_copy(update={"ruleset_hash": "0" * 64}))
    assert mismatch.value.code == "RULESET_SCENARIO_MISMATCH"

    target = compile_ruleset(root / "target_2026_27_partial")
    empty = GameweekScenario(gameweek_id="blank", fixtures=())
    with pytest.raises(RulesValidationError) as blocked:
        score_gameweek(target, empty)
    assert blocked.value.code == "RULESET_SCORING_BLOCKED"
