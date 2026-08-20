"""Transient GW1 initial-squad bridge into the accepted exact Stage-10 service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.current import CurrentFootballEventBundle
from dmf_pulse.fpl_points.current_acceptance import (
    CurrentProjectionAcceptanceReport,
    assess_current_projection,
)
from dmf_pulse.fpl_points.current_points import (
    TARGET_RULESET_HASH,
    CurrentFplPointsBundle,
    CurrentPlayerPointsProjection,
)
from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.optimisation.candidate_pool import snapshot_hash
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidatePoolSnapshot,
    OneGameweekOptimisationRequest,
    OneGameweekOptimisationResult,
    OptimisationStatus,
    SearchScope,
)
from dmf_pulse.optimisation.service import optimise_one_gameweek
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset, RuleCapability

PortfolioKind = Literal["EXPECTED_POINTS", "CONSERVATIVE", "HIGHER_UPSIDE"]
SelectionRole = Literal["STARTING_XI", "BENCH_GOALKEEPER", "BENCH_1", "BENCH_2", "BENCH_3"]
CURRENT_INITIAL_SQUAD_ADAPTER_VERSION: Literal["gw1-current-initial-squad-stage10-v1"] = (
    "gw1-current-initial-squad-stage10-v1"
)
TARGET_GW1_INITIAL_SQUAD_CAPABILITY_HASH = (
    "b2e1268800d793c48a92299b49a60b69aab6ebbfb330708658d3386ea623549a"
)
_PORTFOLIO_KINDS: tuple[PortfolioKind, ...] = (
    "EXPECTED_POINTS",
    "CONSERVATIVE",
    "HIGHER_UPSIDE",
)
_BEAM_WIDTH = 512


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


class CurrentInitialSquadPlayer(_FrozenModel):
    official_fpl_player_id: int = Field(gt=0)
    transient_player_id: str = Field(min_length=1, max_length=100)
    player_name: str = Field(min_length=1, max_length=200)
    official_fpl_team_id: int = Field(gt=0)
    team_name: str = Field(min_length=1, max_length=200)
    position: PlayerPosition
    current_price_tenths: int = Field(gt=0)
    selection_role: SelectionRole
    captain: StrictBool
    vice_captain: StrictBool
    probability_appearance: str
    probability_start: str
    expected_minutes: str
    mean_expected_fpl_points: Decimal
    p10_fpl_points: int
    median_fpl_points: int
    p90_fpl_points: int
    points_standard_deviation: Decimal = Field(ge=0)
    limitations: tuple[str, ...] = Field(min_length=1)
    source_row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CurrentInitialSquadPortfolio(_FrozenModel):
    portfolio_kind: PortfolioKind
    search_classification: Literal["HEURISTIC_PORTFOLIO_EXACT_STAGE10_TACTICS"] = (
        "HEURISTIC_PORTFOLIO_EXACT_STAGE10_TACTICS"
    )
    players: tuple[CurrentInitialSquadPlayer, ...] = Field(min_length=15, max_length=15)
    total_spend_tenths: int = Field(ge=0)
    bank_tenths: int = Field(ge=0)
    starting_xi: tuple[str, ...] = Field(min_length=11, max_length=11)
    bench_goalkeeper: str
    bench_order: tuple[str, str, str]
    captain: str
    vice_captain: str
    squad_expected_fpl_points: Decimal
    xi_expected_fpl_points: Decimal
    expected_manager_points: Decimal
    p10_manager_points: int
    median_manager_points: int
    p90_manager_points: int
    solver_guarantee: Literal["EXACT_DECLARED_PLAYER_POOL"] = "EXACT_DECLARED_PLAYER_POOL"
    optimiser_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reasons: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_portfolio(self) -> CurrentInitialSquadPortfolio:
        player_ids = tuple(row.transient_player_id for row in self.players)
        roles = {row.transient_player_id: row.selection_role for row in self.players}
        if (
            len(player_ids) != len(set(player_ids))
            or set(self.starting_xi) | {self.bench_goalkeeper, *self.bench_order} != set(player_ids)
            or self.captain not in self.starting_xi
            or self.vice_captain not in self.starting_xi
            or self.captain == self.vice_captain
            or roles[self.bench_goalkeeper] != "BENCH_GOALKEEPER"
            or tuple(roles[player] for player in self.bench_order)
            != ("BENCH_1", "BENCH_2", "BENCH_3")
            or any(roles[player] != "STARTING_XI" for player in self.starting_xi)
            or sum(row.current_price_tenths for row in self.players) != self.total_spend_tenths
        ):
            raise ValueError("current initial-squad portfolio is inconsistent")
        return self


class CurrentInitialSquadDecision(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_INITIAL_SQUAD_DECISION"] = "GW1_CURRENT_INITIAL_SQUAD_DECISION"
    status: Literal["SUCCESS", "BLOCKED"]
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    adapter_version: Literal["gw1-current-initial-squad-stage10-v1"] = (
        CURRENT_INITIAL_SQUAD_ADAPTER_VERSION
    )
    projection_acceptance: CurrentProjectionAcceptanceReport
    blocker_codes: tuple[str, ...]
    portfolios: tuple[CurrentInitialSquadPortfolio, ...]
    recommended_portfolio_kind: PortfolioKind | None
    information_cutoff: datetime
    ruleset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    gw1_initial_squad_capability_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    limitations: tuple[str, ...] = Field(min_length=1)
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    automated_fpl_account_action: Literal[False] = False
    chip_used: Literal[False] = False
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_decision(self) -> CurrentInitialSquadDecision:
        kinds = tuple(row.portfolio_kind for row in self.portfolios)
        success = self.status == "SUCCESS"
        if (
            success != (not self.blocker_codes)
            or success != (self.recommended_portfolio_kind is not None)
            or success != bool(self.portfolios)
            or (success and set(kinds) != set(_PORTFOLIO_KINDS))
            or len(kinds) != len(set(kinds))
            or (
                self.recommended_portfolio_kind is not None
                and self.recommended_portfolio_kind not in kinds
            )
            or self.blocker_codes != tuple(sorted(set(self.blocker_codes)))
            or self.semantic_sha256 != _decision_sha256(self)
        ):
            raise ValueError("current initial-squad decision is inconsistent")
        return self


@dataclass(frozen=True)
class _BeamState:
    selected: tuple[str, ...]
    cost: int
    clubs: tuple[tuple[str, int], ...]
    score: tuple[Decimal, Decimal, Decimal]


def _decision_sha256(value: CurrentInitialSquadDecision) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


def _metric(
    row: CurrentPlayerPointsProjection, kind: PortfolioKind
) -> tuple[Decimal, Decimal, Decimal]:
    mean = Decimal(str(row.mean_expected_fpl_points))
    if kind == "CONSERVATIVE":
        return (
            Decimal(row.selected_percentiles["p10"]),
            Decimal(row.probability_appearance),
            -Decimal(str(row.uncertainty.points_standard_deviation)),
        )
    if kind == "HIGHER_UPSIDE":
        return (
            Decimal(row.selected_percentiles["p90"]),
            Decimal(str(row.probability_10_plus)),
            mean,
        )
    return (mean, Decimal(row.probability_start), Decimal(row.probability_appearance))


def _sum_metric(
    left: tuple[Decimal, Decimal, Decimal], right: tuple[Decimal, Decimal, Decimal]
) -> tuple[Decimal, Decimal, Decimal]:
    return tuple(a + b for a, b in zip(left, right, strict=True))  # type: ignore[return-value]


def _trim(states: list[tuple[_BeamState, int]]) -> list[tuple[_BeamState, int]]:
    unique = {state.selected: (state, last) for state, last in states}
    values = list(unique.values())
    by_score = sorted(
        values,
        key=lambda item: (item[0].score, -item[0].cost, item[0].selected),
        reverse=True,
    )[: _BEAM_WIDTH // 2]
    by_cost = sorted(
        values,
        key=lambda item: (item[0].cost, tuple(-value for value in item[0].score), item[0].selected),
    )[: _BEAM_WIDTH // 2]
    return list({item[0].selected: item for item in (*by_score, *by_cost)}.values())


def _portfolio_states(
    rows: tuple[CurrentPlayerPointsProjection, ...],
    rules: Any,
    kind: PortfolioKind,
) -> tuple[_BeamState, ...]:
    by_position = {
        position: tuple(
            sorted(
                (row for row in rows if row.position is position),
                key=lambda row: str(row.transient_player_id),
            )
        )
        for position in PlayerPosition
    }
    states = [
        _BeamState(
            selected=(),
            cost=0,
            clubs=(),
            score=(Decimal(0), Decimal(0), Decimal(0)),
        )
    ]
    for position in PlayerPosition:
        partial: list[tuple[_BeamState, int]] = [(state, -1) for state in states]
        for _ in range(rules.position_squad_quota[position]):
            expanded: list[tuple[_BeamState, int]] = []
            for state, last_index in partial:
                clubs = dict(state.clubs)
                for index in range(last_index + 1, len(by_position[position])):
                    row = by_position[position][index]
                    player_id = str(row.transient_player_id)
                    club_id = str(row.transient_team_id)
                    if (
                        state.cost + row.current_price_tenths > rules.initial_budget_tenths
                        or clubs.get(club_id, 0) >= rules.max_players_per_club
                    ):
                        continue
                    updated_clubs = dict(clubs)
                    updated_clubs[club_id] = updated_clubs.get(club_id, 0) + 1
                    expanded.append(
                        (
                            _BeamState(
                                selected=(*state.selected, player_id),
                                cost=state.cost + row.current_price_tenths,
                                clubs=tuple(sorted(updated_clubs.items())),
                                score=_sum_metric(state.score, _metric(row, kind)),
                            ),
                            index,
                        )
                    )
            partial = _trim(expanded)
            if not partial:
                return ()
        states = [state for state, _ in partial]
    return tuple(
        sorted(
            states,
            key=lambda state: (state.score, -state.cost, state.selected),
            reverse=True,
        )
    )


def _select_portfolios(
    rows: tuple[CurrentPlayerPointsProjection, ...], rules: Any
) -> dict[PortfolioKind, tuple[str, ...]]:
    selected: dict[PortfolioKind, tuple[str, ...]] = {}
    used: set[tuple[str, ...]] = set()
    for kind in _PORTFOLIO_KINDS:
        states = _portfolio_states(rows, rules, kind)
        choice = next(
            (
                tuple(sorted(state.selected))
                for state in states
                if tuple(sorted(state.selected)) not in used
            ),
            None,
        )
        if choice is None:
            raise IngestionError(
                "INITIAL_SQUAD_BLOCKED",
                f"a distinct legal {kind} portfolio is unavailable within the bounded beam",
            )
        selected[kind] = choice
        used.add(choice)
    return selected


def _seal_request(value: OneGameweekOptimisationRequest) -> OneGameweekOptimisationRequest:
    payload = value.model_dump(mode="json")
    payload["request_sha256"] = None
    return value.model_copy(update={"request_sha256": canonical_sha256(payload)})


def _run_portfolio(
    kind: PortfolioKind,
    player_ids: tuple[str, ...],
    projection: CurrentFplPointsBundle,
    compiled: CompiledRuleset,
    capability: CapabilityArtifact,
) -> OneGameweekOptimisationResult:
    rows = {str(row.transient_player_id): row for row in projection.player_table}
    candidates = tuple(
        sorted(
            (
                CandidatePlayer(
                    player_id=player_id,
                    club_id=str(rows[player_id].transient_team_id),
                    position=rows[player_id].position,
                    initial_selection_cost_tenths=rows[player_id].current_price_tenths,
                )
                for player_id in player_ids
            ),
            key=lambda row: row.player_id,
        )
    )
    cutoff = projection.run_config.information_cutoff.isoformat().replace("+00:00", "Z")
    pool = CandidatePoolSnapshot(
        information_cutoff_utc=cutoff,
        players=candidates,
        source_bundle_ids=(projection.semantic_sha256,),
        snapshot_sha256="0" * 64,
    )
    pool = pool.model_copy(update={"snapshot_sha256": snapshot_hash(pool)})
    request = _seal_request(
        OneGameweekOptimisationRequest(
            request_id=f"gw1-{kind.lower().replace('_', '-')}-{projection.semantic_sha256[:16]}",
            projection_mode=ProjectionMode.PRESEASON_DECISION_SUPPORT,
            gameweek_id=projection.gameweek_projection.scenario_set.gameweek_id,
            information_cutoff_utc=cutoff,
            search_scope=SearchScope.BOUNDED_PLAYER_POOL,
            candidate_pool=pool,
            request_sha256="0" * 64,
        )
    )
    return optimise_one_gameweek(
        request,
        projection.gameweek_projection,
        compiled,
        capability=capability,
    )


def _portfolio_view(
    kind: PortfolioKind,
    result: OneGameweekOptimisationResult,
    rows: dict[str, CurrentPlayerPointsProjection],
) -> CurrentInitialSquadPortfolio:
    if result.status is not OptimisationStatus.SUCCESS or result.recommended_plan is None:
        raise IngestionError(
            "INITIAL_SQUAD_BLOCKED",
            f"accepted Stage-10 service returned {result.error_code or result.status.value}",
        )
    plan = result.recommended_plan
    tactic = plan.tactical_configuration
    roles: dict[str, SelectionRole] = {player: "STARTING_XI" for player in tactic.starting_xi}
    roles[tactic.bench_goalkeeper] = "BENCH_GOALKEEPER"
    for index, player in enumerate(tactic.bench_order, start=1):
        roles[player] = ("BENCH_1", "BENCH_2", "BENCH_3")[index - 1]
    assert plan.total_cost_tenths is not None
    assert plan.remaining_budget_tenths is not None
    players = tuple(
        CurrentInitialSquadPlayer(
            official_fpl_player_id=row.official_fpl_player_id,
            transient_player_id=player_id,
            player_name=row.player_name,
            official_fpl_team_id=row.official_fpl_team_id,
            team_name=row.team_name,
            position=row.position,
            current_price_tenths=row.current_price_tenths,
            selection_role=roles[player_id],
            captain=player_id == tactic.captain,
            vice_captain=player_id == tactic.vice_captain,
            probability_appearance=row.probability_appearance,
            probability_start=row.probability_start,
            expected_minutes=row.expected_minutes,
            mean_expected_fpl_points=Decimal(str(row.mean_expected_fpl_points)),
            p10_fpl_points=row.selected_percentiles["p10"],
            median_fpl_points=row.median_fpl_points,
            p90_fpl_points=row.selected_percentiles["p90"],
            points_standard_deviation=Decimal(str(row.uncertainty.points_standard_deviation)),
            limitations=row.uncertainty.limitations,
            source_row_sha256=row.row_sha256,
        )
        for player_id in sorted(plan.squad)
        for row in (rows[player_id],)
    )
    return CurrentInitialSquadPortfolio(
        portfolio_kind=kind,
        players=players,
        total_spend_tenths=plan.total_cost_tenths,
        bank_tenths=plan.remaining_budget_tenths,
        starting_xi=tactic.starting_xi,
        bench_goalkeeper=tactic.bench_goalkeeper,
        bench_order=tactic.bench_order,
        captain=tactic.captain,
        vice_captain=tactic.vice_captain,
        squad_expected_fpl_points=sum(
            (row.mean_expected_fpl_points for row in players), Decimal(0)
        ),
        xi_expected_fpl_points=sum(
            (Decimal(str(rows[player].mean_expected_fpl_points)) for player in tactic.starting_xi),
            Decimal(0),
        ),
        expected_manager_points=plan.expected_manager_points,
        p10_manager_points=plan.point_distribution.p10,
        median_manager_points=plan.point_distribution.median,
        p90_manager_points=plan.point_distribution.p90,
        optimiser_result_sha256=result.result_sha256,
        plan_sha256=plan.plan_sha256,
        reasons=(
            f"{kind}_PORTFOLIO_FROM_ACCEPTED_STAGE9_DISTRIBUTIONS",
            "EXACT_STAGE10_TACTICS_WITHIN_DECLARED_15_PLAYER_PORTFOLIO",
        ),
    )


def _decision(
    *,
    status: Literal["SUCCESS", "BLOCKED"],
    acceptance: CurrentProjectionAcceptanceReport,
    blockers: tuple[str, ...],
    portfolios: tuple[CurrentInitialSquadPortfolio, ...],
    recommended: str | None,
    projection: CurrentFplPointsBundle,
    compiled: CompiledRuleset,
    capability: CapabilityArtifact,
) -> CurrentInitialSquadDecision:
    values: dict[str, Any] = {
        "status": status,
        "projection_acceptance": acceptance,
        "blocker_codes": tuple(sorted(set(blockers))),
        "portfolios": portfolios,
        "recommended_portfolio_kind": recommended,
        "information_cutoff": projection.run_config.information_cutoff,
        "ruleset_hash": compiled.ruleset_hash,
        "gw1_initial_squad_capability_hash": capability.capability_hash,
        "projection_semantic_sha256": projection.semantic_sha256,
        "limitations": tuple(
            sorted(
                {
                    "CURRENT_FPL_DERIVED_OUTPUT_TRANSIENT_ONLY",
                    "NO_GLOBAL_OPTIMUM_CLAIM_OUTSIDE_THREE_BOUNDED_PORTFOLIOS",
                    "PRESEASON_NON_PRODUCTION_DECISION_SUPPORT",
                    *acceptance.warnings,
                }
            )
        ),
    }
    provisional = CurrentInitialSquadDecision.model_construct(**values, semantic_sha256="0" * 64)
    return CurrentInitialSquadDecision(**values, semantic_sha256=_decision_sha256(provisional))


def optimise_current_initial_squad(
    source: CurrentFootballEventBundle,
    projection: CurrentFplPointsBundle,
    compiled: CompiledRuleset,
    capability: CapabilityArtifact,
) -> CurrentInitialSquadDecision:
    """Produce three transient initial-squad portfolios or an explicit blocker."""

    expected_capability = compile_capability_artifact(compiled, RuleCapability.GW1_INITIAL_SQUAD)
    if (
        compiled.ruleset_hash != TARGET_RULESET_HASH
        or capability.model_dump(mode="json") != expected_capability.model_dump(mode="json")
        or capability.capability_hash != TARGET_GW1_INITIAL_SQUAD_CAPABILITY_HASH
        or not capability.source_backed
        or not capability.production_eligible
        or capability.blockers
    ):
        raise IngestionError(
            "INITIAL_SQUAD_BLOCKED",
            "target GW1_INITIAL_SQUAD capability differs from accepted authority",
        )
    acceptance = assess_current_projection(source, projection)
    if not acceptance.accepted_for_initial_squad:
        return _decision(
            status="BLOCKED",
            acceptance=acceptance,
            blockers=acceptance.blocker_codes,
            portfolios=(),
            recommended=None,
            projection=projection,
            compiled=compiled,
            capability=capability,
        )

    from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view

    rules = build_one_gameweek_rules_view(
        compiled,
        projection_mode=ProjectionMode.PRESEASON_DECISION_SUPPORT,
        capability=capability,
    )
    selected = _select_portfolios(projection.player_table, rules)
    rows = {str(row.transient_player_id): row for row in projection.player_table}
    results = {
        kind: _run_portfolio(kind, player_ids, projection, compiled, capability)
        for kind, player_ids in selected.items()
    }
    failed = tuple(
        sorted(
            f"STAGE10_{result.error_code or result.status.value}"
            for result in results.values()
            if result.status is not OptimisationStatus.SUCCESS
        )
    )
    if failed:
        return _decision(
            status="BLOCKED",
            acceptance=acceptance,
            blockers=failed,
            portfolios=(),
            recommended=None,
            projection=projection,
            compiled=compiled,
            capability=capability,
        )
    portfolios = tuple(_portfolio_view(kind, results[kind], rows) for kind in _PORTFOLIO_KINDS)
    recommended = max(
        portfolios,
        key=lambda row: (
            row.expected_manager_points,
            tuple(-ord(char) for char in row.portfolio_kind),
        ),
    ).portfolio_kind
    return _decision(
        status="SUCCESS",
        acceptance=acceptance,
        blockers=(),
        portfolios=portfolios,
        recommended=recommended,
        projection=projection,
        compiled=compiled,
        capability=capability,
    )


__all__ = [
    "CURRENT_INITIAL_SQUAD_ADAPTER_VERSION",
    "TARGET_GW1_INITIAL_SQUAD_CAPABILITY_HASH",
    "CurrentInitialSquadDecision",
    "CurrentInitialSquadPlayer",
    "CurrentInitialSquadPortfolio",
    "optimise_current_initial_squad",
]
