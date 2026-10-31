"""Exact installed new-purpose Odds authority for the transient operator path only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import (
    CapabilityValue,
    RightsCapability,
    RightsProfile,
    RightsProfileStatus,
)
from dmf_pulse.ingestion.odds.config import provider_config_sha256, rights_config_sha256
from dmf_pulse.ingestion.odds.models import QualifiedOperatorQuota, QuotaState

if TYPE_CHECKING:
    from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
    from dmf_pulse.operation.enrollment import SourceQualification

PRIVATE_OPERATOR_PROFILE_ID = "the_odds_api_private_operator_recommendations_v1"
PRIVATE_OPERATOR_GEOGRAPHY = (
    "private DMF Pulse analytical use from Italy and the United Kingdom (IT, GB)"
)
PrivateCurrentOddsProfileId = Literal[
    "the_odds_api_private_analytics_v1", "the_odds_api_private_operator_recommendations_v1"
]
_PURPOSE = "PRIVATE_OPERATOR_FPL_RECOMMENDATIONS"
_TERMS_SOURCE = "https://the-odds-api.com/terms-and-conditions.html"
_ALLOWED = frozenset(
    {
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.DERIVED_STORAGE,
        RightsCapability.PRIVATE_INTERNAL_USE,
    }
)


def _blocked() -> IngestionError:
    return IngestionError(
        "RIGHTS_BLOCKED", "new-purpose Odds use requires exact current installed qualification"
    )


def _utc(checked_at: datetime) -> datetime:
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise _blocked()
    return checked_at.astimezone(UTC)


def _qualified_row(profile: RightsProfile, *, checked_at: datetime) -> SourceQualification:
    from dmf_pulse.operation.enrollment import installed_enrollment, rights_fingerprint
    from dmf_pulse.operation.models import OperationError

    checked = _utc(checked_at)
    exact = (
        profile.rights_profile_id == PRIVATE_OPERATOR_PROFILE_ID
        and profile.provider_key == "the_odds_api"
        and profile.profile_version == "1.0.0"
        and profile.status is RightsProfileStatus.HUMAN_APPROVED
        and profile.approved_purpose == _PURPOSE
        and profile.geography_scope == PRIVATE_OPERATOR_GEOGRAPHY
        and profile.terms_source == _TERMS_SOURCE
        and profile.retention_seconds == 0
        and profile.termination_deletion_required
        and not profile.unresolved_rights
        and not profile.attribution_required
        and profile.attribution_text is None
        and all(
            profile.capabilities[capability]
            is (CapabilityValue.ALLOW if capability in _ALLOWED else CapabilityValue.DENY)
            for capability in RightsCapability
        )
    )
    try:
        qualifications = installed_enrollment().qualifications if exact else ()
    except OperationError:
        qualifications = ()
    rows = [
        row
        for row in qualifications
        if row.scope.provider == "ODDS"
        and row.scope.source_kind == "RIGHTS_QUALIFIED_PRIVATE"
        and row.scope.profile_id == PRIVATE_OPERATOR_PROFILE_ID
        and row.scope.profile_sha256 == rights_fingerprint(profile)
        and row.profile == profile
    ]
    if len(rows) != 1:
        raise _blocked()
    row = rows[0]
    if (
        row.purpose != _PURPOSE
        or row.account_review_sha256 is None
        or row.operator_country not in {"IT", "GB"}
        or profile.account_scope != "qualified private Odds account: " + row.scope.account_ref
        or not profile.approved_at <= profile.checked_at <= row.qualified_at <= checked
        or checked >= row.valid_until
        or not row.control_metadata_retention_approved
        or tuple(
            (route.method, route.host, route.path, route.maximum_calls)
            for route in row.scope.routes
        )
        != (("GET", "api.the-odds-api.com", "/v4/sports/soccer_epl/odds", 1),)
    ):
        raise _blocked()
    return row


def require_private_operator_profile(profile: RightsProfile, *, checked_at: datetime) -> str:
    """Return the selected complete rights-config identity; this issues no execution grant."""
    row = _qualified_row(profile, checked_at=checked_at)
    return canonical_sha256(
        {
            "schema_version": "private-operator-odds-rights-authority-v1",
            "packaged_rights_config_sha256": rights_config_sha256(),
            "installed_source_qualification": row.model_dump(mode="json"),
        }
    )


def private_operator_authority(*, checked_at: datetime) -> tuple[RightsProfile, str]:
    from dmf_pulse.operation.enrollment import installed_enrollment
    from dmf_pulse.operation.models import OperationError

    try:
        rows = [
            row
            for row in installed_enrollment().qualifications
            if row.scope.provider == "ODDS" and row.scope.profile_id == PRIVATE_OPERATOR_PROFILE_ID
        ]
    except OperationError:
        rows = []
    if len(rows) != 1:
        raise _blocked()
    profile = rows[0].profile
    return profile, require_private_operator_profile(profile, checked_at=checked_at)


def require_private_operator_quota(
    profile: RightsProfile,
    quota: QuotaState | QualifiedOperatorQuota | None,
    *,
    checked_at: datetime,
) -> None:
    """Use the installed reviewed account observation; the existing ledger still reserves it."""
    from dmf_pulse.operation.enrollment import installed_enrollment

    checked = _utc(checked_at)
    row = _qualified_row(profile, checked_at=checked)
    if not isinstance(quota, QualifiedOperatorQuota):
        raise IngestionError(
            "QUOTA_EVIDENCE_REQUIRED", "qualified new-purpose account quota required"
        )
    approvals = [
        approval
        for approval in installed_enrollment().approvals
        if row.scope in approval.source_scopes
        and approval.classification == "PRIVATE_CURRENT"
        and approval.status == "APPROVED_REVIEWED"
        and approval.plan_quota.account_ref == row.scope.account_ref
        and approval.plan_quota.evidence_sha256 == quota.evidence_sha256
        and approval.plan_quota.observed_at == quota.observed_at
        and approval.plan_quota.remaining_credits == quota.remaining
        and approval.not_before <= checked < approval.expires_at
        and approval.qualified_deadline_at is not None
        and checked < approval.qualified_deadline_at
        and approval.plan_quota.period_started_at <= checked < approval.plan_quota.resets_at
        and quota.observed_at
        <= checked
        <= quota.observed_at + timedelta(seconds=approval.quota_max_age_seconds)
    ]
    if len(approvals) != 1:
        raise IngestionError(
            "QUOTA_EVIDENCE_REQUIRED", "new-purpose account observation is unqualified"
        )
    if quota.remaining < 2 + approvals[0].safety_reserve_credits:
        raise IngestionError("QUOTA_EXHAUSTED", "new-purpose account quota is insufficient")


def require_private_operator_input(value: OddsProviderCurrentInput) -> tuple[RightsProfile, str]:
    """Authenticate truthful selected-profile lineage without relabeling the consumed profile."""
    from dmf_pulse.ingestion.odds.current import _rights_state

    profile, identity = private_operator_authority(checked_at=value.temporal.usable_at)
    if (
        value.rights != _rights_state(profile, value.temporal.received_at)
        or value.provenance.provider_config_sha256 != provider_config_sha256()
        or value.provenance.rights_config_sha256 != identity
        or value.provenance.effective_config_sha256
        != canonical_sha256(
            {"provider_config_sha256": provider_config_sha256(), "rights_config_sha256": identity}
        )
        or value.provenance.raw_payload_retained
    ):
        raise _blocked()
    return profile, identity
