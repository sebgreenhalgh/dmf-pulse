"""D7 generated-policy governance and lossless streaming-Pareto proofs."""

import importlib.util
import sys
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.optimisation.multi_gameweek_errors import ResourceLimitKind, ResourceLimitReached
from dmf_pulse.optimisation.multi_gameweek_models import (
    BackendStatus,
    MultiGameweekResultStatus,
    OptimalityGuarantee,
    SearchPolicy,
    SolverDiagnostics,
    seal_request,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.optimisation.multi_gameweek_solver import (
    SearchCounters,
    Stage11SearchProfile,
    _enforce_pareto_frontier_limit,
    _enforce_streaming_pareto_limit,
    _ExactParetoAccumulator,
    _pareto_frontier,
    _root_sufficient_candidates,
    _RootSufficientAccumulator,
    enumerate_legal_actions,
    solve_frontier,
)
from tests.unit.private_v1.horizon_oracle_support import HorizonPointsEvaluator, oracle_fixture

pytestmark = pytest.mark.unit

_PROFILE_SCRIPT = Path(__file__).resolve().parents[3] / "scripts/profile_live_scale_exact.py"
_PROFILE_SPEC = importlib.util.spec_from_file_location(
    "d7_profile_live_scale_exact", _PROFILE_SCRIPT
)
assert _PROFILE_SPEC is not None and _PROFILE_SPEC.loader is not None
_PROFILE_MODULE = importlib.util.module_from_spec(_PROFILE_SPEC)
sys.modules[_PROFILE_SPEC.name] = _PROFILE_MODULE
_PROFILE_SPEC.loader.exec_module(_PROFILE_MODULE)
_profile_squads = _PROFILE_MODULE._profile_squads
_resolve_policy_candidate_limits = _PROFILE_MODULE._resolve_policy_candidate_limits
_StatelessHorizonPointsEvaluator = _PROFILE_MODULE._StatelessHorizonPointsEvaluator
_decision_semantics = _PROFILE_MODULE._decision_semantics


def _v2_policy(policy: SearchPolicy, *, generated: int, retained: int) -> SearchPolicy:
    payload = policy.model_dump(mode="python")
    payload.update(
        {
            "schema_version": "multi-gameweek-search-policy-v2",
            "max_generated_policy_candidates": generated,
            "max_retained_pareto_candidates": retained,
            "max_cumulative_legal_actions": 10000,
            "policy_sha256": "0" * 64,
        }
    )
    payload.pop("max_policy_candidates")
    return seal_search_policy(SearchPolicy.model_validate(payload))


def _candidate_family():
    request, _, _, points = oracle_fixture("mixed")
    result = solve_frontier(request, HorizonPointsEvaluator(points))
    base = result.candidates[0]
    scores = (
        (8, 2, 9, "k-5"),
        (8, 2, 9, "k-1"),
        (9, 1, 8, "k-2"),
        (7, 7, 7, "k-3"),
        (6, 6, 6, "k-4"),
        (10, 0, 10, "k-0"),
    )
    return [
        replace(
            base,
            expected_score=Decimal(expected),
            conservative_score=Decimal(conservative),
            upside_score=Decimal(upside),
            tie_key=tie,
        )
        for expected, conservative, upside, tie in scores
    ]


def test_streaming_pareto_is_exact_and_deterministic() -> None:
    candidates = _candidate_family()
    expected = _pareto_frontier(candidates)
    for ordered in (candidates, list(reversed(candidates))):
        accumulator = _ExactParetoAccumulator()
        for candidate in ordered:
            accumulator.add(candidate)
        assert accumulator.values() == expected
        assert accumulator.evaluated == len(candidates)
        assert accumulator.peak_materialized <= len(candidates)
        assert accumulator.tie_equivalence_events == 1
        assert accumulator.strict_dominance_events + accumulator.tie_equivalence_events == len(
            candidates
        ) - len(expected)


def test_streaming_root_summary_equals_materialised_reference() -> None:
    candidates = _candidate_family()
    single = _RootSufficientAccumulator()
    single.add(candidates[0])
    assert single.peak_materialized == 1
    expected = _root_sufficient_candidates(candidates)
    for ordered in (candidates, list(reversed(candidates))):
        accumulator = _RootSufficientAccumulator()
        for candidate in ordered:
            accumulator.add(candidate)
        assert accumulator.values() == expected


def test_v2_generated_policy_limit_is_independent_from_retained_frontier() -> None:
    request, _, _, points = oracle_fixture("mixed")
    policy = _v2_policy(request.search_policy, generated=1, retained=1000)
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    with pytest.raises(ResourceLimitReached) as caught:
        profile = Stage11SearchProfile()
        solve_frontier(request, HorizonPointsEvaluator(points), profile=profile)
    assert caught.value.kind is ResourceLimitKind.POLICY_GENERATION_LIMIT
    assert caught.value.counters.policy_candidates == 2
    assert any(item.generated_policy_candidates > 0 for item in caught.value.counters.layer_work)

    public = optimise_multi_gameweek(
        request,
        evaluator=HorizonPointsEvaluator(points),
        prefer_deterministic_linear=True,
        profile=Stage11SearchProfile(),
    )
    assert public.status is MultiGameweekResultStatus.RESOURCE_LIMIT
    assert public.solver_status.resource_limit_kind is ResourceLimitKind.POLICY_GENERATION_LIMIT
    assert any(item.generated_policy_candidates > 0 for item in public.solver_status.layer_work)


def test_v2_retained_frontier_limit_has_its_own_typed_failure() -> None:
    request, _, _, _ = oracle_fixture("mixed")
    policy = _v2_policy(request.search_policy, generated=1000, retained=1)
    counters = SearchCounters(policy_candidates=2)
    frontier = tuple(_pareto_frontier(_candidate_family()))
    assert len(frontier) > 1
    with pytest.raises(ResourceLimitReached) as caught:
        _enforce_pareto_frontier_limit(frontier, policy=policy, counters=counters)
    assert caught.value.kind is ResourceLimitKind.PARETO_FRONTIER_LIMIT


def test_streaming_retained_limit_fails_at_transient_peak_not_only_final_size() -> None:
    request, _, _, _ = oracle_fixture("mixed")
    policy = _v2_policy(request.search_policy, generated=1000, retained=1)
    base = _candidate_family()[0]
    first = replace(
        base,
        expected_score=Decimal(1),
        conservative_score=Decimal(0),
        upside_score=Decimal(0),
        tie_key="transient-a",
    )
    second = replace(
        base,
        expected_score=Decimal(0),
        conservative_score=Decimal(1),
        upside_score=Decimal(0),
        tie_key="transient-b",
    )
    final_dominator = replace(
        base,
        expected_score=Decimal(2),
        conservative_score=Decimal(2),
        upside_score=Decimal(0),
        tie_key="transient-c",
    )
    complete = _ExactParetoAccumulator()
    for candidate in (first, second, final_dominator):
        complete.add(candidate)
    assert complete.retained_count == 1

    bounded = _ExactParetoAccumulator()
    bounded.add(first)
    _enforce_streaming_pareto_limit(bounded, policy=policy, counters=SearchCounters())
    bounded.add(second)
    with pytest.raises(ResourceLimitReached) as caught:
        counters = SearchCounters()
        _enforce_streaming_pareto_limit(bounded, policy=policy, counters=counters)
    assert caught.value.kind is ResourceLimitKind.PARETO_FRONTIER_LIMIT
    assert caught.value.counters.peak_retained_pareto_frontier == 2


def test_v1_compatibility_and_v2_fail_closed_shape() -> None:
    request, _, _, _ = oracle_fixture("mixed")
    legacy = request.search_policy
    assert legacy.schema_version == "multi-gameweek-search-policy-v1"
    assert legacy.generated_policy_limit == legacy.max_policy_candidates
    assert legacy.retained_pareto_limit == legacy.max_policy_candidates
    with pytest.raises(ValidationError, match="distinct generated-policy"):
        SearchPolicy.model_validate(
            legacy.model_dump(mode="python") | {"schema_version": "multi-gameweek-search-policy-v2"}
        )


def test_resource_diagnostics_reject_mixed_legacy_and_v2_capacities() -> None:
    with pytest.raises(ValidationError, match="exactly one legacy or split"):
        SolverDiagnostics(
            status=BackendStatus.TIME_RESOURCE_LIMIT_NO_INCUMBENT,
            termination_reason="bounded",
            optimality_guarantee=OptimalityGuarantee.NONE,
            state_expansions=1,
            observed_action_combinations=1,
            action_candidates=1,
            policy_candidates=2,
            pareto_candidates=1,
            resource_limit_kind=ResourceLimitKind.POLICY_GENERATION_LIMIT,
            configured_max_actions_per_state=1,
            configured_max_state_expansions=1,
            configured_max_policy_candidates=1,
            configured_max_generated_policy_candidates=1,
            configured_max_retained_pareto_candidates=1,
            configured_max_returned_root_candidates=1,
            configured_cumulative_legal_action_limit=1,
            cumulative_legal_actions=1,
            reachable_layer_state_count=1,
            configuration_sha256="0" * 64,
        )


def test_profile_legacy_capacity_maps_to_both_units_and_cannot_mix() -> None:
    assert _resolve_policy_candidate_limits(
        legacy=123,
        generated=None,
        retained=None,
        default_generated=10,
        default_retained=20,
    ) == (123, 123)
    assert _resolve_policy_candidate_limits(
        legacy=None,
        generated=30,
        retained=40,
        default_generated=10,
        default_retained=20,
    ) == (30, 40)
    for generated, retained in ((0, None), (None, -1)):
        with pytest.raises(ValueError, match="must be positive"):
            _resolve_policy_candidate_limits(
                legacy=None,
                generated=generated,
                retained=retained,
                default_generated=10,
                default_retained=20,
            )
    with pytest.raises(ValueError, match="cannot be combined"):
        _resolve_policy_candidate_limits(
            legacy=123,
            generated=30,
            retained=None,
            default_generated=10,
            default_retained=20,
        )


def test_stateless_stress_evaluator_is_decision_equivalent_to_cached_reference() -> None:
    request, _, _, points = oracle_fixture("mixed")
    cached = HorizonPointsEvaluator(points)
    stateless = _StatelessHorizonPointsEvaluator(points)
    profile = Stage11SearchProfile()
    assert solve_frontier(request, stateless, profile=profile) == solve_frontier(request, cached)
    assert stateless.cache == {}
    assert cached.cache
    squads = _profile_squads(profile)
    assert squads
    assert sum(map(len, squads.values())) == sum(
        len(node.unique_resulting_squads) for node in profile.nodes.values()
    )


def test_decision_oracle_binds_full_tactical_and_economic_path_semantics() -> None:
    request, _, _, points = oracle_fixture("mixed")
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
    result = optimise_multi_gameweek(
        request,
        evaluator=HorizonPointsEvaluator(points),
        prefer_deterministic_linear=True,
        root_action_counterfactual=no_transfer,
    )
    semantics = _decision_semantics(result)
    value = semantics["value"]
    recommended = value["recommended"]
    assert "solver_status" not in recommended and "plan_sha256" not in recommended
    decision = recommended["current_action"]
    for field in (
        "state_before_sha256",
        "state_after",
        "bank_before_tenths",
        "bank_after_tenths",
        "free_transfers_before",
        "free_transfers_after",
        "paid_transfers",
        "hit_points",
        "squad_after",
        "tactical_evaluation",
    ):
        assert field in decision
    for path, replacement in (
        (("tactical_evaluation", "tactical_plan_sha256"), "f" * 64),
        (("state_after", "bank_tenths"), 999),
    ):
        tampered = deepcopy(value)
        nested = tampered["recommended"]["current_action"]
        nested[path[0]][path[1]] = replacement
        assert canonical_sha256(tampered) != semantics["semantic_sha256"]
