"""R6 capacity and residual-tie contracts, written before the V3 implementation."""

import pytest

from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.horizon_candidates import bounded_horizon_screen
from scripts.profile_horizon_candidate_pressure import pressure_fixture, v2_pressure
from tests.unit.private_v1.test_horizon_candidate_screen import screen_fixture


def screen(fixture, protected=()):
    ids, catalog, prices, projections = fixture
    return bounded_horizon_screen(
        ids,
        catalog=catalog,
        prices=prices,
        gameweeks=projections,
        protected_incoming_ids=protected,
    )


def test_v2_115_pressure_becomes_finite_objective_ranked_node_scopes():
    fixture = pressure_fixture()
    assert v2_pressure(fixture)["v2_union"] == 115
    result = screen(fixture)
    assert all(0 < len(n.retained_incoming_ids) <= result.maximum_retained for n in result.nodes)
    assert result.policy == "PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V3"
    assert result.certified_dominated_candidates == result.equivalence_removed == 0
    assert fixture[0][-1] in result.nodes[0].retained_incoming_ids


def test_final_mean_price_ties_are_preserved_or_fail_not_identity_truncated():
    fixture = screen_fixture(count=8, tied=True)
    result = screen(fixture)
    assert all(n.retained_incoming_ids == fixture[0] for n in result.nodes)
    assert result.nodes[0].tie_expansion > 0
    with pytest.raises(PrivateV1Error, match=r"FINAL_MODEL_TIE.*full=30"):
        screen(screen_fixture(count=30, tied=True))


def test_protect_actual_one_gw_action_at_root_not_whole_legacy_universe():
    fixture = pressure_fixture()
    protected = (fixture[0][40],)
    result = screen(fixture, protected)
    assert set(protected) <= set(result.nodes[0].retained_incoming_ids)
    assert result.nodes[0].protected_count == 1
    assert result.nodes[-1].protected_count == 0
    assert result.semantic_sha256 != screen(fixture).semantic_sha256


def test_shuffle_and_future_hash_binding():
    fixture = pressure_fixture()
    result = screen(fixture)
    ids, catalog, prices, projections = fixture
    assert result == screen((tuple(reversed(ids)), catalog, prices, projections))
    projections[-1].result_sha256 = "f" * 64
    assert screen(fixture).semantic_sha256 != result.semantic_sha256


def test_expired_current_only_value_does_not_fill_final_node():
    fixture = pressure_fixture("low_overlap")
    result = screen(fixture)
    assert result.nodes[0].horizon_gameweeks == (1, 2, 3)
    assert result.nodes[1].horizon_gameweeks == (2, 3)
    assert result.nodes[2].horizon_gameweeks == (3,)
    assert set(result.nodes[0].retained_incoming_ids) - set(result.nodes[2].retained_incoming_ids)


def test_small_universe_is_exhaustive():
    fixture = screen_fixture(count=4)
    assert all(n.retained_incoming_ids == fixture[0] for n in screen(fixture).nodes)


def test_empty_metric_and_empty_incoming_have_no_implicit_candidate_admission():
    from dmf_pulse.private_v1.horizon_candidates import _select

    assert _select({}, 2) == (set(), 0, 0)
    fixture = pressure_fixture()
    assert all(not n.retained_incoming_ids for n in screen(((), *fixture[1:])).nodes)


def test_renaming_ids_cannot_change_semantic_retention():
    from copy import deepcopy

    fixture = pressure_fixture()
    original = screen(fixture)
    ids, catalog, prices, projections = deepcopy(fixture)
    renamed = {p: f"renamed-{len(ids) - i:04d}" for i, p in enumerate(ids)}
    for projection in projections:
        projection.player_summaries = {
            renamed[p]: summary for p, summary in projection.player_summaries.items()
        }
    changed = screen(
        (
            tuple(renamed[p] for p in ids),
            {
                renamed[p]: entry.model_copy(update={"player_id": renamed[p]})
                for p, entry in catalog.items()
            },
            {renamed[p]: price for p, price in prices.items()},
            projections,
        )
    )
    assert all(
        {renamed[p] for p in left.retained_incoming_ids} == set(right.retained_incoming_ids)
        for left, right in zip(original.nodes, changed.nodes, strict=True)
    )


def test_pressure_action_counts_match_canonical_simultaneous_ft2_enumeration():
    from dmf_pulse.optimisation.manager_state import seal_manager_state
    from dmf_pulse.optimisation.multi_gameweek_models import seal_search_policy
    from dmf_pulse.optimisation.multi_gameweek_solver import enumerate_legal_actions
    from scripts.profile_horizon_candidate_pressure import projected_legal_actions
    from tests.unit.private_v1.horizon_oracle_support import oracle_fixture

    fixture = pressure_fixture()
    ids = fixture[0][:8]
    projected = projected_legal_actions((ids, *fixture[1:]))
    base, _, _, _ = oracle_fixture()
    catalog = tuple(p for p in base.candidate_pool if p.player_id in base.initial_state.squad_ids)
    catalog = tuple(sorted((*catalog, *(fixture[1][p] for p in ids)), key=lambda p: p.player_id))
    node = base.scenario_tree.root.model_copy(
        update={
            "allowed_transfer_in_ids": ids,
            "prices": {**base.scenario_tree.root.prices, **fixture[2]},
        }
    )
    state = seal_manager_state(base.initial_state.model_copy(update={"free_transfers": 2}))
    policy = seal_search_policy(
        base.search_policy.model_copy(
            update={
                "max_transfers_per_node": 2,
                "transfer_action_scope": None,
            }
        )
    )
    actions = enumerate_legal_actions(
        state, node=node, candidate_pool=catalog, rules=base.rules, policy=policy
    )
    assert projected["legal_actions_by_count"] == {
        str(count): sum(a.transfer_count == count for a in actions) for count in (1, 2)
    }


@pytest.mark.parametrize("kind", ["unsealed", "gap", "unknown_protected", "too_many_protected"])
def test_invalid_scope_fails_closed(kind):
    fixture = pressure_fixture()
    protected = ()
    if kind == "unsealed":
        fixture[3][0].result_sha256 = None
    elif kind == "gap":
        fixture[3][-1].scenario_set.gameweek_id = "GW-9"
    elif kind == "unknown_protected":
        protected = ("absent",)
    else:
        protected = fixture[0][:3]
    with pytest.raises(PrivateV1Error, match="HORIZON_SCREEN_INPUT_INVALID"):
        screen(fixture, protected)
