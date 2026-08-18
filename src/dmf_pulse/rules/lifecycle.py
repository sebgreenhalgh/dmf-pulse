"""Fail-closed immutable ruleset activation."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dmf_pulse.rules.canonical import canonical_rules_sha256, pretty_rules_json, self_hash
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import ensure_compiled_ruleset_integrity
from dmf_pulse.rules.errors import RulesActivationError, RulesIntegrityError
from dmf_pulse.rules.models import (
    ActivationEvidence,
    ActivationReceipt,
    ApprovalRecord,
    ApprovalTrustStore,
    CapabilityArtifact,
    CompiledRuleset,
    RuleCapability,
    RulesetStatus,
)


def approval_record_hash(value: ApprovalRecord) -> str:
    payload = value.model_dump(mode="json")
    payload.pop("record_hash", None)
    return canonical_rules_sha256(payload)


def activation_evidence_hash(value: ActivationEvidence) -> str:
    payload = value.model_dump(mode="json")
    payload.pop("evidence_hash", None)
    return canonical_rules_sha256(payload)


def approval_trust_store_hash(value: ApprovalTrustStore) -> str:
    payload = value.model_dump(mode="json")
    payload.pop("store_hash", None)
    return canonical_rules_sha256(payload)


def _utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if not value.endswith("Z") or parsed.utcoffset() != UTC.utcoffset(parsed):
        return None
    return parsed


def activate_ruleset(
    compiled: CompiledRuleset,
    approval: ApprovalRecord,
    registry: Path,
    *,
    capability: CapabilityArtifact | None = None,
    evidence: ActivationEvidence | None = None,
    approval_trust: ApprovalTrustStore | None = None,
) -> ActivationReceipt:
    ensure_compiled_ruleset_integrity(compiled)
    blockers: list[str] = list(compiled.unknown_blockers)
    if compiled.status is not RulesetStatus.VERIFIED:
        blockers.append(f"status:{compiled.status.value}")
    if not compiled.production_eligible:
        blockers.append("production_eligible:false")
    if not approval.approved:
        blockers.append("approval:false")
    if (
        approval.ruleset_id != compiled.ruleset_id
        or approval.ruleset_version != compiled.ruleset_version
    ):
        blockers.append("approval:identity_mismatch")
    if approval.ruleset_hash != compiled.ruleset_hash:
        blockers.append("approval:hash_mismatch")
    if approval.approved_at is None or approval.approved_by is None:
        blockers.append("approval:provenance_missing")
    else:
        approved_at = _utc(approval.approved_at)
        if approved_at is None or not approval.approved_by.strip():
            blockers.append("approval:provenance_invalid")
    if compiled.schema_version == "1.1":
        expected_capability = compile_capability_artifact(compiled, RuleCapability.FULL_SEASON)
        if capability is None:
            blockers.append("capability:missing")
        elif capability.model_dump(mode="json") != expected_capability.model_dump(mode="json"):
            blockers.append("capability:mismatch")
        if (
            expected_capability.blockers
            or not expected_capability.source_backed
            or not expected_capability.production_eligible
        ):
            blockers.append("capability:not_production_eligible")

        if evidence is None:
            blockers.append("evidence:missing")
        else:
            if activation_evidence_hash(evidence) != evidence.evidence_hash:
                blockers.append("evidence:hash_mismatch")
            if (
                evidence.ruleset_id != compiled.ruleset_id
                or evidence.ruleset_version != compiled.ruleset_version
                or evidence.ruleset_hash != compiled.ruleset_hash
            ):
                blockers.append("evidence:identity_mismatch")
            if (
                evidence.capability is not RuleCapability.FULL_SEASON
                or evidence.capability_hash != expected_capability.capability_hash
            ):
                blockers.append("evidence:capability_mismatch")
            if (
                evidence.source_manifest_sha256
                != compiled.source_files["source_manifest.yaml"].raw_sha256
            ):
                blockers.append("evidence:source_manifest_mismatch")
            checked_at = _utc(evidence.source_checked_at)
            fresh_until = _utc(evidence.source_fresh_until)
            if checked_at is None or fresh_until is None or checked_at > fresh_until:
                blockers.append("evidence:source_freshness_invalid")
            elif approval.approved_at is not None:
                approved_at = _utc(approval.approved_at)
                if approved_at is not None and not checked_at <= approved_at <= fresh_until:
                    blockers.append("evidence:source_stale_at_approval")
            if evidence.official_conflicts:
                blockers.append("evidence:official_conflict")
            if evidence.unresolved_required_rules:
                blockers.append("evidence:unresolved_rule")
            for name, check in (
                ("golden", evidence.golden_tests),
                ("differential", evidence.differential_tests),
                ("reconciliation", evidence.representative_official_match),
            ):
                if check.status != "PASS" or check.artifact_sha256 is None:
                    blockers.append(f"evidence:{name}_incomplete")
            if not evidence.no_newer_governing_conflict:
                blockers.append("evidence:newer_governing_conflict")

        advanced_approval_fields = (
            approval.status,
            approval.approval_id,
            approval.approval_kind,
            approval.capability_hash,
            approval.activation_evidence_hash,
            approval.approval_statement,
            approval.record_hash,
        )
        if any(value is None for value in advanced_approval_fields):
            blockers.append("approval:binding_missing")
        else:
            assert approval.record_hash is not None
            if approval_record_hash(approval) != approval.record_hash:
                blockers.append("approval:record_hash_mismatch")
            if approval.capability_hash != expected_capability.capability_hash:
                blockers.append("approval:capability_mismatch")
            if evidence is None or approval.activation_evidence_hash != evidence.evidence_hash:
                blockers.append("approval:evidence_mismatch")
            if approval.approval_statement is None or not approval.approval_statement.strip():
                blockers.append("approval:statement_invalid")
            if approval.status != "APPROVED":
                blockers.append("approval:status_invalid")
        if approval_trust is None:
            blockers.append("approval:trust_store_missing")
        else:
            if approval_trust_store_hash(approval_trust) != approval_trust.store_hash:
                blockers.append("approval:trust_store_hash_mismatch")
            if approval.record_hash not in approval_trust.trusted_approval_hashes:
                blockers.append("approval:not_trusted")
    if blockers:
        raise RulesActivationError(
            "RULESET_ACTIVATION_BLOCKED",
            "ruleset activation is blocked by governance requirements",
            blockers=tuple(sorted(set(blockers))),
        )
    assert approval.approved_at is not None
    active_value: dict[str, Any] = compiled.model_dump(mode="json")
    active_value["status"] = RulesetStatus.ACTIVE.value
    active_value["ruleset_hash"] = self_hash(active_value)
    active = CompiledRuleset.model_validate(active_value)
    destination = registry / active.ruleset_id / active.ruleset_version
    approval_bytes = pretty_rules_json(approval.model_dump(mode="json")).encode("utf-8")
    approval_sha256 = hashlib.sha256(approval_bytes).hexdigest()
    receipt = ActivationReceipt(
        ruleset_id=active.ruleset_id,
        ruleset_version=active.ruleset_version,
        ruleset_hash=active.ruleset_hash,
        verified_ruleset_hash=compiled.ruleset_hash,
        approval_sha256=approval_sha256,
        activated_at=approval.approved_at,
        artifact=destination.as_posix(),
    )
    children = {
        "verified_ruleset.json": pretty_rules_json(compiled.model_dump(mode="json")).encode(
            "utf-8"
        ),
        "active_ruleset.json": pretty_rules_json(active.model_dump(mode="json")).encode("utf-8"),
        "approval.json": approval_bytes,
        "activation_receipt.json": pretty_rules_json(receipt.model_dump(mode="json")).encode(
            "utf-8"
        ),
    }
    if compiled.schema_version == "1.1":
        assert capability is not None
        assert evidence is not None
        assert approval_trust is not None
        children.update(
            {
                "full_season_capability.json": pretty_rules_json(
                    capability.model_dump(mode="json")
                ).encode("utf-8"),
                "activation_evidence.json": pretty_rules_json(
                    evidence.model_dump(mode="json")
                ).encode("utf-8"),
                "approval_trust_store.json": pretty_rules_json(
                    approval_trust.model_dump(mode="json")
                ).encode("utf-8"),
            }
        )
    manifest: dict[str, Any] = {
        "active_ruleset_hash": active.ruleset_hash,
        "children": {
            filename: {
                "ruleset_hash": (
                    compiled.ruleset_hash
                    if filename == "verified_ruleset.json"
                    else active.ruleset_hash
                    if filename in {"active_ruleset.json", "activation_receipt.json"}
                    else compiled.ruleset_hash
                ),
                "ruleset_id": active.ruleset_id,
                "ruleset_version": active.ruleset_version,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for filename, content in sorted(children.items())
        },
        "ruleset_id": active.ruleset_id,
        "ruleset_version": active.ruleset_version,
        "schema_version": "1.0",
        "verified_ruleset_hash": compiled.ruleset_hash,
    }
    children["activation_manifest.json"] = pretty_rules_json(manifest).encode("utf-8")

    def existing_is_identical() -> bool:
        if not destination.is_dir():
            return False
        actual_names = {entry.name for entry in destination.iterdir() if entry.is_file()}
        if actual_names != set(children):
            return False
        try:
            return all(
                (destination / name).read_bytes() == content for name, content in children.items()
            )
        except OSError:
            return False

    if destination.exists():
        if existing_is_identical():
            return receipt
        raise RulesIntegrityError(
            "RULESET_ACTIVE_COLLISION", "activation directory contains different content"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".activate-", dir=destination.parent))
    try:
        for filename, content in children.items():
            with (temporary / filename).open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        try:
            os.rename(temporary, destination)
        except OSError as exc:
            if destination.exists():
                if existing_is_identical():
                    return receipt
                raise RulesIntegrityError(
                    "RULESET_ACTIVE_COLLISION",
                    "activation directory was concurrently created with different content",
                ) from exc
            raise RulesIntegrityError(
                "RULESET_ACTIVE_UNAVAILABLE", "active artifact could not be published"
            ) from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return receipt
