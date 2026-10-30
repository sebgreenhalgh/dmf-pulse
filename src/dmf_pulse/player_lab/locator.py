"""Explicit bounded local forecast discovery; payloads are hashed, never executed."""

from __future__ import annotations

import stat
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from dmf_pulse.operation.models import Metadata, MetadataTime
from dmf_pulse.player_lab.local_handles import DirectoryPins
from dmf_pulse.player_lab.recovery import (
    RecoveryError,
    _artifact_digest,
    _safe_lexical_path,
    recovery_catalogue,
)
from dmf_pulse.player_lab.recovery_models import Classification, Retention


class LocatorBounds(Metadata):
    maximum_files: Annotated[int, Field(ge=1, le=128)] = 32
    maximum_depth: Annotated[int, Field(ge=0, le=3)] = 0
    maximum_total_bytes: Annotated[int, Field(ge=1, le=512 * 1024 * 1024)] = 128 * 1024 * 1024


class LocatedArtifact(Metadata):
    relative_locator: str
    byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    reviewed_family_id: str | None
    classification: Classification
    retention: Retention
    evaluation_eligibility: Literal["EVALUATION_INELIGIBLE_PENDING_QUALIFICATION"] = (
        "EVALUATION_INELIGIBLE_PENDING_QUALIFICATION"
    )
    custody: Literal["REVIEWED_ORIGINAL_BYTE_MATCH", "UNVERIFIED_NO_EXTERNAL_PREDEADLINE_PROOF"]
    original_forecast_origin: datetime | None = None
    original_information_cutoff: datetime | None = None
    original_frozen_at: datetime | None = None


class LocatorInventory(Metadata):
    schema_version: Literal["approved-local-forecast-locator-inventory-v1"] = (
        "approved-local-forecast-locator-inventory-v1"
    )
    observed_at: datetime
    bounds: LocatorBounds
    artifacts: tuple[LocatedArtifact, ...]
    body_retention: Literal["NO_BODY_COPIED_OR_PARSED"] = "NO_BODY_COPIED_OR_PARSED"
    mtime_is_freeze_proof: Literal[False] = False
    pickle_executed: Literal[False] = False
    source_rights_granted: Literal[False] = False
    evaluation_authorized: Literal[False] = False

    def public_summary(self) -> dict[str, object]:
        """Only aggregates leave the private operator directory."""
        return {
            "schema_version": "forecast-locator-public-summary-v1",
            "inventory_semantic_sha256": self.semantic_sha256,
            "files_hashed": len(self.artifacts),
            "bytes_hashed": sum(row.bytes for row in self.artifacts),
            "classifications": {
                kind: sum(row.classification == kind for row in self.artifacts)
                for kind in sorted({row.classification for row in self.artifacts})
            },
            "evaluation_authorized": False,
            "additional_owner_freezes": "UNRESOLVED_NOT_DISPROVED",
        }


def _safe_local(path: Path) -> None:
    _safe_lexical_path(path)
    raw = str(path)
    if not path.is_absolute() or raw.startswith(("\\\\", "//")) or "://" in raw:
        raise ValueError("explicit absolute local locator required")
    for item in (path, *path.parents):
        metadata = item.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("links and reparse points are excluded")


def _inventory_pinned(
    path: Path, bounds: LocatorBounds, now: datetime, pins: DirectoryPins
) -> LocatorInventory | None:
    try:
        _safe_local(path)
        if path.is_file():
            candidates = [(path, path.name)]
        elif path.is_dir():
            candidates = []
            pending = [(path, 0)]
            visited = 0
            while pending:
                directory, depth = pending.pop()
                _safe_local(directory)
                with pins.scan(directory) as scan:
                    for entry in scan:
                        visited += 1
                        if visited > bounds.maximum_files * 4:
                            raise ValueError("directory census exceeds bound")
                        selected = directory / entry.name
                        _safe_local(selected)
                        if entry.is_dir(follow_symlinks=False):
                            if depth < bounds.maximum_depth:
                                pins.pin(selected)
                                pending.append((selected, depth + 1))
                        elif entry.is_file(follow_symlinks=False):
                            candidates.append((selected, selected.relative_to(path).as_posix()))
                        else:
                            raise ValueError("nonregular local entry")
                        if len(candidates) > bounds.maximum_files:
                            raise ValueError("file budget exceeded")
        else:
            raise ValueError("locator is not a local file or directory")
        catalogue = recovery_catalogue()
        known = {
            row.artifact_byte_sha256: row for row in catalogue.families if row.artifact_byte_sha256
        }
        # Held metadata descriptors identify files; check the byte budget before
        # reading any candidate body.
        census = {relative: pins.metadata(item) for item, relative in candidates}
        if sum(value.st_size for value in census.values()) > bounds.maximum_total_bytes:
            raise ValueError("total byte budget exceeded")
        artifacts = []
        total = 0
        for item, relative in sorted(candidates, key=lambda pair: pair[1]):
            metadata = census[relative]
            digest, size = _artifact_digest(
                item,
                maximum_bytes=bounds.maximum_total_bytes - total,
                expected_identity=(
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                ),
                pins=pins,
            )
            total += size
            if total > bounds.maximum_total_bytes:
                raise ValueError("total byte budget exceeded")
            family = known.get(digest)
            artifacts.append(
                LocatedArtifact(
                    relative_locator=relative,
                    byte_sha256=digest,
                    bytes=size,
                    reviewed_family_id=None if family is None else family.family_id,
                    classification="UNVERIFIED_CUSTODY"
                    if family is None
                    else family.classification,
                    retention="NOT_ESTABLISHED" if family is None else family.retention,
                    custody="UNVERIFIED_NO_EXTERNAL_PREDEADLINE_PROOF"
                    if family is None
                    else "REVIEWED_ORIGINAL_BYTE_MATCH",
                    original_forecast_origin=None if family is None else family.forecast_origin,
                    original_information_cutoff=None
                    if family is None
                    else family.information_cutoff,
                    original_frozen_at=None if family is None else family.frozen_at,
                )
            )
        return LocatorInventory(observed_at=now, bounds=bounds, artifacts=tuple(artifacts))
    except (OSError, ValueError, TypeError, RecoveryError):
        return None


def _inventory_or_none(path: Path, bounds: LocatorBounds, now: datetime) -> LocatorInventory | None:
    try:
        _safe_local(path)
        if any(part in {".", ".."} for part in path.parts):
            return None
        selected = path.lstat()
        with DirectoryPins() as pins:
            if stat.S_ISDIR(selected.st_mode):
                pins.pin(path, expected=selected)
            elif stat.S_ISREG(selected.st_mode):
                pins.pin(path.parent)
            else:
                return None
            return _inventory_pinned(path, bounds, now, pins)
    except (OSError, ValueError, TypeError):
        return None


def onboard_locator(
    path: Path, *, bounds: LocatorBounds | None = None, now: datetime
) -> LocatorInventory:
    bounds = LocatorBounds() if bounds is None else LocatorBounds.model_validate(bounds)
    now = MetadataTime(checked_at=now).checked_at
    result = _inventory_or_none(path, bounds, now)
    if result is None:
        raise RecoveryError("RECOVERY_LOCATOR_UNSAFE_OR_BUDGET_EXCEEDED")
    return result
