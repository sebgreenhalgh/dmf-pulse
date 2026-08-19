from __future__ import annotations

import os
import subprocess
import sys
from copy import deepcopy

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.captaincy import evaluate_triple_captain
from dmf_pulse.chips.definitions import semantic_sha256
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import build_chip_inventory
from dmf_pulse.chips.schedule_models import (
    ChipScheduleRequest,
    ScheduleObjectiveConfig,
    scenario_set_hash,
    seal_schedule_request,
)
from dmf_pulse.chips.service import (
    evaluate_chip_opportunities,
    seal_chip_service_request,
    validate_compiled_chip_bundle,
    validate_installed_chip_capability,
)
from dmf_pulse.chips.service_models import ChipDecisionAction, ChipServiceRequest
from dmf_pulse.evaluation.leakage import scan_for_leakage
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.models import ActivationStatus as PriceActivationStatus
from dmf_pulse.prices.models import ConfidenceGrade
from tests.support.stage14_chip_fixtures import (
    MANAGER_HASH,
    NOW,
    scenario_universe,
    schedule_opportunity,
    service_request,
    stage12_feature_records,
)
from tests.unit.chips.test_captaincy import (
    Rules,
    Scenario,
    bundle_for,
    evaluator,
    tactic,
)


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


def test_rules_validation_independently_recompiles_forged_ready_definition() -> None:
    request = service_request()
    payload = deepcopy(request.chip_bundle.model_dump(mode="json"))
    payload["definitions"][0]["capabilities"] = [
        *payload["definitions"][0]["capabilities"],
        "TEMPORARY_SQUAD",
    ]
    bundle_payload = {key: value for key, value in payload.items() if key != "bundle_hash"}
    payload["bundle_hash"] = semantic_sha256(bundle_payload)

    with pytest.raises(ChipError) as exc_info:
        validate_compiled_chip_bundle(payload)

    assert exc_info.value.code == "CHIP_DEFINITION_COMPILE_MISMATCH"


def test_service_rejects_self_sealed_inventory_not_minted_by_bundle() -> None:
    payload = service_request().model_dump(mode="json")
    for inventory in (payload["inventory"], payload["schedule_request"]["inventory"]):
        inventory["concurrency_limit"] = 2
        inventory["inventory_hash"] = semantic_sha256(
            {key: value for key, value in inventory.items() if key != "inventory_hash"}
        )
    payload["schedule_request"]["request_hash"] = semantic_sha256(
        {key: value for key, value in payload["schedule_request"].items() if key != "request_hash"}
    )
    payload["service_request_hash"] = "0" * 64
    forged = seal_chip_service_request(ChipServiceRequest.model_validate(payload))

    with pytest.raises(ChipError) as exc_info:
        evaluate_chip_opportunities(forged)

    assert exc_info.value.code == "CHIP_INVENTORY_BUNDLE_MISMATCH"


def test_service_composes_real_domain_evaluation_with_distinct_bundle_hash() -> None:
    scenarios = (
        Scenario(
            "S1",
            "D1",
            0.5,
            {"A": 10, "B": 4, "C": 2},
            {"A": True, "B": True, "C": True},
        ),
        Scenario(
            "S2",
            "D2",
            0.5,
            {"A": 0, "B": 7, "C": 3},
            {"A": False, "B": True, "C": True},
        ),
    )
    bundle = bundle_for()
    inventory = build_chip_inventory(bundle, current_gameweek=1)
    token_id = inventory.tokens[0].token_id
    triple_captain = evaluate_triple_captain(
        scenarios=scenarios,
        base_tactic=tactic(),
        players={},
        rules=Rules(),
        chip_bundle=bundle,
        inventory=inventory,
        token_id=token_id,
        evaluator=evaluator,
    )
    gross = tuple(item.gross_increment for item in triple_captain.scenario_values)
    opportunity = schedule_opportunity(
        inventory,
        token_id=token_id,
        gameweek=1,
        values=gross,
        now=NOW,
    )
    scenario_identities = scenario_universe()
    objective = ScheduleObjectiveConfig(config_version="DOMAIN-COMPOSITION-V1")
    schedule = seal_schedule_request(
        ChipScheduleRequest(
            request_id="domain-composition",
            inventory=inventory,
            horizon_start_gameweek=1,
            horizon_end_gameweek=1,
            information_cutoff=NOW,
            scenario_universe=scenario_identities,
            scenario_set_hash=scenario_set_hash(scenario_identities),
            opportunities=(opportunity,),
            objective=objective,
            request_hash="0" * 64,
        )
    )
    records = stage12_feature_records(now=NOW, include_price=False)
    request = seal_chip_service_request(
        ChipServiceRequest(
            request_id="domain-service",
            decision_id="domain-decision",
            manager_state_id="manager-domain",
            manager_state_hash=MANAGER_HASH,
            forecast_origin=NOW,
            information_cutoff=NOW,
            dataset_mode=DatasetMode.LIVE_OBSERVED,
            feature_records=records,
            leakage_report=scan_for_leakage(
                records,
                forecast_origin=NOW,
                dataset_mode=DatasetMode.LIVE_OBSERVED,
            ),
            chip_bundle=bundle,
            inventory=inventory,
            schedule_request=schedule,
            captain_vice=triple_captain.ordinary,
            triple_captain=triple_captain,
            confidence=ConfidenceGrade.B,
            continuation_model_version="DOMAIN-COMPOSITION-V1",
            continuation_configuration_hash=semantic_sha256(objective),
            code_commit="eea9591282c2147ad674b35e7c8e2c328a20c68a",
            service_request_hash="0" * 64,
        )
    )

    assert triple_captain.scenario_set_hash != schedule.scenario_set_hash
    result = evaluate_chip_opportunities(request)
    assert result.triple_captain == triple_captain
    assert result.opportunities[0].domain_evaluation_hash == triple_captain.evaluation_hash


def test_installed_validation_does_not_claim_target_rules_are_active() -> None:
    result = validate_installed_chip_capability()

    assert result.production_eligible is False
    assert result.target_rules_required is True
    assert result.status == "ENGINEERING_READY_PENDING_TARGET_RULES"
    assert "ROOT_ONLY_SEQUENTIAL_REPLAY" in result.capabilities
