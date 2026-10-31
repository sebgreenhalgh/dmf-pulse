"""Owned fixed-registry and provider-shaped fixtures; never actual source permission."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from dmf_pulse.dashboard.authorization import (
    OperatorRefreshApproval,
    QualifiedPlanQuota,
    RouteBudget,
    SourceScope,
)
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability, RightsProfile
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.models import QualifiedOperatorQuota
from dmf_pulse.ingestion.odds.private_operator import (
    PRIVATE_OPERATOR_GEOGRAPHY,
    PRIVATE_OPERATOR_PROFILE_ID,
)
from dmf_pulse.operation.enrollment import (
    InstalledEnrollment,
    SourceQualification,
    rights_fingerprint,
)

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
ACCOUNT = "odds-account-owned-new-purpose"


def owned_profile(at=NOW, **changes) -> RightsProfile:
    original = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    allowed = {
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.DERIVED_STORAGE,
        RightsCapability.PRIVATE_INTERNAL_USE,
    }
    return original.model_copy(
        update={
            "rights_profile_id": PRIVATE_OPERATOR_PROFILE_ID,
            "capabilities": {
                key: CapabilityValue.ALLOW if key in allowed else CapabilityValue.DENY
                for key in RightsCapability
            },
            "account_scope": "qualified private Odds account: " + ACCOUNT,
            "approved_purpose": "PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
            "geography_scope": PRIVATE_OPERATOR_GEOGRAPHY,
            "terms_source": "https://the-odds-api.com/terms-and-conditions.html",
            "terms_version": "OWNED-TEST-NOT-REAL-TERMS",
            "human_approval_id": "OWNED-SYNTHETIC-NOT-REAL-PERMISSION",
            "approved_by": "Owned test reviewer",
            "approved_at": at - timedelta(minutes=5),
            "checked_at": at - timedelta(minutes=4),
            "unresolved_rights": (),
            "notes": "Owned synthetic fixture only; no supplier or owner decision is asserted.",
            **changes,
        }
    )


def owned_registry(at=NOW, profile=None):
    profile = owned_profile(at) if profile is None else profile
    odds_scope = SourceScope(
        provider="ODDS",
        account_ref=ACCOUNT,
        profile_id=profile.rights_profile_id,
        profile_sha256=rights_fingerprint(profile),
        source_kind="RIGHTS_QUALIFIED_PRIVATE",
        routes=(
            RouteBudget(
                host="api.the-odds-api.com", path="/v4/sports/soccer_epl/odds", maximum_calls=1
            ),
        ),
    )
    scopes = (
        SourceScope(
            provider="FPL",
            account_ref="owned-fpl",
            profile_id="owned-fpl-test-only",
            profile_sha256="a" * 64,
            source_kind="RIGHTS_QUALIFIED_PRIVATE",
            routes=(
                RouteBudget(
                    host="fantasy.premierleague.com", path="/api/bootstrap-static/", maximum_calls=1
                ),
            ),
        ),
        odds_scope,
        SourceScope(
            provider="OPENFOOTBALL",
            account_ref="owned-score",
            profile_id="owned-score-test-only",
            profile_sha256="b" * 64,
            source_kind="RIGHTS_QUALIFIED_PRIVATE",
            routes=(
                RouteBudget(
                    host="raw.githubusercontent.com", path="/owned/prior.json", maximum_calls=1
                ),
            ),
        ),
    )
    qualification = SourceQualification(
        qualification_id="owned-new-odds-qualification",
        scope=odds_scope,
        profile=profile,
        purpose="PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
        permission_basis="SUPPLIER_WRITTEN_PERMISSION",
        permission_evidence_sha256="e" * 64,
        account_review_sha256="d" * 64,
        independent_review_sha256="f" * 64,
        decision_ref="OWNED-SYNTHETIC-NOT-REAL-PERMISSION",
        operator_country="IT",
        qualified_at=at - timedelta(minutes=3),
        valid_until=at + timedelta(days=1),
        control_metadata_retention_approved=True,
    )
    plan = QualifiedPlanQuota(
        account_ref=ACCOUNT,
        plan_ref="owned-plan",
        evidence_sha256="c" * 64,
        terms_evidence_sha256="e" * 64,
        monthly_plan_credits=500,
        allocated_monthly_credits=2,
        remaining_credits=500,
        observed_at=at,
        period_started_at=at - timedelta(days=1),
        resets_at=at + timedelta(days=29),
    )
    approval = OperatorRefreshApproval(
        authorization_id="OWNED-NEW-PURPOSE-TEST-ONLY",
        classification="PRIVATE_CURRENT",
        approval_evidence_sha256="1" * 64,
        implementation_sha="2" * 40,
        review_sha256="3" * 64,
        operator_ref="owned-test-operator",
        purpose="PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
        season_code="2026/27",
        horizons=(1, 3),
        source_scopes=scopes,
        plan_quota=plan,
        ledger_id="9" * 64,
        ledger_backend="POSTGRES",
        status="APPROVED_REVIEWED",
        usage="ONE_SHOT",
        approved_at=at - timedelta(minutes=2),
        not_before=at - timedelta(minutes=1),
        expires_at=at + timedelta(days=1),
        qualified_deadline_at=at + timedelta(days=2),
        quota_max_age_seconds=300,
        max_acquisition_seconds=30,
        max_run_seconds=900,
        daily_request_limit=1,
        monthly_request_limit=1,
        daily_credit_limit=2,
        monthly_credit_limit=2,
        safety_reserve_credits=0,
        control_metadata_retention_approved=True,
    )
    quota = QualifiedOperatorQuota(remaining=500, observed_at=at, evidence_sha256="c" * 64)
    return (
        InstalledEnrollment(approvals=(approval,), qualifications=(qualification,)),
        profile,
        quota,
    )


def owned_body(repository_root):
    """The existing one-command six-club synthetic market family in provider JSON form."""
    template = json.loads((repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes())[
        0
    ]
    events = []
    for offset in (0, 7):
        for index, (home, away) in enumerate(((1, 2), (3, 4), (5, 6))):
            event = deepcopy(template)
            old_home, old_away = event["home_team"], event["away_team"]
            home_name, away_name = f"One Command Club {home}", f"One Command Club {away}"
            event.update(
                id=f"owned-new-purpose-event-{offset}-{index}",
                commence_time=(
                    datetime(2026, 9, 5, 14, tzinfo=UTC) + timedelta(days=offset, hours=index)
                )
                .isoformat()
                .replace("+00:00", "Z"),
                home_team=home_name,
                away_team=away_name,
            )
            for book in event["bookmakers"]:
                book["last_update"] = "2026-09-01T11:55:00Z"
                for market in book["markets"]:
                    market["last_update"] = "2026-09-01T11:55:00Z"
                    if market["key"] == "h2h":
                        for outcome in market["outcomes"]:
                            if outcome["name"] == old_home:
                                outcome["name"] = home_name
                            elif outcome["name"] == old_away:
                                outcome["name"] = away_name
            events.append(event)
    return json.dumps(events, separators=(",", ":")).encode()
