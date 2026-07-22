"""Safe typed configuration failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ConfigIssue:
    """One sanitized configuration issue without the rejected input value."""

    location: str
    message: str
    issue_type: str

    def as_dict(self) -> dict[str, str]:
        """Return the stable machine representation."""

        return {
            "location": self.location,
            "message": self.message,
            "type": self.issue_type,
        }


class ConfigError(Exception):
    """A safe configuration failure suitable for CLI rendering."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        issues: tuple[ConfigIssue, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.issues = issues

    def as_error_object(self) -> dict[str, Any]:
        """Return deterministic JSON-ready error data."""

        return {
            "error": {
                "code": self.code,
                "issues": [issue.as_dict() for issue in self.issues],
                "message": self.message,
            },
            "ok": False,
        }
