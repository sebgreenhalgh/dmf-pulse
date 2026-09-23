"""Offline closed diagnostics for every known post-comparison wrapper path."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timedelta

import pytest

from dmf_pulse.private_v1 import team_strength_live as live
from dmf_pulse.private_v1.team_strength_comparison import TeamStrengthComparisonRun
from dmf_pulse.private_v1.team_strength_diagnostics import (
    ComparisonReason,
    ComparisonStage,
    ComparisonTrace,
    TeamStrengthComparisonFailure,
)
from dmf_pulse.private_v1.team_strength_live_network import OneShotNetworkGate
from tests.unit.private_v1.team_strength_shadow_support import STAMP

pytestmark = pytest.mark.unit


def gate() -> OneShotNetworkGate:
    return OneShotNetworkGate(STAMP, STAMP + timedelta(minutes=5), lambda: STAMP, closed=True)


def service(active_gate: OneShotNetworkGate) -> live.TeamStrengthL1ObservationService:
    result = live.TeamStrengthL1ObservationService(clock=lambda: STAMP)
    result._gate = active_gate
    return result


def sealed_type_witness() -> TeamStrengthComparisonRun:
    # The invocation wrapper validates only the nominal return boundary. Real
    # comparison contents and summary authentication are covered by inherited tests.
    return object.__new__(TeamStrengthComparisonRun)


def failure_result(
    active: live.TeamStrengthL1ObservationService, caught: live._LiveWrapperFailure
) -> dict[str, object]:
    return active._blocked(caught.stage, caught.reason)


@pytest.mark.parametrize(
    "before,after",
    [
        ((0,), (0,) * 7),
        ((0,) * 7, (False,) + (0,) * 6),
        ((1,) + (0,) * 6, (0,) * 7),
    ],
)
def test_counter_delta_contract_rejects_shape_type_and_backwards_values(before, after):
    with pytest.raises(ValueError):
        live._counter_deltas(before, after)


def test_successful_comparison_return_and_unchanged_counters_are_preserved(monkeypatch):
    active_gate = gate()
    active = service(active_gate)
    expected = sealed_type_witness()
    monkeypatch.setattr(live, "run_team_strength_shadow_comparison", lambda *_: expected)
    result, before, after = active._invoke_two_world_comparison(object(), object(), active_gate)
    assert result is expected and before == after == active_gate.counters()
    assert active._comparison_invocation_started
    assert active._comparison_invocation_returned
    assert active._provider_counter_deltas is None


def test_initial_counter_capture_failure_is_explicit_and_pre_invocation(monkeypatch):
    active_gate = gate()
    active = service(active_gate)
    monkeypatch.setattr(
        active_gate,
        "counters",
        lambda: (_ for _ in ()).throw(ValueError("PRIVATE_CANARY")),
    )
    with pytest.raises(live._LiveWrapperFailure) as caught:
        active._invoke_two_world_comparison(object(), object(), active_gate)
    result = failure_result(active, caught.value)
    assert result["stage"] == "RECONCILE_POST_COMPARISON_PROVIDER_COUNTERS"
    assert result["reason"] == "PROVIDER_COUNTER_RECONCILIATION_FAILED"
    assert not result["comparison_invocation_started"]
    assert not result["comparison_invocation_returned"]
    assert "PRIVATE_CANARY" not in str(result)


def test_suppressed_audit_denial_is_a_named_denied_only_divergence(monkeypatch):
    active_gate = gate()
    active = service(active_gate)
    expected = sealed_type_witness()

    def suppressed_denial(*_):
        with suppress(ValueError):
            active.guard_network_event()
        return expected

    monkeypatch.setattr(live, "run_team_strength_shadow_comparison", suppressed_denial)
    with pytest.raises(live._LiveWrapperFailure) as caught:
        active._invoke_two_world_comparison(object(), object(), active_gate)
    result = failure_result(active, caught.value)
    assert result["stage"] == "RECONCILE_POST_COMPARISON_PROVIDER_COUNTERS"
    assert result["reason"] == "PROVIDER_COUNTER_DIVERGENCE_DURING_COMPARISON"
    assert result["comparison_invocation_started"]
    assert result["comparison_invocation_returned"]
    assert result["provider_counter_deltas"] == {
        "FPL_SENDS": 0,
        "ODDS_SENDS": 0,
        "OPENFOOTBALL_SENDS": 0,
        "FPL_SESSIONS": 0,
        "ODDS_ACQUISITIONS": 0,
        "LEAGUE_ACQUISITIONS": 0,
        "DENIED_SENDS": 1,
    }


def test_actual_send_counter_delta_is_distinct_from_denied_send(monkeypatch):
    active_gate = gate()
    active = service(active_gate)
    expected = sealed_type_witness()

    def synthetic_send_counter(*_):
        # Counter-only adversarial injection: no transport/delegate is called.
        active_gate.counts["FPL"] += 1
        return expected

    monkeypatch.setattr(live, "run_team_strength_shadow_comparison", synthetic_send_counter)
    with pytest.raises(live._LiveWrapperFailure) as caught:
        active._invoke_two_world_comparison(object(), object(), active_gate)
    result = failure_result(active, caught.value)
    deltas = result["provider_counter_deltas"]
    assert deltas["FPL_SENDS"] == 1
    assert deltas["DENIED_SENDS"] == 0
    assert sum(deltas.values()) == 1


def test_wrong_result_type_has_its_own_returned_diagnostic(monkeypatch):
    active_gate = gate()
    active = service(active_gate)
    monkeypatch.setattr(live, "run_team_strength_shadow_comparison", lambda *_: object())
    with pytest.raises(live._LiveWrapperFailure) as caught:
        active._invoke_two_world_comparison(object(), object(), active_gate)
    result = failure_result(active, caught.value)
    assert result["stage"] == "VALIDATE_COMPARISON_RESULT_TYPE"
    assert result["reason"] == "COMPARISON_RESULT_TYPE_INVALID"
    assert result["comparison_invocation_started"]
    assert result["comparison_invocation_returned"]
    assert "object" not in str(result)


def test_valid_typed_d1_failure_survives_wrapper_unchanged(monkeypatch):
    active_gate = gate()
    active = service(active_gate)
    failure = ComparisonTrace().failure(
        ComparisonStage.SEAL_COMPARISON,
        ComparisonReason.COMPARISON_SEAL_FAILED,
        ValueError(),
    )

    def fail(*_):
        raise failure

    monkeypatch.setattr(live, "run_team_strength_shadow_comparison", fail)
    with pytest.raises(TeamStrengthComparisonFailure) as caught:
        active._invoke_two_world_comparison(object(), object(), active_gate)
    result = active._comparison_failure_result(caught.value)
    assert result["stage"] == "SEAL_COMPARISON"
    assert result["reason"] == "COMPARISON_SEAL_FAILED"
    assert result["comparison_invocation_started"]
    assert not result["comparison_invocation_returned"]
    assert result["baseline_world_started"] is False
    assert result["shadow_world_started"] is False


def test_tampered_d1_failure_has_specific_closed_serialization_diagnostic():
    active = service(gate())
    active._comparison_invocation_started = True
    failure = ComparisonTrace().failure(
        ComparisonStage.SEAL_COMPARISON,
        ComparisonReason.COMPARISON_SEAL_FAILED,
        ValueError(),
    )
    object.__setattr__(failure.diagnostic, "internal_code", "PRIVATE_CANARY")
    result = active._comparison_failure_result(failure)
    assert result["stage"] == "SERIALIZE_COMPARISON_DIAGNOSTIC"
    assert result["reason"] == "SAFE_COMPARISON_DIAGNOSTIC_INVALID"
    assert result["comparison_invocation_started"]
    assert not result["comparison_invocation_returned"]
    assert "PRIVATE_CANARY" not in str(result)


def test_safe_success_summary_failure_has_specific_closed_diagnostic(monkeypatch):
    active_gate = gate()
    active = service(active_gate)
    active._comparison_invocation_started = True
    active._comparison_invocation_returned = True
    monkeypatch.setattr(
        live,
        "safe_team_strength_summary",
        lambda *_: (_ for _ in ()).throw(ValueError("PRIVATE_CANARY")),
    )
    with pytest.raises(live._LiveWrapperFailure) as caught:
        active._build_safe_success_summary(
            run=sealed_type_witness(),
            shadow=object(),
            gate=active_gate,
            prepared=object(),
            before=active_gate.counters(),
            after=active_gate.counters(),
            request=object(),
            ready=object(),
        )
    result = failure_result(active, caught.value)
    assert result["stage"] == "BUILD_SAFE_SUCCESS_SUMMARY"
    assert result["reason"] == "SAFE_SUCCESS_SUMMARY_FAILED"
    assert result["comparison_invocation_started"]
    assert result["comparison_invocation_returned"]
    assert "PRIVATE_CANARY" not in str(result)


def test_untyped_invocation_failure_cannot_use_historical_coarse_stage(monkeypatch):
    active_gate = gate()
    active = service(active_gate)
    monkeypatch.setattr(
        live,
        "run_team_strength_shadow_comparison",
        lambda *_: (_ for _ in ()).throw(RuntimeError("PRIVATE_CANARY")),
    )
    with pytest.raises(live._LiveWrapperFailure) as caught:
        active._invoke_two_world_comparison(object(), object(), active_gate)
    result = failure_result(active, caught.value)
    assert result["stage"] == "INVOKE_TWO_WORLD_COMPARISON"
    assert result["reason"] == "COMPARISON_INVOCATION_FAILED"
    assert result["comparison_invocation_started"]
    assert not result["comparison_invocation_returned"]
    assert "RUN_TWO_WORLD_COMPARISON" not in str(result)
    assert "PRIVATE_CANARY" not in str(result)


def test_counter_shape_failure_has_specific_reconciliation_diagnostic(monkeypatch):
    active_gate = gate()
    active = service(active_gate)
    expected = sealed_type_witness()
    calls = 0
    counters = active_gate.counters

    def malformed_after():
        nonlocal calls
        calls += 1
        return counters() if calls == 1 else (0,)

    monkeypatch.setattr(active_gate, "counters", malformed_after)
    monkeypatch.setattr(live, "run_team_strength_shadow_comparison", lambda *_: expected)
    with pytest.raises(live._LiveWrapperFailure) as caught:
        active._invoke_two_world_comparison(object(), object(), active_gate)
    result = failure_result(active, caught.value)
    assert result["stage"] == "RECONCILE_POST_COMPARISON_PROVIDER_COUNTERS"
    assert result["reason"] == "PROVIDER_COUNTER_RECONCILIATION_FAILED"
    assert result["comparison_invocation_returned"]


def test_outer_terminal_boundary_preserves_closed_wrapper_failure(monkeypatch):
    active = live.TeamStrengthL1ObservationService(clock=lambda: STAMP)
    monkeypatch.setattr(
        live,
        "validate_l1_authority",
        lambda **_: (_ for _ in ()).throw(
            live._LiveWrapperFailure(
                live.L1Stage.VALIDATE_COMPARISON_RESULT_TYPE,
                live.L1Reason.COMPARISON_RESULT_TYPE_INVALID,
            )
        ),
    )
    result = active.run(live.L1OperatorRequest(1, "a" * 40, "offline", "offline", "0" * 64), None)
    assert result["stage"] == "VALIDATE_COMPARISON_RESULT_TYPE"
    assert result["reason"] == "COMPARISON_RESULT_TYPE_INVALID"


def test_outer_terminal_boundary_preserves_typed_d1_failure(monkeypatch):
    active = live.TeamStrengthL1ObservationService(clock=lambda: STAMP)
    failure = ComparisonTrace().failure(
        ComparisonStage.SEAL_COMPARISON,
        ComparisonReason.COMPARISON_SEAL_FAILED,
        ValueError(),
    )
    monkeypatch.setattr(
        live,
        "validate_l1_authority",
        lambda **_: (_ for _ in ()).throw(failure),
    )
    result = active.run(live.L1OperatorRequest(1, "a" * 40, "offline", "offline", "0" * 64), None)
    assert result["stage"] == "SEAL_COMPARISON"
    assert result["reason"] == "COMPARISON_SEAL_FAILED"


def test_naive_authority_clock_is_closed_before_any_current_authority_check():
    from dmf_pulse.private_v1.team_strength_live_authority import validate_l1_authority

    with pytest.raises(ValueError, match="clock must be aware"):
        validate_l1_authority(
            approval="offline", attestation="offline", checked_at=datetime(2026, 1, 1)
        )
