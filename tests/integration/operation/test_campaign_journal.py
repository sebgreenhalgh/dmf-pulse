"""Real owned PostgreSQL, injected owned authority, and no football transport."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from dmf_pulse.operation.campaign import DiagnosticPaidGateProof
from dmf_pulse.operation.campaign_journal import DiagnosticJournal
from dmf_pulse.operation.campaign_runtime import (
    bind_official_discovery,
    campaign_runtime_enrollment,
    diagnostic_source_context,
)
from dmf_pulse.operation.diagnostics import DiagnosticLog
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.quota import QUOTA_HOST, QUOTA_PATH
from tests.integration.operation import test_standing_journal as support
from tests.unit.operation.standing_support import NOW, owned_event, owned_quota
from tests.unit.operation.test_campaign import proposal

case = support.case
journal_engine = support.journal_engine
clean_postgres_test = support.clean_postgres_test
pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def campaign_case(case, monkeypatch):
    policy = proposal().model_copy(
        update={
            "created_at": NOW - timedelta(minutes=30),
            "original_ledger_id": case.policy.ledger_id,
            "odds_account_ref": case.policy.odds_account_ref,
            "entry_id": case.policy.entry_id,
        }
    )
    from dmf_pulse.operation import campaign_journal

    monkeypatch.setattr(campaign_journal, "CAMPAIGN_POLICY_SHA", policy.semantic_sha256)
    # This test-only injected authority does not exercise the production fixed
    # file/signature boundary; that boundary has separate RSA adversarial tests.
    authority = SimpleNamespace(
        proposal=policy,
        normal_policy=case.policy,
        signed_campaign=SimpleNamespace(semantic_sha256="f" * 64),
        acceptance=SimpleNamespace(
            semantic_sha256="a" * 64, accepted_at=NOW - timedelta(minutes=20)
        ),
    )
    now = [NOW]
    monkeypatch.setattr(campaign_journal, "load_verified_campaign", lambda: authority)
    journal = DiagnosticJournal(case.journal)
    monkeypatch.setattr(DiagnosticJournal, "production", classmethod(lambda cls: journal))
    from dmf_pulse.operation import campaign_runtime

    monkeypatch.setattr(campaign_runtime, "_production_utc_now", lambda: now[0])
    return SimpleNamespace(journal=journal, original=case, now=now, authority=authority)


def request(c, key, provider, host, path, *, phase=None):
    c.now[0] += timedelta(seconds=1)
    identity = c.journal.admit_provider(key, provider, "GET", host, path, phase=phase, now=c.now[0])
    c.journal.record_transport(key, identity, "TRANSPORT_STARTED", now=c.now[0])
    c.journal.record_transport(key, identity, "RESPONSE_COMPLETED", now=c.now[0], http_status=200)
    return identity


def quota(c, key, phase, *, used=0):
    request(c, key, "QUOTA", QUOTA_HOST, QUOTA_PATH, phase=phase)
    proof = owned_quota(c.original.policy, now=c.now[0] + timedelta(seconds=5), used=used)
    c.journal.record_quota(key, phase, proof, now=c.now[0])
    return proof


def discover(c, key):
    request(c, key, "FPL", "fantasy.premierleague.com", "/api/bootstrap-static/")
    c.now[0] += timedelta(seconds=5)
    event = owned_event(now=c.now[0])
    bind_official_discovery(key, event)
    return event


def gate(c, key, event):
    c.now[0] += timedelta(seconds=1)
    fpl_at = c.now[0]
    c.journal.record_stage(key, "FPL_VALIDATION", "1" * 64, now=fpl_at)
    c.now[0] += timedelta(seconds=1)
    controlled_at = c.now[0]
    c.journal.record_stage(key, "CONTROLLED_GATE", "2" * 64, now=controlled_at)
    observed = quota(c, key, "PRE_PAID")
    proof = DiagnosticPaidGateProof(
        campaign_sha256=c.authority.proposal.semantic_sha256,
        session_index=1,
        fpl_validation_sha256="1" * 64,
        controlled_pipeline_sha256="2" * 64,
        controlled_classification="REAL_FPL_CONTROLLED_MARKET_ENGINEERING",
        actual_fpl_contracts_passed=True,
        stage8_stage9_stage12_passed=True,
        fpl_validation_completed_at=fpl_at,
        controlled_pipeline_completed_at=controlled_at,
        quota_received_at=observed.received_at,
        quota_remaining_credits=500,
        quota_used_credits=0,
        quota_reconciled_with_original_account=True,
        credential_expires_at=NOW + timedelta(hours=1),
        official_gameweek=10,
        official_deadline_at=event.deadline_at,
    )
    return proof, observed


def test_context_default_is_absent_and_reset_after_exception(campaign_case):
    c = campaign_case
    before = c.original.original.audit()
    session = c.journal.begin_session("READ_ONLY", now=NOW)
    assert campaign_runtime_enrollment() is None
    with (
        pytest.raises(RuntimeError, match="owned unwind"),
        diagnostic_source_context(c.journal, session.session_key),
    ):
        enrolled = campaign_runtime_enrollment()
        assert not enrolled.approvals
        assert len(enrolled.qualifications) == 1
        assert [route.path for route in enrolled.qualifications[0].scope.routes] == [
            "/api/bootstrap-static/"
        ]
        raise RuntimeError("owned unwind")
    assert campaign_runtime_enrollment() is None
    assert c.original.original.audit() == before
    assert not any(row["kind"] == "ENROLL" for row in support.rows(c.original))


def test_failed_initial_quota_consumes_phase_and_cannot_be_prepaid_retry(campaign_case):
    c = campaign_case
    session = c.journal.begin_session("PAID_ELIGIBLE", now=NOW)
    with diagnostic_source_context(c.journal, session.session_key):
        c.journal.admit_provider(
            session.session_key, "QUOTA", "GET", QUOTA_HOST, QUOTA_PATH, phase="INITIAL", now=NOW
        )
        with pytest.raises(OperationError, match="QUOTA_PHASE_EXHAUSTED"):
            c.journal.admit_provider(
                session.session_key,
                "QUOTA",
                "GET",
                QUOTA_HOST,
                QUOTA_PATH,
                phase="INITIAL",
                now=NOW,
            )
        with pytest.raises(OperationError, match="PRE_PAID_GATE_REQUIRED"):
            c.journal.admit_provider(
                session.session_key,
                "QUOTA",
                "GET",
                QUOTA_HOST,
                QUOTA_PATH,
                phase="PRE_PAID",
                now=NOW,
            )
        with pytest.raises(OperationError, match="INITIAL_QUOTA_REQUIRED"):
            c.journal.admit_provider(
                session.session_key,
                "FPL",
                "GET",
                "fantasy.premierleague.com",
                "/api/bootstrap-static/",
                now=NOW,
            )


def test_paid_gate_uses_actual_time_atomic_original_reservation_and_tight_cutoff(campaign_case):
    c = campaign_case
    session = c.journal.begin_session("PAID_ELIGIBLE", now=NOW)
    with diagnostic_source_context(c.journal, session.session_key):
        quota(c, session.session_key, "INITIAL")
        event = discover(c, session.session_key)
        proof, observed = gate(c, session.session_key, event)
        c.now[0] += timedelta(seconds=30)
        grant = c.journal.reserve_paid(
            session.session_key,
            proof,
            observed,
            model_cutoff=NOW + timedelta(seconds=1200),
            now=c.now[0],
        )
        assert grant.issued_at == c.now[0] > proof.fpl_validation_completed_at
        assert grant.request.information_cutoff == c.now[0] + timedelta(seconds=300)
        assert c.original.original.audit().reservation_count == 1
        assert c.original.original.audit().claim_count == 1
        request(
            c,
            session.session_key,
            "ODDS_PAID",
            "api.the-odds-api.com",
            "/v4/sports/soccer_epl/odds",
        )
        c.journal.settle_headers(session.session_key, support.headers(2), 200, now=c.now[0])
        c.journal.settle_headers(session.session_key, support.headers(2), 200, now=c.now[0])
        with pytest.raises(
            OperationError, match=r"SOURCE_ROUTE_ALREADY_ATTEMPTED|PROVIDER_BUDGET_EXHAUSTED"
        ):
            c.journal.admit_provider(
                session.session_key,
                "ODDS_PAID",
                "GET",
                "api.the-odds-api.com",
                "/v4/sports/soccer_epl/odds",
                now=c.now[0],
            )
    records = support.rows(c.original)
    assert not any(row["kind"] == "ENROLL" for row in records)
    assert (
        len([row for row in records if row["payload"]["value"].get("subtype") == "ACTUAL_QUOTA"])
        == 1
    )
    assert c.original.original.audit().attempt_count == 1


def test_expiry_denies_new_transport_but_keeps_late_response_failure_and_close(campaign_case):
    c = campaign_case
    session = c.journal.begin_session("READ_ONLY", now=NOW)
    with diagnostic_source_context(c.journal, session.session_key):
        c.journal.admit_provider(
            session.session_key, "QUOTA", "GET", QUOTA_HOST, QUOTA_PATH, phase="INITIAL", now=NOW
        )
        records = support.rows(c.original)
        identity = records[-1]["payload"]["value"]["request_id"]
        c.journal.record_transport(session.session_key, identity, "TRANSPORT_STARTED", now=NOW)
        c.now[0] = session.lease_until + timedelta(seconds=1)
        with pytest.raises(OperationError, match="CLOSED_CHANGED_OR_EXPIRED"):
            c.journal.admit_provider(
                session.session_key,
                "QUOTA",
                "GET",
                QUOTA_HOST,
                QUOTA_PATH,
                phase="PRE_PAID",
                now=c.now[0],
            )
        c.journal.record_transport(
            session.session_key, identity, "RESPONSE_COMPLETED", now=c.now[0], http_status=200
        )
    log = DiagnosticLog(clock=lambda: c.now[0])
    log.failed(TimeoutError("never retain message"))
    c.journal.terminate(
        session.session_key,
        diagnostics=log.report(),
        error_code="CURRENT_TRANSPORT_FAILED",
        now=c.now[0],
    )
    c.journal.close(session.session_key, worker_and_transports_quiescent=True, now=c.now[0])
    with pytest.raises(OperationError, match="NOT_FOUND_OR_ALREADY_QUIESCENT"):
        c.journal.record_transport(
            session.session_key, identity, "RESPONSE_COMPLETED", now=c.now[0], http_status=200
        )
    assert c.original.original.audit().event_count == 0


def test_next_session_requires_terminal_quiescence_and_exact_inspection(campaign_case):
    c = campaign_case
    first = c.journal.begin_session("READ_ONLY", now=NOW)
    log = DiagnosticLog(clock=lambda: NOW)
    log.failed(ValueError("owned"))
    c.journal.terminate(
        first.session_key, diagnostics=log.report(), error_code="CURRENT_TRANSPORT_FAILED", now=NOW
    )
    with pytest.raises(OperationError):
        c.journal.begin_session("READ_ONLY", now=NOW)
    terminal = support.rows(c.original)[-1]["sha256"]
    with pytest.raises(OperationError, match="CLOSED_TERMINAL_INSPECTION_REQUIRED"):
        c.journal.inspect_previous(first.session_key, terminal, now=NOW)
    c.journal.close(first.session_key, worker_and_transports_quiescent=True, now=NOW)
    c.journal.inspect_previous(first.session_key, terminal, now=NOW)
    assert c.journal.begin_session("READ_ONLY", now=NOW).session_index == 2


def test_complete_owned_quota_client_guard_transport_chain_records_real_boundary_events(
    campaign_case,
):
    from dmf_pulse.ingestion.odds.client import OddsHttpResponse
    from dmf_pulse.operation.campaign_sources import DiagnosticGuard, DiagnosticQuotaTransport
    from dmf_pulse.operation.quota import QuotaClient

    c = campaign_case
    session = c.journal.begin_session("READ_ONLY", now=NOW)

    class OwnedCredential:
        def get_credential(self):
            return "owned-no-provider-placeholder-value"

    class OwnedTransport:
        calls = 0

        def send(self, request, credential):
            assert request.path == QUOTA_PATH
            assert credential == "owned-no-provider-placeholder-value"
            self.calls += 1
            return OddsHttpResponse(200, "application/json", support.headers(0), b"")

    delegate = OwnedTransport()
    log = DiagnosticLog(clock=lambda: c.now[0])
    with diagnostic_source_context(c.journal, session.session_key):
        guard = DiagnosticGuard(c.journal, session.session_key, diagnostics=log)
        observed = QuotaClient(
            guard=guard,
            credential_provider=OwnedCredential(),
            transport=DiagnosticQuotaTransport(guard, delegate),
            clock=lambda: c.now[0],
        ).fetch(c.original.policy.quota_qualification, admission=guard.quota_admission)
    assert delegate.calls == 1
    assert observed.remaining_credits == 500 and observed.used_credits == 0
    assert [event.kind for event in log.report().events] == [
        "ADMITTED",
        "TRANSPORT_STARTED",
        "RESPONSE_COMPLETED",
    ]
    records = support.rows(c.original)
    assert [row["payload"]["value"]["subtype"] for row in records] == [
        "SESSION",
        "PROVIDER_ADMISSION",
        "TRANSPORT_STARTED",
        "RESPONSE_COMPLETED",
    ]
    assert c.original.original.audit().event_count == 0


def test_fresh_earlier_deadline_caps_quota_guard_and_canonical_active_session(campaign_case):
    from dmf_pulse.operation.campaign_sources import DiagnosticGuard

    c = campaign_case
    session = c.journal.begin_session("PAID_ELIGIBLE", now=NOW)
    with diagnostic_source_context(c.journal, session.session_key):
        quota(c, session.session_key, "INITIAL")
        event = discover(c, session.session_key)
        # The owned provider now reports an earlier deadline; persist it through
        # the same typed discovery method in a separate independent session.
    c.journal.terminate(
        session.session_key,
        diagnostics=DiagnosticLog(clock=lambda: c.now[0]).report(),
        error_code="CURRENT_TRANSPORT_FAILED",
        now=c.now[0],
    )
    terminal = support.rows(c.original)[-1]["sha256"]
    c.journal.close(session.session_key, worker_and_transports_quiescent=True, now=c.now[0])
    c.journal.inspect_previous(session.session_key, terminal, now=c.now[0])
    later = c.journal.begin_session("READ_ONLY", now=c.now[0])
    with diagnostic_source_context(c.journal, later.session_key):
        quota(c, later.session_key, "INITIAL")
        request(c, later.session_key, "FPL", "fantasy.premierleague.com", "/api/bootstrap-static/")
        c.now[0] += timedelta(seconds=5)
        early_event = owned_event(now=c.now[0]).model_copy(
            update={"deadline_at": c.now[0] + timedelta(seconds=10)}
        )
        bind_official_discovery(later.session_key, early_event)
        guard = DiagnosticGuard(
            c.journal,
            later.session_key,
            diagnostics=DiagnosticLog(clock=lambda: c.now[0]),
        )
        guard.check()
        c.now[0] = early_event.deadline_at
        with pytest.raises(OperationError, match="CLOSED_CHANGED_OR_EXPIRED"):
            guard.check()
        with pytest.raises(OperationError, match="CLOSED_CHANGED_OR_EXPIRED"):
            c.journal.check(later.session_key, now=c.now[0])
        assert event.deadline_at > early_event.deadline_at


def failed_unknown_paid(c, *, invoked=True, contradictory_headers=False):
    session = c.journal.begin_session("PAID_ELIGIBLE", now=NOW)
    with diagnostic_source_context(c.journal, session.session_key):
        quota(c, session.session_key, "INITIAL")
        event = discover(c, session.session_key)
        proof, observed = gate(c, session.session_key, event)
        c.journal.reserve_paid(
            session.session_key,
            proof,
            observed,
            model_cutoff=NOW + timedelta(seconds=1200),
            now=c.now[0],
        )
        identity = c.journal.admit_provider(
            session.session_key,
            "ODDS_PAID",
            "GET",
            "api.the-odds-api.com",
            "/v4/sports/soccer_epl/odds",
            now=c.now[0],
        )
        if invoked:
            c.journal.record_transport(
                session.session_key, identity, "TRANSPORT_STARTED", now=c.now[0]
            )
        if contradictory_headers:
            with pytest.raises(OperationError, match="CHARGED_QUOTA_HEADERS_CONTRADICT_LEDGER"):
                c.journal.settle_headers(session.session_key, support.headers(3), 500, now=c.now[0])
    finish_failure(c, session)
    return session


def finish_failure(c, session):
    log = DiagnosticLog(clock=lambda: c.now[0])
    log.failed(TimeoutError("owned timeout without source values"))
    c.journal.terminate(
        session.session_key,
        diagnostics=log.report(),
        error_code="CURRENT_TRANSPORT_FAILED",
        now=c.now[0],
    )
    terminal = support.rows(c.original)[-1]["sha256"]
    c.journal.close(session.session_key, worker_and_transports_quiescent=True, now=c.now[0])
    c.journal.inspect_previous(session.session_key, terminal, now=c.now[0])


@pytest.mark.parametrize("delta", [0, 1])
def test_zero_or_partial_fresh_counter_delta_never_clears_unknown_paid_use(campaign_case, delta):
    c = campaign_case
    failed_unknown_paid(c)
    before = c.original.original.audit()
    later = c.journal.begin_session("READ_ONLY", now=c.now[0])
    with diagnostic_source_context(c.journal, later.session_key):
        observed = quota(c, later.session_key, "INITIAL", used=delta)
        with pytest.raises(OperationError, match="PAID_CONSUMPTION_UNRESOLVED"):
            c.journal.reconcile_initial_counter(later.session_key, observed, now=c.now[0])
    finish_failure(c, later)
    with pytest.raises(OperationError, match="PAID_CONSUMPTION_UNRESOLVED"):
        c.journal.begin_session("PAID_ELIGIBLE", now=c.now[0])
    assert c.original.original.audit() == before


def test_exact_full_delta_reconciles_one_invoked_unsettled_request_without_refund(campaign_case):
    c = campaign_case
    failed_unknown_paid(c)
    before = c.original.original.audit()
    later = c.journal.begin_session("READ_ONLY", now=c.now[0])
    with diagnostic_source_context(c.journal, later.session_key):
        observed = quota(c, later.session_key, "INITIAL", used=2)
        c.journal.reconcile_initial_counter(later.session_key, observed, now=c.now[0])
    assert c.original.original.audit() == before
    assert before.reservation_count == before.attempt_count == 1
    period = c.original.journal.qualify_quota(observed, now=c.now[0])
    assert period.expected_used_credits == 2
    finish_failure(c, later)
    assert c.journal.begin_session("PAID_ELIGIBLE", now=c.now[0]).session_index == 3


@pytest.mark.parametrize("invoked,headers", [(False, False), (True, True)])
def test_counter_delta_cannot_invent_invocation_or_override_contradictory_headers(
    campaign_case, invoked, headers
):
    c = campaign_case
    failed_unknown_paid(c, invoked=invoked, contradictory_headers=headers)
    later = c.journal.begin_session("READ_ONLY", now=c.now[0])
    with diagnostic_source_context(c.journal, later.session_key):
        observed = quota(c, later.session_key, "INITIAL", used=2)
        with pytest.raises(OperationError, match="EXACT_UNSETTLED_PRIOR_INVOCATION_REQUIRED"):
            c.journal.reconcile_initial_counter(later.session_key, observed, now=c.now[0])
    assert not any(
        row["payload"]["value"].get("subtype") == "COUNTER_RECONCILIATION"
        for row in support.rows(c.original)
    )
