"""Exact deterministic-linear Stage-11 acceleration contracts for 001N-R2."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from itertools import combinations, product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.optimisation.manager_state import (
    ManagerState,
    OwnershipSpell,
    continuation_state_fingerprint,
    seal_manager_state,
    state_fingerprint,
)
from dmf_pulse.optimisation.models import CandidateSquad
from dmf_pulse.optimisation.multi_gameweek_errors import InputInvalidError
from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekOptimisationRequest,
    ScenarioTreeNode,
    TacticalNodeEvaluation,
    seal_request,
    verify_result_hash,
)
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.optimisation.multi_gameweek_solver import (
    BoundedExactEnumerator,
    DeterministicLinearExactEnumerator,
    Stage11SearchProfile,
    apply_transfer_action,
    deterministic_linear_fast_path_eligible,
    enumerate_legal_actions,
    make_transfer_action,
    observe_node,
    select_horizon_transfer_count_frontier,
    solve_frontier,
)
from tests.support.multi_gameweek_factories import NodeSpec, build_request


@dataclass
class _ExactSurrogate:
    calls: int = 0
    cache: dict[tuple[str, tuple[str, ...]], TacticalNodeEvaluation] = field(default_factory=dict)
    batch_calls: dict[str, int] = field(default_factory=dict)

    @property
    def squad_only(self) -> bool:
        return True

    @staticmethod
    def _value(node: ScenarioTreeNode, squad_ids: tuple[str, ...]) -> TacticalNodeEvaluation:
        value = Decimal(
            sum(
                (index + 1) * sum(player_id.encode("utf-8"))
                for index, player_id in enumerate(squad_ids)
            )
        ) / Decimal(1000)
        digest = semantic_sha256({"node_id": node.node_id, "squad_ids": squad_ids})
        return TacticalNodeEvaluation(
            expected_points=value,
            p10_points=value - Decimal(1),
            p90_points=value + Decimal(1),
            tactical_plan_sha256=digest,
            tactical_plan={},
            exact_stage10_evaluation=True,
            source="FROZEN_STAGE10_RECORD",
        )

    def evaluate(self, *, node: ScenarioTreeNode, state: ManagerState) -> TacticalNodeEvaluation:
        key = (node.node_id, state.squad_ids)
        value = self.cache.get(key)
        if value is None:
            self.calls += 1
            value = self._value(node, state.squad_ids)
            self.cache[key] = value
        return value

    def precompute_node(
        self,
        *,
        node: ScenarioTreeNode,
        squads: tuple[CandidateSquad, ...],
    ) -> None:
        pending = tuple(
            squad
            for squad in sorted(set(squads), key=lambda item: item.player_ids)
            if (node.node_id, squad.player_ids) not in self.cache
        )
        if not pending:
            return
        self.batch_calls[node.node_id] = self.batch_calls.get(node.node_id, 0) + 1
        for squad in pending:
            self.cache[(node.node_id, squad.player_ids)] = self._value(node, squad.player_ids)


def _request(*, branching: bool = False) -> MultiGameweekOptimisationRequest:
    incoming = ("p15", "p16", "p17")
    specs = [
        NodeSpec(node_id="GW-1", gameweek=1, allowed_transfer_in_ids=incoming),
        NodeSpec(
            node_id="GW-2",
            parent_id="GW-1",
            gameweek=2,
            allowed_transfer_in_ids=incoming,
        ),
        NodeSpec(
            node_id="GW-3",
            parent_id="GW-2",
            gameweek=3,
            allowed_transfer_in_ids=incoming,
        ),
    ]
    if branching:
        specs.append(
            NodeSpec(
                node_id="GW-2-B",
                parent_id="GW-1",
                gameweek=2,
                conditional_probability=Decimal("0.5"),
                allowed_transfer_in_ids=incoming,
            )
        )
        specs[1] = NodeSpec(
            node_id="GW-2",
            parent_id="GW-1",
            gameweek=2,
            conditional_probability=Decimal("0.5"),
            allowed_transfer_in_ids=incoming,
        )
    request = build_request(
        tuple(specs),
        free_transfers=2,
        max_transfers_per_node=2,
        max_actions_per_state=10000,
        max_state_expansions=100000,
        max_policy_candidates=1000000,
        max_returned_root_candidates=10000,
    )
    if branching:
        return request
    assumptions = tuple(
        sorted(
            {
                *request.assumptions,
                "DETERMINISTIC_NO_NEW_INFORMATION_REVELATION_V1",
                "EXPECTED_THREE_GAMEWEEK_POINTS_WITH_LEGAL_RECOURSE",
                "FUTURE_PRICE_CHANGES_NOT_MODELLED_IN_PRIVATE_3GW_V1",
                "NO_CHIP_EXPLICIT",
                "HORIZON_TRANSFER_COUNT_FRONTIER_V1",
                "THREE_GAMEWEEK_ZERO_TERMINAL_VALUE_AFTER_HORIZON",
            }
        )
    )
    return seal_request(
        request.model_copy(update={"assumptions": assumptions, "request_sha256": "0" * 64})
    )


def _candidate_signature(result) -> tuple[object, ...]:
    return tuple(
        (
            tuple(decision.action.signature for decision in candidate.decisions),
            tuple(decision.squad_after for decision in candidate.decisions),
            tuple(decision.bank_after_tenths for decision in candidate.decisions),
            tuple(decision.free_transfers_after for decision in candidate.decisions),
            tuple(decision.hit_points for decision in candidate.decisions),
            tuple(decision.selling_prices for decision in candidate.decisions),
            tuple(decision.buying_prices for decision in candidate.decisions),
            tuple(
                decision.tactical_evaluation.tactical_plan_sha256
                for decision in candidate.decisions
            ),
            candidate.expected_score,
            candidate.conservative_score,
            candidate.upside_score,
            candidate.terminal_total,
            candidate.tie_key,
        )
        for candidate in result.candidates
    )


def _with_closed_history(
    request: MultiGameweekOptimisationRequest, *, spell_id: str
) -> ManagerState:
    catalog = {item.player_id: item for item in request.candidate_pool}
    entry = catalog["p15"]
    closed = OwnershipSpell(
        spell_id=spell_id,
        player_id=entry.player_id,
        club_id=entry.club_id,
        position=entry.position,
        purchase_price_tenths=50,
        current_price_tenths=50,
        started_gameweek=1,
        started_at_node_id="historical-node",
        ended_gameweek=1,
        ended_at_node_id="historical-node",
        realised_selling_price_tenths=50,
    )
    return seal_manager_state(
        request.initial_state.model_copy(
            update={
                "state_id": f"state-{spell_id}",
                "ownership_spells": tuple(
                    sorted(
                        (*request.initial_state.ownership_spells, closed),
                        key=lambda item: (item.player_id, item.started_gameweek, item.spell_id),
                    )
                ),
                "state_sha256": "0" * 64,
            }
        )
    )


def test_closed_history_is_excluded_only_from_economically_sufficient_key() -> None:
    request = _request()
    left = _with_closed_history(request, spell_id="closed-a")
    right = _with_closed_history(request, spell_id="closed-b")

    assert state_fingerprint(left) != state_fingerprint(right)
    assert continuation_state_fingerprint(left) == continuation_state_fingerprint(right)

    for field_name, value in (
        ("bank_tenths", left.bank_tenths + 1),
        ("free_transfers", left.free_transfers - 1),
        ("ruleset_hash", "f" * 64),
    ):
        changed = left.model_copy(update={field_name: value})
        assert continuation_state_fingerprint(left) != continuation_state_fingerprint(changed)

    active = left.active_spells[0]
    for field_name, value in (
        ("purchase_price_tenths", active.purchase_price_tenths + 1),
        ("current_price_tenths", active.current_price_tenths + 1),
        ("club_id", "different-club"),
        ("position", left.active_spells[-1].position),
    ):
        changed_spell = active.model_copy(update={field_name: value})
        changed = left.model_copy(
            update={
                "ownership_spells": tuple(
                    changed_spell if item.spell_id == active.spell_id else item
                    for item in left.ownership_spells
                )
            }
        )
        assert continuation_state_fingerprint(left) != continuation_state_fingerprint(changed)


def test_deterministic_linear_fast_path_matches_generic_oracle_exactly() -> None:
    request = _request()
    generic_evaluator = _ExactSurrogate()
    fast_evaluator = _ExactSurrogate()
    generic = BoundedExactEnumerator(request=request, evaluator=generic_evaluator).enumerate()
    profile = Stage11SearchProfile()

    accelerated = solve_frontier(
        request,
        fast_evaluator,
        prefer_deterministic_linear=True,
        profile=profile,
    )

    assert _candidate_signature(accelerated) == _candidate_signature(generic)
    assert accelerated.candidates == generic.candidates
    assert accelerated.complete is generic.complete is True
    assert profile.fast_path_used is True
    assert profile.memo_hits > 0
    assert profile.economically_equivalent_full_states > 0
    assert fast_evaluator.batch_calls.keys() == {"GW-1", "GW-2", "GW-3"}
    assert fast_evaluator.calls == 0


def test_fast_path_request_on_branching_tree_falls_back_to_generic() -> None:
    request = _request(branching=True)
    expected = BoundedExactEnumerator(request=request, evaluator=_ExactSurrogate()).enumerate()
    profile = Stage11SearchProfile()

    actual = solve_frontier(
        request,
        _ExactSurrogate(),
        prefer_deterministic_linear=True,
        profile=profile,
    )

    assert _candidate_signature(actual) == _candidate_signature(expected)
    assert profile.fast_path_used is False


def test_different_closed_histories_have_identical_future_actions_and_utilities() -> None:
    request = _request()
    left = _with_closed_history(request, spell_id="closed-a")
    right = _with_closed_history(request, spell_id="closed-b")
    node = request.scenario_tree.root
    action_sets = [
        enumerate_legal_actions(
            state,
            node=node,
            candidate_pool=request.candidate_pool,
            rules=request.rules,
            policy=request.search_policy,
        )
        for state in (left, right)
    ]
    assert action_sets[0] == action_sets[1]
    for action in action_sets[0]:
        transitions = [
            apply_transfer_action(
                state,
                action,
                node=node,
                candidate_pool=request.candidate_pool,
                rules=request.rules,
            )
            for state in (left, right)
        ]
        a, b = transitions
        assert continuation_state_fingerprint(a.state) == continuation_state_fingerprint(b.state)
        assert a.free_transfer_arc == b.free_transfer_arc
        assert a.selling_prices == b.selling_prices
        assert a.buying_prices == b.buying_prices
        assert _ExactSurrogate._value(node, a.state.squad_ids) == _ExactSurrogate._value(
            node, b.state.squad_ids
        )
        assert any(spell.spell_id == "closed-a" for spell in a.state.ownership_spells)
        assert any(spell.spell_id == "closed-b" for spell in b.state.ownership_spells)


@pytest.mark.parametrize(
    "mutation",
    [
        "assumption",
        "length",
        "gameweek",
        "parent",
        "probability",
        "revelation",
        "availability",
        "fixture",
        "prices",
        "shortlist",
        "event",
        "terminal_enabled",
        "terminal_bank",
        "terminal_ft",
        "terminal_liquidation",
    ],
)
def test_fast_path_preconditions_fail_closed(mutation) -> None:
    request = _request()
    nodes = list(request.scenario_tree.nodes)
    if mutation == "assumption":
        request = request.model_copy(update={"assumptions": ()})
    elif mutation.startswith("terminal"):
        field_name = {
            "terminal_enabled": "enabled",
            "terminal_bank": "bank_points_per_tenth",
            "terminal_ft": "free_transfer_points",
            "terminal_liquidation": "liquidation_points_per_tenth",
        }[mutation]
        request = request.model_copy(
            update={
                "terminal_policy": request.terminal_policy.model_copy(
                    update={field_name: True if mutation == "terminal_enabled" else Decimal(1)}
                )
            }
        )
    else:
        if mutation == "length":
            nodes.pop()
        else:
            field_name, value = {
                "gameweek": ("gameweek", 9),
                "parent": ("parent_id", "GW-1"),
                "probability": ("conditional_probability", Decimal("0.5")),
                "revelation": ("revealed_information", ("new",)),
                "availability": ("availability_state", {"p15": "OUT"}),
                "fixture": ("fixture_state", {"fixture": "postponed"}),
                "prices": ("prices", {}),
                "shortlist": ("allowed_transfer_in_ids", ("p15",)),
                "event": ("transition_event", "WILDCARD"),
            }[mutation]
            nodes[2] = nodes[2].model_copy(update={field_name: value})
        request = request.model_copy(
            update={
                "scenario_tree": request.scenario_tree.model_copy(update={"nodes": tuple(nodes)})
            }
        )
    assert deterministic_linear_fast_path_eligible(request) is False
    with pytest.raises(InputInvalidError, match="preconditions"):
        DeterministicLinearExactEnumerator(request=request, evaluator=_ExactSurrogate()).enumerate()


@settings(max_examples=12, deadline=None, derandomize=True)
@given(bank=st.integers(0, 10), ft=st.integers(0, 3), purchase=st.integers(40, 55))
def test_random_economics_and_order_preserve_complete_oracle_candidates(bank, ft, purchase) -> None:
    request = _request()
    nodes = tuple(
        node.model_copy(update={"allowed_transfer_in_ids": ("p15", "p16")})
        for node in request.scenario_tree.nodes
    )
    spells = tuple(
        spell.model_copy(update={"purchase_price_tenths": purchase})
        for spell in request.initial_state.ownership_spells
    )
    state = seal_manager_state(
        request.initial_state.model_copy(
            update={
                "ownership_spells": spells,
                "bank_tenths": bank,
                "free_transfers": ft,
            }
        )
    )
    request = request.model_copy(
        update={
            "initial_state": state,
            "scenario_tree": request.scenario_tree.model_copy(update={"nodes": nodes}),
        }
    )
    reference = BoundedExactEnumerator(request, _ExactSurrogate()).enumerate()
    shuffled = request.model_copy(
        update={"candidate_pool": tuple(reversed(request.candidate_pool))}
    )
    accelerated = solve_frontier(shuffled, _ExactSurrogate(), prefer_deterministic_linear=True)
    assert reference.candidates == accelerated.candidates
    assert reference.complete == accelerated.complete


def test_sell_rebuy_resets_purchase_cohort_and_preserves_closed_history() -> None:
    request = _request()
    nodes = tuple(
        node.model_copy(update={"allowed_transfer_in_ids": ("p07", "p15")})
        for node in request.scenario_tree.nodes
    )
    spells = tuple(
        spell.model_copy(update={"purchase_price_tenths": 40})
        if spell.player_id == "p07"
        else spell
        for spell in request.initial_state.ownership_spells
    )
    initial = seal_manager_state(
        request.initial_state.model_copy(
            update={
                "ownership_spells": spells,
                "bank_tenths": 10,
            }
        )
    )
    sale = apply_transfer_action(
        initial,
        make_transfer_action(transfers_out=("p07",), transfers_in=("p15",), event="NORMAL"),
        node=nodes[0],
        candidate_pool=request.candidate_pool,
        rules=request.rules,
    )
    assert sale.selling_prices[0].price_tenths == 45
    repurchase = apply_transfer_action(
        observe_node(sale.state, node=nodes[1]),
        make_transfer_action(transfers_out=("p15",), transfers_in=("p07",), event="NORMAL"),
        node=nodes[1],
        candidate_pool=request.candidate_pool,
        rules=request.rules,
    )
    assert repurchase.state.active_by_player["p07"].purchase_price_tenths == 50
    assert len([s for s in repurchase.state.ownership_spells if s.player_id == "p07"]) == 2
    request = request.model_copy(
        update={
            "initial_state": initial,
            "scenario_tree": request.scenario_tree.model_copy(update={"nodes": nodes}),
        }
    )
    expected = BoundedExactEnumerator(request, _ExactSurrogate()).enumerate()
    actual = solve_frontier(request, _ExactSurrogate(), prefer_deterministic_linear=True)
    assert actual.candidates == expected.candidates


def _publication_fixture(case):
    fixed = set(_request().initial_state.squad_ids) - {"p07", "p08", "p12"}
    squads = tuple(
        sorted(
            tuple(sorted((*fixed, *mids, forward)))
            for mids, forward in product(
                combinations(("p07", "p08", "p15", "p19"), 2), ("p12", "p16")
            )
        )
    )
    prices = {f"p{i:02d}": 40 for i in range(20)}
    prices.update({p: 50 for p in ("p07", "p08", "p12", "p15", "p16", "p19")})
    values = {
        "ties": ({}, {}, {}),
        "hold": ({"p07": 20, "p08": 20}, {"p15": 30, "p19": 30}, {"p15": 30, "p19": 30}),
        "future_hit": (
            {"p07": 30, "p08": 30, "p16": 50},
            {"p15": 40, "p19": 40, "p16": 50},
            {"p15": 40, "p19": 40, "p16": 50},
        ),
        "mixed": ({"p15": 9, "p16": 5}, {"p19": 12}, {"p15": 8, "p16": 14}),
    }[case]
    request = build_request(
        tuple(
            NodeSpec(
                node_id=f"GW-{i + 1}",
                parent_id=f"GW-{i}" if i else None,
                gameweek=i + 1,
                points=points,
                prices=prices,
                allowed_transfer_in_ids=("p15", "p16", "p19"),
                squads=squads,
            )
            for i, points in enumerate(values)
        ),
        root_prices=prices,
        include_second_mid=True,
        free_transfers=1 if case in {"hold", "future_hit"} else 2,
        max_transfers_per_node=2,
    )
    return seal_request(request.model_copy(update={"assumptions": _request().assumptions}))


def _semantic_publication(value):
    """Remove only physical-work counters and their enclosing Stage-11 digests.

    All economic, state/provenance, tactical plan/hash, utility and tie fields remain.
    Every original publication is independently hash-verified before comparison.
    """
    if isinstance(value, list):
        return [_semantic_publication(item) for item in value]
    if not isinstance(value, dict):
        return value
    omit = set()
    if "configuration_sha256" in value:
        omit.update(
            {
                "state_expansions",
                "action_candidates",
                "policy_candidates",
                "pareto_candidates",
                "memo_entries",
            }
        )
    schema = value.get("schema_version", "")
    if schema == "multi-gameweek-plan-v1":
        omit.add("plan_sha256")
    elif schema == "multi-gameweek-optimisation-result-v1":
        omit.add("result_sha256")
    elif schema == "horizon-transfer-count-frontier-v1":
        omit.add("frontier_sha256")
    return {key: _semantic_publication(item) for key, item in value.items() if key not in omit}


@pytest.mark.parametrize("case", ["ties", "hold", "future_hit", "mixed"])
def test_complete_publication_frontier_baseline_alternatives_equal_oracle(case) -> None:
    request = _publication_fixture(case)
    reference = optimise_multi_gameweek(request)
    profile = Stage11SearchProfile()
    accelerated = optimise_multi_gameweek(
        request, prefer_deterministic_linear=True, profile=profile
    )
    assert reference.status.value == accelerated.status.value == "SUCCESS"
    assert profile.fast_path_used
    verify_result_hash(reference)
    verify_result_hash(accelerated)
    assert _semantic_publication(reference.model_dump(mode="json")) == _semantic_publication(
        accelerated.model_dump(mode="json")
    )
    assert tuple(point.transfer_count for point in accelerated.transfer_count_frontier.points) == (
        0,
        1,
        2,
    )
    assert accelerated.no_transfer_baseline.current_action.action.transfer_count == 0
    if case == "hold":
        assert accelerated.current_action.transfer_count == 0
        assert accelerated.future_policy[0].action.transfer_count == 2
        assert accelerated.future_policy[0].hit_points == 0
    if case == "future_hit":
        assert any(item.hit_points > 0 for item in accelerated.future_policy)


def test_unpromised_state_dependent_evaluator_uses_generic_path() -> None:
    class Unpromised:
        def evaluate(self, *, node, state):
            return _ExactSurrogate._value(node, state.squad_ids)

    request = _publication_fixture("ties")
    profile = Stage11SearchProfile()
    result = solve_frontier(
        request, Unpromised(), prefer_deterministic_linear=True, profile=profile
    )
    assert result.complete
    assert not profile.fast_path_used


def test_progress_is_throttled_and_disclosure_safe(monkeypatch) -> None:
    messages = []
    profile = Stage11SearchProfile(progress=messages.append)
    monkeypatch.setattr("dmf_pulse.optimisation.multi_gameweek_solver.perf_counter", lambda: 100.0)
    profile.report_progress(gameweek=2)
    profile.report_progress(gameweek=2)
    assert len(messages) == 1
    assert "GW2" in messages[0] and "states_solved=0" in messages[0]
    assert "%" not in messages[0] and "ETA" not in messages[0] and "p15" not in messages[0]
    profile.report_progress(gameweek=3, force=True)
    assert len(messages) == 2


def test_non_nested_horizon_root_actions_remain_exact() -> None:
    class NonNested(_ExactSurrogate):
        @staticmethod
        def _value(node, squad_ids):
            members = set(squad_ids)
            score = (
                120
                if {"p16", "p17"} <= members and "p15" not in members
                else (100 if "p15" in members and not members & {"p16", "p17"} else 0)
            )
            return _ExactSurrogate._value(node, squad_ids).model_copy(
                update={
                    "expected_points": Decimal(score),
                    "p10_points": Decimal(score),
                    "p90_points": Decimal(score),
                }
            )

    request = _request()
    expected = BoundedExactEnumerator(request, NonNested()).enumerate()
    actual = solve_frontier(request, NonNested(), prefer_deterministic_linear=True)
    assert actual.candidates == expected.candidates
    points = select_horizon_transfer_count_frontier(actual.candidates)
    assert tuple(p.root_action.transfer_count for p in points) == (0, 1, 2)
    assert points[1].root_action.transfers_in == ("p15",)
    assert points[2].root_action.transfers_in == ("p16", "p17")


def test_future_node_batch_memo_reuses_exact_values_and_counts_each_squad_once(monkeypatch) -> None:
    from dmf_pulse.private_v1.service import _MemoizedStage10Evaluator

    class Delegate:
        def evaluate(self, *, node, state):
            return _ExactSurrogate._value(node, state.squad_ids)

        def evaluate_many(self, *, node, squads, progress):
            values = {}
            for i, squad in enumerate(squads, 1):
                values[squad.player_ids] = _ExactSurrogate._value(node, squad.player_ids)
                progress((i, len(squads)))
            return values

    messages = []
    evaluator = _MemoizedStage10Evaluator(Delegate(), progress_message=messages.append)
    evaluator.precompute()
    assert evaluator.batch_calls == 0
    monkeypatch.setattr("dmf_pulse.private_v1.service.perf_counter", lambda: 100.0)
    request = _request()
    squads = (CandidateSquad(player_ids=request.initial_state.squad_ids),)
    for node in request.scenario_tree.nodes:
        evaluator.precompute_node(node=node, squads=(*squads, *squads))
        expected = evaluator.evaluate(node=node, state=request.initial_state)
        evaluator.precompute_node(node=node, squads=squads)
        assert evaluator.evaluate(node=node, state=request.initial_state) is expected
        counters = evaluator.counters_by_node[node.node_id]
        assert counters.evaluated_squads == counters.cache_misses == counters.batch_calls == 1
        assert counters.cache_hits == 3
        assert counters.individual_calls == 0
    assert len(messages) == 1
    assert evaluator.batch_calls == 3 and evaluator.individual_calls == 0
    assert len(evaluator._cache) == 3


def test_node_kernel_reused_only_for_unchanged_exact_problem() -> None:
    from dmf_pulse.optimisation.stage10_adapter import Stage10TacticalAdapter
    from dmf_pulse.private_v1.service import load_one_gameweek_policy
    from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
    from tests.support.multi_gameweek_factories import _scenario, compiled_ruleset

    request = _request()
    node = request.scenario_tree.root
    scenarios = {
        node.node_id: _scenario(
            node_id=node.node_id, gameweek=node.gameweek, catalog=request.candidate_pool, points={}
        )
    }
    adapter = Stage10TacticalAdapter(
        candidate_pool=request.candidate_pool,
        rules=build_one_gameweek_rules_view(
            compiled_ruleset(), projection_mode=request.projection_mode
        ),
        policy=load_one_gameweek_policy(),
        scenarios_by_node=scenarios,
    )
    kernel = adapter._node_kernel(node)
    assert adapter.squad_only
    from dmf_pulse.optimisation.multi_gameweek_errors import InfeasiblePolicyError

    with pytest.raises(InfeasiblePolicyError, match="no Stage-9"):
        adapter._node_kernel(node.model_copy(update={"node_id": "missing"}))
    assert adapter._node_kernel(node) is kernel
    price = node.prices["p15"].model_copy(update={"current_price_tenths": 51})
    changed = node.model_copy(update={"prices": {**node.prices, "p15": price}})
    replacement = adapter._node_kernel(changed)
    assert replacement is not kernel
    assert replacement.players["p15"].initial_selection_cost_tenths == 51
    scenarios[node.node_id][0].player_points["p15"] = 17
    mutated = adapter._node_kernel(changed)
    assert mutated is not replacement
    assert mutated.scenarios[0].player_points["p15"] == 17
    scenarios[node.node_id] = tuple(
        item.model_copy(update={"weight": 0.5}) for item in scenarios[node.node_id]
    )
    assert adapter._node_kernel(changed) is not replacement


def test_resource_limits_remain_fail_closed() -> None:
    request = _publication_fixture("mixed")
    from dmf_pulse.optimisation.multi_gameweek_models import seal_search_policy

    policy = seal_search_policy(
        request.search_policy.model_copy(update={"max_state_expansions": 1})
    )
    request = seal_request(request.model_copy(update={"search_policy": policy}))
    result = optimise_multi_gameweek(request, prefer_deterministic_linear=True)
    assert result.solver_status.optimality_guarantee.value == "NONE"
    assert result.status.value != "SUCCESS"


@pytest.mark.parametrize("mutation", ["all_chips", "duplicate_node_ids"])
def test_inconsistent_private_topology_is_ineligible(mutation) -> None:
    request = _request()
    nodes = tuple(
        node.model_copy(update={"transition_event": "WILDCARD"})
        if mutation == "all_chips"
        else node.model_copy(update={"node_id": "duplicate"})
        for node in request.scenario_tree.nodes
    )
    request = request.model_copy(
        update={"scenario_tree": request.scenario_tree.model_copy(update={"nodes": nodes})}
    )
    assert not deterministic_linear_fast_path_eligible(request)


@pytest.mark.parametrize("closed", [False, True])
def test_future_dated_ownership_provenance_is_outside_economic_memo_proof(closed) -> None:
    request = _request()
    if closed:
        state = _with_closed_history(request, spell_id="future-history")
        spells = tuple(
            spell.model_copy(update={"ended_gameweek": 3}) if not spell.active else spell
            for spell in state.ownership_spells
        )
    else:
        state = request.initial_state
        spells = tuple(
            spell.model_copy(update={"started_gameweek": 3}) for spell in state.ownership_spells
        )
    request = request.model_copy(
        update={"initial_state": state.model_copy(update={"ownership_spells": spells})}
    )
    assert not deterministic_linear_fast_path_eligible(request)


def test_exact_affordability_and_club_precheck_keeps_all_and_only_legal_actions() -> None:
    request = _request()
    catalog = tuple(
        item.model_copy(update={"club_id": "saturated"})
        if item.player_id in {"p00", "p01", "p02", "p15"}
        else item
        for item in request.candidate_pool
    )
    by_id = {item.player_id: item for item in catalog}
    spells = tuple(
        spell.model_copy(update={"club_id": by_id[spell.player_id].club_id})
        for spell in request.initial_state.ownership_spells
    )
    state = seal_manager_state(
        request.initial_state.model_copy(update={"ownership_spells": spells})
    )
    node = request.scenario_tree.root
    prices = {
        **node.prices,
        "p16": node.prices["p16"].model_copy(update={"current_price_tenths": 51}),
    }
    node = node.model_copy(update={"prices": prices})
    kwargs = {
        "node": node,
        "candidate_pool": catalog,
        "rules": request.rules,
        "policy": request.search_policy,
    }
    expected = enumerate_legal_actions(state, **kwargs)
    profile = Stage11SearchProfile().node(node, depth=0)
    captured = {}
    actual = enumerate_legal_actions(
        state, **kwargs, precheck_economics=True, applied_transitions=captured, profile=profile
    )
    assert actual == expected
    assert profile.legality_precheck_rejections > 0
    assert (
        profile.action_combinations_considered
        == profile.transition_applications + profile.legality_precheck_rejections
    )
    assert all("p16" not in action.transfers_in for action in actual)
    assert all("p02" in action.transfers_out for action in actual if "p15" in action.transfers_in)
    assert any("p15" in action.transfers_in for action in actual)
    assert len(captured) == len(actual)


def test_profile_export_contains_counts_not_player_identities() -> None:
    import json

    request = _request()
    profile = Stage11SearchProfile()
    enumerator = BoundedExactEnumerator(request, _ExactSurrogate(), profile=profile)
    enumerator._record_state(request.scenario_tree.root, request.initial_state)
    payload = profile.as_dict()
    assert payload["memo_misses"] == profile.memo_misses == 0
    assert payload["nodes"][0]["unique_current_state_fingerprints"] == 1
    assert "p00" not in json.dumps(payload)
    assert enumerator._cached_frontier("GW-1", request.initial_state, ()) == ()
    enumerator._prepare_tactical_batch(node=request.scenario_tree.root, transitions=())


@pytest.mark.parametrize("corruption", [None, "node", "economics", "tactics"])
def test_cached_multi_node_suffix_is_replayed_and_tampering_fails_closed(corruption) -> None:
    request = _publication_fixture("mixed")
    evaluator = _ExactSurrogate()
    candidate = BoundedExactEnumerator(request, evaluator).enumerate().candidates[0]
    suffix = replace(candidate, decisions=candidate.decisions[1:])
    current = observe_node(candidate.decisions[0].state_after, node=request.scenario_tree.nodes[1])
    if corruption:
        first = suffix.decisions[0]
        if corruption == "node":
            first = first.model_copy(update={"node_id": "wrong"})
        elif corruption == "economics":
            first = first.model_copy(
                update={"state_after": first.state_after.model_copy(update={"bank_tenths": 99})}
            )
        else:
            first = first.model_copy(
                update={
                    "tactical_evaluation": first.tactical_evaluation.model_copy(
                        update={"expected_points": Decimal(99)}
                    )
                }
            )
        suffix = replace(suffix, decisions=(first, *suffix.decisions[1:]))
    enumerator = DeterministicLinearExactEnumerator(request, evaluator)
    if corruption:
        with pytest.raises(ValueError, match=r"cached deterministic|economic memo"):
            enumerator._rebase_candidate("GW-2", current, suffix)
    else:
        assert enumerator._rebase_candidate("GW-2", current, suffix) == suffix


def test_multiobjective_pareto_families_are_preserved_without_scalar_pruning() -> None:
    class RiskTradeoff(_ExactSurrogate):
        @staticmethod
        def _value(node, squad_ids):
            value = _ExactSurrogate._value(node, squad_ids)
            return value.model_copy(
                update={
                    "p10_points": value.expected_points - Decimal(5 if "p15" in squad_ids else 1),
                    "p90_points": value.expected_points + Decimal(20 if "p16" in squad_ids else 1),
                }
            )

    request = _request()
    nodes = tuple(
        node.model_copy(update={"allowed_transfer_in_ids": ("p15", "p16")})
        for node in request.scenario_tree.nodes
    )
    request = request.model_copy(
        update={"scenario_tree": request.scenario_tree.model_copy(update={"nodes": nodes})}
    )
    expected = BoundedExactEnumerator(request, RiskTradeoff()).enumerate()
    profile = Stage11SearchProfile()
    actual = solve_frontier(
        request, RiskTradeoff(), prefer_deterministic_linear=True, profile=profile
    )
    assert actual.complete and expected.complete
    assert actual.candidates == expected.candidates
    assert any(n.peak_retained_frontier > 1 for n in profile.nodes.values())
