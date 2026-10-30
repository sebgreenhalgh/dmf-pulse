"""Nonsecret operator facts and remedies; drafts never become executable grants."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from dmf_pulse.operation.account import OddsAccountEvidence, prepare_account_review
from dmf_pulse.operation.enrollment import installed_enrollment
from dmf_pulse.operation.models import (
    CredentialObservation,
    Metadata,
    MetadataTime,
    OperatorReadiness,
    Stage,
    StageCheck,
    readiness,
)
from dmf_pulse.operation.packages import read_nonexecuting_input
from dmf_pulse.player_lab.compatibility import FutureCohortProposal, future_cohort_proposal


class CredentialDetail(Metadata):
    provider: Literal["odds", "fpl"]
    state: Literal["NOT_CHECKED", "CONFIGURED", "MISSING", "EXPIRED", "UNAVAILABLE", "CORRUPT"]
    configured: bool | None = None
    expires_at: datetime | None = None
    registered_at: datetime | None = None
    provider_authentication_performed: Literal[False] = False


class OperationalReadiness(Metadata):
    schema_version: Literal["operator-detailed-readiness-v1"] = "operator-detailed-readiness-v1"
    readiness: OperatorReadiness
    credentials: tuple[CredentialDetail, ...]
    account_input_state: Literal[
        "NOT_SUPPLIED", "INCOMPLETE", "READY_FOR_INDEPENDENT_ACCOUNT_REVIEW"
    ]
    missing_account_facts: tuple[str, ...]
    account_evidence_sha256: str | None = None
    reported_remaining_credits: int | None = None
    qualified_available_budget: Literal["NOT_CHECKED_REQUIRES_INSTALLED_PREFLIGHT"] = (
        "NOT_CHECKED_REQUIRES_INSTALLED_PREFLIGHT"
    )
    enrollment_state: Literal["MISSING_TRUSTED_DEFAULT", "INSTALLED_REQUIRES_CURRENT_PREFLIGHT"]
    next_deadline_candidate: FutureCohortProposal
    source_freshness: Literal["NOT_CHECKED_NO_PROVIDER_REQUEST"] = "NOT_CHECKED_NO_PROVIDER_REQUEST"
    actual_information_set: Literal["NONE_ACQUIRED_BY_READINESS"] = "NONE_ACQUIRED_BY_READINESS"
    operator_actions: tuple[str, ...]
    provider_requests: Literal[0] = 0
    reservation_created: Literal[False] = False
    production_active: Literal[False] = False


def detailed_readiness(
    *, now: datetime, check_credentials: bool = False, account_input: Path | None = None
) -> OperationalReadiness:
    now = MetadataTime(checked_at=now).checked_at
    facts = (
        OddsAccountEvidence(account_ref="odds-account-local-owner")
        if account_input is None
        else read_nonexecuting_input(account_input, OddsAccountEvidence)
    )
    account = prepare_account_review(facts, now=now)
    registry = installed_enrollment()
    enrolled = registry.default_authorization_id is not None and any(
        row.authorization_id == registry.default_authorization_id for row in registry.approvals
    )
    details = []
    observations = None
    providers: tuple[Literal["odds", "fpl"], ...] = ("odds", "fpl")
    if check_credentials:
        from dmf_pulse.credentials.service import CredentialError, CredentialService

        service = CredentialService()
        rows = []
        for provider in providers:
            try:
                status = service.status(provider)
                observed_state = status.state
                detail = CredentialDetail(
                    provider=provider,
                    state=status.state,
                    configured=status.configured,
                    expires_at=status.expires_at,
                    registered_at=status.registered_at,
                )
            except CredentialError:
                observed_state = "UNAVAILABLE"
                detail = CredentialDetail(provider=provider, state="UNAVAILABLE", configured=False)
            details.append(detail)
            rows.append(
                CredentialObservation(
                    provider=provider, configured=detail.configured is True, state=observed_state
                )
            )
        observations = tuple(rows)
    else:
        details = [
            CredentialDetail(provider=provider, state="NOT_CHECKED") for provider in providers
        ]
    blocked_stages: tuple[Stage, ...] = (
        "ACCOUNT_ENTITLEMENT_VERIFIED",
        "PROJECT_RIGHTS_APPROVED",
        "CONTROL_LEDGER_READY",
        "LIVE_PILOT_AUTHORIZED",
    )
    checks = tuple(
        StageCheck(
            stage=stage,
            state="BLOCKED",
            checked_at=now,
            reason_code="TRUSTED_ENROLLMENT_REQUIRED"
            if not enrolled
            else "EXPLICIT_INSTALLED_PREFLIGHT_REQUIRED",
        )
        for stage in blocked_stages
    )
    actions = (
        "Complete the private nonsecret account draft, then run operation review-account; a complete draft still requires independent review.",
        "Obtain exact supplier permission for FPL automated routes and a new Odds pilot purpose; the old risk acceptance and consumed purpose do not grant these.",
        "Register a freshly issued FPL replacement locally with credentials set fpl --fresh-issued --expires-at <actual-UTC-expiry>; input stays hidden.",
        "Have the exact manager-bound package, source qualifications, budget, deadline, code and wheel independently reviewed and separately accepted; install only that reviewed private wheel.",
        "Validate the canonical PostgreSQL control ledger and current quota before a manually initiated refresh.",
        "After reviewed installation, run operation launch, pair the browser and click Refresh once. Launch and page reload do not fetch data.",
    )
    return OperationalReadiness(
        readiness=readiness(now=now, checks=checks, credentials=observations),
        credentials=tuple(details),
        account_input_state="NOT_SUPPLIED" if account_input is None else account.state,
        missing_account_facts=account.blockers,
        account_evidence_sha256=None if account_input is None else facts.semantic_sha256,
        reported_remaining_credits=facts.remaining_credits,
        enrollment_state="INSTALLED_REQUIRES_CURRENT_PREFLIGHT"
        if enrolled
        else "MISSING_TRUSTED_DEFAULT",
        next_deadline_candidate=future_cohort_proposal(assessed_at=now),
        operator_actions=actions,
    )
