from __future__ import annotations

import os
import subprocess
import sys
from copy import deepcopy

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.service import (
    evaluate_chip_opportunities,
    validate_compiled_chip_bundle,
    validate_installed_chip_capability,
)
from dmf_pulse.chips.service_models import ChipDecisionAction, ChipServiceRequest
from dmf_pulse.prices.models import ActivationStatus as PriceActivationStatus
from dmf_pulse.prices.models import ConfidenceGrade
from tests.support.stage14_chip_fixtures import service_request


def test_shared_service_selects_one_executable_root_action() -> None:
    request = service_request(
        keys=("TRIPLE_CAPTAIN", "BENCH_BOOST"),
        current_values={"TRIPLE_CAPTAIN": (7.0, 5.0), "BENCH_BOOST": (2.0, 2.0)},
        future_values={"TRIPLE_CAPTAIN": (3.0, 3.0), "BENCH_BOOST": (4.0, 4.0)},
    )

    result = evaluate_chip_opportunities(request)

    assert result.decision.recommended_action is ChipDecisionAction.USE
    assert result.decision.selected_chip == "TRIPLE_CAPTAIN"
    assert result.decision.selected_token_id is not None
    assert result.decision.executable_root_only is True
    assert result.schedule_policy.future_schedule_advisory_only is True
    assert result.lineage.manager_state_hash == request.manager_state_hash
    assert result.lineage.scenario_set_hash == request.schedule_request.scenario_set_hash
    assert result.decision.probability_diagnostic.denominator_weight == 1.0
    assert result.decision.probability_diagnostic.scenario_weights == (
        result.lineage.scenario_weights
    )
    assert result.decision.probability_diagnostic.model_version == (
        request.continuation_model_version
    )
    assert result.decision.probability_diagnostic.configuration_hash == (
        request.continuation_configuration_hash
    )
    assert result.decision.probability_diagnostic.comparison_rule == (
        "PER_SCENARIO_BEST_LEGAL_SCHEDULE_ACTIVATES_AT_ROOT"
    )


def test_hold_and_wait_are_successful_valid_outcomes() -> None:
    wait = evaluate_chip_opportunities(
        service_request(
            current_values={"TRIPLE_CAPTAIN": (1.0, 1.0)},
            future_values={"TRIPLE_CAPTAIN": (8.0, 8.0)},
        )
    )
    hold = evaluate_chip_opportunities(
        service_request(
            current_values={"TRIPLE_CAPTAIN": (-1.0, -1.0)},
            future_values={"TRIPLE_CAPTAIN": (-2.0, -2.0)},
        )
    )

    assert wait.decision.recommended_action is ChipDecisionAction.WAIT
    assert wait.decision.selected_chip is None
    assert hold.decision.recommended_action is ChipDecisionAction.HOLD
    assert hold.decision.selected_chip is None


def test_expire_unused_is_a_successful_explicit_service_outcome() -> None:
    result = evaluate_chip_opportunities(
        service_request(
            activation_end_gameweek=1,
            current_values={},
            future_values={},
        )
    )

    assert result.decision.recommended_action is ChipDecisionAction.EXPIRE_UNUSED
    assert result.decision.selected_chip is None
    assert "TOKEN_EXPIRES_UNUSED" in result.decision.reasons


def test_each_exposed_opportunity_probability_retains_full_diagnostic() -> None:
    result = evaluate_chip_opportunities(service_request())
    opportunity = result.opportunities[0]

    assert opportunity.probability_now_optimal == (
        opportunity.probability_diagnostic.probability_now_optimal
    )
    assert opportunity.probability_diagnostic.denominator_weight == 1.0
    assert opportunity.probability_diagnostic.scenario_weights == result.lineage.scenario_weights
    assert opportunity.probability_diagnostic.comparison_rule == (
        "PER_SCENARIO_CURRENT_OPPORTUNITY_GTE_BEST_SAME_TOKEN_DELAY_OR_TERMINAL"
    )


def test_stage13_limitations_are_propagated_and_confidence_is_not_promoted() -> None:
    request = service_request(
        price_statuses=(
            PriceActivationStatus.SHADOW_ONLY,
            PriceActivationStatus.TARGET_SEASON_UNCALIBRATED,
            PriceActivationStatus.RIGHTS_BLOCKED,
        ),
        confidence=ConfidenceGrade.A,
    )

    result = evaluate_chip_opportunities(request)

    assert result.decision.confidence is ConfidenceGrade.D
    assert result.decision.price_activation_statuses == request.price_activation_statuses
    assert "STAGE13_RIGHTS_BLOCKED_PROPAGATED" in result.decision.reasons
    assert result.lineage.price_input_hash == request.price_input_hash


def test_same_semantic_input_has_same_decision_identity() -> None:
    request = service_request(keys=("TRIPLE_CAPTAIN", "BENCH_BOOST"))

    first = evaluate_chip_opportunities(request)
    second = evaluate_chip_opportunities(
        ChipServiceRequest.model_validate(request.model_dump(mode="python"))
    )

    assert first.decision.decision_hash == second.decision.decision_hash
    assert first.decision_set_hash == second.decision_set_hash
    assert first.schedule_policy.policy_hash == second.schedule_policy.policy_hash


def test_service_hashes_are_stable_across_python_hash_seeds() -> None:
    script = (
        "from tests.support.stage14_chip_fixtures import service_request; "
        "request = service_request(); "
        "print(request.chip_bundle.bundle_hash, request.service_request_hash)"
    )
    outputs: set[str] = set()
    for seed in ("1", "2", "3", "101"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = "src:."
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        outputs.add(completed.stdout.strip())

    assert len(outputs) == 1


def test_unsealed_or_tampered_request_fails_closed() -> None:
    request = service_request()
    tampered = request.model_copy(update={"manager_state_hash": "9" * 64})

    with pytest.raises(ChipError, match="correctly sealed") as exc_info:
        evaluate_chip_opportunities(tampered)

    assert exc_info.value.code == "CHIP_SERVICE_REQUEST_UNSEALED"


def test_invalid_scenario_weights_are_rejected_before_service_execution() -> None:
    request = service_request()
    payload = request.model_dump(mode="python")
    payload["schedule_request"]["scenario_universe"][0]["weight"] = 0.7

    with pytest.raises(ValidationError, match="weights must sum to one"):
        ChipServiceRequest.model_validate(payload)


def test_rules_validation_rejects_definition_tampering() -> None:
    request = service_request()
    payload = deepcopy(request.chip_bundle.model_dump(mode="python"))
    payload["definitions"][0]["definition_hash"] = "9" * 64

    with pytest.raises(ChipError) as exc_info:
        validate_compiled_chip_bundle(payload)

    assert exc_info.value.code == "CHIP_DEFINITION_HASH_MISMATCH"


def test_installed_validation_does_not_claim_target_rules_are_active() -> None:
    result = validate_installed_chip_capability()

    assert result.production_eligible is False
    assert result.target_rules_required is True
    assert result.status == "ENGINEERING_READY_PENDING_TARGET_RULES"
    assert "ROOT_ONLY_SEQUENTIAL_REPLAY" in result.capabilities
