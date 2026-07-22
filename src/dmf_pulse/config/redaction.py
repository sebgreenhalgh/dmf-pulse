"""Deterministic defense-in-depth redaction for display and evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dmf_pulse.config.models import AppConfig
from dmf_pulse.config.sensitivity import looks_sensitive_string

REDACTED = "<redacted>"
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|apikey|token|secret|password|passwd|authorization|cookie|session|"
    r"credential|private[_-]?key|client[_-]?secret|dsn)(?:_ref)?$"
)


def redact_sensitive(value: object, *, key: str | None = None) -> Any:
    """Recursively redact sensitive keys/values and sort mappings deterministically."""

    if key is not None and SENSITIVE_KEY_PATTERN.search(key) is not None:
        if key.casefold().endswith("_ref") and (
            value is None or (isinstance(value, str) and not looks_sensitive_string(value))
        ):
            return value
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_sensitive(item_value, key=str(item_key))
            for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str) and looks_sensitive_string(value):
        return REDACTED
    return value


def canonical_config(config: AppConfig) -> dict[str, Any]:
    """Return deterministic, redacted, JSON-compatible configuration output."""

    raw = config.model_dump(mode="json")
    redacted = redact_sensitive(raw)
    if not isinstance(redacted, dict):
        raise TypeError("configuration serialization did not produce a mapping")
    return redacted
