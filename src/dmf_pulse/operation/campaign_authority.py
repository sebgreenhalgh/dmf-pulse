"""Separate accepted diagnostic authority; ordinary standing trust is unchanged."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError, field_validator

from dmf_pulse.operation.campaign import DiagnosticCampaignProposal
from dmf_pulse.operation.maintenance import (
    RootTrust,
    _read,
    _safe_path,
    material_policy_sha256,
    operator_root,
)
from dmf_pulse.operation.models import Metadata, MetadataTime, OperationError, Ref, Sha
from dmf_pulse.operation.release_signatures import SignedReleaseManifest, verify_signed_manifest
from dmf_pulse.operation.standing import StandingPolicy, require_policy

CAMPAIGN_PROPOSAL_SHA = "210720717eb84414417cb971ee5b379c3cecbc35cf2afbf3e82f913caa4a158c"
CAMPAIGN_POLICY_SHA = "08bfa7a58835ef62ef4de5c57980098f92a41a4a8f29148ad7f8889253c0e9a0"
ORIGINAL_TRUST_SHA = "5d652e16cdcfe07b0c2b51c5d9f3a9b4d28b7bbb4a11d23a7cee406ee91588e6"
ORIGINAL_MATERIAL_SHA = "8b1600bef7791138a306b9869c2e7bbec4784a40f9b557daf47d1d4860d95c13"
ORIGINAL_OWNER_SHA = "a9bcc5dfbbfd1c2b1f8ce2a1ef940c0f493a2386199ca2aa9cb88d7459b371fb"
REVIEW_KEY_SHA = "ba6f4a089b9f8d2535f9c78f964e0306d8432f3648e0d8d5e9dc22acb05792d2"
CAMPAIGN_REVIEWER_ROLE = "OPR003_DIAGNOSTIC_AUTHORITY_NOT_STANDING_ENROLLMENT"


class CampaignOwnerAcceptance(Metadata):
    """Retained actual owner decision; a caller object alone grants nothing."""

    schema_version: Literal["gw10-diagnostic-owner-acceptance-v1"] = (
        "gw10-diagnostic-owner-acceptance-v1"
    )
    origin: Literal["ACTUAL_OWNER_CHAT_REPLY"] = "ACTUAL_OWNER_CHAT_REPLY"
    decision_ref: Literal["GW10-DIAGNOSTIC-CAMPAIGN-001"] = "GW10-DIAGNOSTIC-CAMPAIGN-001"
    owner_ref: Ref
    proposal_byte_sha256: Sha
    policy_sha256: Sha
    actual_reply_byte_sha256: Sha
    accepted_at: datetime
    exact_scope_accepted: Literal[True]
    repeated_owner_attested_permission_coverage_accepted: Literal[True]
    standing_consumption_preserved: Literal[True]

    @field_validator(
        "exact_scope_accepted",
        "repeated_owner_attested_permission_coverage_accepted",
        "standing_consumption_preserved",
        mode="before",
    )
    @classmethod
    def explicit_decision(cls, value: object) -> object:
        if value is not True:
            raise ValueError("actual owner acceptance requires explicit boolean true")
        return value


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedCampaignAuthority:
    proposal: DiagnosticCampaignProposal
    acceptance: CampaignOwnerAcceptance
    signed_campaign: SignedReleaseManifest
    normal_policy: StandingPolicy
    normal_signed: SignedReleaseManifest


def verify_campaign_role_bindings(
    *,
    proposal: DiagnosticCampaignProposal,
    acceptance: CampaignOwnerAcceptance,
    signed_campaign: SignedReleaseManifest,
    normal_policy: StandingPolicy,
    normal_signed: SignedReleaseManifest,
    trust: RootTrust,
    technical_review_sha256: str,
    actual_reply_sha256: str,
    now: datetime,
) -> VerifiedCampaignAuthority:
    """Pure crypto/role check after the normal installed verifier succeeds.

    Production only supplies fixed installed files; this seam supports owned
    adversarial tests and cannot install, open credentials or send requests.
    """
    now = MetadataTime(checked_at=now).checked_at
    normal = verify_signed_manifest(normal_signed, trust.review_public_key)
    campaign = verify_signed_manifest(signed_campaign, trust.review_public_key)
    expected_evidence = (
        CAMPAIGN_PROPOSAL_SHA,
        acceptance.semantic_sha256,
        technical_review_sha256,
        normal_signed.semantic_sha256,
    )
    if (
        trust.review_public_key_sha256 != REVIEW_KEY_SHA
        or trust.owner_acceptance_sha256 != ORIGINAL_OWNER_SHA
        or trust.material_policy_sha256 != ORIGINAL_MATERIAL_SHA
        or normal.material_policy_sha256 != ORIGINAL_MATERIAL_SHA
        or normal.owner_acceptance_sha256 != ORIGINAL_OWNER_SHA
        or normal_policy.owner_acceptance_sha256 != ORIGINAL_OWNER_SHA
        or normal_policy.accepted_at != trust.accepted_at
        or material_policy_sha256(normal_policy) != ORIGINAL_MATERIAL_SHA
        or normal.implementation_sha != normal_policy.implementation_sha
        or normal.protected_numerical_sha256 != normal_policy.protected_numerical_sha256
        or normal.original_ledger_id != normal_policy.ledger_id
        or normal.original_ledger_id != proposal.original_ledger_id
        or normal.original_ledger_id != trust.original_ledger_id
        or normal.independent_review_sha256 != normal_policy.independent_review_sha256
        or normal.wheel_sha256 != signed_campaign.manifest.wheel_sha256
    ):
        raise OperationError("DIAGNOSTIC_NORMAL_AUTHORITY_BINDING_CHANGED")
    if (
        proposal.semantic_sha256 != CAMPAIGN_POLICY_SHA
        or acceptance.proposal_byte_sha256 != CAMPAIGN_PROPOSAL_SHA
        or acceptance.policy_sha256 != CAMPAIGN_POLICY_SHA
        or acceptance.owner_ref != normal_policy.owner_ref
        or acceptance.actual_reply_byte_sha256 != actual_reply_sha256
        or not proposal.created_at <= acceptance.accepted_at <= now
        or acceptance.accepted_at >= proposal.deadline_not_after
        or acceptance.semantic_sha256 == ORIGINAL_OWNER_SHA
    ):
        raise OperationError("DIAGNOSTIC_ACTUAL_OWNER_ACCEPTANCE_REQUIRED")
    if (
        campaign.material_policy_sha256 != CAMPAIGN_POLICY_SHA
        or campaign.owner_acceptance_sha256 != acceptance.semantic_sha256
        or campaign.original_ledger_id != proposal.original_ledger_id
        or campaign.original_ledger_id != normal_policy.ledger_id
        or campaign.implementation_sha != normal.implementation_sha
        or campaign.installation_inventory_sha256 != normal.installation_inventory_sha256
        or campaign.protected_numerical_sha256 != normal.protected_numerical_sha256
        or campaign.protected_numerical_sha256 != proposal.protected_numerical_sha256
        or campaign.independent_review_sha256 != technical_review_sha256
        or campaign.reviewer_ref != CAMPAIGN_REVIEWER_ROLE
        or campaign.release_class != "WITHIN_POLICY_COMPATIBILITY"
        or campaign.test_evidence_sha256 != expected_evidence
        or not acceptance.accepted_at <= campaign.reviewed_at <= now
    ):
        raise OperationError("DIAGNOSTIC_SIGNED_ROLE_BINDING_CHANGED")
    return VerifiedCampaignAuthority(
        proposal, acceptance, signed_campaign, normal_policy, normal_signed
    )


def _body(path: Path, maximum: int) -> bytes:
    path = _safe_path(path)
    if not path.is_file() or path.stat().st_size > maximum:
        raise OperationError("DIAGNOSTIC_FIXED_AUTHORITY_FILE_REQUIRED")
    data = path.read_bytes()
    if len(data) > maximum:
        raise OperationError("DIAGNOSTIC_FIXED_AUTHORITY_FILE_REQUIRED")
    return data


def load_verified_campaign(*, now: datetime | None = None) -> VerifiedCampaignAuthority:
    """No argument accepts an authority path, policy JSON or acceptance boolean."""
    policy = require_policy()  # Authenticate the normal installed runtime FIRST.
    root = operator_root()
    try:
        trust_body = _body(root / "root-trust.json", 16384)
        if hashlib.sha256(trust_body).hexdigest() != ORIGINAL_TRUST_SHA:
            raise OperationError("DIAGNOSTIC_ORIGINAL_TRUST_CHANGED")
        trust = RootTrust.model_validate_json(trust_body)
        normal = SignedReleaseManifest.model_validate_json(
            json.dumps(_read(root / "active-release.json"))
        )
        base = root.parent / "GW10-diagnostics/authority/GW10-DIAGNOSTIC-CAMPAIGN-001"
        proposal_body = _body(base / "proposal.json", 262144)
        if hashlib.sha256(proposal_body).hexdigest() != CAMPAIGN_PROPOSAL_SHA:
            raise OperationError("DIAGNOSTIC_ACCEPTED_PROPOSAL_CHANGED")
        value = json.loads(proposal_body)
        proposal = DiagnosticCampaignProposal.model_validate_json(
            json.dumps(value["campaign_policy"])
        )
        acceptance = CampaignOwnerAcceptance.model_validate_json(
            _body(base / "owner-acceptance.json", 32768)
        )
        signed = SignedReleaseManifest.model_validate_json(
            _body(base / "signed-authority.json", 16384)
        )
        review_body = _body(base / "execution-review.json", 262144)
        review = json.loads(review_body)
        if (
            review["state"] != "GW10_DIAGNOSTIC_EXECUTION_REVIEW_CLEAR"
            or review["unresolved_p0_p1"] != 0
            or review["unresolved_material_p2"] != 0
        ):
            raise OperationError("DIAGNOSTIC_EXECUTION_REVIEW_REQUIRED")
        reply = _body(base / "owner-response.txt", 32768)
        return verify_campaign_role_bindings(
            proposal=proposal,
            acceptance=acceptance,
            signed_campaign=signed,
            normal_policy=policy,
            normal_signed=normal,
            trust=trust,
            technical_review_sha256=hashlib.sha256(review_body).hexdigest(),
            actual_reply_sha256=hashlib.sha256(reply).hexdigest(),
            now=now or datetime.now(UTC),
        )
    except OperationError:
        raise
    except (OSError, ValueError, TypeError, KeyError, ValidationError):
        raise OperationError("DIAGNOSTIC_OWNER_AND_SIGNED_AUTHORITY_REQUIRED") from None
