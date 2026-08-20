from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.opponent_actions import (
    combine_opponent_action_distributions,
    model_opponent_actions,
)
from dmf_pulse.rank_strategy.opponent_models import JointOpponentActionDistribution
from tests.support.opponent_action_fixtures import (
    baseline_candidates,
    behaviour_profile,
    observed_state,
)

pytestmark = pytest.mark.unit


def _distribution(manager_id: str):
    return model_opponent_actions(
        observed_state(manager_id),
        baseline_candidates(manager_id),
        behaviour_profile(manager_id),
    )


def test_joint_distribution_is_exact_cartesian_product_with_product_probabilities() -> None:
    first = _distribution("rival-a")
    second = _distribution("rival-b")
    result = combine_opponent_action_distributions((second, first))

    assert result.manager_ids == ("rival-a", "rival-b")
    assert len(result.scenarios) == len(first.actions) * len(second.actions)
    assert sum(item.probability for item in result.scenarios) == pytest.approx(1.0)
    assert tuple(item.scenario_id for item in result.scenarios) == tuple(
        sorted(item.scenario_id for item in result.scenarios)
    )
    first_probs = {item.action_id: item.probability for item in first.actions}
    second_probs = {item.action_id: item.probability for item in second.actions}
    for scenario in result.scenarios:
        expected = (
            first_probs[scenario.action_ids["rival-a"]]
            * second_probs[scenario.action_ids["rival-b"]]
        )
        assert scenario.probability == pytest.approx(expected)
        assert tuple(scenario.action_ids) == result.manager_ids
        assert tuple(scenario.manager_plans) == result.manager_ids


def test_joint_distribution_preserves_each_marginal_exactly() -> None:
    first = _distribution("rival-a")
    second = _distribution("rival-b")
    result = combine_opponent_action_distributions((first, second))

    for distribution in (first, second):
        expected = {item.action_id: item.probability for item in distribution.actions}
        actual = {
            action_id: sum(
                scenario.probability
                for scenario in result.scenarios
                if scenario.action_ids[distribution.manager_id] == action_id
            )
            for action_id in expected
        }
        assert actual == pytest.approx(expected)


def test_joint_distribution_boundary_fails_closed() -> None:
    first = _distribution("rival-a")
    second = _distribution("rival-b")

    with pytest.raises(RankStrategyError) as exc_info:
        combine_opponent_action_distributions(())
    assert exc_info.value.code == "RANK_OPPONENT_DISTRIBUTIONS_EMPTY"

    with pytest.raises(RankStrategyError) as exc_info:
        combine_opponent_action_distributions((first,), max_joint_scenarios=0)
    assert exc_info.value.code == "RANK_OPPONENT_JOINT_LIMIT_INVALID"

    with pytest.raises(RankStrategyError) as exc_info:
        combine_opponent_action_distributions((first, first))
    assert exc_info.value.code == "RANK_OPPONENT_DISTRIBUTION_DUPLICATE_MANAGER"

    shifted = second.model_copy(
        update={
            "information_cutoff": second.information_cutoff - timedelta(minutes=1),
        }
    )
    with pytest.raises(RankStrategyError) as exc_info:
        combine_opponent_action_distributions((first, shifted))
    assert exc_info.value.code == "RANK_OPPONENT_JOINT_TEMPORAL_MISMATCH"

    with pytest.raises(RankStrategyError) as exc_info:
        combine_opponent_action_distributions((first, second), max_joint_scenarios=8)
    assert exc_info.value.code == "RANK_OPPONENT_JOINT_LIMIT_EXCEEDED"


def test_joint_contract_rejects_invalid_manager_and_probability_state() -> None:
    result = combine_opponent_action_distributions(
        (_distribution("rival-a"), _distribution("rival-b"))
    )
    mutations = (
        lambda payload: payload.update(manager_ids=tuple(reversed(payload["manager_ids"]))),
        lambda payload: payload.update(source_distribution_hashes={"rival-a": "0" * 64}),
        lambda payload: payload.update(
            scenarios=tuple({**item, "probability": 0.01} for item in payload["scenarios"])
        ),
        lambda payload: payload.update(scenarios=tuple(reversed(payload["scenarios"]))),
    )
    for mutation in mutations:
        payload = result.model_dump(mode="python")
        mutation(payload)
        with pytest.raises(ValidationError):
            JointOpponentActionDistribution.model_validate(payload)


def test_single_opponent_joint_distribution_is_valid_and_identical_to_source_vector() -> None:
    source = _distribution("rival-a")
    result = combine_opponent_action_distributions((source,))
    assert len(result.scenarios) == len(source.actions)
    actual = {scenario.action_ids["rival-a"]: scenario.probability for scenario in result.scenarios}
    expected = {item.action_id: item.probability for item in source.actions}
    assert actual == pytest.approx(expected)


def test_joint_distribution_rejects_stale_source_distribution_hash() -> None:
    source = _distribution("rival-a")
    changed_action = source.actions[0].model_copy(
        update={"probability": source.actions[0].probability + 0.01}
    )
    forged = source.model_copy(update={"actions": (changed_action, *source.actions[1:])})

    with pytest.raises(RankStrategyError) as exc_info:
        combine_opponent_action_distributions((forged,))
    assert exc_info.value.code == "RANK_OPPONENT_DISTRIBUTION_HASH_INVALID"
