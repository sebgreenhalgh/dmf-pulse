"""Pure semantic identities for the MIN-007F availability registry."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_semantic_sha256(value: object) -> str:
    """Hash one canonical JSON semantic value without runtime metadata."""

    try:
        payload = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("semantic identity must be finite, UTF-8 JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def dataset_version_semantic_sha256(value: Mapping[str, Any]) -> str:
    """Return the content identity of a dataset-version declaration."""

    return canonical_semantic_sha256(value)


def model_version_semantic_sha256(value: Mapping[str, Any]) -> str:
    """Return the content identity of a model-version declaration."""

    return canonical_semantic_sha256(value)


def prediction_input_signature_sha256(value: Mapping[str, Any]) -> str:
    """Return a stable identity for a complete, cutoff-safe prediction input."""
    return canonical_semantic_sha256(value)
