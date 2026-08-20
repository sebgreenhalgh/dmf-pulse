from __future__ import annotations

import pytest

from dmf_pulse.rank_strategy.manager_multipliers import calculate_manager_multipliers
from dmf_pulse.rank_strategy.opponent_actions import (
    combine_opponent_action_distributions,
    model_opponent_actions,
)
from dmf_pulse.rank_strategy.opponent_models import OpponentChipAction
from tests.support.opponent_action_fixtures import (
    baseline_candidates,
    behaviour_profile,
    candidate,
    observed_state,
)
from tests.support.rank_strategy_fixtures import (
    multiplier_policy,
    rank_players,
    rank_rules,
    scenario_set,
)

pytestmark = pytest.mark.integration


def _score_all_hidden_actions(manager_id: str):
    distribution = model_opponent_actions(
        observed_state(manager_id),
        (
            *baseline_candidates(manager_id),
            candidate(
                "free-hit",
                manager_id=manager_id,
                expected_points=56.0,
                transfer_count=3,
                chip=OpponentChipAction.FREE_HIT,
            ),
        ),
        behaviour_profile(manager_id),
    )
    shared = scenario_set(
        {f"p{index:02d}": index % 6 for index in range(16)},
        {f"p{index:02d}": (15 - index) % 7 for index in range(16)},
        weights=(0.4, 0.6),
        include_extra=True,
    )
    scored = {
        action.action_id: calculate_manager_multipliers(
            action.manager_plan,
            shared,
            rank_players(include_extra=True),
            rank_rules(),
            multiplier_policy(),
        )
        for action in distribution.actions
    }
    return distribution, shared, scored


def test_every_hidden_rival_action_reuses_identical_raw_football_scenarios() -> None:
    distribution, shared, scored = _score_all_hidden_actions("rival")

    expected_projection_hashes = {item.raw_projection_hash for item in scored.values()}
    expected_scenario_hashes = {item.scenario_set_hash for item in scored.values()}
    expected_identities = {
        tuple(
            (scenario.scenario_id, scenario.outcome_draw_id, scenario.weight)
            for scenario in item.scenarios
        )
        for item in scored.values()
    }
    assert len(expected_projection_hashes) == 1
    assert len(expected_scenario_hashes) == 1
    assert len(expected_identities) == 1
    assert next(iter(expected_identities)) == tuple(
        (scenario.scenario_id, scenario.outcome_draw_id, scenario.weight)
        for scenario in shared.scenarios
    )
    assert sum(item.probability for item in distribution.actions) == pytest.approx(1.0)


def test_multiple_rivals_share_action_uncertainty_but_not_independent_football_draws() -> None:
    first, shared, first_scored = _score_all_hidden_actions("rival-a")
    second, same_shared, second_scored = _score_all_hidden_actions("rival-b")
    joint = combine_opponent_action_distributions((first, second))

    assert shared == same_shared
    all_sets = (*first_scored.values(), *second_scored.values())
    assert len({item.raw_projection_hash for item in all_sets}) == 1
    assert len({item.scenario_set_hash for item in all_sets}) == 1
    expected_football_identities = tuple(
        (scenario.scenario_id, scenario.outcome_draw_id) for scenario in shared.scenarios
    )
    assert all(
        tuple((scenario.scenario_id, scenario.outcome_draw_id) for scenario in item.scenarios)
        == expected_football_identities
        for item in all_sets
    )
    assert len(joint.scenarios) == len(first.actions) * len(second.actions)
    assert sum(item.probability for item in joint.scenarios) == pytest.approx(1.0)


def test_hidden_captain_chip_and_transfer_actions_change_only_manager_decisions() -> None:
    distribution, _, scored = _score_all_hidden_actions("rival")
    raw_hash = next(iter(scored.values())).raw_projection_hash
    expected_points = {action_id: item.expected_net_points for action_id, item in scored.items()}

    assert len(set(expected_points.values())) > 1
    assert all(item.raw_projection_hash == raw_hash for item in scored.values())
    assert any(
        action.chip_action is OpponentChipAction.TRIPLE_CAPTAIN for action in distribution.actions
    )
    assert any(action.transfer_count > 0 for action in distribution.actions)
