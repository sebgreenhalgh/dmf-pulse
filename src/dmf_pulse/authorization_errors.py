"""Shared authorization failure type and bounded transport diagnostics.

The allowlist is a disclosure boundary, not an authorization policy. The existing
refresh authorizer and durable ledger remain the only grant decision makers.
"""

from __future__ import annotations

from typing import Literal

AuthorizationState = Literal[
    "RIGHTS_APPROVAL_REQUIRED", "SOURCE_NOT_AVAILABLE", "BLOCKED", "EXPIRED"
]


class AuthorizationError(ValueError):
    """An authorization failure with a code and presentation state."""

    def __init__(self, code: str, state: AuthorizationState = "BLOCKED") -> None:
        super().__init__(code)
        self.code = code
        self.state = state


# Failures reachable from acquisition checks and canonical ledger operations.
# Unknown codes must never be copied from a credential-bearing exception graph.
_ACQUISITION_CODES = frozenset(
    {
        "ACQUISITION_CLOSED",
        "ACQUISITION_CUTOFF_PASSED",
        "AUTHORIZATION_CLOCK_INVALID",
        "AUTHORIZATION_CLOCK_REGRESSED",
        "AUTHORIZATION_REVOKED",
        "AUTHORIZATION_EXPIRED",
        "CONTROL_DATABASE_REFERENCE_INVALID",
        "IMPLEMENTATION_IDENTITY_CHANGED",
        "PRIVATE_CONTROL_DATABASE_REQUIRED",
        "PRODUCTION_CONTROL_STORE_NOT_ACCEPTED",
        "REFRESH_GRANT_INVALID",
        "REFRESH_GRANT_EXPIRED",
        "REFRESH_GRANT_NOT_CLAIMED",
        "REFRESH_GRANT_ALREADY_CLAIMED",
        "SOURCE_REQUEST_BUDGET_EXHAUSTED",
        "SOURCE_ROUTE_NOT_AUTHORIZED",
        "USAGE_LEDGER_ACCOUNT_MISMATCH",
        "USAGE_LEDGER_CONFIGURATION_INVALID",
        "USAGE_LEDGER_IDENTITY_INVALID",
        "USAGE_LEDGER_IDENTITY_MISMATCH",
        "USAGE_LEDGER_INVALID",
        "USAGE_LEDGER_BACKEND_INVALID",
        "USAGE_LEDGER_UNAVAILABLE",
        "USAGE_LEDGER_CAPACITY_REACHED",
        "USAGE_LEDGER_SCHEMA_NOT_READY",
        "USAGE_LEDGER_TRANSACTION_REQUIRED",
    }
)


def safe_authorization_fields(error: AuthorizationError) -> tuple[str, AuthorizationState]:
    """Return only recognized constants, never the raw exception or its message."""
    code = error.code
    if type(code) is not str or code not in _ACQUISITION_CODES:
        return "AUTHORIZATION_UNAVAILABLE", "BLOCKED"
    state: AuthorizationState = (
        "EXPIRED"
        if code in {"ACQUISITION_CUTOFF_PASSED", "AUTHORIZATION_EXPIRED", "REFRESH_GRANT_EXPIRED"}
        else "BLOCKED"
    )
    return code, state
