"""Unknown operational prerequisites remain unknown; reviewed drafts are not grants."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from dmf_pulse.dashboard.authorization import LedgerAudit
from dmf_pulse.operation import control
from dmf_pulse.operation.control import ControlRecoveryRequest, ControlSetupRequest
from dmf_pulse.operation.models import (
    STAGES,
    CredentialObservation,
    OperationError,
    OperatorReadiness,
    StageCheck,
    readiness,
)
from dmf_pulse.operation.packages import (
    OwnerPackage,
    PilotProposal,
    prepare_pilot,
    read_metadata,
    write_metadata,
)

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)


def test_default_status_has_eight_unknown_stages_and_no_automatic_reads(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("passive readiness touched a database or vault")

    monkeypatch.setattr(control.PostgresUsageLedger, "initialize", forbidden)
    monkeypatch.setattr(control.PostgresUsageLedger, "audit", forbidden)
    result = readiness(now=NOW)
    assert tuple(row.stage for row in result.checks) == STAGES
    assert all(row.state == "NOT_CHECKED" and row.checked_at is None for row in result.checks)
    assert result == readiness(now=NOW)


@pytest.mark.parametrize("state", ["MISSING", "EXPIRED", "UNAVAILABLE", "CORRUPT"])
def test_explicit_credential_observation_never_establishes_rights_or_entitlement(state):
    result = readiness(
        now=NOW,
        credentials=(
            CredentialObservation(provider="odds", configured=True, state="CONFIGURED"),
            CredentialObservation(provider="fpl", configured=False, state=state),
        ),
    )
    assert result.checks[1].state == "BLOCKED"
    assert all(row.state == "NOT_CHECKED" for row in (*result.checks[:1], *result.checks[2:]))


def test_both_configured_only_verifies_credential_presence():
    result = readiness(
        now=NOW,
        credentials=tuple(
            CredentialObservation(provider=provider, configured=True, state="CONFIGURED")
            for provider in ("odds", "fpl")
        ),
    )
    assert result.checks[1].state == "VERIFIED"
    assert sum(row.state == "VERIFIED" for row in result.checks) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "VERIFIED"},
        {"state": "BLOCKED"},
        {"checked_at": NOW},
        {"checked_at": NOW, "state": "VERIFIED", "evidence_sha256": ()},
    ],
)
def test_stages_cannot_fake_observation_or_verification(changes):
    with pytest.raises(ValidationError):
        StageCheck(stage="PROJECT_RIGHTS_APPROVED", **changes)


def test_duplicate_stages_and_production_activation_rejected():
    checked = StageCheck(
        stage="ENGINEERING_READY", state="VERIFIED", checked_at=NOW, evidence_sha256=("a" * 64,)
    )
    with pytest.raises(OperationError, match="DUPLICATE_READINESS_STAGE"):
        readiness(now=NOW, checks=(checked, checked))
    forbidden = StageCheck(
        stage="PRODUCTION_ACTIVE", state="VERIFIED", checked_at=NOW, evidence_sha256=("a" * 64,)
    )
    with pytest.raises(ValidationError, match="production activation"):
        readiness(now=NOW, checks=(forbidden,))
    with pytest.raises(ValidationError, match="canonical order"):
        OperatorReadiness(observed_at=NOW, checks=(checked,))


def test_prepare_pilot_preserves_unknown_owner_account_plan_and_all_fixed_caps():
    proposal = PilotProposal(authorization_id="ACCEL004-PILOT-unapproved")
    package = prepare_pilot(proposal, now=NOW)
    assert package.state == "INCOMPLETE"
    assert {
        "OWNER_APPROVAL_REQUIRED",
        "ACCOUNT_ENTITLEMENT_REQUIRED",
        "QUALIFIED_PLAN_QUOTA_REQUIRED",
        "PROJECT_RIGHTS_REVIEW_REQUIRED",
        "CANONICAL_LEDGER_REQUIRED",
    } <= set(package.blockers)
    assert package.runtime_authority == "NOT_GRANTED"
    assert (package.odds_gets, package.reserved_odds_credits, package.automatic_retries) == (
        1,
        2,
        0,
    )
    assert package.markets == ("h2h", "totals") and package.regions == "uk"
    assert package.horizon == 1 and package.usage == "ONE_SHOT"


@pytest.mark.parametrize(
    "attack", ["consumed_id", "secret", "budget", "fake_ready", "naive", "expired"]
)
def test_pilot_draft_rejects_authority_or_scope_shortcuts(attack):
    if attack == "consumed_id":
        with pytest.raises(ValidationError):
            PilotProposal(authorization_id="CURRENT-TEAM-STRENGTH-001V-A02")
    elif attack == "secret":
        with pytest.raises(ValidationError):
            PilotProposal.model_validate(
                {"authorization_id": "ACCEL004-PILOT-test", "api_key": "example"}
            )
    elif attack == "budget":
        package = prepare_pilot(PilotProposal(authorization_id="ACCEL004-PILOT-test"), now=NOW)
        with pytest.raises(ValidationError):
            OwnerPackage.model_validate({**package.model_dump(), "reserved_odds_credits": 1})
    elif attack == "fake_ready":
        package = prepare_pilot(PilotProposal(authorization_id="ACCEL004-PILOT-test"), now=NOW)
        with pytest.raises(ValidationError):
            OwnerPackage.model_validate(
                {
                    **package.model_dump(),
                    "state": "READY_FOR_INDEPENDENT_OWNER_REVIEW",
                    "blockers": (),
                }
            )
    elif attack == "naive":
        with pytest.raises(ValidationError):
            prepare_pilot(
                PilotProposal(authorization_id="ACCEL004-PILOT-test"), now=NOW.replace(tzinfo=None)
            )
    else:
        package = prepare_pilot(
            PilotProposal(
                authorization_id="ACCEL004-PILOT-test",
                qualified_deadline_at=NOW - timedelta(seconds=1),
            ),
            now=NOW,
        )
        assert "QUALIFIED_DEADLINE_EXPIRED" in package.blockers


def test_immutable_metadata_artifact_roundtrip_and_tamper_detection(tmp_path):
    package = prepare_pilot(PilotProposal(authorization_id="ACCEL004-PILOT-test"), now=NOW)
    path = tmp_path / "owner-package.json"
    digest = write_metadata(path, package)
    assert len(digest) == 64 and read_metadata(path, OwnerPackage) == package
    before = path.read_bytes()
    with pytest.raises(OperationError, match="WRITE_FAILED"):
        write_metadata(path, package)
    assert path.read_bytes() == before
    value = json.loads(before)
    value["payload"]["proposal"]["entry_id"] = 42
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(OperationError, match="ARTIFACT_INVALID"):
        read_metadata(path, OwnerPackage)


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"payload":{},"payload":{},"semantic_sha256":"x"}',
        b"x" * 131073,
        b"[" * 1500,
    ],
    ids=["empty", "duplicate", "oversize", "depth"],
)
def test_bounded_strict_metadata_reader(tmp_path, body):
    path = tmp_path / "invalid.json"
    path.write_bytes(body)
    with pytest.raises(OperationError, match="ARTIFACT_INVALID"):
        read_metadata(path, OwnerPackage)


def _setup_values():
    return dict(
        classification="OWNED_SYNTHETIC",
        account_ref="owned-account",
        operator_ref="owned-operator",
        database_ref="SYNTHETIC_TEST_DATABASE",
        control_metadata_retention_approved=True,
        control_permission_evidence_sha256="b" * 64,
    )


def test_control_setup_idempotency_and_recovery_never_initializes(monkeypatch):
    calls = []
    audit = LedgerAudit(
        ledger_id="a" * 64,
        backend="POSTGRES",
        event_count=5,
        head_sha256="c" * 64,
        reservation_count=1,
        claim_count=1,
        check_count=1,
        attempt_count=2,
        last_event_at=NOW,
    )

    class Ledger:
        def __init__(self, factory, ledger_id, **kwargs):
            assert ledger_id == audit.ledger_id
            calls.append("construct")

        @classmethod
        def initialize(cls, factory, **kwargs):
            calls.append("initialize")
            return cls(factory, audit.ledger_id, **kwargs)

        def audit(self):
            calls.append("audit")
            return audit

    monkeypatch.setattr(control, "PostgresUsageLedger", Ledger)
    setup = ControlSetupRequest(**_setup_values())
    initialized = control.init_control(setup, lambda: None, now=NOW)
    calls.clear()
    recovered = control.recover_control(
        ControlRecoveryRequest(**_setup_values(), ledger_id=audit.ledger_id), lambda: None, now=NOW
    )
    assert calls == ["construct", "audit"]
    assert recovered.audit == initialized.audit == audit
    assert recovered.provider_authority == "NOT_GRANTED"


def test_corrupt_or_missing_recovery_fails_without_initialization(monkeypatch):
    class Ledger:
        def __init__(self, *args, **kwargs):
            return

        def audit(self):
            raise control.OperationError("CONTROL_HISTORY_UNAVAILABLE")

        @classmethod
        def initialize(cls, *args, **kwargs):
            raise AssertionError("recovery recreated missing history")

    monkeypatch.setattr(control, "PostgresUsageLedger", Ledger)
    with pytest.raises(OperationError, match="CONTROL_HISTORY_UNAVAILABLE"):
        control.recover_control(
            ControlRecoveryRequest(**_setup_values(), ledger_id="a" * 64), lambda: None, now=NOW
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"control_metadata_retention_approved": 1},
        {"control_metadata_retention_approved": False},
        {"classification": "PRIVATE_CURRENT"},
        {"database_ref": "postgresql://not-an-identifier"},
        {"account_ref": "contains/credential-or-url"},
    ],
)
def test_control_requests_deny_before_connection(changes):
    with pytest.raises(ValidationError):
        ControlSetupRequest(**{**_setup_values(), **changes})


def test_constructed_private_test_setup_and_recovery_are_revalidated_before_factory():
    setup = ControlSetupRequest(**_setup_values())
    forged_setup = setup.model_copy(update={"classification": "PRIVATE_CURRENT"})
    recovery = ControlRecoveryRequest(**_setup_values(), ledger_id="a" * 64)
    forged_recovery = recovery.model_copy(update={"classification": "PRIVATE_CURRENT"})

    def forbidden():
        raise AssertionError("forged private selector reached a connection")

    for request, operation in (
        (forged_setup, control.init_control),
        (forged_recovery, control.recover_control),
    ):
        with pytest.raises(ValidationError, match="operator database"):
            operation(request, forbidden, now=NOW)


def test_expired_metadata_cannot_remain_verified_at_later_status():
    checked = StageCheck(
        stage="LIVE_PILOT_AUTHORIZED",
        state="VERIFIED",
        checked_at=NOW,
        valid_until=NOW + timedelta(seconds=1),
        evidence_sha256=("a" * 64,),
    )
    with pytest.raises(ValidationError, match="expired verified stage"):
        readiness(now=NOW + timedelta(seconds=2), checks=(checked,))
    expired = StageCheck(
        stage="LIVE_PILOT_AUTHORIZED",
        state="EXPIRED",
        checked_at=NOW + timedelta(seconds=2),
        valid_until=NOW + timedelta(seconds=1),
        evidence_sha256=("a" * 64,),
    )
    assert readiness(now=NOW + timedelta(seconds=2), checks=(expired,)).checks[5].state == "EXPIRED"


def test_metadata_reader_bounds_the_open_descriptor_after_size_race(tmp_path, monkeypatch):
    from dmf_pulse.operation import packages

    path = tmp_path / "grown.json"
    path.write_bytes(b"x" * 131074)
    monkeypatch.setattr(
        packages.os, "fstat", lambda _: SimpleNamespace(st_mode=stat.S_IFREG, st_size=0)
    )
    with pytest.raises(OperationError, match="ARTIFACT_INVALID"):
        read_metadata(path, OwnerPackage)


def test_nonregular_descriptor_is_rejected_before_json(tmp_path, monkeypatch):
    from dmf_pulse.operation import packages

    path = tmp_path / "regular-before-open.json"
    path.write_bytes(b"{}")
    monkeypatch.setattr(
        packages.os, "fstat", lambda _: SimpleNamespace(st_mode=stat.S_IFIFO, st_size=0)
    )
    monkeypatch.setattr(
        packages.json, "loads", lambda *_, **__: pytest.fail("nonregular input reached JSON")
    )
    with pytest.raises(OperationError, match="ARTIFACT_INVALID"):
        read_metadata(path, OwnerPackage)


def test_invalid_metadata_does_not_retain_raw_canary_in_error_chain_or_loader_frames(tmp_path):
    from dmf_pulse.operation import packages

    canary = "OWNED_SYNTHETIC_INVALID_METADATA_VALUE_DO_NOT_RETAIN"
    path = tmp_path / "invalid-private-field.json"
    path.write_text(
        json.dumps({"payload": {"api_key": canary}, "semantic_sha256": "a" * 64}), encoding="utf-8"
    )
    with pytest.raises(OperationError) as caught:
        read_metadata(path, OwnerPackage)
    error = caught.value
    assert error.__context__ is None and error.__cause__ is None
    assert canary not in repr(error.args)
    traceback = error.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_filename == packages.__file__:
            assert canary not in repr(traceback.tb_frame.f_locals)
        traceback = traceback.tb_next
