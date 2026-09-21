"""Explicit private content-addressed retention; never writes on import."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.football_events.team_strength_model import TeamStrengthModelArtifactV1
from dmf_pulse.ingestion.openfootball.team_strength_data import StrengthEvidenceError, authenticate


def persist_team_strength(artifact: TeamStrengthModelArtifactV1, *, artifact_root: Path) -> Path:
    artifact = authenticate(artifact)
    root = artifact_root.resolve()
    destination = (
        root
        / "team-strength-shadow"
        / artifact.model.semantic_sha256
        / f"{artifact.semantic_sha256}.json"
    )
    if not destination.resolve().is_relative_to(root) or destination.is_symlink():
        raise StrengthEvidenceError("artifact destination escapes the requested private root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.resolve().is_relative_to(root) or destination.is_symlink():
        raise StrengthEvidenceError("artifact destination changed during directory creation")
    payload = pretty_json(artifact).encode("utf-8")
    if destination.exists():
        if destination.read_bytes() != payload:
            raise StrengthEvidenceError("immutable model artifact identity collision")
        return destination
    # An exclusive hard-link publication has no replacement race. Unsupported
    # filesystems fail closed; there is no overwrite or mutable latest alias.
    handle, temporary_name = tempfile.mkstemp(prefix=".team-strength-", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != payload:
                raise StrengthEvidenceError(
                    "immutable model artifact publication collision"
                ) from None
    finally:
        temporary.unlink()
    return destination


def load_team_strength(path: Path, *, expected_artifact_sha256: str) -> TeamStrengthModelArtifactV1:
    return authenticate(
        TeamStrengthModelArtifactV1.model_validate_json(path.read_bytes()), expected_artifact_sha256
    )
