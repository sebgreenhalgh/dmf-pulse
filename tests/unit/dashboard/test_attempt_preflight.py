"""Exact claimed-route preflight before secret lookup; all histories are owned."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from dmf_pulse.dashboard import authorization as auth
from dmf_pulse.dashboard.authorization import AuthorizationError, RefreshAuthorizer, UsageLedger
from dmf_pulse.dashboard.postgres_authorization import PostgresUsageLedger
from tests.unit.dashboard.test_live_authorization import NOW, WORKER, setup

pytestmark = pytest.mark.unit


def _scope():
    return dict(
        provider="ODDS",
        method="GET",
        host="api.the-odds-api.com",
        path="/v4/sports/soccer_epl/odds",
        now=NOW,
    )


def _bytes(ledger):
    return {path.name: path.read_bytes() for path in ledger.path.iterdir()}


def _claimed(tmp_path):
    ledger, _approval, request, authorizer = setup(tmp_path)
    grant = authorizer.authorize(request)
    ledger.claim(grant, WORKER, now=NOW)
    return ledger, grant


def test_repeated_attempt_preflights_are_read_only_then_transport_consumes_once(tmp_path):
    ledger, grant = _claimed(tmp_path)
    before = _bytes(ledger)
    for _ in range(3):
        assert ledger.preflight_attempt(grant, WORKER, **_scope()) is None
        assert _bytes(ledger) == before
    ledger.attempt(grant, WORKER, **_scope())
    spent = _bytes(ledger)
    assert len(spent) == len(before) + 1
    audit = ledger.audit()
    assert (audit.reservation_count, audit.claim_count, audit.attempt_count, audit.check_count) == (
        1,
        1,
        1,
        0,
    )
    for action in (ledger.preflight_attempt, ledger.attempt):
        with pytest.raises(AuthorizationError, match="SOURCE_REQUEST_BUDGET_EXHAUSTED"):
            action(grant, WORKER, **_scope())
        assert _bytes(ledger) == spent


@pytest.mark.parametrize(
    "attack,expected",
    [
        ("expiry", "REFRESH_GRANT_EXPIRED"),
        ("cutoff", "ACQUISITION_CUTOFF_PASSED"),
        ("naive", "AUTHORIZATION_CLOCK_INVALID"),
        ("method", "SOURCE_ROUTE_NOT_AUTHORIZED"),
        ("host", "SOURCE_ROUTE_NOT_AUTHORIZED"),
        ("path", "SOURCE_ROUTE_NOT_AUTHORIZED"),
        ("provider", "SOURCE_ROUTE_NOT_AUTHORIZED"),
        ("worker", "REFRESH_GRANT_NOT_CLAIMED"),
        ("grant_identity", "REFRESH_GRANT_INVALID"),
    ],
)
def test_attempt_and_preflight_have_identical_denials_without_writes(tmp_path, attack, expected):
    ledger, grant = _claimed(tmp_path)
    options, worker = _scope(), WORKER
    if attack == "expiry":
        options["now"] = grant.expires_at
    elif attack == "cutoff":
        options["now"] = grant.request.information_cutoff + timedelta(microseconds=1)
    elif attack == "naive":
        options["now"] = NOW.replace(tzinfo=None)
    elif attack in ("method", "host", "path", "provider"):
        options[attack] = {
            "method": "POST",
            "host": "other.example",
            "path": "/not-authorized",
            "provider": "FPL",
        }[attack]
    elif attack == "worker":
        worker = "b" * 64
    else:
        grant = grant.model_copy(update={"ledger_id": "f" * 64})
    before = _bytes(ledger)
    for action in (ledger.preflight_attempt, ledger.attempt):
        with pytest.raises(AuthorizationError, match=expected):
            action(grant, worker, **options)
        assert _bytes(ledger) == before


def test_unclaimed_grant_cannot_reach_a_credential_lookup_callback(tmp_path):
    ledger, _, request, authorizer = setup(tmp_path)
    grant = authorizer.authorize(request)
    before = _bytes(ledger)
    called = []

    def resolve_only_if_allowed():
        ledger.preflight_attempt(grant, WORKER, **_scope())
        called.append("owned-credential")

    with pytest.raises(AuthorizationError, match="REFRESH_GRANT_NOT_CLAIMED"):
        resolve_only_if_allowed()
    assert called == [] and _bytes(ledger) == before


def test_corrupt_custody_denies_attempt_preflight_without_repair_or_append(tmp_path):
    ledger, grant = _claimed(tmp_path)
    path = ledger.path / "0000000000.json"
    record = json.loads(path.read_bytes())
    record["sha256"] = "f" * 64
    path.write_text(json.dumps(record), encoding="utf-8")
    before = _bytes(ledger)
    for action in (ledger.preflight_attempt, ledger.attempt):
        with pytest.raises(AuthorizationError, match="USAGE_LEDGER_INVALID"):
            action(grant, WORKER, **_scope())
        assert _bytes(ledger) == before


def test_new_route_lookup_does_not_reuse_another_routes_spent_attempt(tmp_path):
    ledger, grant = _claimed(tmp_path)
    ledger.attempt(grant, WORKER, **_scope())
    fpl = dict(
        provider="FPL",
        method="GET",
        host="fantasy.premierleague.com",
        path="/api/bootstrap-static/",
        now=NOW,
    )
    before = _bytes(ledger)
    ledger.preflight_attempt(grant, WORKER, **fpl)
    assert _bytes(ledger) == before
    ledger.attempt(grant, WORKER, **fpl)
    assert ledger.audit().attempt_count == 2


def test_revoked_installed_scope_denies_before_transaction_or_lookup(tmp_path, monkeypatch):
    file_ledger, approval, request, _ = setup(tmp_path)
    # Hypothetical installed approval and PG-discriminated hooks are injected
    # over an OWNED file history solely to exercise shared revocation policy.
    private = approval.model_copy(
        update={
            "classification": "PRIVATE_CURRENT",
            "ledger_backend": "POSTGRES",
            "qualified_deadline_at": request.deadline_at,
            "source_scopes": tuple(
                row.model_copy(update={"source_kind": "RIGHTS_QUALIFIED_PRIVATE"})
                for row in approval.source_scopes
            ),
        }
    )
    private_request = request.model_copy(update={"source_scopes": private.source_scopes})
    monkeypatch.setattr(auth, "production_approvals", lambda: (private,))
    ledger = UsageLedger(
        file_ledger.ledger_id,
        backend="POSTGRES",
        transaction=file_ledger._file_transaction,
        append=file_ledger._file_append,
    )
    grant = RefreshAuthorizer(ledger, clock=lambda: NOW).authorize(private_request)
    ledger.claim(grant, WORKER, now=NOW)
    before = _bytes(file_ledger)
    monkeypatch.setattr(
        auth, "production_approvals", lambda: (private.model_copy(update={"status": "REVOKED"}),)
    )
    ledger._transaction = lambda: pytest.fail("revoked grant touched custody storage")
    for action in (ledger.preflight_attempt, ledger.attempt):
        with pytest.raises(AuthorizationError, match="REFRESH_GRANT_INVALID"):
            action(grant, WORKER, **_scope())
    assert _bytes(file_ledger) == before


def test_private_test_database_selector_denies_attempt_preflight_before_connection(tmp_path):
    _, grant = _claimed(tmp_path)
    private = grant.model_copy(
        update={"classification": "PRIVATE_CURRENT", "ledger_backend": "POSTGRES"}
    )
    ledger = PostgresUsageLedger(
        lambda: pytest.fail("private TEST selector reached DB"),
        grant.ledger_id,
        account_ref="owned-test-account",
        database_ref="SYNTHETIC_TEST_DATABASE",
    )
    with pytest.raises(AuthorizationError, match="PRIVATE_CONTROL_DATABASE_REQUIRED"):
        ledger.preflight_attempt(private, WORKER, **_scope())
