"""Strict public contracts for OPT-010."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class OptimisationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OptimisationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"
    INFEASIBLE = "INFEASIBLE"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"


class SearchScope(StrEnum):
    FIXED_SQUAD = "FIXED_SQUAD"
    PROVIDED_SQUADS = "PROVIDED_SQUADS"
    BOUNDED_PLAYER_POOL = "BOUNDED_PLAYER_POOL"


class OptimalityGuarantee(StrEnum):
    EXACT_FIXED_SQUAD = "EXACT_FIXED_SQUAD"
    EXACT_PROVIDED_SET = "EXACT_PROVIDED_SET"
    EXACT_DECLARED_PLAYER_POOL = "EXACT_DECLARED_PLAYER_POOL"
    NONE = "NONE"


class CandidatePlayer(OptimisationModel):
    player_id: StrictStr = Field(min_length=1, max_length=100)
    position: PlayerPosition
    club_id: StrictStr = Field(min_length=1, max_length=100)
    initial_selection_cost_tenths: NonNegativeInt | None = None


class CandidatePoolSnapshot(OptimisationModel):
    schema_version: Literal["one-gameweek-candidate-pool-v1"] = "one-gameweek-candidate-pool-v1"
    information_cutoff_utc: StrictStr = Field(min_length=1)
    candidates: tuple[CandidatePlayer, ...] = Field(min_length=1)
    source_bundle_ids: tuple[StrictStr, ...] = ()
    candidate_snapshot_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def candidates_are_unique(self) -> CandidatePoolSnapshot:
        ids = tuple(item.player_id for item in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("candidate player IDs must be unique")
        if tuple(sorted(ids)) != ids:
            raise ValueError("candidate players must be sorted by player ID")
        return self


class CandidateSquad(OptimisationModel):
    player_ids: tuple[StrictStr, ...] = Field(min_length=1)
    initial_selection_cost_tenths: NonNegativeInt | None = None
    squad_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def squad_is_canonical(self) -> CandidateSquad:
        if len(self.player_ids) != len(set(self.player_ids)):
            raise ValueError("squad player IDs must be unique")
        if tuple(sorted(self.player_ids)) != self.player_ids:
            raise ValueError("squad player IDs must be sorted")
        return self


class OneGameweekOptimisationRequest(OptimisationModel):
    schema_version: Literal["one-gameweek-optimisation-request-v1"] = (
        "one-gameweek-optimisation-request-v1"
    )
    request_id: StrictStr = Field(min_length=1, max_length=100)
    gameweek_id: StrictStr = Field(min_length=1, max_length=100)
    projection_mode: ProjectionMode
    information_cutoff_utc: StrictStr = Field(min_length=1)
    search_scope: SearchScope
    candidate_pool: CandidatePoolSnapshot
    fixed_squad: CandidateSquad | None = None
    provided_squads: tuple[CandidateSquad, ...] = ()
    required_player_ids: tuple[StrictStr, ...] = ()
    excluded_player_ids: tuple[StrictStr, ...] = ()
    request_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def scope_shape_is_valid(self) -> OneGameweekOptimisationRequest:
        if self.search_scope is SearchScope.FIXED_SQUAD and self.fixed_squad is None:
            raise ValueError("FIXED_SQUAD requires fixed_squad")
        if self.search_scope is not SearchScope.FIXED_SQUAD and self.fixed_squad is not None:
            raise ValueError("fixed_squad is only valid for FIXED_SQUAD")
        if self.search_scope is SearchScope.PROVIDED_SQUADS and not self.provided_squads:
            raise ValueError("PROVIDED_SQUADS requires provided_squads")
        if self.search_scope is not SearchScope.PROVIDED_SQUADS and self.provided_squads:
            raise ValueError("provided_squads is only valid for PROVIDED_SQUADS")
        provided_signatures = tuple(squad.player_ids for squad in self.provided_squads)
        if len(provided_signatures) != len(set(provided_signatures)):
            raise ValueError("provided squads must be unique")
        if len(set(self.required_player_ids)) != len(self.required_player_ids):
            raise ValueError("required players must be unique")
        if len(set(self.excluded_player_ids)) != len(self.excluded_player_ids):
            raise ValueError("excluded players must be unique")
        if set(self.required_player_ids) & set(self.excluded_player_ids):
            raise ValueError("required and excluded players cannot overlap")
        return self


class OneGameweekOptimiserPolicy(OptimisationModel):
    schema_version: Literal["one-gameweek-optimiser-policy-v1"] = "one-gameweek-optimiser-policy-v1"
    max_squad_candidates: NonNegativeInt
    max_tactical_configurations: NonNegativeInt
    max_scenario_score_operations: NonNegativeInt
    max_returned_ties: NonNegativeInt
    objective_tolerance: None = None


class OneGameweekRulesView(OptimisationModel):
    ruleset_id: StrictStr
    ruleset_version: StrictStr
    ruleset_hash: Sha256
    projection_mode: ProjectionMode
    squad_size: StrictInt = Field(gt=0)
    position_squad_quota: dict[PlayerPosition, StrictInt]
    starting_size: StrictInt = Field(gt=0)
    bench_size: StrictInt = Field(gt=0)
    lineup_min: dict[PlayerPosition, StrictInt]
    lineup_max: dict[PlayerPosition, StrictInt]
    initial_budget_tenths: NonNegativeInt | None
    max_players_per_club: NonNegativeInt | None
    captain_multiplier: StrictInt = Field(gt=0)
    vice_captain_fallback: StrictBool
    auto_substitution_timing: StrictStr
    auto_substitution_zero_appearance_minutes: StrictInt = Field(ge=0)
    designated_bench_goalkeeper_if_appeared: StrictBool
    manager_bench_order: StrictBool
    maintain_legal_formation: StrictBool
    capability: StrictStr


class TacticalConfiguration(OptimisationModel):
    starting_xi: tuple[StrictStr, ...] = Field(min_length=1)
    bench_goalkeeper: StrictStr
    outfield_bench_order: tuple[StrictStr, ...]
    captain: StrictStr
    vice_captain: StrictStr

    @model_validator(mode="after")
    def all_designations_are_distinct(self) -> TacticalConfiguration:
        values = (*self.starting_xi, self.bench_goalkeeper, *self.outfield_bench_order)
        if len(values) != len(set(values)):
            raise ValueError("tactical player designations must be unique")
        if self.captain not in self.starting_xi or self.vice_captain not in self.starting_xi:
            raise ValueError("captain and vice-captain must start")
        if self.captain == self.vice_captain:
            raise ValueError("captain and vice-captain must differ")
        return self


class AutosubEvent(OptimisationModel):
    scenario_id: StrictStr
    player_out: StrictStr
    player_in: StrictStr
    slot: StrictInt = Field(ge=1)
    position: PlayerPosition


class CaptainResolution(OptimisationModel):
    captain: StrictStr
    vice_captain: StrictStr
    multiplier_player: StrictStr | None
    multiplier: StrictInt = Field(ge=1)


class ScenarioManagerScore(OptimisationModel):
    scenario_id: StrictStr
    weighted_numerator: StrictInt
    weight_token: StrictStr
    manager_points: StrictInt
    player_points: dict[StrictStr, StrictInt]
    autosub_events: tuple[AutosubEvent, ...]
    captain_resolution: CaptainResolution


class PointMass(OptimisationModel):
    points: StrictInt
    probability: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))


class PointDistributionSummary(OptimisationModel):
    expected_points: Decimal
    minimum_points: StrictInt
    maximum_points: StrictInt
    masses: tuple[PointMass, ...]
    p10: StrictInt
    median: StrictInt
    p90: StrictInt
    probability_field_11: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    probability_field_10_or_fewer: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    captain_fallback_probability: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    captain_and_vice_failure_probability: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    expected_bench_contribution: Decimal
    component_means: dict[StrictStr, Decimal]
    component_covariance: dict[StrictStr, dict[StrictStr, Decimal]]


class LegalityIssue(OptimisationModel):
    code: StrictStr
    message: StrictStr
    player_ids: tuple[StrictStr, ...] = ()


class LegalityReport(OptimisationModel):
    legal: StrictBool
    issues: tuple[LegalityIssue, ...] = ()


class SolverStatus(OptimisationModel):
    backend: Literal["DETERMINISTIC_EXHAUSTIVE_ENUMERATOR"] = "DETERMINISTIC_EXHAUSTIVE_ENUMERATOR"
    termination: Literal["OPTIMAL", "INFEASIBLE", "RESOURCE_LIMIT", "BLOCKED"] = "BLOCKED"
    squads_examined: NonNegativeInt = 0
    tactical_configurations_examined: NonNegativeInt = 0
    scenario_score_operations: NonNegativeInt = 0
    conservative_squad_upper_bound: NonNegativeInt = 0
    conservative_tactical_upper_bound: NonNegativeInt = 0
    conservative_operation_upper_bound: NonNegativeInt = 0
    total_optimal_ties: NonNegativeInt = 0
    returned_ties: NonNegativeInt = 0
    ties_truncated: StrictBool = False
    objective_value: Decimal | None = None
    best_bound: Decimal | None = None
    absolute_gap: Decimal | None = None
    relative_gap: Decimal | None = None


class OptimisationLineage(OptimisationModel):
    request_sha256: Sha256
    candidate_snapshot_sha256: Sha256
    gameweek_artifact_sha256: Sha256
    stage9_scenario_set_sha256: Sha256 | None = None
    stage9_joint_matrix_sha256: Sha256 | None = None
    ruleset_hash: Sha256
    capability_hash: Sha256 | None
    input_sha256: Sha256
    policy_sha256: Sha256 | None = None
    plan_sha256: Sha256 | None
    result_sha256: Sha256 | None


class ExplanationItem(OptimisationModel):
    code: StrictStr
    message: StrictStr
    details: dict[str, Any] = {}


class OneGameweekPlan(OptimisationModel):
    candidate_squad: CandidateSquad
    tactical_configuration: TacticalConfiguration
    scenario_scores: tuple[ScenarioManagerScore, ...]
    distribution: PointDistributionSummary
    expected_manager_points: Decimal
    initial_selection_cost_tenths: NonNegativeInt | None
    budget_tenths: NonNegativeInt | None
    signature: StrictStr
    legality_report: LegalityReport
    plan_sha256: Sha256 | None = None


class OneGameweekOptimisationResult(OptimisationModel):
    schema_version: Literal["one-gameweek-optimisation-result-v1"] = (
        "one-gameweek-optimisation-result-v1"
    )
    status: OptimisationStatus
    request_id: StrictStr
    gameweek_id: StrictStr
    objective: Literal["EXPECTED_CURRENT_GAMEWEEK_MANAGER_POINTS"] = (
        "EXPECTED_CURRENT_GAMEWEEK_MANAGER_POINTS"
    )
    search_scope: SearchScope
    optimality_guarantee: OptimalityGuarantee
    recommended_plan: OneGameweekPlan | None = None
    tied_plans: tuple[OneGameweekPlan, ...] = ()
    solver_status: SolverStatus
    lineage: OptimisationLineage
    upstream_mc_status: Literal["PASS", "CONTINUE", "BLOCKED"]
    upstream_warnings: tuple[StrictStr, ...] = ()
    explanations: tuple[ExplanationItem, ...] = ()
    error_code: StrictStr | None = None
    error_message: StrictStr | None = None
    result_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def status_shape_is_valid(self) -> OneGameweekOptimisationResult:
        if self.status is OptimisationStatus.SUCCESS:
            if self.recommended_plan is None or not self.tied_plans:
                raise ValueError("successful result requires a recommended plan and ties")
            if self.error_code is not None:
                raise ValueError("successful result cannot carry an error")
        elif self.recommended_plan is not None or self.tied_plans:
            raise ValueError("non-success result cannot carry a plan")
        return self
