"""Real prepared-runner seam proofs for D3; generated inputs and zero network."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.odds.client import OddsHttpResponse
from dmf_pulse.ingestion.openfootball import service as league
from dmf_pulse.private_v1 import one_command
from dmf_pulse.private_v1 import team_strength_live as live
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.prepared_control import PreparedRollingControlFlow
from dmf_pulse.private_v1.team_strength_diagnostics import (
    ComparisonReason,
    ComparisonStage,
    ComparisonTrace,
    InternalCode,
    Stage8Outcome,
    TeamStrengthComparisonFailure,
)
from tests.unit.ingestion.openfootball.conftest import FakeTransport, synthetic_snapshot
from tests.unit.private_v1.l1_test_support import deny_writes
from tests.unit.private_v1.test_one_command import _DirectTransport
from tests.unit.private_v1.test_team_strength_l1 import offline_run, request, service
from tests.unit.private_v1.test_team_strength_l1 import readiness as readiness
from tests.unit.private_v1.test_team_strength_l1_e2e import sources

pytestmark = pytest.mark.unit
PARENT = "b774056f20e855d7a755186fe62489e3d393ecfe"


class _OddsTransport:
    transport_id = "injected"

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls = 0

    def send(self, request, credential):
        del request, credential
        self.calls += 1
        return OddsHttpResponse(
            200,
            "application/json",
            {"x-requests-remaining": "100", "x-requests-used": "2", "x-requests-last": "2"},
            self.body,
        )


def _full_seam(readiness, repository_root, monkeypatch, tmp_path, inject):
    direct_bodies, odds_body = sources(repository_root)
    fpl = _DirectTransport(direct_bodies)
    odds = _OddsTransport(odds_body)
    config, bodies = synthetic_snapshot()
    public = FakeTransport(bodies)
    monkeypatch.setattr(league, "load_provider_config", lambda: config)
    monkeypatch.setattr(league, "provider_config_sha256", lambda: canonical_sha256(config))
    original_request = one_command.OneCommandRequest

    def bounded_request(**kwargs):
        return replace(original_request(**kwargs), scenario_count=2)

    monkeypatch.setattr(live, "OneCommandRequest", bounded_request)
    active = service(fpl_transport=fpl, odds_transport=odds, public_transport=public)
    inject(active)
    with deny_writes():
        result = offline_run(active, request(readiness), readiness)
    assert len(fpl.requests) == 8 and odds.calls == 1 and len(public.requests) == 4
    assert result["fpl_requests"] == 8 and result["odds_requests"] == 1
    return result


def test_d1_failure_survives_real_one_command_callback_seam(
    readiness, repository_root, monkeypatch, tmp_path
):
    trace = ComparisonTrace()
    trace.start_world("LEAGUE_BASELINE")
    trace.complete_world("LEAGUE_BASELINE")
    trace.start_world("TEAM_STRENGTH_SHADOW")
    trace.location = (2, 3, "MARKET_BACKED")
    trace.stage8_outcome = Stage8Outcome.BLOCKED
    trace.stage8_code = InternalCode.STAGE8_BLOCKED
    failure = trace.failure(
        ComparisonStage.RUN_TEAM_STRENGTH_WORLD,
        ComparisonReason.TEAM_STRENGTH_WORLD_FAILED,
        PrivateV1Error("STAGE8_BLOCKED", "private body"),
    )

    def inject(active):
        del active
        monkeypatch.setattr(
            live,
            "run_team_strength_shadow_comparison",
            lambda *_: (_ for _ in ()).throw(failure),
        )

    result = _full_seam(readiness, repository_root, monkeypatch, tmp_path, inject)
    assert result["stage"] == "RUN_TEAM_STRENGTH_WORLD"
    assert result["reason"] == "WORLD_STAGE8_BLOCKED"
    assert result["failed_world"] == "TEAM_STRENGTH_SHADOW"
    assert result["baseline_world_started"] and result["baseline_world_completed"]
    assert result["shadow_world_started"] and not result["shadow_world_completed"]
    assert (result["failed_gameweek"], result["failed_fixture_ordinal"]) == (2, 3)
    assert result["market_coverage_class"] == "MARKET_BACKED"
    assert result["stage8_outcome"] == "BLOCKED"
    assert result["internal_stage8_error_code"] == "STAGE8_BLOCKED"
    assert result["comparison_invocation_started"]
    assert not result["comparison_invocation_returned"]
    assert "ONE_COMMAND_INPUT_INVALID" not in json.dumps(result)
    assert "SHADOW_UNAVAILABLE" not in json.dumps(result)
    assert "TWO_WORLD_COMPARISON_FAILED" not in json.dumps(result)


def test_d2_wrapper_failure_survives_real_one_command_callback_seam(
    readiness, repository_root, monkeypatch, tmp_path
):
    def inject(active):
        del active
        monkeypatch.setattr(
            live,
            "run_team_strength_shadow_comparison",
            lambda *_: (_ for _ in ()).throw(RuntimeError("PRIVATE_CANARY")),
        )

    result = _full_seam(readiness, repository_root, monkeypatch, tmp_path, inject)
    assert result["stage"] == "INVOKE_TWO_WORLD_COMPARISON"
    assert result["reason"] == "COMPARISON_INVOCATION_FAILED"
    assert result["comparison_invocation_started"]
    assert not result["comparison_invocation_returned"]
    assert "PRIVATE_CANARY" not in json.dumps(result)


def test_ordinary_valueerror_is_still_sanitized_by_real_one_command_seam(
    readiness, repository_root, monkeypatch, tmp_path
):
    seen: list[tuple[str, str]] = []
    original_error = PrivateV1Error

    class RecordingPrivateV1Error(original_error):
        def __init__(self, code: str, message: str) -> None:
            seen.append((code, message))
            super().__init__(code, message)

    monkeypatch.setattr(one_command, "PrivateV1Error", RecordingPrivateV1Error)

    def inject(active):
        del active
        monkeypatch.setattr(
            live,
            "prepare_team_strength_shadow",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("PRIVATE_ORDINARY_VALUEERROR")
            ),
        )

    result = _full_seam(readiness, repository_root, monkeypatch, tmp_path, inject)
    assert seen[-1] == (
        "ONE_COMMAND_INPUT_INVALID",
        "automatic current input assembly failed",
    )
    assert result["stage"] == "PREPARE_TEAM_STRENGTH_SHADOW"
    assert result["reason"] == "SHADOW_UNAVAILABLE"
    assert "PRIVATE_ORDINARY_VALUEERROR" not in json.dumps(result)


def test_parent_valueerror_masking_mechanism_is_reproduced_at_real_seam(
    readiness, repository_root, monkeypatch, tmp_path
):
    diagnostics_parent = subprocess.run(
        ["git", "show", f"{PARENT}:src/dmf_pulse/private_v1/team_strength_diagnostics.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    live_parent = subprocess.run(
        ["git", "show", f"{PARENT}:src/dmf_pulse/private_v1/team_strength_live.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "class TeamStrengthComparisonFailure(ValueError):" in diagnostics_parent
    assert "class _LiveWrapperFailure(ValueError):" in live_parent

    seen: list[str] = []
    original_error = PrivateV1Error

    class RecordingPrivateV1Error(original_error):
        def __init__(self, code: str, message: str) -> None:
            seen.append(code)
            super().__init__(code, message)

    class HistoricalTypedFailure(ValueError):
        pass

    monkeypatch.setattr(one_command, "PrivateV1Error", RecordingPrivateV1Error)

    def inject(active):
        def historical_failure(*_args):
            active._comparison_invocation_started = True
            raise HistoricalTypedFailure("historical private diagnostic")

        monkeypatch.setattr(active, "_invoke_two_world_comparison", historical_failure)

    result = _full_seam(readiness, repository_root, monkeypatch, tmp_path, inject)
    assert seen[-1] == "ONE_COMMAND_INPUT_INVALID"
    assert result["comparison_invocation_started"]
    # D3's immediate fallback-state update prevents the old stale shadow reason,
    # even when this test deliberately recreates the parent's ValueError ancestry.
    assert result["stage"] == "INVOKE_TWO_WORLD_COMPARISON"
    assert result["reason"] == "COMPARISON_INVOCATION_FAILED"
    assert "historical private diagnostic" not in json.dumps(result)


def test_explicit_control_flow_family_is_not_valueerror():
    assert issubclass(TeamStrengthComparisonFailure, PreparedRollingControlFlow)
    assert issubclass(live._LiveWrapperFailure, PreparedRollingControlFlow)
    assert issubclass(live._ObservationComplete, PreparedRollingControlFlow)
    assert not issubclass(PreparedRollingControlFlow, ValueError)
