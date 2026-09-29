"""Physical node-wide batching cannot change complete exact frontiers."""

import pytest

from dmf_pulse.optimisation.multi_gameweek_errors import ResourceLimitKind, ResourceLimitReached
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


def test_complete_frontier_reuses_exact_retained_no_transfer_root_family(monkeypatch):
    from dmf_pulse.optimisation import multi_gameweek_service as service
    from dmf_pulse.optimisation.multi_gameweek_models import ObjectiveMode
    from dmf_pulse.optimisation.multi_gameweek_solver import select_candidate

    request, _, _, points = oracle_fixture("budget")
    original = service.solve_frontier
    calls: list[bool] = []

    def counted(*args, **kwargs):
        calls.append(bool(kwargs.get("root_no_transfer_only")))
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "solve_frontier", counted)
    result = service.optimise_multi_gameweek(
        request,
        evaluator=HorizonPointsEvaluator(points),
        prefer_deterministic_linear=True,
    )
    assert result.status.value == "SUCCESS"
    assert calls == [False]
    independent = original(
        request,
        HorizonPointsEvaluator(points),
        root_no_transfer_only=True,
        prefer_deterministic_linear=True,
    )
    expected = select_candidate(independent.candidates, mode=ObjectiveMode.EXPECTED)
    baseline = result.no_transfer_baseline
    assert baseline is not None
    assert baseline.current_action == expected.root_decision
    assert baseline.future_policy == expected.decisions[1:]


@pytest.mark.parametrize("limit_field", ["max_cumulative_legal_actions", "max_state_expansions"])
def test_cumulative_work_limits_fail_before_any_tactical_batch(limit_field):
    request, _, _, points = oracle_fixture("budget")
    policy = seal_search_policy(request.search_policy.model_copy(update={limit_field: 1}))
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    evaluator = HorizonPointsEvaluator(points)
    with pytest.raises(ResourceLimitReached, match="before tactical evaluation") as caught:
        solve_frontier(request, evaluator, prefer_deterministic_linear=True)
    assert caught.value.kind is (
        ResourceLimitKind.CUMULATIVE_LEGAL_ACTION_LIMIT
        if limit_field == "max_cumulative_legal_actions"
        else ResourceLimitKind.LAYER_REACHABLE_STATE_LIMIT
    )
    if limit_field == "max_cumulative_legal_actions":
        assert caught.value.counters.cumulative_legal_actions > 1
        assert caught.value.counters.cumulative_legal_action_limit == 1
        work = caught.value.counters.layer_work
        assert len(work) == 1
        assert work[0].reachable_states == work[0].unique_economic_states == 1
        assert work[0].legal_actions_generated > 1
        assert set(work[0].model_dump()) == {
            "depth",
            "gameweek",
            "reachable_states",
            "unique_economic_states",
            "legal_actions_generated",
            "action_combinations_considered",
            "unique_resulting_squads",
        }
    else:
        assert caught.value.counters.reachable_layer_state_count > 1
    assert not evaluator.batch_calls
    assert not evaluator.cache


@pytest.mark.parametrize("limit_field", ["max_cumulative_legal_actions", "max_state_expansions"])
def test_shared_budget_cannot_relax_the_sealed_policy_limits(limit_field):
    from dmf_pulse.optimisation.multi_gameweek_solver import Stage11WorkBudget

    request, _, _, points = oracle_fixture()
    request = with_candidates(request, (request.initial_state.squad_ids[0],))
    policy = seal_search_policy(request.search_policy.model_copy(update={limit_field: 1}))
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    evaluator = HorizonPointsEvaluator(points)
    with pytest.raises(ResourceLimitReached, match="before tactical evaluation") as caught:
        solve_frontier(
            request,
            evaluator,
            prefer_deterministic_linear=True,
            work_budget=Stage11WorkBudget(999999, 999999),
        )
    assert caught.value.kind is (
        ResourceLimitKind.CUMULATIVE_LEGAL_ACTION_LIMIT
        if limit_field == "max_cumulative_legal_actions"
        else ResourceLimitKind.LAYER_REACHABLE_STATE_LIMIT
    )
    assert not evaluator.batch_calls


def test_rejected_combinations_do_not_consume_retained_legal_action_envelope():
    request, incoming, _, points = oracle_fixture()
    prices = dict(request.scenario_tree.root.prices)
    for player_id in incoming:
        prices[player_id] = PlayerPriceState(current_price_tenths=10000)
    request = with_candidates(request, incoming, prices=prices)
    policy = seal_search_policy(
        request.search_policy.model_copy(update={"max_cumulative_legal_actions": 10})
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
    "field,limit,complete,expected_actions",
    [
        ("max_cumulative_legal_actions", 2, False, 3),
        ("max_cumulative_legal_actions", 3, True, 3),
        ("max_state_expansions", 1, False, 2),
        ("max_state_expansions", 2, True, 3),
    ],
)
def test_public_solve_budget_and_diagnostics_include_no_transfer_baseline(
    field, limit, complete, expected_actions
):
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
        assert result.status.value == "RESOURCE_LIMIT"
        assert result.recommended_plan is None
        assert result.solver_status.resource_limit_kind is (
            ResourceLimitKind.CUMULATIVE_LEGAL_ACTION_LIMIT
            if field == "max_cumulative_legal_actions"
            else ResourceLimitKind.LAYER_REACHABLE_STATE_LIMIT
        )
        assert profile.as_dict()["cumulative_legal_actions"] == expected_actions
    else:
        assert result.status.value == "SUCCESS"
        assert profile.as_dict()["cumulative_legal_actions"] == expected_actions
        generic = optimise_multi_gameweek(request, evaluator=HorizonPointsEvaluator(points))
        assert result == generic


def test_policy_candidate_cap_is_not_reused_as_layered_legal_action_cap():
    request, _, _, points = oracle_fixture()
    request = with_candidates(request, (request.initial_state.squad_ids[0],))
    policy = seal_search_policy(
        request.search_policy.model_copy(
            update={"max_policy_candidates": 1, "max_cumulative_legal_actions": 100}
        )
    )
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    evaluator = HorizonPointsEvaluator(points)
    with pytest.raises(ResourceLimitReached) as caught:
        solve_frontier(request, evaluator, prefer_deterministic_linear=True)
    assert caught.value.kind is ResourceLimitKind.POLICY_GENERATION_LIMIT
    assert evaluator.batch_calls


@pytest.mark.parametrize(
    "policy_update,prefer_linear,expected_kind",
    [
        (
            {"max_actions_per_state": 1},
            True,
            ResourceLimitKind.PER_STATE_ACTION_COMBINATION_LIMIT,
        ),
        (
            {"max_state_expansions": 1},
            False,
            ResourceLimitKind.STATE_EXPANSION_LIMIT,
        ),
        (
            {"max_state_expansions": 1},
            True,
            ResourceLimitKind.LAYER_REACHABLE_STATE_LIMIT,
        ),
        (
            {"max_cumulative_legal_actions": 1},
            True,
            ResourceLimitKind.CUMULATIVE_LEGAL_ACTION_LIMIT,
        ),
        (
            {"max_policy_candidates": 1, "max_cumulative_legal_actions": 10000},
            True,
            ResourceLimitKind.POLICY_GENERATION_LIMIT,
        ),
        (
            {"max_returned_root_candidates": 1},
            True,
            ResourceLimitKind.ROOT_SUMMARY_LIMIT,
        ),
    ],
)
def test_exact_three_gameweek_resource_limit_matrix(
    policy_update,
    prefer_linear,
    expected_kind,
):
    from dmf_pulse.optimisation.multi_gameweek_models import (
        BackendStatus,
        MultiGameweekResultStatus,
    )
    from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek

    request, _, _, points = oracle_fixture()
    request = seal_request(
        request.model_copy(
            update={
                "search_policy": seal_search_policy(
                    request.search_policy.model_copy(update=policy_update)
                )
            }
        )
    )
    result = optimise_multi_gameweek(
        request,
        evaluator=HorizonPointsEvaluator(points),
        prefer_deterministic_linear=prefer_linear,
    )
    assert result.status is MultiGameweekResultStatus.RESOURCE_LIMIT
    assert result.solver_status.resource_limit_kind is expected_kind
    assert result.solver_status.observed_action_combinations is not None
    assert result.solver_status.configured_max_actions_per_state >= 1
    assert result.solver_status.configured_max_state_expansions >= 1
    assert result.solver_status.configured_max_policy_candidates >= 1
    assert result.solver_status.configured_max_returned_root_candidates >= 1
    assert result.solver_status.configured_cumulative_legal_action_limit >= 1
    with_incumbent = result.solver_status.status is BackendStatus.TIME_RESOURCE_LIMIT_WITH_INCUMBENT
    assert with_incumbent is (result.recommended_plan is not None)


def test_pareto_limit_is_structurally_dominated_in_exact_three_gameweek_search(
    monkeypatch,
):
    """The shared policy cap fires before its Pareto subset can exceed that same cap."""

    from dmf_pulse.optimisation import multi_gameweek_solver as solver

    request, _, _, points = oracle_fixture()
    observed: list[tuple[int, int, int]] = []
    original = solver._enforce_pareto_frontier_limit

    def checked(frontier, *, policy, counters):
        observed.append((len(frontier), counters.policy_candidates, policy.max_policy_candidates))
        assert len(frontier) <= counters.policy_candidates
        return original(frontier, policy=policy, counters=counters)

    monkeypatch.setattr(solver, "_enforce_pareto_frontier_limit", checked)
    result = solver.solve_frontier(request, HorizonPointsEvaluator(points))
    assert result.complete
    assert observed
    assert all(frontier <= generated <= cap for frontier, generated, cap in observed)


def test_complete_frontier_never_invokes_legacy_no_transfer_replay(monkeypatch):
    from dmf_pulse.optimisation import multi_gameweek_service as service
    from dmf_pulse.optimisation.multi_gameweek_models import (
        BackendStatus,
        MultiGameweekResultStatus,
        OptimalityGuarantee,
    )

    request, _, _, points = oracle_fixture()
    original = service.solve_frontier

    def incomplete_baseline(*args, **kwargs):
        frontier = original(*args, **kwargs)
        if kwargs.get("root_no_transfer_only"):
            diagnostics = frontier.diagnostics.model_copy(
                update={
                    "status": BackendStatus.TIME_RESOURCE_LIMIT_WITH_INCUMBENT,
                    "optimality_guarantee": OptimalityGuarantee.NONE,
                    "bound": None,
                    "absolute_gap": None,
                    "relative_gap": None,
                    "resource_limit_kind": ResourceLimitKind.ROOT_SUMMARY_LIMIT,
                    "configured_max_actions_per_state": (
                        request.search_policy.max_actions_per_state
                    ),
                    "configured_max_state_expansions": (request.search_policy.max_state_expansions),
                    "configured_max_policy_candidates": (
                        request.search_policy.max_policy_candidates
                    ),
                    "configured_max_returned_root_candidates": (
                        request.search_policy.max_returned_root_candidates
                    ),
                    "configured_cumulative_legal_action_limit": (
                        request.search_policy.cumulative_legal_action_limit
                    ),
                    "observed_action_combinations": 1,
                    "cumulative_legal_actions": 1,
                    "reachable_layer_state_count": 1,
                }
            )
            return type(frontier)(
                candidates=frontier.candidates,
                diagnostics=diagnostics,
                complete=False,
            )
        return frontier

    monkeypatch.setattr(service, "solve_frontier", incomplete_baseline)
    result = service.optimise_multi_gameweek(
        request,
        evaluator=HorizonPointsEvaluator(points),
        prefer_deterministic_linear=True,
    )
    assert result.status is MultiGameweekResultStatus.SUCCESS
    assert result.solver_status.status is BackendStatus.OPTIMAL
    assert result.no_transfer_baseline is not None


def test_preferred_but_ineligible_generic_path_retains_authenticated_baseline_replay(
    monkeypatch,
):
    from dmf_pulse.optimisation import multi_gameweek_service as service

    request, _, _, points = oracle_fixture()
    delegate = HorizonPointsEvaluator(points)

    class GenericOnlyEvaluator:
        def evaluate(self, *, node, state):
            return delegate.evaluate(node=node, state=state)

    original = service.solve_frontier
    calls: list[bool] = []

    def counted(*args, **kwargs):
        calls.append(bool(kwargs.get("root_no_transfer_only")))
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "solve_frontier", counted)
    preferred = service.optimise_multi_gameweek(
        request,
        evaluator=GenericOnlyEvaluator(),
        prefer_deterministic_linear=True,
    )
    assert calls == [False, True]
    calls.clear()
    generic = service.optimise_multi_gameweek(
        request,
        evaluator=GenericOnlyEvaluator(),
    )
    assert calls == [False, True]
    assert preferred == generic


def test_remediated_legal_work_envelope_is_exactly_equal_to_high_budget_reference(
    monkeypatch,
):
    from dmf_pulse.optimisation import multi_gameweek_service as service
    from dmf_pulse.optimisation.multi_gameweek_models import MultiGameweekResultStatus
    from dmf_pulse.optimisation.multi_gameweek_solver import (
        Stage11WorkBudget,
        enumerate_legal_actions,
    )

    request, _, _, points = oracle_fixture()
    request = with_candidates(request, (request.initial_state.squad_ids[0],))
    policy = seal_search_policy(
        request.search_policy.model_copy(update={"max_cumulative_legal_actions": 100})
    )
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    root = request.scenario_tree.root
    no_transfer = next(
        action
        for action in enumerate_legal_actions(
            request.initial_state,
            node=root,
            candidate_pool=request.candidate_pool,
            rules=request.rules,
            policy=request.search_policy,
        )
        if action.transfer_count == 0
    )
    actual_budget = Stage11WorkBudget

    monkeypatch.setattr(
        service,
        "Stage11WorkBudget",
        lambda _legal, state: actual_budget(2, state),
    )
    old_envelope = service.optimise_multi_gameweek(
        request,
        evaluator=HorizonPointsEvaluator(points),
        prefer_deterministic_linear=True,
        root_action_counterfactual=no_transfer,
    )
    assert old_envelope.status is MultiGameweekResultStatus.RESOURCE_LIMIT
    assert old_envelope.recommended_plan is None
    assert (
        old_envelope.solver_status.resource_limit_kind
        is ResourceLimitKind.CUMULATIVE_LEGAL_ACTION_LIMIT
    )

    monkeypatch.setattr(
        service,
        "Stage11WorkBudget",
        lambda _legal, state: actual_budget(6, state),
    )
    remediated = service.optimise_multi_gameweek(
        request,
        evaluator=HorizonPointsEvaluator(points),
        prefer_deterministic_linear=True,
        root_action_counterfactual=no_transfer,
    )
    monkeypatch.setattr(
        service,
        "Stage11WorkBudget",
        lambda _legal, state: actual_budget(100, state),
    )
    reference = service.optimise_multi_gameweek(
        request,
        evaluator=HorizonPointsEvaluator(points),
        prefer_deterministic_linear=True,
        root_action_counterfactual=no_transfer,
    )
    assert remediated.status is reference.status is MultiGameweekResultStatus.SUCCESS
    assert remediated == reference
    assert remediated.no_transfer_baseline is not None
    assert remediated.root_action_counterfactual_plan is not None
    assert remediated.transfer_count_frontier is not None
