"""Standing authority, fresh calendar/quota admission and event-specific grants."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.operation import standing
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.standing import derive_enrollment, execution_key, verify_period
from tests.unit.operation.standing_support import NOW, owned_event, owned_policy, owned_quota


@pytest.fixture
def policy(tmp_path):
    return owned_policy(tmp_path)


def period(policy, quota, *, now=NOW, settled=0, unresolved=0):
    return verify_period(
        policy, quota, now=now, settled_credits=settled, unresolved_paid_attempts=unresolved
    )


def test_no_standing_authority_in_public_wheel():
    assert standing.installed_standing_policy(required=False) is None
    with pytest.raises(OperationError, match="STANDING_OWNER_ACCEPTANCE_REQUIRED"):
        standing.require_policy()


def test_fresh_provider_headers_reconcile_original_anchor(policy):
    quota = owned_quota(policy)
    observed = period(policy, quota)
    assert observed.started_at.isoformat() == "2026-11-01T00:00:00+00:00"
    assert observed.resets_at.isoformat() == "2026-12-01T00:00:00+00:00"
    assert "OWNER_QUALIFIED" in observed.basis


@pytest.mark.parametrize(
    "changes,settled,unresolved,code",
    [
        ({"used": 2}, 0, 0, "EXCLUSIVE_ACCOUNT_USAGE_CONTRADICTION"),
        ({"used": 2}, 2, 1, "QUOTA_EVIDENCE_OR_LEDGER_CONTRADICTION"),
        ({"remaining": 499}, 0, 0, "QUOTA_EVIDENCE_OR_LEDGER_CONTRADICTION"),
        ({"used": 489}, 489, 0, "QUOTA_BELOW_SAFETY_RESERVE"),
    ],
)
def test_quota_contradictions_prevent_any_grant(policy, changes, settled, unresolved, code):
    with pytest.raises(OperationError, match=code):
        period(policy, owned_quota(policy, **changes), settled=settled, unresolved=unresolved)


def test_actual_consumption_and_remaining_both_reconcile(policy):
    observed = period(policy, owned_quota(policy, used=2), settled=2)
    assert observed.expected_used_credits == 2


def test_monthly_reset_requires_current_headers_not_rolled_balance(policy):
    december = NOW.replace(month=12)
    assert period(policy, owned_quota(policy, now=december), now=december).started_at.month == 12
    with pytest.raises(OperationError, match="EXCLUSIVE_ACCOUNT_USAGE_CONTRADICTION"):
        period(policy, owned_quota(policy, now=december, used=2), now=december)
    with pytest.raises(OperationError, match="QUOTA_EVIDENCE_OR_LEDGER_CONTRADICTION"):
        period(policy, owned_quota(policy), now=december)


def test_quota_request_spanning_reset_fails_closed(policy):
    boundary = NOW.replace(month=12, hour=0, minute=0, second=2)
    with pytest.raises(OperationError, match="QUOTA_CHECK_CROSSED_MONTHLY_RESET"):
        period(policy, owned_quota(policy, now=boundary), now=boundary)


def test_next_official_event_derives_exact_manager_routes_and_single_paid_scope(policy):
    event, quota = owned_event(gameweek=21), owned_quota(policy)
    enrollment = derive_enrollment(policy, event, quota, period(policy, quota), created_at=NOW)
    approval = enrollment.approvals[0]
    fpl = next(s for s in approval.source_scopes if s.provider == "FPL")
    odds = next(s for s in approval.source_scopes if s.provider == "ODDS")
    assert len(fpl.routes) == 19
    assert all(
        "/18/" not in r.path for r in fpl.routes if "/entry/" in r.path or "/my-team/" in r.path
    )
    assert {r.path for r in fpl.routes if "/event/" in r.path and r.path.endswith("live/")} == {
        f"/api/event/{i}/live/" for i in range(9, 21)
    }
    assert len(odds.routes) == 1 and odds.routes[0].maximum_calls == 1
    assert odds.routes[0].path == "/v4/sports/soccer_epl/odds"
    assert approval.usage == "ONE_SHOT" and approval.horizons == (1,)
    assert approval.qualified_deadline_at == event.deadline_at
    assert approval.expires_at == NOW + timedelta(seconds=900)
    assert (
        enrollment.qualifications[0].permission_basis == policy.qualifications[0].permission_basis
    )


def test_dedup_identity_survives_maintenance_and_policy_revision(policy):
    changed = policy.model_copy(
        update={"policy_id": "OWNED-REVISION-2", "implementation_sha": "0" * 40}
    )
    assert execution_key(policy, 10) == execution_key(changed, 10)
    assert execution_key(policy, 10) != execution_key(policy, 11)
    assert execution_key(policy, 10) != execution_key(
        policy.model_copy(update={"entry_id": 18}), 10
    )


@pytest.mark.parametrize("age", [61, 3600])
def test_stale_discovery_is_never_rolled_forward(policy, age):
    quota = owned_quota(policy)
    event = owned_event(now=NOW - timedelta(seconds=age))
    with pytest.raises(OperationError, match="STANDING_EVENT_OR_QUOTA_STALE"):
        derive_enrollment(policy, event, quota, period(policy, quota), created_at=NOW)


def test_deadline_too_close_refuses_before_reservation(policy):
    quota = owned_quota(policy)
    event = owned_event().model_copy(update={"deadline_at": NOW + timedelta(seconds=900)})
    with pytest.raises(OperationError, match="STANDING_EVENT_OR_QUOTA_STALE"):
        derive_enrollment(policy, event, quota, period(policy, quota), created_at=NOW)


@pytest.mark.parametrize(
    "change",
    [
        {"automatic_retries": 1},
        {"monthly_requests": 9},
        {"monthly_credits": 18},
        {"fpl_total_requests": 21},
        {"safety_reserve_credits": 9},
    ],
)
def test_policy_cannot_expand_accepted_operating_ceiling(policy, change):
    value = policy.limits.model_dump()
    with pytest.raises(ValidationError):
        type(policy.limits).model_validate({**value, **change})
