"""OPT-010 JSON loading and immutable result persistence."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from dmf_pulse.fpl_points.artifacts import canonical_json_bytes, sha256_bytes
from dmf_pulse.optimisation.errors import OptimisationError


def load_canonical_json[T: BaseModel](path: Path, model_type: type[T]) -> T:
    try:
        raw = path.read_bytes()
        value = model_type.model_validate(json.loads(raw.decode("utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", f"invalid artifact: {path}"
        ) from exc
    if canonical_json_bytes(value) != raw:
        raise OptimisationError("OPTIMISATION_ARTIFACT_INVALID", "artifact is not canonical JSON")
    return value


def persist_result(result: BaseModel, *, artifact_root: Path, gameweek_id: str) -> Path:
    digest = sha256_bytes(canonical_json_bytes(result))
    safe = gameweek_id.replace("/", "_").replace("\\", "_")
    directory = artifact_root / "optimisation" / "one-gameweek" / safe
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.json"
    data = canonical_json_bytes(result)
    if path.exists() and path.read_bytes() != data:
        raise OptimisationError("OPTIMISATION_ARTIFACT_INVALID", "immutable artifact collision")
    if not path.exists():
        path.write_bytes(data)
    sidecar = path.with_suffix(".sha256")
    if sidecar.exists() and sidecar.read_text(encoding="ascii").split()[0] != digest:
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", "immutable detached hash collision"
        )
    if not sidecar.exists():
        sidecar.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return path
