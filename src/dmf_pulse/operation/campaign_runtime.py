"""Process-scoped source closure for a verified canonical diagnostic session.

No caller path, environment flag or owner-supplied JSON enrolls authority. The
scope is entered only after the fixed signed authority and journal are checked.
Outside the scope the ordinary standing resolver remains in control.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dmf_pulse.dashboard.authorization import OperatorRefreshApproval, QualifiedPlanQuota
from dmf_pulse.operation.campaign import DiagnosticPaidGateProof
from dmf_pulse.operation.discovery import EventDiscovery, fpl_routes
from dmf_pulse.operation.enrollment import InstalledEnrollment
from dmf_pulse.operation.models import MetadataTime, OperationError
from dmf_pulse.operation.standing import QuotaProof, VerifiedPeriod

if TYPE_CHECKING:
    from dmf_pulse.operation.campaign_authority import VerifiedCampaignAuthority
    from dmf_pulse.operation.campaign_journal import DiagnosticJournal, DiagnosticSession


@dataclass(slots=True, repr=False)
class _Runtime:
    authority: VerifiedCampaignAuthority
    session: DiagnosticSession
    journal: DiagnosticJournal
    clock: Callable[[], datetime]
    registry: InstalledEnrollment
    event: EventDiscovery | None = None
    paid_cutoff: datetime | None = None


_active: ContextVar[_Runtime | None] = ContextVar("verified_gw10_diagnostic_scope", default=None)


def _production_utc_now() -> datetime:
    return datetime.now(UTC)


def campaign_runtime_enrollment() -> InstalledEnrollment | None:
    runtime = _active.get()
    if runtime is None:
        return None
    now = MetadataTime(checked_at=runtime.clock()).checked_at
    ceiling = min(
        runtime.session.lease_until,
        runtime.event.deadline_at if runtime.event is not None else runtime.session.lease_until,
    )
    if not runtime.session.started_at <= now < ceiling:
        raise OperationError("DIAGNOSTIC_SESSION_CLOSED_CHANGED_OR_EXPIRED")
    return runtime.registry


def require_runtime(key: str) -> _Runtime:
    runtime = _active.get()
    if runtime is None or runtime.session.session_key != key:
        raise OperationError("DIAGNOSTIC_VERIFIED_PROCESS_SCOPE_REQUIRED")
    campaign_runtime_enrollment()
    return runtime


def _source_registry(
    authority: VerifiedCampaignAuthority,
    session: DiagnosticSession,
    *,
    event: EventDiscovery | None,
    expires_at: datetime,
) -> InstalledEnrollment:
    policy = authority.normal_policy
    qualified = []
    for source in policy.qualifications:
        if event is None and source.scope.provider != "FPL":
            continue
        routes = source.scope.routes
        if source.scope.provider == "FPL":
            routes = (
                fpl_routes(policy.entry_id, event)
                if event is not None
                else tuple(route for route in routes if route.path == "/api/bootstrap-static/")
            )
            if not routes:
                raise OperationError("DIAGNOSTIC_BOOTSTRAP_SCOPE_INVALID")
        qualified.append(
            source.model_copy(
                update={
                    "qualification_id": f"OPR003-{session.session_key[:32]}-{source.scope.provider}",
                    "scope": source.scope.model_copy(update={"routes": routes}),
                    "qualified_at": session.started_at,
                    "valid_until": expires_at,
                }
            )
        )
    return InstalledEnrollment(qualifications=tuple(qualified))


@contextmanager
def diagnostic_source_context(
    journal: DiagnosticJournal,
    key: str,
) -> Iterator[DiagnosticJournal]:
    from dmf_pulse.operation.campaign_journal import DiagnosticJournal

    if _active.get() is not None:
        raise OperationError("DIAGNOSTIC_PROCESS_SCOPE_ALREADY_ACTIVE")
    canonical = DiagnosticJournal.production()
    if canonical.original.policy != journal.original.policy:
        raise OperationError("DIAGNOSTIC_ORIGINAL_CONTROL_BINDING_CHANGED")
    with canonical._transaction() as (authority, _, rows):
        selected = canonical._tagged(rows, authority.proposal)
        session = canonical._active(authority, selected, key, _production_utc_now())
    runtime = _Runtime(
        authority,
        session,
        canonical,
        _production_utc_now,
        _source_registry(authority, session, event=None, expires_at=session.lease_until),
    )
    token = _active.set(runtime)
    try:
        yield canonical
    finally:
        _active.reset(token)


def bind_official_discovery(key: str, event: EventDiscovery) -> None:
    runtime = require_runtime(key)
    proposal = runtime.authority.proposal
    if (
        runtime.event is not None
        or event.target_gameweek != proposal.gameweek
        or not runtime.session.started_at <= event.request_started_at <= event.received_at
        or event.received_at > runtime.clock()
        or not runtime.clock() < min(event.deadline_at, proposal.deadline_not_after)
    ):
        raise OperationError("DIAGNOSTIC_FRESH_GW10_DISCOVERY_REQUIRED")
    runtime.journal.record_discovery(key, event, now=runtime.clock())
    runtime.event = event
    runtime.registry = _source_registry(
        runtime.authority,
        runtime.session,
        event=event,
        expires_at=min(runtime.session.lease_until, event.deadline_at),
    )


def paid_enrollment(
    runtime: _Runtime,
    gate: DiagnosticPaidGateProof,
    quota: QuotaProof,
    period: VerifiedPeriod,
    *,
    now: datetime,
    expires_at: datetime,
) -> InstalledEnrollment:
    """Derive only inside the original locked journal's checked paid-gate path."""
    policy, session, event = runtime.authority.normal_policy, runtime.session, runtime.event
    if (
        event is None
        or event.target_gameweek != gate.official_gameweek
        or event.deadline_at != gate.official_deadline_at
        or quota.received_at != gate.quota_received_at
        or quota.remaining_credits != gate.quota_remaining_credits
        or quota.used_credits != gate.quota_used_credits
        or period.quota_sha256 != quota.semantic_sha256
        or period.resets_at < expires_at
    ):
        raise OperationError("DIAGNOSTIC_PAID_SOURCE_BINDING_INVALID")
    registry = _source_registry(runtime.authority, session, event=event, expires_at=expires_at)
    approval = OperatorRefreshApproval(
        authorization_id=f"OPR003-{session.session_key}",
        classification="PRIVATE_CURRENT",
        approval_evidence_sha256=runtime.authority.acceptance.semantic_sha256,
        implementation_sha=policy.implementation_sha,
        review_sha256=policy.independent_review_sha256,
        operator_ref=policy.owner_ref,
        purpose=policy.purpose,
        season_code=policy.season_code,
        horizons=(1,),
        source_scopes=tuple(q.scope for q in registry.qualifications),
        plan_quota=QualifiedPlanQuota(
            account_ref=policy.odds_account_ref,
            plan_ref=policy.plan_ref,
            evidence_sha256=quota.observation_sha256,
            terms_evidence_sha256=policy.quota_terms_sha256,
            monthly_plan_credits=policy.plan_credit_allowance,
            allocated_monthly_credits=policy.limits.monthly_credits,
            remaining_credits=quota.remaining_credits,
            observed_at=quota.received_at,
            period_started_at=period.started_at,
            resets_at=period.resets_at,
        ),
        ledger_id=policy.ledger_id,
        ledger_backend="POSTGRES",
        status="APPROVED_REVIEWED",
        usage="ONE_SHOT",
        approved_at=runtime.authority.acceptance.accepted_at,
        not_before=now,
        expires_at=expires_at,
        quota_max_age_seconds=runtime.authority.proposal.limits.quota_max_age_seconds,
        max_acquisition_seconds=300,
        max_run_seconds=900,
        qualified_deadline_at=event.deadline_at,
        # Account-wide retained reservations remain inclusive. The separate
        # campaign ceiling permits four diagnostic reservations plus the old one.
        daily_request_limit=5,
        daily_credit_limit=10,
        monthly_request_limit=policy.limits.monthly_requests,
        monthly_credit_limit=policy.limits.monthly_credits,
        safety_reserve_credits=runtime.authority.proposal.limits.safety_reserve_credits,
        control_metadata_retention_approved=True,
    )
    return registry.model_copy(update={"approvals": (approval,)})
