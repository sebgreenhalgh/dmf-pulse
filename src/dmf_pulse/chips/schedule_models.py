"""Immutable finite-inventory chip-schedule contracts.

The scheduler consumes only forecasts that were usable at the request cutoff.
Future activations in a returned schedule are advisory continuation actions: the
replay layer must re-solve before any later action is executed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from dmf_pulse.chips.definitions import FrozenModel, PositiveInt, Sha256, semantic_sha256
from dmf_pulse.chips.inventory import ChipInventory, TokenStatus

FiniteFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0.0, allow_inf_nan=False)]
Probability = Annotated[StrictFloat, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


def require_utc(value: datetime, *, field_name: str) -> datetime:
    """Require an aware UTC timestamp without silently converting it."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must use UTC")
    return value


class OpportunitySourceKind(StrEnum):
    """Whether an opportunity can enter the executable truth path."""

    FORECAST = "FORECAST"
    REALISED_OUTCOME = "REALISED_OUTCOME"
    PERFECT_INFORMATION_DIAGNOSTIC = "PERFECT_INFORMATION_DIAGNOSTIC"


class ScheduleSearchMethod(StrEnum):
    EXACT_DYNAMIC_PROGRAMMING = "EXACT_DYNAMIC_PROGRAMMING"
    BOUNDED_BEAM = "BOUNDED_BEAM"


class ScheduleObjectiveMode(StrEnum):
    EXPECTED = "EXPECTED"
    ROBUST = "ROBUST"
    CASH_TERMINAL = "CASH_TERMINAL"


class RootScheduleAction(StrEnum):
    ACTIVATE = "ACTIVATE"
    HOLD = "HOLD"
    EXPIRE_UNUSED = "EXPIRE_UNUSED"


class TokenDispositionKind(StrEnum):
    SCHEDULED = "SCHEDULED"
    HOLD = "HOLD"
    EXPIRE_UNUSED = "EXPIRE_UNUSED"
    ALREADY_ACTIVE = "ALREADY_ACTIVE"
    ALREADY_USED = "ALREADY_USED"
    ALREADY_EXPIRED = "ALREADY_EXPIRED"


class ScheduleScenarioIdentity(FrozenModel):
    """One weighted member of the common scenario universe."""

    scenario_id: StrictStr = Field(min_length=1)
    outcome_draw_id: StrictStr = Field(min_length=1)
    weight: Probability


class ScheduleScenarioValue(FrozenModel):
    """One common-scenario value decomposition for one activation candidate."""

    scenario_id: StrictStr = Field(min_length=1)
    outcome_draw_id: StrictStr = Field(min_length=1)
    weight: Probability
    gross_current_gain: FiniteFloat
    continuation_value: FiniteFloat
    policy_cost: NonNegativeFloat = 0.0
    net_policy_value: FiniteFloat
    cash_like_value: FiniteFloat = 0.0
    terminal_state_value: FiniteFloat = 0.0

    @model_validator(mode="after")
    def value_reconciles(self) -> ScheduleScenarioValue:
        expected = self.gross_current_gain + self.continuation_value - self.policy_cost
        if abs(self.net_policy_value - expected) > 1e-9:
            raise ValueError(
                "schedule scenario net policy value must equal gross plus continuation minus cost"
            )
        return self


class OpportunityLineage(FrozenModel):
    """Deadline-safe lineage for a forecasted future exercise opportunity."""

    forecast_origin: datetime
    information_cutoff: datetime
    usable_at: datetime
    decision_cutoff: datetime
    source_kind: OpportunitySourceKind
    source_artifact_hash: Sha256
    scenario_set_hash: Sha256
    model_version: StrictStr = Field(min_length=1)
    configuration_hash: Sha256
    code_commit: StrictStr = Field(min_length=7)

    @model_validator(mode="after")
    def timestamps_are_valid(self) -> OpportunityLineage:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        usable = require_utc(self.usable_at, field_name="usable_at")
        decision = require_utc(self.decision_cutoff, field_name="decision_cutoff")
        if cutoff > origin:
            raise ValueError("opportunity information cutoff cannot follow forecast origin")
        if usable > origin:
            raise ValueError("opportunity cannot be usable after its forecast origin")
        if decision < origin:
            raise ValueError("activation decision cutoff cannot precede forecast origin")
        return self


class ChipScheduleOpportunity(FrozenModel):
    """One rules-bound candidate use of one finite inventory token."""

    opportunity_id: StrictStr = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    candidate_history_key: StrictStr = Field(min_length=1)
    token_id: StrictStr = Field(min_length=1)
    chip_key: StrictStr = Field(min_length=1)
    activation_gameweek: PositiveInt
    duration_gameweeks: PositiveInt
    requires_prior_opportunity_ids: tuple[StrictStr, ...] = ()
    forbids_prior_opportunity_ids: tuple[StrictStr, ...] = ()
    scenario_values: tuple[ScheduleScenarioValue, ...]
    expected_gross_current_gain: FiniteFloat
    expected_continuation_value: FiniteFloat
    expected_policy_cost: NonNegativeFloat
    expected_net_policy_value: FiniteFloat
    expected_cash_like_value: FiniteFloat
    expected_terminal_state_value: FiniteFloat
    robust_penalty: NonNegativeFloat = 0.0
    optimistic_upper_bound: FiniteFloat
    lineage: OpportunityLineage
    opportunity_hash: Sha256

    @model_validator(mode="after")
    def opportunity_reconciles(self) -> ChipScheduleOpportunity:
        identities = tuple(
            (item.scenario_id, item.outcome_draw_id) for item in self.scenario_values
        )
        if not identities or identities != tuple(sorted(identities)):
            raise ValueError("schedule opportunity scenarios must be non-empty and sorted")
        if len(identities) != len(set(identities)):
            raise ValueError("schedule opportunity scenario identities must be unique")
        if abs(sum(item.weight for item in self.scenario_values) - 1.0) > 1e-9:
            raise ValueError("schedule opportunity scenario weights must sum to one")
        if self.requires_prior_opportunity_ids != tuple(
            sorted(self.requires_prior_opportunity_ids)
        ):
            raise ValueError("required prior opportunity IDs must be sorted")
        if self.forbids_prior_opportunity_ids != tuple(sorted(self.forbids_prior_opportunity_ids)):
            raise ValueError("forbidden prior opportunity IDs must be sorted")
        if len(self.requires_prior_opportunity_ids) != len(
            set(self.requires_prior_opportunity_ids)
        ) or len(self.forbids_prior_opportunity_ids) != len(
            set(self.forbids_prior_opportunity_ids)
        ):
            raise ValueError("opportunity prefix constraints must be unique")
        if set(self.requires_prior_opportunity_ids) & set(self.forbids_prior_opportunity_ids):
            raise ValueError("an opportunity cannot both require and forbid the same prefix")
        if self.opportunity_id in self.requires_prior_opportunity_ids or self.opportunity_id in (
            self.forbids_prior_opportunity_ids
        ):
            raise ValueError("an opportunity cannot depend on itself")

        expected_fields = (
            (
                self.expected_gross_current_gain,
                sum(item.weight * item.gross_current_gain for item in self.scenario_values),
                "gross current gain",
            ),
            (
                self.expected_continuation_value,
                sum(item.weight * item.continuation_value for item in self.scenario_values),
                "continuation value",
            ),
            (
                self.expected_policy_cost,
                sum(item.weight * item.policy_cost for item in self.scenario_values),
                "policy cost",
            ),
            (
                self.expected_net_policy_value,
                sum(item.weight * item.net_policy_value for item in self.scenario_values),
                "net policy value",
            ),
            (
                self.expected_cash_like_value,
                sum(item.weight * item.cash_like_value for item in self.scenario_values),
                "cash-like value",
            ),
            (
                self.expected_terminal_state_value,
                sum(item.weight * item.terminal_state_value for item in self.scenario_values),
                "terminal-state value",
            ),
        )
        for observed, expected, label in expected_fields:
            if abs(observed - expected) > 1e-9:
                raise ValueError(f"schedule opportunity expected {label} does not reconcile")
        optimistic_floor = (
            self.expected_net_policy_value
            + self.expected_cash_like_value
            + self.expected_terminal_state_value
        )
        if self.optimistic_upper_bound + 1e-9 < optimistic_floor:
            raise ValueError("opportunity optimistic upper bound is below its declared value")
        payload = self.model_dump(mode="json", exclude={"opportunity_hash"})
        if self.opportunity_hash != "0" * 64 and semantic_sha256(payload) != self.opportunity_hash:
            raise ValueError("schedule opportunity hash mismatch")
        return self


class TerminalTokenValue(FrozenModel):
    """Explicit finite-horizon value of retaining one unused token."""

    token_id: StrictStr = Field(min_length=1)
    expected_terminal_value: FiniteFloat = 0.0
    cash_like_value: FiniteFloat = 0.0
    robust_penalty: NonNegativeFloat = 0.0


class ScheduleObjectiveConfig(FrozenModel):
    """Versioned deterministic search and objective controls."""

    objective_mode: ScheduleObjectiveMode = ScheduleObjectiveMode.EXPECTED
    exact_state_threshold: PositiveInt = 100_000
    beam_width: PositiveInt = 256
    beam_branch_limit: PositiveInt = 64
    max_returned_alternatives: PositiveInt = 20
    robust_penalty_weight: NonNegativeFloat = 1.0
    cash_like_weight: FiniteFloat = 1.0
    terminal_state_weight: NonNegativeFloat = 1.0
    tie_break_policy: Literal["PRESERVE_INVENTORY_THEN_LEXICOGRAPHIC"] = (
        "PRESERVE_INVENTORY_THEN_LEXICOGRAPHIC"
    )
    config_version: StrictStr = Field(min_length=1)


class ChipScheduleRequest(FrozenModel):
    """A sealed, deadline-safe finite-inventory schedule request."""

    request_id: StrictStr = Field(min_length=1)
    inventory: ChipInventory
    horizon_start_gameweek: PositiveInt
    horizon_end_gameweek: PositiveInt
    information_cutoff: datetime
    scenario_universe: tuple[ScheduleScenarioIdentity, ...]
    scenario_set_hash: Sha256
    opportunities: tuple[ChipScheduleOpportunity, ...]
    terminal_token_values: tuple[TerminalTokenValue, ...] = ()
    objective: ScheduleObjectiveConfig
    request_hash: Sha256

    @model_validator(mode="after")
    def request_is_coherent(self) -> ChipScheduleRequest:
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        if self.horizon_start_gameweek != self.inventory.current_gameweek:
            raise ValueError("schedule horizon must begin at the inventory Gameweek")
        if self.horizon_end_gameweek < self.horizon_start_gameweek:
            raise ValueError("schedule horizon is inverted")
        scenario_identities = tuple(
            (item.scenario_id, item.outcome_draw_id, item.weight) for item in self.scenario_universe
        )
        if not scenario_identities or scenario_identities != tuple(sorted(scenario_identities)):
            raise ValueError("schedule scenario universe must be non-empty and sorted")
        if len(scenario_identities) != len(set(scenario_identities)):
            raise ValueError("schedule scenario universe must be unique")
        if abs(sum(item.weight for item in self.scenario_universe) - 1.0) > 1e-9:
            raise ValueError("schedule scenario universe weights must sum to one")
        expected_scenario_hash = semantic_sha256(
            {"scenarios": [item.model_dump(mode="json") for item in self.scenario_universe]}
        )
        if self.scenario_set_hash != expected_scenario_hash:
            raise ValueError("schedule scenario-set hash mismatch")

        ordered = tuple(
            sorted(
                self.opportunities,
                key=lambda item: (
                    item.activation_gameweek,
                    item.chip_key,
                    item.token_id,
                    item.opportunity_id,
                ),
            )
        )
        if self.opportunities != ordered:
            raise ValueError("schedule opportunities must be sorted deterministically")
        opportunity_ids = tuple(item.opportunity_id for item in self.opportunities)
        if len(opportunity_ids) != len(set(opportunity_ids)):
            raise ValueError("schedule opportunity IDs must be unique")

        inventory_ids = tuple(item.token_id for item in self.inventory.tokens)
        if len(inventory_ids) != len(set(inventory_ids)):
            # The inventory model already enforces this. Keep the scheduler boundary explicit.
            raise ValueError("duplicate inventory token IDs are prohibited")
        token_map = {item.token_id: item for item in self.inventory.tokens}
        opportunity_map = {item.opportunity_id: item for item in self.opportunities}
        scenario_signature = scenario_identities
        for opportunity in self.opportunities:
            token = token_map.get(opportunity.token_id)
            if token is None:
                raise ValueError("schedule opportunity refers to an unknown inventory token")
            if opportunity.chip_key != token.chip_key:
                raise ValueError("schedule opportunity chip key differs from its inventory token")
            if opportunity.duration_gameweeks != token.duration_gameweeks:
                raise ValueError("schedule opportunity duration differs from its inventory token")
            if not (
                token.acquired_gameweek
                <= opportunity.activation_gameweek
                <= token.activation_end_gameweek
            ):
                raise ValueError("schedule opportunity lies outside token acquisition/window")
            if opportunity.activation_gameweek < token.activation_start_gameweek:
                raise ValueError("schedule opportunity precedes token activation start")
            if opportunity.activation_gameweek in token.excluded_gameweeks:
                raise ValueError("schedule opportunity uses an excluded Gameweek")
            if not (
                self.horizon_start_gameweek
                <= opportunity.activation_gameweek
                <= self.horizon_end_gameweek
            ):
                raise ValueError("schedule opportunity lies outside the request horizon")
            if token.status in {TokenStatus.USED, TokenStatus.EXPIRED, TokenStatus.ACTIVE}:
                raise ValueError("schedule opportunity targets a consumed or already-active token")
            lineage = opportunity.lineage
            if lineage.source_kind is not OpportunitySourceKind.FORECAST:
                raise ValueError("executable scheduler accepts forecast opportunities only")
            if lineage.usable_at > cutoff or lineage.information_cutoff > cutoff:
                raise ValueError("future-artifact leakage: opportunity was not usable at cutoff")
            if lineage.forecast_origin > cutoff:
                raise ValueError("future-artifact leakage: opportunity forecast is post-cutoff")
            if lineage.scenario_set_hash != self.scenario_set_hash:
                raise ValueError("schedule opportunity scenario hash differs from request")
            signature = tuple(
                (item.scenario_id, item.outcome_draw_id, item.weight)
                for item in opportunity.scenario_values
            )
            if signature != scenario_signature:
                raise ValueError("schedule opportunities are not aligned on common scenarios")
            for required_id in opportunity.requires_prior_opportunity_ids:
                required = opportunity_map.get(required_id)
                if required is None:
                    raise ValueError("required prior opportunity does not exist")
                if required.activation_gameweek >= opportunity.activation_gameweek:
                    raise ValueError("required opportunity must occur in an earlier Gameweek")
            for forbidden_id in opportunity.forbids_prior_opportunity_ids:
                forbidden = opportunity_map.get(forbidden_id)
                if forbidden is None:
                    raise ValueError("forbidden prior opportunity does not exist")
                if forbidden.activation_gameweek >= opportunity.activation_gameweek:
                    raise ValueError("forbidden prefix opportunity must occur earlier")

        terminal_ids = tuple(item.token_id for item in self.terminal_token_values)
        if terminal_ids != tuple(sorted(terminal_ids)):
            raise ValueError("terminal token values must be sorted by token ID")
        if len(terminal_ids) != len(set(terminal_ids)):
            raise ValueError("terminal token values must be unique by token ID")
        if not set(terminal_ids) <= set(inventory_ids):
            raise ValueError("terminal value refers to an unknown inventory token")
        payload = self.model_dump(mode="json", exclude={"request_hash"})
        if self.request_hash != "0" * 64 and semantic_sha256(payload) != self.request_hash:
            raise ValueError("chip schedule request hash mismatch")
        return self


class ScheduledActivation(FrozenModel):
    opportunity_id: StrictStr
    candidate_history_key: StrictStr
    token_id: StrictStr
    chip_key: StrictStr
    activation_gameweek: PositiveInt
    active_until_gameweek: PositiveInt
    expected_gross_current_gain: FiniteFloat
    expected_continuation_value: FiniteFloat
    expected_policy_cost: NonNegativeFloat
    expected_net_policy_value: FiniteFloat
    expected_cash_like_value: FiniteFloat
    expected_terminal_state_value: FiniteFloat
    robust_penalty: NonNegativeFloat
    opportunity_hash: Sha256


class TokenDisposition(FrozenModel):
    token_id: StrictStr
    chip_key: StrictStr
    disposition: TokenDispositionKind
    disposition_gameweek: PositiveInt | None = None


class ScheduleScenarioOutcome(FrozenModel):
    scenario_id: StrictStr
    outcome_draw_id: StrictStr
    weight: Probability
    gross_current_gain: FiniteFloat
    continuation_value: FiniteFloat
    policy_cost: NonNegativeFloat
    net_policy_value: FiniteFloat
    cash_like_value: FiniteFloat
    terminal_state_value: FiniteFloat
    expected_mode_value: FiniteFloat

    @model_validator(mode="after")
    def outcome_reconciles(self) -> ScheduleScenarioOutcome:
        if (
            abs(
                self.net_policy_value
                - (self.gross_current_gain + self.continuation_value - self.policy_cost)
            )
            > 1e-9
        ):
            raise ValueError("schedule scenario outcome decomposition does not reconcile")
        if (
            abs(self.expected_mode_value - (self.net_policy_value + self.terminal_state_value))
            > 1e-9
        ):
            raise ValueError("schedule expected-mode scenario value does not reconcile")
        return self


class ChipScheduleCandidate(FrozenModel):
    """One legal schedule and its complete common-scenario value decomposition."""

    schedule_id: StrictStr
    objective_mode: ScheduleObjectiveMode
    activations: tuple[ScheduledActivation, ...]
    token_dispositions: tuple[TokenDisposition, ...]
    scenario_outcomes: tuple[ScheduleScenarioOutcome, ...]
    expected_gross_current_gain: FiniteFloat
    expected_continuation_value: FiniteFloat
    expected_policy_cost: NonNegativeFloat
    expected_net_policy_value: FiniteFloat
    expected_cash_like_value: FiniteFloat
    expected_terminal_state_value: FiniteFloat
    robust_penalty: NonNegativeFloat
    expected_objective: FiniteFloat
    risk_adjusted_objective: FiniteFloat
    cash_terminal_objective: FiniteFloat
    selected_objective: FiniteFloat
    current_action: RootScheduleAction
    current_opportunity_ids: tuple[StrictStr, ...]
    schedule_hash: Sha256

    @model_validator(mode="after")
    def schedule_reconciles(self) -> ChipScheduleCandidate:
        ordering = tuple(
            sorted(
                self.activations,
                key=lambda item: (
                    item.activation_gameweek,
                    item.chip_key,
                    item.token_id,
                    item.opportunity_id,
                ),
            )
        )
        if self.activations != ordering:
            raise ValueError("scheduled activations must be sorted")
        token_ids = tuple(item.token_id for item in self.activations)
        if len(token_ids) != len(set(token_ids)):
            raise ValueError("a finite chip token cannot be scheduled more than once")
        identities = tuple(
            (item.scenario_id, item.outcome_draw_id) for item in self.scenario_outcomes
        )
        if not identities or identities != tuple(sorted(identities)):
            raise ValueError("schedule scenario outcomes must be non-empty and sorted")
        if len(identities) != len(set(identities)):
            raise ValueError("schedule scenario outcomes must be unique")
        if abs(sum(item.weight for item in self.scenario_outcomes) - 1.0) > 1e-9:
            raise ValueError("schedule scenario weights must sum to one")
        checks = (
            (
                self.expected_gross_current_gain,
                sum(item.weight * item.gross_current_gain for item in self.scenario_outcomes),
                "gross current gain",
            ),
            (
                self.expected_continuation_value,
                sum(item.weight * item.continuation_value for item in self.scenario_outcomes),
                "continuation value",
            ),
            (
                self.expected_policy_cost,
                sum(item.weight * item.policy_cost for item in self.scenario_outcomes),
                "policy cost",
            ),
            (
                self.expected_net_policy_value,
                sum(item.weight * item.net_policy_value for item in self.scenario_outcomes),
                "net policy value",
            ),
            (
                self.expected_cash_like_value,
                sum(item.weight * item.cash_like_value for item in self.scenario_outcomes),
                "cash-like value",
            ),
            (
                self.expected_terminal_state_value,
                sum(item.weight * item.terminal_state_value for item in self.scenario_outcomes),
                "terminal-state value",
            ),
            (
                self.expected_objective,
                sum(item.weight * item.expected_mode_value for item in self.scenario_outcomes),
                "expected objective",
            ),
        )
        for observed, expected, label in checks:
            if abs(observed - expected) > 1e-9:
                raise ValueError(f"schedule expected {label} does not reconcile")
        if self.current_opportunity_ids != tuple(sorted(self.current_opportunity_ids)):
            raise ValueError("current opportunity IDs must be sorted")
        if self.current_action is RootScheduleAction.ACTIVATE and not self.current_opportunity_ids:
            raise ValueError("ACTIVATE requires at least one current opportunity")
        if self.current_action is not RootScheduleAction.ACTIVATE and self.current_opportunity_ids:
            raise ValueError("non-activation root action cannot identify current opportunities")
        expected_selected = {
            ScheduleObjectiveMode.EXPECTED: self.expected_objective,
            ScheduleObjectiveMode.ROBUST: self.risk_adjusted_objective,
            ScheduleObjectiveMode.CASH_TERMINAL: self.cash_terminal_objective,
        }[self.objective_mode]
        if abs(self.selected_objective - expected_selected) > 1e-9:
            raise ValueError("schedule selected objective differs from its configured mode")
        payload = self.model_dump(mode="json", exclude={"schedule_hash"})
        if self.schedule_hash != "0" * 64 and semantic_sha256(payload) != self.schedule_hash:
            raise ValueError("chip schedule hash mismatch")
        return self


class ScheduleSearchDiagnostics(FrozenModel):
    method: ScheduleSearchMethod
    estimated_state_space: PositiveInt
    explored_states: NonNegativeInt
    pruned_states: NonNegativeInt
    feasible_schedules: PositiveInt
    memo_hits: NonNegativeInt
    beam_width: PositiveInt | None = None
    exact_optimality: StrictBool
    prefix_sensitive_memoisation: Literal[True]
    finite_state_optimistic_bounds: Literal[True]
    deterministic_tie_breaking: Literal[True]


class ProbabilityNowOptimalDiagnostic(FrozenModel):
    probability_now_optimal: Probability
    numerator_weight: Probability
    denominator_weight: Probability
    scenario_set_hash: Sha256
    comparison_rule: Literal["PER_SCENARIO_BEST_LEGAL_SCHEDULE_ACTIVATES_AT_ROOT"] = (
        "PER_SCENARIO_BEST_LEGAL_SCHEDULE_ACTIVATES_AT_ROOT"
    )
    objective_config_hash: Sha256
    exact_search: StrictBool
    diagnostic_only: Literal[True] = True


class PerfectInformationUpperBound(FrozenModel):
    expected_upper_bound: FiniteFloat
    executable_expected_objective: FiniteFloat
    upper_bound_gap: NonNegativeFloat
    scenario_best_schedule_ids: tuple[StrictStr, ...]
    bound_method: Literal["EXACT_SCENARIO_ORACLE", "RELAXED_FINITE_STATE_BOUND"]
    exact_search: StrictBool
    diagnostic_only: Literal[True] = True

    @model_validator(mode="after")
    def upper_bound_reconciles(self) -> PerfectInformationUpperBound:
        if (
            abs(
                self.upper_bound_gap
                - (self.expected_upper_bound - self.executable_expected_objective)
            )
            > 1e-9
        ):
            raise ValueError("perfect-information upper-bound gap does not reconcile")
        return self


class ChipSchedulePolicy(FrozenModel):
    """Executable root action plus advisory future finite-inventory schedule."""

    request_hash: Sha256
    selected_schedule: ChipScheduleCandidate
    best_use_now_schedule: ChipScheduleCandidate | None
    best_delay_schedule: ChipScheduleCandidate | None
    best_never_use_schedule: ChipScheduleCandidate
    alternatives: tuple[ChipScheduleCandidate, ...]
    recommended_action: RootScheduleAction
    selected_chip_keys: tuple[StrictStr, ...]
    selected_token_ids: tuple[StrictStr, ...]
    gross_current_gain: FiniteFloat
    net_policy_value: FiniteFloat
    continuation_value: FiniteFloat
    opportunity_cost: NonNegativeFloat
    exercise_advantage: FiniteFloat
    probability_now_optimal: ProbabilityNowOptimalDiagnostic
    perfect_information_upper_bound: PerfectInformationUpperBound
    diagnostics: ScheduleSearchDiagnostics
    future_schedule_advisory_only: Literal[True] = True
    policy_hash: Sha256

    @model_validator(mode="after")
    def policy_reconciles(self) -> ChipSchedulePolicy:
        alternative_hashes = tuple(item.schedule_hash for item in self.alternatives)
        if not alternative_hashes or len(alternative_hashes) != len(set(alternative_hashes)):
            raise ValueError("schedule alternatives must be non-empty and unique")
        if self.selected_schedule.schedule_hash not in set(alternative_hashes):
            raise ValueError("selected schedule must be retained in alternatives")
        if self.recommended_action != self.selected_schedule.current_action:
            raise ValueError("policy root action differs from selected schedule")
        if self.selected_chip_keys != tuple(sorted(self.selected_chip_keys)):
            raise ValueError("selected chip keys must be sorted")
        if self.selected_token_ids != tuple(sorted(self.selected_token_ids)):
            raise ValueError("selected token IDs must be sorted")
        expected_keys = tuple(
            sorted(
                item.chip_key
                for item in self.selected_schedule.activations
                if item.opportunity_id in self.selected_schedule.current_opportunity_ids
            )
        )
        expected_tokens = tuple(
            sorted(
                item.token_id
                for item in self.selected_schedule.activations
                if item.opportunity_id in self.selected_schedule.current_opportunity_ids
            )
        )
        if self.selected_chip_keys != expected_keys or self.selected_token_ids != expected_tokens:
            raise ValueError("selected root chip/token identities do not reconcile")
        baseline = self.best_never_use_schedule.selected_objective
        if (
            abs(self.net_policy_value - (self.selected_schedule.selected_objective - baseline))
            > 1e-9
        ):
            raise ValueError("policy net value must be relative to the never-use baseline")
        hold_value = baseline
        if self.best_delay_schedule is not None:
            hold_value = max(hold_value, self.best_delay_schedule.selected_objective)
        if self.best_use_now_schedule is not None:
            expected_advantage = self.best_use_now_schedule.selected_objective - hold_value
            if abs(self.exercise_advantage - expected_advantage) > 1e-9:
                raise ValueError("policy exercise advantage does not reconcile")
        payload = self.model_dump(mode="json", exclude={"policy_hash"})
        if self.policy_hash != "0" * 64 and semantic_sha256(payload) != self.policy_hash:
            raise ValueError("chip schedule policy hash mismatch")
        return self


def scenario_set_hash(
    values: tuple[ScheduleScenarioIdentity, ...] | tuple[ScheduleScenarioValue, ...],
) -> str:
    """Hash the ordered common-scenario universe and weights only."""

    return semantic_sha256(
        {
            "scenarios": [
                {
                    "scenario_id": item.scenario_id,
                    "outcome_draw_id": item.outcome_draw_id,
                    "weight": item.weight,
                }
                for item in values
            ]
        }
    )


def seal_opportunity(value: ChipScheduleOpportunity) -> ChipScheduleOpportunity:
    """Seal an opportunity after validating all non-hash fields."""

    payload = value.model_dump(mode="json", exclude={"opportunity_hash"})
    return ChipScheduleOpportunity.model_validate(
        value.model_copy(update={"opportunity_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def seal_schedule_request(value: ChipScheduleRequest) -> ChipScheduleRequest:
    """Seal a schedule request after validating all non-hash fields."""

    payload = value.model_dump(mode="json", exclude={"request_hash"})
    return ChipScheduleRequest.model_validate(
        value.model_copy(update={"request_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )
