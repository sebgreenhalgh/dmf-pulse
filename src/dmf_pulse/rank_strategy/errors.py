"""Typed fail-closed errors for Stage-15 rank strategy."""

from __future__ import annotations

from typing import Any


class RankStrategyError(ValueError):
    """Stable machine-readable Stage-15 error."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_error_object(self) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }
