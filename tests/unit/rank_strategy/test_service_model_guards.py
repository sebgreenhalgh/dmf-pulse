from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.rank_strategy.service import (
    evaluate_rank_plans,
    validate_installed_rank_capability,
)
from dmf_pulse.rank_strategy.service_models import (
    AcceptedRankPlan,
    RankCapabilityValidation,
    RankComponentKind,
    RankGateCheck,
    RankGateReport,
    RankServiceLineage,
    RankServiceProjectionEvidence,
    RankServiceRequest,
    RankServiceResult,
)
from dmf_pulse.rank_strategy.utility_models import (
    RankActivationStatus,
    RankObjectiveMode,
)
from tests.support.rank_service_fixtures import service_request

pytestmark = pytest.mark.unit

_ZERO_HASH = "0" * 64
Mutation = Callable[[dict[str, Any]], None]


def _reject(
    model_type: type[Any],
    source: dict[str, Any],
    mutation: Mutation,
    match: str,
) -> None:
    payload = deepcopy(source)
    mutation(payload)
    with pytest.raises(ValidationError, match=match):
        model_type.model_validate(payload)


def _seal_payload(payload: dict[str, Any], hash_field: str) -> None:
    payload[hash_field] = semantic_sha256(
        {key: value for key, value in payload.items() if key != hash_field}
    )


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (
            lambda payload: (
                payload["stage9_scenarios"].update(
                    component=RankComponentKind.STAGE_10_TACTICS,
                ),
                payload.update(lineage_hash=_ZERO_HASH),
            ),
            "component identity mismatch",
        ),
        (
            lambda payload: payload.update(lineage_hash="f" * 64),
            "lineage hash mismatch",
        ),
    ),
)
def test_lineage_rejects_component_or_hash_tampering(
    mutation: Mutation,
    match: str,
) -> None:
    lineage = service_request().lineage
    _reject(RankServiceLineage, lineage.model_dump(mode="python"), mutation, match)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (
            lambda payload: payload.update(plan_id="different", binding_hash=_ZERO_HASH),
            "plan ID differs",
        ),
        (
            lambda payload: payload.update(
                source_stage="STAGE_14"
                if payload["candidate"]["source_stage"] == "STAGE_12"
                else "STAGE_12",
                binding_hash=_ZERO_HASH,
            ),
            "source stage differs",
        ),
        (
            lambda payload: payload.update(binding_hash="f" * 64),
            "binding hash mismatch",
        ),
    ),
)
def test_accepted_plan_rejects_cross_binding_tampering(
    mutation: Mutation,
    match: str,
) -> None:
    plan = service_request().plans[0]
    _reject(AcceptedRankPlan, plan.model_dump(mode="python"), mutation, match)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (
            lambda payload: payload.update(
                information_cutoff=payload["forecast_origin"] + timedelta(seconds=1),
                service_request_hash=_ZERO_HASH,
            ),
            "cutoff cannot follow forecast origin",
        ),
        (
            lambda payload: (
                payload["lineage"].update(
                    information_cutoff=payload["information_cutoff"] - timedelta(seconds=1),
                    lineage_hash=_ZERO_HASH,
                ),
                payload.update(service_request_hash=_ZERO_HASH),
            ),
            "request and lineage information cutoffs differ",
        ),
        (
            lambda payload: payload.update(
                plans=tuple(reversed(payload["plans"])),
                service_request_hash=_ZERO_HASH,
            ),
            "plans must be sorted and unique",
        ),
        (
            lambda payload: payload.update(
                plans=(payload["plans"][0], payload["plans"][0]),
                service_request_hash=_ZERO_HASH,
            ),
            "plans must be sorted and unique",
        ),
        (
            lambda payload: (
                payload["lineage"].update(points_floor_hash="f" * 64, lineage_hash=_ZERO_HASH),
                payload.update(service_request_hash=_ZERO_HASH),
            ),
            "points-floor configuration hash mismatch",
        ),
        (
            lambda payload: payload.update(service_request_hash="f" * 64),
            "request hash mismatch",
        ),
    ),
)
def test_service_request_rejects_temporal_ordering_and_seal_tampering(
    mutation: Mutation,
    match: str,
) -> None:
    value = service_request()
    _reject(RankServiceRequest, value.model_dump(mode="python"), mutation, match)


@pytest.mark.parametrize(
    "payload",
    (
        {
            "name": "RULES",
            "required": True,
            "passed": True,
            "reason_code": "SHOULD_NOT_EXIST",
        },
        {
            "name": "RULES",
            "required": True,
            "passed": False,
            "reason_code": None,
        },
    ),
)
def test_gate_check_requires_reason_exactly_when_failed(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="pass state must reconcile"):
        RankGateCheck.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (
            lambda payload: payload.update(checks=tuple(reversed(payload["checks"]))),
            "complete sorted gate inventory",
        ),
        (
            lambda payload: payload.update(
                checks=payload["checks"] + (deepcopy(payload["checks"][0]),),
            ),
            "complete sorted gate inventory",
        ),
        (
            lambda payload: payload.update(
                executable_rank_utility=not payload["executable_rank_utility"],
            ),
            "executable status does not reconcile",
        ),
        (
            lambda payload: payload.update(report_hash="f" * 64),
            "report hash mismatch",
        ),
    ),
)
def test_gate_report_rejects_noncanonical_or_unsealed_payloads(
    mutation: Mutation,
    match: str,
) -> None:
    report = evaluate_rank_plans(service_request()).gate_report
    _reject(RankGateReport, report.model_dump(mode="python"), mutation, match)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (
            lambda payload: payload.update(
                before_score_hashes=dict(reversed(tuple(payload["before_score_hashes"].items()))),
            ),
            "before-score hashes must be sorted",
        ),
        (
            lambda payload: payload.update(
                after_score_hashes=dict(reversed(tuple(payload["after_score_hashes"].items()))),
            ),
            "after-score hashes must be sorted",
        ),
        (
            lambda payload: payload["after_score_hashes"].update(
                {next(iter(payload["after_score_hashes"])): "f" * 64}
            ),
            "cannot mutate accepted scenario scores",
        ),
        (
            lambda payload: payload.update(evidence_hash="f" * 64),
            "projection evidence hash mismatch",
        ),
    ),
)
def test_projection_evidence_rejects_mutation_or_noncanonical_maps(
    mutation: Mutation,
    match: str,
) -> None:
    evidence = evaluate_rank_plans(service_request()).projection_invariance
    _reject(
        RankServiceProjectionEvidence,
        evidence.model_dump(mode="python"),
        mutation,
        match,
    )


def _assert_result_guard(value: RankServiceResult, match: str, **updates: Any) -> None:
    mutated = value.model_copy(update={**updates, "result_hash": _ZERO_HASH})
    with pytest.raises(ValueError, match=match):
        mutated.result_reconciles()


def test_result_rejects_noncanonical_reasons_and_point_difference() -> None:
    value = evaluate_rank_plans(service_request(rights_valid=False))
    _assert_result_guard(
        value,
        "reasons must be sorted and unique",
        fail_closed_reasons=value.fail_closed_reasons * 2,
    )
    _assert_result_guard(
        value,
        "expected-points difference does not reconcile",
        expected_points_difference=value.expected_points_difference + 1.0,
    )


def test_result_without_decision_rejects_impossible_diagnostics() -> None:
    value = evaluate_rank_plans(service_request(rank_raw_hash="9" * 64))
    active = evaluate_rank_plans(service_request())
    _assert_result_guard(
        value,
        "diagnostics cannot be available without a decision",
        diagnostic_output_available=True,
    )
    _assert_result_guard(
        value,
        "active non-points result requires rank diagnostics",
        activation_status=RankActivationStatus.ACTIVE,
    )
    _assert_result_guard(
        value,
        "unavailable rank diagnostics must retain the points plan",
        rank_optimal_plan=active.rank_optimal_plan,
        expected_points_difference=(
            active.rank_optimal_plan.candidate.expected_points
            - value.points_optimal_plan.candidate.expected_points
        ),
    )
    _assert_result_guard(
        value,
        "unavailable rank diagnostics cannot claim target gain",
        target_probability_difference=0.1,
    )


def test_result_with_decision_rejects_cross_contract_mismatches() -> None:
    value = evaluate_rank_plans(service_request())
    assert value.rank_decision is not None
    _assert_result_guard(
        value,
        "decision must be exposed as diagnostic output",
        diagnostic_output_available=False,
    )
    _assert_result_guard(
        value,
        "request IDs differ",
        rank_decision=value.rank_decision.model_copy(update={"request_id": "different"}),
    )
    _assert_result_guard(
        value,
        "points-optimal plan differs from decision",
        rank_decision=value.rank_decision.model_copy(
            update={"points_optimal_plan_id": "different"}
        ),
    )
    _assert_result_guard(
        value,
        "rank-optimal plan differs from decision",
        rank_decision=value.rank_decision.model_copy(update={"rank_optimal_plan_id": "different"}),
    )
    _assert_result_guard(
        value,
        "target-probability difference differs from decision",
        target_probability_difference=(value.target_probability_difference or 0.0) + 0.1,
    )


def test_active_result_rejects_fallback_or_wrong_selected_plan() -> None:
    value = evaluate_rank_plans(service_request())
    _assert_result_guard(
        value,
        "active rank service result cannot contain fallback reasons",
        fail_closed_reasons=("INVALID",),
    )
    _assert_result_guard(
        value,
        "active rank service selected plan is inconsistent",
        selected_plan=value.points_optimal_plan,
    )


def test_inactive_result_rejects_missing_reasons_wrong_objective_or_plan() -> None:
    value = evaluate_rank_plans(service_request(rights_valid=False))
    _assert_result_guard(
        value,
        "inactive rank service result requires fail-closed reasons",
        fail_closed_reasons=(),
    )
    _assert_result_guard(
        value,
        "inactive rank service result must use pure points",
        effective_objective=RankObjectiveMode.TARGET_RANK,
    )
    _assert_result_guard(
        value,
        "inactive rank service result must select points optimum",
        selected_plan=value.rank_optimal_plan,
    )


def test_result_rejects_projection_and_scenario_evidence_mismatches() -> None:
    value = evaluate_rank_plans(service_request())
    _assert_result_guard(
        value,
        "raw projection lineage differs from evidence",
        raw_projection_hash="f" * 64,
    )
    _assert_result_guard(
        value,
        "scenario lineage differs from evidence",
        scenario_set_hash="f" * 64,
    )
    with pytest.raises(ValueError, match="result hash mismatch"):
        value.model_copy(update={"result_hash": "f" * 64}).result_reconciles()


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (
            lambda payload: payload.update(
                cli_commands=tuple(reversed(payload["cli_commands"])),
            ),
            "CLI commands must be sorted and unique",
        ),
        (
            lambda payload: payload.update(validation_hash="f" * 64),
            "validation hash mismatch",
        ),
    ),
)
def test_capability_validation_rejects_noncanonical_or_unsealed_payloads(
    mutation: Mutation,
    match: str,
) -> None:
    value = validate_installed_rank_capability()
    _reject(RankCapabilityValidation, value.model_dump(mode="python"), mutation, match)
