"""Small complete synthetic Stage-9/rules inputs for OPT-010 tests."""

from __future__ import annotations

from pathlib import Path

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.gameweek_summaries import build_gameweek_projection
from dmf_pulse.fpl_points.models import (
    BpsCompletenessMode,
    GameweekAssemblyMode,
    GameweekPointScenario,
    GameweekScenarioSet,
    MonteCarloPolicy,
    PlayerPosition,
    ProjectionMode,
)
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidatePoolSnapshot,
    CandidateSquad,
    OneGameweekOptimisationRequest,
    SearchScope,
)
from dmf_pulse.rules.compiler import load_compiled_ruleset
from dmf_pulse.rules.models import CompiledRuleset

POINT_COMPONENTS = (
    "appearance",
    "goals",
    "assists",
    "clean_sheet",
    "saves",
    "penalty_saves",
    "defensive_contributions",
    "goals_conceded",
    "penalty_misses",
    "yellow_cards",
    "red_cards",
    "own_goals",
    "bonus",
)


def synthetic_ruleset() -> CompiledRuleset:
    return load_compiled_ruleset(
        Path("fixtures/optimisation/one_gameweek/reference_ruleset_test_only.json")
    )


def players() -> tuple[CandidatePlayer, ...]:
    values: list[CandidatePlayer] = []
    for index in range(15):
        position = (
            PlayerPosition.GK
            if index < 2
            else PlayerPosition.DEF
            if index < 7
            else PlayerPosition.MID
            if index < 12
            else PlayerPosition.FWD
        )
        values.append(
            CandidatePlayer(player_id=f"p{index:02d}", position=position, club_id=f"club-{index}")
        )
    return tuple(values)


def candidate_pool(
    candidates: tuple[CandidatePlayer, ...] | None = None,
) -> CandidatePoolSnapshot:
    pool = CandidatePoolSnapshot(
        information_cutoff_utc="2026-08-16T00:00:00Z",
        players=tuple(sorted(candidates or players(), key=lambda item: item.player_id)),
        snapshot_sha256="0" * 64,
    )
    payload = pool.model_dump(mode="json")
    payload["snapshot_sha256"] = None
    return pool.model_copy(update={"snapshot_sha256": semantic_sha256(payload)})


def seal_request(
    value: OneGameweekOptimisationRequest,
) -> OneGameweekOptimisationRequest:
    payload = value.model_dump(mode="json")
    payload["request_sha256"] = None
    return value.model_copy(update={"request_sha256": semantic_sha256(payload)})


def scenario_set(
    ruleset_hash: str,
    *,
    values: tuple[dict[str, int], ...] | None = None,
    appeared_values: tuple[dict[str, bool], ...] | None = None,
    weights: tuple[float, ...] | None = None,
    gameweek_id: str = "GW1",
) -> GameweekScenarioSet:
    candidate_ids = tuple(player.player_id for player in players())
    values = values or ({player: 0 for player in candidate_ids},)
    weights = weights or tuple(1.0 / len(values) for _ in values)
    scenarios: list[GameweekPointScenario] = []
    for index, point_map in enumerate(values):
        appeared_source = appeared_values[index] if appeared_values is not None else {}
        appeared = {player: appeared_source.get(player, True) for player in candidate_ids}
        points = {player: point_map.get(player, 0) for player in candidate_ids}
        components = {
            player: {
                component: (points[player] if component == "appearance" else 0)
                for component in POINT_COMPONENTS
            }
            for player in candidate_ids
        }
        scenarios.append(
            GameweekPointScenario(
                scenario_id=f"scenario-{index}",
                outcome_draw_id=f"draw-{index}",
                weight=weights[index],
                gameweek_id=gameweek_id,
                fixture_ids=("fixture-1",),
                player_points=points,
                player_components=components,
                player_bps={player: 0 for player in candidate_ids},
                player_bonus={player: 0 for player in candidate_ids},
                player_minutes={player: 90 if appeared[player] else 0 for player in candidate_ids},
                player_appeared=appeared,
                assembly_mode=GameweekAssemblyMode.SINGLE_FIXTURE,
                approximation_labels=(),
            )
        )
    return GameweekScenarioSet(
        gameweek_id=gameweek_id,
        scenarios=tuple(scenarios),
        player_ids=candidate_ids,
        ruleset_hash=ruleset_hash,
        assembly_mode=GameweekAssemblyMode.SINGLE_FIXTURE,
        bps_completeness_mode=BpsCompletenessMode.EVENT_LINKED_ONLY,
        confidence_grade="E",
        model_version_ids=(),
        dataset_version_ids=(),
        source_bundle_ids=(),
        upstream_stage8_sha256s=(),
        fixture_result_sha256_by_fixture={"fixture-1": "0" * 64},
        warnings=(),
    )


def projection(ruleset_hash: str, **kwargs: object):
    scenario_values = kwargs.pop("values", None)
    scenario_appearances = kwargs.pop("appeared_values", None)
    scenario_weights = kwargs.pop("weights", None)
    return build_gameweek_projection(
        scenario_set(
            ruleset_hash,
            values=scenario_values if isinstance(scenario_values, tuple) else None,
            appeared_values=(
                scenario_appearances if isinstance(scenario_appearances, tuple) else None
            ),
            weights=scenario_weights if isinstance(scenario_weights, tuple) else None,
        ),
        MonteCarloPolicy(
            minimum_effective_scenarios=1,
            maximum_mean_mcse=1000,
            maximum_probability_se=1000,
            maximum_quantile_span=1000,
            quantiles=(0.5,),
            thresholds=(1,),
            batch_count=2,
        ),
    )


def request(
    *,
    projection_mode: ProjectionMode = ProjectionMode.TEST,
    scope: SearchScope = SearchScope.FIXED_SQUAD,
) -> OneGameweekOptimisationRequest:
    candidate_values = players()
    if scope is SearchScope.BOUNDED_PLAYER_POOL:
        candidate_values = tuple(
            player.model_copy(update={"initial_selection_cost_tenths": 1})
            for player in candidate_values
        )
    pool = candidate_pool(candidate_values)
    squad_ids = tuple(player.player_id for player in candidate_values)
    req = OneGameweekOptimisationRequest(
        request_id="request-1",
        projection_mode=projection_mode,
        gameweek_id="GW1",
        information_cutoff_utc="2026-08-16T00:00:00Z",
        search_scope=scope,
        candidate_pool=pool,
        fixed_squad_ids=squad_ids if scope is SearchScope.FIXED_SQUAD else None,
        provided_candidate_squads=(CandidateSquad(player_ids=squad_ids),)
        if scope is SearchScope.PROVIDED_SQUADS
        else (),
        request_sha256="0" * 64,
    )
    return seal_request(req)
