"""Fixed operator actions; never include provider inputs, paths or secrets."""

from dmf_pulse.operation.campaign_failures import DIAGNOSTIC_FAILURE_ACTIONS

OPERATOR_FAILURE_ACTIONS = {
    "LOCAL_DASHBOARD_INSTANCE_UNVERIFIED": "The local port belongs to an unverified listener. No page or refresh was opened. Inspect or close that process before launching Seb's Desk; it is never terminated automatically.",
    "ANALYSIS_STORAGE_UNAVAILABLE_OR_INVALID": "The private analysis warehouse could not be authenticated or opened. Existing files were preserved and no refresh was admitted. Inspect its read-only schema/status or restore an authenticated backup before refreshing.",
    **DIAGNOSTIC_FAILURE_ACTIONS,
    "STANDING_OWNER_ACCEPTANCE_REQUIRED": "Complete the one-time standing policy installation before starting live operation.",
    "STANDING_PERMISSION_REVIEW_EXPIRED": "The accepted season or permission review has ended. Review the changed scope before further acquisition.",
    "ORIGINAL_SSPI_CONTROL_RECOVERY_FAILED": "Run the installed launcher as the original Windows owner and restore the original control installation. No replacement ledger is permitted.",
    "STANDING_CONTROL_MIGRATION_REQUIRED": "Install the independently reviewed additive control migration; retain the original ledger and history.",
    "STANDING_CONTROL_UNAVAILABLE_OR_INVALID": "Restore access to the original control database and audit its retained history before acquiring data.",
    "ANOTHER_OPERATOR_LAUNCH_IS_RUNNING": "Use the existing dashboard. If its process stopped, wait for the bounded launch lease to expire.",
    "QUOTA_EVIDENCE_OR_LEDGER_CONTRADICTION": "Quota evidence is stale, inconsistent or an earlier paid attempt is unresolved. Audit actual provider usage against the original ledger; no chargeable retry is allowed.",
    "EXCLUSIVE_ACCOUNT_USAGE_CONTRADICTION": "Actual account usage contradicts exclusive DMF Pulse use or the verified period. Resolve the account and ledger discrepancy before any paid acquisition.",
    "QUOTA_BELOW_SAFETY_RESERVE": "Available credits cannot cover the two-credit reservation plus the accepted safety reserve. Wait for a verified reset or review a changed budget.",
    "QUOTA_CHECK_CROSSED_MONTHLY_RESET": "The free quota check crossed the verified monthly boundary. Start a new manual launch after the reset; no paid request was admitted.",
    "CHARGED_QUOTA_HEADERS_CONTRADICT_LEDGER": "The actual charged response contradicts expected usage. Its receipt is retained; audit the account before another paid acquisition.",
    "GAMEWEEK_ACQUISITION_ALREADY_RECORDED": "This Gameweek already has a durable acquisition record. Review its saved as-of result; another paid request is blocked.",
    "GAMEWEEK_ALREADY_ATTEMPTED_NO_COMPLETED_PUBLICATION": "This Gameweek has an incomplete retained attempt. Audit its original request and charge records; automatic or duplicate paid acquisition is blocked.",
    "STANDING_REQUEST_BUDGET_EXHAUSTED": "The accepted daily or monthly run budget is exhausted. Wait for its next period; repeated launch cannot expand the budget.",
    "STANDING_EVENT_OR_QUOTA_STALE": "Official deadline or quota evidence no longer admits a complete run. No paid acquisition was admitted; start again only when fresh evidence can satisfy the standing scope.",
    "QUOTA_HEADERS_MISSING_OR_INVALID": "The provider did not supply complete valid quota headers. No chargeable acquisition was admitted.",
    "QUOTA_HEADERS_INVALID": "The provider quota headers are missing, duplicated or invalid. Further paid acquisition is blocked; retain and audit the original attempt.",
    "QUOTA_HEADERS_INCONSISTENT": "The provider quota counters disagree. Retain the original attempt and audit actual account consumption before any paid acquisition.",
    "CHARGED_QUOTA_RESPONSE_INVALID": "The charged response could not supply a valid quota receipt. Retain its attempt and audit actual consumption before any paid acquisition.",
    "QUOTA_LOOKUP_FAILED": "The zero-credit account check failed. Check provider availability and start a new manual launch; there are no automatic retries.",
}


def operator_action(code: str) -> str:
    return OPERATOR_FAILURE_ACTIONS.get(
        code,
        "This launch is blocked. Inspect the fixed error code and retained control receipt, correct the source or installation issue, then start manually within the accepted scope. No automatic provider retry will occur.",
    )
