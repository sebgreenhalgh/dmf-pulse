"""Typed Stage-14 chip-domain errors."""

from __future__ import annotations

from typing import Any


class ChipError(ValueError):
    """Stable domain error used by the chip compiler and inventory engine."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_error_object(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe error payload."""

        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": dict(sorted(self.details.items())),
            }
        }
