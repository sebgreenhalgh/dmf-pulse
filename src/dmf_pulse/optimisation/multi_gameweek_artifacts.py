"""Canonical immutable Stage-11 artifacts with detached SHA-256 verification."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ValidationError

from dmf_pulse.fpl_points.artifacts import canonical_json_bytes, sha256_bytes
from dmf_pulse.optimisation.errors import OptimisationError
from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekOptimisationRequest,
    MultiGameweekOptimisationResult,
    StateAdvanceResult,
    verify_advance_hash,
    verify_request_hash,
    verify_result_hash,
)


def _safe_segment(value: str, *, label: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or any(token in value for token in ("/", "\\", ":", "\x00"))
        or Path(value).is_absolute()
    ):
        raise OptimisationError(
            "MULTI_GAMEWEEK_ARTIFACT_INVALID",
            f"{label} must be one safe artifact path segment",
        )
    return value


def _write_once(path: Path, data: bytes, *, root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.resolve().relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise OptimisationError(
            "MULTI_GAMEWEEK_ARTIFACT_INVALID",
            "artifact path escapes the configured root",
        ) from exc
    if path.is_symlink():
        raise OptimisationError(
            "MULTI_GAMEWEEK_ARTIFACT_INVALID",
            "artifact destination cannot be a symbolic link",
        )
    if path.exists():
        if path.is_symlink():
            raise OptimisationError(
                "MULTI_GAMEWEEK_ARTIFACT_INVALID",
                "artifact destination cannot be a symbolic link",
            )
        if path.read_bytes() != data:
            raise OptimisationError(
                "MULTI_GAMEWEEK_ARTIFACT_COLLISION",
                "immutable artifact path already contains different bytes",
            )
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".opt-011-", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink():
                raise OptimisationError(
                    "MULTI_GAMEWEEK_ARTIFACT_INVALID",
                    "artifact destination cannot be a symbolic link",
                ) from None
            if path.read_bytes() != data:
                raise OptimisationError(
                    "MULTI_GAMEWEEK_ARTIFACT_COLLISION",
                    "artifact was concurrently created with different bytes",
                ) from None
        temporary.unlink(missing_ok=True)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def persist_model(
    value: BaseModel,
    *,
    artifact_root: Path,
    category: str,
    request_id: str,
) -> Path:
    _verify_known_model(value)
    root = artifact_root.resolve()
    if artifact_root.is_symlink():
        raise OptimisationError(
            "MULTI_GAMEWEEK_ARTIFACT_INVALID",
            "artifact root cannot itself be a symbolic link",
        )
    directory = (
        root
        / "optimisation"
        / "multi_gameweek"
        / _safe_segment(category, label="category")
        / _safe_segment(request_id, label="request ID")
    )
    try:
        directory.resolve().relative_to(root)
    except (OSError, ValueError) as exc:
        raise OptimisationError(
            "MULTI_GAMEWEEK_ARTIFACT_INVALID",
            "artifact path escapes the configured root",
        ) from exc
    data = canonical_json_bytes(value)
    digest = sha256_bytes(data)
    path = directory / f"{digest}.json"
    _write_once(path, data, root=root)
    _write_once(
        path.with_suffix(".sha256"),
        f"{digest}  {path.name}\n".encode("ascii"),
        root=root,
    )
    return path


def persist_result(
    value: MultiGameweekOptimisationResult,
    *,
    artifact_root: Path,
) -> Path:
    return persist_model(
        value,
        artifact_root=artifact_root,
        category="results",
        request_id=value.request_id,
    )


def persist_advance(value: StateAdvanceResult, *, artifact_root: Path) -> Path:
    return persist_model(
        value,
        artifact_root=artifact_root,
        category="advances",
        request_id=value.request_id,
    )


def _verify_known_model(value: BaseModel) -> None:
    try:
        if isinstance(value, MultiGameweekOptimisationRequest):
            verify_request_hash(value)
        elif isinstance(value, MultiGameweekOptimisationResult):
            verify_result_hash(value)
        elif isinstance(value, StateAdvanceResult):
            verify_advance_hash(value)
    except ValueError as exc:
        raise OptimisationError(
            "MULTI_GAMEWEEK_ARTIFACT_INVALID",
            "artifact embedded semantic hash does not match",
        ) from exc


def load_canonical_json[T: BaseModel](path: Path, model_type: type[T]) -> T:
    try:
        raw = path.read_bytes()
        value = model_type.model_validate(json.loads(raw.decode("utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise OptimisationError(
            "MULTI_GAMEWEEK_ARTIFACT_INVALID",
            f"invalid artifact: {path}",
        ) from exc
    if canonical_json_bytes(value) != raw:
        raise OptimisationError(
            "MULTI_GAMEWEEK_ARTIFACT_INVALID",
            "artifact is not canonical JSON",
        )
    _verify_known_model(value)
    return value


def load_verified_artifact[T: BaseModel](path: Path, model_type: type[T]) -> T:
    try:
        raw = path.read_bytes()
        sidecar = path.with_suffix(".sha256").read_bytes()
    except OSError as exc:
        raise OptimisationError(
            "MULTI_GAMEWEEK_ARTIFACT_INVALID",
            "artifact or detached hash is unavailable",
        ) from exc
    digest = sha256_bytes(raw)
    if sidecar != f"{digest}  {path.name}\n".encode("ascii"):
        raise OptimisationError(
            "MULTI_GAMEWEEK_ARTIFACT_INVALID",
            "artifact detached hash does not match",
        )
    return load_canonical_json(path, model_type)
