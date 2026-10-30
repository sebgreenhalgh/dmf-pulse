"""Read-only validation against the installed enrollment and shared current policy."""

from __future__ import annotations

from typing import Literal

from dmf_pulse.dashboard.authorization import (
    AuthorizationError,
    AuthorizationPreview,
    production_approvals,
)
from dmf_pulse.dashboard.current import CurrentRefreshSession
from dmf_pulse.operation.models import (
    Metadata,
    OperatorReadiness,
    Ref,
    Stage,
    StageCheck,
    readiness,
)


class InstalledValidation(Metadata):
    schema_version: Literal["installed-operation-validation-v1"] = (
        "installed-operation-validation-v1"
    )
    authorization_id: Ref
    preview: AuthorizationPreview
    readiness: OperatorReadiness
    reservation_created: Literal[False] = False
    credentials_checked: Literal[False] = False
    provider_contacted: Literal[False] = False


def validate_installed(
    *,
    authorization_id: str,
    entry_id: int,
    horizon: Literal[1, 3] = 1,
) -> InstalledValidation:
    """A preview is not a grant; actual Refresh repeats the complete locked checks."""
    if type(entry_id) is not int or entry_id < 1:
        raise AuthorizationError("AUTHORIZATION_SCOPE_MISMATCH")
    rows = [row for row in production_approvals() if row.authorization_id == authorization_id]
    if len(rows) != 1:
        raise AuthorizationError(
            "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED", "RIGHTS_APPROVAL_REQUIRED"
        )
    approval = rows[0]
    if approval.qualified_deadline_at is None:
        raise AuthorizationError("AUTHORIZATION_DEADLINE_SCOPE_MISMATCH")
    session = CurrentRefreshSession.enrolled(
        authorization_id=authorization_id,
        entry_id=entry_id,
        deadline_at=approval.qualified_deadline_at,
    )
    preview = session.preflight(horizon)
    evidence = (preview.approval_sha256, preview.request_sha256)
    verified_stages: tuple[Stage, ...] = (
        "ACCOUNT_ENTITLEMENT_VERIFIED",
        "PROJECT_RIGHTS_APPROVED",
        "CONTROL_LEDGER_READY",
        "LIVE_PILOT_AUTHORIZED",
    )
    checks = tuple(
        StageCheck(
            stage=stage,
            state="VERIFIED",
            checked_at=preview.checked_at,
            valid_until=preview.expires_at,
            reason_code="INSTALLED_APPROVAL_AND_SHARED_PREFLIGHT",
            evidence_sha256=evidence,
        )
        for stage in verified_stages
    )
    return InstalledValidation(
        authorization_id=authorization_id,
        preview=preview,
        readiness=readiness(now=preview.checked_at, checks=checks),
    )
