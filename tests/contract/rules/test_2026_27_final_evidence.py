"""Governance and evidence regressions for 2026/27 activation readiness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.errors import RulesActivationError, RulesIntegrityError
from dmf_pulse.rules.lifecycle import (
    activate_ruleset,
    activation_evidence_hash,
    approval_trust_store_hash,
)
from dmf_pulse.rules.models import (
    ActivationEvidence,
    ApprovalRecord,
    ApprovalTrustStore,
    CompiledRuleset,
    RuleCapability,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET = REPO_ROOT / "config/rules/fpl-2026-27"
EVIDENCE = REPO_ROOT / "evidence/tickets/RUL-2026-27"


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def compiled() -> CompiledRuleset:
    return compile_ruleset(TARGET)


@pytest.fixture(scope="module")
def capability(compiled):
    return compile_capability_artifact(compiled, RuleCapability.FULL_SEASON)


@pytest.fixture(scope="module")
def activation_evidence() -> ActivationEvidence:
    return ActivationEvidence.model_validate_json(
        (EVIDENCE / "ACTIVATION_EVIDENCE.json").read_bytes()
    )


@pytest.fixture(scope="module")
def pending_approval() -> ApprovalRecord:
    return ApprovalRecord.model_validate_json(
        (EVIDENCE / "PENDING_HUMAN_APPROVAL.json").read_bytes()
    )


@pytest.fixture(scope="module")
def trust_store() -> ApprovalTrustStore:
    return ApprovalTrustStore.model_validate_json(
        (TARGET / "approval_trust_store.json").read_bytes()
    )


def test_pending_approval_and_empty_trust_store_are_explicit(pending_approval, trust_store) -> None:
    assert pending_approval.status == "PENDING_HUMAN_APPROVAL"
    assert pending_approval.approved is False
    assert pending_approval.approved_by is None
    assert pending_approval.record_hash is None
    assert trust_store.trusted_approval_hashes == ()
    assert approval_trust_store_hash(trust_store) == trust_store.store_hash


def test_activation_evidence_is_hash_bound_but_reconciliation_unavailable(
    compiled, capability, activation_evidence
) -> None:
    assert activation_evidence_hash(activation_evidence) == activation_evidence.evidence_hash
    assert activation_evidence.ruleset_hash == compiled.ruleset_hash
    assert activation_evidence.capability_hash == capability.capability_hash
    assert activation_evidence.golden_tests.status == "PASS"
    assert activation_evidence.differential_tests.status == "PASS"
    assert activation_evidence.representative_official_match.status == ("TEMPORARILY_UNAVAILABLE")


def test_activation_without_human_approval_and_reconciliation_fails_closed(
    tmp_path: Path,
    compiled,
    capability,
    activation_evidence,
    pending_approval,
    trust_store,
) -> None:
    with pytest.raises(RulesActivationError) as caught:
        activate_ruleset(
            compiled,
            pending_approval,
            tmp_path / "active",
            capability=capability,
            evidence=activation_evidence,
            approval_trust=trust_store,
        )
    assert set(caught.value.blockers) >= {
        "approval:false",
        "approval:binding_missing",
        "approval:not_trusted",
        "evidence:reconciliation_incomplete",
    }
    assert not (tmp_path / "active").exists()


def test_forged_or_tampered_governance_artifacts_fail_closed(
    tmp_path: Path,
    compiled,
    capability,
    activation_evidence,
    trust_store,
) -> None:
    forged = ApprovalRecord(
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
        status="APPROVED",
        approved=True,
        approved_at="2026-08-18T00:00:00Z",
        approved_by="Sebastian Greenhalgh",
        approval_id="APR-FORGED-001",
        approval_kind="HUMAN_RULESET_ACTIVATION",
        capability_hash=capability.capability_hash,
        activation_evidence_hash=activation_evidence.evidence_hash,
        approval_statement="forged",
        record_hash="0" * 64,
    )
    with pytest.raises(RulesActivationError) as caught:
        activate_ruleset(
            compiled,
            forged,
            tmp_path / "active",
            capability=capability,
            evidence=activation_evidence,
            approval_trust=trust_store,
        )
    assert "approval:record_hash_mismatch" in caught.value.blockers
    assert "approval:not_trusted" in caught.value.blockers

    tampered = activation_evidence.model_copy(update={"no_newer_governing_conflict": False})
    with pytest.raises(RulesActivationError) as evidence_error:
        activate_ruleset(
            compiled,
            forged,
            tmp_path / "active",
            capability=capability,
            evidence=tampered,
            approval_trust=trust_store,
        )
    assert "evidence:hash_mismatch" in evidence_error.value.blockers
    assert "evidence:newer_governing_conflict" in evidence_error.value.blockers


def test_tampered_compiled_artifact_is_rejected_before_governance(
    tmp_path: Path, compiled, pending_approval
) -> None:
    tampered = compiled.model_copy(update={"ruleset_version": "9.9.9"})
    with pytest.raises(RulesIntegrityError, match="self-hash"):
        activate_ruleset(tampered, pending_approval, tmp_path / "active")


def test_source_manifest_verification_and_reconciliation_are_green() -> None:
    manifest = _load(EVIDENCE / "SOURCE_MANIFEST.json")
    reconciliation = _load(EVIDENCE / "OFFICIAL_SOURCE_RECONCILIATION.json")
    assert manifest["verification_status"] == "PASS"
    assert reconciliation["status"] == "PASS"
    assert reconciliation["blocking_findings"] == []
    assert all(manifest["coverage"].values())


def test_representative_match_is_not_waived() -> None:
    reconciliation = _load(EVIDENCE / "REPRESENTATIVE_OFFICIAL_GAME_RECONCILIATION.json")
    assert reconciliation["status"] == "TEMPORARILY_UNAVAILABLE"
    assert reconciliation["production_activation_blocker"] is True
    assert reconciliation["waived"] is False
    assert reconciliation["completed_target_season_matches"] == 0


def test_final_evidence_describes_reviewed_not_active_state() -> None:
    readiness = _load(EVIDENCE / "READINESS_STATUS.json")
    assert readiness["engineering_review_status"] == "COMPLETE"
    assert readiness["human_approval_status"] == "PENDING_HUMAN_APPROVAL"
    assert readiness["production_activation_status"] == "NOT_ACTIVE"
    assert readiness["full_season_capability"]["production_eligible"] is True
    assert readiness["full_season_capability"]["blockers"] == []
