"""Canonical rules serialization and self-hashing."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def normalize_json(value: object) -> object:
    """Normalize every JSON string/key to NFC without reordering semantic lists."""

    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical JSON mapping keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError("canonical JSON mapping keys collide after NFC normalization")
            normalized[normalized_key] = normalize_json(item)
        return normalized
    return value


def canonical_rules_bytes(value: object) -> bytes:
    """Return platform-independent canonical UTF-8 JSON bytes."""

    return json.dumps(
        normalize_json(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_rules_sha256(value: object) -> str:
    return hashlib.sha256(canonical_rules_bytes(value)).hexdigest()


def pretty_rules_json(value: object) -> str:
    return (
        json.dumps(
            normalize_json(value),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def self_hash(value: dict[str, Any]) -> str:
    """Hash an artifact excluding only its own ``ruleset_hash`` field."""

    return canonical_rules_sha256(
        {key: item for key, item in value.items() if key != "ruleset_hash"}
    )
