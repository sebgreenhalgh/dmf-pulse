"""Strict public contracts for OPT-010."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode

Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]


class OptimisationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


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
    club_id: StrictStr = Field(min_length=1, max_length=100)
    position: PlayerPosition
    initial_selection_cost_tenths: NonNegativeInt | None = None


class CandidatePoolSnapshot(OptimisationModel):
    schema_version: Literal["one-gameweek-candidate-pool-v1"] = "one-gameweek-candidate-pool-v1"
    information_cutoff_utc: StrictStr = Field(min_length=1)
    players: tuple[CandidatePlayer, ...] = Field(min_length=1)
    source_bundle_ids: tuple[StrictStr, ...] = ()
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def candidates_are_canonical(self) -> CandidatePoolSnapshot:
        ids = tuple(item.player_id for item in self.players)
        if len(ids) != len(set(ids)):
            raise ValueError("candidate player IDs must be unique")
        if tuple(sorted(ids)) != ids:
            raise ValueError("candidate players must be sorted by player ID")
        if tuple(sorted(self.source_bundle_ids)) != self.source_bundle_ids:
            raise ValueError("candidate source bundle IDs must be sorted")
        if len(self.source_bundle_ids) != len(set(self.source_bundle_ids)):
            raise ValueError("candidate source bundle IDs must be unique")
        return self

    @property
    def candidates(self) -> tuple[CandidatePlayer, ...]:
        """Compatibility accessor for internal enumeration code."""

        return self.players

    @property
    def candidate_snapshot_sha256(self) -> str:
        return self.snapshot_sha256


class CandidateSquad(OptimisationModel):
    player_ids: tuple[StrictStr, ...] = Field(min_length=1)

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
    projection_mode: ProjectionMode
    gameweek_id: StrictStr = Field(min_length=1, max_length=100)
    information_cutoff_utc: StrictStr = Field(min_length=1)
    search_scope: SearchScope
    candidate_pool: CandidatePoolSnapshot
    fixed_squad_ids: tuple[StrictStr, ...] | None = None
    provided_candidate_squads: tuple[CandidateSquad, ...] = ()
    required_player_ids: tuple[StrictStr, ...] = ()
    excluded_player_ids: tuple[StrictStr, ...] = ()
    request_sha256: Sha256

    @model_validator(mode="after")
    def scope_shape_is_valid(self) -> OneGameweekOptimisationRequest:
        if self.search_scope is SearchScope.FIXED_SQUAD and self.fixed_squad_ids is None:
            raise ValueError("FIXED_SQUAD requires fixed_squad_ids")
        if self.search_scope is not SearchScope.FIXED_SQUAD and self.fixed_squad_ids is not None:
            raise ValueError("fixed_squad_ids is only valid for FIXED_SQUAD")
        if self.search_scope is SearchScope.PROVIDED_SQUADS and not self.provided_candidate_squads:
            raise ValueError("PROVIDED_SQUADS requires provided_candidate_squads")
        if self.search_scope is not SearchScope.PROVIDED_SQUADS and self.provided_candidate_squads:
            raise ValueError("provided_candidate_squads is only valid for PROVIDED_SQUADS")
        provided_signatures = tuple(squad.player_ids for squad in self.provided_candidate_squads)
        if len(provided_signatures) != len(set(provided_signatures)):
            raise ValueError("provided squads must be unique")
        if self.fixed_squad_ids is not None:
            if len(self.fixed_squad_ids) != len(set(self.fixed_squad_ids)):
                raise ValueError("fixed squad player IDs must be unique")
            if tuple(sorted(self.fixed_squad_ids)) != self.fixed_squad_ids:
                raise ValueError("fixed squad player IDs must be sorted")
        for name, values in (
            ("required players", self.required_player_ids),
            ("excluded players", self.excluded_player_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
            if tuple(sorted(values)) != values:
                raise ValueError(f"{name} must be sorted")
        if set(self.required_player_ids) & set(self.excluded_player_ids):
            raise ValueError("required and excluded players cannot overlap")
        candidate_ids = {player.player_id for player in self.candidate_pool.players}
        declared_squad_ids = set(self.fixed_squad_ids or ()) | {
            player_id for squad in self.provided_candidate_squads for player_id in squad.player_ids
        }
        if not declared_squad_ids <= candidate_ids:
            raise ValueError("declared squad players must exist in the candidate snapshot")
        if not set(self.required_player_ids) <= candidate_ids:
            raise ValueError("required players must exist in the candidate snapshot")
        if not set(self.excluded_player_ids) <= candidate_ids:
            raise ValueError("excluded players must exist in the candidate snapshot")
        if self.search_scope is SearchScope.BOUNDED_PLAYER_POOL and any(
            player.initial_selection_cost_tenths is None for player in self.candidate_pool.players
        ):
            raise ValueError("BOUNDED_PLAYER_POOL requires every candidate cost")
        return self

    @property
    def fixed_squad(self) -> CandidateSquad | None:
        return CandidateSquad(player_ids=self.fixed_squad_ids) if self.fixed_squad_ids else None

    @property
    def provided_squads(self) -> tuple[CandidateSquad, ...]:
        return self.provided_candidate_squads


class OneGameweekOptimiserPolicy(OptimisationModel):
    schema_version: Literal["one-gameweek-optimiser-policy-v1"] = "one-gameweek-optimiser-policy-v1"
    max_squad_candidates: PositiveInt
    max_tactical_configurations: PositiveInt
    max_scenario_score_operations: PositiveInt
    max_returned_ties: PositiveInt
    objective_tolerance: None = None


class OneGameweekRulesView(OptimisationModel):
    ruleset_id: StrictStr
    ruleset_version: StrictStr
    ruleset_hash: Sha256
    projection_mode: ProjectionMode
    squad_size: PositiveInt
    position_squad_quota: dict[PlayerPosition, StrictInt]
    starting_size: PositiveInt
    bench_size: PositiveInt
    lineup_min: dict[PlayerPosition, StrictInt]
    lineup_max: dict[PlayerPosition, StrictInt]
    initial_budget_tenths: NonNegativeInt | None
    max_players_per_club: NonNegativeInt | None
    captain_multiplier: PositiveInt
    vice_captain_fallback: StrictBool
    auto_substitution_timing: StrictStr
    auto_substitution_zero_appearance_minutes: NonNegativeInt
    designated_bench_goalkeeper_if_appeared: StrictBool
    manager_bench_order: StrictBool
    maintain_legal_formation: StrictBool
    manager_capability: StrictStr | None
    manager_capability_hash: Sha256 | None

    @property
    def capability(self) -> str:
        return self.manager_capability or "REFERENCE_ONLY"


class TacticalConfiguration(OptimisationModel):
    starting_xi: tuple[StrictStr, ...] = Field(min_length=1)
    bench_goalkeeper: StrictStr
    bench_order: tuple[StrictStr, StrictStr, StrictStr]
    captain: StrictStr
    vice_captain: StrictStr

    @model_validator(mode="after")
    def all_designations_are_distinct(self) -> TacticalConfiguration:
        values = (*self.starting_xi, self.bench_goalkeeper, *self.bench_order)
        if len(values) != len(set(values)):
            raise ValueError("tactical player designations must be unique")
        if self.captain not in self.starting_xi or self.vice_captain not in self.starting_xi:
            raise ValueError("captain and vice-captain must start")
        if self.captain == self.vice_captain:
            raise ValueError("captain and vice-captain must differ")
        return self

    @property
    def outfield_bench_order(self) -> tuple[str, ...]:
        return self.bench_order


class AutosubEvent(OptimisationModel):
    player_out: StrictStr
    player_in: StrictStr
    bench_slot: PositiveInt
    reason_code: Literal["GOALKEEPER_REPLACEMENT", "OUTFIELD_BENCH_ORDER"]

    @property
    def slot(self) -> int:
        return self.bench_slot


class CaptainResolution(StrEnum):
    CAPTAIN = "CAPTAIN"
    VICE_CAPTAIN = "VICE_CAPTAIN"
    NEITHER = "NEITHER"


class ScenarioManagerScore(OptimisationModel):
    scenario_id: StrictStr
    outcome_draw_id: StrictStr
    counted_player_ids: tuple[StrictStr, ...]
    autosubs: tuple[AutosubEvent, ...]
    captain_resolution: CaptainResolution
    effective_captain_id: StrictStr | None
    base_points: StrictInt
    captain_bonus_points: StrictInt
    bench_contribution_points: StrictInt
    manager_points: StrictInt

    @property
    def autosub_events(self) -> tuple[AutosubEvent, ...]:
        return self.autosubs


class PointMass(OptimisationModel):
    points: StrictInt
    probability: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))


class PointDistributionSummary(OptimisationModel):
    pmf: tuple[PointMass, ...]
    expected_points: Decimal
    minimum: StrictInt
    p10: StrictInt
    median: StrictInt
    p90: StrictInt
    maximum: StrictInt
    probability_field_11: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    probability_field_10_or_fewer: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    captain_fallback_probability: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    captain_and_vice_failure_probability: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    expected_bench_contribution: Decimal
    component_means: dict[StrictStr, Decimal]
    component_covariance: dict[StrictStr, dict[StrictStr, Decimal]]

    @property
    def masses(self) -> tuple[PointMass, ...]:
        return self.pmf

    @property
    def minimum_points(self) -> int:
        return self.minimum

    @property
    def maximum_points(self) -> int:
        return self.maximum


class LegalityIssue(OptimisationModel):
    code: StrictStr
    message: StrictStr
    player_ids: tuple[StrictStr, ...] = ()
    rule_paths: tuple[StrictStr, ...] = ()


class LegalityReport(OptimisationModel):
    legal: StrictBool
    issues: tuple[LegalityIssue, ...] = ()


class SolverStatus(OptimisationModel):
    backend: Literal["DETERMINISTIC_EXHAUSTIVE_ENUMERATOR"] = "DETERMINISTIC_EXHAUSTIVE_ENUMERATOR"
    termination: Literal["OPTIMAL", "INFEASIBLE", "RESOURCE_LIMIT", "BLOCKED"] = "BLOCKED"
    search_scope: SearchScope
    guarantee: OptimalityGuarantee
    squad_upper_bound: NonNegativeInt = 0
    tactical_upper_bound: NonNegativeInt = 0
    scenario_operation_upper_bound: NonNegativeInt = 0
    squad_candidates_evaluated: NonNegativeInt = 0
    legal_squads_evaluated: NonNegativeInt = 0
    tactical_configurations_evaluated: NonNegativeInt = 0
    scenario_operations_evaluated: NonNegativeInt = 0
    objective_value: Decimal | None = None
    best_bound: Decimal | None = None
    absolute_gap: Decimal | None = None
    relative_gap: Decimal | None = None
    tied_optima_total: NonNegativeInt = 0
    returned_ties: NonNegativeInt = 0
    ties_truncated: StrictBool = False

    @property
    def conservative_squad_upper_bound(self) -> int:
        return self.squad_upper_bound

    @property
    def conservative_tactical_upper_bound(self) -> int:
        return self.tactical_upper_bound

    @property
    def conservative_operation_upper_bound(self) -> int:
        return self.scenario_operation_upper_bound

    @property
    def squads_examined(self) -> int:
        return self.squad_candidates_evaluated

    @property
    def tactical_configurations_examined(self) -> int:
        return self.tactical_configurations_evaluated

    @property
    def scenario_score_operations(self) -> int:
        return self.scenario_operations_evaluated

    @property
    def total_optimal_ties(self) -> int:
        return self.tied_optima_total


class OptimisationLineage(OptimisationModel):
    stage9_result_sha256: Sha256
    stage9_artifact_sha256: Sha256
    stage9_scenario_set_sha256: Sha256
    stage9_joint_matrix_sha256: Sha256
    candidate_pool_sha256: Sha256
    request_sha256: Sha256
    ruleset_hash: Sha256
    manager_capability: StrictStr | None
    manager_capability_hash: Sha256 | None
    policy_sha256: Sha256
    input_sha256: Sha256

    @property
    def candidate_snapshot_sha256(self) -> str:
        return self.candidate_pool_sha256

    @property
    def gameweek_artifact_sha256(self) -> str:
        return self.stage9_artifact_sha256

    @property
    def capability_hash(self) -> str | None:
        return self.manager_capability_hash


class ExplanationItem(OptimisationModel):
    code: StrictStr
    message: StrictStr
    player_ids: tuple[StrictStr, ...] = ()
    rule_paths: tuple[StrictStr, ...] = ()
    metrics: dict[StrictStr, Decimal | StrictInt | StrictStr] = Field(default_factory=dict)


class OneGameweekPlan(OptimisationModel):
    squad: tuple[StrictStr, ...]
    tactical_configuration: TacticalConfiguration
    total_cost_tenths: NonNegativeInt | None
    remaining_budget_tenths: NonNegativeInt | None
    expected_manager_points: Decimal
    point_distribution: PointDistributionSummary
    scenario_scores: tuple[ScenarioManagerScore, ...]
    legality: LegalityReport
    solver_status: SolverStatus
    explanations: tuple[ExplanationItem, ...]
    plan_sha256: Sha256

    @property
    def signature(self) -> str:
        tactic = self.tactical_configuration
        return "|".join(
            (
                ",".join(sorted(self.squad)),
                ",".join(sorted(tactic.starting_xi)),
                tactic.bench_goalkeeper,
                ",".join(tactic.bench_order),
                tactic.captain,
                tactic.vice_captain,
            )
        )

    @property
    def candidate_squad(self) -> CandidateSquad:
        return CandidateSquad(player_ids=self.squad)

    @property
    def distribution(self) -> PointDistributionSummary:
        return self.point_distribution

    @property
    def legality_report(self) -> LegalityReport:
        return self.legality

    @property
    def initial_selection_cost_tenths(self) -> int | None:
        return self.total_cost_tenths

    @property
    def budget_tenths(self) -> int | None:
        if self.total_cost_tenths is None or self.remaining_budget_tenths is None:
            return None
        return self.total_cost_tenths + self.remaining_budget_tenths


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
    recommended_plan: OneGameweekPlan | None = None
    tied_optimal_plans: tuple[OneGameweekPlan, ...] = ()
    solver_status: SolverStatus
    lineage: OptimisationLineage
    upstream_mc_status: Literal["PASS", "CONTINUE", "BLOCKED"]
    upstream_warnings: tuple[StrictStr, ...] = ()
    explanations: tuple[ExplanationItem, ...] = ()
    error_code: StrictStr | None = None
    error_message: StrictStr | None = None
    result_sha256: Sha256

    @model_validator(mode="after")
    def status_shape_is_valid(self) -> OneGameweekOptimisationResult:
        if self.status is OptimisationStatus.SUCCESS:
            if self.recommended_plan is None or not self.tied_optimal_plans:
                raise ValueError("successful result requires a recommended plan and ties")
            if self.error_code is not None:
                raise ValueError("successful result cannot carry an error")
            if (
                self.solver_status.termination != "OPTIMAL"
                or self.solver_status.guarantee is OptimalityGuarantee.NONE
                or self.solver_status.objective_value != self.solver_status.best_bound
                or self.solver_status.absolute_gap != 0
                or self.solver_status.relative_gap != 0
                or any(plan.solver_status != self.solver_status for plan in self.tied_optimal_plans)
            ):
                raise ValueError("successful result requires a complete exact solver proof")
            canonical = tuple(sorted(self.tied_optimal_plans, key=lambda plan: plan.signature))
            if self.tied_optimal_plans != canonical or self.recommended_plan != canonical[0]:
                raise ValueError("successful result ties and recommendation must be canonical")
        elif self.recommended_plan is not None or self.tied_optimal_plans:
            raise ValueError("non-success result cannot carry a plan")
        elif self.solver_status.guarantee is not OptimalityGuarantee.NONE:
            raise ValueError("non-success result cannot carry an optimality guarantee")
        return self

    @property
    def tied_plans(self) -> tuple[OneGameweekPlan, ...]:
        return self.tied_optimal_plans

    @property
    def search_scope(self) -> SearchScope:
        return self.solver_status.search_scope

    @property
    def optimality_guarantee(self) -> OptimalityGuarantee:
        return self.solver_status.guarantee
