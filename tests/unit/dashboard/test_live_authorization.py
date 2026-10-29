"""Scope, custody and restart tests; all approvals are owned synthetic only."""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    production_approvals,
)

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
WORKER = "a" * 64


def setup(tmp_path: Path, **changes):
    ledger = DurableUsageLedger.create(tmp_path / "usage")
    scopes = tuple(
        SourceScope(
            provider=provider,
            account_ref="owned_account",
            profile_id=f"synthetic_{provider.lower()}_v1",
            profile_sha256="1" * 64,
            source_kind="REPOSITORY_OWNED_SYNTHETIC",
            routes=(RouteBudget(host=host, path=path, maximum_calls=calls),),
        )
        for provider, host, path, calls in (
            ("FPL", "fantasy.premierleague.com", "/api/bootstrap-static/", 1),
            ("ODDS", "api.the-odds-api.com", "/v4/sports/soccer_epl/odds", 1),
            ("OPENFOOTBALL", "raw.githubusercontent.com", "/owned/pinned/prior.json", 1),
        )
    )
    quota = QualifiedPlanQuota(
        account_ref="owned_account",
        plan_ref="owned_plan",
        evidence_sha256="2" * 64,
        terms_evidence_sha256="3" * 64,
        monthly_plan_credits=500,
        allocated_monthly_credits=20,
        remaining_credits=20,
        observed_at=NOW,
        period_started_at=NOW - timedelta(days=1),
        resets_at=NOW + timedelta(days=29),
    )
    approval = OperatorRefreshApproval(
        authorization_id="owned_refresh_v1",
        classification="OWNED_SYNTHETIC",
        approval_evidence_sha256="4" * 64,
        implementation_sha="5" * 40,
        review_sha256="6" * 64,
        operator_ref="owned_operator",
        purpose="PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
        season_code="2026/27",
        horizons=(1, 3),
        source_scopes=scopes,
        plan_quota=quota,
        ledger_id=ledger.ledger_id,
        status="APPROVED_REVIEWED",
        usage="MANUAL_RECURRING",
        approved_at=NOW - timedelta(hours=1),
        not_before=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        quota_max_age_seconds=300,
        max_acquisition_seconds=30,
        max_run_seconds=900,
        daily_request_limit=3,
        daily_credit_limit=6,
        monthly_request_limit=10,
        monthly_credit_limit=20,
        safety_reserve_credits=0,
        control_metadata_retention_approved=True,
    ).model_copy(update=changes)
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
        horizon=3,
        information_cutoff=NOW + timedelta(seconds=30),
        deadline_at=NOW + timedelta(hours=2),
    )
    authorizer = RefreshAuthorizer.for_owned_sources(approval, ledger, clock=lambda: NOW)
    return ledger, approval, request, authorizer


def test_production_registry_has_no_runtime_enrollment(tmp_path):
    ledger, _, request, _ = setup(tmp_path)
    assert production_approvals() == ()
    for authorizer in (RefreshAuthorizer(), RefreshAuthorizer(ledger)):
        with pytest.raises(AuthorizationError) as caught:
            authorizer.authorize(request)
        assert caught.value.code == "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED"
        assert caught.value.state == "RIGHTS_APPROVAL_REQUIRED"
    assert sorted(path.name for path in ledger.path.iterdir()) == ["identity.json"]


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b"not JSON",
        b'{"schema_version":"trusted-refresh-enrollments-v1","approvals":{},"extra":1}',
        b'{"schema_version":"trusted-refresh-enrollments-v1","approvals":[],"approvals":[]}',
        b"x" * 131073,
        b"[" * 1500 + b"0" + b"]" * 1500,
    ],
    ids=["empty", "malformed", "extras", "duplicates", "oversize", "depth"],
)
def test_fixed_enrollment_resource_corruption_is_typed(monkeypatch, body):
    class Resource:
        def joinpath(self, name):
            assert name == "production_refresh_enrollments.json"
            return self

        def read_bytes(self):
            return body

    monkeypatch.setattr(auth, "files", lambda package: Resource())
    with pytest.raises(AuthorizationError, match="TRUSTED_APPROVAL_REGISTRY_INVALID"):
        production_approvals()


@pytest.mark.parametrize(
    "field,value",
    [
        ("implementation_sha", "7" * 40),
        ("review_sha256", "7" * 64),
        ("operator_ref", "other_operator"),
        ("season_code", "2025/26"),
    ],
)
def test_exact_review_code_operator_season_scope(tmp_path, field, value):
    ledger, _, request, authorizer = setup(tmp_path)
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_SCOPE_MISMATCH"):
        authorizer.authorize(request.model_copy(update={field: value}))
    assert len(list(ledger.path.iterdir())) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_ref", "other_account"),
        ("profile_id", "other_profile"),
        ("profile_sha256", "9" * 64),
    ],
)
def test_account_profile_and_route_are_exact(tmp_path, field, value):
    ledger, _, request, authorizer = setup(tmp_path)
    scopes = list(request.source_scopes)
    scopes[0] = scopes[0].model_copy(update={field: value})
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_SCOPE_MISMATCH"):
        authorizer.authorize(request.model_copy(update={"source_scopes": tuple(scopes)}))
    assert len(list(ledger.path.iterdir())) == 1


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"status": "REVOKED"}, "AUTHORIZATION_REVOKED"),
        ({"expires_at": NOW}, "AUTHORIZATION_EXPIRED"),
        ({"not_before": NOW + timedelta(seconds=1)}, "AUTHORIZATION_EXPIRED"),
        ({"horizons": (1,)}, "AUTHORIZATION_HORIZON_NOT_APPROVED"),
    ],
)
def test_approval_rejections_before_reservation(tmp_path, changes, code):
    ledger, _, request, authorizer = setup(tmp_path, **changes)
    with pytest.raises(AuthorizationError, match=code):
        authorizer.authorize(request)
    assert len(list(ledger.path.iterdir())) == 1


def test_quota_and_deadline_before_reservation(tmp_path):
    ledger, approval, request, _ = setup(tmp_path)
    cases = (
        (
            request.model_copy(update={"information_cutoff": NOW - timedelta(seconds=1)}),
            NOW,
            "DEADLINE_INVALID",
        ),
        (
            request.model_copy(update={"information_cutoff": NOW + timedelta(seconds=31)}),
            NOW,
            "ACQUISITION_WINDOW_EXCEEDED",
        ),
        (request, NOW + timedelta(minutes=6), "DEADLINE_INVALID"),
        (
            request.model_copy(update={"information_cutoff": NOW + timedelta(seconds=29)}),
            NOW - timedelta(seconds=1),
            "QUALIFIED_QUOTA_EVIDENCE_STALE",
        ),
    )
    for value, clock, code in cases:
        with pytest.raises(AuthorizationError, match=code):
            RefreshAuthorizer.for_owned_sources(
                approval, ledger, clock=lambda clock=clock: clock
            ).authorize(value)
    stale_request = request.model_copy(update={"information_cutoff": NOW + timedelta(minutes=6)})
    with pytest.raises(AuthorizationError, match="QUALIFIED_QUOTA_EVIDENCE_STALE"):
        RefreshAuthorizer.for_owned_sources(
            approval, ledger, clock=lambda: NOW + timedelta(minutes=6)
        ).authorize(stale_request)
    assert len(list(ledger.path.iterdir())) == 1


def test_private_approval_cannot_enter_owned_injection(tmp_path):
    ledger, approval, _, _ = setup(tmp_path)
    private = approval.model_copy(
        update={
            "classification": "PRIVATE_CURRENT",
            "source_scopes": tuple(
                row.model_copy(update={"source_kind": "RIGHTS_QUALIFIED_PRIVATE"})
                for row in approval.source_scopes
            ),
        }
    )
    with pytest.raises(AuthorizationError, match="OWNED_SOURCE_INJECTION_REQUIRED"):
        RefreshAuthorizer.for_owned_sources(private, ledger)


def test_library_reservation_cannot_enroll_private_approval(tmp_path):
    ledger, approval, request, authorizer = setup(tmp_path)
    owned = authorizer.authorize(request)
    scopes = tuple(
        row.model_copy(update={"source_kind": "RIGHTS_QUALIFIED_PRIVATE"})
        for row in approval.source_scopes
    )
    private = approval.model_copy(
        update={"classification": "PRIVATE_CURRENT", "source_scopes": scopes}
    )
    forged = owned.model_copy(
        update={
            "reservation_id": "e" * 64,
            "classification": "PRIVATE_CURRENT",
            "approval_sha256": canonical_sha256(private.model_dump(mode="json")),
            "request": request.model_copy(update={"source_scopes": scopes}),
        }
    )
    with pytest.raises(AuthorizationError, match="PRODUCTION_CONTROL_STORE_NOT_ACCEPTED"):
        ledger.reserve(private, forged)
    with pytest.raises(AuthorizationError, match="PRODUCTION_CONTROL_STORE_NOT_ACCEPTED"):
        ledger.claim(forged, WORKER, now=NOW)
    assert len(list(ledger.path.glob("[0-9]*.json"))) == 1


@pytest.mark.parametrize("attack", ["run_window", "acquisition_window", "scope", "quota_issuance"])
def test_direct_reservation_cannot_expand_issued_scope(tmp_path, attack):
    ledger, approval, request, authorizer = setup(tmp_path)
    grant = authorizer.authorize(request)
    if attack == "run_window":
        forged = grant.model_copy(update={"expires_at": NOW + timedelta(minutes=30)})
    elif attack == "acquisition_window":
        forged = grant.model_copy(
            update={
                "request": request.model_copy(
                    update={"information_cutoff": NOW + timedelta(minutes=5)}
                )
            }
        )
    elif attack == "scope":
        forged = grant.model_copy(
            update={"request": request.model_copy(update={"operator_ref": "different_operator"})}
        )
    else:
        forged = grant.model_copy(update={"issued_at": NOW - timedelta(seconds=1)})
    with pytest.raises(AuthorizationError):
        ledger.reserve(approval, forged)
    assert len(list(ledger.path.glob("[0-9]*.json"))) == 1


def test_one_shot_spent_before_worker_and_survives_restart(tmp_path):
    ledger, approval, request, authorizer = setup(tmp_path, usage="ONE_SHOT")
    grant = authorizer.authorize(request)
    reopened = DurableUsageLedger(ledger.path, ledger.ledger_id)
    # No worker, transport, success callback or refund is needed for consumption.
    updated_receipt = approval.model_copy(update={"approval_evidence_sha256": "8" * 64})
    with pytest.raises(AuthorizationError, match="ONE_SHOT_CONSUMED"):
        RefreshAuthorizer.for_owned_sources(updated_receipt, reopened, clock=lambda: NOW).authorize(
            request
        )
    reopened.claim(grant, WORKER, now=NOW)
    with pytest.raises(AuthorizationError, match="ALREADY_CLAIMED"):
        ledger.claim(grant, WORKER, now=NOW)


def test_child_process_claim_uses_same_durable_grant(tmp_path):
    ledger, _, request, authorizer = setup(tmp_path)
    grant = authorizer.authorize(request)
    program = """
import sys
from pathlib import Path
from dmf_pulse.dashboard.authorization import DurableUsageLedger, RefreshGrant
grant = RefreshGrant.model_validate_json(sys.stdin.read())
ledger = DurableUsageLedger(Path(sys.argv[1]), grant.ledger_id)
ledger.claim(grant, 'a' * 64, now=grant.issued_at)
print('CLAIMED')
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, str(ledger.path)],
        input=grant.model_dump_json(),
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    assert completed.stdout.strip() == "CLAIMED"
    with pytest.raises(AuthorizationError, match="ALREADY_CLAIMED"):
        DurableUsageLedger(ledger.path, ledger.ledger_id).claim(grant, WORKER, now=NOW)


def test_reservation_needs_exact_ledger_and_reinitialization_is_forbidden(tmp_path):
    ledger, approval, request, _ = setup(tmp_path)
    with pytest.raises(AuthorizationError, match="INITIALIZATION_FAILED"):
        DurableUsageLedger.create(ledger.path)
    wrong = DurableUsageLedger(tmp_path / "missing", ledger.ledger_id)
    with pytest.raises(AuthorizationError, match="USAGE_LEDGER_INVALID"):
        RefreshAuthorizer.for_owned_sources(approval, wrong, clock=lambda: NOW).authorize(request)
    other = DurableUsageLedger.create(tmp_path / "other")
    with pytest.raises(AuthorizationError, match="USAGE_LEDGER_REQUIRED"):
        RefreshAuthorizer.for_owned_sources(approval, other, clock=lambda: NOW).authorize(request)


@pytest.mark.parametrize(
    "alteration", ["unexpected_file", "truncated_record", "missing_middle", "deep_record"]
)
def test_ledger_corruption_is_never_silently_reset(tmp_path, alteration):
    ledger, _, request, authorizer = setup(tmp_path)
    grant = authorizer.authorize(request)
    ledger.claim(grant, WORKER, now=NOW)
    ledger.check(grant, WORKER, now=NOW)
    if alteration == "unexpected_file":
        (ledger.path / "unexpected.json").write_text("{}", encoding="utf-8")
    elif alteration == "truncated_record":
        (ledger.path / "0000000000.json").write_text('{"kind":', encoding="utf-8")
    elif alteration == "deep_record":
        (ledger.path / "0000000000.json").write_text(
            "[" * 1500 + "0" + "]" * 1500, encoding="utf-8"
        )
    else:
        (ledger.path / "0000000001.json").unlink()
    with pytest.raises(AuthorizationError):
        ledger.check(grant, WORKER, now=NOW)


def test_grants_expire_and_worker_identity_is_bounded(tmp_path):
    ledger, _, request, authorizer = setup(tmp_path)
    grant = authorizer.authorize(request)
    with pytest.raises(AuthorizationError, match="GRANT_INVALID"):
        ledger.claim(grant, "not-a-worker-id", now=NOW)
    with pytest.raises(AuthorizationError, match="GRANT_EXPIRED"):
        ledger.claim(grant, WORKER, now=grant.expires_at)
    with pytest.raises(AuthorizationError, match="CLOCK_INVALID"):
        ledger.claim(grant, WORKER, now=NOW.replace(tzinfo=None))


def test_grant_tampering_cannot_relabel_or_expand_worker(tmp_path):
    ledger, _, request, authorizer = setup(tmp_path)
    grant = authorizer.authorize(request)
    for modified in (
        grant.model_copy(update={"classification": "PRIVATE_CURRENT"}),
        grant.model_copy(update={"expires_at": NOW + timedelta(days=1)}),
        grant.model_copy(
            update={
                "request": request.model_copy(
                    update={"information_cutoff": NOW + timedelta(days=1)}
                )
            }
        ),
    ):
        with pytest.raises(AuthorizationError):
            ledger.claim(modified, WORKER, now=NOW)
    ledger.claim(grant, WORKER, now=NOW)
    with pytest.raises(AuthorizationError, match="NOT_CLAIMED"):
        ledger.check(grant, "b" * 64, now=NOW)


def test_every_attempt_requires_exact_claim_route_and_remaining_cap(tmp_path):
    ledger, _, request, authorizer = setup(tmp_path)
    grant = authorizer.authorize(request)
    kwargs = dict(
        provider="ODDS",
        method="GET",
        host="api.the-odds-api.com",
        path="/v4/sports/soccer_epl/odds",
        now=NOW,
    )
    with pytest.raises(AuthorizationError, match="NOT_CLAIMED"):
        ledger.attempt(grant, WORKER, **kwargs)
    ledger.claim(grant, WORKER, now=NOW)
    with pytest.raises(AuthorizationError, match="ROUTE_NOT_AUTHORIZED"):
        ledger.attempt(grant, WORKER, **{**kwargs, "path": "/v4/sports/"})
    ledger.attempt(grant, WORKER, **kwargs)
    # Delegate failure/429 occurs after this durable call and cannot undo it.
    reopened = DurableUsageLedger(ledger.path, ledger.ledger_id)
    with pytest.raises(AuthorizationError, match="SOURCE_REQUEST_BUDGET_EXHAUSTED"):
        reopened.attempt(grant, WORKER, **kwargs)
    with pytest.raises(AuthorizationError, match="ACQUISITION_CUTOFF_PASSED"):
        reopened.attempt(grant, WORKER, **{**kwargs, "now": NOW + timedelta(seconds=31)})


@pytest.mark.parametrize("scope", ["daily", "monthly", "quota"])
def test_conservative_budgets_include_unstarted_failed_refreshes(tmp_path, scope):
    ledger, approval, request, _ = setup(tmp_path)
    if scope == "daily":
        approval = approval.model_copy(update={"daily_request_limit": 1, "daily_credit_limit": 2})
        code = "DAILY_BUDGET_EXHAUSTED"
    elif scope == "monthly":
        approval = approval.model_copy(
            update={
                "daily_request_limit": 2,
                "daily_credit_limit": 4,
                "monthly_request_limit": 2,
                "monthly_credit_limit": 4,
            }
        )
        code = "MONTHLY_BUDGET_EXHAUSTED"
    else:
        approval = approval.model_copy(
            update={"plan_quota": approval.plan_quota.model_copy(update={"remaining_credits": 2})}
        )
        code = "QUOTA_EXHAUSTED"
    authorizer = RefreshAuthorizer.for_owned_sources(approval, ledger, clock=lambda: NOW)
    authorizer.authorize(request)
    if scope == "monthly":
        # Shift one retained reservation's *actual trusted test time* to yesterday
        # by first using a separate chronological history, rather than editing it.
        ledger2 = DurableUsageLedger.create(tmp_path / "monthly")
        previous = NOW - timedelta(days=1)
        quota = approval.plan_quota.model_copy(
            update={"observed_at": previous, "period_started_at": previous - timedelta(days=1)}
        )
        approval2 = approval.model_copy(
            update={
                "ledger_id": ledger2.ledger_id,
                "approved_at": previous - timedelta(hours=1),
                "not_before": previous,
                "expires_at": NOW + timedelta(hours=1),
                "plan_quota": quota,
                "quota_max_age_seconds": 86400,
            }
        )
        request2 = request.model_copy(
            update={"information_cutoff": previous + timedelta(seconds=30)}
        )
        old = RefreshAuthorizer.for_owned_sources(approval2, ledger2, clock=lambda: previous)
        old.authorize(request2)
        old.authorize(request2)
        current = RefreshAuthorizer.for_owned_sources(approval2, ledger2, clock=lambda: NOW)
        with pytest.raises(AuthorizationError, match=code):
            current.authorize(request)
    else:
        with pytest.raises(AuthorizationError, match=code):
            RefreshAuthorizer.for_owned_sources(
                approval, DurableUsageLedger(ledger.path, ledger.ledger_id), clock=lambda: NOW
            ).authorize(request)


def test_concurrent_one_shot_never_reserves_twice(tmp_path):
    ledger, approval, request, _ = setup(tmp_path, usage="ONE_SHOT")

    def reserve():
        try:
            return RefreshAuthorizer.for_owned_sources(
                approval, DurableUsageLedger(ledger.path, ledger.ledger_id), clock=lambda: NOW
            ).authorize(request)
        except AuthorizationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: reserve(), range(2)))
    assert sum(not isinstance(row, str) for row in results) == 1
    assert len(list(ledger.path.glob("[0-9]*.json"))) == 1


def test_missing_replaced_corrupt_or_crashed_ledger_fails_closed(tmp_path):
    ledger, _, request, authorizer = setup(tmp_path)
    grant = authorizer.authorize(request)
    ledger.claim(grant, WORKER, now=NOW)
    ledger.check(grant, WORKER, now=NOW + timedelta(seconds=1))
    with pytest.raises(AuthorizationError, match="CLOCK_REGRESSED"):
        ledger.check(grant, WORKER, now=NOW)
    with pytest.raises(AuthorizationError, match="IDENTITY_MISMATCH"):
        DurableUsageLedger(ledger.path, "f" * 64).check(
            grant.model_copy(update={"ledger_id": "f" * 64}), WORKER, now=NOW
        )
    (ledger.path / "lock").mkdir()
    with pytest.raises(AuthorizationError, match="LEDGER_UNAVAILABLE"):
        ledger.check(grant, WORKER, now=NOW)
    (ledger.path / "lock").rmdir()
    path = ledger.path / "0000000000.json"
    path.write_text(path.read_text().replace('"RESERVATION"', '"FORGED"'), encoding="utf-8")
    with pytest.raises(AuthorizationError, match="LEDGER_INVALID"):
        ledger.check(grant, WORKER, now=NOW)


def test_control_records_contain_only_hashes_times_and_counters(tmp_path):
    ledger, _, request, authorizer = setup(tmp_path)
    grant = authorizer.authorize(request)
    ledger.claim(grant, WORKER, now=NOW)
    ledger.check(grant, WORKER, now=NOW)
    contents = "".join(path.read_text() for path in ledger.path.glob("*.json"))
    for forbidden in (
        "owned_account",
        "owned_operator",
        "api.the-odds-api",
        "bootstrap",
        "profile",
        "credential",
        "token",
        "2026/27",
    ):
        assert forbidden not in contents
    rows = [json.loads(path.read_text()) for path in ledger.path.glob("[0-9]*.json")]
    assert {row["kind"] for row in rows} == {"RESERVATION", "CLAIM", "CHECK"}


@pytest.mark.parametrize(
    "update",
    [
        {"approved_at": NOW.replace(tzinfo=None)},
        {"horizons": ()},
        {"horizons": (1, 1)},
        {"daily_credit_limit": 22},
        {"daily_request_limit": 11},
        {"monthly_credit_limit": 22},
        {"control_metadata_retention_approved": False},
        {"control_metadata_retention_approved": 1},
        {"control_metadata_retention_approved": "true"},
        {"horizons": (True,)},
    ],
)
def test_incomplete_or_unsafe_approval_contract_rejects(tmp_path, update):
    _, approval, _, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        approval.model_copy(update=update)


def test_json_horizon_boolean_cannot_be_normalized_into_approval(tmp_path):
    _, approval, _, _ = setup(tmp_path)
    body = approval.model_dump(mode="json")
    body["horizons"] = [True]
    with pytest.raises(ValueError, match="exact integers"):
        OperatorRefreshApproval.model_validate_json(json.dumps(body))
