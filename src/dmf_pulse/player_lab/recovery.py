"""Explicit bounded recovery reads, with packaged reviewed custody as the trust root."""

from __future__ import annotations

import hashlib
import os
import stat
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from dmf_pulse.player_lab.recovery_models import ArtifactVerification, RecoveryCatalogue

_RESOURCE = "recovered_forecasts_v1.json"
# Exact reviewed metadata bytes, not a caller-supplied status or approval file.
_RESOURCE_SHA256 = "3dde6cd2322e72cf9e7a4232c8f98a679b5bd6c687c19af5adbce0ac2bafb4f3"
_MAX_CATALOGUE_BYTES = 48_000
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_DENIED_NAMES = frozenset({".aws", ".ssh", ".env", "credentials", "secrets"})
_P01_BYTE_SHA256 = "e3b7db4ef8db933a6ff5ed940bbe0a250601ad1780361fbef4195282ed27f2ee"
_P01_SEMANTIC_SHA256 = "96a13e8265095672708586dd1fd2a7f9653857594ba5fa325e82c0b3385ab15a"


class RecoveryError(ValueError):
    """Typed safe error without input paths, bodies or underlying exception text."""

    def __init__(
        self,
        code: Literal["RECOVERY_CATALOGUE_UNAVAILABLE", "RECOVERY_ARTIFACT_UNSAFE_OR_UNREADABLE"],
    ) -> None:
        self.code = code
        super().__init__(code)


def _catalogue_or_none() -> RecoveryCatalogue | None:
    try:
        body = files("dmf_pulse.player_lab").joinpath("resources", _RESOURCE).read_bytes()
        if len(body) > _MAX_CATALOGUE_BYTES or hashlib.sha256(body).hexdigest() != _RESOURCE_SHA256:
            raise ValueError("metadata byte binding failed")
        value = RecoveryCatalogue.model_validate_json(body)
        original = tuple(
            item for item in value.families if item.classification == "REAL_PRE_OUTCOME_FROZEN"
        )
        if (
            len(original) != 1
            or original[0].family_id != "P01_PUBLIC_MATCH_FORECAST"
            or original[0].artifact_byte_sha256 != _P01_BYTE_SHA256
            or original[0].artifact_semantic_sha256 != _P01_SEMANTIC_SHA256
            or original[0].sample_count != 10
            or original[0].products_per_sample != 3
        ):
            raise ValueError("original P01 binding failed")
        return value
    except (OSError, ValueError, TypeError, RecursionError, ValidationError):
        return None


def recovery_catalogue() -> RecoveryCatalogue:
    """Read only shipped, hash-bound metadata; never scan, acquire, score or admit."""
    # Raise after the parser frame has returned: a suppressed exception context
    # would still retain parser input and raw-body locals for introspection.
    outcome = _catalogue_or_none()
    if outcome is None:
        raise RecoveryError("RECOVERY_CATALOGUE_UNAVAILABLE")
    return outcome


def _artifact_digest(path: Path) -> tuple[str, int]:
    # No recursive search. The operator selects one local regular artifact.
    raw = str(path)
    if (
        raw.startswith(("\\\\", "//"))
        or "://" in raw
        or (bool(path.drive) and not path.is_absolute())
        or any(
            part.lower() in _DENIED_NAMES
            or part.lower().startswith(".env.")
            or "credential" in part.lower()
            or "secret" in part.lower()
            or (":" in part and part.rstrip("\\/") != path.drive)
            for part in path.parts
        )
    ):
        raise ValueError("unsafe input identity")
    for candidate in (path, *path.parents):
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("links and reparse points are excluded")
    selected = path.lstat()
    if not stat.S_ISREG(selected.st_mode) or selected.st_size > _MAX_ARTIFACT_BYTES:
        raise ValueError("input is not a bounded regular file")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > _MAX_ARTIFACT_BYTES
            or (selected.st_ino, selected.st_dev) != (metadata.st_ino, metadata.st_dev)
        ):
            raise ValueError("input is not a bounded regular file")
        digest = hashlib.sha256()
        size = 0
        while chunk := handle.read(min(1024 * 1024, _MAX_ARTIFACT_BYTES - size + 1)):
            size += len(chunk)
            if size > _MAX_ARTIFACT_BYTES:
                raise ValueError("input grew beyond limit")
            digest.update(chunk)
        final_metadata = os.fstat(handle.fileno())
        if (metadata.st_size, metadata.st_mtime_ns) != (
            final_metadata.st_size,
            final_metadata.st_mtime_ns,
        ) or size != metadata.st_size:
            raise ValueError("input changed during authentication")
    return digest.hexdigest(), size


def _digest_or_none(path: Path) -> tuple[str, int] | None:
    try:
        return _artifact_digest(path)
    except (OSError, ValueError, TypeError):
        return None


def verify_recovered_artifact(path: Path) -> ArtifactVerification:
    """Authenticate bytes only; unknown JSON/pickle cannot self-assert real custody."""
    catalogue = recovery_catalogue()
    outcome = _digest_or_none(path)
    if outcome is None:
        raise RecoveryError("RECOVERY_ARTIFACT_UNSAFE_OR_UNREADABLE")
    digest, size = outcome
    matched = next(
        (item for item in catalogue.families if item.artifact_byte_sha256 == digest), None
    )
    return ArtifactVerification(
        byte_sha256=digest,
        bytes=size,
        family_id=None if matched is None else matched.family_id,
        classification="UNVERIFIED_CUSTODY" if matched is None else matched.classification,
        retention="NOT_ESTABLISHED" if matched is None else matched.retention,
        catalogue_semantic_sha256=catalogue.semantic_sha256,
        status=(
            "UNKNOWN_BYTES_NO_CUSTODY_PROOF"
            if matched is None
            else "MATCHED_REVIEWED_ORIGINAL_BYTES"
        ),
    )
