"""Capability-scoped verification and deterministic review artifacts."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Final, cast

from pydantic import ValidationError

from dmf_pulse.rules.authoring import (
    CapabilitiesFile,
    InterpretationsFile,
    RuleVerificationFile,
    RuleVerificationRecord,
)
from dmf_pulse.rules.canonical import canonical_rules_sha256, pretty_rules_json
from dmf_pulse.rules.errors import RulesIntegrityError, RulesValidationError
from dmf_pulse.rules.models import (
    CapabilityArtifact,
    CompiledRuleset,
    InterpretationDecision,
    RuleCapability,
    VerificationStatus,
)

CAPABILITY_CONTRACT: Final[dict[RuleCapability, dict[str, tuple[str, ...]]]] = {
    RuleCapability.PLAYER_POINTS: {
        "inherits": (),
        "rule_paths": (
            "/rules/scoring",
            "/rules/assists",
            "/rules/bonus",
        ),
    },
    RuleCapability.GW1_INITIAL_SQUAD: {
        "inherits": (RuleCapability.PLAYER_POINTS.value,),
        "rule_paths": (
            "/rules/positions",
            "/rules/squad",
            "/rules/lineup/starting_size",
            "/rules/lineup/bench_size",
            "/rules/prices/price_unit",
            "/rules/prices/integer_only",
            "/rules/prices/initial_purchase_price_basis",
            "/rules/prices/current_purchase_price_basis",
            "/rules/deadlines/gameweeks/0",
        ),
    },
    RuleCapability.TRANSFER_STATE: {
        "inherits": (RuleCapability.GW1_INITIAL_SQUAD.value,),
        "rule_paths": ("/rules/transfers", "/rules/prices/selling_price"),
    },
    RuleCapability.CHIP_STATE: {
        "inherits": (RuleCapability.TRANSFER_STATE.value,),
        "rule_paths": ("/rules/chips", "/rules/lineup/automatic_substitutions"),
    },
    RuleCapability.FULL_SEASON: {
        "inherits": (
            RuleCapability.PLAYER_POINTS.value,
            RuleCapability.GW1_INITIAL_SQUAD.value,
            RuleCapability.TRANSFER_STATE.value,
            RuleCapability.CHIP_STATE.value,
        ),
        "rule_paths": (
            "/rules/positions",
            "/rules/scoring",
            "/rules/assists",
            "/rules/bonus",
            "/rules/squad",
            "/rules/lineup",
            "/rules/transfers",
            "/rules/prices",
            "/rules/chips",
            "/rules/deadlines",
            "/rules/special_events",
        ),
    },
}


def interpretation_decision_hash(decision: InterpretationDecision | dict[str, Any]) -> str:
    """Hash every immutable decision field except the hash field itself."""

    value = (
        decision.model_dump(mode="json")
        if isinstance(decision, InterpretationDecision)
        else dict(decision)
    )
    value.pop("decision_hash", None)
    return canonical_rules_sha256(value)


def _validate_interpretation_hashes(decisions: tuple[InterpretationDecision, ...]) -> None:
    for decision in decisions:
        if interpretation_decision_hash(decision) != decision.decision_hash:
            raise RulesValidationError(
                "RULESET_INTERPRETATION_HASH",
                f"interpretation decision hash does not match: {decision.decision_id}",
            )


def validate_capability_contract(capabilities: CapabilitiesFile) -> None:
    """Prevent an author from weakening a governed capability dependency set."""

    for capability in RuleCapability:
        actual = getattr(capabilities.capabilities, capability.value)
        contract = CAPABILITY_CONTRACT[capability]
        if tuple(item.value for item in actual.inherits) != contract["inherits"]:
            raise RulesValidationError(
                "RULESET_CAPABILITY_CONTRACT",
                f"{capability.value} inheritance does not match schema 1.1",
            )
        if actual.rule_paths != contract["rule_paths"]:
            raise RulesValidationError(
                "RULESET_CAPABILITY_CONTRACT",
                f"{capability.value} dependencies do not match schema 1.1",
            )


def validate_v11_governance(rules: dict[str, Any], season_code: str) -> None:
    """Validate capability declarations and immutable interpretation decisions."""

    try:
        capabilities = CapabilitiesFile.model_validate(rules.get("capabilities"))
        interpretations = InterpretationsFile.model_validate(rules.get("interpretations"))
        verification = RuleVerificationFile.model_validate(rules.get("rule_verification"))
    except ValidationError as exc:
        raise RulesValidationError(
            "RULESET_CAPABILITY_SCHEMA", "schema 1.1 governance metadata is invalid"
        ) from exc
    validate_capability_contract(capabilities)
    _validate_interpretation_hashes(interpretations.decisions)
    decisions = {decision.decision_id: decision for decision in interpretations.decisions}
    decision_ids = set(decisions)
    for decision in interpretations.decisions:
        if decision.season != season_code:
            raise RulesValidationError(
                "RULESET_INTERPRETATION_SEASON", "interpretation season does not match ruleset"
            )
    for record in verification.rules:
        missing = set(record.interpretation_decision_ids) - decision_ids
        if missing:
            raise RulesValidationError(
                "RULESET_INTERPRETATION_REFERENCE",
                "rule verification references an unknown interpretation decision",
                blockers=tuple(sorted(missing)),
            )
        for decision_id in record.interpretation_decision_ids:
            expected = "APPROVED" if decisions[decision_id].approved else "UNAPPROVED"
            if record.interpretation_approval_states.get(decision_id) != expected:
                raise RulesValidationError(
                    "RULESET_INTERPRETATION_APPROVAL_STATE",
                    "rule verification approval state contradicts its interpretation decision",
                    blockers=(decision_id,),
                )


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/"):
        raise RulesValidationError("RULESET_CAPABILITY_POINTER", "rule path is not a JSON pointer")
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/"))


def _pointer_value(root: dict[str, Any], pointer: str) -> object:
    value: object = root
    for token in _pointer_tokens(pointer):
        if isinstance(value, dict) and value.get("verification_status") in {
            "UNKNOWN",
            "CONFLICTED",
        }:
            return value
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        else:
            raise RulesValidationError(
                "RULESET_CAPABILITY_DEPENDENCY", f"capability dependency is absent: {pointer}"
            )
    return value


def _leaf_paths(value: object, pointer: str) -> tuple[str, ...]:
    if isinstance(value, dict):
        if value.get("verification_status") in {"UNKNOWN", "CONFLICTED"}:
            return (pointer,)
        paths: list[str] = []
        for key in sorted(value):
            escaped = key.replace("~", "~0").replace("/", "~1")
            paths.extend(_leaf_paths(value[key], f"{pointer}/{escaped}"))
        return tuple(paths)
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_leaf_paths(item, f"{pointer}/{index}"))
        return tuple(paths)
    return (pointer,)


def _path_matches(prefix: str, path: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _verification_for(
    path: str, records: tuple[RuleVerificationRecord, ...]
) -> RuleVerificationRecord | None:
    matches = [record for record in records if _path_matches(record.rule_path, path)]
    return max(matches, key=lambda record: len(record.rule_path), default=None)


def _dependency_closure(
    capability: RuleCapability, capabilities: CapabilitiesFile
) -> tuple[str, ...]:
    paths: list[str] = []
    visiting: set[RuleCapability] = set()

    def visit(item: RuleCapability) -> None:
        if item in visiting:
            raise RulesValidationError("RULESET_CAPABILITY_CYCLE", "capability inheritance cycles")
        visiting.add(item)
        definition = getattr(capabilities.capabilities, item.value)
        for inherited in definition.inherits:
            visit(inherited)
        for path in definition.rule_paths:
            if path not in paths:
                paths.append(path)
        visiting.remove(item)

    visit(capability)
    return tuple(paths)


def compile_capability_artifact(
    compiled: CompiledRuleset, capability: RuleCapability
) -> CapabilityArtifact:
    """Compile one capability's exact rules, evidence, decisions, blockers, and hash."""

    from dmf_pulse.rules.compiler import ensure_compiled_ruleset_integrity

    ensure_compiled_ruleset_integrity(compiled)
    if compiled.schema_version != "1.1":
        raise RulesValidationError(
            "RULESET_CAPABILITY_SCHEMA", "capability artifacts require schema version 1.1"
        )
    validate_v11_governance(compiled.rules, compiled.season_code)
    capabilities = CapabilitiesFile.model_validate(compiled.rules["capabilities"])
    verification = RuleVerificationFile.model_validate(compiled.rules["rule_verification"])
    interpretation_file = InterpretationsFile.model_validate(compiled.rules["interpretations"])
    decisions = {decision.decision_id: decision for decision in interpretation_file.decisions}
    dependency_paths = _dependency_closure(capability, capabilities)
    root = {"rules": compiled.rules}
    selected_rules: dict[str, Any] = {}
    expanded_verification: dict[str, dict[str, Any]] = {}
    relevant_decisions: dict[str, InterpretationDecision] = {}
    blockers: list[str] = []
    source_backed = True
    for dependency in dependency_paths:
        value = _pointer_value(root, dependency)
        selected_rules[dependency] = value
        for leaf in _leaf_paths(value, dependency):
            leaf_value = _pointer_value(root, leaf)
            if isinstance(leaf_value, dict) and leaf_value.get("verification_status") in {
                "UNKNOWN",
                "CONFLICTED",
            }:
                blockers.append(f"unknown:{leaf}")
                source_backed = False
                continue
            record = _verification_for(leaf, verification.rules)
            if record is None:
                blockers.append(f"verification_missing:{leaf}")
                source_backed = False
                continue
            if not record.source_refs:
                source_backed = False
            provenance = compiled.rule_provenance.get(leaf)
            if provenance is None:
                blockers.append(f"provenance_missing:{leaf}")
                source_backed = False
            else:
                expanded_verification[leaf] = {
                    "rule_path": leaf,
                    "value": leaf_value,
                    "verification_status": record.verification_status.value,
                    "source_refs": list(record.source_refs),
                    "sources": [source.model_dump(mode="json") for source in provenance.sources],
                    "interpretation_decision_ids": list(record.interpretation_decision_ids),
                    "interpretation_note": record.interpretation_note,
                }
            if record.verification_status in {
                VerificationStatus.UNKNOWN,
                VerificationStatus.CONFLICTED,
            }:
                blockers.append(f"{record.verification_status.value.lower()}:{leaf}")
            elif record.verification_status is VerificationStatus.INTERPRETATION_REQUIRED:
                for decision_id in record.interpretation_decision_ids:
                    decision = decisions[decision_id]
                    relevant_decisions[decision_id] = decision
                    if decision.affected_rule != record.rule_path:
                        blockers.append(f"interpretation:{decision_id}:wrong_rule")
                    elif not decision.approved:
                        blockers.append(f"interpretation:{decision_id}:unapproved")
                    elif capability not in decision.scope:
                        blockers.append(f"interpretation:{decision_id}:out_of_scope")
    blockers_tuple = tuple(sorted(set(blockers)))
    approval_only = bool(blockers_tuple) and all(
        blocker.startswith("interpretation:") and blocker.endswith(":unapproved")
        for blocker in blockers_tuple
    )
    payload: dict[str, Any] = {
        "artifact_type": "DMF_RULE_CAPABILITY",
        "schema_version": "1.1",
        "ruleset_id": compiled.ruleset_id,
        "ruleset_version": compiled.ruleset_version,
        "season_code": compiled.season_code,
        "capability": capability.value,
        "dependency_paths": list(dependency_paths),
        "source_backed": source_backed,
        "ready_for_human_approval": source_backed and (not blockers_tuple or approval_only),
        "production_eligible": source_backed and not blockers_tuple,
        "blockers": list(blockers_tuple),
        "selected_rules": dict(sorted(selected_rules.items())),
        "rule_verification": [record for _, record in sorted(expanded_verification.items())],
        "interpretations": [
            decision.model_dump(mode="json") for _, decision in sorted(relevant_decisions.items())
        ],
    }
    payload["capability_hash"] = canonical_rules_sha256(payload)
    return CapabilityArtifact.model_validate(payload)


def write_capability_artifact(artifact: CapabilityArtifact, output: Path) -> None:
    value = artifact.model_dump(mode="json")
    claimed = value.pop("capability_hash")
    if canonical_rules_sha256(value) != claimed:
        raise RulesIntegrityError(
            "RULESET_CAPABILITY_HASH", "capability artifact hash does not match"
        )
    value["capability_hash"] = claimed
    data = pretty_rules_json(value).encode("utf-8")
    if output.exists():
        if output.read_bytes() != data:
            raise RulesIntegrityError(
                "RULESET_OUTPUT_COLLISION", "capability output contains a different artifact"
            )
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".capability-", dir=output.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
    temporary.replace(output)


def load_capability_artifact(path: Path) -> CapabilityArtifact:
    try:
        raw = path.read_bytes()
        artifact = CapabilityArtifact.model_validate(json.loads(raw.decode("utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise RulesIntegrityError(
            "RULESET_CAPABILITY_INVALID", "capability artifact is unavailable or invalid"
        ) from exc
    value = artifact.model_dump(mode="json")
    claimed = cast(str, value.pop("capability_hash"))
    if canonical_rules_sha256(value) != claimed:
        raise RulesIntegrityError("RULESET_CAPABILITY_HASH", "capability artifact hash mismatch")
    value["capability_hash"] = claimed
    if raw != pretty_rules_json(value).encode("utf-8"):
        raise RulesIntegrityError(
            "RULESET_CAPABILITY_CANONICAL", "capability artifact is not canonical JSON"
        )
    return artifact
