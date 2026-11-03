"""Owned signed attribution is separate from paid HTTP evidence and authority."""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.operation import prior_usage as subject
from dmf_pulse.operation.maintenance import RootTrust, material_policy_sha256
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.quota import QUOTA_HOST, QUOTA_PATH
from dmf_pulse.operation.release_signatures import ReleaseManifest
from tests.unit.operation.standing_support import NOW, owned_policy, owned_quota
from tests.unit.operation.test_maintenance import KEY, seal


def owned_case(policy, monkeypatch):
    """Owned raw rows for pure validation only; PG tests authenticate real chains."""
    key, session, request = "a" * 64, "b" * 64, "c" * 64
    zero = owned_quota(policy, now=NOW - timedelta(minutes=5))
    observed = owned_quota(policy, now=NOW + timedelta(minutes=5), used=2)
    owner_at, when = NOW + timedelta(minutes=6), NOW + timedelta(minutes=7)
    rows = []

    def row(kind, value, seconds, execution_key=None):
        digest = canonical_sha256(["owned-row", len(rows)])
        item = {
            "kind": kind,
            "execution_key": execution_key,
            "at": NOW + timedelta(seconds=seconds),
            "sha256": digest,
            "payload": {"value": value},
        }
        rows.append(item)
        return item

    approval = "d" * 64
    z = row("QUOTA", {"proof": zero.model_dump(mode="json")}, -300)
    row(
        "ENROLL",
        {
            "event": {"target_gameweek": 10},
            "approval_sha256": approval,
            "quota": zero.model_dump(mode="json"),
        },
        -290,
        key,
    )
    row("LAUNCH", {"subtype": "SESSION", "mode": "PAID_ELIGIBLE", "session_index": 1}, 280, session)
    row(
        "LAUNCH",
        {
            "subtype": "PROVIDER_ADMISSION",
            "provider": "QUOTA",
            "phase": "INITIAL",
            "request_id": request,
            "route_sha256": canonical_sha256(["QUOTA", "GET", QUOTA_HOST, QUOTA_PATH]),
        },
        290,
        session,
    )
    row("LAUNCH", {"subtype": "TRANSPORT_STARTED", "request_id": request}, 295, session)
    row(
        "LAUNCH",
        {"subtype": "RESPONSE_COMPLETED", "request_id": request, "http_status": 200},
        295,
        session,
    )
    q = row(
        "QUOTA",
        {
            "subtype": "QUOTA",
            "phase": "INITIAL",
            "campaign_policy_sha256": subject.CAMPAIGN_POLICY_SHA,
            "proof": observed.model_dump(mode="json"),
        },
        300,
        session,
    )
    terminal = row(
        "FAILURE",
        {
            "subtype": "TERMINAL",
            "outcome": "FAILED",
            "error_code": "EXCLUSIVE_ACCOUNT_USAGE_CONTRADICTION",
        },
        301,
        session,
    )
    row(
        "CLOSE",
        {"subtype": "QUIESCENT_CLOSE", "worker_and_transports_quiescent": True},
        302,
        session,
    )
    row("CLOSE", {"subtype": "INSPECTION", "terminal_sha256": terminal["sha256"]}, 303, session)
    original = [
        {
            "kind": "RESERVATION",
            "reservation_id": "e" * 64,
            "sha256": "f" * 64,
            "ledger_id": policy.ledger_id,
            "at": (NOW - timedelta(minutes=10)).isoformat(),
            "account_sha256": canonical_sha256(policy.odds_account_ref),
            "authorization_sha256": canonical_sha256("OPR001-" + key),
            "approval_sha256": approval,
            "period": policy.calendar_anchor_at.isoformat(),
        }
    ]
    fact = subject.PriorUsageFact(
        owner_ref=policy.owner_ref,
        owner_reply_sha256=hashlib.sha256(b"owned prior-use statement").hexdigest(),
        owner_attribution_recorded_at=owner_at,
        ledger_id=policy.ledger_id,
        account_ref=policy.odds_account_ref,
        period_started_at=policy.calendar_anchor_at,
        period_resets_at=policy.calendar_anchor_resets_at,
        original_consumed_execution_key=key,
        reservation_id=original[0]["reservation_id"],
        reservation_record_sha256=original[0]["sha256"],
        previous_zero_quota_record_sha256=z["sha256"],
        observed_quota_record_sha256=q["sha256"],
        observed_quota=observed,
    )
    trust = RootTrust(
        review_public_key=KEY,
        review_public_key_sha256=KEY.fingerprint_sha256,
        owner_acceptance_sha256=policy.owner_acceptance_sha256,
        material_policy_sha256=material_policy_sha256(policy),
        original_ledger_id=policy.ledger_id,
        accepted_at=policy.accepted_at,
    )
    monkeypatch.setattr(subject, "REVIEW_KEY_SHA", KEY.fingerprint_sha256)
    monkeypatch.setattr(subject, "_installed_trust", lambda: trust)
    normal = seal(
        ReleaseManifest(
            wheel_sha256="2" * 64,
            implementation_sha=policy.implementation_sha,
            protected_numerical_sha256=policy.protected_numerical_sha256,
            material_policy_sha256=material_policy_sha256(policy),
            owner_acceptance_sha256=policy.owner_acceptance_sha256,
            original_ledger_id=policy.ledger_id,
            independent_review_sha256=policy.independent_review_sha256,
            installation_inventory_sha256="3" * 64,
            reviewer_ref="OWNED_NORMAL",
            reviewed_at=owner_at,
            release_class="WITHIN_POLICY_COMPATIBILITY",
            test_evidence_sha256=("4" * 64,),
        )
    )
    campaign = seal(
        normal.manifest.model_copy(
            update={
                "material_policy_sha256": subject.CAMPAIGN_POLICY_SHA,
                "owner_acceptance_sha256": subject.OWNER_SHA,
                "reviewer_ref": subject.CAMPAIGN_REVIEWER_ROLE,
                "reviewed_at": owner_at + timedelta(seconds=1),
                "test_evidence_sha256": (
                    subject.CAMPAIGN_PROPOSAL_SHA,
                    subject.OWNER_SHA,
                    "5" * 64,
                    normal.semantic_sha256,
                ),
            }
        )
    )
    signature = seal(
        campaign.manifest.model_copy(
            update={
                "reviewer_ref": subject.ROLE,
                "reviewed_at": owner_at + timedelta(seconds=2),
                "test_evidence_sha256": (
                    fact.semantic_sha256,
                    fact.owner_reply_sha256,
                    fact.observed_quota_record_sha256,
                    normal.semantic_sha256,
                ),
            }
        )
    )
    evidence = subject.PriorUsageEvidence(
        fact=fact, signed_fact=signature, normal_signed=normal, campaign_signed=campaign
    )
    return SimpleNamespace(
        policy=policy,
        trust=trust,
        fact=fact,
        evidence=evidence,
        rows=rows,
        original=original,
        now=when,
    )


@pytest.fixture
def prior(tmp_path, monkeypatch):
    return owned_case(owned_policy(tmp_path), monkeypatch)


def test_exact_owner_fact_accounts_two_without_http_or_history_rewrite(prior):
    p = prior
    before = deepcopy((p.rows, p.original, p.policy.model_dump(mode="json")))
    subject.verify_evidence(p.evidence, p.trust, p.policy, now=p.now)
    subject.validate_canonical_fact(p.fact, p.policy, p.rows, p.original, recorded_at=p.now)
    row = {
        "kind": "QUOTA",
        "sha256": "9" * 64,
        "execution_key": None,
        "at": p.now,
        "payload": {
            "value": {"subtype": subject.KIND, "evidence": p.evidence.model_dump(mode="json")}
        },
    }
    assert (
        subject.attributed_usage_credits(
            [*p.rows, row], p.original, p.policy, p.policy.calendar_anchor_at
        )
        == 2
    )
    assert (
        subject.attributed_usage_credits(
            [*p.rows, row], [], p.policy, p.policy.calendar_anchor_resets_at
        )
        == 0
    )
    assert (p.rows, p.original, p.policy.model_dump(mode="json")) == before
    assert p.fact.historical_http_proof == "NOT_HTTP_PROVEN"
    assert p.fact.observed_quota.last_request_cost == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewer_ref", "ORDINARY_STANDING"),
        ("material_policy_sha256", "7" * 64),
        ("owner_acceptance_sha256", "7" * 64),
        ("wheel_sha256", "7" * 64),
        ("implementation_sha", "7" * 40),
        ("installation_inventory_sha256", "7" * 64),
        ("original_ledger_id", "7" * 64),
        ("protected_numerical_sha256", "7" * 64),
        ("release_class", "INITIAL_STANDING_INSTALL"),
        ("test_evidence_sha256", ("7" * 64,)),
    ],
)
def test_even_valid_signature_cannot_change_prior_role_or_binding(prior, field, value):
    p = prior
    signed = seal(p.evidence.signed_fact.manifest.model_copy(update={field: value}))
    with pytest.raises(OperationError):
        subject.verify_evidence(
            p.evidence.model_copy(update={"signed_fact": signed}), p.trust, p.policy, now=p.now
        )


def test_signature_or_fact_substitution_is_not_authority(prior):
    p = prior
    for replacement in (
        p.evidence.normal_signed,
        p.evidence.campaign_signed,
        p.evidence.signed_fact.model_copy(update={"signature_b64": "A" * 512}),
    ):
        with pytest.raises(OperationError):
            subject.verify_evidence(
                p.evidence.model_copy(update={"signed_fact": replacement}),
                p.trust,
                p.policy,
                now=p.now,
            )
    with pytest.raises(OperationError):
        subject.verify_evidence(
            p.evidence.model_copy(
                update={"fact": p.fact.model_copy(update={"owner_reply_sha256": "8" * 64})}
            ),
            p.trust,
            p.policy,
            now=p.now,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("attributed_credits", 1),
        ("attributed_credits", 3),
        ("historical_http_proof", "HTTP_PROVEN"),
        ("historical_http_proof", True),
    ],
)
def test_fact_cannot_become_generic_usage_or_http_proof(prior, field, value):
    data = prior.fact.model_dump(mode="json")
    data[field] = value
    with pytest.raises(ValidationError):
        subject.PriorUsageFact.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_sha256", "9" * 64),
        ("authorization_sha256", "9" * 64),
        ("approval_sha256", "9" * 64),
        ("period", "2026-10-01T00:00:00Z"),
        ("reservation_id", "9" * 64),
        ("ledger_id", "9" * 64),
    ],
)
def test_original_reservation_identity_is_exact(prior, field, value):
    original = deepcopy(prior.original)
    original[0][field] = value
    with pytest.raises(OperationError):
        subject.validate_canonical_fact(
            prior.fact, prior.policy, prior.rows, original, recorded_at=prior.now
        )


@pytest.mark.parametrize(
    "subtype",
    [
        "SESSION",
        "PROVIDER_ADMISSION",
        "TRANSPORT_STARTED",
        "RESPONSE_COMPLETED",
        "TERMINAL",
        "QUIESCENT_CLOSE",
        "INSPECTION",
    ],
)
def test_missing_actual_chain_cannot_support_owner_attribution(prior, subtype):
    rows = [r for r in prior.rows if r["payload"]["value"].get("subtype") != subtype]
    with pytest.raises(OperationError):
        subject.validate_canonical_fact(
            prior.fact, prior.policy, rows, prior.original, recorded_at=prior.now
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_route",
        "http_error",
        "unclosed",
        "uninspected",
        "wrong_zero",
        "overlap",
        "paid_attempt",
        "duplicate",
    ],
)
def test_canonical_observation_and_overlap_fail_closed(prior, mutation):
    p = prior
    rows = deepcopy(p.rows)
    original = deepcopy(p.original)

    def event(subtype):
        return next(r for r in rows if r["payload"]["value"].get("subtype") == subtype)

    if mutation == "wrong_route":
        event("PROVIDER_ADMISSION")["payload"]["value"]["route_sha256"] = "0" * 64
    elif mutation == "http_error":
        event("RESPONSE_COMPLETED")["payload"]["value"]["http_status"] = 500
    elif mutation == "unclosed":
        event("QUIESCENT_CLOSE")["payload"]["value"]["worker_and_transports_quiescent"] = False
    elif mutation == "uninspected":
        event("INSPECTION")["payload"]["value"]["terminal_sha256"] = "0" * 64
    elif mutation == "wrong_zero":
        rows[1]["payload"]["value"]["quota"]["remaining_credits"] = 499
    elif mutation == "overlap":
        rows.append(
            {
                "kind": "SETTLEMENT",
                "sha256": "9" * 64,
                "execution_key": None,
                "at": p.now,
                "payload": {"value": {"reservation_id": p.fact.reservation_id}},
            }
        )
    elif mutation == "paid_attempt":
        from dmf_pulse.operation.journal import PAID_ROUTE_SHA

        original.append({"kind": "ATTEMPT", "route_sha256": PAID_ROUTE_SHA, "at": NOW.isoformat()})
    elif mutation == "duplicate":
        rows.append(deepcopy(event("PROVIDER_ADMISSION")))
    with pytest.raises(OperationError):
        subject.validate_canonical_fact(p.fact, p.policy, rows, original, recorded_at=p.now)


def test_duplicate_attribution_is_rejected_even_if_identical(prior):
    row = {
        "kind": "QUOTA",
        "sha256": "9" * 64,
        "execution_key": None,
        "at": prior.now,
        "payload": {
            "value": {"subtype": subject.KIND, "evidence": prior.evidence.model_dump(mode="json")}
        },
    }
    with pytest.raises(OperationError, match="DUPLICATE"):
        subject.attributed_usage_credits(
            [*prior.rows, row, row], prior.original, prior.policy, prior.policy.calendar_anchor_at
        )


@pytest.fixture
def fixed_files(prior, tmp_path, monkeypatch):
    p = prior
    root = tmp_path / "operator"
    base = root.parent / "GW10-diagnostics/prior-usage-001"
    base.mkdir(parents=True)
    review = {
        "state": "OWNER_ATTRIBUTED_PRIOR_USAGE_REVIEW_CLEAR",
        "unresolved_p0_p1": 0,
        "unresolved_material_p2": 0,
    }
    body = json.dumps(review).encode()
    signature = seal(
        p.evidence.signed_fact.manifest.model_copy(
            update={"independent_review_sha256": hashlib.sha256(body).hexdigest()}
        )
    )
    evidence = p.evidence.model_copy(update={"signed_fact": signature})
    (base / "evidence.json").write_text(evidence.model_dump_json(), encoding="utf-8")
    (base / "owner-response.txt").write_bytes(b"owned prior-use statement")
    (base / "technical-review.json").write_bytes(body)
    authority = SimpleNamespace(
        normal_policy=p.policy,
        normal_signed=evidence.normal_signed,
        signed_campaign=evidence.campaign_signed,
        proposal=SimpleNamespace(
            original_consumed_execution_key=p.fact.original_consumed_execution_key
        ),
    )
    monkeypatch.setattr(subject, "operator_root", lambda: root)
    monkeypatch.setattr(subject, "load_verified_campaign", lambda: authority)
    return SimpleNamespace(base=base, authority=authority, evidence=evidence)


def test_only_fixed_authenticated_files_can_load(prior, fixed_files):
    verified = subject.load_prior_usage_import()
    assert verified.evidence == fixed_files.evidence
    assert verified.policy == prior.policy
    with pytest.raises(TypeError):
        subject.load_prior_usage_import(acknowledged=True)
    with pytest.raises(TypeError):
        subject.load_prior_usage_import(path=fixed_files.base)


@pytest.mark.parametrize(
    "case", ["reply", "review", "normal", "campaign", "oldkey", "signature", "oversize"]
)
def test_fixed_loader_rejects_changed_owner_review_identity_or_signature(prior, fixed_files, case):
    f = fixed_files
    if case == "reply":
        (f.base / "owner-response.txt").write_bytes(b"another owned statement")
    elif case == "review":
        (f.base / "technical-review.json").write_bytes(b"{}")
    elif case == "normal":
        f.authority.normal_signed = f.evidence.campaign_signed
    elif case == "campaign":
        f.authority.signed_campaign = f.evidence.normal_signed
    elif case == "oldkey":
        f.authority.proposal.original_consumed_execution_key = "9" * 64
    elif case == "signature":
        bad = f.evidence.model_copy(
            update={
                "signed_fact": f.evidence.signed_fact.model_copy(
                    update={"signature_b64": "A" * 512}
                )
            }
        )
        (f.base / "evidence.json").write_text(bad.model_dump_json(), encoding="utf-8")
    else:
        (f.base / "evidence.json").write_bytes(b" " * 262145)
    with pytest.raises((OperationError, ValidationError)):
        subject.load_prior_usage_import()


def test_loader_authentication_precedes_all_file_reads(monkeypatch):
    def refuse():
        raise OperationError("DIAGNOSTIC_NORMAL_AUTHORITY_BINDING_CHANGED")

    monkeypatch.setattr(subject, "load_verified_campaign", refuse)
    monkeypatch.setattr(subject, "_body", lambda *_: pytest.fail("unauthenticated file read"))
    with pytest.raises(OperationError, match="NORMAL_AUTHORITY"):
        subject.load_prior_usage_import()


@pytest.mark.parametrize("value", [2.0, True, "2"])
def test_exact_credit_type_is_required(prior, value):
    data = prior.fact.model_dump(mode="json")
    data["attributed_credits"] = value
    with pytest.raises(ValidationError):
        subject.PriorUsageFact.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("fail_at", [None, "auth", "recovery", "append"])
def test_argument_free_cli_authenticates_and_recovers_before_append(monkeypatch, fail_at):
    from typer.testing import CliRunner

    from dmf_pulse.cli.app import app
    from dmf_pulse.operation import campaign_authority, journal, local_control

    calls = []
    policy = object()

    def authority():
        calls.append("auth")
        if fail_at == "auth":
            raise OperationError("DIAGNOSTIC_OWNER_AND_SIGNED_AUTHORITY_REQUIRED")
        return SimpleNamespace(normal_policy=policy)

    def recover(value):
        calls.append("recovery")
        assert value is policy
        if fail_at == "recovery":
            raise OperationError("ORIGINAL_SSPI_CONTROL_RECOVERY_FAILED")

    class Owned:
        def record_owner_attributed_prior_usage(self):
            calls.append("append")
            if fail_at == "append":
                raise OperationError("PRIOR_USAGE_DUPLICATE_OR_INVALID_ATTRIBUTION")
            return "9" * 64

    def production(value):
        calls.append("production")
        assert value is policy and calls[:2] == ["auth", "recovery"]
        return Owned()

    monkeypatch.setattr(campaign_authority, "load_verified_campaign", authority)
    monkeypatch.setattr(local_control, "recover_local_control", recover)
    monkeypatch.setattr(journal.OperationJournal, "production", production)
    result = CliRunner().invoke(app, ["operation", "reconcile-gw10-prior-usage"])
    if fail_at:
        assert result.exit_code == 2
        assert (
            calls
            == (
                {
                    "auth": ["auth"],
                    "recovery": ["auth", "recovery"],
                    "append": ["auth", "recovery", "production", "append"],
                }[fail_at]
            )
        )
    else:
        assert result.exit_code == 0
        value = json.loads(result.stdout)
        assert value["historical_http_proof"] == "NOT_HTTP_PROVEN"
        assert value["provider_requests"] == value["new_reservations"] == 0


def test_no_caller_fields_can_override_prior_usage_or_closed_bootstrap():
    from typer.testing import CliRunner

    from dmf_pulse.cli.app import app
    from tests.unit.operation.test_operator_bootstrap import bootstrap

    args = ["operation", "reconcile-gw10-prior-usage"]
    assert bootstrap().approved_arguments(args) == args
    for extra in (["--used", "2"], ["--acknowledged"], ["another-fact.json"]):
        with pytest.raises(ValueError):
            bootstrap().approved_arguments([*args, *extra])
        assert CliRunner().invoke(app, [*args, *extra]).exit_code == 2
