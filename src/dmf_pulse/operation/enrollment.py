"""Trusted installed enrollment metadata, including independently reviewed source closure.

Reading a caller document never enrolls it. Installation of reviewed code and its
fixed resource remains the existing authority boundary.
"""

from __future__ import annotations

import json
from datetime import datetime
from importlib.resources import files
from typing import Literal, Self

from pydantic import field_serializer, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard.authorization import OperatorRefreshApproval, SourceScope
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.operation.models import Metadata, MetadataTime, OperationError, Ref, Sha


def rights_fingerprint(profile: RightsProfile) -> str:
    value = profile.model_dump(mode="json", exclude={"capabilities"})
    value["capabilities"] = {key.value: item.value for key, item in profile.capabilities.items()}
    return canonical_sha256(value)


class SourceQualification(Metadata):
    qualification_id: Ref
    scope: SourceScope
    profile: RightsProfile
    purpose: Literal["PRIVATE_OPERATOR_FPL_RECOMMENDATIONS"]
    permission_basis: Literal[
        "SUPPLIER_WRITTEN_PERMISSION", "APPLICABLE_EXCEPTION", "VENDOR_TERMS_AND_ACCOUNT"
    ]
    permission_evidence_sha256: Sha
    account_review_sha256: Sha | None = None
    independent_review_sha256: Sha
    decision_ref: Ref
    operator_country: str
    qualified_at: datetime
    valid_until: datetime
    control_metadata_retention_approved: Literal[True]
    source_body_retention: Literal["DENIED_TRANSIENT_ONLY"] = "DENIED_TRANSIENT_ONLY"

    @field_serializer("profile", when_used="json")
    def serializable_profile(self, profile: RightsProfile) -> dict[str, object]:
        value = profile.model_dump(mode="json", exclude={"capabilities"})
        value["capabilities"] = {
            key.value: item.value for key, item in profile.capabilities.items()
        }
        return value

    @field_validator("control_metadata_retention_approved", mode="before")
    @classmethod
    def exact_permission(cls, value: object) -> object:
        if value is not True:
            raise ValueError("control permission requires explicit boolean true")
        return value

    @model_validator(mode="after")
    def exact_qualified_scope(self) -> Self:
        if (
            self.scope.source_kind != "RIGHTS_QUALIFIED_PRIVATE"
            or self.scope.profile_id != self.profile.rights_profile_id
            or self.scope.profile_sha256 != rights_fingerprint(self.profile)
            or self.qualified_at >= self.valid_until
            or len(self.operator_country) != 2
            or not self.operator_country.isascii()
            or not self.operator_country.isupper()
            or not self.operator_country.isalpha()
            or self.control_metadata_retention_approved is not True
        ):
            raise ValueError("qualified source closure differs")
        if self.scope.provider == "FPL" and (
            self.permission_basis == "VENDOR_TERMS_AND_ACCOUNT"
            or self.profile.rights_profile_id == "fpl_official_private_operator_initiated_read_v1"
        ):
            raise ValueError("owner contractual risk does not establish supplier permission")
        if self.scope.provider == "ODDS" and (
            self.profile.rights_profile_id == "the_odds_api_private_analytics_v1"
            or self.account_review_sha256 is None
        ):
            raise ValueError("consumed Odds purpose cannot qualify the new pilot")
        return self


class ReleasePermit(Metadata):
    permit_id: Ref
    base_wheel_sha256: Sha
    registry_sha256: Sha
    owner_package_sha256: Sha
    independent_review_sha256: Sha
    owner_decision_ref: Ref
    accepted_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if self.accepted_at >= self.expires_at:
            raise ValueError("release permit has no validity window")
        return self


class InstalledEnrollment(Metadata):
    schema_version: Literal["trusted-refresh-enrollments-v2"] = "trusted-refresh-enrollments-v2"
    approvals: tuple[OperatorRefreshApproval, ...] = ()
    qualifications: tuple[SourceQualification, ...] = ()
    release_permits: tuple[ReleasePermit, ...] = ()
    default_authorization_id: Ref | None = None

    @model_validator(mode="after")
    def unique_authority(self) -> Self:
        for rows, field in (
            (self.approvals, "authorization_id"),
            (self.qualifications, "qualification_id"),
            (self.release_permits, "permit_id"),
        ):
            if len(rows) > 32 or len({getattr(row, field) for row in rows}) != len(rows):
                raise ValueError("duplicate or excessive enrollment metadata")
        if any(row.classification != "PRIVATE_CURRENT" for row in self.approvals):
            raise ValueError("installed production rows must be private current")
        if (
            self.default_authorization_id is not None
            and sum(row.authorization_id == self.default_authorization_id for row in self.approvals)
            != 1
        ):
            raise ValueError("default launch must identify one installed approval")
        return self


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate enrollment field")
        value[key] = item
    return value


def installed_enrollment() -> InstalledEnrollment:
    """Only this fixed installed resource grants source closure or release permits."""
    try:
        body = (
            files("dmf_pulse.dashboard.resources")
            .joinpath("production_refresh_enrollments.json")
            .read_bytes()
        )
        if len(body) > 131072:
            raise ValueError("registry exceeds bound")
        value = json.loads(body, object_pairs_hook=_unique)
        # Read-only compatibility with historical empty/reviewed v1 installations.
        if (
            isinstance(value, dict)
            and value.get("schema_version") == "trusted-refresh-enrollments-v1"
        ):
            if set(value) != {"schema_version", "approvals"}:
                raise ValueError("historical registry fields differ")
            value = {**value, "schema_version": "trusted-refresh-enrollments-v2"}
        elif not isinstance(value, dict) or set(value) != {
            "schema_version",
            "approvals",
            "qualifications",
            "release_permits",
            "default_authorization_id",
        }:
            raise ValueError("installed registry fields differ")
        return InstalledEnrollment.model_validate_json(json.dumps(value, allow_nan=False))
    except (OSError, ValueError, TypeError, RecursionError):
        raise OperationError("TRUSTED_APPROVAL_REGISTRY_INVALID") from None


def require_source_closure(scopes: tuple[SourceScope, ...], *, now: datetime) -> datetime:
    now = MetadataTime(checked_at=now).checked_at
    registry = installed_enrollment()
    expiries = []
    for scope in scopes:
        rows = [row for row in registry.qualifications if row.scope == scope]
        if len(rows) != 1 or not rows[0].qualified_at <= now < rows[0].valid_until:
            raise OperationError(
                "FPL_SUPPLIER_PERMISSION_REQUIRED"
                if scope.provider == "FPL"
                else "NEW_ODDS_PURPOSE_QUALIFICATION_REQUIRED"
                if scope.provider == "ODDS"
                else "OPENFOOTBALL_SCOPE_QUALIFICATION_REQUIRED"
            )
        expiries.append(rows[0].valid_until)
    if not expiries:
        raise OperationError("SOURCE_SCOPE_INVALID")
    return min(expiries)


def require_fpl_route(
    method: str, host: str, path: str, *, now: datetime, profile_sha256: str | None = None
) -> None:
    """Supplier permission is necessary even for public and standalone real routes."""
    now = MetadataTime(checked_at=now).checked_at
    rows = [
        row
        for row in installed_enrollment().qualifications
        if row.scope.provider == "FPL"
        and row.scope.profile_sha256 == profile_sha256
        and row.qualified_at <= now < row.valid_until
        and any(
            (route.method, route.host, route.path) == (method, host, path)
            for route in row.scope.routes
        )
    ]
    if len(rows) != 1:
        raise OperationError("FPL_SUPPLIER_PERMISSION_REQUIRED")
