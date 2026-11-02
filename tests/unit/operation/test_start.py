"""Owned credential orchestration, one-launch admission and browser boundaries."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.dashboard.app import create_app
from dmf_pulse.dashboard.current import CurrentEligibility
from dmf_pulse.dashboard.runtime import DeskRuntime, JobState
from dmf_pulse.operation import start
from dmf_pulse.operation.models import ChargedQuotaStatus, OperationError
from tests.unit.dashboard.test_dashboard import request
from tests.unit.operation.standing_support import NOW, owned_policy


def test_public_start_refuses_without_one_time_accepted_policy():
    result = CliRunner().invoke(app, ["start"])
    assert result.exit_code == 2
    assert "STANDING_OWNER_ACCEPTANCE_REQUIRED" in result.output


def test_start_is_registered_without_hidden_required_parameters():
    result = CliRunner().invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    assert "--expires-at" not in result.output
    assert "--quota" not in result.output


def test_valid_fresh_v2_metadata_reused_without_secret_resolution(tmp_path):
    policy = owned_policy(tmp_path)
    expiry = NOW + timedelta(hours=1)
    service = SimpleNamespace(
        status=lambda p: SimpleNamespace(
            configured=p == "fpl", expires_at=expiry, registered_at=NOW - timedelta(minutes=1)
        )
    )
    assert (
        start.ensure_fpl_credential(
            policy,
            service=service,
            prompt=lambda **_: pytest.fail("valid metadata prompted"),
            clock=lambda: NOW,
        )
        == expiry
    )


@pytest.mark.parametrize("remaining,registered", [(-1, NOW), (1199, NOW), (3600, None)])
def test_one_secure_rotation_prompt_before_any_source_call(tmp_path, remaining, registered):
    policy = owned_policy(tmp_path)
    service = SimpleNamespace(
        status=lambda p: SimpleNamespace(
            configured=True, expires_at=NOW + timedelta(seconds=remaining), registered_at=registered
        )
    )
    calls = []

    def prompt(**kwargs):
        calls.append(kwargs)
        return NOW + timedelta(hours=1)

    assert start.ensure_fpl_credential(
        policy, service=service, prompt=prompt, clock=lambda: NOW
    ) == NOW + timedelta(hours=1)
    assert len(calls) == 1
    assert calls[0]["service"] is service
    assert calls[0]["minimum_remaining_seconds"] == 1200
    assert calls[0]["maximum_remaining_seconds"] == 86400


def test_preparation_guard_cannot_be_reused_for_charged_route(tmp_path, monkeypatch):
    policy = owned_policy(tmp_path)
    monkeypatch.setattr(start, "require_policy", lambda: policy)
    guard = start.PreparationGuard(policy, provider="ODDS", clock=lambda: NOW)
    with pytest.raises(OperationError, match="PREPARATION_ROUTE_OR_BUDGET_DENIED"):
        guard.before_send("ODDS", "GET", "api.the-odds-api.com", "/v4/sports/soccer_epl/odds")
    guard.before_send("ODDS", "GET", "api.the-odds-api.com", "/v4/sports/")
    with pytest.raises(OperationError, match="PREPARATION_ROUTE_OR_BUDGET_DENIED"):
        guard.before_send("ODDS", "GET", "api.the-odds-api.com", "/v4/sports/")


def test_withdrawn_or_changed_policy_denies_before_transport(tmp_path, monkeypatch):
    policy = owned_policy(tmp_path)
    guard = start.PreparationGuard(policy, provider="FPL", clock=lambda: NOW)
    monkeypatch.setattr(
        start, "require_policy", lambda: policy.model_copy(update={"policy_id": "CHANGED"})
    )
    with pytest.raises(OperationError, match="PREPARATION_AUTHORITY_CHANGED_OR_EXPIRED"):
        guard.discovery_before_send()
    assert not guard.attempted


def test_browser_refresh_and_reload_never_begin_second_acquisition(monkeypatch):
    calls = []
    monkeypatch.setattr(
        DeskRuntime, "refresh", lambda self, h: calls.append(h) or JobState(status="RUNNING")
    )
    monkeypatch.setattr(DeskRuntime, "tick", lambda self: JobState(status="RUNNING"))
    runtime = start.SingleAcquisitionRuntime(
        current_session=None, on_publication=lambda _: None, on_failure=lambda _: None
    )
    for _ in range(10):
        runtime.refresh(1)
    assert calls == [1]


def test_actual_charged_counters_remain_visible_when_forecasting_failed(monkeypatch):
    value = ChargedQuotaStatus(
        remaining_credits=498,
        used_credits=2,
        last_request_cost=2,
        received_at=NOW,
        provider_status=200,
        consistent_with_ledger=True,
        receipt_sha256="1" * 64,
    )
    calls = []
    monkeypatch.setattr(
        DeskRuntime,
        "eligibility",
        lambda _: CurrentEligibility(
            source_classification="PRIVATE_CURRENT",
            state="BLOCKED",
            error_code="CURRENT_SNAPSHOT_INVALID",
        ),
    )
    runtime = start.SingleAcquisitionRuntime(
        current_session=None,
        on_publication=lambda _: pytest.fail("No successful forecast exists"),
        on_failure=lambda _: None,
        quota_status=lambda: calls.append("read-committed-receipt") or value,
    )
    assert runtime.view() is None
    for _ in range(3):
        eligibility = runtime.eligibility()
        assert eligibility.actual_market_quota == value
        assert eligibility.error_code == "CURRENT_SNAPSHOT_INVALID"
    assert calls == ["read-committed-receipt"]


@pytest.mark.parametrize(
    "headers",
    [
        None,
        {
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
        },
        {"sec-fetch-site": "none", "sec-fetch-mode": "navigate", "sec-fetch-dest": "iframe"},
    ],
)
def test_one_command_browser_bootstrap_rejects_non_navigation(headers):
    runtime = DeskRuntime()
    application = create_app(
        runtime=runtime,
        pairing_code="UNUSED-STANDING-OWNED",
        port=8765,
        trusted_local_navigation=True,
    )
    status, _, _ = request(application, "/", headers=headers)
    assert status == 403
    assert request(application, "/api/context")[0] == 401


def test_direct_navigation_gets_private_cookie_without_any_pairing_paste():
    runtime = DeskRuntime()
    application = create_app(
        runtime=runtime,
        pairing_code="UNUSED-STANDING-OWNED",
        port=8765,
        trusted_local_navigation=True,
    )
    status, headers, _ = request(
        application,
        "/",
        headers={
            "sec-fetch-site": "none",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
        },
    )
    assert status == 200
    browser_session_header = headers["set-cookie"]
    assert "HttpOnly" in browser_session_header and "SameSite=strict" in browser_session_header
    assert (
        request(
            application, "/api/context", browser_header=browser_session_header.split(";", 1)[0]
        )[0]
        == 200
    )
    assert request(application, "/api/context")[0] == 401
    assert "set-cookie" not in request(application, "/")[1]
