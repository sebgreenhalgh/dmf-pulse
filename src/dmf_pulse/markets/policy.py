"""Frozen, versioned market-normalisation policy loading."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any, Final, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dmf_pulse.ingestion.errors import IngestionError

POLICY_ID = "market-normalisation-v1"
POLICY_SHA256 = "4cdcc026240ddfab9eda18cbcc60b8757b0ce9238322aa3b9e0798a7f1ebd040"
CONFIDENCE_GATE_POLICY_SHA256 = "e9de3bfeb1fc06781ccc31b21c2cd14d11199430fce00750ced827ab099d4c98"

ConfidenceGrade = Literal["A", "B", "C", "D"]
WarningLevel = Literal["NONE", "NONBLOCKING", "BLOCKING"]
CONFIDENCE_GRADES: Final[tuple[ConfidenceGrade, ...]] = ("A", "B", "C", "D")


def canonical_json_sha256(value: object) -> str:
    """Hash canonical compact UTF-8 JSON."""

    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PowerPolicy(_PolicyModel):
    bisection_iterations: Literal[256]
    maximum_bracket_exponent: Literal["1024"]


class ConsensusMethodPolicy(_PolicyModel):
    operator_weighting: Literal["EQUAL"]
    bounds: Literal["PUBLIC_VECTOR_ENVELOPE"]
    disagreement: Literal["MAX_TOTAL_VARIATION"]


class FreshnessPolicy(_PolicyModel):
    stale_after_seconds: Literal[1800]


class ConfidenceThreshold(_PolicyModel):
    minimum_operators: int = Field(ge=1)
    maximum_age_seconds: int | None = Field(
        default=None,
        ge=0,
        exclude_if=lambda value: value is None,
    )
    maximum_disagreement: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class ConfidencePolicy(_PolicyModel):
    A: ConfidenceThreshold
    B: ConfidenceThreshold
    C: ConfidenceThreshold
    D: ConfidenceThreshold


class ConfidenceGate(_PolicyModel):
    fallback_allowed: bool
    maximum_warning_level: WarningLevel


class ConfidenceGateGrades(_PolicyModel):
    A: ConfidenceGate
    B: ConfidenceGate
    C: ConfidenceGate
    D: ConfidenceGate


class ConfidenceGatePolicy(_PolicyModel):
    """Separately authenticated gates omitted from the byte-frozen numeric policy."""

    policy_id: Literal["market-normalisation-confidence-gates-v1"]
    version: Literal["1.0.0"]
    normalisation_policy_sha256: Literal[
        "4cdcc026240ddfab9eda18cbcc60b8757b0ce9238322aa3b9e0798a7f1ebd040"
    ]
    grades: ConfidenceGateGrades
    sha256: str = CONFIDENCE_GATE_POLICY_SHA256


class Retry429Policy(_PolicyModel):
    maximum_attempts: Literal[2]
    default_delay_seconds: Literal[1]
    maximum_retry_after_seconds: Literal[60]


class MarketNormalisationPolicy(_PolicyModel):
    """The only accepted Stage A6 normalisation policy."""

    policy_id: Literal["market-normalisation-v1"]
    version: Literal["1.0.0"]
    decimal_context_precision: Literal[60]
    rounding: Literal["ROUND_HALF_EVEN"]
    public_fractional_digits: Literal[12]
    vector_residual_outcome_order: tuple[Literal["HOME", "DRAW", "AWAY"], ...]
    primary_method: Literal["POWER"]
    sensitivity_methods: tuple[Literal["PROPORTIONAL"], ...]
    power: PowerPolicy
    consensus: ConsensusMethodPolicy
    freshness: FreshnessPolicy
    confidence: ConfidencePolicy
    retry_429: Retry429Policy
    sha256: str = POLICY_SHA256

    @model_validator(mode="after")
    def validate_frozen_order_and_thresholds(self) -> Self:
        if self.vector_residual_outcome_order != ("HOME", "DRAW", "AWAY"):
            raise ValueError("probability residual order is not the frozen policy")
        if self.sensitivity_methods != ("PROPORTIONAL",):
            raise ValueError("sensitivity methods are not the frozen policy")
        expected = {
            "A": (3, 600, "0.020000000000"),
            "B": (2, 1800, "0.050000000000"),
            "C": (1, 1800, "0.100000000000"),
            "D": (1, None, None),
        }
        for grade, values in expected.items():
            threshold = getattr(self.confidence, grade)
            if (
                threshold.minimum_operators,
                threshold.maximum_age_seconds,
                threshold.maximum_disagreement,
            ) != values:
                raise ValueError("confidence thresholds are not the frozen policy")
        return self


ConsensusPolicy = MarketNormalisationPolicy


def require_authenticated_policy(policy: MarketNormalisationPolicy) -> None:
    """Reject copied/constructed policy objects whose fields do not match their hash."""

    material = policy.model_dump(mode="json", exclude={"sha256"})
    if policy.sha256 != POLICY_SHA256 or canonical_json_sha256(material) != POLICY_SHA256:
        raise IngestionError("POLICY_INVALID", "market normalisation policy identity is invalid")


def _policy_resource() -> bytes:
    return files("dmf_pulse.markets.resources").joinpath("normalisation_policy.json").read_bytes()


def _confidence_gate_policy_resource() -> bytes:
    return files("dmf_pulse.markets.resources").joinpath("confidence_gate_policy.json").read_bytes()


def load_confidence_gate_policy() -> ConfidenceGatePolicy:
    """Load the separately versioned confidence warning/fallback gates."""

    try:
        raw = _confidence_gate_policy_resource()
        decoded: Any = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("confidence gate policy root must be an object")
        actual_sha = canonical_json_sha256(decoded)
        if actual_sha != CONFIDENCE_GATE_POLICY_SHA256:
            raise ValueError("confidence gate policy hash differs from authority")
        policy = ConfidenceGatePolicy.model_validate_json(raw)
        if policy.sha256 != actual_sha:
            raise ValueError("confidence gate policy identity differs from authenticated bytes")
        return policy
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError("POLICY_INVALID", "market confidence gate policy is invalid") from exc


def confidence_gate(policy_sha256: str, grade: ConfidenceGrade) -> ConfidenceGate:
    """Resolve a gate only when its separate policy binds the numeric policy hash."""

    gate_policy = load_confidence_gate_policy()
    if gate_policy.normalisation_policy_sha256 != policy_sha256:
        raise IngestionError(
            "POLICY_INVALID", "confidence gates are unavailable for the policy identity"
        )
    return cast(ConfidenceGate, getattr(gate_policy.grades, grade))


def load_market_normalisation_policy() -> MarketNormalisationPolicy:
    """Load and authenticate the wheel-contained frozen policy."""

    try:
        raw = _policy_resource()
        decoded: Any = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("policy root must be an object")
        actual_sha = canonical_json_sha256(decoded)
        if actual_sha != POLICY_SHA256:
            raise ValueError("policy hash differs from the frozen authority")
        policy = MarketNormalisationPolicy.model_validate_json(raw)
        if policy.sha256 != actual_sha:
            raise ValueError("loaded policy identity differs from authenticated bytes")
        require_authenticated_policy(policy)
        return policy
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError("POLICY_INVALID", "market normalisation policy is invalid") from exc
