"""Canonical SQL custody, atomic quotas, restart and control-only mutation attacks."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.exc import DBAPIError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard.authorization import (
    AuthorizationError,
    OperatorRefreshApproval,
    QualifiedPlanQuota,
    RefreshAuthorizer,
    RefreshRequest,
    RouteBudget,
    SourceScope,
)
from dmf_pulse.dashboard.postgres_authorization import PostgresUsageLedger
from dmf_pulse.data_model.tables import refresh_control_event

pytestmark = [pytest.mark.integration, pytest.mark.postgres]
NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
WORKER = "a" * 64


def _setup(engine: Engine, **changes):
    account = "owned_pg_" + uuid4().hex
    ledger = PostgresUsageLedger.initialize(
        engine.connect, account_ref=account, database_ref="SYNTHETIC_TEST_DATABASE"
    )
    scopes = tuple(
        SourceScope(
            provider=provider,
            account_ref=account,
            profile_id=f"synthetic_{provider.lower()}_v1",
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
        plan_quota=QualifiedPlanQuota(
            account_ref=account,
            plan_ref="owned_plan",
            evidence_sha256="2" * 64,
            terms_evidence_sha256="3" * 64,
            monthly_plan_credits=500,
            allocated_monthly_credits=20,
            remaining_credits=20,
            observed_at=NOW,
            period_started_at=NOW - timedelta(days=1),
            resets_at=NOW + timedelta(days=29),
        ),
        ledger_id=ledger.ledger_id,
        ledger_backend="POSTGRES",
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
    return account, ledger, approval, request


def _authorizer(ledger, approval):
    return RefreshAuthorizer.for_owned_sources(approval, ledger, clock=lambda: NOW)


def _rows(engine, ledger):
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                select(refresh_control_event.c.payload)
                .where(refresh_control_event.c.ledger_id == ledger.ledger_id)
                .order_by(refresh_control_event.c.sequence)
            ).scalars()
        ]


def test_full_pg_reserve_claim_check_attempt_and_restart(postgres_engine):
    account, ledger, approval, request = _setup(postgres_engine)
    grant = _authorizer(ledger, approval).authorize(request)
    ledger.claim(grant, WORKER, now=NOW)
    ledger.check(grant, WORKER, now=NOW)
    route = next(item for item in request.source_scopes if item.provider == "ODDS").routes[0]
    ledger.attempt(
        grant, WORKER, provider="ODDS", method="GET", host=route.host, path=route.path, now=NOW
    )
    rows = _rows(postgres_engine, ledger)
    assert [row["kind"] for row in rows] == ["RESERVATION", "CLAIM", "CHECK", "ATTEMPT"]
    assert all(row["ledger_id"] == ledger.ledger_id for row in rows)
    reopened = PostgresUsageLedger.initialize(
        postgres_engine.connect, account_ref=account, database_ref="SYNTHETIC_TEST_DATABASE"
    )
    assert reopened.ledger_id == ledger.ledger_id
    assert _rows(postgres_engine, reopened) == rows
    with pytest.raises(AuthorizationError, match="ALREADY_CLAIMED"):
        reopened.claim(grant, WORKER, now=NOW)
    with pytest.raises(AuthorizationError, match="SOURCE_REQUEST_BUDGET_EXHAUSTED"):
        reopened.attempt(
            grant, WORKER, provider="ODDS", method="GET", host=route.host, path=route.path, now=NOW
        )


def test_pg_one_shot_and_different_ledger_cannot_reset_account(postgres_engine):
    account, ledger, approval, request = _setup(postgres_engine, usage="ONE_SHOT")
    _authorizer(ledger, approval).authorize(request)
    reopened = PostgresUsageLedger.initialize(
        postgres_engine.connect, account_ref=account, database_ref="SYNTHETIC_TEST_DATABASE"
    )
    with pytest.raises(AuthorizationError, match="ONE_SHOT_CONSUMED"):
        _authorizer(reopened, approval).authorize(request)
    forged = PostgresUsageLedger(
        postgres_engine.connect,
        "f" * 64,
        account_ref=account,
        database_ref="SYNTHETIC_TEST_DATABASE",
    )
    with pytest.raises(AuthorizationError, match="IDENTITY_MISMATCH"):
        _authorizer(forged, approval.model_copy(update={"ledger_id": forged.ledger_id})).authorize(
            request
        )
    assert len(_rows(postgres_engine, reopened)) == 1


@pytest.mark.parametrize(
    "usage,code",
    [("ONE_SHOT", "ONE_SHOT_CONSUMED"), ("MANUAL_RECURRING", "DAILY_BUDGET_EXHAUSTED")],
)
def test_concurrent_reservations_serialize_exactly_one(postgres_engine, usage, code):
    _, ledger, approval, request = _setup(
        postgres_engine, usage=usage, daily_request_limit=1, daily_credit_limit=2
    )

    def reserve(_):
        try:
            return _authorizer(ledger, approval).authorize(request)
        except AuthorizationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(reserve, range(6)))
    assert sum(not isinstance(item, str) for item in results) == 1
    assert sum(item == code for item in results) == 5
    assert len(_rows(postgres_engine, ledger)) == 1


def test_concurrent_claims_and_attempts_cannot_duplicate(postgres_engine):
    _, ledger, approval, request = _setup(postgres_engine)
    grant = _authorizer(ledger, approval).authorize(request)

    def claim(_):
        try:
            ledger.claim(grant, WORKER, now=NOW)
            return "PASS"
        except AuthorizationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, range(4)))
    assert results.count("PASS") == 1 and results.count("REFRESH_GRANT_ALREADY_CLAIMED") == 3
    route = next(item for item in request.source_scopes if item.provider == "ODDS").routes[0]

    def attempt(_):
        try:
            ledger.attempt(
                grant,
                WORKER,
                provider="ODDS",
                method="GET",
                host=route.host,
                path=route.path,
                now=NOW,
            )
            return "PASS"
        except AuthorizationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count("PASS") == 1 and results.count("SOURCE_REQUEST_BUDGET_EXHAUSTED") == 3


def test_atomic_failure_rolls_back_reservation(postgres_engine, monkeypatch):
    _, ledger, approval, request = _setup(postgres_engine)
    original = ledger._append

    def failed(records, payload):
        original(records, payload)
        raise ValueError("owned synthetic forced rollback")

    with monkeypatch.context() as local:
        local.setattr(ledger, "_append", failed)
        with pytest.raises(AuthorizationError, match="USAGE_LEDGER_UNAVAILABLE"):
            _authorizer(ledger, approval).authorize(request)
    assert _rows(postgres_engine, ledger) == []
    _authorizer(ledger, approval).authorize(request)
    assert len(_rows(postgres_engine, ledger)) == 1


@pytest.mark.parametrize("table", ["ledger", "event"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_pg_control_rows_are_append_only_including_truncate(postgres_engine, table, operation):
    _, ledger, approval, request = _setup(postgres_engine)
    _authorizer(ledger, approval).authorize(request)
    name = "core.refresh_control_" + table
    statement = (
        f"UPDATE {name} SET ledger_id=ledger_id WHERE ledger_id=:ledger"
        if operation == "UPDATE"
        else f"DELETE FROM {name} WHERE ledger_id=:ledger"
        if operation == "DELETE"
        else f"TRUNCATE TABLE {name} CASCADE"
    )
    with (
        pytest.raises(DBAPIError, match="REFRESH_CONTROL_APPEND_ONLY"),
        postgres_engine.begin() as connection,
    ):
        connection.execute(text(statement), {"ledger": ledger.ledger_id})
    assert len(_rows(postgres_engine, ledger)) == 1


@pytest.mark.parametrize(
    "attack",
    [
        "extra_private_field",
        "null_account",
        "wrong_hash",
        "wrong_previous",
        "replay",
        "wrong_row_at",
    ],
)
def test_direct_sql_control_schema_and_chain_reject_injected_values(postgres_engine, attack):
    _, ledger, approval, request = _setup(postgres_engine)
    _authorizer(ledger, approval).authorize(request)
    original = _rows(postgres_engine, ledger)[0]
    value = {
        **original,
        "sequence": 1,
        "previous_sha256": original["sha256"],
        "reservation_id": "e" * 64,
    }
    if attack == "extra_private_field":
        value["provider_body"] = "OWNED_SYNTHETIC_DISALLOWED_FIELD"
    elif attack == "null_account":
        value["account_sha256"] = None
    elif attack == "wrong_previous":
        value["previous_sha256"] = "0" * 64
    elif attack == "replay":
        value["reservation_id"] = original["reservation_id"]
    value["sha256"] = canonical_sha256(
        {key: item for key, item in value.items() if key != "sha256"}
    )
    if attack == "wrong_hash":
        value["sha256"] = "0" * 64
    row = {
        key: value[key] for key in ("ledger_id", "sequence", "sha256", "previous_sha256", "kind")
    }
    row["at"] = NOW + timedelta(seconds=1) if attack == "wrong_row_at" else NOW
    with pytest.raises(DBAPIError), postgres_engine.begin() as connection:
        connection.execute(insert(refresh_control_event).values(**row, payload=value))
    assert len(_rows(postgres_engine, ledger)) == 1


def test_privileged_test_corruption_is_detected_before_next_operation(postgres_engine):
    _, ledger, approval, request = _setup(postgres_engine)
    grant = _authorizer(ledger, approval).authorize(request)
    ledger.claim(grant, WORKER, now=NOW)
    original = _rows(postgres_engine, ledger)[1]
    changed = {**original, "worker_sha256": "b" * 64}

    def replace(payload):
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE core.refresh_control_event DISABLE TRIGGER trg_refresh_control_event_immutable"
                )
            )
            connection.execute(
                text(
                    "UPDATE core.refresh_control_event SET payload=CAST(:payload AS jsonb) WHERE ledger_id=:ledger AND sequence=1"
                ),
                {"payload": json.dumps(payload), "ledger": ledger.ledger_id},
            )
            connection.execute(
                text(
                    "ALTER TABLE core.refresh_control_event ENABLE TRIGGER trg_refresh_control_event_immutable"
                )
            )

    try:
        replace(changed)
        with pytest.raises(AuthorizationError, match="USAGE_LEDGER_INVALID"):
            ledger.check(grant, WORKER, now=NOW)
    finally:
        replace(original)
    ledger.check(grant, WORKER, now=NOW)


def test_forged_private_grant_is_denied_before_any_pg_connection(postgres_engine):
    account, ledger, approval, request = _setup(postgres_engine)
    owned = _authorizer(ledger, approval).authorize(request)
    calls = []

    def forbidden():
        calls.append(True)
        raise AssertionError("private grant reached DB before enrollment validation")

    closed = PostgresUsageLedger(forbidden, ledger.ledger_id, account_ref=account)
    forged = owned.model_copy(update={"classification": "PRIVATE_CURRENT"})
    with pytest.raises(AuthorizationError, match="REFRESH_GRANT_INVALID"):
        closed.claim(forged, WORKER, now=NOW)
    assert not calls


@pytest.mark.parametrize("operation", ["reserve", "claim", "check", "attempt"])
def test_synthetic_database_selector_never_admits_private_current(postgres_engine, operation):
    account, ledger, approval, request = _setup(postgres_engine)
    owned = _authorizer(ledger, approval).authorize(request)
    calls = []

    def forbidden():
        calls.append(True)
        raise AssertionError("private grant used synthetic database selector")

    closed = PostgresUsageLedger(
        forbidden, ledger.ledger_id, account_ref=account, database_ref="SYNTHETIC_TEST_DATABASE"
    )
    forged = owned.model_copy(update={"classification": "PRIVATE_CURRENT"})
    with pytest.raises(AuthorizationError, match="PRIVATE_CONTROL_DATABASE_REQUIRED"):
        if operation == "reserve":
            private = approval.model_copy(
                update={
                    "classification": "PRIVATE_CURRENT",
                    "source_scopes": tuple(
                        item.model_copy(update={"source_kind": "RIGHTS_QUALIFIED_PRIVATE"})
                        for item in approval.source_scopes
                    ),
                }
            )
            closed.reserve(private, forged)
        elif operation == "claim":
            closed.claim(forged, WORKER, now=NOW)
        elif operation == "check":
            closed.check(forged, WORKER, now=NOW)
        else:
            closed.attempt(
                forged,
                WORKER,
                provider="ODDS",
                method="GET",
                host="api.the-odds-api.com",
                path="/v4/sports/soccer_epl/odds",
                now=NOW,
            )
    assert not calls
