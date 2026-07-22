"""Fail-closed immutable ruleset activation."""

from __future__ import annotations

import os
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
    active_value: dict[str, Any] = compiled.model_dump(mode="json")
    active_value["status"] = RulesetStatus.ACTIVE.value
    active_value["ruleset_hash"] = self_hash(active_value)
    active = CompiledRuleset.model_validate(active_value)
    destination = registry / active.ruleset_id / f"{active.ruleset_version}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".activate-", dir=destination.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(pretty_rules_json(active.model_dump(mode="json")).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise RulesIntegrityError(
                "RULESET_ACTIVE_COLLISION", "an active artifact already exists at this ID/version"
            ) from exc
        except OSError as exc:
            raise RulesIntegrityError(
                "RULESET_ACTIVE_UNAVAILABLE", "active artifact could not be published"
            ) from exc
        temporary.unlink()
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return ActivationReceipt(
        ruleset_id=active.ruleset_id,
        ruleset_version=active.ruleset_version,
        ruleset_hash=active.ruleset_hash,
        artifact=destination.as_posix(),
    )
