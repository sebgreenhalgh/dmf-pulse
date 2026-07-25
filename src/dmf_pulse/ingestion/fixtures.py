"""Manifest-bound synthetic fixture authorization and path safety."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from dmf_pulse.ingestion.errors import IngestionError

TRUSTED_MANIFEST_SHA256 = "a59443aae90ff6f030a39c02d14fc90e3ee2f64b5eb1e2a8cb527224c48f278b"


@dataclass(frozen=True, slots=True)
class ApprovedFixture:
    path: Path
    relative_path: str
    sha256: str


def _find_manifest(path: Path) -> Path:
    for parent in (path, *path.parents):
        candidate = parent / "manifest.json"
        if candidate.is_file() and parent.name == "fixtures":
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
    fixture_root = manifest_path.parent.parent.resolve(strict=True)
    try:
        relative = resolved.relative_to(fixture_root).as_posix()
        manifest_bytes = manifest_path.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != TRUSTED_MANIFEST_SHA256:
            raise ValueError("untrusted fixture manifest")
        value = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture manifest is invalid") from exc
    entries = value.get("entries") if isinstance(value, dict) else None
    if not isinstance(entries, list):
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture manifest is invalid")
    if (
        value.get("manifest_version") != "1.0.0"
        or value.get("pack_id") != "FPL-004"
        or value.get("fixture_count") != len(entries)
        or len({entry.get("path") for entry in entries if isinstance(entry, dict)}) != len(entries)
    ):
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture manifest is invalid")
    matches = [
        entry for entry in entries if isinstance(entry, dict) and entry.get("path") == relative
    ]
    if len(matches) != 1:
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture is not manifest-approved")
    entry = matches[0]
    if entry.get("synthetic") is not True or entry.get("rights_profile") != profile_id:
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture rights metadata does not match")
    raw = resolved.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if entry.get("sha256") != digest or entry.get("bytes") != len(raw):
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture bytes do not match the manifest")
    return ApprovedFixture(path=resolved, relative_path=relative, sha256=digest)
