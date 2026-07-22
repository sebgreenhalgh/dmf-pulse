"""Stable typed ruleset differences."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dmf_pulse.rules.compiler import ensure_compiled_ruleset_integrity, resolve_ruleset
from dmf_pulse.rules.models import CompiledRuleset, RuleChange, RulesetDiff


def _changes(left: object, right: object, path: str = "rules") -> list[RuleChange]:
    if isinstance(left, dict) and isinstance(right, dict):
        changes: list[RuleChange] = []
        for key in sorted(left.keys() | right.keys()):
            child = f"{path}.{key}"
            if key not in left:
                changes.append(RuleChange(path=child, kind="ADDED", right=right[key]))
            elif key not in right:
                changes.append(RuleChange(path=child, kind="REMOVED", left=left[key]))
            else:
                changes.extend(_changes(left[key], right[key], child))
        return changes
    if isinstance(left, list) and isinstance(right, list):
        if left == right:
            return []
        return [RuleChange(path=path, kind="CHANGED", left=left, right=right)]
    if left != right:
        return [RuleChange(path=path, kind="CHANGED", left=left, right=right)]
    return []


def diff_rulesets(left: CompiledRuleset | Path, right: CompiledRuleset | Path) -> RulesetDiff:
    left_ruleset = resolve_ruleset(left) if isinstance(left, Path) else left
    right_ruleset = resolve_ruleset(right) if isinstance(right, Path) else right
    ensure_compiled_ruleset_integrity(left_ruleset)
    ensure_compiled_ruleset_integrity(right_ruleset)
    left_value: dict[str, Any] = {
        "production_eligible": left_ruleset.production_eligible,
        "rules": left_ruleset.rules,
        "status": left_ruleset.status.value,
        "unknown_blockers": list(left_ruleset.unknown_blockers),
    }
    right_value: dict[str, Any] = {
        "production_eligible": right_ruleset.production_eligible,
        "rules": right_ruleset.rules,
        "status": right_ruleset.status.value,
        "unknown_blockers": list(right_ruleset.unknown_blockers),
    }
    return RulesetDiff(
        left_id=left_ruleset.ruleset_id,
        left_hash=left_ruleset.ruleset_hash,
        right_id=right_ruleset.ruleset_id,
        right_hash=right_ruleset.ruleset_hash,
        changes=tuple(_changes(left_value, right_value, "$")),
    )
