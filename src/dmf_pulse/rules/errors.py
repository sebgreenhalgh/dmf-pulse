"""Stable, non-disclosing rules-domain failures."""

from __future__ import annotations

from typing import Any


class RulesError(Exception):
    """Base rules failure with a stable machine code."""

    exit_code = 3

    def __init__(self, code: str, message: str, *, blockers: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.blockers = blockers

    def as_error_object(self) -> dict[str, Any]:
        return {
            "error": {
                "blockers": list(self.blockers),
                "code": self.code,
                "message": self.message,
            },
            "ok": False,
        }


class RulesValidationError(RulesError):
    """Source, scenario, or schema validation failed."""


class RulesActivationError(RulesError):
    """Governance prevents activation."""

    exit_code = 4


class RulesIntegrityError(RulesError):
    """An artifact hash or immutable output contract failed."""

    exit_code = 5
