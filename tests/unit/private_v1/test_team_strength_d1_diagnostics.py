"""Synthetic failure injection and disclosure attacks; no providers or credentials."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from dmf_pulse.football_events.market_constraints import MarketFamily
from dmf_pulse.football_events.service import ScoreDistributionError
from dmf_pulse.private_v1 import team_strength_comparison as comparison
from dmf_pulse.private_v1 import team_strength_diagnostics as diagnostics
from dmf_pulse.private_v1 import team_strength_live as live
from dmf_pulse.private_v1 import team_strength_live_authority as authority
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.team_strength_comparison_models import CONTROL_NAMES
from dmf_pulse.private_v1.team_strength_diagnostics import (
    ComparisonFailureDiagnostic,
    ComparisonTrace,
    ControlName,
    InternalCode,
    Stage8Outcome,
    TeamStrengthComparisonFailure,
    comparison_boundary,
    safe_comparison_failure,
)
from dmf_pulse.private_v1.team_strength_diagnostics import (
    ComparisonReason as Reason,
)
from dmf_pulse.private_v1.team_strength_diagnostics import (
    ComparisonStage as Stage,
)
from tests.unit.private_v1.test_team_strength_shadow_comparison import (
    comparison_inputs as comparison_inputs,
)


def fail(*args, **kwargs):
    raise ValueError("SYNTHETIC_PRIVATE_BODY_AND_ENTRY_ID_MUST_NEVER_ESCAPE")


@pytest.mark.parametrize("stage", tuple(Stage))
def test_every_boundary_suppresses_arbitrary_exception_text(stage):
    trace = ComparisonTrace()
    with (
        pytest.raises(TeamStrengthComparisonFailure) as caught,
        trace.activate(),
        comparison_boundary(stage, Reason.COMPARISON_INPUT_INVALID),
    ):
        fail()
    payload = safe_comparison_failure(caught.value)
    assert payload["stage"] == stage.value
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + str(payload)
    assert caught.value.__suppress_context__ and caught.value.__cause__ is None
    assert not payload["baseline_world_started"] and not payload["shadow_world_started"]
    assert diagnostics._TRACE.get() is None


def test_no_observer_leaves_ordinary_error_and_callbacks_unchanged():
    error = ValueError("ordinary existing failure")
    with (
        pytest.raises(ValueError) as caught,
        comparison_boundary(Stage.SEAL_COMPARISON, Reason.COMPARISON_SEAL_FAILED),
    ):
        raise error
    assert caught.value is error
    diagnostics.note_stage8_input(1, 1, ())
    diagnostics.note_stage8_input_failure(ValueError("unused"))
    diagnostics.note_stage8_blocked("unused")
    diagnostics.note_stage8_projected()
    diagnostics.note_control_divergence((), ())
    trace = ComparisonTrace()
    with trace.activate():
        diagnostics.note_stage8_projected()  # no active world
        with ComparisonTrace().activate():
            assert diagnostics._TRACE.get() is not trace
        assert diagnostics._TRACE.get() is trace
    assert diagnostics._TRACE.get() is None


@pytest.mark.parametrize("code", [*InternalCode, "UNAPPROVED_PRIVATE_CODE", object()])
def test_only_typed_allowlisted_codes_escape(code):
    trace = ComparisonTrace()
    trace.start_world("LEAGUE_BASELINE")
    text = code.value if isinstance(code, InternalCode) else code
    error = trace.failure(
        Stage.RUN_LEAGUE_BASELINE_WORLD,
        Reason.BASELINE_WORLD_FAILED,
        PrivateV1Error(text, "private payload"),
    )
    assert error.diagnostic.internal_code == (code if isinstance(code, InternalCode) else None)
    arbitrary = SimpleNamespace(code="STAGE8_BLOCKED")
    assert (
        trace.failure(
            Stage.RUN_LEAGUE_BASELINE_WORLD, Reason.BASELINE_WORLD_FAILED, arbitrary
        ).diagnostic.internal_code
        is None
    )


@pytest.mark.parametrize("world", ["LEAGUE_BASELINE", "TEAM_STRENGTH_SHADOW"])
@pytest.mark.parametrize(
    "families,coverage",
    [
        ((), "PRIOR_ONLY"),
        ((MarketFamily.ONE_X_TWO,), "PARTIAL_MARKET"),
        ((MarketFamily.ONE_X_TWO, MarketFamily.TOTALS), "MARKET_BACKED"),
    ],
)
@pytest.mark.parametrize("outcome", ["invalid", "blocked", "projected", "fallback"])
def test_stage8_locations_counts_and_fallback_are_not_conflated(world, families, coverage, outcome):
    trace = ComparisonTrace()
    trace.start_world(world)
    with trace.activate():
        diagnostics.note_stage8_input(6, 3, families)
        if outcome == "invalid":
            diagnostics.note_stage8_input_failure(
                ScoreDistributionError("PRIOR_RATE_OUT_OF_RANGE", "private")
            )
        elif outcome == "blocked":
            diagnostics.note_stage8_blocked("FIXTURE_POSTPONED")
        else:
            diagnostics.note_stage8_projected(prior_fallback=outcome == "fallback")
    stage = (
        Stage.RUN_LEAGUE_BASELINE_WORLD
        if world == "LEAGUE_BASELINE"
        else Stage.RUN_TEAM_STRENGTH_WORLD
    )
    result = trace.failure(stage, Reason.BASELINE_WORLD_FAILED, ValueError("private")).diagnostic
    assert result.failed_world == world
    if outcome in {"invalid", "blocked"}:
        assert (
            result.failed_gameweek,
            result.failed_fixture_ordinal,
            result.market_coverage_class,
        ) == (6, 3, coverage)
        assert result.reason == (
            Reason.WORLD_STAGE8_INPUT_INVALID
            if outcome == "invalid"
            else Reason.WORLD_STAGE8_BLOCKED
        )
        assert result.internal_stage8_error_code is not None
    else:
        assert result.failed_gameweek is result.failed_fixture_ordinal is None
        assert result.stage8_outcome == (
            Stage8Outcome.PROJECTED_WITH_PRIOR_FALLBACK
            if outcome == "fallback"
            else Stage8Outcome.PROJECTED
        )
        assert result.baseline_stage8_projected + result.shadow_stage8_projected == 1
        assert result.baseline_stage8_prior_fallback + result.shadow_stage8_prior_fallback == (
            outcome == "fallback"
        )


def test_diagnostic_tamper_and_nonfinite_or_private_fields_fail_closed():
    value = (
        ComparisonTrace()
        .failure(Stage.VALIDATE_COMPARISON_INPUT, Reason.COMPARISON_INPUT_INVALID, ValueError())
        .diagnostic
    )
    for changes in (
        {"stage": "private"},
        {"reason": "private"},
        {"internal_code": "private"},
        {"failed_gameweek": 9999999},
        {"failed_fixture_ordinal": -1},
        {"control_name": "private"},
        {"baseline_world_completed": True},
        {"failed_gameweek": 1},
        {"provider_body": "private"},
    ):
        with pytest.raises(ValueError):
            ComparisonFailureDiagnostic.model_validate(vars(value) | changes)
    object.__setattr__(value, "internal_code", "private")
    with pytest.raises(ValueError):
        safe_comparison_failure(TeamStrengthComparisonFailure(value))


def test_control_name_allowlist_covers_exact_accepted_inventory():
    assert {item.value for item in ControlName} == CONTROL_NAMES
    trace = ComparisonTrace()
    with trace.activate():
        diagnostics.note_control_divergence((("work_budget", "a"),), (("work_budget", "b"),))
        assert trace.control == ControlName.work_budget
        diagnostics.note_control_divergence((), ())
        assert trace.control is None
        for name in ControlName:
            diagnostics.note_control_divergence(((name.value, "a"),), ((name.value, "b"),))
            assert trace.control is name


@pytest.mark.parametrize("failed_world", ["LEAGUE_BASELINE", "TEAM_STRENGTH_SHADOW"])
def test_public_comparison_reports_which_world_started_and_completed(
    comparison_inputs, monkeypatch, failed_world
):
    def run(self, execution):
        world = "LEAGUE_BASELINE" if self._score_prior_resolver is None else "TEAM_STRENGTH_SHADOW"
        if world == failed_world:
            raise PrivateV1Error("STAGE8_BLOCKED", "private body")
        return object()  # injected earlier completed world; never used as a mathematical result

    monkeypatch.setattr(comparison.PrivateV1RollingRecommendationService, "run", run)
    with pytest.raises(TeamStrengthComparisonFailure) as caught:
        comparison.run_team_strength_shadow_comparison(*comparison_inputs)
    result = caught.value.diagnostic
    assert result.failed_world == failed_world and result.reason == Reason.WORLD_STAGE8_BLOCKED
    assert result.baseline_world_started
    assert result.baseline_world_completed == (failed_world == "TEAM_STRENGTH_SHADOW")
    assert result.shadow_world_started == (failed_world == "TEAM_STRENGTH_SHADOW")
    assert not result.shadow_world_completed


@pytest.mark.parametrize(
    "target,expected",
    [
        ("binding", Stage.RECONCILE_WORLD_BINDINGS),
        ("_world", Stage.RECONCILE_WORLD_BINDINGS),
        ("controls", Stage.RECONCILE_HARD_CONTROLS),
        ("_movements", Stage.BUILD_PLAYER_MOVEMENT),
        ("summarise_movements", Stage.BUILD_PLAYER_MOVEMENT),
        ("_fixture_comparisons", Stage.BUILD_FIXTURE_PRIOR_COMPARISON),
        ("summarise_coverage", Stage.BUILD_FIXTURE_PRIOR_COMPARISON),
        ("compare_signatures", Stage.BUILD_DECISION_MATERIALITY),
        ("seal", Stage.SEAL_COMPARISON),
    ],
)
def test_post_solve_boundary_injections(comparison_inputs, monkeypatch, target, expected):
    prepared, preparation = comparison_inputs
    shadow = preparation.shadow_input
    baseline = SimpleNamespace(
        decision=SimpleNamespace(
            lineage=SimpleNamespace(
                rolling_execution_input_sha256=prepared.rolling_execution.semantic_sha256
            )
        )
    )
    alternative = SimpleNamespace(
        decision=SimpleNamespace(
            lineage=SimpleNamespace(rolling_execution_input_sha256=shadow.semantic_sha256)
        )
    )
    if target == "binding":
        baseline.decision.lineage.rolling_execution_input_sha256 = "wrong"

    def world(name, *args):
        return SimpleNamespace(
            signature=object(),
            controls=(
                (
                    "work_budget",
                    "different"
                    if target == "controls" and name == "TEAM_STRENGTH_SHADOW"
                    else "same",
                ),
            ),
        )

    monkeypatch.setattr(comparison, "_world", world)
    for name in (
        "_movements",
        "summarise_movements",
        "_fixture_comparisons",
        "summarise_coverage",
        "compare_signatures",
    ):
        monkeypatch.setattr(comparison, name, lambda *args: ())
    if target not in {"binding", "controls"}:
        monkeypatch.setattr(comparison, target, fail)
    trace = ComparisonTrace()
    for name in ("LEAGUE_BASELINE", "TEAM_STRENGTH_SHADOW"):
        trace.start_world(name)
        trace.complete_world(name)
    with pytest.raises(TeamStrengthComparisonFailure) as caught, trace.activate():
        comparison._compare_runs(prepared, shadow, baseline, alternative)
    result = caught.value.diagnostic
    assert result.stage == expected
    assert result.baseline_world_completed and result.shadow_world_completed
    assert result.failed_world is None
    assert result.control_name == (ControlName.work_budget if target == "controls" else None)


def test_consumed_authority_blocks_before_any_credentials_or_provider():
    class ForbiddenCredentials:
        def get(self):
            raise AssertionError("D1 must not inspect credentials")

        get_credential = get

    with pytest.raises(authority.ConsumedL1ApprovalError):
        authority.validate_l1_authority(
            approval=authority.APPROVAL,
            attestation=authority.ATTESTATION,
            checked_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    service = live.TeamStrengthL1ObservationService(
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        fpl_credentials=ForbiddenCredentials(),
        odds_credentials=ForbiddenCredentials(),
    )
    result = service.run(
        live.L1OperatorRequest(42, "a" * 40, authority.APPROVAL, authority.ATTESTATION, "0" * 64),
        None,
    )
    assert result["reason"] == "AUTHORITY_CONSUMED" and result["prior_l1_one_shot_consumed"]
    assert result["fpl_requests"] == result["odds_requests"] == 0
    assert not result["private_attempt_consumed"] and result["fresh_live_authorization_required"]


@pytest.mark.parametrize("tamper", [False, True])
def test_l1_serializes_only_valid_closed_comparison_diagnostic(monkeypatch, tamper):
    diagnostic = (
        ComparisonTrace()
        .failure(Stage.SEAL_COMPARISON, Reason.COMPARISON_SEAL_FAILED, ValueError())
        .diagnostic
    )
    if tamper:
        object.__setattr__(diagnostic, "internal_code", "private secret")
    error = TeamStrengthComparisonFailure(diagnostic)
    monkeypatch.setattr(
        live, "validate_l1_authority", lambda **kwargs: (_ for _ in ()).throw(error)
    )
    result = live.TeamStrengthL1ObservationService(
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC)
    ).run(
        live.L1OperatorRequest(42, "a" * 40, authority.APPROVAL, authority.ATTESTATION, "0" * 64),
        None,
    )
    assert result["reason"] == ("AUTHORITY_INVALID" if tamper else "COMPARISON_SEAL_FAILED")
    assert "private secret" not in str(result)


@pytest.mark.parametrize(
    "target,stage",
    [
        ("resolver", Stage.VALIDATE_SHADOW_RESOLVER),
        ("stage7", Stage.VALIDATE_STAGE7_CONTROL),
        ("timing", Stage.BUILD_TIMINGS),
    ],
)
def test_public_comparison_remaining_boundaries(comparison_inputs, monkeypatch, target, stage):
    if target == "resolver":
        monkeypatch.setattr(comparison._TeamStrengthShadowResolver, "validate_execution", fail)
    elif target == "stage7":
        monkeypatch.setattr(
            comparison, "horizon_fixtures", lambda _: (SimpleNamespace(stage7=None),)
        )
    else:
        monkeypatch.setattr(
            comparison.PrivateV1RollingRecommendationService, "run", lambda *args: object()
        )
        monkeypatch.setattr(comparison, "_compare_runs", lambda *args: object())
        monkeypatch.setattr(comparison, "_timing", fail)
    with pytest.raises(TeamStrengthComparisonFailure) as caught:
        comparison.run_team_strength_shadow_comparison(*comparison_inputs)
    diagnostic = caught.value.diagnostic
    assert diagnostic.stage == stage
    assert diagnostic.baseline_world_completed == (target == "timing")
    assert diagnostic.shadow_world_completed == (target == "timing")


@pytest.mark.parametrize("target", ["signature", "controls"])
def test_signature_failure_has_specific_nested_boundary(monkeypatch, target):
    decision = SimpleNamespace(by_gameweek=(), horizon_comparison=None)
    monkeypatch.setattr(
        comparison.PrivateV1RollingDecision, "model_validate_json", lambda _: decision
    )
    monkeypatch.setattr(comparison, "_candidate_screen_sha", lambda _: ("a" * 64, 0))
    if target == "signature":
        monkeypatch.setattr(comparison, "seal", fail)
    else:
        monkeypatch.setattr(comparison, "seal", lambda *args, **kwargs: object())
        monkeypatch.setattr(comparison, "_controls", fail)
    run = SimpleNamespace(decision=SimpleNamespace(model_dump_json=lambda: "{}"))
    trace = ComparisonTrace()
    with pytest.raises(TeamStrengthComparisonFailure) as caught, trace.activate():
        comparison._world("LEAGUE_BASELINE", None, run)
    assert caught.value.diagnostic.stage == (
        Stage.BUILD_DECISION_MATERIALITY if target == "signature" else Stage.RECONCILE_HARD_CONTROLS
    )


@pytest.mark.parametrize("world", ["LEAGUE_BASELINE", "TEAM_STRENGTH_SHADOW"])
@pytest.mark.parametrize("outcome", ["invalid", "blocked", "projected"])
def test_actual_private_stage8_boundary_emits_only_safe_location(
    comparison_inputs, monkeypatch, world, outcome
):
    from dmf_pulse.private_v1 import service

    project = service.ScoreDistributionService.project

    def injected(self, request):
        if outcome == "invalid":
            raise ScoreDistributionError("PRIOR_RATE_OUT_OF_RANGE", "synthetic private error")
        return project(self, request.model_copy(update={"fixture_status": "POSTPONED"}))

    if outcome != "projected":
        monkeypatch.setattr(service.ScoreDistributionService, "project", injected)
    else:
        monkeypatch.setattr(service, "_participation_scenarios", fail)
    trace = ComparisonTrace()
    trace.start_world(world)
    prepared, _ = comparison_inputs
    stage = (
        Stage.RUN_LEAGUE_BASELINE_WORLD
        if world == "LEAGUE_BASELINE"
        else Stage.RUN_TEAM_STRENGTH_WORLD
    )
    with (
        pytest.raises(TeamStrengthComparisonFailure) as caught,
        trace.activate(),
        comparison_boundary(stage, Reason.BASELINE_WORLD_FAILED),
    ):
        service._project_fixtures(prepared.rolling_execution.current_execution, None)
    value = safe_comparison_failure(caught.value)
    assert value["failed_world"] == world
    assert value["failed_fixture_ordinal"] == (None if outcome == "projected" else 1)
    assert value["failed_gameweek"] == (
        None if outcome == "projected" else prepared.rolling_execution.horizon_gameweeks[0]
    )
    if outcome == "projected":
        # This inherited generated fixture exercises the accepted numerical fallback.
        assert value["stage8_outcome"] == "PROJECTED_WITH_PRIOR_FALLBACK"
        assert value["baseline_stage8_prior_fallback"] + value["shadow_stage8_prior_fallback"] == 1
    else:
        assert (
            value["stage8_outcome"] == {"invalid": "INPUT_INVALID", "blocked": "BLOCKED"}[outcome]
        )
    assert "synthetic private" not in str(value)


def test_tampered_diagnostic_never_emits_serializer_warning(recwarn, capsys):
    error = ComparisonTrace().failure(
        Stage.SEAL_COMPARISON, Reason.COMPARISON_SEAL_FAILED, ValueError()
    )
    object.__setattr__(error.diagnostic, "internal_code", "SYNTHETIC_PRIVATE_CANARY")
    with pytest.raises(ValueError) as caught:
        safe_comparison_failure(error)
    assert "SYNTHETIC_PRIVATE_CANARY" not in str(caught.value)
    assert not recwarn.list
    output = capsys.readouterr()
    assert "SYNTHETIC_PRIVATE_CANARY" not in output.out + output.err
    object.__setattr__(error, "diagnostic", object())
    with pytest.raises(ValueError):
        safe_comparison_failure(error)


def test_completed_worlds_and_nested_boundary_preserve_specific_failure():
    trace = ComparisonTrace()
    for world in ("LEAGUE_BASELINE", "TEAM_STRENGTH_SHADOW"):
        trace.start_world(world)
        trace.complete_world(world)
    with (
        pytest.raises(TeamStrengthComparisonFailure) as caught,
        trace.activate(),
        comparison_boundary(Stage.VALIDATE_COMPARISON_INPUT, Reason.COMPARISON_INPUT_INVALID),
        comparison_boundary(Stage.BUILD_TIMINGS, Reason.COMPARISON_TIMING_FAILED),
    ):
        fail()
    value = safe_comparison_failure(caught.value)
    assert value["baseline_world_completed"] and value["shadow_world_completed"]
    assert value["stage"] == "BUILD_TIMINGS" and value["reason"] == "COMPARISON_TIMING_FAILED"


@pytest.mark.parametrize("kind", [RuntimeError, ArithmeticError, ValueError])
@pytest.mark.parametrize("after_success", [False, True])
def test_pending_projection_is_not_a_proved_input_failure(kind, after_success):
    trace = ComparisonTrace()
    trace.start_world("LEAGUE_BASELINE")
    error = kind("SYNTHETIC_PRIVATE_CANARY")
    with trace.activate():
        if after_success:
            diagnostics.note_stage8_input(1, 1, ())
            diagnostics.note_stage8_projected(prior_fallback=True)
        diagnostics.note_stage8_input(1, 2, ())
        if kind is ValueError:
            # Mirrors the original service's caught-input exception branch.
            diagnostics.note_stage8_input_failure(error)
            error = PrivateV1Error("STAGE8_INPUT_INVALID", "safe fixed text")
        value = safe_comparison_failure(
            trace.failure(Stage.RUN_LEAGUE_BASELINE_WORLD, Reason.BASELINE_WORLD_FAILED, error)
        )
    assert value["failed_fixture_ordinal"] == 2
    assert value["baseline_stage8_projected"] == int(after_success)
    assert value["stage8_outcome"] == ("INPUT_INVALID" if kind is ValueError else None)
    assert value["reason"] == (
        "WORLD_STAGE8_INPUT_INVALID" if kind is ValueError else "BASELINE_WORLD_FAILED"
    )
    assert "SYNTHETIC_PRIVATE_CANARY" not in str(value)
