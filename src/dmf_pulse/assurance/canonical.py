"""Canonical JSON serialization and streaming SHA-256 utilities."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel


def _json_compatible(value: object) -> object:
    """Return a JSON-safe representation without introducing float rounding.

    ``json.loads(..., parse_float=Decimal)`` is intentionally used by several
    ingestion boundaries.  Decimal-bearing provider settings are therefore a
    normal input shape, not an exceptional one.  Render finite decimals as
    fixed-point strings: this preserves their exact value and scale without a
    binary-float round trip.  Existing JSON-native values retain their prior
    serialisation byte-for-byte.
    """

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical JSON does not allow non-finite Decimal values")
        return format(value, "f")
    if isinstance(value, BaseModel):
        return _json_compatible(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {key: _json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_compatible(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_json_compatible(item) for item in value)
    return value


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON-compatible data with stable UTF-8 bytes and no NaN values."""

    return json.dumps(
        _json_compatible(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    """Hash the canonical JSON representation of ``value``."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a file without loading it fully into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pretty_json(value: object) -> str:
    """Render stable human-readable JSON with a final newline."""

    return (
        json.dumps(
            _json_compatible(value),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
