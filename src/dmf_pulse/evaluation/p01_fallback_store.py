"""Exclusive content-addressed storage for the explicit P01 fallback schemas."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.evaluation.p01_fallback import (
    P01FallbackReconciliationV1,
    P01FallbackScorecardV1,
    P01FallbackScoreV1,
)
from dmf_pulse.evaluation.p01_fallback_context import require_openligadb_rights, strict_json
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    StrengthEvidenceError,
    authenticate,
)
from dmf_pulse.ingestion.p01_fallback import PublicP01FallbackOutcomesV1

type FallbackArtifact = (
    PublicP01FallbackOutcomesV1
    | P01FallbackScoreV1
    | P01FallbackScorecardV1
    | P01FallbackReconciliationV1
)
_SCHEMAS: dict[str, type[FallbackArtifact]] = {
    "public-team-strength-p01-fallback-outcomes-v1": PublicP01FallbackOutcomesV1,
    "public-team-strength-p01-fallback-score-v1": P01FallbackScoreV1,
    "public-team-strength-p01-fallback-scorecard-v1": P01FallbackScorecardV1,
    "public-team-strength-p01-fallback-reconciliation-v1": P01FallbackReconciliationV1,
}


def persist_fallback(value: FallbackArtifact, *, artifact_root: Path) -> Path:
    require_openligadb_rights()
    if type(value) not in _SCHEMAS.values():
        raise StrengthEvidenceError("only explicit public fallback schemas may persist")
    value = authenticate(value)
    if artifact_root.is_symlink():
        raise StrengthEvidenceError("fallback artifact root is a symbolic link")
    root = artifact_root.resolve()
    destination = root / value.schema_version / f"{value.semantic_sha256}.json"
    if destination.is_symlink() or not destination.resolve().is_relative_to(root):
        raise StrengthEvidenceError("fallback artifact path escapes root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or not destination.resolve().is_relative_to(root):
        raise StrengthEvidenceError("fallback destination changed")
    payload = pretty_json(value).encode("utf-8")
    if destination.exists():
        if destination.read_bytes() != payload:
            raise StrengthEvidenceError("immutable fallback artifact collision")
        return destination
    descriptor, name = tempfile.mkstemp(prefix=".p01-fallback-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != payload:
                raise StrengthEvidenceError("immutable fallback publication collision") from None
    finally:
        temporary.unlink()
    loaded = load_fallback(destination, expected_sha256=value.semantic_sha256)
    if loaded != value:
        raise StrengthEvidenceError("fallback persisted artifact differs")
    return destination


def load_fallback(path: Path, *, expected_sha256: str) -> FallbackArtifact:
    if path.is_symlink():
        raise StrengthEvidenceError("fallback artifact is a symbolic link")
    data = path.read_bytes()
    value = strict_json(data)
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("schema_version"), str)
        or value["schema_version"] not in _SCHEMAS
    ):
        raise StrengthEvidenceError("not an explicit public fallback schema")
    schema = _SCHEMAS[value["schema_version"]]
    return authenticate(schema.model_validate_json(data), expected_sha256)
