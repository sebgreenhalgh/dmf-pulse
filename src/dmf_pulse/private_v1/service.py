"""One application service for the private current-input recommendation vertical slice."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from importlib.resources import files
from math import comb
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.current_model import (
    CurrentModelFixtureMinutesInput,
    CurrentModelWeightedScenario,
    current_model_fixture_sha256,
)
from dmf_pulse.availability.manual_override import (
    MANUAL_SAMPLE_COUNT,
    ManualFixtureMinutesInput,
    ManualScenarioPlayer,
    ManualWeightedScenario,
    build_manual_minutes_override,
    manual_fixture_input_sha256,
)
from dmf_pulse.chips.captaincy import optimise_captain_vice
from dmf_pulse.football_events.minutes_context import Stage7MinutesContext
from dmf_pulse.football_events.service import (
    ScoreDistributionRequest,
    ScoreDistributionService,
    load_score_baseline_policy,
)
from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.gameweek import assemble_gameweek
from dmf_pulse.fpl_points.gameweek_summaries import build_gameweek_projection
from dmf_pulse.fpl_points.models import (
    PENALTY_GOAL_SHARE_PROXY_WARNING,
    EventAllocationConfig,
    FixtureProjectionResult,
    FixtureSimulationRequest,
    GameweekProjectionResult,
    GameweekScenarioSet,
    PenaltyHierarchyExhaustionPolicy,
    PenaltyTakerHierarchyEntry,
    PlayerPosition,
    SimulationStatus,
)
from dmf_pulse.fpl_points.player_prior import (
    GovernedPlayerPrior,
    bind_current_gw_fixture_allocation_profiles,
    bind_fixture_allocation_profiles,
    build_current_gw_player_prior_binding,
    build_player_prior_identity_binding,
    load_packaged_player_prior,
)
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter
from dmf_pulse.fpl_points.service import FplPointsService
from dmf_pulse.fpl_points.upstream import build_participation_scenario
from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateService,
    bind_current_unified_state_request,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct_payloads import CurrentPenaltyHierarchyTeamStatus
from dmf_pulse.markets.current import (
    CurrentMarketConstraintError,
    CurrentMarketConstraintService,
    CurrentMarketReadiness,
    bind_current_market_constraint_request,
)
from dmf_pulse.optimisation.manager_state import ManagerState, OwnershipSpell, seal_manager_state
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidateSquad,
    OneGameweekPlan,
    OneGameweekRulesView,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    BackendStatus,
    FreeTransferArc,
    MultiGameweekOptimisationRequest,
    MultiGameweekOptimisationResult,
    MultiGameweekResultStatus,
    PlayerCatalogEntry,
    PlayerPriceState,
    ScenarioTree,
    ScenarioTreeNode,
    SearchPolicy,
    TacticalNodeEvaluation,
    TransferAction,
    TransferMove,
    seal_request,
    seal_scenario_tree,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_policy import (
    load_multi_gameweek_search_policy,
    load_terminal_value_policy,
)
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.optimisation.multi_gameweek_solver import (
    action_moves,
    enumerate_legal_actions,
    information_set_key,
    make_transfer_action,
    resolve_free_transfer_arc,
)
from dmf_pulse.optimisation.policy import load_policy as load_one_gameweek_policy
from dmf_pulse.optimisation.stage10_adapter import Stage10TacticalAdapter
from dmf_pulse.private_v1.automatic_inputs import (
    PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import (
    PrivateDecisionLineage,
    PrivateDecisionStatus,
    PrivateFreeTransferState,
    PrivateFrontierComparison,
    PrivateGainMass,
    PrivatePairedComparison,
    PrivateTacticalDecision,
    PrivateTransferFrontier,
    PrivateTransferFrontierDelta,
    PrivateTransferFrontierPoint,
    PrivateTransferMove,
    PrivateV1Decision,
    PrivateV1ExecutionInput,
    seal_private_decision,
    seal_private_free_transfer_state,
    seal_private_frontier_comparison,
    seal_private_transfer_frontier,
    seal_private_transfer_frontier_point,
)
from dmf_pulse.private_v1.progress import NullProgress, ProgressSink
from dmf_pulse.private_v1.reporting import render_transfer_frontier
from dmf_pulse.private_v1.rolling_models import PrivateRollingGameweekInput
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view

_DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
_PRIVATE_EXPECTED_CANDIDATES_PER_POSITION = 2
_PRIVATE_UPSIDE_CANDIDATES_PER_POSITION = 1
_PRIVATE_VALUE_CANDIDATES_PER_POSITION = 1
_PRIVATE_MAX_RETAINED_INCOMING = 24


def _exact_root_action_upper_bound(
    *, squad_size: int, incoming_count: int, maximum_transfers: int
) -> int:
    """Return the finite unfiltered combination bound for exact root enumeration."""

    return sum(
        comb(squad_size, count) * comb(incoming_count, count)
        for count in range(min(maximum_transfers, squad_size, incoming_count) + 1)
    )


@dataclass(frozen=True)
class PrivateTransferSearchScope:
    """Auditable current-root scope produced before exact Stage-10 evaluation."""

    full_incoming_count: int
    retained_incoming_ids: tuple[str, ...]
    transfer_counts_considered: tuple[int, ...]
    one_transfer_actions: int
    two_transfer_actions: int
    exact_tactical_squads: int
    certified_dominated_candidates: int
    pruning_policy: str | None


def _action_space_disclosure(scope: PrivateTransferSearchScope) -> str:
    return (
        "Exact tactical optimum within the declared bounded transfer candidate set: "
        f"{len(scope.retained_incoming_ids)} retained incoming candidate(s) "
        f"from {scope.full_incoming_count} selectable player(s), the exact "
        f"current squad, transfer counts "
        f"{','.join(str(item) for item in scope.transfer_counts_considered)}, "
        f"{scope.one_transfer_actions} retained one-transfer action(s), "
        f"{scope.two_transfer_actions} retained two-transfer action(s), "
        f"{scope.exact_tactical_squads} exact tactical squad evaluation(s), "
        f"{scope.certified_dominated_candidates} certified pointwise-dominated "
        "incoming candidate(s) removed, and the declared Stage-9 scenario set. "
        f"Screening policy: {scope.pruning_policy or 'EXPLICIT_DECLARED_ACTION_SPACE'}."
    )


def _ranked_with_boundary_ties(
    player_ids: tuple[str, ...],
    *,
    limit: int,
    score: Callable[[str], Decimal],
) -> set[str]:
    """Select by a declared metric without an alphabetical or player-ID boundary cut."""

    if len(player_ids) <= limit:
        return set(player_ids)
    values = {player_id: score(player_id) for player_id in player_ids}
    cutoff = sorted(values.values(), reverse=True)[limit - 1]
    return {player_id for player_id, value in values.items() if value >= cutoff}


def _certified_pointwise_dominated(
    player_ids: tuple[str, ...],
    *,
    catalog: dict[str, PlayerCatalogEntry],
    prices: dict[str, PlayerPriceState],
    gameweek: GameweekProjectionResult,
) -> set[str]:
    """Prove one-GW dominance only within identical club/position feasibility cohorts."""

    groups: dict[tuple[PlayerPosition, str], list[str]] = defaultdict(list)
    for player_id in player_ids:
        entry = catalog[player_id]
        groups[(entry.position, entry.club_id)].append(player_id)
    dominated: set[str] = set()
    scenarios = gameweek.scenario_set.scenarios
    points_by_player = {
        player_id: tuple(scenario.player_points[player_id] for scenario in scenarios)
        for player_id in player_ids
    }
    appearances_by_player = {
        player_id: tuple(scenario.player_appeared[player_id] for scenario in scenarios)
        for player_id in player_ids
    }
    for members in groups.values():
        for player_id in members:
            for challenger_id in members:
                if challenger_id == player_id:
                    continue
                challenger_price = prices[challenger_id].current_price_tenths
                player_price = prices[player_id].current_price_tenths
                if challenger_price > player_price:
                    continue
                challenger_points = points_by_player[challenger_id]
                player_points = points_by_player[player_id]
                same_appearances = (
                    appearances_by_player[challenger_id] == appearances_by_player[player_id]
                )
                if (
                    same_appearances
                    and all(
                        left >= right
                        for left, right in zip(challenger_points, player_points, strict=True)
                    )
                    and (
                        challenger_price < player_price
                        or any(
                            left > right
                            for left, right in zip(challenger_points, player_points, strict=True)
                        )
                    )
                ):
                    dominated.add(player_id)
                    break
    return dominated


def _bounded_private_incoming_ids(
    player_ids: tuple[str, ...],
    *,
    catalog: dict[str, PlayerCatalogEntry],
    prices: dict[str, PlayerPriceState],
    gameweek: GameweekProjectionResult,
    maximum_transfers: int,
) -> tuple[tuple[str, ...], int]:
    """Apply the labelled private STANDARD shortlist; small universes remain exhaustive."""

    if maximum_transfers == 0:
        return (), 0
    dominated = _certified_pointwise_dominated(
        player_ids,
        catalog=catalog,
        prices=prices,
        gameweek=gameweek,
    )
    survivors = tuple(player_id for player_id in player_ids if player_id not in dominated)
    by_position: dict[PlayerPosition, list[str]] = defaultdict(list)
    for player_id in survivors:
        by_position[catalog[player_id].position].append(player_id)
    retained: set[str] = set()
    for position in PlayerPosition:
        members = tuple(by_position[position])
        if len(members) <= (
            _PRIVATE_EXPECTED_CANDIDATES_PER_POSITION
            + _PRIVATE_UPSIDE_CANDIDATES_PER_POSITION
            + _PRIVATE_VALUE_CANDIDATES_PER_POSITION
        ):
            retained.update(members)
            continue

        def expected(player_id: str) -> Decimal:
            return Decimal(str(gameweek.player_summaries[player_id].expected_points))

        def upside(player_id: str) -> Decimal:
            summary = gameweek.player_summaries[player_id]
            return Decimal(str(summary.expected_points)) + Decimal(
                str(summary.points_standard_deviation)
            )

        def value(player_id: str) -> Decimal:
            price = max(prices[player_id].current_price_tenths, 1)
            return expected(player_id) / Decimal(price)

        retained.update(
            _ranked_with_boundary_ties(
                members,
                limit=_PRIVATE_EXPECTED_CANDIDATES_PER_POSITION,
                score=expected,
            )
        )
        retained.update(
            _ranked_with_boundary_ties(
                members,
                limit=_PRIVATE_UPSIDE_CANDIDATES_PER_POSITION,
                score=upside,
            )
        )
        retained.update(
            _ranked_with_boundary_ties(
                members,
                limit=_PRIVATE_VALUE_CANDIDATES_PER_POSITION,
                score=value,
            )
        )
    if len(retained) > _PRIVATE_MAX_RETAINED_INCOMING:
        raise PrivateV1Error(
            "PRIVATE_TRANSFER_SCREEN_UNBOUNDED",
            "metric-boundary ties exceed the governed private STANDARD candidate limit",
        )
    return tuple(sorted(retained)), len(dominated)


def _uses_model_stage7(value: PrivateV1ExecutionInput) -> bool:
    return all(isinstance(item, CurrentModelFixtureMinutesInput) for item in value.manual_minutes)


def _stage7_input_sha256(
    value: ManualFixtureMinutesInput | CurrentModelFixtureMinutesInput,
) -> str:
    return (
        current_model_fixture_sha256(value)
        if isinstance(value, CurrentModelFixtureMinutesInput)
        else manual_fixture_input_sha256(value)
    )


def _penalty_role_limitations(
    execution: PrivateV1ExecutionInput,
    fixture_results: tuple[FixtureProjectionResult, ...],
) -> tuple[str, ...]:
    limitations: set[str] = set()
    if execution.current_penalty_hierarchy is not None:
        limitations.add("CURRENT_FPL_PENALTY_HIERARCHY_DETERMINISTIC_V1")
        limitations.update(getattr(execution.current_penalty_hierarchy, "warnings", ()))
    if any(
        "HISTORICAL_PENALTY_ROLE_FALLBACK_USED" in result.warnings for result in fixture_results
    ):
        limitations.add("HISTORICAL_PENALTY_ROLE_FALLBACK_USED")
    if any(PENALTY_GOAL_SHARE_PROXY_WARNING in result.warnings for result in fixture_results):
        limitations.add(PENALTY_GOAL_SHARE_PROXY_WARNING)
    return tuple(sorted(limitations))


def _penalty_hierarchy_exhaustion_policy(
    execution: PrivateV1ExecutionInput,
) -> PenaltyHierarchyExhaustionPolicy:
    if (
        execution.current_penalty_hierarchy is not None
        and execution.retention_class == "PRIVATE_TRANSIENT_NO_RETENTION"
    ):
        return PenaltyHierarchyExhaustionPolicy.PRIVATE_CURRENT_PENALTY_ROLE_GOAL_SHARE_PROXY_V1
    return PenaltyHierarchyExhaustionPolicy.BLOCK


@dataclass(frozen=True)
class PrivateV1RunResult:
    """Complete in-memory result; only the strict decision is safe for machine output."""

    decision: PrivateV1Decision
    report: str
    gameweek_projection: GameweekProjectionResult
    optimiser_result: MultiGameweekOptimisationResult


@dataclass(frozen=True)
class PrivateV1ReplayResult:
    """Exact outcome of re-executing and comparing a frozen synthetic bundle."""

    run: PrivateV1RunResult
    manifest_sha256: str


@dataclass
class _MemoizedStage10Evaluator:
    """Cache the canonical exact result for repeated Stage-11 visits to one squad."""

    delegate: Stage10TacticalAdapter
    _cache: dict[tuple[str, tuple[str, ...]], TacticalNodeEvaluation] = field(default_factory=dict)
    prepared_node: ScenarioTreeNode | None = None
    prepared_squads: tuple[CandidateSquad, ...] = ()

    @property
    def rules(self) -> OneGameweekRulesView:
        return self.delegate.rules

    def evaluate(self, *, node: ScenarioTreeNode, state: ManagerState) -> TacticalNodeEvaluation:
        key = (node.node_id, state.squad_ids)
        result = self._cache.get(key)
        if result is None:
            result = self.delegate.evaluate(node=node, state=state)
            self._cache[key] = result
        return result

    def precompute(
        self,
        *,
        progress: Callable[[tuple[int, int]], None] | None = None,
    ) -> None:
        """Populate the existing node/squad memo through one exact shared kernel."""

        if self.prepared_node is None or not self.prepared_squads:
            return
        pending = tuple(
            squad
            for squad in sorted(self.prepared_squads, key=lambda item: item.player_ids)
            if (self.prepared_node.node_id, squad.player_ids) not in self._cache
        )
        if not pending:
            return
        results = self.delegate.evaluate_many(
            node=self.prepared_node,
            squads=pending,
            progress=progress,
        )
        for squad_ids, result in results.items():
            self._cache[(self.prepared_node.node_id, squad_ids)] = result


def load_packaged_event_allocation_config() -> EventAllocationConfig:
    """Load the exact packaged Stage-9 allocation policy through strict YAML."""

    try:
        raw = yaml.safe_load(
            files("dmf_pulse.fpl_points.resources")
            .joinpath("event_allocation_baseline.yaml")
            .read_text(encoding="utf-8")
        )
        if not isinstance(raw, dict):
            raise ValueError("allocation configuration is not a mapping")
        parameters = raw.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("allocation parameters are missing")
        return EventAllocationConfig.model_validate(
            {
                "model_version_id": raw.get("model_version_id"),
                "source_tag": raw.get("source_tag"),
                "bps_completeness_mode": raw.get("bps_completeness_mode"),
                "auxiliary_source_tag": raw.get("auxiliary_source_tag"),
                **parameters,
            }
        )
    except (OSError, ValidationError, ValueError, yaml.YAMLError) as exc:
        raise PrivateV1Error(
            "STAGE9_POLICY_INVALID", "packaged event-allocation policy is invalid"
        ) from exc


def _utc_text(value: Any) -> str:
    rendered = value.isoformat()
    if not isinstance(rendered, str):  # pragma: no cover - datetime-like public contracts
        raise PrivateV1Error("TIMESTAMP_INVALID", "timestamp cannot be rendered")
    return rendered.replace("+00:00", "Z")


def _participant_row(
    value: ManualScenarioPlayer,
    *,
    team_id: str,
    hard_ineligible_ids: set[str],
) -> dict[str, object]:
    row: dict[str, object] = {
        "player_id": value.player_id,
        "team_id": team_id,
        "position": value.position,
        "official_minutes": value.official_minutes,
        "hard_ineligible": value.player_id in hard_ineligible_ids,
        "starter": value.role == "START",
    }
    if value.official_minutes > 0:
        if value.role == "START":
            row["entry_minute"] = 0
            row["exit_minute"] = value.official_minutes
        elif value.official_minutes < 90:
            row["entry_minute"] = 90 - value.official_minutes
            row["exit_minute"] = 90
        else:
            raise PrivateV1Error(
                "STAGE7_PARTICIPATION_INVALID",
                "a bench participation path cannot claim all 90 minutes",
            )
    return row


def _scenario_map(
    values: Sequence[ManualWeightedScenario | CurrentModelWeightedScenario],
) -> dict[str, ManualWeightedScenario | CurrentModelWeightedScenario]:
    return {item.scenario_id: item for item in values}


def _participation_scenarios(
    value: ManualFixtureMinutesInput | CurrentModelFixtureMinutesInput,
    *,
    gameweek_id: str,
    home_projection: object,
    away_projection: object,
) -> tuple[Any, ...]:
    home = _scenario_map(value.home.scenarios)
    away = _scenario_map(value.away.scenarios)
    if set(home) != set(away):
        raise PrivateV1Error(
            "STAGE7_SCENARIO_ALIGNMENT_INVALID",
            "home and away manual scenario identities must match exactly",
        )
    if isinstance(value, CurrentModelFixtureMinutesInput):
        home_hard = set(value.home.hard_ineligible_player_ids)
        away_hard = set(value.away.hard_ineligible_player_ids)
    else:
        home_hard = {item.player_id for item in value.home.hard_overrides}
        away_hard = {item.player_id for item in value.away.hard_overrides}
    scenarios: list[Any] = []
    for scenario_id in sorted(home):
        home_scenario = home[scenario_id]
        away_scenario = away[scenario_id]
        if home_scenario.count != away_scenario.count:
            raise PrivateV1Error(
                "STAGE7_SCENARIO_ALIGNMENT_INVALID",
                "paired manual scenarios must have the same exact count",
            )
        rows = tuple(
            _participant_row(item, team_id=value.home_team_id, hard_ineligible_ids=home_hard)
            for item in home_scenario.players
        ) + tuple(
            _participant_row(item, team_id=value.away_team_id, hard_ineligible_ids=away_hard)
            for item in away_scenario.players
        )
        try:
            scenarios.append(
                build_participation_scenario(
                    scenario_id=(
                        "PV1-"
                        + canonical_sha256(
                            {"fixture_id": value.fixture_id, "scenario_id": scenario_id}
                        )[:24].upper()
                    ),
                    probability=home_scenario.count / MANUAL_SAMPLE_COUNT,
                    fixture_id=value.fixture_id,
                    gameweek_id=gameweek_id,
                    home_team_id=value.home_team_id,
                    away_team_id=value.away_team_id,
                    participant_rows=rows,
                    home_projection=home_projection,
                    away_projection=away_projection,
                    information_cutoff_utc=_utc_text(value.information_cutoff),
                )
            )
        except FplPointsError as exc:
            raise PrivateV1Error(exc.code, "Stage-7 participation path is invalid") from None
    return tuple(scenarios)


def _verify_current_sources(value: PrivateV1ExecutionInput) -> None:
    state = value.current_state
    request = bind_current_unified_state_request(
        state.fpl_input,
        state.odds_input,
        state.identity_map,
        state.manager_state,
        value.ruleset,
        value.full_season_capability,
    )
    try:
        CurrentUnifiedStateService().verify(
            state,
            request,
            fpl_input=state.fpl_input,
            odds_input=state.odds_input,
            identity_map=state.identity_map,
            manager_state=state.manager_state,
            ruleset=value.ruleset,
            capability=value.full_season_capability,
            private_rules_authority=value.private_rules_authority,
        )
    except IngestionError as exc:
        raise PrivateV1Error(
            "CURRENT_STATE_INVALID", "current source state failed verification"
        ) from exc
    market_request = bind_current_market_constraint_request(state, value.market_identity_view)
    try:
        CurrentMarketConstraintService().verify(
            value.market_constraints,
            market_request,
            source=state,
            identity_view=value.market_identity_view,
        )
    except CurrentMarketConstraintError as exc:
        raise PrivateV1Error(
            "CURRENT_MARKET_INVALID", "current market state failed verification"
        ) from exc
    if any(
        fixture.readiness is CurrentMarketReadiness.BLOCKED
        for fixture in value.market_constraints.fixtures
    ):
        raise PrivateV1Error(
            "CURRENT_MARKET_BLOCKED", "at least one target fixture has no usable current market"
        )


def _verify_runtime_artifacts(value: PrivateV1ExecutionInput, prior: GovernedPlayerPrior) -> None:
    if (
        prior.artifact.artifact_sha256 != value.expected_player_prior_artifact_sha256
        or prior.historical_acceptance.acceptance_sha256
        != value.expected_player_prior_acceptance_sha256
    ):
        raise PrivateV1Error(
            "PLAYER_PRIOR_IDENTITY_MISMATCH",
            "packaged player-allocation prior differs from the execution contract",
        )
    if load_score_baseline_policy().sha256 != value.expected_stage8_policy_sha256:
        raise PrivateV1Error(
            "STAGE8_POLICY_IDENTITY_MISMATCH",
            "packaged Stage-8 policy differs from the execution contract",
        )


def _fixture_authority(value: PrivateV1ExecutionInput) -> dict[str, tuple[Any, Any]]:
    state = value.current_state
    target_identity = state.fpl_input.target_event.identity
    fpl_fixtures = {
        item.provider_fixture_id: item
        for item in state.fpl_input.fixtures
        if item.event_identity == target_identity
    }
    canonical = {item.official_fpl_fixture_id: item for item in value.market_identity_view.fixtures}
    if set(fpl_fixtures) != set(canonical):
        raise PrivateV1Error(
            "FIXTURE_SET_MISMATCH", "canonical fixture view does not equal the target FPL set"
        )
    return {
        str(canonical[fixture_id].canonical_fixture_id): (fixture, canonical[fixture_id])
        for fixture_id, fixture in fpl_fixtures.items()
    }


def _current_identity_maps(value: PrivateV1ExecutionInput) -> tuple[dict[str, Any], dict[str, Any]]:
    fpl_players = {item.provider_element_id: item for item in value.current_state.fpl_input.players}
    fpl_teams = {item.provider_team_id: item for item in value.current_state.fpl_input.teams}
    players = {
        str(mapping.canonical_player_id): fpl_players[mapping.official_fpl_element_id]
        for mapping in value.player_identity_map.players
    }
    teams = {
        str(mapping.canonical_team_id): fpl_teams[mapping.official_fpl_team_id]
        for mapping in value.player_identity_map.teams
    }
    if len(players) != len(value.player_identity_map.players) or len(teams) != len(
        value.player_identity_map.teams
    ):
        raise PrivateV1Error("CURRENT_FPL_INPUT_INVALID", "current FPL identities are ambiguous")
    return players, teams


def _canonical_player_by_element(value: PrivateV1ExecutionInput) -> dict[int, str]:
    return {
        item.official_fpl_element_id: str(item.canonical_player_id)
        for item in value.player_identity_map.players
    }


def _canonical_team_by_official(value: PrivateV1ExecutionInput) -> dict[int, str]:
    return {
        item.official_fpl_team_id: str(item.canonical_team_id)
        for item in value.player_identity_map.teams
    }


def _project_fixtures(
    value: PrivateV1ExecutionInput,
    prior: GovernedPlayerPrior,
    progress: ProgressSink | None = None,
    *,
    future_gameweek: PrivateRollingGameweekInput | None = None,
) -> tuple[
    tuple[FixtureProjectionResult, ...],
    dict[str, str],
    dict[str, str],
    dict[str, str],
    set[str],
]:
    active_progress = progress or NullProgress()
    current_players, current_teams = _current_identity_maps(value)
    if future_gameweek is None:
        fixture_authority = _fixture_authority(value)
        minutes_by_fixture = {item.fixture_id: item for item in value.manual_minutes}
        prior_by_fixture = {str(item.fixture_id): item for item in value.score_priors}
        constraints_by_fixture = {
            str(item.canonical_fixture_id): item.constraint_set.constraints
            for item in value.market_constraints.fixtures
        }
        target_gameweek = value.current_state.target_gameweek
    else:
        if any(item.market_mode == "BLOCKED" for item in future_gameweek.fixtures):
            raise PrivateV1Error(
                "FUTURE_FIXTURE_INPUT_BLOCKED",
                "at least one future fixture lacks an accepted current-cutoff projection input",
            )
        fpl_by_id = {
            item.provider_fixture_id: item for item in value.current_state.fpl_input.fixtures
        }
        fixture_authority = {
            str(item.canonical_fixture_id): (fpl_by_id[item.official_fpl_fixture_id], item)
            for item in future_gameweek.fixtures
        }
        minutes_by_fixture = {
            str(item.canonical_fixture_id): item.stage7 for item in future_gameweek.fixtures
        }
        prior_by_fixture = {
            str(item.canonical_fixture_id): item.score_prior for item in future_gameweek.fixtures
        }
        constraints_by_fixture = {
            str(item.canonical_fixture_id): item.market_constraints
            for item in future_gameweek.fixtures
        }
        target_gameweek = future_gameweek.gameweek
    engine = AcceptedRulesAdapter(value.ruleset)
    points = FplPointsService(engine, value.stage9_monte_carlo_policy)
    gameweek_id = f"GW-{target_gameweek}"
    stage7_context_hashes: dict[str, str] = {}
    stage8_hashes: dict[str, str] = {}
    binding_hashes: dict[str, str] = {}
    fallback_player_ids: set[str] = set()
    results: list[FixtureProjectionResult] = []
    canonical_teams = _canonical_team_by_official(value)
    ordered_fixture_ids = sorted(fixture_authority)
    fixture_count = len(ordered_fixture_ids)
    for fixture_number, fixture_id in enumerate(ordered_fixture_ids, start=1):
        active_progress.message(f"Stage 8/9 fixture {fixture_number}/{fixture_count}...")
        fpl_fixture, _canonical_fixture = fixture_authority[fixture_id]
        stage7 = minutes_by_fixture[fixture_id]
        score_prior = prior_by_fixture[fixture_id]
        expected_home = canonical_teams[int(fpl_fixture.home_team_identity.external_id_text)]
        expected_away = canonical_teams[int(fpl_fixture.away_team_identity.external_id_text)]
        if (
            stage7.home_team_id != expected_home
            or stage7.away_team_id != expected_away
            or str(score_prior.home_team_id) != expected_home
            or str(score_prior.away_team_id) != expected_away
        ):
            raise PrivateV1Error(
                "FIXTURE_IDENTITY_MISMATCH", "fixture team orientation differs across sources"
            )
        if isinstance(stage7, CurrentModelFixtureMinutesInput):
            home_projection = stage7.home_projection
            away_projection = stage7.away_projection
        else:
            minutes = build_manual_minutes_override(stage7)
            home_projection = minutes.home
            away_projection = minutes.away
        context = Stage7MinutesContext.from_projections(home_projection, away_projection)
        stage7_context_hashes[fixture_id] = context.semantic_sha256
        try:
            stage8 = ScoreDistributionService().project(
                ScoreDistributionRequest(
                    schema_version="score-distribution-request-v1",
                    fixture_id=UUID(fixture_id),
                    home_team_id=UUID(expected_home),
                    away_team_id=UUID(expected_away),
                    as_of=value.current_state.information_cutoff,
                    minutes_context=context,
                    prior=score_prior.score_prior_request,
                    constraints=constraints_by_fixture[fixture_id],
                )
            )
        except (IngestionError, ValidationError, ValueError) as exc:
            raise PrivateV1Error(
                "STAGE8_INPUT_INVALID", "Stage-8 fixture input is invalid"
            ) from exc
        if stage8.status != "PROJECTED" or stage8.distribution is None:
            raise PrivateV1Error(
                stage8.error_code or "STAGE8_BLOCKED", "Stage-8 fixture projection is blocked"
            )
        distribution = stage8.distribution
        stage8_hashes[fixture_id] = distribution.result_sha256
        participation = _participation_scenarios(
            stage7,
            gameweek_id=gameweek_id,
            home_projection=home_projection,
            away_projection=away_projection,
        )
        participant_ids = {
            item.player_id for scenario in participation for item in scenario.participants
        }
        unknown = participant_ids - set(current_players)
        if unknown:
            raise PrivateV1Error(
                "STAGE7_PLAYER_NOT_CURRENT", "Stage-7 contains a player outside current FPL input"
            )
        source_player_map = {
            current_players[player_id].provider_element_id: player_id
            for player_id in participant_ids
        }
        team_ids = {
            canonical_teams[int(current_players[player_id].team_identity.external_id_text)]
            for player_id in participant_ids
        }
        source_team_map = {
            int(current_teams[team_id].identity.external_id_text): team_id for team_id in team_ids
        }
        try:
            if value.current_state.target_gameweek == 1:
                binding = build_player_prior_identity_binding(
                    prior,
                    value.current_state.fpl_input,
                    canonical_player_ids_by_source_id=source_player_map,
                    canonical_team_ids_by_source_id=source_team_map,
                )
                profiles, prior_identity = bind_fixture_allocation_profiles(
                    prior, binding, participation
                )
                binding_sha256 = binding.semantic_sha256
            else:
                policy = value.player_prior_carry_forward_policy
                if policy is None:  # guarded by PrivateV1ExecutionInput
                    raise PrivateV1Error(
                        "PLAYER_PRIOR_POLICY_MISSING",
                        "current Gameweek carry-forward policy is unavailable",
                    )
                current_binding = build_current_gw_player_prior_binding(
                    prior,
                    value.current_state.fpl_input,
                    policy,
                    canonical_player_ids_by_source_id=source_player_map,
                    canonical_team_ids_by_source_id=source_team_map,
                )
                fallback_player_ids.update(
                    entry.current_player_id
                    for entry in current_binding.entries
                    if entry.assignment_level == "FPL_POSITION_FALLBACK"
                )
                profiles, prior_identity = bind_current_gw_fixture_allocation_profiles(
                    prior, current_binding, participation
                )
                binding_sha256 = current_binding.semantic_sha256
        except FplPointsError as exc:
            raise PrivateV1Error(
                exc.code, "current player allocation prior is unavailable"
            ) from None
        binding_hashes[fixture_id] = binding_sha256
        penalty_hierarchy: tuple[PenaltyTakerHierarchyEntry, ...] = ()
        if value.current_penalty_hierarchy is not None:
            usable_team_ids = {
                team.official_fpl_team_id
                for team in value.current_penalty_hierarchy.teams
                if team.status is CurrentPenaltyHierarchyTeamStatus.USABLE_UNIQUE_ORDER
            }
            hierarchy_entries: list[PenaltyTakerHierarchyEntry] = []
            for entry in value.current_penalty_hierarchy.entries:
                if entry.official_fpl_team_id not in source_team_map:
                    continue
                if entry.official_fpl_team_id not in usable_team_ids:
                    continue
                player_id = source_player_map.get(entry.official_fpl_element_id)
                if player_id is None:
                    raise PrivateV1Error(
                        "PENALTY_HIERARCHY_MAPPING_MISMATCH",
                        "current penalty hierarchy differs from the fixture player universe",
                    )
                hierarchy_entries.append(
                    PenaltyTakerHierarchyEntry(
                        player_id=player_id,
                        team_id=source_team_map[entry.official_fpl_team_id],
                        order=entry.penalties_order,
                    )
                )
            penalty_hierarchy = tuple(
                sorted(
                    hierarchy_entries,
                    key=lambda item: (item.team_id, item.order, item.player_id),
                )
            )
        request = FixtureSimulationRequest(
            schema_version="fpl-points-fixture-request-v1",
            gameweek_id=gameweek_id,
            projection_mode=value.projection_mode,
            as_of_utc=_utc_text(value.current_state.information_cutoff),
            information_cutoff_utc=_utc_text(value.current_state.information_cutoff),
            root_seed=value.root_seed,
            scenario_count=value.scenario_count,
            score_distribution=distribution,
            participation_scenarios=participation,
            allocation_profiles=profiles,
            penalty_taker_hierarchy=penalty_hierarchy,
            penalty_hierarchy_exhaustion_policy=(_penalty_hierarchy_exhaustion_policy(value)),
            player_prior_identity=prior_identity,
            allocation_config=value.event_allocation_config,
            expected_ruleset_id=engine.identity.ruleset_id,
            expected_ruleset_version=engine.identity.ruleset_version,
            expected_ruleset_hash=engine.identity.ruleset_hash,
        )
        with active_progress.stage(
            started=None,
            completed=f"Stage 8/9 fixture {fixture_number}/{fixture_count} complete",
            failed=f"Stage 9 fixture {fixture_number}/{fixture_count}",
            heartbeat=f"Stage 9 fixture {fixture_number}/{fixture_count} still running",
        ):
            result = points.project(request)
        if result.status is not SimulationStatus.SUCCESS:
            raise PrivateV1Error(
                result.error_code or "STAGE9_BLOCKED", "Stage-9 fixture projection is blocked"
            )
        results.append(result)
    return (
        tuple(results),
        stage7_context_hashes,
        stage8_hashes,
        binding_hashes,
        fallback_player_ids,
    )


def _manager_state(
    value: PrivateV1ExecutionInput,
    *,
    root_node_id: str,
) -> ManagerState:
    ownership = {item.official_fpl_element_id: item for item in value.ownership.members}
    spells: list[OwnershipSpell] = []
    canonical_players = _canonical_player_by_element(value)
    canonical_teams = _canonical_team_by_official(value)
    for member in value.current_state.manager_state.squad:
        fact = ownership[member.official_fpl_element_id]
        player_id = canonical_players[member.official_fpl_element_id]
        spells.append(
            OwnershipSpell(
                spell_id=canonical_sha256(
                    {
                        "contract": "PRIVATE_V1_OPERATOR_ATTESTED_OWNERSHIP",
                        "player_id": player_id,
                        "acquired_gameweek": fact.acquired_gameweek,
                        "ownership_sha256": value.ownership.semantic_sha256,
                    }
                ),
                player_id=player_id,
                club_id=canonical_teams[int(member.team_identity.external_id_text)],
                position=PlayerPosition(member.position.value),
                purchase_price_tenths=member.purchase_price_tenths,
                current_price_tenths=member.current_price_tenths,
                started_gameweek=fact.acquired_gameweek,
                started_at_node_id=f"OPERATOR_ATTESTED_GW_{fact.acquired_gameweek}",
            )
        )
    provisional = ManagerState(
        state_id=f"{value.run_id}-CURRENT",
        current_gameweek=value.current_state.target_gameweek,
        observed_node_id=root_node_id,
        bank_tenths=value.current_state.manager_state.bank_tenths,
        free_transfers=value.current_state.manager_state.free_transfers,
        ownership_spells=tuple(
            sorted(spells, key=lambda item: (item.player_id, item.started_gameweek, item.spell_id))
        ),
        ruleset_id=value.ruleset.ruleset_id,
        ruleset_version=value.ruleset.ruleset_version,
        ruleset_hash=value.ruleset.ruleset_hash,
        state_sha256="0" * 64,
    )
    return seal_manager_state(provisional)


def _stage11_request(
    value: PrivateV1ExecutionInput,
    gameweek: GameweekProjectionResult,
    *,
    future_gameweeks: tuple[GameweekProjectionResult, ...] = (),
) -> tuple[
    MultiGameweekOptimisationRequest,
    _MemoizedStage10Evaluator,
    dict[str, CandidatePlayer],
    PrivateTransferSearchScope,
]:
    current_players, _teams = _current_identity_maps(value)
    canonical_players = _canonical_player_by_element(value)
    canonical_teams = _canonical_team_by_official(value)
    projections = (gameweek, *future_gameweeks)
    scenario_player_ids = set(gameweek.scenario_set.player_ids)
    if any(set(item.scenario_set.player_ids) != scenario_player_ids for item in projections[1:]):
        raise PrivateV1Error(
            "HORIZON_PLAYER_UNIVERSE_MISMATCH",
            "all private horizon Gameweeks must retain one canonical player universe",
        )
    required = {
        canonical_players[item.official_fpl_element_id]
        for item in value.current_state.manager_state.squad
    } | {
        canonical_players[element_id]
        for element_id in value.candidate_action_policy.allowed_transfer_in_element_ids
    }
    if not required <= scenario_player_ids:
        raise PrivateV1Error(
            "MISSING_PLAYER_PROJECTION",
            "manager or incoming candidate is absent from the Stage-9 joint matrix",
        )
    if not scenario_player_ids <= set(current_players):
        raise PrivateV1Error(
            "STAGE9_PLAYER_NOT_CURRENT", "Stage-9 contains a player outside current FPL input"
        )
    catalog = tuple(
        sorted(
            (
                PlayerCatalogEntry(
                    player_id=player_id,
                    club_id=canonical_teams[
                        int(current_players[player_id].team_identity.external_id_text)
                    ],
                    position=PlayerPosition(current_players[player_id].position.value),
                )
                for player_id in scenario_player_ids
            ),
            key=lambda item: item.player_id,
        )
    )
    candidates = {
        item.player_id: CandidatePlayer(
            player_id=item.player_id,
            club_id=item.club_id,
            position=item.position,
            initial_selection_cost_tenths=current_players[item.player_id].current_price_tenths,
        )
        for item in catalog
    }
    prices = {
        item.player_id: PlayerPriceState(
            current_price_tenths=current_players[item.player_id].current_price_tenths,
            purchasable=True,
        )
        for item in catalog
    }
    element_to_player = {
        element_id: player_id for element_id, player_id in canonical_players.items()
    }
    full_allowed = tuple(
        sorted(
            element_to_player[item]
            for item in value.candidate_action_policy.allowed_transfer_in_element_ids
        )
    )
    root_id = f"GW-{value.current_state.target_gameweek}-CURRENT"
    if gameweek.result_sha256 is None:  # guarded by the successful projection contract
        raise PrivateV1Error("STAGE9_GAMEWEEK_INVALID", "Stage-9 result hash is absent")
    declared_transfer_limit = value.candidate_action_policy.maximum_transfers
    pruning_policy = (
        PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1
        if PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1 in value.candidate_action_policy.rationale
        else None
    )
    certified_dominated = 0
    allowed = full_allowed
    if pruning_policy is not None:
        allowed, certified_dominated = _bounded_private_incoming_ids(
            full_allowed,
            catalog={item.player_id: item for item in catalog},
            prices=prices,
            gameweek=gameweek,
            maximum_transfers=declared_transfer_limit,
        )
    root = ScenarioTreeNode(
        node_id=root_id,
        gameweek=value.current_state.target_gameweek,
        conditional_probability=Decimal(1),
        information_set_key="pending",
        points_state_id=gameweek.result_sha256,
        prices=prices,
        allowed_transfer_in_ids=allowed,
        tactical_values=(),
    )
    root = root.model_copy(
        update={"information_set_key": information_set_key(root, parent_key=None)}
    )
    nodes = [root]
    parent = root
    parent_key = root.information_set_key
    for future in future_gameweeks:
        if future.result_sha256 is None:
            raise PrivateV1Error("STAGE9_GAMEWEEK_INVALID", "future Stage-9 result hash is absent")
        node_id = f"GW-{future.scenario_set.gameweek_id.removeprefix('GW-')}-CURRENT-CUTOFF-PLAN"
        preliminary = ScenarioTreeNode(
            node_id=node_id,
            parent_id=parent.node_id,
            gameweek=parent.gameweek + 1,
            conditional_probability=Decimal(1),
            information_set_key="pending",
            points_state_id=future.result_sha256,
            prices=prices,
            allowed_transfer_in_ids=allowed,
            tactical_values=(),
        )
        node = preliminary.model_copy(
            update={"information_set_key": information_set_key(preliminary, parent_key=parent_key)}
        )
        nodes.append(node)
        parent = node
        parent_key = node.information_set_key
    tree = seal_scenario_tree(
        ScenarioTree(
            tree_id=(
                f"{value.run_id}-GW-{value.current_state.target_gameweek}"
                if not future_gameweeks
                else (
                    f"{value.run_id}-GW-{value.current_state.target_gameweek}-TO-"
                    f"{value.current_state.target_gameweek + len(future_gameweeks)}"
                )
            ),
            nodes=tuple(nodes),
            tree_sha256="0" * 64,
        )
    )
    transfer_rules = build_multi_gameweek_transfer_rules(
        value.ruleset,
        projection_mode=value.projection_mode,
    )
    search = load_multi_gameweek_search_policy()
    search_payload = search.model_dump(mode="python")
    effective_maximum_transfers = min(
        declared_transfer_limit,
        search.max_transfers_per_node,
        transfer_rules.max_transfers_per_deadline,
        len(allowed),
        len(value.current_state.manager_state.squad),
    )
    search_payload["max_transfers_per_node"] = effective_maximum_transfers
    root_action_upper = _exact_root_action_upper_bound(
        squad_size=len(value.current_state.manager_state.squad),
        incoming_count=len(allowed),
        maximum_transfers=effective_maximum_transfers,
    )
    search_payload["max_actions_per_state"] = max(search.max_actions_per_state, root_action_upper)
    search_payload["max_returned_root_candidates"] = max(
        search.max_returned_root_candidates, root_action_upper
    )
    search_payload["policy_sha256"] = "0" * 64
    search = seal_search_policy(SearchPolicy.model_validate(search_payload))
    manager_state = _manager_state(value, root_node_id=root_id)
    request = seal_request(
        MultiGameweekOptimisationRequest(
            request_id=value.run_id,
            projection_mode=value.projection_mode,
            initial_state=manager_state,
            candidate_pool=catalog,
            rules=transfer_rules,
            scenario_tree=tree,
            search_policy=search,
            terminal_policy=load_terminal_value_policy(),
            assumptions=tuple(
                sorted(
                    {
                        "NO_CHIP",
                        (
                            "ONE_GAMEWEEK_HORIZON_ZERO_TERMINAL_VALUE"
                            if not future_gameweeks
                            else "THREE_GAMEWEEK_ZERO_TERMINAL_VALUE_AFTER_HORIZON"
                        ),
                        "OPERATOR_ATTESTED_OWNERSHIP_ACQUISITION_GAMEWEEKS",
                        (
                            "ACCEPTED_REGULARISED_EMPIRICAL_BAYES_COHERENCE_STAGE7"
                            if _uses_model_stage7(value)
                            else "PRIVATE_MANUAL_TRANSIENT_STAGE7_NOT_MODEL_DERIVED"
                        ),
                        (
                            PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1
                            if pruning_policy is not None
                            else "TRANSFER_SCOPE_EXPLICIT_OPERATOR_DECLARATION"
                        ),
                        (
                            "ONE_GAMEWEEK_ZERO_TERMINAL_VALUE_OBJECTIVE"
                            if not future_gameweeks
                            else "EXPECTED_THREE_GAMEWEEK_POINTS_WITH_LEGAL_RECOURSE"
                        ),
                        *(
                            ()
                            if not future_gameweeks
                            else (
                                "DETERMINISTIC_NO_NEW_INFORMATION_REVELATION_V1",
                                "FUTURE_PRICE_CHANGES_NOT_MODELLED_IN_PRIVATE_3GW_V1",
                                "HORIZON_TRANSFER_COUNT_FRONTIER_V1",
                                "NO_CHIP_EXPLICIT",
                            )
                        ),
                    }
                )
            ),
            request_sha256="0" * 64,
        )
    )
    tactical = Stage10TacticalAdapter(
        candidate_pool=catalog,
        rules=build_one_gameweek_rules_view(
            value.ruleset,
            projection_mode=value.projection_mode,
        ),
        policy=load_one_gameweek_policy(),
        scenarios_by_node={
            node.node_id: projection.scenario_set.scenarios
            for node, projection in zip(nodes, projections, strict=True)
        },
    )
    actions = enumerate_legal_actions(
        manager_state,
        node=root,
        candidate_pool=catalog,
        rules=transfer_rules,
        policy=search,
    )
    counts = tuple(sorted({item.transfer_count for item in actions}))
    expected_counts = tuple(range(effective_maximum_transfers + 1))
    if counts != expected_counts:
        raise PrivateV1Error(
            "PRIVATE_TRANSFER_COUNT_SCOPE_INCOMPLETE",
            "the declared private transfer-count scope has no legal action at every count "
            f"(available={counts}, retained_incoming={len(allowed)}, "
            f"certified_removed={certified_dominated})",
        )
    current_squad = set(manager_state.squad_ids)
    squad_signatures = {
        tuple(sorted((current_squad - set(action.transfers_out)) | set(action.transfers_in)))
        for action in actions
    }
    scope = PrivateTransferSearchScope(
        full_incoming_count=len(full_allowed),
        retained_incoming_ids=allowed,
        transfer_counts_considered=counts,
        one_transfer_actions=sum(item.transfer_count == 1 for item in actions),
        two_transfer_actions=sum(item.transfer_count == 2 for item in actions),
        exact_tactical_squads=len(squad_signatures),
        certified_dominated_candidates=certified_dominated,
        pruning_policy=pruning_policy,
    )
    memoized = _MemoizedStage10Evaluator(
        tactical,
        prepared_node=root,
        prepared_squads=tuple(
            CandidateSquad(player_ids=squad_ids) for squad_ids in sorted(squad_signatures)
        ),
    )
    return request, memoized, candidates, scope


def _parse_tactical_plan(value: dict[str, object]) -> OneGameweekPlan:
    try:
        return OneGameweekPlan.model_validate(value)
    except ValidationError:
        raise PrivateV1Error(
            "OPTIMISER_OUTPUT_INVALID", "Stage-11 tactical output failed validation"
        ) from None


def _verify_captain(
    plan: OneGameweekPlan,
    *,
    scenarios: GameweekScenarioSet,
    candidates: dict[str, CandidatePlayer],
    tactical: _MemoizedStage10Evaluator,
) -> str:
    decision = optimise_captain_vice(  # type: ignore[type-var]
        scenarios=scenarios.scenarios,
        base_tactic=plan.tactical_configuration,
        players=candidates,
        rules=tactical.rules,
    )
    if (
        decision.captain != plan.tactical_configuration.captain
        or decision.vice_captain != plan.tactical_configuration.vice_captain
        or abs(Decimal(str(decision.expected_manager_points)) - plan.expected_manager_points)
        > Decimal("0.000000001")
    ):
        raise PrivateV1Error(
            "CAPTAIN_LAYER_MISMATCH",
            "captain/vice verification differs from exact Stage-10 tactics",
        )
    return decision.decision_hash


def _tactical_decision(plan: OneGameweekPlan, captain_hash: str) -> PrivateTacticalDecision:
    tactic = plan.tactical_configuration
    return PrivateTacticalDecision(
        starting_xi=tuple(sorted(tactic.starting_xi)),
        bench_goalkeeper=tactic.bench_goalkeeper,
        bench_outfield_order=tactic.bench_order,
        captain=tactic.captain,
        vice_captain=tactic.vice_captain,
        captain_decision_sha256=captain_hash,
        captain_scoring_layer="STAGE10_EXACT_TACTICAL_EVALUATOR",
        captain_verification_layer="CHIPS_CAPTAINCY_OPTIMISE_CAPTAIN_VICE",
    )


def _private_free_transfer_state(
    arc: FreeTransferArc,
    *,
    manager_state_before: int,
) -> PrivateFreeTransferState:
    return seal_private_free_transfer_state(
        PrivateFreeTransferState.model_construct(
            transition_event=arc.event,
            unlimited_transfers_without_hits=arc.unlimited_transfers_without_hits,
            manager_state_before=manager_state_before,
            effective_before_action=arc.effective_ft_before,
            transfer_count=arc.transfer_count,
            used_by_action=arc.free_used,
            paid_transfers=arc.paid_transfers,
            hit_points=arc.hit_points,
            remaining_immediately_after_action=arc.effective_ft_before - arc.free_used,
            granted_for_next_deadline=arc.earned_for_next_deadline,
            next_decision_deadline=arc.ft_after,
            maximum_free_transfers=arc.maximum_free_transfers,
            semantic_sha256="0" * 64,
        )
    )


def _frontier_relationship(
    lower: TransferAction,
    higher: TransferAction,
    *,
    candidate_pool: tuple[PlayerCatalogEntry, ...],
) -> tuple[Literal["STRICT_EXTENSION", "NON_NESTED"], tuple[TransferMove, ...]]:
    lower_out = set(lower.transfers_out)
    lower_in = set(lower.transfers_in)
    higher_out = set(higher.transfers_out)
    higher_in = set(higher.transfers_in)
    if (
        lower.transition_event == higher.transition_event
        and lower_out < higher_out
        and lower_in < higher_in
        and len(higher_out - lower_out) == len(higher_in - lower_in)
    ):
        incremental = make_transfer_action(
            transfers_out=tuple(higher_out - lower_out),
            transfers_in=tuple(higher_in - lower_in),
            event=higher.transition_event,
        )
        return "STRICT_EXTENSION", action_moves(incremental, candidate_pool=candidate_pool)
    return "NON_NESTED", ()


def _private_transfer_moves(
    action: TransferAction,
    *,
    candidate_pool: tuple[PlayerCatalogEntry, ...],
    element_by_player: dict[str, int],
) -> tuple[PrivateTransferMove, ...]:
    return tuple(
        PrivateTransferMove(
            player_out_id=move.player_out,
            player_in_id=move.player_in,
            official_fpl_element_out=element_by_player[move.player_out],
            official_fpl_element_in=element_by_player[move.player_in],
        )
        for move in action_moves(action, candidate_pool=candidate_pool)
    )


def _formation(
    plan: OneGameweekPlan,
    *,
    candidates: dict[str, CandidatePlayer],
) -> tuple[int, int, int]:
    starting_xi = plan.tactical_configuration.starting_xi
    defenders = sum(
        candidates[player_id].position is PlayerPosition.DEF for player_id in starting_xi
    )
    midfielders = sum(
        candidates[player_id].position is PlayerPosition.MID for player_id in starting_xi
    )
    forwards = sum(
        candidates[player_id].position is PlayerPosition.FWD for player_id in starting_xi
    )
    return defenders, midfielders, forwards


def _quantile(masses: dict[int, Fraction], probability: Fraction) -> int:
    total = sum(masses.values(), Fraction(0))
    cumulative = Fraction(0)
    for points, mass in sorted(masses.items()):
        cumulative += mass / total
        if cumulative >= probability:
            return points
    raise PrivateV1Error("COMPARATOR_INVALID", "paired comparison has no quantile")


def _decimal(value: Fraction) -> Decimal:
    with localcontext(_DECIMAL_CONTEXT):
        return Decimal(value.numerator) / Decimal(value.denominator)


def _frontier_comparison(
    plan: OneGameweekPlan,
    baseline: OneGameweekPlan,
    *,
    scenarios: GameweekScenarioSet,
    hit_points: int,
) -> PrivateFrontierComparison:
    plan_scores = {
        (item.scenario_id, item.outcome_draw_id): item.manager_points
        for item in plan.scenario_scores
    }
    baseline_scores = {
        (item.scenario_id, item.outcome_draw_id): item.manager_points
        for item in baseline.scenario_scores
    }
    scenario_weights = {
        (item.scenario_id, item.outcome_draw_id): Fraction(str(item.weight))
        for item in scenarios.scenarios
    }
    if not plan_scores.keys() == baseline_scores.keys() == scenario_weights.keys():
        raise PrivateV1Error(
            "COMPARATOR_SCENARIO_MISMATCH", "recommendation and baseline scenarios differ"
        )
    total_weight = sum(scenario_weights.values(), Fraction(0))
    if total_weight <= 0:
        raise PrivateV1Error("COMPARATOR_INVALID", "scenario weights are invalid")
    normalized = {key: weight / total_weight for key, weight in scenario_weights.items()}
    gain_masses: dict[int, Fraction] = {}
    expected_plan = Fraction(0)
    expected_baseline = Fraction(0)
    for key, weight in normalized.items():
        plan_points = plan_scores[key]
        baseline_points = baseline_scores[key]
        gain = plan_points - hit_points - baseline_points
        gain_masses[gain] = gain_masses.get(gain, Fraction(0)) + weight
        expected_plan += weight * plan_points
        expected_baseline += weight * baseline_points
    gain_expected = expected_plan - hit_points - expected_baseline
    return seal_private_frontier_comparison(
        PrivateFrontierComparison.model_construct(
            scenario_count=len(normalized),
            plan_expected_points_before_hit=_decimal(expected_plan),
            baseline_expected_points=_decimal(expected_baseline),
            transfer_hit_points=hit_points,
            plan_expected_points_after_hit=_decimal(expected_plan) - hit_points,
            expected_uplift=_decimal(gain_expected),
            gain_p10=_quantile(gain_masses, Fraction(1, 10)),
            gain_median=_quantile(gain_masses, Fraction(1, 2)),
            gain_p90=_quantile(gain_masses, Fraction(9, 10)),
            probability_plan_beats_hold=_decimal(
                sum((mass for points, mass in gain_masses.items() if points > 0), Fraction(0))
            ),
            probability_gain_at_least_four=_decimal(
                sum((mass for points, mass in gain_masses.items() if points >= 4), Fraction(0))
            ),
            probability_loss_at_least_four=_decimal(
                sum((mass for points, mass in gain_masses.items() if points <= -4), Fraction(0))
            ),
            gain_pmf=tuple(
                PrivateGainMass(points=points, probability=_decimal(mass))
                for points, mass in sorted(gain_masses.items())
            ),
            semantic_sha256="0" * 64,
        )
    )


def _paired_comparison(
    recommended: OneGameweekPlan,
    baseline: OneGameweekPlan,
    *,
    scenarios: GameweekScenarioSet,
    hit_points: int,
) -> PrivatePairedComparison:
    frontier = _frontier_comparison(
        recommended,
        baseline,
        scenarios=scenarios,
        hit_points=hit_points,
    )
    return _paired_comparison_from_frontier(frontier)


def _paired_comparison_from_frontier(
    frontier: PrivateFrontierComparison,
) -> PrivatePairedComparison:
    provisional = PrivatePairedComparison.model_construct(
        scenario_count=frontier.scenario_count,
        recommended_expected_points_before_hit=frontier.plan_expected_points_before_hit,
        no_transfer_expected_points=frontier.baseline_expected_points,
        transfer_hit_points=frontier.transfer_hit_points,
        recommended_expected_points_after_hit=frontier.plan_expected_points_after_hit,
        net_expected_uplift=frontier.expected_uplift,
        gain_p10=frontier.gain_p10,
        gain_median=frontier.gain_median,
        gain_p90=frontier.gain_p90,
        probability_recommended_beats_baseline=frontier.probability_plan_beats_hold,
        probability_gain_at_least_four=frontier.probability_gain_at_least_four,
        probability_loss_at_least_four=frontier.probability_loss_at_least_four,
        gain_pmf=frontier.gain_pmf,
        semantic_sha256="0" * 64,
    )
    payload = provisional.model_dump(mode="python")
    payload["semantic_sha256"] = canonical_sha256(
        provisional.model_dump(mode="json", exclude={"semantic_sha256"})
    )
    return PrivatePairedComparison.model_validate(payload)


def _build_private_transfer_frontier(
    optimiser: MultiGameweekOptimisationResult,
    *,
    request: MultiGameweekOptimisationRequest,
    scenarios: GameweekScenarioSet,
    baseline: OneGameweekPlan,
    candidates: dict[str, CandidatePlayer],
    tactical: _MemoizedStage10Evaluator,
    element_by_player: dict[str, int],
    action_space_disclosure: str,
    stage9_projection_sha256: str,
    stage9_joint_scenario_sha256: str,
    candidate_action_policy_sha256: str,
) -> tuple[PrivateTransferFrontier, dict[str, str]]:
    source = optimiser.transfer_count_frontier
    if source is None:
        raise PrivateV1Error(
            "TRANSFER_FRONTIER_UNAVAILABLE",
            "complete Stage-11 result omitted the evaluated transfer-count frontier",
        )
    points: list[PrivateTransferFrontierPoint] = []
    captain_hashes: dict[str, str] = {}
    actions: list[TransferAction] = []
    for item in source.points:
        decision = item.plan.current_action
        plan = _parse_tactical_plan(decision.tactical_evaluation.tactical_plan)
        captain_hash = _verify_captain(
            plan,
            scenarios=scenarios,
            candidates=candidates,
            tactical=tactical,
        )
        captain_hashes[decision.tactical_evaluation.tactical_plan_sha256] = captain_hash
        comparison = _frontier_comparison(
            plan,
            baseline,
            scenarios=scenarios,
            hit_points=decision.hit_points,
        )
        if comparison.plan_expected_points_after_hit != item.current_gameweek_objective:
            raise PrivateV1Error(
                "FRONTIER_OBJECTIVE_MISMATCH",
                "paired current-GW frontier value differs from Stage-11 selection",
            )
        arc = resolve_free_transfer_arc(
            request.rules,
            event=decision.action.transition_event,
            ft_before=decision.free_transfers_before,
            transfer_count=decision.action.transfer_count,
        )
        if (
            arc.paid_transfers != decision.paid_transfers
            or arc.hit_points != decision.hit_points
            or arc.ft_after != decision.free_transfers_after
        ):
            raise PrivateV1Error(
                "FRONTIER_FT_TRANSITION_MISMATCH",
                "frontier FT disclosure differs from the accepted Stage-11 transition",
            )
        moves = _private_transfer_moves(
            decision.action,
            candidate_pool=request.candidate_pool,
            element_by_player=element_by_player,
        )
        point = seal_private_transfer_frontier_point(
            PrivateTransferFrontierPoint.model_construct(
                transfer_count=decision.action.transfer_count,
                action_id=decision.action.action_id,
                action_signature=decision.action.signature,
                action_sha256=semantic_sha256(decision.action.model_dump(mode="json")),
                transfers=moves,
                resulting_squad=decision.squad_after,
                tactics=_tactical_decision(plan, captain_hash),
                formation=_formation(plan, candidates=candidates),
                comparison_vs_hold=comparison,
                bank_after_tenths=decision.bank_after_tenths,
                free_transfer_state=_private_free_transfer_state(
                    arc,
                    manager_state_before=decision.free_transfers_before,
                ),
                tactical_plan_sha256=decision.tactical_evaluation.tactical_plan_sha256,
                stage11_plan_sha256=item.plan.plan_sha256,
                semantic_sha256="0" * 64,
            )
        )
        points.append(point)
        actions.append(decision.action)
    deltas: list[PrivateTransferFrontierDelta] = []
    for lower_point, higher_point, lower_action, higher_action in zip(
        points[:-1],
        points[1:],
        actions[:-1],
        actions[1:],
        strict=True,
    ):
        relationship, incremental = _frontier_relationship(
            lower_action,
            higher_action,
            candidate_pool=request.candidate_pool,
        )
        deltas.append(
            PrivateTransferFrontierDelta(
                lower_transfer_count=lower_point.transfer_count,
                higher_transfer_count=higher_point.transfer_count,
                immediate_expected_points_delta=(
                    higher_point.comparison_vs_hold.plan_expected_points_after_hit
                    - lower_point.comparison_vs_hold.plan_expected_points_after_hit
                ),
                plan_relationship=relationship,
                nested_incremental_transfers=tuple(
                    PrivateTransferMove(
                        player_out_id=move.player_out,
                        player_in_id=move.player_in,
                        official_fpl_element_out=element_by_player[move.player_out],
                        official_fpl_element_in=element_by_player[move.player_in],
                    )
                    for move in incremental
                ),
            )
        )
    frontier = seal_private_transfer_frontier(
        PrivateTransferFrontier.model_construct(
            objective="ONE_GAMEWEEK_ZERO_TERMINAL_VALUE_OBJECTIVE",
            points=tuple(points),
            deltas=tuple(deltas),
            action_space_disclosure=action_space_disclosure,
            stage9_projection_sha256=stage9_projection_sha256,
            stage9_joint_scenario_sha256=stage9_joint_scenario_sha256,
            optimiser_request_sha256=request.request_sha256,
            optimiser_result_sha256=optimiser.result_sha256,
            candidate_action_policy_sha256=candidate_action_policy_sha256,
            semantic_sha256="0" * 64,
        )
    )
    return frontier, captain_hashes


def _report(value: PrivateV1ExecutionInput, decision: PrivateV1Decision) -> str:
    players, _teams = _current_identity_maps(value)

    def label(player_id: str) -> str:
        player = players[player_id]
        return f"{player.web_name} [FPL {player.provider_element_id}]"

    frontier = render_transfer_frontier(decision.transfer_frontier, label=label)
    frontier_section = f"\n{frontier}\n" if frontier else ""
    transfers = (
        "NO TRANSFER"
        if not decision.transfers
        else ", ".join(
            f"{label(item.player_out_id)} -> {label(item.player_in_id)}"
            for item in decision.transfers
        )
    )
    comparison = decision.paired_comparison
    tactics = decision.tactics
    warnings = "\n".join(f"- {item}" for item in decision.warnings)
    xi = ", ".join(label(item) for item in tactics.starting_xi)
    bench = ", ".join(
        (label(tactics.bench_goalkeeper), *(label(item) for item in tactics.bench_outfield_order))
    )
    current_squad = ", ".join(
        label(_canonical_player_by_element(value)[item.official_fpl_element_id])
        for item in value.current_state.manager_state.squad
    )
    resulting_squad = ", ".join(label(item) for item in decision.resulting_squad)
    position_counts = {
        position: sum(players[item].position.value == position for item in tactics.starting_xi)
        for position in ("DEF", "MID", "FWD")
    }
    formation = "-".join(str(position_counts[item]) for item in ("DEF", "MID", "FWD"))
    score_prior_classes = ", ".join(sorted({item.source_class for item in value.score_priors}))
    mc_reasons = (
        ", ".join(decision.stage9_monte_carlo_reasons)
        if decision.stage9_monte_carlo_reasons
        else "NONE"
    )
    transient_banner = (
        "TRANSIENT PRIVATE DECISION\n"
        "NOT REPLAYABLE UNDER CURRENT RIGHTS PROFILE\n"
        "NOT PRODUCTION ACTIVE\n"
        if decision.execution_status == "REAL_PRIVATE_TRANSIENT_RECOMMENDATION"
        else "REPOSITORY-OWNED SYNTHETIC REPLAY DECISION\nNOT PRODUCTION ACTIVE\n"
    )
    fallback_labels = (
        ", ".join(label(item) for item in decision.player_prior_fallback_player_ids)
        if decision.player_prior_fallback_player_ids
        else "NONE"
    )
    replay_text = (
        "Replay retention: FORBIDDEN_BY_CURRENT_RIGHTS_PROFILE\n"
        "No live replay bundle or recommendation report was persisted.\n"
        if decision.replay_retention == "FORBIDDEN_BY_CURRENT_RIGHTS_PROFILE"
        else (
            "Replay retention: ALLOWED_REPOSITORY_OWNED_SYNTHETIC_ONLY\n"
            "Replay: dmf private-v1 replay --bundle <bundle-directory>\n"
            "The replay manifest hash is emitted alongside a retention-authorised frozen bundle.\n"
        )
    )
    acceptance_text = (
        "Historical human acceptance scope: PRIVATE_2026_27_GW1_ONLY; this GW1 use is within "
        "that private scope.\n"
        if decision.player_prior_status == "HISTORICAL_GW1_ACCEPTED_SCOPE"
        else (
            "Historical human acceptance scope: PRIVATE_2026_27_GW1_ONLY; current-GW "
            "carry-forward is not covered by that acceptance.\n"
        )
    )
    stage7_quality = (
        f"Confidence: {decision.confidence}. Stage 7 uses the accepted "
        "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1 model with current-season "
        "provider-observed roles/minutes and early-season shrinkage."
        if decision.stage7_model_derived
        else ("Confidence: LOW. Stage 7 is a private manual transient override, NOT_MODEL_DERIVED.")
    )
    return (
        "DMF PULSE PRIVATE V1 RECOMMENDATION\n"
        f"{transient_banner}"
        f"Run: {decision.run_id}\n"
        "\nTARGET\n"
        f"Season / Gameweek: {decision.season} / GW{decision.target_gameweek}\n"
        f"Information cutoff: {_utc_text(decision.information_cutoff)}\n"
        f"Status: {decision.engineering_status}; {decision.activation_status}\n"
        "\nCURRENT STATE\n"
        f"Squad: {current_squad}\n"
        f"Bank: {value.current_state.manager_state.bank_tenths / 10:.1f}\n"
        f"Free transfers: {value.current_state.manager_state.free_transfers}\n"
        "Chip configuration: NO CHIP\n"
        f"{frontier_section}"
        "\nRECOMMENDATION\n"
        f"Transfers: {transfers}\n"
        f"Transfer hit: -{comparison.transfer_hit_points}\n"
        f"Resulting squad: {resulting_squad}\n"
        "\nLINEUP\n"
        f"Formation: {formation}\n"
        f"XI: {xi}\n"
        f"Bench (GK, 1, 2, 3): {bench}\n"
        f"Captain: {label(tactics.captain)}\n"
        f"Vice-captain: {label(tactics.vice_captain)}\n"
        "\nPROJECTION - NO-ACTION COMPARATOR ON IDENTICAL JOINT SCENARIOS\n"
        f"Recommended before hit: {comparison.recommended_expected_points_before_hit:.2f}\n"
        f"No transfer: {comparison.no_transfer_expected_points:.2f}\n"
        f"Transfer hit: -{comparison.transfer_hit_points}\n"
        f"Recommended after hit: {comparison.recommended_expected_points_after_hit:.2f}\n"
        f"Net expected uplift: {comparison.net_expected_uplift:+.2f}\n"
        f"Paired gain p10 / median / p90: {comparison.gain_p10} / "
        f"{comparison.gain_median} / {comparison.gain_p90}\n"
        "P(recommended beats no transfer): "
        f"{comparison.probability_recommended_beats_baseline:.1%}\n\n"
        "DATA QUALITY\n"
        f"{stage7_quality} The player-allocation prior remains the grade-E GW1 candidate with "
        "historical cutoff and CANDIDATE_NOT_ACCEPTED status.\n"
        f"Player-prior current use: {decision.player_prior_status}\n"
        f"Player-prior evidence cutoff: {_utc_text(decision.player_prior_evidence_cutoff)}\n"
        f"{acceptance_text}"
        f"Explicit position-fallback players: {fallback_labels}\n"
        f"Score-prior source class: {score_prior_classes}\n"
        f"Stage-9 Monte Carlo gate: {decision.stage9_monte_carlo_status}; "
        f"reasons: {mc_reasons}\n"
        f"Declared optimiser scope: {decision.action_space_disclosure}\n"
        "The exact optimality guarantee applies only to that declared candidate/action space and "
        "one-Gameweek zero-terminal-value horizon.\n"
        f"{warnings}\n\n"
        "REPRODUCIBILITY\n"
        f"Code SHA: {decision.lineage.code_sha}\n"
        f"Execution input hash: {decision.lineage.execution_input_sha256}\n"
        f"Stage-9 joint matrix hash: {decision.lineage.stage9_joint_matrix_sha256}\n"
        f"Decision hash: {decision.semantic_sha256}\n"
        f"{replay_text}"
    )


class PrivateV1RecommendationService:
    """Execute all accepted public boundaries without transport, persistence, or clock reads."""

    def run(
        self,
        value: PrivateV1ExecutionInput,
        *,
        progress: ProgressSink | None = None,
    ) -> PrivateV1RunResult:
        active_progress = progress or NullProgress()
        try:
            execution = PrivateV1ExecutionInput.model_validate_json(value.model_dump_json())
        except ValidationError:
            raise PrivateV1Error(
                "PRIVATE_EXECUTION_INPUT_INVALID", "private execution input failed validation"
            ) from None
        _verify_current_sources(execution)
        prior = load_packaged_player_prior()
        _verify_runtime_artifacts(execution, prior)
        with active_progress.stage(
            started=None,
            completed="Stage 8/9 complete",
            failed="Stage 8/9 fixture projection",
        ):
            (
                fixture_results,
                stage7_contexts,
                stage8_hashes,
                binding_hashes,
                fallback_player_ids,
            ) = _project_fixtures(execution, prior, active_progress)
        with active_progress.stage(
            started="Assembling joint Gameweek scenarios...",
            completed="Joint Gameweek scenarios ready",
            failed="Stage 9 Gameweek assembly",
            heartbeat="Stage 9 Gameweek assembly still running",
        ):
            try:
                scenario_set = assemble_gameweek(fixture_results)
                gameweek = build_gameweek_projection(
                    scenario_set, execution.stage9_monte_carlo_policy
                )
            except (FplPointsError, ValidationError, ValueError) as exc:
                raise PrivateV1Error(
                    "STAGE9_GAMEWEEK_INVALID", "Stage-9 Gameweek assembly failed"
                ) from exc
        if execution.require_stage9_mc_pass and gameweek.monte_carlo.stopping_result != "PASS":
            raise PrivateV1Error(
                "STAGE9_MC_QUALITY_BLOCKED", "Stage-9 Monte Carlo quality gate did not pass"
            )
        penalty_role_limitations = _penalty_role_limitations(execution, fixture_results)
        with active_progress.stage(
            started="Preparing optimiser...",
            completed="Optimiser ready",
            failed="Stage 11 request preparation",
        ):
            request, tactical, candidates, transfer_scope = _stage11_request(execution, gameweek)
        active_progress.message(f"candidate players: {len(candidates)}")
        active_progress.message(
            f"free transfers available: {execution.current_state.manager_state.free_transfers}"
        )
        active_progress.message(
            "transfer counts considered: "
            + ",".join(str(item) for item in transfer_scope.transfer_counts_considered)
        )
        active_progress.message(
            f"full selectable incoming universe: {transfer_scope.full_incoming_count}"
        )
        active_progress.message(
            f"retained transfer candidates: {len(transfer_scope.retained_incoming_ids)}"
        )
        active_progress.message(
            f"retained one-transfer actions: {transfer_scope.one_transfer_actions}"
        )
        active_progress.message(
            f"retained two-transfer actions: {transfer_scope.two_transfer_actions}"
        )
        active_progress.message(
            f"exact tactical squads requiring evaluation: {transfer_scope.exact_tactical_squads}"
        )
        active_progress.message(
            f"maximum transfers: {execution.candidate_action_policy.maximum_transfers}"
        )
        root_action_upper = _exact_root_action_upper_bound(
            squad_size=len(execution.current_state.manager_state.squad),
            incoming_count=len(transfer_scope.retained_incoming_ids),
            maximum_transfers=execution.candidate_action_policy.maximum_transfers,
        )
        active_progress.message(f"root action upper bound: {root_action_upper}")

        def batch_progress(value: tuple[int, int]) -> None:
            completed, total = value
            if completed == 1 or completed == total or completed % 25 == 0:
                active_progress.message(f"Stage 10 tactical squads: {completed}/{total} complete")

        with active_progress.stage(
            started="Stage-10 tactical batch starting",
            completed="Stage-10 tactical batch ready",
            failed="Stage-10 tactical batch",
            heartbeat="Stage 10 tactical batch still running",
            long_warning=(
                "WARNING: exact Stage-10 tactical evaluation has exceeded the expected "
                "private-V1 runtime; computation is still active."
            ),
        ):
            tactical.precompute(progress=batch_progress)
        with active_progress.stage(
            started="Stage-11 policy selection...",
            completed="Stage-11 policy selection complete",
            failed="Stage-11 policy selection",
            heartbeat="Stage-11 policy selection still running",
        ):
            optimiser = optimise_multi_gameweek(request, evaluator=tactical)
        if (
            optimiser.status is not MultiGameweekResultStatus.SUCCESS
            or optimiser.solver_status.status is not BackendStatus.OPTIMAL
            or optimiser.recommended_plan is None
            or optimiser.no_transfer_baseline is None
            or optimiser.transfer_count_frontier is None
        ):
            raise PrivateV1Error(
                optimiser.error_code or "OPTIMISER_BLOCKED",
                "existing Stage-11 optimiser did not return an exact recommendation and baseline",
            )
        recommended_action = optimiser.recommended_plan.current_action
        baseline_action = optimiser.no_transfer_baseline.current_action
        recommended = _parse_tactical_plan(recommended_action.tactical_evaluation.tactical_plan)
        baseline = _parse_tactical_plan(baseline_action.tactical_evaluation.tactical_plan)
        if gameweek.result_sha256 is None:  # guarded by GameweekProjectionResult
            raise PrivateV1Error("STAGE9_GAMEWEEK_INVALID", "Stage-9 result hash is absent")
        current_players, _teams = _current_identity_maps(execution)
        element_by_player = {
            player_id: item.provider_element_id for player_id, item in current_players.items()
        }
        matrix_hash = semantic_sha256(gameweek.joint_matrix)
        action_space_disclosure = _action_space_disclosure(transfer_scope)
        with active_progress.stage(
            started="Verifying captain / vice-captain...",
            completed="Captain verification complete",
            failed="captain / vice-captain verification",
        ):
            private_frontier, captain_hashes = _build_private_transfer_frontier(
                optimiser,
                request=request,
                scenarios=scenario_set,
                baseline=baseline,
                candidates=candidates,
                tactical=tactical,
                element_by_player=element_by_player,
                action_space_disclosure=action_space_disclosure,
                stage9_projection_sha256=gameweek.result_sha256,
                stage9_joint_scenario_sha256=matrix_hash,
                candidate_action_policy_sha256=(execution.candidate_action_policy.semantic_sha256),
            )
            try:
                recommended_captain_hash = captain_hashes[
                    recommended_action.tactical_evaluation.tactical_plan_sha256
                ]
                baseline_captain_hash = captain_hashes[
                    baseline_action.tactical_evaluation.tactical_plan_sha256
                ]
            except KeyError:
                raise PrivateV1Error(
                    "FRONTIER_RECOMMENDATION_MISMATCH",
                    "canonical recommendation or hold is absent from the transfer frontier",
                ) from None
            recommended_frontier_point = next(
                (
                    item
                    for item in private_frontier.points
                    if item.action_id == recommended_action.action.action_id
                ),
                None,
            )
            if recommended_frontier_point is None:
                raise PrivateV1Error(
                    "FRONTIER_RECOMMENDATION_MISMATCH",
                    "canonical recommendation is absent from the transfer frontier",
                )
        with active_progress.stage(
            started="Building paired comparator...",
            completed="Paired comparator ready",
            failed="paired comparator",
        ):
            comparison = _paired_comparison_from_frontier(
                recommended_frontier_point.comparison_vs_hold
            )
        if comparison.net_expected_uplift != optimiser.recommended_plan.utility.objective_total - (
            optimiser.no_transfer_baseline.utility.objective_total
        ):
            raise PrivateV1Error(
                "COMPARATOR_OBJECTIVE_MISMATCH",
                "paired current-GW gain differs from the one-GW Stage-11 objective",
            )
        moves = _private_transfer_moves(
            recommended_action.action,
            candidate_pool=request.candidate_pool,
            element_by_player=element_by_player,
        )
        stage8_policy_hash = load_score_baseline_policy().sha256
        model_stage7 = _uses_model_stage7(execution)
        stage7_confidence = (
            min(
                (
                    item.confidence
                    for item in execution.manual_minutes
                    if isinstance(item, CurrentModelFixtureMinutesInput)
                ),
                key=lambda item: {"LOW": 0, "MEDIUM": 1, "HIGH": 2}[item],
            )
            if model_stage7
            else "LOW"
        )
        warnings = tuple(
            sorted(
                {
                    *(
                        ()
                        if model_stage7
                        else ("MANUAL_STAGE7_PRIVATE_TRANSIENT_NOT_MODEL_DERIVED",)
                    ),
                    *(
                        warning
                        for item in execution.manual_minutes
                        if isinstance(item, CurrentModelFixtureMinutesInput)
                        for warning in item.warnings
                    ),
                    "PLAYER_ALLOCATION_PRIOR_GRADE_E_CANDIDATE_NOT_ACCEPTED",
                    "PLAYER_ALLOCATION_PRIOR_HISTORICAL_GW1_CUTOFF",
                    "DONOR_PRIVATE_ACCEPTANCE_IS_NOT_PORT_ACCEPTANCE",
                    "NO_CHIP_EXPLICIT",
                    "NOT_PRODUCTION_ACTIVE",
                    "ONE_GAMEWEEK_ZERO_TERMINAL_VALUE_OBJECTIVE",
                    "EXACT_ONLY_WITHIN_DECLARED_CANDIDATE_ACTION_SPACE",
                    *((transfer_scope.pruning_policy,) if transfer_scope.pruning_policy else ()),
                    *penalty_role_limitations,
                    *(
                        (
                            "CURRENT_GW_USE_NOT_COVERED_BY_HISTORICAL_GW1_ACCEPTANCE",
                            "PRIVATE_CURRENT_GW_STALE_PRIOR_CARRY_FORWARD_V1",
                        )
                        if execution.current_state.target_gameweek > 1
                        else ()
                    ),
                    *(
                        ("REPOSITORY_OWNED_SYNTHETIC_SCORE_PRIOR_TEST_ONLY",)
                        if any(
                            item.source_class == "REPOSITORY_OWNED_SYNTHETIC"
                            for item in execution.score_priors
                        )
                        else ()
                    ),
                    *(
                        ("STAGE9_MC_PASS_NOT_REQUIRED_TEST_ONLY",)
                        if not execution.require_stage9_mc_pass
                        else ()
                    ),
                    *(
                        ("REPOSITORY_OWNED_SYNTHETIC_EVENT_ALLOCATION_TEST_ONLY",)
                        if execution.event_allocation_config.source_tag == "TEST_SYNTHETIC"
                        else ()
                    ),
                    *scenario_set.warnings,
                    *optimiser.warnings,
                }
            )
        )
        lineage = PrivateDecisionLineage(
            current_state_sha256=execution.current_state.semantic_sha256,
            player_identity_map_sha256=execution.player_identity_map.semantic_sha256,
            fpl_input_sha256=execution.current_state.fpl_input.semantic_sha256,
            fixture_source_sha256=(
                execution.current_state.fpl_input.provenance.fixtures_semantic_sha256
            ),
            odds_market_sha256=execution.current_state.odds_input.market_semantic_sha256,
            manager_state_sha256=execution.current_state.manager_state.semantic_sha256,
            market_constraints_sha256=execution.market_constraints.semantic_sha256,
            score_prior_sha256_by_fixture={
                str(item.fixture_id): item.semantic_sha256 for item in execution.score_priors
            },
            stage7_input_sha256_by_fixture={
                item.fixture_id: _stage7_input_sha256(item) for item in execution.manual_minutes
            },
            stage7_context_sha256_by_fixture=stage7_contexts,
            stage8_result_sha256_by_fixture=stage8_hashes,
            stage8_policy_sha256=stage8_policy_hash,
            player_prior_artifact_sha256=prior.artifact.artifact_sha256,
            player_prior_acceptance_sha256=(prior.historical_acceptance.acceptance_sha256),
            player_prior_binding_sha256_by_fixture=binding_hashes,
            player_prior_carry_forward_policy_sha256=(
                execution.player_prior_carry_forward_policy.semantic_sha256
                if execution.player_prior_carry_forward_policy is not None
                else None
            ),
            private_rules_authority_sha256=(
                execution.private_rules_authority.attestation_sha256
                if execution.private_rules_authority is not None
                else None
            ),
            stage9_result_sha256=gameweek.result_sha256,
            stage9_joint_matrix_sha256=matrix_hash,
            optimiser_request_sha256=request.request_sha256,
            optimiser_result_sha256=optimiser.result_sha256,
            candidate_action_policy_sha256=(execution.candidate_action_policy.semantic_sha256),
            ownership_sha256=execution.ownership.semantic_sha256,
            ruleset_sha256=execution.ruleset.ruleset_hash,
            execution_input_sha256=execution.semantic_sha256,
            code_sha=execution.code_sha,
        )
        provisional = PrivateV1Decision.model_construct(
            status=PrivateDecisionStatus.SUCCESS,
            engineering_status=("PRIVATE_V1_E2E_001A_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW"),
            activation_status="NOT_PRODUCTION_ACTIVE",
            execution_status=(
                "SYNTHETIC_REPLAYABLE_RECOMMENDATION"
                if execution.retention_class == "SYNTHETIC_REPLAY_ALLOWED"
                else "REAL_PRIVATE_TRANSIENT_RECOMMENDATION"
            ),
            replay_retention=(
                "ALLOWED_REPOSITORY_OWNED_SYNTHETIC_ONLY"
                if execution.retention_class == "SYNTHETIC_REPLAY_ALLOWED"
                else "FORBIDDEN_BY_CURRENT_RIGHTS_PROFILE"
            ),
            run_id=execution.run_id,
            season=execution.current_state.season_code,
            target_gameweek=execution.current_state.target_gameweek,
            information_cutoff=execution.current_state.information_cutoff,
            projection_mode=execution.projection_mode,
            action="NO_TRANSFER" if not moves else "TRANSFER",
            transfers=moves,
            resulting_squad=recommended_action.squad_after,
            tactics=_tactical_decision(recommended, recommended_captain_hash),
            no_transfer_tactics=_tactical_decision(baseline, baseline_captain_hash),
            chip_action="NO_CHIP",
            paired_comparison=comparison,
            transfer_frontier=private_frontier,
            stage7_family=(
                "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"
                if model_stage7
                else "PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1"
            ),
            stage7_model_derived=model_stage7,
            confidence=stage7_confidence,
            player_prior_status=(
                "HISTORICAL_GW1_ACCEPTED_SCOPE"
                if execution.current_state.target_gameweek == 1
                else "PRIVATE_CURRENT_GW_STALE_PRIOR_CARRY_FORWARD_V1"
            ),
            player_prior_evidence_cutoff=prior.artifact.information_cutoff,
            player_prior_fallback_player_ids=tuple(sorted(fallback_player_ids)),
            scenario_count=len(scenario_set.scenarios),
            stage9_monte_carlo_status=gameweek.monte_carlo.stopping_result,
            stage9_monte_carlo_reasons=tuple(sorted(set(gameweek.monte_carlo.stopping_reasons))),
            solver_optimality="EXACT_DECLARED_TREE_AND_ACTION_SPACE",
            action_space_disclosure=action_space_disclosure,
            warnings=warnings,
            lineage=lineage,
            semantic_sha256="0" * 64,
        )
        decision = seal_private_decision(provisional)
        return PrivateV1RunResult(
            decision=decision,
            report=_report(execution, decision),
            gameweek_projection=gameweek,
            optimiser_result=optimiser,
        )

    def replay(self, directory: Path) -> PrivateV1ReplayResult:
        """Recompute a verified synthetic bundle without any provider or clock access."""

        from dmf_pulse.private_v1.artifacts import verify_replay_bundle

        manifest, execution, frozen_decision, frozen_report = verify_replay_bundle(directory)
        run = self.run(execution)
        if run.decision != frozen_decision or run.report != frozen_report:
            raise PrivateV1Error(
                "REPLAY_RESULT_MISMATCH",
                "recomputed decision or report differs from the frozen bundle",
            )
        return PrivateV1ReplayResult(
            run=run,
            manifest_sha256=manifest.manifest_sha256,
        )


__all__ = [
    "PrivateV1RecommendationService",
    "PrivateV1ReplayResult",
    "PrivateV1RunResult",
    "load_packaged_event_allocation_config",
]
