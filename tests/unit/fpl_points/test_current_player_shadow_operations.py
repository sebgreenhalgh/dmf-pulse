"""No network/storage compiler and probe tests; all acquisition is mocked."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.fpl_points.current_player_posterior import load_historical_rate_resource
from dmf_pulse.fpl_points.current_player_shadow import compile_current_player_shadow
from tests.unit.fpl_points.current_shadow_support import load_r9b_script, synthetic_inputs

probe = load_r9b_script("probe_current_player_posterior_shadow")

pytestmark = pytest.mark.unit


def test_compiler_and_observation_do_not_write_or_fetch(repository_root, monkeypatch):
    inputs, snapshot = synthetic_inputs(repository_root, with_snapshot=True)

    def blocked(*args, **kwargs):
        raise AssertionError("unexpected IO")

    monkeypatch.setattr(Path, "write_text", blocked)
    monkeypatch.setattr(Path, "write_bytes", blocked)
    monkeypatch.setattr(probe.DirectFplClient, "fetch", blocked)
    shadow = compile_current_player_shadow(**inputs)
    summary = probe.observe_snapshot(snapshot)
    assert summary["fpl_acquisition_requests"] == 11
    assert summary["fpl_endpoint_classes"] == snapshot.endpoint_classes
    assert (
        summary["new_network_requests"]
        == summary["stage7_11_invocations"]
        == summary["odds_requests"]
        == 0
    )
    assert shadow.model_input_status == summary["model_input_status"] == "SHADOW_NOT_MODEL_INPUT"
    assert "source_body" not in shadow.model_dump_json()
    assert not {"credential", "token", "raw_body", "names"} & set(type(shadow).model_fields)


def test_operator_arguments_fail_before_any_client(repository_root, monkeypatch, capsys):
    def blocked(*args, **kwargs):
        raise AssertionError("client must not be constructed")

    monkeypatch.setattr(probe, "DirectFplClient", blocked)
    assert probe.run_operator(42, None, False)["fpl_acquisition_requests"] == 0
    assert probe.run_operator(-1, None, False)["status"] == "BLOCKED"
    assert probe.main(["--entry-id", "DO_NOT_ECHO_PRIVATE_VALUE"]) == 2
    assert "DO_NOT_ECHO_PRIVATE_VALUE" not in capsys.readouterr().err


def test_operator_mocked_acquisition_safe_success_and_sanitized_failure(
    repository_root, monkeypatch, capsys
):
    _, snapshot = synthetic_inputs(repository_root, with_snapshot=True)

    class FakeClient:
        request_count = 11

        def __init__(self, *args, **kwargs):
            return None

    monkeypatch.setattr(probe, "DirectFplClient", FakeClient)
    monkeypatch.setattr(probe, "acquire_direct_fpl_snapshot", lambda *args, **kwargs: snapshot)
    profile = probe.load_rights_profiles()[probe.DIRECT_FPL_PROFILE_ID]

    def clock():
        return datetime(2026, 9, 16, 12, tzinfo=UTC)

    result = probe.run_operator(42, profile.human_approval_id, True, clock=clock)
    assert result["status"] == "SHADOW_OBSERVATION_ONLY"

    def fail(*args, **kwargs):
        raise ValueError("DO_NOT_ECHO_PRIVATE_PROVIDER_VALUE")

    monkeypatch.setattr(probe, "observe_snapshot", fail)
    result = probe.run_operator(42, profile.human_approval_id, True, clock=clock)
    assert result["status"] == "BLOCKED"
    assert "DO_NOT_ECHO" not in json.dumps(result)
    monkeypatch.setattr(probe, "run_operator", lambda *args, **kwargs: result)
    assert probe.main(["--entry-id", "42"]) == 2
    assert "DO_NOT_ECHO" not in capsys.readouterr().out


def test_resource_is_single_cached_historical_read_only():
    assert load_historical_rate_resource() is load_historical_rate_resource()
