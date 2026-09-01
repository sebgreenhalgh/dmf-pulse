"""Disclosure-minimised errors for the private V1 execution boundary."""

from __future__ import annotations


class PrivateV1Error(ValueError):
    """Stable fail-closed application error without private payload fragments."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


__all__ = ["PrivateV1Error"]
