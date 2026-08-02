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
ODD005_FROZEN_INPUTS = {
    "fixtures/odds/ODD-005/manifest.json": (
        "97d123ad5dff035996c26870ad48fc8d6cd8bda99179620a270bb1a977518ebc"
    ),
    "public_contracts/market_observation.schema.json": (
        "be1e753ad192368fbd8a2b82383cd86e07be2104ba5595e1ea81b5581144f217"
    ),
    "public_contracts/market_query_result.schema.json": (
        "24b5268c4e22a2b99ac7eefc4073045f2f95a71071556c74e3394a7472aafa46"
    ),
    "public_contracts/odds_ingestion_result.schema.json": (
        "4b64765a95b3ce05ec4f0170baa069f871aec98c170232c1e97a6d029f7014d3"
    ),
    "public_contracts/provider_failure.schema.json": (
        "3e6cc5975ed408e3fc027887f1b0aff834b2ccbae381679798e957f56856854b"
    ),
    "public_contracts/quota_state.schema.json": (
        "d4510bda339b0cb8992305daff9794f681735f281840623175a7b96739df79c9"
    ),
    "tickets/ODD-005/ACCEPTANCE.md": (
        "5dd3700f0fe2ee8b1c02aa4668ee8a1154166b13a0f84c7564d59e0aa48399d0"
    ),
    "tickets/ODD-005/ticket.yaml": (
        "2f21febe234cb36cf5e031c56ff0a52b665f564a3239a0ed6c258a803590243c"
    ),
    "fixtures/odds/ODD-005/expected_outputs/as_of_2026-08-20T12-05-00Z.json": (
        "015a3180323a06aa9a09e99ffb90c00a1e411d819a3c51d1ac927843086ede73"
    ),
    "fixtures/odds/ODD-005/expected_outputs/changed_quote.json": (
        "09408d93ee5051899bf2b5ab9b3d6e230e4100ca577edca516385ff35105b3a6"
    ),
    "fixtures/odds/ODD-005/expected_outputs/controlled_live_refusal.json": (
        "4ad725025a2c88f66a8b3e60d9ed82167af3f0a68892769f26d3811d0b17286a"
    ),
    "fixtures/odds/ODD-005/expected_outputs/happy_path.json": (
        "05d16722d6027822d3e03bff3cdeb56bcf475600b033c18820e4d1f027b619d7"
    ),
    "fixtures/odds/ODD-005/expected_outputs/incomplete_book.json": (
        "584e2a60ccaf4876f979510b7866a37ee27357e487f8fc48c87f6a181bf6ca37"
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


class OddFrozenInputValidationError(FrozenInputValidationError):
    def __init__(self, errors: list[str]) -> None:
        ValueError.__init__(self, "ODD-005 frozen inputs are invalid")
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


def validate_odd005_frozen_inputs(root: Path) -> dict[str, object]:
    """Verify every Pack 1.1 fixture, schema, and ticket input pinned by ODD-005."""

    root = root.resolve()
    errors: list[str] = []
    actual: dict[str, str] = {}
    for relative, expected in ODD005_FROZEN_INPUTS.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            errors.append(f"{relative}: missing or non-regular frozen input")
            continue
        digest = _digest(path)
        actual[relative] = digest
        if digest != expected:
            errors.append(f"{relative}: frozen SHA-256 mismatch")
    fixture_actual: dict[str, str] = {}
    manifest_path = root / "fixtures/odds/ODD-005/manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"fixtures/odds/ODD-005/manifest.json: invalid: {type(exc).__name__}")
        manifest = {}
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or manifest.get("manifest_version") != "1.0.0"
        or manifest.get("pack_id") != "ODD-005"
        or manifest.get("fixture_count") != 13
        or not isinstance(entries, list)
        or len(entries) != 13
    ):
        errors.append("fixtures/odds/ODD-005/manifest.json: invalid frozen envelope")
        entries = []
    seen_paths: set[str] = set()
    required_entry_keys = {
        "bytes",
        "path",
        "purpose",
        "rights_profile",
        "sha256",
        "synthetic",
    }
    fixture_root = (root / "fixtures/odds/ODD-005").resolve()
    for index, entry in enumerate(entries):
        label = f"fixtures/odds/ODD-005/manifest.json entry {index + 1}"
        if not isinstance(entry, dict) or set(entry) != required_entry_keys:
            errors.append(f"{label}: invalid keys")
            continue
        raw_relative = entry.get("path")
        expected_sha = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if (
            not isinstance(raw_relative, str)
            or not raw_relative.startswith("fixtures/odds/ODD-005/")
            or "\\" in raw_relative
            or raw_relative.startswith("/")
            or ".." in Path(raw_relative).parts
            or raw_relative in seen_paths
            or not isinstance(expected_sha, str)
            or SHA256.fullmatch(expected_sha) is None
            or isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
            or entry.get("synthetic") is not True
            or entry.get("rights_profile") != "synthetic_the_odds_api_v1"
            or entry.get("purpose") != "ODD-005 deterministic synthetic provider-shaped fixture"
        ):
            errors.append(f"{label}: invalid frozen entry")
            continue
        relative = raw_relative
        seen_paths.add(relative)
        candidate = root / relative
        try:
            candidate.resolve().relative_to(fixture_root)
        except ValueError:
            errors.append(f"{relative}: fixture path escapes its frozen root")
            continue
        if candidate.is_symlink() or not candidate.is_file():
            errors.append(f"{relative}: missing or non-regular frozen fixture")
            continue
        digest = _digest(candidate)
        fixture_actual[relative] = digest
        if candidate.stat().st_size != expected_bytes:
            errors.append(f"{relative}: frozen byte-size mismatch")
        if digest != expected_sha:
            errors.append(f"{relative}: frozen SHA-256 mismatch")
    discovered = {
        path.relative_to(root).as_posix()
        for path in fixture_root.rglob("*")
        if path.is_file()
        and path.name != "manifest.json"
        and "expected_outputs" not in path.relative_to(fixture_root).parts
    }
    if discovered != seen_paths:
        errors.append("fixtures/odds/ODD-005/manifest.json: fixture inventory mismatch")
    if errors:
        raise OddFrozenInputValidationError(errors)
    return {
        "file_count": len(actual),
        "files": dict(sorted(actual.items())),
        "fixture_entry_count": len(fixture_actual),
        "fixture_files": dict(sorted(fixture_actual.items())),
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
    if (
        root / "tickets/ODD-005/ticket.yaml"
    ).is_file() and "A5-odds-manual-import" not in scope_map:
        errors.append("authority_manifest: A5-odds-manual-import scope is missing")
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
    "ODD005_FROZEN_INPUTS",
    "FrozenInputValidationError",
    "OddFrozenInputValidationError",
    "SpecValidationError",
    "validate_fpl004_frozen_inputs",
    "validate_odd005_frozen_inputs",
    "validate_specifications",
]
