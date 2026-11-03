"""Closed diagnostic code catalogue; no source text or authority is accepted."""

DIAGNOSTIC_FAILURE_ACTIONS: dict[str, str] = {}
DIAGNOSTIC_FAILURE_ACTIONS.update(
    {
        "CURRENT_MANAGER_TRANSFER_LIMIT_UNRESOLVED": "The authenticated current-team input has no finite transfer limit. Keep paid access blocked; inspect this supported-contract boundary without inventing a free-transfer count.",
        "CURRENT_MANAGER_CHIP_IDENTITY_UNSUPPORTED": "The current-team chip identity is outside the supported contract. Keep the source rejection and review the supported chip schema before another session.",
        "CURRENT_MANAGER_CHIP_STATUS_UNSUPPORTED": "The current-team chip status is outside the supported contract. Keep the source rejection and review the supported chip schema before another session.",
        "CURRENT_MANAGER_PRIVATE_RULES_STATUS_INVALID": "The private manager compiler rejected the rules status. Verify the exact existing rules authority; do not activate or infer a ruleset.",
        "CURRENT_MANAGER_RULES_AUTHORITY_INVALID": "The manager compiler rejected target-season FULL_SEASON authority. Verify the bound existing rules and capability without changing model policy.",
        "CURRENT_MANAGER_RULES_COMPILATION_FAILED": "The manager compiler could not compile the existing target rules. Inspect the owned rules boundary offline before another session.",
        "CURRENT_MANAGER_RULE_VIEWS_INCONSISTENT": "The compiled manager rule views disagree. Inspect their existing bindings offline; retain the rejection.",
        "CURRENT_MANAGER_PRICE_UNIT_UNRESOLVED": "The existing manager rule view has no usable FPL price unit. Do not infer a monetary policy value.",
        "CURRENT_MANAGER_FREE_HIT_RESTORATION_UNAVAILABLE": "Active or pending Free Hit requires restoration state that this supported manager contract does not provide. Keep the rejection; do not substitute ordinary squad state.",
        "CURRENT_MANAGER_CLOCK_NAIVE": "The manager compilation clock was not timezone-aware. Correct the operational clock without backdating source captures.",
        "CURRENT_MANAGER_CLOCK_REGRESSED": "The manager compilation clock moved backwards. Inspect operation chronology without changing captured source times.",
    }
)
DIAGNOSTIC_FAILURE_ACTIONS.update(
    dict.fromkeys(
        (
            "PRIOR_USAGE_ORIGINAL_ACCOUNT_BINDING_INVALID",
            "PRIOR_USAGE_SIGNED_IDENTITY_INVALID",
            "PRIOR_USAGE_DISTINCT_SIGNED_ROLE_REQUIRED",
            "PRIOR_USAGE_ORIGINAL_TRUST_CHANGED",
            "PRIOR_USAGE_ACTUAL_OWNER_AND_REVIEW_REQUIRED",
            "PRIOR_USAGE_EXACT_CANONICAL_FACT_REQUIRED",
            "PRIOR_USAGE_EXACT_OLD_RESERVATION_AND_EVENT_REQUIRED",
            "PRIOR_USAGE_ACTUAL_QUOTA_ROWS_REQUIRED",
            "PRIOR_USAGE_EXACT_TWO_CREDIT_OBSERVATION_REQUIRED",
            "PRIOR_USAGE_ACTUAL_FREE_RESPONSE_REQUIRED",
            "PRIOR_USAGE_EXACT_CLOSED_FAILED_SESSION_REQUIRED",
            "PRIOR_USAGE_EXACT_INSPECTED_QUOTA_CHRONOLOGY_REQUIRED",
            "PRIOR_USAGE_CANNOT_RECONCILE_A_PAID_INVOCATION",
            "PRIOR_USAGE_OVERLAPS_ACTUAL_SETTLEMENT",
            "PRIOR_USAGE_DUPLICATE_OR_INVALID_ATTRIBUTION",
            "PRIOR_USAGE_CURRENT_INSTALLED_POLICY_REQUIRED",
            "PRIOR_USAGE_IMPORT_PERIOD_CLOSED",
        ),
        "Verify the signed prior-usage attribution and its original reservation, account and period evidence; retain all spend and do not infer historical HTTP proof.",
    )
)
DIAGNOSTIC_FAILURE_ACTIONS.update(
    dict.fromkeys(
        (
            "DIAGNOSTIC_ACCEPTED_CONFIGURATION_UNRESOLVED",
            "DIAGNOSTIC_CONTROLLED_ASSEMBLY_CHRONOLOGY_INVALID",
            "DIAGNOSTIC_CONTROLLED_PROOF_REQUIRED",
            "DIAGNOSTIC_EXACT_UNSTARTED_FIXTURES_REQUIRED",
            "DIAGNOSTIC_MARKET_PROVENANCE_CLASS_MISMATCH",
            "DIAGNOSTIC_ONE_GAMEWEEK_REQUIRED",
            "DIAGNOSTIC_SNAPSHOT_CUTOFF_MISMATCH",
        ),
        "Inspect the recorded typed-input or controlled-kernel contract before another separately admitted diagnostic session. These engineering inputs cannot be published as real recommendations.",
    )
)
DIAGNOSTIC_FAILURE_ACTIONS.update(
    dict.fromkeys(
        (
            "DIAGNOSTIC_ACCEPTED_PROPOSAL_CHANGED",
            "DIAGNOSTIC_ACQUISITION_CLOSED",
            "DIAGNOSTIC_ACTUAL_HTTP_STATUS_REQUIRED",
            "DIAGNOSTIC_ACTUAL_ODDS_RESPONSE_REQUIRED",
            "DIAGNOSTIC_ACTUAL_OWNER_ACCEPTANCE_REQUIRED",
            "DIAGNOSTIC_ACTUAL_PAID_SETTLEMENT_REQUIRED",
            "DIAGNOSTIC_BOOTSTRAP_SCOPE_INVALID",
            "DIAGNOSTIC_CAMPAIGN_ALREADY_SUCCEEDED",
            "DIAGNOSTIC_CAMPAIGN_HISTORY_COLLISION",
            "DIAGNOSTIC_CANONICAL_GATE_PROOF_REQUIRED",
            "DIAGNOSTIC_CLOSED_TERMINAL_INSPECTION_REQUIRED",
            "DIAGNOSTIC_EVENT_ENVELOPE_COLLISION",
            "DIAGNOSTIC_EXACT_FPL_DISCOVERY_SNAPSHOT_REQUIRED",
            "DIAGNOSTIC_EXACT_PRIOR_PAID_IDENTITY_REQUIRED",
            "DIAGNOSTIC_EXACT_READ_ONLY_ROUTE_REQUIRED",
            "DIAGNOSTIC_EXACT_SOURCE_ROUTE_REQUIRED",
            "DIAGNOSTIC_EXECUTION_REVIEW_REQUIRED",
            "DIAGNOSTIC_FIXED_AUTHORITY_FILE_REQUIRED",
            "DIAGNOSTIC_FRESH_GW10_DISCOVERY_REQUIRED",
            "DIAGNOSTIC_IMMUTABLE_RECEIPT_COLLISION",
            "DIAGNOSTIC_INTERNAL_PIPE_REQUIRED",
            "DIAGNOSTIC_LATE_PAID_GRANT_REQUIRED",
            "DIAGNOSTIC_MODEL_CUTOFF_INVALID",
            "DIAGNOSTIC_NORMAL_AUTHORITY_BINDING_CHANGED",
            "DIAGNOSTIC_OFFICIAL_GAMEWEEK_MISMATCH",
            "DIAGNOSTIC_ORIGINAL_CONSUMPTION_PREFIX_CHANGED",
            "DIAGNOSTIC_ORIGINAL_CONTROL_BINDING_CHANGED",
            "DIAGNOSTIC_ORIGINAL_TRUST_CHANGED",
            "DIAGNOSTIC_OWNER_AND_SIGNED_AUTHORITY_REQUIRED",
            "DIAGNOSTIC_PAID_GATE_BINDING_INVALID",
            "DIAGNOSTIC_PAID_SAFETY_RESERVE_REQUIRED",
            "DIAGNOSTIC_PAID_SESSION_NOT_ACTIVE",
            "DIAGNOSTIC_PAID_SOURCE_BINDING_INVALID",
            "DIAGNOSTIC_PREVIOUS_SESSION_INSPECTION_REQUIRED",
            "DIAGNOSTIC_PRE_PAID_GATE_REQUIRED",
            "DIAGNOSTIC_PRIOR_TRANSPORT_QUIESCENCE_REQUIRED",
            "DIAGNOSTIC_PROCESS_SCOPE_ALREADY_ACTIVE",
            "DIAGNOSTIC_QUIESCENCE_REQUIRED",
            "DIAGNOSTIC_REAL_PUBLICATION_PROOF_INVALID",
            "DIAGNOSTIC_REAL_SOURCE_AND_KERNEL_BINDING_REQUIRED",
            "DIAGNOSTIC_REAL_SOURCE_VINTAGES_INVALID",
            "DIAGNOSTIC_SESSION_ALREADY_TERMINAL",
            "DIAGNOSTIC_SESSION_HISTORY_INVALID",
            "DIAGNOSTIC_SESSION_MODE_INVALID",
            "DIAGNOSTIC_SESSION_NOT_FOUND",
            "DIAGNOSTIC_SESSION_NOT_FOUND_OR_ALREADY_QUIESCENT",
            "DIAGNOSTIC_SIGNED_ROLE_BINDING_CHANGED",
            "DIAGNOSTIC_SOURCE_ROUTE_ALREADY_ATTEMPTED",
            "DIAGNOSTIC_STAGE_ALREADY_RECORDED",
            "DIAGNOSTIC_STAGE_PROOF_INVALID",
            "DIAGNOSTIC_TERMINAL_RESULT_REQUIRED",
            "DIAGNOSTIC_TRANSPORT_ADMISSION_REQUIRED",
            "DIAGNOSTIC_VERIFIED_PROCESS_SCOPE_REQUIRED",
        ),
        "Inspect this fixed diagnostic refusal and the original canonical receipt. Correct and independently review the implementation or signed binding within the accepted campaign before another separately admitted session.",
    )
)
DIAGNOSTIC_FAILURE_ACTIONS.update(
    dict.fromkeys(
        (
            "DIAGNOSTIC_ACQUISITION_WINDOW_EXPIRED",
            "DIAGNOSTIC_FRESH_CREDENTIAL_WINDOW_REQUIRED",
            "DIAGNOSTIC_PAID_CREDENTIAL_OR_WINDOW_EXPIRED",
            "DIAGNOSTIC_PAID_GATE_CHRONOLOGY_INVALID",
            "DIAGNOSTIC_PRE_PAID_WINDOW_EXPIRED",
            "DIAGNOSTIC_REAL_PUBLICATION_CHRONOLOGY_INVALID",
            "DIAGNOSTIC_SESSION_CLOSED_CHANGED_OR_EXPIRED",
            "DIAGNOSTIC_SESSION_WINDOW_EXPIRED",
            "DIAGNOSTIC_TRANSPORT_CHRONOLOGY_INVALID",
            "DIAGNOSTIC_WINDOW_EXPIRED_OR_REGRESSED",
        ),
        "The recorded diagnostic time or phase boundary does not admit this action. Retain the session and inspect its exact chronology before any separately permitted session.",
    )
)
DIAGNOSTIC_FAILURE_ACTIONS.update(
    dict.fromkeys(
        (
            "DIAGNOSTIC_ACTUAL_PAID_INVOCATION_REQUIRED",
            "DIAGNOSTIC_ACTUAL_QUOTA_COMPLETION_REQUIRED",
            "DIAGNOSTIC_CANONICAL_PRE_PAID_QUOTA_REQUIRED",
            "DIAGNOSTIC_CONTRADICTORY_RESPONSE_QUOTA",
            "DIAGNOSTIC_EXACT_QUOTA_PHASE_REQUIRED",
            "DIAGNOSTIC_EXACT_QUOTA_ROUTE_REQUIRED",
            "DIAGNOSTIC_EXACT_UNSETTLED_PRIOR_INVOCATION_REQUIRED",
            "DIAGNOSTIC_INITIAL_QUOTA_REQUIRED",
            "DIAGNOSTIC_PAID_CONSUMPTION_UNRESOLVED",
            "DIAGNOSTIC_PAID_QUOTA_CONTRADICTS_PLAN",
            "DIAGNOSTIC_PAID_QUOTA_STALE",
            "DIAGNOSTIC_QUOTA_PHASE_EXHAUSTED",
            "DIAGNOSTIC_READ_ONLY_INITIAL_RECONCILIATION_REQUIRED",
            "DIAGNOSTIC_REAL_QUOTA_RECEIPT_INVALID",
        ),
        "Inspect the retained quota/request receipt and reconcile the original account ledger before another paid session. No automatic retry or refund is authorized.",
    )
)
DIAGNOSTIC_FAILURE_ACTIONS.update(
    dict.fromkeys(
        (
            "DIAGNOSTIC_COMPLETE_ACTUAL_HTTP_RESPONSES_REQUIRED",
            "DIAGNOSTIC_PAID_SLOT_LIMIT_EXHAUSTED",
            "DIAGNOSTIC_PROVIDER_BUDGET_EXHAUSTED",
            "DIAGNOSTIC_SESSION_LIMIT_EXHAUSTED",
        ),
        "The bounded diagnostic phase or allowance has ended. Inspect this session; no automatic retry or enlargement is permitted.",
    )
)
DIAGNOSTIC_FAILURE_ACTIONS.update(
    dict.fromkeys(
        ("DIAGNOSTIC_READ_ONLY_COMPLETE",),
        "The controlled engineering run completed. It is not a genuine market forecast and made no paid reservation or request. Inspect its receipt before another separately admitted session.",
    )
)
DIAGNOSTIC_FAILURE_ACTIONS.update(
    dict.fromkeys(
        ("LOCAL_DASHBOARD_OR_DIAGNOSTIC_PROCESS_UNAVAILABLE",),
        "Recover the private loopback dashboard or local process after inspecting the canonical diagnostic receipt. No automatic provider retry is authorized.",
    )
)

DIAGNOSTIC_FAILURE_ACTIONS.update(
    dict.fromkeys(
        (
            "QUOTA_ADMISSION_DENIED",
            "QUOTA_ADMISSION_OR_CLOCK_INVALID",
            "QUOTA_ADMISSION_REQUIRED",
            "QUOTA_CONTENT_TYPE_INVALID",
            "QUOTA_COST_BOUND_INVALID",
            "QUOTA_CREDENTIAL_UNAVAILABLE",
            "QUOTA_FRESHNESS_BOUND_INVALID",
            "QUOTA_HTTP_REJECTED",
            "QUOTA_LAST_COST_LIMIT_EXCEEDED",
            "QUOTA_LOOKUP_ALREADY_ATTEMPTED",
            "QUOTA_LOOKUP_UNEXPECTED_COST",
            "QUOTA_OBSERVATION_STALE",
            "QUOTA_PROVIDER_DATE_INVALID",
            "QUOTA_PROVIDER_DATE_STALE",
            "QUOTA_REDIRECT_BLOCKED",
            "QUOTA_RESPONSE_INVALID",
            "QUOTA_SOURCE_QUALIFICATION_EXPIRED",
            "QUOTA_SOURCE_QUALIFICATION_REQUIRED",
            "QUOTA_SOURCE_UNAVAILABLE",
            "QUOTA_UNEXPECTED_LAST_COST",
        ),
        "The separate zero-credit quota phase failed its fixed credential, HTTP, header, time or qualification contract. Inspect its canonical request/response facts; no automatic retry or charged admission is authorized.",
    )
)
