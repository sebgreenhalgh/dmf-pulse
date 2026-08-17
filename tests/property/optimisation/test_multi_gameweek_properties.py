"""Deterministic property and invariant tests for OPT-011."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from dmf_pulse.optimisation.manager_state import (
    seal_manager_state,
    validate_manager_state,
    verify_manager_state_hash,
)
from dmf_pulse.optimisation.multi_gameweek_artifacts import load_canonical_json
from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekOptimisationRequest,
    MultiGameweekResultStatus,
    seal_request,
)
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek

pytestmark = pytest.mark.property

ROOT = Path("fixtures/optimisation/multi_gameweek/adversarial")
SUCCESS_CASES = (
    "simple_one_ft",
    "roll_ft",
    "rational_hit",
    "retained_selling_profit",
    "price_fall",
    "repurchase_resets_cohort",
    "funding_transfer_bundle",
    "price_change_blocks_later_route",
    "injury_revealed_after_current_decision",
    "postponed_reassigned_fixture",
    "horizon_reversal",
    "futures_identical_until_revelation",
    "clairvoyance_trap",
    "terminal_value_reversal",
    "tied_plans",
    "resource_limit_incumbent",
    "no_materially_distinct_alternative",
)


def _request(name: str) -> MultiGameweekOptimisationRequest:
    return load_canonical_json(ROOT / f"{name}.json", MultiGameweekOptimisationRequest)


@pytest.mark.parametrize("name", SUCCESS_CASES)
def test_every_emitted_state_preserves_squad_bank_ft_and_spell_invariants(name: str) -> None:
    request = _request(name)
    result = optimise_multi_gameweek(request)
    assert result.status in {
        MultiGameweekResultStatus.SUCCESS,
        MultiGameweekResultStatus.RESOURCE_LIMIT,
    }
    assert result.recommended_plan is not None
    catalog = {item.player_id: item for item in request.candidate_pool}
    for decision in (
        result.recommended_plan.current_action,
        *result.recommended_plan.future_policy,
    ):
        state = decision.state_after
        verify_manager_state_hash(state)
        validate_manager_state(state, candidate_pool=request.candidate_pool, rules=request.rules)
        assert state.bank_tenths >= 0
        assert 0 <= state.free_transfers <= request.rules.maximum_free_transfers
        assert len(state.active_spells) == request.rules.squad_size
        assert len(state.squad_ids) == len(set(state.squad_ids))
        assert Counter(catalog[player].position for player in state.squad_ids) == Counter(
            request.rules.position_squad_quota
        )
        club_counts = Counter(catalog[player].club_id for player in state.squad_ids)
        assert max(club_counts.values()) <= request.rules.max_players_per_club
        assert decision.bank_after_tenths == (
            decision.bank_before_tenths
            + sum(item.price_tenths for item in decision.selling_prices)
            - sum(item.price_tenths for item in decision.buying_prices)
        )


@pytest.mark.parametrize("name", SUCCESS_CASES)
def test_objective_components_and_tree_policy_reconcile_exactly(name: str) -> None:
    result = optimise_multi_gameweek(_request(name))
    assert result.recommended_plan is not None
    utility = result.recommended_plan.utility
    assert utility.objective_total == (
        utility.current_gameweek_contribution
        + utility.future_contribution
        - utility.expected_hit_cost
        + utility.terminal_flexibility_contribution
    )
    decisions = (
        result.recommended_plan.current_action,
        *result.recommended_plan.future_policy,
    )
    assert len({item.node_id for item in decisions}) == len(decisions)
    assert len({item.information_set_key for item in decisions}) == len(decisions)


def _with_state(
    request: MultiGameweekOptimisationRequest,
    *,
    bank_tenths: int | None = None,
    free_transfers: int | None = None,
) -> MultiGameweekOptimisationRequest:
    state = seal_manager_state(
        request.initial_state.model_copy(
            update={
                "state_id": request.initial_state.state_id + "-monotone",
                "bank_tenths": (
                    request.initial_state.bank_tenths if bank_tenths is None else bank_tenths
                ),
                "free_transfers": (
                    request.initial_state.free_transfers
                    if free_transfers is None
                    else free_transfers
                ),
                "state_sha256": "0" * 64,
            }
        )
    )
    return seal_request(
        request.model_copy(update={"initial_state": state, "request_sha256": "0" * 64})
    )


def test_additional_usable_budget_cannot_reduce_feasible_optimum() -> None:
    request = _request("simple_one_ft")
    baseline = optimise_multi_gameweek(request)
    richer = optimise_multi_gameweek(
        _with_state(request, bank_tenths=request.initial_state.bank_tenths + 10)
    )
    assert baseline.recommended_plan is not None and richer.recommended_plan is not None
    assert (
        richer.recommended_plan.utility.objective_total
        >= baseline.recommended_plan.utility.objective_total
    )


def test_additional_usable_free_transfer_cannot_reduce_feasible_optimum() -> None:
    request = _request("rational_hit")
    baseline = optimise_multi_gameweek(request)
    richer = optimise_multi_gameweek(_with_state(request, free_transfers=2))
    assert baseline.recommended_plan is not None and richer.recommended_plan is not None
    assert (
        richer.recommended_plan.utility.objective_total
        >= baseline.recommended_plan.utility.objective_total
    )


def test_no_transfer_policy_is_feasible_and_reported_when_rules_permit() -> None:
    for name in SUCCESS_CASES:
        result = optimise_multi_gameweek(_request(name))
        assert result.no_transfer_baseline is not None
        assert result.no_transfer_baseline.current_action.action.transfer_count == 0
