"""Canonical immutable evaluation artifacts and semantic hashes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from dmf_pulse.evaluation.errors import EvaluationError

_SEMANTIC_HASH_FIELDS = {
    "BenchmarkProjection": "projection_sha256",
    "CalibrationArtifact": "artifact_sha256",
    "DecisionRegret": "regret_sha256",
    "EvaluationFold": "fold_sha256",
    "EvaluationReport": "report_sha256",
    "ForecastArtifact": "forecast_sha256",
    "InformationBundle": "bundle_sha256",
    "InnerFold": "fold_sha256",
    "LeakageReport": "report_sha256",
    "OutcomeLabel": "label_sha256",
    "PolicyDecisionArtifact": "decision_sha256",
    "PolicyTrajectory": "trajectory_sha256",
}
_PORTABLE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_WINDOWS_RESERVED_SEGMENTS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def canonical_json_bytes(value: BaseModel | dict[str, Any] | list[Any]) -> bytes:
    payload: object = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def semantic_sha256(value: BaseModel | dict[str, Any] | list[Any]) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def hash_without(value: BaseModel, field: str) -> str:
    if field not in type(value).model_fields:
        raise ValueError(f"unknown semantic hash field: {field}")
    payload = value.model_dump(mode="json")
    payload[field] = None
    return semantic_sha256(payload)


def seal[T: BaseModel](value: T, field: str) -> T:
    validated = type(value).model_validate(value.model_dump(mode="python"))
    return validated.model_copy(update={field: hash_without(validated, field)})


def verify_sealed(value: BaseModel, field: str) -> None:
    embedded = getattr(value, field)
    actual = hash_without(value, field)
    if embedded != actual:
        raise EvaluationError(
            "EVALUATION_SEMANTIC_HASH_MISMATCH",
            f"{type(value).__name__}.{field} does not match its semantic payload",
        )


def _verify_declared_semantic_hash(value: BaseModel, field: str | None = None) -> None:
    declared = field or _SEMANTIC_HASH_FIELDS.get(type(value).__name__)
    if declared is not None:
        verify_sealed(value, declared)


def _safe_segment(value: str) -> str:
    if (
        _PORTABLE_SEGMENT.fullmatch(value) is None
        or value.endswith(".")
        or value.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED_SEGMENTS
    ):
        raise EvaluationError(
            "EVALUATION_ARTIFACT_IDENTITY_INVALID",
            "artifact identity must be one portable path segment",
        )
    return value


def _write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise EvaluationError(
                "EVALUATION_ARTIFACT_COLLISION",
                f"immutable artifact path already contains different bytes: {path}",
            )
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".eval-", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise EvaluationError(
                    "EVALUATION_ARTIFACT_COLLISION",
                    "concurrent immutable artifact creation produced different bytes",
                ) from None
        temporary.unlink(missing_ok=True)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def persist_artifact(
    value: BaseModel,
    *,
    artifact_root: Path,
    category: str,
    identity: str,
) -> Path:
    validated = type(value).model_validate(value.model_dump(mode="python"))
    _verify_declared_semantic_hash(validated)
    root = artifact_root.resolve()
    directory = (root / "evaluation" / _safe_segment(category) / _safe_segment(identity)).resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise EvaluationError(
            "EVALUATION_ARTIFACT_PATH_ESCAPE",
            "artifact path escapes configured root",
        ) from exc
    data = canonical_json_bytes(validated)
    digest = sha256_bytes(data)
    path = directory / f"{digest}.json"
    _write_once(path, data)
    _write_once(path.with_suffix(".sha256"), f"{digest}  {path.name}\n".encode("ascii"))
    return path


def load_verified_artifact[T: BaseModel](
    path: Path,
    model_type: type[T],
    *,
    hash_field: str | None = None,
) -> T:
    try:
        data = path.read_bytes()
        sidecar_bytes = path.with_suffix(".sha256").read_bytes()
        sidecar_parts = sidecar_bytes.decode("ascii").strip().split()
        if len(sidecar_parts) != 2:
            raise IndexError("detached hash must contain digest and filename")
        sidecar = sidecar_parts[0]
        sidecar_name = sidecar_parts[1]
    except (OSError, IndexError, UnicodeError) as exc:
        raise EvaluationError(
            "EVALUATION_ARTIFACT_UNAVAILABLE",
            "artifact or detached hash is unavailable",
        ) from exc
    digest = sha256_bytes(data)
    if digest != sidecar:
        raise EvaluationError(
            "EVALUATION_ARTIFACT_HASH_MISMATCH",
            "artifact detached hash does not match",
        )
    if path.stem != digest:
        raise EvaluationError(
            "EVALUATION_ARTIFACT_CONTENT_ADDRESS_MISMATCH",
            "artifact filename is not the canonical content-addressed digest",
        )
    if sidecar_name != path.name:
        raise EvaluationError(
            "EVALUATION_ARTIFACT_SIDECAR_FILENAME_MISMATCH",
            "artifact detached hash filename does not match the artifact",
        )
    if sidecar_bytes != f"{digest}  {path.name}\n".encode("ascii"):
        raise EvaluationError(
            "EVALUATION_ARTIFACT_SIDECAR_NONCANONICAL",
            "artifact detached hash is not canonical",
        )
    try:
        value = model_type.model_validate(json.loads(data.decode("utf-8")))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise EvaluationError("EVALUATION_ARTIFACT_INVALID", "artifact payload is invalid") from exc
    if canonical_json_bytes(value) != data:
        raise EvaluationError(
            "EVALUATION_ARTIFACT_NONCANONICAL",
            "artifact is not canonical JSON",
        )
    _verify_declared_semantic_hash(value, hash_field)
    return value
