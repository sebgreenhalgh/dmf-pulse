"""Strict installed specification and authority-manifest validation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA256 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^\d+\.\d+(?:\.\d+)?(?:\s|$)")
APPROVED_DMFP04 = "DMFP-04_DATA_SOURCES_MARKETS_APIS_AND_LICENSING_ZERO_COST_v1.0.txt"
FPL004_FROZEN_INPUTS = {
    "fixtures/manifest.json": "a59443aae90ff6f030a39c02d14fc90e3ee2f64b5eb1e2a8cb527224c48f278b",
    "public_contracts/provider_snapshot_result.schema.json": (
        "53ab2f4e350d06c9b36c4e450447c907efcd4dcff3b9eb8707bd3c13794839de"
    ),
    "public_contracts/quality_report.schema.json": (
        "b8110e58a28cf562d21ae6674c95d52398b200191d145ca9d7ef0bf48ae8cd5e"
    ),
    "public_contracts/rights_decision.schema.json": (
        "dffa2b0dd6dbbdc7a280b91e8753274bcc58c9fcc2e63421e5864409ac8ac33c"
    ),
    "public_contracts/source_bundle_summary.schema.json": (
        "aec43210bee973712b21b45244db0bf4d2d00812b08b74e05a4000f395bfe679"
    ),
}


class SpecValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("installed specification manifests are invalid")
        self.errors = tuple(errors)

    def as_error_object(self) -> dict[str, object]:
        return {
            "error": {
                "code": "SPEC_MANIFEST_INVALID",
                "details": list(self.errors),
                "message": str(self),
            },
            "ok": False,
        }


class FrozenInputValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("FPL-004 frozen inputs are invalid")
        self.errors = tuple(errors)


def validate_fpl004_frozen_inputs(root: Path) -> dict[str, object]:
    """Verify pack-derived fixtures and public contracts against pinned digests."""

    root = root.resolve()
    errors: list[str] = []
    actual: dict[str, str] = {}
    for relative, expected in FPL004_FROZEN_INPUTS.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            errors.append(f"{relative}: missing or non-regular frozen input")
            continue
        digest = _digest(path)
        actual[relative] = digest
        if digest != expected:
            errors.append(f"{relative}: frozen SHA-256 mismatch")
    if errors:
        raise FrozenInputValidationError(errors)
    return {
        "file_count": len(actual),
        "files": dict(sorted(actual.items())),
        "ok": True,
    }


def _object(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path.as_posix()}: malformed or unavailable: {type(exc).__name__}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.as_posix()}: root must be an object")
        return {}
    return value


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def validate_specifications(root: Path) -> dict[str, object]:
    """Validate installed document bytes, decisions, and every authority reference."""

    root = root.resolve()
    manifests = root / "specs" / "manifests"
    errors: list[str] = []
    documents = _object(manifests / "document_manifest.json", errors)
    decisions = _object(manifests / "decision_manifest.json", errors)
    authority = _object(manifests / "authority_manifest.json", errors)
    stages = _object(manifests / "stage_authority_requirements.json", errors)

    document_ids: set[str] = set()
    filenames: set[str] = set()
    raw_documents = documents.get("documents")
    if not isinstance(raw_documents, list):
        errors.append("document_manifest.documents: must be an array")
        raw_documents = []
    for index, item in enumerate(raw_documents):
        label = f"document_manifest.documents[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object")
            continue
        document_id = item.get("document_id")
        filename = item.get("filename")
        if not isinstance(document_id, str) or not document_id:
            errors.append(f"{label}: invalid document_id")
            continue
        if document_id in document_ids:
            errors.append(f"{label}: duplicate document_id {document_id}")
        document_ids.add(document_id)
        if not isinstance(filename, str) or Path(filename).name != filename:
            errors.append(f"{label}: invalid filename")
            continue
        if filename in filenames:
            errors.append(f"{label}: duplicate filename {filename}")
        filenames.add(filename)
        if document_id == "DMFP-04" and filename != APPROVED_DMFP04:
            errors.append(f"{label}: paid or obsolete DMFP-04 is forbidden")
        version = item.get("version")
        status = item.get("status")
        if not isinstance(version, str) or VERSION.match(version) is None:
            errors.append(f"{label}: malformed version")
        if not isinstance(status, str) or not status.strip():
            errors.append(f"{label}: malformed status")
        path = (
            root / "docs" / "implementation" / filename
            if document_id == "DMF-PULSE-CODEX-PLAYBOOK"
            else root / "specs" / "approved" / filename
        )
        try:
            size = path.stat().st_size
            digest = _digest(path)
        except OSError:
            errors.append(f"{label}: installed file is missing")
            continue
        if item.get("bytes") != size:
            errors.append(f"{label}: byte count mismatch")
        expected = item.get("sha256")
        if not isinstance(expected, str) or SHA256.fullmatch(expected) is None:
            errors.append(f"{label}: malformed SHA-256")
        elif expected != digest:
            errors.append(f"{label}: SHA-256 mismatch")

    decision_ids: set[str] = set()
    raw_decisions = decisions.get("decisions")
    if not isinstance(raw_decisions, list):
        errors.append("decision_manifest.decisions: must be an array")
        raw_decisions = []
    for index, item in enumerate(raw_decisions):
        label = f"decision_manifest.decisions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object")
            continue
        decision_id = item.get("id")
        if not isinstance(decision_id, str) or not decision_id:
            errors.append(f"{label}: invalid decision ID")
            continue
        if decision_id in decision_ids:
            errors.append(f"{label}: duplicate decision ID {decision_id}")
        decision_ids.add(decision_id)
        status = item.get("status")
        if status not in {"ACCEPTED", "ACTIVE", "PROVISIONAL", "SUPERSEDED", "REJECTED"}:
            errors.append(f"{label}: malformed status")
        source = item.get("source")
        if not isinstance(source, dict):
            errors.append(f"{label}: source must be an object")
            continue
        source_path = source.get("path")
        source_hash = source.get("document_sha256")
        if not isinstance(source_path, str) or not (root / source_path).is_file():
            errors.append(f"{label}: stale source path")
        elif not isinstance(source_hash, str) or _digest(root / source_path) != source_hash:
            errors.append(f"{label}: stale source hash")

    scope_map: dict[str, tuple[set[str], set[str]]] = {}
    raw_scopes = authority.get("scopes")
    if not isinstance(raw_scopes, list):
        errors.append("authority_manifest.scopes: must be an array")
        raw_scopes = []
    for index, item in enumerate(raw_scopes):
        label = f"authority_manifest.scopes[{index}]"
        if not isinstance(item, dict) or not isinstance(item.get("scope"), str):
            errors.append(f"{label}: malformed scope")
            continue
        scope = str(item["scope"])
        if scope in scope_map:
            errors.append(f"{label}: duplicate scope {scope}")
        scope_documents = item.get("documents")
        scope_decisions = item.get("decisions")
        if not isinstance(scope_documents, list) or not all(
            isinstance(value, str) for value in scope_documents
        ):
            errors.append(f"{label}: documents must be string IDs")
            scope_documents = []
        if not isinstance(scope_decisions, list) or not all(
            isinstance(value, str) for value in scope_decisions
        ):
            errors.append(f"{label}: decisions must be string IDs")
            scope_decisions = []
        missing_documents = set(scope_documents) - document_ids
        missing_decisions = set(scope_decisions) - decision_ids
        if missing_documents:
            errors.append(f"{label}: stale documents {sorted(missing_documents)}")
        if missing_decisions:
            errors.append(f"{label}: stale decisions {sorted(missing_decisions)}")
        scope_map[scope] = (set(scope_documents), set(scope_decisions))

    stage_map = stages.get("required_scopes")
    if not isinstance(stage_map, dict):
        errors.append("stage_authority_requirements.stages: must be an object")
    else:
        for scope, requirements in stage_map.items():
            if scope not in scope_map or not isinstance(requirements, dict):
                errors.append(f"stage_authority_requirements: stale scope {scope}")
                continue
            expected_documents, expected_decisions = scope_map[scope]
            if set(requirements.get("documents", [])) != expected_documents:
                errors.append(f"stage_authority_requirements: {scope} document mismatch")
            if set(requirements.get("decisions", [])) != expected_decisions:
                errors.append(f"stage_authority_requirements: {scope} decision mismatch")

    if "A4-FPL-ingestion" not in scope_map:
        errors.append("authority_manifest: A4-FPL-ingestion scope is missing")
    if errors:
        raise SpecValidationError(errors)
    return {
        "decision_count": len(decision_ids),
        "document_count": len(document_ids),
        "ok": True,
        "scope_count": len(scope_map),
    }


__all__ = [
    "FPL004_FROZEN_INPUTS",
    "FrozenInputValidationError",
    "SpecValidationError",
    "validate_fpl004_frozen_inputs",
    "validate_specifications",
]
