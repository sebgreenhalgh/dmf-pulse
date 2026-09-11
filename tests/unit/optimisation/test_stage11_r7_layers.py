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


@pytest.mark.parametrize("limit_field", ["max_policy_candidates", "max_state_expansions"])
def test_shared_budget_cannot_relax_the_sealed_policy_limits(limit_field):
    from dmf_pulse.optimisation.multi_gameweek_solver import Stage11WorkBudget

    request, _, _, points = oracle_fixture()
    request = with_candidates(request, (request.initial_state.squad_ids[0],))
    policy = seal_search_policy(request.search_policy.model_copy(update={limit_field: 1}))
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    evaluator = HorizonPointsEvaluator(points)
    with pytest.raises(ResourceLimitReached, match="before tactical evaluation"):
        solve_frontier(
            request,
            evaluator,
            prefer_deterministic_linear=True,
            work_budget=Stage11WorkBudget(999999, 999999),
        )
    assert not evaluator.batch_calls


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
    exported = profile.as_dict()
    assert exported["cumulative_legal_actions"] == 3
    assert exported["cumulative_legal_action_limit"] == 10


def test_individual_tactical_cpu_counter_counts_work_once_without_changing_value(monkeypatch):
    from dmf_pulse.private_v1.service import _MemoizedStage10Evaluator

    request, _, _, points = oracle_fixture()
    delegate = HorizonPointsEvaluator(points)
    evaluator = _MemoizedStage10Evaluator(delegate)
    ticks = iter((10.0, 12.0))
    monkeypatch.setattr("dmf_pulse.private_v1.service.process_time", lambda: next(ticks))
    node, state = request.scenario_tree.root, request.initial_state
    actual = evaluator.evaluate(node=node, state=state)
    assert actual == delegate._value(node, state.squad_ids)
    assert evaluator.evaluate(node=node, state=state) is actual
    counts = evaluator.counters_by_node[node.node_id]
    assert counts.evaluation_cpu_seconds == 2.0
    assert counts.evaluated_squads == counts.individual_calls == 1
    assert counts.cache_hits == 1


@pytest.mark.parametrize(
    "field,limit,complete",
    [
        ("max_policy_candidates", 4, False),
        ("max_policy_candidates", 6, True),
        ("max_state_expansions", 3, False),
        ("max_state_expansions", 4, True),
    ],
)
def test_public_solve_budget_and_diagnostics_include_no_transfer_baseline(field, limit, complete):
    from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek

    request, _, _, points = oracle_fixture()
    request = with_candidates(request, (request.initial_state.squad_ids[0],))
    policy = seal_search_policy(request.search_policy.model_copy(update={field: limit}))
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    profile = Stage11SearchProfile()
    result = optimise_multi_gameweek(
        request,
        evaluator=HorizonPointsEvaluator(points),
        prefer_deterministic_linear=True,
        profile=profile,
    )
    if not complete:
        assert result.status.value == "ERROR"
        assert result.recommended_plan is None
        assert profile.as_dict()["cumulative_legal_actions"] == 5
    else:
        assert result.status.value == "SUCCESS"
        assert profile.as_dict()["cumulative_legal_actions"] == 6
        generic = optimise_multi_gameweek(request, evaluator=HorizonPointsEvaluator(points))
        assert result == generic
