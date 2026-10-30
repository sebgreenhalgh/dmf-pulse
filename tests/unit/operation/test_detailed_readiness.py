"""Operator facts stay distinct from account/source/grant acceptance."""

import json
from datetime import timedelta

import pytest
from typer.testing import CliRunner

from dmf_pulse.credentials.service import CredentialService, CredentialStatus
from dmf_pulse.operation.cli import operation_app
from dmf_pulse.operation.models import STAGES
from dmf_pulse.operation.readiness import detailed_readiness
from tests.unit.player_lab.real_support import AT

pytestmark = pytest.mark.unit


def test_passive_detailed_report_never_checks_vault_or_grants_authority(monkeypatch):
    monkeypatch.setattr(CredentialService, "status", lambda *a: pytest.fail("passive vault read"))
    report = detailed_readiness(now=AT)
    assert tuple(row.stage for row in report.readiness.checks) == STAGES
    assert all(row.state != "VERIFIED" for row in report.readiness.checks)
    assert len(report.missing_account_facts) == 22
    assert (
        report.account_input_state == "NOT_SUPPLIED" and report.reported_remaining_credits is None
    )
    assert report.enrollment_state == "MISSING_TRUSTED_DEFAULT"
    assert (
        report.provider_requests == 0
        and not report.reservation_created
        and not report.production_active
    )
    assert all(row.state == "NOT_CHECKED" for row in report.credentials)


def test_explicit_presence_keeps_actual_fresh_fpl_expiry_separate(monkeypatch):
    calls = []

    def status(self, provider):
        calls.append(provider)
        return (
            CredentialStatus(True, "CONFIGURED", AT + timedelta(hours=2), AT - timedelta(minutes=1))
            if provider == "fpl"
            else CredentialStatus(True, "CONFIGURED")
        )

    monkeypatch.setattr(CredentialService, "status", status)
    report = detailed_readiness(now=AT, check_credentials=True)
    assert calls == ["odds", "fpl"]
    assert report.credentials[1].expires_at == AT + timedelta(hours=2)
    assert report.credentials[1].registered_at == AT - timedelta(minutes=1)
    verified = [row.stage for row in report.readiness.checks if row.state == "VERIFIED"]
    assert verified == ["CREDENTIALS_CONFIGURED"]
    assert not any(row.provider_authentication_performed for row in report.credentials)


def test_cli_detailed_report_has_concrete_remedies_without_private_manager():
    result = CliRunner().invoke(operation_app, ["readiness"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)["payload"]
    assert len(report["readiness"]["checks"]) == 8
    assert any("--fresh-issued" in row for row in report["operator_actions"])
    assert any("operation launch" in row for row in report["operator_actions"])
    assert report["actual_information_set"] == "NONE_ACQUIRED_BY_READINESS"


def test_passed_deadline_stays_expired_without_inventing_next_gameweek():
    report = detailed_readiness(now=AT + timedelta(days=2))
    assert report.next_deadline_candidate.status == "EXPIRED_NEXT_DEADLINE_UNRESOLVED"
    assert not report.next_deadline_candidate.execution_authorized
