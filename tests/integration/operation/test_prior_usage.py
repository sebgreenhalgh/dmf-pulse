"""Owned PostgreSQL attribution custody, with explicitly injected test authority.

These cases exclude signature/file admission, which has separate RSA tests.
They use a disposable database and unique account through the guarded standing
fixture, and never call a provider or the real operator database.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from dmf_pulse.dashboard.authorization import RefreshAuthorizer, RefreshRequest
from dmf_pulse.operation import enrollment, prior_usage
from dmf_pulse.operation import journal as journal_module
from dmf_pulse.operation.prior_usage import PriorUsageEvidence, PriorUsageFact
from dmf_pulse.operation.release_signatures import ReleaseManifest, SignedReleaseManifest
from tests.integration.operation import test_standing_journal as support
from tests.unit.operation.standing_support import NOW, owned_event, owned_quota

case = support.case
journal_engine = support.journal_engine
clean_postgres_test = support.clean_postgres_test
pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def prior_case(case, monkeypatch):
    zero = owned_quota(case.policy, now=NOW + timedelta(seconds=1))
    case.journal.record_quota(zero, now=NOW)
    old_key, registry = support.admit(case, now=NOW + timedelta(seconds=1))
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
        deadline_at=owned_event(now=NOW + timedelta(seconds=1)).deadline_at,
    )
    authorizer = RefreshAuthorizer(case.journal.ledger, clock=lambda: NOW + timedelta(seconds=2))
    grant = authorizer.authorize(request)
    case.journal.ledger.claim(grant, support.WORKER, now=NOW + timedelta(seconds=3))
    with case.journal.ledger._sql_transaction() as original:
        reservation = next(row.copy() for row in original if row["kind"] == "RESERVATION")
    key = "d" * 64
    proof = owned_quota(case.policy, now=NOW + timedelta(seconds=18), used=2)
    common = {
        "execution_class": "GW10_DIAGNOSTIC",
        "campaign_id": "GW10-DIAGNOSTIC-CAMPAIGN-001",
        "campaign_policy_sha256": prior_usage.CAMPAIGN_POLICY_SHA,
        "authority_sha256": "e" * 64,
        "session_index": 1,
        "launch_id": key,
        "lease_until": (NOW + timedelta(minutes=30)).isoformat(),
    }

    def append(kind, subtype, value, second):
        with case.journal._transaction() as (connection, rows):
            return case.journal._append(
                connection,
                rows,
                kind,
                {**common, "subtype": subtype, **value},
                now=NOW + timedelta(seconds=second),
                key=key,
            )

    append("LAUNCH", "SESSION", {"mode": "PAID_ELIGIBLE", "reserved_credits": 0}, 10)
    from dmf_pulse.assurance.canonical import canonical_sha256

    request_id = "c" * 64
    append(
        "LAUNCH",
        "PROVIDER_ADMISSION",
        {
            "provider": "QUOTA",
            "phase": "INITIAL",
            "route_sha256": canonical_sha256(
                ["QUOTA", "GET", "api.the-odds-api.com", "/v4/sports/"]
            ),
            "request_id": request_id,
        },
        11,
    )
    append("LAUNCH", "TRANSPORT_STARTED", {"request_id": request_id, "http_status": None}, 12)
    append("LAUNCH", "RESPONSE_COMPLETED", {"request_id": request_id, "http_status": 200}, 13)
    quota_sha = append(
        "QUOTA", "QUOTA", {"phase": "INITIAL", "proof": proof.model_dump(mode="json")}, 14
    )
    terminal_sha = append(
        "FAILURE",
        "TERMINAL",
        {"outcome": "FAILED", "error_code": "EXCLUSIVE_ACCOUNT_USAGE_CONTRADICTION", "view": None},
        15,
    )
    append("CLOSE", "QUIESCENT_CLOSE", {"worker_and_transports_quiescent": True}, 16)
    append("CLOSE", "INSPECTION", {"terminal_sha256": terminal_sha}, 17)
    zero_row = next(row for row in support.rows(case) if row["kind"] == "QUOTA")
    fact = PriorUsageFact(
        owner_ref=case.policy.owner_ref,
        owner_reply_sha256="4" * 64,
        owner_attribution_recorded_at=NOW + timedelta(seconds=30),
        ledger_id=case.policy.ledger_id,
        account_ref=case.policy.odds_account_ref,
        period_started_at=case.policy.calendar_anchor_at,
        period_resets_at=case.policy.calendar_anchor_resets_at,
        original_consumed_execution_key=old_key,
        reservation_id=grant.reservation_id,
        reservation_record_sha256=reservation["sha256"],
        previous_zero_quota_record_sha256=zero_row["sha256"],
        observed_quota_record_sha256=quota_sha,
        observed_quota=proof,
    )
    # Deliberately invalid owned signature bytes: crypto is not bypassed in
    # production. This explicit test injection isolates real SQL custody only.
    manifest = ReleaseManifest(
        wheel_sha256="5" * 64,
        implementation_sha=case.policy.implementation_sha,
        protected_numerical_sha256=case.policy.protected_numerical_sha256,
        material_policy_sha256=prior_usage.CAMPAIGN_POLICY_SHA,
        owner_acceptance_sha256=prior_usage.OWNER_SHA,
        original_ledger_id=case.policy.ledger_id,
        independent_review_sha256="6" * 64,
        installation_inventory_sha256="7" * 64,
        reviewer_ref="OWNED_PRIOR_USAGE_CUSTODY_ONLY",
        reviewed_at=NOW + timedelta(seconds=31),
        release_class="WITHIN_POLICY_COMPATIBILITY",
        test_evidence_sha256=("8" * 64,),
    )
    signed = SignedReleaseManifest(
        manifest=manifest, review_public_key_sha256="9" * 64, signature_b64="A" * 512
    )
    evidence = PriorUsageEvidence(
        fact=fact, signed_fact=signed, normal_signed=signed, campaign_signed=signed
    )
    verified = SimpleNamespace(evidence=evidence, policy=case.policy)
    monkeypatch.setattr(prior_usage, "load_prior_usage_import", lambda: verified)
    monkeypatch.setattr(prior_usage, "_installed_trust", lambda: object())
    monkeypatch.setattr(prior_usage, "verify_evidence", lambda *_args, **_kwargs: None)

    class OwnedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            del tz
            return NOW + timedelta(seconds=40)

    monkeypatch.setattr(journal_module, "datetime", OwnedClock)
    return SimpleNamespace(case=case, fact=fact, verified=verified)


def test_attribution_is_one_new_fact_without_legacy_spend_or_settlement(prior_case):
    case = prior_case.case
    original_before = case.original.audit()
    rows_before = support.rows(case)

    recorded = case.journal.record_owner_attributed_prior_usage()

    rows_after = support.rows(case)
    assert case.original.audit() == original_before
    assert rows_after[:-1] == rows_before
    assert rows_after[-1]["sha256"] == recorded and rows_after[-1]["kind"] == "QUOTA"
    value = rows_after[-1]["payload"]["value"]
    assert value["subtype"] == prior_usage.KIND
    assert value["evidence"]["fact"]["historical_http_proof"] == "NOT_HTTP_PROVEN"
    assert value["evidence"]["fact"]["attributed_credits"] == 2
    assert not any(row["kind"] == "SETTLEMENT" for row in rows_after)
    current = owned_quota(case.policy, now=NOW + timedelta(seconds=45), used=2)
    period = case.journal.qualify_quota(current, now=NOW + timedelta(seconds=45))
    assert period.expected_used_credits == 2
    assert original_before.reservation_count == case.original.audit().reservation_count == 1


def test_duplicate_attribution_cannot_append_again_or_restore_a_reservation(prior_case):
    case = prior_case.case
    case.journal.record_owner_attributed_prior_usage()
    before = support.rows(case)
    original = case.original.audit()

    with pytest.raises(journal_module.OperationError, match="DUPLICATE_OR_INVALID_ATTRIBUTION"):
        case.journal.record_owner_attributed_prior_usage()

    assert support.rows(case) == before and case.original.audit() == original


@pytest.mark.parametrize("used", [0, 1, 3])
def test_attribution_never_explains_a_different_fresh_provider_counter(prior_case, used):
    case = prior_case.case
    case.journal.record_owner_attributed_prior_usage()
    before = support.rows(case)
    original = case.original.audit()
    quota = owned_quota(case.policy, now=NOW + timedelta(seconds=45), used=used)

    with pytest.raises(
        journal_module.OperationError, match="EXCLUSIVE_ACCOUNT_USAGE_CONTRADICTION"
    ):
        case.journal.qualify_quota(quota, now=NOW + timedelta(seconds=45))

    assert support.rows(case) == before and case.original.audit() == original


def test_failure_after_fact_insert_rolls_back_only_its_new_row(prior_case, monkeypatch):
    case = prior_case.case
    before = support.rows(case)
    original = case.original.audit()
    append = case.journal._append
    inserted = []

    def interrupted(connection, rows, kind, value, **kwargs):
        digest = append(connection, rows, kind, value, **kwargs)
        if value.get("subtype") == prior_usage.KIND:
            inserted.append(digest)
            raise journal_module.OperationError("OWNED_ROLLBACK_AFTER_INSERT")
        return digest

    monkeypatch.setattr(case.journal, "_append", interrupted)
    with pytest.raises(journal_module.OperationError, match="OWNED_ROLLBACK_AFTER_INSERT"):
        case.journal.record_owner_attributed_prior_usage()

    assert len(inserted) == 1
    assert support.rows(case) == before and case.original.audit() == original


@pytest.mark.parametrize(
    "field", ["reservation_id", "reservation_record_sha256", "original_consumed_execution_key"]
)
def test_wrong_canonical_identity_cannot_append_fact(prior_case, field):
    case = prior_case.case
    replacement = prior_case.fact.model_copy(update={field: "0" * 64})
    prior_case.verified.evidence = prior_case.verified.evidence.model_copy(
        update={"fact": replacement}
    )
    before = support.rows(case)
    original = case.original.audit()

    with pytest.raises(
        journal_module.OperationError, match="EXACT_OLD_RESERVATION_AND_EVENT_REQUIRED"
    ):
        case.journal.record_owner_attributed_prior_usage()

    assert support.rows(case) == before and case.original.audit() == original
