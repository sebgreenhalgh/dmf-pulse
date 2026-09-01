"""Explicit authority for VERIFIED-rules private transient decision support.

This module does not activate a ruleset.  It validates one operator attestation against an exact
VERIFIED ruleset and its complete FULL_SEASON capability for a private, zero-retention use only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import ensure_compiled_ruleset_integrity
from dmf_pulse.rules.errors import RulesError, RulesValidationError
from dmf_pulse.rules.models import (
    CapabilityArtifact,
    CompiledRuleset,
    RuleCapability,
    RulesetStatus,
)

Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class PrivateTransientRulesAuthority(BaseModel):
    """Hash-sealed operator authority that cannot confer ACTIVE or production status."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    schema_version: Literal["private-transient-rules-authority-v1"] = (
        "private-transient-rules-authority-v1"
    )
    ruleset_id: StrictStr = Field(min_length=3, max_length=100)
    ruleset_version: StrictStr = Field(min_length=1, max_length=100)
    season_code: Literal["2026/2027"] = "2026/2027"
    ruleset_sha256: Sha256
    ruleset_status: Literal["VERIFIED"] = "VERIFIED"
    capability: Literal["FULL_SEASON"] = "FULL_SEASON"
    capability_sha256: Sha256
    execution_purpose: Literal["PRIVATE_TRANSIENT_DECISION_SUPPORT"] = (
        "PRIVATE_TRANSIENT_DECISION_SUPPORT"
    )
    privacy: Literal["PRIVATE"] = "PRIVATE"
    retention: Literal["NO_PERSISTENCE"] = "NO_PERSISTENCE"
    activation_status: Literal["NOT_PRODUCTION_ACTIVE"] = "NOT_PRODUCTION_ACTIVE"
    operator_approval_reference: StrictStr = Field(min_length=1, max_length=200)
    operator_approved_at: datetime
    attestation_sha256: Sha256

    @field_validator("operator_approved_at")
    @classmethod
    def approval_time_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("operator approval time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def attestation_is_sealed(self) -> Self:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"attestation_sha256"}))
        if self.attestation_sha256 != expected:
            raise ValueError("private transient rules attestation hash does not match")
        return self


def seal_private_transient_rules_authority(
    value: PrivateTransientRulesAuthority,
) -> PrivateTransientRulesAuthority:
    payload = value.model_dump(mode="python")
    payload["attestation_sha256"] = canonical_sha256(
        value.model_dump(mode="json", exclude={"attestation_sha256"})
    )
    return PrivateTransientRulesAuthority.model_validate(payload)


def validate_private_transient_rules_authority(
    authority: PrivateTransientRulesAuthority,
    *,
    ruleset: CompiledRuleset,
    capability: CapabilityArtifact,
    information_cutoff: datetime,
) -> PrivateTransientRulesAuthority:
    """Validate the narrow exception without changing either supplied rules artifact."""

    try:
        checked = PrivateTransientRulesAuthority.model_validate(authority.model_dump(mode="python"))
        checked_ruleset = CompiledRuleset.model_validate(ruleset.model_dump(mode="python"))
        checked_capability = CapabilityArtifact.model_validate(capability.model_dump(mode="python"))
        ensure_compiled_ruleset_integrity(checked_ruleset)
        expected_capability = compile_capability_artifact(
            checked_ruleset, RuleCapability.FULL_SEASON
        )
    except (RulesError, ValidationError, ValueError, TypeError) as exc:
        raise RulesValidationError(
            "PRIVATE_TRANSIENT_RULES_AUTHORITY_INVALID",
            "private transient rules authority failed integrity validation",
        ) from exc
    cutoff = information_cutoff
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise RulesValidationError(
            "PRIVATE_TRANSIENT_RULES_AUTHORITY_INVALID",
            "private transient rules authority requires an aware information cutoff",
        )
    if (
        checked_ruleset.status is not RulesetStatus.VERIFIED
        or checked_ruleset.schema_version != "1.1"
        or checked_capability != expected_capability
        or checked_capability.capability is not RuleCapability.FULL_SEASON
        or not checked_capability.source_backed
        or not checked_capability.production_eligible
        or checked_capability.blockers
        or checked.ruleset_id != checked_ruleset.ruleset_id
        or checked.ruleset_version != checked_ruleset.ruleset_version
        or checked.season_code != checked_ruleset.season_code
        or checked.ruleset_sha256 != checked_ruleset.ruleset_hash
        or checked.capability_sha256 != checked_capability.capability_hash
        or checked.operator_approved_at > cutoff.astimezone(UTC)
    ):
        raise RulesValidationError(
            "PRIVATE_TRANSIENT_RULES_AUTHORITY_INVALID",
            "private transient authority does not bind the exact complete VERIFIED ruleset",
        )
    return checked


__all__ = [
    "PrivateTransientRulesAuthority",
    "seal_private_transient_rules_authority",
    "validate_private_transient_rules_authority",
]
