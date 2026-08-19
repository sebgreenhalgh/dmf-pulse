from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.definitions import ActivationStatus, semantic_sha256
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.schedule_models import seal_schedule_request
from dmf_pulse.chips.service import (
    evaluate_chip_opportunities,
    validate_compiled_chip_bundle,
    validate_installed_chip_capability,
    validate_service_requests,
)
from dmf_pulse.chips.service_models import (
    ChipCapabilityValidation,
    ChipDecision,
    ChipDecisionLineage,
    ChipDecisionSet,
    ChipOpportunityEvaluation,
    ChipProbabilityDiagnostic,
    ChipRulesValidation,
    ChipServiceRequest,
)
from dmf_pulse.evaluation.leakage import scan_for_leakage
from tests.support.stage14_chip_fixtures import service_request

Payload = dict[str, Any]
Mutation = Callable[[Payload], None]


def _set(path: tuple[str | int, ...], value: Any) -> Mutation:
    def mutate(payload: Payload) -> None:
        target: Any = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _reject(model: type, payload: Payload, mutation: Mutation, match: str) -> None:
    candidate = deepcopy(payload)
    mutation(candidate)
    with pytest.raises(ValidationError, match=match):
        model.model_validate(candidate)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (_set(("scenario_weights",), []), "non-empty and sorted"),
        (
            lambda p: p.update(scenario_weights=tuple(reversed(p["scenario_weights"]))),
            "non-empty and sorted",
        ),
        (
            lambda p: p.update(
                scenario_weights=(p["scenario_weights"][0], p["scenario_weights"][0])
            ),
            "identities must be unique",
        ),
        (_set(("scenario_weights", 0, "weight"), 0.6), "must sum to one"),
        (_set(("denominator_weight",), 0.5), "denominator differs"),
        (_set(("probability_now_optimal",), 0.25), "does not reconcile"),
        (_set(("scenario_set_hash",), "f" * 64), "scenario-set hash differs"),
        (_set(("diagnostic_hash",), "f" * 64), "diagnostic hash mismatch"),
    ),
)
def test_probability_diagnostic_rejects_unexplained_or_unsealed_payloads(
    mutation: Mutation,
    match: str,
) -> None:
    diagnostic = evaluate_chip_opportunities(service_request()).decision.probability_diagnostic
    _reject(
        ChipProbabilityDiagnostic,
        diagnostic.model_dump(mode="python"),
        mutation,
        match,
    )


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (
            lambda p: p.update(
                information_cutoff=p["forecast_origin"] + timedelta(seconds=1),
                lineage_hash="0" * 64,
            ),
            "cannot follow forecast origin",
        ),
        (
            lambda p: p.update(chip_definition_hashes=[], lineage_hash="0" * 64),
            "requires chip definitions",
        ),
        (
            lambda p: p.update(
                chip_definition_hashes=p["chip_definition_hashes"] * 2,
                lineage_hash="0" * 64,
            ),
            "sorted and unique",
        ),
        (
            lambda p: p.update(scenario_weights=[], lineage_hash="0" * 64),
            "non-empty and sorted",
        ),
        (
            lambda p: (
                p.update(scenario_weights=tuple(reversed(p["scenario_weights"]))),
                p.update(lineage_hash="0" * 64),
            ),
            "non-empty and sorted",
        ),
        (
            lambda p: (
                p.update(
                    scenario_weights=(
                        p["scenario_weights"][0],
                        p["scenario_weights"][0],
                    )
                ),
                p.update(lineage_hash="0" * 64),
            ),
            "unique identities",
        ),
        (
            lambda p: (
                p["scenario_weights"][0].update(weight=0.6),
                p.update(lineage_hash="0" * 64),
            ),
            "weights must sum to one",
        ),
        (
            lambda p: p.update(feature_record_hashes=[], lineage_hash="0" * 64),
            "requires Stage-12 feature records",
        ),
        (
            lambda p: p.update(
                feature_record_hashes=p["feature_record_hashes"] * 2,
                lineage_hash="0" * 64,
            ),
            "sorted and unique",
        ),
        (
            lambda p: p.update(
                price_activation_statuses=["SHADOW_ONLY", "SHADOW_ONLY"],
                price_input_hash="f" * 64,
                lineage_hash="0" * 64,
            ),
            "sorted and unique",
        ),
        (
            lambda p: p.update(
                price_activation_statuses=["SHADOW_ONLY"],
                price_input_hash=None,
                lineage_hash="0" * 64,
            ),
            "statuses require a price input hash",
        ),
        (_set(("lineage_hash",), "f" * 64), "lineage hash mismatch"),
    ),
)
def test_decision_lineage_rejects_ambiguous_or_unsealed_payloads(
    mutation: Mutation,
    match: str,
) -> None:
    lineage = evaluate_chip_opportunities(service_request()).lineage
    _reject(ChipDecisionLineage, lineage.model_dump(mode="python"), mutation, match)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (
            lambda p: p.update(
                net_policy_value=p["net_policy_value"] + 1.0,
                summary_hash="0" * 64,
            ),
            "net policy value does not reconcile",
        ),
        (
            lambda p: p.update(
                probability_now_optimal=1.0 - p["probability_now_optimal"],
                summary_hash="0" * 64,
            ),
            "probability differs",
        ),
        (_set(("summary_hash",), "f" * 64), "summary hash mismatch"),
    ),
)
def test_opportunity_rejects_nonreconciling_or_unsealed_payloads(
    mutation: Mutation,
    match: str,
) -> None:
    opportunity = evaluate_chip_opportunities(service_request()).opportunities[0]
    _reject(
        ChipOpportunityEvaluation,
        opportunity.model_dump(mode="python"),
        mutation,
        match,
    )


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (
            lambda p: p.update(selected_chip=None, decision_hash="0" * 64),
            "USE must identify exactly one selected chip",
        ),
        (
            lambda p: p.update(selected_token_id=None, decision_hash="0" * 64),
            "USE must identify exactly one selected token",
        ),
        (
            lambda p: p.update(reasons=[], decision_hash="0" * 64),
            "reasons must be non-empty",
        ),
        (
            lambda p: p.update(reasons=p["reasons"] * 2, decision_hash="0" * 64),
            "sorted and unique",
        ),
        (
            lambda p: p.update(
                probability_now_optimal=1.0 - p["probability_now_optimal"],
                decision_hash="0" * 64,
            ),
            "probability differs",
        ),
        (
            lambda p: p.update(
                price_activation_statuses=["SHADOW_ONLY", "SHADOW_ONLY"],
                decision_hash="0" * 64,
            ),
            "sorted and unique",
        ),
        (_set(("decision_hash",), "f" * 64), "decision hash mismatch"),
    ),
)
def test_decision_rejects_incomplete_or_unsealed_payloads(
    mutation: Mutation,
    match: str,
) -> None:
    decision = evaluate_chip_opportunities(service_request()).decision
    _reject(ChipDecision, decision.model_dump(mode="python"), mutation, match)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (
            lambda p: p.update(
                information_cutoff=p["forecast_origin"] + timedelta(seconds=1),
                service_request_hash="0" * 64,
            ),
            "cannot follow forecast origin",
        ),
        (
            lambda p: p.update(feature_records=[], service_request_hash="0" * 64),
            "non-empty and sorted",
        ),
        (
            lambda p: p.update(
                feature_records=p["feature_records"] + (p["feature_records"][-1],),
                service_request_hash="0" * 64,
            ),
            "IDs must be unique",
        ),
        (
            lambda p: p.update(
                continuation_configuration_hash="f" * 64,
                service_request_hash="0" * 64,
            ),
            "configuration hash differs",
        ),
        (
            lambda p: p.update(
                price_activation_statuses=["SHADOW_ONLY", "SHADOW_ONLY"],
                price_input_hash="f" * 64,
                service_request_hash="0" * 64,
            ),
            "sorted and unique",
        ),
        (
            lambda p: p.update(
                price_activation_statuses=["SHADOW_ONLY"],
                price_input_hash=None,
                service_request_hash="0" * 64,
            ),
            "statuses require a price input hash",
        ),
        (_set(("service_request_hash",), "f" * 64), "request hash mismatch"),
    ),
)
def test_service_request_rejects_incoherent_or_unsealed_payloads(
    mutation: Mutation,
    match: str,
) -> None:
    request = service_request()
    _reject(ChipServiceRequest, request.model_dump(mode="python"), mutation, match)


def test_decision_set_rejects_cross_contract_mismatches() -> None:
    result = evaluate_chip_opportunities(service_request(keys=("TRIPLE_CAPTAIN", "BENCH_BOOST")))
    payload = result.model_dump(mode="python")
    mutations: tuple[tuple[Mutation, str], ...] = (
        (
            lambda p: p.update(request_hash="f" * 64, decision_set_hash="0" * 64),
            "request and service lineage hashes differ",
        ),
        (
            lambda p: (
                p["lineage"].update(schedule_request_hash="f" * 64, lineage_hash="0" * 64),
                p.update(decision_set_hash="0" * 64),
            ),
            "different scheduler request hash",
        ),
        (
            lambda p: (
                p["decision"].update(schedule_policy_hash="f" * 64, decision_hash="0" * 64),
                p.update(decision_set_hash="0" * 64),
            ),
            "not bound to its schedule policy",
        ),
        (
            lambda p: (
                p["decision"].update(
                    gross_current_gain=p["decision"]["gross_current_gain"] + 1.0,
                    decision_hash="0" * 64,
                ),
                p.update(decision_set_hash="0" * 64),
            ),
            "value decomposition differs",
        ),
        (
            lambda p: (
                p.update(opportunities=tuple(reversed(p["opportunities"]))),
                p.update(decision_set_hash="0" * 64),
            ),
            "opportunities must be sorted",
        ),
        (
            lambda p: p.update(
                opportunities=tuple(
                    sorted(
                        p["opportunities"] + (deepcopy(p["opportunities"][0]),),
                        key=lambda item: (
                            item["chip_key"],
                            item["token_id"],
                            item["opportunity_id"],
                        ),
                    )
                ),
                decision_set_hash="0" * 64,
            ),
            "IDs must be unique",
        ),
        (
            lambda p: p.update(opportunities=[], decision_set_hash="0" * 64),
            "lacks a current opportunity",
        ),
        (_set(("decision_set_hash",), "f" * 64), "decision-set hash mismatch"),
    )
    for mutation, match in mutations:
        _reject(ChipDecisionSet, payload, mutation, match)


def test_rules_and_capability_reports_reject_ambiguous_or_unsealed_payloads() -> None:
    rules = validate_compiled_chip_bundle(service_request().chip_bundle)
    rules_payload = rules.model_dump(mode="python")
    for mutation, match in (
        (
            lambda p: p.update(chip_keys=p["chip_keys"] * 2, validation_hash="0" * 64),
            "sorted and unique",
        ),
        (
            lambda p: p.update(definition_count=2, validation_hash="0" * 64),
            "definition count differs",
        ),
        (_set(("validation_hash",), "f" * 64), "validation hash mismatch"),
    ):
        _reject(ChipRulesValidation, rules_payload, mutation, match)

    capability = validate_installed_chip_capability()
    capability_payload = capability.model_dump(mode="python")
    for mutation, match in (
        (
            lambda p: p.update(capabilities=[], validation_hash="0" * 64),
            "non-empty, sorted and unique",
        ),
        (
            lambda p: p.update(
                capabilities=p["capabilities"] * 2,
                validation_hash="0" * 64,
            ),
            "non-empty, sorted and unique",
        ),
        (_set(("validation_hash",), "f" * 64), "validation hash mismatch"),
    ):
        _reject(ChipCapabilityValidation, capability_payload, mutation, match)


def test_bundle_service_rejects_invalid_compiler_blocked_and_unsealed_rules() -> None:
    bundle = service_request().chip_bundle
    with pytest.raises(ChipError, match="Stage-14 contract"):
        validate_compiled_chip_bundle({})

    compiler_payload = bundle.model_dump(mode="json")
    compiler_payload["compiler_version"] = "unsupported-compiler"
    compiler_payload["bundle_hash"] = semantic_sha256(
        {key: value for key, value in compiler_payload.items() if key != "bundle_hash"}
    )
    with pytest.raises(ChipError) as compiler_error:
        validate_compiled_chip_bundle(compiler_payload)
    assert compiler_error.value.code == "CHIP_COMPILER_VERSION_MISMATCH"

    blocked_definition = bundle.definitions[0].model_copy(
        update={
            "activation_status": ActivationStatus.BLOCKED_UNKNOWN_EFFECT,
            "blockers": ("UNKNOWN_EFFECT:SYNTHETIC",),
        }
    )
    blocked_bundle = bundle.model_copy(update={"definitions": (blocked_definition,)})
    with pytest.raises(ChipError) as blocked_error:
        validate_compiled_chip_bundle(blocked_bundle)
    assert blocked_error.value.code == "CHIP_RULES_BLOCKED"

    unsealed_bundle = bundle.model_copy(update={"bundle_hash": "f" * 64})
    with pytest.raises(ChipError) as hash_error:
        validate_compiled_chip_bundle(unsealed_bundle)
    assert hash_error.value.code == "CHIP_BUNDLE_HASH_MISMATCH"


def test_service_request_collection_must_be_nonempty_unique_and_is_sorted() -> None:
    first = service_request(current_values={"TRIPLE_CAPTAIN": (1.0, 1.0)})
    second = service_request(current_values={"TRIPLE_CAPTAIN": (2.0, 2.0)})

    with pytest.raises(ChipError) as empty_error:
        validate_service_requests(())
    assert empty_error.value.code == "CHIP_SERVICE_REQUEST_SET_INVALID"
    with pytest.raises(ChipError) as duplicate_error:
        validate_service_requests((first, first))
    assert duplicate_error.value.code == "CHIP_SERVICE_REQUEST_SET_INVALID"
    assert validate_service_requests((second, first)) == tuple(
        sorted((first.service_request_hash, second.service_request_hash))
    )


def test_service_request_rejects_schedule_cutoff_and_leakage_report_drift() -> None:
    request = service_request()
    payload = request.model_dump(mode="python")
    schedule = request.schedule_request.model_copy(
        update={
            "information_cutoff": request.information_cutoff + timedelta(seconds=1),
            "request_hash": "0" * 64,
        }
    )
    payload["schedule_request"] = seal_schedule_request(schedule)
    payload["service_request_hash"] = "0" * 64
    _reject(ChipServiceRequest, payload, lambda _: None, "information cutoffs differ")

    payload = request.model_dump(mode="python")
    payload["leakage_report"] = scan_for_leakage(
        request.feature_records,
        forecast_origin=request.information_cutoff - timedelta(seconds=1),
        dataset_mode=request.dataset_mode,
    )
    payload["service_request_hash"] = "0" * 64
    _reject(ChipServiceRequest, payload, lambda _: None, "leakage report differs")
