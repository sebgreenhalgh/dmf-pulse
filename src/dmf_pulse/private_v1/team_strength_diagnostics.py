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
