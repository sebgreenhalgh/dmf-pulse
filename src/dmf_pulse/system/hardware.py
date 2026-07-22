"""Safe local filesystem probing with deterministic cleanup semantics."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WritabilityProbe:
    """Result of a non-persistent artifact-root writability probe."""

    writable: bool
    cleaned_up: bool
    basis: str
    error_code: str | None = None


def _nearest_existing_directory(path: Path) -> tuple[Path | None, str]:
    if path.exists():
        if path.is_dir():
            return path, "artifact_root"
        return None, "artifact_root_not_directory"
    candidate = path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if candidate.is_dir():
        return candidate, "nearest_existing_parent"
    return None, "no_existing_parent"


def probe_artifact_writability(artifact_root: Path, *, working_directory: Path) -> WritabilityProbe:
    """Probe a root or its nearest parent without creating the configured directory."""

    target = artifact_root if artifact_root.is_absolute() else working_directory / artifact_root
    probe_directory, basis = _nearest_existing_directory(target)
    if probe_directory is None:
        return WritabilityProbe(
            writable=False,
            cleaned_up=True,
            basis=basis,
            error_code="NO_WRITABLE_PROBE_DIRECTORY",
        )

    descriptor: int | None = None
    probe_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=".dmf-pulse-probe-", dir=probe_directory)
        probe_path = Path(raw_path)
        os.close(descriptor)
        descriptor = None
        probe_path.unlink()
        return WritabilityProbe(writable=True, cleaned_up=True, basis=basis)
    except OSError:
        cleaned_up = probe_path is None or not probe_path.exists()
        return WritabilityProbe(
            writable=False,
            cleaned_up=cleaned_up,
            basis=basis,
            error_code="WRITE_PROBE_FAILED",
        )
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if probe_path is not None and probe_path.exists():
            with suppress(OSError):
                probe_path.unlink()
