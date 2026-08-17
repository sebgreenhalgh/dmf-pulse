"""Typed Stage-12 evaluation failures."""

from __future__ import annotations


class EvaluationError(Exception):
    """A deterministic, machine-readable evaluation failure."""

    def __init__(self, code: str, message: str, *, blocking: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.blocking = blocking

    def as_error_object(self) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "blocking": self.blocking,
            }
        }


class LeakageError(EvaluationError):
    """Raised when a strict historical replay contains temporal contamination."""
