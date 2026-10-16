"""Immutable historical consumption fact; never a provider authorization."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from dmf_pulse.evaluation.p01_fallback_context import CONTEXT_SHA, resource_bytes, strict_json
from dmf_pulse.ingestion.openfootball.team_strength_data import SealedEvidence, authenticate
from dmf_pulse.ingestion.p01_fallback_diagnostics import FailureReason, ReasonFailure

CONSUMPTION_SHA = "b7250789c2982de2b4e74371e012f66b7ca8c0b195a554dded00d6a68d36d68f"


class A02Consumption(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-a02-consumption-v1"]
    context_sha256: Literal["6bb80a9c0b17b673044be5b5c53a2eda6c4e4110ef09f7a586e87e0d8432c259"]
    forecast_sha256: Literal["96a13e8265095672708586dd1fd2a7f9653857594ba5fa325e82c0b3385ab15a"]
    historical_marker_byte_sha256: Literal[
        "48048afc55688eddb21ce3dbd9f258e8b2dba333cda728109e45bd17f5d28be2"
    ]
    historical_stopped_handoff_sha256: Literal[
        "38a84ac114b025ce9e2573d7ddbc886c2dd2fb582544a7b41289e699b5afd0e0"
    ]
    historical_stage: Literal["UNKNOWN_HISTORICAL"]
    historical_reason: Literal["P01_OUTCOME_ADMISSION_FAILED_CLOSED"]
    historical_exact_cause: Literal["NOT_RETAINED"]
    consumed: Literal[True]
    new_provider_authority: Literal[False]
    sealed_at: datetime


def load_consumption() -> A02Consumption:
    data = resource_bytes("evaluation/team_strength_p01_a02_consumption.json")
    strict_json(data)
    return authenticate(A02Consumption.model_validate_json(data), CONSUMPTION_SHA)


def require_unconsumed_synthetic_context(context_sha256: str, *, explicit_fake: bool) -> None:
    """A02 stays consumed even if a caller changes directories or deletes a marker."""
    consumed = load_consumption()
    if (
        context_sha256 == consumed.context_sha256
        or context_sha256 == CONTEXT_SHA
        or not explicit_fake
    ):
        raise ReasonFailure(FailureReason.ONE_ATTEMPT_ALREADY_CONSUMED)
