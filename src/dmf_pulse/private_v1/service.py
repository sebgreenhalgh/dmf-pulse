"""One application service for the private current-input recommendation vertical slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.current_model import (
    CurrentModelFixtureMinutesInput,
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
    EventAllocationConfig,
    FixtureProjectionResult,
    FixtureSimulationRequest,
    GameweekProjectionResult,
    GameweekScenarioSet,
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
from dmf_pulse.markets.current import (
    CurrentMarketConstraintError,
    CurrentMarketConstraintService,
    CurrentMarketReadiness,
    bind_current_market_constraint_request,
)
from dmf_pulse.optimisation.manager_state import ManagerState, OwnershipSpell, seal_manager_state
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    OneGameweekPlan,
    OneGameweekRulesView,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    BackendStatus,
    MultiGameweekOptimisationRequest,
    MultiGameweekOptimisationResult,
    MultiGameweekResultStatus,
    PlayerCatalogEntry,
    PlayerPriceState,
    ScenarioTree,
    ScenarioTreeNode,
    SearchPolicy,
    TacticalNodeEvaluation,
    seal_request,
    seal_scenario_tree,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_policy import (
    load_multi_gameweek_search_policy,
    load_terminal_value_policy,
)
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.optimisation.multi_gameweek_solver import information_set_key
from dmf_pulse.optimisation.policy import load_policy as load_one_gameweek_policy
from dmf_pulse.optimisation.stage10_adapter import Stage10TacticalAdapter
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import (
    PrivateDecisionLineage,
    PrivateDecisionStatus,
    PrivateGainMass,
    PrivatePairedComparison,
    PrivateTacticalDecision,
    PrivateTransferMove,
    PrivateV1Decision,
    PrivateV1ExecutionInput,
    seal_private_decision,
)
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view

_DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


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
    values: tuple[ManualWeightedScenario, ...],
) -> dict[str, ManualWeightedScenario]:
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
) -> tuple[
    tuple[FixtureProjectionResult, ...],
    dict[str, str],
    dict[str, str],
    dict[str, str],
    set[str],
]:
    fixture_authority = _fixture_authority(value)
    current_players, current_teams = _current_identity_maps(value)
    minutes_by_fixture = {item.fixture_id: item for item in value.manual_minutes}
    prior_by_fixture = {str(item.fixture_id): item for item in value.score_priors}
    markets_by_fixture = {
        str(item.canonical_fixture_id): item for item in value.market_constraints.fixtures
    }
    engine = AcceptedRulesAdapter(value.ruleset)
    points = FplPointsService(engine, value.stage9_monte_carlo_policy)
    gameweek_id = f"GW-{value.current_state.target_gameweek}"
    stage7_context_hashes: dict[str, str] = {}
    stage8_hashes: dict[str, str] = {}
    binding_hashes: dict[str, str] = {}
    fallback_player_ids: set[str] = set()
    results: list[FixtureProjectionResult] = []
    canonical_teams = _canonical_team_by_official(value)
    for fixture_id in sorted(fixture_authority):
        fpl_fixture, _canonical_fixture = fixture_authority[fixture_id]
        stage7 = minutes_by_fixture[fixture_id]
        market = markets_by_fixture[fixture_id]
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
                    constraints=market.constraint_set.constraints,
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
            player_prior_identity=prior_identity,
            allocation_config=value.event_allocation_config,
            expected_ruleset_id=engine.identity.ruleset_id,
            expected_ruleset_version=engine.identity.ruleset_version,
            expected_ruleset_hash=engine.identity.ruleset_hash,
        )
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
) -> tuple[
    MultiGameweekOptimisationRequest,
    _MemoizedStage10Evaluator,
    dict[str, CandidatePlayer],
]:
    current_players, _teams = _current_identity_maps(value)
    canonical_players = _canonical_player_by_element(value)
    canonical_teams = _canonical_team_by_official(value)
    scenario_player_ids = set(gameweek.scenario_set.player_ids)
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
    allowed = tuple(
        sorted(
            element_to_player[item]
            for item in value.candidate_action_policy.allowed_transfer_in_element_ids
        )
    )
    root_id = f"GW-{value.current_state.target_gameweek}-CURRENT"
    if gameweek.result_sha256 is None:  # guarded by the successful projection contract
        raise PrivateV1Error("STAGE9_GAMEWEEK_INVALID", "Stage-9 result hash is absent")
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
    tree = seal_scenario_tree(
        ScenarioTree(
            tree_id=f"{value.run_id}-GW-{value.current_state.target_gameweek}",
            nodes=(root,),
            tree_sha256="0" * 64,
        )
    )
    search = load_multi_gameweek_search_policy()
    search_payload = search.model_dump(mode="python")
    search_payload["max_transfers_per_node"] = value.candidate_action_policy.maximum_transfers
    search_payload["policy_sha256"] = "0" * 64
    search = seal_search_policy(SearchPolicy.model_validate(search_payload))
    transfer_rules = build_multi_gameweek_transfer_rules(
        value.ruleset,
        projection_mode=value.projection_mode,
    )
    request = seal_request(
        MultiGameweekOptimisationRequest(
            request_id=value.run_id,
            projection_mode=value.projection_mode,
            initial_state=_manager_state(value, root_node_id=root_id),
            candidate_pool=catalog,
            rules=transfer_rules,
            scenario_tree=tree,
            search_policy=search,
            terminal_policy=load_terminal_value_policy(),
            assumptions=tuple(
                sorted(
                    {
                        "NO_CHIP",
                        "ONE_GAMEWEEK_HORIZON_ZERO_TERMINAL_VALUE",
                        "OPERATOR_ATTESTED_OWNERSHIP_ACQUISITION_GAMEWEEKS",
                        (
                            "ACCEPTED_REGULARISED_EMPIRICAL_BAYES_COHERENCE_STAGE7"
                            if _uses_model_stage7(value)
                            else "PRIVATE_MANUAL_TRANSIENT_STAGE7_NOT_MODEL_DERIVED"
                        ),
                        "TRANSFER_SCOPE_EXPLICIT_OPERATOR_DECLARATION",
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
        scenarios_by_node={root_id: gameweek.scenario_set.scenarios},
    )
    return request, _MemoizedStage10Evaluator(tactical), candidates


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


def _paired_comparison(
    recommended: OneGameweekPlan,
    baseline: OneGameweekPlan,
    *,
    scenarios: GameweekScenarioSet,
    hit_points: int,
) -> PrivatePairedComparison:
    recommended_scores = {
        (item.scenario_id, item.outcome_draw_id): item.manager_points
        for item in recommended.scenario_scores
    }
    baseline_scores = {
        (item.scenario_id, item.outcome_draw_id): item.manager_points
        for item in baseline.scenario_scores
    }
    scenario_weights = {
        (item.scenario_id, item.outcome_draw_id): Fraction(str(item.weight))
        for item in scenarios.scenarios
    }
    if not recommended_scores.keys() == baseline_scores.keys() == scenario_weights.keys():
        raise PrivateV1Error(
            "COMPARATOR_SCENARIO_MISMATCH", "recommendation and baseline scenarios differ"
        )
    total_weight = sum(scenario_weights.values(), Fraction(0))
    if total_weight <= 0:
        raise PrivateV1Error("COMPARATOR_INVALID", "scenario weights are invalid")
    normalized = {key: weight / total_weight for key, weight in scenario_weights.items()}
    gain_masses: dict[int, Fraction] = {}
    expected_recommended = Fraction(0)
    expected_baseline = Fraction(0)
    for key, weight in normalized.items():
        recommended_points = recommended_scores[key]
        baseline_points = baseline_scores[key]
        gain = recommended_points - hit_points - baseline_points
        gain_masses[gain] = gain_masses.get(gain, Fraction(0)) + weight
        expected_recommended += weight * recommended_points
        expected_baseline += weight * baseline_points
    gain_expected = expected_recommended - hit_points - expected_baseline
    provisional = PrivatePairedComparison.model_construct(
        scenario_count=len(normalized),
        recommended_expected_points_before_hit=_decimal(expected_recommended),
        no_transfer_expected_points=_decimal(expected_baseline),
        transfer_hit_points=hit_points,
        recommended_expected_points_after_hit=_decimal(expected_recommended) - hit_points,
        net_expected_uplift=_decimal(gain_expected),
        gain_p10=_quantile(gain_masses, Fraction(1, 10)),
        gain_median=_quantile(gain_masses, Fraction(1, 2)),
        gain_p90=_quantile(gain_masses, Fraction(9, 10)),
        probability_recommended_beats_baseline=_decimal(
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
    payload = provisional.model_dump(mode="python")
    payload["semantic_sha256"] = canonical_sha256(
        provisional.model_dump(mode="json", exclude={"semantic_sha256"})
    )
    return PrivatePairedComparison.model_validate(payload)


def _report(value: PrivateV1ExecutionInput, decision: PrivateV1Decision) -> str:
    players, _teams = _current_identity_maps(value)

    def label(player_id: str) -> str:
        player = players[player_id]
        return f"{player.web_name} [FPL {player.provider_element_id}]"

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

    def run(self, value: PrivateV1ExecutionInput) -> PrivateV1RunResult:
        try:
            execution = PrivateV1ExecutionInput.model_validate_json(value.model_dump_json())
        except ValidationError:
            raise PrivateV1Error(
                "PRIVATE_EXECUTION_INPUT_INVALID", "private execution input failed validation"
            ) from None
        _verify_current_sources(execution)
        prior = load_packaged_player_prior()
        _verify_runtime_artifacts(execution, prior)
        (
            fixture_results,
            stage7_contexts,
            stage8_hashes,
            binding_hashes,
            fallback_player_ids,
        ) = _project_fixtures(execution, prior)
        try:
            scenario_set = assemble_gameweek(fixture_results)
            gameweek = build_gameweek_projection(scenario_set, execution.stage9_monte_carlo_policy)
        except (FplPointsError, ValidationError, ValueError) as exc:
            raise PrivateV1Error(
                "STAGE9_GAMEWEEK_INVALID", "Stage-9 Gameweek assembly failed"
            ) from exc
        if execution.require_stage9_mc_pass and gameweek.monte_carlo.stopping_result != "PASS":
            raise PrivateV1Error(
                "STAGE9_MC_QUALITY_BLOCKED", "Stage-9 Monte Carlo quality gate did not pass"
            )
        request, tactical, candidates = _stage11_request(execution, gameweek)
        optimiser = optimise_multi_gameweek(request, evaluator=tactical)
        if (
            optimiser.status is not MultiGameweekResultStatus.SUCCESS
            or optimiser.solver_status.status is not BackendStatus.OPTIMAL
            or optimiser.recommended_plan is None
            or optimiser.no_transfer_baseline is None
        ):
            raise PrivateV1Error(
                optimiser.error_code or "OPTIMISER_BLOCKED",
                "existing Stage-11 optimiser did not return an exact recommendation and baseline",
            )
        recommended_action = optimiser.recommended_plan.current_action
        baseline_action = optimiser.no_transfer_baseline.current_action
        recommended = _parse_tactical_plan(recommended_action.tactical_evaluation.tactical_plan)
        baseline = _parse_tactical_plan(baseline_action.tactical_evaluation.tactical_plan)
        recommended_captain_hash = _verify_captain(
            recommended,
            scenarios=scenario_set,
            candidates=candidates,
            tactical=tactical,
        )
        baseline_captain_hash = _verify_captain(
            baseline,
            scenarios=scenario_set,
            candidates=candidates,
            tactical=tactical,
        )
        comparison = _paired_comparison(
            recommended,
            baseline,
            scenarios=scenario_set,
            hit_points=recommended_action.hit_points,
        )
        if comparison.net_expected_uplift != optimiser.recommended_plan.utility.objective_total - (
            optimiser.no_transfer_baseline.utility.objective_total
        ):
            raise PrivateV1Error(
                "COMPARATOR_OBJECTIVE_MISMATCH",
                "paired current-GW gain differs from the one-GW Stage-11 objective",
            )
        current_players, _teams = _current_identity_maps(execution)
        element_by_player = {
            player_id: item.provider_element_id for player_id, item in current_players.items()
        }
        moves = tuple(
            PrivateTransferMove(
                player_out_id=player_out,
                player_in_id=player_in,
                official_fpl_element_out=element_by_player[player_out],
                official_fpl_element_in=element_by_player[player_in],
            )
            for player_out, player_in in zip(
                recommended_action.action.transfers_out,
                recommended_action.action.transfers_in,
                strict=True,
            )
        )
        matrix_hash = semantic_sha256(gameweek.joint_matrix)
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
        if gameweek.result_sha256 is None:  # guarded by GameweekProjectionResult
            raise PrivateV1Error("STAGE9_GAMEWEEK_INVALID", "Stage-9 result hash is absent")
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
            action_space_disclosure=(
                f"Exact over {len(execution.candidate_action_policy.allowed_transfer_in_element_ids)} "
                "explicit incoming candidate(s), the current squad, at most "
                f"{execution.candidate_action_policy.maximum_transfers} transfer(s), and the "
                "declared Stage-9 scenario set."
            ),
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
