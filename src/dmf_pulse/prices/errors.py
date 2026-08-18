"""Typed, machine-readable Stage-13 failures."""

from __future__ import annotations


class PriceError(Exception):
    """A deterministic Stage-13 failure safe to expose through the CLI."""

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


class PriceLeakageError(PriceError):
    """Raised when a price feature or calibration row crosses its cutoff."""
