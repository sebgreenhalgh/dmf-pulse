"""Nonsecret account facts and bounded review preparation; never an access grant."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from dmf_pulse.operation.models import Metadata, MetadataTime, Ref, Sha

Country = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
Count = Annotated[int, Field(ge=0)]


class ProposedPilotBudget(Metadata):
    """Owner-requested starting bounds, explicitly unaccepted."""

    sport: Literal["soccer_epl"] = "soccer_epl"
    region: Literal["uk"] = "uk"
    markets: tuple[Literal["h2h"], Literal["totals"]] = ("h2h", "totals")
    horizon: Literal[1] = 1
    requests: Literal[1] = 1
    reserved_credits: Literal[2] = 2
    automatic_retries: Literal[0] = 0
    daily_requests: Literal[1] = 1
    daily_credits: Literal[2] = 2
    period_requests: Literal[1] = 1
    period_credits: Literal[2] = 2
    acceptance: Literal["PROPOSED_NOT_ACCEPTED"] = "PROPOSED_NOT_ACCEPTED"

    @field_validator(
        "horizon",
        "requests",
        "reserved_credits",
        "automatic_retries",
        "daily_requests",
        "daily_credits",
        "period_requests",
        "period_credits",
        mode="before",
    )
    @classmethod
    def exact_integer_bounds(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("pilot bounds require exact integers")
        return value


class OddsAccountEvidence(Metadata):
    """An operator may fill this input locally; its facts remain owner-reported."""

    schema_version: Literal["odds-account-evidence-v1"] = "odds-account-evidence-v1"
    account_ref: Annotated[str, Field(pattern=r"^odds-account-[A-Za-z0-9_.:-]{1,80}$")]
    provenance: Literal["OWNER_REPORTED_REDACTED_ACCOUNT_EVIDENCE"] = (
        "OWNER_REPORTED_REDACTED_ACCOUNT_EVIDENCE"
    )
    evidence_ref: Ref | None = None
    redacted_evidence_sha256: Sha | None = None
    plan_name: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    plan_ref: Ref | None = None
    covered_sports: tuple[Ref, ...] | None = None
    covered_regions: tuple[Ref, ...] | None = None
    covered_markets: tuple[Ref, ...] | None = None
    operator_country: Country | None = None
    permitted_countries: tuple[Country, ...] | None = None
    permitted_purposes: tuple[Ref, ...] | None = None
    plan_credit_allowance: Annotated[int, Field(ge=1)] | None = None
    remaining_credits: Count | None = None
    used_credits: Count | None = None
    last_request_cost: Count | None = None
    observed_at: datetime | None = None
    period_started_at: datetime | None = None
    resets_at: datetime | None = None
    reset_period: Literal["CALENDAR_MONTH", "SUBSCRIPTION_MONTH", "CREDIT_PACK"] | None = None
    other_usage: Literal["EXCLUSIVE_ACCOUNT_DURING_PILOT", "QUALIFIED_RESERVATION"] | None = None
    other_usage_reserved_credits: Count | None = None
    safety_reserve_credits: Count | None = None
    proposed_quota_max_age_seconds: Annotated[int, Field(ge=1, le=86400)] | None = None
    terms_url: Literal["https://the-odds-api.com/terms-and-conditions.html"] = (
        "https://the-odds-api.com/terms-and-conditions.html"
    )
    terms_version: Ref | None = None
    terms_reviewed_at: datetime | None = None
    terms_evidence_sha256: Sha | None = None
    proposed_budget: ProposedPilotBudget = ProposedPilotBudget()

    @field_validator("plan_name")
    @classmethod
    def nonsecret_plan_label(cls, value: str | None) -> str | None:
        if value is not None and (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}", value) is None
            or re.fullmatch(r"[0-9a-fA-F]{24,80}", value) is not None
        ):
            raise ValueError("use a nonsecret plan label")
        return value

    @model_validator(mode="after")
    def consistent_facts(self) -> Self:
        for name in (
            "covered_sports",
            "covered_regions",
            "covered_markets",
            "permitted_countries",
            "permitted_purposes",
        ):
            values = getattr(self, name)
            if values is not None and len(values) != len(set(values)):
                raise ValueError("duplicate account entitlement fact")
        if self.plan_credit_allowance is not None and any(
            value is not None and value > self.plan_credit_allowance
            for value in (self.remaining_credits, self.used_credits)
        ):
            raise ValueError("reported usage exceeds the account allowance")
        if (
            self.last_request_cost is not None
            and self.used_credits is not None
            and self.last_request_cost > self.used_credits
        ):
            raise ValueError("last request cost exceeds reported usage")
        if (
            self.other_usage == "EXCLUSIVE_ACCOUNT_DURING_PILOT"
            and self.other_usage_reserved_credits not in (None, 0)
        ):
            raise ValueError("exclusive account cannot have another reserved consumer")
        if (
            self.period_started_at is not None
            and self.resets_at is not None
            and self.period_started_at >= self.resets_at
        ):
            raise ValueError("account reset period is empty")
        if self.observed_at is not None:
            if self.period_started_at is not None and self.observed_at < self.period_started_at:
                raise ValueError("observation predates the quota period")
            if self.resets_at is not None and self.observed_at >= self.resets_at:
                raise ValueError("observation follows the quota reset")
        return self


class AccountReviewPackage(Metadata):
    schema_version: Literal["odds-account-review-package-v1"] = "odds-account-review-package-v1"
    prepared_at: datetime
    evidence: OddsAccountEvidence
    state: Literal["INCOMPLETE", "READY_FOR_INDEPENDENT_ACCOUNT_REVIEW"]
    blockers: tuple[Ref, ...]
    entitlement_verified: Literal[False] = False
    project_rights_approved: Literal[False] = False
    owner_budget_accepted: Literal[False] = False
    runtime_authority: Literal["NOT_GRANTED"] = "NOT_GRANTED"
    required_review: tuple[
        Literal["ACCOUNT_ENTITLEMENT", "NEW_ODDS_PURPOSE", "SUPPLIER_TERMS", "OWNER_BUDGET"], ...
    ] = ("ACCOUNT_ENTITLEMENT", "NEW_ODDS_PURPOSE", "SUPPLIER_TERMS", "OWNER_BUDGET")

    @model_validator(mode="after")
    def derived_state(self) -> Self:
        expected = account_blockers(self.evidence, self.prepared_at)
        if expected != self.blockers or (self.state == "INCOMPLETE") != bool(expected):
            raise ValueError("account review state differs from actual facts")
        if self.required_review != (
            "ACCOUNT_ENTITLEMENT",
            "NEW_ODDS_PURPOSE",
            "SUPPLIER_TERMS",
            "OWNER_BUDGET",
        ):
            raise ValueError("account review requirements are fixed")
        return self


def account_blockers(evidence: OddsAccountEvidence, now: datetime) -> tuple[str, ...]:
    """Completeness/freshness only; these checks do not authenticate any claim."""
    evidence = OddsAccountEvidence.model_validate(evidence)
    now = MetadataTime(checked_at=now).checked_at
    required = (
        "evidence_ref",
        "redacted_evidence_sha256",
        "plan_name",
        "plan_ref",
        "covered_sports",
        "covered_regions",
        "covered_markets",
        "operator_country",
        "permitted_countries",
        "permitted_purposes",
        "plan_credit_allowance",
        "remaining_credits",
        "observed_at",
        "period_started_at",
        "resets_at",
        "reset_period",
        "other_usage",
        "safety_reserve_credits",
        "proposed_quota_max_age_seconds",
        "terms_version",
        "terms_reviewed_at",
        "terms_evidence_sha256",
    )
    blockers = [
        "ACCOUNT_" + name.upper() + "_REQUIRED"
        for name in required
        if getattr(evidence, name) is None
    ]
    for name, needed, reason in (
        ("covered_sports", {"soccer_epl"}, "ACCOUNT_EPL_NOT_COVERED"),
        ("covered_regions", {"uk"}, "ACCOUNT_UK_MARKET_REGION_NOT_COVERED"),
        ("covered_markets", {"h2h", "totals"}, "ACCOUNT_REQUIRED_MARKETS_NOT_COVERED"),
        (
            "permitted_purposes",
            {"PRIVATE_OPERATOR_FPL_RECOMMENDATIONS"},
            "ACCOUNT_PURPOSE_NOT_COVERED",
        ),
    ):
        values = getattr(evidence, name)
        if values is not None and not needed <= set(values):
            blockers.append(reason)
    if (
        evidence.operator_country is not None
        and evidence.permitted_countries is not None
        and evidence.operator_country not in evidence.permitted_countries
    ):
        blockers.append("ACCOUNT_OPERATOR_GEOGRAPHY_NOT_COVERED")
    if (
        evidence.other_usage == "QUALIFIED_RESERVATION"
        and evidence.other_usage_reserved_credits is None
    ):
        blockers.append("ACCOUNT_OTHER_USAGE_RESERVATION_REQUIRED")
    if evidence.observed_at is not None:
        if evidence.observed_at > now:
            blockers.append("ACCOUNT_OBSERVATION_IN_FUTURE")
        if (
            evidence.proposed_quota_max_age_seconds is not None
            and (now - evidence.observed_at).total_seconds()
            > evidence.proposed_quota_max_age_seconds
        ):
            blockers.append("ACCOUNT_OBSERVATION_STALE")
    if evidence.resets_at is not None and evidence.resets_at <= now:
        blockers.append("ACCOUNT_QUOTA_PERIOD_EXPIRED")
    if evidence.terms_reviewed_at is not None and evidence.terms_reviewed_at > now:
        blockers.append("ACCOUNT_TERMS_REVIEW_IN_FUTURE")
    if evidence.remaining_credits is not None and evidence.safety_reserve_credits is not None:
        other = evidence.other_usage_reserved_credits
        if other is None and evidence.other_usage == "EXCLUSIVE_ACCOUNT_DURING_PILOT":
            other = 0
        if (
            other is not None
            and evidence.remaining_credits < 2 + evidence.safety_reserve_credits + other
        ):
            blockers.append("ACCOUNT_QUALIFIED_AVAILABLE_CREDITS_INSUFFICIENT")
    return tuple(blockers)


def prepare_account_review(evidence: OddsAccountEvidence, *, now: datetime) -> AccountReviewPackage:
    now = MetadataTime(checked_at=now).checked_at
    evidence = OddsAccountEvidence.model_validate(evidence)
    blockers = account_blockers(evidence, now)
    return AccountReviewPackage(
        prepared_at=now,
        evidence=evidence,
        blockers=blockers,
        state="INCOMPLETE" if blockers else "READY_FOR_INDEPENDENT_ACCOUNT_REVIEW",
    )
