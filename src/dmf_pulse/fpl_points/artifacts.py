"""Canonical, immutable JSON artifacts with detached SHA-256 verification."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from dmf_pulse.fpl_points.errors import FplPointsError


def canonical_json_bytes(value: BaseModel | dict[str, Any]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
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


def semantic_sha256(value: BaseModel | dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def embedded_semantic_sha256(value: BaseModel) -> str | None:
    """Return the embedded semantic digest convention when the model exposes it.

    The detached artifact digest covers the serialized file including ``result_sha256``. The
    embedded digest covers the semantic payload with that self-referential field set to null.
    """

    if "result_sha256" not in type(value).model_fields:
        return None
    embedded = getattr(value, "result_sha256", None)
    if embedded is None:
        return None
    payload = value.model_dump(mode="json")
    payload["result_sha256"] = None
    return sha256_bytes(canonical_json_bytes(payload))


def verify_embedded_semantic_hash(value: BaseModel) -> None:
    if "result_sha256" not in type(value).model_fields:
        return
    embedded = getattr(value, "result_sha256", None)
    if embedded is None:
        return
    actual = embedded_semantic_sha256(value)
    if actual != embedded:
        raise FplPointsError(
            "ARTIFACT_EMBEDDED_HASH_MISMATCH",
            "artifact semantic payload does not match its embedded result hash",
        )


def _write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise FplPointsError(
                "ARTIFACT_COLLISION", f"immutable artifact path already differs: {path}"
            )
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".pts-", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise FplPointsError(
                    "ARTIFACT_COLLISION", f"artifact was concurrently created differently: {path}"
                ) from None
        temporary.unlink(missing_ok=True)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def persist_model_artifact(
    value: BaseModel,
    *,
    artifact_root: Path,
    category: str,
    identity_parts: tuple[str, ...],
) -> Path:
    data = canonical_json_bytes(value)
    digest = sha256_bytes(data)
    directory = artifact_root / "fpl_points" / category
    for part in identity_parts:
        directory /= part
    path = directory / f"{digest}.json"
    _write_once(path, data)
    _write_once(path.with_suffix(".sha256"), f"{digest}  {path.name}\n".encode("ascii"))
    return path


def load_verified_model[T: BaseModel](path: Path, model_type: type[T]) -> T:
    try:
        data = path.read_bytes()
        sidecar = path.with_suffix(".sha256").read_text(encoding="ascii").strip().split()[0]
    except (OSError, IndexError) as exc:
        raise FplPointsError(
            "ARTIFACT_UNAVAILABLE", "artifact or detached hash is unavailable"
        ) from exc
    actual = sha256_bytes(data)
    if actual != sidecar:
        raise FplPointsError("ARTIFACT_HASH_MISMATCH", "artifact detached hash does not match")
    try:
        value = model_type.model_validate(json.loads(data.decode("utf-8")))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise FplPointsError("ARTIFACT_INVALID", "artifact payload is invalid") from exc
    if canonical_json_bytes(value) != data:
        raise FplPointsError("ARTIFACT_NONCANONICAL", "artifact is not canonical JSON")
    verify_embedded_semantic_hash(value)
    return value
