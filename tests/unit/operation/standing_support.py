"""Owned standing-policy fixtures; never an account, approval or provider result."""

from datetime import UTC, datetime, timedelta

from dmf_pulse.dashboard.authorization import RouteBudget
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability, RightsProfileStatus
from dmf_pulse.operation.discovery import EventDiscovery
from dmf_pulse.operation.enrollment import rights_fingerprint
from dmf_pulse.operation.standing import OperatingLimits, QuotaProof, validate_policy
from tests.unit.operation.enrollment_support import wheel_case
from tests.unit.operation.test_quota import qualification

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
UNTIL = datetime(2027, 6, 1, tzinfo=UTC)


def owned_policy(tmp_path):
    _, envelope, _ = wheel_case(tmp_path)
    quota = qualification.__wrapped__().model_copy(update={"valid_until": UNTIL})
    sources = []
    for source in envelope.candidate.qualifications:
        profile = source.profile.model_copy(
            update={
                "status": RightsProfileStatus.HUMAN_APPROVED,
                "approved_purpose": "PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
                "unresolved_rights": (),
                "approved_at": NOW - timedelta(days=2),
                "checked_at": NOW - timedelta(days=2),
                "capabilities": {
                    **dict(source.profile.capabilities),
                    **{
                        c: CapabilityValue.ALLOW
                        for c in (
                            RightsCapability.AUTOMATED_ACCESS,
                            RightsCapability.TRANSIENT_PROCESSING,
                            RightsCapability.PRIVATE_INTERNAL_USE,
                            RightsCapability.DERIVED_STORAGE,
                        )
                    },
                },
            }
        )
        source = source.model_copy(update={"profile": profile})
        scope = source.scope
        if scope.provider == "FPL":
            scope = scope.model_copy(
                update={
                    "routes": (
                        RouteBudget(
                            host="fantasy.premierleague.com",
                            path="/api/bootstrap-static/",
                            maximum_calls=1,
                        ),
                        RouteBudget(
                            host="fantasy.premierleague.com",
                            path="/api/my-team/17/",
                            maximum_calls=1,
                        ),
                    )
                }
            )
        if scope.provider == "ODDS":
            scope = scope.model_copy(update={"account_ref": quota.account_ref})
            source = source.model_copy(
                update={"account_review_sha256": quota.account_review_sha256}
            )
        if scope.provider == "OPENFOOTBALL":
            scope = scope.model_copy(
                update={
                    "routes": tuple(
                        RouteBudget(
                            host="raw.githubusercontent.com",
                            path=f"/owned/pinned/{name}",
                            maximum_calls=1,
                        )
                        for name in ("LICENSE.md", "2023.json", "2024.json", "2025.json")
                    )
                }
            )
        scope = scope.model_copy(update={"profile_sha256": rights_fingerprint(source.profile)})
        sources.append(
            source.model_copy(
                update={
                    "scope": scope,
                    "operator_country": "IT",
                    "qualified_at": NOW - timedelta(days=1),
                    "valid_until": UNTIL,
                }
            )
        )
    limits = OperatingLimits(
        fpl_discovery_requests=1,
        fpl_snapshot_requests=19,
        fpl_total_requests=20,
        openfootball_requests=4,
        quota_requests_per_launch=1,
        charged_requests_per_event=1,
        reserved_credits_per_event=2,
        automatic_retries=0,
        daily_requests=1,
        daily_credits=2,
        monthly_requests=8,
        monthly_credits=16,
        safety_reserve_credits=10,
        quota_max_age_seconds=300,
        max_acquisition_seconds=300,
        max_run_seconds=900,
        credential_minimum_remaining_seconds=1200,
        credential_maximum_remaining_seconds=86400,
    )
    return validate_policy(
        {
            "schema_version": "standing-private-operation-v1",
            "policy_id": "OWNED-STANDING-001",
            "owner_ref": "owned-operator",
            "entry_id": 17,
            "season_code": "2026/27",
            "purpose": "PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
            "permitted_countries": ["IT", "GB"],
            "operator_country": "IT",
            "permission_provenance": "OWNER_ATTESTED_NOT_ISSUER_AUTHENTICATED",
            "supplier_permission_withdrawn": False,
            "owner_acceptance_sha256": "a" * 64,
            "owner_decision_ref": "OWNED-NOT-REAL-ACCEPTANCE",
            "independent_review_sha256": "b" * 64,
            "accepted_at": (NOW - timedelta(hours=1)).isoformat(),
            "valid_until": UNTIL.isoformat(),
            "implementation_sha": "c" * 40,
            "protected_numerical_sha256": "d" * 64,
            "dependency_lock_sha256": "6" * 64,
            "dependency_project_sha256": "7" * 64,
            "dependency_tree_sha256": "8" * 64,
            "python_platform_sha256": "9" * 64,
            "execution_entrypoint": "REVIEWED_STDLIB_BOOTSTRAP_ONLY",
            "ledger_id": "e" * 64,
            "odds_account_ref": quota.account_ref,
            "plan_ref": "OWNED-FREE-500",
            "plan_credit_allowance": 500,
            "account_exclusive_to_dmf": True,
            "account_review_sha256": quota.account_review_sha256,
            "quota_terms_sha256": "1" * 64,
            "calendar_anchor_at": "2026-11-01T00:00:00Z",
            "calendar_anchor_resets_at": "2026-12-01T00:00:00Z",
            "calendar_anchor_used_credits": 0,
            "calendar_anchor_evidence_sha256": "2" * 64,
            "control_metadata_retention_approved": True,
            "private_derived_forecast_retention_approved": True,
            "raw_source_retention": "DENIED_TRANSIENT_ONLY",
            "limits": limits.model_dump(mode="json"),
            "qualifications": [q.model_dump(mode="json") for q in sources],
            "quota_qualification": quota.model_dump(mode="json"),
        }
    )


def owned_quota(policy, *, now=NOW, used=0, remaining=None):
    return QuotaProof(
        source="ZERO_CREDIT_PROVIDER_RESPONSE_HEADERS",
        remaining_credits=500 - used if remaining is None else remaining,
        used_credits=used,
        last_request_cost=0,
        request_started_at=now - timedelta(seconds=6),
        received_at=now - timedelta(seconds=5),
        qualification_sha256=policy.quota_qualification.semantic_sha256,
        observation_sha256="3" * 64,
    )


def owned_event(*, now=NOW, gameweek=10):
    return EventDiscovery(
        target_gameweek=gameweek,
        deadline_at=now + timedelta(hours=2),
        history_gameweeks=tuple(range(max(1, gameweek - 12), gameweek)),
        request_started_at=now - timedelta(seconds=4),
        received_at=now - timedelta(seconds=2),
        bootstrap_sha256="4" * 64,
        request_count=1,
    )
