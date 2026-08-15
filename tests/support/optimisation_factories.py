"""Small complete synthetic Stage-9/rules inputs for OPT-010 tests."""

from __future__ import annotations

from pathlib import Path

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
from dmf_pulse.rules.models import CompiledRuleset, RulesetStatus

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
    source = load_compiled_ruleset(
        Path("artifacts/rules/fpl-2026-27-0.1.0-prelaunch.1.schema-v1.1.json")
    )
    rules = {
        "positions": {
            "positions": {
                "GK": {"squad_quota": 2, "lineup_min": 1, "lineup_max": 1},
                "DEF": {"squad_quota": 5, "lineup_min": 3, "lineup_max": 5},
                "MID": {"squad_quota": 5, "lineup_min": 2, "lineup_max": 5},
                "FWD": {"squad_quota": 3, "lineup_min": 1, "lineup_max": 3},
            }
        },
        "squad": {"budget_tenths": 1000, "max_players_per_club": 3},
        "lineup": {
            "starting_size": 11,
            "bench_size": 4,
            "captain_multiplier": 2,
            "vice_captain_fallback": True,
            "automatic_substitutions": {
                "timing": "AFTER_ALL_GAMEWEEK_FIXTURES",
                "zero_official_appearance_minutes": 0,
                "designated_bench_goalkeeper_if_appeared": True,
                "manager_bench_order": True,
                "maintain_legal_formation": True,
            },
        },
    }
    return source.model_copy(
        update={
            "status": RulesetStatus.REFERENCE_ONLY,
            "production_eligible": False,
            "rules": rules,
        }
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


def scenario_set(
    ruleset_hash: str,
    *,
    values: tuple[dict[str, int], ...] | None = None,
    weights: tuple[float, ...] | None = None,
    gameweek_id: str = "GW1",
) -> GameweekScenarioSet:
    candidate_ids = tuple(player.player_id for player in players())
    values = values or ({player: 0 for player in candidate_ids},)
    weights = weights or tuple(1.0 / len(values) for _ in values)
    scenarios: list[GameweekPointScenario] = []
    for index, point_map in enumerate(values):
        appeared = {player: point_map.get(player, 0) != 0 for player in candidate_ids}
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
    return build_gameweek_projection(
        scenario_set(
            ruleset_hash, values=scenario_values if isinstance(scenario_values, tuple) else None
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
    pool = CandidatePoolSnapshot(
        candidates=tuple(sorted(players(), key=lambda item: item.player_id))
    )
    squad = CandidateSquad(player_ids=tuple(player.player_id for player in players()))
    return OneGameweekOptimisationRequest(
        gameweek_id="GW1",
        projection_mode=projection_mode,
        search_scope=scope,
        candidate_pool=pool,
        fixed_squad=squad if scope is SearchScope.FIXED_SQUAD else None,
        provided_squads=(squad,) if scope is SearchScope.PROVIDED_SQUADS else (),
    )
