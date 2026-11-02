"""Independent real PostgreSQL custody tests using unique owned accounts only."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError

from dmf_pulse.dashboard.authorization import RefreshAuthorizer, RefreshRequest
from dmf_pulse.dashboard.postgres_authorization import PostgresUsageLedger
from dmf_pulse.data_model.tables import operator_journal
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.operation import enrollment, standing
from dmf_pulse.operation.enrollment import rights_fingerprint
from dmf_pulse.operation.journal import OperationJournal
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.standing import execution_key, validate_policy
from tests.unit.operation.standing_support import NOW, owned_event, owned_policy, owned_quota

pytestmark = [pytest.mark.integration, pytest.mark.postgres]
WORKER = "a" * 64


@pytest.fixture(autouse=True)
def clean_postgres_test():
    """Override broad cleanup: every test owns a fresh immutable account/ledger."""
    return None


@pytest.fixture
def case(postgres_engine, tmp_path):
    # Refuse an operator database even if the test environment is misconfigured.
    if postgres_engine.url.database != "dmf_pulse_test":
        pytest.fail("standing journal tests require the explicitly owned test database")
    account = "owned_standing_" + uuid4().hex
    original = PostgresUsageLedger.initialize(
        postgres_engine.connect,
        account_ref=account,
        database_ref="SYNTHETIC_TEST_DATABASE",
    )
    value = owned_policy(tmp_path).model_dump(mode="json")
    value.update(ledger_id=original.ledger_id, odds_account_ref=account)
    quota = value["quota_qualification"]
    quota["account_ref"] = account
    quota["profile"]["account_scope"] = f"qualified private Odds account: {account}"
    quota["profile_sha256"] = rights_fingerprint(
        RightsProfile.model_validate_json(json.dumps(quota["profile"]))
    )
    paid = next(q for q in value["qualifications"] if q["scope"]["provider"] == "ODDS")
    paid["scope"]["account_ref"] = account
    paid["profile"]["account_scope"] = f"qualified private Odds account: {account}"
    paid["scope"]["profile_sha256"] = rights_fingerprint(
        RightsProfile.model_validate_json(json.dumps(paid["profile"]))
    )
    policy = validate_policy(value)
    return SimpleNamespace(
        policy=policy,
        original=original,
        engine=postgres_engine,
        journal=OperationJournal(policy, postgres_engine.connect),
    )


def rows(case):
    with case.engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                select(operator_journal)
                .where(operator_journal.c.ledger_id == case.policy.ledger_id)
                .order_by(operator_journal.c.sequence)
            ).mappings()
        ]


def admit(case, *, now=NOW, gameweek=10, used=0):
    event = owned_event(now=now, gameweek=gameweek)
    quota = owned_quota(case.policy, now=now, used=used)
    key = case.journal.enroll(event, quota, now=now)
    active = case.journal.active_enrollment(case.policy, now=now + timedelta(seconds=1))
    assert active is not None and len(active.approvals) == 1
    return key, active


def paid_attempt(case, monkeypatch, *, dynamic_registry=False):
    key, registry = admit(case)
    # Only the owned test context resolves this genuine typed private grant.
    if dynamic_registry:

        class OwnedClock(datetime):
            @classmethod
            def now(cls, tz=None):
                del tz
                return NOW + timedelta(seconds=2)

        monkeypatch.setattr(standing, "datetime", OwnedClock)
        monkeypatch.setattr(standing, "installed_standing_policy", lambda **_: case.policy)
        monkeypatch.setattr(
            OperationJournal,
            "production",
            classmethod(lambda cls, policy: cls(policy, case.engine.connect)),
        )
    else:
        monkeypatch.setattr(enrollment, "installed_enrollment", lambda: registry)
    approval = registry.approvals[0]
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
        information_cutoff=NOW + timedelta(seconds=300),
        deadline_at=owned_event().deadline_at,
    )
    # This ledger still points only at the explicit owned engine; its reference
    # is the same private-control discriminator exercised by the actual worker.
    authorizer = RefreshAuthorizer(case.journal.ledger, clock=lambda: NOW + timedelta(seconds=2))
    authorizer.preflight(request)
    grant = authorizer.authorize(request)
    case.journal.ledger.claim(grant, WORKER, now=NOW + timedelta(seconds=3))
    case.journal.ledger.attempt(
        grant,
        WORKER,
        provider="ODDS",
        method="GET",
        host="api.the-odds-api.com",
        path="/v4/sports/soccer_epl/odds",
        now=NOW + timedelta(seconds=4),
    )
    return key, grant


def headers(cost):
    return {
        "x-requests-remaining": str(500 - cost),
        "x-requests-used": str(cost),
        "x-requests-last": str(cost),
    }


def test_journal_restart_preserves_original_ledger_head_and_identity(case):
    before = case.original.audit()
    launch = case.journal.begin_launch(now=NOW)
    case.journal.close_launch(launch, now=NOW + timedelta(seconds=1))
    reopened = OperationJournal(case.policy, case.engine.connect)
    recovered = reopened.recover()
    assert recovered["ledger_id"] == before.ledger_id
    assert recovered["original_event_count"] == before.event_count == 0
    assert recovered["original_head_sha256"] == before.head_sha256
    assert recovered["standing_event_count"] == 2
    assert case.original.audit() == before


def test_concurrent_launch_leases_serialize_and_recover_after_close(case):
    barrier = Barrier(2)

    def launch():
        barrier.wait(timeout=10)
        try:
            return case.journal.begin_launch(now=NOW)
        except OperationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: launch(), range(2)))
    assert results.count("ANOTHER_OPERATOR_LAUNCH_IS_RUNNING") == 1
    identity = next(value for value in results if len(value) == 64)
    reopened = OperationJournal(case.policy, case.engine.connect)
    with pytest.raises(OperationError, match="ANOTHER_OPERATOR_LAUNCH_IS_RUNNING"):
        reopened.begin_launch(now=NOW + timedelta(seconds=1))
    reopened.close_launch(identity, now=NOW + timedelta(seconds=2))
    assert len(reopened.begin_launch(now=NOW + timedelta(seconds=3))) == 64


def test_abandoned_lease_is_not_reclaimed_before_its_durable_expiry(case):
    case.journal.begin_launch(now=NOW)
    reopened = OperationJournal(case.policy, case.engine.connect)
    with pytest.raises(OperationError, match="ANOTHER_OPERATOR_LAUNCH_IS_RUNNING"):
        reopened.begin_launch(now=NOW + timedelta(seconds=1199))
    assert len(reopened.begin_launch(now=NOW + timedelta(seconds=1201))) == 64


def test_concurrent_same_event_admission_writes_exactly_one_marker(case):
    barrier = Barrier(2)
    event, quota = owned_event(), owned_quota(case.policy)

    def enroll():
        barrier.wait(timeout=10)
        try:
            return case.journal.enroll(event, quota, now=NOW)
        except OperationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: enroll(), range(2)))
    key = execution_key(case.policy, event.target_gameweek)
    assert results.count(key) == 1
    assert results.count("GAMEWEEK_ACQUISITION_ALREADY_RECORDED") == 1
    assert len([row for row in rows(case) if row["kind"] == "ENROLL"]) == 1
    assert case.original.audit().reservation_count == 0


def test_distinct_concurrent_events_cannot_bypass_account_daily_limit(case):
    barrier = Barrier(2)

    def enroll(gameweek):
        barrier.wait(timeout=10)
        try:
            return case.journal.enroll(
                owned_event(gameweek=gameweek), owned_quota(case.policy), now=NOW
            )
        except OperationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(enroll, (10, 11)))
    assert results.count("STANDING_REQUEST_BUDGET_EXHAUSTED") == 1
    assert len([row for row in rows(case) if row["kind"] == "ENROLL"]) == 1


def test_daily_admissions_cannot_bypass_monthly_limit_or_reset_old_event(case):
    for offset in range(8):
        admit(case, now=NOW + timedelta(days=offset), gameweek=10 + offset)
    ninth = NOW + timedelta(days=8)
    with pytest.raises(OperationError, match="STANDING_REQUEST_BUDGET_EXHAUSTED"):
        case.journal.enroll(
            owned_event(now=ninth, gameweek=18), owned_quota(case.policy, now=ninth), now=ninth
        )
    december = NOW.replace(month=12)
    admit(case, now=december, gameweek=19)
    with pytest.raises(OperationError, match="GAMEWEEK_ACQUISITION_ALREADY_RECORDED"):
        case.journal.enroll(
            owned_event(now=december, gameweek=10),
            owned_quota(case.policy, now=december),
            now=december + timedelta(seconds=2),
        )
    assert case.original.audit().event_count == 0


def test_restart_and_maintenance_cannot_clear_incomplete_event_marker(case):
    key, _ = admit(case)
    revised = validate_policy(
        {**case.policy.model_dump(mode="json"), "policy_id": "OWNED-MAINTENANCE-REVISION"}
    )
    reopened = OperationJournal(revised, case.engine.connect)
    assert reopened.contains_event(key)
    assert reopened.saved_view(key) is None
    with pytest.raises(OperationError, match="GAMEWEEK_ACQUISITION_ALREADY_RECORDED"):
        reopened.enroll(owned_event(), owned_quota(revised), now=NOW + timedelta(seconds=2))
    assert case.original.audit().event_count == 0


def test_maintenance_cannot_hide_live_grant_from_previous_policy_revision(case):
    admit(case)
    revised = validate_policy(
        {
            **case.policy.model_dump(mode="json"),
            "policy_id": "OWNED-REVIEWED-COMPATIBILITY",
            "implementation_sha": "3" * 40,
            "independent_review_sha256": "4" * 64,
        }
    )
    reopened = OperationJournal(revised, case.engine.connect)
    # The incoming release has no matching active policy; maintenance must still
    # find the old release's live grant through the unchanged canonical ledger.
    assert reopened.active_enrollment(revised, now=NOW + timedelta(seconds=1)) is None
    with pytest.raises(OperationError, match="MAINTENANCE_REQUIRES_FINISHED_EXECUTION_WINDOW"):
        reopened.require_no_live_execution(now=NOW + timedelta(seconds=1))
    reopened.require_no_live_execution(now=NOW + timedelta(seconds=901))
    assert case.original.audit().event_count == 0


def test_maintenance_cannot_hide_previous_policy_unclosed_launch_lease(case):
    identity = case.journal.begin_launch(now=NOW)
    revised = validate_policy(
        {**case.policy.model_dump(mode="json"), "policy_id": "OWNED-INCOMING-RELEASE"}
    )
    reopened = OperationJournal(revised, case.engine.connect)
    with pytest.raises(OperationError, match="MAINTENANCE_REQUIRES_FINISHED_LAUNCH_LEASE"):
        reopened.require_no_live_execution(now=NOW + timedelta(seconds=1))
    case.journal.close_launch(identity, now=NOW + timedelta(seconds=2))
    reopened.require_no_live_execution(now=NOW + timedelta(seconds=3))
    assert case.original.audit().event_count == 0


@pytest.mark.parametrize("cost", [0, 1, 2])
def test_actual_response_cost_is_retained_without_inferred_two_credit_charge(
    case, monkeypatch, cost
):
    key, grant = paid_attempt(case, monkeypatch)
    before = case.original.audit()
    assert before.reservation_count == before.claim_count == before.attempt_count == 1
    case.journal.settle_response(grant, headers(cost), 200, now=NOW + timedelta(seconds=5))
    settlement = next(row for row in rows(case) if row["kind"] == "SETTLEMENT")
    value = settlement["payload"]["value"]
    assert settlement["execution_key"] == key
    assert value["reserved_credits"] == 2
    assert value["last_request_cost"] == cost
    assert value["remaining_credits"] == 500 - cost
    assert value["consistent"] is True
    assert case.original.audit() == before
    reopened = OperationJournal(case.policy, case.engine.connect)
    tomorrow = NOW + timedelta(days=1)
    verified = reopened.qualify_quota(
        owned_quota(case.policy, now=tomorrow, used=cost), now=tomorrow
    )
    assert verified.expected_used_credits == cost


def test_dynamic_installed_enrollment_uses_owned_journal_without_nested_pg_lock(case, monkeypatch):
    _, grant = paid_attempt(case, monkeypatch, dynamic_registry=True)
    case.journal.settle_response(grant, headers(2), 200, now=NOW + timedelta(seconds=5))
    audit = case.original.audit()
    assert audit.reservation_count == audit.claim_count == audit.attempt_count == 1
    assert (
        case.journal.qualify_quota(
            owned_quota(case.policy, used=2), now=NOW + timedelta(seconds=6)
        ).expected_used_credits
        == 2
    )


def test_fresh_monthly_reset_preserves_paid_history_and_same_event_dedup(case, monkeypatch):
    key, grant = paid_attempt(case, monkeypatch)
    case.journal.settle_response(grant, headers(2), 200, now=NOW + timedelta(seconds=5))
    original = case.original.audit()
    december = NOW.replace(month=12)
    reopened = OperationJournal(case.policy, case.engine.connect)
    period = reopened.qualify_quota(owned_quota(case.policy, now=december), now=december)
    assert period.expected_used_credits == 0 and period.started_at.month == 12
    assert reopened.contains_event(key)
    with pytest.raises(OperationError, match="GAMEWEEK_ACQUISITION_ALREADY_RECORDED"):
        reopened.enroll(
            owned_event(now=december), owned_quota(case.policy, now=december), now=december
        )
    assert case.original.audit() == original


@pytest.mark.parametrize(
    "bad_headers",
    [
        {},
        {"x-requests-remaining": "498", "x-requests-used": "2"},
        {"x-requests-remaining": "0498", "x-requests-used": "2", "x-requests-last": "2"},
    ],
)
def test_missing_or_invalid_postpaid_headers_remain_unresolved_after_restart(
    case, monkeypatch, bad_headers
):
    _, grant = paid_attempt(case, monkeypatch)
    with pytest.raises(OperationError):
        case.journal.settle_response(grant, bad_headers, 200, now=NOW + timedelta(seconds=5))
    assert not any(row["kind"] == "SETTLEMENT" for row in rows(case))
    assert case.original.audit().attempt_count == 1
    reopened = OperationJournal(case.policy, case.engine.connect)
    tomorrow = NOW + timedelta(days=1)
    with pytest.raises(OperationError, match="QUOTA_EVIDENCE_OR_LEDGER_CONTRADICTION"):
        reopened.qualify_quota(owned_quota(case.policy, now=tomorrow), now=tomorrow)


@pytest.mark.parametrize(
    "bad_headers",
    [
        {"x-requests-remaining": "496", "x-requests-used": "4", "x-requests-last": "2"},
        {"x-requests-remaining": "497", "x-requests-used": "3", "x-requests-last": "3"},
    ],
)
def test_actual_contradiction_is_committed_before_admission_is_refused(
    case, monkeypatch, bad_headers
):
    _, grant = paid_attempt(case, monkeypatch)
    with pytest.raises(OperationError, match="CHARGED_QUOTA_HEADERS_CONTRADICT_LEDGER"):
        case.journal.settle_response(grant, bad_headers, 200, now=NOW + timedelta(seconds=5))
    settlement = next(row for row in rows(case) if row["kind"] == "SETTLEMENT")
    assert settlement["payload"]["value"]["consistent"] is False
    assert settlement["payload"]["value"]["last_request_cost"] == int(
        bad_headers["x-requests-last"]
    )
    with pytest.raises(OperationError, match="QUOTA_EVIDENCE_OR_LEDGER_CONTRADICTION"):
        case.journal.qualify_quota(
            owned_quota(case.policy, used=int(bad_headers["x-requests-used"])),
            now=NOW + timedelta(seconds=6),
        )


def test_same_paid_response_cannot_settle_twice(case, monkeypatch):
    _, grant = paid_attempt(case, monkeypatch)
    barrier = Barrier(2)

    def settle():
        barrier.wait(timeout=10)
        try:
            case.journal.settle_response(grant, headers(2), 200, now=NOW + timedelta(seconds=5))
            return "SETTLED"
        except OperationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: settle(), range(2)))
    assert results.count("SETTLED") == 1
    assert len([row for row in rows(case) if row["kind"] == "SETTLEMENT"]) == 1
    assert (
        case.journal.qualify_quota(
            owned_quota(case.policy, used=2), now=NOW + timedelta(seconds=6)
        ).expected_used_credits
        == 2
    )


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_owned_journal_rows_reject_mutation_and_preserve_original_head(case, operation):
    launch = case.journal.begin_launch(now=NOW)
    before = rows(case)
    original = case.original.audit()
    statement = (
        "UPDATE core.operator_journal SET kind='FAILURE' WHERE ledger_id=:ledger"
        if operation == "UPDATE"
        else "DELETE FROM core.operator_journal WHERE ledger_id=:ledger"
    )
    with pytest.raises(DBAPIError), case.engine.begin() as connection:
        connection.execute(text(statement), {"ledger": case.policy.ledger_id})
    assert rows(case) == before
    assert case.original.audit() == original
    case.journal.close_launch(launch, now=NOW + timedelta(seconds=1))


def test_raw_forged_append_cannot_bypass_database_chain_guard(case):
    case.journal.begin_launch(now=NOW)
    before = rows(case)
    last = before[-1]
    with pytest.raises(DBAPIError), case.engine.begin() as connection:
        connection.execute(
            insert(operator_journal).values(
                ledger_id=case.policy.ledger_id,
                sequence=1,
                sha256="0" * 64,
                previous_sha256=last["sha256"],
                at=NOW + timedelta(seconds=1),
                kind="FAILURE",
                execution_key=None,
                payload={
                    "recorded_at": (NOW + timedelta(seconds=1)).isoformat(),
                    "value": {"error_code": "OWNED-TAMPER"},
                },
            )
        )
    assert rows(case) == before
    assert case.original.audit().event_count == 0
