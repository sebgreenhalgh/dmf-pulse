"""Typed Stage-11 failures."""

from __future__ import annotations

from dmf_pulse.optimisation.errors import OptimisationError


class MultiGameweekError(OptimisationError):
    """Base Stage-11 error."""


class InputInvalidError(MultiGameweekError):
    def __init__(self, message: str) -> None:
        super().__init__("MULTI_GAMEWEEK_INPUT_INVALID", message)


class InfeasiblePolicyError(MultiGameweekError):
    def __init__(self, message: str) -> None:
        super().__init__("MULTI_GAMEWEEK_INFEASIBLE", message, status="INFEASIBLE")


class ResourceLimitReached(MultiGameweekError):
    def __init__(self, message: str, *, counters: object | None = None) -> None:
        super().__init__("MULTI_GAMEWEEK_RESOURCE_LIMIT", message, status="RESOURCE_LIMIT")
        self.counters = counters


class CapabilityBlockedError(MultiGameweekError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, status="BLOCKED")
