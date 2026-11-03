"""One signed owner attribution of observed prior usage; never HTTP proof."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.operation.campaign_authority import (
    CAMPAIGN_POLICY_SHA,
    CAMPAIGN_PROPOSAL_SHA,
    CAMPAIGN_REVIEWER_ROLE,
    ORIGINAL_TRUST_SHA,
    REVIEW_KEY_SHA,
    _body,
    load_verified_campaign,
)
from dmf_pulse.operation.maintenance import (
    RootTrust,
    material_policy_sha256,
    operator_root,
)
from dmf_pulse.operation.models import Metadata, MetadataTime, OperationError, Ref, Sha
from dmf_pulse.operation.quota import QUOTA_HOST, QUOTA_PATH
from dmf_pulse.operation.release_signatures import SignedReleaseManifest, verify_signed_manifest
from dmf_pulse.operation.standing import QuotaProof, StandingPolicy, next_month

KIND = "OWNER_ATTRIBUTED_AGGREGATE_PRIOR_USAGE"
ROLE = "OPR003_OWNER_ATTRIBUTED_PRIOR_USAGE_NOT_HTTP_PROVEN"
OWNER_SHA = "c99fb8afe7851590429b9dade340e3c1ad169527caa9c7031faf6cb786581269"


class PriorUsageFact(Metadata):
    schema_version: Literal["owner-attributed-prior-usage-v1"] = "owner-attributed-prior-usage-v1"
    fact_id: Literal["GW10-PRIOR-USAGE-001"] = "GW10-PRIOR-USAGE-001"
    provenance: Literal["OWNER_ATTRIBUTED_AGGREGATE_PRIOR_USAGE"] = (
        "OWNER_ATTRIBUTED_AGGREGATE_PRIOR_USAGE"
    )
    historical_http_proof: Literal["NOT_HTTP_PROVEN"] = "NOT_HTTP_PROVEN"
    attributed_credits: Literal[2] = 2
    owner_ref: Ref
    owner_reply_sha256: Sha
    owner_attribution_recorded_at: datetime
    ledger_id: Sha
    account_ref: Ref
    period_started_at: datetime
    period_resets_at: datetime
    original_consumed_execution_key: Sha
    reservation_id: Sha
    reservation_record_sha256: Sha
    previous_zero_quota_record_sha256: Sha
    observed_quota_record_sha256: Sha
    observed_quota: QuotaProof

    @field_validator("attributed_credits", mode="before")
    @classmethod
    def exact_credit_count(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("prior attributed credits require an exact integer")
        return value

    @model_validator(mode="after")
    def finite_observation(self) -> PriorUsageFact:
        start = self.period_started_at
        if (
            start != start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            or self.period_resets_at != next_month(start)
            or not start
            <= self.observed_quota.request_started_at
            <= self.observed_quota.received_at
            <= self.owner_attribution_recorded_at
            < self.period_resets_at
            or self.observed_quota.used_credits != 2
        ):
            raise ValueError("prior usage must be the exact observed two-credit period")
        return self


class PriorUsageEvidence(Metadata):
    schema_version: Literal["signed-prior-usage-evidence-v1"] = "signed-prior-usage-evidence-v1"
    fact: PriorUsageFact
    signed_fact: SignedReleaseManifest
    normal_signed: SignedReleaseManifest
    campaign_signed: SignedReleaseManifest


def verify_evidence(
    evidence: PriorUsageEvidence, trust: RootTrust, policy: StandingPolicy, *, now: datetime
) -> None:
    """Pure signature/role validation; a caller object cannot install or append."""
    evidence = PriorUsageEvidence.model_validate(evidence)
    now = MetadataTime(checked_at=now).checked_at
    normal = verify_signed_manifest(evidence.normal_signed, trust.review_public_key)
    campaign = verify_signed_manifest(evidence.campaign_signed, trust.review_public_key)
    signed = verify_signed_manifest(evidence.signed_fact, trust.review_public_key)
    fact = evidence.fact
    normal_identity = (
        normal.wheel_sha256,
        normal.implementation_sha,
        normal.protected_numerical_sha256,
        normal.installation_inventory_sha256,
        normal.original_ledger_id,
    )
    if (
        trust.review_public_key_sha256 != REVIEW_KEY_SHA
        or normal.material_policy_sha256 != trust.material_policy_sha256
        or normal.material_policy_sha256 != material_policy_sha256(policy)
        or normal.owner_acceptance_sha256 != trust.owner_acceptance_sha256
        or normal.owner_acceptance_sha256 != policy.owner_acceptance_sha256
        or normal.original_ledger_id != trust.original_ledger_id
        or normal.original_ledger_id != policy.ledger_id
        or normal.protected_numerical_sha256 != policy.protected_numerical_sha256
        or fact.ledger_id != policy.ledger_id
        or fact.account_ref != policy.odds_account_ref
        or fact.owner_ref != policy.owner_ref
        or fact.period_started_at != policy.calendar_anchor_at
        or fact.period_resets_at != policy.calendar_anchor_resets_at
        or policy.calendar_anchor_used_credits != 0
        or policy.limits.reserved_credits_per_event != fact.attributed_credits
        or fact.observed_quota.qualification_sha256 != policy.quota_qualification.semantic_sha256
        or fact.observed_quota.remaining_credits + fact.observed_quota.used_credits
        != policy.plan_credit_allowance
    ):
        raise OperationError("PRIOR_USAGE_ORIGINAL_ACCOUNT_BINDING_INVALID")
    for manifest in (campaign, signed):
        if (
            (
                manifest.wheel_sha256,
                manifest.implementation_sha,
                manifest.protected_numerical_sha256,
                manifest.installation_inventory_sha256,
                manifest.original_ledger_id,
            )
            != normal_identity
            or manifest.material_policy_sha256 != CAMPAIGN_POLICY_SHA
            or manifest.owner_acceptance_sha256 != OWNER_SHA
            or manifest.release_class != "WITHIN_POLICY_COMPATIBILITY"
            or manifest.reviewed_at > now
        ):
            raise OperationError("PRIOR_USAGE_SIGNED_IDENTITY_INVALID")
    if (
        campaign.reviewer_ref != CAMPAIGN_REVIEWER_ROLE
        or len(campaign.test_evidence_sha256) != 4
        or campaign.test_evidence_sha256[:2] != (CAMPAIGN_PROPOSAL_SHA, OWNER_SHA)
        or campaign.test_evidence_sha256[-1] != evidence.normal_signed.semantic_sha256
        or signed.reviewer_ref != ROLE
        or signed.test_evidence_sha256
        != (
            fact.semantic_sha256,
            fact.owner_reply_sha256,
            fact.observed_quota_record_sha256,
            evidence.normal_signed.semantic_sha256,
        )
        or not trust.accepted_at <= normal.reviewed_at <= campaign.reviewed_at <= signed.reviewed_at
        or not fact.owner_attribution_recorded_at <= signed.reviewed_at <= now
    ):
        raise OperationError("PRIOR_USAGE_DISTINCT_SIGNED_ROLE_REQUIRED")


def _installed_trust() -> RootTrust:
    body = _body(operator_root() / "root-trust.json", 16384)
    if hashlib.sha256(body).hexdigest() != ORIGINAL_TRUST_SHA:
        raise OperationError("PRIOR_USAGE_ORIGINAL_TRUST_CHANGED")
    return RootTrust.model_validate_json(body)


@dataclass(frozen=True, slots=True)
class VerifiedPriorUsageImport:
    evidence: PriorUsageEvidence
    trust: RootTrust
    policy: StandingPolicy


def load_prior_usage_import() -> VerifiedPriorUsageImport:
    """Fixed signed files only; no caller JSON, path, acknowledgement or clock."""
    authority = load_verified_campaign()
    base = operator_root().parent / "GW10-diagnostics/prior-usage-001"
    body = _body(base / "evidence.json", 262144)
    evidence = PriorUsageEvidence.model_validate_json(body)
    reply = _body(base / "owner-response.txt", 32768)
    review = _body(base / "technical-review.json", 262144)
    checked = json.loads(review)
    if (
        len(reply) > 32768
        or len(review) > 262144
        or hashlib.sha256(reply).hexdigest() != evidence.fact.owner_reply_sha256
        or hashlib.sha256(review).hexdigest()
        != evidence.signed_fact.manifest.independent_review_sha256
        or checked.get("state") != "OWNER_ATTRIBUTED_PRIOR_USAGE_REVIEW_CLEAR"
        or checked.get("unresolved_p0_p1") != 0
        or checked.get("unresolved_material_p2") != 0
        or evidence.normal_signed != authority.normal_signed
        or evidence.campaign_signed != authority.signed_campaign
        or evidence.fact.original_consumed_execution_key
        != authority.proposal.original_consumed_execution_key
    ):
        raise OperationError("PRIOR_USAGE_ACTUAL_OWNER_AND_REVIEW_REQUIRED")
    trust = _installed_trust()
    verify_evidence(evidence, trust, authority.normal_policy, now=datetime.now(UTC))
    return VerifiedPriorUsageImport(evidence, trust, authority.normal_policy)


def validate_canonical_fact(
    fact: PriorUsageFact,
    policy: StandingPolicy,
    rows: list[dict[str, Any]],
    original: list[dict[str, Any]],
    *,
    recorded_at: datetime,
) -> None:
    """Tie signed attribution to existing immutable facts, never create a call."""

    def matching(digest: str) -> dict[str, Any]:
        found = [r for r in rows if r["sha256"] == digest]
        if len(found) != 1:
            raise OperationError("PRIOR_USAGE_EXACT_CANONICAL_FACT_REQUIRED")
        return found[0]

    reservations = [
        r
        for r in original
        if r["kind"] == "RESERVATION" and r["sha256"] == fact.reservation_record_sha256
    ]
    before = [
        r
        for r in original
        if r["kind"] == "RESERVATION"
        and datetime.fromisoformat(r["at"]) <= fact.observed_quota.request_started_at
    ]
    enrollments = [
        r
        for r in rows
        if r["kind"] == "ENROLL" and r["execution_key"] == fact.original_consumed_execution_key
    ]
    if (
        len(reservations) != 1
        or len(before) != 1
        or reservations[0] != before[0]
        or reservations[0]["reservation_id"] != fact.reservation_id
        or reservations[0]["ledger_id"] != fact.ledger_id
        or reservations[0]["account_sha256"] != canonical_sha256(policy.odds_account_ref)
        or reservations[0]["authorization_sha256"]
        != canonical_sha256("OPR001-" + fact.original_consumed_execution_key)
        or datetime.fromisoformat(reservations[0]["period"]) != fact.period_started_at
        or not fact.period_started_at
        <= datetime.fromisoformat(reservations[0]["at"])
        <= fact.observed_quota.request_started_at
        or len(enrollments) != 1
        or enrollments[0]["payload"]["value"]["event"]["target_gameweek"] != 10
        or reservations[0]["approval_sha256"]
        != enrollments[0]["payload"]["value"]["approval_sha256"]
    ):
        raise OperationError("PRIOR_USAGE_EXACT_OLD_RESERVATION_AND_EVENT_REQUIRED")
    zero = matching(fact.previous_zero_quota_record_sha256)
    observed = matching(fact.observed_quota_record_sha256)
    zero_value, value = zero["payload"]["value"], observed["payload"]["value"]
    if zero["kind"] != "QUOTA" or observed["kind"] != "QUOTA":
        raise OperationError("PRIOR_USAGE_ACTUAL_QUOTA_ROWS_REQUIRED")
    old = QuotaProof.model_validate_json(json.dumps(zero_value["proof"]))
    current = QuotaProof.model_validate_json(json.dumps(value["proof"]))
    if (
        old.used_credits != 0
        or old.remaining_credits != policy.plan_credit_allowance
        or old.qualification_sha256 != current.qualification_sha256
        or old.model_dump(mode="json") != enrollments[0]["payload"]["value"]["quota"]
        or not fact.period_started_at
        <= old.request_started_at
        <= old.received_at
        <= current.request_started_at
        or current != fact.observed_quota
        or value.get("subtype") != "QUOTA"
        or value.get("phase") != "INITIAL"
        or value.get("campaign_policy_sha256") != CAMPAIGN_POLICY_SHA
        or current.remaining_credits + current.used_credits != policy.plan_credit_allowance
    ):
        raise OperationError("PRIOR_USAGE_EXACT_TWO_CREDIT_OBSERVATION_REQUIRED")
    related_rows = [r for r in rows if r["execution_key"] == observed["execution_key"]]
    related = [r["payload"]["value"] for r in related_rows]
    admissions = [
        v
        for v in related
        if v.get("subtype") == "PROVIDER_ADMISSION"
        and v.get("provider") == "QUOTA"
        and v.get("phase") == "INITIAL"
    ]
    if len(admissions) != 1 or admissions[0].get("route_sha256") != canonical_sha256(
        ["QUOTA", "GET", QUOTA_HOST, QUOTA_PATH]
    ):
        raise OperationError("PRIOR_USAGE_ACTUAL_FREE_RESPONSE_REQUIRED")
    identity = admissions[0]["request_id"]
    starts = [
        v
        for v in related
        if v.get("subtype") == "TRANSPORT_STARTED" and v.get("request_id") == identity
    ]
    completions = [
        v
        for v in related
        if v.get("subtype") == "RESPONSE_COMPLETED"
        and v.get("request_id") == identity
        and v.get("http_status") == 200
    ]
    if len(starts) != 1 or len(completions) != 1:
        raise OperationError("PRIOR_USAGE_ACTUAL_FREE_RESPONSE_REQUIRED")

    def event_rows(subtype: str) -> list[dict[str, Any]]:
        return [r for r in related_rows if r["payload"]["value"].get("subtype") == subtype]

    session, terminal, closed = (
        event_rows("SESSION"),
        event_rows("TERMINAL"),
        event_rows("QUIESCENT_CLOSE"),
    )
    if (
        len(session) != 1
        or len(terminal) != 1
        or len(closed) != 1
        or session[0]["payload"]["value"].get("session_index") != 1
        or session[0]["payload"]["value"].get("mode") != "PAID_ELIGIBLE"
        or terminal[0]["kind"] != "FAILURE"
        or terminal[0]["payload"]["value"].get("outcome") != "FAILED"
        or terminal[0]["payload"]["value"].get("error_code")
        != "EXCLUSIVE_ACCOUNT_USAGE_CONTRADICTION"
        or closed[0]["kind"] != "CLOSE"
        or closed[0]["payload"]["value"].get("worker_and_transports_quiescent") is not True
    ):
        raise OperationError("PRIOR_USAGE_EXACT_CLOSED_FAILED_SESSION_REQUIRED")
    inspected = [
        r
        for r in event_rows("INSPECTION")
        if r["kind"] == "CLOSE"
        and r["payload"]["value"].get("terminal_sha256") == terminal[0]["sha256"]
    ]
    admitted = event_rows("PROVIDER_ADMISSION")[0]
    started = event_rows("TRANSPORT_STARTED")[0]
    completed = event_rows("RESPONSE_COMPLETED")[0]
    if (
        not inspected
        or not session[0]["at"] <= admitted["at"] <= current.request_started_at
        or not admitted["at"]
        <= started["at"]
        <= completed["at"]
        <= current.received_at
        <= observed["at"]
        <= terminal[0]["at"]
        <= closed[0]["at"]
        <= min(r["at"] for r in inspected)
        <= recorded_at
    ):
        raise OperationError("PRIOR_USAGE_EXACT_INSPECTED_QUOTA_CHRONOLOGY_REQUIRED")
    from dmf_pulse.operation.journal import PAID_ROUTE_SHA

    if any(
        r["kind"] == "ATTEMPT"
        and r["route_sha256"] == PAID_ROUTE_SHA
        and datetime.fromisoformat(r["at"]) <= current.received_at
        for r in original
    ):
        raise OperationError("PRIOR_USAGE_CANNOT_RECONCILE_A_PAID_INVOCATION")
    from dmf_pulse.operation.campaign_journal import is_diagnostic_settlement

    if any(
        (r["kind"] == "SETTLEMENT" or is_diagnostic_settlement(r))
        and (
            r["payload"]["value"].get("reservation_id") == fact.reservation_id
            or r["at"] <= current.received_at
        )
        for r in rows
    ):
        raise OperationError("PRIOR_USAGE_OVERLAPS_ACTUAL_SETTLEMENT")


def attributed_usage_credits(
    rows: list[dict[str, Any]],
    original: list[dict[str, Any]],
    policy: StandingPolicy,
    start: datetime,
) -> int:
    facts = [r for r in rows if r["payload"]["value"].get("subtype") == KIND]
    if not facts:
        return 0
    if len(facts) != 1 or facts[0]["kind"] != "QUOTA":
        raise OperationError("PRIOR_USAGE_DUPLICATE_OR_INVALID_ATTRIBUTION")
    row = facts[0]
    evidence = PriorUsageEvidence.model_validate_json(
        json.dumps(row["payload"]["value"]["evidence"])
    )
    verify_evidence(evidence, _installed_trust(), policy, now=row["at"])
    if evidence.fact.period_started_at != start:
        return 0
    validate_canonical_fact(evidence.fact, policy, rows, original, recorded_at=row["at"])
    return evidence.fact.attributed_credits
