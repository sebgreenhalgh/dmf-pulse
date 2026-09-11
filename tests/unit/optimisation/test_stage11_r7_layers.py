"""Physical node-wide batching cannot change complete exact frontiers."""

import pytest

from dmf_pulse.optimisation.multi_gameweek_errors import ResourceLimitReached
from dmf_pulse.optimisation.multi_gameweek_models import (
    PlayerPriceState,
    seal_request,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_solver import Stage11SearchProfile, solve_frontier
from tests.unit.private_v1.horizon_oracle_support import (
    HorizonPointsEvaluator,
    oracle_fixture,
    with_candidates,
)


def test_one_pending_tactical_batch_per_node_and_complete_generic_equality():
    request, _, _, points = oracle_fixture("budget")
    evaluator = HorizonPointsEvaluator(points)
    accelerated = solve_frontier(request, evaluator, prefer_deterministic_linear=True)
    generic = solve_frontier(request, HorizonPointsEvaluator(points))
    assert accelerated.complete and generic.complete
    assert accelerated.candidates == generic.candidates
    assert evaluator.batch_calls == {node.node_id: 1 for node in request.scenario_tree.nodes}


@pytest.mark.parametrize("limit_field", ["max_policy_candidates", "max_state_expansions"])
def test_cumulative_work_limits_fail_before_any_tactical_batch(limit_field):
    request, _, _, points = oracle_fixture("budget")
    policy = seal_search_policy(request.search_policy.model_copy(update={limit_field: 1}))
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    evaluator = HorizonPointsEvaluator(points)
    with pytest.raises(ResourceLimitReached, match="before tactical evaluation"):
        solve_frontier(request, evaluator, prefer_deterministic_linear=True)
    assert not evaluator.batch_calls
    assert not evaluator.cache


def test_rejected_combinations_do_not_consume_retained_legal_action_envelope():
    request, incoming, _, points = oracle_fixture()
    prices = dict(request.scenario_tree.root.prices)
    for player_id in incoming:
        prices[player_id] = PlayerPriceState(current_price_tenths=10000)
    request = with_candidates(request, incoming, prices=prices)
    policy = seal_search_policy(
        request.search_policy.model_copy(update={"max_policy_candidates": 10})
    )
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    profile = Stage11SearchProfile()
    result = solve_frontier(
        request, HorizonPointsEvaluator(points), prefer_deterministic_linear=True, profile=profile
    )
    assert result.complete
    assert sum(n.action_combinations_considered for n in profile.nodes.values()) > 10
    assert sum(n.legal_actions_generated for n in profile.nodes.values()) == 3
