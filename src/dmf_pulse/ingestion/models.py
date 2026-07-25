"""Public and internal typed contracts for FPL-004 ingestion."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    @model_validator(mode="after")
    def normalize_and_validate_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must be timezone-aware")
        return self


class CapabilityValue(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    UNKNOWN = "UNKNOWN"


class RightsCapability(StrEnum):
    AUTOMATED_ACCESS = "automated_access"
    MANUAL_IMPORT = "manual_import"
    TRANSIENT_PROCESSING = "transient_processing"
    CACHE = "cache"
    RAW_STORAGE = "raw_storage"
    DERIVED_STORAGE = "derived_storage"
    MODEL_TRAINING = "model_training"
    PRIVATE_INTERNAL_USE = "private_internal_use"
    PUBLIC_DISPLAY = "public_display"
    REDISTRIBUTION = "redistribution"
    BACKUP = "backup"


class RightsProfileStatus(StrEnum):
    DRAFT = "DRAFT"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    BLOCKED = "BLOCKED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ImmutableCapabilities(Mapping[RightsCapability, CapabilityValue]):
    """A read-only mapping without mutable ``dict`` back doors such as ``|=``."""

    __slots__ = ("_values",)
    _values: Mapping[RightsCapability, CapabilityValue]

    def __init__(self, values: Mapping[RightsCapability, CapabilityValue]) -> None:
        object.__setattr__(self, "_values", MappingProxyType(dict(values)))

    def __getitem__(self, key: RightsCapability) -> CapabilityValue:
        return self._values[key]

    def __iter__(self) -> Iterator[RightsCapability]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise TypeError("rights capabilities are immutable")


class RightsProfile(FrozenModel):
    rights_profile_id: str = Field(min_length=1, max_length=120)
    provider_key: str = Field(min_length=1, max_length=80)
    profile_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    status: RightsProfileStatus
    capabilities: Mapping[RightsCapability, CapabilityValue]
    retention_seconds: int | None = Field(default=None, ge=0)
    retention_reason: str | None = None
    termination_deletion_required: bool
    attribution_required: bool
    attribution_text: str | None = None
    geography_scope: str = Field(min_length=1)
    account_scope: str = Field(min_length=1)
    approved_purpose: str = Field(min_length=1)
    terms_source: str = Field(min_length=1)
    terms_version: str = Field(min_length=1)
    checked_at: datetime
    human_approval_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    notes: str = ""
    unresolved_rights: tuple[str, ...] = ()

    @field_validator("checked_at", "approved_at")
    @classmethod
    def normalize_rights_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("rights timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("capabilities")
    @classmethod
    def freeze_capabilities(
        cls, value: Mapping[RightsCapability, CapabilityValue]
    ) -> Mapping[RightsCapability, CapabilityValue]:
        return ImmutableCapabilities(value)

    @model_validator(mode="after")
    def validate_complete_profile(self) -> RightsProfile:
        if set(self.capabilities) != set(RightsCapability):
            raise ValueError("rights profile must define every capability exactly once")
        if self.retention_seconds is None and not self.retention_reason:
            raise ValueError("unbounded retention requires an explicit reason")
        if self.attribution_required and not self.attribution_text:
            raise ValueError("required attribution text is missing")
        if self.checked_at.tzinfo is None or self.approved_at.tzinfo is None:
            raise ValueError("rights timestamps must be timezone-aware")
        return self


class RightsDecision(FrozenModel):
    profile_id: str
    profile_version: str
    capability: str
    decision: Literal["ALLOW", "DENY"]
    reason: str
    checked_at: datetime | None = None


class MissingnessValue(StrEnum):
    NOT_PUBLISHED = "NOT_PUBLISHED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    MAPPING_FAILED = "MAPPING_FAILED"
    RIGHTS_BLOCKED = "RIGHTS_BLOCKED"
    POST_CUTOFF = "POST_CUTOFF"
    UNKNOWN = "UNKNOWN"


class QualityIssue(FrozenModel):
    severity: Literal["P0", "P1", "P2", "P3"]
    code: str
    stage: str = "VALIDATION"
    subject_scope: str
    message: str | None = None
    observed_at: datetime = datetime(1970, 1, 1, tzinfo=UTC)
    resolution_status: Literal["OPEN", "RESOLVED", "ACCEPTED"] = "OPEN"
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    decision_impact: Literal["BLOCKING", "NONBLOCKING"] | None = None
    missingness: MissingnessValue | None = None
    safe_details: dict[str, Any] = Field(default_factory=dict)
    owner: str | None = None
    review_at: datetime | None = None

    @model_validator(mode="after")
    def complete_quality_evidence(self) -> QualityIssue:
        impact = "BLOCKING" if self.severity in {"P0", "P1"} else "NONBLOCKING"
        if self.decision_impact is not None and self.decision_impact != impact:
            raise ValueError("quality decision impact contradicts severity")
        if self.decision_impact is None:
            object.__setattr__(self, "decision_impact", impact)
        if self.evidence_sha256 is None:
            material = f"{self.code}:{self.stage}:{self.subject_scope}".encode()
            object.__setattr__(self, "evidence_sha256", hashlib.sha256(material).hexdigest())
        return self


class QualityReport(FrozenModel):
    status: Literal["PASS", "PASS_WITH_WARNINGS", "BLOCKED"]
    warning_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    issues: tuple[QualityIssue, ...] = ()

    @model_validator(mode="after")
    def validate_counts(self) -> QualityReport:
        blockers = sum(issue.severity in {"P0", "P1"} for issue in self.issues)
        warnings = sum(issue.severity in {"P2", "P3"} for issue in self.issues)
        expected_status = "BLOCKED" if blockers else "PASS_WITH_WARNINGS" if warnings else "PASS"
        if (
            self.blocker_count != blockers
            or self.warning_count != warnings
            or self.status != expected_status
        ):
            raise ValueError("quality counts or status do not match issues")
        return self


class ProviderResourceResult(FrozenModel):
    resource: Literal["bootstrap", "fixtures"]
    source_snapshot_id: UUID
    lifecycle_state: str
    drift: str | None = None
    raw_retention: str | None = None
    usable_at: datetime | None = None


class SourceBundleMember(FrozenModel):
    role: Literal["BOOTSTRAP", "FIXTURES"]
    source_snapshot_id: UUID
    usable_at: datetime


class SourceBundleSummary(FrozenModel):
    bundle_id: UUID
    bundle_type: Literal["FPL_BOOTSTRAP_FIXTURES"] = "FPL_BOOTSTRAP_FIXTURES"
    competition_id: UUID
    season_id: UUID
    information_cutoff: datetime
    members: tuple[SourceBundleMember, SourceBundleMember]
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_status: Literal["PASS", "PASS_WITH_WARNINGS"]

    @model_validator(mode="after")
    def validate_member_order(self) -> SourceBundleSummary:
        if tuple(member.role for member in self.members) != ("BOOTSTRAP", "FIXTURES"):
            raise ValueError("bundle members must be ordered BOOTSTRAP then FIXTURES")
        if self.members[0].source_snapshot_id == self.members[1].source_snapshot_id:
            raise ValueError("bundle members must reference distinct snapshots")
        if any(member.usable_at > self.information_cutoff for member in self.members):
            raise ValueError("bundle members must be usable no later than the information cutoff")
        return self


class ProviderSnapshotResult(FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["USABLE", "USABLE_WITH_WARNINGS", "QUARANTINED", "RIGHTS_BLOCKED", "FAILED"]
    provider: str
    resources: tuple[ProviderResourceResult, ...]
    rights: RightsDecision
    quality: QualityReport
    canonical_effects: dict[str, Any]
    source_bundle: SourceBundleSummary | None = None


class DriftClassification(StrEnum):
    NO_DRIFT = "NO_DRIFT"
    ADDITIVE_UNKNOWN = "ADDITIVE_UNKNOWN"
    MISSING_OPTIONAL = "MISSING_OPTIONAL"
    BLOCKING_MISSING_REQUIRED = "BLOCKING_MISSING_REQUIRED"
    BLOCKING_TYPE_CHANGE = "BLOCKING_TYPE_CHANGE"
    MALFORMED = "MALFORMED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


class SchemaDriftReport(FrozenModel):
    adapter_version: str = "fpl-reference-v1"
    contract_version: str
    classification: DriftClassification
    unknown_paths: tuple[str, ...] = ()
    missing_optional_paths: tuple[str, ...] = ()
    missing_required_paths: tuple[str, ...] = ()
    type_error_paths: tuple[str, ...] = ()
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_type_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class FplValidationResult(FrozenModel):
    schema_version: str = "1.0.0"
    status: str
    provider: str
    resource: str
    contract_version: str
    payload_semantic_sha256: str | None = None
    drift: SchemaDriftReport
    quality: QualityReport
    next_action: str
