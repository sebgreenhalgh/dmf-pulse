"""Typed Stage-11 failures."""

from __future__ import annotations

from enum import StrEnum

from dmf_pulse.optimisation.errors import OptimisationError


class MultiGameweekError(OptimisationError):
    """Base Stage-11 error."""


class InputInvalidError(MultiGameweekError):
    def __init__(self, message: str) -> None:
        super().__init__("MULTI_GAMEWEEK_INPUT_INVALID", message)


class InfeasiblePolicyError(MultiGameweekError):
    def __init__(self, message: str) -> None:
        super().__init__("MULTI_GAMEWEEK_INFEASIBLE", message, status="INFEASIBLE")


class ResourceLimitKind(StrEnum):
    """Closed identity for every Stage-11 exact-search resource envelope."""

    PER_STATE_ACTION_COMBINATION_LIMIT = "PER_STATE_ACTION_COMBINATION_LIMIT"
    STATE_EXPANSION_LIMIT = "STATE_EXPANSION_LIMIT"
    LAYER_REACHABLE_STATE_LIMIT = "LAYER_REACHABLE_STATE_LIMIT"
    CUMULATIVE_LEGAL_ACTION_LIMIT = "CUMULATIVE_LEGAL_ACTION_LIMIT"
    POLICY_GENERATION_LIMIT = "POLICY_GENERATION_LIMIT"
    PARETO_FRONTIER_LIMIT = "PARETO_FRONTIER_LIMIT"
    ROOT_SUMMARY_LIMIT = "ROOT_SUMMARY_LIMIT"
    UNKNOWN_RESOURCE_LIMIT = "UNKNOWN_RESOURCE_LIMIT"


class ResourceLimitReached(MultiGameweekError):
    def __init__(
        self,
        message: str,
        *,
        kind: ResourceLimitKind = ResourceLimitKind.UNKNOWN_RESOURCE_LIMIT,
        counters: object | None = None,
    ) -> None:
        super().__init__("MULTI_GAMEWEEK_RESOURCE_LIMIT", message, status="RESOURCE_LIMIT")
        self.kind = kind
        self.counters = counters


class CapabilityBlockedError(MultiGameweekError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, status="BLOCKED")
