"""Closed R9C-D1 probe diagnostics using only mocks and synthetic snapshots."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from tests.unit.fpl_points.current_shadow_support import load_r9b_script, synthetic_inputs

probe = load_r9b_script("probe_current_player_posterior_shadow")

pytestmark = pytest.mark.unit

SENTINELS = (
    "SECRET_BEARER_TOKEN_ABC123",
    "PRIVATE_ENTRY_999999",
    "PLAYER_NAME_SHOULD_NOT_LEAK",
    r"C:\\private\\operator\\path",
    "https://fantasy.premierleague.com/api/entry/999999/",
    '{"private":"body"}',
)


class FakeClient:
    def __init__(self, *args, request_count=11, **kwargs):
        self.request_count = request_count


def _clock() -> datetime:
    return datetime(2026, 9, 16, 12, tzinfo=UTC)


def _profile_reference() -> str:
    return probe.load_rights_profiles()[probe.DIRECT_FPL_PROFILE_ID].human_approval_id


def _assert_safe(result, capsys, caplog):
    rendered = json.dumps(result, sort_keys=True)
    captured = capsys.readouterr()
    for value in SENTINELS:
        assert value not in rendered
        assert value not in captured.out
        assert value not in captured.err
        assert value not in caplog.text
    assert set(result) == {
        "diagnostic_schema_version",
        "status",
        "reason_code",
        "failure_stage",
        "fpl_acquisition_requests",
        "odds_requests",
        "stage7_11_invocations",
        "persistence_performed",
        "model_training_performed",
        "model_input_status",
        "retry_performed",
    }
    assert result["diagnostic_schema_version"] == "r9c-shadow-probe-diagnostics-v1"
    assert result["odds_requests"] == result["stage7_11_invocations"] == 0
    assert result["persistence_performed"] is result["model_training_performed"] is False
    assert result["model_input_status"] == "SHADOW_NOT_MODEL_INPUT"
    assert result["retry_performed"] is False


def _raise_secret(*args, **kwargs):
    del args, kwargs
    try:
        raise RuntimeError(SENTINELS[0])
    except RuntimeError as cause:
        raise ValueError(SENTINELS[1]) from cause


def test_blocked_contract_is_closed_and_strict():
    result = probe.ShadowProbeBlockedResult(
        diagnostic_schema_version="r9c-shadow-probe-diagnostics-v1",
        status="BLOCKED",
        reason_code=probe.ShadowProbeFailureReason.FPL_ACQUISITION_FAILED,
        failure_stage=probe.ShadowProbeFailureStage.ACQUIRE_FPL_SNAPSHOT,
        fpl_acquisition_requests=6,
    )
    with pytest.raises(ValidationError):
        probe.ShadowProbeBlockedResult.model_validate(
            result.model_dump(mode="python") | {"unsafe_details": SENTINELS[0]}
        )
    with pytest.raises(ValidationError):
        probe.ShadowProbeBlockedResult.model_validate(
            result.model_dump(mode="python") | {"fpl_acquisition_requests": -1}
        )


def test_cli_prints_only_the_closed_blocked_payload(monkeypatch, capsys):
    blocked = probe._blocked(
        probe.ShadowProbeFailureReason.FPL_ACQUISITION_FAILED,
        probe.ShadowProbeFailureStage.ACQUIRE_FPL_SNAPSHOT,
        None,
    )
    monkeypatch.setattr(probe, "run_operator", lambda *args, **kwargs: blocked)

    assert probe.main(["--entry-id", "42"]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == blocked
    assert captured.err == ""
    for value in SENTINELS:
        assert value not in captured.out


@pytest.mark.parametrize(
    ("name", "patch_name", "reason", "stage"),
    (
        (
            "history",
            "build_current_player_history_evidence",
            "R9A_HISTORY_BUILD_FAILED",
            "BUILD_R9A_HISTORY",
        ),
        (
            "policy",
            "build_automatic_current_gw_stale_prior_policy",
            "STALE_PRIOR_POLICY_BUILD_FAILED",
            "BUILD_STALE_PRIOR_POLICY",
        ),
        (
            "binding",
            "build_current_gw_player_prior_binding",
            "CURRENT_PRIOR_BINDING_FAILED",
            "BUILD_CURRENT_PRIOR_BINDING",
        ),
        (
            "resource",
            "load_historical_rate_resource",
            "HISTORICAL_RESOURCE_LOAD_FAILED",
            "LOAD_HISTORICAL_RATE_RESOURCE",
        ),
        (
            "compile",
            "compile_current_player_shadow",
            "R9B_SHADOW_COMPILE_FAILED",
            "COMPILE_R9B_SHADOW",
        ),
        ("summary", "safe_shadow_summary", "SAFE_SUMMARY_FAILED", "BUILD_SAFE_SUMMARY"),
    ),
)
def test_stage_failures_are_closed_safe_and_preserve_acquisition_count(
    repository_root, monkeypatch, capsys, caplog, name, patch_name, reason, stage
):
    del name
    _, snapshot = synthetic_inputs(repository_root, with_snapshot=True)
    monkeypatch.setattr(probe, "DirectFplClient", FakeClient)
    calls = []

    def acquire(*args, **kwargs):
        calls.append((args, kwargs))
        return snapshot

    monkeypatch.setattr(probe, "acquire_direct_fpl_snapshot", acquire)
    monkeypatch.setattr(probe, patch_name, _raise_secret)
    caplog.set_level(logging.DEBUG)
    result = probe.run_operator(42, _profile_reference(), True, clock=_clock)
    assert result["status"] == "BLOCKED"
    assert (result["reason_code"], result["failure_stage"]) == (reason, stage)
    assert result["fpl_acquisition_requests"] == 11
    assert len(calls) == 1
    _assert_safe(result, capsys, caplog)


def test_rights_cutoff_acquisition_and_internal_boundaries(
    repository_root, monkeypatch, capsys, caplog
):
    del repository_root
    caplog.set_level(logging.DEBUG)
    confirmation = probe.run_operator(42, None, False, clock=_clock)
    assert (confirmation["reason_code"], confirmation["failure_stage"]) == (
        "RIGHTS_CONFIRMATION_FAILED",
        "VALIDATE_RIGHTS_REFERENCE",
    )
    _assert_safe(confirmation, capsys, caplog)

    def deny(*args, **kwargs):
        raise RuntimeError(SENTINELS[2])

    monkeypatch.setattr(probe, "require_rights", deny)
    capability = probe.run_operator(42, _profile_reference(), True, clock=_clock)
    assert (capability["reason_code"], capability["failure_stage"]) == (
        "RIGHTS_CAPABILITY_FAILED",
        "VALIDATE_RIGHTS_CAPABILITIES",
    )
    assert capability["fpl_acquisition_requests"] == 0
    _assert_safe(capability, capsys, caplog)


def test_cutoff_acquisition_six_request_shape_and_unexpected_are_closed(
    repository_root, monkeypatch, capsys, caplog
):
    _, snapshot = synthetic_inputs(repository_root, with_snapshot=True)
    caplog.set_level(logging.DEBUG)
    now = _clock()
    times = iter((now, now, now + timedelta(minutes=6)))
    monkeypatch.setattr(probe, "DirectFplClient", FakeClient)
    monkeypatch.setattr(probe, "acquire_direct_fpl_snapshot", lambda *args, **kwargs: snapshot)
    cutoff = probe.run_operator(42, _profile_reference(), True, clock=lambda: next(times))
    assert (cutoff["reason_code"], cutoff["failure_stage"]) == (
        "CUTOFF_WINDOW_FAILED",
        "FINAL_CUTOFF_CHECK",
    )
    _assert_safe(cutoff, capsys, caplog)

    class ProgressClient(FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, request_count=0, **kwargs)

    monkeypatch.setattr(probe, "DirectFplClient", ProgressClient)
    acquisitions = []

    def fails_after_six(*args, **kwargs):
        acquisitions.append(1)
        direct = args[0]
        direct.request_count += 6
        raise IngestionError("SOURCE_UNAVAILABLE", SENTINELS[0])

    monkeypatch.setattr(probe, "acquire_direct_fpl_snapshot", fails_after_six)
    six = probe.run_operator(42, _profile_reference(), True, clock=_clock)
    assert (six["reason_code"], six["failure_stage"], six["fpl_acquisition_requests"]) == (
        "FPL_ACQUISITION_FAILED",
        "ACQUIRE_FPL_SNAPSHOT",
        6,
    )
    assert acquisitions == [1]
    _assert_safe(six, capsys, caplog)

    monkeypatch.setattr(probe, "DirectFplClient", _raise_secret)
    internal = probe.run_operator(42, _profile_reference(), True, clock=_clock)
    assert (internal["reason_code"], internal["failure_stage"]) == (
        "UNEXPECTED_INTERNAL_FAILURE",
        "INTERNAL",
    )
    _assert_safe(internal, capsys, caplog)


def test_success_is_compatible_and_probe_never_writes_or_calls_recommendation(
    repository_root, monkeypatch, capsys, caplog
):
    _, snapshot = synthetic_inputs(repository_root, with_snapshot=True)
    monkeypatch.setattr(probe, "DirectFplClient", FakeClient)
    monkeypatch.setattr(probe, "acquire_direct_fpl_snapshot", lambda *args, **kwargs: snapshot)

    def no_write(*args, **kwargs):
        raise AssertionError("diagnostic probe attempted a file write")

    monkeypatch.setattr(Path, "write_text", no_write)
    monkeypatch.setattr(Path, "write_bytes", no_write)

    forbidden_calls = []

    def forbidden_service(*args, **kwargs):
        forbidden_calls.append((args, kwargs))
        raise AssertionError("recommendation or Odds service was invoked")

    # These sentinels deliberately model prohibited services; the dedicated shadow
    # probe has no dependency on either symbol and must leave them untouched.
    monkeypatch.setattr(probe, "run_private_recommendation", forbidden_service, raising=False)
    monkeypatch.setattr(probe, "acquire_odds", forbidden_service, raising=False)
    caplog.set_level(logging.DEBUG)
    result = probe.run_operator(42, _profile_reference(), True, clock=_clock)
    assert result["status"] == "SHADOW_OBSERVATION_ONLY"
    assert result["fpl_acquisition_requests"] == snapshot.request_count
    assert result["stage7_11_invocations"] == result["odds_requests"] == 0
    assert result["active_recommendation_path_changed"] is False
    assert result["persistence_performed"] is result["model_training_performed"] is False
    assert forbidden_calls == []
    assert "source_body" not in json.dumps(result)
    for value in SENTINELS:
        assert value not in json.dumps(result)
        assert value not in capsys.readouterr().out
        assert value not in caplog.text
