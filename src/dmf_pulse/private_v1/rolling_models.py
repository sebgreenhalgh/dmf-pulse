"""Separate immutable contracts for the explicit private three-Gameweek mode."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.current_model import CurrentModelFixtureMinutesInput
from dmf_pulse.availability.manual_override import ManualFixtureMinutesInput
from dmf_pulse.football_events.market_constraints import MarketConstraint
from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.models import NonNegativeInt, Sha256
from dmf_pulse.private_v1.models import (
    PrivateFixtureScorePrior,
    PrivateFreeTransferState,
    PrivateGainMass,
    PrivateTacticalDecision,
    PrivateTransferMove,
    PrivateV1ExecutionInput,
)


class _RollingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """Revalidate copies so nested tampering cannot bypass public invariants."""

        del deep
        payload = {field_name: getattr(self, field_name) for field_name in type(self).model_fields}
        if update:
            payload.update(update)
        return type(self).model_validate(payload)


def _semantic_hash(value: BaseModel) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


def _utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


class PrivateRollingFixtureInput(_RollingModel):
    """One future fixture projected from the current immutable information cutoff."""

    schema_version: Literal["private-rolling-fixture-input-v1"] = "private-rolling-fixture-input-v1"
    official_fpl_fixture_id: PositiveInt
    official_fpl_fixture_lookup_sha256: Sha256
    canonical_fixture_id: UUID
    home_official_fpl_team_id: PositiveInt
    away_official_fpl_team_id: PositiveInt
    home_canonical_team_id: UUID
    away_canonical_team_id: UUID
    kickoff_at: datetime
    information_cutoff: datetime
    market_mode: Literal["MARKET_BACKED", "SCORE_PRIOR_ONLY", "BLOCKED"]
    market_constraints: tuple[MarketConstraint, ...]
    blocked_reason: StrictStr | None = None
    score_prior: PrivateFixtureScorePrior
    stage7: ManualFixtureMinutesInput | CurrentModelFixtureMinutesInput
    warnings: tuple[StrictStr, ...] = ()
    semantic_sha256: Sha256

    @field_validator("kickoff_at", "information_cutoff")
    @classmethod
    def times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, label=info.field_name)

    @model_validator(mode="after")
    def fixture_is_coherent_and_sealed(self) -> Self:
        fixture_id = str(self.canonical_fixture_id)
        prior = self.score_prior
        stage7 = self.stage7
        if self.home_official_fpl_team_id == self.away_official_fpl_team_id:
            raise ValueError("future fixture teams must differ")
        if self.home_canonical_team_id == self.away_canonical_team_id:
            raise ValueError("future canonical teams must differ")
        if self.kickoff_at <= self.information_cutoff:
            raise ValueError("future fixture kickoff must be after the current cutoff")
        if (
            str(prior.fixture_id) != fixture_id
            or prior.home_team_id != self.home_canonical_team_id
            or prior.away_team_id != self.away_canonical_team_id
            or prior.as_of != self.information_cutoff
            or stage7.fixture_id != fixture_id
            or stage7.home_team_id != str(self.home_canonical_team_id)
            or stage7.away_team_id != str(self.away_canonical_team_id)
            or stage7.information_cutoff != self.information_cutoff
        ):
            raise ValueError("future fixture Stage-7/prior identity or cutoff differs")
        if self.market_mode == "MARKET_BACKED":
            if not self.market_constraints or self.blocked_reason is not None:
                raise ValueError("market-backed fixture requires constraints and no blocker")
        elif self.market_mode == "SCORE_PRIOR_ONLY":
            if self.market_constraints or self.blocked_reason is not None:
                raise ValueError("score-prior-only fixture cannot carry market evidence")
        elif self.market_constraints or not self.blocked_reason:
            raise ValueError("blocked future fixture requires one typed blocker")
        if any(item.usable_at > self.information_cutoff for item in self.market_constraints):
            raise ValueError("future market constraint is post-cutoff")
        if self.warnings != tuple(sorted(set(self.warnings))):
            raise ValueError("future fixture warnings must be unique and sorted")
        if self.semantic_sha256 != _semantic_hash(self):
            raise ValueError("future fixture semantic hash does not match")
        return self


def seal_rolling_fixture_input(value: PrivateRollingFixtureInput) -> PrivateRollingFixtureInput:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


class PrivateRollingGameweekInput(_RollingModel):
    """Complete officially assigned future fixture set for one horizon Gameweek."""

    schema_version: Literal["private-rolling-gameweek-input-v1"] = (
        "private-rolling-gameweek-input-v1"
    )
    gameweek: PositiveInt
    fixtures: Annotated[tuple[PrivateRollingFixtureInput, ...], Field(min_length=1)]
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def gameweek_is_canonical_and_sealed(self) -> Self:
        ids = tuple(item.official_fpl_fixture_id for item in self.fixtures)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("future Gameweek fixtures must be unique and sorted")
        if self.semantic_sha256 != _semantic_hash(self):
            raise ValueError("future Gameweek semantic hash does not match")
        return self


def seal_rolling_gameweek_input(
    value: PrivateRollingGameweekInput,
) -> PrivateRollingGameweekInput:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


class PrivateV1RollingExecutionInput(_RollingModel):
    """Explicit three-GW wrapper; the accepted one-GW input remains unchanged."""

    schema_version: Literal["private-v1-rolling-execution-input-v1"] = (
        "private-v1-rolling-execution-input-v1"
    )
    horizon_gameweeks: tuple[PositiveInt, PositiveInt, PositiveInt]
    current_execution: PrivateV1ExecutionInput
    future_gameweeks: tuple[PrivateRollingGameweekInput, PrivateRollingGameweekInput]
    terminal_value_mode: Literal["THREE_GAMEWEEK_ZERO_TERMINAL_VALUE_AFTER_HORIZON"]
    terminal_policy_sha256: Sha256
    future_price_mode: Literal["FUTURE_PRICE_CHANGES_NOT_MODELLED_IN_PRIVATE_3GW_V1"]
    scenario_tree_mode: Literal["DETERMINISTIC_NO_NEW_INFORMATION_REVELATION_V1"]
    search_scope_mode: Literal["PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1"]
    transfer_count_scope_source: Literal[
        "CURRENT_FT_COMPILED_RULES_AND_TICKET_BOUNDED_SEARCH_POLICY"
    ]
    maximum_transfers_per_deadline: Annotated[StrictInt, Field(ge=0, le=2)]
    chip_mode: Literal["NO_CHIP_EXPLICIT"]
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def horizon_is_coherent_and_sealed(self) -> Self:
        current_gameweek = self.current_execution.current_state.target_gameweek
        expected = (current_gameweek, current_gameweek + 1, current_gameweek + 2)
        if self.horizon_gameweeks != expected:
            raise ValueError("rolling horizon must contain exactly three consecutive Gameweeks")
        if tuple(item.gameweek for item in self.future_gameweeks) != expected[1:]:
            raise ValueError("future inputs must cover the next two consecutive Gameweeks")
        if (
            self.maximum_transfers_per_deadline
            != self.current_execution.candidate_action_policy.maximum_transfers
        ):
            raise ValueError(
                "rolling transfer-count scope must derive from the current governed candidate policy"
            )
        cutoff = self.current_execution.current_state.information_cutoff
        synthetic = self.current_execution.retention_class == "SYNTHETIC_REPLAY_ALLOWED"
        fpl_fixtures = {
            item.provider_fixture_id: item
            for item in self.current_execution.current_state.fpl_input.fixtures
        }
        for gameweek in self.future_gameweeks:
            assigned = {
                item.provider_fixture_id: item
                for item in fpl_fixtures.values()
                if item.event_identity is not None
                and item.event_identity.external_id_text == str(gameweek.gameweek)
            }
            if not assigned or any(item.kickoff_at is None for item in assigned.values()):
                raise ValueError("future official fixture set is absent or unscheduled")
            official = {fixture_id: item for fixture_id, item in assigned.items()}
            declared = {item.official_fpl_fixture_id: item for item in gameweek.fixtures}
            if set(declared) != set(official):
                raise ValueError("future input must cover every officially assigned fixture")
            for fixture_id, declared_fixture in declared.items():
                source = official[fixture_id]
                if (
                    source.identity.canonical_lookup_sha256
                    != declared_fixture.official_fpl_fixture_lookup_sha256
                    or source.kickoff_at != declared_fixture.kickoff_at
                    or int(source.home_team_identity.external_id_text)
                    != declared_fixture.home_official_fpl_team_id
                    or int(source.away_team_identity.external_id_text)
                    != declared_fixture.away_official_fpl_team_id
                    or declared_fixture.information_cutoff != cutoff
                    or source.started
                    or source.finished
                    or source.finished_provisional
                ):
                    raise ValueError("future fixture differs from the current official FPL view")
                if synthetic != (
                    declared_fixture.score_prior.source_class == "REPOSITORY_OWNED_SYNTHETIC"
                ):
                    raise ValueError("future fixture source class differs from current authority")
        if self.semantic_sha256 != _semantic_hash(self):
            raise ValueError("rolling execution input semantic hash does not match")
        return self


def seal_rolling_execution_input(
    value: PrivateV1RollingExecutionInput,
) -> PrivateV1RollingExecutionInput:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


class PrivateRollingFixtureCoverage(_RollingModel):
    fixtures_total: PositiveInt
    market_backed_fixtures: NonNegativeInt
    score_prior_only_fixtures: NonNegativeInt
    blocked_fixtures: NonNegativeInt

    @model_validator(mode="after")
    def counts_reconcile(self) -> Self:
        if (
            self.market_backed_fixtures + self.score_prior_only_fixtures + self.blocked_fixtures
            != self.fixtures_total
        ):
            raise ValueError("rolling fixture coverage counts do not reconcile")
        return self


class PrivateRollingGameweekDecision(_RollingModel):
    gameweek: PositiveInt
    actionability: Literal["DO_NOW", "PROVISIONAL_REOPTIMISE_AT_DEADLINE"]
    transfers: tuple[PrivateTransferMove, ...]
    transfer_count: NonNegativeInt
    hit_points: NonNegativeInt
    free_transfer_state: PrivateFreeTransferState
    bank_after_tenths: NonNegativeInt
    squad_after: tuple[StrictStr, ...]
    tactics: PrivateTacticalDecision
    expected_manager_points_before_hit: Decimal
    expected_manager_points_after_hit: Decimal
    fixture_coverage: PrivateRollingFixtureCoverage
    limitations: tuple[StrictStr, ...]
    tactical_plan_sha256: Sha256

    @model_validator(mode="after")
    def decision_reconciles(self) -> Self:
        if len(self.transfers) != self.transfer_count:
            raise ValueError("rolling transfer count differs from its moves")
        if self.free_transfer_state.transfer_count != self.transfer_count:
            raise ValueError("rolling transfer count differs from its FT transition")
        if self.free_transfer_state.hit_points != self.hit_points:
            raise ValueError("rolling hit differs from its FT transition")
        if self.expected_manager_points_before_hit - Decimal(self.hit_points) != (
            self.expected_manager_points_after_hit
        ):
            raise ValueError("rolling Gameweek points do not reconcile with hit")
        if self.squad_after != tuple(sorted(set(self.squad_after))):
            raise ValueError("rolling squad must be unique and sorted")
        if self.limitations != tuple(sorted(set(self.limitations))):
            raise ValueError("rolling Gameweek limitations must be unique and sorted")
        return self


class PrivateRollingHorizonComparison(_RollingModel):
    cross_gameweek_scenario_mode: Literal[
        "INDEPENDENT_GAMEWEEK_SCENARIO_PRODUCT_NO_INFORMATION_REVELATION_V1"
    ]
    joint_scenario_path_count: PositiveInt
    plan_expected_horizon_utility: Decimal
    baseline_expected_horizon_utility: Decimal
    expected_uplift: Decimal
    gain_p10: StrictInt
    gain_median: StrictInt
    gain_p90: StrictInt
    probability_plan_beats_baseline: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    probability_gain_at_least_four: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    probability_loss_at_least_four: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    gain_pmf: tuple[PrivateGainMass, ...]
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def comparison_reconciles(self) -> Self:
        if (
            self.plan_expected_horizon_utility - self.baseline_expected_horizon_utility
            != self.expected_uplift
            or not self.gain_p10 <= self.gain_median <= self.gain_p90
            or sum((item.probability for item in self.gain_pmf), Decimal(0)) != Decimal(1)
            or self.semantic_sha256 != _semantic_hash(self)
        ):
            raise ValueError("rolling horizon comparison does not reconcile")
        return self


def seal_rolling_horizon_comparison(
    value: PrivateRollingHorizonComparison,
) -> PrivateRollingHorizonComparison:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


class PrivateRollingFutureActionSummary(_RollingModel):
    gameweek: PositiveInt
    status: Literal["PROVISIONAL_REOPTIMISE_AT_DEADLINE"]
    transfers: tuple[PrivateTransferMove, ...]
    hit_points: NonNegativeInt
    free_transfers_entering: NonNegativeInt
    free_transfers_at_next_deadline: NonNegativeInt
    bank_after_tenths: NonNegativeInt


class PrivateRollingFrontierPoint(_RollingModel):
    transfer_count: NonNegativeInt
    action_signature: StrictStr
    transfers: tuple[PrivateTransferMove, ...]
    immediate_expected_points_after_hit: Decimal
    expected_horizon_utility: Decimal
    immediate_uplift_vs_hold: Decimal
    horizon_uplift_vs_hold: Decimal
    free_transfers_entering_next_gameweek: NonNegativeInt
    bank_after_tenths: NonNegativeInt
    paired_horizon_comparison: PrivateRollingHorizonComparison
    planned_future_policy: tuple[PrivateRollingFutureActionSummary, ...]
    stage11_plan_sha256: Sha256
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def point_reconciles(self) -> Self:
        if (
            len(self.transfers) != self.transfer_count
            or self.paired_horizon_comparison.plan_expected_horizon_utility
            != self.expected_horizon_utility
            or self.paired_horizon_comparison.expected_uplift != self.horizon_uplift_vs_hold
            or self.semantic_sha256 != _semantic_hash(self)
        ):
            raise ValueError("rolling frontier point does not reconcile")
        return self


def seal_rolling_frontier_point(
    value: PrivateRollingFrontierPoint,
) -> PrivateRollingFrontierPoint:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


class PrivateRollingFrontier(_RollingModel):
    schema_version: Literal["private-rolling-transfer-frontier-v1"] = (
        "private-rolling-transfer-frontier-v1"
    )
    objective: Literal["EXPECTED_THREE_GAMEWEEK_POINTS_WITH_LEGAL_RECOURSE"]
    points: tuple[PrivateRollingFrontierPoint, ...]
    action_space_disclosure: StrictStr
    optimiser_request_sha256: Sha256
    optimiser_result_sha256: Sha256
    candidate_action_policy_sha256: Sha256
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def frontier_is_canonical_and_sealed(self) -> Self:
        counts = tuple(item.transfer_count for item in self.points)
        if (
            not counts
            or counts[0] != 0
            or counts != tuple(sorted(set(counts)))
            or self.semantic_sha256 != _semantic_hash(self)
        ):
            raise ValueError("rolling transfer frontier is not canonical")
        return self


def seal_rolling_frontier(value: PrivateRollingFrontier) -> PrivateRollingFrontier:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


class PrivateOneGameweekVersusRollingComparison(_RollingModel):
    actions_differ: StrictBool
    one_gameweek_action_signature: StrictStr
    three_gameweek_action_signature: StrictStr
    one_gameweek_transfers: tuple[PrivateTransferMove, ...]
    three_gameweek_transfers: tuple[PrivateTransferMove, ...]
    counterfactual_basis: Literal["THREE_GAMEWEEK_FRONTIER_AT_ONE_GAMEWEEK_TRANSFER_COUNT"]
    counterfactual_action_matches_one_gameweek_action: StrictBool
    current_gameweek_points_difference: Decimal
    future_gameweek_points_difference: Decimal
    expected_hit_cost_difference: Decimal
    terminal_contribution_difference: Decimal
    total_horizon_utility_difference: Decimal
    free_transfers_entering_next_difference: StrictInt

    @model_validator(mode="after")
    def decomposition_reconciles(self) -> Self:
        expected = (
            self.current_gameweek_points_difference
            + self.future_gameweek_points_difference
            - self.expected_hit_cost_difference
            + self.terminal_contribution_difference
        )
        if expected != self.total_horizon_utility_difference:
            raise ValueError("one-GW versus rolling decomposition does not reconcile")
        if self.actions_differ != (
            self.one_gameweek_action_signature != self.three_gameweek_action_signature
        ):
            raise ValueError("one-GW versus rolling action comparison is inconsistent")
        return self


class PrivateRollingDecisionLineage(_RollingModel):
    rolling_execution_input_sha256: Sha256
    current_execution_input_sha256: Sha256
    current_manager_state_sha256: Sha256
    stage7_input_sha256_by_gameweek: dict[PositiveInt, dict[StrictStr, Sha256]]
    stage7_context_sha256_by_gameweek: dict[PositiveInt, dict[StrictStr, Sha256]]
    stage8_distribution_sha256_by_gameweek: dict[PositiveInt, dict[StrictStr, Sha256]]
    player_prior_binding_sha256_by_gameweek: dict[PositiveInt, dict[StrictStr, Sha256]]
    fixture_projection_sha256_by_gameweek: dict[PositiveInt, dict[StrictStr, Sha256]]
    player_prior_fallback_ids: tuple[StrictStr, ...]
    gameweek_projection_sha256_by_gameweek: dict[PositiveInt, Sha256]
    joint_matrix_sha256_by_gameweek: dict[PositiveInt, Sha256]
    future_gameweek_input_sha256_by_gameweek: dict[PositiveInt, Sha256]
    scenario_tree_sha256: Sha256
    optimiser_request_sha256: Sha256
    optimiser_result_sha256: Sha256
    one_gameweek_optimiser_result_sha256: Sha256
    terminal_policy_sha256: Sha256
    candidate_action_policy_sha256: Sha256
    ruleset_sha256: Sha256
    code_sha: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")


class PrivateV1RollingDecision(_RollingModel):
    schema_version: Literal["private-v1-rolling-decision-v1"] = "private-v1-rolling-decision-v1"
    status: Literal["SUCCESS"]
    activation_status: Literal["NOT_PRODUCTION_ACTIVE"]
    execution_status: Literal[
        "SYNTHETIC_REPLAYABLE_RECOMMENDATION", "REAL_PRIVATE_TRANSIENT_RECOMMENDATION"
    ]
    run_id: StrictStr
    season: Literal["2026/27"]
    projection_mode: ProjectionMode
    horizon_gameweeks: tuple[PositiveInt, PositiveInt, PositiveInt]
    information_cutoff: datetime
    horizon_objective: Literal["EXPECTED_THREE_GAMEWEEK_POINTS_WITH_LEGAL_RECOURSE"]
    terminal_value_mode: Literal["THREE_GAMEWEEK_ZERO_TERMINAL_VALUE_AFTER_HORIZON"]
    future_price_mode: Literal["FUTURE_PRICE_CHANGES_NOT_MODELLED_IN_PRIVATE_3GW_V1"]
    scenario_tree_mode: Literal["DETERMINISTIC_NO_NEW_INFORMATION_REVELATION_V1"]
    search_scope_mode: Literal["PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1"]
    transfer_count_scope_source: Literal[
        "CURRENT_FT_COMPILED_RULES_AND_TICKET_BOUNDED_SEARCH_POLICY"
    ]
    maximum_transfers_per_deadline: Annotated[StrictInt, Field(ge=0, le=2)]
    chip_mode: Literal["NO_CHIP_EXPLICIT"]
    do_now: PrivateRollingGameweekDecision
    by_gameweek: tuple[
        PrivateRollingGameweekDecision,
        PrivateRollingGameweekDecision,
        PrivateRollingGameweekDecision,
    ]
    future_plan: tuple[PrivateRollingGameweekDecision, PrivateRollingGameweekDecision]
    horizon_comparison: PrivateRollingHorizonComparison
    transfer_frontier: PrivateRollingFrontier
    one_gameweek_comparison: PrivateOneGameweekVersusRollingComparison
    solver_optimality: Literal["EXACT_DECLARED_TREE_AND_ACTION_SPACE"]
    action_space_disclosure: StrictStr
    warnings: tuple[StrictStr, ...]
    lineage: PrivateRollingDecisionLineage
    semantic_sha256: Sha256

    @field_validator("information_cutoff")
    @classmethod
    def cutoff_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="information_cutoff")

    @model_validator(mode="after")
    def decision_is_canonical_and_sealed(self) -> Self:
        if tuple(item.gameweek for item in self.by_gameweek) != self.horizon_gameweeks:
            raise ValueError("rolling by-Gameweek decisions differ from the horizon")
        if self.do_now != self.by_gameweek[0] or self.do_now.actionability != "DO_NOW":
            raise ValueError("rolling root action must be the only DO NOW decision")
        if self.future_plan != self.by_gameweek[1:] or any(
            item.actionability != "PROVISIONAL_REOPTIMISE_AT_DEADLINE" for item in self.future_plan
        ):
            raise ValueError("rolling future decisions must be provisional")
        if self.action_space_disclosure != self.transfer_frontier.action_space_disclosure:
            raise ValueError("rolling action-space disclosures differ")
        if any(
            item.transfer_count > self.maximum_transfers_per_deadline for item in self.by_gameweek
        ) or any(
            item.transfer_count > self.maximum_transfers_per_deadline
            for item in self.transfer_frontier.points
        ):
            raise ValueError("rolling transfer count exceeds its derived governed scope")
        if self.warnings != tuple(sorted(set(self.warnings))):
            raise ValueError("rolling warnings must be unique and sorted")
        if self.semantic_sha256 != _semantic_hash(self):
            raise ValueError("rolling decision semantic hash does not match")
        return self


def seal_rolling_decision(value: PrivateV1RollingDecision) -> PrivateV1RollingDecision:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


__all__ = [
    "PrivateOneGameweekVersusRollingComparison",
    "PrivateRollingDecisionLineage",
    "PrivateRollingFixtureCoverage",
    "PrivateRollingFixtureInput",
    "PrivateRollingFrontier",
    "PrivateRollingFrontierPoint",
    "PrivateRollingFutureActionSummary",
    "PrivateRollingGameweekDecision",
    "PrivateRollingGameweekInput",
    "PrivateRollingHorizonComparison",
    "PrivateV1RollingDecision",
    "PrivateV1RollingExecutionInput",
    "seal_rolling_decision",
    "seal_rolling_execution_input",
    "seal_rolling_fixture_input",
    "seal_rolling_frontier",
    "seal_rolling_frontier_point",
    "seal_rolling_gameweek_input",
    "seal_rolling_horizon_comparison",
]
