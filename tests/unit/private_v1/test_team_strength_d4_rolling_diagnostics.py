"""D4 closed rolling-phase diagnostics; generated inputs and zero network."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from dmf_pulse.optimisation.multi_gameweek_errors import ResourceLimitKind
from dmf_pulse.optimisation.multi_gameweek_models import (
    BackendStatus,
    MultiGameweekResultStatus,
    OptimalityGuarantee,
    SolverDiagnostics,
)
from dmf_pulse.private_v1 import one_command, rolling
from dmf_pulse.private_v1 import team_strength_diagnostics as diagnostics
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.team_strength_diagnostics import (
    ComparisonReason,
    ComparisonStage,
    ComparisonTrace,
    RollingFailureClass,
    RollingInternalCode,
    RollingPhase,
    TeamStrengthComparisonFailure,
    comparison_boundary,
    rolling_boundary,
    safe_comparison_failure,
)
from tests.unit.private_v1.e2e_test_support import build_rolling_execution_input
from tests.unit.private_v1.test_team_strength_d1_diagnostics import fail
from tests.unit.private_v1.test_team_strength_d3_seam import _full_seam
from tests.unit.private_v1.test_team_strength_l1 import readiness as readiness

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def captured_rolling_pipeline(repository_root, tmp_path_factory):
    """Run the real pipeline once, retaining only generated in-process test objects."""

    execution = build_rolling_execution_input(
        repository_root, tmp_path_factory.mktemp("d4-rolling-capture")
    )
    captured: dict[str, list[object]] = {
        "project": [],
        "assemble": [],
        "projection": [],
        "request": [],
        "optimise": [],
    }
    patcher = pytest.MonkeyPatch()

    def capture(name, original):
        def wrapped(*args, **kwargs):
            result = original(*args, **kwargs)
            captured[name].append(result)
            return result

        return wrapped

    for name, target in (
        ("project", "_project_fixtures"),
        ("assemble", "assemble_gameweek"),
        ("projection", "build_gameweek_projection"),
        ("request", "_stage11_request"),
        ("optimise", "optimise_multi_gameweek"),
    ):
        patcher.setattr(rolling, target, capture(name, getattr(rolling, target)))
    try:
        result = rolling.PrivateV1RollingRecommendationService().run(execution)
    finally:
        patcher.undo()
    assert result.decision.status == "SUCCESS"
    assert {name: len(values) for name, values in captured.items()} == {
        "project": 3,
        "assemble": 3,
        "projection": 3,
        "request": 2,
        "optimise": 2,
    }
    return execution, captured


@pytest.fixture(scope="module")
def captured_full_seam_pipeline(readiness, repository_root, tmp_path_factory):
    """Capture one real baseline world reached through the complete offline seam."""

    captured: dict[str, list[object]] = {
        "rolling_minutes": [],
        "project": [],
        "assemble": [],
        "projection": [],
        "request": [],
        "optimise": [],
    }
    patcher = pytest.MonkeyPatch()

    def capture(name, original):
        def wrapped(*args, **kwargs):
            result = original(*args, **kwargs)
            captured[name].append(result)
            return result

        return wrapped

    patcher.setattr(
        one_command,
        "build_automatic_rolling_model_minutes",
        capture(
            "rolling_minutes",
            one_command.build_automatic_rolling_model_minutes,
        ),
    )

    def inject(_active):
        for name, target in (
            ("project", "_project_fixtures"),
            ("assemble", "assemble_gameweek"),
            ("projection", "build_gameweek_projection"),
            ("request", "_stage11_request"),
            ("optimise", "optimise_multi_gameweek"),
        ):
            patcher.setattr(rolling, target, capture(name, getattr(rolling, target)))
        original_boundary = diagnostics.rolling_boundary

        @contextmanager
        def stop_after_capture(phase, *, gameweek=None):
            with original_boundary(phase, gameweek=gameweek):
                if phase is RollingPhase.BUILD_STAGE11_WORK:
                    raise RuntimeError("CAPTURE_COMPLETE")
                yield

        patcher.setattr(rolling, "rolling_boundary", stop_after_capture)

    try:
        result = _full_seam(
            readiness,
            repository_root,
            patcher,
            tmp_path_factory.mktemp("d4-full-seam-capture"),
            inject,
        )
    finally:
        patcher.undo()
    assert result["rolling_phase"] == "BUILD_STAGE11_WORK"
    assert {name: len(values) for name, values in captured.items()} == {
        "rolling_minutes": 1,
        "project": 3,
        "assemble": 3,
        "projection": 3,
        "request": 2,
        "optimise": 2,
    }
    return captured


def _closed_failure(phase: RollingPhase, error: Exception) -> dict[str, object]:
    trace = ComparisonTrace()
    trace.start_world("LEAGUE_BASELINE")
    with (
        pytest.raises(TeamStrengthComparisonFailure) as caught,
        trace.activate(),
        comparison_boundary(
            ComparisonStage.RUN_LEAGUE_BASELINE_WORLD,
            ComparisonReason.BASELINE_WORLD_FAILED,
        ),
        rolling_boundary(phase, gameweek=7),
    ):
        raise error
    return safe_comparison_failure(caught.value)


@pytest.mark.parametrize("phase", tuple(RollingPhase))
@pytest.mark.parametrize(
    "error,failure_class,code",
    [
        (
            RuntimeError("PRIVATE_CANARY"),
            RollingFailureClass.UNEXPECTED_FAILURE,
            RollingInternalCode.ROLLING_UNEXPECTED_FAILURE,
        ),
        (
            PrivateV1Error("PRIVATE_DYNAMIC_CANARY", "PRIVATE_CANARY"),
            RollingFailureClass.TYPED_FAILURE,
            RollingInternalCode.PRIVATE_V1_FAILURE_UNCLASSIFIED,
        ),
    ],
)
def test_every_rolling_phase_has_closed_generic_and_typed_failure(
    phase, error, failure_class, code
):
    result = _closed_failure(phase, error)
    assert result["rolling_phase"] == phase.value
    assert result["rolling_gameweek"] == 7
    expected_class = (
        RollingFailureClass.OPTIMISER_FAILURE
        if failure_class is RollingFailureClass.TYPED_FAILURE
        and phase
        in {
            RollingPhase.SOLVE_ONE_GW_COMPARATOR,
            RollingPhase.VALIDATE_ONE_GW_RESULT,
            RollingPhase.SOLVE_THREE_GW_POLICY,
            RollingPhase.VALIDATE_THREE_GW_RESULT,
        }
        else failure_class
    )
    assert result["rolling_failure_class"] == expected_class.value
    expected = (
        RollingInternalCode.OPTIMISER_FAILURE_UNCLASSIFIED
        if failure_class is RollingFailureClass.TYPED_FAILURE
        and phase
        in {
            RollingPhase.SOLVE_ONE_GW_COMPARATOR,
            RollingPhase.VALIDATE_ONE_GW_RESULT,
            RollingPhase.SOLVE_THREE_GW_POLICY,
            RollingPhase.VALIDATE_THREE_GW_RESULT,
        }
        else code
    )
    assert result["rolling_internal_code"] == expected.value
    assert "PRIVATE_CANARY" not in json.dumps(result)


@pytest.mark.parametrize("code", tuple(RollingInternalCode)[:-3])
def test_allowlisted_rolling_codes_round_trip_without_private_text(code):
    result = _closed_failure(
        RollingPhase.BUILD_TRANSFER_FRONTIER,
        PrivateV1Error(code.value, "PRIVATE_CANARY"),
    )
    assert result["rolling_internal_code"] == code.value
    assert "PRIVATE_CANARY" not in json.dumps(result)


def test_unknown_optimizer_code_is_never_null_or_disclosed():
    result = _closed_failure(
        RollingPhase.VALIDATE_THREE_GW_RESULT,
        PrivateV1Error("DYNAMIC_PRIVATE_OPTIMISER_CODE", "PRIVATE_CANARY"),
    )
    assert result["rolling_failure_class"] == "OPTIMISER_FAILURE"
    assert result["rolling_internal_code"] == "OPTIMISER_FAILURE_UNCLASSIFIED"
    assert result["internal_code"] is None
    assert "DYNAMIC_PRIVATE" not in json.dumps(result)


def test_ordinary_rolling_boundary_has_no_observer_and_preserves_exception_identity():
    error = RuntimeError("ordinary error")
    with pytest.raises(RuntimeError) as caught, rolling_boundary(RollingPhase.BUILD_STAGE11_WORK):
        raise error
    assert caught.value is error
    diagnostics.note_rolling_progress("STAGE8")
    diagnostics.note_optimiser_result(status=object(), solver_status=object())
    assert diagnostics._TRACE.get() is None


def test_resource_limit_identity_and_safe_counters_reach_terminal_diagnostic():
    trace = ComparisonTrace()
    trace.start_world("LEAGUE_BASELINE")
    solver = SolverDiagnostics(
        status=BackendStatus.TIME_RESOURCE_LIMIT_NO_INCUMBENT,
        termination_reason="PRIVATE RAW MESSAGE CANARY",
        optimality_guarantee=OptimalityGuarantee.NONE,
        state_expansions=101,
        observed_action_combinations=505,
        action_candidates=202,
        policy_candidates=303,
        pareto_candidates=404,
        resource_limit_kind=ResourceLimitKind.CUMULATIVE_LEGAL_ACTION_LIMIT,
        configured_max_actions_per_state=5000,
        configured_max_state_expansions=25000,
        configured_max_policy_candidates=250000,
        configured_max_returned_root_candidates=1000,
        configured_cumulative_legal_action_limit=524288,
        cumulative_legal_actions=524289,
        reachable_layer_state_count=999,
        configuration_sha256="0" * 64,
    )
    with trace.activate():
        diagnostics.note_rolling_phase(RollingPhase.VALIDATE_THREE_GW_RESULT)
        diagnostics.note_optimiser_result(
            status=MultiGameweekResultStatus.RESOURCE_LIMIT,
            solver_status=solver,
        )
        failure = trace.failure(
            ComparisonStage.RUN_LEAGUE_BASELINE_WORLD,
            ComparisonReason.BASELINE_WORLD_FAILED,
            PrivateV1Error("MULTI_GAMEWEEK_RESOURCE_LIMIT", "PRIVATE RAW MESSAGE CANARY"),
        )
    result = safe_comparison_failure(failure)
    assert result["resource_limit_kind"] == "CUMULATIVE_LEGAL_ACTION_LIMIT"
    assert result["configured_cumulative_legal_action_limit"] == 524288
    assert result["cumulative_legal_actions"] == 524289
    assert result["reachable_layer_state_count"] == 999
    assert result["observed_state_expansions"] == 101
    assert result["observed_action_combinations"] == 505
    assert result["observed_action_candidates"] == 202
    assert result["observed_policy_candidates"] == 303
    assert result["observed_pareto_candidates"] == 404
    assert "PRIVATE RAW MESSAGE CANARY" not in json.dumps(result)


def test_every_declared_phase_is_wired_into_real_rolling_service_source():
    source = Path(rolling.__file__).read_text(encoding="utf-8")
    for phase in RollingPhase:
        assert f"RollingPhase.{phase.name}" in source


def _patch_captured_pipeline(monkeypatch, captured, *, optimiser_values=None):
    for key, target in (
        ("project", "_project_fixtures"),
        ("assemble", "assemble_gameweek"),
        ("projection", "build_gameweek_projection"),
        ("request", "_stage11_request"),
        ("optimise", "optimise_multi_gameweek"),
    ):
        values = iter(
            optimiser_values
            if key == "optimise" and optimiser_values is not None
            else captured[key]
        )
        monkeypatch.setattr(rolling, target, lambda *args, _values=values, **kwargs: next(_values))
    tactical_type = type(captured["request"][0][1])
    monkeypatch.setattr(tactical_type, "precompute", lambda self: None)


def _patch_captured_preparation(monkeypatch, captured):
    values = iter(captured["rolling_minutes"])
    monkeypatch.setattr(
        one_command,
        "build_automatic_rolling_model_minutes",
        lambda *args, _values=values, **kwargs: next(_values),
    )


@pytest.mark.parametrize("phase", tuple(RollingPhase))
def test_every_phase_failure_is_injected_through_real_rolling_service(
    captured_rolling_pipeline, monkeypatch, phase
):
    execution, captured = captured_rolling_pipeline
    _patch_captured_pipeline(monkeypatch, captured)
    original_boundary = diagnostics.rolling_boundary

    @contextmanager
    def injected_boundary(active_phase, *, gameweek=None):
        with original_boundary(active_phase, gameweek=gameweek):
            if active_phase is phase:
                raise RuntimeError("PRIVATE_PHASE_INJECTION_CANARY")
            yield

    monkeypatch.setattr(rolling, "rolling_boundary", injected_boundary)
    trace = ComparisonTrace()
    trace.start_world("LEAGUE_BASELINE")
    with (
        pytest.raises(TeamStrengthComparisonFailure) as caught,
        trace.activate(),
        comparison_boundary(
            ComparisonStage.RUN_LEAGUE_BASELINE_WORLD,
            ComparisonReason.BASELINE_WORLD_FAILED,
        ),
    ):
        rolling.PrivateV1RollingRecommendationService().run(execution)
    result = safe_comparison_failure(caught.value)
    assert result["rolling_phase"] == phase.value
    assert result["rolling_failure_class"] == "UNEXPECTED_FAILURE"
    assert result["rolling_internal_code"] == "ROLLING_UNEXPECTED_FAILURE"
    assert "PRIVATE_PHASE_INJECTION_CANARY" not in json.dumps(result)


@pytest.mark.parametrize(
    "failed_index,expected_phase",
    [
        (0, RollingPhase.VALIDATE_ONE_GW_RESULT),
        (1, RollingPhase.VALIDATE_THREE_GW_RESULT),
    ],
)
def test_dynamic_optimizer_result_is_closed_through_real_rolling_service(
    captured_rolling_pipeline, monkeypatch, failed_index, expected_phase
):
    execution, captured = captured_rolling_pipeline
    optimiser_values = list(captured["optimise"])
    source = optimiser_values[failed_index]
    solver_status = source.solver_status.model_copy(
        update={"status": BackendStatus.INPUT_CAPABILITY_BLOCKED}
    )
    optimiser_values[failed_index] = source.model_copy(
        update={
            "status": MultiGameweekResultStatus.BLOCKED,
            "solver_status": solver_status,
            "recommended_plan": None,
            "error_code": "DYNAMIC_PRIVATE_OPTIMISER_CODE",
        }
    )
    _patch_captured_pipeline(monkeypatch, captured, optimiser_values=optimiser_values)
    trace = ComparisonTrace()
    trace.start_world("LEAGUE_BASELINE")
    with (
        pytest.raises(TeamStrengthComparisonFailure) as caught,
        trace.activate(),
        comparison_boundary(
            ComparisonStage.RUN_LEAGUE_BASELINE_WORLD,
            ComparisonReason.BASELINE_WORLD_FAILED,
        ),
    ):
        rolling.PrivateV1RollingRecommendationService().run(execution)
    result = safe_comparison_failure(caught.value)
    assert result["rolling_phase"] == expected_phase.value
    assert result["rolling_failure_class"] == "OPTIMISER_FAILURE"
    assert result["rolling_internal_code"] == "OPTIMISER_FAILURE_UNCLASSIFIED"
    assert result["optimiser_status_class"] == "BLOCKED"
    assert result["optimiser_backend_status_class"] == "INPUT_CAPABILITY_BLOCKED"
    assert "DYNAMIC_PRIVATE" not in json.dumps(result)


def test_real_rolling_service_localises_after_stage8_before_stage9(
    repository_root, tmp_path, monkeypatch
):
    execution = build_rolling_execution_input(repository_root, tmp_path / "rolling")
    monkeypatch.setattr(
        rolling,
        "assemble_gameweek",
        lambda *_: (_ for _ in ()).throw(ValueError("PRIVATE_STAGE9_CANARY")),
    )
    trace = ComparisonTrace()
    trace.start_world("LEAGUE_BASELINE")
    with (
        pytest.raises(TeamStrengthComparisonFailure) as caught,
        trace.activate(),
        comparison_boundary(
            ComparisonStage.RUN_LEAGUE_BASELINE_WORLD,
            ComparisonReason.BASELINE_WORLD_FAILED,
        ),
    ):
        rolling.PrivateV1RollingRecommendationService().run(execution)
    result = safe_comparison_failure(caught.value)
    assert result["rolling_phase"] == "ASSEMBLE_GAMEWEEK_SCENARIOS"
    assert result["rolling_gameweek"] == execution.horizon_gameweeks[0]
    assert result["rolling_internal_code"] == "STAGE9_GAMEWEEK_INVALID"
    assert result["gameweeks_stage8_complete"] == 1
    assert result["gameweeks_stage9_assembled"] == 0
    assert result["gameweeks_stage9_mc_passed"] == 0
    assert result["baseline_stage8_projected"] > 0
    assert "PRIVATE_STAGE9_CANARY" not in json.dumps(result)


def test_rolling_failure_survives_complete_d1_d2_d3_one_command_seam(
    readiness, repository_root, monkeypatch, tmp_path
):
    def inject(_active):
        monkeypatch.setattr(rolling, "assemble_gameweek", fail)

    result = _full_seam(readiness, repository_root, monkeypatch, tmp_path, inject)
    assert result["stage"] == "RUN_LEAGUE_BASELINE_WORLD"
    assert result["reason"] == "BASELINE_WORLD_FAILED"
    assert result["failed_world"] == "LEAGUE_BASELINE"
    assert result["rolling_phase"] == "ASSEMBLE_GAMEWEEK_SCENARIOS"
    assert result["rolling_failure_class"] == "TYPED_FAILURE"
    assert result["rolling_internal_code"] == "STAGE9_GAMEWEEK_INVALID"
    assert result["gameweeks_stage8_complete"] == 1
    assert result["gameweeks_stage9_assembled"] == 0
    assert result["gameweeks_stage9_mc_passed"] == 0
    assert result["comparison_invocation_started"]
    assert not result["comparison_invocation_returned"]
    assert "SYNTHETIC_PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("phase", tuple(RollingPhase))
def test_every_phase_survives_complete_d1_d2_d3_one_command_seam(
    captured_full_seam_pipeline,
    readiness,
    repository_root,
    monkeypatch,
    tmp_path,
    phase,
):
    captured = captured_full_seam_pipeline
    _patch_captured_preparation(monkeypatch, captured)

    def inject(_active):
        _patch_captured_pipeline(monkeypatch, captured)
        original_boundary = diagnostics.rolling_boundary

        @contextmanager
        def injected_boundary(active_phase, *, gameweek=None):
            with original_boundary(active_phase, gameweek=gameweek):
                if active_phase is phase:
                    raise RuntimeError("PRIVATE_FULL_SEAM_PHASE_CANARY")
                yield

        monkeypatch.setattr(rolling, "rolling_boundary", injected_boundary)

    result = _full_seam(readiness, repository_root, monkeypatch, tmp_path, inject)
    assert result["stage"] == "RUN_LEAGUE_BASELINE_WORLD"
    assert result["reason"] == "BASELINE_WORLD_FAILED"
    assert result["failed_world"] == "LEAGUE_BASELINE"
    assert result["rolling_phase"] == phase.value
    assert result["rolling_failure_class"] == "UNEXPECTED_FAILURE"
    assert result["rolling_internal_code"] == "ROLLING_UNEXPECTED_FAILURE"
    assert result["comparison_invocation_started"]
    assert not result["comparison_invocation_returned"]
    assert "PRIVATE_FULL_SEAM_PHASE_CANARY" not in json.dumps(result)


@pytest.mark.parametrize(
    "failed_index,expected_phase",
    [
        (0, RollingPhase.VALIDATE_ONE_GW_RESULT),
        (1, RollingPhase.VALIDATE_THREE_GW_RESULT),
    ],
)
def test_optimizer_failure_survives_complete_d1_d2_d3_one_command_seam(
    captured_full_seam_pipeline,
    readiness,
    repository_root,
    monkeypatch,
    tmp_path,
    failed_index,
    expected_phase,
):
    captured = captured_full_seam_pipeline
    _patch_captured_preparation(monkeypatch, captured)
    optimiser_values = list(captured["optimise"])
    source = optimiser_values[failed_index]
    optimiser_values[failed_index] = source.model_copy(
        update={
            "status": MultiGameweekResultStatus.BLOCKED,
            "solver_status": source.solver_status.model_copy(
                update={"status": BackendStatus.INPUT_CAPABILITY_BLOCKED}
            ),
            "recommended_plan": None,
            "error_code": "DYNAMIC_PRIVATE_OPTIMISER_CODE",
        }
    )

    def inject(_active):
        _patch_captured_pipeline(monkeypatch, captured, optimiser_values=optimiser_values)

    result = _full_seam(readiness, repository_root, monkeypatch, tmp_path, inject)
    assert result["rolling_phase"] == expected_phase.value
    assert result["rolling_failure_class"] == "OPTIMISER_FAILURE"
    assert result["rolling_internal_code"] == "OPTIMISER_FAILURE_UNCLASSIFIED"
    assert result["optimiser_status_class"] == "BLOCKED"
    assert result["optimiser_backend_status_class"] == "INPUT_CAPABILITY_BLOCKED"
    assert "DYNAMIC_PRIVATE" not in json.dumps(result)


def test_resource_identity_survives_complete_d1_d2_d3_d4_one_command_seam(
    captured_full_seam_pipeline,
    readiness,
    repository_root,
    monkeypatch,
    tmp_path,
):
    captured = captured_full_seam_pipeline
    _patch_captured_preparation(monkeypatch, captured)
    optimiser_values = list(captured["optimise"])
    source = optimiser_values[1]
    resource_status = source.solver_status.model_copy(
        update={
            "status": BackendStatus.TIME_RESOURCE_LIMIT_NO_INCUMBENT,
            "termination_reason": "PRIVATE RESOURCE MESSAGE CANARY",
            "optimality_guarantee": OptimalityGuarantee.NONE,
            "objective": None,
            "incumbent": None,
            "bound": None,
            "absolute_gap": None,
            "relative_gap": None,
            "state_expansions": 101,
            "observed_action_combinations": 5001,
            "action_candidates": 202,
            "policy_candidates": 303,
            "pareto_candidates": 404,
            "resource_limit_kind": ResourceLimitKind.PER_STATE_ACTION_COMBINATION_LIMIT,
            "configured_max_actions_per_state": 5000,
            "configured_max_state_expansions": 25000,
            "configured_max_policy_candidates": 250000,
            "configured_max_returned_root_candidates": 1000,
            "configured_cumulative_legal_action_limit": 524288,
            "cumulative_legal_actions": 202,
            "reachable_layer_state_count": 101,
        }
    )
    optimiser_values[1] = source.model_copy(
        update={
            "status": MultiGameweekResultStatus.RESOURCE_LIMIT,
            "solver_status": resource_status,
            "recommended_plan": None,
            "error_code": "MULTI_GAMEWEEK_RESOURCE_LIMIT",
            "error_message": "PRIVATE RESOURCE MESSAGE CANARY",
        }
    )

    def inject(_active):
        _patch_captured_pipeline(monkeypatch, captured, optimiser_values=optimiser_values)

    result = _full_seam(readiness, repository_root, monkeypatch, tmp_path, inject)
    assert result["rolling_phase"] == "VALIDATE_THREE_GW_RESULT"
    assert result["rolling_internal_code"] == "MULTI_GAMEWEEK_RESOURCE_LIMIT"
    assert result["optimiser_status_class"] == "RESOURCE_LIMIT"
    assert result["optimiser_backend_status_class"] == "TIME_RESOURCE_LIMIT_NO_INCUMBENT"
    assert result["resource_limit_kind"] == "PER_STATE_ACTION_COMBINATION_LIMIT"
    assert result["configured_max_actions_per_state"] == 5000
    assert result["observed_action_combinations"] == 5001
    assert result["observed_state_expansions"] == 101
    assert result["observed_action_candidates"] == 202
    assert result["observed_policy_candidates"] == 303
    assert result["observed_pareto_candidates"] == 404
    assert result["cumulative_legal_actions"] == 202
    assert result["reachable_layer_state_count"] == 101
    assert "PRIVATE RESOURCE MESSAGE CANARY" not in json.dumps(result)
