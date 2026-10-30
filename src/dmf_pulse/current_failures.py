"""Fixed operator diagnostics shared by current worker, runtime and console.

These constants disclose reasons; they grant no authority and change no budgets.
"""

CURRENT_FAILURE_ACTIONS = {
    "FPL_SUPPLIER_PERMISSION_REQUIRED": "Qualify supplier permission or an applicable exception for the exact FPL routes; owner risk acceptance is insufficient.",
    "NEW_ODDS_PURPOSE_QUALIFICATION_REQUIRED": "Review current account evidence and approve the new Odds purpose; the consumed historical profile cannot authorize this pilot.",
    "OPENFOOTBALL_SCOPE_QUALIFICATION_REQUIRED": "Qualify the exact pinned OpenFootball source scope in the reviewed enrollment.",
    "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED": "Enroll a reviewed refresh approval; run dmf operation status.",
    "PRODUCTION_APPROVAL_NOT_ENROLLED": "Install the reviewed enrollment wheel; run dmf operation status.",
    "CREDENTIAL_UNAVAILABLE": "Configure the required credentials with dmf credentials; check dmf credentials status.",
    "CREDENTIAL_NOT_CONFIGURED": "Configure the required credentials with dmf credentials; check dmf credentials status.",
    "CREDENTIAL_EXPIRED": "Supply a freshly issued replacement locally with dmf credentials set-fpl-token --replace --fresh-issued --expires-at <actual-expiry>.",
    "CREDENTIAL_CORRUPT": "Explicitly replace the invalid entry through dmf credentials.",
    "CREDENTIAL_BACKEND_UNAVAILABLE": "Use the correct Windows user session and check Windows Credential Manager.",
    "FPL_AUTH_REQUIRED": "Obtain an authorized current FPL token and replace it through dmf credentials.",
    "AUTHORIZATION_REVOKED": "Obtain a new reviewed approval; this approval was revoked.",
    "AUTHORIZATION_EXPIRED": "Obtain a new reviewed approval and current official deadline evidence.",
    "REFRESH_GRANT_EXPIRED": "Obtain a new reviewed approval and current official deadline evidence.",
    "ACQUISITION_CUTOFF_PASSED": "The acquisition window closed; obtain a new reviewed scope.",
    "ONE_SHOT_CONSUMED": "This attempt is spent; a fresh explicit authorization is required.",
    "QUOTA_EXHAUSTED": "Qualify remaining account credits and obtain an approved budget before retrying.",
    "DAILY_BUDGET_EXHAUSTED": "The approved daily request budget is spent.",
    "MONTHLY_BUDGET_EXHAUSTED": "The approved monthly credit budget is spent.",
    "SOURCE_REQUEST_BUDGET_EXHAUSTED": "The approved source attempt budget is spent.",
    "USAGE_LEDGER_UNAVAILABLE": "Recover the existing canonical control ledger with dmf operation recover-control.",
    "USAGE_LEDGER_IDENTITY_MISMATCH": "Recover the expected canonical ledger; do not initialize a replacement.",
    "IMPLEMENTATION_IDENTITY_CHANGED": "Install the exact reviewed wheel and its matching enrollment.",
    "AUTHORIZATION_SCOPE_MISMATCH": "Use the exact approved manager and source scope.",
    "AUTHORIZATION_HORIZON_NOT_APPROVED": "Use an approved one- or three-GW horizon.",
    "AUTHORIZATION_DEADLINE_SCOPE_MISMATCH": "Qualify the exact official deadline in the installed approval.",
    "RUN_TIMEOUT": "The worker timed out; inspect control usage before any authorized retry.",
    "QUALIFIED_QUOTA_EVIDENCE_STALE": "Qualify fresh dated remaining-credit evidence; no live quota probe is authorized.",
    "AUTHORIZATION_DEADLINE_INVALID": "Replace invalid or expired official deadline evidence in a reviewed approval.",
    "USAGE_LEDGER_SCHEMA_NOT_READY": "Install and run the accepted canonical control migration before recovery.",
    "SOURCE_PROFILE_CHANGED": "Review the changed provider terms/profile and enroll its exact current hash.",
    "OFFICIAL_DEADLINE_SCOPE_MISMATCH": "Use the exact target Gameweek and qualified official deadline.",
    "ACQUISITION_CLOSED": "The acquisition phase is closed; use a fresh reviewed attempt if needed.",
    "ACQUISITION_WINDOW_EXCEEDED": "Reduce acquisition to the reviewed time window or obtain a new approval.",
    "AUTHORIZATION_CLOCK_INVALID": "Correct the local UTC clock before retrying an authorized operation.",
    "AUTHORIZATION_CLOCK_REGRESSED": "Correct the local UTC clock and recover the existing control ledger.",
    "CONTROL_DATABASE_REFERENCE_INVALID": "Configure the accepted private control database reference.",
    "MANAGER_SCOPE_INVALID": "Use the exact manager entry approved for this refresh.",
    "OPERATOR_CONTROL_CONTEXT_REQUIRED": "Complete canonical control setup and reviewed enrollment with dmf operation.",
    "OWNED_SOURCE_INJECTION_REQUIRED": "Use owned injected sources for this synthetic acceptance run.",
    "PRIVATE_CONTROL_DATABASE_REQUIRED": "Use the canonical private control database for a real refresh.",
    "PRODUCTION_CONTROL_STORE_NOT_ACCEPTED": "Use the accepted PostgreSQL control ledger and installed enrollment.",
    "REFRESH_GRANT_ALREADY_CLAIMED": "This grant was already claimed; audit usage before a fresh authorized attempt.",
    "REFRESH_GRANT_INVALID": "Recover the canonical ledger and exact reviewed enrollment; do not edit a grant.",
    "REFRESH_GRANT_NOT_CLAIMED": "Launch through the enrolled worker; a copied grant cannot authorize acquisition.",
    "SOURCE_CLASSIFICATION_MISMATCH": "Keep real and owned synthetic source enrollments separate.",
    "SOURCE_PROFILE_NOT_AVAILABLE": "Install the exact reviewed provider profile before refresh.",
    "SOURCE_ROUTE_NOT_AUTHORIZED": "Use only the source routes in the installed approval.",
    "SOURCE_SCOPE_INVALID": "Qualify the exact source scope and purpose before enrollment.",
    "TRUSTED_APPROVAL_REGISTRY_INVALID": "Reinstall the reviewed wheel; arbitrary approval JSON is not accepted.",
    "USAGE_LEDGER_ACCOUNT_MISMATCH": "Recover the existing ledger for the exact approved quota account.",
    "USAGE_LEDGER_BACKEND_INVALID": "Use the canonical PostgreSQL ledger backend for private current refresh.",
    "USAGE_LEDGER_CAPACITY_REACHED": "Review and maintain the existing ledger without resetting spent usage.",
    "USAGE_LEDGER_CONFIGURATION_INVALID": "Correct the canonical control database configuration.",
    "USAGE_LEDGER_IDENTITY_INVALID": "Recover the expected canonical ledger identity; do not invent a replacement.",
    "USAGE_LEDGER_INITIALIZATION_FAILED": "Inspect canonical control initialization before repeating explicit setup.",
    "USAGE_LEDGER_INVALID": "Recover and audit the existing ledger; do not reset its usage history.",
    "USAGE_LEDGER_REQUIRED": "Complete explicit canonical control setup with dmf operation.",
    "USAGE_LEDGER_TRANSACTION_REQUIRED": "Use the accepted transactional control database adapter.",
    "WORKER_CLEANUP_FAILED": "Close the session and resolve worker cleanup before any new refresh.",
    "WORKER_RESULT_BINDING_INVALID": "Discard this result and inspect the exact installed worker/enrollment identity.",
}

CURRENT_FAILURE_ACTIONS.update(
    {
        "CREDENTIAL_INVALID": "Replace the invalid credential explicitly through dmf credentials.",
        "CREDENTIAL_BACKEND_UNSUPPORTED": "Use Windows native setup or the explicit supported session credential mechanism.",
        "DECISION_DEADLINE_PASSED": "The official deadline passed; this recommendation cannot be published.",
        "MANAGER_OR_FIXTURE_MAPPING_INVALID": "Qualify exact manager, player and fixture identity mappings.",
        "SOURCE_NOT_AVAILABLE": "The approved source was unavailable; inspect attempt usage before an authorized retry.",
        "SOURCE_AUTHENTICATION_REJECTED": "Replace the required credential through secure setup and verify the approved source scope.",
        "SOURCE_AUTHENTICATION_OR_REQUEST_REJECTED": "Verify the approved route and credential without exposing source responses.",
        "SOURCE_RESPONSE_INVALID": "The source response failed its contract; inspect sanitized evidence before any authorized retry.",
        "CURRENT_SOURCE_OR_RUN_BLOCKED": "Inspect dmf operation status and sanitized control evidence before a new authorized attempt.",
        "HTTP_429": "The provider rate limited this request; respect retry guidance and audit spent usage before any authorized retry. Remaining credits are unproven.",
    }
)

CURRENT_FAILURE_CODES = frozenset(CURRENT_FAILURE_ACTIONS)
CREDENTIAL_FAILURE_CODES = frozenset(
    code for code in CURRENT_FAILURE_CODES if code.startswith("CREDENTIAL_")
)
EXPIRED_FAILURE_CODES = frozenset(
    {
        "DECISION_DEADLINE_PASSED",
        "AUTHORIZATION_EXPIRED",
        "REFRESH_GRANT_EXPIRED",
        "ACQUISITION_CUTOFF_PASSED",
        "AUTHORIZATION_DEADLINE_INVALID",
    }
)
_LEGACY_SOURCE_CATEGORIES = {
    "CREDENTIAL_MISSING": "CREDENTIAL_UNAVAILABLE",
    "MAPPING_CONFLICT": "MANAGER_OR_FIXTURE_MAPPING_INVALID",
    "SOURCE_UNAVAILABLE": "SOURCE_NOT_AVAILABLE",
    "HTTP_5XX": "SOURCE_NOT_AVAILABLE",
    "CONNECT_TIMEOUT": "SOURCE_NOT_AVAILABLE",
    "READ_TIMEOUT": "SOURCE_NOT_AVAILABLE",
    "TOTAL_TIMEOUT": "SOURCE_NOT_AVAILABLE",
    "HTTP_4XX": "SOURCE_AUTHENTICATION_OR_REQUEST_REJECTED",
    "CONTENT_TYPE_INVALID": "SOURCE_RESPONSE_INVALID",
    "SCHEMA_INVALID": "SOURCE_RESPONSE_INVALID",
    "PAYLOAD_TOO_LARGE": "SOURCE_RESPONSE_INVALID",
    "POST_CUTOFF": "ACQUISITION_CUTOFF_PASSED",
}


def safe_current_failure_code(code: object) -> str:
    """Emit only fixed, recognized diagnostics, never raw error text or payloads."""
    if type(code) is not str:
        return "CURRENT_SOURCE_OR_RUN_BLOCKED"
    value = _LEGACY_SOURCE_CATEGORIES.get(code, code)
    return value if value in CURRENT_FAILURE_CODES else "CURRENT_SOURCE_OR_RUN_BLOCKED"
