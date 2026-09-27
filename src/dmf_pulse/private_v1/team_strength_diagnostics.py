"""Closed, transient diagnostics; no provider, logging, persistence or activation.

The ContextVar is populated only by the explicit two-world comparison. Ordinary
private construction sees no observer. No request/result object is retained here.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dmf_pulse.football_events.market_constraints import MarketFamily
from dmf_pulse.football_events.service import ScoreDistributionError
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.prepared_control import PreparedRollingControlFlow

World = Literal["LEAGUE_BASELINE", "TEAM_STRENGTH_SHADOW"]


class ComparisonStage(StrEnum):
    VALIDATE_COMPARISON_INPUT = "VALIDATE_COMPARISON_INPUT"
    VALIDATE_SHADOW_RESOLVER = "VALIDATE_SHADOW_RESOLVER"
    VALIDATE_STAGE7_CONTROL = "VALIDATE_STAGE7_CONTROL"
    RUN_LEAGUE_BASELINE_WORLD = "RUN_LEAGUE_BASELINE_WORLD"
    RUN_TEAM_STRENGTH_WORLD = "RUN_TEAM_STRENGTH_WORLD"
    RECONCILE_WORLD_BINDINGS = "RECONCILE_WORLD_BINDINGS"
    RECONCILE_HARD_CONTROLS = "RECONCILE_HARD_CONTROLS"
    BUILD_PLAYER_MOVEMENT = "BUILD_PLAYER_MOVEMENT"
    BUILD_FIXTURE_PRIOR_COMPARISON = "BUILD_FIXTURE_PRIOR_COMPARISON"
    BUILD_DECISION_MATERIALITY = "BUILD_DECISION_MATERIALITY"
    SEAL_COMPARISON = "SEAL_COMPARISON"
    BUILD_TIMINGS = "BUILD_TIMINGS"


class ComparisonReason(StrEnum):
    COMPARISON_INPUT_INVALID = "COMPARISON_INPUT_INVALID"
    SHADOW_RESOLVER_INVALID = "SHADOW_RESOLVER_INVALID"
    STAGE7_CONTROL_INVALID = "STAGE7_CONTROL_INVALID"
    BASELINE_WORLD_FAILED = "BASELINE_WORLD_FAILED"
    TEAM_STRENGTH_WORLD_FAILED = "TEAM_STRENGTH_WORLD_FAILED"
    WORLD_STAGE8_INPUT_INVALID = "WORLD_STAGE8_INPUT_INVALID"
    WORLD_STAGE8_BLOCKED = "WORLD_STAGE8_BLOCKED"
    WORLD_BINDING_MISMATCH = "WORLD_BINDING_MISMATCH"
    HARD_CONTROL_DIVERGENCE = "HARD_CONTROL_DIVERGENCE"
    PLAYER_PROJECTION_COVERAGE_MISMATCH = "PLAYER_PROJECTION_COVERAGE_MISMATCH"
    STAGE8_HORIZON_COVERAGE_MISMATCH = "STAGE8_HORIZON_COVERAGE_MISMATCH"
    MATERIALITY_COMPARISON_FAILED = "MATERIALITY_COMPARISON_FAILED"
    COMPARISON_SEAL_FAILED = "COMPARISON_SEAL_FAILED"
    COMPARISON_TIMING_FAILED = "COMPARISON_TIMING_FAILED"


class InternalCode(StrEnum):
    STAGE8_INPUT_INVALID = "STAGE8_INPUT_INVALID"
    STAGE8_BLOCKED = "STAGE8_BLOCKED"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    POLICY_INVALID = "POLICY_INVALID"
    MARKET_CONSTRAINT_INVALID = "MARKET_CONSTRAINT_INVALID"
    MARKET_SUPPORT_OUT_OF_RANGE = "MARKET_SUPPORT_OUT_OF_RANGE"
    PRIOR_RATE_OUT_OF_RANGE = "PRIOR_RATE_OUT_OF_RANGE"
    FIXTURE_POSTPONED = "FIXTURE_POSTPONED"
    FIXTURE_CANCELLED = "FIXTURE_CANCELLED"
    FIXTURE_ABANDONED = "FIXTURE_ABANDONED"
    STAGE9_GAMEWEEK_INVALID = "STAGE9_GAMEWEEK_INVALID"
    STAGE9_MC_QUALITY_BLOCKED = "STAGE9_MC_QUALITY_BLOCKED"
    ONE_GAMEWEEK_COMPARATOR_BLOCKED = "ONE_GAMEWEEK_COMPARATOR_BLOCKED"
    ROLLING_OPTIMISER_BLOCKED = "ROLLING_OPTIMISER_BLOCKED"
    ONE_GAMEWEEK_COUNTERFACTUAL_UNAVAILABLE = "ONE_GAMEWEEK_COUNTERFACTUAL_UNAVAILABLE"


class ControlName(StrEnum):
    algorithm_build = "algorithm_build"
    candidate_policy = "candidate_policy"
    chip_policy = "chip_policy"
    current_source = "current_source"
    draw_identity = "draw_identity"
    exact_acceleration = "exact_acceleration"
    fixture_order = "fixture_order"
    frozen_execution = "frozen_execution"
    future_price_policy = "future_price_policy"
    manager_state = "manager_state"
    market_constraints = "market_constraints"
    ownership = "ownership"
    player_allocation = "player_allocation"
    player_allocation_fallbacks = "player_allocation_fallbacks"
    prices = "prices"
    root_randomness = "root_randomness"
    rules = "rules"
    scenario_identity = "scenario_identity"
    scenario_policy = "scenario_policy"
    scenario_tree_policy = "scenario_tree_policy"
    stage7_contexts = "stage7_contexts"
    stage7_inputs = "stage7_inputs"
    terminal_policy = "terminal_policy"
    work_budget = "work_budget"


class Stage8Outcome(StrEnum):
    INPUT_INVALID = "INPUT_INVALID"
    BLOCKED = "BLOCKED"
    PROJECTED = "PROJECTED"
    PROJECTED_WITH_PRIOR_FALLBACK = "PROJECTED_WITH_PRIOR_FALLBACK"


class RollingPhase(StrEnum):
    VALIDATE_ROLLING_EXECUTION = "VALIDATE_ROLLING_EXECUTION"
    VERIFY_ROLLING_INPUTS = "VERIFY_ROLLING_INPUTS"
    PROJECT_GAMEWEEK_FIXTURES = "PROJECT_GAMEWEEK_FIXTURES"
    ASSEMBLE_GAMEWEEK_SCENARIOS = "ASSEMBLE_GAMEWEEK_SCENARIOS"
    CHECK_STAGE9_MC = "CHECK_STAGE9_MC"
    BUILD_ONE_GW_COMPARATOR_REQUEST = "BUILD_ONE_GW_COMPARATOR_REQUEST"
    PRECOMPUTE_ONE_GW_TACTICS = "PRECOMPUTE_ONE_GW_TACTICS"
    SOLVE_ONE_GW_COMPARATOR = "SOLVE_ONE_GW_COMPARATOR"
    VALIDATE_ONE_GW_RESULT = "VALIDATE_ONE_GW_RESULT"
    BUILD_THREE_GW_REQUEST = "BUILD_THREE_GW_REQUEST"
    PRECOMPUTE_THREE_GW_TACTICS = "PRECOMPUTE_THREE_GW_TACTICS"
    SOLVE_THREE_GW_POLICY = "SOLVE_THREE_GW_POLICY"
    VALIDATE_THREE_GW_RESULT = "VALIDATE_THREE_GW_RESULT"
    BUILD_TRANSFER_FRONTIER = "BUILD_TRANSFER_FRONTIER"
    BUILD_GAMEWEEK_DECISIONS = "BUILD_GAMEWEEK_DECISIONS"
    BUILD_HORIZON_COMPARISON = "BUILD_HORIZON_COMPARISON"
    BUILD_ONE_GW_VS_ROLLING_COMPARISON = "BUILD_ONE_GW_VS_ROLLING_COMPARISON"
    SEAL_ROLLING_DECISION = "SEAL_ROLLING_DECISION"
    BUILD_ROLLING_REPORT = "BUILD_ROLLING_REPORT"
    BUILD_STAGE11_WORK = "BUILD_STAGE11_WORK"


class RollingFailureClass(StrEnum):
    TYPED_FAILURE = "TYPED_FAILURE"
    OPTIMISER_FAILURE = "OPTIMISER_FAILURE"
    UNEXPECTED_FAILURE = "UNEXPECTED_FAILURE"


class RollingOptimiserStatusClass(StrEnum):
    SUCCESS = "SUCCESS"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    INFEASIBLE = "INFEASIBLE"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class RollingOptimiserBackendStatusClass(StrEnum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE_NOT_PROVEN_OPTIMAL = "FEASIBLE_NOT_PROVEN_OPTIMAL"
    TIME_RESOURCE_LIMIT_WITH_INCUMBENT = "TIME_RESOURCE_LIMIT_WITH_INCUMBENT"
    TIME_RESOURCE_LIMIT_NO_INCUMBENT = "TIME_RESOURCE_LIMIT_NO_INCUMBENT"
    INFEASIBLE = "INFEASIBLE"
    UNBOUNDED = "UNBOUNDED"
    SOLVER_BACKEND_ERROR = "SOLVER_BACKEND_ERROR"
    INPUT_CAPABILITY_BLOCKED = "INPUT_CAPABILITY_BLOCKED"


class RollingInternalCode(StrEnum):
    STAGE9_GAMEWEEK_INVALID = "STAGE9_GAMEWEEK_INVALID"
    STAGE9_MC_QUALITY_BLOCKED = "STAGE9_MC_QUALITY_BLOCKED"
    ROLLING_HORIZON_INCOMPLETE = "ROLLING_HORIZON_INCOMPLETE"
    ONE_GAMEWEEK_COMPARATOR_BLOCKED = "ONE_GAMEWEEK_COMPARATOR_BLOCKED"
    MULTI_GAMEWEEK_PRODUCTION_BACKEND_UNAVAILABLE = "MULTI_GAMEWEEK_PRODUCTION_BACKEND_UNAVAILABLE"
    MULTI_GAMEWEEK_INPUT_INVALID = "MULTI_GAMEWEEK_INPUT_INVALID"
    MULTI_GAMEWEEK_INFEASIBLE = "MULTI_GAMEWEEK_INFEASIBLE"
    MULTI_GAMEWEEK_RESOURCE_LIMIT = "MULTI_GAMEWEEK_RESOURCE_LIMIT"
    OPTIMISER_EMITTED_INVALID_POLICY = "OPTIMISER_EMITTED_INVALID_POLICY"
    NO_TRANSFER_BASELINE_UNAVAILABLE = "NO_TRANSFER_BASELINE_UNAVAILABLE"
    MOVE_ATTRIBUTION_INVALID = "MOVE_ATTRIBUTION_INVALID"
    ROLLING_OPTIMISER_BLOCKED = "ROLLING_OPTIMISER_BLOCKED"
    ONE_GAMEWEEK_COUNTERFACTUAL_UNAVAILABLE = "ONE_GAMEWEEK_COUNTERFACTUAL_UNAVAILABLE"
    ROLLING_FRONTIER_UNAVAILABLE = "ROLLING_FRONTIER_UNAVAILABLE"
    ROLLING_POLICY_INCOMPLETE = "ROLLING_POLICY_INCOMPLETE"
    ROLLING_FT_TRANSITION_MISMATCH = "ROLLING_FT_TRANSITION_MISMATCH"
    ROLLING_COMPARATOR_SCENARIO_MISMATCH = "ROLLING_COMPARATOR_SCENARIO_MISMATCH"
    ROLLING_COMPARATOR_INVALID = "ROLLING_COMPARATOR_INVALID"
    ROLLING_COMPARATOR_HORIZON_MISMATCH = "ROLLING_COMPARATOR_HORIZON_MISMATCH"
    ROLLING_COMPARATOR_OBJECTIVE_MISMATCH = "ROLLING_COMPARATOR_OBJECTIVE_MISMATCH"
    COUNTERFACTUAL_ACTION_MISMATCH = "COUNTERFACTUAL_ACTION_MISMATCH"
    PRIVATE_V1_FAILURE_UNCLASSIFIED = "PRIVATE_V1_FAILURE_UNCLASSIFIED"
    OPTIMISER_FAILURE_UNCLASSIFIED = "OPTIMISER_FAILURE_UNCLASSIFIED"
    ROLLING_UNEXPECTED_FAILURE = "ROLLING_UNEXPECTED_FAILURE"


class ComparisonFailureDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    stage: ComparisonStage
    reason: ComparisonReason
    internal_code: InternalCode | None = None
    failed_world: World | None = None
    baseline_world_started: bool
    baseline_world_completed: bool
    shadow_world_started: bool
    shadow_world_completed: bool
    failed_gameweek: int | None = Field(default=None, ge=1, le=38)
    failed_fixture_ordinal: int | None = Field(default=None, ge=1, le=380)
    market_coverage_class: Literal["MARKET_BACKED", "PARTIAL_MARKET", "PRIOR_ONLY"] | None = None
    stage8_outcome: Stage8Outcome | None = None
    internal_stage8_error_code: InternalCode | None = None
    baseline_stage8_projected: int = Field(default=0, ge=0, le=380)
    shadow_stage8_projected: int = Field(default=0, ge=0, le=380)
    baseline_stage8_prior_fallback: int = Field(default=0, ge=0, le=380)
    shadow_stage8_prior_fallback: int = Field(default=0, ge=0, le=380)
    control_name: ControlName | None = None
    rolling_phase: RollingPhase | None = None
    rolling_gameweek: int | None = Field(default=None, ge=1, le=38)
    rolling_failure_class: RollingFailureClass | None = None
    rolling_internal_code: RollingInternalCode | None = None
    optimiser_status_class: RollingOptimiserStatusClass | None = None
    optimiser_backend_status_class: RollingOptimiserBackendStatusClass | None = None
    gameweeks_stage8_complete: int = Field(default=0, ge=0, le=3)
    gameweeks_stage9_assembled: int = Field(default=0, ge=0, le=3)
    gameweeks_stage9_mc_passed: int = Field(default=0, ge=0, le=3)

    @model_validator(mode="after")
    def consistent_progress(self) -> Self:
        if (self.baseline_world_completed and not self.baseline_world_started) or (
            self.shadow_world_completed and not self.shadow_world_started
        ):
            raise ValueError("invalid comparison progress")
        location = (self.failed_gameweek, self.failed_fixture_ordinal, self.market_coverage_class)
        if any(item is not None for item in location) and not all(
            item is not None for item in location
        ):
            raise ValueError("partial Stage-8 location")
        if self.rolling_phase is None and any(
            item is not None
            for item in (
                self.rolling_gameweek,
                self.rolling_failure_class,
                self.rolling_internal_code,
                self.optimiser_status_class,
                self.optimiser_backend_status_class,
            )
        ):
            raise ValueError("rolling detail requires rolling phase")
        if self.rolling_phase is not None and (
            self.rolling_failure_class is None or self.rolling_internal_code is None
        ):
            raise ValueError("rolling phase requires finite failure classification")
        if (self.optimiser_status_class is None) != (self.optimiser_backend_status_class is None):
            raise ValueError("partial optimiser status")
        if not (
            self.gameweeks_stage9_mc_passed
            <= self.gameweeks_stage9_assembled
            <= self.gameweeks_stage8_complete
        ):
            raise ValueError("invalid rolling progress")
        return self


class TeamStrengthComparisonFailure(PreparedRollingControlFlow):
    """Only the frozen closed diagnostic is serializable; exception text is unused."""

    def __init__(self, diagnostic: ComparisonFailureDiagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(f"{diagnostic.stage.value}: {diagnostic.reason.value}")


def safe_comparison_failure(error: TeamStrengthComparisonFailure) -> dict[str, object]:
    # Revalidate even a model_copy/object.__setattr__ tamper at the terminal boundary.
    if type(error.diagnostic) is not ComparisonFailureDiagnostic:
        raise ValueError("invalid diagnostic type")
    # Validate before serialization: serializer warnings can quote invalid values.
    # The raw field dictionary also preserves unexpected model_copy keys for rejection.
    try:
        value = ComparisonFailureDiagnostic.model_validate(vars(error.diagnostic))
    except ValidationError:
        raise ValueError("invalid comparison diagnostic") from None
    return value.model_dump(mode="json")


def _code(value: object) -> InternalCode | None:
    return InternalCode(value) if type(value) is str and value in InternalCode else None


@dataclass
class ComparisonTrace:
    started: set[World] = field(default_factory=set)
    completed: set[World] = field(default_factory=set)
    world: World | None = None
    location: tuple[int, int, Literal["MARKET_BACKED", "PARTIAL_MARKET", "PRIOR_ONLY"]] | None = (
        None
    )
    stage8_outcome: Stage8Outcome | None = None
    stage8_code: InternalCode | None = None
    projected: dict[World, int] = field(default_factory=dict)
    fallback: dict[World, int] = field(default_factory=dict)
    control: ControlName | None = None
    rolling_phase: RollingPhase | None = None
    rolling_gameweek: int | None = None
    rolling_failure_class: RollingFailureClass | None = None
    rolling_internal_code: RollingInternalCode | None = None
    optimiser_status_class: RollingOptimiserStatusClass | None = None
    optimiser_backend_status_class: RollingOptimiserBackendStatusClass | None = None
    gameweeks_stage8_complete: int = 0
    gameweeks_stage9_assembled: int = 0
    gameweeks_stage9_mc_passed: int = 0

    @contextmanager
    def activate(self) -> Iterator[None]:
        token = _TRACE.set(self)
        try:
            yield
        finally:
            _TRACE.reset(token)

    def start_world(self, world: World) -> None:
        self.world = world
        self.started.add(world)
        self.location = None
        self.stage8_outcome = None
        self.stage8_code = None
        self.rolling_phase = None
        self.rolling_gameweek = None
        self.rolling_failure_class = None
        self.rolling_internal_code = None
        self.optimiser_status_class = None
        self.optimiser_backend_status_class = None
        self.gameweeks_stage8_complete = 0
        self.gameweeks_stage9_assembled = 0
        self.gameweeks_stage9_mc_passed = 0

    def complete_world(self, world: World) -> None:
        self.completed.add(world)
        self.world = None

    def failure(
        self, stage: ComparisonStage, reason: ComparisonReason, error: Exception
    ) -> TeamStrengthComparisonFailure:
        code = _code(error.code) if isinstance(error, PrivateV1Error) else None
        world_stage = stage in {
            ComparisonStage.RUN_LEAGUE_BASELINE_WORLD,
            ComparisonStage.RUN_TEAM_STRENGTH_WORLD,
        }
        if world_stage and self.rolling_phase is not None and self.rolling_failure_class is None:
            self.rolling_failure_class = (
                RollingFailureClass.UNEXPECTED_FAILURE
                if not isinstance(error, PrivateV1Error)
                else RollingFailureClass.OPTIMISER_FAILURE
                if self.rolling_phase in _OPTIMISER_PHASES
                else RollingFailureClass.TYPED_FAILURE
            )
            self.rolling_internal_code = _rolling_code(error, self.rolling_phase)
        outcome = self.stage8_outcome if world_stage else None
        if world_stage:
            if outcome == Stage8Outcome.INPUT_INVALID or code == InternalCode.STAGE8_INPUT_INVALID:
                reason = ComparisonReason.WORLD_STAGE8_INPUT_INVALID
            elif outcome == Stage8Outcome.BLOCKED or code == InternalCode.STAGE8_BLOCKED:
                reason = ComparisonReason.WORLD_STAGE8_BLOCKED
        location = self.location if world_stage else None
        return TeamStrengthComparisonFailure(
            ComparisonFailureDiagnostic(
                stage=stage,
                reason=reason,
                internal_code=code,
                failed_world=self.world if world_stage else None,
                baseline_world_started="LEAGUE_BASELINE" in self.started,
                baseline_world_completed="LEAGUE_BASELINE" in self.completed,
                shadow_world_started="TEAM_STRENGTH_SHADOW" in self.started,
                shadow_world_completed="TEAM_STRENGTH_SHADOW" in self.completed,
                failed_gameweek=location[0] if location else None,
                failed_fixture_ordinal=location[1] if location else None,
                market_coverage_class=location[2] if location else None,
                stage8_outcome=outcome,
                internal_stage8_error_code=self.stage8_code if world_stage else None,
                baseline_stage8_projected=self.projected.get("LEAGUE_BASELINE", 0),
                shadow_stage8_projected=self.projected.get("TEAM_STRENGTH_SHADOW", 0),
                baseline_stage8_prior_fallback=self.fallback.get("LEAGUE_BASELINE", 0),
                shadow_stage8_prior_fallback=self.fallback.get("TEAM_STRENGTH_SHADOW", 0),
                control_name=self.control
                if stage == ComparisonStage.RECONCILE_HARD_CONTROLS
                else None,
                rolling_phase=self.rolling_phase if world_stage else None,
                rolling_gameweek=self.rolling_gameweek if world_stage else None,
                rolling_failure_class=self.rolling_failure_class if world_stage else None,
                rolling_internal_code=self.rolling_internal_code if world_stage else None,
                optimiser_status_class=(self.optimiser_status_class if world_stage else None),
                optimiser_backend_status_class=(
                    self.optimiser_backend_status_class if world_stage else None
                ),
                gameweeks_stage8_complete=(self.gameweeks_stage8_complete if world_stage else 0),
                gameweeks_stage9_assembled=(self.gameweeks_stage9_assembled if world_stage else 0),
                gameweeks_stage9_mc_passed=(self.gameweeks_stage9_mc_passed if world_stage else 0),
            )
        )


_TRACE: ContextVar[ComparisonTrace | None] = ContextVar(
    "team_strength_comparison_trace", default=None
)


@contextmanager
def comparison_boundary(stage: ComparisonStage, reason: ComparisonReason) -> Iterator[None]:
    trace = _TRACE.get()
    try:
        yield
    except TeamStrengthComparisonFailure:
        raise
    except Exception as error:
        if trace is None:
            raise
        raise trace.failure(stage, reason, error) from None


_OPTIMISER_PHASES = frozenset(
    {
        RollingPhase.SOLVE_ONE_GW_COMPARATOR,
        RollingPhase.VALIDATE_ONE_GW_RESULT,
        RollingPhase.SOLVE_THREE_GW_POLICY,
        RollingPhase.VALIDATE_THREE_GW_RESULT,
    }
)


def _rolling_code(error: Exception, phase: RollingPhase) -> RollingInternalCode:
    if not isinstance(error, PrivateV1Error):
        return RollingInternalCode.ROLLING_UNEXPECTED_FAILURE
    if type(error.code) is str and error.code in RollingInternalCode:
        return RollingInternalCode(error.code)
    if phase in _OPTIMISER_PHASES:
        return RollingInternalCode.OPTIMISER_FAILURE_UNCLASSIFIED
    return RollingInternalCode.PRIVATE_V1_FAILURE_UNCLASSIFIED


@contextmanager
def rolling_boundary(phase: RollingPhase, *, gameweek: int | None = None) -> Iterator[None]:
    """Record one rolling phase only while an explicit comparison trace is active."""

    trace = _TRACE.get()
    if trace is None:
        yield
        return
    trace.rolling_phase = phase
    trace.rolling_gameweek = gameweek
    trace.rolling_failure_class = None
    trace.rolling_internal_code = None
    try:
        yield
    except TeamStrengthComparisonFailure:
        raise
    except Exception as error:
        trace.rolling_failure_class = (
            RollingFailureClass.UNEXPECTED_FAILURE
            if not isinstance(error, PrivateV1Error)
            else RollingFailureClass.OPTIMISER_FAILURE
            if phase in _OPTIMISER_PHASES
            else RollingFailureClass.TYPED_FAILURE
        )
        trace.rolling_internal_code = _rolling_code(error, phase)
        raise


def note_rolling_progress(kind: Literal["STAGE8", "STAGE9_ASSEMBLED", "STAGE9_MC_PASS"]) -> None:
    trace = _TRACE.get()
    if trace is None:
        return
    if kind == "STAGE8":
        trace.gameweeks_stage8_complete += 1
    elif kind == "STAGE9_ASSEMBLED":
        trace.gameweeks_stage9_assembled += 1
    else:
        trace.gameweeks_stage9_mc_passed += 1


def note_rolling_phase(phase: RollingPhase, *, gameweek: int | None = None) -> None:
    """Mark the finite phase for non-call scaffolding between guarded operations."""

    trace = _TRACE.get()
    if trace is not None:
        trace.rolling_phase = phase
        trace.rolling_gameweek = gameweek
        trace.rolling_failure_class = None
        trace.rolling_internal_code = None


def note_optimiser_result(*, status: object, backend_status: object) -> None:
    trace = _TRACE.get()
    if trace is not None:
        status_value = getattr(status, "value", None)
        backend_value = getattr(backend_status, "value", None)
        trace.optimiser_status_class = (
            RollingOptimiserStatusClass(status_value)
            if isinstance(status_value, str) and status_value in RollingOptimiserStatusClass
            else None
        )
        trace.optimiser_backend_status_class = (
            RollingOptimiserBackendStatusClass(backend_value)
            if isinstance(backend_value, str)
            and backend_value in RollingOptimiserBackendStatusClass
            else None
        )


def note_control_divergence(
    left: tuple[tuple[str, str], ...], right: tuple[tuple[str, str], ...]
) -> None:
    trace = _TRACE.get()
    if trace is not None:
        a, b = dict(left), dict(right)
        trace.control = next((name for name in ControlName if a.get(name) != b.get(name)), None)


def note_stage8_input(gameweek: int, ordinal: int, families: tuple[MarketFamily, ...]) -> None:
    trace = _TRACE.get()
    if trace is not None:
        coverage: Literal["MARKET_BACKED", "PARTIAL_MARKET", "PRIOR_ONLY"] = (
            "PRIOR_ONLY"
            if not families
            else "MARKET_BACKED"
            if {MarketFamily.ONE_X_TWO, MarketFamily.TOTALS} <= set(families)
            else "PARTIAL_MARKET"
        )
        trace.location = (gameweek, ordinal, coverage)
        # The call has started, but its failure class is not yet known.
        trace.stage8_outcome = None
        trace.stage8_code = None


def note_stage8_input_failure(error: Exception) -> None:
    trace = _TRACE.get()
    if trace is not None:
        trace.stage8_outcome = Stage8Outcome.INPUT_INVALID
        trace.stage8_code = _code(error.code) if isinstance(error, ScoreDistributionError) else None


def note_stage8_blocked(code: str | None) -> None:
    trace = _TRACE.get()
    if trace is not None:
        trace.stage8_outcome = Stage8Outcome.BLOCKED
        trace.stage8_code = _code(code)


def note_stage8_projected(*, prior_fallback: bool = False) -> None:
    trace = _TRACE.get()
    if trace is not None and trace.world is not None:
        trace.projected[trace.world] = trace.projected.get(trace.world, 0) + 1
        if prior_fallback:
            trace.fallback[trace.world] = trace.fallback.get(trace.world, 0) + 1
        # A later Stage-9/10/11 failure must not blame the last successful fixture.
        trace.location = None
        trace.stage8_outcome = (
            Stage8Outcome.PROJECTED_WITH_PRIOR_FALLBACK
            if prior_fallback
            else Stage8Outcome.PROJECTED
        )
        trace.stage8_code = None
