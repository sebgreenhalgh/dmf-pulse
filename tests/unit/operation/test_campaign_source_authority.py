"""Caller objects cannot substitute for fixed campaign/source authority.

All authority and canonical custody below are explicit owned monkeypatches.
No PostgreSQL connection, credential service or provider transport is invoked.
"""

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest

from dmf_pulse.operation import campaign_journal, campaign_runtime
from dmf_pulse.operation.campaign_journal import DiagnosticJournal
from dmf_pulse.operation.campaign_sources import DiagnosticGuard
from dmf_pulse.operation.diagnostics import DiagnosticLog
from dmf_pulse.operation.enrollment import installed_enrollment
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.quota import QUOTA_HOST, QUOTA_PATH
from tests.unit.operation.standing_support import NOW, owned_policy
from tests.unit.operation.test_campaign import proposal

KEY = "f" * 64


@pytest.fixture
def owned_authority(monkeypatch, tmp_path):
    policy = owned_policy(tmp_path)
    campaign = proposal().model_copy(
        update={"original_ledger_id": policy.ledger_id, "odds_account_ref": policy.odds_account_ref}
    )
    authority = SimpleNamespace(
        normal_policy=policy,
        proposal=campaign,
        signed_campaign=SimpleNamespace(semantic_sha256="a" * 64),
    )
    rows = [
        {
            "kind": "LAUNCH",
            "execution_key": KEY,
            "at": NOW - timedelta(seconds=1),
            "payload": {
                "value": {
                    "execution_class": "GW10_DIAGNOSTIC",
                    "campaign_id": campaign.campaign_id,
                    "campaign_policy_sha256": campaign.semantic_sha256,
                    "subtype": "SESSION",
                    "session_index": 1,
                    "launch_id": KEY,
                    "mode": "PAID_ELIGIBLE",
                    "lease_until": (NOW + timedelta(minutes=30)).isoformat(),
                    "authority_sha256": authority.signed_campaign.semantic_sha256,
                }
            },
        }
    ]
    events = []
    clock = [NOW]
    connection = object()

    class Original:
        def __init__(self, current_policy):
            self.policy = current_policy

        @contextmanager
        def _transaction(self):
            events.append("OWNED_CANONICAL_CUSTODY_READ")
            yield connection, rows

    def fixed_loader():
        events.append("FIXED_SIGNED_LOADER")
        return authority

    def utc_now():
        return clock[0]

    canonical = DiagnosticJournal(Original(policy))

    def caller_transaction():
        raise AssertionError("caller custody must never populate installed qualification")

    caller = SimpleNamespace(
        original=SimpleNamespace(policy=policy), _transaction=caller_transaction
    )
    monkeypatch.setattr(campaign_journal, "load_verified_campaign", fixed_loader)
    monkeypatch.setattr(DiagnosticJournal, "production", classmethod(lambda cls: canonical))
    monkeypatch.setattr(campaign_runtime, "_production_utc_now", utc_now)
    assert campaign_runtime.campaign_runtime_enrollment() is None
    yield SimpleNamespace(
        policy=policy,
        authority=authority,
        canonical=canonical,
        caller=caller,
        original_type=Original,
        events=events,
        clock=clock,
        utc_now=utc_now,
        connection=connection,
        rows=rows,
    )
    assert campaign_runtime.campaign_runtime_enrollment() is None


@pytest.mark.parametrize("keyword", [False, True])
def test_caller_authority_loader_is_not_an_accepted_constructor_seam(owned_authority, keyword):
    owned = owned_authority
    if keyword:
        with pytest.raises(TypeError):
            DiagnosticJournal(owned.canonical.original, authority_loader=lambda: owned.authority)
    else:
        with pytest.raises(TypeError):
            DiagnosticJournal(owned.canonical.original, lambda: owned.authority)
    assert owned.events == []


def test_journal_uses_fixed_loader_before_reading_owned_canonical_custody(owned_authority):
    owned = owned_authority
    with owned.canonical._transaction() as (authority, connection, rows):
        assert (
            authority is owned.authority and connection is owned.connection and rows is owned.rows
        )
    assert owned.events == ["FIXED_SIGNED_LOADER", "OWNED_CANONICAL_CUSTODY_READ"]


@pytest.mark.parametrize("changed", ["limits", "qualification"])
def test_matching_account_and_ledger_do_not_hide_changed_full_policy(owned_authority, changed):
    owned = owned_authority
    if changed == "limits":
        forged = owned.policy.model_copy(
            update={"limits": owned.policy.limits.model_copy(update={"quota_max_age_seconds": 1})}
        )
    else:
        sources = owned.policy.qualifications
        forged = owned.policy.model_copy(
            update={
                "qualifications": (
                    sources[0].model_copy(update={"independent_review_sha256": "0" * 64}),
                    *sources[1:],
                )
            }
        )
    assert forged.ledger_id == owned.policy.ledger_id
    assert forged.odds_account_ref == owned.policy.odds_account_ref
    journal = DiagnosticJournal(owned.original_type(forged))
    with (
        pytest.raises(OperationError, match="DIAGNOSTIC_ORIGINAL_CONTROL_BINDING_CHANGED"),
        journal._transaction(),
    ):
        raise AssertionError("forged full policy accepted")
    assert owned.events == ["FIXED_SIGNED_LOADER"]


def test_context_uses_canonical_session_and_resets_even_after_owned_exception(owned_authority):
    owned = owned_authority
    with (
        pytest.raises(RuntimeError, match="owned unwind"),
        campaign_runtime.diagnostic_source_context(owned.caller, KEY) as canonical,
    ):
        assert canonical is owned.canonical and canonical is not owned.caller
        assert campaign_runtime.require_runtime(KEY).journal is canonical
        registry = installed_enrollment()
        assert not registry.approvals
        assert len(registry.qualifications) == 1
        assert registry.qualifications[0].scope.provider == "FPL"
        assert [route.path for route in registry.qualifications[0].scope.routes] == [
            "/api/bootstrap-static/"
        ]
        raise RuntimeError("owned unwind")
    assert owned.events == ["FIXED_SIGNED_LOADER", "OWNED_CANONICAL_CUSTODY_READ"]
    assert campaign_runtime.campaign_runtime_enrollment() is None


def test_context_refuses_foreign_policy_before_any_custody_read(owned_authority):
    owned = owned_authority
    forged = SimpleNamespace(
        original=SimpleNamespace(
            policy=owned.policy.model_copy(update={"owner_ref": "owned-other"})
        )
    )
    with (
        pytest.raises(OperationError, match="DIAGNOSTIC_ORIGINAL_CONTROL_BINDING_CHANGED"),
        campaign_runtime.diagnostic_source_context(forged, KEY),
    ):
        raise AssertionError("foreign policy entered context")
    assert owned.events == []


def test_context_rejects_caller_clock_and_fixed_clock_expires_actual_session(owned_authority):
    owned = owned_authority
    with (
        pytest.raises(TypeError),
        campaign_runtime.diagnostic_source_context(owned.caller, KEY, clock=lambda: NOW),
    ):
        raise AssertionError("caller clock accepted")
    assert owned.events == []
    owned.clock[0] = NOW + timedelta(minutes=31)
    with (
        pytest.raises(OperationError, match="DIAGNOSTIC_SESSION_CLOSED_CHANGED_OR_EXPIRED"),
        campaign_runtime.diagnostic_source_context(owned.caller, KEY),
    ):
        raise AssertionError("expired canonical session entered context")


@pytest.mark.parametrize("phase", ["prepaid", "paid"])
def test_frozen_diagnostic_clock_cannot_extend_authoritative_acquisition_window(
    owned_authority, phase
):
    owned = owned_authority
    with campaign_runtime.diagnostic_source_context(owned.caller, KEY) as canonical:
        log = DiagnosticLog(clock=lambda: NOW)
        with pytest.raises(TypeError):
            DiagnosticGuard(canonical, KEY, diagnostics=log, clock=lambda: NOW)
        guard = DiagnosticGuard(canonical, KEY, diagnostics=log)
        assert guard.clock is owned.utc_now
        runtime = campaign_runtime.require_runtime(KEY)
        if phase == "paid":
            runtime.paid_cutoff = NOW + timedelta(seconds=300)
            owned.clock[0] = NOW + timedelta(seconds=301)
        else:
            owned.clock[0] = NOW + timedelta(seconds=1201)
        with pytest.raises(OperationError, match="DIAGNOSTIC_ACQUISITION_WINDOW_EXPIRED"):
            guard.check()


@pytest.mark.parametrize("operation", ["guard", "paid_reservation", "provider_admission"])
def test_foreign_journal_object_cannot_use_active_canonical_source_context(
    owned_authority, operation
):
    owned = owned_authority
    foreign = DiagnosticJournal(owned.original_type(owned.policy))
    with campaign_runtime.diagnostic_source_context(owned.caller, KEY):
        before = list(owned.events)
        with pytest.raises(OperationError, match="DIAGNOSTIC_VERIFIED_PROCESS_SCOPE_REQUIRED"):
            if operation == "guard":
                DiagnosticGuard(foreign, KEY, diagnostics=DiagnosticLog())
            elif operation == "paid_reservation":
                # Foreign identity must fail before reading even typed gate data.
                foreign.reserve_paid(KEY, None, None, model_cutoff=NOW, now=NOW)
            else:
                foreign.admit_provider(
                    KEY, "QUOTA", "GET", QUOTA_HOST, QUOTA_PATH, phase="INITIAL", now=NOW
                )
        assert owned.events == before
