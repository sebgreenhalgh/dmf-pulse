"""Secret-safe typed failures for database and data-model operations."""

from __future__ import annotations


class DatabaseError(Exception):
    """A deterministic public failure that never embeds driver exception text."""

    def __init__(self, code: str, message: str, *, exit_code: int = 50) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code

    def as_error_object(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": self.message}}
