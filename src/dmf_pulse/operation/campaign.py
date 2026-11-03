"""Exact GW10 diagnostic proposal and budget arithmetic; no runtime authority.

These pure contracts prepare the owner's separate material decision. Constructing
or reading a proposal cannot enroll a session, reserve money or admit transport.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.operation.models import Metadata, MetadataTime, OperationError, Ref, Sha

SessionMode = Literal["READ_ONLY", "PAID_ELIGIBLE"]
One = Literal[1]
Two = Literal[2]
Four = Literal[4]
Twenty = Literal[20]


class DiagnosticLimits(Metadata):
    maximum_sessions: Literal[8] = 8
    fpl_gets_per_session: Twenty = 20
    paid_eligible_sessions: Literal[4] = 4
    paid_gets_total: Literal[4] = 4
    paid_gets_per_session: One = 1
    reserved_credits_per_paid_session: Two = 2
    reserved_credits_total: Literal[8] = 8
    safety_reserve_credits: Literal[10] = 10
    openfootball_gets_per_session: Four = 4
    quota_gets_per_session: Two = 2
    quota_gets_campaign_total: Literal[12] = 12
    automatic_retries: Literal[0] = 0
    concurrent_sessions: Literal[1] = 1
    quota_max_age_seconds: Literal[300] = 300
    maximum_session_seconds: Literal[1800] = 1800
    maximum_pre_paid_seconds: Literal[1200] = 1200
    minimum_fpl_credential_remaining_seconds: Literal[2100] = 2100

    @field_validator("*", mode="before")
    @classmethod
    def integer_limits(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("diagnostic limits require exact integers")
        return value


class DiagnosticCampaignProposal(Metadata):
    schema_version: Literal["gw10-diagnostic-campaign-proposal-v1"] = (
        "gw10-diagnostic-campaign-proposal-v1"
    )
    state: Literal["PROPOSED_NO_RUNTIME_AUTHORITY"] = "PROPOSED_NO_RUNTIME_AUTHORITY"
    campaign_id: Literal["GW10-DIAGNOSTIC-CAMPAIGN-001"] = "GW10-DIAGNOSTIC-CAMPAIGN-001"
    owner_request_sha256: Sha
    owner_ref: Ref
    entry_id: Annotated[int, Field(ge=1)]
    season_code: Literal["2026/27"] = "2026/27"
    gameweek: Literal[10] = 10
    permitted_countries: tuple[Literal["IT"], Literal["GB"]] = ("IT", "GB")
    original_ledger_id: Sha
    odds_account_ref: Ref
    plan_ref: Ref
    plan_credit_allowance: Annotated[int, Field(ge=1)]
    original_consumed_execution_key: Sha
    original_standing_material_sha256: Sha
    original_standing_policy_sha256: Sha
    original_owner_acceptance_sha256: Sha
    original_root_trust_sha256: Sha
    review_public_key_sha256: Sha
    protected_numerical_sha256: Sha
    original_marker_manifest_sha256: Sha
    permission_provenance: Literal["OWNER_ATTESTED_NOT_ISSUER_AUTHENTICATED"] = (
        "OWNER_ATTESTED_NOT_ISSUER_AUTHENTICATED"
    )
    fpl_permission_sha256: Sha
    odds_permission_sha256: Sha
    source_scope_sha256: Sha
    official_deadline_observation_sha256: Sha
    deadline_not_after: datetime
    created_at: datetime
    limits: DiagnosticLimits = DiagnosticLimits()
    reservation_timing: Literal["AFTER_CONTROLLED_GATE_BEFORE_PAID_SUBGRANT_NO_REFUND"] = (
        "AFTER_CONTROLLED_GATE_BEFORE_PAID_SUBGRANT_NO_REFUND"
    )
    paid_admission: Literal["AFTER_REAL_FPL_AND_CONTROLLED_MARKET_PIPELINE_PASS"] = (
        "AFTER_REAL_FPL_AND_CONTROLLED_MARKET_PIPELINE_PASS"
    )
    shared_budget_accounting: Literal["ALL_ORIGINAL_ACCOUNT_RESERVATIONS_REMAIN_COUNTED"] = (
        "ALL_ORIGINAL_ACCOUNT_RESERVATIONS_REMAIN_COUNTED"
    )
    result_label: Literal["GW10 diagnostic / forecasts unvalidated"] = (
        "GW10 diagnostic / forecasts unvalidated"
    )
    raw_source_body_retention: Literal["DENIED_TRANSIENT_MEMORY_ONLY"] = (
        "DENIED_TRANSIENT_MEMORY_ONLY"
    )
    standing_material_policy_changed: Literal[False] = False
    fpl_writes: Literal[False] = False
    numerical_model_changed: Literal[False] = False
    source_routes_expanded: Literal[False] = False

    @field_validator("entry_id", "gameweek", mode="before")
    @classmethod
    def integer_identity(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("diagnostic identity requires exact integers")
        return value

    @field_validator(
        "standing_material_policy_changed",
        "fpl_writes",
        "numerical_model_changed",
        "source_routes_expanded",
        mode="before",
    )
    @classmethod
    def boolean_denials(cls, value: object) -> object:
        if value is not False:
            raise ValueError("diagnostic exclusions require boolean false")
        return value

    @model_validator(mode="after")
    def current_window(self) -> Self:
        if self.created_at >= self.deadline_not_after:
            raise ValueError("diagnostic proposal is outside the GW10 window")
        return self


class DiagnosticSessionSummary(Metadata):
    """Authenticated journal projections are supplied by the custody layer."""

    campaign_sha256: Sha
    session_index: Annotated[int, Field(ge=1, le=8)]
    mode: SessionMode
    started_at: datetime
    terminal: bool
    inspected: bool
    successful_real_recommendation: bool
    unresolved_paid_consumption: bool
    paid_credits_reserved: bool = False
    terminal_diagnostics_sha256: Sha | None = None
    real_publication_sha256: Sha | None = None

    @field_validator("session_index", mode="before")
    @classmethod
    def integer_index(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("diagnostic session index requires exact integer")
        return value

    @model_validator(mode="after")
    def exact_inspection(self) -> Self:
        if self.inspected and (not self.terminal or self.terminal_diagnostics_sha256 is None):
            raise ValueError("inspection requires a terminal immutable diagnostic receipt")
        if self.successful_real_recommendation and not self.terminal:
            raise ValueError("success requires a terminal publication")
        if self.successful_real_recommendation and (
            self.mode != "PAID_ELIGIBLE"
            or not self.paid_credits_reserved
            or self.unresolved_paid_consumption
            or self.real_publication_sha256 is None
        ):
            raise ValueError(
                "real success requires settled paid input and an immutable publication"
            )
        if self.paid_credits_reserved and self.mode != "PAID_ELIGIBLE":
            raise ValueError("read-only sessions cannot reserve paid credits")
        if self.unresolved_paid_consumption and not self.paid_credits_reserved:
            raise ValueError("unknown paid consumption requires an admitted reservation")
        return self


class DiagnosticBudgetPreview(Metadata):
    state: Literal["BUDGET_PREVIEW_NOT_AUTHORIZATION"] = "BUDGET_PREVIEW_NOT_AUTHORIZATION"
    campaign_sha256: Sha
    session_index: Annotated[int, Field(ge=1, le=8)]
    mode: SessionMode
    session_key: Sha
    reserved_credits: Literal[0, 2]
    remaining_sessions_after_admission: Annotated[int, Field(ge=0, le=7)]
    remaining_paid_eligible_sessions_after_admission: Annotated[int, Field(ge=0, le=4)]
    runtime_authority: Literal[False] = False


def preview_diagnostic_budget(
    proposal: DiagnosticCampaignProposal,
    sessions: tuple[DiagnosticSessionSummary, ...],
    *,
    mode: SessionMode,
    now: datetime,
    fresh_official_gameweek: int,
    fresh_official_deadline: datetime,
) -> DiagnosticBudgetPreview:
    """Fail closed on replay, exhausted/unknown spend and uninspected prior work.

    This does not authenticate its inputs or grant permission. The eventual
    accepted execution path must authenticate custody and hold its account lock.
    """
    now = MetadataTime(checked_at=now).checked_at
    deadline = MetadataTime(checked_at=fresh_official_deadline).checked_at
    if mode not in {"READ_ONLY", "PAID_ELIGIBLE"}:
        raise OperationError("DIAGNOSTIC_SESSION_MODE_INVALID")
    if type(fresh_official_gameweek) is not int or fresh_official_gameweek != proposal.gameweek:
        raise OperationError("DIAGNOSTIC_OFFICIAL_GAMEWEEK_MISMATCH")
    if not proposal.created_at <= now < min(deadline, proposal.deadline_not_after):
        raise OperationError("DIAGNOSTIC_WINDOW_EXPIRED_OR_REGRESSED")
    if len(sessions) >= proposal.limits.maximum_sessions:
        raise OperationError("DIAGNOSTIC_SESSION_LIMIT_EXHAUSTED")
    expected = tuple(range(1, len(sessions) + 1))
    if tuple(row.session_index for row in sessions) != expected or any(
        row.campaign_sha256 != proposal.semantic_sha256
        or not proposal.created_at <= row.started_at <= now
        for row in sessions
    ):
        raise OperationError("DIAGNOSTIC_SESSION_HISTORY_INVALID")
    if any(row.successful_real_recommendation for row in sessions):
        raise OperationError("DIAGNOSTIC_CAMPAIGN_ALREADY_SUCCEEDED")
    if any(not row.terminal or not row.inspected for row in sessions):
        raise OperationError("DIAGNOSTIC_PREVIOUS_SESSION_INSPECTION_REQUIRED")
    if mode == "PAID_ELIGIBLE" and any(row.unresolved_paid_consumption for row in sessions):
        raise OperationError("DIAGNOSTIC_PAID_CONSUMPTION_UNRESOLVED")
    paid = sum(row.mode == "PAID_ELIGIBLE" for row in sessions)
    if paid > proposal.limits.paid_eligible_sessions:
        raise OperationError("DIAGNOSTIC_SESSION_HISTORY_INVALID")
    if mode == "PAID_ELIGIBLE" and paid >= proposal.limits.paid_eligible_sessions:
        raise OperationError("DIAGNOSTIC_PAID_SLOT_LIMIT_EXHAUSTED")
    index = len(sessions) + 1
    return DiagnosticBudgetPreview(
        campaign_sha256=proposal.semantic_sha256,
        session_index=index,
        mode=mode,
        session_key=canonical_sha256(
            [
                "GW10_DIAGNOSTIC",
                proposal.original_ledger_id,
                proposal.original_consumed_execution_key,
                proposal.campaign_id,
                index,
            ]
        ),
        reserved_credits=0,
        remaining_sessions_after_admission=proposal.limits.maximum_sessions - index,
        remaining_paid_eligible_sessions_after_admission=(
            proposal.limits.paid_eligible_sessions - paid - (mode == "PAID_ELIGIBLE")
        ),
    )


class DiagnosticPaidGateProof(Metadata):
    campaign_sha256: Sha
    session_index: Annotated[int, Field(ge=1, le=8)]
    fpl_validation_sha256: Sha
    controlled_pipeline_sha256: Sha
    controlled_classification: Literal["REAL_FPL_CONTROLLED_MARKET_ENGINEERING"]
    actual_fpl_contracts_passed: Literal[True]
    stage8_stage9_stage12_passed: Literal[True]
    fpl_validation_completed_at: datetime
    controlled_pipeline_completed_at: datetime
    quota_received_at: datetime
    quota_remaining_credits: Annotated[int, Field(ge=0)]
    quota_used_credits: Annotated[int, Field(ge=0)]
    quota_reconciled_with_original_account: Literal[True]
    credential_expires_at: datetime
    official_gameweek: Literal[10]
    official_deadline_at: datetime

    @field_validator("official_gameweek", mode="before")
    @classmethod
    def exact_gameweek(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("official gameweek requires an exact integer")
        return value

    @field_validator(
        "actual_fpl_contracts_passed",
        "stage8_stage9_stage12_passed",
        "quota_reconciled_with_original_account",
        mode="before",
    )
    @classmethod
    def explicit_gate(cls, value: object) -> object:
        if value is not True:
            raise ValueError("paid diagnostic gate requires explicit boolean true")
        return value


class DiagnosticPaidReservationPreview(Metadata):
    state: Literal["PAID_RESERVATION_PREVIEW_NOT_AUTHORIZATION"] = (
        "PAID_RESERVATION_PREVIEW_NOT_AUTHORIZATION"
    )
    session_index: Annotated[int, Field(ge=1, le=8)]
    issued_at: datetime
    expires_at: datetime
    acquisition_ends_at: datetime
    gate_proof_sha256: Sha
    reserved_credits: Literal[2] = 2
    runtime_authority: Literal[False] = False


def preview_diagnostic_paid_reservation(
    proposal: DiagnosticCampaignProposal,
    sessions: tuple[DiagnosticSessionSummary, ...],
    proof: DiagnosticPaidGateProof,
    *,
    now: datetime,
) -> DiagnosticPaidReservationPreview:
    """A late reservation uses its actual time; it cannot backdate FPL authority."""
    now = MetadataTime(checked_at=now).checked_at
    if (
        not sessions
        or tuple(row.session_index for row in sessions) != tuple(range(1, len(sessions) + 1))
        or any(
            row.campaign_sha256 != proposal.semantic_sha256
            or not proposal.created_at <= row.started_at <= now
            for row in sessions
        )
    ):
        raise OperationError("DIAGNOSTIC_SESSION_HISTORY_INVALID")
    active = sessions[-1]
    if (
        active.mode != "PAID_ELIGIBLE"
        or active.terminal
        or active.paid_credits_reserved
        or any(not row.terminal or not row.inspected for row in sessions[:-1])
        or any(row.successful_real_recommendation for row in sessions[:-1])
    ):
        raise OperationError("DIAGNOSTIC_PAID_SESSION_NOT_ACTIVE")
    if any(row.unresolved_paid_consumption for row in sessions):
        raise OperationError("DIAGNOSTIC_PAID_CONSUMPTION_UNRESOLVED")
    if (
        sum(row.mode == "PAID_ELIGIBLE" for row in sessions)
        > proposal.limits.paid_eligible_sessions
        or sum(row.paid_credits_reserved for row in sessions) >= proposal.limits.paid_gets_total
    ):
        raise OperationError("DIAGNOSTIC_PAID_SLOT_LIMIT_EXHAUSTED")
    if (
        proof.campaign_sha256 != proposal.semantic_sha256
        or proof.session_index != active.session_index
    ):
        raise OperationError("DIAGNOSTIC_PAID_GATE_BINDING_INVALID")
    if (
        not proposal.created_at
        <= now
        < min(proof.official_deadline_at, proposal.deadline_not_after)
    ):
        raise OperationError("DIAGNOSTIC_WINDOW_EXPIRED_OR_REGRESSED")
    if now >= active.started_at + timedelta(seconds=proposal.limits.maximum_session_seconds):
        raise OperationError("DIAGNOSTIC_SESSION_WINDOW_EXPIRED")
    if now >= active.started_at + timedelta(seconds=proposal.limits.maximum_pre_paid_seconds):
        raise OperationError("DIAGNOSTIC_PRE_PAID_WINDOW_EXPIRED")
    age = (now - proof.quota_received_at).total_seconds()
    if not 0 <= age <= proposal.limits.quota_max_age_seconds:
        raise OperationError("DIAGNOSTIC_PAID_QUOTA_STALE")
    if not (
        active.started_at
        <= proof.fpl_validation_completed_at
        <= proof.controlled_pipeline_completed_at
        <= proof.quota_received_at
        <= now
    ):
        raise OperationError("DIAGNOSTIC_PAID_GATE_CHRONOLOGY_INVALID")
    if proof.quota_remaining_credits + proof.quota_used_credits != proposal.plan_credit_allowance:
        raise OperationError("DIAGNOSTIC_PAID_QUOTA_CONTRADICTS_PLAN")
    if proof.quota_remaining_credits < proposal.limits.safety_reserve_credits + 2:
        raise OperationError("DIAGNOSTIC_PAID_SAFETY_RESERVE_REQUIRED")
    expires = min(
        now + timedelta(seconds=900),
        active.started_at + timedelta(seconds=proposal.limits.maximum_session_seconds),
        proof.credential_expires_at,
        proof.official_deadline_at,
        proposal.deadline_not_after,
    )
    if expires <= now:
        raise OperationError("DIAGNOSTIC_PAID_CREDENTIAL_OR_WINDOW_EXPIRED")
    return DiagnosticPaidReservationPreview(
        session_index=active.session_index,
        issued_at=now,
        expires_at=expires,
        acquisition_ends_at=min(now + timedelta(seconds=300), expires),
        gate_proof_sha256=proof.semantic_sha256,
    )
