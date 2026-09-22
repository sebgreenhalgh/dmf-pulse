"""Memory-only, authenticated 001P comparison records and fixed materiality rules."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FrozenEvidence,
    SealedEvidence,
    seal,
)
from dmf_pulse.private_v1.rolling_models import (
    PrivateRollingGameweekDecision,
    PrivateRollingHorizonComparison,
)

World = Literal["LEAGUE_BASELINE", "TEAM_STRENGTH_SHADOW"]
Classification = Literal[
    "EXACT_DECISION_ROBUST",
    "UTILITY_ONLY_MOVEMENT",
    "PLAYER_PROJECTION_MATERIAL_BUT_DECISION_ROBUST",
    "ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE",
    "ROOT_ACTION_ROBUST_TACTICS_SENSITIVE",
    "TEAM_STRENGTH_ROOT_ACTION_MATERIAL",
    "CANDIDATE_SCREEN_CONFOUNDED",
]
XP_THRESHOLD = Decimal("0.15")
UTILITY_THRESHOLD = Decimal("0.50")
CONTROL_NAMES = frozenset(
    {
        "algorithm_build",
        "candidate_policy",
        "chip_policy",
        "current_source",
        "draw_identity",
        "exact_acceleration",
        "fixture_order",
        "frozen_execution",
        "future_price_policy",
        "manager_state",
        "market_constraints",
        "ownership",
        "player_allocation",
        "player_allocation_fallbacks",
        "prices",
        "root_randomness",
        "rules",
        "scenario_identity",
        "scenario_policy",
        "scenario_tree_policy",
        "stage7_contexts",
        "stage7_inputs",
        "terminal_policy",
        "work_budget",
    }
)


def _classification(
    *,
    root: bool,
    continuation: bool,
    tactics: bool,
    player: bool,
    screen_equal: bool,
    utility_changed: bool,
) -> Classification:
    if root:
        return (
            "TEAM_STRENGTH_ROOT_ACTION_MATERIAL" if screen_equal else "CANDIDATE_SCREEN_CONFOUNDED"
        )
    if continuation:
        return "ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE"
    if tactics:
        return "ROOT_ACTION_ROBUST_TACTICS_SENSITIVE"
    if player:
        return "PLAYER_PROJECTION_MATERIAL_BUT_DECISION_ROBUST"
    return "UTILITY_ONLY_MOVEMENT" if utility_changed else "EXACT_DECISION_ROBUST"


class PlayerMovement(FrozenEvidence):
    gameweek: int = Field(gt=0)
    player_id: str
    team_id: str
    in_current_squad: bool
    baseline_xp: Decimal
    shadow_xp: Decimal
    delta: Decimal
    baseline_rank: int = Field(gt=0)
    shadow_rank: int = Field(gt=0)

    @model_validator(mode="after")
    def reconcile(self) -> Self:
        if any(not value.is_finite() for value in (self.baseline_xp, self.shadow_xp, self.delta)):
            raise ValueError("nonfinite projection movement")
        if self.shadow_xp - self.baseline_xp != self.delta:
            raise ValueError("projection delta differs")
        return self


class MovementSummary(FrozenEvidence):
    player_count: int = Field(gt=0)
    player_gameweek_count: int = Field(gt=0)
    median_absolute_xp: Decimal = Field(ge=0)
    p90_absolute_xp: Decimal = Field(ge=0)
    maximum_absolute_xp: Decimal = Field(ge=0)
    material_player_gameweek_count: int = Field(ge=0)
    materially_moved_player_count: int = Field(ge=0)
    material_rank_movement_count: int = Field(ge=0)
    current_squad_delta_by_gameweek: tuple[tuple[int, Decimal], ...]
    team_delta_by_gameweek: tuple[tuple[int, str, Decimal], ...]
    threshold: Decimal = Field(default=XP_THRESHOLD, ge=XP_THRESHOLD, le=XP_THRESHOLD)
    quantile_definition: Literal["LINEAR_INTERPOLATION_AT_P_TIMES_N_MINUS_ONE"] = (
        "LINEAR_INTERPOLATION_AT_P_TIMES_N_MINUS_ONE"
    )
    rank_definition: Literal[
        "DESCENDING_XP_THEN_CANONICAL_PLAYER_ID;MATERIAL_XP_AND_RANK_CHANGE"
    ] = "DESCENDING_XP_THEN_CANONICAL_PLAYER_ID;MATERIAL_XP_AND_RANK_CHANGE"


class DecisionSignature(SealedEvidence):
    by_gameweek: tuple[
        PrivateRollingGameweekDecision,
        PrivateRollingGameweekDecision,
        PrivateRollingGameweekDecision,
    ]
    action_sha256s: tuple[SHA, SHA, SHA]
    tactical_selection_sha256s: tuple[SHA, SHA, SHA]
    candidate_screen_sha256: SHA
    utility: PrivateRollingHorizonComparison

    @model_validator(mode="after")
    def signatures_reconcile(self) -> Self:
        if self.action_sha256s != tuple(action_hash(row) for row in self.by_gameweek) or (
            self.tactical_selection_sha256s != tuple(tactics_hash(row) for row in self.by_gameweek)
        ):
            raise ValueError("decision signature differs from decisions")
        return self


class PriorWorldResult(SealedEvidence):
    world: World
    signature: DecisionSignature
    rolling_decision_sha256: SHA
    controls: tuple[tuple[str, SHA], ...]
    stage8_sha256s: tuple[tuple[int, str, SHA], ...]
    optimiser_request_sha256: SHA
    optimiser_result_sha256: SHA
    stage11_work_sha256: SHA
    canonical_legal_actions: int = Field(gt=0)

    @model_validator(mode="after")
    def complete_controls(self) -> Self:
        if tuple(name for name, _digest in self.controls) != tuple(sorted(CONTROL_NAMES)):
            raise ValueError("prior-world hard control inventory is incomplete or unordered")
        return self


class FixturePriorComparison(FrozenEvidence):
    gameweek: int = Field(gt=0)
    fixture_id: str
    baseline_prior_sha256: SHA
    shadow_prior_sha256: SHA
    shadow_bundle_sha256: SHA
    market_constraints_sha256: SHA
    baseline_stage8_sha256: SHA
    shadow_stage8_sha256: SHA
    market_coverage: Literal["MARKET_BACKED", "PARTIAL_MARKET", "PRIOR_ONLY"]


class GameweekMarketCoverage(FrozenEvidence):
    gameweek: int = Field(gt=0)
    total: int = Field(gt=0)
    market_backed: int = Field(ge=0)
    partial_market: int = Field(ge=0)
    prior_only: int = Field(ge=0)

    @model_validator(mode="after")
    def reconcile(self) -> Self:
        if self.total != self.market_backed + self.partial_market + self.prior_only:
            raise ValueError("market coverage does not reconcile")
        return self


class MaterialityComparison(SealedEvidence):
    root_action_changed: bool
    continuation_changed: bool
    tactics_changed: bool
    starting_xi_changed: bool
    captain_changed: bool
    vice_captain_changed: bool
    candidate_screen_equal: bool
    utility_delta: Decimal
    hold_utility_delta: Decimal
    uplift_delta: Decimal
    utility_material: bool
    decision_material: bool
    player_projection_material: bool
    classification: Classification
    utility_threshold: Decimal = Field(
        default=UTILITY_THRESHOLD, ge=UTILITY_THRESHOLD, le=UTILITY_THRESHOLD
    )

    @model_validator(mode="after")
    def classification_is_fixed(self) -> Self:
        if any(
            not value.is_finite()
            for value in (self.utility_delta, self.hold_utility_delta, self.uplift_delta)
        ):
            raise ValueError("nonfinite utility movement")
        if self.utility_material != (abs(self.utility_delta) >= UTILITY_THRESHOLD) or (
            self.decision_material != (self.root_action_changed or self.utility_material)
        ):
            raise ValueError("materiality threshold differs")
        expected = _classification(
            root=self.root_action_changed,
            continuation=self.continuation_changed,
            tactics=self.tactics_changed,
            player=self.player_projection_material,
            screen_equal=self.candidate_screen_equal,
            utility_changed=any((self.utility_delta, self.hold_utility_delta, self.uplift_delta)),
        )
        if self.classification != expected:
            raise ValueError("comparison classification contradicts deterministic precedence")
        return self


class TeamStrengthDecisionComparison(SealedEvidence):
    schema_version: Literal["private-team-strength-decision-comparison-v1"] = (
        "private-team-strength-decision-comparison-v1"
    )
    status: Literal["SHADOW_NOT_MODEL_INPUT"] = "SHADOW_NOT_MODEL_INPUT"
    production_activation: Literal[False] = False
    persistence_performed: Literal[False] = False
    provider_requests_during_solves: Literal[0] = 0
    experiment_class: Literal["SYNTHETIC_OFFLINE", "PRIVATE_TRANSIENT"]
    information_cutoff: datetime
    horizon: tuple[int, int, int]
    fpl_request_count: int = Field(ge=0)
    odds_request_count: int = Field(ge=0)
    baseline_execution_sha256: SHA
    shadow_input_sha256: SHA
    model_sha256: SHA
    dataset_mode: Literal["RECONSTRUCTED", "LIVE_OBSERVED"]
    freshness: Literal["FRESH", "DEGRADED"]
    worlds: tuple[PriorWorldResult, PriorWorldResult]
    fixtures: tuple[FixturePriorComparison, ...] = Field(min_length=1)
    market_coverage: tuple[GameweekMarketCoverage, ...]
    player_movements: tuple[PlayerMovement, ...] = Field(min_length=1)
    movement: MovementSummary
    comparison: MaterialityComparison
    common_random_numbers: Literal[True] = True
    random_draw_disclosure: Literal[
        "SAME_SEEDS_NAMESPACES_AND_DRAW_INDICES;OUTCOMES_AND_BRANCH_DEPENDENT_DRAW_CONSUMPTION_MAY_DIFFER"
    ] = "SAME_SEEDS_NAMESPACES_AND_DRAW_INDICES;OUTCOMES_AND_BRANCH_DEPENDENT_DRAW_CONSUMPTION_MAY_DIFFER"

    @model_validator(mode="after")
    def controls_and_coverage(self) -> Self:
        left, right = self.worlds
        if (left.world, right.world) != ("LEAGUE_BASELINE", "TEAM_STRENGTH_SHADOW"):
            raise ValueError("two prior worlds are incomplete or unordered")
        if left.controls != right.controls:
            raise ValueError("comparison hard controls differ")
        if dict(left.controls)["frozen_execution"] != self.baseline_execution_sha256:
            raise ValueError("comparison frozen execution identity differs from worlds")
        keys = tuple((row.gameweek, row.fixture_id) for row in self.fixtures)
        if keys != tuple(sorted(set(keys))) or set(row.gameweek for row in self.fixtures) != set(
            self.horizon
        ):
            raise ValueError("comparison fixture coverage differs")
        if tuple(
            (row.gameweek, row.fixture_id, row.baseline_stage8_sha256) for row in self.fixtures
        ) != left.stage8_sha256s or (
            tuple((row.gameweek, row.fixture_id, row.shadow_stage8_sha256) for row in self.fixtures)
            != right.stage8_sha256s
        ):
            raise ValueError("fixture Stage-8 evidence differs from worlds")
        player_keys = tuple((row.gameweek, row.player_id) for row in self.player_movements)
        if player_keys != tuple(sorted(set(player_keys))) or set(
            row.gameweek for row in self.player_movements
        ) != set(self.horizon):
            raise ValueError("player movement coverage differs")
        if self.movement != summarise_movements(
            self.player_movements
        ) or self.comparison != compare_signatures(left.signature, right.signature, self.movement):
            raise ValueError("comparison aggregates or classification differ from evidence")
        if self.market_coverage != summarise_coverage(self.fixtures):
            raise ValueError("market coverage differs from fixture evidence")
        return self


class ComparisonTimings(FrozenEvidence):
    """Execution envelope: timings never contribute to semantic comparison identity."""

    preparation_ms: Decimal | None = Field(default=None, ge=0)
    baseline_projection_ms: Decimal = Field(ge=0)
    baseline_solve_ms: Decimal = Field(ge=0)
    shadow_projection_ms: Decimal = Field(ge=0)
    shadow_solve_ms: Decimal = Field(ge=0)
    comparison_overhead_ms: Decimal = Field(ge=0)


def action_hash(row: PrivateRollingGameweekDecision) -> str:
    return canonical_sha256(
        {
            "gameweek": row.gameweek,
            "transfers": tuple(move.model_dump(mode="json") for move in row.transfers),
            "count": row.transfer_count,
            "hit": row.hit_points,
            "free_transfers": row.free_transfer_state.model_dump(mode="json"),
            "bank_after": row.bank_after_tenths,
        }
    )


def tactics_hash(row: PrivateRollingGameweekDecision) -> str:
    return canonical_sha256(
        row.tactics.model_dump(mode="json", exclude={"captain_decision_sha256"})
    )


def summarise_movements(rows: tuple[PlayerMovement, ...]) -> MovementSummary:
    if not rows:
        raise ValueError("player movement is empty")
    absolute = sorted(abs(row.delta) for row in rows)

    def quantile(p: Decimal) -> Decimal:
        position = p * (len(absolute) - 1)
        lower = int(position)
        upper = min(lower + 1, len(absolute) - 1)
        return absolute[lower] + (position - lower) * (absolute[upper] - absolute[lower])

    material = tuple(row for row in rows if abs(row.delta) >= XP_THRESHOLD)
    return MovementSummary(
        player_count=len({row.player_id for row in rows}),
        player_gameweek_count=len(rows),
        median_absolute_xp=quantile(Decimal("0.5")),
        p90_absolute_xp=quantile(Decimal("0.9")),
        maximum_absolute_xp=absolute[-1],
        material_player_gameweek_count=len(material),
        materially_moved_player_count=len({row.player_id for row in material}),
        material_rank_movement_count=sum(row.baseline_rank != row.shadow_rank for row in material),
        current_squad_delta_by_gameweek=tuple(
            (
                gw,
                sum(
                    (row.delta for row in rows if row.gameweek == gw and row.in_current_squad),
                    Decimal(0),
                ),
            )
            for gw in sorted({row.gameweek for row in rows})
        ),
        team_delta_by_gameweek=tuple(
            (
                gw,
                team,
                sum(
                    (row.delta for row in rows if (row.gameweek, row.team_id) == (gw, team)),
                    Decimal(0),
                ),
            )
            for gw, team in sorted({(row.gameweek, row.team_id) for row in rows})
        ),
    )


def compare_signatures(
    left: DecisionSignature, right: DecisionSignature, movement: MovementSummary
) -> MaterialityComparison:
    root = left.action_sha256s[0] != right.action_sha256s[0]
    continuation = left.action_sha256s[1:] != right.action_sha256s[1:]
    tactics = left.tactical_selection_sha256s != right.tactical_selection_sha256s
    screen_equal = left.candidate_screen_sha256 == right.candidate_screen_sha256
    delta = right.utility.plan_expected_horizon_utility - left.utility.plan_expected_horizon_utility
    hold_delta = (
        right.utility.baseline_expected_horizon_utility
        - left.utility.baseline_expected_horizon_utility
    )
    uplift_delta = right.utility.expected_uplift - left.utility.expected_uplift
    player_material = movement.material_player_gameweek_count > 0
    classification = _classification(
        root=root,
        continuation=continuation,
        tactics=tactics,
        player=player_material,
        screen_equal=screen_equal,
        utility_changed=any((delta, hold_delta, uplift_delta)),
    )
    return seal(
        MaterialityComparison,
        root_action_changed=root,
        continuation_changed=continuation,
        tactics_changed=tactics,
        starting_xi_changed=left.by_gameweek[0].tactics.starting_xi
        != right.by_gameweek[0].tactics.starting_xi,
        captain_changed=left.by_gameweek[0].tactics.captain != right.by_gameweek[0].tactics.captain,
        vice_captain_changed=left.by_gameweek[0].tactics.vice_captain
        != right.by_gameweek[0].tactics.vice_captain,
        candidate_screen_equal=screen_equal,
        utility_delta=delta,
        hold_utility_delta=hold_delta,
        uplift_delta=uplift_delta,
        utility_material=abs(delta) >= UTILITY_THRESHOLD,
        decision_material=root or abs(delta) >= UTILITY_THRESHOLD,
        player_projection_material=player_material,
        classification=classification,
    )


def summarise_coverage(
    fixtures: tuple[FixturePriorComparison, ...],
) -> tuple[GameweekMarketCoverage, ...]:
    return tuple(
        GameweekMarketCoverage(
            gameweek=gw,
            total=sum(row.gameweek == gw for row in fixtures),
            market_backed=sum(
                row.gameweek == gw and row.market_coverage == "MARKET_BACKED" for row in fixtures
            ),
            partial_market=sum(
                row.gameweek == gw and row.market_coverage == "PARTIAL_MARKET" for row in fixtures
            ),
            prior_only=sum(
                row.gameweek == gw and row.market_coverage == "PRIOR_ONLY" for row in fixtures
            ),
        )
        for gw in sorted({row.gameweek for row in fixtures})
    )
