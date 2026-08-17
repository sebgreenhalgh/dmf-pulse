"""Golden and independent-oracle acceptance for OPT-011."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmf_pulse.optimisation.multi_gameweek_artifacts import load_canonical_json
from dmf_pulse.optimisation.multi_gameweek_models import MultiGameweekOptimisationRequest
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from tests.support.stage11_oracle import exhaustive_expected_oracle

pytestmark = pytest.mark.golden

FIXTURE_ROOT = Path("fixtures/optimisation/multi_gameweek/adversarial")
EXPECTED = json.loads((FIXTURE_ROOT / "expected_summaries.json").read_text(encoding="utf-8"))
ORACLE_CASES = (
    "simple_one_ft",
    "roll_ft",
    "rational_hit",
    "retained_selling_profit",
    "price_change_blocks_later_route",
    "funding_transfer_bundle",
    "horizon_reversal",
    "injury_revealed_after_current_decision",
    "clairvoyance_trap",
    "terminal_value_reversal",
    "repurchase_resets_cohort",
    "tied_plans",
)
UNIQUE_ROOT_CASES = {
    "simple_one_ft",
    "roll_ft",
    "rational_hit",
    "retained_selling_profit",
    "price_change_blocks_later_route",
    "horizon_reversal",
    "injury_revealed_after_current_decision",
    "clairvoyance_trap",
    "terminal_value_reversal",
    "repurchase_resets_cohort",
}


def _request(name: str) -> MultiGameweekOptimisationRequest:
    return load_canonical_json(
        FIXTURE_ROOT / f"{name}.json",
        MultiGameweekOptimisationRequest,
    )


@pytest.mark.parametrize("name", tuple(EXPECTED))
def test_adversarial_fixture_matches_frozen_summary(name: str) -> None:
    result = optimise_multi_gameweek(_request(name))
    expected = EXPECTED[name]
    assert result.status.value == expected["status"]
    assert result.solver_status.status.value == expected["backend_status"]
    assert result.error_code == expected["error_code"]
    assert result.result_sha256 == expected["result_sha256"]
    assert (
        result.current_action.signature if result.current_action is not None else None
    ) == expected["current_action"]
    assert (
        str(result.recommended_plan.utility.objective_total)
        if result.recommended_plan is not None
        else None
    ) == expected["objective"]


@pytest.mark.parametrize("name", ORACLE_CASES)
def test_bounded_exact_backend_matches_independent_expected_oracle(name: str) -> None:
    request = _request(name)
    result = optimise_multi_gameweek(request)
    oracle = exhaustive_expected_oracle(request)
    assert result.recommended_plan is not None
    assert result.recommended_plan.utility.objective_total == oracle.expected_score
    if name in UNIQUE_ROOT_CASES:
        assert result.current_action is not None
        assert result.current_action.signature == oracle.root_action_signature


def test_tied_plan_is_deterministic_across_repeated_execution() -> None:
    request = _request("tied_plans")
    left = optimise_multi_gameweek(request)
    right = optimise_multi_gameweek(request)
    assert left == right
    assert left.result_sha256 == right.result_sha256
    assert left.current_action is not None
    assert left.current_action.signature == EXPECTED["tied_plans"]["current_action"]
