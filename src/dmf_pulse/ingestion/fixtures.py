"""Manifest-bound synthetic fixture authorization and path safety."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from dmf_pulse.ingestion.errors import IngestionError

TRUSTED_MANIFEST_SHA256 = "a59443aae90ff6f030a39c02d14fc90e3ee2f64b5eb1e2a8cb527224c48f278b"
ODD005_MANIFEST_SHA256 = "b02bb6d02d6454fb39cb79170cc63b5e21e19a639623151a3d11edf3fe564f96"
NRM006_MANIFEST_SHA256 = "a63bd28ef7fcea90c56697ee0e77dc28ec10f63b53bdd794d21aa84815d85d23"
TRUSTED_MANIFESTS = {
    TRUSTED_MANIFEST_SHA256: "FPL-004",
    ODD005_MANIFEST_SHA256: "ODD-005",
    NRM006_MANIFEST_SHA256: "NRM-006",
}

_SYNTHETIC_TEST_PROFILES = frozenset({"synthetic_test_v1", "synthetic_the_odds_api_v1"})


@dataclass(frozen=True, slots=True)
class ApprovedFixture:
    path: Path
    relative_path: str
    sha256: str


def _find_manifest(path: Path) -> Path:
    for parent in (path, *path.parents):
        candidate = parent / "manifest.json"
        if candidate.is_file():
            # The nearest manifest is authoritative for this fixture tree.  A
            # malformed or untrusted nested manifest must fail closed instead
            # of silently falling through to an unrelated ancestor manifest.
            return candidate
    raise IngestionError("FIXTURE_NOT_APPROVED", "fixture manifest was not found")


def approve_synthetic_fixture(path: Path, *, profile_id: str) -> ApprovedFixture:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture path is unavailable") from exc
    if path.is_symlink() or not resolved.is_file():
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture path is not a regular file")
    manifest_path = _find_manifest(resolved.parent)
    fixture_ancestor = next(
        (
            parent
            for parent in (manifest_path.parent, *manifest_path.parents)
            if parent.name == "fixtures"
        ),
        None,
    )
    if fixture_ancestor is None:
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture manifest is outside fixtures")
    fixture_root = fixture_ancestor.parent.resolve(strict=True)
    try:
        relative = resolved.relative_to(fixture_root).as_posix()
        manifest_bytes = manifest_path.read_bytes()
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        pack_id = TRUSTED_MANIFESTS.get(manifest_sha256)
        if pack_id is None:
            raise ValueError("untrusted fixture manifest")
        value = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture manifest is invalid") from exc
    entries = value.get("entries") if isinstance(value, dict) else None
    if not isinstance(entries, list):
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture manifest is invalid")
    paths = {entry.get("path") for entry in entries if isinstance(entry, dict)}
    legacy_envelope = (
        value.get("manifest_version") == "1.0.0"
        and value.get("pack_id") == pack_id
        and value.get("fixture_count") == len(entries)
    )
    nrm006_envelope = (
        pack_id == "NRM-006"
        and value.get("fixture_manifest_version") == "nrm-006-fixtures-v1.1"
        and value.get("ticket") == pack_id
        and len(entries) == 12
        and value.get("oracles")
        == [
            "expected_outputs/balanced_book.json",
            "expected_outputs/duplicate_outcome_same_payload.json",
            "expected_outputs/future_mapping_canaries.json",
            "expected_outputs/happy_path_consensus.json",
            "expected_outputs/heavy_favourite.json",
            "expected_outputs/high_overround.json",
            "expected_outputs/incomplete_book.json",
            "expected_outputs/processing_crosses_cutoff.json",
            "expected_outputs/rate_limit_retry.json",
            "expected_outputs/same_value_reobservation.json",
            "expected_outputs/stale_mixed_books.json",
        ]
    )
    if (
        not (legacy_envelope or nrm006_envelope)
        or len(paths) != len(entries)
        or not all(isinstance(path_value, str) for path_value in paths)
    ):
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture manifest is invalid")
    matches = [
        entry for entry in entries if isinstance(entry, dict) and entry.get("path") == relative
    ]
    if len(matches) != 1:
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture is not manifest-approved")
    entry = matches[0]
    rights_match = (
        entry.get("rights_profile") == profile_id
        if legacy_envelope
        else entry.get("rights_classification") == "SYNTHETIC_TEST"
        and profile_id in _SYNTHETIC_TEST_PROFILES
    )
    if entry.get("synthetic") is not True or not rights_match:
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture rights metadata does not match")
    raw = resolved.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    size_matches = entry.get("bytes") == len(raw) if legacy_envelope else "bytes" not in entry
    if entry.get("sha256") != digest or not size_matches:
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture bytes do not match the manifest")
    return ApprovedFixture(path=resolved, relative_path=relative, sha256=digest)
