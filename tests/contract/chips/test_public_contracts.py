from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

import dmf_pulse.chips as chips
from dmf_pulse.chips.policy_models import (
    BenchBoostEvaluation,
    CaptainViceDecision,
    FreeHitEvaluation,
    TripleCaptainEvaluation,
    WildcardEvaluation,
)
from dmf_pulse.chips.service import evaluate_chip_opportunities
from dmf_pulse.chips.service_models import (
    ChipDecision,
    ChipDecisionSet,
    ChipProbabilityDiagnostic,
    ChipServiceRequest,
)
from tests.support.stage14_chip_fixtures import service_request

pytestmark = pytest.mark.contract


def test_public_service_reuses_accepted_domain_types() -> None:
    assert chips.CaptainViceDecision is CaptainViceDecision
    assert chips.TripleCaptainEvaluation is TripleCaptainEvaluation
    assert chips.BenchBoostEvaluation is BenchBoostEvaluation
    assert chips.FreeHitEvaluation is FreeHitEvaluation
    assert chips.WildcardEvaluation is WildcardEvaluation
    assert chips.ChipDecision is ChipDecision
    assert chips.ChipDecisionSet is ChipDecisionSet
    assert chips.ChipProbabilityDiagnostic is ChipProbabilityDiagnostic


def test_public_service_signatures_are_bounded_and_shared() -> None:
    assert tuple(inspect.signature(chips.evaluate_chip_opportunities).parameters) == ("request",)
    assert tuple(inspect.signature(chips.optimise_chip_schedule).parameters) == ("request",)
    assert chips.evaluate_chip_opportunities is evaluate_chip_opportunities


def test_public_models_are_frozen_and_extra_forbid() -> None:
    request = service_request()
    with pytest.raises(ValidationError, match="frozen"):
        request.manager_state_id = "other"  # type: ignore[misc]
    payload = request.model_dump(mode="python")
    payload["unknown"] = "blocked"
    with pytest.raises(ValidationError, match="Extra inputs"):
        ChipServiceRequest.model_validate(payload)


def test_probability_contract_cannot_exist_without_explanation() -> None:
    diagnostic = evaluate_chip_opportunities(service_request()).decision.probability_diagnostic
    payload = diagnostic.model_dump(mode="python")
    payload["numerator_weight"] = 0.25
    payload["diagnostic_hash"] = "0" * 64

    with pytest.raises(ValidationError, match="does not reconcile"):
        ChipProbabilityDiagnostic.model_validate(payload)


def test_stage14_public_surface_contains_required_vertical_slice() -> None:
    required = {
        "CaptainViceDecision",
        "TripleCaptainEvaluation",
        "BenchBoostEvaluation",
        "FreeHitEvaluation",
        "WildcardEvaluation",
        "ChipDecision",
        "ChipDecisionSet",
        "ChipSchedulePolicy",
        "Stage14DecisionArtifact",
        "evaluate_chip_opportunities",
        "optimise_chip_schedule",
        "replay_chip_policy",
        "verify_decision_artifact",
    }
    assert required <= set(chips.__all__)
