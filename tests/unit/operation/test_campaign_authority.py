"""Owned deterministic RSA: a valid signature alone never grants a new role."""

from datetime import timedelta

import pytest

from dmf_pulse.operation import campaign_authority as subject
from dmf_pulse.operation.campaign_authority import CampaignOwnerAcceptance
from dmf_pulse.operation.maintenance import RootTrust, material_policy_sha256
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.release_signatures import ReleaseManifest
from tests.unit.operation.standing_support import NOW, owned_policy
from tests.unit.operation.test_campaign import proposal
from tests.unit.operation.test_maintenance import KEY, seal


@pytest.fixture
def bound(tmp_path, monkeypatch):
    policy = owned_policy(tmp_path)
    material = material_policy_sha256(policy)
    campaign = proposal().model_copy(
        update={
            "created_at": NOW - timedelta(minutes=30),
            "original_ledger_id": policy.ledger_id,
            "owner_ref": policy.owner_ref,
            "protected_numerical_sha256": policy.protected_numerical_sha256,
        }
    )
    pins = {
        "CAMPAIGN_PROPOSAL_SHA": "1" * 64,
        "CAMPAIGN_POLICY_SHA": campaign.semantic_sha256,
        "ORIGINAL_OWNER_SHA": policy.owner_acceptance_sha256,
        "ORIGINAL_MATERIAL_SHA": material,
        "REVIEW_KEY_SHA": KEY.fingerprint_sha256,
    }
    for name, value in pins.items():
        monkeypatch.setattr(subject, name, value)
    acceptance = CampaignOwnerAcceptance(
        owner_ref=policy.owner_ref,
        proposal_byte_sha256=pins["CAMPAIGN_PROPOSAL_SHA"],
        policy_sha256=campaign.semantic_sha256,
        actual_reply_byte_sha256="2" * 64,
        accepted_at=NOW - timedelta(minutes=10),
        exact_scope_accepted=True,
        repeated_owner_attested_permission_coverage_accepted=True,
        standing_consumption_preserved=True,
    )
    trust = RootTrust(
        review_public_key=KEY,
        review_public_key_sha256=KEY.fingerprint_sha256,
        owner_acceptance_sha256=policy.owner_acceptance_sha256,
        material_policy_sha256=material,
        original_ledger_id=policy.ledger_id,
        accepted_at=policy.accepted_at,
    )
    normal = seal(
        ReleaseManifest(
            wheel_sha256="4" * 64,
            implementation_sha=policy.implementation_sha,
            protected_numerical_sha256=policy.protected_numerical_sha256,
            material_policy_sha256=material,
            owner_acceptance_sha256=policy.owner_acceptance_sha256,
            original_ledger_id=policy.ledger_id,
            independent_review_sha256=policy.independent_review_sha256,
            installation_inventory_sha256="5" * 64,
            reviewer_ref="OWNED_NORMAL_REVIEW",
            reviewed_at=NOW - timedelta(minutes=20),
            release_class="WITHIN_POLICY_COMPATIBILITY",
            test_evidence_sha256=("6" * 64,),
        )
    )
    signed = seal(
        normal.manifest.model_copy(
            update={
                "material_policy_sha256": campaign.semantic_sha256,
                "owner_acceptance_sha256": acceptance.semantic_sha256,
                "independent_review_sha256": "3" * 64,
                "reviewer_ref": subject.CAMPAIGN_REVIEWER_ROLE,
                "reviewed_at": NOW,
                "test_evidence_sha256": (
                    pins["CAMPAIGN_PROPOSAL_SHA"],
                    acceptance.semantic_sha256,
                    "3" * 64,
                    normal.semantic_sha256,
                ),
            }
        )
    )
    return dict(
        proposal=campaign,
        acceptance=acceptance,
        signed_campaign=signed,
        normal_policy=policy,
        normal_signed=normal,
        trust=trust,
        technical_review_sha256="3" * 64,
        actual_reply_sha256="2" * 64,
        now=NOW,
    )


def test_dual_role_binding_accepts_only_matching_owner_key_code_inventory_and_ledger(bound):
    result = subject.verify_campaign_role_bindings(**bound)
    assert result.proposal == bound["proposal"]
    assert result.normal_policy == bound["normal_policy"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("material_policy_sha256", "7" * 64),
        ("owner_acceptance_sha256", "7" * 64),
        ("original_ledger_id", "7" * 64),
        ("implementation_sha", "7" * 40),
        ("installation_inventory_sha256", "7" * 64),
        ("protected_numerical_sha256", "7" * 64),
        ("independent_review_sha256", "7" * 64),
        ("wheel_sha256", "7" * 64),
        ("reviewer_ref", "ORDINARY_STANDING_ENROLLMENT"),
        ("test_evidence_sha256", ("7" * 64,)),
        ("reviewed_at", NOW + timedelta(seconds=1)),
    ],
)
def test_valid_signature_with_wrong_role_binding_is_rejected(bound, field, value):
    bound["signed_campaign"] = seal(
        bound["signed_campaign"].manifest.model_copy(update={field: value})
    )
    with pytest.raises(OperationError):
        subject.verify_campaign_role_bindings(**bound)


def test_ordinary_signature_cannot_substitute_for_campaign_signature(bound):
    bound["signed_campaign"] = bound["normal_signed"]
    with pytest.raises(OperationError, match="SIGNED_ROLE_BINDING_CHANGED"):
        subject.verify_campaign_role_bindings(**bound)


def test_campaign_signature_cannot_substitute_for_normal_signature(bound):
    bound["normal_signed"] = bound["signed_campaign"]
    with pytest.raises(OperationError, match="NORMAL_AUTHORITY_BINDING_CHANGED"):
        subject.verify_campaign_role_bindings(**bound)


def test_signature_tamper_is_rejected(bound):
    bound["signed_campaign"] = bound["signed_campaign"].model_copy(
        update={"signature_b64": "A" * 512}
    )
    with pytest.raises(OperationError, match="SIGNATURE_INVALID"):
        subject.verify_campaign_role_bindings(**bound)


@pytest.mark.parametrize(
    "field,value",
    [
        ("proposal_byte_sha256", "8" * 64),
        ("policy_sha256", "8" * 64),
        ("actual_reply_byte_sha256", "8" * 64),
        ("owner_ref", "different-owned-operator"),
        ("accepted_at", NOW + timedelta(seconds=1)),
    ],
)
def test_acceptance_cannot_be_relabelled(bound, field, value):
    bound["acceptance"] = bound["acceptance"].model_copy(update={field: value})
    with pytest.raises(OperationError, match="ACTUAL_OWNER_ACCEPTANCE_REQUIRED"):
        subject.verify_campaign_role_bindings(**bound)


def test_expired_signature_authenticates_history_but_does_not_create_live_context(bound):
    bound["now"] = bound["proposal"].deadline_not_after + timedelta(seconds=1)
    assert subject.verify_campaign_role_bindings(**bound).proposal == bound["proposal"]
    from dmf_pulse.operation.campaign_runtime import campaign_runtime_enrollment

    assert campaign_runtime_enrollment() is None
