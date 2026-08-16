"""Typed OPT-010 failures and stable exit-code mapping."""

from __future__ import annotations


class OptimisationError(Exception):
    def __init__(self, code: str, message: str, *, status: str = "BLOCKED") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class ResourceLimitError(OptimisationError):
    def __init__(self, message: str, *, solver_status: object | None = None) -> None:
        super().__init__("ONE_GAMEWEEK_RESOURCE_LIMIT", message, status="RESOURCE_LIMIT")
        self.solver_status = solver_status


class InfeasibleError(OptimisationError):
    def __init__(self, message: str) -> None:
        super().__init__("ONE_GAMEWEEK_INFEASIBLE", message, status="INFEASIBLE")
