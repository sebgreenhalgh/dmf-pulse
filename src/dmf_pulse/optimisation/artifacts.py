"""Canonical, immutable, root-confined OPT-010 artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ValidationError

from dmf_pulse.fpl_points.artifacts import canonical_json_bytes, sha256_bytes
from dmf_pulse.optimisation.errors import OptimisationError

_SEMANTIC_HASH_FIELDS = (
    "snapshot_sha256",
    "request_sha256",
    "plan_sha256",
    "result_sha256",
)


def _semantic_hash(value: BaseModel, field: str) -> str:
    payload = value.model_dump(mode="json")
    payload[field] = None
    return sha256_bytes(canonical_json_bytes(payload))


def _verify_embedded_hash(value: BaseModel, *, required: bool = False) -> None:
    field = next(
        (candidate for candidate in _SEMANTIC_HASH_FIELDS if candidate in type(value).model_fields),
        None,
    )
    if field is None:
        return
    claimed = getattr(value, field)
    if claimed is None:
        if required:
            raise OptimisationError(
                "OPTIMISATION_ARTIFACT_INVALID", f"artifact is missing required {field}"
            )
        return
    if claimed != _semantic_hash(value, field):
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", f"artifact {field} does not match semantic payload"
        )


def load_canonical_json[T: BaseModel](path: Path, model_type: type[T]) -> T:
    """Load canonical JSON and verify an embedded semantic hash when one is present."""

    try:
        raw = path.read_bytes()
        value = model_type.model_validate(json.loads(raw.decode("utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", f"invalid artifact: {path}"
        ) from exc
    if canonical_json_bytes(value) != raw:
        raise OptimisationError("OPTIMISATION_ARTIFACT_INVALID", "artifact is not canonical JSON")
    _verify_embedded_hash(value)
    return value


def load_verified_artifact[T: BaseModel](path: Path, model_type: type[T]) -> T:
    """Load an immutable OPT-010 result artifact with exact detached and embedded hashes."""

    try:
        raw = path.read_bytes()
        sidecar = path.with_suffix(".sha256").read_bytes()
    except OSError as exc:
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", "artifact or detached hash is unavailable"
        ) from exc
    digest = sha256_bytes(raw)
    expected_sidecar = f"{digest}  {path.name}\n".encode("ascii")
    if sidecar != expected_sidecar:
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", "artifact detached hash does not match"
        )
    value = load_canonical_json(path, model_type)
    _verify_embedded_hash(value, required=True)
    return value


def _safe_segment(value: str, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or any(token in value for token in ("/", "\\", ":", "\x00"))
        or Path(value).is_absolute()
    ):
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", f"{label} must be a safe artifact path segment"
        )
    return value


def _contained_directory(artifact_root: Path, *, gameweek_id: str, request_id: str) -> Path:
    if artifact_root.is_symlink():
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", "artifact root cannot itself be a symbolic link"
        )
    try:
        root = artifact_root.resolve()
        directory = (
            root
            / "optimisation"
            / "one_gameweek"
            / _safe_segment(gameweek_id, label="gameweek ID")
            / _safe_segment(request_id, label="request ID")
        )
        resolved = directory.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", "artifact path escapes the configured root"
        ) from exc
    return directory


def _write_once(path: Path, data: bytes, *, root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.resolve().relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", "artifact path escapes the configured root"
        ) from exc
    if path.is_symlink():
        raise OptimisationError(
            "OPTIMISATION_ARTIFACT_INVALID", "artifact destination cannot be a symbolic link"
        )
    if path.exists():
        if path.read_bytes() != data:
            raise OptimisationError("OPTIMISATION_ARTIFACT_INVALID", "immutable artifact collision")
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".opt-", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink():
                raise OptimisationError(
                    "OPTIMISATION_ARTIFACT_INVALID",
                    "artifact destination cannot be a symbolic link",
                ) from None
            if path.read_bytes() != data:
                raise OptimisationError(
                    "OPTIMISATION_ARTIFACT_INVALID", "immutable artifact collision"
                ) from None
        temporary.unlink(missing_ok=True)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def persist_result(
    result: BaseModel,
    *,
    artifact_root: Path,
    gameweek_id: str,
    request_id: str = "request",
) -> Path:
    """Publish exact bytes once below a verified root-confined identity path."""

    _verify_embedded_hash(result, required=True)
    data = canonical_json_bytes(result)
    digest = sha256_bytes(data)
    directory = _contained_directory(artifact_root, gameweek_id=gameweek_id, request_id=request_id)
    path = directory / f"{digest}.json"
    _write_once(path, data, root=artifact_root)
    _write_once(
        path.with_suffix(".sha256"),
        f"{digest}  {path.name}\n".encode("ascii"),
        root=artifact_root,
    )
    return path
