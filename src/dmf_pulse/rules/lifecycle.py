"""Fail-closed immutable ruleset activation."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dmf_pulse.rules.canonical import pretty_rules_json, self_hash
from dmf_pulse.rules.compiler import ensure_compiled_ruleset_integrity
from dmf_pulse.rules.errors import RulesActivationError, RulesIntegrityError
from dmf_pulse.rules.models import (
    ActivationReceipt,
    ApprovalRecord,
    CompiledRuleset,
    RulesetStatus,
)


def activate_ruleset(
    compiled: CompiledRuleset, approval: ApprovalRecord, registry: Path
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
        try:
            approved_at = datetime.fromisoformat(approval.approved_at.replace("Z", "+00:00"))
        except ValueError:
            approved_at = None
        if (
            approved_at is None
            or approved_at.utcoffset() != UTC.utcoffset(approved_at)
            or not approval.approved_at.endswith("Z")
            or not approval.approved_by.strip()
        ):
            blockers.append("approval:provenance_invalid")
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
