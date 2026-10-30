"""Read-only preview shares the actual reservation policy; no providers or secrets."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard import authorization as auth
from dmf_pulse.dashboard.authorization import (
    AuthorizationError,
    DurableUsageLedger,
    OperatorRefreshApproval,
    QualifiedPlanQuota,
    RefreshAuthorizer,
    RefreshRequest,
    RouteBudget,
    SourceScope,
)
from dmf_pulse.dashboard.postgres_authorization import PostgresUsageLedger

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)


@pytest.fixture
def case(tmp_path):
    ledger = DurableUsageLedger.create(tmp_path / "owned-usage")
    scopes = tuple(
        SourceScope(
            provider=provider,
            account_ref="owned-account",
            profile_id=f"owned-{provider}",
            profile_sha256="1" * 64,
            source_kind="REPOSITORY_OWNED_SYNTHETIC",
            routes=(RouteBudget(host=host, path=path, maximum_calls=1),),
        )
        for provider, host, path in (
            ("FPL", "fantasy.premierleague.com", "/api/bootstrap-static/"),
            ("ODDS", "api.the-odds-api.com", "/v4/sports/soccer_epl/odds"),
            ("OPENFOOTBALL", "raw.githubusercontent.com", "/owned/pinned/prior.json"),
        )
    )
    approval = OperatorRefreshApproval(
        authorization_id="owned-preview",
        classification="OWNED_SYNTHETIC",
        approval_evidence_sha256="2" * 64,
        implementation_sha="3" * 40,
        review_sha256="4" * 64,
        operator_ref="owned-operator",
        purpose="PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
        season_code="2026/27",
        horizons=(1, 3),
        source_scopes=scopes,
        plan_quota=QualifiedPlanQuota(
            account_ref="owned-account",
            plan_ref="owned-plan",
            evidence_sha256="5" * 64,
            terms_evidence_sha256="6" * 64,
            monthly_plan_credits=20,
            allocated_monthly_credits=20,
            remaining_credits=20,
            observed_at=NOW,
            period_started_at=NOW - timedelta(days=1),
            resets_at=NOW + timedelta(days=29),
        ),
        ledger_id=ledger.ledger_id,
        status="APPROVED_REVIEWED",
        usage="MANUAL_RECURRING",
        approved_at=NOW - timedelta(hours=1),
        not_before=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(days=2),
        quota_max_age_seconds=300,
        max_acquisition_seconds=30,
        max_run_seconds=900,
        daily_request_limit=3,
        daily_credit_limit=6,
        monthly_request_limit=10,
        monthly_credit_limit=20,
        safety_reserve_credits=0,
        control_metadata_retention_approved=True,
    )
    request = RefreshRequest(
        **{
            name: getattr(approval, name)
            for name in (
                "authorization_id",
                "implementation_sha",
                "review_sha256",
                "operator_ref",
                "purpose",
                "season_code",
                "mode",
                "source_scopes",
            )
        },
        horizon=1,
        information_cutoff=NOW + timedelta(seconds=30),
        deadline_at=NOW + timedelta(hours=1),
    )
    return ledger, approval, request


def issuer(ledger, approval, now=NOW):
    return RefreshAuthorizer.for_owned_sources(approval, ledger, clock=lambda: now)


def test_preview_does_not_spend_or_mint_and_actual_refresh_spends_once(case):
    ledger, approval, request = case
    before = {path.name: path.read_bytes() for path in ledger.path.iterdir()}
    authorizer = issuer(ledger, approval)
    first = authorizer.preflight(request)
    assert authorizer.preflight(request) == first
    assert first.ledger.audit.event_count == 0
    assert first.ledger.budget.daily_requests_available == 3
    assert {path.name: path.read_bytes() for path in ledger.path.iterdir()} == before
    grant = authorizer.authorize(request)
    audit = ledger.audit()
    assert audit.event_count == audit.reservation_count == 1
    assert (audit.claim_count, audit.check_count, audit.attempt_count) == (0, 0, 0)
    assert grant.reserved_odds_credits == 2
    next_preview = authorizer.preflight(request)
    assert next_preview.ledger.budget.daily_requests_available == 2
    assert next_preview.ledger.budget.qualified_credits_available == 18
    assert ledger.audit() == audit


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"usage": "ONE_SHOT"}, "ONE_SHOT_CONSUMED"),
        ({"daily_request_limit": 1}, "DAILY_BUDGET_EXHAUSTED"),
        ({"daily_credit_limit": 2}, "DAILY_BUDGET_EXHAUSTED"),
        ({"safety_reserve_credits": 18}, "QUOTA_EXHAUSTED"),
    ],
)
def test_preview_and_reserve_have_same_exhaustion_policy(case, changes, expected):
    ledger, approval, request = case
    approval = approval.model_copy(update=changes)
    authorizer = issuer(ledger, approval)
    authorizer.authorize(request)
    before = ledger.audit()
    for action in (authorizer.preflight, authorizer.authorize):
        with pytest.raises(AuthorizationError, match=expected):
            action(request)
        assert ledger.audit() == before


def test_new_approval_id_does_not_reset_canonical_account_budget(case):
    ledger, approval, request = case
    limited = approval.model_copy(update={"daily_request_limit": 1})
    issuer(ledger, limited).authorize(request)
    new = limited.model_copy(update={"authorization_id": "new-owned-id"})
    changed_request = request.model_copy(update={"authorization_id": new.authorization_id})
    with pytest.raises(AuthorizationError, match="DAILY_BUDGET_EXHAUSTED"):
        issuer(ledger, new).preflight(changed_request)
    assert ledger.audit().reservation_count == 1


def test_utc_day_rollover_retains_monthly_spend(case):
    ledger, approval, request = case
    limited = approval.model_copy(
        update={
            "daily_request_limit": 1,
            "daily_credit_limit": 2,
            "monthly_request_limit": 1,
            "monthly_credit_limit": 2,
        }
    )
    issuer(ledger, limited).authorize(request)
    later = NOW + timedelta(days=1)
    new = limited.model_copy(
        update={"plan_quota": limited.plan_quota.model_copy(update={"observed_at": later})}
    )
    later_request = request.model_copy(
        update={"information_cutoff": later, "deadline_at": later + timedelta(hours=1)}
    )
    with pytest.raises(AuthorizationError, match="MONTHLY_BUDGET_EXHAUSTED"):
        issuer(ledger, new, later).preflight(later_request)
    assert ledger.audit().reservation_count == 1


def test_naive_preview_clock_denies_before_transaction(case):
    ledger, approval, request = case
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_CLOCK_INVALID"):
        ledger.preflight(approval, request, now=NOW.replace(tzinfo=None))
    assert ledger.audit().event_count == 0


def test_preview_clock_regression_denies_without_append(case):
    ledger, approval, request = case
    issuer(ledger, approval).authorize(request)
    # Scope is valid at this earlier time but canonical control history is newer.
    earlier = NOW - timedelta(seconds=1)
    backdated = approval.model_copy(
        update={"plan_quota": approval.plan_quota.model_copy(update={"observed_at": earlier})}
    )
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_CLOCK_REGRESSED"):
        issuer(ledger, backdated, earlier).preflight(
            request.model_copy(update={"information_cutoff": NOW})
        )
    assert ledger.audit().event_count == 1


def test_unknown_resealed_event_kind_is_not_an_audited_control_event(case):
    ledger, approval, request = case
    issuer(ledger, approval).authorize(request)
    path = ledger.path / "0000000000.json"
    value = json.loads(path.read_bytes())
    value["kind"] = "FORECAST"
    value["sha256"] = canonical_sha256(
        {key: item for key, item in value.items() if key != "sha256"}
    )
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(AuthorizationError, match="USAGE_LEDGER_INVALID"):
        ledger.audit()


@pytest.mark.parametrize(
    "selector,expected",
    [
        ("SYNTHETIC_TEST_DATABASE", "PRIVATE_CONTROL_DATABASE_REQUIRED"),
        ("OPERATOR_CONTROL_DATABASE", "PRODUCTION_APPROVAL_NOT_ENROLLED"),
    ],
)
def test_forged_private_preview_denies_before_any_database(case, selector, expected):
    _, approval, request = case
    scopes = tuple(
        row.model_copy(update={"source_kind": "RIGHTS_QUALIFIED_PRIVATE"})
        for row in approval.source_scopes
    )
    private = approval.model_copy(
        update={
            "classification": "PRIVATE_CURRENT",
            "ledger_backend": "POSTGRES",
            "qualified_deadline_at": request.deadline_at,
            "source_scopes": scopes,
        }
    )
    private_request = request.model_copy(update={"source_scopes": scopes})
    calls = []

    def forbidden():
        calls.append(True)
        raise AssertionError("unapproved preview reached a connection")

    ledger = PostgresUsageLedger(
        forbidden, private.ledger_id, account_ref="owned-account", database_ref=selector
    )
    with pytest.raises(AuthorizationError, match=expected):
        ledger.preflight(private, private_request, now=NOW)
    assert calls == []


def test_empty_fixed_registry_denies_preview_before_ledger_or_credentials(case, monkeypatch):
    ledger, _, request = case
    monkeypatch.setattr(auth, "production_approvals", lambda: ())
    with pytest.raises(AuthorizationError, match="RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED"):
        RefreshAuthorizer(ledger).preflight(request)
    assert ledger.audit().event_count == 0
